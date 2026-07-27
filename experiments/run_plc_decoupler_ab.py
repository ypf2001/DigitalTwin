"""Run the gated E4 acid-to-EC constrained-decoupling campaign."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_client import PLCClient
from plc_control.constrained_ab import evaluate_constrained_ab, summarize_constrained_rows
from plc_control.gain_schedule import load_gain_schedule
from plc_control.mimo_fopdt import MIMOFOPDTParameters, MIMOFOPDTPlant


POINT_INDEX = {"low": 0, "medium": 1, "high": 2}
DISTURBANCES = ("ph_high", "ec_step", "ph_low")


def _f(state: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(state.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _load_e3(path: Path) -> tuple[dict, dict, str]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    if not summary.get("e3_passed", False):
        raise ValueError(f"E4 requires e3_passed=true: {path}")
    if int(summary.get("repetitions_required", 0)) != 3:
        raise ValueError("E4 requires the formal three-repetition E3 contract")
    schedule_path = path.with_name("gain_schedule.yaml")
    schedule = load_gain_schedule(schedule_path)
    if not schedule.get("e3_passed", False) or not schedule.get("enabled", False):
        raise ValueError(f"E3 gain schedule is not deployable: {schedule_path}")
    source = str(summary.get("metadata", {}).get("evidence_label", schedule.get("source", "unknown")))
    return summary, schedule, source


def _criteria(path: Path, source: str) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result = deepcopy(raw.get("ab_validation", raw))
    precision = result["measured" if source == "measured" else "hil"]
    result.update(precision)
    return result


def _point(schedule: dict, point_id: str) -> dict:
    for point in schedule.get("stages", {}).get("MID", {}).get("points", []):
        if point.get("id") == point_id and point.get("valid", False):
            return point
    raise ValueError(f"validated E3 point missing: {point_id}")


class E4Campaign:
    def __init__(self, args: argparse.Namespace, schedule: dict, criteria: dict, out_dir: Path):
        self.args = args
        self.schedule = schedule
        self.criteria = criteria
        self.out_dir = out_dir
        self.plc = PLCClient(cycle_s=args.plc_wait_s)
        self.rows: list[dict] = []

    def connect_and_load(self) -> None:
        if not self.plc.connect():
            raise RuntimeError("PLC/PLCSIM connection failed")
        if not self.plc.write_emergency_stop(False):
            raise RuntimeError("could not clear Emergency_Stop")
        if not self.plc.write_gain_schedule_table(
            self.schedule, parameter_version=self.args.parameter_version,
            pulse_flow=self.args.pulse_flow,
        ):
            raise RuntimeError("PLC rejected the passed E3 gain schedule")
        if not self.plc.write_controller_mode(2):
            raise RuntimeError("could not select Controller_Mode=2")
        if not self.plc.write_ph_pulse_parameters(
            self.args.pulse_flow, self.args.pulse_on_s, self.args.pulse_off_s
        ):
            raise RuntimeError("could not write E4 pH pulse parameters")
        if not self.plc.set_e4_test_enabled(True):
            raise RuntimeError("could not open the guarded E4 commissioning gate")
        if not self.plc.set_e4_compressed_time(
            self.args.plant == "plcsim", self.args.sim_step_s
        ):
            raise RuntimeError("could not configure the E4 PLCSIM time base")

    def finish(self, approved: bool) -> bool:
        approval_written = False
        try:
            self.plc.set_decoupler_enabled(False)
            self.plc.write_decoupler_weight(0.0)
            self.plc.set_gain_point_override(None)
            if self.args.commit_approval and self.args.plant == "hardware":
                approval_written = self.plc.write_e4_approval(approved)
            else:
                self.plc.write_e4_approval(False)
            self.plc.write_standby()
            self.plc.write_water_command(False, 0.0, 0.0)
            if self.args.plant == "plcsim":
                self.plc.write_water_feedback(0.0, 0.0, 0.0, False)
            self.plc.write_emergency_stop(True)
        finally:
            self.plc.disconnect()
        return approval_written

    def _prepare_case(self, point: dict, weight: float, ec: float, ph: float,
                      base_ec: float) -> None:
        point_index = POINT_INDEX[str(point["id"])]
        if not self.plc.set_gain_point_override(point_index):
            raise RuntimeError("could not lock the E4 gain point")
        if not self.plc.write_remote_auto_mode():
            raise RuntimeError("could not enter remote automatic mode")
        if not self.plc.write_growth_stage(2):
            raise RuntimeError("could not select MID stage for E4")
        if not self.plc.write_decoupler_weight(weight):
            raise RuntimeError("could not write E4 decoupler weight")
        if not self.plc.write_water_command(True, self.args.q_w, self.args.pressure_set):
            raise RuntimeError("could not start E4 carrier water")
        if self.args.plant == "plcsim" and not self.plc.write_water_feedback(
            self.args.q_w, self.args.pressure_set, 50.0, True
        ):
            raise RuntimeError("could not provide PLCSIM water feedback")
        self.plc.write_system_alarm_reset(True)
        self.plc.write_residual_command(
            1.0, float(base_ec) - 1.5, 1.5, ec, ph,
            ph_band_low=self.criteria["ph_band_low"],
            ph_band_high=self.criteria["ph_band_high"],
            recipe_id=2, controller_mode=2, sac_enable=True,
        )
        time.sleep(max(0.3, self.args.plc_wait_s * 3.0))
        self.plc.write_system_alarm_reset(False)
        state = {}
        for _ in range(30):
            # Gain-point activation can take several PLC scans.  Keep the
            # commissioning heartbeat alive while waiting; a read-only wait
            # lets the PLC watchdog revoke remote authority before the point
            # switch can be verified.
            if not self.plc.write_feedback(ec, ph, sac_enable=True):
                raise RuntimeError("E4 heartbeat handshake failed")
            time.sleep(max(self.args.plc_wait_s, 0.1))
            state = self.plc.read_state()
            if (
                state.get("Remote_Comms_OK", False)
                and state.get("Auto_Active", False)
                and state.get("Gain_Schedule_Valid", False)
                and int(state.get("Active_Gain_Point", -1)) == point_index
                and state.get("Decoupler_Valid", False)
            ):
                break
        if (
            not state.get("Remote_Comms_OK", False)
            or not state.get("Auto_Active", False)
            or not state.get("Gain_Schedule_Valid", False)
            or int(state.get("Active_Gain_Point", -1)) != point_index
        ):
            raise RuntimeError(f"PLC did not activate E3 point {point['id']}: {state}")
        if not self.plc.set_decoupler_enabled(weight > 0.0):
            raise RuntimeError("could not apply E4 decoupler state")

    def _finish_case(self) -> None:
        self.plc.set_decoupler_enabled(False)
        self.plc.write_decoupler_weight(0.0)
        self.plc.write_standby()
        # Give the PLC at least one scan with SAC_Enable=FALSE so integrals,
        # filters and acid-pulse state are reset before the next paired case.
        time.sleep(max(self.args.plc_wait_s, 0.2))
        state = self.plc.read_state()
        if state.get("SAC_Enable", True) or abs(_f(state, "q_a_cmd")) > 1e-6:
            raise RuntimeError("PLC did not reset between E4 cases")

    def run_case(self, point_id: str, weight: float, disturbance: str, repetition: int) -> None:
        point = _point(self.schedule, point_id)
        # The residual-action contract is bounded to +/-0.15 around MID=1.5.
        # Low keeps its local 1.4 target; medium/high use 1.5 so the +0.15 E4
        # step remains inside the same deployable PLC interface.
        base_ec = min(float(point["ec"]), 1.5)
        gains = point["gains"]
        plant = None
        if self.args.plant == "plcsim":
            plant = MIMOFOPDTPlant(MIMOFOPDTParameters(
                float(gains["g_ec_f"]), float(gains["g_ec_a"]),
                float(gains["g_ph_f"]), float(gains["g_ph_a"]),
                float(point["delay_s"]), float(point["tau_s"]), float(point["tau_s"]),
            ), self.args.sim_step_s)
            q_f_nominal = float(point["q_f"]) + (
                base_ec - float(point["ec"])
            ) / float(gains["g_ec_f"])
            plant.reset(q_f_nominal, 0.0, base_ec, self.args.ph_initial)
        ec_actual, ph_actual = base_ec, self.args.ph_initial
        self._prepare_case(point, weight, ec_actual, ph_actual, base_ec)
        injected = False
        external_confirmed = self.args.plant == "plcsim"
        try:
            total_s = self.args.warmup_s + self.args.duration_s
            total = max(1, int(round(total_s / self.args.sim_step_s)))
            for index in range(total):
                time_s = index * self.args.sim_step_s
                ec_set = base_ec
                if disturbance == "ec_step" and time_s >= self.args.warmup_s:
                    ec_set += float(self.criteria["ec_step_ds_m"])
                disturbance_held = (
                    disturbance != "ec_step"
                    and self.args.warmup_s <= time_s < self.args.warmup_s + self.args.disturbance_hold_s
                )
                if time_s >= self.args.warmup_s and not injected and disturbance != "ec_step":
                    if self.args.plant == "plcsim":
                        target = float(self.criteria[
                            "ph_high_disturbance" if disturbance == "ph_high" else "ph_low_disturbance"
                        ])
                        assert plant is not None
                        ec_actual, ph_actual = plant.inject_output(ph_delta=target - ph_actual)
                        external_confirmed = True
                    else:
                        logging.warning("Apply the external %s disturbance now", disturbance)
                    injected = True
                elif disturbance_held and self.args.plant == "plcsim":
                    target = float(self.criteria[
                        "ph_high_disturbance" if disturbance == "ph_high" else "ph_low_disturbance"
                    ])
                    assert plant is not None
                    ec_actual, ph_actual = plant.inject_output(ph_delta=target - ph_actual)

                ec_residual = ec_set - 1.5
                if not self.plc.write_residual_command(
                    1.0, ec_residual, 1.5, ec_actual, ph_actual,
                    ph_band_low=self.criteria["ph_band_low"],
                    ph_band_high=self.criteria["ph_band_high"],
                    recipe_id=2, controller_mode=2, sac_enable=True,
                ):
                    raise RuntimeError("E4 setpoint/feedback write failed")
                time.sleep(max(self.args.plc_wait_s, 0.0))
                state = self.plc.read_state()
                if not state.get("Remote_Comms_OK", False):
                    raise RuntimeError("communication dropped during E4")
                if state.get("System_Alarm_Light", False):
                    raise RuntimeError("PLC alarm became active during E4")
                if int(state.get("Controller_Mode", -1)) != 2:
                    raise RuntimeError("PLC left Controller_Mode=2 during E4")
                if self.args.plant == "plcsim" and not state.get(
                    "E4_Compressed_Time_Enable", False
                ):
                    raise RuntimeError("PLC left the E4 compressed-time mode")
                q_f, q_a = _f(state, "q_f_cmd"), _f(state, "q_a_cmd")
                if self.args.plant == "hardware":
                    ec_actual, ph_actual = _f(state, "EC_Actual"), _f(state, "pH_Actual")
                    target = float(self.criteria.get(
                        "ph_high_disturbance" if disturbance == "ph_high" else "ph_low_disturbance",
                        ph_actual,
                    ))
                    if disturbance == "ph_high" and ph_actual >= target:
                        external_confirmed = True
                    if disturbance == "ph_low" and ph_actual <= target:
                        external_confirmed = True
                self.rows.append({
                    "point": point_id, "weight": weight, "disturbance": disturbance,
                    "repetition": repetition, "time_s": time_s,
                    "disturbance_active": time_s >= self.args.warmup_s,
                    "external_disturbance_confirmed": external_confirmed,
                    "ec_set": ec_set, "ec_actual": ec_actual, "ph_actual": ph_actual,
                    "q_f_cmd": q_f, "q_a_cmd": q_a,
                    # Preserve the complete constrained-compensation path.  The
                    # final command alone cannot show whether a failed A/B run
                    # was caused by the model, the weight blend, or an output
                    # limit.
                    "q_f_feedforward": _f(state, "q_f_Feedforward"),
                    "q_f_pid_correction": _f(state, "q_f_PID_Correction"),
                    "delta_q_f": _f(state, "Delta_q_f"),
                    "q_f_raw": _f(state, "q_f_raw"),
                    "decoupler_weight_applied": _f(state, "Decoupler_Weight_Applied"),
                    "q_f_limited": bool(state.get("q_f_limited", False)),
                    "q_a_limited": bool(state.get("q_a_limited", False)),
                    "ph_flush_request": bool(state.get("pH_Flush_Request", False)),
                    "batch_reject": bool(state.get("Batch_Reject", False)),
                    "decoupling_limited": bool(state.get("Decoupling_Limited", False)),
                    "decoupler_active": bool(state.get("Decoupler_Active_Diag", False)),
                    "active_gain_point": int(state.get("Active_Gain_Point", -1)),
                    "alarm": bool(state.get("System_Alarm_Light", False)),
                    "remote_comms_ok": bool(state.get("Remote_Comms_OK", False)),
                })
                if self.args.plant == "plcsim":
                    assert plant is not None
                    ec_actual, ph_actual = plant.step(q_f, q_a)
            if disturbance != "ec_step" and not external_confirmed:
                raise RuntimeError(f"hardware {disturbance} disturbance was not observed")
        finally:
            self._finish_case()

    def run_point(self, point: str, weights: list[float]) -> None:
        for repetition in range(1, int(self.criteria["repetitions"]) + 1):
            for disturbance in DISTURBANCES:
                for weight in weights:
                    logging.info(
                        "E4 point=%s disturbance=%s repetition=%d weight=%.2f",
                        point, disturbance, repetition, weight,
                    )
                    self.run_case(point, weight, disturbance, repetition)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run gated mode-2 E4 constrained-decoupling A/B.")
    parser.add_argument("--e3-summary", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plant", choices=("plcsim", "hardware"), default="plcsim")
    parser.add_argument("--commit-approval", action="store_true",
                        help="Write E4_Approved only for a passed measured hardware campaign.")
    parser.add_argument("--parameter-version", type=int, default=1)
    parser.add_argument("--pulse-flow", type=float, default=0.8)
    parser.add_argument("--pulse-on-s", type=float, default=None)
    parser.add_argument("--pulse-off-s", type=float, default=None)
    parser.add_argument("--warmup-s", type=float, default=600.0)
    parser.add_argument("--duration-s", type=float, default=1200.0)
    parser.add_argument("--disturbance-hold-s", type=float, default=300.0)
    parser.add_argument("--baseline-window-s", type=float, default=None)
    parser.add_argument("--sim-step-s", type=float, default=60.0)
    parser.add_argument("--plc-wait-s", type=float, default=0.2)
    parser.add_argument("--q-w", type=float, default=136.0)
    parser.add_argument("--pressure-set", type=float, default=1.0)
    parser.add_argument("--ph-initial", type=float, default=6.2)
    args = parser.parse_args()
    if not args.apply:
        parser.error("E4 writes are protected; pass --apply")
    if args.commit_approval and args.plant != "hardware":
        parser.error("--commit-approval is allowed only for hardware evidence")
    if args.pulse_on_s is None:
        args.pulse_on_s = 300.0 if args.plant == "plcsim" else 5.0
    if args.pulse_off_s is None:
        args.pulse_off_s = 300.0 if args.plant == "plcsim" else 30.0

    e3_summary, schedule, source = _load_e3(args.e3_summary.resolve())
    if args.plant == "hardware" and source != "measured":
        parser.error("hardware E4 requires an E3 campaign labelled measured")
    criteria = _criteria(ROOT / "config" / "decoupler_ab.yaml", source)
    if args.baseline_window_s is None:
        args.baseline_window_s = float(criteria["baseline_window_s"])
    out_dir = ROOT / "results" / "plc_decoupler_ab" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    campaign = E4Campaign(args, schedule, criteria, out_dir)
    approved = False
    approval_written = False
    try:
        campaign.connect_and_load()
        medium_weights = [float(criteria["baseline_weight"])] + [float(value) for value in criteria["candidate_weights"]]
        campaign.run_point("medium", medium_weights)
        medium_metrics = summarize_constrained_rows(
            campaign.rows, disturbance_time_s=args.warmup_s,
            baseline_window_s=args.baseline_window_s,
            delay_s=float(_point(schedule, "medium")["delay_s"]),
            ph_low=float(criteria["ph_band_low"]), ph_high=float(criteria["ph_band_high"]),
        )
        medium_verdict = evaluate_constrained_ab(medium_metrics, criteria, point="medium")
        selected = medium_verdict["selected_weight"]
        point_verdicts = {"medium": medium_verdict}
        if selected is not None:
            campaign.run_point("low", [float(criteria["baseline_weight"]), float(selected)])
            campaign.run_point("high", [float(criteria["baseline_weight"]), float(selected)])
            all_metrics = summarize_constrained_rows(
                campaign.rows, disturbance_time_s=args.warmup_s,
                baseline_window_s=args.baseline_window_s,
                delay_s=float(_point(schedule, "medium")["delay_s"]),
                ph_low=float(criteria["ph_band_low"]), ph_high=float(criteria["ph_band_high"]),
            )
            verification_criteria = deepcopy(criteria)
            verification_criteria["candidate_weights"] = [float(selected)]
            point_verdicts["low"] = evaluate_constrained_ab(all_metrics, verification_criteria, point="low")
            point_verdicts["high"] = evaluate_constrained_ab(all_metrics, verification_criteria, point="high")
            approved = all(verdict["passed"] for verdict in point_verdicts.values())
        else:
            all_metrics = medium_metrics
    except Exception:
        logging.exception("E4 campaign stopped")
        try:
            approval_written = campaign.finish(False)
        except Exception:
            logging.exception("failed to force final E4 safe state")
        return 2
    else:
        approval_written = campaign.finish(approved)

    with (out_dir / "ab_results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(campaign.rows[0]))
        writer.writeheader()
        writer.writerows(campaign.rows)
    with (out_dir / "ab_metrics.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_metrics[0]))
        writer.writeheader()
        writer.writerows(all_metrics)
    summary = {
        "schema_version": 2, "method": criteria["method"],
        "e3_summary": str(args.e3_summary.resolve()), "evidence_label": source,
        "criteria": criteria, "point_verdicts": point_verdicts,
        "passed": approved, "selected_weight": point_verdicts["medium"].get("selected_weight"),
        "approval_written": approval_written, "raw_samples": len(campaign.rows),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved E4 results: {out_dir}")
    print(json.dumps(point_verdicts, indent=2, ensure_ascii=False))
    print(f"E4 passed={approved}; approval_written={approval_written}")
    return 0 if approved else 3


if __name__ == "__main__":
    raise SystemExit(main())
