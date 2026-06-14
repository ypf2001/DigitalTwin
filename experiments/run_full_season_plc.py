r"""110 天 SAC + PLC 全生命周期压缩仿真。

这个脚本通过 PLCGymEnv 驱动 PLCSIM/PLC：
SAC 输出 EC/pH 目标值，PLC 根据 EC_Actual/pH_Actual 计算 q_f/q_a，
Python 再用 PLC 输出推动数字孪生模型继续运行。

默认运行模式是 SAC + PLC，不加参数会跑 110 天生命周期，并压缩到约 20 分钟完成。
当 PLC 等待时间为 1 秒时，默认约 1080 步，所以 1 步约等于 0.102 天。

注意：
- 不加 --manual-test：使用 SAC 模型输出 EC_Set_SP / pH_Set_SP。
- 加上 --manual-test：不用 SAC，改用四个生长阶段的固定 EC/pH 目标。

PowerShell 常用运行命令：

1. 默认 SAC + PLC 全生命周期仿真：

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py

2. 固定四阶段 PLC 策略全生命周期仿真：

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py `
     --manual-test `
     --fixed-ini-ec 0.8 --fixed-ini-ph 6.2 `
     --fixed-dev-ec 1.1 --fixed-dev-ph 6.1 `
     --fixed-mid-ec 1.5 --fixed-mid-ph 5.9 `
     --fixed-late-ec 1.0 --fixed-late-ph 6.1

3. 10 天快速 PLC 测试：

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py `
     --manual-test `
     --target-runtime-min 2 `
     --season-days 10 `
     --plc-wait-s 1 `
     --log-every 20 `
     --fixed-ini-ec 0.8 --fixed-ini-ph 6.2 `
     --fixed-dev-ec 1.1 --fixed-dev-ph 6.1 `
     --fixed-mid-ec 1.5 --fixed-mid-ph 5.9 `
     --fixed-late-ec 1.0 --fixed-late-ph 6.1

     .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py `
  --manual-test `
  --target-runtime-min 1 `
  --plc-wait-s 1 `
  --log-every 10

  cd "D:\Digital Twin"
.\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py `
  --manual-test `
  --target-runtime-min 10 `
  --plc-wait-s 1 `
  --log-every 10
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

logger = logging.getLogger(__name__)


STAGES = {
    "INI": {"idx": 0, "tag": "ini", "start_day": 0.0, "end_day": 20.0},
    "DEV": {"idx": 1, "tag": "dev", "start_day": 20.0, "end_day": 50.0},
    "MID": {"idx": 2, "tag": "mid", "start_day": 50.0, "end_day": 75.0},
    "LATE": {"idx": 3, "tag": "late", "start_day": 75.0, "end_day": 110.0},
}

FIXED_ACTIONS = {
    "INI": np.array([0.75, 6.172], dtype=np.float32),
    "DEV": np.array([1.115, 6.068], dtype=np.float32),
    "MID": np.array([1.445, 5.856], dtype=np.float32),
    "LATE": np.array([0.928, 6.072], dtype=np.float32),
}

CROP_TARGETS = {
    "INI": np.array([0.8, 6.2], dtype=np.float32),
    "DEV": np.array([1.2, 6.1], dtype=np.float32),
    "MID": np.array([1.5, 5.9], dtype=np.float32),
    "LATE": np.array([1.0, 6.1], dtype=np.float32),
}

STAGE_SEQUENCE = ("INI", "DEV", "MID", "LATE")


def _fixed_actions_from_args(args: argparse.Namespace) -> dict[str, np.ndarray]:
    return {
        "INI": np.array([args.fixed_ini_ec, args.fixed_ini_ph], dtype=np.float32),
        "DEV": np.array([args.fixed_dev_ec, args.fixed_dev_ph], dtype=np.float32),
        "MID": np.array([args.fixed_mid_ec, args.fixed_mid_ph], dtype=np.float32),
        "LATE": np.array([args.fixed_late_ec, args.fixed_late_ph], dtype=np.float32),
    }


def _estimate_soil_ph(prev_ph: float, ph_drip: float, irrigation_mm_h: float, dt_hours: float) -> float:
    """Estimate root-zone pH from drip pH.

    The current soil model tracks water and EC but not pH. This lightweight
    estimate gives a buffered root-zone pH curve for deployment plots.
    """
    root_depth_mm = 300.0
    exchange = np.clip((irrigation_mm_h * dt_hours) / root_depth_mm, 0.0, 0.25)
    buffered_exchange = 1.20 * exchange
    neutral_relax = 0.0005 * dt_hours
    ph = prev_ph + buffered_exchange * (ph_drip - prev_ph) + neutral_relax * (7.0 - prev_ph)
    return float(np.clip(ph, 4.5, 8.5))


def _json_default(value: Any):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _stage_for_day(day: float) -> str:
    if day < STAGES["DEV"]["start_day"]:
        return "INI"
    if day < STAGES["MID"]["start_day"]:
        return "DEV"
    if day < STAGES["LATE"]["start_day"]:
        return "MID"
    return "LATE"


def _smoothstep(value: float) -> float:
    x = float(np.clip(value, 0.0, 1.0))
    return x * x * (3.0 - 2.0 * x)


def _ramped_stage_pair(day: float, values: dict[str, np.ndarray], transition_days: float) -> np.ndarray:
    stage = _stage_for_day(day)
    current = values[stage].astype(np.float32).copy()
    if transition_days <= 0.0:
        return current

    stage_pos = STAGE_SEQUENCE.index(stage)
    if stage_pos == 0:
        return current

    start_day = STAGES[stage]["start_day"]
    if day >= start_day + transition_days:
        return current

    prev_stage = STAGE_SEQUENCE[stage_pos - 1]
    ratio = _smoothstep((day - start_day) / transition_days)
    return (values[prev_stage] * (1.0 - ratio) + current * ratio).astype(np.float32)


def _ramped_stage_pair_custom(day: float,
                              values: dict[str, np.ndarray],
                              transition_days: float,
                              ec_transition_days: float | None = None,
                              ph_transition_days: float | None = None,
                              ph_down_transition_days: float | None = None,
                              ph_up_transition_days: float | None = None) -> np.ndarray:
    stage = _stage_for_day(day)
    current = values[stage].astype(np.float32).copy()
    stage_pos = STAGE_SEQUENCE.index(stage)
    if stage_pos == 0:
        return current

    start_day = STAGES[stage]["start_day"]
    prev_stage = STAGE_SEQUENCE[stage_pos - 1]
    prev = values[prev_stage].astype(np.float32)

    ec_days = transition_days if ec_transition_days is None else ec_transition_days
    ph_days = transition_days if ph_transition_days is None else ph_transition_days
    if current[1] < prev[1] and ph_down_transition_days is not None:
        ph_days = ph_down_transition_days
    elif current[1] > prev[1] and ph_up_transition_days is not None:
        ph_days = ph_up_transition_days

    result = current.copy()
    for idx, days in ((0, ec_days), (1, ph_days)):
        if days <= 0.0 or day >= start_day + days:
            result[idx] = current[idx]
        else:
            ratio = _smoothstep((day - start_day) / days)
            result[idx] = prev[idx] * (1.0 - ratio) + current[idx] * ratio
    return result.astype(np.float32)


def _load_models(model_dir: Path, single_model: str | None):
    try:
        from stable_baselines3 import SAC
    except ImportError as exc:
        raise RuntimeError("Please install stable-baselines3 before running SAC mode.") from exc

    models = {}
    if single_model:
        path = Path(single_model)
        base = path.with_suffix("") if path.suffix == ".zip" else path
        if not base.with_suffix(".zip").exists():
            raise FileNotFoundError(f"SAC model not found: {base}.zip")
        for stage in STAGES:
            models[stage] = SAC.load(str(base))
        return models

    for stage, meta in STAGES.items():
        base = model_dir / f"sac_{meta['tag']}_final"
        if not base.with_suffix(".zip").exists():
            raise FileNotFoundError(f"SAC model not found: {base}.zip")
        logger.info("Loading SAC model for %s: %s.zip", stage, base)
        models[stage] = SAC.load(str(base))
    return models


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _plot_soil_ec_ph(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if Path(simhei_path).exists():
        fm.fontManager.addfont(simhei_path)
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    raw_day = np.array([row["time_day"] for row in rows], dtype=float)
    raw_ec_soil = np.array([row["ec_soil"] for row in rows], dtype=float)
    raw_soil_ph = np.array([row["soil_ph_est"] for row in rows], dtype=float)
    raw_target_ec = np.array([row["target_ec"] for row in rows], dtype=float)
    raw_target_ph = np.array([row.get("target_ph", 6.0) for row in rows], dtype=float)

    # The compressed run records sub-daily control steps. Plot daily averages
    # with a short rolling mean so irrigation pulses do not dominate the chart.
    day_index = np.floor(raw_day).astype(int)
    days = np.arange(0, int(np.ceil(max(raw_day.max(), 110.0))) + 1)
    time_day = []
    ec_soil = []
    soil_ph = []
    target_ec = []
    target_ph = []
    for day in days:
        mask = day_index == day
        if not mask.any():
            continue
        time_day.append(float(day))
        ec_soil.append(float(np.mean(raw_ec_soil[mask])))
        soil_ph.append(float(np.mean(raw_soil_ph[mask])))
        target_ec.append(float(np.mean(raw_target_ec[mask])))
        target_ph.append(float(np.mean(raw_target_ph[mask])))

    time_day = np.array(time_day, dtype=float)
    ec_soil = _rolling_mean(np.array(ec_soil, dtype=float), window=3)
    soil_ph = _rolling_mean(np.array(soil_ph, dtype=float), window=3)
    target_ec = np.array(target_ec, dtype=float)
    target_ph = np.array(target_ph, dtype=float)

    fig, ax_ec = plt.subplots(figsize=(10, 5.2))
    ax_ph = ax_ec.twinx()

    ec_line, = ax_ec.plot(time_day, ec_soil, color="#2f7d32", linewidth=1.6, label="土壤EC")
    ec_target_line, = ax_ec.plot(
        time_day,
        target_ec,
        color="#2f7d32",
        linestyle="--",
        linewidth=1.3,
        alpha=0.75,
        label="目标EC",
    )
    ph_line, = ax_ph.plot(time_day, soil_ph, color="#4e79a7", linewidth=1.6, label="估算土壤pH")
    ph_target_line = ax_ph.axhline(6.0, color="#4e79a7", linestyle="--", linewidth=1.2, alpha=0.65, label="目标pH")

    for stage, meta in STAGES.items():
        if meta["start_day"] > 0:
            ax_ec.axvline(meta["start_day"], color="#999999", linestyle=":", linewidth=0.9)
        mid = (meta["start_day"] + meta["end_day"]) / 2.0
        ax_ec.text(mid, 0.98, stage, transform=ax_ec.get_xaxis_transform(), ha="center", va="top", fontsize=9)

    ax_ec.set_title("110天SAC+PLC仿真：土壤EC与pH（日均平滑）")
    ax_ec.set_xlabel("天数")
    ax_ec.set_ylabel("土壤EC (dS/m)", color="#2f7d32")
    ax_ph.set_ylabel("估算土壤pH", color="#4e79a7")
    ax_ec.tick_params(axis="y", labelcolor="#2f7d32")
    ax_ph.tick_params(axis="y", labelcolor="#4e79a7")
    ax_ec.set_xlim(0.0, max(110.0, float(time_day[-1])))
    ax_ec.set_ylim(bottom=0.0)
    ax_ph.set_ylim(5.0, 7.5)
    ax_ec.grid(True, axis="y", color="#dddddd", linewidth=0.7)
    ax_ec.spines["top"].set_visible(False)
    ax_ph.spines["top"].set_visible(False)
    ax_ec.legend(
        [ec_line, ec_target_line, ph_line, ph_target_line],
        [ec_line.get_label(), ec_target_line.get_label(), ph_line.get_label(), ph_target_line.get_label()],
        loc="best",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) == 0 or window <= 1:
        return values
    smoothed = np.empty_like(values, dtype=float)
    half = window // 2
    for index in range(len(values)):
        start = max(0, index - half)
        end = min(len(values), index + half + 1)
        smoothed[index] = float(np.mean(values[start:end]))
    return smoothed


def _set_stage(env, plc, stage: str) -> bool:
    env.current_stage = stage
    if plc is None:
        return False
    return plc.write_growth_stage(STAGES[stage]["idx"])


def run(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if args.steps is None:
        runtime_budget_s = max(60.0, args.target_runtime_min * 60.0)
        per_step_s = max(0.05, args.plc_wait_s)
        args.steps = max(1, int(runtime_budget_s * args.runtime_margin / per_step_s))
    dt_min = args.season_days * 24.0 * 60.0 / args.steps
    cfg = load_config()
    action_cfg = cfg.action()

    plc = None
    if args.no_plc:
        from digital_twin_gym_env import DigitalTwinGymEnv
    else:
        try:
            from plc_client import PLCClient
            from plc_gym_env import PLCGymEnv
        except ModuleNotFoundError as exc:
            if exc.name == "snap7":
                raise RuntimeError("Missing python-snap7. Install it with: python -m pip install python-snap7") from exc
            raise

        plc = PLCClient(cycle_s=args.plc_wait_s)
        if not plc.connect():
            raise RuntimeError("PLC connection failed. Check PLCSIM/NetToPLCsim and DB access.")

    models = None if args.manual_test else _load_models(Path(args.model_dir), args.model)
    fixed_actions = _fixed_actions_from_args(args)

    if args.no_plc:
        env = DigitalTwinGymEnv(
            growth_stage="INI",
            area_ha=args.area_ha,
            dt_min=dt_min,
            ep_len_days=args.season_days,
            et0_mm_day=args.et0,
            reward_scale=1.0,
            seed=args.seed,
        )
    else:
        env = PLCGymEnv(
            plc_client=plc,
            plc_enabled=True,
            growth_stage="INI",
            area_ha=args.area_ha,
            dt_min=dt_min,
            ep_len_days=args.season_days,
            et0_mm_day=args.et0,
            reward_scale=1.0,
            seed=args.seed,
        )

    obs, _ = env.reset()
    rows: list[dict[str, Any]] = []
    total_reward = 0.0
    plc_ok_count = 0
    stage_write_supported = False
    current_stage = None
    soil_ph_est = 7.0

    try:
        for step in range(args.steps):
            day = step * dt_min / (24.0 * 60.0)
            stage = _stage_for_day(day)
            if stage != current_stage:
                stage_write_supported = _set_stage(env, plc, stage) or stage_write_supported
                current_stage = stage
                logger.info("Stage changed: day %.1f -> %s", day, stage)

            if args.manual_test:
                action = _ramped_stage_pair_custom(
                    day,
                    fixed_actions,
                    args.transition_days,
                    ec_transition_days=args.ec_transition_days,
                    ph_transition_days=args.ph_transition_days,
                    ph_down_transition_days=args.ph_down_transition_days,
                    ph_up_transition_days=args.ph_up_transition_days,
                )
                ec_min = action_cfg.get("plc_ec_set_min", 0.5)
                ph_min = action_cfg.get("plc_ph_set_min", 5.5)
            else:
                action, _ = models[stage].predict(obs, deterministic=True)
                action = np.asarray(action, dtype=np.float32).flatten()
                ec_min = action_cfg.get("ec_set_min", 0.8)
                ph_min = action_cfg.get("ph_set_min", 5.8)

            action = np.array(
                [
                    np.clip(action[0], ec_min, action_cfg.get("ec_set_max", 2.5)),
                    np.clip(action[1], ph_min, action_cfg.get("ph_set_max", 6.8)),
                ],
                dtype=np.float32,
            )

            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += float(reward)
            if "soil_ph_est" in info:
                soil_ph_est = float(info["soil_ph_est"])
            else:
                soil_ph_est = _estimate_soil_ph(
                    soil_ph_est,
                    float(info.get("ph_drip", 7.0)),
                    float(info.get("irrigation_mm_h", 0.0)),
                    dt_min / 60.0,
                )

            plc_state = info.get("plc", {})
            comm_ok = bool(plc_state.get("Remote_Comms_OK", False))
            plc_ok_count += int(comm_ok)
            crop_target = _ramped_stage_pair(day, CROP_TARGETS, args.transition_days)

            rows.append(
                {
                    "step": step + 1,
                    "time_day": float(info.get("time_day", day)),
                    "stage": stage,
                    "plc_stage": STAGES[stage]["idx"],
                    "ec_set": float(action[0]),
                    "ph_set": float(action[1]),
                    "ec_drip": float(info.get("ec_drip", 0.0)),
                    "ph_drip": float(info.get("ph_drip", 7.0)),
                    "soil_ph_est": soil_ph_est,
                    "theta": float(info.get("theta", 0.0)),
                    "ec_soil": float(info.get("ec_soil", 0.0)),
                    "raw_ec_soil": float(info.get("raw_ec_soil", info.get("ec_soil", 0.0))),
                    "target_ec": float(crop_target[0]),
                    "raw_target_ec": float(info.get("target_ec", 0.0)),
                    "target_ph": float(crop_target[1]),
                    "q_f_cmd": float(plc_state.get("q_f_cmd", info.get("q_f", 0.0))),
                    "q_a_cmd": float(plc_state.get("q_a_cmd", info.get("q_a", 0.0))),
                    "q_n_cmd": float(plc_state.get("q_n_cmd", info.get("q_n", 0.0))),
                    "q_p_cmd": float(plc_state.get("q_p_cmd", info.get("q_p", 0.0))),
                    "q_k_cmd": float(plc_state.get("q_k_cmd", info.get("q_k", 0.0))),
                    "n_actual": float(info.get("n_actual", plc_state.get("N_Actual", 0.0))),
                    "p_actual": float(info.get("p_actual", plc_state.get("P_Actual", 0.0))),
                    "k_actual": float(info.get("k_actual", plc_state.get("K_Actual", 0.0))),
                    "n_target": float(info.get("n_target", plc_state.get("N_Target", 0.0))),
                    "p_target": float(info.get("p_target", plc_state.get("P_Target", 0.0))),
                    "k_target": float(info.get("k_target", plc_state.get("K_Target", 0.0))),
                    "remote_comms_ok": comm_ok,
                    "alarm": bool(plc_state.get("System_Alarm_Light", False)),
                    "burn": bool(info.get("burn", False)),
                    "reward": float(reward),
                }
            )

            if (step + 1) % args.log_every == 0 or step == 0:
                logger.info(
                    "[%03d/%03d] day=%5.1f stage=%s EC_set=%.2f pH_set=%.2f "
                    "q_f=%.3f q_a=%.3f EC_root=%.3f CommOK=%s",
                    step + 1,
                    args.steps,
                    rows[-1]["time_day"],
                    stage,
                    rows[-1]["ec_set"],
                    rows[-1]["ph_set"],
                    rows[-1]["q_f_cmd"],
                    rows[-1]["q_a_cmd"],
                    rows[-1]["ec_soil"],
                    comm_ok,
                )

            if terminated or truncated:
                logger.info("Environment ended at step %d.", step + 1)
                if args.stop_on_end:
                    break
                if hasattr(env, "unwrapped_env"):
                    env.unwrapped_env._done = False

    finally:
        env.close()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "results" / "full_season_plc" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "full_season_plc_timeseries.csv", rows)
    plot_path = out_dir / "soil_ec_ph_by_day.png"
    _plot_soil_ec_ph(plot_path, rows)
    npk_plot_path = out_dir / "npk_ec_ph_execution.png"
    try:
        from experiments.plot_plc_npk_ec_ph import plot as plot_npk_ec_ph

        plot_npk_ec_ph(out_dir)
    except Exception as exc:
        logger.warning("N/P/K EC pH plot failed: %s", exc)

    stats = {
        "run_id": run_id,
        "season_days": args.season_days,
        "steps": len(rows),
        "dt_min": dt_min,
        "days_per_step": dt_min / (24.0 * 60.0),
        "plc_wait_s": args.plc_wait_s,
        "target_runtime_min": args.target_runtime_min,
        "transition_days": args.transition_days,
        "manual_test": args.manual_test,
        "fixed_actions": {stage: action.tolist() for stage, action in fixed_actions.items()},
        "plc_enabled": not args.no_plc,
        "stage_write_supported": stage_write_supported,
        "plc_ok_rate": plc_ok_count / len(rows) if rows else 0.0,
        "total_reward": total_reward,
        "final": rows[-1] if rows else {},
        "artifacts": {
            "csv": "full_season_plc_timeseries.csv",
            "soil_ec_ph_png": "soil_ec_ph_by_day.png",
            "npk_ec_ph_png": npk_plot_path.name,
            "summary": "summary.json",
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return out_dir, stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Run compressed 110-day SAC + PLC simulation.")
    parser.add_argument("--season-days", type=float, default=110.0)
    parser.add_argument("--steps", type=int, default=None, help="Override step count. Default is calculated from --target-runtime-min.")
    parser.add_argument("--target-runtime-min", type=float, default=20.0, help="Approximate PLC run budget. Default is 20 minutes.")
    parser.add_argument("--runtime-margin", type=float, default=0.9, help="Fraction of runtime budget used for PLC waits.")
    parser.add_argument("--plc-wait-s", type=float, default=1.0, help="Seconds to wait for PLC scan/PID each step.")
    parser.add_argument("--model-dir", default=str(ROOT / "rl_models"))
    parser.add_argument("--model", default=None, help="Optional single SAC model path, with or without .zip.")
    parser.add_argument("--manual-test", action="store_true", help="Use fixed four-stage EC/pH targets instead of SAC.")
    parser.add_argument("--fixed-ini-ec", type=float, default=float(FIXED_ACTIONS["INI"][0]))
    parser.add_argument("--fixed-dev-ec", type=float, default=float(FIXED_ACTIONS["DEV"][0]))
    parser.add_argument("--fixed-mid-ec", type=float, default=float(FIXED_ACTIONS["MID"][0]))
    parser.add_argument("--fixed-late-ec", type=float, default=float(FIXED_ACTIONS["LATE"][0]))
    parser.add_argument("--fixed-ini-ph", type=float, default=float(FIXED_ACTIONS["INI"][1]))
    parser.add_argument("--fixed-dev-ph", type=float, default=float(FIXED_ACTIONS["DEV"][1]))
    parser.add_argument("--fixed-mid-ph", type=float, default=float(FIXED_ACTIONS["MID"][1]))
    parser.add_argument("--fixed-late-ph", type=float, default=float(FIXED_ACTIONS["LATE"][1]))
    parser.add_argument(
        "--transition-days",
        type=float,
        default=6.0,
        help="Days used to ramp between lifecycle EC/pH targets. Use 0 for hard fixed stage setpoints.",
    )
    parser.add_argument("--ec-transition-days", type=float, default=None, help="Override transition days for EC setpoints in manual-test mode.")
    parser.add_argument("--ph-transition-days", type=float, default=None, help="Override transition days for pH setpoints in manual-test mode.")
    parser.add_argument("--ph-down-transition-days", type=float, default=3.0, help="pH transition days when the next stage pH setpoint is lower.")
    parser.add_argument("--ph-up-transition-days", type=float, default=None, help="pH transition days when the next stage pH setpoint is higher.")
    parser.add_argument("--no-plc", action="store_true", help="Run the same loop without PLC connection for script testing.")
    parser.add_argument("--stop-on-end", action="store_true", help="Stop when the digital twin reports burn/end instead of completing all steps.")
    parser.add_argument("--area-ha", type=float, default=0.1)
    parser.add_argument("--et0", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-every", type=int, default=10)
    args = parser.parse_args()

    out_dir, stats = run(args)
    logger.info("Full-season PLC run saved to: %s", out_dir)
    logger.info(
        "steps=%d, one_step=%.3f day, plc_ok_rate=%.1f%%, stage_write_supported=%s",
        stats["steps"],
        stats["days_per_step"],
        stats["plc_ok_rate"] * 100.0,
        stats["stage_write_supported"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
