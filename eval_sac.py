"""
SAC 闭环评估脚本 — eval_sac.py
================================

加载训练好的 SAC 模型，在全生育期（8 次灌溉事件）上做确定性推演，
录制水倍率/EC残差、执行层 q_f/q_a、土壤水盐状态和灌溉过程数据。
"""

import argparse
import csv
import io
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")
ROOT = Path(__file__).resolve().parent
RESULTS_ROOT = ROOT / "results"
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rl_logs")
os.makedirs(_log_dir, exist_ok=True)
_error_fh = logging.FileHandler(os.path.join(_log_dir, "error.log"), encoding="utf-8")
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
logging.getLogger().addHandler(_error_fh)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

try:
    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if os.path.exists(simhei_path):
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"] + plt.rcParams.get("font.sans-serif", [])
    plt.rcParams["axes.unicode_minus"] = False
except Exception:
    pass

from digital_twin_env import DigitalTwinEnv, GrowthStage
from irrigation_schedule import get_irrigation_schedule, event_duration_hours, run_season_simulation
from config_loader import load_config
from sac_model_registry import get_existing_stage_models
from plot_style import (
    apply_academic_style, style_axis, set_ylim_tight,
    EC_ACTUAL, EC_TARGET, THETA, QF, QA, ET_COLOR, IRRIGATION,
    FC_LINE, WP_LINE, ERROR_BAND,
)

cfg_obs = load_config().obs()
OBS_LOW = np.array(cfg_obs["obs_low"], dtype=np.float32)
OBS_HIGH = np.array(cfg_obs["obs_high"], dtype=np.float32)

try:
    from stable_baselines3 import SAC
except ImportError:
    logger.error("请安装 stable-baselines3: pip install stable-baselines3")
    sys.exit(1)


STAGE_TO_TAG = {
    GrowthStage.EMERGENCE: "ini",
    GrowthStage.VEGETATIVE: "dev",
    GrowthStage.TUBER_INIT: "dev",
    GrowthStage.BULKING: "mid",
    GrowthStage.STARCH_ACCUMULATION: "late",
    GrowthStage.MATURATION: "late",
}
TAG_TO_STAGE = {v: k for k, v in STAGE_TO_TAG.items()}


def normalize_obs(obs: np.ndarray) -> np.ndarray:
    eps = 1e-6
    norm = 2.0 * (obs - OBS_LOW) / (OBS_HIGH - OBS_LOW + eps) - 1.0
    return np.clip(norm, -1.0, 1.0).astype(np.float32)


class SACSeasonRunner:
    """加载 SAC 模型，在完整生育期上闭环运行。"""

    def __init__(self, model_dir="./rl_models", stage_models=None, single_model=None):
        self.model_dir = model_dir
        self.models = {}
        self._single = single_model

        if single_model:
            for tag in ["ini", "dev", "mid", "late"]:
                self.models[tag] = single_model
        elif stage_models:
            self.models = stage_models
        else:
            self._auto_discover()

    def _auto_discover(self):
        residual_model = os.path.join(self.model_dir, "sac_residual_all_final")
        if os.path.exists(residual_model + ".zip"):
            self.models = {tag: residual_model for tag in ["ini", "dev", "mid", "late"]}
            return
        self.models.update(get_existing_stage_models())
        for tag in ["ini", "dev", "mid", "late"]:
            if tag in self.models:
                continue
            for stem in (f"sac_residual_{tag}_final", f"sac_{tag}_final"):
                path = os.path.join(self.model_dir, stem)
                if os.path.exists(path + ".zip"):
                    self.models[tag] = path
                    break
        if not self.models:
            for tag in ["mid", "ini", "dev", "late"]:
                path = os.path.join(self.model_dir, f"sac_residual_{tag}_final")
                if os.path.exists(path + ".zip"):
                    self.models = {t: path for t in ["ini", "dev", "mid", "late"]}
                    logger.info(f"[INFO] 未找到全部阶段模型，使用单一模型: {path}")
                    break

    def get_action(self, obs: np.ndarray, stage_tag: str) -> np.ndarray:
        """返回确定性的 V2 残差动作 [water_multiplier, EC_residual]。"""
        if stage_tag not in self.models or self.models[stage_tag] is None:
            fixed = load_config().action().get("fixed_strategy", [1.0, 0.0])
            return np.array(fixed, dtype=np.float32)

        path = self.models[stage_tag]
        if not hasattr(self, "_loaded_models"):
            self._loaded_models = {}
        if stage_tag not in self._loaded_models:
            self._loaded_models[stage_tag] = SAC.load(path)
            logger.info(f"  [加载] {path}.zip")

        model = self._loaded_models[stage_tag]
        norm_obs = normalize_obs(obs)
        action, _ = model.predict(norm_obs, deterministic=True)
        return action.astype(np.float32)


