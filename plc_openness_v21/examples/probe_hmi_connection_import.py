from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import iter_device_items, open_project


PROJECT_PATH = Path(r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
GENERATED = ROOT / "generated_hmi"
LOG = GENERATED / "probe_hmi_connection_import.log"
CONNECTION_NAME = "HMI_Connection_PLC_1"
SAFETY_TEXT = (
    "Risky probe disabled by default. This script imports guessed HMI connection XML and may destabilize TIA Portal. "
    "Run only in an isolated test session with --allow-risk."
)


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


def connection_xml(variant: str) -> str:
    common_head = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V21" />
"""
    common_tail = """
</Document>
"""
    attrs: list[str]
    if variant == "driver_only":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>ILRT_S7_1500_OMS</Driver>",
        ]
    elif variant == "driver_plcid":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>ILRT_S7_1500_OMS</Driver>",
            "<PlcId>ILRT_S7_1500_OMS</PlcId>",
        ]
    elif variant == "driver_plcid_params":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>ILRT_S7_1500_OMS</Driver>",
            "<PlcId>ILRT_S7_1500_OMS</PlcId>",
            "<Online>false</Online>",
            "<StationName>HMI_1</StationName>",
            "<PartnerName>PLC_1</PartnerName>",
            "<ParametersDescription>SIMATIC S7 1200/1500</ParametersDescription>",
        ]
    elif variant == "driver_s7plus":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>SIMATIC S7 1200/1500</Driver>",
            "<PlcId>ILRT_S7_1500_OMS</PlcId>",
        ]
    elif variant == "driver_params_name":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>ILRT_S7_1500_OMS</Driver>",
            "<ParametersDescription>SIMATIC S7 1200/1500</ParametersDescription>",
        ]
    elif variant == "driver_params_station":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>ILRT_S7_1500_OMS</Driver>",
            "<Online>false</Online>",
            "<StationName>HMI_1</StationName>",
            "<PartnerName>PLC_1</PartnerName>",
            "<ParametersDescription>SIMATIC S7 1200/1500</ParametersDescription>",
        ]
    elif variant == "driver_params_xml":
        attrs = [
            f"<Name>{CONNECTION_NAME}</Name>",
            "<Driver>ILRT_S7_1500_OMS</Driver>",
            "<ParametersDescription>&lt;PlcId&gt;ILRT_S7_1500_OMS&lt;/PlcId&gt;</ParametersDescription>",
        ]
    else:
        raise RuntimeError(f"Unknown variant {variant}")

    body = "\n".join(f"      {line}" for line in attrs)
    return (
        common_head
        + '  <Hmi.Communication.Connection ID="1" CompositionName="Connections">\n'
        + "    <AttributeList>\n"
        + body
        + "\n    </AttributeList>\n"
        + "  </Hmi.Communication.Connection>\n"
        + common_tail
    )


def main(argv: list[str]) -> int:
    if "--allow-risk" not in argv:
        print(SAFETY_TEXT)
        return 2

    variant = "driver_only"
    for arg in argv[1:]:
        if not arg.startswith("--"):
            variant = arg
            break
    if LOG.exists():
        LOG.unlink()
    log(f"Variant={variant}")
    xml_path = GENERATED / f"probe_connection_{variant}.xml"
    xml_path.write_text(connection_xml(variant), encoding="utf-8")
    log(f"XML={xml_path}")

    load_openness()
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ExportOptions, ImportOptions  # type: ignore

    # Never attach this risky import probe to an already-open engineering session.
    attached = False
    tia = start_tia(with_ui=False)
    project = None
    try:
        project = open_project(tia, PROJECT_PATH)
        hmi = find_hmi(project)
        existing = hmi.Connections.Find(CONNECTION_NAME)
        if existing is not None:
            log("Existing connection found; deleting before probe.")
            existing.Delete()
        imported = hmi.Connections.Import(FileInfo(str(xml_path)), ImportOptions.Override)
        log(f"Imported count={imported.Count if hasattr(imported, 'Count') else len(list(imported))}")
        conn = hmi.Connections.Find(CONNECTION_NAME)
        if conn is None:
            log("Import returned but connection not found by name.")
            return 2
        log(f"Imported connection name={conn.Name}")
        export_path = GENERATED / "exported_probe_connection.xml"
        conn.Export(FileInfo(str(export_path)), ExportOptions.WithReadOnly)
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
            log(f"Close skipped after failure: {exc}")
        try:
            tia.Dispose()
        except BaseException as exc:
            log(f"Dispose skipped after failure: {exc}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
