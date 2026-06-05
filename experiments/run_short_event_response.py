"""短期单次灌溉事件响应仿真脚本。

这个脚本和完整季节实验脚本分开，是为了单独回答一个问题：
在执行一次固定水肥灌溉事件后，根区土壤含水率和 EC 会如何响应？

实验流程：
- 总共仿真 5 天，默认使用 5 分钟步长；
- 只在前 2 小时执行固定水肥动作；
- 之后切换为 dry_step，只保留蒸散和降雨等自然过程；
- CSV 数据保存到 results/short_event_response/<run_id>/；
- PNG 图片保存到 experiments/images/<run_id>/。
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
    # 允许脚本从 experiments/ 子目录直接导入项目根目录下的模型模块。
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from crop_model import GrowthStage
from digital_twin_env import DigitalTwinEnv
from plot_utils import set_time_axis_origin

logger = logging.getLogger(__name__)


def _json_default(value: Any):
    """把 numpy 类型转换为 JSON 可序列化的 Python 原生类型。"""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_csv(path: Path, columns: dict[str, list[float]]) -> None:
    """把同长度时序列写入 CSV，首行为字段名。"""
    keys = list(columns.keys())
    rows = zip(*(columns[k] for k in keys))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerows(rows)


def run_event_response(
    stage: GrowthStage,
    out_dir: Path,
    image_dir: Path,
    duration_days: float,
    event_hours: float,
    use_weather: bool,
) -> dict[str, Any]:
    """运行短期灌溉事件响应实验。

    参数
    ----
    stage:
        当前生育阶段，例如 BULKING。
    out_dir:
        CSV 和 summary.json 的输出目录。
    image_dir:
        图片输出目录。
    duration_days:
        总仿真天数。
    event_hours:
        灌溉事件持续小时数。

    返回
    ----
    dict
        本次实验的关键统计指标，用于写入 summary.json。
    """
    cfg = load_config()
    env_cfg = cfg.env()
    irr_cfg = cfg.irrigation()
    # 使用实验专用步长，避免影响 SAC 训练默认 dt_min。
    dt_min = float(cfg.get("experiment.short_dt_min", 5.0))
    dt_hours = dt_min / 60.0
    et0_mm_day = float(env_cfg.get("et0_mm_day", 5.0))
    rain_mm_day = float(irr_cfg.get("rain_mm_day", 0.0))
    weather_source = "config"
    weather_location = None

    if use_weather:
        try:
            from weather_client import fetch_daily_weather

            weather = fetch_daily_weather(forecast_days=max(1, int(round(duration_days))))
            et0_values = weather.get("et0_mm_day", [])
            rain_values = weather.get("rain_mm_day", [])
            if et0_values:
                et0_mm_day = float(et0_values[0])
            if rain_values:
                rain_mm_day = float(rain_values[0])
            weather_source = "weather_client_fallback" if weather.get("fallback") else "weather_client"
            weather_location = weather.get("location")
        except Exception as exc:
            logger.warning("Weather lookup failed, using config defaults: %s", exc)

    # 固定策略动作来自 YAML。B 方案中含义是 [EC_set, pH_set]，
    # 环境内部再通过执行层模型转换为 q_f/q_a。
    action = np.array(cfg.action().get("fixed_strategy", [1.5, 6.0]), dtype=np.float32)
    env = DigitalTwinEnv(
        growth_stage=stage,
        area_ha=env_cfg.get("area_ha", 0.1),
        dt_min=dt_min,
        ep_len_days=duration_days,
        et0_mm_day=et0_mm_day,
        seed=env_cfg.get("seed"),
    )
    env.reset()

    # dry_step 期间仍可保留背景降雨，单位从 mm/day 转为 mm/hour。
    rain_mm_h = rain_mm_day / 24.0
    total_steps = int(round(duration_days * 24.0 / dt_hours))
    event_steps = int(round(event_hours / dt_hours))

    series: dict[str, list[float]] = {
        # 全部时序字段集中记录，后面统一写 CSV 和绘图。
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
        "event_marker": [],
    }

    stopped_by_safety = False
    for step in range(total_steps):
        in_event = step < event_steps
        if in_event:
            # 灌溉事件内执行固定水肥动作。
            _obs, _reward, done, info = env.step(action)
        else:
            # 灌溉事件结束后不再给动作，只推进干燥/蒸散过程。
            _obs, _reward, done, info = env.dry_step(rain_mm_h=rain_mm_h)
        q_f = float(info.get("q_f", 0.0))
        q_a = float(info.get("q_a", 0.0))

        if done and in_event:
            stopped_by_safety = bool(info.get("burn", False))
            # 若固定动作触发烧苗终止，为了保持图像可读，停止灌溉事件，
            # 但继续后续 dry_step，便于观察恢复/干燥过程。
            event_steps = step + 1
            env._done = False

        series["time_hours"].append(float(info["time_day"] * 24.0))
        series["theta"].append(float(info["theta"]))
        series["ec_soil"].append(float(info["ec_soil"]))
        series["target_ec"].append(float(info["target_ec"]))
        series["ec_drip"].append(float(info["ec_drip"]))
        series["ph_drip"].append(float(info.get("ph_drip", 7.0)))
        series["ec_set"].append(float(info.get("ec_set", action[0] if in_event else 0.0)))
        series["ph_set"].append(float(info.get("ph_set", action[1] if in_event else 7.0)))
        series["irrigation_mm_h"].append(float(info["irrigation_mm_h"]))
        series["etc_mm_h"].append(float(info["etc_mm_h"]))
        series["q_f"].append(q_f)
        series["q_a"].append(q_a)
        series["event_marker"].append(1.0 if in_event and step < event_steps else 0.0)

    _write_csv(out_dir / "short_event_response_timeseries.csv", series)
    image_path = image_dir / "short_event_response.png"
    _plot_event_response(series, image_path, event_hours)

    theta = np.array(series["theta"], dtype=float)
    ec_soil = np.array(series["ec_soil"], dtype=float)
    ec_target = np.array(series["target_ec"], dtype=float)
    irrigation = np.array(series["irrigation_mm_h"], dtype=float)

    return {
        # 这些指标用于快速判断一次灌溉事件是否过强、是否达到预期响应。
        "stage": stage.value,
        "dt_min": dt_min,
        "duration_days": duration_days,
        "event_hours_requested": event_hours,
        "event_hours_effective": event_steps * dt_hours,
        "weather_source": weather_source,
        "weather_location": weather_location,
        "et0_mm_day": et0_mm_day,
        "rain_mm_day": rain_mm_day,
        "stopped_by_safety": stopped_by_safety,
        "theta_initial": float(theta[0]),
        "theta_peak": float(theta.max()),
        "theta_final": float(theta[-1]),
        "ec_initial": float(ec_soil[0]),
        "ec_peak": float(ec_soil.max()),
        "ec_final": float(ec_soil[-1]),
        "ec_mae": float(np.abs(ec_soil - ec_target).mean()),
        "total_irrigation_mm": float(irrigation.sum() * dt_hours),
        "image": str(image_path),
    }


def _plot_event_response(series: dict[str, list[float]], path: Path, event_hours: float) -> None:
    """绘制短期事件响应图。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    cfg = load_config()
    soil_cfg = cfg.soil()
    t = np.array(series["time_hours"], dtype=float)
    theta = np.array(series["theta"], dtype=float)
    ec_soil = np.array(series["ec_soil"], dtype=float)
    ec_target = np.array(series["target_ec"], dtype=float)
    irrigation = np.array(series["irrigation_mm_h"], dtype=float)
    etc = np.array(series["etc_mm_h"], dtype=float)
    q_f = np.array(series["q_f"], dtype=float)
    q_a = np.array(series["q_a"], dtype=float)

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(4, 1, figsize=(8, 9), sharex=True)
    fig.suptitle("短期单次灌溉事件响应", fontsize=13)

    for ax in axes:
        # 浅绿色阴影表示灌溉事件发生的时间窗口，参考作物生育期图的背景风格。
        ax.axvspan(0.0, event_hours, color="#d8f0d2", alpha=0.55, label="灌溉事件")
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out", length=4, width=1)

    # 第一幅图：土壤含水率，同时画出田间持水量和凋萎点参考线。
    theta_fc = float(soil_cfg.get("theta_fc", 0.334))
    theta_wp = float(soil_cfg.get("theta_wp", 0.09))
    marker_every = max(1, len(t) // 14)
    axes[0].plot(t, theta, color="#2ca25f", marker="o", markevery=marker_every,
                 markersize=3.0, linewidth=1.5, label="土壤含水率")
    axes[0].axhline(theta_fc, color="#238b45", linestyle="--", linewidth=1.0, label="田间持水量")
    axes[0].axhline(theta_wp, color="#8c510a", linestyle=":", linewidth=1.0, label="凋萎点")
    axes[0].set_ylabel("土壤含水率")
    axes[0].legend(loc="best")

    # 第二幅图：根区 EC 与当前生育阶段马铃薯适宜 EC 参考。
    axes[1].plot(t, ec_soil, color="#f28e2b", marker="s", markevery=marker_every,
                 markersize=3.0, linewidth=1.5, label="根区EC")
    axes[1].plot(t, ec_target, color="#4e79a7", linestyle="--", linewidth=1.1, label="目标EC")
    axes[1].set_ylabel("EC（dS/m）")
    axes[1].set_ylim(bottom=0.0)
    axes[1].legend(loc="best")

    # 第三幅图：灌溉输入与作物蒸散。
    axes[2].plot(t, irrigation, color="#4e79a7", marker="^", markevery=marker_every,
                 markersize=3.0, linewidth=1.5, label="灌溉强度")
    axes[2].plot(t, etc, color="#f28e2b", linestyle="-", marker="o",
                 markevery=marker_every, markersize=2.8, linewidth=1.1, label="作物蒸散ETc")
    axes[2].set_ylabel("水量（mm/h）")
    axes[2].set_ylim(bottom=0.0)
    axes[2].legend(loc="best")

    # 第四幅图：控制动作，事件结束后动作归零。
    axes[3].plot(t, q_f, color="#59a14f", marker="o", markevery=marker_every,
                 markersize=3.0, linewidth=1.5, label="肥液流量")
    axes[3].plot(t, q_a, color="#e15759", linestyle="--", marker="s",
                 markevery=marker_every, markersize=3.0, linewidth=1.1, label="酸液流量")
    axes[3].set_ylabel("流量（L/min）")
    axes[3].set_xlabel("时间（h）")
    axes[3].set_ylim(bottom=0.0)
    axes[3].legend(loc="best")

    set_time_axis_origin(axes, t)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Run a short irrigation-event response simulation.")
    parser.add_argument("--stage", default="BULKING", choices=[stage.name for stage in GrowthStage])
    parser.add_argument("--duration-days", type=float, default=5.0)
    parser.add_argument("--event-hours", type=float, default=2.0)
    parser.add_argument("--weather", action="store_true", help="Use weather_client ET0/rain instead of YAML defaults.")
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # 每次运行单独建时间戳目录，避免覆盖历史实验结果。
    out_dir = ROOT / "results" / "short_event_response" / run_id
    image_dir = ROOT / "experiments" / "images" / "short_event_response" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        # summary.json 是本次实验的入口索引，记录指标和输出文件位置。
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "short_event_response": run_event_response(
            stage=GrowthStage[args.stage],
            out_dir=out_dir,
            image_dir=image_dir,
            duration_days=args.duration_days,
            event_hours=args.event_hours,
            use_weather=args.weather,
        ),
        "artifacts": {
            "summary": "summary.json",
            "csv": "short_event_response_timeseries.csv",
            "image_dir": str(image_dir),
            "png": str(image_dir / "short_event_response.png"),
        },
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)

    logger.info("Short event response complete: %s", out_dir)
    logger.info("Image saved to: %s", image_dir / "short_event_response.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
