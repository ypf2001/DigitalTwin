from __future__ import annotations

import html
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_hmi_codegen import all_hmi_tags, db1_field_map, default_scl_path
from plc_programming import attach_to_open_project, force_project_offline, iter_device_items, open_project


DEFAULT_PROJECT_PATH = Path(r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
GENERATED_DIR = ROOT / "generated_hmi"
LOG_PATH = GENERATED_DIR / "import_hmi_db1_tags.log"
DEFAULT_HMI_CONNECTION_NAME = "HMI_\u8fde\u63a5_1"
DEFAULT_TEMPLATE_TAG_NAME = "DB1.EC_Set_SP"
FIELD_MAP_CACHE = {}


def log(message: str) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


def hmi_tag_xml(tag_name: str, connection_name: str, controller_tag: str) -> str:
    data_type = plc_to_hmi_datatype(tag_name)
    coding = plc_to_hmi_coding(tag_name)
    length = plc_to_length(tag_name)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V21" />
  <Hmi.Tag.Tag ID="0">
    <AttributeList>
      <AcquisitionTriggerMode>Visible</AcquisitionTriggerMode>
      <AddressAccessMode>Symbolic</AddressAccessMode>
      <Coding>{html.escape(coding)}</Coding>
      <ConfirmationType>None</ConfirmationType>
      <GmpRelevant>false</GmpRelevant>
      <JobNumber>0</JobNumber>
      <Length>{length}</Length>
      <LinearScaling>false</LinearScaling>
      <LogicalAddress />
      <MandatoryCommenting>false</MandatoryCommenting>
      <Name>{html.escape(controller_tag)}</Name>
      <Persistency>false</Persistency>
      <QualityCode>false</QualityCode>
      <Synchronization>false</Synchronization>
      <UpdateMode>ProjectWide</UpdateMode>
      <UseMultiplexing>false</UseMultiplexing>
    </AttributeList>
    <LinkList>
      <AcquisitionCycle TargetID="@OpenLink">
        <Name>1 s</Name>
      </AcquisitionCycle>
      <Connection TargetID="@OpenLink">
        <Name>{html.escape(connection_name)}</Name>
      </Connection>
      <DataType TargetID="@OpenLink">
        <Name>{html.escape(data_type)}</Name>
      </DataType>
      <HmiDataType TargetID="@OpenLink">
        <Name>{html.escape(data_type)}</Name>
      </HmiDataType>
    </LinkList>
    <ObjectList>
      <MultilingualText ID="5" CompositionName="Comment">
        <ObjectList>
          <MultilingualTextItem ID="6" CompositionName="Items">
            <AttributeList>
              <Culture>zh-CN</Culture>
              <Text />
            </AttributeList>
          </MultilingualTextItem>
        </ObjectList>
      </MultilingualText>
      <MultilingualText ID="7" CompositionName="DisplayName">
        <ObjectList>
          <MultilingualTextItem ID="8" CompositionName="Items">
            <AttributeList>
              <Culture>zh-CN</Culture>
              <Text />
            </AttributeList>
          </MultilingualTextItem>
        </ObjectList>
      </MultilingualText>
      <MultilingualText ID="9" CompositionName="TagValue">
        <ObjectList>
          <MultilingualTextItem ID="A" CompositionName="Items">
            <AttributeList>
              <Culture>zh-CN</Culture>
              <Text />
            </AttributeList>
          </MultilingualTextItem>
        </ObjectList>
      </MultilingualText>
    </ObjectList>
  </Hmi.Tag.Tag>
</Document>
"""


def resolve_connection_name(hmi, template_tag_name: str) -> str:
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ExportOptions  # type: ignore

    table = hmi.TagFolder.DefaultTagTable
    template_tag = table.Tags.Find(template_tag_name)
    if template_tag is None:
        raise RuntimeError(
            f"Template HMI tag not found: {template_tag_name}. "
            "Please create one bound tag in the default HMI tag table first."
        )

    export_path = GENERATED_DIR / "reference_hmi_tag_export.xml"
    if export_path.exists():
        export_path.unlink()
    template_tag.Export(FileInfo(str(export_path)), ExportOptions.WithReadOnly)
    tree = ET.parse(export_path)
    conn_node = tree.find(".//Connection/Name")
    if conn_node is None or not (conn_node.text or "").strip():
        raise RuntimeError(f"Connection name not found in exported template tag: {template_tag_name}")
    connection_name = (conn_node.text or "").strip()
    log(f"Template HMI tag: {template_tag_name}")
    log(f"Exported template tag: {export_path}")
    log(f"Resolved HMI connection name: {connection_name}")
    return connection_name


def plc_to_hmi_datatype(tag_name: str) -> str:
    field = FIELD_MAP_CACHE[tag_name]
    return field.datatype


def plc_to_hmi_coding(tag_name: str) -> str:
    field = FIELD_MAP_CACHE[tag_name]
    if field.datatype == "Real":
        return "IEEE754Float"
    return "Binary"


def plc_to_length(tag_name: str) -> int:
    field = FIELD_MAP_CACHE[tag_name]
    lengths = {
        "Bool": 1,
        "Byte": 1,
        "Word": 2,
        "Int": 2,
        "UInt": 2,
        "DWord": 4,
        "DInt": 4,
        "UDInt": 4,
        "Real": 4,
    }
    return lengths.get(field.datatype, 4)


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
            if container is not None and container.Software is not None and container.Software.Name.startswith("HMI_RT_"):
                return container.Software
    raise RuntimeError("HMI_1 runtime software not found.")


def import_hmi_tags(hmi, field_map, connection_name: str):
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ImportOptions  # type: ignore

    table = hmi.TagFolder.DefaultTagTable
    imported_count = 0
    for tag_name in all_hmi_tags():
        field = field_map[tag_name]
        controller_tag = f"DB1.{field.name}"
        xml_path = GENERATED_DIR / f"hmi_tag_{tag_name}.xml"
        xml_path.write_text(hmi_tag_xml(tag_name, connection_name, controller_tag), encoding="utf-8")
        imported = table.Tags.Import(FileInfo(str(xml_path)), ImportOptions.Override)
        imported_names = [tag.Name for tag in imported]
        imported_count += len(imported_names)
        log(f"Imported HMI tag: {tag_name} -> {connection_name} / {controller_tag} ({imported_names})")
    return imported_count


def log_hmi_connection_state(hmi) -> None:
    count = hmi.Connections.Count
    log(f"HMI connection count: {count}")
    for conn in hmi.Connections:
        log(f"HMI connection: {conn.Name}")


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv
    project_path = Path(args[1]) if len(args) > 1 else DEFAULT_PROJECT_PATH
    connection_name = args[2] if len(args) > 2 else None
    template_tag_name = args[3] if len(args) > 3 else DEFAULT_TEMPLATE_TAG_NAME
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    log("Start HMI DB1 tag import.")
    log(f"Project path: {project_path}")
    log(f"Requested HMI connection name: {connection_name or '<auto>'}")
    log(f"Template HMI tag name: {template_tag_name}")

    load_openness()
    field_map = db1_field_map(default_scl_path())
    global FIELD_MAP_CACHE
    FIELD_MAP_CACHE = field_map

    tia, project = attach_to_open_project(project_path)
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=False)

    try:
        if project is None:
            project = open_project(tia, project_path)
        log(f"Project: {project.Name}")

        offline_count = force_project_offline(project)
        log(f"Requested offline mode for {offline_count} online provider(s).")
        hmi = find_hmi(project)
        log(f"HMI: {hmi.Name}")
        log_hmi_connection_state(hmi)
        if not connection_name:
            connection_name = resolve_connection_name(hmi, template_tag_name)
        imported_count = import_hmi_tags(hmi, field_map, connection_name)
        log(f"Imported HMI tag count: {imported_count}")

        project.Save()
        log("Project saved.")
        return 0
    except BaseException:
        log("FAILED:")
        log(traceback.format_exc())
        return 1
    finally:
        try:
            if project is not None and not attached_project:
                project.Close()
        except BaseException as exc:
            log(f"Close skipped after failure: {exc}")
        try:
            tia.Dispose()
        except BaseException as exc:
            log(f"Dispose skipped after failure: {exc}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
