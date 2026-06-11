from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Iterable

from openness_loader import load_openness


def open_project(tia, project_path: str | Path):
    load_openness()

    from System.IO import FileInfo  # type: ignore

    project_file = FileInfo(str(Path(project_path).resolve()))
    return tia.Projects.Open(project_file)


def attach_to_open_project(project_path: str | Path):
    load_openness()

    from Siemens.Engineering import TiaPortal  # type: ignore

    target = str(Path(project_path).resolve()).lower()
    for process in TiaPortal.GetProcesses():
        try:
            open_project_path = str(process.ProjectPath)
        except Exception:
            open_project_path = ""

        if open_project_path and Path(open_project_path).resolve().as_posix().lower() == Path(target).as_posix():
            tia = process.Attach()
            for project in tia.Projects:
                if str(Path(str(project.Path)).resolve()).lower() == target:
                    return tia, project
            if tia.Projects.Count > 0:
                return tia, tia.Projects[0]

    return None, None


def create_project(tia, directory: str | Path, name: str):
    load_openness()

    from System.IO import DirectoryInfo  # type: ignore

    project_dir = DirectoryInfo(str(Path(directory).resolve()))
    return tia.Projects.Create(project_dir, name)


def iter_device_items(device_item) -> Iterable[object]:
    yield device_item
    try:
        for child in device_item.DeviceItems:
            yield from iter_device_items(child)
    except Exception:
        return


def iter_plc_softwares(project) -> Iterable[object]:
    load_openness()

    from Siemens.Engineering.HW.Features import SoftwareContainer  # type: ignore
    from Siemens.Engineering.SW import PlcSoftware  # type: ignore

    for device in project.Devices:
        for item in iter_device_items(device):
            try:
                container = item.GetService[SoftwareContainer]()
            except Exception:
                container = None

            if container is None:
                continue

            software = container.Software
            if software is not None and isinstance(software, PlcSoftware):
                yield software


def get_plc_software(project, plc_name: str | None = None):
    matches = list(iter_plc_softwares(project))
    if not matches:
        raise RuntimeError("No PLC software found. Open a project that contains a CPU.")

    if plc_name:
        for software in matches:
            if software.Name == plc_name:
                return software
        names = ", ".join(software.Name for software in matches)
        raise RuntimeError(f"PLC software '{plc_name}' not found. Available: {names}")

    return matches[0]


def force_project_offline(project) -> int:
    """Try to switch all PLC device items in the project to offline mode."""
    load_openness()

    from Siemens.Engineering.Online import OnlineProvider  # type: ignore

    switched = 0
    for device in project.Devices:
        for item in iter_device_items(device):
            try:
                provider = item.GetService[OnlineProvider]()
            except Exception:
                provider = None

            if provider is None:
                continue

            try:
                provider.GoOffline()
                switched += 1
            except Exception:
                # Already offline or not currently connected. Import can proceed.
                pass
    return switched


def force_project_online(project) -> int:
    """Try to switch all PLC device items in the project to online mode."""
    load_openness()

    from Siemens.Engineering.Online import OnlineProvider  # type: ignore

    switched = 0
    for device in project.Devices:
        for item in iter_device_items(device):
            try:
                provider = item.GetService[OnlineProvider]()
            except Exception:
                provider = None

            if provider is None:
                continue

            try:
                provider.GoOnline()
                switched += 1
            except Exception:
                pass
    return switched


def find_plc_block(plc_software, block_name: str):
    block = plc_software.BlockGroup.Blocks.Find(block_name)
    if block is None:
        raise RuntimeError(f"PLC block '{block_name}' not found.")
    return block


def export_plc_block_xml(plc_software, block_name: str, output_path: str | Path):
    load_openness()

    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ExportOptions  # type: ignore

    output_file = Path(output_path).resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    block = find_plc_block(plc_software, block_name)
    block.Export(FileInfo(str(output_file)), ExportOptions.WithReadOnly)
    return output_file


def import_plc_block_xml(plc_software, xml_path: str | Path, override: bool = True):
    load_openness()

    from System.IO import FileInfo  # type: ignore
    from Siemens.Engineering import ImportOptions  # type: ignore

    xml_file = Path(xml_path).resolve()
    if not xml_file.exists():
        raise FileNotFoundError(xml_file)

    import_options = ImportOptions.Override if override else getattr(ImportOptions, "None")
    return plc_software.BlockGroup.Blocks.Import(FileInfo(str(xml_file)), import_options)


def import_scl_source(plc_software, source_path: str | Path, source_name: str | None = None):
    load_openness()

    from Siemens.Engineering.SW.ExternalSources import GenerateBlockOption  # type: ignore

    source_file = Path(source_path).resolve()
    if not source_file.exists():
        raise FileNotFoundError(source_file)

    name = source_name or source_file.stem
    sources = plc_software.ExternalSourceGroup.ExternalSources

    existing = sources.Find(name)
    if existing is not None:
        try:
            existing.Delete()
        except Exception:
            name = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    external_source = sources.CreateFromFile(name, str(source_file))
    external_source.GenerateBlocksFromSource(GenerateBlockOption.KeepOnError)
    return external_source


def compile_plc_software(plc_software):
    load_openness()

    from Siemens.Engineering.Compiler import ICompilable  # type: ignore

    compiler = plc_software.GetService[ICompilable]()
    if compiler is None:
        raise RuntimeError("This PLC software does not expose ICompilable.")
    return compiler.Compile()


def print_compile_result(result) -> None:
    print(f"Compile state: {result.State}")
    print(f"Errors: {result.ErrorCount}, warnings: {result.WarningCount}")
    for message in result.Messages:
        print(f"[{message.State}] {message.Description}")
