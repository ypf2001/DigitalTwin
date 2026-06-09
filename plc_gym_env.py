"""
PLC 在环 Gymnasium 环境 — PLCGymEnv
=====================================

B 方案 HIL/PLCSIM 闭环：

    Agent action [EC_set, pH_set]
        ↓
    Python 写入 PLC/PLCSIM：EC_Set_SP、pH_Set_SP、EC_Actual、pH_Actual
        ↓
    PLC/PLCSIM 内部 EC-PID、pH-PID 计算 q_f_cmd、q_a_cmd
        ↓
    Python 回读 q_f_cmd、q_a_cmd，并驱动数字孪生模型推进田间状态

说明
----
DigitalTwinGymEnv 纯仿真模式仍使用内部 SetpointToFlowController；
PLCGymEnv 则用 PLC/PLCSIM 作为执行层，更接近真实系统。
"""

import logging
import time

import gymnasium as gym
import numpy as np

from config_loader import load_config
from digital_twin_gym_env import DigitalTwinGymEnv, STAGE_MAP
from plc_client import PLCClient

logger = logging.getLogger(__name__)


class PLCGymEnv(gym.Env):
    """PLC/PLCSIM 在环 Gymnasium 环境。"""

    metadata = {"render_modes": []}

    def __init__(self,
                 plc_client: PLCClient = None,
                 growth_stage: str = "MID",
                 area_ha: float = None,
                 dt_min: float = None,
                 ep_len_days: float = None,
                 et0_mm_day: float = None,
                 obs_noise_std: float = None,
                 reward_scale: float = 1.0,
                 seed: int = None,
                 plc_enabled: bool = True):
        super().__init__()

        self.plc = plc_client
        self.plc_enabled = plc_enabled and (self.plc is not None)
        plc_cfg = load_config().plc()
        feedback_filter_cfg = plc_cfg.get("feedback_filter", {})
        self.feedback_filter_enabled = bool(feedback_filter_cfg.get("enabled", True))
        self.feedback_filter_alpha = float(feedback_filter_cfg.get("alpha", 0.8))
        self.feedback_filter_alpha = float(np.clip(self.feedback_filter_alpha, 0.0, 0.99))
        self._ec_actual_filtered = None
        self._ph_actual_filtered = None
        self._soil_ph_est = 7.0

        self._sim_env = DigitalTwinGymEnv(
            growth_stage=growth_stage,
            area_ha=area_ha,
            dt_min=dt_min,
            ep_len_days=ep_len_days,
            et0_mm_day=et0_mm_day,
            obs_noise_std=obs_noise_std,
            reward_scale=reward_scale,
            seed=seed,
        )

        self.observation_space = self._sim_env.observation_space
        self.action_space = self._sim_env.action_space

        self._last_plc_state = {
            "Remote_Comms_OK": False,
            "Watchdog_Timer": 0,
            "q_f_cmd": 0.0,
            "q_a_cmd": 0.0,
            "Valve_F_Actual": 0.0,
            "Valve_A_Actual": 0.0,
            "AQ_Valve_F_Raw": 0,
            "AQ_Valve_A_Raw": 0,
            "System_Alarm_Light": False,
        }

    def reset(self, seed=None, options=None):
        """重置仿真环境，并向 PLC 写入安全默认目标。"""
        obs, _ = self._sim_env.reset(seed=seed, options=options)
        base = self._sim_env.unwrapped_env
        self._soil_ph_est = 7.0
        self._reset_feedback_filter(ec_actual=0.0, ph_actual=7.0)

        if self.plc_enabled:
            self._safe_write_setpoints(
                ec_set=0.8,
                ph_set=7.0,
                ec_actual=0.0,
                ph_actual=7.0,
                sac_enable=False,
            )
            time.sleep(self.plc.cycle_s)
            plc_state = self.plc.read_state()
            if plc_state is not None:
                self._last_plc_state = plc_state

        return obs, self._build_info({
            "theta": base.soil.theta,
            "ec_soil": base.soil.ec_soil,
            "ec_drip": 0.0,
            "ph_drip": 7.0,
        })

    def step(self, action):
        """执行一个 PLC 在环控制步。

        action 为 SAC 输出的 [EC_set, pH_set]。如果启用 PLC，则 PLC 执行层计算 q_f/q_a；
        如果未启用 PLC，则退化为 DigitalTwinGymEnv 的纯仿真执行层。
        """
        action = np.asarray(action, dtype=np.float32).flatten()
        action_clipped = np.clip(action, self.action_space.low, self.action_space.high)
        ec_set = float(action_clipped[0])
        ph_set = float(action_clipped[1])

        if not self.plc_enabled:
            obs, reward, terminated, truncated, sim_info = self._sim_env.step(action_clipped)
            return obs, reward, terminated, truncated, self._build_info(sim_info)

        base = self._sim_env.unwrapped_env

        # 1. 写入目标值和当前虚拟传感器值，供 PLC-PID 使用
        # EC target tracking is evaluated on root-zone soil EC, so feed the PLC
        # the same controlled variable instead of the pipe outlet EC.
        ec_actual = float(base.soil.ec_soil)
        ph_actual = float(self._soil_ph_est)
        ec_actual, ph_actual = self._filter_feedback(ec_actual, ph_actual)
        self._safe_write_setpoints(ec_set, ph_set, ec_actual, ph_actual, sac_enable=True)

        # 2. 等待 PLC/PLCSIM 扫描周期和 PID 执行
        time.sleep(self.plc.cycle_s)

        # 3. 回读 PLC 执行层输出
        plc_state = self.plc.read_state()
        if plc_state is not None:
            self._last_plc_state = plc_state
            if not plc_state.get("Remote_Comms_OK", True):
                logger.warning(
                    f"[HIL] ⚠ PLC 通讯异常! Watchdog={plc_state.get('Watchdog_Timer')}, "
                    f"Alarm={plc_state.get('System_Alarm_Light')}"
                )
        else:
            logger.error("[HIL] PLC 读取失败，使用上一次 PLC 输出")
            plc_state = self._last_plc_state

        q_f = float(plc_state.get("q_f_cmd", 0.0))
        q_a = float(plc_state.get("q_a_cmd", 0.0))

        # 4. 用 PLC 输出 q_f/q_a 驱动底层数字孪生模型。
        obs, reward, terminated, truncated, sim_info = self._step_with_plc_flows(
            ec_set=ec_set,
            ph_set=ph_set,
            q_f=q_f,
            q_a=q_a,
        )
        info = self._build_info(sim_info)
        return obs, reward, terminated, truncated, info

    def _step_with_plc_flows(self, ec_set: float, ph_set: float, q_f: float, q_a: float):
        """绕过内部 SetpointToFlowController，直接使用 PLC 输出 q_f/q_a 推进模型。"""
        base = self._sim_env.unwrapped_env

        q_w = base.q_w
        if base._is_nighttime(base._time_min):
            q_f = 0.0
            q_a = 0.0
            q_w = 0.0

        total_flow_with_water = q_f + q_a + q_w
        irrigation_mm_h = total_flow_with_water * 60.0 / (base.area_ha * 10000.0)
        actuator_flow_Lmin = q_f + q_a

        ec_tank, ph_tank = base.tank.step(q_f, q_a, q_w=q_w)
        ec_drip, ph_drip = base.pipe.step(ec_tank, ph_tank)

        et_mm_h = base._get_actual_et(base._time_min)
        dt_hours = base.dt_min / 60.0
        theta, ec_soil = base.soil.step(irrigation_mm_h, ec_drip, et_mm_h, dt_hours)
        self._soil_ph_est = self._estimate_soil_ph(
            self._soil_ph_est,
            ph_drip,
            irrigation_mm_h,
            dt_hours,
        )

        base._theta_history.append(theta)
        base._ec_soil_history.append(ec_soil)
        base._ec_in_history.append(ec_drip)
        base._ph_in_history.append(ph_drip)

        control_active = not base._is_nighttime(base._time_min)
        reward, ec_reward_component, ph_reward_component, setpoint_reward_component, burn = base._compute_reward(
            ec_drip,
            ec_soil,
            ph_drip,
            actuator_flow_Lmin,
            ec_set,
            ph_set,
            control_active=control_active,
        )
        if burn:
            base._done = True

        base._time_min += base.dt_min
        base._total_steps += 1
        if base._total_steps >= base._max_steps:
            base._done = True

        obs = base._get_obs()
        obs = self._sim_env._normalize_obs(obs)
        reward = reward * self._sim_env.reward_scale

        sim_info = {
            "time_min": base._time_min,
            "time_day": base._time_min / (24 * 60),
            "theta": theta,
            "ec_soil": ec_soil,
            "ec_drip": ec_drip,
            "ph_drip": ph_drip,
            "soil_ph_est": self._soil_ph_est,
            "ec_set": ec_set,
            "ph_set": ph_set,
            "etc_mm_h": et_mm_h,
            "target_ec": base.crop.get_target_ec(base.current_stage),
            "irrigation_mm_h": irrigation_mm_h,
            "q_f": q_f,
            "q_a": q_a,
            "total_flow_Lmin": actuator_flow_Lmin,
            "is_night": base._is_nighttime(base._time_min),
            "ec_reward": ec_reward_component,
            "ph_reward": ph_reward_component,
            "setpoint_reward": setpoint_reward_component,
            "burn": burn,
        }
        return obs, reward, base._done, False, sim_info

    @staticmethod
    def _estimate_soil_ph(prev_ph: float, ph_drip: float, irrigation_mm_h: float, dt_hours: float) -> float:
        """Buffered root-zone pH estimate used as the PLC feedback variable."""
        root_depth_mm = 300.0
        exchange = np.clip((irrigation_mm_h * dt_hours) / root_depth_mm, 0.0, 0.25)
        buffered_exchange = 1.20 * exchange
        neutral_relax = 0.0005 * dt_hours
        ph = prev_ph + buffered_exchange * (ph_drip - prev_ph) + neutral_relax * (7.0 - prev_ph)
        return float(np.clip(ph, 4.5, 8.5))

    def render(self, mode="human"):
        pass

    def close(self):
        if self.plc_enabled:
            self._safe_write_setpoints(0.8, 7.0, 0.0, 7.0, sac_enable=False)
            self.plc.disconnect()
        self._sim_env.close()

    @property
    def current_stage(self):
        return self._sim_env.current_stage

    @current_stage.setter
    def current_stage(self, stage):
        if isinstance(stage, str):
            stage = STAGE_MAP[stage.upper()]
        self._sim_env.current_stage = stage
        self._sim_env.unwrapped_env.set_growth_stage(stage)

    @property
    def unwrapped_env(self):
        return self._sim_env.unwrapped_env

    def _safe_write_setpoints(self,
                              ec_set: float,
                              ph_set: float,
                              ec_actual: float,
                              ph_actual: float,
                              sac_enable: bool = True) -> bool:
        if not self.plc_enabled:
            return True
        try:
            return self.plc.write_setpoints(ec_set, ph_set, ec_actual, ph_actual, sac_enable=sac_enable)
        except Exception as e:
            logger.error(f"[HIL] PLC 目标值写入异常: {e}")
            return False

    def _reset_feedback_filter(self, ec_actual: float, ph_actual: float):
        """Initialize the EC/pH feedback filter at the start of an HIL episode."""
        self._ec_actual_filtered = float(ec_actual)
        self._ph_actual_filtered = float(ph_actual)

    def _filter_feedback(self, ec_actual: float, ph_actual: float) -> tuple[float, float]:
        """Low-pass filter feedback before writing EC_Actual/pH_Actual to PLC."""
        if not self.feedback_filter_enabled:
            self._ec_actual_filtered = float(ec_actual)
            self._ph_actual_filtered = float(ph_actual)
            return float(ec_actual), float(ph_actual)

        if self._ec_actual_filtered is None or self._ph_actual_filtered is None:
            self._reset_feedback_filter(ec_actual, ph_actual)
            return float(ec_actual), float(ph_actual)

        alpha = self.feedback_filter_alpha
        self._ec_actual_filtered = alpha * self._ec_actual_filtered + (1.0 - alpha) * float(ec_actual)
        self._ph_actual_filtered = alpha * self._ph_actual_filtered + (1.0 - alpha) * float(ph_actual)
        return self._ec_actual_filtered, self._ph_actual_filtered

    def _build_info(self, sim_info: dict) -> dict:
        info = dict(sim_info)
        info["plc"] = dict(self._last_plc_state)
        info["plc_enabled"] = self.plc_enabled
        return info

    def get_plc_state(self) -> dict:
        return dict(self._last_plc_state)
