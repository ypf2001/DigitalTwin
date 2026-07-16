"""
上位机调控控制器 — PLCController
==================================

功能：
- 实时读取 PLC 状态
- 写入控制指令（EC/pH 目标、NPK 配比、PID 参数）
- 支持自动/手动模式切换
- 心跳监控和通信诊断
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

# 延迟导入，避免循环依赖
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from plc_client import PLCClient
from config_loader import load_config

logger = logging.getLogger(__name__)


class ControlMode(Enum):
    """控制模式"""
    MANUAL = "manual"      # 手动模式
    AUTO_LOCAL = "auto_local"  # 本地自动（阶段配方）
    AUTO_REMOTE = "auto_remote"  # 远程自动（SAC/AI 控制）


@dataclass
class PLCState:
    """PLC 状态快照"""
    # 通信状态
    comm_ok: bool = False
    heartbeat: int = 0

    # 目标值
    ec_set: float = 0.0
    ph_set: float = 0.0

    # 反馈值
    ec_actual: float = 0.0
    ph_actual: float = 0.0

    # 执行输出
    q_f_cmd: float = 0.0  # 总肥液流量
    q_a_cmd: float = 0.0  # 酸液流量
    q_n_cmd: float = 0.0  # N 肥流量
    q_p_cmd: float = 0.0  # P 肥流量
    q_k_cmd: float = 0.0  # K 肥流量

    # NPK 配比
    n_ratio: float = 0.333
    p_ratio: float = 0.333
    k_ratio: float = 0.334

    # 生长阶段
    growth_stage: int = 0

    # 模式状态
    manual_mode: bool = False
    auto_mode: bool = False
    sac_enable: bool = False

    # 告警
    system_alarm: bool = False


class PLCController:
    """PLC 调控控制器"""

    def __init__(self, ip: str = None, rack: int = None, slot: int = None):
        """初始化控制器"""
        self._client = PLCClient(ip=ip, rack=rack, slot=slot)

        # 状态缓存
        self._state: Optional[PLCState] = None
        self._last_update: float = 0.0

        # 控制参数
        self._control_mode = ControlMode.AUTO_LOCAL
        self._ec_setpoint = 1.5
        self._ph_setpoint = 6.0

    # ================================================================
    #  连接管理
    # ================================================================

    def connect(self) -> bool:
        """连接 PLC"""
        return self._client.connect()

    def disconnect(self):
        """断开连接"""
        self._client.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    # ================================================================
    #  状态读取
    # ================================================================

    def read_state(self) -> PLCState:
        """读取 PLC 当前状态"""
        raw = self._client.read_state()
        if raw is None:
            logger.warning("[Controller] PLC 状态读取失败")
            return self._state or PLCState()

        state = PLCState(
            comm_ok=raw.get("Remote_Comms_OK", False),
            heartbeat=raw.get("Remote_Heartbeat", 0),

            ec_set=raw.get("EC_Set_SP", 0.0),
            ph_set=raw.get("pH_Set_SP", 0.0),

            ec_actual=raw.get("EC_Actual", 0.0),
            ph_actual=raw.get("pH_Actual", 0.0),

            q_f_cmd=raw.get("q_f_cmd", 0.0),
            q_a_cmd=raw.get("q_a_cmd", 0.0),
            q_n_cmd=raw.get("q_n_cmd", 0.0),
            q_p_cmd=raw.get("q_p_cmd", 0.0),
            q_k_cmd=raw.get("q_k_cmd", 0.0),

            n_ratio=raw.get("N_Ratio", 0.333),
            p_ratio=raw.get("P_Ratio", 0.333),
            k_ratio=raw.get("K_Ratio", 0.334),

            growth_stage=raw.get("Growth_Stage", 0),

            manual_mode=raw.get("Manual_Mode", False),
            auto_mode=raw.get("Auto_Mode", False),
            sac_enable=raw.get("SAC_Enable", False),

            system_alarm=raw.get("System_Alarm_Light", False),
        )

        self._state = state
        self._last_update = time.time()
        return state

    @property
    def state(self) -> PLCState:
        """获取缓存的状态"""
        if self._state is None:
            return self.read_state()
        return self._state

    # ================================================================
    #  控制指令
    # ================================================================

    def set_control_mode(self, mode: ControlMode) -> bool:
        """设置控制模式"""
        self._control_mode = mode

        if mode == ControlMode.MANUAL:
            self._client.write_manual_mode(enabled=True)
        elif mode == ControlMode.AUTO_LOCAL:
            self._client.write_manual_mode(enabled=False)
            self._client.write_setpoints(
                ec_set=self._ec_setpoint,
                ph_set=self._ph_setpoint,
                ec_actual=self._state.ec_actual if self._state else 0.0,
                ph_actual=self._state.ph_actual if self._state else 0.0,
                sac_enable=False,
            )
        elif mode == ControlMode.AUTO_REMOTE:
            self._client.write_manual_mode(enabled=False)

        logger.info(f"[Controller] 模式切换: {mode.value}")
        return True

    def set_setpoints(self, ec: float, ph: float) -> bool:
        """设置 EC/pH 目标值"""
        self._ec_setpoint = ec
        self._ph_setpoint = ph

        state = self._state or PLCState()
        return self._client.write_setpoints(
            ec_set=ec,
            ph_set=ph,
            ec_actual=state.ec_actual,
            ph_actual=state.ph_actual,
            sac_enable=(self._control_mode == ControlMode.AUTO_REMOTE),
        )

    def set_feedback(self, ec_actual: float, ph_actual: float) -> bool:
        """更新传感器反馈值"""
        return self._client.write_feedback(
            ec_actual=ec_actual,
            ph_actual=ph_actual,
            sac_enable=(self._control_mode == ControlMode.AUTO_REMOTE),
        )

    def set_growth_stage(self, stage: int) -> bool:
        """设置生长阶段 (0=INI, 1=DEV, 2=MID, 3=LATE)"""
        return self._client.write_growth_stage(stage)

    def set_npk_ratios(self, n: float, p: float, k: float) -> bool:
        """设置 NPK 配比"""
        channels = {
            "N": {"ratio": n},
            "P": {"ratio": p},
            "K": {"ratio": k},
        }
        return self._client.write_fertilizer_channels(channels)

    def set_pid_params(self,
                       kp_ec: float, ki_ec: float, kd_ec: float,
                       kp_ph: float, ki_ph: float, kd_ph: float) -> bool:
        """设置 PID 参数"""
        return self._client.write_pid_params(
            kp_ec=kp_ec, ki_ec=ki_ec, kd_ec=kd_ec,
            kp_ph=kp_ph, ki_ph=ki_ph, kd_ph=kd_ph,
        )

    def set_manual_outputs(self,
                           q_f: float = 0.0,
                           q_a: float = 0.0,
                           q_n: float = 0.0,
                           q_p: float = 0.0,
                           q_k: float = 0.0) -> bool:
        """手动模式下直接设置输出"""
        if self._control_mode != ControlMode.MANUAL:
            logger.warning("[Controller] 非手动模式，无法设置手动输出")
            return False
        return self._client.write_manual_mode(
            enabled=True,
            q_f=q_f, q_a=q_a,
            q_n=q_n, q_p=q_p, q_k=q_k,
        )

    def emergency_stop(self, enable: bool = True) -> bool:
        """紧急停止"""
        return self._client.write_emergency_stop(enable)

    # ================================================================
    #  高级控制
    # ================================================================

    def run_auto_control(self,
                         ec_set: float,
                         ph_set: float,
                         ec_actual: float,
                         ph_actual: float) -> dict:
        """
        执行一次自动控制周期

        返回:
            dict: 包含写入结果和读取状态的字典
        """
        # 写入目标值和反馈
        write_ok = self._client.write_setpoints(
            ec_set=ec_set,
            ph_set=ph_set,
            ec_actual=ec_actual,
            ph_actual=ph_actual,
            sac_enable=True,
        )

        # 读取执行结果
        state = self.read_state()

        return {
            "write_success": write_ok,
            "comm_ok": state.comm_ok,
            "ec_set": state.ec_set,
            "ph_set": state.ph_set,
            "q_f_cmd": state.q_f_cmd,
            "q_a_cmd": state.q_a_cmd,
            "q_n_cmd": state.q_n_cmd,
            "q_p_cmd": state.q_p_cmd,
            "q_k_cmd": state.q_k_cmd,
            "system_alarm": state.system_alarm,
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


def demo_controller():
    """演示控制器使用"""
    print("=== PLC 调控控制器演示 ===\n")

    with PLCController() as ctrl:
        # 读取当前状态
        print("1. 读取 PLC 状态...")
        state = ctrl.read_state()
        print(f"   通信状态: {state.comm_ok}")
        print(f"   EC 目标: {state.ec_set:.3f}, pH 目标: {state.ph_set:.2f}")
        print(f"   EC 实际: {state.ec_actual:.3f}, pH 实际: {state.ph_actual:.2f}")
        print(f"   肥液输出: q_f={state.q_f_cmd:.3f}, q_a={state.q_a_cmd:.3f}")

        # 设置控制模式
        print("\n2. 切换到远程自动模式...")
        ctrl.set_control_mode(ControlMode.AUTO_REMOTE)

        # 设置目标值
        print("\n3. 设置 EC/pH 目标值...")
        ctrl.set_setpoints(ec=1.8, ph=6.2)

        # 设置生长阶段
        print("\n4. 设置生长阶段...")
        ctrl.set_growth_stage(2)  # MID 阶段

        # 设置 NPK 配比
        print("\n5. 设置 NPK 配比...")
        ctrl.set_npk_ratios(n=0.35, p=0.25, k=0.40)

        # 读取最终状态
        print("\n6. 读取最终状态...")
        state = ctrl.read_state()
        print(f"   EC 目标: {state.ec_set:.3f}")
        print(f"   N/P/K 配比: {state.n_ratio:.2f}/{state.p_ratio:.2f}/{state.k_ratio:.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo_controller()