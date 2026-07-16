"""
PLC 故障诊断脚本
==================

用于诊断 PLC 卡死、HMI 通信断开等问题
"""

import time
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from plc_client import PLCClient
from config_loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def diagnose_plc_connection():
    """诊断 PLC 连接问题"""
    print("\n" + "=" * 60)
    print("           PLC 故障诊断工具")
    print("=" * 60)

    client = PLCClient()

    # 1. 检查连接
    print("\n[1] 检查 PLC 连接...")
    if not client.connect():
        print("    ❌ PLC 连接失败！")
        print("\n    可能原因：")
        print("    - PLCSIM 未运行")
        print("    - IP 地址错误")
        print("    - Rack/Slot 配置错误")
        return False
    print("    ✓ PLC 连接成功")

    # 2. 读取 DB1 状态
    print("\n[2] 读取 DB1 状态...")
    state = client.read_state()
    if state is None:
        print("    ❌ DB1 读取失败！")
        print("    可能原因：DB1 「优化的块访问」未关闭")
        client.disconnect()
        return False

    # 3. 分析状态
    print("\n[3] 分析 PLC 状态...")
    print(f"    Remote_Comms_OK = {state.get('Remote_Comms_OK', False)}")
    print(f"    Watchdog_Timer   = {state.get('Watchdog_Timer', 0)}")
    print(f"    Remote_Heartbeat = {state.get('Remote_Heartbeat', 0)}")
    print(f"    System_Alarm     = {state.get('System_Alarm_Light', False)}")

    # 4. 检查看门狗状态
    print("\n[4] 看门狗状态分析...")
    watchdog = state.get('Watchdog_Timer', 0)
    if watchdog > 8000:
        print(f"    ⚠️  看门狗计数过高: {watchdog}/10000")
        print("    上位机可能已停止发送心跳！")
    elif watchdog > 5000:
        print(f"    ⚠️  看门狗计数偏高: {watchdog}/10000")
    else:
        print(f"    ✓ 看门狗正常: {watchdog}/10000")

    # 5. 检查通信状态
    print("\n[5] 通信状态分析...")
    if not state.get('Remote_Comms_OK', False):
        print("    ❌ Remote_Comms_OK = FALSE")
        print("    PLC 认为上位机通信已断开！")
        print("\n    解决方案：")
        print("    - 重启上位机 Python 脚本")
        print("    - 检查 SAC_Enable 是否为 TRUE")
        print("    - 确认上位机正在写入 Heartbeat")
    else:
        print("    ✓ 通信状态正常")

    # 6. 检查输出状态
    print("\n[6] 输出状态分析...")
    q_f = state.get('q_f_cmd', 0)
    q_a = state.get('q_a_cmd', 0)
    print(f"    q_f_cmd = {q_f:.3f} L/min")
    print(f"    q_a_cmd = {q_a:.3f} L/min")

    if state.get('Emergency_Stop', False):
        print("    ⚠️  急停激活！")

    # 7. 检查模式状态
    print("\n[7] 模式状态分析...")
    print(f"    Manual_Mode = {state.get('Manual_Mode', False)}")
    print(f"    Auto_Mode   = {state.get('Auto_Mode', False)}")
    print(f"    SAC_Enable  = {state.get('SAC_Enable', False)}")

    # 8. 持续监控
    print("\n[8] 开始持续监控（10次，每秒一次）...")
    print("-" * 60)
    print(f"{'时间':^12} | {'心跳':^6} | {'看门狗':^6} | {'通信OK':^6} | {'q_f':^8}")
    print("-" * 60)

    for i in range(10):
        state = client.read_state()
        if state:
            t = time.strftime("%H:%M:%S")
            hb = state.get('Remote_Heartbeat', 0)
            wd = state.get('Watchdog_Timer', 0)
            ok = "✓" if state.get('Remote_Comms_OK', False) else "✗"
            qf = state.get('q_f_cmd', 0)
            print(f"{t:^12} | {hb:^6} | {wd:^6} | {ok:^6} | {qf:^8.3f}")
        time.sleep(1)

    print("-" * 60)
    client.disconnect()
    print("\n诊断完成。")
    return True


def reset_plc_state():
    """重置 PLC 状态"""
    print("\n重置 PLC 状态...")

    client = PLCClient()
    if not client.connect():
        print("连接失败")
        return False

    # 清除急停
    client.write_emergency_stop(False)

    # 写入心跳
    state = client.read_state()
    if state:
        client.write_feedback(
            ec_actual=state.get('EC_Actual', 1.5),
            ph_actual=state.get('pH_Actual', 6.0),
            sac_enable=True,
        )

    client.disconnect()
    print("状态已重置")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PLC 故障诊断工具")
    parser.add_argument("--reset", action="store_true", help="重置 PLC 状态")
    args = parser.parse_args()

    if args.reset:
        reset_plc_state()
    else:
        diagnose_plc_connection()