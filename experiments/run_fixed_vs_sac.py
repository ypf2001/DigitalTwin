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
from crop_model import GrowthStage
from digital_twin_env import DigitalTwinEnv
from irrigation_schedule import normalize_obs

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


def _make_env(stage: GrowthStage, dt_min: float, duration_days: float, et0_mm_day: float, seed: int | None):
    cfg = load_config()
    env_cfg = cfg.env()
    return DigitalTwinEnv(
        growth_stage=stage,
        area_ha=env_cfg.get("area_ha", 0.1),
        dt_min=dt_min,
        ep_len_days=duration_days,
        et0_mm_day=et0_mm_day,
        seed=seed,
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
    continuous_control: bool = False,
    model=None,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    """运行单个策略并返回时序数据与统计指标。"""
    cfg = load_config()
    irr_cfg = cfg.irrigation()
    fixed_action = np.array(cfg.action().get("fixed_strategy", [5.0, 1.0]), dtype=np.float32)
    env = _make_env(stage, dt_min, duration_days, et0_mm_day, seed)
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
        if in_event:
            if model is None:
                action = fixed_action.copy()
            else:
                # SAC 训练时使用归一化观测，这里必须先归一化再 predict。
                action, _ = model.predict(normalize_obs(obs), deterministic=True)

            obs, _reward, done, info = env.step(action)
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
        series["irrigation_mm_h"].append(float(info["irrigation_mm_h"]))
        series["etc_mm_h"].append(float(info["etc_mm_h"]))
        series["q_f"].append(float(info["q_f"]))
        series["q_a"].append(float(info["q_a"]))
        series["burn"].append(1.0 if info.get("burn") else 0.0)
        # 目标 EC/pH 仅在允许注肥注酸的白天评价；夜间虽然持续供水，但不追踪配液目标。
        target_active = in_event and not bool(info.get("is_night", False))
        series["event_marker"].append(1.0 if target_active else 0.0)

    theta = np.array(series["theta"], dtype=float)
    ec_soil = np.array(series["ec_soil"], dtype=float)
    ec_target = np.array(series["target_ec"], dtype=float)
    ec_drip = np.array(series["ec_drip"], dtype=float)
    ph_drip = np.array(series["ph_drip"], dtype=float)
    event_mask = np.array(series["event_marker"], dtype=float) > 0.5
    irrigation = np.array(series["irrigation_mm_h"], dtype=float)
    q_f = np.array(series["q_f"], dtype=float)
    q_a = np.array(series["q_a"], dtype=float)
    ph_target = float(load_config().reward().get("pH_target", 6.0))
    stats = {
        "policy": name,
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
        "soil_ec_mae": float(np.abs(ec_soil - ec_target).mean()) if len(ec_soil) else 0.0,
        "soil_ec_final": float(ec_soil[-1]) if len(ec_soil) else 0.0,
        # 出口 EC/pH 只在注肥、注酸控制事件内评价；事件结束后回到清水不计入误差。
        "event_ec_drip_mae": float(np.abs(ec_drip[event_mask] - ec_target[event_mask]).mean()) if event_mask.any() else 0.0,
        "event_ec_drip_final": float(ec_drip[event_mask][-1]) if event_mask.any() else 0.0,
        "event_ph_mae": float(np.abs(ph_drip[event_mask] - ph_target).mean()) if event_mask.any() else 0.0,
        "event_ph_final": float(ph_drip[event_mask][-1]) if event_mask.any() else 0.0,
        "total_irrigation_mm": float(irrigation.sum() * dt_hours),
        "q_f_mean": float(q_f.mean()) if len(q_f) else 0.0,
        "q_a_mean": float(q_a.mean()) if len(q_a) else 0.0,
        "burn_count": int(np.sum(series["burn"])),
    }
    return series, stats


def plot_comparison(
    fixed: dict[str, list[float]],
    sac: dict[str, list[float]],
    path: Path,
    continuous_control: bool = False,
) -> None:
    """绘制固定策略与 SAC 对比图。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(6, 1, figsize=(8, 12.5), sharex=True)
    fig.suptitle("固定策略与 SAC 控制策略对比", fontsize=13)
    marker_every = 12
    styles = {
        "固定策略": (fixed, "#4e79a7", "o"),
        "SAC策略": (sac, "#f28e2b", "s"),
    }

    marker = np.array(fixed.get("event_marker", []), dtype=float) > 0.5
    t_marker = np.array(fixed.get("time_hours", []), dtype=float)
    if len(marker) and len(t_marker):
        starts = np.flatnonzero(marker & ~np.r_[False, marker[:-1]])
        ends = np.flatnonzero(marker & ~np.r_[marker[1:], False])
        for ax in axes:
            for index, (start, end) in enumerate(zip(starts, ends)):
                ax.axvspan(
                    t_marker[start] - (t_marker[0] if len(t_marker) else 0.0),
                    t_marker[end],
                    color="#d8f0d2",
                    alpha=0.45,
                    label="目标追踪时段" if index == 0 else None,
                )

    for label, (series, color, marker) in styles.items():
        t = np.array(series["time_hours"], dtype=float)
        axes[0].plot(t, series["theta"], color=color, marker=marker, markevery=marker_every,
                     markersize=3.0, linewidth=1.4, label=label)
        axes[1].plot(t, series["ec_soil"], color=color, marker=marker, markevery=marker_every,
                     markersize=3.0, linewidth=1.4, label=label)
        event_mask = np.array(series["event_marker"], dtype=float) > 0.5
        ec_drip = np.array(series["ec_drip"], dtype=float)
        ph_drip = np.array(series["ph_drip"], dtype=float)
        ec_drip_plot = ec_drip if continuous_control else np.where(event_mask, ec_drip, np.nan)
        ph_drip_plot = ph_drip if continuous_control else np.where(event_mask, ph_drip, np.nan)
        axes[2].plot(t, ec_drip_plot, color=color, marker=marker, markevery=marker_every,
                     markersize=3.0, linewidth=1.4, label=label)
        axes[3].plot(t, ph_drip_plot, color=color, marker=marker, markevery=marker_every,
                     markersize=3.0, linewidth=1.4, label=label)
        axes[4].plot(t, series["irrigation_mm_h"], color=color, marker=marker, markevery=marker_every,
                     markersize=3.0, linewidth=1.4, label=label)
        axes[5].plot(t, series["q_f"], color=color, marker=marker, markevery=marker_every,
                     markersize=3.0, linewidth=1.4, label=f"{label} 肥液")

    t_ref = np.array(fixed["time_hours"], dtype=float)
    fixed_event_mask = np.array(fixed["event_marker"], dtype=float) > 0.5
    target_ec_event = np.where(fixed_event_mask, np.array(fixed["target_ec"], dtype=float), np.nan)
    axes[2].plot(t_ref, target_ec_event, color="#59a14f", linestyle="--", linewidth=1.2, label="目标出口EC")
    ph_target = float(load_config().reward().get("pH_target", 6.0))
    target_ph_event = np.where(fixed_event_mask, ph_target, np.nan)
    axes[3].plot(t_ref, target_ph_event, color="#59a14f", linestyle="--", linewidth=1.2, label="目标出口pH")
    axes[5].plot(t_ref, fixed["q_a"], color="#4e79a7", linestyle=":", linewidth=1.0, label="固定策略 酸液")
    axes[5].plot(np.array(sac["time_hours"], dtype=float), sac["q_a"], color="#f28e2b", linestyle=":", linewidth=1.0, label="SAC策略 酸液")

    axes[0].set_ylabel("土壤含水率")
    axes[1].set_ylabel("根区EC（dS/m）")
    axes[2].set_ylabel("出口EC（dS/m）")
    axes[3].set_ylabel("出口pH")
    axes[4].set_ylabel("灌溉强度（mm/h）")
    axes[5].set_ylabel("流量（L/min）")
    axes[5].set_xlabel("时间（h）")
    axes[1].set_ylim(bottom=0.0)
    axes[2].set_ylim(bottom=0.0)
    axes[4].set_ylim(bottom=0.0)
    axes[5].set_ylim(bottom=0.0)

    # 时间轴从原点开始，避免 Matplotlib 默认边距让 0 h 刻度偏离纵轴。
    all_times = np.concatenate(
        [
            np.asarray(fixed.get("time_hours", []), dtype=float),
            np.asarray(sac.get("time_hours", []), dtype=float),
        ]
    )
    time_max = float(all_times.max()) if len(all_times) else 0.0
    for ax in axes:
        ax.set_xlim(left=0.0, right=time_max if time_max > 0.0 else None)
        ax.margins(x=0.0)
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)
        ax.legend(loc="best")

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    env_cfg = cfg.env()

    parser = argparse.ArgumentParser(description="Run fixed-policy vs SAC offline simulation.")
    parser.add_argument("--stage", default="MID", choices=list(STAGE_MAP.keys()))
    parser.add_argument("--model", default=str(ROOT / "rl_models" / "sac_mid_final"))
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
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_dir = ROOT / "results" / "fixed_vs_sac" / run_id
    image_dir = ROOT / "experiments" / "images" / "fixed_vs_sac" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    stage = STAGE_MAP[args.stage]
    model = _load_sac_model(Path(args.model))

    fixed_series, fixed_stats = run_policy(
        "fixed", stage, args.dt_min, args.duration_days, args.event_start_hour,
        args.event_hours, args.et0, args.seed, args.continuous_control, model=None
    )
    sac_series, sac_stats = run_policy(
        "sac", stage, args.dt_min, args.duration_days, args.event_start_hour,
        args.event_hours, args.et0, args.seed, args.continuous_control, model=model
    )

    _write_csv(out_dir / "fixed_timeseries.csv", fixed_series)
    _write_csv(out_dir / "sac_timeseries.csv", sac_series)
    image_path = image_dir / "fixed_vs_sac.png"
    plot_comparison(fixed_series, sac_series, image_path, continuous_control=args.continuous_control)

    summary = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stage": args.stage,
        "model": str(Path(args.model)),
        "dt_min": args.dt_min,
        "duration_days": args.duration_days,
        "event_start_hour": args.event_start_hour,
        "event_hours": args.event_hours,
        "continuous_control": args.continuous_control,
        "et0_mm_day": args.et0,
        "fixed": fixed_stats,
        "sac": sac_stats,
        "comparison": {
            "ec_mae_change_pct": (
                (sac_stats["event_ec_drip_mae"] - fixed_stats["event_ec_drip_mae"])
                / (fixed_stats["event_ec_drip_mae"] + 1e-9) * 100.0
            ),
            "irrigation_change_pct": (
                (sac_stats["total_irrigation_mm"] - fixed_stats["total_irrigation_mm"])
                / (fixed_stats["total_irrigation_mm"] + 1e-9) * 100.0
            ),
            "ph_mae_change_pct": (
                (sac_stats["event_ph_mae"] - fixed_stats["event_ph_mae"])
                / (fixed_stats["event_ph_mae"] + 1e-9) * 100.0
            ),
        },
        "artifacts": {
            "summary": "summary.json",
            "fixed_csv": "fixed_timeseries.csv",
            "sac_csv": "sac_timeseries.csv",
            "image_dir": str(image_dir),
            "png": str(image_path),
        },
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)

    logger.info("Fixed vs SAC complete: %s", out_dir)
    logger.info("Image saved to: %s", image_path)
    logger.info("事件内出口 EC MAE: fixed=%.4f, sac=%.4f", fixed_stats["event_ec_drip_mae"], sac_stats["event_ec_drip_mae"])
    logger.info("事件内出口 pH MAE: fixed=%.4f, sac=%.4f", fixed_stats["event_ph_mae"], sac_stats["event_ph_mae"])
    logger.info("Irrigation: fixed=%.2f mm, sac=%.2f mm", fixed_stats["total_irrigation_mm"], sac_stats["total_irrigation_mm"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
