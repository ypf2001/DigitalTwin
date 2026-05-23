"""
PLC 通讯客户端 — PLCClient
============================
面向对象的 snap7 通讯封装，提供：
  1. 双向通讯：db_write 下发动作 + db_read 回读 PLC 状态
  2. 工业级断线重连：指数退避 (Exponential Backoff) 无限重试
  3. 精准的 Bytearray 内存偏移读写（set_real / get_real 等）

用法:
    from plc_client import PLCClient

    plc = PLCClient()
    plc.connect()

    # 下发动作
    plc.write_action(valve_f=0.85, valve_a=0.23)

    # 回读状态
    state = plc.read_state()
    print(state["Actual_Valve_F"], state["Remote_Comms_OK"])

    plc.disconnect()
"""

import time
import logging
import os

import snap7
from snap7.util import set_real, get_real, set_int, get_int, get_bool

from config_loader import load_config

logger = logging.getLogger(__name__)

# ---- 日志配置 ----
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
_error_fh = logging.FileHandler(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'),
    encoding='utf-8'
)
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)


class PLCClient:
    """S7-1200 PLC 通讯客户端，封装 snap7 的双向读写与断线重连。

    参数
    ----------
    ip : str
        PLC IP 地址，默认从配置文件读取
    rack : int
        机架号，默认 0
    slot : int
        槽位号，默认 1
    db_number : int
        DB 块编号，默认 1
    cycle_s : float
        通讯周期 (秒)，默认 1.0
    addr_map : dict or None
        DB1 地址映射字典，None 时从配置文件加载
    """

    # ---- 默认重连参数 ----
    RECONNECT_BASE_DELAY = 1.0     # 基础等待秒数
    RECONNECT_BACKOFF_FACTOR = 2.0 # 退避因子
    RECONNECT_MAX_DELAY = 60.0     # 最大等待秒数

    def __init__(self,
                 ip: str = None,
                 rack: int = None,
                 slot: int = None,
                 db_number: int = None,
                 cycle_s: float = None,
                 addr_map: dict = None):
        cfg = load_config().plc()

        self.ip = ip if ip is not None else cfg.get("ip", "127.0.0.1")
        self.rack = rack if rack is not None else cfg.get("rack", 0)
        self.slot = slot if slot is not None else cfg.get("slot", 1)
        self.db_number = db_number if db_number is not None else cfg.get("db_number", 1)
        self.cycle_s = cycle_s if cycle_s is not None else cfg.get("cycle_s", 1.0)

        # 地址映射：从配置文件读取，也可由外部传入覆盖
        if addr_map is None:
            self.addr_map = cfg.get("addresses", {})
        else:
            self.addr_map = addr_map

        # 内部状态
        self._client = snap7.client.Client()
        self._connected = False
        self._heartbeat = 0

        # 计算读写所需的缓冲区大小
        self._write_buf_size_reals = self._calc_buf_size([
            "Valve_F_Opt_SP", "Valve_A_Opt_SP"
        ])
        self._write_buf_size_heartbeat = self._calc_buf_size([
            "Remote_Heartbeat"
        ])
        self._read_buf_size = self._calc_buf_size([
            "Remote_Comms_OK", "Watchdog_Timer",
            "Actual_Valve_F", "Actual_Valve_A",
            "AQ_Valve_F_Raw", "AQ_Valve_A_Raw",
            "System_Alarm_Light",
        ])

    # ================================================================
    #  连接管理
    # ================================================================

    def connect(self) -> bool:
        """连接 PLC，失败则打印诊断信息。

        返回
        ----------
        bool
            连接是否成功
        """
        try:
            self._client.connect(self.ip, self.rack, self.slot)
            self._connected = self._client.get_connected()
        except Exception as e:
            self._connected = False
            logger.error(f"PLC 连接异常: {e}")

        if self._connected:
            logger.info(f"[PLC] 连接成功 → {self.ip} (rack={self.rack}, slot={self.slot})")
            # 诊断：快速验证 DB 可读
            self._diagnose_db()
        else:
            self._print_connection_diag("")

        return self._connected

    def disconnect(self):
        """断开 PLC 连接。"""
        if self._connected:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._connected = False
            logger.info("[PLC] 已断开连接")

    def _diagnose_db(self):
        """快速诊断 DB 块是否可访问。"""
        try:
            raw = self._client.db_read(self.db_number, 0, 4)
            logger.info(f"[PLC] DB{self.db_number} 可读，首 4 字节: {raw.hex()}")
        except Exception as e:
            logger.error(
                f"[PLC] ⚠ DB{self.db_number} 读取失败: {e}\n"
                f"    请确认 DB{self.db_number}「优化的块访问」已关闭！\n"
                f"    操作: TIA Portal → 右键 DB{self.db_number} → 属性 → 取消「优化的块访问」→ 编译下载"
            )

    @staticmethod
    def _print_connection_diag(last_error: str):
        """打印连接失败的排查指南。"""
        logger.error(
            "\n" + "=" * 55 + "\n"
            "  PLC 连接失败，逐项排查：\n"
            "=" * 55 + "\n"
            "  1. NetToPLCsim / PLCSIM Advanced 是否 Running？\n"
            "  2. TIA Portal 是否已下载到虚拟 PLC？\n"
            "  3. DB 块是否已关闭「优化的块访问」？\n"
            "  4. IP / Rack / Slot 是否匹配？\n"
            f"  5. 最后异常: {last_error}\n"
            "=" * 55
        )

    # ================================================================
    #  断线重连 (Exponential Backoff)
    # ================================================================

    def reconnect(self) -> bool:
        """指数退避无限重连，直到成功。

        返回
        ----------
        bool
            始终返回 True（无限重试直到成功）
        """
        attempt = 0
        delay = self.RECONNECT_BASE_DELAY

        while not self._connected:
            attempt += 1
            logger.warning(
                f"[PLC] 断线重连 第 {attempt} 次 (等待 {delay:.1f}s)..."
            )
            time.sleep(delay)

            try:
                # 先尝试清理旧连接
                try:
                    self._client.disconnect()
                except Exception:
                    pass

                self._client.connect(self.ip, self.rack, self.slot)
                self._connected = self._client.get_connected()
            except Exception as e:
                logger.error(f"[PLC] 重连异常: {e}")
                self._connected = False

            if self._connected:
                logger.info(f"[PLC] ✓ 重连成功 (第 {attempt} 次)")
                self._diagnose_db()
                return True

            # 指数退避
            delay = min(delay * self.RECONNECT_BACKOFF_FACTOR, self.RECONNECT_MAX_DELAY)

        return True  # unreachable

    def _ensure_connected(self):
        """执行操作前确保已连接，否则触发重连。"""
        if not self._connected:
            logger.warning("[PLC] 未连接，尝试重连...")
            self.reconnect()

    # ================================================================
    #  数据写入 (Python → PLC)
    # ================================================================

    def write_action(self, valve_f: float, valve_a: float) -> bool:
        """下发阀门目标开度与心跳到 PLC。

        参数
        ----------
        valve_f : float
            母液阀门开度 (0.0 ~ 1.0 或 0 ~ 100，取决于 PLC 端约定)
        valve_a : float
            酸液阀门开度

        返回
        ----------
        bool
            写入是否成功
        """
        try:
            self._ensure_connected()

            self._heartbeat = (self._heartbeat + 1) % 32000

            # ---- 分两次写入，只碰需要改的字节 ----
            #   offset 0~3:  Valve_F_Opt_SP (Real)
            #   offset 4~7:  Valve_A_Opt_SP (Real)
            #   offset 8~9:  ← 不碰！Remote_Comms_OK 完全由 PLC 管理
            #   offset 10~11: Remote_Heartbeat (Int)
            #   offset 12~15: ← 不碰！Last_Heartbeat、Watchdog_Timer 由 PLC 管理
            #
            #   分次写入顺序：先写阀门，再写心跳。
            #   PLC 在两次写入之间扫描到旧心跳无影响，
            #   心跳信号只要最终进入新值就能被 PLC 检测到。

            # 写入阀门目标值 (offset 0~7)
            buf_v = bytearray(8)
            set_real(buf_v, 0, valve_f)
            set_real(buf_v, 4, valve_a)
            self._client.db_write(self.db_number, 0, buf_v)

            # 写入心跳 (offset 10~11)，不碰中间 byte 8~9
            buf_h = bytearray(2)
            set_int(buf_h, 0, self._heartbeat)
            self._client.db_write(self.db_number, 10, buf_h)

            logger.info(
                f"[PLC] 写入 → Valve_F={valve_f:.3f}, Valve_A={valve_a:.3f}, "
                f"Heartbeat={self._heartbeat}"
            )
            return True

        except (OSError, ConnectionError, AttributeError) as e:
            logger.error(f"[PLC] 写入失败 (网络断开): {e}")
            self._connected = False
            self.reconnect()
            return False
        except Exception as e:
            logger.error(f"[PLC] 写入异常: {e}")
            return False

    # ================================================================
    #  数据读取 (PLC → Python)
    # ================================================================

    def read_state(self) -> dict:
        """从 PLC 回读当前状态。

        读取变量:
            Remote_Comms_OK   — 通讯正常标志
            Watchdog_Timer    — 看门狗计时
            Actual_Valve_F    — 实际阀门开度 F（经过 PLC 斜坡处理后的值）
            Actual_Valve_A    — 实际阀门开度 A
            AQ_Valve_F_Raw    — 模拟量输出原始值 F
            AQ_Valve_A_Raw    — 模拟量输出原始值 A
            System_Alarm_Light— 系统报警灯

        返回
        ----------
        dict
            {
                "Remote_Comms_OK": bool,
                "Watchdog_Timer": int,
                "Actual_Valve_F": float,
                "Actual_Valve_A": float,
                "AQ_Valve_F_Raw": int,
                "AQ_Valve_A_Raw": int,
                "System_Alarm_Light": bool,
            }
            读取失败时返回 None
        """
        try:
            self._ensure_connected()

            # ---- 计算需要读取的最小连续区域 ----
            read_vars = [
                "Remote_Comms_OK", "Watchdog_Timer",
                "Actual_Valve_F", "Actual_Valve_A",
                "AQ_Valve_F_Raw", "AQ_Valve_A_Raw",
                "System_Alarm_Light",
            ]
            start_offset, total_size = self._calc_read_range(read_vars)

            # ---- 一次性 db_read ----
            raw = self._client.db_read(self.db_number, start_offset, total_size)

            # ---- 逐变量解析 ----
            state = {}

            for var_name in read_vars:
                addr = self.addr_map[var_name]
                # 计算该变量在 raw buffer 中的相对偏移
                rel_offset = addr["offset"] - start_offset
                var_type = addr["type"]

                if var_type == "real":
                    state[var_name] = get_real(raw, rel_offset)
                elif var_type == "int":
                    state[var_name] = get_int(raw, rel_offset)
                elif var_type == "bool":
                    # get_bool 返回 (byte_index, bit_index) 的布尔值
                    state[var_name] = get_bool(raw, rel_offset, 0)
                else:
                    state[var_name] = None

            logger.info(
                f"[PLC] 读取 ← CommOK={state['Remote_Comms_OK']}, "
                f"Watchdog={state['Watchdog_Timer']}, "
                f"ValveF={state['Actual_Valve_F']:.3f}, "
                f"ValveA={state['Actual_Valve_A']:.3f}"
            )
            return state

        except (OSError, ConnectionError, AttributeError) as e:
            logger.error(f"[PLC] 读取失败 (网络断开): {e}")
            self._connected = False
            self.reconnect()
            return None
        except Exception as e:
            logger.error(f"[PLC] 读取异常: {e}")
            return None

    @property
    def is_connected(self) -> bool:
        """返回当前连接状态。"""
        return self._connected

    # ================================================================
    #  辅助方法
    # ================================================================

    def _calc_buf_size(self, var_names: list) -> int:
        """计算覆盖指定变量所需的总字节数。"""
        if not var_names:
            return 0
        max_end = 0
        for name in var_names:
            if name in self.addr_map:
                addr = self.addr_map[name]
                end = addr["offset"] + addr["bytes"]
                if end > max_end:
                    max_end = end
        return max_end

    def _calc_read_range(self, var_names: list) -> tuple:
        """计算一次 db_read 能覆盖所有目标变量的 [起始偏移, 总大小]。

        返回 (start_offset, total_size)。
        """
        min_off = float('inf')
        max_end = 0
        for name in var_names:
            if name in self.addr_map:
                addr = self.addr_map[name]
                if addr["offset"] < min_off:
                    min_off = addr["offset"]
                end = addr["offset"] + addr["bytes"]
                if end > max_end:
                    max_end = end
        return int(min_off), int(max_end - min_off)
