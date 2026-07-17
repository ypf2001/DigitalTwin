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
    import_plc_block_xml,
    open_project,
    print_compile_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a generated LAD XML block into a TIA project.")
    parser.add_argument("--project", required=True, help="Path to .ap21 project.")
    parser.add_argument("--xml", required=True, help="XML file to import.")
    parser.add_argument("--plc", help="PLC software name, for example PLC_1.")
    parser.add_argument("--compile", action="store_true", help="Compile PLC software after import.")
    parser.add_argument("--go-online-after", action="store_true", help="Switch PLC device items back online after import/compile/save.")
    parser.add_argument("--no-ui", action="store_true", help="Start TIA Portal without UI if not already open.")
    parser.add_argument("--no-override", action="store_true", help="Do not override existing blocks.")
    args = parser.parse_args()

    tia, project = attach_to_open_project(args.project)
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=not args.no_ui)

    compile_failed = False
    try:
        if project is None:
            project = open_project(tia, args.project)
            print(f"Opened project: {project.Name}", flush=True)
        else:
            print(f"Attached to open project: {project.Name}", flush=True)

        offline_count = force_project_offline(project)
        print(f"Requested offline mode for {offline_count} online provider(s).", flush=True)

        plc_software = get_plc_software(project, args.plc)
        imported_blocks = import_plc_block_xml(plc_software, args.xml, override=not args.no_override)
        print(f"Imported XML: {Path(args.xml).resolve()}", flush=True)
        for block in imported_blocks:
            print(f"Imported block: {block.Name} ({block.ProgrammingLanguage})", flush=True)

        if args.compile:
            result = compile_plc_software(plc_software)
            print_compile_result(result)
            compile_failed = int(result.ErrorCount) > 0

        project.Save()
        print("Project saved.", flush=True)

        if args.go_online_after:
            online_count = force_project_online(project)
            print(f"Requested online mode for {online_count} online provider(s).", flush=True)
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()

    return 1 if compile_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
