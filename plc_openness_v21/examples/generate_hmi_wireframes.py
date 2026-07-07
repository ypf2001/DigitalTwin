from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def build_paragraph_body(lines: list[str]) -> ET.Element:
    body = ET.Element("body")
    p = ET.SubElement(body, "p")
    p.text = " | ".join(lines)
    return body


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "Item"


def add_text_field(
    layer: ET.Element,
    *,
    item_id: int,
    font_id: int,
    font_item_id: int,
    text_id: int,
    text_item_id: int,
    left: int,
    top: int,
    width: int,
    height: int,
    font_size: int,
    bold: bool,
    align: str,
    object_name: str,
    lines: list[str],
) -> None:
    field = ET.SubElement(layer, "Hmi.Screen.TextField", {"ID": format(item_id, "X"), "CompositionName": "ScreenItems"})
    attrs = ET.SubElement(field, "AttributeList")
    ET.SubElement(attrs, "BackColor").text = "255, 255, 255"
    ET.SubElement(attrs, "BackFillStyle").text = "Transparent"
    ET.SubElement(attrs, "BorderBackColor").text = "226, 225, 225"
    ET.SubElement(attrs, "BorderColor").text = "156, 154, 165"
    ET.SubElement(attrs, "BorderWidth").text = "0"
    ET.SubElement(attrs, "BottomMargin").text = "2"
    ET.SubElement(attrs, "CornerRadius").text = "3"
    ET.SubElement(attrs, "EdgeStyle").text = "Double"
    ET.SubElement(attrs, "FitToLargest").text = "false"
    ET.SubElement(attrs, "Height").text = str(height)
    ET.SubElement(attrs, "HorizontalAlignment").text = align
    ET.SubElement(attrs, "Left").text = str(left)
    ET.SubElement(attrs, "LeftMargin").text = "3"
    ET.SubElement(attrs, "ObjectName").text = object_name
    ET.SubElement(attrs, "RightMargin").text = "2"
    ET.SubElement(attrs, "Top").text = str(top)
    ET.SubElement(attrs, "TopMargin").text = "2"
    ET.SubElement(attrs, "UseDesignColorSchema").text = "false"
    ET.SubElement(attrs, "VerticalAlignment").text = "Middle"
    ET.SubElement(attrs, "Width").text = str(width)

    obj = ET.SubElement(field, "ObjectList")
    font = ET.SubElement(obj, "Hmi.Globalization.MultiLingualFont", {"ID": format(font_id, "X"), "CompositionName": "Font"})
    font_obj = ET.SubElement(font, "ObjectList")
    font_item = ET.SubElement(font_obj, "Hmi.Globalization.FontItem", {"ID": format(font_item_id, "X"), "CompositionName": "Items"})
    font_attrs = ET.SubElement(font_item, "AttributeList")
    ET.SubElement(font_attrs, "Culture").text = "zh-CN"
    ET.SubElement(font_attrs, "FontFamily").text = "宋体"
    ET.SubElement(font_attrs, "FontSize").text = str(font_size)
    ET.SubElement(font_attrs, "FontStyle").text = "Bold" if bold else "Regular"

    text = ET.SubElement(obj, "MultilingualText", {"ID": format(text_id, "X"), "CompositionName": "Text"})
    text_obj = ET.SubElement(text, "ObjectList")
    text_item = ET.SubElement(text_obj, "MultilingualTextItem", {"ID": format(text_item_id, "X"), "CompositionName": "Items"})
    text_attrs = ET.SubElement(text_item, "AttributeList")
    ET.SubElement(text_attrs, "Culture").text = "zh-CN"
    text_node = ET.SubElement(text_attrs, "Text")
    text_node.append(build_paragraph_body(lines))


