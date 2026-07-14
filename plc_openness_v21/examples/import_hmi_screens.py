from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import (
    attach_to_open_project,
    force_project_offline,
    force_project_online,
    open_project,
    iter_device_items,
)


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
            if sw.Name.startswith("HMI_RT_"):
                return sw
    raise RuntimeError(f"HMI target not found for device '{hmi_name}'.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import generated HMI screen XML files into a TIA Portal HMI target.")
    parser.add_argument("--project", required=True, help="Path to .ap21 project.")
    parser.add_argument("--hmi", default="HMI_1", help="HMI device name in the project.")
    parser.add_argument("--dir", required=True, help="Directory containing generated screen XML files.")
    parser.add_argument("--go-online-after", action="store_true", help="Switch PLC device items back online after import/save.")
    parser.add_argument("--no-ui", action="store_true", help="Start TIA Portal without UI if not already open.")
    args = parser.parse_args()

    load_openness()
    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ImportOptions  # type: ignore

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

        offline_count = force_project_offline(project)
        print(f"Requested offline mode for {offline_count} online provider(s).", flush=True)

        hmi = get_hmi_target(project, args.hmi)
        source_dir = Path(args.dir).resolve()
        files = sorted(source_dir.glob("*.xml"))
        if not files:
            raise RuntimeError(f"No XML files found in {source_dir}")

        for xml_file in files:
            imported = hmi.ScreenFolder.Screens.Import(FileInfo(str(xml_file)), ImportOptions.Override)
            print(f"Imported screen XML: {xml_file}", flush=True)
            for screen in imported:
                print(f"Imported screen: {screen.Name}", flush=True)

        project.Save()
        print("Project saved.", flush=True)

        if args.go_online_after:
            online_count = force_project_online(project)
            print(f"Requested online mode for {online_count} online provider(s).", flush=True)
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
