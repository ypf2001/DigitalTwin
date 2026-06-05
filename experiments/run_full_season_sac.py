"""Full-season SAC fertigation simulation.

This experiment evaluates SAC as a water-fertilizer control strategy across the
whole potato season. The irrigation calendar is still the T2 irrigation regime
from the literature; SAC outputs EC/pH setpoints during each irrigation event,
and the execution layer converts those setpoints to fertilizer/acid flows.
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
from digital_twin_env import DigitalTwinEnv
from irrigation_schedule import (
    event_duration_hours,
    get_irrigation_schedule,
    normalize_obs,
)
from plot_utils import set_time_axis_origin

logger = logging.getLogger(__name__)


STAGE_TAGS = {
    "emergence": "ini",
    "vegetative": "dev",
    "tuber_init": "dev",
    "bulking": "mid",
    "starch_accumulation": "late",
    "maturation": "late",
}


def _json_default(value: Any):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_csv(path: Path, columns: dict[str, list[float] | list[str]]) -> None:
    keys = list(columns.keys())
    rows = zip(*(columns[k] for k in keys))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)


def _load_sac_class():
    try:
        from stable_baselines3 import SAC
    except ImportError as exc:
        raise RuntimeError("需要安装 stable-baselines3 才能运行 SAC 全生育期仿真。") from exc
    return SAC


class StageModelBank:
    """Lazy loader for one SAC model per simplified growth-stage tag."""

    def __init__(self, model_dir: Path, single_model: Path | None = None):
        self._sac_cls = _load_sac_class()
        self.model_paths: dict[str, Path] = {}
        self.loaded: dict[str, Any] = {}

        if single_model is not None:
            base = self._strip_zip(single_model)
            for tag in ("ini", "dev", "mid", "late"):
                self.model_paths[tag] = base
        else:
            for tag in ("ini", "dev", "mid", "late"):
                candidate = model_dir / f"sac_{tag}_final"
                if candidate.with_suffix(".zip").exists():
                    self.model_paths[tag] = candidate

    @staticmethod
    def _strip_zip(path: Path) -> Path:
        return path.with_suffix("") if path.suffix == ".zip" else path

    def require_available(self) -> None:
        if not self.model_paths:
            raise FileNotFoundError("没有找到 SAC 模型。请传入 --model，或训练 sac_ini/dev/mid/late_final。")
        missing = [tag for tag, path in self.model_paths.items() if not path.with_suffix(".zip").exists()]
        if missing:
            joined = ", ".join(f"{tag}: {self.model_paths[tag]}.zip" for tag in missing)
            raise FileNotFoundError(f"SAC 模型不存在: {joined}")

    def action(self, obs: np.ndarray, tag: str) -> np.ndarray:
        if tag not in self.model_paths:
            # If only part of the season has trained models, fall back to the
            # first available model so the simulation can still run explicitly.
            fallback_tag = sorted(self.model_paths)[0]
            tag = fallback_tag
        if tag not in self.loaded:
            model_path = self.model_paths[tag]
            self.loaded[tag] = self._sac_cls.load(str(model_path))
            logger.info("加载 SAC 模型: %s.zip", model_path)
        action, _ = self.loaded[tag].predict(normalize_obs(obs), deterministic=True)
        return np.asarray(action, dtype=np.float32)


def _make_env(area_ha: float, dt_min: float, season_days: float, et0: float, seed: int | None) -> DigitalTwinEnv:
    schedule = get_irrigation_schedule()
    return DigitalTwinEnv(
        growth_stage=schedule[0].growth_stage,
        area_ha=area_ha,
        dt_min=dt_min,
        ep_len_days=season_days,
        et0_mm_day=et0,
        seed=seed,
    )


def _record(series: dict[str, list[Any]], info: dict[str, Any], action: np.ndarray, stage_tag: str, event_idx: int, is_event: bool) -> None:
    series["time_day"].append(float(info["time_day"]))
    series["theta"].append(float(info["theta"]))
    series["ec_soil"].append(float(info["ec_soil"]))
    series["target_ec"].append(float(info["target_ec"]))
    series["ec_drip"].append(float(info["ec_drip"]))
    series["ph_drip"].append(float(info.get("ph_drip", 7.0)))
    series["irrigation_mm_h"].append(float(info["irrigation_mm_h"]))
    series["etc_mm_h"].append(float(info["etc_mm_h"]))
    series["ec_set"].append(float(info.get("ec_set", action[0] if len(action) else 0.0)))
    series["ph_set"].append(float(info.get("ph_set", action[1] if len(action) > 1 else 7.0)))
    series["q_f"].append(float(info.get("q_f", 0.0)))
    series["q_a"].append(float(info.get("q_a", 0.0)))
    series["stage_tag"].append(stage_tag)
    series["event_idx"].append(int(event_idx))
    series["event_marker"].append(1.0 if is_event else 0.0)


def run_full_season_sac(args: argparse.Namespace) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    cfg = load_config()
    irr_cfg = cfg.irrigation()
    schedule = get_irrigation_schedule()
    model_bank = StageModelBank(Path(args.model_dir), Path(args.model) if args.model else None)
    model_bank.require_available()

    env = _make_env(args.area_ha, args.dt_min, args.season_days, args.et0, args.seed)
    obs = env.reset()
    env.soil.theta = irr_cfg.get("initial_theta") or env.soil.theta_fc
    env.soil.ec_soil = float(irr_cfg.get("initial_ec", 0.1))
    env._theta_history.clear()
    env._ec_soil_history.clear()
    for _ in range(env.history_len):
        env._theta_history.append(env.soil.theta)
        env._ec_soil_history.append(env.soil.ec_soil)

    dt_hours = args.dt_min / 60.0
    rain_mm_h = float(irr_cfg.get("rain_mm_day", 0.0)) / 24.0
    series: dict[str, list[Any]] = {
        "time_day": [],
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
        "stage_tag": [],
        "event_idx": [],
        "event_marker": [],
    }

    total_irrigation_mm = 0.0
    total_etc_mm = 0.0
    prev_day = 0.0

    for event_idx, event in enumerate(schedule):
        env.set_growth_stage(event.growth_stage)
        stage_key = event.growth_stage.value
        tag = STAGE_TAGS[stage_key]

        dry_steps = int(((event.day - prev_day) * 24.0) / dt_hours)
        for _ in range(dry_steps):
            obs, _reward, _done, info = env.dry_step(rain_mm_h=rain_mm_h)
            total_etc_mm += info["etc_mm_h"] * dt_hours
            _record(series, info, np.array([0.0, 0.0], dtype=np.float32), tag, event_idx, False)

        amount_m3ha = event.t2_amount_m3ha if args.irrigation_regime == "T2" else event.t1_amount_m3ha
        event_steps = max(1, int(event_duration_hours(amount_m3ha, args.area_ha) / dt_hours))
        event_irrigation_mm = 0.0
        for _ in range(event_steps):
            action = model_bank.action(obs, tag)
            obs, _reward, done, info = env.step(action)
            if done and info.get("burn"):
                env._done = False
            applied = info["irrigation_mm_h"] * dt_hours
            total_irrigation_mm += applied
            event_irrigation_mm += applied
            total_etc_mm += info["etc_mm_h"] * dt_hours
            _record(series, info, action, tag, event_idx, True)

        logger.info(
            "事件 %d/%d day %.0f stage=%s tag=%s irrigation=%.2f mm theta=%.3f root_EC=%.3f",
            event_idx + 1,
            len(schedule),
            event.day,
            stage_key,
            tag,
            event_irrigation_mm,
            info["theta"],
            info["ec_soil"],
        )
        prev_day = event.day

    current_day = env._time_min / (24.0 * 60.0)
    tail_steps = int(max(0.0, (args.season_days - current_day) * 24.0) / dt_hours)
    if schedule:
        env.set_growth_stage(schedule[-1].growth_stage)
        tail_tag = STAGE_TAGS[schedule[-1].growth_stage.value]
    else:
        tail_tag = "late"
    for _ in range(tail_steps):
        obs, _reward, _done, info = env.dry_step(rain_mm_h=rain_mm_h)
        total_etc_mm += info["etc_mm_h"] * dt_hours
        _record(series, info, np.array([0.0, 0.0], dtype=np.float32), tail_tag, len(schedule), False)

    root_ec = np.array(series["ec_soil"], dtype=float)
    target_ec = np.array(series["target_ec"], dtype=float)
    event_mask = np.array(series["event_marker"], dtype=float) > 0.5
    ec_drip = np.array(series["ec_drip"], dtype=float)
    ph_drip = np.array(series["ph_drip"], dtype=float)
    ec_set = np.array(series["ec_set"], dtype=float)
    ph_set = np.array(series["ph_set"], dtype=float)
    stats = {
        "irrigation_regime": args.irrigation_regime,
        "season_days": args.season_days,
        "dt_min": args.dt_min,
        "models": {tag: str(path) + ".zip" for tag, path in model_bank.model_paths.items()},
        "steps": len(series["time_day"]),
        "total_irrigation_mm": total_irrigation_mm,
        "total_etc_mm": total_etc_mm,
        "root_zone_ec_mae": float(np.mean(np.abs(root_ec - target_ec))) if len(root_ec) else 0.0,
        "root_zone_ec_final_error": float(abs(root_ec[-1] - target_ec[-1])) if len(root_ec) else 0.0,
        "outlet_ec_setpoint_mae_during_events": float(np.mean(np.abs(ec_drip[event_mask] - ec_set[event_mask]))) if event_mask.any() else 0.0,
        "outlet_ph_setpoint_mae_during_events": float(np.mean(np.abs(ph_drip[event_mask] - ph_set[event_mask]))) if event_mask.any() else 0.0,
        "ec_set_mean_during_events": float(np.mean(ec_set[event_mask])) if event_mask.any() else 0.0,
        "ph_set_mean_during_events": float(np.mean(ph_set[event_mask])) if event_mask.any() else 0.0,
        "q_f_mean_during_events": float(np.mean(np.array(series["q_f"], dtype=float)[event_mask])) if event_mask.any() else 0.0,
        "q_a_mean_during_events": float(np.mean(np.array(series["q_a"], dtype=float)[event_mask])) if event_mask.any() else 0.0,
    }
    return series, stats


def _setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _shade_events(ax, time_day: np.ndarray, marker: np.ndarray, label: str = "灌溉控制时段") -> None:
    starts = np.flatnonzero(marker & ~np.r_[False, marker[:-1]])
    ends = np.flatnonzero(marker & ~np.r_[marker[1:], False])
    for index, (start, end) in enumerate(zip(starts, ends)):
        ax.axvspan(time_day[start], time_day[end], color="#d8f0d2", alpha=0.28, label=label if index == 0 else None)


def plot_full_season_root_ec(series: dict[str, list[Any]], path: Path) -> None:
    plt = _setup_matplotlib()
    time_day = np.array(series["time_day"], dtype=float)
    marker = np.array(series["event_marker"], dtype=float) > 0.5
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _shade_events(ax, time_day, marker)
    ax.plot(time_day, series["ec_soil"], color="#f28e2b", linewidth=1.5, label="SAC根区EC")
    ax.step(time_day, series["target_ec"], where="post", color="#2f7d32", linestyle="--", linewidth=1.8, label="模型设定EC参考")
    set_time_axis_origin([ax], time_day)
    ax.set_title("全生育期 SAC 根区 EC 跟踪")
    ax.set_xlabel("时间（d）")
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


def plot_full_season_delivery(series: dict[str, list[Any]], path: Path) -> None:
    plt = _setup_matplotlib()
    time_day = np.array(series["time_day"], dtype=float)
    marker = np.array(series["event_marker"], dtype=float) > 0.5
    fig, axes = plt.subplots(4, 1, figsize=(9, 8.5), sharex=True)
    for ax in axes:
        _shade_events(ax, time_day, marker)
    target_ec_event = np.where(marker, np.array(series["ec_set"], dtype=float), np.nan)
    target_ph_event = np.where(marker, np.array(series["ph_set"], dtype=float), np.nan)
    axes[0].plot(time_day, series["ec_drip"], color="#4e79a7", linewidth=1.4, label="出口EC")
    axes[0].plot(time_day, target_ec_event, color="#2f7d32", linestyle="--", linewidth=1.3, label="配液设定EC")
    axes[1].plot(time_day, series["ph_drip"], color="#4e79a7", linewidth=1.4, label="出口pH")
    axes[1].plot(time_day, target_ph_event, color="#2f7d32", linestyle="--", linewidth=1.3, label="配液设定pH")
    axes[2].plot(time_day, series["q_f"], color="#f28e2b", linewidth=1.4, label="肥料母液 q_f")
    axes[3].plot(time_day, series["q_a"], color="#e15759", linewidth=1.4, label="酸液 q_a")
    axes[0].set_title("全生育期 SAC 配液执行效果")
    axes[0].set_ylabel("出口EC（dS/m）")
    axes[1].set_ylabel("出口pH")
    axes[2].set_ylabel("q_f（L/min）")
    axes[3].set_ylabel("q_a（L/min）")
    axes[3].set_xlabel("时间（d）")
    for ax in axes:
        ax.set_ylim(bottom=0.0 if ax is not axes[1] else None)
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)
        ax.legend(loc="best")
    set_time_axis_origin(axes, time_day)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def plot_full_season_water(series: dict[str, list[Any]], path: Path) -> None:
    plt = _setup_matplotlib()
    time_day = np.array(series["time_day"], dtype=float)
    marker = np.array(series["event_marker"], dtype=float) > 0.5
    soil_cfg = load_config().soil()
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.2), sharex=True)
    for ax in axes:
        _shade_events(ax, time_day, marker)
    axes[0].plot(time_day, series["theta"], color="#4e79a7", linewidth=1.4, label="土壤含水率")
    axes[0].axhline(float(soil_cfg.get("theta_fc", 0.334)), color="#59a14f", linestyle="--", linewidth=1.0, label="田间持水量")
    axes[0].axhline(float(soil_cfg.get("theta_safe_upper", 0.38)), color="#76b7b2", linestyle=":", linewidth=1.0, label="偏湿参考线")
    axes[1].plot(time_day, series["irrigation_mm_h"], color="#f28e2b", linewidth=1.3, label="灌溉强度")
    axes[1].plot(time_day, series["etc_mm_h"], color="#666666", linestyle="--", linewidth=1.2, label="ETc")
    axes[0].set_title("全生育期 SAC 水分响应")
    axes[0].set_ylabel("土壤含水率")
    axes[1].set_ylabel("水量（mm/h）")
    axes[1].set_xlabel("时间（d）")
    axes[0].set_ylim(bottom=0.0)
    axes[1].set_ylim(bottom=0.0)
    for ax in axes:
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)
        ax.legend(loc="best")
    set_time_axis_origin(axes, time_day)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    season_cfg = cfg.season_comparison()
    parser = argparse.ArgumentParser(description="Run full-season SAC fertigation simulation.")
    parser.add_argument("--model-dir", default=str(ROOT / "rl_models"))
    parser.add_argument("--model", default=None, help="单一模型路径，不含或包含 .zip；缺省则查找 sac_ini/dev/mid/late_final。")
    parser.add_argument("--irrigation-regime", default="T2", choices=["T1", "T2"])
    parser.add_argument("--area-ha", type=float, default=float(season_cfg.get("area_ha", 0.1)))
    parser.add_argument("--dt-min", type=float, default=float(season_cfg.get("dt_min", 15.0)))
    parser.add_argument("--season-days", type=float, default=float(season_cfg.get("ep_len_days", 90.0)))
    parser.add_argument("--et0", type=float, default=float(season_cfg.get("et0_mm_day", 4.0)))
    parser.add_argument("--seed", type=int, default=int(season_cfg.get("seed", 42)))
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_dir = ROOT / "results" / "full_season_sac" / run_id
    image_dir = ROOT / "experiments" / "images" / "full_season_sac" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    series, stats = run_full_season_sac(args)
    _write_csv(out_dir / "full_season_sac_timeseries.csv", series)

    root_ec_png = image_dir / "full_season_root_zone_ec.png"
    delivery_png = image_dir / "full_season_delivery_execution.png"
    water_png = image_dir / "full_season_water_response.png"
    plot_full_season_root_ec(series, root_ec_png)
    plot_full_season_delivery(series, delivery_png)
    plot_full_season_water(series, water_png)

    summary = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stats": stats,
        "artifacts": {
            "summary": "summary.json",
            "csv": "full_season_sac_timeseries.csv",
            "image_dir": str(image_dir),
            "root_zone_ec_png": str(root_ec_png),
            "delivery_execution_png": str(delivery_png),
            "water_response_png": str(water_png),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    logger.info("Full-season SAC complete: %s", out_dir)
    logger.info("Images saved to: %s", image_dir)
    logger.info("Root-zone EC MAE: %.4f", stats["root_zone_ec_mae"])
    logger.info("Total irrigation: %.2f mm", stats["total_irrigation_mm"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
