"""
上位机控制面板 — PLCControlPanel
================================

功能：
- PLC 实时监控
- 控制参数设置
- 运行状态可视化
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from plc_control.controller import PLCController, PLCState, ControlMode


class PLCControlPanel:
    """PLC 上位机控制面板"""

    def __init__(self, plc_ip: str = "127.0.0.1"):
        """
        初始化控制面板

        参数:
            plc_ip: PLC IP 地址
        """
        self.plc_ip = plc_ip

        self._controller: Optional[PLCController] = None

    # ================================================================
    #  PLC 通信
    # ================================================================

    def connect_plc(self) -> bool:
        """连接 PLC"""
        print(f"[Panel] 正在连接 PLC: {self.plc_ip}")

        self._controller = PLCController(ip=self.plc_ip)
        success = self._controller.connect()

        if success:
            print("[Panel] PLC 连接成功")
        else:
            print("[Panel] PLC 连接失败")

        return success

    def disconnect_plc(self):
        """断开 PLC 连接"""
        if self._controller:
            self._controller.disconnect()
            self._controller = None
        print("[Panel] PLC 已断开")

    # ================================================================
    #  状态监控
    # ================================================================

    def read_plc_state(self) -> PLCState:
        """读取 PLC 状态"""
        if not self._controller:
            print("[Panel] 请先连接 PLC")
            return PLCState()

        return self._controller.read_state()

    def print_status(self):
        """打印当前状态"""
        state = self.read_plc_state()

        print("\n" + "=" * 60)
        print("                    PLC 运行状态")
        print("=" * 60)
        print(f"  通信状态: {'正常 ✓' if state.comm_ok else '异常 ✗'}")
        print(f"  系统告警: {'有' if state.system_alarm else '无'}")
        print("-" * 60)
        print(f"  EC 目标:  {state.ec_set:.3f} dS/m")
        print(f"  pH 目标:  {state.ph_set:.2f}")
        print(f"  EC 实际:  {state.ec_actual:.3f} dS/m")
        print(f"  pH 实际:  {state.ph_actual:.2f}")
        print("-" * 60)
        print(f"  总肥液:   {state.q_f_cmd:.3f} L/min")
        print(f"  酸液:     {state.q_a_cmd:.3f} L/min")
        print(f"  N 肥:     {state.q_n_cmd:.3f} L/min")
        print(f"  P 肥:     {state.q_p_cmd:.3f} L/min")
        print(f"  K 肥:     {state.q_k_cmd:.3f} L/min")
        print("-" * 60)
        print(f"  N/P/K 配比: {state.n_ratio:.1%}/{state.p_ratio:.1%}/{state.k_ratio:.1%}")
        print(f"  生长阶段: {['INI', 'DEV', 'MID', 'LATE'][state.growth_stage]}")
        print(f"  控制模式: {'手动' if state.manual_mode else ('SAC' if state.sac_enable else '自动')}")
        print("=" * 60 + "\n")

    # ================================================================
    #  控制操作
    # ================================================================

    def set_mode(self, mode: str) -> bool:
        """
        设置控制模式

        参数:
            mode: 'manual' | 'auto_local' | 'auto_remote'
        """
        if not self._controller:
            print("[Panel] 请先连接 PLC")
            return False

        mode_map = {
            "manual": ControlMode.MANUAL,
            "auto_local": ControlMode.AUTO_LOCAL,
            "auto_remote": ControlMode.AUTO_REMOTE,
        }

        if mode not in mode_map:
            print(f"[Panel] 未知模式: {mode}")
            return False

        return self._controller.set_control_mode(mode_map[mode])

    def set_setpoints(self, ec: float, ph: float) -> bool:
        """设置 EC/pH 目标值"""
        if not self._controller:
            print("[Panel] 请先连接 PLC")
            return False

        return self._controller.set_setpoints(ec=ec, ph=ph)

    def set_growth_stage(self, stage: int) -> bool:
        """设置生长阶段 (0-3)"""
        if not self._controller:
            return False
        return self._controller.set_growth_stage(stage)

    def set_npk_ratios(self, n: float, p: float, k: float) -> bool:
        """设置 NPK 配比"""
        if not self._controller:
            return False
        return self._controller.set_npk_ratios(n=n, p=p, k=k)

    def emergency_stop(self) -> bool:
        """紧急停止"""
        if not self._controller:
            return False
        print("[Panel] ⚠ 执行紧急停止!")
        return self._controller.emergency_stop(True)

    def clear_emergency(self) -> bool:
        """清除紧急停止"""
        if not self._controller:
            return False
        return self._controller.emergency_stop(False)

    # ================================================================
    #  高级功能
    # ================================================================

    def run_monitoring(self, interval: float = 1.0, count: int = 10):
        """
        运行监控循环

        参数:
            interval: 采样间隔（秒）
            count: 采样次数
        """
        print(f"\n[Panel] 开始监控，间隔 {interval}s，共 {count} 次...")
        print("-" * 80)
        print(f"{'时间':^12} | {'EC目标':^8} | {'EC实际':^8} | {'pH目标':^6} | {'pH实际':^6} | {'q_f':^8} | {'状态':^8}")
        print("-" * 80)

        for i in range(count):
            state = self.read_plc_state()
            timestamp = time.strftime("%H:%M:%S")

            status = "正常"
            if state.system_alarm:
                status = "告警"
            elif not state.comm_ok:
                status = "通信断"

            print(f"{timestamp:^12} | {state.ec_set:^8.3f} | {state.ec_actual:^8.3f} | "
                  f"{state.ph_set:^6.2f} | {state.ph_actual:^6.2f} | {state.q_f_cmd:^8.3f} | {status:^8}")

            if i < count - 1:
                time.sleep(interval)

        print("-" * 80)
        print("[Panel] 监控结束")

    def run_control_test(self, ec_target: float = 1.5, ph_target: float = 6.0):
        """
        运行控制测试

        参数:
            ec_target: 目标 EC
            ph_target: 目标 pH
        """
        print(f"\n[Panel] 开始控制测试...")
        print(f"  目标 EC: {ec_target:.3f} dS/m")
        print(f"  目标 pH: {ph_target:.2f}")

        # 设置自动模式
        self.set_mode("auto_remote")

        # 设置目标值
        self.set_setpoints(ec=ec_target, ph=ph_target)

        # 模拟反馈（实际应用中从传感器读取）
        for i in range(5):
            # 模拟 EC/pH 逐渐接近目标
            ec_actual = ec_target * (0.8 + 0.05 * i)
            ph_actual = ph_target + (0.3 - 0.06 * i)

            result = self._controller.run_auto_control(
                ec_set=ec_target,
                ph_set=ph_target,
                ec_actual=ec_actual,
                ph_actual=ph_actual,
            )

            print(f"\n  周期 {i+1}:")
            print(f"    EC: 目标={result['ec_set']:.3f}, 实际={ec_actual:.3f}")
            print(f"    pH: 目标={result['ph_set']:.2f}, 实际={ph_actual:.2f}")
            print(f"    输出: q_f={result['q_f_cmd']:.3f}, q_a={result['q_a_cmd']:.3f}")

            time.sleep(0.5)

        print("\n[Panel] 控制测试完成")


def interactive_panel():
    """交互式控制面板"""
    panel = PLCControlPanel()

    print("\n" + "=" * 60)
    print("           PLC 上位机控制面板 - 交互模式")
    print("=" * 60)

    while True:
        print("\n可用命令:")
        print("  1. connect  - 连接 PLC")
        print("  2. status   - 显示当前状态")
        print("  3. monitor  - 启动监控")
        print("  4. set EC pH - 设置目标值")
        print("  5. stage N  - 设置生长阶段")
        print("  6. npk N P K - 设置配比")
        print("  7. test     - 运行控制测试")
        print("  8. estop    - 紧急停止")
        print("  0. quit     - 退出")

        try:
            cmd = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd == "quit" or cmd == "0":
            break

        elif cmd == "connect" or cmd == "1":
            panel.connect_plc()

        elif cmd == "status" or cmd == "2":
            panel.print_status()

        elif cmd == "monitor" or cmd == "3":
            panel.run_monitoring()

        elif cmd.startswith("set ") or cmd.startswith("4"):
            try:
                parts = cmd.split()
                if len(parts) >= 3:
                    ec = float(parts[1])
                    ph = float(parts[2])
                    panel.set_setpoints(ec, ph)
                    print(f"[Panel] 已设置 EC={ec}, pH={ph}")
            except (ValueError, IndexError):
                print("[Panel] 用法: set EC值 pH值")

        elif cmd.startswith("stage ") or cmd.startswith("5"):
            try:
                stage = int(cmd.split()[1])
                panel.set_growth_stage(stage)
                print(f"[Panel] 已设置生长阶段: {stage}")
            except (ValueError, IndexError):
                print("[Panel] 用法: stage 阶段号(0-3)")

        elif cmd.startswith("npk ") or cmd.startswith("6"):
            try:
                parts = cmd.split()
                if len(parts) >= 4:
                    n = float(parts[1])
                    p = float(parts[2])
                    k = float(parts[3])
                    panel.set_npk_ratios(n, p, k)
                    print(f"[Panel] 已设置 NPK 配比: {n}/{p}/{k}")
            except (ValueError, IndexError):
                print("[Panel] 用法: npk N值 P值 K值")

        elif cmd == "test" or cmd == "7":
            panel.run_control_test()

        elif cmd == "estop" or cmd == "8":
            panel.emergency_stop()

        else:
            print("[Panel] 未知命令，请重试")

    # 清理
    panel.disconnect_plc()
    print("\n[Panel] 已退出")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    interactive_panel()
