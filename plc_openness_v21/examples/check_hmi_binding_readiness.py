from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import iter_device_items, open_project


PROJECT_PATH = Path(r"D:\dw_plc\xiaweiji\xiaweiji.ap21")


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


def main() -> int:
    load_openness()
    tia = start_tia(with_ui=False)
    project = None
    try:
        project = open_project(tia, PROJECT_PATH)
        hmi = find_hmi(project)
        print(f"Project: {project.Name}")
        print(f"HMI runtime: {hmi.Name}")
        print(f"Connections: {hmi.Connections.Count}")
        for conn in hmi.Connections:
            print(f"  - {conn.Name}")
        default_table = hmi.TagFolder.DefaultTagTable
        print(f"Default tag table: {default_table.Name}")
        print(f"Default tag count: {default_table.Tags.Count}")
        if hmi.Connections.Count <= 0:
            print("READY: NO")
            print("Reason: create and save one HMI-to-PLC connection in TIA Portal first.")
        else:
            print("READY: YES")
        return 0
    finally:
        if project is not None:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
