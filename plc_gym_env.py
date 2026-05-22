"""
PLC 在环 Gymnasium 环境 — PLCGymEnv
=====================================
将 RL 动作写入 PLC 执行，读取 PLC 实际阀门反馈，同时用仿真模型预测
土壤/作物状态转移。实现完整的硬件在环 (HIL) 闭环。

数据流:
  Agent action [q_f, q_a]
    │
    ├─→ PLC: db_write(Valve_F_Opt_SP, Valve_A_Opt_SP, Heartbeat)
    │         ↓ (PLC 看门狗 + 斜坡护盾)
    │   PLC: db_read(Actual_Valve_F, Actual_Valve_A, ...)  ← 真实物理反馈
    │
    └─→ DigitalTwinEnv: step()  ← 仿真预测土壤/作物状态
              │
              └─→ obs, reward, done, info

用法:
    from plc_client import PLCClient
    from plc_gym_env import PLCGymEnv

    plc = PLCClient()
    plc.connect()

    env = PLCGymEnv(plc_client=plc, growth_stage="MID")
    obs, _ = env.reset()
    obs, reward, terminated, truncated, info = env.step([5.0, 1.0])
"""

import time
import logging
import numpy as np

import gymnasium as gym
from gymnasium import spaces

from digital_twin_gym_env import DigitalTwinGymEnv, STAGE_MAP
from plc_client import PLCClient

logger = logging.getLogger(__name__)


