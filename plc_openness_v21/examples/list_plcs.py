from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import start_tia
from plc_programming import attach_to_open_project, iter_plc_softwares, open_project


def main() -> int:
    parser = argparse.ArgumentParser(description="List PLC software objects in a TIA project.")
    parser.add_argument("--project", required=True, help="Path to the .ap21 project file.")
    args = parser.parse_args()

    print("Looking for an already-open TIA project...", flush=True)
    tia, project = attach_to_open_project(args.project)
    if tia is None:
        print("Starting TIA Portal...", flush=True)
        tia = start_tia(with_ui=True)

    attached_project = project is not None
    try:
        if project is None:
            print("Opening project...", flush=True)
            project = open_project(tia, args.project)
        else:
            print("Attached to open project.", flush=True)
        print(f"Project: {project.Name}", flush=True)

        count = 0
        for software in iter_plc_softwares(project):
            count += 1
            print(f"PLC software {count}: {software.Name}", flush=True)

        if count == 0:
            print("No PLC software found.", flush=True)
            return 2
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
