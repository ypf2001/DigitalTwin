from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_PUBLIC_API = Path(
    r"D:\Program Files\Siemens\Automation\Portal V21\PublicAPI\V21\net48"
)
DEFAULT_BIN_PUBLIC_API = Path(
    r"D:\Program Files\Siemens\Automation\Portal V21\Bin\PublicAPI"
)


def load_openness(public_api_dir: str | os.PathLike[str] | None = None) -> Path:
    """Load Siemens TIA Portal V21 Openness .NET assemblies."""
    api_dir = Path(public_api_dir) if public_api_dir else DEFAULT_PUBLIC_API
    if not api_dir.exists():
        raise FileNotFoundError(f"PublicAPI folder not found: {api_dir}")

    try:
        from pythonnet import load

        load("netfx")
    except RuntimeError:
        # The CLR may already be loaded by another module in this process.
        pass

    import clr  # type: ignore

    sys.path.append(str(api_dir))
    if DEFAULT_BIN_PUBLIC_API.exists():
        sys.path.append(str(DEFAULT_BIN_PUBLIC_API))
        contract_dll = DEFAULT_BIN_PUBLIC_API / "Siemens.Engineering.Contract.dll"
        if contract_dll.exists():
            clr.AddReference(str(contract_dll))

    for dll_name in (
        "Siemens.Engineering.Base.dll",
        "Siemens.Engineering.Step7.dll",
    ):
        dll_path = api_dir / dll_name
        if not dll_path.exists():
            raise FileNotFoundError(f"Required Openness DLL not found: {dll_path}")
        clr.AddReference(str(dll_path))

    return api_dir


def start_tia(with_ui: bool = True):
    """Start TIA Portal and return the TiaPortal instance."""
    load_openness()

    from Siemens.Engineering import TiaPortal, TiaPortalMode  # type: ignore

    mode = TiaPortalMode.WithUserInterface if with_ui else TiaPortalMode.WithoutUserInterface
    return TiaPortal(mode)
