"""Append a compact, read-only irrigation monitor to the live HMI overview."""

from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, force_project_offline, iter_device_items, open_project


ROWS = (
    ("本次目标 (L)", "DB1.Water_Volume_SP"),
    ("累计灌溉 (L)", "DB1.Water_Volume_Actual"),
    ("主管流量 (L/min)", "DB1.Qw_Actual"),
)
REMOVE_NAMES = {
    "Hdr_Irrigation_Monitor",
    "Panel_Irrigation_Monitor",
    *(f"Lbl_{tag}" for _, tag in ROWS),
    *(f"IO_{tag}" for _, tag in ROWS),
}


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
            if container is not None and container.Software is not None and str(container.Software.Name).startswith("HMI_RT_"):
                return container.Software
    raise RuntimeError(f"HMI target not found for device '{hmi_name}'.")


def next_ids(root: ET.Element):
    highest = 0x100
    for elem in root.iter():
        try:
            highest = max(highest, int(elem.get("ID", "0"), 16))
        except ValueError:
            pass
    while True:
        highest += 1
        yield format(highest, "X")


def assign_ids(node: ET.Element, ids) -> None:
    for elem in node.iter():
        if "ID" in elem.attrib:
            elem.attrib["ID"] = next(ids)


def set_attr(node: ET.Element, name: str, value: str) -> None:
    attributes = node.find("./AttributeList")
    if attributes is None:
        raise RuntimeError("Control has no AttributeList.")
    attr = attributes.find(name)
    if attr is None:
        attr = ET.SubElement(attributes, name)
    attr.text = value


def set_text(node: ET.Element, value: str) -> None:
    text = node.find(".//MultilingualText[@CompositionName='Text']//Text")
    if text is None:
        raise RuntimeError("Text control has no Text composition.")
    for child in list(text):
        text.remove(child)
    text.text = None
    body = ET.SubElement(text, "body")
    paragraph = ET.SubElement(body, "p")
    paragraph.text = value


def set_process_value_tag(node: ET.Element, tag_name: str, ids) -> None:
    objects = node.find("./ObjectList")
    if objects is None:
        objects = ET.SubElement(node, "ObjectList")
    for child in list(objects):
        if child.tag == "Hmi.Screen.Property" and child.findtext("./AttributeList/Name") == "ProcessValue":
            objects.remove(child)
    prop = ET.SubElement(objects, "Hmi.Screen.Property", {"ID": next(ids), "CompositionName": "Properties"})
    attrs = ET.SubElement(prop, "AttributeList")
    ET.SubElement(attrs, "Name").text = "ProcessValue"
    prop_objects = ET.SubElement(prop, "ObjectList")
    dynamic = ET.SubElement(prop_objects, "Hmi.Dynamic.TagConnectionDynamic", {"ID": next(ids), "CompositionName": "Dynamic"})
    dynamic_attrs = ET.SubElement(dynamic, "AttributeList")
    ET.SubElement(dynamic_attrs, "Indirect").text = "false"
    links = ET.SubElement(dynamic, "LinkList")
    tag = ET.SubElement(links, "Tag", {"TargetID": "@OpenLink"})
    ET.SubElement(tag, "Name").text = f'"{tag_name}"'


def find_item(root: ET.Element, object_name: str) -> ET.Element:
    for item in root.findall(".//Hmi.Screen.ScreenLayer/ObjectList/*"):
        if item.findtext("./AttributeList/ObjectName") == object_name:
            return item
    raise RuntimeError(f"Required screen item '{object_name}' was not found.")


