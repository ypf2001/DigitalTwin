"""PLC outlet stability test across the four lifecycle stages.

This is a pre-field test. It keeps one continuous mixing tank + pipe process
and switches the PLC through INI -> DEV -> MID -> LATE targets. Each stage is
checked against the outlet acceptance targets before field/root-zone coupling.
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

from config_loader import load_config
from mixing_tank import MixingTank
from pipe_dynamics import PipeDynamics
from plc_client import PLCClient


STAGES = {
    "INI": {"idx": 0, "ec": 0.8, "ph": 6.2},
    "DEV": {"idx": 1, "ec": 1.1, "ph": 6.1},
    "MID": {"idx": 2, "ec": 1.5, "ph": 5.9},
    "LATE": {"idx": 3, "ec": 1.0, "ph": 6.1},
}
STAGE_SEQUENCE = ("INI", "DEV", "MID", "LATE")


def _plot(out_dir: Path, rows: list[dict[str, float]]) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if simhei_path.exists():
        fm.fontManager.addfont(str(simhei_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    t = np.array([r["time_s"] for r in rows], dtype=float)
    ec = np.array([r["ec_actual"] for r in rows], dtype=float)
    ph = np.array([r["ph_actual"] for r in rows], dtype=float)
    ec_sp = np.array([r["ec_set"] for r in rows], dtype=float)
    ph_sp = np.array([r["ph_set"] for r in rows], dtype=float)
    q_f = np.array([r["q_f_cmd"] for r in rows], dtype=float)
    q_a = np.array([r["q_a_cmd"] for r in rows], dtype=float)

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(t, ec, color="#26734d", linewidth=1.5, label="EC actual")
    axes[0].step(t, ec_sp, where="post", color="#26734d", linestyle="--", linewidth=1.0, label="EC set")
    axes[0].set_ylabel("EC")
    axes[0].legend(loc="best")

    axes[1].plot(t, ph, color="#2f5f9f", linewidth=1.5, label="pH actual")
    axes[1].step(t, ph_sp, where="post", color="#2f5f9f", linestyle="--", linewidth=1.0, label="pH set")
    axes[1].set_ylabel("pH")
    axes[1].legend(loc="best")

    axes[2].plot(t, q_f, color="#6f8f2f", linewidth=1.3, label="q_f")
    axes[2].plot(t, q_a, color="#9f4f5f", linewidth=1.3, label="q_a")
    axes[2].set_ylabel("L/min")
    axes[2].set_xlabel("Simulated time (s)")
    axes[2].legend(loc="best")

    stage_starts = {}
    for row in rows:
        stage_starts.setdefault(row["stage"], row["time_s"])
    for ax in axes:
        for stage, start in stage_starts.items():
            ax.axvline(float(start), color="#999999", linestyle=":", linewidth=0.8)
            ax.text(float(start), 0.98, stage, transform=ax.get_xaxis_transform(), va="top", fontsize=9)
        ax.grid(True, axis="y", color="#dddddd", linewidth=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.tight_layout()
    plot_path = out_dir / "lifecycle_outlet_stability.png"
    fig.savefig(plot_path, dpi=220)
    plt.close(fig)
    return plot_path


def _stage_metrics(rows: list[dict[str, float]], args: argparse.Namespace) -> dict[str, dict[str, float | bool]]:
    result: dict[str, dict[str, float | bool]] = {}
    tail_steps = max(3, int(round(args.tail_s / args.sim_step_s_effective)))
    for stage in STAGE_SEQUENCE:
        stage_rows = [r for r in rows if r["stage"] == stage]
        if not stage_rows:
            result[stage] = {"passed": False, "error": "no rows"}
            continue
        tail = stage_rows[max(0, len(stage_rows) - tail_steps) :]
        ec_tail_mae = float(np.mean([abs(r["ec_actual"] - r["ec_set"]) for r in tail]))
        ph_tail_mae = float(np.mean([abs(r["ph_actual"] - r["ph_set"]) for r in tail]))
        ec_final_error = float(stage_rows[-1]["ec_actual"] - stage_rows[-1]["ec_set"])
        ph_final_error = float(stage_rows[-1]["ph_actual"] - stage_rows[-1]["ph_set"])
        ph_tail_drop = float(tail[0]["ph_actual"] - tail[-1]["ph_actual"])
        passed = (
            ec_tail_mae <= args.ec_mae_max
            and ph_tail_mae <= args.ph_mae_max
            and abs(ec_final_error) <= args.ec_final_band
            and abs(ph_final_error) <= args.ph_final_band
            and ph_tail_drop <= args.ph_tail_drop_max
        )
        result[stage] = {
            "passed": passed,
            "ec_tail_mae": ec_tail_mae,
            "ph_tail_mae": ph_tail_mae,
            "ec_final_error": ec_final_error,
            "ph_final_error": ph_final_error,
            "ph_tail_drop": ph_tail_drop,
            "ec_final": float(stage_rows[-1]["ec_actual"]),
            "ph_final": float(stage_rows[-1]["ph_actual"]),
            "q_f_final": float(stage_rows[-1]["q_f_cmd"]),
            "q_a_final": float(stage_rows[-1]["q_a_cmd"]),
        }
    return result


def run(args: argparse.Namespace) -> tuple[Path, dict]:
    logging.getLogger("plc_client").setLevel(logging.WARNING)

    cfg = load_config()
    q_w = float(args.q_w if args.q_w is not None else cfg.env().get("q_w", 136.0))
    args.sim_step_s_effective = float(args.sim_step_s if args.sim_step_s is not None else args.plc_wait_s)

    tank = MixingTank()
    pipe = PipeDynamics(
        tau=args.pipe_tau_min,
        T=args.pipe_t_min,
        dt=max(args.sim_step_s_effective / 60.0, 1e-6),
    )
    tank.reset()
    pipe.reset()

    plc = PLCClient(cycle_s=args.plc_wait_s)
    if not plc.connect():
        raise RuntimeError("PLC connection failed.")

    if args.write_pid:
        plc.write_pid_params(
            kp_ec=args.kp_ec,
            ki_ec=args.ki_ec,
            kd_ec=args.kd_ec,
            kp_ph=args.kp_ph,
            ki_ph=args.ki_ph,
            kd_ph=args.kd_ph,
            ec_trim_band=args.ec_trim_band,
            ph_trim_band=args.ph_trim_band,
        )

    out_dir = ROOT / "results" / "lifecycle_outlet_stability" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "lifecycle_outlet_stability.csv"

    rows: list[dict[str, float]] = []
    ec_actual = float(args.ec_initial)
    ph_actual = float(args.ph_initial)
    steps_per_stage = max(1, int(round(args.stage_duration_s / args.sim_step_s_effective)))

    fieldnames = [
        "step",
        "stage",
        "stage_step",
        "time_s",
        "ec_set",
        "ph_set",
        "ec_actual",
        "ph_actual",
        "q_f_cmd",
        "q_a_cmd",
        "active_ec_sp",
        "active_ph_sp",
        "remote_comms_ok",
    ]

    with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        global_step = 0
        try:
            for stage in STAGE_SEQUENCE:
                meta = STAGES[stage]
                plc.write_growth_stage(int(meta["idx"]))
                for stage_step in range(steps_per_stage):
                    time_s = global_step * args.sim_step_s_effective
                    ec_set = float(meta["ec"])
                    ph_set = float(meta["ph"])
                    plc.write_setpoints(ec_set, ph_set, ec_actual, ph_actual, sac_enable=True)
                    time.sleep(args.plc_wait_s)
                    state = plc.read_state() or {}

                    q_f = float(state.get("q_f_cmd", 0.0))
                    q_a = float(state.get("q_a_cmd", 0.0))
                    ec_tank, ph_tank = tank.step(q_f=q_f, q_a=q_a, q_w=q_w)
                    ec_actual, ph_actual = pipe.step(ec_tank, ph_tank)

                    row = {
                        "step": global_step,
                        "stage": stage,
                        "stage_step": stage_step,
                        "time_s": time_s,
                        "ec_set": ec_set,
                        "ph_set": ph_set,
                        "ec_actual": float(ec_actual),
                        "ph_actual": float(ph_actual),
                        "q_f_cmd": q_f,
                        "q_a_cmd": q_a,
                        "active_ec_sp": float(state.get("Active_EC_SP", ec_set)),
                        "active_ph_sp": float(state.get("Active_pH_SP", ph_set)),
                        "remote_comms_ok": bool(state.get("Remote_Comms_OK", False)),
                    }
                    rows.append(row)
                    writer.writerow(row)
                    csv_file.flush()
                    if global_step % max(args.log_every, 1) == 0:
                        print(
                            f"t={time_s:7.1f}s stage={stage} "
                            f"EC={ec_actual:.3f}/{ec_set:.3f} pH={ph_actual:.3f}/{ph_set:.3f} "
                            f"q_f={q_f:.3f} q_a={q_a:.3f}",
                            flush=True,
                        )
                    global_step += 1
        finally:
            try:
                plc.write_setpoints(STAGES["LATE"]["ec"], STAGES["LATE"]["ph"], ec_actual, ph_actual, sac_enable=False)
            finally:
                plc.disconnect()

    plot_path = _plot(out_dir, rows)
    metrics = _stage_metrics(rows, args)
    passed = all(bool(metrics[stage].get("passed")) for stage in STAGE_SEQUENCE)
    summary = {
        "passed": passed,
        "targets": {
            "ec_tail_mae_max": args.ec_mae_max,
            "ph_tail_mae_max": args.ph_mae_max,
            "ec_final_abs_max": args.ec_final_band,
            "ph_final_abs_max": args.ph_final_band,
            "ph_tail_drop_max": args.ph_tail_drop_max,
        },
        "stage_duration_s": args.stage_duration_s,
        "sim_step_s": args.sim_step_s_effective,
        "csv": str(csv_path),
        "plot": str(plot_path),
        "stages": metrics,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved CSV: {csv_path}", flush=True)
    print(f"Saved plot: {plot_path}", flush=True)
    print(json.dumps({"passed": passed, "stages": metrics}, ensure_ascii=False, indent=2), flush=True)
    if args.strict and not passed:
        raise RuntimeError("Lifecycle outlet stability did not meet thresholds.")
    return out_dir, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run continuous PLC outlet stability test across INI/DEV/MID/LATE.")
    parser.add_argument("--stage-duration-s", type=float, default=3600.0)
    parser.add_argument("--plc-wait-s", type=float, default=1.0)
    parser.add_argument("--sim-step-s", type=float, default=None)
    parser.add_argument("--pipe-tau-min", type=float, default=None)
    parser.add_argument("--pipe-t-min", type=float, default=None)
    parser.add_argument("--q-w", type=float, default=None)
    parser.add_argument("--ec-initial", type=float, default=0.0)
    parser.add_argument("--ph-initial", type=float, default=7.0)
    parser.add_argument("--tail-s", type=float, default=900.0)
    parser.add_argument("--ec-mae-max", type=float, default=0.03)
    parser.add_argument("--ph-mae-max", type=float, default=0.05)
    parser.add_argument("--ec-final-band", type=float, default=0.05)
    parser.add_argument("--ph-final-band", type=float, default=0.08)
    parser.add_argument("--ph-tail-drop-max", type=float, default=0.02)
    parser.add_argument("--write-pid", action="store_true")
    parser.add_argument("--kp-ec", type=float, default=1.2)
    parser.add_argument("--ki-ec", type=float, default=0.0)
    parser.add_argument("--kd-ec", type=float, default=0.0)
    parser.add_argument("--kp-ph", type=float, default=1.2)
    parser.add_argument("--ki-ph", type=float, default=0.01)
    parser.add_argument("--kd-ph", type=float, default=0.0)
    parser.add_argument("--ec-trim-band", type=float, default=0.10)
    parser.add_argument("--ph-trim-band", type=float, default=0.08)
    parser.add_argument("--log-every", type=int, default=30)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
