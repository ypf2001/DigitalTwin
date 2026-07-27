"""
灌溉事件调度器 — 基于论文 Table 9
=================================
实现等量灌溉 (T1) 和基于根系分布的变量灌溉 (T2) 两种策略。

论文数据 (乌兰 2022，内蒙古农业大学):
  - 出苗后天数: 5, 15, 24, 31, 38, 45, 55, 65
  - T1 (等量): 每次 225 m³/ha (22.5 mm)
  - T2 (变量): 90, 90, 195, 195, 345, 345, 345, 195 m³/ha
  - 总灌溉量: 1800 m³/ha (180 mm)，8 次事件
  - 滴头流量: 2.2 L/h，间距 0.3m，操作压力 0.1 MPa
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional
import logging

from crop_model import GrowthStage
from config_loader import load_config
from residual_action import ResidualActionProjector, SeasonBudgetGuard

import os

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')
_error_fh = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'), encoding='utf-8')
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)

_irr_cfg = load_config().irrigation()
EMITTERS_PER_HA = _irr_cfg["emitters_per_ha"]
EMITTER_FLOW_LPH = _irr_cfg["emitter_flow_lph"]


@dataclass
class IrrigationEvent:
    """单次灌溉事件。"""
    day: float                         # 出苗后天数
    growth_stage: GrowthStage          # 当前生育阶段
    t1_amount_m3ha: float             # T1 灌溉量 (m³/ha)
    t2_amount_m3ha: float             # T2 灌溉量 (m³/ha)
    control_stage: str                 # V2母液/EC控制阶段 INI/DEV/MID/LATE

    @property
    def t1_mm(self) -> float:
        """T1 灌溉量换算为 mm。"""
        return self.t1_amount_m3ha / 10.0

    @property
    def t2_mm(self) -> float:
        """T2 灌溉量换算为 mm。"""
        return self.t2_amount_m3ha / 10.0


# 灌溉计划从配置文件读取
_STAGE_KEY_TO_ENUM = {
    "emergence": GrowthStage.EMERGENCE,
    "vegetative": GrowthStage.VEGETATIVE,
    "tuber_init": GrowthStage.TUBER_INIT,
    "bulking": GrowthStage.BULKING,
    "starch_accumulation": GrowthStage.STARCH_ACCUMULATION,
    "maturation": GrowthStage.MATURATION,
}

_SCHEDULE_DATA = []
for entry in _irr_cfg["schedule"]:
    day, stage_key, t1, t2 = entry
    _SCHEDULE_DATA.append((float(day), _STAGE_KEY_TO_ENUM[stage_key], float(t1), float(t2)))


def normalize_obs(obs: np.ndarray) -> np.ndarray:
    """Normalize raw DigitalTwinEnv observations to the SAC training range."""
    obs_cfg = load_config().obs()
    obs_low = np.array(obs_cfg["obs_low"], dtype=np.float32)
    obs_high = np.array(obs_cfg["obs_high"], dtype=np.float32)
    eps = 1e-6
    normalized = 2.0 * (obs - obs_low) / (obs_high - obs_low + eps) - 1.0
    return np.clip(normalized, -1.0, 1.0).astype(np.float32)


def get_irrigation_schedule() -> List[IrrigationEvent]:
    """返回8次事件，同时保留生物学阶段与配方控制阶段。"""
    recipes = load_config().thesis_experiment_v2()["irrigation"]["control_recipe_by_event"]
    events = []
    for index, (day, _paper_stage, t1, t2) in enumerate(_SCHEDULE_DATA):
        if day <= 20:
            biological = GrowthStage.EMERGENCE
        elif day <= 35:
            biological = GrowthStage.TUBER_INIT
        else:
            biological = GrowthStage.BULKING
        events.append(IrrigationEvent(day, biological, t1, t2, str(recipes[index])))
    return events


def event_duration_hours(amount_m3ha: float, area_ha: float) -> float:
    """计算单次灌溉事件的持续时间 (小时)。

    参数
    ----------
    amount_m3ha : float
        灌溉量 (m³/ha)
    area_ha : float
        灌溉面积 (ha)

    返回
    ----------
    duration : float
        事件持续时间 (h)
    """
    total_emitters = EMITTERS_PER_HA * area_ha
    total_flow_Lmin = total_emitters * EMITTER_FLOW_LPH / 60.0
    total_volume_L = amount_m3ha * area_ha * 1000.0
    if total_flow_Lmin <= 0:
        return 0.0
    return total_volume_L / total_flow_Lmin / 60.0


def run_season_simulation(
    env,
    model=None,
    strategy: str = "T2",
    area_ha: float = 0.1,
    dt_min: float = 15.0,
    rain_mm_day: float = None,
    initial_theta: float = None,
    initial_ec: float = None,
    fixed_action: np.ndarray = None,
    season_days: float = None,
    verbose: bool = True,
) -> dict:
    irr = load_config().irrigation()
    season_cfg = load_config().season_comparison()
    if rain_mm_day is None:
        rain_mm_day = irr["rain_mm_day"]
    if initial_theta is None:
        initial_theta = irr.get("initial_theta") or env.soil.theta_fc
    if initial_ec is None:
        initial_ec = irr["initial_ec"]
    if season_days is None:
        season_days = season_cfg.get("ep_len_days", 90.0)
    """运行完整生育期仿真（8 次灌溉事件）。

    参数
    ----------
    env : DigitalTwinEnv
        数字孪生环境实例
    model : stable_baselines3 model, optional
        RL 模型，若为 None 则使用 fixed_action
    strategy : str
        "T1" = 等量灌溉, "T2" = 变量灌溉（基于根系分布）
    area_ha : float
        灌溉面积 (ha)
    dt_min : float
        仿真步长 (分钟)
    fixed_action : np.ndarray, optional
        固定残差动作 [water_multiplier, EC_residual]（model=None 时使用）
    verbose : bool
        是否打印进度

    返回
    ----------
    results : dict
        包含 time_day, theta, ec_soil, target_ec, ec_set, ph_set, q_f, q_a,
        total_irrigation_mm, etc_cumulative_mm 等
    """
    if fixed_action is None:
        fixed_action = np.array(
            load_config().action().get("fixed_strategy", [1.0, 0.0]),
            dtype=np.float32,
        )

    schedule = get_irrigation_schedule()
    dt_hours = dt_min / 60.0
    baseline_event_water_l = [
        (event.t1_amount_m3ha if strategy == "T1" else event.t2_amount_m3ha)
        * area_ha * 1000.0
        for event in schedule
    ]
    budget_guard = SeasonBudgetGuard(
        baseline_water_l=sum(baseline_event_water_l),
        baseline_nutrient_g=0.0,
    )
    action_projector = ResidualActionProjector()

    # 初始化记录
    history = {
        "time_day": [],
        "theta": [],
        "ec_soil": [],
        "target_ec": [],
        "ec_set": [],
        "ph_set": [],
        "q_f": [],
        "q_a": [],
        "irrigation_mm_h": [],
        "etc_mm_h": [],
        "ec_drip": [],
        "stage": [],
        "event_marker": [],  # 1 = during irrigation event, 0 = between events
        "water_multiplier": [],
        "ec_residual": [],
        "budget_limited": [],
        "batch_target_volume_l": [],
    }

    obs = env.reset()
    if getattr(env, "soil_model", "lumped_v1") == "lumped_v1":
        env.soil.theta = initial_theta
        env.soil.ec_soil = initial_ec
        # 更新历史缓冲以匹配新的初始 theta。
        env._theta_history.clear()
        env._ec_soil_history.clear()
        for _ in range(env.history_len):
            env._theta_history.append(initial_theta)
            env._ec_soil_history.append(initial_ec)
    # layered_v2 使用 soil_v2.yaml 中的分层初始剖面，避免用单一标量覆盖田间参数。
    total_irrigation_mm = 0.0
    total_scheduled_irrigation_mm = 0.0
    total_etc_mm = 0.0
    total_steps = 0

    # 按事件推进
    prev_day = 0.0
    for event_idx, event in enumerate(schedule):
        # 切换到当前事件的生育阶段
        control_enum = {"INI": GrowthStage.EMERGENCE, "DEV": GrowthStage.TUBER_INIT,
                        "MID": GrowthStage.BULKING, "LATE": GrowthStage.STARCH_ACCUMULATION}[event.control_stage]
        env.set_growth_stage(event.growth_stage, control_stage=control_enum)

        # 非灌溉期：从 prev_day 到 event.day（只发生 ET + 降雨）
        dry_hours = (event.day - prev_day) * 24.0
        dry_steps = int(dry_hours / dt_hours)
        rain_mm_h = rain_mm_day / 24.0  # 日均降雨 → 时均
        for _ in range(dry_steps):
            obs, _, done, info = env.dry_step(rain_mm_h=rain_mm_h)
            total_steps += 1
            total_etc_mm += info["etc_mm_h"] * dt_hours

            _record_step(history, info, np.array([0.0, 0.0]), event_idx, is_event=False)

        # 灌溉期：一次论文定额是清水预冲洗、载肥水和清水后冲洗的总量。
        # 主水泵按累计水量结束，持续时间仅用于防止配置/执行异常导致无限循环。
        amount = event.t1_amount_m3ha if strategy == "T1" else event.t2_amount_m3ha
        total_scheduled_irrigation_mm += amount / 10.0
        if model is not None:
            event_action, _ = model.predict(normalize_obs(obs), deterministic=True)
        else:
            event_action = fixed_action.copy()
        projected = action_projector.project(
            event_action,
            stage_ec=env.crop.get_target_ec(control_enum),
        )
        requested_volume_l = baseline_event_water_l[event_idx] * projected.water_multiplier
        remaining_water_l = sum(baseline_event_water_l[event_idx + 1:])
        target_volume_l, _, budget_limited = budget_guard.project_event(
            requested_volume_l,
            0.0,
            remaining_baseline_water_l=remaining_water_l,
        )
        env.set_irrigation_command(
            enabled=True,
            target_volume_l=target_volume_l,
            reset_volume=True,
        )
        projected_amount_m3ha = target_volume_l / max(area_ha * 1000.0, 1e-9)
        event_hours = event_duration_hours(projected_amount_m3ha, area_ha)
        max_event_steps = max(2, int(np.ceil(event_hours / dt_hours)) + 8)

        event_irr_total = 0.0
        for _ in range(max_event_steps):
            # One slow action is sampled at event start and held for the
            # complete batch. Fast EC/pH loops remain inside the executor/PLC.
            obs, reward, done, info = env.step(event_action)
            info["budget_limited"] = bool(budget_limited)
            info["batch_target_volume_l"] = float(target_volume_l)
            total_steps += 1
            # The agronomic quota is main carrier water. Fertilizer/acid stock
            # solution remains part of the hydraulic model but not the paper's
            # irrigation-water accounting.
            carrier_mm_h = info.get("carrier_irrigation_mm_h", info["irrigation_mm_h"])
            total_irrigation_mm += carrier_mm_h * dt_hours
            event_irr_total += carrier_mm_h * dt_hours
            total_etc_mm += info["etc_mm_h"] * dt_hours

            _record_step(history, info, event_action, event_idx, is_event=True)

            if bool(info.get("water_volume_complete", False)):
                break
        else:
            raise RuntimeError(
                f"Irrigation event {event_idx + 1} did not reach its water-volume target "
                f"within {max_event_steps} simulation steps."
            )

        if verbose:
            target_ec = env.crop.get_target_ec(control_enum)
            logger.info(f"  事件 {event_idx+1}/8  day {event.day:3.0f}  "
                        f"stage={event.growth_stage.value:12s}/{event.control_stage:4s}  "
                        f"{strategy}={amount:3.0f} m^3/ha  "
                        f"duration={event_hours:.1f}h  "
                        f"m_w={projected.water_multiplier:.3f}  "
                        f"irr_applied={event_irr_total:.1f}mm  "
                        f"theta={info['theta']:.3f}  EC={info['ec_soil']:.3f}")

        prev_day = event.day

    # 最后一次灌溉后继续推进到完整生育期，避免统计只到 day 65。
    current_day = env._time_min / (24.0 * 60.0)
    tail_hours = max(0.0, (season_days - current_day) * 24.0)
    tail_steps = int(tail_hours / dt_hours)
    rain_mm_h = rain_mm_day / 24.0
    if schedule:
        env.set_growth_stage(GrowthStage.STARCH_ACCUMULATION)
    for _ in range(tail_steps):
        obs, _, done, info = env.dry_step(rain_mm_h=rain_mm_h)
        total_steps += 1
        total_etc_mm += info["etc_mm_h"] * dt_hours
        _record_step(history, info, np.array([0.0, 0.0]), len(schedule), is_event=False)

    results = {
        "time_day": np.array(history["time_day"]),
        "theta": np.array(history["theta"]),
        "ec_soil": np.array(history["ec_soil"]),
        "target_ec": np.array(history["target_ec"]),
        "ec_set": np.array(history["ec_set"]),
        "ph_set": np.array(history["ph_set"]),
        "q_f": np.array(history["q_f"]),
        "q_a": np.array(history["q_a"]),
        "irrigation_mm_h": np.array(history["irrigation_mm_h"]),
        "etc_mm_h": np.array(history["etc_mm_h"]),
        "ec_drip": np.array(history["ec_drip"]),
        "stage": history["stage"],
        "event_marker": np.array(history["event_marker"]),
        "water_multiplier": np.array(history["water_multiplier"]),
        "ec_residual": np.array(history["ec_residual"]),
        "budget_limited": np.array(history["budget_limited"], dtype=bool),
        "batch_target_volume_l": np.array(history["batch_target_volume_l"]),
        "total_irrigation_mm": total_irrigation_mm,
        "total_scheduled_irrigation_mm": total_scheduled_irrigation_mm,
        "total_simulated_irrigation_mm": total_irrigation_mm,
        "total_etc_mm": total_etc_mm,
        "total_steps": total_steps,
    }
    return results


def _record_step(history, info, action, event_idx, is_event):
    history["time_day"].append(info["time_day"])
    history["theta"].append(info["theta"])
    history["ec_soil"].append(info["ec_soil"])
    history["target_ec"].append(info["target_ec"])
    history["ec_set"].append(info.get("ec_set", 0.0))
    history["ph_set"].append(info.get("ph_set", 7.0))
    history["q_f"].append(info["q_f"])
    history["q_a"].append(info["q_a"])
    history["irrigation_mm_h"].append(info["irrigation_mm_h"])
    history["etc_mm_h"].append(info["etc_mm_h"])
    history["ec_drip"].append(info["ec_drip"])
    history["stage"].append(event_idx)
    history["event_marker"].append(1.0 if is_event else 0.0)
    history["water_multiplier"].append(float(info.get("water_multiplier", 0.0)))
    history["ec_residual"].append(float(info.get("ec_residual", 0.0)))
    history["budget_limited"].append(bool(info.get("budget_limited", False)))
    history["batch_target_volume_l"].append(float(info.get("batch_target_volume_l", 0.0)))