def _write_history_csv(path: Path, history: dict[str, list]) -> None:
    keys = list(history.keys())
    row_count = len(history[keys[0]]) if keys else 0
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        for index in range(row_count):
            writer.writerow([history[key][index] for key in keys])


def _metric_values(error: np.ndarray) -> tuple[float, float, float]:
    if len(error) == 0:
        return 0.0, 0.0, 0.0
    abs_error = np.abs(error)
    return (
        float(abs_error.mean()),
        float(np.sqrt(np.mean(error * error))),
        float(abs_error.max()),
    )


def _summary_model_path(args: argparse.Namespace, runner: SACSeasonRunner) -> str:
    if args.model:
        return str(Path(args.model).with_suffix("").resolve())
    if len(set(runner.models.values())) == 1:
        return str(Path(next(iter(runner.models.values()))).resolve())
    return str(Path(args.model_dir).resolve())


def run_eval(args):
    cfg = load_config()
    irr_cfg = cfg.irrigation()
    pipe_cfg = cfg.pipe()
    pipe_tau_min = float(pipe_cfg.get("tau", 0.0))
    warnings: list[dict[str, str | float]] = []
    if pipe_tau_min > 0.0 and float(args.dt_min) >= pipe_tau_min:
        warnings.append(
            {
                "code": "pipe_delay_under_resolved",
                "message": (
                    "PipeDynamics pure delay is under-resolved because dt_min is greater than or equal to "
                    "pipe tau. Use --dt-min 1 or --dt-min 5 for formal evaluation."
                ),
                "dt_min": float(args.dt_min),
                "pipe_tau_min": pipe_tau_min,
            }
        )

    logger.info("=" * 60)
    logger.info("SAC-PID 闭环评估 — 全生育期推演")
    logger.info("=" * 60)

    runner = SACSeasonRunner(
        model_dir=args.model_dir,
        single_model=args.model if args.model else None,
    )
    if not runner.models:
        logger.error("[ERROR] 未找到任何 SAC 模型，请先训练。")
        logger.error(f"  检查目录: {os.path.abspath(args.model_dir)}")
        sys.exit(1)

    logger.info(f"阶段模型配置: {runner.models}\n")

    schedule = get_irrigation_schedule()
    env = DigitalTwinEnv(
        growth_stage=schedule[0].growth_stage,
        area_ha=args.area_ha,
        dt_min=args.dt_min,
        ep_len_days=90.0,
        et0_mm_day=args.et0,
        seed=args.seed,
        soil_model=args.soil_model,
    )

    history = {
        "time_day": [], "theta": [], "ec_soil": [], "target_ec": [],
        "ec_set": [], "ph_set": [], "q_f": [], "q_a": [],
        "irrigation_mm_h": [], "etc_mm_h": [], "ec_drip": [], "ph_drip": [],
        "stage_tag": [], "event_idx": [], "burn": [],
    }

    obs = env.reset()
    if env.soil_model == "lumped_v1":
        env.soil.theta = irr_cfg.get("initial_theta") or env.soil.theta_fc
        env.soil.ec_soil = irr_cfg.get("initial_ec", 0.1)
        env._theta_history.clear()
        env._ec_soil_history.clear()
        for _ in range(env.history_len):
            env._theta_history.append(env.soil.theta)
            env._ec_soil_history.append(env.soil.ec_soil)

    total_irr_mm = 0.0
    total_etc_mm = 0.0
    prev_day = 0.0
    dt_hours = args.dt_min / 60.0
    rain_mm_h = irr_cfg.get("rain_mm_day", 2.0) / 24.0
    event_tags = ["ini", "ini", "dev", "dev", "mid", "mid", "mid", "late"]
    stopped_by_safety = False

    logger.info("按灌溉事件推进...")
    logger.info("-" * 60)

    for i, (event, tag) in enumerate(zip(schedule, event_tags)):
        env.set_growth_stage(event.growth_stage)
        stage_name = event.growth_stage.value

        dry_hours = (event.day - prev_day) * 24.0
        dry_steps = int(dry_hours / dt_hours)
        for _ in range(dry_steps):
            obs, _, _done, info = env.dry_step(rain_mm_h=rain_mm_h)
            total_etc_mm += info["etc_mm_h"] * dt_hours
            _append(history, info, tag, i)

        amount = event.t2_amount_m3ha
        event_hours = event_duration_hours(amount, args.area_ha)
        event_steps = max(1, int(event_hours / dt_hours))
        event_irr = 0.0

        for _ in range(event_steps):
            action = runner.get_action(obs, tag)
            obs, _reward, _done, info = env.step(action)
            if _done and info.get("burn"):
                stopped_by_safety = True
                env._done = False
            total_irr_mm += info["irrigation_mm_h"] * dt_hours
            event_irr += info["irrigation_mm_h"] * dt_hours
            total_etc_mm += info["etc_mm_h"] * dt_hours
            _append(history, info, tag, i)

        target_ec = env.crop.get_target_ec(event.growth_stage)
        logger.info(
            f"  事件 {i+1}/8  day {event.day:3.0f}  stage={stage_name:20s}  tag={tag}  "
            f"irr={event_irr:.1f}mm  theta={info.get('theta', 0):.3f}  "
            f"EC={info.get('ec_soil', 0):.3f}  target={target_ec:.2f}"
        )
        prev_day = event.day

    logger.info("\n" + "=" * 60)
    logger.info("评估汇总")
    logger.info("=" * 60)
    theta_arr = np.array(history["theta"])
    ec_arr = np.array(history["ec_soil"])
    target_arr = np.array(history["target_ec"])
    ec_set_arr = np.array(history["ec_set"])
    ph_set_arr = np.array(history["ph_set"])
    qf_arr = np.array(history["q_f"])
    qa_arr = np.array(history["q_a"])
    ph_drip_arr = np.array(history["ph_drip"])

    ec_error = ec_arr - target_arr
    ph_error = ph_drip_arr - ph_set_arr
    ec_mae, ec_rmse, ec_max_error = _metric_values(ec_error)
    ph_mae, ph_rmse, ph_max_error = _metric_values(ph_error)
    logger.info(f"  总步数:          {len(history['time_day'])}")
    logger.info(f"  总灌溉量:        {total_irr_mm:.1f} mm")
    logger.info(f"  总蒸散发:        {total_etc_mm:.1f} mm")
    logger.info(f"  平均 theta:      {theta_arr.mean():.4f} ± {theta_arr.std():.4f}")
    logger.info(f"  根区 EC MAE:     {ec_mae:.4f} dS/m")
    logger.info(f"  出口 pH MAE:     {ph_mae:.4f}")
    logger.info(f"  EC_set 范围:     [{ec_set_arr.min():.2f}, {ec_set_arr.max():.2f}] dS/m")
    logger.info(f"  pH_set 范围:     [{ph_set_arr.min():.2f}, {ph_set_arr.max():.2f}]")
    logger.info(f"  q_f 均值/范围:   {qf_arr.mean():.2f} / [{qf_arr.min():.2f}, {qf_arr.max():.2f}]")
    logger.info(f"  q_a 均值/范围:   {qa_arr.mean():.2f} / [{qa_arr.min():.2f}, {qa_arr.max():.2f}]")

    wue = total_etc_mm / (total_irr_mm + irr_cfg.get("rain_mm_day", 2.0) * 65 + 1e-6)
    logger.info(f"  WUE 代理:        {wue:.4f}")

    logger.info("\n--- 对比基线 (T1/T2) ---")
    for strategy in ["T1", "T2"]:
        env2 = DigitalTwinEnv(
            growth_stage=schedule[0].growth_stage,
            area_ha=args.area_ha,
            dt_min=args.dt_min,
            ep_len_days=90.0,
            et0_mm_day=args.et0,
            seed=args.seed,
            soil_model=args.soil_model,
        )
        res = run_season_simulation(
            env2, strategy=strategy, area_ha=args.area_ha,
            dt_min=args.dt_min, rain_mm_day=irr_cfg.get("rain_mm_day"),
            initial_theta=env2.soil.theta_fc, initial_ec=0.1, verbose=False,
        )
        ec_m = np.abs(res["ec_soil"] - res["target_ec"]).mean()
        w = res["total_etc_mm"] / (res["total_irrigation_mm"] + irr_cfg.get("rain_mm_day", 2.0) * 65 + 1e-6)
        logger.info(
            f"  {strategy}: 灌溉={res['total_irrigation_mm']:.1f}mm  "
            f"EC_MAE={ec_m:.4f}  WUE={w:.4f}  theta_CV={res['theta'].std()/res['theta'].mean():.4f}"
        )

    apply_academic_style()
    time_day = np.array(history["time_day"])
    fig, axes = plt.subplots(4, 1, figsize=(9, 12), sharex=True)
    fig.subplots_adjust(hspace=0.38)

    ax = axes[0]
    style_axis(ax)
    ax.plot(time_day, theta_arr, color=THETA, linewidth=1.5, label="θ (soil moisture)")
    ax.axhline(y=0.32, color=FC_LINE, linestyle="--", linewidth=1.0, alpha=0.8, label="Field capacity")
    ax.axhline(y=0.04, color=WP_LINE, linestyle=":", linewidth=1.0, alpha=0.8, label="Wilting point")
    set_ylim_tight(ax, theta_arr, pad_pct=5, min_val=0.0)
    ax.set_ylabel("θ (m³/m³)")
    ax.set_title("Root-zone soil moisture — SAC-PID closed-loop control")
    ax.legend(loc="upper right", framealpha=0.55, edgecolor="#aaaaaa", fontsize=8.5, borderpad=0.5)

    ax = axes[1]
    style_axis(ax)
    ax.plot(time_day, ec_arr, color=EC_ACTUAL, linewidth=1.5, label="EC_soil")
    ax.plot(time_day, target_arr, color=EC_TARGET, linestyle="--", linewidth=1.8, label="Target EC")
    ax.fill_between(time_day, ec_arr, target_arr, color=ERROR_BAND, alpha=0.35, linewidth=0)
    set_ylim_tight(ax, np.concatenate([ec_arr, target_arr]), pad_pct=8)
    ax.set_ylabel("EC (dS/m)")
    ax.set_title("Root-zone EC tracking")
    ax.legend(loc="upper right", framealpha=0.55, edgecolor="#aaaaaa", fontsize=8.5, borderpad=0.5)

    ax = axes[2]
    style_axis(ax)
    n_pts = len(time_day)
    mk_every = max(1, n_pts // 40)
    ax.plot(time_day, ec_set_arr, color=QF, linewidth=1.2, marker="o", markersize=3.0,
            markevery=mk_every, label="EC_set")
    ax.plot(time_day, ph_set_arr, color=QA, linewidth=1.2, marker="^", markersize=3.5,
            markevery=mk_every, label="pH_set")
    set_ylim_tight(ax, np.concatenate([ec_set_arr, ph_set_arr]), pad_pct=10)
    ax.set_ylabel("Setpoint")
    ax.set_title("SAC setpoint sequence")
    ax.legend(loc="upper right", framealpha=0.55, edgecolor="#aaaaaa", fontsize=8.5, borderpad=0.5)

    ax = axes[3]
    style_axis(ax)
    irr_arr = np.array(history["irrigation_mm_h"])
    etc_arr = np.array(history["etc_mm_h"])
    ax.fill_between(time_day, 0, irr_arr, color=IRRIGATION, alpha=0.30, linewidth=0, label="Irrigation")
    ax.plot(time_day, etc_arr, color=ET_COLOR, linewidth=2.0, linestyle="--", label="ET (mm/h)")
    set_ylim_tight(ax, np.concatenate([irr_arr, etc_arr]), pad_pct=10, min_val=0.0)
    ax.set_xlabel("Days after emergence")
    ax.set_ylabel("Rate (mm/h)")
    ax.set_title("Irrigation and evapotranspiration")
    ax.legend(loc="upper right", framealpha=0.55, edgecolor="#aaaaaa", fontsize=8.5, borderpad=0.5)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir = RESULTS_ROOT / "eval_sac" / ts
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "eval_sac_timeseries.csv"
    summary_path = result_dir / "summary.json"
    png_path = result_dir / "sac_pid_eval.png"
    _write_history_csv(csv_path, history)

    plt.savefig(png_path, dpi=300)
    legacy_dir = ROOT / "pic_output" / "eval_sac"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_png = legacy_dir / f"sac_pid_eval_{ts}.png"
    plt.savefig(legacy_png, dpi=300)
    plt.close()

    summary = {
        "run_id": ts,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "EC_MAE": ec_mae,
        "pH_MAE": ph_mae,
        "EC_RMSE": ec_rmse,
        "pH_RMSE": ph_rmse,
        "EC_Max_Error": ec_max_error,
        "pH_Max_Error": ph_max_error,
        "total_irrigation_mm": float(total_irr_mm),
        "total_etc_mm": float(total_etc_mm),
        "q_f_mean": float(qf_arr.mean()) if len(qf_arr) else 0.0,
        "q_a_mean": float(qa_arr.mean()) if len(qa_arr) else 0.0,
        "q_f_max": float(qf_arr.max()) if len(qf_arr) else 0.0,
        "q_a_max": float(qa_arr.max()) if len(qa_arr) else 0.0,
        "stopped_by_safety": bool(stopped_by_safety),
        "model_path": _summary_model_path(args, runner),
        "soil_model": args.soil_model,
        "parameter_status": info.get("parameter_status", "unknown"),
        "parameter_version": info.get("parameter_version", "unknown"),
        "stage_model_paths": runner.models,
        "dt_min": float(args.dt_min),
        "pipe_tau_min": pipe_tau_min,
        "pipe_delay_resolved": bool(pipe_tau_min <= 0.0 or float(args.dt_min) < pipe_tau_min),
        "warnings": warnings,
        "et0": float(args.et0),
        "seed": args.seed,
        "area_ha": float(args.area_ha),
        "metric_definitions": {
            "EC": "root-zone ec_soil minus crop target_ec over all recorded steps",
            "pH": "outlet ph_drip minus ph_set over all recorded steps",
        },
        "artifacts": {
            "csv": "eval_sac_timeseries.csv",
            "summary": "summary.json",
            "png": "sac_pid_eval.png",
            "csv_path": str(csv_path),
            "summary_path": str(summary_path),
            "png_path": str(png_path),
            "legacy_png": str(legacy_png),
        },
    }
    if warnings:
        summary["model_warning"] = warnings[0]["message"]
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"\n标准结果目录: {result_dir}")
    logger.info(f"CSV 已保存: {csv_path}")
    logger.info(f"summary.json 已保存: {summary_path}")
    logger.info(f"图表已保存: {png_path}")


