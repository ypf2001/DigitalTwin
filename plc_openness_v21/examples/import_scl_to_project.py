from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import start_tia
from plc_programming import (
    attach_to_open_project,
    compile_plc_software,
    force_project_offline,
    force_project_online,
    get_plc_software,
    import_scl_source,
    open_project,
    print_compile_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import an SCL source into a TIA Portal V21 PLC.")
    parser.add_argument("--project", required=True, help="Path to the .ap21 project file.")
    parser.add_argument("--source", required=True, help="Path to the .scl source file.")
    parser.add_argument("--plc", help="PLC software name, for example PLC_1.")
    parser.add_argument("--source-name", help="Name of the external source in TIA Portal.")
    parser.add_argument("--compile", action="store_true", help="Compile PLC software after generating blocks.")
    parser.add_argument("--go-online-after", action="store_true", help="Switch PLC device items back online after import/compile/save.")
    parser.add_argument("--no-ui", action="store_true", help="Start TIA Portal without UI.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

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

        plc_software = get_plc_software(project, args.plc)
        print(f"Using PLC software: {plc_software.Name}", flush=True)

        external_source = import_scl_source(plc_software, args.source, args.source_name)
        print(f"Imported and generated blocks from source: {external_source.Name}", flush=True)

        if args.compile:
            result = compile_plc_software(plc_software)
            print_compile_result(result)

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
