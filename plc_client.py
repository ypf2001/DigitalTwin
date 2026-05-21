import snap7
from snap7.util import set_real, set_int, set_bool
import time
from config_loader import load_config

# ---- 从配置文件读取 PLC 连接参数 ----
cfg = load_config()
plc_cfg = cfg.plc()

PLC_IP = plc_cfg.get("ip", "127.0.0.1")
PLC_RACK = plc_cfg.get("rack", 0)
PLC_SLOT = plc_cfg.get("slot", 1)
DB_NUMBER = plc_cfg.get("db_number", 1)
MAX_RETRIES = plc_cfg.get("max_retries", 5)
CYCLE_S = plc_cfg.get("cycle_s", 1.0)

# 1. 连接 PLC（带重试 + 详细诊断）
plc = snap7.client.Client()

connected = False
last_error = ""

for attempt in range(1, MAX_RETRIES + 1):
    try:
        print(f"[尝试 {attempt}/{MAX_RETRIES}] 连接 PLC {PLC_IP} (rack={PLC_RACK}, slot={PLC_SLOT})...")
        plc.connect(PLC_IP, PLC_RACK, PLC_SLOT)
        connected = plc.get_connected()
        if connected:
            print(f"[成功] 与虚拟 PLC 连接成功！")
            break
        else:
            print(f"[失败] 连接返回 False")
    except Exception as e:
        last_error = str(e)
        print(f"[异常] {last_error}")
        time.sleep(2)

if not connected:
    print("\n" + "=" * 55)
    print("  PLC 连接失败，请逐项排查：")
    print("=" * 55)
    print("  1. NetToPLCsim 是否打开并处于 Running 状态？")
    print("     打开 NetToPLCsim → 确认 Status 为 Running")
    print("     确认 Network IP Address 设为: " + PLC_IP)
    print()
    print("  2. 博途 TIA Portal 是否已启动 PLCSIM 仿真？")
    print("     在博途中点击仿真按钮 → 下载到虚拟 PLC")
    print()
    print(f"  3. DB{DB_NUMBER} 数据块是否存在且非优化访问？")
    print(f"     右键 DB{DB_NUMBER} → 属性 → 取消「优化的块访问」")
    print()
    print(f"  4. 最后异常信息: {last_error}")
    print("=" * 55)
    exit(1)

# ---- 诊断：先尝试读 DB，确认块可访问 ----
print(f"[诊断] 尝试读取 DB{DB_NUMBER} 的前 10 字节...")
try:
    raw = plc.db_read(DB_NUMBER, 0, 10)
    print(f"[诊断] 读成功: {raw.hex()}")
except Exception as e:
    print(f"[诊断] 读失败: {e}")
    print()
    print(f"  ⚠ 读取也失败 → 确认是 DB{DB_NUMBER}「优化的块访问」未关闭！")
    print("  操作步骤：")
    print(f"    1. 博途中右键 DB{DB_NUMBER} → 属性")
    print("    2. 取消勾选「优化的块访问」(Optimized block access)")
    print("    3. 重新编译 DB（右键 → 编译 → 软件(全部重建)）")
    print("    4. 重新下载到 PLC（仿真按钮 → 下载）")
    print("    5. 重新运行本脚本")
    exit(1)

heartbeat_val = 0

try:
    while True:
        # 模拟你的 SAC 模型输出的动作
        valve_f = 0.85  # 母液开度
        valve_a = 0.23  # 酸液开度

        # 准备一个长度为 10 字节的空白内存块 (因为 DB 块偏移量到了 8.0，再加上一个 Int(2字节) = 10)
        data_buffer = bytearray(10)

        # 把数据打包进这个内存块（严格对应博途里的偏移量）
        set_real(data_buffer, 0, valve_f)  # 偏移量 0.0: AI_Valve_F (Real)
        set_real(data_buffer, 4, valve_a)  # 偏移量 4.0: AI_Valve_A (Real)

        heartbeat_val = (heartbeat_val + 1) % 32000
        set_int(data_buffer, 8, heartbeat_val)  # 偏移量 8.0: AI_Heartbeat (Int)

        # 把这块内存一口气写入 PLC 的 DB
        plc.db_write(DB_NUMBER, 0, data_buffer)

        print(f"数据下发成功 | 母液: {valve_f}, 酸液: {valve_a}, 心跳: {heartbeat_val}")
        time.sleep(CYCLE_S)

except KeyboardInterrupt:
    print("\nPython 停止下发，触发 PLC 异常接管。")
finally:
    plc.disconnect()
