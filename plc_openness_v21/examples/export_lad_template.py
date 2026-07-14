from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import start_tia
from plc_programming import (
    attach_to_open_project,
    export_plc_block_xml,
    force_project_offline,
    force_project_online,
    get_plc_software,
    open_project,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a PLC block, including LAD blocks, to TIA XML.")
    parser.add_argument("--project", required=True, help="Path to .ap21 project.")
    parser.add_argument("--block", required=True, help="Template block name, for example FB_LAD_Template.")
    parser.add_argument("--output", required=True, help="Output XML path.")
    parser.add_argument("--plc", help="PLC software name, for example PLC_1.")
    parser.add_argument("--go-online-after", action="store_true", help="Switch PLC device items back online after export.")
    parser.add_argument("--no-ui", action="store_true", help="Start TIA Portal without UI if not already open.")
    args = parser.parse_args()

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
        output = export_plc_block_xml(plc_software, args.block, args.output)
        print(f"Exported block '{args.block}' to: {output}", flush=True)

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
