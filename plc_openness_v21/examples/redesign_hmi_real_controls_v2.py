from __future__ import annotations

import argparse
import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RowSpec:
    label: str
    control: str
    tag: str


@dataclass(frozen=True)
class SectionSpec:
    title: str
    left: int
    top: int
    width: int
    height: int
    rows: tuple[RowSpec, ...]
    columns: int = 1


@dataclass(frozen=True)
class ScreenSpec:
    title: str
    sections: tuple[SectionSpec, ...]
    top_buttons: tuple[RowSpec, ...] = ()


NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("总览", "Screen_01_MainOverview"),
    ("手动", "Screen_02_ManualControl"),
    ("参数", "Screen_03_PID_Settings"),
    ("报警", "Screen_04_AlarmsDiagnostics"),
)


SCREEN_SPECS: dict[str, ScreenSpec] = {
    "Screen_01_MainOverview": ScreenSpec(
        title="画面 1：主监控画面",
        sections=(
            SectionSpec(
                "EC / pH 总览",
                20,
                60,
                360,
                148,
                (
                    RowSpec("EC 设定", "io_rw", "DB1.EC_Set_SP"),
                    RowSpec("EC 实际", "io_ro", "DB1.EC_Actual"),
                    RowSpec("pH 设定", "io_rw", "DB1.pH_Set_SP"),
                    RowSpec("pH 实际", "io_ro", "DB1.pH_Actual"),
                    RowSpec("当前 EC 目标", "io_ro", "DB1.Active_EC_SP"),
                    RowSpec("当前 pH 目标", "io_ro", "DB1.Active_pH_SP"),
                    RowSpec("生长阶段", "symbolic", "DB1.Growth_Stage"),
                ),
                2,
            ),
            SectionSpec(
                "系统状态",
                410,
                60,
                370,
                148,
                (
                    RowSpec("远程通信", "switch_ro", "DB1.Remote_Comms_OK"),
                    RowSpec("通信正常", "switch_ro", "DB1.Comm_Normal"),
                    RowSpec("总报警灯", "switch_ro", "DB1.System_Alarm_Light"),
                    RowSpec("急停状态", "switch_rw", "DB1.Emergency_Stop"),
                    RowSpec("手动激活", "switch_ro", "DB1.Manual_Active"),
                    RowSpec("自动激活", "switch_ro", "DB1.Auto_Active"),
                ),
                2,
            ),
            SectionSpec(
                "执行量监控",
                20,
                225,
                360,
                148,
                (
                    RowSpec("肥液指令", "io_ro", "DB1.q_f_cmd"),
                    RowSpec("酸液指令", "io_ro", "DB1.q_a_cmd"),
                    RowSpec("肥阀反馈", "io_ro", "DB1.Valve_F_Actual"),
                    RowSpec("酸阀反馈", "io_ro", "DB1.Valve_A_Actual"),
                    RowSpec("肥阀原始量", "io_ro", "DB1.AQ_Valve_F_Raw"),
                    RowSpec("酸阀原始量", "io_ro", "DB1.AQ_Valve_A_Raw"),
                ),
                2,
            ),
            SectionSpec(
                "多通道输出",
                410,
                225,
                370,
                148,
                (
                    RowSpec("氮肥输出", "io_ro", "DB1.q_n_cmd"),
                    RowSpec("磷肥输出", "io_ro", "DB1.q_p_cmd"),
                    RowSpec("钾肥输出", "io_ro", "DB1.q_k_cmd"),
                    RowSpec("阶段 EC 保护", "io_ro", "DB1.Stage_EC_SP"),
                    RowSpec("阶段 pH 保护", "io_ro", "DB1.Stage_pH_SP"),
                    RowSpec("保护激活", "switch_ro", "DB1.Setpoint_Protection_Active"),
                ),
                2,
            ),
        ),
    ),
    "Screen_02_ManualControl": ScreenSpec(
        title="画面 2：手动与调试画面",
        top_buttons=(
            RowSpec("手动模式", "button", "DB1.Manual_Mode"),
            RowSpec("自动模式", "button", "DB1.Auto_Mode"),
            RowSpec("急停", "button_alarm", "DB1.Emergency_Stop"),
        ),
        sections=(
            SectionSpec(
                "模式与联锁",
                20,
                104,
                360,
                116,
                (
                    RowSpec("手动激活", "switch_ro", "DB1.Manual_Active"),
                    RowSpec("自动激活", "switch_ro", "DB1.Auto_Active"),
                    RowSpec("通信正常", "switch_ro", "DB1.Comm_Normal"),
                    RowSpec("泵阀使能", "switch_ro", "DB1.Manual_PumpValve_Enable"),
                ),
                2,
            ),
            SectionSpec(
                "手动设定输入",
                20,
                235,
                360,
                150,
                (
                    RowSpec("肥液设定", "io_rw", "DB1.Manual_q_f_Set"),
                    RowSpec("酸液设定", "io_rw", "DB1.Manual_q_a_Set"),
                    RowSpec("氮肥设定", "io_rw", "DB1.Manual_q_n_Set"),
                    RowSpec("磷肥设定", "io_rw", "DB1.Manual_q_p_Set"),
                    RowSpec("钾肥设定", "io_rw", "DB1.Manual_q_k_Set"),
                ),
            ),
            SectionSpec(
                "手动输出选择",
                410,
                104,
                370,
                116,
                (
                    RowSpec("肥液选择", "io_ro", "DB1.Manual_q_f_Selected"),
                    RowSpec("酸液选择", "io_ro", "DB1.Manual_q_a_Selected"),
                ),
            ),
            SectionSpec(
                "执行反馈",
                410,
                235,
                370,
                150,
                (
                    RowSpec("肥液指令", "io_ro", "DB1.q_f_cmd"),
                    RowSpec("酸液指令", "io_ro", "DB1.q_a_cmd"),
                    RowSpec("肥阀反馈", "io_ro", "DB1.Valve_F_Actual"),
                    RowSpec("酸阀反馈", "io_ro", "DB1.Valve_A_Actual"),
                ),
            ),
        ),
    ),
    "Screen_03_PID_Settings": ScreenSpec(
        title="画面 3：参数设置画面",
        sections=(
            SectionSpec(
                "EC PID",
                20,
                60,
                240,
                148,
                (
                    RowSpec("Kp", "io_rw", "DB1.Kp_EC_Set"),
                    RowSpec("Ki", "io_rw", "DB1.Ki_EC_Set"),
                    RowSpec("Kd", "io_rw", "DB1.Kd_EC_Set"),
                    RowSpec("修正带", "io_rw", "DB1.EC_Trim_Band"),
                    RowSpec("当前目标", "io_ro", "DB1.Active_EC_SP"),
                ),
            ),
            SectionSpec(
                "pH PID",
                280,
                60,
                240,
                148,
                (
                    RowSpec("Kp", "io_rw", "DB1.Kp_pH_Set"),
                    RowSpec("Ki", "io_rw", "DB1.Ki_pH_Set"),
                    RowSpec("Kd", "io_rw", "DB1.Kd_pH_Set"),
                    RowSpec("修正带", "io_rw", "DB1.pH_Trim_Band"),
                    RowSpec("当前目标", "io_ro", "DB1.Active_pH_SP"),
                ),
            ),
            SectionSpec(
                "N / P / K 配方",
                540,
                60,
                240,
                148,
                (
                    RowSpec("氮启用", "io_rw", "DB1.N_Enable"),
                    RowSpec("氮比例", "io_rw", "DB1.N_Ratio"),
                    RowSpec("氮上限", "io_rw", "DB1.N_Max"),
                    RowSpec("磷启用", "io_rw", "DB1.P_Enable"),
                    RowSpec("磷比例", "io_rw", "DB1.P_Ratio"),
                    RowSpec("磷上限", "io_rw", "DB1.P_Max"),
                    RowSpec("钾启用", "io_rw", "DB1.K_Enable"),
                    RowSpec("钾比例", "io_rw", "DB1.K_Ratio"),
                    RowSpec("钾上限", "io_rw", "DB1.K_Max"),
                ),
                2,
            ),
            SectionSpec(
                "阶段与策略",
                20,
                228,
                500,
                152,
                (
                    RowSpec("生长阶段", "symbolic", "DB1.Growth_Stage"),
                    RowSpec("阶段自动设定", "switch_rw", "DB1.Stage_Auto_SP_Enable"),
                    RowSpec("阶段 EC 保护", "io_ro", "DB1.Stage_EC_SP"),
                    RowSpec("阶段 pH 保护", "io_ro", "DB1.Stage_pH_SP"),
                    RowSpec("保护激活", "switch_ro", "DB1.Setpoint_Protection_Active"),
                ),
                2,
            ),
            SectionSpec(
                "多肥液通道",
                540,
                228,
                240,
                152,
                (
                    RowSpec("N 目标", "io_ro", "DB1.N_Target"),
                    RowSpec("N 实际", "io_ro", "DB1.N_Actual"),
                    RowSpec("N 输出", "io_ro", "DB1.q_n_cmd"),
                    RowSpec("P 目标", "io_ro", "DB1.P_Target"),
                    RowSpec("P 实际", "io_ro", "DB1.P_Actual"),
                    RowSpec("P 输出", "io_ro", "DB1.q_p_cmd"),
                    RowSpec("K 目标", "io_ro", "DB1.K_Target"),
                    RowSpec("K 实际", "io_ro", "DB1.K_Actual"),
                    RowSpec("K 输出", "io_ro", "DB1.q_k_cmd"),
                ),
                2,
            ),
        ),
    ),
    "Screen_04_AlarmsDiagnostics": ScreenSpec(
        title="画面 4：报警与诊断",
        sections=(
            SectionSpec(
                "报警摘要",
                20,
                60,
                360,
                120,
                (
                    RowSpec("报警灯", "switch_ro", "DB1.System_Alarm_Light"),
                    RowSpec("急停", "switch_rw", "DB1.Emergency_Stop"),
                    RowSpec("远程通信", "switch_ro", "DB1.Remote_Comms_OK"),
                    RowSpec("通信正常", "switch_ro", "DB1.Comm_Normal"),
                ),
                2,
            ),
            SectionSpec(
                "通信诊断",
                20,
                196,
                360,
                184,
                (
                    RowSpec("远程心跳", "io_ro", "DB1.Remote_Heartbeat"),
                    RowSpec("最近心跳", "io_ro", "DB1.Last_Heartbeat"),
                    RowSpec("看门狗计时", "io_ro", "DB1.Watchdog_Timer"),
                    RowSpec("看门狗计数", "io_ro", "DB1.Watchdog_Count"),
                    RowSpec("曾通信正常", "switch_ro", "DB1.Remote_Comms_Was_OK"),
                ),
            ),
            SectionSpec(
                "模式联锁诊断",
                410,
                60,
                370,
                120,
                (
                    RowSpec("手动模式", "switch_rw", "DB1.Manual_Mode"),
                    RowSpec("自动模式", "switch_rw", "DB1.Auto_Mode"),
                    RowSpec("手动激活", "switch_ro", "DB1.Manual_Active"),
                    RowSpec("自动激活", "switch_ro", "DB1.Auto_Active"),
                    RowSpec("泵阀使能", "switch_ro", "DB1.Manual_PumpValve_Enable"),
                ),
                2,
            ),
            SectionSpec(
                "手动执行快照",
                410,
                196,
                370,
                184,
                (
                    RowSpec("肥液设定", "io_rw", "DB1.Manual_q_f_Set"),
                    RowSpec("肥液选择", "io_ro", "DB1.Manual_q_f_Selected"),
                    RowSpec("酸液设定", "io_rw", "DB1.Manual_q_a_Set"),
                    RowSpec("酸液选择", "io_ro", "DB1.Manual_q_a_Selected"),
                    RowSpec("肥液指令", "io_ro", "DB1.q_f_cmd"),
                    RowSpec("酸液指令", "io_ro", "DB1.q_a_cmd"),
                ),
            ),
        ),
    ),
}


