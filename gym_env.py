"""
Gymnasium 标准环境封装 — PotatoFertigationEnv
=============================================
将 DigitalTwinEnv 封装为 gymnasium.Env 子类，兼容 Gymnasium API。

使用方式:
    import gymnasium as gym
    from gym_env import PotatoFertigationEnv

    env = PotatoFertigationEnv()
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(action)
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from digital_twin_env import DigitalTwinEnv, GrowthStage


class PotatoFertigationEnv(gym.Env):
    """马铃薯施肥灌溉数字孪生环境 — Gymnasium 封装版。

    参数
    ----------
    growth_stage : GrowthStage
        马铃薯生育阶段
    area_ha : float
        灌溉面积 (公顷)
    dt_min : float
        仿真步长 (分钟)
    ep_len_days : float
        每 episode 天数
    et0_mm_day : float
        参考蒸散发量 (mm/day)
    obs_noise_std : float
        观测噪声标准差
    seed : int, optional
        随机种子
    """

    metadata = {"render_modes": []}

    def __init__(self,
                 growth_stage: GrowthStage = GrowthStage.BULKING,
                 area_ha: float = 0.1,
                 dt_min: float = 1.0,
                 ep_len_days: float = 30.0,
                 et0_mm_day: float = 5.0,
                 obs_noise_std: float = 0.0,
                 seed: int = None):
        super().__init__()

        # 内部环境
        self._env = DigitalTwinEnv(
            growth_stage=growth_stage,
            area_ha=area_ha,
            dt_min=dt_min,
            ep_len_days=ep_len_days,
            et0_mm_day=et0_mm_day,
            obs_noise_std=obs_noise_std,
            seed=seed,
        )

        # --- Gymnasium 空间定义 ---
        obs_dim = self._env.get_obs_dim()
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

        # 动作: [母液流量, 酸液流量]
        self.action_space = spaces.Box(
            low=np.array([0.0, 0.0], dtype=np.float32),
            high=np.array([3.0, 2.0], dtype=np.float32),
            dtype=np.float32,
        )

    def reset(self, seed=None, options=None):
        """重置环境。

        参数
        ----------
        seed : int, optional
            随机种子
        options : dict, optional
            附加选项

        返回
        ----------
        obs : np.ndarray
            初始观测
        info : dict
            附加信息
        """
        if seed is not None:
            self._env._rng = np.random.RandomState(seed)

        obs = self._env.reset()
        # Gymnasium reset 返回 (obs, info)
        return obs, {}

    def step(self, action):
        """执行一个仿真步。

        参数
        ----------
        action : np.ndarray
            [q_f, q_a]

        返回
        ----------
        obs : np.ndarray
            观测
        reward : float
            奖励
        terminated : bool
            是否终止 (到达预设天数)
        truncated : bool
            是否截断 (当前未使用)
        info : dict
            附加信息
        """
        obs, reward, done, info = self._env.step(action)
        # Gymnasium 使用 terminated/truncated
        terminated = done
        truncated = False
        return obs, reward, terminated, truncated, info

    def render(self, mode="human"):
        """渲染（当前无图形界面）。"""
        pass

    def close(self):
        """关闭环境。"""
        pass

    @property
    def current_stage(self):
        return self._env.current_stage

    @current_stage.setter
    def current_stage(self, stage):
        self._env.set_growth_stage(stage)
