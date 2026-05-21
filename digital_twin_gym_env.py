"""
Gymnasium 标准环境封装 — DigitalTwinGymEnv
==========================================
将 DigitalTwinEnv 封装为标准 Gymnasium 环境。
新增功能：
  - 可配置仿真步长 dt_min（默认 60 min = 1 hour/step）
  - 阶段名称映射：INI→EMERGENCE, DEV→VEGETATIVE, MID→BULKING, LATE→MATURATION
  - 奖励缩放（乘缩放因子使数值更稳定）
  - 观测归一化（各维度缩放到 ~[-1,1] 范围）
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from digital_twin_env import DigitalTwinEnv, GrowthStage
from config_loader import load_config

# 生育阶段映射：简写 → GrowthStage（对齐论文四阶段 + 收获期）
STAGE_MAP = {
    "INI": GrowthStage.EMERGENCE,              # 苗期
    "DEV": GrowthStage.TUBER_INIT,             # 块茎形成期
    "MID": GrowthStage.BULKING,                # 块茎膨大期
    "LATE": GrowthStage.STARCH_ACCUMULATION,   # 淀粉积累期（论文新增）
}
STAGE_NAMES = list(STAGE_MAP.keys())  # ["INI", "DEV", "MID", "LATE"]

# 观测各维度的归一化上下界（从配置文件读取）
def _make_obs_bounds():
    cfg = load_config().obs()
    return (
        np.array(cfg["obs_low"], dtype=np.float32),
        np.array(cfg["obs_high"], dtype=np.float32),
    )

OBS_LOW, OBS_HIGH = _make_obs_bounds()


class DigitalTwinGymEnv(gym.Env):
    """施肥灌溉数字孪生 — Gymnasium 标准封装。

    参数
    ----------
    growth_stage : str or GrowthStage
        生育阶段，可选 "INI"/"DEV"/"MID"/"LATE" 或 GrowthStage 枚举
    area_ha : float
        灌溉面积 (公顷)
    dt_min : float
        仿真步长 (分钟)，默认 60 min（即 1 小时/步）
    ep_len_days : float
        episode 长度 (天)，默认 5 天
    et0_mm_day : float
        参考蒸散发量 (mm/day)
    obs_noise_std : float
        观测噪声标准差
    reward_scale : float
        奖励缩放因子，默认 1.0（不缩放）
    seed : int, optional
        随机种子
    """

    metadata = {"render_modes": []}

    def __init__(self,
                 growth_stage="MID",
                 area_ha: float = None,
                 dt_min: float = None,
                 ep_len_days: float = None,
                 et0_mm_day: float = None,
                 obs_noise_std: float = None,
                 reward_scale: float = 1.0,
                 seed: int = None):
        super().__init__()

        if isinstance(growth_stage, str):
            stage = STAGE_MAP[growth_stage.upper()]
        else:
            stage = growth_stage

        self.reward_scale = reward_scale

        self._env = DigitalTwinEnv(
            growth_stage=stage,
            area_ha=area_ha,
            dt_min=dt_min,
            ep_len_days=ep_len_days,
            et0_mm_day=et0_mm_day,
            obs_noise_std=obs_noise_std,
            seed=seed,
        )

        obs_dim = self._env.get_obs_dim()
        self._obs_low = OBS_LOW.copy()
        self._obs_high = OBS_HIGH.copy()
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(obs_dim,), dtype=np.float32
        )

        act = load_config().action()
        self.action_space = spaces.Box(
            low=np.array([act["q_f_min"], act["q_a_min"]], dtype=np.float32),
            high=np.array([act["q_f_max"], act["q_a_max"]], dtype=np.float32),
            dtype=np.float32,
        )

    def _normalize_obs(self, obs: np.ndarray) -> np.ndarray:
        """将观测归一化到 [-1, 1]。"""
        # 避免除零
        eps = 1e-6
        normalized = 2.0 * (obs - self._obs_low) / (self._obs_high - self._obs_low + eps) - 1.0
        return np.clip(normalized, -1.0, 1.0, dtype=np.float32)

    def reset(self, seed=None, options=None):
        if seed is not None:
            self._env._rng = np.random.RandomState(seed)
        obs = self._env.reset()
        obs = self._normalize_obs(obs)
        return obs, {}

    def step(self, action):
        obs, reward, done, info = self._env.step(action)
        obs = self._normalize_obs(obs)
        reward = reward * self.reward_scale
        terminated = done
        truncated = False
        return obs, reward, terminated, truncated, info

    def render(self, mode="human"):
        pass

    def close(self):
        pass

    @property
    def current_stage(self):
        return self._env.current_stage

    @current_stage.setter
    def current_stage(self, stage):
        if isinstance(stage, str):
            stage = STAGE_MAP[stage.upper()]
        self._env.set_growth_stage(stage)

    @property
    def unwrapped_env(self):
        """返回底层 DigitalTwinEnv（用于评估时读取额外信息）。"""
        return self._env
