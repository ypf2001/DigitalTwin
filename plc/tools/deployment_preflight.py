"""Deployment preflight checks for the digital twin PLC interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from plc_client import PLCClient


# 上位机每个控制周期必须写入的 DB1 变量。
REQUIRED_WRITE_TAGS = [
    "EC_Set_SP",
    "pH_Set_SP",
    "EC_Actual",
    "pH_Actual",
    "SAC_Enable",
    "Remote_Heartbeat",
]

# 上位机至少要读回这些变量，才能判断 PLC 是否接收命令、执行量是否正常。
REQUIRED_READ_TAGS = [
    "Remote_Comms_OK",
    "Watchdog_Timer",
    "Active_EC_SP",
    "Active_pH_SP",
    "q_f_cmd",
    "q_a_cmd",
    "System_Alarm_Light",
]

# PID 参数仍然暴露在 DB1，便于离线/在线调参和部署前检查。
REQUIRED_PID_TAGS = [
    "Kp_EC_Set",
    "Ki_EC_Set",
    "Kd_EC_Set",
    "Kp_pH_Set",
    "Ki_pH_Set",
    "Kd_pH_Set",
]

REQUIRED_FERTILIZER_CHANNEL_TAGS = [
    "N_Enable",
    "N_Ratio",
    "Kp_N_Set",
    "Ki_N_Set",
    "Kd_N_Set",
    "N_Max",
    "q_n_cmd",
    "P_Enable",
    "P_Ratio",
    "Kp_P_Set",
    "Ki_P_Set",
    "Kd_P_Set",
    "P_Max",
    "q_p_cmd",
    "K_Enable",
    "K_Ratio",
    "Kp_K_Set",
    "Ki_K_Set",
    "Kd_K_Set",
    "K_Max",
    "q_k_cmd",
]

REQUIRED_WATER_PUMP_TAGS = [
    "Water_Enable",
    "Qw_Set",
    "Qw_Actual",
    "Pressure_Set",
    "Pressure_Actual",
    "Water_Volume_SP",
    "Water_Volume_Actual",
    "Water_Pump_Run_CMD",
    "Water_Pump_Running",
    "Water_Pump_Fault",
    "Water_Flow_OK",
    "AQ_Water_Pump_Raw",
    "Water_Control_Mode",
    "Water_Pump_Reset",
    "Pre_Flush_Ratio",
    "Post_Flush_Ratio",
    "Pre_Flush_Volume",
    "Fertigation_End_Volume",
    "Water_Batch_Phase",
    "Batch_Fertigation_Active",
    "Water_Batch_Active",
]


def _check(condition: bool, ok: str, fail: str, errors: list[str]) -> None:
    if condition:
        print(f"[OK] {ok}")
    else:
        print(f"[FAIL] {fail}")
        errors.append(fail)


def _check_addresses(addr_map: dict, errors: list[str]) -> None:
    # 只检查通讯契约是否完整，不在这里判断每个 offset 的物理含义。
    required = (
        REQUIRED_WRITE_TAGS + REQUIRED_READ_TAGS + REQUIRED_PID_TAGS
        + REQUIRED_FERTILIZER_CHANNEL_TAGS + REQUIRED_WATER_PUMP_TAGS
    )
    for tag in required:
        _check(
            tag in addr_map,
            f"DB tag mapped: {tag}",
            f"Missing DB tag mapping: {tag}",
            errors,
        )

    for tag, spec in addr_map.items():
        if not isinstance(spec, dict):
            errors.append(f"Invalid address spec for {tag}")
            continue
        for field in ("offset", "type", "bytes"):
            if field not in spec:
                errors.append(f"Address {tag} missing field: {field}")


def _check_files(errors: list[str]) -> None:
    files = [
        ROOT / "plc" / "xiaweiji" / "src" / "xiaweiji.scl",
        ROOT / "plc_openness_v21" / "run_import_xiaweiji.ps1",
        ROOT / "experiments" / "run_plc_setpoint_step.py",
        ROOT / "config" / "deployment.yaml",
    ]
    for path in files:
        _check(path.exists(), f"Required file exists: {path}", f"Missing file: {path}", errors)


def _connect_plc(errors: list[str]) -> None:
    # 可选在线检查：用于确认 PLCSIM/真实 PLC 的 DB1 当前可读。
    plc = PLCClient()
    if not plc.connect():
        errors.append("PLC/PLCSIM connection failed.")
        return
    try:
        state = plc.read_state()
        _check(state is not None, "PLC state readable.", "PLC state read failed.", errors)
        if state:
            for tag in (
                "q_f_cmd", "q_a_cmd", "Active_EC_SP", "Active_pH_SP",
                "Qw_Actual", "Water_Pump_Run_CMD", "Water_Flow_OK",
            ):
                _check(tag in state, f"PLC readback contains {tag}", f"PLC readback missing {tag}", errors)
    finally:
        plc.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check deployment readiness for PLC interface.")
    parser.add_argument("--connect", action="store_true", help="Also connect to PLC/PLCSIM and read DB1.")
    args = parser.parse_args()

    errors: list[str] = []
    cfg = load_config()
    raw = cfg.raw()
    plc_cfg = cfg.plc()
    deployment_cfg = cfg.deployment()

    _check("plc" in raw, "plc config section exists.", "Missing plc config section.", errors)
    _check("deployment" in raw, "deployment config section exists.", "Missing deployment config section.", errors)
    _check(int(plc_cfg.get("db_number", -1)) == 1, "PLC DB number is DB1.", "PLC db_number is not 1.", errors)
    _check(bool(deployment_cfg), "deployment config loaded.", "deployment config is empty.", errors)

    _check_addresses(plc_cfg.get("addresses", {}), errors)
    _check_files(errors)

    if args.connect:
        _connect_plc(errors)

    if errors:
        print("\nPreflight failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("\nDeployment preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
