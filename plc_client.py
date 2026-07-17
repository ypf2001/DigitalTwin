"""
PLC 通讯客户端 — PLCClient
============================

B 方案通讯约定：
- Python/SAC 写入上层目标值 EC_Set_SP、pH_Set_SP，以及数字孪生/传感器反馈 EC_Actual、pH_Actual；
- PLC/PLCSIM 内部运行 EC-PID、pH-PID，输出 q_f_cmd、q_a_cmd 或阀门开度；
- Python 回读 PLC 执行结果，用于驱动数字孪生模型或记录半实物在环试验。
"""

import logging
import math
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
        self._heartbeat_initialized = False
        self._read_retrying = False

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

    def _read_real(self, name: str) -> float:
        addr = self._addr(name)
        raw = self._client.db_read(self.db_number, int(addr["offset"]), 4)
        return float(get_real(raw, 0))

    def _read_bool(self, name: str) -> bool:
        addr = self._addr(name)
        raw = self._client.db_read(self.db_number, int(addr["offset"]), 1)
        return bool(get_bool(raw, 0, int(addr.get("bit", 0))))

    def _advance_heartbeat(self) -> int:
        """Continue the PLC heartbeat across short-lived client processes."""
        if not getattr(self, "_heartbeat_initialized", True):
            try:
                addr = self._addr("Remote_Heartbeat")
                raw = self._client.db_read(self.db_number, int(addr["offset"]), 2)
                self._heartbeat = int(get_int(raw, 0))
            except Exception:
                # A missing/unsupported read falls back to the historical
                # zero-based behavior; the write still remains best effort.
                self._heartbeat = int(getattr(self, "_heartbeat", 0))
            self._heartbeat_initialized = True
        self._heartbeat = (int(self._heartbeat) + 1) % 32000
        return self._heartbeat

    @staticmethod
    def _control_float(section: dict, key: str, *, minimum: float = None,
                       maximum: float = None) -> float:
        """Read and validate one deployable control parameter."""
        try:
            value = float(section[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid control parameter: {key}") from exc
        if not math.isfinite(value):
            raise ValueError(f"non-finite control parameter: {key}")
        if minimum is not None and value < minimum:
            raise ValueError(f"control parameter below minimum: {key}")
        if maximum is not None and value > maximum:
            raise ValueError(f"control parameter above maximum: {key}")
        return value

    def write_control_parameters(self, parameters: dict, verify: bool = True) -> bool:
        """Write deployable DB1 parameters while keeping decoupling disabled.

        The caller must explicitly call set_decoupler_enabled(True) after PLC
        readback and commissioning checks. This method never enables the
        decoupler as part of a parameter update.
        """
        dec = parameters.get("decoupling", {})
        limits = parameters.get("limits", {})
        pid = parameters.get("pid", {})
        ec_pid = pid.get("ec", {})
        ph_pid = pid.get("ph", {})
        npk = parameters.get("npk")
        required = [
            "G_EC_F", "G_EC_A", "G_pH_F", "G_pH_A",
            "Decoupler_Weight", "Decoupler_Regularization",
            "Mixing_Delay_s", "Decoupler_Determinant_Min",
            "q_f_min", "q_f_max", "q_a_min", "q_a_max",
            "Decoupler_Enable",
        ]
        missing = [name for name in required if name not in self.addr_map]
        if missing:
            logger.error("[PLC] control parameter address mapping missing: %s", missing)
            return False

        try:
            values = {
                "G_EC_F": self._control_float(dec, "g_ec_f"),
                "G_EC_A": self._control_float(dec, "g_ec_a"),
                "G_pH_F": self._control_float(dec, "g_ph_f"),
                "G_pH_A": self._control_float(dec, "g_ph_a"),
                "Decoupler_Weight": self._control_float(dec, "weight", minimum=0.0, maximum=1.0),
                "Decoupler_Regularization": self._control_float(dec, "regularization", minimum=0.0),
                "Mixing_Delay_s": self._control_float(dec, "mixing_delay_s", minimum=0.0),
                "Decoupler_Determinant_Min": self._control_float(dec, "determinant_min", minimum=0.0),
                "q_f_min": self._control_float(limits, "q_f_min", minimum=0.0),
                "q_f_max": self._control_float(limits, "q_f_max", minimum=0.0),
                "q_a_min": self._control_float(limits, "q_a_min", minimum=0.0),
                "q_a_max": self._control_float(limits, "q_a_max", minimum=0.0),
            }
            if values["q_f_max"] <= values["q_f_min"]:
                raise ValueError("q_f_max must be greater than q_f_min")
            if values["q_a_max"] <= values["q_a_min"]:
                raise ValueError("q_a_max must be greater than q_a_min")
            pid_values = {
                "Kp_EC_Set": self._control_float(ec_pid, "kp", minimum=0.0),
                "Ki_EC_Set": self._control_float(ec_pid, "ki", minimum=0.0),
                "Kd_EC_Set": self._control_float(ec_pid, "kd", minimum=0.0),
                "Kp_pH_Set": self._control_float(ph_pid, "kp", minimum=0.0),
                "Ki_pH_Set": self._control_float(ph_pid, "ki", minimum=0.0),
                "Kd_pH_Set": self._control_float(ph_pid, "kd", minimum=0.0),
            }
            missing_pid = [name for name in pid_values if name not in self.addr_map]
            if missing_pid:
                raise ValueError(f"PID address mapping missing: {missing_pid}")
            npk_values = {}
            if npk is not None:
                npk_values = {
                    "N_Enable": 1.0 if bool(npk.get("n_enable", True)) else 0.0,
                    "N_Ratio": self._control_float(npk, "n_ratio", minimum=0.0),
                    "P_Enable": 1.0 if bool(npk.get("p_enable", True)) else 0.0,
                    "P_Ratio": self._control_float(npk, "p_ratio", minimum=0.0),
                    "K_Enable": 1.0 if bool(npk.get("k_enable", True)) else 0.0,
                    "K_Ratio": self._control_float(npk, "k_ratio", minimum=0.0),
                }
                missing_npk = [name for name in npk_values if name not in self.addr_map]
                if missing_npk:
                    raise ValueError(f"N/P/K address mapping missing: {missing_npk}")
        except ValueError as exc:
            logger.error("[PLC] invalid control parameters: %s", exc)
            return False

        try:
            self._ensure_connected()
            # Invalidate the runtime contract before changing any value.
            self._write_bool("Decoupler_Enable", False)
            for name, value in {**values, **pid_values, **npk_values}.items():
                self._write_real(name, value)

            if verify:
                readback = self.read_control_parameters()
                if readback is None:
                    logger.error("[PLC] control parameter readback failed")
                    return False
                expected = {**values, **pid_values, **npk_values}
                actual = readback["flat"]
                mismatched = [
                    name for name, value in expected.items()
                    if abs(float(actual[name]) - float(value)) > 1e-5
                ]
                if mismatched:
                    logger.error("[PLC] control parameter readback mismatch: %s", mismatched)
                    return False
            logger.info("[PLC] control parameters written; decoupler remains disabled")
            return True
        except Exception as exc:
            logger.error("[PLC] control parameter write failed: %s", exc)
            return False

    def read_control_parameters(self) -> dict | None:
        """Read the deployable DB1 control contract and diagnostics."""
        real_names = [
            "G_EC_F", "G_EC_A", "G_pH_F", "G_pH_A",
            "Decoupler_Weight", "Decoupler_Regularization",
            "Mixing_Delay_s", "Decoupler_Determinant_Min",
            "q_f_min", "q_f_max", "q_a_min", "q_a_max",
            "Kp_EC_Set", "Ki_EC_Set", "Kd_EC_Set",
            "Kp_pH_Set", "Ki_pH_Set", "Kd_pH_Set",
            "N_Enable", "N_Ratio", "P_Enable", "P_Ratio", "K_Enable", "K_Ratio",
            "Decoupler_Determinant", "Delta_q_f", "Delta_q_a",
        ]
        bool_names = ["Decoupler_Enable", "Decoupler_Valid"]
        missing = [name for name in [*real_names, *bool_names] if name not in self.addr_map]
        if missing:
            logger.error("[PLC] control parameter read mapping missing: %s", missing)
            return None
        try:
            self._ensure_connected()
            flat = {name: self._read_real(name) for name in real_names}
            flat.update({name: self._read_bool(name) for name in bool_names})
            return {"flat": flat}
        except Exception as exc:
            logger.error("[PLC] control parameter read failed: %s", exc)
            return None

    def set_decoupler_enabled(self, enabled: bool) -> bool:
        """Change the enable bit only after a valid PLC readback."""
        required = ["Decoupler_Enable", "Decoupler_Valid"]
        missing = [name for name in required if name not in self.addr_map]
        if missing:
            logger.error("[PLC] decoupler enable mapping missing: %s", missing)
            return False
        try:
            self._ensure_connected()
            if enabled and not self._read_bool("Decoupler_Valid"):
                logger.error("[PLC] decoupler rejected: PLC reports Decoupler_Valid=FALSE")
                return False
            self._write_bool("Decoupler_Enable", bool(enabled))
            return True
        except Exception as exc:
            logger.error("[PLC] decoupler enable write failed: %s", exc)
            return False

    def write_active_gain_matrix(self, point: dict, verify: bool = True) -> bool:
        """Write one validated local G matrix without enabling decoupling.

        ``point`` is one entry from the supervisory gain schedule.  The full
        schedule remains in Python; DB1 receives only the active four gains
        and optional process delay.  Enabling the PLC decoupler is a separate,
        explicitly guarded operation.
        """
        try:
            from plc_control.gain_schedule import gain_diagnostics

            diagnostics = gain_diagnostics(point)
            if not diagnostics["valid"]:
                logger.error("[PLC] rejected invalid active gain point: %s", diagnostics)
                return False
            gains = point.get("gains", point)
            values = {
                "G_EC_F": float(gains["g_ec_f"]),
                "G_EC_A": float(gains["g_ec_a"]),
                "G_pH_F": float(gains["g_ph_f"]),
                "G_pH_A": float(gains["g_ph_a"]),
            }
            if "Mixing_Delay_s" in self.addr_map and point.get("delay_s") is not None:
                values["Mixing_Delay_s"] = max(float(point["delay_s"]), 0.0)
            missing = [name for name in values if name not in self.addr_map]
            if missing:
                logger.error("[PLC] active gain address mapping missing: %s", missing)
                return False

            self._ensure_connected()
            # Invalidate the runtime contract before replacing the matrix.
            self._write_bool("Decoupler_Enable", False)
            for name, value in values.items():
                self._write_real(name, value)
            if not verify:
                return True
            readback = self.read_control_parameters()
            if readback is None:
                return False
            actual = readback["flat"]
            return all(abs(float(actual[name]) - value) <= 1e-5 for name, value in values.items())
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("[PLC] invalid active gain point: %s", exc)
            return False
        except Exception as exc:
            logger.error("[PLC] active gain write failed: %s", exc)
            return False

    def write_decoupler_weight(self, weight: float, verify: bool = True) -> bool:
        """Write the bounded A/B test weight without changing the enable bit."""
        try:
            value = float(weight)
            if not math.isfinite(value) or value < 0.0 or value > 1.0:
                raise ValueError("decoupler weight must be finite and within [0, 1]")
            self._ensure_connected()
            self._write_real("Decoupler_Weight", value)
            if verify:
                return abs(self._read_real("Decoupler_Weight") - value) <= 1e-5
            return True
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("[PLC] invalid decoupler weight: %s", exc)
            return False
        except Exception as exc:
            logger.error("[PLC] decoupler weight write failed: %s", exc)
            return False

    def write_growth_stage(self, stage: int) -> bool:
        """Write the simplified PLC growth stage if it is mapped in config.

        Stage values are 0=INI, 1=DEV, 2=MID, 3=LATE.
        """
        if "Growth_Stage" not in self.addr_map:
            return False
        try:
            self._ensure_connected()
            self._write_int("Growth_Stage", int(stage))
            return True
        except Exception as e:
            logger.error(f"[PLC] Growth_Stage write failed: {e}")
            return False

    def write_pid_params(self,
                         kp_ec: float,
                         ki_ec: float,
                         kd_ec: float,
                         kp_ph: float,
                         ki_ph: float,
                         kd_ph: float,
                         ec_trim_band: float = None,
                         ph_trim_band: float = None) -> bool:
        """Write PLC PID parameters stored in DB1.

        This lets Python coarse-tuning results replace the PLC gains without
        editing SCL, recompiling, or downloading again.
        """
        names = [
            "Kp_EC_Set", "Ki_EC_Set", "Kd_EC_Set",
            "Kp_pH_Set", "Ki_pH_Set", "Kd_pH_Set",
        ]
        if not all(name in self.addr_map for name in names):
            missing = [name for name in names if name not in self.addr_map]
            logger.error(f"[PLC] PID address mapping missing: {missing}")
            return False

        requested_trim_names = []
        if ec_trim_band is not None:
            requested_trim_names.append("EC_Trim_Band")
        if ph_trim_band is not None:
            requested_trim_names.append("pH_Trim_Band")
        missing_trim = [name for name in requested_trim_names if name not in self.addr_map]
        if missing_trim:
            logger.error(f"[PLC] fine-trim address mapping missing: {missing_trim}")
            return False

        try:
            self._ensure_connected()
            self._write_real("Kp_EC_Set", kp_ec)
            self._write_real("Ki_EC_Set", ki_ec)
            self._write_real("Kd_EC_Set", kd_ec)
            self._write_real("Kp_pH_Set", kp_ph)
            self._write_real("Ki_pH_Set", ki_ph)
            self._write_real("Kd_pH_Set", kd_ph)
            if ec_trim_band is not None:
                self._write_real("EC_Trim_Band", ec_trim_band)
            if ph_trim_band is not None:
                self._write_real("pH_Trim_Band", ph_trim_band)
            logger.info(
                "[PLC] PID params written: "
                f"EC=({kp_ec:.4f}, {ki_ec:.4f}, {kd_ec:.4f}), "
                f"pH=({kp_ph:.4f}, {ki_ph:.4f}, {kd_ph:.4f})"
            )
            if requested_trim_names:
                logger.info(
                    "[PLC] fine-trim bands written: EC=%s, pH=%s",
                    f"{ec_trim_band:.4f}" if ec_trim_band is not None else "unchanged",
                    f"{ph_trim_band:.4f}" if ph_trim_band is not None else "unchanged",
                )
            return True
        except Exception as e:
            logger.error(f"[PLC] PID params write failed: {e}")
            return False

    def write_fertilizer_channels(self, channels: dict[str, dict]) -> bool:
        """Write N/P/K fertilizer channel configuration into DB1.

        Expected channel keys are "N", "P", and "K". Each channel may contain:
        enable, ratio, target, actual, kp, ki, kd, max_flow.
        Missing values keep conservative defaults.
        """
        channel_tags = {
            "N": ("N_Enable", "N_Ratio", "N_Target", "N_Actual", "Kp_N_Set", "Ki_N_Set", "Kd_N_Set", "N_Max"),
            "P": ("P_Enable", "P_Ratio", "P_Target", "P_Actual", "Kp_P_Set", "Ki_P_Set", "Kd_P_Set", "P_Max"),
            "K": ("K_Enable", "K_Ratio", "K_Target", "K_Actual", "Kp_K_Set", "Ki_K_Set", "Kd_K_Set", "K_Max"),
        }
        required = [tag for tags in channel_tags.values() for tag in tags]
        missing = [name for name in required if name not in self.addr_map]
        if missing:
            logger.error(f"[PLC] fertilizer channel address mapping missing: {missing}")
            return False

        defaults = {
            "N": {"enable": 1.0, "ratio": 0.3333, "target": 0.0, "actual": 0.0, "kp": 0.25, "ki": 0.01, "kd": 0.0, "max_flow": 4.0},
            "P": {"enable": 1.0, "ratio": 0.3333, "target": 0.0, "actual": 0.0, "kp": 0.12, "ki": 0.006, "kd": 0.0, "max_flow": 4.0},
            "K": {"enable": 1.0, "ratio": 0.3334, "target": 0.0, "actual": 0.0, "kp": 0.25, "ki": 0.008, "kd": 0.0, "max_flow": 4.0},
        }

        try:
            self._ensure_connected()
            for key, tags in channel_tags.items():
                cfg = {**defaults[key], **channels.get(key, {})}
                values = [
                    1.0 if bool(cfg.get("enable", True)) else 0.0,
                    float(cfg.get("ratio", defaults[key]["ratio"])),
                    float(cfg.get("target", 0.0)),
                    float(cfg.get("actual", 0.0)),
                    float(cfg.get("kp", 0.0)),
                    float(cfg.get("ki", 0.0)),
                    float(cfg.get("kd", 0.0)),
                    float(cfg.get("max_flow", 4.0)),
                ]
                for tag, value in zip(tags, values):
                    self._write_real(tag, value)
            logger.info("[PLC] fertilizer channel config written: %s", channels)
            return True
        except Exception as e:
            logger.error(f"[PLC] fertilizer channel config write failed: {e}")
            return False

    def write_water_command(self,
                             enabled: bool,
                             q_w_set: float,
                             pressure_set: float,
                             volume_set: float = 0.0,
                             control_mode: int = 0,
                             pre_flush_ratio: float | None = None,
                             post_flush_ratio: float | None = None,
                             reset_volume: bool = False) -> bool:
        """Write the slow main-pump command. Mode 0=flow, 1=pressure."""
        names = [
            "Water_Enable", "Qw_Set", "Pressure_Set",
            "Water_Volume_SP", "Water_Control_Mode",
        ]
        if not all(name in self.addr_map for name in names):
            return False
        try:
            self._ensure_connected()
            self._write_real("Water_Enable", 1.0 if enabled else 0.0)
            self._write_real("Qw_Set", q_w_set)
            self._write_real("Pressure_Set", pressure_set)
            self._write_real("Water_Volume_SP", max(float(volume_set), 0.0))
            self._write_int("Water_Control_Mode", int(control_mode))
            if pre_flush_ratio is not None and "Pre_Flush_Ratio" in self.addr_map:
                self._write_real("Pre_Flush_Ratio", min(max(float(pre_flush_ratio), 0.0), 1.0))
            if post_flush_ratio is not None and "Post_Flush_Ratio" in self.addr_map:
                self._write_real("Post_Flush_Ratio", min(max(float(post_flush_ratio), 0.0), 1.0))
            if "Water_Pump_Reset" in self.addr_map:
                self._write_bool("Water_Pump_Reset", bool(reset_volume))
            return True
        except Exception as e:
            logger.error(f"[PLC] water-pump command write failed: {e}")
            return False

    def write_water_feedback(self,
                             q_w_actual: float,
                             pressure_actual: float,
                             speed_actual: float,
                             running: bool) -> bool:
        """Write simulated pump feedback during PLCSIM/HIL operation."""
        names = [
            "Qw_Actual", "Pressure_Actual", "Water_Pump_Speed_Actual",
            "Water_Pump_Run_Feedback", "Water_Pump_Drive_Ready",
            "Water_Pump_Drive_Fault", "Water_Source_Low_Level",
        ]
        if not all(name in self.addr_map for name in names):
            return False
        try:
            self._ensure_connected()
            self._write_real("Qw_Actual", q_w_actual)
            self._write_real("Pressure_Actual", pressure_actual)
            self._write_real("Water_Pump_Speed_Actual", speed_actual)
            self._write_bool("Water_Pump_Run_Feedback", running)
            self._write_bool("Water_Pump_Drive_Ready", True)
            self._write_bool("Water_Pump_Drive_Fault", False)
            self._write_bool("Water_Source_Low_Level", False)
            return True
        except Exception as e:
            logger.error(f"[PLC] water-pump feedback write failed: {e}")
            return False

    def write_fertilizer_feedback(self,
                                  n_target: float,
                                  p_target: float,
                                  k_target: float,
                                  n_actual: float,
                                  p_actual: float,
                                  k_actual: float,
                                  feedback_valid: bool = True) -> bool:
        """Write N/P/K targets and feedback, then atomically expose validity to PLC logic."""
        names = [
            "N_Target", "P_Target", "K_Target",
            "N_Actual", "P_Actual", "K_Actual",
            "NPK_Feedback_Valid",
        ]
        missing = [name for name in names if name not in self.addr_map]
        if missing:
            logger.error(f"[PLC] fertilizer feedback address mapping missing: {missing}")
            return False
        try:
            self._ensure_connected()
            # Invalidate first so a partially written feedback frame is never consumed.
            self._write_bool("NPK_Feedback_Valid", False)
            self._write_real("N_Target", n_target)
            self._write_real("P_Target", p_target)
            self._write_real("K_Target", k_target)
            self._write_real("N_Actual", n_actual)
            self._write_real("P_Actual", p_actual)
            self._write_real("K_Actual", k_actual)
            self._write_bool("NPK_Feedback_Valid", bool(feedback_valid))
            return True
        except Exception as e:
            logger.error(f"[PLC] fertilizer feedback write failed: {e}")
            return False

    def write_fertilizer_actuals(self, n_actual: float, p_actual: float, k_actual: float) -> bool:
        """Backward-compatible actual-only update; it does not enable N/P/K closed loop."""
        return self.write_fertilizer_feedback(
            0.0, 0.0, 0.0, n_actual, p_actual, k_actual, feedback_valid=False
        )

    def write_compressed_hil_mode(self, enabled: bool) -> bool:
        """Enable shortened PLC feedforward hold for compressed PLCSIM tests only."""
        if "Compressed_HIL_Enable" not in self.addr_map:
            logger.error("[PLC] Compressed_HIL_Enable address mapping missing")
            return False
        try:
            self._ensure_connected()
            self._write_bool("Compressed_HIL_Enable", bool(enabled))
            return True
        except Exception as e:
            logger.error(f"[PLC] compressed HIL mode write failed: {e}")
            return False

    def write_fixed_pid_test_mode(self, enabled: bool) -> bool:
        """Select fixed base gains for controlled PLC A/B tests only."""
        if "Fixed_PID_Test_Enable" not in self.addr_map:
            logger.error("[PLC] Fixed_PID_Test_Enable address mapping missing")
            return False
        try:
            self._ensure_connected()
            self._write_bool("Fixed_PID_Test_Enable", bool(enabled))
            return True
        except Exception as e:
            logger.error(f"[PLC] fixed PID test mode write failed: {e}")
            return False
    def write_manual_mode(self,
                          enabled: bool,
                          q_f: float = 0.0,
                          q_a: float = 0.0,
                          q_n: float = 0.0,
                          q_p: float = 0.0,
                          q_k: float = 0.0) -> bool:
        """Enable local PLC manual mode and write direct flow setpoints.

        Manual mode is intended for bench commissioning. The PLC still applies
        hard limits and analog output scaling before writing q_*_cmd.
        """
        names = [
            "Manual_Mode",
            "Manual_q_f_Set", "Manual_q_a_Set",
            "Manual_q_n_Set", "Manual_q_p_Set", "Manual_q_k_Set",
        ]
        missing = [name for name in names if name not in self.addr_map]
        if missing:
            logger.error(f"[PLC] manual mode address mapping missing: {missing}")
            return False
        try:
            self._ensure_connected()
            self._write_real("Manual_q_f_Set", q_f)
            self._write_real("Manual_q_a_Set", q_a)
            self._write_real("Manual_q_n_Set", q_n)
            self._write_real("Manual_q_p_Set", q_p)
            self._write_real("Manual_q_k_Set", q_k)
            self._write_bool("Manual_Mode", enabled)
            if "Auto_Mode" in self.addr_map:
                self._write_bool("Auto_Mode", not enabled)
            logger.info(
                "[PLC] manual mode %s: q_f=%.3f q_a=%.3f q_n=%.3f q_p=%.3f q_k=%.3f",
                "enabled" if enabled else "disabled",
                q_f, q_a, q_n, q_p, q_k,
            )
            return True
        except Exception as e:
            logger.error(f"[PLC] manual mode write failed: {e}")
            return False

    def write_manual_flow(self, q_f: float, q_a: float,
                          q_n: float = 0.0, q_p: float = 0.0,
                          q_k: float = 0.0) -> bool:
        """Update manual flow values without rewriting the mode selector bits."""
        names = [
            "Manual_q_f_Set", "Manual_q_a_Set", "Manual_q_n_Set",
            "Manual_q_p_Set", "Manual_q_k_Set",
        ]
        missing = [name for name in names if name not in self.addr_map]
        if missing:
            logger.error("[PLC] manual flow address mapping missing: %s", missing)
            return False
        try:
            self._ensure_connected()
            for name, value in zip(names, (q_f, q_a, q_n, q_p, q_k)):
                self._write_real(name, value)
            return True
        except Exception as e:
            logger.error(f"[PLC] manual flow write failed: {e}")
            return False

    def write_gain_experiment_frame(self, ec_actual: float, ph_actual: float,
                                    q_f: float, q_a: float) -> bool:
        """Write one compact PLCSIM identification frame with two DB writes."""
        required = [
            "Manual_q_f_Set", "Manual_q_k_Set", "EC_Actual", "pH_Actual",
            "SAC_Enable", "Remote_Heartbeat",
        ]
        if any(name not in self.addr_map for name in required):
            return False
        try:
            self._ensure_connected()
            flow_start = int(self.addr_map["Manual_q_f_Set"]["offset"])
            flow_end = int(self.addr_map["Manual_q_k_Set"]["offset"]) + 4
            flow_buf = bytearray(flow_end - flow_start)
            for index, value in enumerate((q_f, q_a, 0.0, 0.0, 0.0)):
                set_real(flow_buf, index * 4, float(value))
            self._client.db_write(self.db_number, flow_start, flow_buf)

            self._advance_heartbeat()
            feedback_start = int(self.addr_map["EC_Actual"]["offset"])
            heartbeat_end = int(self.addr_map["Remote_Heartbeat"]["offset"]) + 2
            feedback_buf = bytearray(heartbeat_end - feedback_start)
            set_real(feedback_buf, int(self.addr_map["EC_Actual"]["offset"]) - feedback_start, ec_actual)
            set_real(feedback_buf, int(self.addr_map["pH_Actual"]["offset"]) - feedback_start, ph_actual)
            sac_addr = self.addr_map["SAC_Enable"]
            set_bool(feedback_buf, int(sac_addr["offset"]) - feedback_start,
                     int(sac_addr.get("bit", 0)), False)
            set_int(feedback_buf, int(self.addr_map["Remote_Heartbeat"]["offset"]) - feedback_start,
                    self._heartbeat)
            self._client.db_write(self.db_number, feedback_start, feedback_buf)
            return True
        except Exception as e:
            logger.error(f"[PLC] compact experiment frame write failed: {e}")
            return False

    def read_gain_experiment_state(self) -> dict:
        """Read only the compact DB1 fields needed by the identification loop."""
        try:
            self._ensure_connected()
            state = {}
            feedback_start = int(self.addr_map["Remote_Comms_OK"]["offset"])
            feedback_end = int(self.addr_map["q_a_cmd"]["offset"]) + 4
            raw = self._client.db_read(self.db_number, feedback_start, feedback_end - feedback_start)
            for name in ("Remote_Comms_OK", "Watchdog_Timer", "q_f_cmd", "q_a_cmd"):
                addr = self.addr_map[name]
                rel = int(addr["offset"]) - feedback_start
                if addr["type"] == "bool":
                    state[name] = bool(get_bool(raw, rel, int(addr.get("bit", 0))))
                elif addr["type"] == "int":
                    state[name] = int(get_int(raw, rel))
                else:
                    state[name] = float(get_real(raw, rel))
            for name in ("System_Alarm_Light", "Manual_Active", "Water_Flow_OK",
                         "Decoupler_Enable", "Decoupler_Valid", "q_f_limited", "q_a_limited"):
                addr = self.addr_map[name]
                raw_one = self._client.db_read(self.db_number, int(addr["offset"]), 1)
                state[name] = bool(get_bool(raw_one, 0, int(addr.get("bit", 0))))
            return state
        except Exception as e:
            logger.error(f"[PLC] compact experiment state read failed: {e}")
            return {}

    def write_standby(self) -> bool:
        """Return the PLC to a non-running standby mode after commissioning."""
        names = [name for name in ("Manual_Mode", "Auto_Mode") if name in self.addr_map]
        if len(names) < 2:
            logger.error("[PLC] standby mode requires Manual_Mode and Auto_Mode mappings")
            return False
        try:
            self._ensure_connected()
            self._write_bool("Manual_Mode", False)
            self._write_bool("Auto_Mode", False)
            if "SAC_Enable" in self.addr_map:
                self._write_bool("SAC_Enable", False)
            logger.info("[PLC] standby mode requested")
            return True
        except Exception as e:
            logger.error(f"[PLC] standby mode write failed: {e}")
            return False

    def write_remote_auto_mode(self) -> bool:
        """Select remote automatic mode without changing setpoints."""
        names = [name for name in ("Manual_Mode", "Auto_Mode") if name in self.addr_map]
        if len(names) != 2:
            logger.error("[PLC] remote automatic mode mappings are incomplete")
            return False
        try:
            self._ensure_connected()
            self._write_bool("Manual_Mode", False)
            self._write_bool("Auto_Mode", True)
            return True
        except Exception as exc:
            logger.error("[PLC] remote automatic mode write failed: %s", exc)
            return False

    def write_system_alarm_reset(self, enabled: bool) -> bool:
        """Pulse the DB1 alarm acknowledge bit during commissioning."""
        if "System_Alarm_Reset" not in self.addr_map:
            logger.error("[PLC] System_Alarm_Reset address mapping missing")
            return False
        try:
            self._ensure_connected()
            self._write_bool("System_Alarm_Reset", bool(enabled))
            return True
        except Exception as e:
            logger.error(f"[PLC] system alarm reset write failed: {e}")
            return False

    def write_emergency_stop(self, enabled: bool = True) -> bool:
        """Set or clear the PLC emergency stop flag in DB1."""
        if "Emergency_Stop" not in self.addr_map:
            logger.error("[PLC] Emergency_Stop address mapping missing")
            return False
        try:
            self._ensure_connected()
            self._write_bool("Emergency_Stop", enabled)
            logger.warning("[PLC] Emergency_Stop=%s", enabled)
            return True
        except Exception as e:
            logger.error(f"[PLC] Emergency_Stop write failed: {e}")
            return False

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
            self._write_real("EC_Set_SP", ec_set)
            self._write_real("pH_Set_SP", ph_set)
        except (OSError, ConnectionError, AttributeError) as e:
            logger.error(f"[PLC] 写入失败 (网络断开): {e}")
            self._connected = False
            self.reconnect()
            return False
        except Exception as e:
            logger.error(f"[PLC] 写入异常: {e}")
            return False

        return self.write_feedback(
            ec_actual=ec_actual,
            ph_actual=ph_actual,
            sac_enable=sac_enable,
        )

    def write_feedback(self,
                       ec_actual: float,
                       ph_actual: float,
                       sac_enable: bool) -> bool:
        """Write feedback and heartbeat without changing automatic targets.

        Local manual mode uses this path so the supervisory system keeps
        monitoring the process without overwriting EC_Set_SP or pH_Set_SP.
        """
        try:
            self._ensure_connected()
            self._advance_heartbeat()

            # Remove remote automatic authority first when manual is active.
            if "SAC_Enable" in self.addr_map:
                self._write_bool("SAC_Enable", sac_enable)
            self._write_real("EC_Actual", ec_actual)
            self._write_real("pH_Actual", ph_actual)
            self._write_int("Remote_Heartbeat", self._heartbeat)

            logger.info(
                "[PLC] feedback: EC_actual=%.3f, pH_actual=%.3f, "
                "SAC_Enable=%s, Heartbeat=%d",
                ec_actual,
                ph_actual,
                sac_enable,
                self._heartbeat,
            )
            return True
        except (OSError, ConnectionError, AttributeError) as e:
            logger.error(f"[PLC] feedback write failed (connection lost): {e}")
            self._connected = False
            self.reconnect()
            return False
        except Exception as e:
            logger.error(f"[PLC] feedback write failed: {e}")
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
            self._advance_heartbeat()
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

    def read_control_mode(self) -> dict | None:
        """Read only the mode interlock bits needed by the control loop."""
        names = ["Manual_Mode", "Auto_Mode", "Manual_Active", "Auto_Active"]
        read_vars = [name for name in names if name in self.addr_map]
        if not read_vars:
            return {}

        try:
            self._ensure_connected()
            start_offset, total_size = self._calc_read_range(read_vars)
            raw = self._client.db_read(self.db_number, start_offset, total_size)
            state = {}
            for name in read_vars:
                addr = self.addr_map[name]
                state[name] = get_bool(
                    raw,
                    int(addr["offset"]) - start_offset,
                    int(addr.get("bit", 0)),
                )
            return state
        except (OSError, ConnectionError, AttributeError) as e:
            logger.error(f"[PLC] mode read failed (connection lost): {e}")
            self._connected = False
            self.reconnect()
            return None
        except Exception as e:
            logger.error(f"[PLC] mode read failed: {e}")
            return None

    def read_state(self) -> dict:
        """从 PLC 回读执行层状态。"""
        preferred = [
            "Remote_Comms_OK", "Watchdog_Timer",
            "EC_Set_SP", "pH_Set_SP", "EC_Actual", "pH_Actual",
            "SAC_Enable", "Remote_Heartbeat",
            "Growth_Stage",
            "Stage_EC_SP", "Stage_pH_SP",
            "Active_EC_SP", "Active_pH_SP",
            "Setpoint_Protection_Active", "Stage_Auto_SP_Enable",
            "Kp_EC_Set", "Ki_EC_Set", "Kd_EC_Set",
            "Kp_pH_Set", "Ki_pH_Set", "Kd_pH_Set",
            "Kp_EC_Effective", "Ki_EC_Effective", "Kd_EC_Effective",
            "Kp_pH_Effective", "Ki_pH_Effective", "Kd_pH_Effective",
            "EC_PID_Error", "pH_PID_Error", "EC_PID_Integral", "pH_PID_Integral",
            "q_f_Feedforward", "q_f_PID_Correction", "q_f_raw", "q_f_limited",
            "q_a_Feedforward", "q_a_PID_Correction", "q_a_raw", "q_a_limited",
            "N_Error", "P_Error", "K_Error",
            "N_PID_Correction", "P_PID_Correction", "K_PID_Correction",
            "NPK_Optimization_Weight", "NPK_Feedback_Valid", "NPK_Capacity_Limited",
            "Compressed_HIL_Enable", "Feedforward_Hold_Active", "Adaptive_PID_Active",
            "Fixed_PID_Test_Enable",
            "G_EC_F", "G_EC_A", "G_pH_F", "G_pH_A",
            "Decoupler_Weight", "Decoupler_Regularization", "Mixing_Delay_s",
            "Decoupler_Determinant_Min", "q_f_min", "q_f_max", "q_a_min", "q_a_max",
            "Decoupler_Enable", "Decoupler_Valid", "Decoupler_Determinant",
            "Delta_q_f", "Delta_q_a",
            "Water_Enable", "Qw_Set", "Qw_Actual",
            "Pressure_Set", "Pressure_Actual",
            "Water_Volume_SP", "Water_Volume_Actual",
            "Water_Pump_Speed_CMD", "Water_Pump_Speed_Actual",
            "Water_Pump_Run_CMD", "Water_Pump_Running", "Water_Pump_Ready",
            "Water_Pump_Fault", "Water_Flow_OK", "Water_Volume_Complete",
            "AQ_Water_Pump_Raw", "Water_Control_Mode", "Water_Pump_Alarm",
            "Water_Pump_Run_Feedback", "Water_Pump_Drive_Ready",
            "Water_Pump_Drive_Fault", "Water_Source_Low_Level", "Water_Pump_Reset",
            "Pre_Flush_Ratio", "Post_Flush_Ratio",
            "Pre_Flush_Volume", "Fertigation_End_Volume",
            "Water_Batch_Phase", "Batch_Fertigation_Active", "Water_Batch_Active",
            "Manual_Mode", "Auto_Mode", "Emergency_Stop", "Manual_Active", "Auto_Active",
            "Comm_Normal", "Manual_PumpValve_Enable",
            "Actuator_Execution_Enable", "Actuator_Any_Alarm", "Actuator_Any_Trip",
            "Manual_q_f_Set", "Manual_q_a_Set",
            "Manual_q_f_Selected", "Manual_q_a_Selected",
            "Manual_q_n_Set", "Manual_q_p_Set", "Manual_q_k_Set",
            "N_Enable", "N_Ratio", "N_Target", "N_Actual", "Kp_N_Set", "Ki_N_Set", "Kd_N_Set", "N_Max",
            "P_Enable", "P_Ratio", "P_Target", "P_Actual", "Kp_P_Set", "Ki_P_Set", "Kd_P_Set", "P_Max",
            "K_Enable", "K_Ratio", "K_Target", "K_Actual", "Kp_K_Set", "Ki_K_Set", "Kd_K_Set", "K_Max",
            "q_f_cmd", "q_a_cmd",
            "q_n_cmd", "q_p_cmd", "q_k_cmd",
            "Valve_F_Actual", "Valve_A_Actual",
            "AQ_Valve_F_Raw", "AQ_Valve_A_Raw",
            "AQ_Valve_N_Raw", "AQ_Valve_P_Raw", "AQ_Valve_K_Raw",
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

        # Keep older PLCSIM DB1 schemas observable while updated SCL is being
        # compiled and downloaded. The adaptive schema ends at byte 396 and the
        # optional water-pump extension begins at byte 400.
        adaptive_schema_vars = [
            name for name in read_vars
            if int(self.addr_map[name]["offset"]) + int(self.addr_map[name]["bytes"]) <= 397
        ]
        legacy_schema_vars = [
            name for name in read_vars
            if int(self.addr_map[name]["offset"]) + int(self.addr_map[name]["bytes"]) <= 312
        ]

        def decode(var_names: list[str], raw: bytearray, start_offset: int) -> dict:
            decoded = {}
            for var_name in var_names:
                addr = self.addr_map[var_name]
                rel_offset = int(addr["offset"]) - start_offset
                var_type = addr["type"]
                if var_type == "real":
                    decoded[var_name] = get_real(raw, rel_offset)
                elif var_type == "int":
                    decoded[var_name] = get_int(raw, rel_offset)
                elif var_type == "bool":
                    decoded[var_name] = get_bool(raw, rel_offset, int(addr.get("bit", 0)))
                else:
                    decoded[var_name] = None
            return decoded

        def add_aliases(state: dict) -> dict:
            if "q_f_cmd" not in state and "Actual_Valve_F" in state:
                state["q_f_cmd"] = state["Actual_Valve_F"]
            if "q_a_cmd" not in state and "Actual_Valve_A" in state:
                state["q_a_cmd"] = state["Actual_Valve_A"]
            if "Valve_F_Actual" not in state and "Actual_Valve_F" in state:
                state["Valve_F_Actual"] = state["Actual_Valve_F"]
            if "Valve_A_Actual" not in state and "Actual_Valve_A" in state:
                state["Valve_A_Actual"] = state["Actual_Valve_A"]
            return state

        try:
            self._ensure_connected()
            start_offset, total_size = self._calc_read_range(read_vars)
            try:
                raw = self._client.db_read(self.db_number, start_offset, total_size)
                state = decode(read_vars, raw, start_offset)
                state["adaptive_schema_available"] = all(
                    name in state
                    for name in ("Kp_EC_Effective", "Kp_pH_Effective", "Adaptive_PID_Active")
                )
            except Exception as full_read_error:
                if adaptive_schema_vars and adaptive_schema_vars != read_vars:
                    try:
                        adaptive_start, adaptive_size = self._calc_read_range(adaptive_schema_vars)
                        raw = self._client.db_read(self.db_number, adaptive_start, adaptive_size)
                        state = decode(adaptive_schema_vars, raw, adaptive_start)
                        state["adaptive_schema_available"] = all(
                            name in state
                            for name in ("Kp_EC_Effective", "Kp_pH_Effective", "Adaptive_PID_Active")
                        )
                        state["water_schema_available"] = False
                    except Exception:
                        state = None
                else:
                    state = None

                if state is None:
                    if not legacy_schema_vars or legacy_schema_vars == read_vars:
                        raise
                    fallback_start, fallback_size = self._calc_read_range(legacy_schema_vars)
                    logger.warning(
                        "[PLC] extended DB1 fields unavailable; using legacy schema read: %s",
                        full_read_error,
                    )
                    raw = self._client.db_read(self.db_number, fallback_start, fallback_size)
                    state = decode(legacy_schema_vars, raw, fallback_start)
                    state["adaptive_schema_available"] = False

            state.setdefault("water_schema_available", all(
                name in state
                for name in ("Qw_Set", "Qw_Actual", "Water_Pump_Run_CMD", "Water_Flow_OK")
            ))
            state["water_batch_schema_available"] = all(
                name in state
                for name in (
                    "Pre_Flush_Ratio", "Post_Flush_Ratio", "Water_Batch_Phase",
                    "Batch_Fertigation_Active",
                )
            )

            state = add_aliases(state)

            # The adaptive DB1 snapshot is larger than the negotiated 240-byte
            # PDU, so snap7 may split one logical db_read across PLC scans. At a
            # stage transition that can pair an old q_f_cmd with new N/P/K flows.
            # Re-read only the fertilizer budget with q_f bracketing the compact
            # N/P/K range; accept it only when q_f is stable across both reads.
            budget_names = ("q_f_cmd", "q_n_cmd", "q_p_cmd", "q_k_cmd")
            if all(name in state and name in self.addr_map for name in budget_names):
                budget_error = (
                    float(state["q_n_cmd"]) + float(state["q_p_cmd"])
                    + float(state["q_k_cmd"]) - float(state["q_f_cmd"])
                )
                if not state.get("NPK_Capacity_Limited", False) and abs(budget_error) > 0.001:
                    q_f_addr = self.addr_map["q_f_cmd"]
                    npk_names = ("q_n_cmd", "q_p_cmd", "q_k_cmd")
                    npk_start, npk_size = self._calc_read_range(list(npk_names))
                    for _ in range(3):
                        q_f_before = get_real(
                            self._client.db_read(
                                self.db_number, int(q_f_addr["offset"]), int(q_f_addr["bytes"])
                            ),
                            0,
                        )
                        npk_raw = self._client.db_read(self.db_number, npk_start, npk_size)
                        npk_values = {
                            name: get_real(
                                npk_raw, int(self.addr_map[name]["offset"]) - npk_start
                            )
                            for name in npk_names
                        }
                        q_f_after = get_real(
                            self._client.db_read(
                                self.db_number, int(q_f_addr["offset"]), int(q_f_addr["bytes"])
                            ),
                            0,
                        )
                        if abs(q_f_after - q_f_before) <= 1e-5:
                            candidate_error = sum(npk_values.values()) - q_f_after
                            if abs(candidate_error) < abs(budget_error):
                                state["q_f_cmd"] = q_f_after
                                state.update(npk_values)
                                budget_error = candidate_error
                            if abs(candidate_error) <= 0.001:
                                break

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
            message = str(e).lower()
            connection_fault = any(
                marker in message
                for marker in ("not connected", "receive timeout", "connection reset", "iso :")
            )
            if connection_fault:
                logger.warning(f"[PLC] 读取通信异常，立即重连并重试一次: {e}")
                self._connected = False
                if self.reconnect() and not self._read_retrying:
                    self._read_retrying = True
                    try:
                        return self.read_state()
                    finally:
                        self._read_retrying = False
            logger.error(f"[PLC] 读取异常: {e}")
            return None

    @property
    def is_connected(self) -> bool:
        return self._connected
