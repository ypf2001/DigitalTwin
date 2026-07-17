"""Validate and optionally write the deployable DB1 control contract.

Default behavior is a dry run. Use --apply only after the PLC is in manual
or a controlled local-automatic commissioning mode. The script never enables
the EC/pH decoupler; enabling is a separate guarded PLCClient operation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "control_parameters.yaml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_client import PLCClient

def load_parameters(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        parameters = yaml.safe_load(handle) or {}
    if not isinstance(parameters, dict):
        raise ValueError("control parameter file must contain a YAML mapping")
    return parameters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the validated parameters to DB1; decoupling remains disabled",
    )
    args = parser.parse_args()

    parameters = load_parameters(args.config.resolve())
    decoupling = parameters.get("decoupling", {})
    limits = parameters.get("limits", {})
    print(f"config: {args.config.resolve()}")
    print(f"decoupler enabled in file: {bool(decoupling.get('enabled', False))}")
    print(
        "limits: q_f=[{0}, {1}], q_a=[{2}, {3}]".format(
            limits.get("q_f_min"), limits.get("q_f_max"),
            limits.get("q_a_min"), limits.get("q_a_max"),
        )
    )

    if not args.apply:
        print("dry run: no PLC connection and no DB1 write")
        return 0

    plc = PLCClient()
    if not plc.connect():
        return 2
    try:
        return 0 if plc.write_control_parameters(parameters, verify=True) else 3
    finally:
        plc.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
