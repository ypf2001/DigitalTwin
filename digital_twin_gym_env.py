"""
Gymnasium 标准环境封装 — DigitalTwinGymEnv
==========================================

将 DigitalTwinEnv 封装为标准 Gymnasium 环境。

B 方案：SAC 动作不再是 q_f/q_a，而是上层水肥目标值：
    action = [EC_set, pH_set]

底层 q_f/q_a 由 DigitalTwinEnv 内部的执行层模型计算，真实部署时由 PLC-PID 计算。
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from digital_twin_env import DigitalTwinEnv, GrowthStage
from config_loader import load_config


STAGE_MAP = {
    "INI": GrowthStage.EMERGENCE,
    "DEV": GrowthStage.TUBER_INIT,
    "MID": GrowthStage.BULKING,
    "LATE": GrowthStage.STARCH_ACCUMULATION,
}
STAGE_NAMES = list(STAGE_MAP.keys())


def _make_obs_bounds():
    cfg = load_config().obs()
    return (
        np.array(cfg["obs_low"], dtype=np.float32),
        np.array(cfg["obs_high"], dtype=np.float32),
    )


OBS_LOW, OBS_HIGH = _make_obs_bounds()


class DigitalTwinGymEnv(gym.Env):
    """施肥灌溉数字孪生 — Gymnasium 标准封装。"""

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
            low=np.array([
                act.get("ec_set_min", 0.8),
                act.get("ph_set_min", 5.8),
            ], dtype=np.float32),
            high=np.array([
                act.get("ec_set_max", 2.5),
                act.get("ph_set_max", 6.8),
            ], dtype=np.float32),
            dtype=np.float32,
        )

    def _normalize_obs(self, obs: np.ndarray) -> np.ndarray:
        """将观测归一化到 [-1, 1]。"""
        eps = 1e-6
        normalized = 2.0 * (obs - self._obs_low) / (self._obs_high - self._obs_low + eps) - 1.0
        return np.clip(normalized, -1.0, 1.0).astype(np.float32)

    def reset(self, seed=None, options=None):
        if seed is not None:
            self._env._rng = np.random.RandomState(seed)
        obs = self._env.reset()
        return self._normalize_obs(obs), {}

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
        """返回底层 DigitalTwinEnv。"""
        return self._env
