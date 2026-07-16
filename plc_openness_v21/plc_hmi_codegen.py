from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbField:
    name: str
    datatype: str
    comment: str
    byte_offset: int
    bit_offset: int | None
    address: str


@dataclass(frozen=True)
class SectionSpec:
    title: str
    tags: tuple[str, ...]
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class ScreenSpec:
    name: str
    title: str
    sections: tuple[SectionSpec, ...]


DEFAULT_SCL = Path(r"D:\Digital Twin\plc\xiaweiji\src\xiaweiji.scl")

TYPE_SIZES = {
    "Bool": ("bit", 1),
    "Byte": ("byte", 1),
    "Word": ("word", 2),
    "Int": ("word", 2),
    "UInt": ("word", 2),
    "DWord": ("dword", 4),
    "DInt": ("dword", 4),
    "UDInt": ("dword", 4),
    "Real": ("dword", 4),
    "TON_TIME": ("struct", 16),
}

WRITABLE_TAGS = {
    "EC_Set_SP",
    "pH_Set_SP",
    "Growth_Stage",
    "Manual_Mode",
    "Auto_Mode",
    "Emergency_Stop",
    "Manual_q_f_Set",
    "Manual_q_a_Set",
    "Manual_q_n_Set",
    "Manual_q_p_Set",
    "Manual_q_k_Set",
    "Kp_EC_Set",
    "Ki_EC_Set",
    "Kd_EC_Set",
    "Kp_pH_Set",
    "Ki_pH_Set",
    "Kd_pH_Set",
    "N_Enable",
    "N_Ratio",
    "N_Max",
    "P_Enable",
    "P_Ratio",
    "P_Max",
    "K_Enable",
    "K_Ratio",
    "K_Max",
    "EC_Trim_Band",
    "pH_Trim_Band",
    "Stage_Auto_SP_Enable",
}

SCREEN_SPECS = (
    ScreenSpec(
        name="Screen_01_MainOverview",
        title="画面 1：主监控画面",
        sections=(
            SectionSpec("EC / pH 总览", ("EC_Set_SP", "EC_Actual", "pH_Set_SP", "pH_Actual", "Active_EC_SP", "Active_pH_SP", "Growth_Stage"), (20, 60, 360, 150)),
            SectionSpec("系统状态", ("Remote_Comms_OK", "Comm_Normal", "SAC_Enable", "System_Alarm_Light", "Emergency_Stop", "Manual_Active", "Auto_Active"), (410, 60, 370, 150)),
            SectionSpec("执行量监控", ("q_f_cmd", "q_a_cmd", "Valve_F_Actual", "Valve_A_Actual", "AQ_Valve_F_Raw", "AQ_Valve_A_Raw"), (20, 225, 360, 150)),
            SectionSpec("多通道输出", ("q_n_cmd", "q_p_cmd", "q_k_cmd", "Stage_EC_SP", "Stage_pH_SP", "Setpoint_Protection_Active"), (410, 225, 370, 150)),
        ),
    ),
    ScreenSpec(
        name="Screen_02_ManualControl",
        title="画面 2：手动与调试画面",
        sections=(
            SectionSpec("模式控制", ("Manual_Mode", "Auto_Mode", "Emergency_Stop", "Manual_Active", "Auto_Active"), (20, 60, 360, 120)),
            SectionSpec("手动设定输入", ("Manual_q_f_Set", "Manual_q_a_Set", "Manual_q_n_Set", "Manual_q_p_Set", "Manual_q_k_Set"), (20, 190, 360, 190)),
            SectionSpec("联锁与放行", ("Comm_Normal", "Manual_PumpValve_Enable", "Manual_q_f_Selected", "Manual_q_a_Selected"), (410, 60, 370, 120)),
            SectionSpec("执行链路反馈", ("q_f_cmd", "q_a_cmd", "Valve_F_Actual", "Valve_A_Actual"), (410, 190, 370, 190)),
        ),
    ),
    ScreenSpec(
        name="Screen_03_PID_Settings",
        title="画面 3：参数设置画面",
        sections=(
            SectionSpec("EC PID", ("Kp_EC_Set", "Ki_EC_Set", "Kd_EC_Set", "EC_Trim_Band", "Active_EC_SP"), (20, 60, 240, 150)),
            SectionSpec("pH PID", ("Kp_pH_Set", "Ki_pH_Set", "Kd_pH_Set", "pH_Trim_Band", "Active_pH_SP"), (280, 60, 240, 150)),
            SectionSpec("N/P/K 配方", ("N_Enable", "N_Ratio", "N_Max", "P_Enable", "P_Ratio", "P_Max", "K_Enable", "K_Ratio", "K_Max"), (540, 60, 240, 150)),
            SectionSpec("阶段与策略", ("Growth_Stage", "Stage_Auto_SP_Enable", "Stage_EC_SP", "Stage_pH_SP", "Setpoint_Protection_Active"), (20, 230, 500, 150)),
            SectionSpec("多肥液通道", ("N_Target", "N_Actual", "q_n_cmd", "P_Target", "P_Actual", "q_p_cmd", "K_Target", "K_Actual", "q_k_cmd"), (540, 230, 240, 150)),
        ),
    ),
    ScreenSpec(
        name="Screen_04_AlarmsDiagnostics",
        title="画面 4：报警与诊断",
        sections=(
            SectionSpec("报警摘要", ("System_Alarm_Light", "Emergency_Stop", "Remote_Comms_OK", "Comm_Normal"), (20, 60, 360, 120)),
            SectionSpec("通信诊断", ("Remote_Heartbeat", "Last_Heartbeat", "Watchdog_Timer", "Watchdog_Count", "Remote_Comms_Was_OK"), (20, 190, 360, 190)),
            SectionSpec("模式联锁诊断", ("Manual_Mode", "Auto_Mode", "Manual_Active", "Auto_Active", "Manual_PumpValve_Enable"), (410, 60, 370, 120)),
            SectionSpec("手动执行快照", ("Manual_q_f_Set", "Manual_q_f_Selected", "Manual_q_a_Set", "Manual_q_a_Selected", "q_f_cmd", "q_a_cmd"), (410, 190, 370, 190)),
        ),
    ),
)