def find_item(root: ET.Element, object_name: str) -> ET.Element:
    for item in root.findall(".//Hmi.Screen.ScreenLayer/ObjectList/*"):
        attrs = item.find("AttributeList")
        if attrs is not None and attrs.findtext("ObjectName", "") == object_name:
            return item
    raise RuntimeError(f"Screen item not found: {object_name}")


def clone(node: ET.Element) -> ET.Element:
    return copy.deepcopy(node)


def all_ids(root: ET.Element) -> list[int]:
    result: list[int] = []
    for elem in root.iter():
        raw = elem.attrib.get("ID")
        if raw:
            try:
                result.append(int(raw, 16))
            except ValueError:
                pass
    return result


def assign_ids(node: ET.Element, next_id: int) -> int:
    for elem in node.iter():
        if "ID" in elem.attrib:
            elem.attrib["ID"] = format(next_id, "X")
            next_id += 1
    return next_id


def set_attr(node: ET.Element, tag: str, value: str) -> None:
    attr = node.find(f"./AttributeList/{tag}")
    if attr is None:
        attr_list = node.find("./AttributeList")
        if attr_list is None:
            raise RuntimeError("AttributeList not found")
        attr = ET.SubElement(attr_list, tag)
    attr.text = value


def set_text(node: ET.Element, value: str, composition: str = "Text") -> None:
    text_node = node.find(f".//MultilingualText[@CompositionName='{composition}']//Text")
    if text_node is None:
        raise RuntimeError(f"Text node not found for composition {composition}")
    for child in list(text_node):
        text_node.remove(child)
    text_node.text = None
    body = ET.SubElement(text_node, "body")
    p = ET.SubElement(body, "p")
    p.text = value


