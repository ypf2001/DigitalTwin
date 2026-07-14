"""
数字孪生集成环境 — DigitalTwinEnv
==================================

将 MixingTank、PipeDynamics、SoilTransport、CropModel 整合为一个仿 Gym 接口的
数字孪生环境，用于马铃薯水肥一体化闭环控制仿真。

B 方案控制结构
--------------
SAC 不再直接输出施肥泵/酸泵流量，而是输出上层目标值：

    action = [EC_set, pH_set]

环境内部通过 SetpointToFlowController 模拟 PLC-PID 执行层，将 EC_set/pH_set 转换为
母液流量 q_f 和酸液流量 q_a，再驱动混合罐、管道和根区水盐模型。

状态流:
    动作 [EC_set, pH_set]
        → SetpointToFlowController → [q_f, q_a]
        → MixingTank → [ec_tank, ph_tank]
        → PipeDynamics → [ec_drip, ph_drip]
        → SoilTransport → [theta, ec_soil]
        → CropModel → [ETc, target_ec]
"""

from collections import deque

import numpy as np

from mixing_tank import MixingTank
from pipe_dynamics import PipeDynamics
from soil_transport import SoilTransport
from soil_profile_v2 import LayeredSoilProfile, sample_soil_config
from crop_model import CropModel, GrowthStage
from config_loader import load_config
from setpoint_controller import SetpointToFlowController