class PLCGymEnv(gym.Env):
    """硬件在环 Gymnasium 环境。

    将数字孪生仿真与 PLC 实物结合：
      - step() 先将动作写入 PLC → 等待 PLC 执行 → 回读实际阀门位置
      - 同时推进仿真模型计算土壤/作物状态转移
      - 奖励由仿真模型计算
      - info 字典中附带 PLC 实时反馈数据

    参数
    ----------
    plc_client : PLCClient
        已创建（可未连接）的 PLC 通讯客户端实例
    growth_stage : str
        生育阶段: "INI" / "DEV" / "MID" / "LATE"
    area_ha : float, optional
        灌溉面积 (公顷)
    dt_min : float, optional
        仿真步长 (分钟)，默认 60 min
    ep_len_days : float, optional
        episode 长度 (天)
    et0_mm_day : float, optional
        参考蒸散发量
    obs_noise_std : float, optional
        观测噪声标准差
    reward_scale : float
        奖励缩放因子
    seed : int, optional
        随机种子
    plc_enabled : bool
        是否启用 PLC 通讯。设为 False 时退化为纯仿真模式（调试用）
    max_action_clip : list
        动作上界 [q_f_max, q_a_max]，用于将动作缩放为 0~1 开度写入 PLC
    """

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
                 plc_enabled: bool = True,
                 max_action_clip: list = None):
        super().__init__()

        # ---- PLC ----
        self.plc = plc_client
        self.plc_enabled = plc_enabled and (self.plc is not None)

        # ---- 动作上界 (用于 PLC 开度缩放) ----
        if max_action_clip is None:
            self._act_max = np.array([10.0, 4.0], dtype=np.float32)  # q_f, q_a 上界
        else:
            self._act_max = np.array(max_action_clip, dtype=np.float32)

        # ---- 仿真环境 ----
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

        # ---- 观测/动作空间 (透传仿真环境) ----
        self.observation_space = self._sim_env.observation_space
        self.action_space = self._sim_env.action_space

        # ---- PLC 反馈缓存 ----
        self._last_plc_state = {
            "Remote_Comms_OK": False,
            "Watchdog_Timer": 0,
            "Actual_Valve_F": 0.0,
            "Actual_Valve_A": 0.0,
            "AQ_Valve_F_Raw": 0,
            "AQ_Valve_A_Raw": 0,
            "System_Alarm_Light": False,
        }

    # ================================================================
    #  Gymnasium 标准接口
    # ================================================================

    def reset(self, seed=None, options=None):
        """重置环境：仿真归零 + PLC 阀门归零。

        返回
        ----------
        obs : np.ndarray
            初始观测
        info : dict
            含 PLC 初始状态
        """
        # ---- 1. 重置仿真 ----
        obs, sim_info = self._sim_env.reset(seed=seed, options=options)

        # ---- 2. PLC 阀门归零 ----
        if self.plc_enabled:
            self._safe_plc_write(0.0, 0.0)
            time.sleep(self.plc.cycle_s)

            plc_state = self.plc.read_state()
            if plc_state is not None:
                self._last_plc_state = plc_state

        # ---- 3. 组装 info ----
        info = self._build_info({})
        return obs, info

    def step(self, action):
        """执行一个 HIL 控制步。

        流程:
            1. 动作裁剪 + 缩放到 0~1 开度
            2. 写入 PLC（下发阀门目标 + 心跳）
            3. 等待 PLC 物理执行 (cycle_s)
            4. 回读 PLC 实际阀门开度
            5. 驱动仿真模型 step()
            6. 返回 (obs, reward, terminated, truncated, info)

        参数
        ----------
        action : array_like
            [母液流量 q_f (0~10 L/min), 酸液流量 q_a (0~4 L/min)]

        返回
        ----------
        obs : np.ndarray
        reward : float
        terminated : bool
        truncated : bool
        info : dict
        """
        action = np.asarray(action, dtype=np.float32).flatten()

        # ---- 1. 裁剪动作 ----
        action_clipped = np.clip(action, self.action_space.low, self.action_space.high)

        # ---- 2. 写入 PLC ----
        if self.plc_enabled:
            # 将 L/min 动作值缩放为 0~1 阀门开度
            valve_f = float(action_clipped[0] / self._act_max[0])
            valve_a = float(action_clipped[1] / self._act_max[1])

            plc_ok = self._safe_plc_write(valve_f, valve_a)

            # ---- 3. 等待 PLC 执行 ----
            time.sleep(self.plc.cycle_s)

            # ---- 4. 回读 PLC 实际状态 ----
            plc_state = self.plc.read_state()
            if plc_state is not None:
                self._last_plc_state = plc_state
                # 如果 PLC 通讯异常，log 警告
                if not plc_state["Remote_Comms_OK"]:
                    logger.warning(
                        f"[HIL] ⚠ PLC 通讯异常! "
                        f"Watchdog={plc_state['Watchdog_Timer']}, "
                        f"Alarm={plc_state['System_Alarm_Light']}"
                    )
            else:
                logger.error("[HIL] PLC 读取失败，已触发重连")

        # ---- 5. 推进仿真模型 ----
        #     注意：仿真仍然使用原始的 L/min 动作值
        obs, reward, terminated, truncated, sim_info = self._sim_env.step(action_clipped)

        # ---- 6. 组装 info ----
        info = self._build_info(sim_info)

        return obs, reward, terminated, truncated, info

    def render(self, mode="human"):
        pass

    def close(self):
        """关闭环境，断开 PLC 连接。"""
        if self.plc_enabled:
            # 安全切断
            self._safe_plc_write(0.0, 0.0)
            self.plc.disconnect()
        self._sim_env.close()

    # ================================================================
    #  属性透传
    # ================================================================

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
        """返回底层 DigitalTwinEnv（用于评估时读取额外信息）。"""
        return self._sim_env.unwrapped_env

    # ================================================================
    #  内部方法
    # ================================================================

    def _safe_plc_write(self, valve_f: float, valve_a: float) -> bool:
        """安全写入 PLC，自动处理断线重连。"""
        if not self.plc_enabled:
            return True
        try:
            return self.plc.write_action(valve_f, valve_a)
        except Exception as e:
            logger.error(f"[HIL] PLC 写入异常: {e}")
            return False

    def _build_info(self, sim_info: dict) -> dict:
        """组装 info 字典，合并仿真信息与 PLC 反馈。"""
        info = dict(sim_info)
        info["plc"] = dict(self._last_plc_state)
        info["plc_enabled"] = self.plc_enabled
        return info

    def get_plc_state(self) -> dict:
        """获取最新的 PLC 状态快照（不触发新读取）。"""
        return dict(self._last_plc_state)