def set_font(node: ET.Element, size: str, style: str = "Regular") -> None:
    font_size = node.find(".//Hmi.Globalization.FontItem/AttributeList/FontSize")
    font_style = node.find(".//Hmi.Globalization.FontItem/AttributeList/FontStyle")
    if font_size is not None:
        font_size.text = size
    if font_style is not None:
        font_style.text = style


def set_color(node: ET.Element, fore: str | None = None, back: str | None = None) -> None:
    if fore is not None:
        set_attr(node, "ForeColor", fore)
    if back is not None:
        set_attr(node, "BackColor", back)


def build_label(template: ET.Element, next_id: int, *, object_name: str, text: str, left: int, top: int, width: int, height: int, font_size: str = "10", bold: bool = False, fore: str = "255, 255, 255") -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", object_name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", str(top))
    set_attr(item, "Width", str(width))
    set_attr(item, "Height", str(height))
    set_attr(item, "HorizontalAlignment", "Left")
    set_attr(item, "VerticalAlignment", "Middle")
    set_attr(item, "BackFillStyle", "Transparent")
    set_attr(item, "BorderWidth", "0")
    set_text(item, text, "Text")
    set_font(item, font_size, "Bold" if bold else "Regular")
    set_color(item, fore=fore, back="255, 255, 255")
    return item, next_id