class DigitalTwinEnv:
    """数字孪生环境，模仿 Gym 的 step/reset 接口。

    参数
    ----------
    growth_stage : GrowthStage
        马铃薯当前生育阶段。
    area_ha : float
        灌溉面积 (ha)，默认从配置读取。
    dt_min : float
        仿真步长 (min)。
    ep_len_days : float
        每个 episode 时长 (d)。
    et0_mm_day : float
        参考蒸散发量基准值 (mm/d)。
    obs_noise_std : float
        观测噪声标准差。
    q_w : float
        清水基础流量 (L/min)。
    seed : int, optional
        随机种子。

    动作空间
    --------
    action = [EC_set, pH_set]
        EC_set : 滴灌/混肥出口目标 EC (dS/m)
        pH_set : 滴灌/混肥出口目标 pH

    观测空间 (维度 = 23)
    -------------------
    obs = [theta历史5维, EC_soil历史5维, ec_drip历史5维, ph_drip历史5维,
           ETc归一化, target_ec归一化, stage_code]
    """

    def __init__(self,
                 growth_stage: GrowthStage = GrowthStage.EMERGENCE,
                 area_ha: float = None,
                 dt_min: float = None,
                 ep_len_days: float = None,
                 et0_mm_day: float = None,
                 obs_noise_std: float = None,
                 q_w: float = None,
                 seed: int = None,
                 soil_model: str = None,
                 domain_randomization: bool = False):
        cfg = load_config()
        env_cfg = cfg.env()
        obs_cfg = cfg.obs()

        self.area_ha = area_ha if area_ha is not None else env_cfg["area_ha"]
        self.dt_min = dt_min if dt_min is not None else env_cfg["dt_min"]
        self.ep_len_days = ep_len_days if ep_len_days is not None else env_cfg["ep_len_days"]
        self.et0_base = et0_mm_day if et0_mm_day is not None else env_cfg["et0_mm_day"]
        self.obs_noise_std = obs_noise_std if obs_noise_std is not None else env_cfg["obs_noise_std"]
        self.q_w = q_w if q_w is not None else env_cfg["q_w"]

        seed = seed if seed is not None else env_cfg.get("seed")
        self._rng = np.random.RandomState(seed)

        # ---- 子模块 ----
        self.tank = MixingTank()
        self.pipe = PipeDynamics(dt=self.dt_min)
        soil_v2_cfg = cfg.soil_v2()
        self._soil_v2_cfg = soil_v2_cfg
        self.domain_randomization = bool(domain_randomization)
        self.soil_model = soil_model or soil_v2_cfg.get("default_model", "lumped_v1")
        supported = soil_v2_cfg.get("supported_models", ["lumped_v1", "layered_v2"])
        if self.soil_model not in supported:
            raise ValueError(f"未知土壤模型: {self.soil_model}，可选值: {supported}")
        if self.soil_model == "layered_v2":
            self.soil = LayeredSoilProfile(config=soil_v2_cfg, area_ha=self.area_ha)
        else:
            self.soil = SoilTransport()
        self.crop = CropModel(growth_stage)
        self.current_stage = growth_stage
        root_depth = self.crop.get_root_depth(growth_stage)
        if self.soil_model == "layered_v2":
            self.soil.set_growth_stage(growth_stage, root_depth)
        else:
            self.soil.root_depth = root_depth
        self.executor = SetpointToFlowController()

        # ---- 观测历史缓冲 ----
        self.history_len = obs_cfg["history_len"]
        self._theta_history = deque(maxlen=self.history_len)
        self._ec_soil_history = deque(maxlen=self.history_len)
        self._ec_in_history = deque(maxlen=self.history_len)
        self._ph_in_history = deque(maxlen=self.history_len)

        # ---- 时钟 ----
        self._time_min: float = 0.0
        self._total_steps: int = 0
        self._max_steps: int = int(self.ep_len_days * 24 * 60 / self.dt_min)
        self._done: bool = False

        # ---- 归一化常数 ----
        self._ETC_NORM = obs_cfg["etc_norm"]
        self._TARGET_EC_NORM = obs_cfg["target_ec_norm"]

        # ---- 日夜间阈值 ----
        dn = cfg.day_night()
        self._night_start = dn["night_start"]
        self._night_end = dn["night_end"]
        self._day_start = dn["day_start"]
        self._day_end = dn["day_end"]
        self._daytime_hours = dn["daytime_hours"]
        self._et_peak_factor = dn["et_peak_factor"]
        self._et_fluctuation = dn["et_fluctuation"]

    def _is_nighttime(self, time_min: float) -> bool:
        hour = (time_min / 60.0) % 24.0
        return hour >= self._night_start or hour < self._night_end

    def _get_actual_et(self, time_min: float) -> float:
        hour = (time_min / 60.0) % 24.0

        if self._day_start <= hour < self._day_end:
            day_frac = (hour - self._day_start) / self._daytime_hours
            solar_factor = np.sin(day_frac * np.pi)
            etc_base_mm_h = self.crop.get_etc(self.current_stage, self.et0_base) / 24.0
            ks = self.crop.get_ks(self.soil.theta, self.soil.theta_fc, self.soil.theta_wp)
            et_actual = etc_base_mm_h * solar_factor * self._et_peak_factor * ks
            et_actual *= (1.0 + self._rng.uniform(-self._et_fluctuation, self._et_fluctuation))
        else:
            et_actual = 0.0

        return max(0.0, et_actual)

    def _setpoint_to_flow(self, action):
        """将动作 [EC_set, pH_set] 转换为执行流量与灌溉强度。

        夜间停肥停酸，但保留清水灌溉，用于维持土壤湿度。
        """
        ec_set = float(action[0])
        ph_set = float(action[1])
        result = self.executor.to_flow(ec_set, ph_set, q_w=self.q_w)

        q_f = result.q_f
        q_a = result.q_a
        if self._is_nighttime(self._time_min):
            q_f = 0.0
            q_a = 0.0

        total_flow_with_water = q_f + q_a + self.q_w
        irrigation_mm_h = total_flow_with_water * 60.0 / (self.area_ha * 10000.0)

        return result.ec_set, result.ph_set, q_f, q_a, irrigation_mm_h

    def _get_obs(self):
        """返回 23 维观测向量。"""
        def _pad_deque(dq, default_val=0.0):
            lst = list(dq)
            if len(lst) < self.history_len:
                pad_val = lst[-1] if lst else default_val
                lst = [pad_val] * (self.history_len - len(lst)) + lst
            return lst[-self.history_len:]

        theta_hist = _pad_deque(self._theta_history, 0.16)
        ec_soil_hist = _pad_deque(self._ec_soil_history, 0.1)
        ec_in_hist = _pad_deque(self._ec_in_history, 0.0)
        ph_in_hist = _pad_deque(self._ph_in_history, 7.0)

        etc = self.crop.get_etc(self.current_stage, self.et0_base)
        target_ec = self.crop.get_target_ec(self.current_stage)
        stage_code = list(GrowthStage).index(self.current_stage)

        obs = np.array(
            theta_hist + ec_soil_hist + ec_in_hist + ph_in_hist +
            [etc / self._ETC_NORM, target_ec / self._TARGET_EC_NORM, float(stage_code)],
            dtype=np.float32,
        )

        if self.obs_noise_std > 0:
            noise = self._rng.normal(0, self.obs_noise_std, size=obs.shape).astype(np.float32)
            obs += noise

        return obs

    def _compute_reward(self,
                        ec_drip,
                        ec_soil,
                        ph_drip,
                        actuator_flow_Lmin,
                        ec_set,
                        ph_set,
                        control_active=True):
        """计算奖励函数（多目标）。

        SAC 动作已经变成 EC_set/pH_set，所以奖励同时考虑：
        - 根区土壤 EC 是否接近当前生育期目标；
        - 出口 pH 是否接近 SAC 给定目标；
        - 出口 EC 是否跟踪 SAC 给定目标；
        - 执行流量是否过大；
        - 是否触发盐害/酸害硬约束。
        """
        rw = load_config().reward()
        w1, w2, w3, w4 = rw["w1"], rw["w2"], rw["w3"], rw["w4"]
        target_ec = self.crop.get_target_ec(self.current_stage)

        ec_error = abs(ec_soil - target_ec)
        ec_reward = -w1 * ec_error * ec_error if control_active else 0.0

        ph_error = abs(ph_drip - ph_set)
        ph_reward = -w2 * ph_error * ph_error if control_active else 0.0

        setpoint_track_error = abs(ec_drip - ec_set)
        setpoint_reward = -rw.get("w_setpoint", 1.0) * setpoint_track_error * setpoint_track_error if control_active else 0.0

        flow_penalty = actuator_flow_Lmin * rw["flow_penalty_scale"] * w3
        wue_bonus = max(0.0, 1.0 - actuator_flow_Lmin / rw["wue_norm"]) * w4

        hard_penalty = 0.0
        if ec_soil > rw["ec_burn_threshold"] or ph_drip < rw["ph_burn_threshold"]:
            hard_penalty = rw["hard_penalty"]

        reward = ec_reward + ph_reward + setpoint_reward - flow_penalty + wue_bonus + hard_penalty
        burn = hard_penalty < 0.0
        return reward, ec_reward, ph_reward, setpoint_reward, burn

    def _soil_diagnostics_info(self):
        """统一返回 V1/V2 土壤诊断，便于日志和后续田间标定。"""
        if self.soil_model == "layered_v2":
            return self.soil.diagnostics()
        return {
            "soil_model": "lumped_v1",
            "parameter_status": "legacy",
            "soil_ph": None,
            "n_actual": None,
            "p_actual": None,
            "k_actual": None,
            "theta_profile": [float(self.soil.theta)],
            "ec_profile": [float(self.soil.ec_soil)],
            "ph_profile": [],
            "n_profile": [],
            "p_profile": [],
            "k_profile": [],
            "drainage_mm": None,
            "water_balance_error_mm": None,
            "salt_balance_error": None,
            "nutrient_balance_error_mg_m2": {},
        }

    def step(self, action):
        """执行一个仿真步。

        参数
        ----------
        action : array_like
            [EC_set (dS/m), pH_set]

        返回
        ----------
        obs, reward, done, info
        """
        # ---- 1. 上层目标值 → 执行流量 ----
        ec_set, ph_set, q_f, q_a, irrigation_mm_h = self._setpoint_to_flow(action)
        actuator_flow_Lmin = q_f + q_a

        # ---- 2. MixingTank ----
        ec_tank, ph_tank = self.tank.step(q_f, q_a, q_w=self.q_w)

        # ---- 3. PipeDynamics ----
        ec_drip, ph_drip = self.pipe.step(ec_tank, ph_tank)

        # ---- 4. SoilTransport ----
        et_mm_h = self._get_actual_et(self._time_min)
        dt_hours = self.dt_min / 60.0
        if self.soil_model == "layered_v2":
            theta, ec_soil = self.soil.step(
                irrigation_mm_h,
                ec_drip,
                et_mm_h,
                dt_hours,
                ph_in=ph_drip,
                q_f_l_min=q_f,
                stage=self.current_stage,
            )
        else:
            theta, ec_soil = self.soil.step(
                irrigation_mm_h, ec_drip, et_mm_h, dt_hours
            )

        # ---- 5. 记录历史 ----
        self._theta_history.append(theta)
        self._ec_soil_history.append(ec_soil)
        self._ec_in_history.append(ec_drip)
        self._ph_in_history.append(ph_drip)

        # ---- 6. 奖励 ----
        control_active = not self._is_nighttime(self._time_min)
        reward, ec_reward_component, ph_reward_component, setpoint_reward_component, burn = self._compute_reward(
            ec_drip,
            ec_soil,
            ph_drip,
            actuator_flow_Lmin,
            ec_set,
            ph_set,
            control_active=control_active,
        )
        if burn:
            self._done = True

        # ---- 7. 时钟推进 ----
        self._time_min += self.dt_min
        self._total_steps += 1
        if self._total_steps >= self._max_steps:
            self._done = True

        # ---- 8. 观测 ----
        obs = self._get_obs()

        # ---- 9. 附加信息 ----
        info = {
            "time_min": self._time_min,
            "time_day": self._time_min / (24 * 60),
            "theta": theta,
            "ec_soil": ec_soil,
            "ec_drip": ec_drip,
            "ph_drip": ph_drip,
            "ec_set": ec_set,
            "ph_set": ph_set,
            "etc_mm_h": et_mm_h,
            "target_ec": self.crop.get_target_ec(self.current_stage),
            "irrigation_mm_h": irrigation_mm_h,
            "q_f": q_f,
            "q_a": q_a,
            "total_flow_Lmin": actuator_flow_Lmin,
            "is_night": self._is_nighttime(self._time_min),
            "ec_reward": ec_reward_component,
            "ph_reward": ph_reward_component,
            "setpoint_reward": setpoint_reward_component,
            "burn": burn,
        }
        info.update(self._soil_diagnostics_info())

        return obs, reward, self._done, info

    def reset(self):
        """重置环境至初始状态。"""
        self.tank.reset()
        self.pipe.reset()
        if self.soil_model == "layered_v2" and self.domain_randomization:
            sampled_cfg = sample_soil_config(self._soil_v2_cfg, self._rng)
            self.soil = LayeredSoilProfile(config=sampled_cfg, area_ha=self.area_ha)
            self.soil.set_growth_stage(
                self.current_stage, self.crop.get_root_depth(self.current_stage)
            )
        else:
            self.soil.reset()

        self._theta_history.clear()
        self._ec_soil_history.clear()
        self._ec_in_history.clear()
        self._ph_in_history.clear()

        self._time_min = 0.0
        self._total_steps = 0
        self._done = False

        init_theta, init_ec_soil = float(self.soil.theta), float(self.soil.ec_soil)
        init_ec_in, init_ph_in = 0.0, 7.0
        for _ in range(self.history_len):
            self._theta_history.append(init_theta)
            self._ec_soil_history.append(init_ec_soil)
            self._ec_in_history.append(init_ec_in)
            self._ph_in_history.append(init_ph_in)

        return self._get_obs()

    def set_growth_stage(self, stage: GrowthStage):
        """切换生育阶段，同步更新作物模型、根系深度和目标 EC 参考。"""
        self.current_stage = stage
        self.crop.current_stage = stage
        root_depth = self.crop.get_root_depth(stage)
        if self.soil_model == "layered_v2":
            self.soil.set_growth_stage(stage, root_depth)
        else:
            self.soil.root_depth = root_depth

    def dry_step(self, rain_mm_h: float = 0.0):
        """执行一个纯蒸发/降雨步进（无灌溉、无施肥）。"""
        dt_hours = self.dt_min / 60.0
        et_mm_h = self._get_actual_et(self._time_min)

        if self.soil_model == "layered_v2":
            theta, ec_soil = self.soil.step(
                I=rain_mm_h,
                EC_in=0.0,
                ET=et_mm_h,
                dt_hours=dt_hours,
                ph_in=7.0,
                q_f_l_min=0.0,
                stage=self.current_stage,
            )
        else:
            theta, ec_soil = self.soil.step(
                I=rain_mm_h, EC_in=0.0, ET=et_mm_h, dt_hours=dt_hours
            )

        self._theta_history.append(theta)
        self._ec_soil_history.append(ec_soil)
        self._ec_in_history.append(0.0)
        self._ph_in_history.append(7.0)

        self._time_min += self.dt_min
        self._total_steps += 1
        if self._total_steps >= self._max_steps:
            self._done = True

        obs = self._get_obs()
        info = {
            "time_min": self._time_min,
            "time_day": self._time_min / (24 * 60),
            "theta": theta,
            "ec_soil": ec_soil,
            "ec_drip": 0.0,
            "ph_drip": 7.0,
            "ec_set": 0.0,
            "ph_set": 7.0,
            "etc_mm_h": et_mm_h,
            "target_ec": self.crop.get_target_ec(self.current_stage),
            "irrigation_mm_h": rain_mm_h,
            "q_f": 0.0,
            "q_a": 0.0,
            "total_flow_Lmin": 0.0,
            "is_night": self._is_nighttime(self._time_min),
        }
        info.update(self._soil_diagnostics_info())
        return obs, 0.0, self._done, info

    def get_obs_dim(self):
        """返回观测向量维度。"""
        return self._get_obs().shape[0]

    def get_action_dim(self):
        """返回动作向量维度。"""
        return 2
