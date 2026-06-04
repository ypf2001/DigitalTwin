"""
PLC 通讯客户端 — PLCClient
============================

B 方案通讯约定：
- Python/SAC 写入上层目标值 EC_Set_SP、pH_Set_SP，以及数字孪生/传感器反馈 EC_Actual、pH_Actual；
- PLC/PLCSIM 内部运行 EC-PID、pH-PID，输出 q_f_cmd、q_a_cmd 或阀门开度；
- Python 回读 PLC 执行结果，用于驱动数字孪生模型或记录半实物在环试验。
"""

import logging
import os
import time

import snap7
from snap7.util import get_bool, get_int, get_real, set_bool, set_int, set_real

from config_loader import load_config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rl_logs")
os.makedirs(_log_dir, exist_ok=True)
_error_fh = logging.FileHandler(os.path.join(_log_dir, "error.log"), encoding="utf-8")
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
logging.getLogger().addHandler(_error_fh)


class PLCClient:
    """S7-1200 / PLCSIM Advanced 通讯客户端。"""

    RECONNECT_BASE_DELAY = 1.0
    RECONNECT_BACKOFF_FACTOR = 2.0
    RECONNECT_MAX_DELAY = 60.0

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
        self.addr_map = addr_map if addr_map is not None else cfg.get("addresses", {})

        self._client = snap7.client.Client()
        self._connected = False
        self._heartbeat = 0

    # ================================================================
    #  连接管理
    # ================================================================

    def connect(self) -> bool:
        """连接 PLC/PLCSIM。"""
        try:
            self._client.connect(self.ip, self.rack, self.slot)
            self._connected = self._client.get_connected()
        except Exception as e:
            self._connected = False
            logger.error(f"PLC 连接异常: {e}")

        if self._connected:
            logger.info(f"[PLC] 连接成功 → {self.ip} (rack={self.rack}, slot={self.slot})")
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
        logger.error(
            "\n" + "=" * 55 + "\n"
            "  PLC 连接失败，逐项排查：\n"
            "=" * 55 + "\n"
            "  1. PLCSIM Advanced 是否 Running？\n"
            "  2. TIA Portal 是否已下载到虚拟 PLC？\n"
            "  3. DB 块是否已关闭「优化的块访问」？\n"
            "  4. IP / Rack / Slot 是否匹配？\n"
            f"  5. 最后异常: {last_error}\n"
            "=" * 55
        )

    def reconnect(self) -> bool:
        """指数退避无限重连。"""
        attempt = 0
        delay = self.RECONNECT_BASE_DELAY
        while not self._connected:
            attempt += 1
            logger.warning(f"[PLC] 断线重连 第 {attempt} 次 (等待 {delay:.1f}s)...")
            time.sleep(delay)
            try:
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
            delay = min(delay * self.RECONNECT_BACKOFF_FACTOR, self.RECONNECT_MAX_DELAY)
        return True

    def _ensure_connected(self):
        if not self._connected:
            logger.warning("[PLC] 未连接，尝试重连...")
            self.reconnect()

    # ================================================================
    #  通用 DB 读写辅助
    # ================================================================

    def _addr(self, name: str) -> dict:
        if name not in self.addr_map:
            raise KeyError(f"PLC 地址映射缺少变量: {name}")
        return self.addr_map[name]

    def _write_real(self, name: str, value: float):
        addr = self._addr(name)
        buf = bytearray(4)
        set_real(buf, 0, float(value))
        self._client.db_write(self.db_number, int(addr["offset"]), buf)

    def _write_int(self, name: str, value: int):
        addr = self._addr(name)
        buf = bytearray(2)
        set_int(buf, 0, int(value))
        self._client.db_write(self.db_number, int(addr["offset"]), buf)

    def _write_bool(self, name: str, value: bool):
        addr = self._addr(name)
        offset = int(addr["offset"])
        raw = self._client.db_read(self.db_number, offset, 1)
        buf = bytearray(raw)
        set_bool(buf, 0, int(addr.get("bit", 0)), bool(value))
        self._client.db_write(self.db_number, offset, buf)

    def _calc_read_range(self, var_names: list) -> tuple[int, int]:
        min_off = float("inf")
        max_end = 0
        for name in var_names:
            if name in self.addr_map:
                addr = self.addr_map[name]
                off = int(addr["offset"])
                size = int(addr["bytes"])
                min_off = min(min_off, off)
                max_end = max(max_end, off + size)
        return int(min_off), int(max_end - min_off)

    # ================================================================
    #  B 方案写入：Python/SAC → PLC/PLCSIM
    # ================================================================

    def write_setpoints(self,
                        ec_set: float,
                        ph_set: float,
                        ec_actual: float,
                        ph_actual: float,
                        sac_enable: bool = True) -> bool:
        """写入 EC/pH 目标值与虚拟/真实传感器反馈。

        参数
        ----------
        ec_set, ph_set : float
            SAC 输出的上层目标值。
        ec_actual, ph_actual : float
            数字孪生或在线传感器反馈值，用作 PLC-PID 的 PV。
        sac_enable : bool
            SAC/远程模式使能位。
        """
        try:
            self._ensure_connected()
            self._heartbeat = (self._heartbeat + 1) % 32000

            self._write_real("EC_Set_SP", ec_set)
            self._write_real("pH_Set_SP", ph_set)
            self._write_real("EC_Actual", ec_actual)
            self._write_real("pH_Actual", ph_actual)
            if "SAC_Enable" in self.addr_map:
                self._write_bool("SAC_Enable", sac_enable)
            self._write_int("Remote_Heartbeat", self._heartbeat)

            logger.info(
                f"[PLC] 写入 → EC_set={ec_set:.3f}, pH_set={ph_set:.3f}, "
                f"EC_actual={ec_actual:.3f}, pH_actual={ph_actual:.3f}, Heartbeat={self._heartbeat}"
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

    def write_action(self, valve_f: float, valve_a: float) -> bool:
        """兼容旧 A 方案接口。

        新代码建议使用 write_setpoints()。如果配置仍保留 Valve_F_Opt_SP/Valve_A_Opt_SP，
        该函数可继续写入旧变量；否则返回 False。
        """
        if "Valve_F_Opt_SP" not in self.addr_map or "Valve_A_Opt_SP" not in self.addr_map:
            logger.error("当前 PLC 地址映射为 B 方案，write_action 已不适用，请使用 write_setpoints。")
            return False
        try:
            self._ensure_connected()
            self._heartbeat = (self._heartbeat + 1) % 32000
            self._write_real("Valve_F_Opt_SP", valve_f)
            self._write_real("Valve_A_Opt_SP", valve_a)
            self._write_int("Remote_Heartbeat", self._heartbeat)
            return True
        except Exception as e:
            logger.error(f"[PLC] write_action 异常: {e}")
            return False

    # ================================================================
    #  读取：PLC/PLCSIM → Python
    # ================================================================

    def read_state(self) -> dict:
        """从 PLC 回读执行层状态。"""
        preferred = [
            "Remote_Comms_OK", "Watchdog_Timer",
            "q_f_cmd", "q_a_cmd",
            "Valve_F_Actual", "Valve_A_Actual",
            "AQ_Valve_F_Raw", "AQ_Valve_A_Raw",
            "System_Alarm_Light",
        ]
        legacy = [
            "Remote_Comms_OK", "Watchdog_Timer",
            "Actual_Valve_F", "Actual_Valve_A",
            "AQ_Valve_F_Raw", "AQ_Valve_A_Raw",
            "System_Alarm_Light",
        ]
        read_vars = [name for name in preferred if name in self.addr_map]
        if "q_f_cmd" not in self.addr_map and "Actual_Valve_F" in self.addr_map:
            read_vars = [name for name in legacy if name in self.addr_map]

        try:
            self._ensure_connected()
            start_offset, total_size = self._calc_read_range(read_vars)
            raw = self._client.db_read(self.db_number, start_offset, total_size)
            state = {}
            for var_name in read_vars:
                addr = self.addr_map[var_name]
                rel_offset = int(addr["offset"]) - start_offset
                var_type = addr["type"]
                if var_type == "real":
                    state[var_name] = get_real(raw, rel_offset)
                elif var_type == "int":
                    state[var_name] = get_int(raw, rel_offset)
                elif var_type == "bool":
                    state[var_name] = get_bool(raw, rel_offset, int(addr.get("bit", 0)))
                else:
                    state[var_name] = None

            # 统一别名，便于 PLCGymEnv 使用
            if "q_f_cmd" not in state and "Actual_Valve_F" in state:
                state["q_f_cmd"] = state["Actual_Valve_F"]
            if "q_a_cmd" not in state and "Actual_Valve_A" in state:
                state["q_a_cmd"] = state["Actual_Valve_A"]
            if "Valve_F_Actual" not in state and "Actual_Valve_F" in state:
                state["Valve_F_Actual"] = state["Actual_Valve_F"]
            if "Valve_A_Actual" not in state and "Actual_Valve_A" in state:
                state["Valve_A_Actual"] = state["Actual_Valve_A"]

            logger.info(
                f"[PLC] 读取 ← CommOK={state.get('Remote_Comms_OK')}, "
                f"q_f={state.get('q_f_cmd', 0):.3f}, q_a={state.get('q_a_cmd', 0):.3f}"
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
        return self._connected
