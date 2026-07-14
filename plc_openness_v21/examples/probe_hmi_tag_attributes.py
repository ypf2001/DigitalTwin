from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, iter_device_items, open_project


PROJECT_PATH = Path(r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
GENERATED = ROOT / "generated_hmi"
LOG = GENERATED / "probe_hmi_tag_attributes.log"
TAG_NAME = "Probe_EC_Set_SP"


def log(msg: str) -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def find_hmi(project):
    from Siemens.Engineering.HW.Features import SoftwareContainer  # type: ignore

    for device in project.Devices:
        if device.Name != "HMI_1":
            continue
        for item in iter_device_items(device):
            try:
                container = item.GetService[SoftwareContainer]()
            except Exception:
                container = None
            if container is not None and container.Software is not None and str(container.Software.Name).startswith("HMI_RT_"):
                return container.Software
    raise RuntimeError("HMI_1 runtime not found")


def tag_xml() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V21" />
  <Hmi.Tag.Tag ID="1" CompositionName="Tags">
    <AttributeList>
      <Length>4</Length>
      <Name>{TAG_NAME}</Name>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink">
        <Name>1 s</Name>
      </AcquisitionCycle>
      <DataType TargetID="@OpenLink">
        <Name>Real</Name>
      </DataType>
      <HmiDataType TargetID="@OpenLink">
        <Name>Real</Name>
      </HmiDataType>
    </LinkList>
  </Hmi.Tag.Tag>
</Document>
"""


def main() -> int:
    if LOG.exists():
        LOG.unlink()
    GENERATED.mkdir(parents=True, exist_ok=True)
    xml_path = GENERATED / "probe_hmi_tag_attributes.xml"
    xml_path.write_text(tag_xml(), encoding="utf-8")

    load_openness()
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ExportOptions, ImportOptions  # type: ignore

    tia, project = attach_to_open_project(PROJECT_PATH)
    attached = project is not None
    if tia is None:
        tia = start_tia(with_ui=True)
    try:
        if project is None:
            project = open_project(tia, PROJECT_PATH)
        hmi = find_hmi(project)
        table = hmi.TagFolder.DefaultTagTable
        old = table.Tags.Find(TAG_NAME)
        if old is not None:
            old.Delete()
        imported = table.Tags.Import(FileInfo(str(xml_path)), ImportOptions.Override)
        log(f"Imported probe tag count={imported.Count if hasattr(imported, 'Count') else len(list(imported))}")
        tag = table.Tags.Find(TAG_NAME)
        if tag is None:
            raise RuntimeError("Probe tag import returned no tag")
        log(f"Probe tag found: {tag.Name}")

        for name, value in [
            ("AddressAccessMode", "Absolute"),
            ("Address", "DB1.DBD0"),
            ("Coding", "IEEE754"),
            ("PlcName", "PLC_1"),
            ("TagAddressPanelInfo", "DB1.DBD0"),
            ("ControllerTag", "DB1.EC_Set_SP"),
        ]:
            try:
                tag.SetAttribute(name, value)
                log(f"SET OK {name}={value}")
            except BaseException as exc:
                log(f"SET FAIL {name}={value}: {exc}")

        export_path = GENERATED / "exported_probe_hmi_tag_attributes.xml"
        tag.Export(FileInfo(str(export_path)), ExportOptions.WithReadOnly)
        log(f"Exported={export_path}")
        project.Save()
        log("Project saved.")
        return 0
    except BaseException:
        log("FAILED:")
        log(traceback.format_exc())
        return 1
    finally:
        try:
            if project is not None and not attached:
                project.Close()
        except BaseException as exc:
            log(f"Close skipped: {exc}")
        try:
            tia.Dispose()
        except BaseException as exc:
            log(f"Dispose skipped: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
