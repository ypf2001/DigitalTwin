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
        action_cfg = load_config().action()
        feedback_filter_cfg = plc_cfg.get("feedback_filter", {})
        self.feedback_filter_enabled = bool(feedback_filter_cfg.get("enabled", True))
        self.feedback_filter_alpha = float(feedback_filter_cfg.get("alpha", 0.8))
        self.feedback_filter_alpha = float(np.clip(self.feedback_filter_alpha, 0.0, 0.99))
        self.plc_action_low = np.array(
            [
                float(action_cfg.get("plc_ec_set_min", 0.5)),
                float(action_cfg.get("plc_ph_set_min", 5.5)),
            ],
            dtype=np.float32,
        )
        self.plc_action_high = np.array(
            [
                float(action_cfg.get("ec_set_max", 2.5)),
                float(action_cfg.get("ph_set_max", 6.8)),
            ],
            dtype=np.float32,
        )
        self._ec_actual_filtered = None
        self._ph_actual_filtered = None
        self._soil_ph_est = 7.0
        self._root_ec_est = 0.0
        self._npk_actual = {"N": 0.0, "P": 0.0, "K": 0.0}

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
            "q_n_cmd": 0.0,
            "q_p_cmd": 0.0,
            "q_k_cmd": 0.0,
            "N_Target": 0.0,
            "P_Target": 0.0,
            "K_Target": 0.0,
            "N_Actual": 0.0,
            "P_Actual": 0.0,
            "K_Actual": 0.0,
            "System_Alarm_Light": False,
        }

    def reset(self, seed=None, options=None):
        """重置仿真环境，并向 PLC 写入安全默认目标。"""
        obs, _ = self._sim_env.reset(seed=seed, options=options)
        base = self._sim_env.unwrapped_env
        base.soil.ec_soil = 0.78
        # reset() populated the observation history before the PLC/HIL-specific
        # EC override. Rebuild that history so the returned first observation
        # and the PLC feedback both start from the same physical state.
        base._ec_soil_history.clear()
        for _ in range(base.history_len):
            base._ec_soil_history.append(float(base.soil.ec_soil))
        obs = self._sim_env._normalize_obs(base._get_obs())
        self._root_ec_est = float(base.soil.ec_soil)
        self._soil_ph_est = 6.25
        self._npk_actual = self._npk_targets_for_stage("INI").copy()
        self._reset_feedback_filter(ec_actual=self._root_ec_est, ph_actual=self._soil_ph_est)

        if self.plc_enabled:
            self._sync_plc_inputs(
                ec_set=0.8,
                ph_set=7.0,
                ec_actual=self._root_ec_est,
                ph_actual=self._soil_ph_est,
                automatic_enable=False,
            )
            time.sleep(self.plc.cycle_s)
            plc_state = self.plc.read_state()
            if plc_state is not None:
                self._last_plc_state = plc_state

        return obs, self._build_info({
            "theta": base.soil.theta,
            "ec_soil": self._root_ec_est,
            "raw_ec_soil": base.soil.ec_soil,
            "ec_drip": 0.0,
            "ph_drip": self._soil_ph_est,
        })

    def step(self, action):
        """执行一个 PLC 在环控制步。

        action 为 SAC 输出的 [EC_set, pH_set]。如果启用 PLC，则 PLC 执行层计算 q_f/q_a；
        如果未启用 PLC，则退化为 DigitalTwinGymEnv 的纯仿真执行层。
        """
        action = np.asarray(action, dtype=np.float32).flatten()
        clip_low = self.plc_action_low if self.plc_enabled else self.action_space.low
        clip_high = self.plc_action_high if self.plc_enabled else self.action_space.high
        action_clipped = np.clip(action, clip_low, clip_high)
        ec_set = float(action_clipped[0])
        ph_set = float(action_clipped[1])

        if not self.plc_enabled:
            obs, reward, terminated, truncated, sim_info = self._sim_env.step(action_clipped)
            return obs, reward, terminated, truncated, self._build_info(sim_info)

        base = self._sim_env.unwrapped_env

        # 1. 写入目标值和当前虚拟传感器值，供 PLC-PID 使用
        # EC target tracking is evaluated on root-zone soil EC, so feed the PLC
        # the same controlled variable instead of the pipe outlet EC.
        ec_actual = float(self._root_ec_est)
        ph_actual = float(self._soil_ph_est)
        ec_actual, ph_actual = self._filter_feedback(ec_actual, ph_actual)
        self._sync_plc_inputs(ec_set, ph_set, ec_actual, ph_actual)
        npk_targets_for_plc = self._npk_targets_for_stage(base.current_stage)
        self.plc.write_fertilizer_feedback(
            npk_targets_for_plc["N"],
            npk_targets_for_plc["P"],
            npk_targets_for_plc["K"],
            self._npk_actual["N"],
            self._npk_actual["P"],
            self._npk_actual["K"],
            feedback_valid=True,
        )

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
        q_n = float(plc_state.get("q_n_cmd", q_f / 3.0))
        q_p = float(plc_state.get("q_p_cmd", q_f / 3.0))
        q_k = float(plc_state.get("q_k_cmd", q_f / 3.0))

        # 4. 用 PLC 输出 q_f/q_a 驱动底层数字孪生模型。
        obs, reward, terminated, truncated, sim_info = self._step_with_plc_flows(
            ec_set=ec_set,
            ph_set=ph_set,
            q_f=q_f,
            q_a=q_a,
            q_n=q_n,
            q_p=q_p,
            q_k=q_k,
        )
        info = self._build_info(sim_info)
        return obs, reward, terminated, truncated, info

    def _step_with_plc_flows(self, ec_set: float, ph_set: float, q_f: float, q_a: float,
                             q_n: float = 0.0, q_p: float = 0.0, q_k: float = 0.0):
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
        theta, raw_ec_soil = base.soil.step(irrigation_mm_h, ec_drip, et_mm_h, dt_hours)
        ec_soil = self._estimate_root_ec(
            prev_ec=self._root_ec_est,
            raw_ec=raw_ec_soil,
            ec_set=ec_set,
            irrigation_mm_h=irrigation_mm_h,
            dt_hours=dt_hours,
        )
        self._root_ec_est = ec_soil
        self._soil_ph_est = self._estimate_soil_ph(
            self._soil_ph_est,
            ph_drip,
            irrigation_mm_h,
            dt_hours,
        )
        npk_targets = self._npk_targets_for_stage(base.current_stage)
        self._npk_actual = self._estimate_npk(
            current=self._npk_actual,
            targets=npk_targets,
            q_n=q_n,
            q_p=q_p,
            q_k=q_k,
            irrigation_mm_h=irrigation_mm_h,
            dt_hours=dt_hours,
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
            "raw_ec_soil": raw_ec_soil,
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
            "q_n": q_n,
            "q_p": q_p,
            "q_k": q_k,
            "n_actual": self._npk_actual["N"],
            "p_actual": self._npk_actual["P"],
            "k_actual": self._npk_actual["K"],
            "n_target": npk_targets["N"],
            "p_target": npk_targets["P"],
            "k_target": npk_targets["K"],
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

    @staticmethod
    def _estimate_root_ec(prev_ec: float,
                          raw_ec: float,
                          ec_set: float,
                          irrigation_mm_h: float,
                          dt_hours: float) -> float:
        """Convert compressed soil EC pulses into a root-zone sensor estimate."""
        prev = float(np.clip(prev_ec, 0.0, 3.0))
        raw = float(np.clip(raw_ec, 0.0, 3.0))

        if irrigation_mm_h <= 1e-6 and raw < prev * 0.65:
            candidate = prev
        else:
            candidate = raw

        if candidate < prev:
            # Compressed full-season runs represent several field hours in one
            # PLC step. When the recipe drops EC sharply, allow a stronger
            # flushing response so the root-zone estimate does not carry the
            # previous stage's high EC for unrealistically long.
            if irrigation_mm_h > 1e-6 and ec_set < prev - 0.18:
                max_down_delta = 0.070 + 0.020 * min(dt_hours, 12.0)
            else:
                max_down_delta = 0.030 + 0.007 * min(dt_hours, 12.0)
            candidate = max(candidate, prev - max_down_delta)
        else:
            max_up_delta = 0.035 + 0.010 * min(dt_hours, 12.0)
            candidate = min(candidate, prev + max_up_delta)

        pull = min(0.20, max(0.0, irrigation_mm_h) * 0.030)
        estimated_raw = candidate + pull * (float(ec_set) - candidate)

        set_gap = abs(float(ec_set) - prev)
        if irrigation_mm_h <= 1e-6:
            sensor_alpha = 0.88
        elif set_gap > 0.25:
            sensor_alpha = 0.45
        elif set_gap > 0.12:
            sensor_alpha = 0.60
        else:
            # In steady stages, root-zone EC sensors should show the buffered
            # root volume rather than every compressed soil-model pulse.
            sensor_alpha = 0.76

        estimated = sensor_alpha * prev + (1.0 - sensor_alpha) * estimated_raw
        return float(np.clip(estimated, 0.0, 3.0))

    @staticmethod
    def _npk_targets_for_stage(stage) -> dict[str, float]:
        name = getattr(stage, "name", str(stage)).upper()
        if "EMERGENCE" in name or name == "INI":
            return {"N": 0.75, "P": 0.55, "K": 0.65}
        if "TUBER" in name or name == "DEV":
            return {"N": 0.95, "P": 0.75, "K": 0.90}
        if "BULKING" in name or name == "MID":
            return {"N": 1.10, "P": 0.85, "K": 1.25}
        return {"N": 0.85, "P": 0.65, "K": 1.05}

    @staticmethod
    def _estimate_npk(current: dict[str, float],
                      targets: dict[str, float],
                      q_n: float,
                      q_p: float,
                      q_k: float,
                      irrigation_mm_h: float,
                      dt_hours: float) -> dict[str, float]:
        """Lightweight root-zone N/P/K estimate for PLC-in-the-loop tuning."""
        flows = {"N": q_n, "P": q_p, "K": q_k}
        updated = {}
        wetting = float(np.clip(irrigation_mm_h / 6.0, 0.0, 1.5))
        for key in ("N", "P", "K"):
            value = float(current.get(key, targets[key]))
            uptake = 0.0045 * dt_hours * (0.6 + 0.4 * targets[key])
            leaching = 0.0060 * dt_hours * wetting * max(value - 0.25, 0.0)
            dosing = 0.0042 * flows[key] * dt_hours
            # The compressed HIL model advances several physical hours per PLC
            # scan. Use a stronger root-zone buffering term so the normalized
            # stage recipe represents a maintainable concentration instead of
            # letting uptake/leaching create a permanent common-mode deficit
            # that cannot be corrected inside the fixed EC fertilizer budget.
            buffer_pull = 0.070 * dt_hours * (targets[key] - value)
            raw_next = value + dosing + buffer_pull - uptake - leaching
            max_delta = 0.030 + 0.006 * min(dt_hours, 12.0)
            raw_next = float(np.clip(raw_next, value - max_delta, value + max_delta))
            updated[key] = float(np.clip(raw_next, 0.0, 2.0))
        return updated

    def render(self, mode="human"):
        pass

    def close(self):
        if self.plc_enabled:
            self._sync_plc_inputs(0.8, 7.0, 0.0, 7.0, automatic_enable=False)
            # Restore real-device defaults even after an interrupted compressed test.
            self.plc.write_fertilizer_feedback(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, feedback_valid=False)
            self.plc.write_compressed_hil_mode(False)
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

    def _safe_write_feedback(self,
                             ec_actual: float,
                             ph_actual: float,
                             sac_enable: bool) -> bool:
        if not self.plc_enabled:
            return True
        try:
            return self.plc.write_feedback(ec_actual, ph_actual, sac_enable=sac_enable)
        except Exception as e:
            logger.error(f"[HIL] PLC feedback write failed: {e}")
            return False

    def _sync_plc_inputs(self,
                         ec_set: float,
                         ph_set: float,
                         ec_actual: float,
                         ph_actual: float,
                         automatic_enable: bool = True) -> bool:
        """Synchronize one cycle without fighting PLC local manual mode."""
        mode_state = self.plc.read_control_mode()
        if mode_state is not None:
            self._last_plc_state.update(mode_state)

        if bool(self._last_plc_state.get("Manual_Active", False)):
            logger.info("[HIL] local manual active: automatic targets paused")
            return self._safe_write_feedback(
                ec_actual=ec_actual,
                ph_actual=ph_actual,
                sac_enable=False,
            )

        return self._safe_write_setpoints(
            ec_set=ec_set,
            ph_set=ph_set,
            ec_actual=ec_actual,
            ph_actual=ph_actual,
            sac_enable=automatic_enable,
        )

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
        # Acid dosing is the remaining noisy actuator in compressed
        # full-season runs. Filter pH a little more strongly than EC so the PLC
        # does not chase small synthetic pH ripples with alternating acid flow.
        ph_alpha = float(np.clip(max(alpha, 0.72), 0.0, 0.90))
        self._ec_actual_filtered = alpha * self._ec_actual_filtered + (1.0 - alpha) * float(ec_actual)
        self._ph_actual_filtered = ph_alpha * self._ph_actual_filtered + (1.0 - ph_alpha) * float(ph_actual)
        return self._ec_actual_filtered, self._ph_actual_filtered

    def _build_info(self, sim_info: dict) -> dict:
        info = dict(sim_info)
        info["plc"] = dict(self._last_plc_state)
        info["plc_enabled"] = self.plc_enabled
        return info

    def get_plc_state(self) -> dict:
        return dict(self._last_plc_state)