def patch_screen(src: Path, dst: Path) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    ids = next_ids(root)
    layer = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer is None:
        raise RuntimeError("Screen layer not found.")

    for child in list(layer):
        if child.findtext("./AttributeList/ObjectName") in REMOVE_NAMES:
            layer.remove(child)

    text_template = find_item(root, "Lbl_DB1.q_n_cmd")
    io_template = find_item(root, "IO_DB1.q_n_cmd")

    header = copy.deepcopy(text_template)
    assign_ids(header, ids)
    set_attr(header, "ObjectName", "Hdr_Irrigation_Monitor")
    set_attr(header, "Left", "20")
    set_attr(header, "Top", "382")
    set_attr(header, "Width", "760")
    set_attr(header, "Height", "20")
    set_attr(header, "BorderWidth", "0")
    set_attr(header, "BackFillStyle", "Transparent")
    set_text(header, "灌溉量监控")
    layer.append(header)

    panel = copy.deepcopy(text_template)
    assign_ids(panel, ids)
    set_attr(panel, "ObjectName", "Panel_Irrigation_Monitor")
    set_attr(panel, "Left", "20")
    set_attr(panel, "Top", "402")
    set_attr(panel, "Width", "760")
    set_attr(panel, "Height", "26")
    set_attr(panel, "BorderWidth", "1")
    set_attr(panel, "BorderColor", "83, 90, 101")
    set_attr(panel, "BackFillStyle", "Solid")
    set_attr(panel, "BackColor", "53, 59, 67")
    set_text(panel, "")
    layer.append(panel)

    for index, (label_text, tag_name) in enumerate(ROWS):
        left = 30 + index * 250
        label = copy.deepcopy(text_template)
        assign_ids(label, ids)
        set_attr(label, "ObjectName", f"Lbl_{tag_name}")
        set_attr(label, "Left", str(left))
        set_attr(label, "Top", "405")
        set_attr(label, "Width", "145")
        set_attr(label, "Height", "20")
        set_attr(label, "BorderWidth", "0")
        set_attr(label, "BackFillStyle", "Transparent")
        set_text(label, label_text)
        layer.append(label)

        io = copy.deepcopy(io_template)
        assign_ids(io, ids)
        set_attr(io, "ObjectName", f"IO_{tag_name}")
        set_attr(io, "Left", str(left + 148))
        set_attr(io, "Top", "404")
        set_attr(io, "Width", "82")
        set_attr(io, "Height", "22")
        set_attr(io, "Mode", "Output")
        set_attr(io, "FieldLength", "8")
        set_attr(io, "FormatPattern", "0.00")
        set_process_value_tag(io, tag_name, ids)
        layer.append(io)

    ET.indent(root)
    tree.write(dst, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a read-only irrigation monitor to the main HMI overview.")
    parser.add_argument("--project", default=r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
    parser.add_argument("--hmi", default="HMI_1")
    parser.add_argument("--work-dir", default=str(ROOT / "generated_hmi" / "irrigation_monitor"))
    args = parser.parse_args()

    load_openness()
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ExportOptions, ImportOptions  # type: ignore

    tia, project = attach_to_open_project(args.project)
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=True)
    try:
        if project is None:
            project = open_project(tia, args.project)
        print(f"Project: {project.Name}", flush=True)
        force_project_offline(project)
        hmi = get_hmi_target(project, args.hmi)
        screen = hmi.ScreenFolder.Screens.Find("Screen_01_MainOverview")
        if screen is None:
            raise RuntimeError("Main overview screen not found.")

        work_dir = Path(args.work_dir).resolve()
        original = work_dir / "Screen_01_MainOverview.before.xml"
        patched = work_dir / "Screen_01_MainOverview.xml"
        work_dir.mkdir(parents=True, exist_ok=True)
        screen.Export(FileInfo(str(original)), ExportOptions.WithReadOnly)
        print(f"Exported current screen: {original}", flush=True)
        patch_screen(original, patched)
        print(f"Patched screen: {patched}", flush=True)
        imported = hmi.ScreenFolder.Screens.Import(FileInfo(str(patched)), ImportOptions.Override)
        print(f"Imported: {[item.Name for item in imported]}", flush=True)
        project.Save()
        print("Project saved.", flush=True)
        return 0
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