def build_screen(
    base_xml: Path,
    output_xml: Path,
    screen_name: str,
    screen_title: str,
    sections: list[tuple[str, list[str], tuple[int, int, int, int]]],
) -> None:
    tree = ET.parse(base_xml)
    root = tree.getroot()
    screen = root.find("Hmi.Screen.Screen")
    if screen is None:
        raise RuntimeError("Expected Hmi.Screen.Screen root object")

    attr_list = screen.find("AttributeList")
    if attr_list is None:
        raise RuntimeError("Missing screen AttributeList")
    for child in attr_list:
        if child.tag == "Name":
            child.text = screen_name
        elif child.tag == "BackColor":
            child.text = "64, 71, 79"

    obj_list = screen.find("ObjectList")
    if obj_list is None:
        raise RuntimeError("Missing screen ObjectList")

    # Remove default generated objects and rebuild from a clean layer.
    for child in list(obj_list):
        obj_list.remove(child)

    help_text = ET.SubElement(obj_list, "MultilingualText", {"ID": "8", "CompositionName": "HelpText"})
    help_obj = ET.SubElement(help_text, "ObjectList")
    help_item = ET.SubElement(help_obj, "MultilingualTextItem", {"ID": "9", "CompositionName": "Items"})
    help_attrs = ET.SubElement(help_item, "AttributeList")
    ET.SubElement(help_attrs, "Culture").text = "zh-CN"
    ET.SubElement(help_attrs, "Text").text = ""

    layer = ET.SubElement(obj_list, "Hmi.Screen.ScreenLayer", {"ID": "A", "CompositionName": "Layers"})
    layer_attrs = ET.SubElement(layer, "AttributeList")
    ET.SubElement(layer_attrs, "Index").text = "0"
    ET.SubElement(layer_attrs, "Name").text = ""
    ET.SubElement(layer_attrs, "VisibleES").text = "true"
    layer_obj = ET.SubElement(layer, "ObjectList")

    next_id = 0x100
    add_text_field(
        layer_obj,
        item_id=next_id,
        font_id=next_id + 1,
        font_item_id=next_id + 2,
        text_id=next_id + 3,
        text_item_id=next_id + 4,
        left=20,
        top=12,
        width=760,
        height=34,
        font_size=18,
        bold=True,
        align="Center",
        object_name="Title",
        lines=[screen_title],
    )
    next_id += 0x10

    add_text_field(
        layer_obj,
        item_id=next_id,
        font_id=next_id + 1,
        font_item_id=next_id + 2,
        text_id=next_id + 3,
        text_item_id=next_id + 4,
        left=20,
        top=430,
        width=760,
        height=34,
        font_size=11,
        bold=False,
        align="Center",
        object_name="NavBar",
        lines=["主监控    手动调试    参数设置    报警诊断    趋势"],
    )
    next_id += 0x10

    for title, lines, (left, top, width, height) in sections:
        add_text_field(
            layer_obj,
            item_id=next_id,
            font_id=next_id + 1,
            font_item_id=next_id + 2,
            text_id=next_id + 3,
            text_item_id=next_id + 4,
            left=left,
            top=top,
            width=width,
            height=26,
            font_size=13,
            bold=True,
            align="Left",
            object_name=f"Hdr_{safe_name(title)}_{next_id}",
            lines=[title],
        )
        next_id += 0x10
        add_text_field(
            layer_obj,
            item_id=next_id,
            font_id=next_id + 1,
            font_item_id=next_id + 2,
            text_id=next_id + 3,
            text_item_id=next_id + 4,
            left=left,
            top=top + 24,
            width=width,
            height=height - 24,
            font_size=11,
            bold=False,
            align="Left",
            object_name=f"Body_{safe_name(title)}_{next_id}",
            lines=lines,
        )
        next_id += 0x10

    output_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_xml, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate KTP900 HMI wireframe screens from an exported screen template.")
    parser.add_argument("--base", required=True, help="Exported HMI screen XML used as template.")
    parser.add_argument("--output-dir", required=True, help="Directory for generated screen XML files.")
    args = parser.parse_args()

    base = Path(args.base).resolve()
    out_dir = Path(args.output_dir).resolve()

    screens = [
        (
            "Screen_01_MainOverview",
            "画面 1：主监控画面",
            [
                ("EC / pH 总览", ["EC_Set_SP", "EC_Actual", "pH_Set_SP", "pH_Actual", "Active_EC_SP", "Active_pH_SP", "Growth_Stage"], (20, 60, 360, 150)),
                ("系统状态", ["Remote_Comms_OK", "Comm_Normal", "System_Alarm_Light", "Emergency_Stop", "Manual_Active", "Auto_Active"], (410, 60, 370, 150)),
                ("执行量监控", ["q_f_cmd", "q_a_cmd", "Valve_F_Actual", "Valve_A_Actual", "AQ_Valve_F_Raw", "AQ_Valve_A_Raw"], (20, 225, 360, 150)),
                ("多通道输出", ["q_n_cmd", "q_p_cmd", "q_k_cmd", "Stage_EC_SP", "Stage_pH_SP", "Setpoint_Protection_Active"], (410, 225, 370, 150)),
            ],
        ),
        (
            "Screen_02_ManualControl",
            "画面 2：手动与调试画面",
            [
                ("模式控制", ["Manual_Mode", "Auto_Mode", "Emergency_Stop", "Manual_Active", "Auto_Active"], (20, 60, 360, 120)),
                ("手动设定输入", ["Manual_q_f_Set", "Manual_q_a_Set", "Manual_q_n_Set", "Manual_q_p_Set", "Manual_q_k_Set"], (20, 190, 360, 190)),
                ("联锁与放行", ["Comm_Normal", "Manual_PumpValve_Enable", "Manual_q_f_Selected", "Manual_q_a_Selected"], (410, 60, 370, 120)),
                ("执行链路反馈", ["q_f_cmd", "q_a_cmd", "Valve_F_Actual", "Valve_A_Actual", "建议起始值: q_f=0.2, q_a=0.0"], (410, 190, 370, 190)),
            ],
        ),
        (
            "Screen_03_PID_Settings",
            "画面 3：参数设置画面",
            [
                ("EC PID", ["Kp_EC_Set", "Ki_EC_Set", "Kd_EC_Set", "EC_Trim_Band", "Active_EC_SP"], (20, 60, 240, 150)),
                ("pH PID", ["Kp_pH_Set", "Ki_pH_Set", "Kd_pH_Set", "pH_Trim_Band", "Active_pH_SP"], (280, 60, 240, 150)),
                ("N/P/K 配方", ["N_Enable / N_Ratio / N_Max", "P_Enable / P_Ratio / P_Max", "K_Enable / K_Ratio / K_Max"], (540, 60, 240, 150)),
                ("阶段与策略", ["Growth_Stage", "Stage_Auto_SP_Enable", "Stage_EC_SP", "Stage_pH_SP", "Setpoint_Protection_Active"], (20, 230, 500, 150)),
                ("执行通道参考", ["N_Target / N_Actual / q_n_cmd", "P_Target / P_Actual / q_p_cmd", "K_Target / K_Actual / q_k_cmd"], (540, 230, 240, 150)),
            ],
        ),
        (
            "Screen_04_AlarmsDiagnostics",
            "画面 4：报警与诊断",
            [
                ("报警摘要", ["System_Alarm_Light", "Emergency_Stop", "Remote_Comms_OK", "Comm_Normal"], (20, 60, 360, 120)),
                ("通信诊断", ["Remote_Heartbeat", "Last_Heartbeat", "Watchdog_Timer", "Watchdog_Count", "Remote_Comms_Was_OK"], (20, 190, 360, 190)),
                ("模式联锁诊断", ["Manual_Mode", "Auto_Mode", "Manual_Active", "Auto_Active", "Manual_PumpValve_Enable"], (410, 60, 370, 120)),
                ("手动执行快照", ["Manual_q_f_Set", "Manual_q_f_Selected", "Manual_q_a_Set", "Manual_q_a_Selected", "q_f_cmd", "q_a_cmd"], (410, 190, 370, 190)),
            ],
        ),
    ]

    for name, title, sections in screens:
        build_screen(base, out_dir / f"{name}.xml", name, title, sections)
        print(f"Generated {out_dir / f'{name}.xml'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
