"""数字孪生核心仿真实验批处理脚本。

这个脚本故意和网页端解耦，目的是先做出一套可复现的实验结果。
后续无论写论文、调模型还是接入网页，都可以直接引用这里生成的数据。

当前会输出：

- 单一生育期短期固定策略仿真
- 90 天 T1/T2 季节灌溉制度对比
- CSV 时序数据
- JSON 指标汇总
- PNG 结果图
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # 允许从 experiments/ 子目录直接导入项目根目录下的模型代码。
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from crop_model import GrowthStage
from digital_twin_env import DigitalTwinEnv
from irrigation_schedule import get_irrigation_schedule, run_season_simulation

logger = logging.getLogger(__name__)


def _json_default(value: Any):
    """把 numpy 类型转换成 JSON 可保存的 Python 原生类型。"""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_csv(path: Path, columns: dict[str, Any]) -> None:
    """把同长度的时序列写成 CSV，第一行为字段名。"""
    keys = list(columns.keys())
    rows = zip(*(columns[k] for k in keys))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)


def _safe_mean(values: np.ndarray) -> float:
    """避免空数组导致 mean 报错。"""
    return float(np.mean(values)) if len(values) else 0.0


def _safe_last(values: np.ndarray) -> float:
    """安全读取最后一个值，空数组返回 0。"""
    return float(values[-1]) if len(values) else 0.0


def run_short_fixed(stage: GrowthStage, out_dir: Path, image_dir: Path) -> dict[str, Any]:
    """运行短期固定策略仿真。

    作用：
    - 用 config/simulation.yaml 中的默认环境参数创建 DigitalTwinEnv；
    - 使用 action.fixed_strategy 作为固定施肥/注酸动作；
    - 导出 5 天左右的时序数据和图表。

    注意：
    如果动作过大导致 EC 或 pH 超过安全阈值，环境会提前终止。
    这可以帮助我们发现固定策略是否过于激进。
    """
    cfg = load_config()
    env_cfg = cfg.env()
    short_dt_min = cfg.get("experiment.short_dt_min", env_cfg.get("dt_min", 60.0))
    action = np.array(cfg.action().get("fixed_strategy", [5.0, 1.0]), dtype=np.float32)

    env = DigitalTwinEnv(
        growth_stage=stage,
        area_ha=env_cfg.get("area_ha", 0.1),
        dt_min=short_dt_min,
        ep_len_days=env_cfg.get("ep_len_days", 5.0),
        et0_mm_day=env_cfg.get("et0_mm_day", 5.0),
        seed=env_cfg.get("seed"),
    )

    obs = env.reset()
    done = False
    series: dict[str, list[float]] = {
        # 后续写 CSV 和画图都从这里取数据，避免各处重复记录字段。
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
        # 固定策略实验不使用 SAC，每一步都执行同一个动作。
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
    dt_hours = short_dt_min / 60.0
    ec_error = np.abs(arrays["ec_soil"] - arrays["target_ec"])
    stats = {
        # 这里的指标用于快速判断一个实验是否可用。
        # 更细的时序变化保存在 short_fixed_mid_timeseries.csv。
        "stage": stage.value,
        "dt_min": float(short_dt_min),
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
    short_png = image_dir / "short_fixed_mid.png"
    _plot_short_fixed(arrays, short_png)
    stats["image"] = str(short_png)
    return stats


def run_season_compare(out_dir: Path, image_dir: Path) -> dict[str, Any]:
    """运行 90 天 T1/T2 灌溉制度对比。

    T1：等量灌溉，每次 225 m3/ha；
    T2：按根系分布变化的变量灌溉制度；
    两者计划总灌溉量都为 180 mm，用来比较灌溉时序差异带来的影响。
    """
    cfg = load_config()
    season_cfg = cfg.season_comparison()
    irr_cfg = cfg.irrigation()
    season_dt_min = cfg.get("experiment.season_dt_min", season_cfg.get("dt_min", 15.0))
    schedule = get_irrigation_schedule()

    results = {}
    planned_cumulative = {"T1": [], "T2": []}
    planned_days = [0.0]
    t1_total = 0.0
    t2_total = 0.0
    planned_cumulative["T1"].append(t1_total)
    planned_cumulative["T2"].append(t2_total)
    for event in schedule:
        planned_days.append(float(event.day))
        t1_total += float(event.t1_mm)
        t2_total += float(event.t2_mm)
        planned_cumulative["T1"].append(t1_total)
        planned_cumulative["T2"].append(t2_total)

    for strategy in ("T1", "T2"):
        # 每个策略单独创建环境，保证初始条件一致。
        env = DigitalTwinEnv(
            growth_stage=schedule[0].growth_stage,
            area_ha=season_cfg.get("area_ha", 0.1),
            dt_min=season_dt_min,
            ep_len_days=season_cfg.get("ep_len_days", 90.0),
            et0_mm_day=season_cfg.get("et0_mm_day", 4.0),
            seed=season_cfg.get("seed", 42),
        )
        results[strategy] = run_season_simulation(
            env,
            model=None,
            strategy=strategy,
            area_ha=season_cfg.get("area_ha", 0.1),
            dt_min=season_dt_min,
            rain_mm_day=season_cfg.get("rain_mm_day", irr_cfg.get("rain_mm_day", 2.5)),
            initial_theta=env.soil.theta_fc,
            initial_ec=irr_cfg.get("initial_ec", 0.1),
            season_days=season_cfg.get("ep_len_days", 90.0),
            verbose=False,
        )

    for strategy, res in results.items():
        # 保存完整时序，后续可直接用 Excel、Origin、Python 重新画图。
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
        # 只把论文/报告中最常用的指标放进 summary.json。
        ec_error = np.abs(res["ec_soil"] - res["target_ec"])
        stats[strategy] = {
            "steps": int(res["total_steps"]),
            "dt_min": float(season_dt_min),
            "last_day": _safe_last(res["time_day"]),
            "theta_mean": _safe_mean(res["theta"]),
            "theta_final": _safe_last(res["theta"]),
            "ec_soil_mean": _safe_mean(res["ec_soil"]),
            "ec_mae": _safe_mean(ec_error),
            "planned_irrigation_mm": float(res["total_scheduled_irrigation_mm"]),
            "simulated_irrigation_mm": float(res["total_simulated_irrigation_mm"]),
            "total_etc_mm": float(res["total_etc_mm"]),
        }
        res["total_scheduled_irrigation_mm"] = stats[strategy]["planned_irrigation_mm"]

    t1 = stats["T1"]
    t2 = stats["T2"]
    comparison = {
        # 正值/负值只表示 T2 相对 T1 的变化方向，不直接代表优劣。
        "theta_mean_change_pct": (t2["theta_mean"] - t1["theta_mean"]) / (t1["theta_mean"] + 1e-9) * 100.0,
        "ec_mae_change_pct": (t2["ec_mae"] - t1["ec_mae"]) / (t1["ec_mae"] + 1e-9) * 100.0,
        "planned_irrigation_equal": abs(t1["planned_irrigation_mm"] - t2["planned_irrigation_mm"]) < 1e-6,
    }

    season_png = image_dir / "season_t1_t2.png"
    _plot_season(results, season_png, planned_days, planned_cumulative)
    return {"T1": t1, "T2": t2, "comparison": comparison, "image": str(season_png)}


def _plot_short_fixed(arrays: dict[str, np.ndarray], path: Path) -> None:
    """绘制短期固定策略结果图。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    t = arrays["time_hours"]
    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    for ax in axes:
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)

    axes[0].plot(t, arrays["theta"], color="#333333", linewidth=1.4, label="土壤含水率")
    axes[0].set_ylabel("土壤含水率")

    axes[1].plot(t, arrays["ec_soil"], color="#333333", linewidth=1.4, label="根区EC")
    axes[1].plot(t, arrays["target_ec"], color="#666666", linestyle="--", linewidth=1.0, label="目标EC")
    axes[1].set_ylabel("EC（dS/m）")
    axes[1].legend()

    axes[2].plot(t, arrays["irrigation_mm_h"], color="#333333", linewidth=1.4, label="灌溉强度")
    axes[2].plot(t, arrays["etc_mm_h"], color="#777777", linestyle="-.", linewidth=1.1, label="作物蒸散ETc")
    axes[2].set_ylabel("水量（mm/h）")
    axes[2].set_xlabel("时间（h）")
    axes[2].legend()

    fig.suptitle("短期固定策略仿真", fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _plot_season(
    results: dict[str, dict[str, Any]],
    path: Path,
    planned_days: list[float],
    planned_cumulative: dict[str, list[float]],
) -> None:
    """绘制 T1/T2 季节仿真对比图。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    cfg = load_config()
    soil_cfg = cfg.soil()
    crop_stages = cfg.crop_stages()
    schedule = get_irrigation_schedule()

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    styles = {
        "T1": {"color": "#4e79a7", "linestyle": "-", "marker": "o"},
        "T2": {"color": "#f28e2b", "linestyle": "-", "marker": "s"},
    }
    marker_every = 900

    # 参考作物生育期图，用浅绿色标出最后一次灌溉后的后期阶段。
    shade_start = schedule[-1].day if schedule else 65.0
    for ax in axes:
        ax.axvspan(shade_start, max(planned_days[-1], 90.0), color="#d8f0d2", alpha=0.55)

    for strategy, style in styles.items():
        res = results[strategy]
        t = res["time_day"]
        axes[0].plot(t, res["theta"], color=style["color"], linestyle=style["linestyle"],
                     marker=style["marker"], markevery=marker_every, markersize=3.0,
                     linewidth=1.4, label=strategy)
        axes[1].plot(t, res["ec_soil"], color=style["color"], linestyle=style["linestyle"],
                     marker=style["marker"], markevery=marker_every, markersize=3.0,
                     linewidth=1.4, label=strategy)
        axes[2].step(planned_days, planned_cumulative[strategy], where="post",
                     color=style["color"], linestyle=style["linestyle"], linewidth=1.5,
                     label=strategy)
        axes[2].plot(planned_days, planned_cumulative[strategy], color=style["color"],
                     marker=style["marker"], linestyle="None", markersize=3.4)

    theta_fc = float(soil_cfg.get("theta_fc", 0.334))
    theta_safe_upper = float(soil_cfg.get("theta_safe_upper", 0.38))
    axes[0].axhline(theta_fc, color="#59a14f", linestyle="--", linewidth=1.0, label="田间持水量")
    axes[0].axhline(theta_safe_upper, color="#76b7b2", linestyle=":", linewidth=1.0, label="偏湿参考线")

    target_time = [0.0]
    target_ec = [float(crop_stages.get(schedule[0].growth_stage.value, {}).get("target_ec", 0.8))]
    for event in schedule:
        target_time.extend([event.day, event.day])
        target_ec.extend([target_ec[-1], float(crop_stages.get(event.growth_stage.value, {}).get("target_ec", target_ec[-1]))])
    last_day = max(float(np.max(res["time_day"])) for res in results.values())
    target_time.append(last_day)
    target_ec.append(target_ec[-1])
    axes[1].step(target_time, target_ec, where="post", color="#59a14f",
                 linestyle=":", linewidth=1.4, label="目标EC")

    planned_total = float(results["T1"].get("total_scheduled_irrigation_mm", 180.0))
    axes[2].axhline(planned_total, color="#59a14f", linestyle=":", linewidth=1.2, label="计划总灌溉量")

    axes[0].set_ylabel("土壤含水率")
    axes[1].set_ylabel("EC（dS/m）")
    axes[2].set_ylabel("累计灌溉量（mm）")
    axes[2].set_xlabel("时间（d）")
    axes[0].set_ylim(bottom=0.32)
    axes[1].set_ylim(bottom=0.0)
    axes[2].set_ylim(bottom=0.0)
    axes[0].text(shade_start + 1.0, axes[0].get_ylim()[1] * 0.995,
                 "后期阶段", ha="left", va="top", fontsize=9, color="#2f6b2f")
    for ax in axes:
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)
        ax.legend()

    fig.suptitle("季节尺度灌溉策略对比", fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Run digital-twin simulation experiment suite.")
    parser.add_argument("--out-dir", default=str(ROOT / "results" / "simulation_suite"))
    parser.add_argument("--stage", default="BULKING", choices=[s.name for s in GrowthStage])
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = ROOT / "experiments" / "images" / "simulation_suite" / run_id
    image_dir.mkdir(parents=True, exist_ok=True)

    stage = GrowthStage[args.stage]
    summary = {
        # summary.json 是本次实验的总入口，记录生成时间、指标和文件名。
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "short_fixed_mid": run_short_fixed(stage, out_dir, image_dir),
        "season_t1_t2": run_season_compare(out_dir, image_dir),
        "artifacts": {
            "summary": "summary.json",
            "short_csv": "short_fixed_mid_timeseries.csv",
            "image_dir": str(image_dir),
            "short_png": str(image_dir / "short_fixed_mid.png"),
            "season_t1_csv": "season_t1_timeseries.csv",
            "season_t2_csv": "season_t2_timeseries.csv",
            "season_png": str(image_dir / "season_t1_t2.png"),
        },
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        # ensure_ascii=False 让中文字段在 JSON 中保持可读。
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)

    logger.info("Simulation suite complete: %s", out_dir)
    logger.info("Images saved to: %s", image_dir)
    logger.info(
        "Season comparison:\n%s",
        json.dumps(summary["season_t1_t2"]["comparison"], ensure_ascii=False, indent=2),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
