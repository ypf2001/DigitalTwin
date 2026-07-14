from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plc_client import PLCClient


REMOTE_TARGET = (1.35, 5.95)
MANUAL_TARGET = (1.40, 6.05)
MID_STAGE_TARGET = (1.50, 5.90)
FEEDBACK = (0.95, 6.20)


def close(a: float, b: float, tolerance: float = 0.015) -> bool:
    return math.isclose(float(a), float(b), abs_tol=tolerance)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def compact(state: dict) -> dict:
    names = (
        "Manual_Mode", "Auto_Mode", "Manual_Active", "Auto_Active",
        "SAC_Enable", "Remote_Comms_OK", "Stage_Auto_SP_Enable",
        "EC_Set_SP", "pH_Set_SP", "Active_EC_SP", "Active_pH_SP",
        "Setpoint_Protection_Active",
        "EC_PID_Error", "pH_PID_Error", "q_f_PID_Correction",
        "q_a_PID_Correction", "q_f_cmd", "q_a_cmd",
        "Adaptive_PID_Active", "Fixed_PID_Test_Enable",
        "Kp_EC_Effective", "Ki_EC_Effective", "Kd_EC_Effective",
        "Kp_pH_Effective", "Ki_pH_Effective", "Kd_pH_Effective",
    )
    return {name: state.get(name) for name in names}


def feedback_cycles(plc: PLCClient, count: int, *, sac_enable: bool) -> dict:
    state: dict = {}
    for _ in range(count):
        check(
            plc.write_feedback(FEEDBACK[0], FEEDBACK[1], sac_enable=sac_enable),
            "feedback write failed",
        )
        time.sleep(0.35)
        state = plc.read_state() or {}
    return state


def remote_cycles(plc: PLCClient, count: int) -> dict:
    state: dict = {}
    for _ in range(count):
        check(
            plc.write_setpoints(
                REMOTE_TARGET[0], REMOTE_TARGET[1],
                FEEDBACK[0], FEEDBACK[1], sac_enable=True,
            ),
            "remote setpoint write failed",
        )
        time.sleep(0.35)
        state = plc.read_state() or {}
    return state


def check_pid_execution(state: dict, label: str) -> None:
    check(bool(state.get("Adaptive_PID_Active")), f"{label}: adaptive PID is not active")
    check(not bool(state.get("Fixed_PID_Test_Enable")), f"{label}: fixed PID test flag is active")
    check(
        abs(float(state.get("EC_PID_Error", 0.0))) > 0.005
        or abs(float(state.get("pH_PID_Error", 0.0))) > 0.005,
        f"{label}: PID error did not respond",
    )
    check(
        abs(float(state.get("q_f_PID_Correction", 0.0))) > 0.0001
        or abs(float(state.get("q_a_PID_Correction", 0.0))) > 0.0001,
        f"{label}: PID correction did not respond",
    )
    check(
        abs(float(state.get("q_f_cmd", 0.0))) > 0.001
        or abs(float(state.get("q_a_cmd", 0.0))) > 0.001,
        f"{label}: final PLC outputs did not respond",
    )