def configure_io(node: ET.Element, *, object_name: str, left: int, top: int, width: int, height: int, mode: str) -> None:
    set_attr(node, "ObjectName", object_name)
    set_attr(node, "Left", str(left))
    set_attr(node, "Top", str(top))
    set_attr(node, "Width", str(width))
    set_attr(node, "Height", str(height))
    set_attr(node, "Mode", mode)
    set_attr(node, "FieldLength", "8")
    set_attr(node, "FormatPattern", "99999")
    set_attr(node, "BorderWidth", "2")


def configure_symbolic(node: ET.Element, *, object_name: str, left: int, top: int, width: int, height: int, mode: str) -> None:
    set_attr(node, "ObjectName", object_name)
    set_attr(node, "Left", str(left))
    set_attr(node, "Top", str(top))
    set_attr(node, "Width", str(width))
    set_attr(node, "Height", str(height))
    set_attr(node, "Mode", mode)
    set_attr(node, "CountVisibleItems", "4")
    set_attr(node, "BorderWidth", "2")


def configure_switch(node: ET.Element, *, object_name: str, left: int, top: int, width: int, height: int, enabled: bool) -> None:
    set_attr(node, "ObjectName", object_name)
    set_attr(node, "Left", str(left))
    set_attr(node, "Top", str(top))
    set_attr(node, "Width", str(width))
    set_attr(node, "Height", str(height))
    set_attr(node, "Enabled", "true" if enabled else "false")
    set_attr(node, "ShowCaption", "false")
    set_text(node, "关", "TextOff")
    set_text(node, "开", "TextOn")


def configure_button(node: ET.Element, *, object_name: str, left: int, top: int, width: int, height: int, text: str, alarm: bool = False, target_screen: str | None = None, active: bool = False) -> None:
    set_attr(node, "ObjectName", object_name)
    set_attr(node, "Left", str(left))
    set_attr(node, "Top", str(top))
    set_attr(node, "Width", str(width))
    set_attr(node, "Height", str(height))
    set_text(node, text, "TextOff")
    set_text(node, text, "TextOn")
    if alarm:
        set_attr(node, "BackColor", "153, 47, 52")
        set_attr(node, "FirstGradientColor", "184, 71, 74")
        set_attr(node, "MiddleGradientColor", "153, 47, 52")
        set_attr(node, "SecondGradientColor", "129, 33, 38")
    elif active:
        set_attr(node, "BackColor", "56, 124, 201")
        set_attr(node, "FirstGradientColor", "86, 150, 222")
        set_attr(node, "MiddleGradientColor", "56, 124, 201")
        set_attr(node, "SecondGradientColor", "40, 95, 160")
    if target_screen:
        set_attr(node, "PictureName", target_screen)


