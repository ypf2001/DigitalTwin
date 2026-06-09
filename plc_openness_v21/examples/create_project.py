from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import start_tia
from plc_programming import create_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a TIA Portal V21 project.")
    parser.add_argument("--directory", required=True, help="Folder where TIA should create the project.")
    parser.add_argument("--name", required=True, help="TIA project name.")
    parser.add_argument("--cpu-name", default="PLC_1", help="Device name when --cpu-type is used.")
    parser.add_argument("--cpu-type", help="Hardware catalog type identifier, for example OrderNumber:6ES7...")
    parser.add_argument("--no-ui", action="store_true", help="Start TIA Portal without UI.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    tia = start_tia(with_ui=not args.no_ui)
    project = None
    try:
        project = create_project(tia, args.directory, args.name)
        print(f"Created project: {project.Name}")

        if args.cpu_type:
            project.Devices.CreateWithItem(args.cpu_type, args.cpu_name, "PLC_1")
            print(f"Created CPU device: {args.cpu_name}")

        project.Save()
        print("Project saved.")
    finally:
        if project is not None:
            project.Close()
        tia.Dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
