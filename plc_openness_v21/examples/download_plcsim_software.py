"""Download the compiled PLC software to the configured PLCSIM target.

This tool refuses field deployment profiles unless --allow-field is supplied.
It intentionally downloads software only, leaving hardware configuration and
physical I/O untouched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config_loader import load_config
from openness_loader import load_openness, start_tia
from plc_programming import (
    attach_to_open_project,
    force_project_offline,
    iter_device_items,
    open_project,
)


def _print_configuration(phase: str, configuration) -> None:
    selection = getattr(configuration, "CurrentSelection", None)
    message = getattr(configuration, "Message", "")
    print(
        f"{phase}: {configuration.GetType().FullName} "
        f"selection={selection} message={message}",
        flush=True,
    )


def _find_download_provider(project, plc_name: str):
    from Siemens.Engineering.Download import DownloadProvider  # type: ignore

    for device in project.Devices:
        for item in iter_device_items(device):
            if item.Name != plc_name:
                continue
            try:
                provider = item.GetService[DownloadProvider]()
            except Exception:
                provider = None
            if provider is not None:
                return provider
    raise RuntimeError(f"PLC download provider '{plc_name}' not found.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download compiled PLC software to PLCSIM.")
    parser.add_argument("--project", default=r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
    parser.add_argument("--plc", default="PLC_1")
    parser.add_argument("--allow-field", action="store_true")
    args = parser.parse_args()

    profile = load_config().deployment().get("profile", "simulation_plc")
    if profile != "simulation_plc" and not args.allow_field:
        print(f"Refusing download because deployment.profile={profile!r}, not simulation_plc.")
        return 2

    load_openness()
    from Siemens.Engineering.Download import DownloadConfigurationDelegate, DownloadOptions  # type: ignore

    project_path = Path(args.project).resolve()
    tia, project = attach_to_open_project(project_path)
    attached_project = project is not None
    if tia is None:
        tia = start_tia(with_ui=True)

    try:
        if project is None:
            project = open_project(tia, project_path)
            print(f"Opened project: {project.Name}")
        else:
            print(f"Attached to open project: {project.Name}")

        offline_count = force_project_offline(project)
        print(f"Requested offline mode for {offline_count} online provider(s)")
        provider = _find_download_provider(project, args.plc)
        configuration = provider.Configuration
        if not bool(configuration.IsConfigured):
            raise RuntimeError("PLC download connection is not configured.")
        target_interface = next(
            target
            for mode in configuration.Modes
            for pc_interface in mode.PcInterfaces
            if pc_interface.Name == "PLCSIM"
            for target in pc_interface.TargetInterfaces
        )
        if not bool(configuration.ApplyConfiguration(target_interface)):
            raise RuntimeError("Could not apply the PLCSIM download target configuration.")
        print(f"Download target: PLCSIM / {target_interface.Name}")

        def before(config) -> None:
            _print_configuration("pre-download", config)
            from Siemens.Engineering.Download.Configurations import (  # type: ignore
                StartModules,
                StartModulesSelections,
                StopModules,
                StopModulesSelections,
            )

            # The download service requires an explicit decision for stopping
            # and restarting the simulated CPU. Do not auto-accept any memory,
            # password, certificate, or protection-level configuration.
            if isinstance(config, StopModules):
                config.CurrentSelection = StopModulesSelections.StopAll
            elif isinstance(config, StartModules):
                config.CurrentSelection = StartModulesSelections.StartModule

        def after(config) -> None:
            _print_configuration("post-download", config)

        # pythonnet does not automatically cast ConnectionConfiguration to its
        # IConfiguration interface for this overloaded .NET method. Select the
        # four-argument overload explicitly and invoke it through reflection.
        overload = next(
            method
            for method in provider.GetType().GetMethods()
            if method.Name == "Download"
            and len(method.GetParameters()) == 4
            and method.GetParameters()[0].ParameterType.FullName
            == "Siemens.Engineering.Connection.IConfiguration"
        )
        from System import Array, Object  # type: ignore

        result = overload.Invoke(
            provider,
            Array[Object](
                [
                    target_interface,
                    DownloadConfigurationDelegate(before),
                    DownloadConfigurationDelegate(after),
                    DownloadOptions.Software,
                ]
            ),
        )
        print(f"Download state: {result.State}")
        print(f"Errors: {result.ErrorCount}, warnings: {result.WarningCount}")
        for message in result.Messages:
            text = getattr(message, "Description", None) or getattr(message, "Message", None) or str(message)
            print(f"[{message.State}] {text}")
        return 0 if result.ErrorCount == 0 else 3
    finally:
        if project is not None and not attached_project:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
