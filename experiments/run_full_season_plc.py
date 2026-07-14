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
   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py `
     --manual-test `
     --fixed-ini-ec 0.8 --fixed-ini-ph 6.2 `
     --fixed-dev-ec 1.1 --fixed-dev-ph 6.1 `
     --fixed-mid-ec 1.5 --fixed-mid-ph 5.9 `
     --fixed-late-ec 1.0 --fixed-late-ph 6.1

        cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\experiments\run_full_season_plc.py `
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
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from sac_model_registry import get_stage_model_path

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


def _enable_compressed_hil_after_handshake(plc, *, max_attempts: int = 8) -> bool:
    """Enable the test-only flag only after the PLC heartbeat is accepted.

    The PLC intentionally clears test flags while Remote_Comms_OK is false.
    A successful Snap7 write alone therefore is not sufficient: wait for the
    heartbeat handshake, write the flag, and verify the value after a scan.
    """
    for attempt in range(1, max_attempts + 1):
        state = plc.read_state() or {}
        if not bool(state.get("Remote_Comms_OK", False)):
            plc.write_feedback(0.8, 6.25, sac_enable=False)
            time.sleep(plc.cycle_s)
            continue

        if not plc.write_compressed_hil_mode(True):
            time.sleep(plc.cycle_s)
            continue

        time.sleep(plc.cycle_s)
        confirmed = plc.read_state() or {}
        if bool(confirmed.get("Remote_Comms_OK", False)) and bool(
            confirmed.get("Compressed_HIL_Enable", False)
        ):
            logger.info("Compressed HIL enabled and verified on attempt %d", attempt)
            return True

        logger.warning(
            "Compressed HIL verification attempt %d/%d failed: CommOK=%s flag=%s",
            attempt,
            max_attempts,
            confirmed.get("Remote_Comms_OK"),
            confirmed.get("Compressed_HIL_Enable"),
        )

    return False

STAGE_SEQUENCE = ("INI", "DEV", "MID", "LATE")
EC_PH_INTEGRAL_LIMIT = 8.0
INTEGRAL_LIMIT_DETECTION_EPSILON = 0.001


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
        base = get_stage_model_path(meta["tag"])
        if not base.with_suffix(".zip").exists():
            fallback = model_dir / f"sac_{meta['tag']}_final"
            if fallback.with_suffix(".zip").exists():
                base = fallback
            else:
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
    ph_target_line, = ax_ph.plot(
        time_day,
        target_ph,
        color="#4e79a7",
        linestyle="--",
        linewidth=1.2,
        alpha=0.65,
        label="目标pH",
    )

    for stage, meta in STAGES.items():
        if meta["start_day"] > 0:
            ax_ec.axvline(meta["start_day"], color="#999999", linestyle=":", linewidth=0.9)
        mid = (meta["start_day"] + meta["end_day"]) / 2.0
        ax_ec.text(mid, 0.98, stage, transform=ax_ec.get_xaxis_transform(), ha="center", va="top", fontsize=9)

    ax_ec.set_title("110天PLC全周期仿真：土壤EC与pH（日均平滑）")
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



def _tail_rows_by_stage(rows: list[dict[str, Any]], fraction: float = 0.25) -> dict[str, list[dict[str, Any]]]:
    """Return the final part of every stage for steady-state acceptance checks."""
    result: dict[str, list[dict[str, Any]]] = {}
    for stage in STAGE_SEQUENCE:
        stage_rows = [row for row in rows if row.get("stage") == stage]
        if not stage_rows:
            continue
        count = min(len(stage_rows), max(3, int(np.ceil(len(stage_rows) * fraction))))
        result[stage] = stage_rows[-count:]
    return result


def _signal_metrics(values: list[float]) -> dict[str, float | None]:
    data = np.asarray(values, dtype=float)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return {"mae": None, "max_abs": None, "mean": None}
    return {
        "mae": float(np.mean(np.abs(finite))),
        "max_abs": float(np.max(np.abs(finite))),
        "mean": float(np.mean(finite)),
    }