def _append(hist, info, tag, idx):
    hist["time_day"].append(info["time_day"])
    hist["theta"].append(info["theta"])
    hist["ec_soil"].append(info["ec_soil"])
    hist["target_ec"].append(info["target_ec"])
    hist["ec_set"].append(info.get("ec_set", 0.0))
    hist["ph_set"].append(info.get("ph_set", 7.0))
    hist["q_f"].append(info.get("q_f", 0.0))
    hist["q_a"].append(info.get("q_a", 0.0))
    hist["irrigation_mm_h"].append(info["irrigation_mm_h"])
    hist["etc_mm_h"].append(info["etc_mm_h"])
    hist["ec_drip"].append(info.get("ec_drip", 0.0))
    hist["ph_drip"].append(info.get("ph_drip", 7.0))
    hist["stage_tag"].append(tag)
    hist["event_idx"].append(idx)
    hist["burn"].append(1.0 if info.get("burn") else 0.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAC-PID 闭环评估")
    parser.add_argument("--model-dir", default="./rl_models")
    parser.add_argument("--model", default=None, help="单一模型路径（不含 .zip）；缺省则自动查找四阶段模型")
    parser.add_argument("--area-ha", type=float, default=0.1)
    parser.add_argument("--dt-min", type=float, default=5.0)
    parser.add_argument("--et0", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--soil-model",
        choices=["lumped_v1", "layered_v2"],
        default="lumped_v1",
        help="评估时使用的土壤模型；应与训练模型时的选择一致。",
    )
    args = parser.parse_args()
    run_eval(args)

