from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plc_client import PLCClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Low-flow PLC manual-mode smoke test. Use --apply to write DB1."
    )
    parser.add_argument("--apply", action="store_true", help="Actually write Emergency_Stop/Manual_Mode/manual setpoints.")
    parser.add_argument("--hold-s", type=float, default=3.0, help="Seconds to hold manual mode before reading back.")
    parser.add_argument("--q-f", type=float, default=0.2, help="Manual fertilizer flow, L/min.")
    parser.add_argument("--q-a", type=float, default=0.0, help="Manual acid flow, L/min.")
    parser.add_argument("--q-n", type=float, default=0.0, help="Manual N flow, L/min.")
    parser.add_argument("--q-p", type=float, default=0.0, help="Manual P flow, L/min.")
    parser.add_argument("--q-k", type=float, default=0.0, help="Manual K flow, L/min.")
    parser.add_argument("--leave-enabled", action="store_true", help="Do not disable Manual_Mode at the end.")
    return parser.parse_args()


def print_state(title: str, state: dict) -> None:
    keys = [
        "Manual_Mode", "Auto_Mode", "Emergency_Stop", "Manual_Active", "Auto_Active",
        "Manual_q_f_Set", "Manual_q_a_Set", "Manual_q_n_Set", "Manual_q_p_Set", "Manual_q_k_Set",
        "q_f_cmd", "q_a_cmd", "q_n_cmd", "q_p_cmd", "q_k_cmd",
        "AQ_Valve_F_Raw", "AQ_Valve_A_Raw", "AQ_Valve_N_Raw", "AQ_Valve_P_Raw", "AQ_Valve_K_Raw",
        "System_Alarm_Light",
    ]
    print(f"\n[{title}]")
    for key in keys:
        if key in state:
            print(f"{key}: {state[key]}")


def main() -> int:
    args = parse_args()
    plc = PLCClient()

    if not plc.connect():
        return 2

    try:
        print_state("initial", plc.read_state())

        if not args.apply:
            print("\nDry run only. Re-run with --apply after pumps/valves are safe to energize.")
            return 0

        if not plc.write_emergency_stop(False):
            return 3

        if not plc.write_manual_mode(
            True,
            q_f=args.q_f,
            q_a=args.q_a,
            q_n=args.q_n,
            q_p=args.q_p,
            q_k=args.q_k,
        ):
            return 4

        time.sleep(max(args.hold_s, 0.0))
        print_state("manual enabled", plc.read_state())

        if not args.leave_enabled:
            if not plc.write_manual_mode(False):
                return 5
            time.sleep(0.5)
            print_state("manual disabled", plc.read_state())

    finally:
        plc.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
