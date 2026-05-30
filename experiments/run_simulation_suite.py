"""Run the core digital-twin simulation experiments and export results.

This script is intentionally independent from the web UI. It produces the
first set of reproducible artifacts needed for method development:

- short fixed-policy simulation for one growth stage
- 90-day T1/T2 seasonal irrigation comparison
- CSV time series
- JSON summary
- PNG figures
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from crop_model import GrowthStage
from digital_twin_env import DigitalTwinEnv
from irrigation_schedule import get_irrigation_schedule, run_season_simulation


def _json_default(value: Any):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_csv(path: Path, columns: dict[str, Any]) -> None:
    keys = list(columns.keys())
    rows = zip(*(columns[k] for k in keys))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)


def _safe_mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if len(values) else 0.0


def _safe_last(values: np.ndarray) -> float:
    return float(values[-1]) if len(values) else 0.0


def run_short_fixed(stage: GrowthStage, out_dir: Path) -> dict[str, Any]:
    cfg = load_config()
    env_cfg = cfg.env()
    action = np.array(cfg.action().get("fixed_strategy", [5.0, 1.0]), dtype=np.float32)

    env = DigitalTwinEnv(
        growth_stage=stage,
        area_ha=env_cfg.get("area_ha", 0.1),
        dt_min=env_cfg.get("dt_min", 60.0),
        ep_len_days=env_cfg.get("ep_len_days", 5.0),
        et0_mm_day=env_cfg.get("et0_mm_day", 5.0),
        seed=env_cfg.get("seed"),
    )

    obs = env.reset()
    done = False
    series: dict[str, list[float]] = {
        "time_hours": [],
        "theta": [],
        "ec_soil": [],
        "target_ec": [],
        "ec_drip": [],
        "irrigation_mm_h": [],
        "etc_mm_h": [],
        "q_f": [],
        "q_a": [],
    }

    while not done:
        obs, _reward, done, info = env.step(action)
        series["time_hours"].append(float(info["time_day"] * 24.0))
        series["theta"].append(float(info["theta"]))
        series["ec_soil"].append(float(info["ec_soil"]))
        series["target_ec"].append(float(info["target_ec"]))
        series["ec_drip"].append(float(info["ec_drip"]))
        series["irrigation_mm_h"].append(float(info["irrigation_mm_h"]))
        series["etc_mm_h"].append(float(info["etc_mm_h"]))
        series["q_f"].append(float(action[0]))
        series["q_a"].append(float(action[1]))

    arrays = {k: np.asarray(v, dtype=float) for k, v in series.items()}
    dt_hours = env_cfg.get("dt_min", 60.0) / 60.0
    ec_error = np.abs(arrays["ec_soil"] - arrays["target_ec"])
    stats = {
        "stage": stage.value,
        "steps": int(len(arrays["time_hours"])),
        "theta_mean": _safe_mean(arrays["theta"]),
        "theta_final": _safe_last(arrays["theta"]),
        "ec_soil_mean": _safe_mean(arrays["ec_soil"]),
        "ec_soil_final": _safe_last(arrays["ec_soil"]),
        "ec_mae": _safe_mean(ec_error),
        "total_irrigation_mm": float(np.sum(arrays["irrigation_mm_h"]) * dt_hours),
        "total_etc_mm": float(np.sum(arrays["etc_mm_h"]) * dt_hours),
        "q_f": float(action[0]),
        "q_a": float(action[1]),
    }

    _write_csv(out_dir / "short_fixed_mid_timeseries.csv", series)
    _plot_short_fixed(arrays, out_dir / "short_fixed_mid.png")
    return stats


def run_season_compare(out_dir: Path) -> dict[str, Any]:
    cfg = load_config()
    season_cfg = cfg.season_comparison()
    irr_cfg = cfg.irrigation()
    schedule = get_irrigation_schedule()

    results = {}
    for strategy in ("T1", "T2"):
        env = DigitalTwinEnv(
            growth_stage=schedule[0].growth_stage,
            area_ha=season_cfg.get("area_ha", 0.1),
            dt_min=season_cfg.get("dt_min", 15.0),
            ep_len_days=season_cfg.get("ep_len_days", 90.0),
            et0_mm_day=season_cfg.get("et0_mm_day", 4.0),
            seed=season_cfg.get("seed", 42),
        )
        results[strategy] = run_season_simulation(
            env,
            model=None,
            strategy=strategy,
            area_ha=season_cfg.get("area_ha", 0.1),
            dt_min=season_cfg.get("dt_min", 15.0),
            rain_mm_day=season_cfg.get("rain_mm_day", irr_cfg.get("rain_mm_day", 2.5)),
            initial_theta=env.soil.theta_fc,
            initial_ec=irr_cfg.get("initial_ec", 0.1),
            season_days=season_cfg.get("ep_len_days", 90.0),
            verbose=False,
        )

    for strategy, res in results.items():
        _write_csv(
            out_dir / f"season_{strategy.lower()}_timeseries.csv",
            {
                "time_day": res["time_day"],
                "theta": res["theta"],
                "ec_soil": res["ec_soil"],
                "target_ec": res["target_ec"],
                "irrigation_mm_h": res["irrigation_mm_h"],
                "etc_mm_h": res["etc_mm_h"],
                "q_f": res["q_f"],
                "q_a": res["q_a"],
                "event_marker": res["event_marker"],
            },
        )

    stats = {}
    for strategy, res in results.items():
        ec_error = np.abs(res["ec_soil"] - res["target_ec"])
        stats[strategy] = {
            "steps": int(res["total_steps"]),
            "last_day": _safe_last(res["time_day"]),
            "theta_mean": _safe_mean(res["theta"]),
            "theta_final": _safe_last(res["theta"]),
            "ec_soil_mean": _safe_mean(res["ec_soil"]),
            "ec_mae": _safe_mean(ec_error),
            "planned_irrigation_mm": float(res["total_scheduled_irrigation_mm"]),
            "simulated_irrigation_mm": float(res["total_simulated_irrigation_mm"]),
            "total_etc_mm": float(res["total_etc_mm"]),
        }

    t1 = stats["T1"]
    t2 = stats["T2"]
    comparison = {
        "theta_mean_change_pct": (t2["theta_mean"] - t1["theta_mean"]) / (t1["theta_mean"] + 1e-9) * 100.0,
        "ec_mae_change_pct": (t2["ec_mae"] - t1["ec_mae"]) / (t1["ec_mae"] + 1e-9) * 100.0,
        "planned_irrigation_equal": abs(t1["planned_irrigation_mm"] - t2["planned_irrigation_mm"]) < 1e-6,
    }

    _plot_season(results, out_dir / "season_t1_t2.png")
    return {"T1": t1, "T2": t2, "comparison": comparison}


def _plot_short_fixed(arrays: dict[str, np.ndarray], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = arrays["time_hours"]
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    axes[0].plot(t, arrays["theta"], label="theta")
    axes[0].set_ylabel("theta")
    axes[0].grid(alpha=0.25)

    axes[1].plot(t, arrays["ec_soil"], label="EC soil")
    axes[1].plot(t, arrays["target_ec"], "--", label="target EC")
    axes[1].set_ylabel("EC (dS/m)")
    axes[1].legend()
    axes[1].grid(alpha=0.25)

    axes[2].plot(t, arrays["irrigation_mm_h"], label="irrigation")
    axes[2].plot(t, arrays["etc_mm_h"], label="ETc")
    axes[2].set_ylabel("mm/h")
    axes[2].set_xlabel("Time (h)")
    axes[2].legend()
    axes[2].grid(alpha=0.25)

    fig.suptitle("Short fixed-policy simulation")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _plot_season(results: dict[str, dict[str, Any]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    styles = {"T1": "#1f77b4", "T2": "#d62728"}

    for strategy, color in styles.items():
        res = results[strategy]
        t = res["time_day"]
        axes[0].plot(t, res["theta"], color=color, label=strategy)
        axes[1].plot(t, res["ec_soil"], color=color, label=strategy)
        axes[2].plot(t, np.cumsum(res["irrigation_mm_h"]) * 0.25, color=color, label=strategy)

    axes[0].set_ylabel("theta")
    axes[1].set_ylabel("EC (dS/m)")
    axes[2].set_ylabel("Cumulative irrigation (mm)")
    axes[2].set_xlabel("Day")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend()

    fig.suptitle("Seasonal irrigation comparison")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run digital-twin simulation experiment suite.")
    parser.add_argument("--out-dir", default=str(ROOT / "results" / "simulation_suite"))
    parser.add_argument("--stage", default="BULKING", choices=[s.name for s in GrowthStage])
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    stage = GrowthStage[args.stage]
    summary = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "short_fixed_mid": run_short_fixed(stage, out_dir),
        "season_t1_t2": run_season_compare(out_dir),
        "artifacts": {
            "summary": "summary.json",
            "short_csv": "short_fixed_mid_timeseries.csv",
            "short_png": "short_fixed_mid.png",
            "season_t1_csv": "season_t1_timeseries.csv",
            "season_t2_csv": "season_t2_timeseries.csv",
            "season_png": "season_t1_t2.png",
        },
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)

    print(f"Simulation suite complete: {out_dir}")
    print(json.dumps(summary["season_t1_t2"]["comparison"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
