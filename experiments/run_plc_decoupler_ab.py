"""Run a guarded PLCSIM A/B comparison for local EC/pH decoupling.

Each weight repeats the same EC-only and pH-only target step from the same
initial process state.  The script writes one validated local matrix to DB1,
but never writes the Python schedule to the PLC and always finishes in
standby with the emergency stop asserted.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mixing_tank import MixingTank
from pipe_dynamics import PipeDynamics
from plc_client import PLCClient
from plc_control.ab_validation import evaluate_ab_summary, load_ab_criteria
from plc_control.gain_schedule import load_gain_schedule


STAGE_INDEX = {"INI": 0, "DEV": 1, "MID": 2, "LATE": 3}
WEIGHTS = (0.0, 0.1, 0.25, 0.5)


def _point(schedule: dict, point_id: str) -> dict:
    for point in schedule.get("stages", {}).get("MID", {}).get("points", []):
        if point.get("id") == point_id and point.get("valid", False):
            return point
    raise ValueError(f"validated MID gain point not found: {point_id}")


def _state_float(state: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(state.get(key, default))
    except (TypeError, ValueError):
        return float(default)


class ABExperiment:
    def __init__(self, args: argparse.Namespace, point: dict, out_dir: Path):
        self.args = args
        self.point = point
        self.out_dir = out_dir
        self.plc = PLCClient(cycle_s=args.plc_wait_s)
        self.rows: list[dict] = []

    def _prepare(self, weight: float, ec: float, ph: float) -> None:
        if not self.plc.connect():
            raise RuntimeError("PLC/PLCSIM connection failed")
        if not self.plc.write_emergency_stop(False):
            raise RuntimeError("could not clear Emergency_Stop")
        if not self.plc.write_remote_auto_mode():
            raise RuntimeError("could not select remote automatic mode")
        if not self.plc.write_growth_stage(STAGE_INDEX["MID"]):
            raise RuntimeError("could not set MID growth stage")
        if not self.plc.write_active_gain_matrix(self.point):
            raise RuntimeError("could not write validated active gain matrix")
        if not self.plc.write_decoupler_weight(weight):
            raise RuntimeError("could not write Decoupler_Weight")
        if not self.plc.write_water_command(True, self.args.q_w, self.args.pressure_set):
            raise RuntimeError("could not enable carrier-water command")
        if not self.plc.write_water_feedback(self.args.q_w, self.args.pressure_set, 50.0, True):
            raise RuntimeError("could not provide carrier-water feedback")
        if not self.plc.write_system_alarm_reset(True):
            raise RuntimeError("could not acknowledge commissioning alarm")
        if not self.plc.write_setpoints(ec, ph, self.args.ec_initial, self.args.ph_initial, True):
            raise RuntimeError("could not establish remote setpoint frame")
        time.sleep(max(self.args.plc_wait_s * 2.0, 0.2))
        self.plc.write_system_alarm_reset(False)
        if not self.plc.set_decoupler_enabled(weight > 0.0):
            raise RuntimeError("could not set decoupler enable state")
        time.sleep(max(self.args.plc_wait_s * 2.0, 0.2))
        state = self.plc.read_state()
        if not state.get("Remote_Comms_OK", False):
            raise RuntimeError(f"remote communication is not healthy: {state}")
        if weight > 0.0 and not state.get("Decoupler_Valid", False):
            raise RuntimeError(f"PLC rejected validated matrix: {state}")
        if bool(state.get("Decoupler_Enable", False)) != (weight > 0.0):
            raise RuntimeError("PLC did not retain requested decoupler enable state")

    def _finish_case(self) -> None:
        self.plc.set_decoupler_enabled(False)
        self.plc.write_decoupler_weight(0.0)
        self.plc.write_setpoints(1.5, 5.9, self.args.ec_initial, self.args.ph_initial, False)
        self.plc.write_water_command(False, 0.0, 0.0)
        self.plc.write_water_feedback(0.0, 0.0, 0.0, False)

    def run_case(self, weight: float, disturbance: str) -> None:
        base_ec, base_ph = 1.5, 5.9
        step_ec = base_ec + (self.args.ec_step if disturbance == "ec" else 0.0)
        step_ph = base_ph + (self.args.ph_step if disturbance == "ph" else 0.0)
        tank = MixingTank()
        pipe = PipeDynamics(
            tau=self.args.pipe_tau_min,
            T=self.args.pipe_t_min,
            dt=max(self.args.sim_step_s / 60.0, 1e-6),
        )
        ec_actual, ph_actual = self.args.ec_initial, self.args.ph_initial
        self._prepare(weight, base_ec, base_ph)
        try:
            total_duration = self.args.warmup_s + self.args.duration_s
            total = max(1, int(round(total_duration / self.args.sim_step_s)))
            step_at = self.args.warmup_s
            for index in range(total):
                time_s = index * self.args.sim_step_s
                ec_set = step_ec if time_s >= step_at else base_ec
                ph_set = step_ph if time_s >= step_at else base_ph
                if not self.plc.write_setpoints(ec_set, ph_set, ec_actual, ph_actual, True):
                    raise RuntimeError("setpoint/feedback write failed")
                time.sleep(max(self.args.plc_wait_s, 0.0))
                state = self.plc.read_state()
                if not state.get("Remote_Comms_OK", False):
                    raise RuntimeError("remote communication dropped during A/B test")
                if state.get("System_Alarm_Light", False):
                    raise RuntimeError("PLC alarm became active during A/B test")
                q_f = _state_float(state, "q_f_cmd")
                q_a = _state_float(state, "q_a_cmd")
                ec_tank, ph_tank = tank.step(q_f, q_a, self.args.q_w)
                ec_actual, ph_actual = pipe.step(ec_tank, ph_tank)
                q_f_max = _state_float(state, "q_f_max", 10.0)
                q_a_max = _state_float(state, "q_a_max", 4.0)
                self.rows.append({
                    "weight": weight,
                    "disturbance": disturbance,
                    "time_s": time_s,
                    "ec_set": ec_set,
                    "ph_set": ph_set,
                    "active_ec_sp": _state_float(state, "Active_EC_SP", ec_set),
                    "active_ph_sp": _state_float(state, "Active_pH_SP", ph_set),
                    "setpoint_protection": bool(state.get("Setpoint_Protection_Active", False)),
                    "ec_actual": ec_actual,
                    "ph_actual": ph_actual,
                    "q_f_cmd": q_f,
                    "q_a_cmd": q_a,
                    "q_f_limited": bool(state.get("q_f_limited", False)),
                    "q_a_limited": bool(state.get("q_a_limited", False)),
                    "q_f_saturated": q_f <= 1e-6 or q_f >= q_f_max - 1e-6,
                    "q_a_saturated": q_a <= 1e-6 or q_a >= q_a_max - 1e-6,
                    "alarm": bool(state.get("System_Alarm_Light", False)),
                    "remote_comms_ok": bool(state.get("Remote_Comms_OK", False)),
                    "decoupler_enable": bool(state.get("Decoupler_Enable", False)),
                    "decoupler_valid": bool(state.get("Decoupler_Valid", False)),
                    "decoupler_determinant": _state_float(state, "Decoupler_Determinant"),
                })
        finally:
            self._finish_case()
            self.plc.disconnect()


def summarize(rows: list[dict], args: argparse.Namespace) -> dict:
    results = []
    for weight in sorted({float(row["weight"]) for row in rows}):
        for disturbance in ("ec", "ph"):
            selected = [row for row in rows if row["weight"] == weight and row["disturbance"] == disturbance]
            post = [row for row in selected if row["time_s"] >= args.warmup_s]
            if not post:
                continue
            cross = "ph_actual" if disturbance == "ec" else "ec_actual"
            cross_set = "ph_set" if disturbance == "ec" else "ec_set"
            results.append({
                "weight": weight,
                "disturbance": disturbance,
                "ec_mae": float(np.mean([abs(row["ec_actual"] - row["ec_set"]) for row in post])),
                "ph_mae": float(np.mean([abs(row["ph_actual"] - row["ph_set"]) for row in post])),
                "cross_coupling_peak": float(max(abs(row[cross] - row[cross_set]) for row in post)),
                "q_f_saturation_count": int(sum(row["q_f_saturated"] or row["q_f_limited"] for row in selected)),
                "q_a_saturation_count": int(sum(row["q_a_saturated"] or row["q_a_limited"] for row in selected)),
                "q_f_rms": float(np.sqrt(np.mean([row["q_f_cmd"] ** 2 for row in post]))),
                "q_a_rms": float(np.sqrt(np.mean([row["q_a_cmd"] ** 2 for row in post]))),
                "alarm_count": int(sum(row["alarm"] for row in selected)),
                "communication_failures": int(sum(not row["remote_comms_ok"] for row in selected)),
                "setpoint_protection_count": int(sum(row["setpoint_protection"] for row in selected)),
                "output_direction_ok": bool(all(np.isfinite([row["q_f_cmd"], row["q_a_cmd"]]).all() for row in selected)),
                "decoupler_valid_all": bool(all(row["decoupler_valid"] for row in selected)),
            })
    by_weight = {}
    for row in results:
        by_weight.setdefault(str(row["weight"]), []).append(row)
    return {"weights": results, "by_weight": by_weight, "decoupler_enabled_during_test": any(row["decoupler_enable"] for row in rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run guarded PLCSIM A/B decoupler validation.")
    parser.add_argument("--apply", action="store_true", help="Allow PLCSIM writes.")
    parser.add_argument("--point", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--weights", nargs="+", type=float, default=list(WEIGHTS))
    parser.add_argument("--duration-s", type=float, default=600.0,
                        help="Response duration after the baseline warm-up.")
    parser.add_argument("--warmup-s", type=float, default=600.0,
                        help="Baseline warm-up before applying the target step.")
    parser.add_argument("--sim-step-s", type=float, default=10.0)
    parser.add_argument("--plc-wait-s", type=float, default=0.1)
    parser.add_argument("--ec-step", type=float, default=0.15)
    parser.add_argument("--ph-step", type=float, default=0.15,
                        help="Positive pH step; keep both targets inside PLC safety limits.")
    parser.add_argument("--q-w", type=float, default=136.0)
    parser.add_argument("--pressure-set", type=float, default=1.0)
    parser.add_argument("--ec-initial", type=float, default=1.35)
    parser.add_argument("--ph-initial", type=float, default=6.0)
    parser.add_argument("--pipe-tau-min", type=float, default=None)
    parser.add_argument("--pipe-t-min", type=float, default=None)
    args = parser.parse_args()
    if not args.apply:
        parser.error("A/B live mode is write-protected; pass --apply")
    if not args.weights or any(weight < 0.0 or weight > 1.0 for weight in args.weights):
        parser.error("weights must be within [0, 1]")
    if args.duration_s <= 0.0 or args.warmup_s <= 0.0:
        parser.error("duration and warm-up must be positive")

    schedule = load_gain_schedule(ROOT / "config" / "gain_schedule.yaml")
    point = _point(schedule, args.point)
    out_dir = ROOT / "results" / "plc_decoupler_ab" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    experiment = ABExperiment(args, point, out_dir)
    try:
        for weight in args.weights:
            for disturbance in ("ec", "ph"):
                logging.info("A/B case weight=%.2f disturbance=%s", weight, disturbance)
                experiment.run_case(float(weight), disturbance)
    except Exception:
        logging.exception("A/B validation stopped")
        try:
            experiment.plc.set_decoupler_enabled(False)
            experiment.plc.write_decoupler_weight(0.0)
            experiment.plc.write_standby()
            experiment.plc.write_emergency_stop(True)
        except Exception:
            logging.exception("failed to force final safe state")
        finally:
            experiment.plc.disconnect()
        return 2

    raw_path = out_dir / "ab_results.csv"
    with raw_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(experiment.rows[0]))
        writer.writeheader()
        writer.writerows(experiment.rows)
    summary = summarize(experiment.rows, args)
    criteria = load_ab_criteria(ROOT / "config" / "decoupler_ab.yaml")
    summary["verdict"] = evaluate_ab_summary(summary, criteria)
    summary["point"] = {key: point[key] for key in ("id", "ec", "ph", "q_f", "q_a", "gains", "determinant", "condition_number")}
    summary["raw_samples"] = len(experiment.rows)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    experiment.plc.connect()
    experiment.plc.write_standby()
    experiment.plc.write_emergency_stop(True)
    experiment.plc.disconnect()
    print(f"Saved A/B results: {out_dir}")
    print(json.dumps(summary["weights"], indent=2))
    print(json.dumps(summary["verdict"], indent=2))
    print("Final PLC state requested: standby + Emergency_Stop=True; decoupler disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