def main() -> int:
    plc = PLCClient(cycle_s=0.35)
    if not plc.connect():
        return 2

    report: dict[str, dict] = {}
    try:
        check(plc.write_emergency_stop(False), "failed to clear Emergency_Stop")
        check(plc.write_fixed_pid_test_mode(False), "failed to select adaptive PID")

        # 自动联网：上位机写 EC/pH 目标，PLC 自适应 PID 执行。
        check(plc.write_manual_mode(False), "failed to select automatic mode")
        remote = remote_cycles(plc, 6)
        check(bool(remote.get("Remote_Comms_OK")), "remote auto: communications not healthy")
        check(bool(remote.get("Auto_Active")), "remote auto: Auto_Active is false")
        check(not bool(remote.get("Manual_Active")), "remote auto: Manual_Active is true")
        check(bool(remote.get("SAC_Enable")), "remote auto: SAC_Enable is false")
        check(close(remote.get("EC_Set_SP", 0.0), REMOTE_TARGET[0]), "remote auto: EC target mismatch")
        check(close(remote.get("pH_Set_SP", 0.0), REMOTE_TARGET[1]), "remote auto: pH target mismatch")
        check(close(remote.get("Active_EC_SP", 0.0), REMOTE_TARGET[0]), "remote auto: active EC target mismatch")
        check(close(remote.get("Active_pH_SP", 0.0), REMOTE_TARGET[1]), "remote auto: active pH target mismatch")
        check(not bool(remote.get("Setpoint_Protection_Active")), "remote auto: target protection unexpectedly active")
        check_pid_execution(remote, "remote auto")
        report["automatic_online"] = compact(remote)

        # 自动本地：关闭远程目标权限，PLC 按 MID 生长阶段生成目标并执行 PID。
        check(plc.write_growth_stage(2), "local auto: failed to select MID stage")
        local = feedback_cycles(plc, 6, sac_enable=False)
        check(bool(local.get("Auto_Active")), "local auto: Auto_Active is false")
        check(not bool(local.get("Manual_Active")), "local auto: Manual_Active is true")
        check(not bool(local.get("SAC_Enable")), "local auto: SAC_Enable is true")
        check(bool(local.get("Stage_Auto_SP_Enable")), "local auto: stage target source is disabled")
        check(close(local.get("EC_Set_SP", 0.0), MID_STAGE_TARGET[0]), "local auto: EC stage target mismatch")
        check(close(local.get("pH_Set_SP", 0.0), MID_STAGE_TARGET[1]), "local auto: pH stage target mismatch")
        check(close(local.get("Active_EC_SP", 0.0), MID_STAGE_TARGET[0]), "local auto: active EC target mismatch")
        check(close(local.get("Active_pH_SP", 0.0), MID_STAGE_TARGET[1]), "local auto: active pH target mismatch")
        check(not bool(local.get("Setpoint_Protection_Active")), "local auto: target protection unexpectedly active")
        check_pid_execution(local, "local auto")
        report["automatic_local"] = compact(local)

        # 手动目标：操作员写安全范围内的 EC/pH 目标，泵流量仍由同一 PLC PID 计算。
        check(plc.write_manual_mode(True), "manual target: failed to select manual mode")
        check(
            plc.write_setpoints(
                MANUAL_TARGET[0], MANUAL_TARGET[1],
                FEEDBACK[0], FEEDBACK[1], sac_enable=False,
            ),
            "manual target: failed to write operator target",
        )
        manual = feedback_cycles(plc, 6, sac_enable=False)
        check(bool(manual.get("Manual_Active")), "manual target: Manual_Active is false")
        check(not bool(manual.get("Auto_Active")), "manual target: Auto_Active is true")
        check(not bool(manual.get("SAC_Enable")), "manual target: SAC_Enable is true")
        check(close(manual.get("EC_Set_SP", 0.0), MANUAL_TARGET[0]), "manual target: EC target mismatch")
        check(close(manual.get("pH_Set_SP", 0.0), MANUAL_TARGET[1]), "manual target: pH target mismatch")
        check(close(manual.get("Active_EC_SP", 0.0), MANUAL_TARGET[0]), "manual target: active EC target mismatch")
        check(close(manual.get("Active_pH_SP", 0.0), MANUAL_TARGET[1]), "manual target: active pH target mismatch")
        check(not bool(manual.get("Setpoint_Protection_Active")), "manual target: target protection unexpectedly active")
        check_pid_execution(manual, "manual target")
        report["manual_target"] = compact(manual)

        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("MODE VALIDATION: PASS (自动联网 / 自动本地 / 手动目标均经过 PLC 自适应 PID)")
        return 0
    finally:
        # 为后续全周期测试恢复自动模式，并关闭远程目标权限。
        plc.write_manual_mode(False)
        plc.write_fixed_pid_test_mode(False)
        plc.write_feedback(FEEDBACK[0], FEEDBACK[1], sac_enable=False)
        plc.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
