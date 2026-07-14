from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, get_plc_software, open_project


def main() -> int:
    load_openness()
    project_path = r"D:\dw_plc\xiaweiji\xiaweiji.ap21"
    print("attach...", flush=True)
    tia, project = attach_to_open_project(project_path)
    attached = project is not None
    print(f"attached: {attached}", flush=True)
    if tia is None:
        print("start tia", flush=True)
        tia = start_tia(with_ui=True)

    try:
        if project is None:
            print("open project", flush=True)
            project = open_project(tia, project_path)
        print(f"project: {project.Name}", flush=True)
        plc = get_plc_software(project, "PLC_1")
        print(f"plc: {plc.Name} {plc.GetType().FullName}", flush=True)
        print("plc tag-related properties:", flush=True)
        for prop in plc.GetType().GetProperties():
            if "Tag" in prop.Name or "Table" in prop.Name:
                print(f"  {prop.Name}: {prop.PropertyType.FullName}", flush=True)

        group = plc.TagTableGroup
        print(f"TagTableGroup: {group.GetType().FullName}", flush=True)
        print("Existing PLC tag tables:", flush=True)
        for table in group.TagTables:
            print(f"  table: {table.Name} {table.GetType().FullName}", flush=True)
            for tag in table.Tags:
                print(f"    tag: {tag.Name}", flush=True)

        print("TagTables methods:", flush=True)
        seen: set[str] = set()
        for method in group.TagTables.GetType().GetMethods():
            if method.DeclaringType == group.TagTables.GetType() and method.Name not in seen:
                seen.add(method.Name)
                sig = ", ".join(f"{p.ParameterType.Name} {p.Name}" for p in method.GetParameters())
                print(f"  {method.Name}({sig})", flush=True)
    finally:
        if project is not None and not attached:
            project.Close()
        tia.Dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        traceback.print_exc()
        raise
