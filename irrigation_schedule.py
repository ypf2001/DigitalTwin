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
    """返回论文的 8 次灌溉事件列表。"""
    return [IrrigationEvent(d, s, t1, t2) for d, s, t1, t2 in _SCHEDULE_DATA]


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
        固定策略动作 [EC_set, pH_set]（model=None 时使用）
    verbose : bool
        是否打印进度

    返回
    ----------
    results : dict
        包含 time_day, theta, ec_soil, target_ec, ec_set, ph_set, q_f, q_a,
        total_irrigation_mm, etc_cumulative_mm 等
    """
    if fixed_action is None:
        fixed_action = np.array([1.5, 6.0], dtype=np.float32)

    schedule = get_irrigation_schedule()
    dt_hours = dt_min / 60.0

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
    }

    obs = env.reset()
    env.soil.theta = initial_theta
    env.soil.ec_soil = initial_ec
    # 更新历史缓冲以匹配新的初始 theta
    env._theta_history.clear()
    env._ec_soil_history.clear()
    for _ in range(env.history_len):
        env._theta_history.append(initial_theta)
        env._ec_soil_history.append(initial_ec)
    total_irrigation_mm = 0.0
    total_scheduled_irrigation_mm = 0.0
    total_etc_mm = 0.0
    total_steps = 0

    # 按事件推进
    prev_day = 0.0
    for event_idx, event in enumerate(schedule):
        # 切换到当前事件的生育阶段
        env.set_growth_stage(event.growth_stage)

        # 非灌溉期：从 prev_day 到 event.day（只发生 ET + 降雨）
        dry_hours = (event.day - prev_day) * 24.0
        dry_steps = int(dry_hours / dt_hours)
        rain_mm_h = rain_mm_day / 24.0  # 日均降雨 → 时均
        for _ in range(dry_steps):
            obs, _, done, info = env.dry_step(rain_mm_h=rain_mm_h)
            total_steps += 1
            total_etc_mm += info["etc_mm_h"] * dt_hours

            _record_step(history, info, np.array([0.0, 0.0]), event_idx, is_event=False)

        # 灌溉期：按 event 水量计算持续时长
        amount = event.t1_amount_m3ha if strategy == "T1" else event.t2_amount_m3ha
        total_scheduled_irrigation_mm += amount / 10.0
        event_hours = event_duration_hours(amount, area_ha)
        event_steps = max(1, int(event_hours / dt_hours))

        event_irr_total = 0.0
        for _ in range(event_steps):
            if model is not None:
                action, _ = model.predict(normalize_obs(obs), deterministic=True)
            else:
                action = fixed_action.copy()

            obs, reward, done, info = env.step(action)
            total_steps += 1
            total_irrigation_mm += info["irrigation_mm_h"] * dt_hours
            event_irr_total += info["irrigation_mm_h"] * dt_hours
            total_etc_mm += info["etc_mm_h"] * dt_hours

            _record_step(history, info, action, event_idx, is_event=True)

        if verbose:
            target_ec = env.crop.get_target_ec(event.growth_stage)
            logger.info(f"  事件 {event_idx+1}/8  day {event.day:3.0f}  "
                        f"stage={event.growth_stage.value:12s}  "
                        f"{strategy}={amount:3.0f} m^3/ha  "
                        f"duration={event_hours:.1f}h  "
                        f"irr_applied={event_irr_total:.1f}mm  "
                        f"theta={info['theta']:.3f}  EC={info['ec_soil']:.3f}")

        prev_day = event.day

    # 最后一次灌溉后继续推进到完整生育期，避免统计只到 day 65。
    current_day = env._time_min / (24.0 * 60.0)
    tail_hours = max(0.0, (season_days - current_day) * 24.0)
    tail_steps = int(tail_hours / dt_hours)
    rain_mm_h = rain_mm_day / 24.0
    if schedule:
        env.set_growth_stage(schedule[-1].growth_stage)
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
