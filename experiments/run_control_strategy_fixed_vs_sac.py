"""固定策略与 SAC 控制策略离线仿真对比。

这是 SAC 田间测试前的第一步：先在数字孪生环境中离线比较。

实验内容：
- 使用同一个马铃薯生育阶段、同样的初始条件；
- 分别运行固定水肥策略和已训练 SAC 模型；
- 默认使用单次控制事件；传入 --continuous-control 时持续供水并在白天连续追踪目标；
- 输出 theta、EC、灌溉强度、控制动作对比图；
- 导出 CSV 与 summary.json，便于后续分析。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from sac_model_registry import get_stage_model_path
from crop_model import GrowthStage
from digital_twin_env import DigitalTwinEnv
from irrigation_schedule import normalize_obs
from plot_utils import set_time_axis_origin

logger = logging.getLogger(__name__)


STAGE_MAP = {
    "INI": GrowthStage.EMERGENCE,
    "DEV": GrowthStage.TUBER_INIT,
    "MID": GrowthStage.BULKING,
    "LATE": GrowthStage.STARCH_ACCUMULATION,
}


def _json_default(value: Any):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_csv(path: Path, columns: dict[str, list[float]]) -> None:
    keys = list(columns.keys())
    rows = zip(*(columns[k] for k in keys))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)


def _load_sac_model(model_path: Path):
    try:
        from stable_baselines3 import SAC
    except ImportError as exc:
        raise RuntimeError("需要安装 stable-baselines3 才能运行 SAC 对比实验。") from exc

    if model_path.suffix == ".zip":
        load_path = model_path.with_suffix("")
    else:
        load_path = model_path
    if not Path(str(load_path) + ".zip").exists():
        raise FileNotFoundError(f"SAC 模型不存在: {load_path}.zip")
    return SAC.load(str(load_path))


def _make_env(
    stage: GrowthStage,
    dt_min: float,
    duration_days: float,
    et0_mm_day: float,
    seed: int | None,
    soil_model: str,
):
    cfg = load_config()
    env_cfg = cfg.env()
    return DigitalTwinEnv(
        growth_stage=stage,
        area_ha=env_cfg.get("area_ha", 0.1),
        dt_min=dt_min,
        ep_len_days=duration_days,
        et0_mm_day=et0_mm_day,
        seed=seed,
        soil_model=soil_model,
    )


def run_policy(
    name: str,
    stage: GrowthStage,
    dt_min: float,
    duration_days: float,
    event_start_hour: float,
    event_hours: float,
    et0_mm_day: float,
    seed: int | None,
    soil_model: str = "lumped_v1",
    continuous_control: bool = False,
    model=None,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    """运行单个策略并返回时序数据与统计指标。"""
    cfg = load_config()
    irr_cfg = cfg.irrigation()
    fixed_action = np.array(cfg.action().get("fixed_strategy", [1.0, 0.0]), dtype=np.float32)
    env = _make_env(stage, dt_min, duration_days, et0_mm_day, seed, soil_model)
    obs = env.reset()
    dt_hours = dt_min / 60.0
    total_steps = int(round(duration_days * 24.0 / dt_hours))
    event_start_step = int(round(event_start_hour / dt_hours))
    event_end_step = event_start_step + int(round(event_hours / dt_hours))
    rain_mm_h = float(irr_cfg.get("rain_mm_day", 0.0)) / 24.0

    series: dict[str, list[float]] = {
        "time_hours": [],
        "theta": [],
        "ec_soil": [],
        "target_ec": [],
        "ec_drip": [],
        "ph_drip": [],
        "ec_set": [],
        "ph_set": [],
        "irrigation_mm_h": [],
        "etc_mm_h": [],
        "q_f": [],
        "q_a": [],
        "burn": [],
        "event_marker": [],
    }

    stopped_by_safety = False
    for step in range(total_steps):
        in_event = continuous_control or event_start_step <= step < event_end_step
        action_for_record = fixed_action.copy()
        if in_event:
            if model is None:
                action_for_record = fixed_action.copy()
            else:
                # SAC 训练时使用归一化观测，这里必须先归一化再 predict。
                action_for_record, _ = model.predict(normalize_obs(obs), deterministic=True)

            obs, _reward, done, info = env.step(action_for_record)
            if done and info.get("burn"):
                # 安全评估模式：记录 burn，但不让整段 5 天评估提前结束。
                # 后续改为 dry_step，观察系统恢复过程。
                stopped_by_safety = True
                if not continuous_control:
                    event_end_step = step + 1
                env._done = False
        else:
            obs, _reward, done, info = env.dry_step(rain_mm_h=rain_mm_h)

        series["time_hours"].append(float(info["time_day"] * 24.0))
        series["theta"].append(float(info["theta"]))
        series["ec_soil"].append(float(info["ec_soil"]))
        series["target_ec"].append(float(info["target_ec"]))
        series["ec_drip"].append(float(info["ec_drip"]))
        series["ph_drip"].append(float(info["ph_drip"]))
        series["ec_set"].append(float(info.get("ec_set", action_for_record[0])))
        series["ph_set"].append(float(info.get("ph_set", action_for_record[1])))
        series["irrigation_mm_h"].append(float(info["irrigation_mm_h"]))
        series["etc_mm_h"].append(float(info["etc_mm_h"]))
        series["q_f"].append(float(info["q_f"]))
        series["q_a"].append(float(info["q_a"]))
        series["burn"].append(1.0 if info.get("burn") else 0.0)
        # 配液设定 EC/pH 仅在允许注肥注酸的白天评价；夜间虽然持续供水，但不追踪配液设定。
        target_active = in_event and not bool(info.get("is_night", False))
        series["event_marker"].append(1.0 if target_active else 0.0)

    theta = np.array(series["theta"], dtype=float)
    ec_soil = np.array(series["ec_soil"], dtype=float)
    ec_target = np.array(series["target_ec"], dtype=float)
    ec_drip = np.array(series["ec_drip"], dtype=float)
    ph_drip = np.array(series["ph_drip"], dtype=float)
    ec_set = np.array(series["ec_set"], dtype=float)
    ph_set = np.array(series["ph_set"], dtype=float)
    event_mask = np.array(series["event_marker"], dtype=float) > 0.5
    irrigation = np.array(series["irrigation_mm_h"], dtype=float)
    q_f = np.array(series["q_f"], dtype=float)
    q_a = np.array(series["q_a"], dtype=float)
    stats = {
        "policy": name,
        "soil_model": env.soil_model,
        "parameter_status": info.get("parameter_status", "unknown"),
        "steps": len(series["time_hours"]),
        "duration_hours": float(series["time_hours"][-1]) if series["time_hours"] else 0.0,
        "event_start_hour": event_start_hour,
        "event_hours_requested": event_hours,
        "event_hours_effective": float(event_mask.sum() * dt_hours),
        "continuous_control": continuous_control,
        "stopped_by_safety": stopped_by_safety,
        "theta_mean": float(theta.mean()) if len(theta) else 0.0,
        "theta_final": float(theta[-1]) if len(theta) else 0.0,
        # 土壤 EC 是根区长期状态，单次控制事件后不要求立即达到灌溉液目标。
        "root_zone_ec_mae": float(np.abs(ec_soil - ec_target).mean()) if len(ec_soil) else 0.0,
        "root_zone_ec_final_error": float(abs(ec_soil[-1] - ec_target[-1])) if len(ec_soil) else 0.0,
        "soil_ec_final": float(ec_soil[-1]) if len(ec_soil) else 0.0,
        # 出口 EC/pH 只在注肥、注酸控制事件内评价；事件结束后回到清水不计入误差。
        "event_ec_drip_mae": float(np.abs(ec_drip[event_mask] - ec_set[event_mask]).mean()) if event_mask.any() else 0.0,
        "event_ec_drip_final": float(ec_drip[event_mask][-1]) if event_mask.any() else 0.0,
        "outlet_ph_mae_during_events": float(np.abs(ph_drip[event_mask] - ph_set[event_mask]).mean()) if event_mask.any() else 0.0,
        "outlet_ph_final_during_events": float(ph_drip[event_mask][-1]) if event_mask.any() else 0.0,
        "ec_set_mean_during_events": float(ec_set[event_mask].mean()) if event_mask.any() else 0.0,
        "ph_set_mean_during_events": float(ph_set[event_mask].mean()) if event_mask.any() else 0.0,
        "total_irrigation_mm": float(irrigation.sum() * dt_hours),
        "q_f_mean": float(q_f.mean()) if len(q_f) else 0.0,
        "q_a_mean": float(q_a.mean()) if len(q_a) else 0.0,
        "burn_count": int(np.sum(series["burn"])),
    }
    return series, stats


def plot_root_zone_ec_tracking(
    fixed: dict[str, list[float]],
    sac: dict[str, list[float]],
    path: Path,
) -> None:
    """绘制根区 EC 跟踪主图。

    这张图只回答一个问题：SAC 是否让根区 EC 更接近模型设定 EC 参考。
    出口 EC、pH 和控制动作属于执行层诊断，放在完整对比图里。
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(8, 4.2))
    fixed_t = np.array(fixed["time_hours"], dtype=float)
    sac_t = np.array(sac["time_hours"], dtype=float)
    marker = np.array(fixed.get("event_marker", []), dtype=float) > 0.5

    if len(marker) and len(fixed_t):
        starts = np.flatnonzero(marker & ~np.r_[False, marker[:-1]])
        ends = np.flatnonzero(marker & ~np.r_[marker[1:], False])
        for index, (start, end) in enumerate(zip(starts, ends)):
            ax.axvspan(
                fixed_t[start],
                fixed_t[end],
                color="#d8f0d2",
                alpha=0.28,
                label="目标追踪时段" if index == 0 else None,
            )

    ax.plot(
        fixed_t,
        fixed["ec_soil"],
        color="#4e79a7",
        linestyle="--",
        marker="o",
        markevery=12,
        markersize=3.2,
        linewidth=1.7,
        label="固定策略",
        zorder=4,
    )
    ax.plot(
        sac_t,
        sac["ec_soil"],
        color="#f28e2b",
        linestyle="-",
        marker="s",
        markevery=12,
        markersize=3.2,
        linewidth=1.5,
        alpha=0.88,
        label="SAC策略",
        zorder=3,
    )
    ax.step(
        fixed_t,
        fixed["target_ec"],
        where="post",
        color="#2f7d32",
        linestyle="--",
        linewidth=1.8,
        label="模型设定EC参考",
        zorder=2,
    )

    set_time_axis_origin([ax], fixed_t, sac_t)
    ax.set_title("根区 EC 跟踪效果对比", fontsize=13)
    ax.set_xlabel("时间（h）")
    ax.set_ylabel("根区EC（dS/m）")
    ax.set_ylim(bottom=0.0)
    ax.grid(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(direction="out", length=4, width=1)
    ax.legend(loc="best")

    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def plot_delivery_execution(
    fixed: dict[str, list[float]],
    sac: dict[str, list[float]],
    path: Path,
) -> None:
    """绘制配液执行效果辅助图。

    用于检查 SAC 的出口 EC、出口 pH 和 q_f/q_a 动作是否平滑、可执行。
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(4, 1, figsize=(8, 8.5), sharex=True)
    fixed_t = np.array(fixed["time_hours"], dtype=float)
    sac_t = np.array(sac["time_hours"], dtype=float)
    marker = np.array(fixed.get("event_marker", []), dtype=float) > 0.5

    if len(marker) and len(fixed_t):
        starts = np.flatnonzero(marker & ~np.r_[False, marker[:-1]])
        ends = np.flatnonzero(marker & ~np.r_[marker[1:], False])
        for ax in axes:
            for index, (start, end) in enumerate(zip(starts, ends)):
                ax.axvspan(
                    fixed_t[start],
                    fixed_t[end],
                    color="#d8f0d2",
                    alpha=0.24,
                    label="目标追踪时段" if index == 0 else None,
                )

    styles = {
        "固定策略": (fixed, fixed_t, "#4e79a7", "--", "o", 0.95, 4, 1.6),
        "SAC策略": (sac, sac_t, "#f28e2b", "-", "s", 0.86, 3, 1.4),
    }
    for label, (series, t, color, linestyle, marker_style, alpha, zorder, linewidth) in styles.items():
        axes[0].plot(
            t, series["ec_drip"], color=color, linestyle=linestyle, marker=marker_style,
            markevery=12, markersize=3.0, linewidth=linewidth, alpha=alpha, zorder=zorder, label=label
        )
        axes[1].plot(
            t, series["ph_drip"], color=color, linestyle=linestyle, marker=marker_style,
            markevery=12, markersize=3.0, linewidth=linewidth, alpha=alpha, zorder=zorder, label=label
        )
        axes[2].plot(
            t, series["q_f"], color=color, linestyle=linestyle, marker=marker_style,
            markevery=12, markersize=3.0, linewidth=linewidth, alpha=alpha, zorder=zorder, label=label
        )
        axes[3].plot(
            t, series["q_a"], color=color, linestyle=linestyle, marker=marker_style,
            markevery=12, markersize=3.0, linewidth=linewidth, alpha=alpha, zorder=zorder, label=label
        )

    target_ec_event = np.where(marker, np.array(fixed["ec_set"], dtype=float), np.nan)
    target_ph_event = np.where(marker, np.array(fixed["ph_set"], dtype=float), np.nan)
    axes[0].plot(fixed_t, target_ec_event, color="#2f7d32", linestyle="--", linewidth=1.4, label="配液设定EC")
    axes[1].plot(fixed_t, target_ph_event, color="#2f7d32", linestyle="--", linewidth=1.4, label="配液设定pH")

    axes[0].set_title("配液执行效果对比", fontsize=13)
    axes[0].set_ylabel("出口EC（dS/m）")
    axes[1].set_ylabel("出口pH")
    axes[2].set_ylabel("肥料母液 q_f（L/min）")
    axes[3].set_ylabel("酸液 q_a（L/min）")
    axes[3].set_xlabel("时间（h）")
    axes[0].set_ylim(bottom=0.0)
    axes[2].set_ylim(bottom=0.0)
    axes[3].set_ylim(bottom=0.0)

    set_time_axis_origin(axes, fixed_t, sac_t)
    for ax in axes:
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)
        ax.legend(loc="best")

    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    env_cfg = cfg.env()

    parser = argparse.ArgumentParser(description="Run fixed-policy vs SAC offline simulation.")
    parser.add_argument("--stage", default="MID", choices=list(STAGE_MAP.keys()))
    parser.add_argument("--model", default=str(get_stage_model_path("mid")))
    parser.add_argument("--duration-days", type=float, default=float(env_cfg.get("ep_len_days", 5.0)))
    parser.add_argument("--event-start-hour", type=float, default=8.0)
    parser.add_argument("--event-hours", type=float, default=2.0)
    parser.add_argument(
        "--continuous-control",
        action="store_true",
        help="持续供水并在每个白天控制步输出动作，匹配 SAC 训练场景。",
    )
    parser.add_argument("--dt-min", type=float, default=float(env_cfg.get("dt_min", 60.0)))
    parser.add_argument("--et0", type=float, default=float(env_cfg.get("et0_mm_day", 5.0)))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--soil-model",
        choices=["lumped_v1", "layered_v2"],
        default="lumped_v1",
        help="固定策略与 SAC 必须使用同一个土壤模型进行公平对比。",
    )
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_dir = ROOT / "results" / "control_strategy_fixed_vs_sac" / run_id
    image_dir = ROOT / "experiments" / "images" / "control_strategy_fixed_vs_sac" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    stage = STAGE_MAP[args.stage]
    model = _load_sac_model(Path(args.model))

    fixed_series, fixed_stats = run_policy(
        "fixed", stage, args.dt_min, args.duration_days, args.event_start_hour,
        args.event_hours, args.et0, args.seed, args.soil_model,
        args.continuous_control, model=None
    )
    sac_series, sac_stats = run_policy(
        "sac", stage, args.dt_min, args.duration_days, args.event_start_hour,
        args.event_hours, args.et0, args.seed, args.soil_model,
        args.continuous_control, model=model
    )

    _write_csv(out_dir / "fixed_timeseries.csv", fixed_series)
    _write_csv(out_dir / "sac_timeseries.csv", sac_series)
    root_zone_ec_path = image_dir / "root_zone_ec_tracking.png"
    delivery_execution_path = image_dir / "delivery_execution.png"
    plot_root_zone_ec_tracking(fixed_series, sac_series, root_zone_ec_path)
    plot_delivery_execution(fixed_series, sac_series, delivery_execution_path)

    summary = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stage": args.stage,
        "model": str(Path(args.model)),
        "soil_model": args.soil_model,
        "dt_min": args.dt_min,
        "duration_days": args.duration_days,
        "event_start_hour": args.event_start_hour,
        "event_hours": args.event_hours,
        "continuous_control": args.continuous_control,
        "et0_mm_day": args.et0,
        "fixed": fixed_stats,
        "sac": sac_stats,
        "comparison": {
            "root_zone_ec_mae_change_pct": (
                (sac_stats["root_zone_ec_mae"] - fixed_stats["root_zone_ec_mae"])
                / (fixed_stats["root_zone_ec_mae"] + 1e-9) * 100.0
            ),
            "outlet_ec_mae_change_pct": (
                (sac_stats["event_ec_drip_mae"] - fixed_stats["event_ec_drip_mae"])
                / (fixed_stats["event_ec_drip_mae"] + 1e-9) * 100.0
            ),
            "irrigation_change_pct": (
                (sac_stats["total_irrigation_mm"] - fixed_stats["total_irrigation_mm"])
                / (fixed_stats["total_irrigation_mm"] + 1e-9) * 100.0
            ),
            "outlet_ph_mae_change_pct": (
                (sac_stats["outlet_ph_mae_during_events"] - fixed_stats["outlet_ph_mae_during_events"])
                / (fixed_stats["outlet_ph_mae_during_events"] + 1e-9) * 100.0
            ),
        },
        "artifacts": {
            "summary": "summary.json",
            "fixed_csv": "fixed_timeseries.csv",
            "sac_csv": "sac_timeseries.csv",
            "image_dir": str(image_dir),
            "root_zone_ec_png": str(root_zone_ec_path),
            "delivery_execution_png": str(delivery_execution_path),
        },
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)

    logger.info("Fixed vs SAC complete: %s", out_dir)
    logger.info("Root-zone EC image saved to: %s", root_zone_ec_path)
    logger.info("Delivery execution image saved to: %s", delivery_execution_path)
    logger.info("根区 EC MAE: fixed=%.4f, sac=%.4f", fixed_stats["root_zone_ec_mae"], sac_stats["root_zone_ec_mae"])
    logger.info("事件内出口 EC MAE: fixed=%.4f, sac=%.4f", fixed_stats["event_ec_drip_mae"], sac_stats["event_ec_drip_mae"])
    logger.info(
        "事件内出口 pH MAE: fixed=%.4f, sac=%.4f",
        fixed_stats["outlet_ph_mae_during_events"],
        sac_stats["outlet_ph_mae_during_events"],
    )
    logger.info("Irrigation: fixed=%.2f mm, sac=%.2f mm", fixed_stats["total_irrigation_mm"], sac_stats["total_irrigation_mm"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
