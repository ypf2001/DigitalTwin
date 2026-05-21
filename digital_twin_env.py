"""
数字孪生集成环境 — DigitalTwinEnv
==================================
将 MixingTank、PipeDynamics、SoilTransport、CropModel 整合为
一个仿 Gym 接口的数字孪生环境，用于施肥灌溉闭环控制仿真。

增强功能:
  - 随机蒸散发波动 (日间正弦 + 随机噪声)
  - 夜间自动停灌 (18:00~6:00 灌溉量为 0)
  - 传感器噪声 (观测叠加高斯噪声，可配置)

状态流:
  动作 [q_f, q_a] → MixingTank → [ec_tank, ph_tank]
                   → PipeDynamics → [ec_drip, ph_drip]
                   → SoilTransport → [theta, ec_soil]
                   → CropModel → [ETc, target_ec]
"""

import numpy as np
from collections import deque

from mixing_tank import MixingTank
from pipe_dynamics import PipeDynamics
from soil_transport import SoilTransport
from crop_model import CropModel, GrowthStage
from config_loader import load_config


class DigitalTwinEnv:
    """数字孪生环境，模仿 Gym 的 step/reset 接口。

    参数
    ----------
    growth_stage : GrowthStage
        马铃薯当前生育阶段
    area_ha : float
        灌溉面积 (公顷)，默认 0.1 ha (1 亩)
    dt_min : float
        仿真步长 (分钟)，默认 1 min
    ep_len_days : float
        每个 episode 时长 (天)，默认 30 天
    et0_mm_day : float
        参考蒸散发量基准值 (mm/day)，默认 5 mm/day
    obs_noise_std : float
        观测噪声标准差，默认 0.01（模拟传感器噪声）
        设为 0.0 关闭噪声
    q_w : float
        清水基础流量 (L/min)，默认 136 L/min
        （匹配论文内蒙古滴灌系统 0.1ha 面积：3704 滴头 × 2.2 L/h）
    seed : int, optional
        随机种子

    动作空间
    --------
    action = [q_f, q_a]
        q_f : 母液流量 0~10 L/min（EC_conc=30 dS/m 时可覆盖目标 EC）
        q_a : 酸液流量 0~4 L/min

    观测空间 (维度 = 23)
    --------
    obs = [θ_{t-4}, ..., θ_t,                         # 5 维: 历史含水率
           EC_soil_{t-4}, ..., EC_soil_t,             # 5 维: 历史土壤 EC
           ec_in_{t-4}, ..., ec_in_t,                 # 5 维: 历史入口 EC
           ph_in_{t-4}, ..., ph_in_t,                 # 5 维: 历史入口 pH
           ETc_mm_day / 10,                           # 1 维: 归一化 ETc
           target_ec / 5,                             # 1 维: 归一化目标 EC
           stage_code]                                # 1 维: 阶段编码 0~4

    奖励
    --------
    r = -|EC_soil - target_ec| * 10 - 总流量 * 0.01
    """

    def __init__(self,
                 growth_stage: GrowthStage = GrowthStage.EMERGENCE,
                 area_ha: float = None,
                 dt_min: float = None,
                 ep_len_days: float = None,
                 et0_mm_day: float = None,
                 obs_noise_std: float = None,
                 q_w: float = None,
                 seed: int = None):
        env_cfg = load_config().env()
        obs_cfg = load_config().obs()

        self.area_ha = area_ha if area_ha is not None else env_cfg["area_ha"]
        self.dt_min = dt_min if dt_min is not None else env_cfg["dt_min"]
        self.ep_len_days = ep_len_days if ep_len_days is not None else env_cfg["ep_len_days"]
        self.et0_base = et0_mm_day if et0_mm_day is not None else env_cfg["et0_mm_day"]
        self.obs_noise_std = obs_noise_std if obs_noise_std is not None else env_cfg["obs_noise_std"]
        self.q_w = q_w if q_w is not None else env_cfg["q_w"]

        # 随机种子
        seed = seed if seed is not None else env_cfg.get("seed")
        self._rng = np.random.RandomState(seed)

        # ---- 子模块 ----
        dt_hours = self.dt_min / 60.0
        self.tank = MixingTank()
        self.pipe = PipeDynamics(dt=self.dt_min)
        self.soil = SoilTransport()
        self.crop = CropModel(growth_stage)
        self.current_stage = growth_stage
        self.soil.root_depth = self.crop.get_root_depth(growth_stage)

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
        dn = load_config().day_night()
        self._night_start = dn["night_start"]
        self._night_end = dn["night_end"]
        self._day_start = dn["day_start"]
        self._day_end = dn["day_end"]
        self._daytime_hours = dn["daytime_hours"]
        self._et_peak_factor = dn["et_peak_factor"]
        self._et_fluctuation = dn["et_fluctuation"]

        # ---- 动作限幅 ----
        act = load_config().action()
        self._q_f_min = act["q_f_min"]
        self._q_f_max = act["q_f_max"]
        self._q_a_min = act["q_a_min"]
        self._q_a_max = act["q_a_max"]

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

    def _action_to_flow(self, action):
        """将动作 [q_f, q_a] 转换为灌溉参数，夜间仅停肥不停水。"""
        q_f = float(np.clip(action[0], self._q_f_min, self._q_f_max))
        q_a = float(np.clip(action[1], self._q_a_min, self._q_a_max))

        # 夜间停肥不停水（清水继续维持土壤湿度）
        if self._is_nighttime(self._time_min):
            q_f = 0.0
            q_a = 0.0

        total_flow_Lmin = q_f + q_a + self.q_w

        # 单位换算: L/min → mm/h
        #   总流量 L/min * 60 min/h = L/h
        #   面积 = area_ha * 10000 m²
        #   1 L = 0.001 m³
        #   mm/h = (L/h * 0.001) m³/h / (area_ha * 10000) m² * 1000 mm/m
        #        = total_flow * 60 / (area_ha * 10000)
        irrigation_mm_h = total_flow_Lmin * 60.0 / (self.area_ha * 10000.0)

        return q_f, q_a, irrigation_mm_h

    def _get_obs(self):
        """
        总共 23 个数,它通过这些数字感知土壤状态。
        """
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
        # 初始化组装
        obs = np.array(
            theta_hist + ec_soil_hist + ec_in_hist + ph_in_hist +
            [etc / self._ETC_NORM,
             target_ec / self._TARGET_EC_NORM,
             float(stage_code)],
            dtype=np.float32
        )

        # --- 传感器噪声 ---
        if self.obs_noise_std > 0:
            noise = self._rng.normal(0, self.obs_noise_std, size=obs.shape).astype(np.float32)
            obs += noise

        return obs

    def _compute_reward(self, ec_soil, ph_drip, total_flow_Lmin):
        """计算奖励函数（多目标）。

        r = -w1*|EC_soil - target_ec|^2
            - w2*|pH_drip - pH_target|^2
            - w3*total_flow * 0.01
            + w4*WUE_bonus
            + 烧苗硬惩罚（EC_soil>3.0 或 pH_drip<4.5 → -100）

        返回 (reward, ec_reward, ph_reward, burn) 四元组。
        """
        rw = load_config().reward()
        w1, w2, w3, w4 = rw["w1"], rw["w2"], rw["w3"], rw["w4"]
        pH_TARGET = rw["pH_target"]

        target_ec = self.crop.get_target_ec(self.current_stage)

        # EC 跟踪惩罚（二次型）
        ec_error = abs(ec_soil - target_ec)
        ec_reward = -w1 * ec_error * ec_error

        # pH 跟踪惩罚（二次型）
        ph_error = abs(ph_drip - pH_TARGET)
        ph_reward = -w2 * ph_error * ph_error

        # 流量惩罚
        flow_penalty = total_flow_Lmin * rw["flow_penalty_scale"] * w3

        # 灌溉效率奖励（流量越小奖励越高）
        wue_bonus = max(0.0, 1.0 - total_flow_Lmin / rw["wue_norm"]) * w4

        # 烧苗硬惩罚
        hard_penalty = 0.0
        if ec_soil > rw["ec_burn_threshold"] or ph_drip < rw["ph_burn_threshold"]:
            hard_penalty = rw["hard_penalty"]

        reward = ec_reward + ph_reward - flow_penalty + wue_bonus + hard_penalty
        burn = (hard_penalty < 0.0)
        return reward, ec_reward, ph_reward, burn

    def step(self, action):
        """执行一个仿真步。

        参数
        ----------
        action : array_like
            [母液流量 q_f (L/min), 酸液流量 q_a (L/min)]

        返回
        ----------
        obs : np.ndarray
            观测向量 (23 维)
        reward : float
            奖励值
        done : bool
            是否结束
        info : dict
            附加信息
        """
        # ---- 1. 动作映射与单位换算 ----
        q_f, q_a, irrigation_mm_h = self._action_to_flow(action)
        total_flow_Lmin = q_f + q_a

        # ---- 2. MixingTank ----
        ec_tank, ph_tank = self.tank.step(q_f, q_a, q_w=self.q_w)

        # ---- 3. PipeDynamics ----
        ec_drip, ph_drip = self.pipe.step(ec_tank, ph_tank)

        # ---- 4. SoilTransport ----
        et_mm_h = self._get_actual_et(self._time_min)
        dt_hours = self.dt_min / 60.0
        theta, ec_soil = self.soil.step(irrigation_mm_h, ec_drip, et_mm_h, dt_hours)

        # ---- 5. 记录历史 ----
        self._theta_history.append(theta)
        self._ec_soil_history.append(ec_soil)
        self._ec_in_history.append(ec_drip)
        self._ph_in_history.append(ph_drip)

        # ---- 6. 奖励 ----
        reward, ec_reward_component, ph_reward_component, burn = self._compute_reward(ec_soil, ph_drip, total_flow_Lmin)
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
            'time_min': self._time_min,
            'time_day': self._time_min / (24 * 60),
            'theta': theta,
            'ec_soil': ec_soil,
            'ec_drip': ec_drip,
            'ph_drip': ph_drip,
            'etc_mm_h': et_mm_h,
            'target_ec': self.crop.get_target_ec(self.current_stage),
            'irrigation_mm_h': irrigation_mm_h,
            'q_f': q_f,
            'q_a': q_a,
            'total_flow_Lmin': total_flow_Lmin,
            'is_night': self._is_nighttime(self._time_min),
            'ec_reward': ec_reward_component,
            'ph_reward': ph_reward_component,
            'burn': burn,
        }

        return obs, reward, self._done, info

    def reset(self):
        """重置环境至初始状态。

        返回
        ----------
        obs : np.ndarray
            初始观测向量
        """
        self.tank.reset()
        self.pipe.reset()
        self.soil.reset()

        self._theta_history.clear()
        self._ec_soil_history.clear()
        self._ec_in_history.clear()
        self._ph_in_history.clear()

        self._time_min = 0.0
        self._total_steps = 0
        self._done = False
        # 因为观测向量包含"最近 5 步"的历史，刚启动时还没有历史，所以用初始值填充：
        soil = load_config().soil()
        init_theta, init_ec_soil = soil["theta_init"], soil["ec_soil_init"]
        init_ec_in, init_ph_in = 0.0, 7.0
        for _ in range(self.history_len):
            self._theta_history.append(init_theta)
            self._ec_soil_history.append(init_ec_soil)
            self._ec_in_history.append(init_ec_in)
            self._ph_in_history.append(init_ph_in)
        #
        return self._get_obs()

    def set_growth_stage(self, stage: GrowthStage):
        """切换生育阶段，同步更新作物模型、根系深度和目标 EC。"""
        self.current_stage = stage
        self.crop.current_stage = stage
        self.soil.root_depth = self.crop.get_root_depth(stage)

    def dry_step(self, rain_mm_h: float = 0.0):
        """执行一个纯蒸发步进（无灌溉，无施肥）。

        用于模拟两次灌溉事件之间的干旱期。
        只推进 SoilTransport 的 ET 和时钟，不涉及 MixingTank/PipeDynamics。

        参数
        ----------
        rain_mm_h : float
            降雨强度 (mm/h)，论文中生育期有效降雨约 2 mm/day ≈ 0.083 mm/h
        """
        dt_hours = self.dt_min / 60.0
        et_mm_h = self._get_actual_et(self._time_min)

        # 降雨视为 EC≈0 的水分输入
        theta, ec_soil = self.soil.step(I=rain_mm_h, EC_in=0.0, ET=et_mm_h, dt_hours=dt_hours)

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
            'time_min': self._time_min,
            'time_day': self._time_min / (24 * 60),
            'theta': theta,
            'ec_soil': ec_soil,
            'ec_drip': 0.0,
            'ph_drip': 7.0,
            'etc_mm_h': et_mm_h,
            'target_ec': self.crop.get_target_ec(self.current_stage),
            'irrigation_mm_h': 0.0,
            'q_f': 0.0,
            'q_a': 0.0,
            'total_flow_Lmin': 0.0,
            'is_night': self._is_nighttime(self._time_min),
        }
        return obs, 0.0, self._done, info

    def get_obs_dim(self):
        """返回观测向量的维度 (23)。"""
        return self._get_obs().shape[0]

    def get_action_dim(self):
        """返回动作向量的维度 (2)。"""
        return 2
