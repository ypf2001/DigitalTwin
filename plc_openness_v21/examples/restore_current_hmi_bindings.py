from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, open_project, iter_device_items


DEFAULT_SCREENS = [
    "Screen_01_MainOverview",
    "Screen_02_ManualControl",
    "Screen_03_PID_Settings",
    "Screen_04_AlarmsDiagnostics",
]


def get_hmi_target(project, hmi_name: str):
    from Siemens.Engineering.HW.Features import SoftwareContainer  # type: ignore

    for device in project.Devices:
        if device.Name != hmi_name:
            continue
        for item in iter_device_items(device):
            try:
                container = item.GetService[SoftwareContainer]()
            except Exception:
                container = None
            if container is None or container.Software is None:
                continue
            sw = container.Software
            if str(sw.Name).startswith("HMI_RT_"):
                return sw
    raise RuntimeError(f"HMI target not found for device '{hmi_name}'.")


def next_id(root: ET.Element):
    used: list[int] = []
    for elem in root.iter():
        raw = elem.get("ID")
        if not raw:
            continue
        try:
            used.append(int(raw, 16))
        except ValueError:
            continue
    current = max(used) if used else 0
    while True:
        current += 1
        yield format(current, "X")


def make_process_value_property(tag_name: str, ids) -> ET.Element:
    prop = ET.Element("Hmi.Screen.Property", {"ID": next(ids), "CompositionName": "Properties"})
    attr = ET.SubElement(prop, "AttributeList")
    ET.SubElement(attr, "Name").text = "ProcessValue"

    obj_list = ET.SubElement(prop, "ObjectList")
    dyn = ET.SubElement(obj_list, "Hmi.Dynamic.TagConnectionDynamic", {"ID": next(ids), "CompositionName": "Dynamic"})
    dyn_attr = ET.SubElement(dyn, "AttributeList")
    ET.SubElement(dyn_attr, "Indirect").text = "false"

    link_list = ET.SubElement(dyn, "LinkList")
    tag = ET.SubElement(link_list, "Tag", {"TargetID": "@OpenLink"})
    ET.SubElement(tag, "Name").text = f'"{tag_name}"'
    return prop


def target_tag_name(object_name: str) -> str | None:
    for prefix in ("IO_DB1.", "Sw_DB1.", "Sym_DB1."):
        if object_name.startswith(prefix):
            return "DB1." + object_name.split("DB1.", 1)[1]
    return None


def patch_screen_xml(src: Path, dst: Path) -> tuple[int, int]:
    tree = ET.parse(src)
    root = tree.getroot()
    ids = next_id(root)
    scanned = 0
    patched = 0

    for elem in root.iter():
        if elem.get("CompositionName") != "ScreenItems":
            continue
        if elem.tag not in ("Hmi.Screen.IOField", "Hmi.Screen.Switch", "Hmi.Screen.SymbolicIOField"):
            continue

        object_name = elem.findtext("./AttributeList/ObjectName")
        if not object_name:
            continue

        tag_name = target_tag_name(object_name)
        if not tag_name:
            continue

        scanned += 1
        obj_list = elem.find("./ObjectList")
        if obj_list is None:
            obj_list = ET.SubElement(elem, "ObjectList")

        removed = False
        for child in list(obj_list):
            if child.tag == "Hmi.Screen.Property" and child.findtext("./AttributeList/Name") == "ProcessValue":
                obj_list.remove(child)
                removed = True

        obj_list.append(make_process_value_property(tag_name, ids))
        patched += 1

    ET.indent(root)
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    return scanned, patched


def export_screens(hmi, screen_names: list[str], out_dir: Path) -> list[Path]:
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ExportOptions  # type: ignore

    out_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    for screen_name in screen_names:
        screen = hmi.ScreenFolder.Screens.Find(screen_name)
        if screen is None:
            raise RuntimeError(f"Screen not found: {screen_name}")
        out_path = out_dir / f"{screen_name}.xml"
        screen.Export(FileInfo(str(out_path)), ExportOptions.WithReadOnly)
        exported.append(out_path)
        print(f"Exported: {out_path}", flush=True)
    return exported


def import_screens(hmi, xml_dir: Path) -> None:
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ImportOptions  # type: ignore

    for xml_path in sorted(xml_dir.glob("*.xml")):
        imported = hmi.ScreenFolder.Screens.Import(FileInfo(str(xml_path)), ImportOptions.Override)
        names = [screen.Name for screen in imported]
        print(f"Imported: {xml_path.name} -> {names}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore HMI control bindings on the current screen layout.")
    parser.add_argument("--project", required=True, help="Path to .ap21 project.")
    parser.add_argument("--hmi", default="HMI_1", help="HMI device name.")
    parser.add_argument("--work-dir", default=str(ROOT / "generated_hmi" / "restore_bindings"), help="Working directory.")
    parser.add_argument("--screens", nargs="*", default=DEFAULT_SCREENS, help="Screen names to patch.")
    parser.add_argument("--no-ui", action="store_true", help="Start TIA Portal without UI if not already open.")
    args = parser.parse_args()

    load_openness()

    tia, project = attach_to_open_project(args.project)
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=not args.no_ui)

    try:
        if project is None:
            project = open_project(tia, args.project)
            print(f"Opened project: {project.Name}", flush=True)
        else:
            print(f"Attached to open project: {project.Name}", flush=True)

        hmi = get_hmi_target(project, args.hmi)
        work_dir = Path(args.work_dir).resolve()
        original_dir = work_dir / "original"
        patched_dir = work_dir / "patched"
        patched_dir.mkdir(parents=True, exist_ok=True)

        export_screens(hmi, list(args.screens), original_dir)

        for xml_path in sorted(original_dir.glob("*.xml")):
            out_path = patched_dir / xml_path.name
            scanned, patched = patch_screen_xml(xml_path, out_path)
            print(f"Patched {xml_path.name}: matched={scanned}, updated={patched}", flush=True)

        import_screens(hmi, patched_dir)
        project.Save()
        print("Project saved.", flush=True)
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
