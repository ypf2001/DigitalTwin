"""Verify the PLC irrigation batch states against PLCSIM only.

The test simulates main-water feedback and leaves all commands in a safe stop
state on exit. It never enables real field hardware.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from plc_client import PLCClient


PHASE_NAMES = {
    0: "idle",
    1: "pre_flush",
    2: "fertigating",
    3: "post_flush",
    4: "complete",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Commission pre/fertigate/post batch states on PLCSIM.")
    parser.add_argument("--volume-l", type=float, default=3.0)
    parser.add_argument("--q-l-min", type=float, default=80.0)
    parser.add_argument("--pre-ratio", type=float, default=0.20)
    parser.add_argument("--post-ratio", type=float, default=0.20)
    parser.add_argument("--cycle-s", type=float, default=0.12)
    parser.add_argument("--max-cycles", type=int, default=80)
    parser.add_argument("--allow-field", action="store_true")
    args = parser.parse_args()

    profile = load_config().deployment().get("profile", "simulation_plc")
    if profile != "simulation_plc" and not args.allow_field:
        print(f"Refusing batch commissioning for deployment.profile={profile!r}.")
        return 2
    if args.volume_l <= 0.0 or args.q_l_min <= 0.0:
        raise ValueError("volume-l and q-l-min must be positive")
    if args.pre_ratio < 0.0 or args.post_ratio < 0.0 or args.pre_ratio + args.post_ratio > 1.0:
        raise ValueError("flush ratios must be nonnegative and sum to no more than 1")

    plc = PLCClient()
    seen: set[int] = set()
    active_during_fertigation = False
    try:
        if not plc.connect():
            print("PLC/PLCSIM connection failed.")
            return 3
        initial = plc.read_state() or {}
        if not initial.get("water_batch_schema_available", False):
            print("Irrigation batch DB1 extension is unavailable. Compile/download the latest PLC software.")
            return 4

        plc.write_water_command(
            enabled=False,
            q_w_set=args.q_l_min,
            pressure_set=1.8,
            volume_set=args.volume_l,
            control_mode=0,
            pre_flush_ratio=args.pre_ratio,
            post_flush_ratio=args.post_ratio,
            reset_volume=True,
        )
        plc.write_water_feedback(0.0, 0.0, 0.0, False)
        time.sleep(args.cycle_s)
        plc.write_water_command(
            enabled=True,
            q_w_set=args.q_l_min,
            pressure_set=1.8,
            volume_set=args.volume_l,
            control_mode=0,
            pre_flush_ratio=args.pre_ratio,
            post_flush_ratio=args.post_ratio,
            reset_volume=False,
        )

        for cycle in range(1, max(args.max_cycles, 1) + 1):
            plc.write_water_feedback(args.q_l_min, 0.5, 45.0, True)
            time.sleep(args.cycle_s)
            state = plc.read_state() or {}
            phase = int(state.get("Water_Batch_Phase", -1))
            active = bool(state.get("Batch_Fertigation_Active", False))
            seen.add(phase)
            active_during_fertigation = active_during_fertigation or (phase == 2 and active)
            print(
                f"Cycle {cycle:02d}: phase={PHASE_NAMES.get(phase, 'unknown')} "
                f"volume={float(state.get('Water_Volume_Actual', 0.0)):.3f}/"
                f"{float(state.get('Water_Volume_SP', 0.0)):.3f} L "
                f"fertigation_active={active}",
                flush=True,
            )
            if bool(state.get("Water_Volume_Complete", False)):
                break

        expected = {1, 2, 3, 4}
        if not expected.issubset(seen) or not active_during_fertigation:
            print(f"FAIL: expected phases {sorted(expected)}, observed {sorted(seen)}")
            return 5
        print("PASS: pre-flush, fertigation permission, post-flush, and completion were verified.")
        return 0
    finally:
        try:
            plc.write_water_command(
                enabled=False,
                q_w_set=args.q_l_min,
                pressure_set=1.8,
                volume_set=0.0,
                control_mode=0,
                reset_volume=False,
            )
            plc.write_water_feedback(0.0, 0.0, 0.0, False)
        finally:
            plc.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
