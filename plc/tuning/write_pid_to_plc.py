r"""把 PID 参数写入 PLC DB1。

用法 1：从粗调结果 summary.json 写入 best 参数

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\write_pid_to_plc.py `
     --summary ".\results\pid_tuning\时间戳\summary.json"

用法 2：手动指定一组参数

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\write_pid_to_plc.py `
     --kp-ec 0.8 --ki-ec 0.002 --kd-ec 0.0 `
     --kp-ph 1.2 --ki-ph 0.005 --kd-ph 0.0 `
     --ec-trim-band 0.10 --ph-trim-band 0.15
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


def _load_params_from_summary(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    best = data.get("best", data)
    required = ["kp_ec", "ki_ec", "kd_ec", "kp_ph", "ki_ph", "kd_ph"]
    missing = [name for name in required if name not in best]
    if missing:
        raise KeyError(f"summary best is missing PID keys: {missing}")
    return {name: float(best[name]) for name in required}


def main() -> int:
    parser = argparse.ArgumentParser(description="Write PID gains into PLC DB1.")
    parser.add_argument("--summary", default=None, help="Path to pid_tuning summary.json. Uses its best candidate.")
    parser.add_argument("--kp-ec", type=float, default=None)
    parser.add_argument("--ki-ec", type=float, default=None)
    parser.add_argument("--kd-ec", type=float, default=None)
    parser.add_argument("--kp-ph", type=float, default=None)
    parser.add_argument("--ki-ph", type=float, default=None)
    parser.add_argument("--kd-ph", type=float, default=None)
    parser.add_argument(
        "--ec-trim-band",
        type=float,
        default=None,
        help="Optional PLC fine-trim window around EC feedforward, e.g. 0.10 for +/-10%.",
    )
    parser.add_argument(
        "--ph-trim-band",
        type=float,
        default=None,
        help="Optional PLC fine-trim window around pH feedforward, e.g. 0.08 for +/-8%.",
    )
    args = parser.parse_args()

    if args.summary:
        params = _load_params_from_summary(Path(args.summary))
    else:
        values = {
            "kp_ec": args.kp_ec,
            "ki_ec": args.ki_ec,
            "kd_ec": args.kd_ec,
            "kp_ph": args.kp_ph,
            "ki_ph": args.ki_ph,
            "kd_ph": args.kd_ph,
        }
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise SystemExit(f"Missing PID args: {missing}. Use --summary or provide all six gains.")
        params = {name: float(value) for name, value in values.items()}

    plc = PLCClient()
    if not plc.connect():
        raise SystemExit("PLC connection failed.")

    try:
        ok = plc.write_pid_params(
            kp_ec=params["kp_ec"],
            ki_ec=params["ki_ec"],
            kd_ec=params["kd_ec"],
            kp_ph=params["kp_ph"],
            ki_ph=params["ki_ph"],
            kd_ph=params["kd_ph"],
            ec_trim_band=args.ec_trim_band,
            ph_trim_band=args.ph_trim_band,
        )
        if not ok:
            raise SystemExit("PID write failed.")

        state = plc.read_state()
        print("PID params written to PLC DB1:")
        print(
            f"  EC: Kp={state.get('Kp_EC_Set', params['kp_ec']):.6f}, "
            f"Ki={state.get('Ki_EC_Set', params['ki_ec']):.6f}, "
            f"Kd={state.get('Kd_EC_Set', params['kd_ec']):.6f}"
        )
        print(
            f"  pH: Kp={state.get('Kp_pH_Set', params['kp_ph']):.6f}, "
            f"Ki={state.get('Ki_pH_Set', params['ki_ph']):.6f}, "
            f"Kd={state.get('Kd_pH_Set', params['kd_ph']):.6f}"
        )
        if args.ec_trim_band is not None or args.ph_trim_band is not None:
            print(
                "  Fine trim: "
                f"EC={args.ec_trim_band if args.ec_trim_band is not None else 'unchanged'}, "
                f"pH={args.ph_trim_band if args.ph_trim_band is not None else 'unchanged'}"
            )
    finally:
        plc.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