def clear_layer_items(root: ET.Element) -> ET.Element:
    layer_obj = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer_obj is None:
        raise RuntimeError("Layer ObjectList not found")
    for child in list(layer_obj):
        layer_obj.remove(child)
    return layer_obj


def add_title_and_nav(layer_obj: ET.Element, title_template: ET.Element, nav_template: ET.Element, next_id: int, screen_title: str, active_nav: str) -> int:
    title_item = clone(title_template)
    next_id = assign_ids(title_item, next_id)
    set_text(title_item, screen_title, "Text")
    set_attr(title_item, "ObjectName", "Title")
    layer_obj.append(title_item)

    nav_item = clone(nav_template)
    next_id = assign_ids(nav_item, next_id)
    set_text(nav_item, f"主监控 | 手动调试 | 参数设置 | 报警诊断    [{active_nav}]", "Text")
    set_attr(nav_item, "ObjectName", "NavBar")
    layer_obj.append(nav_item)
    return next_id


def build_section(layer_obj: ET.Element, next_id: int, templates: dict[str, ET.Element], section: SectionSpec) -> int:
    header, next_id = build_label(
        templates["header"],
        next_id,
        object_name=f"Hdr_{section.title}",
        text=section.title,
        left=section.left,
        top=section.top,
        width=section.width,
        height=24,
        font_size="12",
        bold=True,
    )
    layer_obj.append(header)

    panel, next_id = build_label(
        templates["body"],
        next_id,
        object_name=f"Panel_{section.title}",
        text="",
        left=section.left,
        top=section.top + 24,
        width=section.width,
        height=section.height - 24,
        font_size="10",
        fore="220, 223, 228",
    )
    set_attr(panel, "BorderWidth", "1")
    set_attr(panel, "BorderColor", "83, 90, 101")
    set_attr(panel, "BackFillStyle", "Solid")
    set_attr(panel, "BackColor", "53, 59, 67")
    layer_obj.append(panel)

    content_left = section.left + 10
    content_top = section.top + 36
    content_width = section.width - 20
    columns = max(1, section.columns)
    column_gap = 18
    col_width = (content_width - column_gap * (columns - 1)) // columns
    rows_per_col = (len(section.rows) + columns - 1) // columns
    usable_height = max(80, section.height - 40)
    row_height = max(20, min(24, usable_height // max(1, rows_per_col)))
    control_width = max(48, min(96, int(col_width * 0.46)))
    label_width = max(36, col_width - 8 - control_width)

    for index, row in enumerate(section.rows):
        col = index // rows_per_col
        row_index = index % rows_per_col
        left = content_left + col * (col_width + column_gap)
        top = content_top + row_index * row_height

        label, next_id = build_label(
            templates["body"],
            next_id,
            object_name=f"Lbl_{row.tag}",
            text=row.label,
            left=left,
            top=top,
            width=label_width,
            height=20,
            font_size="10",
        )
        layer_obj.append(label)

        control_left = left + label_width + 8
        control_top = top - 1

        if row.control in {"io_rw", "io_ro"}:
            control = clone(templates["io"])
            next_id = assign_ids(control, next_id)
            configure_io(control, object_name=f"IO_{row.tag}", left=control_left, top=control_top, width=control_width, height=22, mode="InOutput" if row.control == "io_rw" else "Output")
            layer_obj.append(control)
        elif row.control == "symbolic":
            control = clone(templates["symbolic"])
            next_id = assign_ids(control, next_id)
            configure_symbolic(control, object_name=f"Sym_{row.tag}", left=control_left, top=control_top, width=control_width, height=22, mode="InOutput")
            layer_obj.append(control)
        elif row.control in {"switch_rw", "switch_ro"}:
            control = clone(templates["switch"])
            next_id = assign_ids(control, next_id)
            configure_switch(control, object_name=f"Sw_{row.tag}", left=control_left + max(0, (control_width - 64) // 2), top=control_top - 2, width=64, height=24, enabled=row.control == "switch_rw")
            layer_obj.append(control)
        elif row.control in {"button", "button_alarm"}:
            control = clone(templates["button"])
            next_id = assign_ids(control, next_id)
            configure_button(control, object_name=f"Btn_{row.tag}", left=control_left - 32, top=control_top - 3, width=128, height=28, text=row.label, alarm=row.control == "button_alarm")
            layer_obj.append(control)

    return next_id


def build_top_buttons(layer_obj: ET.Element, next_id: int, templates: dict[str, ET.Element], buttons: tuple[RowSpec, ...]) -> int:
    if not buttons:
        return next_id
    x = 20
    for row in buttons:
        item = clone(templates["button"])
        next_id = assign_ids(item, next_id)
        configure_button(item, object_name=f"BtnTop_{row.tag}", left=x, top=62, width=120, height=30, text=row.label, alarm=row.control == "button_alarm")
        layer_obj.append(item)
        x += 132
    return next_id


def build_navigation(layer_obj: ET.Element, next_id: int, templates: dict[str, ET.Element]) -> int:
    hint, next_id = build_label(
        templates["body"],
        next_id,
        object_name="NavHint",
        text="切页：2 主监控 | 3 手动 | 4 参数 | 5 报警",
        left=20,
        top=434,
        width=310,
        height=22,
        font_size="10",
    )
    layer_obj.append(hint)

    nav_label, next_id = build_label(
        templates["body"],
        next_id,
        object_name="NavScreenLabel",
        text="页面号",
        left=600,
        top=434,
        width=54,
        height=22,
        font_size="10",
        bold=True,
    )
    layer_obj.append(nav_label)

    nav = clone(templates["symbolic"])
    next_id = assign_ids(nav, next_id)
    configure_symbolic(nav, object_name="Nav_ScreenNumber", left=658, top=432, width=120, height=24, mode="InOutput")
    obj = nav.find("ObjectList")
    if obj is None:
        raise RuntimeError("Nav symbolic ObjectList not found")
    prop = ET.SubElement(obj, "Hmi.Screen.Property", {"ID": format(next_id, "X"), "CompositionName": "Properties"})
    next_id += 1
    al = ET.SubElement(prop, "AttributeList")
    ET.SubElement(al, "Name").text = "ProcessValue"
    ol = ET.SubElement(prop, "ObjectList")
    dyn = ET.SubElement(ol, "Hmi.Dynamic.TagConnectionDynamic", {"ID": format(next_id, "X"), "CompositionName": "Dynamic"})
    next_id += 1
    dal = ET.SubElement(dyn, "AttributeList")
    ET.SubElement(dal, "Indirect").text = "false"
    ll = ET.SubElement(dyn, "LinkList")
    tag = ET.SubElement(ll, "Tag", {"TargetID": "@OpenLink"})
    ET.SubElement(tag, "Name").text = "Tag_ScreenNumber"
    layer_obj.append(nav)
    return next_id


def redesign_screen(screen_name: str, template_root: ET.Element, screen_root: ET.Element) -> None:
    spec = SCREEN_SPECS[screen_name]
    screen_elem = screen_root.find(".//Hmi.Screen.Screen")
    if screen_elem is None:
        raise RuntimeError("Hmi.Screen.Screen not found")
    link_list = screen_elem.find("LinkList")
    if link_list is not None:
        for child in list(link_list):
            link_list.remove(child)

    templates = {
        "title": find_item(template_root, "Title"),
        "nav": find_item(template_root, "NavBar"),
        "header": find_item(template_root, "Hdr_EC_pH_288"),
        "body": find_item(template_root, "Body_EC_pH_304"),
        "button": find_item(template_root, "按钮_1"),
        "io": find_item(template_root, "I/O 域_1"),
        "symbolic": find_item(template_root, "符号 I/O 域_1"),
        "switch": find_item(template_root, "开关_1"),
    }

    layer_obj = clear_layer_items(screen_root)
    next_id = max(all_ids(screen_root), default=0x100) + 1
    active_nav = spec.title.split("：", 1)[-1]
    next_id = add_title_and_nav(layer_obj, templates["title"], templates["nav"], next_id, spec.title, active_nav)
    next_id = build_top_buttons(layer_obj, next_id, templates, spec.top_buttons)
    for section in spec.sections:
        next_id = build_section(layer_obj, next_id, templates, section)
    build_navigation(layer_obj, next_id, templates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Redesign HMI screens with real controls, no template inheritance, and compact layout.")
    parser.add_argument("--template-screen", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    template_root = ET.parse(Path(args.template_screen).resolve()).getroot()
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for screen_name in SCREEN_SPECS:
        tree = ET.parse(input_dir / f"{screen_name}.xml")
        root = tree.getroot()
        redesign_screen(screen_name, template_root, root)
        out = output_dir / f"{screen_name}.xml"
        tree.write(out, encoding="utf-8", xml_declaration=True)
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
