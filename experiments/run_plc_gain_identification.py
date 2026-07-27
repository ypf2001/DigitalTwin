"""Run guarded low/medium/high E3 gain-identification campaigns."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_client import PLCClient
from plc_control.gain_schedule import aggregate_gain_repetitions, identify_local_gain
from plc_control.mimo_fopdt import MIMOFOPDTParameters, MIMOFOPDTPlant


STAGE_INDEX = {"INI": 0, "DEV": 1, "MID": 2, "LATE": 3}
GAIN_KEYS = ("g_ec_f", "g_ec_a", "g_ph_f", "g_ph_a")


@dataclass(frozen=True)
class OperatingPoint:
    name: str
    ec_set: float
    ph_set: float
    q_f: float
    q_a: float
    q_f_step: float
    q_a_step: float


HIL_POINTS = (
    OperatingPoint("low", 1.40, 5.95, 2.0, 0.40, 0.50, 0.20),
    OperatingPoint("medium", 1.50, 5.90, 4.0, 0.80, 1.00, 0.30),
    OperatingPoint("high", 1.60, 5.85, 6.0, 1.20, 1.50, 0.40),
)

HIL_MODELS = {
    "low": MIMOFOPDTParameters(0.456, 0.104, -0.197, -1.070, 180.0, 300.0, 300.0),
    "medium": MIMOFOPDTParameters(0.403, 0.105, -0.121, -0.551, 180.0, 300.0, 300.0),
    "high": MIMOFOPDTParameters(0.433, 0.142, -0.118, -0.383, 180.0, 300.0, 300.0),
}


def hardware_points(args: argparse.Namespace) -> tuple[OperatingPoint, ...]:
    def channel_points(low: float, high: float, noise: float) -> list[tuple[float, float]]:
        if high <= low:
            raise ValueError("usable pump maximum must exceed minimum")
        span = high - low
        safe_low, safe_high = low + 0.20 * span, low + 0.80 * span
        result = []
        for fraction in (0.30, 0.50, 0.70):
            baseline = low + fraction * span
            requested = max(0.10 * span, 5.0 * max(noise, 0.0))
            step = min(requested, baseline - safe_low, safe_high - baseline)
            if step <= 0.0:
                raise ValueError("calibrated pump range leaves no safe E3 step")
            result.append((baseline, step))
        return result

    fertilizer = channel_points(args.q_f_usable_min, args.q_f_usable_max, args.q_f_noise_std)
    acid = channel_points(args.q_a_usable_min, args.q_a_usable_max, args.q_a_noise_std)
    return tuple(
        OperatingPoint(name, ec, ph, fertilizer[index][0], acid[index][0],
                       fertilizer[index][1], acid[index][1])
        for index, (name, ec, ph) in enumerate((
            ("low", 1.40, 5.95), ("medium", 1.50, 5.90), ("high", 1.60, 5.85)
        ))
    )


def phase_commands(point: OperatingPoint, hold: float, step: float) -> list[tuple[str, float, float, float]]:
    return [
        ("baseline", point.q_f, point.q_a, hold),
        ("fertilizer_pos", point.q_f + point.q_f_step, point.q_a, step),
        ("recovery_1", point.q_f, point.q_a, hold),
        ("fertilizer_neg", point.q_f - point.q_f_step, point.q_a, step),
        ("recovery_2", point.q_f, point.q_a, hold),
        ("acid_pos", point.q_f, point.q_a + point.q_a_step, step),
        ("recovery_3", point.q_f, point.q_a, hold),
        ("acid_neg", point.q_f, point.q_a - point.q_a_step, step),
        ("recovery_4", point.q_f, point.q_a, hold),
    ]


def _state_value(state: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(state.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(args: argparse.Namespace, points: tuple[OperatingPoint, ...]) -> dict:
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        git_dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        git_commit, git_dirty = "unavailable", True
    tracked = (
        ROOT / "experiments" / "run_plc_gain_identification.py",
        ROOT / "plc_control" / "gain_schedule.py",
        ROOT / "plc_control" / "mimo_fopdt.py",
        ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl",
    )
    return {
        "created_at": datetime.now().astimezone().isoformat(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "source_sha256": {str(path.relative_to(ROOT)): _sha256(path) for path in tracked},
        "plc_build_version": args.plc_build_version,
        "parameter_version": args.parameter_version,
        "sensor_calibration_id": args.sensor_calibration_id,
        "plant": args.plant,
        "evidence_label": "measured" if args.plant == "hardware" else "hil_simulation",
        "operating_points": [asdict(point) for point in points],
    }


def _plot(path: Path, rows: list[dict]) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logging.warning("matplotlib unavailable; response plot skipped")
        return
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=False)
    for point_name in sorted({row["operating_point"] for row in rows}):
        for repetition in sorted({int(row["repetition"]) for row in rows if row["operating_point"] == point_name}):
            selected = [row for row in rows if row["operating_point"] == point_name and int(row["repetition"]) == repetition]
            label = f"{point_name}-R{repetition}"
            t = [row["timestamp_s"] for row in selected]
            axes[0].plot(t, [row["ec"] for row in selected], label=label)
            axes[1].plot(t, [row["ph"] for row in selected], label=label)
            axes[2].plot(t, [row["q_f_cmd"] for row in selected], label=f"{label} q_f")
            axes[2].plot(t, [row["q_a_cmd"] for row in selected], linestyle="--", label=f"{label} q_a")
    axes[0].set_ylabel("EC (dS/m)")
    axes[1].set_ylabel("pH")
    axes[2].set_ylabel("flow (L/min)")
    axes[2].set_xlabel("run time (s)")
    for axis in axes:
        axis.grid(True, alpha=0.3)
        axis.legend(loc="best", fontsize=7, ncol=3)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


class GainExperiment:
    def __init__(self, args: argparse.Namespace, out_dir: Path):
        self.args = args
        self.out_dir = out_dir
        self.plc = None if args.offline else PLCClient(cycle_s=args.plc_wait_s)
        self.rows: list[dict] = []
        self.ec = float(args.ec_initial)
        self.ph = float(args.ph_initial)
        self.time_s = 0.0
        self.plant: MIMOFOPDTPlant | None = None
        self.baseline_reference: tuple[float, float] | None = None

    def _live_prepare(self, point: OperatingPoint) -> None:
        assert self.plc is not None
        if not self.plc.connect():
            raise RuntimeError("PLC/PLCSIM connection failed")
        if not self.plc.write_emergency_stop(False):
            raise RuntimeError("could not clear Emergency_Stop")
        if not self.plc.write_growth_stage(STAGE_INDEX["MID"]):
            raise RuntimeError("could not write MID growth stage")
        if not self.plc.set_decoupler_enabled(False):
            raise RuntimeError("could not force Decoupler_Enable=FALSE")
        if not self.plc.write_water_command(True, self.args.q_w, self.args.pressure_set):
            raise RuntimeError("could not enable carrier water")
        if self.args.plant == "plcsim":
            if not self.plc.write_water_feedback(self.args.q_w, self.args.pressure_set, 50.0, True):
                raise RuntimeError("could not provide PLCSIM water feedback")
            if not self.plc.write_feedback(self.ec, self.ph, sac_enable=False):
                raise RuntimeError("could not write simulated sensor feedback")
        if not self.plc.write_system_alarm_reset(True):
            raise RuntimeError("could not acknowledge commissioning alarm")
        time.sleep(max(self.plc.cycle_s * 2.0, 0.2))
        self.plc.write_system_alarm_reset(False)
        if not self.plc.write_manual_mode(True, q_f=point.q_f, q_a=point.q_a):
            raise RuntimeError("could not enter PLC manual mode")
        state = {}
        for _ in range(30):
            time.sleep(max(self.args.plc_wait_s, 0.2))
            if self.args.plant == "hardware":
                self.plc.write_gain_experiment_commands(point.q_f, point.q_a)
            state = self.plc.read_gain_experiment_state()
            if state.get("Remote_Comms_OK", False) and state.get("Water_Flow_OK", False):
                break
        if not state.get("Remote_Comms_OK", False):
            raise RuntimeError("PLC heartbeat was not acknowledged; CPU must be in RUN")
        if not state.get("Manual_Active", False):
            raise RuntimeError(f"PLC did not enter manual mode: {state}")
        if not state.get("Water_Flow_OK", False):
            raise RuntimeError(f"carrier-water interlock is not ready: {state}")
        if state.get("Decoupler_Enable", False):
            raise RuntimeError("Decoupler_Enable remained TRUE during E3")

    def _live_finish(self) -> None:
        if self.plc is None or not getattr(self.plc, "_connected", False):
            return
        try:
            self.plc.set_decoupler_enabled(False)
            self.plc.write_standby()
            self.plc.write_water_command(False, 0.0, 0.0)
            if self.args.plant == "plcsim":
                self.plc.write_water_feedback(0.0, 0.0, 0.0, False)
            self.plc.write_emergency_stop(True)
        finally:
            self.plc.disconnect()

    def _cycle(self, point: OperatingPoint, repetition: int, step_name: str,
               q_f_target: float, q_a_target: float) -> None:
        state = {
            "Manual_Active": True, "Water_Flow_OK": True,
            "Decoupler_Enable": False, "Decoupler_Valid": False,
            "System_Alarm_Light": False,
        }
        if self.plc is None:
            q_f_cmd, q_a_cmd = q_f_target, q_a_target
        else:
            if self.args.plant == "plcsim":
                ok = self.plc.write_gain_experiment_frame(self.ec, self.ph, q_f_target, q_a_target)
            else:
                ok = self.plc.write_gain_experiment_commands(q_f_target, q_a_target)
            if not ok:
                raise RuntimeError("E3 command frame write failed")
            time.sleep(max(self.args.plc_wait_s, 0.0))
            state = self.plc.read_gain_experiment_state()
            if not state:
                raise RuntimeError("E3 compact state read failed")
            if not state.get("Remote_Comms_OK", False):
                raise RuntimeError("PLC communication dropped during E3")
            if not state.get("Manual_Active", False) or not state.get("Water_Flow_OK", False):
                raise RuntimeError("PLC manual/water interlock dropped during E3")
            if state.get("Decoupler_Enable", False):
                raise RuntimeError("Decoupler_Enable changed to TRUE during E3")
            if state.get("System_Alarm_Light", False):
                raise RuntimeError("PLC alarm became active during E3")
            q_f_cmd = _state_value(state, "q_f_cmd")
            q_a_cmd = _state_value(state, "q_a_cmd")
            # DB reads can straddle the FB automatic write and the FC manual
            # override in one PLC scan. Require a stable post-scan read before
            # declaring that the physical command was not executed.
            for _ in range(3):
                if abs(q_f_cmd - q_f_target) <= 1e-3 and abs(q_a_cmd - q_a_target) <= 1e-3:
                    break
                time.sleep(max(self.args.plc_wait_s, 0.1))
                state = self.plc.read_gain_experiment_state()
                q_f_cmd = _state_value(state, "q_f_cmd")
                q_a_cmd = _state_value(state, "q_a_cmd")
            if abs(q_f_cmd - q_f_target) > 1e-3 or abs(q_a_cmd - q_a_target) > 1e-3:
                raise RuntimeError(
                    f"manual command not executed: requested=({q_f_target:.3f},{q_a_target:.3f}) "
                    f"actual=({q_f_cmd:.3f},{q_a_cmd:.3f})"
                )

        if self.args.plant == "plcsim":
            assert self.plant is not None
            self.ec, self.ph = self.plant.step(q_f_cmd, q_a_cmd)
        else:
            self.ec = _state_value(state, "EC_Actual", self.ec)
            self.ph = _state_value(state, "pH_Actual", self.ph)

        self.rows.append({
            "timestamp_s": round(self.time_s, 6), "stage": "MID",
            "operating_point": point.name, "repetition": repetition,
            "step_name": step_name, "ec_set": point.ec_set, "ph_set": point.ph_set,
            "q_f_baseline": point.q_f, "q_a_baseline": point.q_a,
            "q_f_target": q_f_target, "q_a_target": q_a_target,
            "q_f_cmd": q_f_cmd, "q_a_cmd": q_a_cmd, "q_w": self.args.q_w,
            "ec": self.ec, "ph": self.ph,
            "manual_active": bool(state.get("Manual_Active", False)),
            "water_flow_ok": bool(state.get("Water_Flow_OK", False)),
            "decoupler_enable": bool(state.get("Decoupler_Enable", False)),
            "decoupler_valid": bool(state.get("Decoupler_Valid", False)),
            "alarm": bool(state.get("System_Alarm_Light", False)),
            "q_f_limited": bool(state.get("q_f_limited", False)),
            "q_a_limited": bool(state.get("q_a_limited", False)),
            "evidence_label": "measured" if self.args.plant == "hardware" else "hil_simulation",
        })
        self.time_s += self.args.sim_step_s

    def _phase_stable(self, point: OperatingPoint, repetition: int, step_name: str) -> bool:
        selected = [
            row for row in self.rows
            if row["operating_point"] == point.name
            and int(row["repetition"]) == repetition
            and row["step_name"] == step_name
        ]
        if len(selected) < 5:
            return False
        window = selected[-min(5, len(selected)):]
        t = np.asarray([row["timestamp_s"] for row in window], dtype=float) / 60.0
        ec_slope = abs(float(np.polyfit(t, [row["ec"] for row in window], 1)[0]))
        ph_slope = abs(float(np.polyfit(t, [row["ph"] for row in window], 1)[0]))
        stable = ec_slope <= self.args.stable_ec_slope and ph_slope <= self.args.stable_ph_slope
        if stable and step_name.startswith("recovery") and self.baseline_reference is not None:
            ec_base, ph_base = self.baseline_reference
            stable = (
                abs(float(window[-1]["ec"]) - ec_base) <= self.args.recovery_ec_tolerance
                and abs(float(window[-1]["ph"]) - ph_base) <= self.args.recovery_ph_tolerance
            )
        return stable

    def run_point(self, point: OperatingPoint, repetition: int) -> None:
        self.time_s = 0.0
        self.ec, self.ph = float(self.args.ec_initial), float(self.args.ph_initial)
        self.baseline_reference = None
        if self.args.plant == "plcsim":
            self.plant = MIMOFOPDTPlant(HIL_MODELS[point.name], self.args.sim_step_s)
            self.plant.reset(point.q_f, point.q_a, self.ec, self.ph)
        try:
            if self.plc is not None:
                self._live_prepare(point)
            for step_name, q_f, q_a, duration in phase_commands(point, self.args.hold_s, self.args.step_s):
                count = max(1, int(round(duration / self.args.sim_step_s)))
                for _ in range(count):
                    self._cycle(point, repetition, step_name, q_f, q_a)
                if step_name == "baseline" or step_name.startswith("recovery"):
                    max_count = max(count, int(round(self.args.max_recovery_s / self.args.sim_step_s)))
                    while not self._phase_stable(point, repetition, step_name) and count < max_count:
                        self._cycle(point, repetition, step_name, q_f, q_a)
                        count += 1
                    if not self._phase_stable(point, repetition, step_name):
                        raise RuntimeError(f"{point.name} R{repetition} {step_name} did not stabilize")
                    if step_name == "baseline":
                        self.baseline_reference = (self.ec, self.ph)
        finally:
            self._live_finish()


def _reference_validation(point_name: str, aggregate: dict, sample_s: float) -> dict:
    reference = HIL_MODELS[point_name]
    errors = {
        key: abs(float(aggregate["gains"][key]) - float(getattr(reference, key)))
        / max(abs(float(getattr(reference, key))), 1e-9)
        for key in GAIN_KEYS
    }
    delay_error = abs(float(aggregate["delay_s"]) - reference.delay_s)
    return {
        "gain_relative_errors": errors,
        "delay_error_s": delay_error,
        "passed": all(value <= 0.05 for value in errors.values()) and delay_error <= sample_s,
    }


def write_outputs(out_dir: Path, rows: list[dict], args: argparse.Namespace,
                  points: tuple[OperatingPoint, ...], metadata: dict) -> dict:
    if rows:
        with (out_dir / "raw_steps.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    estimates: dict[str, list[dict]] = {point.name: [] for point in points}
    errors = []
    for point in points:
        for repetition in range(1, args.repetitions + 1):
            selected = [
                row for row in rows
                if row["operating_point"] == point.name and int(row["repetition"]) == repetition
            ]
            try:
                estimate = identify_local_gain(selected, "MID", point.name, args.determinant_min)
                estimate["repetition"] = repetition
                estimate["quality_ok"] = all(
                    not row["alarm"] and not row["q_f_limited"] and not row["q_a_limited"]
                    and row["manual_active"] and row["water_flow_ok"]
                    and not row["decoupler_enable"]
                    for row in selected
                )
                estimates[point.name].append(estimate)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append({"point": point.name, "repetition": repetition, "error": str(exc)})

    individual_rows = []
    for point_name, point_estimates in estimates.items():
        for estimate in point_estimates:
            individual_rows.append({
                "operating_point": point_name, "repetition": estimate["repetition"],
                **estimate["gains"], "delay_s": estimate["delay_s"],
                "tau_s": estimate["tau_s"], "determinant": estimate["determinant"],
                "condition_number": estimate["condition_number"],
                "confidence": estimate["confidence"], "quality_ok": estimate["quality_ok"],
                "valid": estimate["valid"],
            })
    if individual_rows:
        with (out_dir / "local_gains_repetitions.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(individual_rows[0]))
            writer.writeheader()
            writer.writerows(individual_rows)

    aggregates = {}
    acceptance_rows = []
    schedule_points = []
    for point in points:
        try:
            aggregate = aggregate_gain_repetitions(
                estimates[point.name], expected_repetitions=3,
                max_cv=args.max_gain_cv, max_condition_number=args.max_condition_number,
                min_snr=args.min_snr, determinant_min=args.determinant_min,
            )
            if args.plant == "plcsim":
                aggregate["reference_validation"] = _reference_validation(
                    point.name, aggregate, args.sim_step_s
                )
                aggregate["valid"] = bool(
                    aggregate["valid"] and aggregate["reference_validation"]["passed"]
                )
            aggregates[point.name] = aggregate
            acceptance_rows.append({
                "operating_point": point.name, "repetitions": aggregate["repetitions"],
                **aggregate["gains"], "delay_s": aggregate["delay_s"],
                "tau_s": aggregate["tau_s"], "determinant": aggregate["determinant"],
                "condition_number": aggregate["condition_number"],
                "minimum_snr": aggregate["minimum_snr"],
                "max_gain_cv": max(
                    stat["cv"] for key, stat in aggregate["gain_stats"].items()
                    if stat["identifiable"] or key in ("g_ec_f", "g_ph_a")
                ),
                "valid": aggregate["valid"],
            })
            schedule_points.append({
                "id": point.name, "stage": "MID", "ec": point.ec_set, "ph": point.ph_set,
                "q_f": point.q_f, "q_a": point.q_a, "gains": aggregate["gains"],
                "delay_s": aggregate["delay_s"], "tau_s": aggregate["tau_s"],
                "determinant": aggregate["determinant"],
                "condition_number": aggregate["condition_number"],
                "valid": aggregate["valid"], "repetitions": aggregate["repetitions"],
                "source": metadata["evidence_label"],
            })
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"point": point.name, "repetition": "aggregate", "error": str(exc)})

    if acceptance_rows:
        with (out_dir / "campaign_acceptance.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(acceptance_rows[0]))
            writer.writeheader()
            writer.writerows(acceptance_rows)

    e3_passed = bool(
        args.campaign and len(aggregates) == 3
        and all(aggregate["valid"] for aggregate in aggregates.values())
    )
    q_f_values = [point.q_f for point in points]
    schedule = {
        "schema_version": 2, "enabled": e3_passed, "e3_passed": e3_passed,
        "parameter_version": args.parameter_version, "source": metadata["evidence_label"],
        "selection": {
            "method": "plc_q_f_hysteresis", "low_medium_threshold": 0.5 * (q_f_values[0] + q_f_values[1]),
            "medium_high_threshold": 0.5 * (q_f_values[1] + q_f_values[2]),
            "hysteresis": 0.10 * min(q_f_values[1] - q_f_values[0], q_f_values[2] - q_f_values[1]),
            "minimum_hold_s": 60.0, "determinant_min": args.determinant_min,
        } if len(q_f_values) == 3 else {},
        "stages": {"INI": {"points": []}, "DEV": {"points": []},
                   "MID": {"points": schedule_points}, "LATE": {"points": []}},
    }
    (out_dir / "gain_schedule.yaml").write_text(
        yaml.safe_dump({"gain_schedule": schedule}, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 2, "metadata": metadata, "campaign": args.campaign,
        "repetitions_required": 3, "e3_passed": e3_passed,
        "aggregates": aggregates, "individual_estimates": individual_rows,
        "errors": errors, "decoupler_enabled": False, "raw_samples": len(rows),
    }
    (out_dir / "campaign_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _plot(out_dir / "response_plot.png", rows)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run guarded three-point E3 identification.")
    parser.add_argument("--offline", action="store_true", help="Exercise HIL plant without PLC writes.")
    parser.add_argument("--apply", action="store_true", help="Allow PLC/PLCSIM writes.")
    parser.add_argument("--plant", choices=("plcsim", "hardware"), default="plcsim")
    parser.add_argument("--campaign", action="store_true", help="Run low/medium/high with three repetitions.")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--point", choices=[point.name for point in HIL_POINTS])
    parser.add_argument("--sim-step-s", type=float, default=60.0)
    parser.add_argument("--plc-wait-s", type=float, default=0.2)
    parser.add_argument("--hold-s", type=float, default=600.0)
    parser.add_argument("--step-s", type=float, default=1200.0)
    parser.add_argument("--max-recovery-s", type=float, default=2400.0)
    parser.add_argument("--stable-ec-slope", type=float, default=0.002, help="dS/m per minute")
    parser.add_argument("--stable-ph-slope", type=float, default=0.005, help="pH per minute")
    parser.add_argument("--recovery-ec-tolerance", type=float, default=0.001)
    parser.add_argument("--recovery-ph-tolerance", type=float, default=0.0025)
    parser.add_argument("--q-w", type=float, default=136.0)
    parser.add_argument("--pressure-set", type=float, default=1.0)
    parser.add_argument("--ec-initial", type=float, default=1.35)
    parser.add_argument("--ph-initial", type=float, default=6.0)
    parser.add_argument("--determinant-min", type=float, default=0.001)
    parser.add_argument("--max-gain-cv", type=float, default=0.20)
    parser.add_argument("--max-condition-number", type=float, default=10.0)
    parser.add_argument("--min-snr", type=float, default=5.0)
    parser.add_argument("--q-f-usable-min", type=float, default=0.0)
    parser.add_argument("--q-f-usable-max", type=float, default=10.0)
    parser.add_argument("--q-a-usable-min", type=float, default=0.0)
    parser.add_argument("--q-a-usable-max", type=float, default=4.0)
    parser.add_argument("--q-f-noise-std", type=float, default=0.0)
    parser.add_argument("--q-a-noise-std", type=float, default=0.0)
    parser.add_argument("--plc-build-version", default="unrecorded")
    parser.add_argument("--parameter-version", default=datetime.now().strftime("E3-%Y%m%d"))
    parser.add_argument("--sensor-calibration-id", default="not_applicable")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.campaign:
        if args.point:
            parser.error("--campaign cannot be combined with --point")
        args.repetitions = 3
    if args.repetitions <= 0:
        parser.error("--repetitions must be positive")
    if args.plant == "hardware" and args.offline:
        parser.error("hardware E3 requires a PLC connection")
    if args.plant == "hardware" and args.sensor_calibration_id in ("", "not_applicable", "unverified"):
        parser.error("hardware E3 requires --sensor-calibration-id")
    if not args.offline and not args.apply:
        parser.error("live mode is write-protected; pass --apply")
    if min(args.sim_step_s, args.hold_s, args.step_s, args.max_recovery_s) <= 0.0:
        parser.error("sample and phase durations must be positive")

    all_points = hardware_points(args) if args.plant == "hardware" else HIL_POINTS
    points = tuple(point for point in all_points if args.point is None or point.name == args.point)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "results" / "plc_gain_identification" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = provenance(args, points)
    (out_dir / "provenance.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    experiment = GainExperiment(args, out_dir)
    try:
        for point in points:
            for repetition in range(1, args.repetitions + 1):
                logging.info("E3 point=%s repetition=%d/%d", point.name, repetition, args.repetitions)
                experiment.run_point(point, repetition)
    except Exception as exc:
        logging.exception("E3 stopped: %s", exc)
        return 2
    summary = write_outputs(out_dir, experiment.rows, args, points, metadata)
    print(f"Saved results: {out_dir}")
    print(f"Samples: {summary['raw_samples']}; E3 passed: {summary['e3_passed']}")
    print("Decoupler remains disabled. E4 must consume a passed campaign_summary.json.")
    return 0 if (not args.campaign or summary["e3_passed"]) else 3


if __name__ == "__main__":
    raise SystemExit(main())
