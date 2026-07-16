"""Read-only reflection dump for HMI connection creation methods."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from add_irrigation_monitor_main_overview import get_hmi_target
from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, open_project


def main() -> int:
    load_openness()
    project_path = Path(r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
    tia, project = attach_to_open_project(project_path)
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=False)
    try:
        if project is None:
            project = open_project(tia, project_path)
        connections = get_hmi_target(project, "HMI_1").Connections
        print(f"Connection count: {connections.Count}")
        for method in connections.GetType().GetMethods():
            if method.Name not in {"Create", "Import", "Find"}:
                continue
            params = ", ".join(f"{p.ParameterType.FullName} {p.Name}" for p in method.GetParameters())
            print(f"{method.ReturnType.FullName} {method.Name}({params})")
        return 0
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