def _sustained_oscillation(errors: list[float], tolerance: float) -> bool:
    data = np.asarray(errors, dtype=float)
    data = data[np.isfinite(data)]
    if data.size < 8 or float(np.max(np.abs(data))) <= tolerance:
        return False
    centered = data - float(np.mean(data))
    signs = np.sign(centered)
    signs = signs[signs != 0.0]
    crossings = int(np.count_nonzero(signs[1:] != signs[:-1])) if signs.size > 1 else 0
    return crossings >= 4 and float(np.ptp(data)) > 2.0 * tolerance


def _build_acceptance_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build auditable steady-state and protection metrics for summary.json."""
    steady_groups = _tail_rows_by_stage(rows)
    per_stage: dict[str, Any] = {}
    ec_errors_all: list[float] = []
    ph_errors_all: list[float] = []
    npk_rel_all: dict[str, list[float]] = {"n": [], "p": [], "k": []}

    for stage, stage_rows in steady_groups.items():
        ec_errors = [float(r["plc_ec_target"]) - float(r["plc_ec_actual"]) for r in stage_rows]
        ph_errors = [float(r["plc_ph_target"]) - float(r["plc_ph_actual"]) for r in stage_rows]
        ec_errors_all.extend(ec_errors)
        ph_errors_all.extend(ph_errors)
        stage_metrics: dict[str, Any] = {
            "samples": len(stage_rows),
            "ec_error": _signal_metrics(ec_errors),
            "ph_error": _signal_metrics(ph_errors),
        }
        for nutrient in ("n", "p", "k"):
            relative = []
            for row in stage_rows:
                target = float(row.get(f"{nutrient}_target", 0.0))
                actual = float(row.get(f"{nutrient}_actual", 0.0))
                if bool(row.get("npk_feedback_valid", False)) and abs(target) > 1e-9:
                    relative.append((actual - target) / target)
            stage_metrics[f"{nutrient}_relative_error"] = _signal_metrics(relative)
            npk_rel_all[nutrient].extend(relative)
        per_stage[stage] = stage_metrics

    normal_budget_rows = [r for r in rows if not bool(r.get("npk_capacity_limited", False))]
    budget_errors = [
        float(r.get("q_n_cmd", 0.0)) + float(r.get("q_p_cmd", 0.0))
        + float(r.get("q_k_cmd", 0.0)) - float(r.get("q_f_cmd", 0.0))
        for r in normal_budget_rows
    ]
    ec_summary = _signal_metrics(ec_errors_all)
    ph_summary = _signal_metrics(ph_errors_all)
    npk_summary = {name: _signal_metrics(values) for name, values in npk_rel_all.items()}
    ec_oscillation = any(
        _sustained_oscillation(
            [float(r["plc_ec_target"]) - float(r["plc_ec_actual"]) for r in group], 0.02
        ) for group in steady_groups.values()
    )
    ph_oscillation = any(
        _sustained_oscillation(
            [float(r["plc_ph_target"]) - float(r["plc_ph_actual"]) for r in group], 0.02
        ) for group in steady_groups.values()
    )

    def rate(key: str) -> float:
        return float(np.mean([bool(r.get(key, False)) for r in rows])) if rows else 0.0

    gain_ranges = {}
    for name in (
        "kp_ec_effective", "ki_ec_effective", "kd_ec_effective",
        "kp_ph_effective", "ki_ph_effective", "kd_ph_effective",
    ):
        values = np.asarray([float(r.get(name, 0.0)) for r in rows], dtype=float)
        gain_ranges[name] = {
            "min": float(np.min(values)) if values.size else 0.0,
            "max": float(np.max(values)) if values.size else 0.0,
        }

    integral_max_abs = {
        "ec": float(max((abs(float(r.get("ec_pid_integral", 0.0))) for r in rows), default=0.0)),
        "ph": float(max((abs(float(r.get("ph_pid_integral", 0.0))) for r in rows), default=0.0)),
    }
    steady_rows = [row for group in steady_groups.values() for row in group]
    integral_limit_threshold = EC_PH_INTEGRAL_LIMIT - INTEGRAL_LIMIT_DETECTION_EPSILON
    integral_limit_rates = {
        "ec": float(np.mean([abs(float(r.get("ec_pid_integral", 0.0))) >= integral_limit_threshold for r in steady_rows])) if steady_rows else 0.0,
        "ph": float(np.mean([abs(float(r.get("ph_pid_integral", 0.0))) >= integral_limit_threshold for r in steady_rows])) if steady_rows else 0.0,
    }
    schema_rate = rate("adaptive_schema_available")
    comm_rate = rate("remote_comms_ok")
    adaptive_rate = rate("adaptive_pid_active")
    q_f_limited_rate = rate("q_f_limited")
    q_a_limited_rate = rate("q_a_limited")
    npk_capacity_limited_rate = rate("npk_capacity_limited")
    budget = _signal_metrics(budget_errors)

    checks = {
        "ec_steady_within_0_02": bool(ec_errors_all) and ec_summary["max_abs"] <= 0.02,
        "ph_steady_within_0_02": bool(ph_errors_all) and ph_summary["max_abs"] <= 0.02,
        "npk_steady_within_5_percent": all(
            bool(npk_rel_all[name]) and npk_summary[name]["max_abs"] <= 0.05
            for name in ("n", "p", "k")
        ),
        "fertilizer_budget_consistent": bool(budget_errors) and budget["max_abs"] <= 0.01,
        "plc_comm_at_least_95_percent": comm_rate >= 0.95,
        "adaptive_schema_at_least_95_percent": schema_rate >= 0.95,
        "adaptive_pid_at_least_95_percent": adaptive_rate >= 0.95,
        "no_sustained_oscillation": not (ec_oscillation or ph_oscillation),
        "no_long_output_saturation": q_f_limited_rate <= 0.10 and q_a_limited_rate <= 0.10,
        "no_long_integral_saturation": integral_limit_rates["ec"] <= 0.10 and integral_limit_rates["ph"] <= 0.10,
    }
    return {
        "steady_state_window": "final 25% of samples in each growth stage",
        "per_stage": per_stage,
        "overall_steady": {
            "ec_error": ec_summary,
            "ph_error": ph_summary,
            "npk_relative_error": npk_summary,
        },
        "fertilizer_budget_error": {**budget, "tolerance_abs": 0.01},
        "rates": {
            "plc_comm": comm_rate,
            "adaptive_schema_available": schema_rate,
            "adaptive_pid_active": adaptive_rate,
            "q_f_limited": q_f_limited_rate,
            "q_a_limited": q_a_limited_rate,
            "npk_capacity_limited": npk_capacity_limited_rate,
        },
        "integral_max_abs": integral_max_abs,
        "integral_limit_rates": integral_limit_rates,
        "effective_gain_ranges": gain_ranges,
        "oscillation": {"ec": ec_oscillation, "ph": ph_oscillation},
        "checks": checks,
        "pass": all(checks.values()),
    }

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
        initial_state = plc.read_state()
        if not initial_state or not initial_state.get("adaptive_schema_available", False):
            plc.disconnect()
            raise RuntimeError(
                "PLCSIM is reachable, but DB1 is still the old schema. Import/compile/download "
                "the updated xiaweiji.scl and DB1 in TIA Portal before running this test."
            )

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
    if plc is not None:
        # reset() starts the heartbeat handshake. Enable and read back the
        # test-only flag only after PLC communications are confirmed valid.
        if not _enable_compressed_hil_after_handshake(plc):
            env.close()
            raise RuntimeError(
                "PLC communication became reachable, but Compressed_HIL_Enable "
                "could not be enabled and verified after the heartbeat handshake."
            )
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
                    "plc_ec_target": float(plc_state.get("Active_EC_SP", action[0])),
                    "plc_ph_target": float(plc_state.get("Active_pH_SP", action[1])),
                    "plc_ec_actual": float(plc_state.get("EC_Actual", info.get("ec_soil", 0.0))),
                    "plc_ph_actual": float(plc_state.get("pH_Actual", soil_ph_est)),
                    "ec_pid_error": float(plc_state.get("EC_PID_Error", 0.0)),
                    "ph_pid_error": float(plc_state.get("pH_PID_Error", 0.0)),
                    "kp_ec_base": float(plc_state.get("Kp_EC_Set", 0.0)),
                    "ki_ec_base": float(plc_state.get("Ki_EC_Set", 0.0)),
                    "kd_ec_base": float(plc_state.get("Kd_EC_Set", 0.0)),
                    "kp_ph_base": float(plc_state.get("Kp_pH_Set", 0.0)),
                    "ki_ph_base": float(plc_state.get("Ki_pH_Set", 0.0)),
                    "kd_ph_base": float(plc_state.get("Kd_pH_Set", 0.0)),
                    "kp_ec_effective": float(plc_state.get("Kp_EC_Effective", 0.0)),
                    "ki_ec_effective": float(plc_state.get("Ki_EC_Effective", 0.0)),
                    "kd_ec_effective": float(plc_state.get("Kd_EC_Effective", 0.0)),
                    "kp_ph_effective": float(plc_state.get("Kp_pH_Effective", 0.0)),
                    "ki_ph_effective": float(plc_state.get("Ki_pH_Effective", 0.0)),
                    "kd_ph_effective": float(plc_state.get("Kd_pH_Effective", 0.0)),
                    "ec_pid_integral": float(plc_state.get("EC_PID_Integral", 0.0)),
                    "ph_pid_integral": float(plc_state.get("pH_PID_Integral", 0.0)),
                    "q_f_feedforward": float(plc_state.get("q_f_Feedforward", 0.0)),
                    "q_f_pid_correction": float(plc_state.get("q_f_PID_Correction", 0.0)),
                    "q_f_raw": float(plc_state.get("q_f_raw", 0.0)),
                    "q_f_limited": bool(plc_state.get("q_f_limited", False)),
                    "q_a_feedforward": float(plc_state.get("q_a_Feedforward", 0.0)),
                    "q_a_pid_correction": float(plc_state.get("q_a_PID_Correction", 0.0)),
                    "q_a_raw": float(plc_state.get("q_a_raw", 0.0)),
                    "q_a_limited": bool(plc_state.get("q_a_limited", False)),
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
                    "n_error": float(plc_state.get("N_Error", 0.0)),
                    "p_error": float(plc_state.get("P_Error", 0.0)),
                    "k_error": float(plc_state.get("K_Error", 0.0)),
                    "n_pid_correction": float(plc_state.get("N_PID_Correction", 0.0)),
                    "p_pid_correction": float(plc_state.get("P_PID_Correction", 0.0)),
                    "k_pid_correction": float(plc_state.get("K_PID_Correction", 0.0)),
                    "npk_optimization_weight": float(plc_state.get("NPK_Optimization_Weight", 0.0)),
                    "npk_feedback_valid": bool(plc_state.get("NPK_Feedback_Valid", False)),
                    "npk_capacity_limited": bool(plc_state.get("NPK_Capacity_Limited", False)),
                    "feedforward_hold_active": bool(plc_state.get("Feedforward_Hold_Active", False)),
                    "adaptive_pid_active": bool(plc_state.get("Adaptive_PID_Active", False)),
                    "adaptive_schema_available": bool(plc_state.get("adaptive_schema_available", False)),
                    "compressed_hil_enable": bool(plc_state.get("Compressed_HIL_Enable", False)),
                    "run_mode": (
                        "manual_target" if plc_state.get("Manual_Active", False)
                        else "auto_online" if plc_state.get("SAC_Enable", False) and comm_ok
                        else "auto_local" if plc_state.get("Auto_Active", True)
                        else "standby"
                    ),
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
        "acceptance": _build_acceptance_metrics(rows),
        "final": rows[-1] if rows else {},
        "artifacts": {
            "csv": "full_season_plc_timeseries.csv",
            "soil_ec_ph_png": "soil_ec_ph_by_day.png",
            "npk_ec_ph_png": npk_plot_path.name,
            "adaptive_pid_npk_diagnostics_png": "adaptive_pid_npk_diagnostics.png",
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

