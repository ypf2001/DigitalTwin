r"""Write N/P/K fertilizer channel configuration into PLC DB1.

The PLC keeps q_f_cmd as total fertilizer demand from the EC controller.
N/P/K channels split that total by ratio and can optionally apply their
own PID trim if online N/P/K feedback is available.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_client import PLCClient


CHANNELS = ("N", "P", "K")


def _load_config(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: dict(data.get(key, {})) for key in CHANNELS}


def _set_channel_value(channels: dict[str, dict], key: str, field: str, value):
    channels.setdefault(key, {})[field] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Write N/P/K fertilizer channel config into PLC DB1.")
    parser.add_argument("--config", default=str(ROOT / "config" / "fertilizer_channels.json"))
    parser.add_argument("--n-ratio", type=float, default=None)
    parser.add_argument("--p-ratio", type=float, default=None)
    parser.add_argument("--k-ratio", type=float, default=None)
    parser.add_argument("--n-max", type=float, default=None)
    parser.add_argument("--p-max", type=float, default=None)
    parser.add_argument("--k-max", type=float, default=None)
    parser.add_argument("--disable-n", action="store_true")
    parser.add_argument("--disable-p", action="store_true")
    parser.add_argument("--disable-k", action="store_true")
    parser.add_argument("--normalize-ratios", action="store_true", help="Normalize enabled channel ratios to sum to 1.")
    args = parser.parse_args()

    channels = _load_config(Path(args.config))

    overrides = [
        ("N", "ratio", args.n_ratio),
        ("P", "ratio", args.p_ratio),
        ("K", "ratio", args.k_ratio),
        ("N", "max_flow", args.n_max),
        ("P", "max_flow", args.p_max),
        ("K", "max_flow", args.k_max),
    ]
    for key, field, value in overrides:
        if value is not None:
            _set_channel_value(channels, key, field, value)

    if args.disable_n:
        _set_channel_value(channels, "N", "enable", False)
    if args.disable_p:
        _set_channel_value(channels, "P", "enable", False)
    if args.disable_k:
        _set_channel_value(channels, "K", "enable", False)

    if args.normalize_ratios:
        total = sum(float(channels[ch].get("ratio", 0.0)) for ch in CHANNELS if channels[ch].get("enable", True))
        if total > 0.0:
            for ch in CHANNELS:
                if channels[ch].get("enable", True):
                    channels[ch]["ratio"] = float(channels[ch].get("ratio", 0.0)) / total
                else:
                    channels[ch]["ratio"] = 0.0

    plc = PLCClient()
    if not plc.connect():
        raise SystemExit("PLC connection failed.")

    try:
        if not plc.write_fertilizer_channels(channels):
            raise SystemExit("Fertilizer channel write failed.")

        state = plc.read_state() or {}
        print("Fertilizer channels written to PLC DB1:")
        for ch in CHANNELS:
            prefix = ch
            print(
                f"  {ch}: enable={state.get(prefix + '_Enable', channels[ch].get('enable'))}, "
                f"ratio={state.get(prefix + '_Ratio', channels[ch].get('ratio'))}, "
                f"max={state.get(prefix + '_Max', channels[ch].get('max_flow'))}, "
                f"Kp={state.get('Kp_' + prefix + '_Set', channels[ch].get('kp'))}, "
                f"Ki={state.get('Ki_' + prefix + '_Set', channels[ch].get('ki'))}, "
                f"Kd={state.get('Kd_' + prefix + '_Set', channels[ch].get('kd'))}"
            )
        print(
            "  outputs: "
            f"q_n={state.get('q_n_cmd', 0.0):.4f}, "
            f"q_p={state.get('q_p_cmd', 0.0):.4f}, "
            f"q_k={state.get('q_k_cmd', 0.0):.4f}"
        )
    finally:
        plc.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
