r"""PID 参数 Python 粗调脚本。

用途：
1. 不连接 PLC，先用数字孪生快速筛选 Kp/Ki/Kd 候选范围。
2. 评分会重点惩罚超过设定值，因为当前控制要求是“宁愿少，不能超过”。
3. 输出的最佳参数只是 PLC 精调候选，最终参数仍要下载到 PLC/PLCSIM 后确认。

运行示例：

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\tune_pid_coarse.py --mode fixed --trials 80 --season-days 10

SAC 目标粗调：

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\tune_pid_coarse.py --mode sac --trials 80 --season-days 10

更快测试：

   cd "D:\Digital Twin"
   .\.venv\Scripts\python.exe .\plc\tuning\tune_pid_coarse.py --trials 20 --season-days 5
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from digital_twin_env import DigitalTwinEnv
from digital_twin_gym_env import STAGE_MAP
from experiments.run_full_season_plc import FIXED_ACTIONS, STAGES, _estimate_soil_ph, _stage_for_day


GAIN_BOUNDS = {
    "kp_ec": (0.2, 1.4),
    "ki_ec": (0.0, 0.012),
    "kd_ec": (0.0, 0.04),
    "kp_ph": (0.6, 2.2),
    "ki_ph": (0.0, 0.012),
    "kd_ph": (0.0, 0.04),
}


DEFAULT_GAIN_STEPS = {
    "kp_ec": 0.1,
    "ki_ec": 0.001,
    "kd_ec": 0.001,
    "kp_ph": 0.1,
    "ki_ph": 0.001,
    "kd_ph": 0.001,
}


@dataclass(frozen=True)
class PIDCandidate:
    kp_ec: float
    ki_ec: float
    kd_ec: float
    kp_ph: float
    ki_ph: float
    kd_ph: float


@dataclass
class RateLimiter:
    max_up: float
    max_down: float
    value: float = 0.0

    def step(self, target: float, dt_s: float) -> float:
        delta = target - self.value
        if delta > self.max_up * dt_s:
            delta = self.max_up * dt_s
        elif delta < -self.max_down * dt_s:
            delta = -self.max_down * dt_s
        self.value += delta
        return self.value


class PLCLikePID:
    """Python 版 PLC 执行层近似模型，用于快速粗调。"""

    def __init__(self, candidate: PIDCandidate):
        cfg = load_config()
        action = cfg.action()
        tank = cfg.mixing_tank()

        self.c = candidate
        self.q_w = float(cfg.env().get("q_w", 136.0))
        self.ec_conc = float(tank.get("ec_conc", 35.0))
        self.q_f_min = float(action.get("q_f_min", 0.0))
        self.q_f_max = float(action.get("q_f_max", 10.0))
        self.q_a_min = float(action.get("q_a_min", 0.0))
        self.q_a_max = float(action.get("q_a_max", 4.0))

        self.ec_i = 0.0
        self.ph_i = 0.0
        self.ec_last = 0.0
        self.ph_last = 0.0
        self.rl_f = RateLimiter(max_up=1.5, max_down=2.0)
        self.rl_a = RateLimiter(max_up=1.0, max_down=1.2)

    def step(self, ec_sp: float, ph_sp: float, ec_actual: float, ph_actual: float, dt_s: float) -> tuple[float, float]:
        ec_error = ec_sp - ec_actual
        ph_error = ph_actual - ph_sp

        if abs(ec_error) < 0.04:
            ec_error = 0.0
        if abs(ph_error) < 0.04:
            ph_error = 0.0

        self.ec_i = float(np.clip(self.ec_i + ec_error * dt_s, -5.0, 5.0))
        self.ph_i = float(np.clip(self.ph_i + ph_error * dt_s, -5.0, 5.0))
        ec_d = (ec_error - self.ec_last) / dt_s if dt_s > 0 else 0.0
        ph_d = (ph_error - self.ph_last) / dt_s if dt_s > 0 else 0.0
        self.ec_last = ec_error
        self.ph_last = ph_error

        if 0.0 < ec_sp < self.ec_conc - 1.0:
            q_f_ff = 0.92 * (ec_sp * self.q_w) / (self.ec_conc - ec_sp)
        else:
            q_f_ff = 0.0

        if ec_error > 0.35:
            q_f_corr = 2.50 * ec_error + 0.80
        elif ec_error > 0.08:
            q_f_corr = 1.60 * ec_error + 0.20
        elif ec_error > 0.03:
            q_f_corr = self.c.kp_ec * ec_error + self.c.ki_ec * self.ec_i + self.c.kd_ec * ec_d
        elif ec_error < -0.08:
            q_f_corr = 3.50 * ec_error
        elif ec_error < -0.03:
            q_f_corr = 2.00 * ec_error
        else:
            q_f_corr = 0.0

        if ph_sp <= 5.95:
            q_a_ff = 1.10
        elif ph_sp <= 6.15:
            q_a_ff = 1.05
        elif ph_sp <= 6.30:
            q_a_ff = 0.80
        else:
            q_a_ff = 0.0

        if ph_error > 0.45:
            q_a_corr = self.q_a_max
        elif ph_error > 0.25:
            q_a_corr = 3.20 * ph_error + 0.85
        elif ph_error > 0.0:
            q_a_corr = self.c.kp_ph * ph_error + self.c.ki_ph * self.ph_i + self.c.kd_ph * ph_d
        elif ph_error < -0.10:
            q_a_corr = 2.50 * ph_error
        else:
            q_a_corr = 0.0

        q_f_target = q_f_ff + q_f_corr
        q_a_target = q_a_ff + q_a_corr

        # 硬保护：粗调阶段也按 PLC 的“宁愿少，不能超过”约束评分。
        if ec_actual >= ec_sp - 0.02:
            q_f_target = 0.0
            self.ec_i = 0.0
        if ph_actual <= ph_sp + 0.03:
            q_a_target = 0.0
            self.ph_i = 0.0

        q_f_target = float(np.clip(q_f_target, self.q_f_min, self.q_f_max))
        q_a_target = float(np.clip(q_a_target, self.q_a_min, self.q_a_max))
        return self.rl_f.step(q_f_target, dt_s), self.rl_a.step(q_a_target, dt_s)


def _sample_gain(
    name: str,
    rng: np.random.Generator,
    center: PIDCandidate | None = None,
    radius: float = 1.0,
    step: float | None = None,
) -> float:
    low, high = GAIN_BOUNDS[name]
    if center is None:
        return _quantize_gain(float(rng.uniform(low, high)), low, high, step)

    center_value = float(getattr(center, name))
    half_width = (high - low) * max(radius, 0.0) * 0.5
    local_low = max(low, center_value - half_width)
    local_high = min(high, center_value + half_width)
    if local_high <= local_low:
        return _quantize_gain(center_value, low, high, step)
    return _quantize_gain(float(rng.uniform(local_low, local_high)), low, high, step)


def _quantize_gain(value: float, low: float, high: float, step: float | None) -> float:
    if step is None or step <= 0:
        return float(np.clip(value, low, high))
    quantized = round(value / step) * step
    return float(np.clip(round(quantized, 6), low, high))


def _sample_candidate(
    rng: np.random.Generator,
    center: PIDCandidate | None = None,
    radius: float = 1.0,
    gain_steps: dict[str, float] | None = None,
) -> PIDCandidate:
    gain_steps = gain_steps or DEFAULT_GAIN_STEPS
    return PIDCandidate(
        kp_ec=_sample_gain("kp_ec", rng, center, radius, gain_steps.get("kp_ec")),
        ki_ec=_sample_gain("ki_ec", rng, center, radius, gain_steps.get("ki_ec")),
        kd_ec=_sample_gain("kd_ec", rng, center, radius, gain_steps.get("kd_ec")),
        kp_ph=_sample_gain("kp_ph", rng, center, radius, gain_steps.get("kp_ph")),
        ki_ph=_sample_gain("ki_ph", rng, center, radius, gain_steps.get("ki_ph")),
        kd_ph=_sample_gain("kd_ph", rng, center, radius, gain_steps.get("kd_ph")),
    )


def _candidate_from_row(row: dict[str, Any]) -> PIDCandidate:
    return PIDCandidate(
        kp_ec=float(row["kp_ec"]),
        ki_ec=float(row["ki_ec"]),
        kd_ec=float(row["kd_ec"]),
        kp_ph=float(row["kp_ph"]),
        ki_ph=float(row["ki_ph"]),
        kd_ph=float(row["kd_ph"]),
    )


def _meets_targets(row: dict[str, Any], args: argparse.Namespace) -> bool:
    return (
        row["ec_mae"] <= args.target_ec_mae
        and row["ph_mae"] <= args.target_ph_mae
        and row["ec_over_max"] <= args.target_ec_over
        and row["ph_over_max"] <= args.target_ph_over
    )


def _load_sac_models(model_dir: Path, single_model: str | None):
    try:
        from stable_baselines3 import SAC
    except ImportError as exc:
        raise RuntimeError("SAC mode requires stable-baselines3.") from exc

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
        models[stage] = SAC.load(str(base))
    return models


def _build_obs(env: DigitalTwinEnv) -> np.ndarray:
    obs = env._get_obs()
    low = np.array(load_config().obs()["obs_low"], dtype=np.float32)
    high = np.array(load_config().obs()["obs_high"], dtype=np.float32)
    return ((obs - low) / (high - low + 1e-8) * 2.0 - 1.0).astype(np.float32)


def evaluate_candidate(
    candidate: PIDCandidate,
    season_days: float,
    dt_min: float,
    seed: int,
    mode: str,
    models: dict[str, Any] | None,
) -> dict[str, Any]:
    env = DigitalTwinEnv(growth_stage=STAGE_MAP["INI"], dt_min=dt_min, ep_len_days=season_days, seed=seed)
    env.reset()
    controller = PLCLikePID(candidate)

    steps = int(season_days * 24.0 * 60.0 / dt_min)
    dt_hours = dt_min / 60.0
    dt_s = dt_min * 60.0
    soil_ph = 7.0
    last_q_f = 0.0
    last_q_a = 0.0

    ec_abs_errors: list[float] = []
    ph_abs_errors: list[float] = []
    ec_overs: list[float] = []
    ph_overs: list[float] = []
    flow_moves: list[float] = []

    for step in range(steps):
        day = step * dt_min / (24.0 * 60.0)
        stage_name = _stage_for_day(day)
        env.set_growth_stage(STAGE_MAP[stage_name])
        if mode == "sac":
            if models is None:
                raise RuntimeError("SAC mode requires loaded models.")
            obs = _build_obs(env)
            action, _ = models[stage_name].predict(obs, deterministic=True)
            action = np.asarray(action, dtype=np.float32).flatten()
            action_cfg = load_config().action()
            ec_sp = float(np.clip(action[0], action_cfg.get("ec_set_min", 0.8), action_cfg.get("ec_set_max", 2.5)))
            ph_sp = float(np.clip(action[1], action_cfg.get("ph_set_min", 5.8), action_cfg.get("ph_set_max", 6.8)))
        else:
            ec_sp, ph_sp = FIXED_ACTIONS[stage_name]
            ec_sp = float(ec_sp)
            ph_sp = float(ph_sp)

        q_f, q_a = controller.step(ec_sp, ph_sp, env.soil.ec_soil, soil_ph, dt_s)
        if env._is_nighttime(env._time_min):
            q_f = 0.0
            q_a = 0.0
            q_w = 0.0
        else:
            q_w = env.q_w

        total_flow = q_f + q_a + q_w
        irrigation_mm_h = total_flow * 60.0 / (env.area_ha * 10000.0)
        ec_tank, ph_tank = env.tank.step(q_f, q_a, q_w=q_w)
        ec_drip, ph_drip = env.pipe.step(ec_tank, ph_tank)
        et_mm_h = env._get_actual_et(env._time_min)
        theta, ec_soil = env.soil.step(irrigation_mm_h, ec_drip, et_mm_h, dt_hours)
        soil_ph = _estimate_soil_ph(soil_ph, ph_drip, irrigation_mm_h, dt_hours)

        env._theta_history.append(theta)
        env._ec_soil_history.append(ec_soil)
        env._ec_in_history.append(ec_drip)
        env._ph_in_history.append(ph_drip)
        env._time_min += dt_min
        env._total_steps += 1

        ec_abs_errors.append(abs(ec_soil - ec_sp))
        ph_abs_errors.append(abs(soil_ph - ph_sp))
        ec_overs.append(max(0.0, ec_soil - ec_sp))
        # pH 目标是上限约束：低一点可以，高于目标要重罚。
        ph_overs.append(max(0.0, soil_ph - ph_sp))
        flow_moves.append(abs(q_f - last_q_f) + abs(q_a - last_q_a))
        last_q_f = q_f
        last_q_a = q_a

    ec_mae = float(np.mean(ec_abs_errors))
    ph_mae = float(np.mean(ph_abs_errors))
    ec_over_max = float(np.max(ec_overs))
    ph_over_max = float(np.max(ph_overs))
    flow_move_mean = float(np.mean(flow_moves))
    score = (
        ec_mae
        + 0.8 * ph_mae
        + 25.0 * ec_over_max
        + 12.0 * ph_over_max
        + 0.03 * flow_move_mean
    )

    return {
        **asdict(candidate),
        "score": float(score),
        "ec_mae": ec_mae,
        "ph_mae": ph_mae,
        "ec_over_max": ec_over_max,
        "ph_over_max": ph_over_max,
        "flow_move_mean": flow_move_mean,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Python coarse tuning for PLC PID candidates.")
    parser.add_argument("--mode", choices=["fixed", "sac"], default="fixed", help="fixed uses four-stage targets; sac loads SAC models.")
    parser.add_argument("--trials", type=int, default=80)
    parser.add_argument("--season-days", type=float, default=10.0)
    parser.add_argument("--dt-min", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--model-dir", default=str(ROOT / "rl_models"))
    parser.add_argument("--model", default=None, help="Optional single SAC model path, with or without .zip.")
    parser.add_argument("--auto", action="store_true", help="Keep refining around the best candidate until target metrics are met.")
    parser.add_argument("--max-rounds", type=int, default=8, help="Maximum auto-refine rounds.")
    parser.add_argument("--round-trials", type=int, default=None, help="Trials per auto-refine round. Defaults to --trials.")
    parser.add_argument("--refine-shrink", type=float, default=0.55, help="Search radius multiplier after each auto round.")
    parser.add_argument("--min-radius", type=float, default=0.04, help="Minimum local search radius as a fraction of each gain range.")
    parser.add_argument("--target-ec-mae", type=float, default=0.08)
    parser.add_argument("--target-ph-mae", type=float, default=0.08)
    parser.add_argument("--target-ec-over", type=float, default=0.02)
    parser.add_argument("--target-ph-over", type=float, default=0.03)
    parser.add_argument("--kp-step", type=float, default=DEFAULT_GAIN_STEPS["kp_ec"], help="Quantize Kp gains to this step. Default is 0.1.")
    parser.add_argument("--ki-step", type=float, default=DEFAULT_GAIN_STEPS["ki_ec"], help="Quantize Ki gains to this step. Default is 0.001.")
    parser.add_argument("--kd-step", type=float, default=DEFAULT_GAIN_STEPS["kd_ec"], help="Quantize Kd gains to this step. Default is 0.001.")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    models = _load_sac_models(Path(args.model_dir), args.model) if args.mode == "sac" else None
    gain_steps = {
        "kp_ec": args.kp_step,
        "ki_ec": args.ki_step,
        "kd_ec": args.kd_step,
        "kp_ph": args.kp_step,
        "ki_ph": args.ki_step,
        "kd_ph": args.kd_step,
    }
    results = []
    best: dict[str, Any] | None = None
    stop_reason = "completed_fixed_trials"

    if args.auto:
        round_trials = args.round_trials or args.trials
        center: PIDCandidate | None = None
        radius = 1.0
        trial_no = 0
        for round_no in range(1, args.max_rounds + 1):
            print(f"\nAuto round {round_no}/{args.max_rounds}: trials={round_trials}, radius={radius:.4f}")
            round_rows = []
            for i in range(round_trials):
                trial_no += 1
                candidate = _sample_candidate(rng, center=center, radius=radius, gain_steps=gain_steps)
                row = evaluate_candidate(candidate, args.season_days, args.dt_min, args.seed + trial_no, args.mode, models)
                row["trial"] = trial_no
                row["round"] = round_no
                results.append(row)
                round_rows.append(row)
                print(
                    f"[R{round_no:02d} {i + 1:03d}/{round_trials}] score={row['score']:.4f} "
                    f"EC_MAE={row['ec_mae']:.4f} pH_MAE={row['ph_mae']:.4f} "
                    f"EC_over={row['ec_over_max']:.4f} pH_over={row['ph_over_max']:.4f}"
                )

            round_rows.sort(key=lambda x: x["score"])
            best = min(results, key=lambda x: x["score"])
            center = _candidate_from_row(best)
            print(
                f"Round best score={round_rows[0]['score']:.4f}; "
                f"global best score={best['score']:.4f}"
            )
            if _meets_targets(best, args):
                stop_reason = "target_metrics_met"
                break
            radius = max(args.min_radius, radius * args.refine_shrink)
        else:
            stop_reason = "max_rounds_reached"
    else:
        for i in range(args.trials):
            candidate = _sample_candidate(rng, gain_steps=gain_steps)
            row = evaluate_candidate(candidate, args.season_days, args.dt_min, args.seed + i, args.mode, models)
            row["trial"] = i + 1
            row["round"] = 1
            results.append(row)
            print(
                f"[{i + 1:03d}/{args.trials}] score={row['score']:.4f} "
                f"EC_MAE={row['ec_mae']:.4f} pH_MAE={row['ph_mae']:.4f} "
                f"EC_over={row['ec_over_max']:.4f} pH_over={row['ph_over_max']:.4f}"
            )

    results.sort(key=lambda x: x["score"])
    best = results[0]
    out_dir = ROOT / "results" / "pid_tuning" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "pid_coarse_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "mode": args.mode,
        "auto": args.auto,
        "season_days": args.season_days,
        "dt_min": args.dt_min,
        "trials": len(results),
        "stop_reason": stop_reason,
        "targets": {
            "ec_mae": args.target_ec_mae,
            "ph_mae": args.target_ph_mae,
            "ec_over_max": args.target_ec_over,
            "ph_over_max": args.target_ph_over,
        },
        "gain_steps": gain_steps,
        "best": best,
        "top": results[: args.top_k],
        "note": "These are Python coarse-tuning candidates. Confirm final PID values with PLC/PLCSIM.",
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nBest candidate:")
    print(json.dumps(best, ensure_ascii=False, indent=2))
    print(f"Stop reason: {stop_reason}")
    print(f"\nSaved: {csv_path}")
    print(f"Saved: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