def _extract_db1_struct_block(source: str) -> str:
    match = re.search(
        r'DATA_BLOCK\s+"DB1".*?STRUCT(?P<body>.*?)END_STRUCT;',
        source,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError('DB1 STRUCT block not found in SCL source.')
    return match.group("body")


def _parse_struct_lines(body: str) -> list[tuple[str, str, str]]:
    fields: list[tuple[str, str, str]] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        match = re.match(
            r'(?P<name>[A-Za-z_]\w*)\s*(?:\{[^}]*\})?\s*:\s*(?P<dtype>[A-Za-z_]\w*)\s*;\s*(?://\s*(?P<comment>.*))?$',
            line,
        )
        if not match:
            continue
        fields.append(
            (
                match.group("name"),
                match.group("dtype"),
                (match.group("comment") or "").strip(),
            )
        )
    if not fields:
        raise RuntimeError("No DB1 fields parsed from SCL source.")
    return fields


def _align_for_non_bool(byte_offset: int, bit_offset: int) -> tuple[int, int]:
    if bit_offset != 0:
        byte_offset += 1
        bit_offset = 0
    return byte_offset, bit_offset


def _address_for(name: str, dtype: str, byte_offset: int, bit_offset: int | None) -> str:
    if dtype == "Bool":
        if bit_offset is None:
            raise RuntimeError(f"Bool field {name} is missing bit offset.")
        return f"DB1.DBX{byte_offset}.{bit_offset}"
    if dtype == "Byte":
        return f"DB1.DBB{byte_offset}"
    if dtype in {"Word", "Int", "UInt"}:
        return f"DB1.DBW{byte_offset}"
    if dtype in {"DWord", "DInt", "UDInt", "Real"}:
        return f"DB1.DBD{byte_offset}"
    if dtype == "TON_TIME":
        return f"DB1.DBB{byte_offset}"
    return f"DB1.DBB{byte_offset}"


def parse_db1_fields(scl_path: str | Path) -> list[DbField]:
    path = Path(scl_path).resolve()
    source = path.read_text(encoding="utf-8")
    body = _extract_db1_struct_block(source)
    raw_fields = _parse_struct_lines(body)

    byte_offset = 0
    bit_offset = 0
    parsed: list[DbField] = []

    for name, dtype, comment in raw_fields:
        if dtype not in TYPE_SIZES:
            raise RuntimeError(f"Unsupported DB1 datatype: {dtype} for field {name}")

        kind, size = TYPE_SIZES[dtype]
        if kind == "bit":
            address = _address_for(name, dtype, byte_offset, bit_offset)
            parsed.append(DbField(name, dtype, comment, byte_offset, bit_offset, address))
            bit_offset += 1
            if bit_offset >= 8:
                bit_offset = 0
                byte_offset += 1
            continue

        byte_offset, bit_offset = _align_for_non_bool(byte_offset, bit_offset)
        if size > 1 and byte_offset % 2 != 0:
            byte_offset += 1

        address = _address_for(name, dtype, byte_offset, None)
        parsed.append(DbField(name, dtype, comment, byte_offset, None, address))
        byte_offset += size

    return parsed


def db1_field_map(scl_path: str | Path) -> dict[str, DbField]:
    return {field.name: field for field in parse_db1_fields(scl_path)}


def tag_access(name: str) -> str:
    return "ReadWrite" if name in WRITABLE_TAGS else "ReadOnly"


def section_lines(field_map: dict[str, DbField], tags: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for tag_name in tags:
        field = field_map[tag_name]
        lines.append(f"{field.name} | {field.address} | {field.datatype} | {'RW' if tag_access(field.name) == 'ReadWrite' else 'RO'}")
    return lines


def all_hmi_tags() -> list[str]:
    seen: list[str] = []
    for screen in SCREEN_SPECS:
        for section in screen.sections:
            for tag in section.tags:
                if tag not in seen:
                    seen.append(tag)
    # Compact read-only irrigation monitor added to the live main screen.
    for tag in ("Water_Volume_SP", "Water_Volume_Actual", "Qw_Actual"):
        if tag not in seen:
            seen.append(tag)
    return seen


def validate_screen_tags(field_map: dict[str, DbField]) -> None:
    missing = [tag for tag in all_hmi_tags() if tag not in field_map]
    if missing:
        raise RuntimeError(f"HMI screen tags not found in DB1: {', '.join(missing)}")


def write_symbol_manifest_csv(field_map: dict[str, DbField], output_path: str | Path) -> Path:
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Name", "Address", "DataType", "Comment"])
        for field in field_map.values():
            writer.writerow([field.name, field.address, field.datatype, field.comment])
    return output


def write_hmi_tag_manifest_csv(field_map: dict[str, DbField], output_path: str | Path) -> Path:
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Screen", "TagName", "Address", "DataType", "Access", "Use"])
        for screen in SCREEN_SPECS:
            for section in screen.sections:
                for tag_name in section.tags:
                    field = field_map[tag_name]
                    writer.writerow(
                        [
                            screen.name,
                            field.name,
                            field.address,
                            field.datatype,
                            tag_access(field.name),
                            field.comment,
                        ]
                    )
    return output


def default_scl_path() -> Path:
    return DEFAULT_SCL
