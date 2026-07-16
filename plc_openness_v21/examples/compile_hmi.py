"""Compile the configured HMI software and print its TIA compiler messages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, force_project_offline, iter_device_items, open_project, print_compile_result


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
            if container is not None and container.Software is not None and str(container.Software.Name).startswith("HMI_RT_"):
                return container.Software
    raise RuntimeError(f"HMI target not found for device '{hmi_name}'.")


def print_messages(messages, depth: int = 0) -> None:
    for message in messages:
        description = getattr(message, "Description", "") or "<no description>"
        path = getattr(message, "Path", "")
        print(f"{'  ' * depth}[{message.State}] {path}: {description}", flush=True)
        children = getattr(message, "Messages", None)
        if children is not None:
            print_messages(children, depth + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the HMI runtime software.")
    parser.add_argument("--project", default=r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
    parser.add_argument("--hmi", default="HMI_1")
    args = parser.parse_args()

    load_openness()
    from Siemens.Engineering.Compiler import ICompilable  # type: ignore

    tia, project = attach_to_open_project(Path(args.project))
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=True)
    try:
        if project is None:
            project = open_project(tia, args.project)
        print(f"Project: {project.Name}", flush=True)
        print(f"Requested offline mode for {force_project_offline(project)} provider(s).", flush=True)
        hmi = get_hmi_target(project, args.hmi)
        compiler = hmi.GetService[ICompilable]()
        if compiler is None:
            raise RuntimeError("HMI runtime does not expose ICompilable.")
        result = compiler.Compile()
        print_compile_result(result)
        if result.ErrorCount:
            print_messages(result.Messages)
        project.Save()
        return 0 if result.ErrorCount == 0 else 3
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
