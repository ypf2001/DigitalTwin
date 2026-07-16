"""Restore the missing S7-1500 HMI connection referenced by the tag table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from add_irrigation_monitor_main_overview import get_hmi_target
from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, force_project_offline, open_project


def connection_xml(name: str) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V21" />
  <Hmi.Communication.Connection ID="1" CompositionName="Connections">
    <AttributeList>
      <Name>{name}</Name>
      <Driver>ILRT_S7_1500_OMS</Driver>
    </AttributeList>
  </Hmi.Communication.Connection>
</Document>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Import the HMI S7-1500 connection required by the HMI tags.")
    parser.add_argument("--project", default=r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
    parser.add_argument("--hmi", default="HMI_1")
    parser.add_argument("--connection", default="HMI_连接_1")
    parser.add_argument("--work-dir", default=str(ROOT / "generated_hmi" / "connection_restore"))
    args = parser.parse_args()

    load_openness()
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ImportOptions  # type: ignore

    tia, project = attach_to_open_project(Path(args.project))
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=True)
    try:
        if project is None:
            project = open_project(tia, args.project)
        print(f"Requested offline mode for {force_project_offline(project)} provider(s).", flush=True)
        hmi = get_hmi_target(project, args.hmi)
        work_dir = Path(args.work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        xml_path = work_dir / "HMI_Connection.xml"
        xml_path.write_text(connection_xml(args.connection), encoding="utf-8")
        imported = hmi.Connections.Import(FileInfo(str(xml_path)), ImportOptions.Override)
        print(f"Imported connection: {[item.Name for item in imported]}", flush=True)
        project.Save()
        print("Project saved.", flush=True)
        return 0
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
