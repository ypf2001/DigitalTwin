from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_client import PLCClient
from plc.tuning.write_fertilizer_channels_to_plc import _load_config as _load_fertilizer_config


def _latest_summary() -> Path:
    tuning_root = ROOT / "results" / "pid_tuning"
    summaries = sorted(tuning_root.glob("*/summary.json"), key=lambda p: p.stat().st_mtime)
    if not summaries:
        raise FileNotFoundError("No PID tuning summary.json found.")
    return summaries[-1]


def _load_best(summary_path: Path) -> dict[str, float]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    best = data.get("best", data)
    return {
        "kp_ec": float(best["kp_ec"]),
        "ki_ec": float(best["ki_ec"]),
        "kd_ec": float(best["kd_ec"]),
        "kp_ph": float(best["kp_ph"]),
        "ki_ph": float(best["ki_ph"]),
        "kd_ph": float(best["kd_ph"]),
    }


def _preflight_plc() -> None:
    plc = PLCClient()
    if not plc.connect():
        raise RuntimeError("PLC connection failed.")
    try:
        # PID + N/P/K online tuning block ends at byte 268 in config/simulation.yaml.
        plc._client.db_read(plc.db_number, 0, 268)
    except Exception as exc:
        raise RuntimeError(
            "PLC is connected, but DB1 is too small for online PID/NPK tuning. "
            "Download the latest TIA project to PLCSIM/PLC first; DB1 must include offsets 126-267."
        ) from exc
    finally:
        plc.disconnect()


def _write_pid(params: dict[str, float]) -> None:
    plc = PLCClient()
    if not plc.connect():
        raise RuntimeError("PLC connection failed.")
    try:
        ok = plc.write_pid_params(
            kp_ec=params["kp_ec"],
            ki_ec=params["ki_ec"],
            kd_ec=params["kd_ec"],
            kp_ph=params["kp_ph"],
            ki_ph=params["ki_ph"],
            kd_ph=params["kd_ph"],
        )
        if not ok:
            raise RuntimeError("PID parameter write failed.")
    finally:
        plc.disconnect()


def _write_default_fertilizer_channels() -> None:
    channels = _load_fertilizer_config(ROOT / "config" / "fertilizer_channels.json")
    plc = PLCClient()
    if not plc.connect():
        raise RuntimeError("PLC connection failed.")
    try:
        if not plc.write_fertilizer_channels(channels):
            raise RuntimeError("Fertilizer channel write failed.")
    finally:
        plc.disconnect()


