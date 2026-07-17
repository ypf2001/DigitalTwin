"""Identify local EC/pH gains at MID low/medium/high operating points.

Live mode uses PLC manual flow commands and simulated EC/pH feedback.  It is
deliberately opt-in with ``--apply``.  The default ``--offline`` mode exercises
the same logging and estimator against MixingTank/PipeDynamics so the data
contract can be checked before PLCSIM is touched.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mixing_tank import MixingTank
from pipe_dynamics import PipeDynamics
from plc_client import PLCClient
from plc_control.gain_schedule import identify_local_gain


STAGE_INDEX = {"INI": 0, "DEV": 1, "MID": 2, "LATE": 3}


@dataclass(frozen=True)
class OperatingPoint:
    name: str
    ec_set: float
    ph_set: float
    q_f: float
    q_a: float
    q_f_step: float
    q_a_step: float


POINTS = (
    OperatingPoint("low", 1.40, 5.95, 2.0, 0.40, 0.50, 0.20),
    OperatingPoint("medium", 1.50, 5.90, 4.0, 0.80, 1.00, 0.30),
    OperatingPoint("high", 1.60, 5.85, 6.0, 1.20, 1.50, 0.40),
)


def phase_commands(point: OperatingPoint, hold: float, step: float) -> list[tuple[str, float, float, float]]:
    return [
        ("baseline", point.q_f, point.q_a, hold),
        ("fertilizer_pos", point.q_f + point.q_f_step, point.q_a, step),
        ("recovery_1", point.q_f, point.q_a, hold),
        ("fertilizer_neg", max(0.0, point.q_f - point.q_f_step), point.q_a, step),
        ("recovery_2", point.q_f, point.q_a, hold),
        ("acid_pos", point.q_f, point.q_a + point.q_a_step, step),
        ("recovery_3", point.q_f, point.q_a, hold),
        ("acid_neg", point.q_f, max(0.0, point.q_a - point.q_a_step), step),
        ("recovery_4", point.q_f, point.q_a, hold),
    ]


def _state_value(state: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(state.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _plot(path: Path, rows: list[dict]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logging.getLogger(__name__).warning("matplotlib unavailable; skipping response plot")
        return
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    for point_name in sorted({row["operating_point"] for row in rows}):
        selected = [row for row in rows if row["operating_point"] == point_name]
        t = np.array([row["timestamp_s"] for row in selected])
        axes[0].plot(t, [row["ec"] for row in selected], label=point_name)
        axes[1].plot(t, [row["ph"] for row in selected], label=point_name)
        axes[2].plot(t, [row["q_f_cmd"] for row in selected], label=f"{point_name} q_f")
        axes[2].plot(t, [row["q_a_cmd"] for row in selected], linestyle="--", label=f"{point_name} q_a")
    axes[0].set_ylabel("EC")
    axes[1].set_ylabel("pH")
    axes[2].set_ylabel("flow (L/min)")
    axes[2].set_xlabel("experiment time (s)")
    for axis in axes:
        axis.grid(True, alpha=0.3)
        axis.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


class GainExperiment:
    def __init__(self, args: argparse.Namespace, out_dir: Path):
        self.args = args
        self.out_dir = out_dir
        self.tank = MixingTank()
        self.pipe = PipeDynamics(
            tau=args.pipe_tau_min,
            T=args.pipe_t_min,
            dt=max(args.sim_step_s / 60.0, 1e-6),
        )
        self.plc = None if args.offline else PLCClient(cycle_s=args.plc_wait_s)
        self.rows: list[dict] = []
        self.ec = float(args.ec_initial)
        self.ph = float(args.ph_initial)
        self.time_s = 0.0

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
            raise RuntimeError("could not enable the PLCSIM carrier-water command")
        if not self.plc.write_water_feedback(self.args.q_w, self.args.pressure_set, 50.0, True):
            raise RuntimeError("could not provide PLCSIM water feedback")
        if not self.plc.write_feedback(self.ec, self.ph, sac_enable=False):
            raise RuntimeError("could not write initial simulated sensor feedback")
        if not self.plc.write_system_alarm_reset(True):
            raise RuntimeError("could not acknowledge the existing commissioning alarm")
        time.sleep(max(self.plc.cycle_s * 2.0, 0.2))
        if not self.plc.write_system_alarm_reset(False):
            raise RuntimeError("could not release the commissioning alarm acknowledge")
        if not self.plc.write_manual_mode(True, q_f=point.q_f, q_a=point.q_a):
            raise RuntimeError("could not enter PLC manual mode")
        time.sleep(max(self.args.plc_wait_s * 2.0, 0.2))
        state = self.plc.read_state()
        if not state.get("Manual_Active", False):
            raise RuntimeError(f"PLC did not enter manual mode: {state}")
        if not state.get("Water_Flow_OK", False):
            raise RuntimeError(f"carrier-water interlock is not ready: {state}")
        if state.get("Decoupler_Enable", False):
            raise RuntimeError("Decoupler_Enable remained TRUE after the safety write")

    def _live_finish(self) -> None:
        if self.plc is None:
            return
        if not getattr(self.plc, "_connected", False):
            return
        try:
            self.plc.write_standby()
            self.plc.write_water_command(False, 0.0, 0.0)
            self.plc.write_water_feedback(0.0, 0.0, 0.0, False)
            self.plc.write_feedback(self.ec, self.ph, sac_enable=False)
        finally:
            self.plc.disconnect()

    def _cycle(self, point: OperatingPoint, step_name: str, q_f_target: float, q_a_target: float) -> None:
        if self.plc is None:
            q_f_cmd, q_a_cmd, q_w = q_f_target, q_a_target, self.args.q_w
            ec_tank, ph_tank = self.tank.step(q_f_cmd, q_a_cmd, q_w)
            self.ec, self.ph = self.pipe.step(ec_tank, ph_tank)
            state = {"Manual_Active": True, "Water_Flow_OK": True, "Decoupler_Enable": False,
                     "Decoupler_Valid": False, "System_Alarm_Light": False}
        else:
            if not self.plc.write_gain_experiment_frame(
                self.ec, self.ph, q_f_target, q_a_target
            ):
                raise RuntimeError("compact experiment frame write failed")
            time.sleep(max(self.args.plc_wait_s, 0.0))
            state = self.plc.read_gain_experiment_state()
            if not state:
                raise RuntimeError("compact experiment state read failed")
            if not state.get("Manual_Active", False):
                raise RuntimeError("PLC left manual mode during the identification run")
            if not state.get("Water_Flow_OK", False):
                raise RuntimeError("carrier-water interlock dropped during the identification run")
            if state.get("Decoupler_Enable", False):
                raise RuntimeError("Decoupler_Enable changed to TRUE during identification")
            q_f_cmd = _state_value(state, "q_f_cmd")
            q_a_cmd = _state_value(state, "q_a_cmd")
            ec_tank, ph_tank = self.tank.step(q_f_cmd, q_a_cmd, self.args.q_w)
            self.ec, self.ph = self.pipe.step(ec_tank, ph_tank)

        self.rows.append({
            "timestamp_s": round(self.time_s, 6),
            "stage": "MID",
            "operating_point": point.name,
            "step_name": step_name,
            "ec_set": point.ec_set,
            "ph_set": point.ph_set,
            "q_f_baseline": point.q_f,
            "q_a_baseline": point.q_a,
            "q_f_target": q_f_target,
            "q_a_target": q_a_target,
            "q_f_cmd": q_f_cmd,
            "q_a_cmd": q_a_cmd,
            "q_w": self.args.q_w,
            "ec": self.ec,
            "ph": self.ph,
            "ec_feedback": self.ec,
            "ph_feedback": self.ph,
            "manual_active": bool(state.get("Manual_Active", False)),
            "water_flow_ok": bool(state.get("Water_Flow_OK", False)),
            "decoupler_enable": bool(state.get("Decoupler_Enable", False)),
            "decoupler_valid": bool(state.get("Decoupler_Valid", False)),
            "alarm": bool(state.get("System_Alarm_Light", False)),
            "q_f_limited": bool(state.get("q_f_limited", False)),
            "q_a_limited": bool(state.get("q_a_limited", False)),
        })
        self.time_s += self.args.sim_step_s

    def run_point(self, point: OperatingPoint) -> None:
        self.tank.reset()
        self.pipe.reset()
        self.ec = float(self.args.ec_initial)
        self.ph = float(self.args.ph_initial)
        try:
            if self.plc is not None:
                self._live_prepare(point)
            for step_name, q_f, q_a, duration in phase_commands(
                point, self.args.hold_s, self.args.step_s
            ):
                count = max(1, int(round(duration / self.args.sim_step_s)))
                for _ in range(count):
                    self._cycle(point, step_name, q_f, q_a)
        finally:
            if self.plc is not None:
                self._live_finish()


def write_outputs(out_dir: Path, rows: list[dict], args: argparse.Namespace) -> dict:
    raw_path = out_dir / "raw_steps.csv"
    if rows:
        with raw_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    points = {}
    errors = {}
    for point_name in sorted({row["operating_point"] for row in rows}):
        try:
            points[point_name] = identify_local_gain(rows, "MID", point_name, determinant_min=args.determinant_min)
        except (KeyError, ValueError, TypeError) as exc:
            errors[point_name] = str(exc)

    local_rows = []
    for name, point in points.items():
        local_rows.append({
            "stage": "MID", "operating_point": name,
            **point["gains"], "delay_s": point["delay_s"], "tau_s": point["tau_s"],
            "determinant": point["determinant"], "condition_number": point["condition_number"],
            "confidence": point["confidence"], "valid": point["valid"],
        })
    if local_rows:
        with (out_dir / "local_gains.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(local_rows[0]))
            writer.writeheader()
            writer.writerows(local_rows)

    schedule_points = [
        {key: value for key, value in point.items() if key != "responses"}
        for point in points.values()
    ]
    schedule = {
        "schema_version": 1,
        "enabled": False,
        "selection": {"method": "nearest", "ec_scale": 0.5, "ph_scale": 0.5,
                       "q_f_scale": 5.0, "q_a_scale": 2.0,
                       "determinant_min": args.determinant_min},
        "stages": {"INI": {"points": []}, "DEV": {"points": []},
                   "MID": {"points": schedule_points}, "LATE": {"points": []}},
    }
    import yaml

    (out_dir / "gain_schedule.yaml").write_text(
        yaml.safe_dump({"gain_schedule": schedule}, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    summary = {"mode": "offline" if args.offline else "plcsim", "points": local_rows, "errors": errors,
               "decoupler_enabled": False, "raw_samples": len(rows)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _plot(out_dir / "response_plot.png", rows)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Identify MID local EC/pH gains at three work points.")
    parser.add_argument("--offline", action="store_true", help="Use MixingTank/PipeDynamics; no PLC writes.")
    parser.add_argument("--apply", action="store_true", help="Allow live PLCSIM/PLC writes.")
    parser.add_argument("--point", choices=[point.name for point in POINTS], default=None)
    parser.add_argument("--sim-step-s", type=float, default=10.0,
                        help="simulated seconds advanced per sample")
    parser.add_argument("--plc-wait-s", type=float, default=1.0)
    parser.add_argument("--hold-s", type=float, default=600.0,
                        help="baseline/recovery duration; should exceed pipe delay")
    parser.add_argument("--step-s", type=float, default=1200.0,
                        help="positive/negative step duration; should exceed delay plus settling")
    parser.add_argument("--pipe-tau-min", type=float, default=None,
                        help="override simulated pipe delay for offline smoke tests")
    parser.add_argument("--pipe-t-min", type=float, default=None,
                        help="override simulated pipe time constant for offline smoke tests")
    parser.add_argument("--q-w", type=float, default=136.0)
    parser.add_argument("--pressure-set", type=float, default=1.0)
    parser.add_argument("--ec-initial", type=float, default=1.35)
    parser.add_argument("--ph-initial", type=float, default=6.0)
    parser.add_argument("--determinant-min", type=float, default=0.001)
    args = parser.parse_args()
    if args.sim_step_s <= 0.0 or args.plc_wait_s < 0.0 or args.hold_s <= 0.0 or args.step_s <= 0.0:
        parser.error("--sim-step-s must be positive and --plc-wait-s cannot be negative")
    if not args.offline and not args.apply:
        parser.error("live mode is write-protected; use --apply, or use --offline first")

    selected = [point for point in POINTS if args.point is None or point.name == args.point]
    out_dir = ROOT / "results" / "plc_gain_identification" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    experiment = GainExperiment(args, out_dir)
    try:
        for point in selected:
            experiment.run_point(point)
    except Exception as exc:
        logging.exception("gain identification stopped: %s", exc)
        return 2
    summary = write_outputs(out_dir, experiment.rows, args)
    print(f"Saved results: {out_dir}")
    print(f"Samples: {summary['raw_samples']}; valid points: {sum(1 for row in summary['points'] if row['valid'])}")
    print("Decoupler remains disabled. Review local_gains.csv before copying the YAML into config/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
