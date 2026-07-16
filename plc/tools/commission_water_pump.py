"""Commission the DB1 main-water-pump channel against PLCSIM.

The script is simulation-only by default. It drives the DB command/feedback
contract without touching physical I/O and always leaves Water_Enable false.
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
from water_pump import WaterPump


def _water_summary(state: dict) -> str:
    return (
        f"run_cmd={bool(state.get('Water_Pump_Run_CMD', False))} "
        f"running={bool(state.get('Water_Pump_Running', False))} "
        f"Q={float(state.get('Qw_Actual', 0.0)):.2f} L/min "
        f"P={float(state.get('Pressure_Actual', 0.0)):.3f} bar "
        f"speed_cmd={float(state.get('Water_Pump_Speed_CMD', 0.0)):.1f}% "
        f"flow_ok={bool(state.get('Water_Flow_OK', False))} "
        f"fault={bool(state.get('Water_Pump_Fault', False))}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Commission the PLCSIM water-pump DB contract.")
    parser.add_argument("--q-set", type=float, default=80.0)
    parser.add_argument("--pressure-set", type=float, default=1.8)
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--cycle-s", type=float, default=0.20)
    parser.add_argument(
        "--allow-field",
        action="store_true",
        help="Allow execution when deployment.profile=field_plc. Use only during controlled commissioning.",
    )
    args = parser.parse_args()

    profile = load_config().deployment().get("profile", "simulation_plc")
    if profile == "field_plc" and not args.allow_field:
        print("Refusing to command a field PLC without --allow-field.")
        return 2

    plc = PLCClient()
    pump = WaterPump(q_set_l_min=args.q_set)
    pump.set_command(enabled=False, q_set_l_min=args.q_set, reset_volume=True)

    if not plc.connect():
        print("PLC/PLCSIM connection failed. Confirm CPU RUN, download, IP, and NetToPLCsim station state.")
        return 3

    passed_run_command = False
    passed_flow_ok = False
    try:
        initial = plc.read_state()
        if not initial or not initial.get("water_schema_available", False):
            print("Water-pump DB1 extension is not readable. Recompile and download the latest DB1.")
            return 4
        print("Initial:", _water_summary(initial))

        # Establish a known safe baseline and pulse the volume reset for one PLC cycle.
        plc.write_water_command(
            enabled=False,
            q_w_set=args.q_set,
            pressure_set=args.pressure_set,
            volume_set=0.0,
            control_mode=0,
            reset_volume=True,
        )
        plc.write_water_feedback(0.0, 0.0, 0.0, False)
        time.sleep(args.cycle_s)

        plc.write_water_command(
            enabled=True,
            q_w_set=args.q_set,
            pressure_set=args.pressure_set,
            volume_set=0.0,
            control_mode=0,
            reset_volume=False,
        )

        for cycle in range(1, max(args.cycles, 1) + 1):
            state = plc.read_state() or {}
            run_command = bool(state.get("Water_Pump_Run_CMD", False))
            passed_run_command = passed_run_command or run_command
            pump.set_command(enabled=run_command, q_set_l_min=args.q_set, mode="flow")
            # Compressed process time keeps PLCSIM commissioning short.
            simulated = pump.step(0.5)
            plc.write_water_feedback(
                q_w_actual=simulated.q_actual_l_min,
                pressure_actual=simulated.pressure_actual_bar,
                speed_actual=simulated.speed_percent,
                running=simulated.running,
            )
            time.sleep(args.cycle_s)
            observed = plc.read_state() or {}
            passed_flow_ok = passed_flow_ok or bool(observed.get("Water_Flow_OK", False))
            print(f"Cycle {cycle:02d}:", _water_summary(observed))
            if bool(observed.get("Water_Pump_Fault", False)):
                print("Water-pump fault detected; stopping commissioning.")
                break

        if not passed_run_command:
            print("FAIL: PLC never issued Water_Pump_Run_CMD.")
            return 5
        if not passed_flow_ok:
            print("FAIL: Water_Flow_OK never became true.")
            return 6
        print("PASS: run command, simulated flow feedback, and Water_Flow_OK were verified.")
        return 0
    finally:
        try:
            plc.write_water_command(
                enabled=False,
                q_w_set=args.q_set,
                pressure_set=args.pressure_set,
                volume_set=0.0,
                control_mode=0,
                reset_volume=False,
            )
            plc.write_water_feedback(0.0, 0.0, 0.0, False)
        finally:
            plc.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