def _run_cmd(cmd: list[str]) -> None:
    print("RUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def _run_python_tuning(args: argparse.Namespace, seed: int) -> Path:
    cmd = [
        sys.executable,
        str(ROOT / "plc" / "tuning" / "tune_pid_coarse.py"),
        "--auto",
        "--mode",
        args.mode,
        "--trials",
        str(args.trials),
        "--max-rounds",
        str(args.python_rounds),
        "--season-days",
        str(args.python_season_days),
        "--dt-min",
        str(args.dt_min),
        "--seed",
        str(seed),
        "--target-ec-mae",
        str(args.target_ec_mae),
        "--target-ph-mae",
        str(args.target_ph_mae),
        "--target-ec-over",
        str(args.target_ec_over),
        "--target-ph-over",
        str(args.target_ph_over),
        "--kp-step",
        str(args.kp_step),
        "--ki-step",
        str(args.ki_step),
        "--kd-step",
        str(args.kd_step),
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.model_dir:
        cmd.extend(["--model-dir", args.model_dir])
    _run_cmd(cmd)
    return _latest_summary()


def _run_plc_validation(args: argparse.Namespace, seed: int) -> Path:
    cmd = [
        sys.executable,
        str(ROOT / "experiments" / "run_full_season_plc.py"),
        "--manual-test",
        "--season-days",
        str(args.plc_season_days),
        "--target-runtime-min",
        str(args.plc_runtime_min),
        "--plc-wait-s",
        str(args.plc_wait_s),
        "--seed",
        str(seed),
        "--log-every",
        str(args.log_every),
    ]
    _run_cmd(cmd)
    run_root = ROOT / "results" / "full_season_plc"
    summaries = sorted(run_root.glob("*/summary.json"), key=lambda p: p.stat().st_mtime)
    if not summaries:
        raise FileNotFoundError("No PLC validation summary.json found.")
    return summaries[-1].parent


def _metrics_from_plc_run(run_dir: Path) -> dict[str, float]:
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig")))
    if not rows:
        raise RuntimeError(f"No rows in {csv_path}")

    ec_soil = np.array([float(r["ec_soil"]) for r in rows], dtype=float)
    ec_target = np.array([float(r["target_ec"]) for r in rows], dtype=float)
    soil_ph = np.array([float(r["soil_ph_est"]) for r in rows], dtype=float)
    ph_set = np.array([float(r["ph_set"]) for r in rows], dtype=float)
    comm_ok = np.array([str(r["remote_comms_ok"]).lower() == "true" for r in rows], dtype=bool)

    ec_error = ec_soil - ec_target
    ph_error = soil_ph - ph_set
    return {
        "ec_mae": float(np.mean(np.abs(ec_error))),
        "ph_mae": float(np.mean(np.abs(ph_error))),
        "ec_over_max": float(np.max(np.maximum(ec_error, 0.0))),
        "ph_over_max": float(np.max(np.maximum(ph_error, 0.0))),
        "plc_ok_rate": float(np.mean(comm_ok)),
    }


def _plot_final_ec_ph(run_dir: Path, metrics: dict[str, float]) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if simhei_path.exists():
        fm.fontManager.addfont(str(simhei_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    csv_path = run_dir / "full_season_plc_timeseries.csv"
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig")))
    day = np.array([float(r["time_day"]) for r in rows], dtype=float)
    ec_soil = np.array([float(r["ec_soil"]) for r in rows], dtype=float)
    ec_target = np.array([float(r["target_ec"]) for r in rows], dtype=float)
    ph_soil = np.array([float(r["soil_ph_est"]) for r in rows], dtype=float)
    ph_target = np.array([float(r["ph_set"]) for r in rows], dtype=float)

    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    ax_ec.plot(day, ec_soil, color="#1f7a4d", linewidth=1.6, label="Root-zone EC")
    ax_ec.step(day, ec_target, where="post", color="#1f7a4d", linestyle="--", linewidth=1.2, label="Target EC")
    ax_ec.set_ylabel("EC (dS/m)")
    ax_ec.set_title(
        f"PLC PID EC tracking  MAE={metrics['ec_mae']:.4f}, over={metrics['ec_over_max']:.4f}"
    )
    ax_ec.grid(True, axis="y", color="#dddddd", linewidth=0.7)
    ax_ec.legend(loc="best")

    ax_ph.plot(day, ph_soil, color="#3569a8", linewidth=1.6, label="Estimated root-zone pH")
    ax_ph.step(day, ph_target, where="post", color="#3569a8", linestyle="--", linewidth=1.2, label="Target pH")
    ax_ph.set_ylabel("pH")
    ax_ph.set_xlabel("Day")
    ax_ph.set_title(
        f"PLC PID pH tracking  MAE={metrics['ph_mae']:.4f}, over={metrics['ph_over_max']:.4f}"
    )
    ax_ph.grid(True, axis="y", color="#dddddd", linewidth=0.7)
    ax_ph.legend(loc="best")

    for ax in (ax_ec, ax_ph):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.tight_layout()
    out_path = run_dir / "final_ec_ph_tracking.png"
    fig.savefig(out_path, dpi=220)
    plt.close(fig)
    return out_path


def _precise(metrics: dict[str, float], args: argparse.Namespace) -> bool:
    return (
        metrics["ec_mae"] <= args.target_ec_mae
        and metrics["ph_mae"] <= args.target_ph_mae
        and metrics["ec_over_max"] <= args.target_ec_over
        and metrics["ph_over_max"] <= args.target_ph_over
        and metrics["plc_ok_rate"] >= args.min_plc_ok_rate
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune PID candidates, write to PLC, and validate until target precision is met.")
    parser.add_argument("--mode", choices=["fixed", "sac"], default="fixed")
    parser.add_argument("--max-plc-rounds", type=int, default=20)
    parser.add_argument("--trials", type=int, default=80)
    parser.add_argument("--python-rounds", type=int, default=4)
    parser.add_argument("--python-season-days", type=float, default=10.0)
    parser.add_argument("--plc-season-days", type=float, default=10.0)
    parser.add_argument("--plc-runtime-min", type=float, default=2.0)
    parser.add_argument("--plc-wait-s", type=float, default=1.0)
    parser.add_argument("--dt-min", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-ec-mae", type=float, default=0.08)
    parser.add_argument("--target-ph-mae", type=float, default=0.08)
    parser.add_argument("--target-ec-over", type=float, default=0.02)
    parser.add_argument("--target-ph-over", type=float, default=0.03)
    parser.add_argument("--kp-step", type=float, default=0.1)
    parser.add_argument("--ki-step", type=float, default=0.001)
    parser.add_argument("--kd-step", type=float, default=0.001)
    parser.add_argument("--min-plc-ok-rate", type=float, default=0.95)
    parser.add_argument("--model-dir", default=str(ROOT / "rl_models"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--log-every", type=int, default=20)
    args = parser.parse_args()

    _preflight_plc()
    _write_default_fertilizer_channels()

    history = []
    best_row = None
    for round_no in range(1, args.max_plc_rounds + 1):
        seed = args.seed + round_no * 1000
        print(f"\n=== PLC tuning round {round_no}/{args.max_plc_rounds} ===", flush=True)
        summary_path = _run_python_tuning(args, seed)
        params = _load_best(summary_path)
        print("Writing PID params to PLC:", json.dumps(params, ensure_ascii=False), flush=True)
        _write_pid(params)

        run_dir = _run_plc_validation(args, seed)
        metrics = _metrics_from_plc_run(run_dir)
        plot_path = _plot_final_ec_ph(run_dir, metrics)
        row = {
            "round": round_no,
            "pid_summary": str(summary_path),
            "plc_run": str(run_dir),
            "plot": str(plot_path),
            **params,
            **metrics,
        }
        history.append(row)
        if best_row is None or (
            metrics["ec_mae"]
            + metrics["ph_mae"]
            + 5.0 * metrics["ec_over_max"]
            + 5.0 * metrics["ph_over_max"]
        ) < (
            best_row["ec_mae"]
            + best_row["ph_mae"]
            + 5.0 * best_row["ec_over_max"]
            + 5.0 * best_row["ph_over_max"]
        ):
            best_row = row
        print("PLC validation metrics:", json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)

        out_dir = ROOT / "results" / "pid_tuning_plc"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "latest_history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "latest_best.json").write_text(json.dumps(best_row, ensure_ascii=False, indent=2), encoding="utf-8")

        if _precise(metrics, args):
            print("Target precision reached.", flush=True)
            print(f"Final EC/pH plot: {plot_path}", flush=True)
            return 0

    print("Reached max PLC rounds before hitting target precision.", flush=True)
    if best_row is not None:
        print("Best PLC validation metrics:", json.dumps({
            "ec_mae": best_row["ec_mae"],
            "ph_mae": best_row["ph_mae"],
            "ec_over_max": best_row["ec_over_max"],
            "ph_over_max": best_row["ph_over_max"],
            "plc_ok_rate": best_row["plc_ok_rate"],
        }, ensure_ascii=False, indent=2), flush=True)
        print(f"Best EC/pH plot: {best_row['plot']}", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
