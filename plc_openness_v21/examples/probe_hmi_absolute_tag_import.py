from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import iter_device_items, open_project


DEFAULT_PROJECT_PATH = Path(r"D:\dw_plc\xiaweiji_hmi_probe\xiaweiji.ap21")
GENERATED_DIR = ROOT / "generated_hmi"
LOG_PATH = GENERATED_DIR / "probe_hmi_absolute_tag_import.log"
TAG_NAME = "Probe_Absolute_EC_Set_SP"
DEFAULT_CONNECTION_NAME = "HMI_\u8fde\u63a5_1"


def log(message: str) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


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
    raise RuntimeError("HMI_1 runtime software not found.")


def xml_for_variant(variant: str, connection_name: str) -> str:
    if variant == "attr_mode_panel":
        body = f"""
  <Hmi.Tag.Tag ID="1" CompositionName="Tags">
    <AttributeList>
      <Name>{TAG_NAME}</Name>
      <Length>4</Length>
      <AddressAccessMode>Absolute</AddressAccessMode>
      <TagAddressPanelInfo>DB1.DBD0</TagAddressPanelInfo>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink"><Name>1 s</Name></AcquisitionCycle>
      <Connection TargetID="@OpenLink"><Name>{connection_name}</Name></Connection>
      <DataType TargetID="@OpenLink"><Name>Real</Name></DataType>
      <HmiDataType TargetID="@OpenLink"><Name>Real</Name></HmiDataType>
    </LinkList>
  </Hmi.Tag.Tag>
"""
    elif variant == "attr_mode_address":
        body = f"""
  <Hmi.Tag.Tag ID="1" CompositionName="Tags">
    <AttributeList>
      <Name>{TAG_NAME}</Name>
      <Length>4</Length>
      <AddressAccessMode>Absolute</AddressAccessMode>
      <Address>DB1.DBD0</Address>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink"><Name>1 s</Name></AcquisitionCycle>
      <Connection TargetID="@OpenLink"><Name>{connection_name}</Name></Connection>
      <DataType TargetID="@OpenLink"><Name>Real</Name></DataType>
      <HmiDataType TargetID="@OpenLink"><Name>Real</Name></HmiDataType>
    </LinkList>
  </Hmi.Tag.Tag>
"""
    elif variant == "link_mode_address":
        body = f"""
  <Hmi.Tag.Tag ID="1" CompositionName="Tags">
    <AttributeList>
      <Name>{TAG_NAME}</Name>
      <Length>4</Length>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink"><Name>1 s</Name></AcquisitionCycle>
      <Connection TargetID="@OpenLink"><Name>{connection_name}</Name></Connection>
      <DataType TargetID="@OpenLink"><Name>Real</Name></DataType>
      <HmiDataType TargetID="@OpenLink"><Name>Real</Name></HmiDataType>
      <AddressAccessMode TargetID="@OpenLink"><Name>Absolute</Name></AddressAccessMode>
      <Address TargetID="@OpenLink"><Name>DB1.DBD0</Name></Address>
    </LinkList>
  </Hmi.Tag.Tag>
"""
    elif variant == "controller_with_types":
        body = f"""
  <Hmi.Tag.Tag ID="1" CompositionName="Tags">
    <AttributeList>
      <Name>{TAG_NAME}</Name>
      <Length>4</Length>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink"><Name>1 s</Name></AcquisitionCycle>
      <Connection TargetID="@OpenLink"><Name>{connection_name}</Name></Connection>
      <DataType TargetID="@OpenLink"><Name>Real</Name></DataType>
      <HmiDataType TargetID="@OpenLink"><Name>Real</Name></HmiDataType>
      <ControllerTag TargetID="@OpenLink"><Name>DB1.EC_Set_SP</Name></ControllerTag>
    </LinkList>
  </Hmi.Tag.Tag>
"""
    elif variant == "controller_symbolic_attr":
        body = f"""
  <Hmi.Tag.Tag ID="1" CompositionName="Tags">
    <AttributeList>
      <Name>{TAG_NAME}</Name>
      <Length>4</Length>
      <AddressAccessMode>Symbolic</AddressAccessMode>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink"><Name>1 s</Name></AcquisitionCycle>
      <Connection TargetID="@OpenLink"><Name>{connection_name}</Name></Connection>
      <DataType TargetID="@OpenLink"><Name>Real</Name></DataType>
      <HmiDataType TargetID="@OpenLink"><Name>Real</Name></HmiDataType>
      <ControllerTag TargetID="@OpenLink"><Name>DB1.EC_Set_SP</Name></ControllerTag>
    </LinkList>
  </Hmi.Tag.Tag>
"""
    else:
        raise RuntimeError(f"Unknown variant: {variant}")

    return f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V21" />
{body}
</Document>
"""


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv
    variant = args[1] if len(args) > 1 else "attr_mode_panel"
    project_path = Path(args[2]) if len(args) > 2 else DEFAULT_PROJECT_PATH
    connection_name = args[3] if len(args) > 3 else DEFAULT_CONNECTION_NAME
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    log(f"Variant={variant}")
    log(f"Project={project_path}")
    log(f"Connection={connection_name}")
    xml_path = GENERATED_DIR / f"probe_hmi_abs_{variant}.xml"
    xml_path.write_text(xml_for_variant(variant, connection_name), encoding="utf-8")

    load_openness()
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ImportOptions  # type: ignore

    tia = start_tia(with_ui=False)
    project = None
    try:
        project = open_project(tia, project_path)
        hmi = find_hmi(project)
        table = hmi.TagFolder.DefaultTagTable
        old = table.Tags.Find(TAG_NAME)
        if old is not None:
            old.Delete()
        imported = table.Tags.Import(FileInfo(str(xml_path)), ImportOptions.Override)
        imported_names = [tag.Name for tag in imported]
        log(f"IMPORTED {imported_names}")
        return 0
    except BaseException:
        log("FAILED:")
        log(traceback.format_exc())
        return 1
    finally:
        try:
            if project is not None:
                project.Close()
        except BaseException as exc:
            log(f"Close skipped: {exc}")
        try:
            tia.Dispose()
        except BaseException as exc:
            log(f"Dispose skipped: {exc}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
