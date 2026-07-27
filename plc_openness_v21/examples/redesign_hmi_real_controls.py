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


SCREEN_SPECS: dict[str, ScreenSpec] = {
    "Screen_01_MainOverview": ScreenSpec(
        title="鐢婚潰 1锛氫富鐩戞帶鐢婚潰",
        sections=(
            SectionSpec(
                "EC / pH 鎬昏",
                20,
                60,
                360,
                148,
                (
                    RowSpec("EC 璁惧畾", "io_rw", "DB1.EC_Set_SP"),
                    RowSpec("EC 瀹為檯", "io_ro", "DB1.EC_Actual"),
                    RowSpec("pH 璁惧畾", "io_rw", "DB1.pH_Set_SP"),
                    RowSpec("pH 瀹為檯", "io_ro", "DB1.pH_Actual"),
                    RowSpec("褰撳墠 EC 鐩爣", "io_ro", "DB1.Active_EC_SP"),
                    RowSpec("褰撳墠 pH 鐩爣", "io_ro", "DB1.Active_pH_SP"),
                    RowSpec("鐢熼暱闃舵", "symbolic", "DB1.Growth_Stage"),
                ),
                2,
            ),
            SectionSpec(
                "绯荤粺鐘舵€?,
                410,
                60,
                370,
                148,
                (
                    RowSpec("杩滅▼閫氫俊", "switch_ro", "DB1.Remote_Comms_OK"),
                    RowSpec("閫氫俊姝ｅ父", "switch_ro", "DB1.Comm_Normal"),
                    RowSpec("鎬绘姤璀︾伅", "switch_ro", "DB1.System_Alarm_Light"),
                    RowSpec("鎬ュ仠鐘舵€?, "switch_rw", "DB1.Emergency_Stop"),
                    RowSpec("鎵嬪姩婵€娲?, "switch_ro", "DB1.Manual_Active"),
                    RowSpec("鑷姩婵€娲?, "switch_ro", "DB1.Auto_Active"),
                ),
                2,
            ),
            SectionSpec(
                "鎵ц閲忕洃鎺?,
                20,
                225,
                360,
                148,
                (
                    RowSpec("鑲ユ恫鎸囦护", "io_ro", "DB1.q_f_cmd"),
                    RowSpec("閰告恫鎸囦护", "io_ro", "DB1.q_a_cmd"),
                    RowSpec("鑲ラ榾鍙嶉", "io_ro", "DB1.Valve_F_Actual"),
                    RowSpec("閰搁榾鍙嶉", "io_ro", "DB1.Valve_A_Actual"),
                    RowSpec("鑲ラ榾鍘熷閲?, "io_ro", "DB1.AQ_Valve_F_Raw"),
                    RowSpec("閰搁榾鍘熷閲?, "io_ro", "DB1.AQ_Valve_A_Raw"),
                ),
                2,
            ),
            SectionSpec(
                "澶氶€氶亾杈撳嚭",
                410,
                225,
                370,
                148,
                (
                    RowSpec("姘偉杈撳嚭", "io_ro", "DB1.q_n_cmd"),
                    RowSpec("纾疯偉杈撳嚭", "io_ro", "DB1.q_p_cmd"),
                    RowSpec("閽捐偉杈撳嚭", "io_ro", "DB1.q_k_cmd"),
                    RowSpec("闃舵 EC 淇濇姢", "io_ro", "DB1.Stage_EC_SP"),
                    RowSpec("闃舵 pH 淇濇姢", "io_ro", "DB1.Stage_pH_SP"),
                    RowSpec("淇濇姢婵€娲?, "switch_ro", "DB1.Setpoint_Protection_Active"),
                ),
                2,
            ),
        ),
    ),
    "Screen_02_ManualControl": ScreenSpec(
        title="鐢婚潰 2锛氭墜鍔ㄤ笌璋冭瘯鐢婚潰",
        top_buttons=(
            RowSpec("鎵嬪姩妯″紡", "button", "DB1.Manual_Mode"),
            RowSpec("鑷姩妯″紡", "button", "DB1.Auto_Mode"),
            RowSpec("鎬ュ仠", "button_alarm", "DB1.Emergency_Stop"),
        ),
        sections=(
            SectionSpec(
                "妯″紡涓庤仈閿?,
                20,
                104,
                360,
                116,
                (
                    RowSpec("鎵嬪姩婵€娲?, "switch_ro", "DB1.Manual_Active"),
                    RowSpec("鑷姩婵€娲?, "switch_ro", "DB1.Auto_Active"),
                    RowSpec("閫氫俊姝ｅ父", "switch_ro", "DB1.Comm_Normal"),
                    RowSpec("娉甸榾浣胯兘", "switch_ro", "DB1.Manual_PumpValve_Enable"),
                ),
                2,
            ),
            SectionSpec(
                "鎵嬪姩璁惧畾杈撳叆",
                20,
                235,
                360,
                150,
                (
                    RowSpec("鑲ユ恫璁惧畾", "io_rw", "DB1.Manual_q_f_Set"),
                    RowSpec("閰告恫璁惧畾", "io_rw", "DB1.Manual_q_a_Set"),
                    RowSpec("姘偉璁惧畾", "io_rw", "DB1.Manual_q_n_Set"),
                    RowSpec("纾疯偉璁惧畾", "io_rw", "DB1.Manual_q_p_Set"),
                    RowSpec("閽捐偉璁惧畾", "io_rw", "DB1.Manual_q_k_Set"),
                ),
                1,
            ),
            SectionSpec(
                "鎵嬪姩杈撳嚭閫夋嫨",
                410,
                104,
                370,
                116,
                (
                    RowSpec("鑲ユ恫閫夋嫨", "io_ro", "DB1.Manual_q_f_Selected"),
                    RowSpec("閰告恫閫夋嫨", "io_ro", "DB1.Manual_q_a_Selected"),
                ),
                1,
            ),
            SectionSpec(
                "鎵ц鍙嶉",
                410,
                235,
                370,
                150,
                (
                    RowSpec("鑲ユ恫鎸囦护", "io_ro", "DB1.q_f_cmd"),
                    RowSpec("閰告恫鎸囦护", "io_ro", "DB1.q_a_cmd"),
                    RowSpec("鑲ラ榾鍙嶉", "io_ro", "DB1.Valve_F_Actual"),
                    RowSpec("閰搁榾鍙嶉", "io_ro", "DB1.Valve_A_Actual"),
                ),
                1,
            ),
        ),
    ),
    "Screen_03_PID_Settings": ScreenSpec(
        title="鐢婚潰 3锛氬弬鏁拌缃敾闈?,
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
                    RowSpec("淇甯?, "io_rw", "DB1.EC_Trim_Band"),
                    RowSpec("褰撳墠鐩爣", "io_ro", "DB1.Active_EC_SP"),
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
                    RowSpec("淇甯?, "io_rw", "DB1.pH_Trim_Band"),
                    RowSpec("褰撳墠鐩爣", "io_ro", "DB1.Active_pH_SP"),
                ),
            ),
            SectionSpec(
                "N / P / K 閰嶆柟",
                540,
                60,
                240,
                148,
                (
                    RowSpec("姘惎鐢?, "io_rw", "DB1.N_Enable"),
                    RowSpec("姘瘮渚?, "io_rw", "DB1.N_Ratio"),
                    RowSpec("姘笂闄?, "io_rw", "DB1.N_Max"),
                    RowSpec("纾峰惎鐢?, "io_rw", "DB1.P_Enable"),
                    RowSpec("纾锋瘮渚?, "io_rw", "DB1.P_Ratio"),
                    RowSpec("纾蜂笂闄?, "io_rw", "DB1.P_Max"),
                    RowSpec("閽惧惎鐢?, "io_rw", "DB1.K_Enable"),
                    RowSpec("閽炬瘮渚?, "io_rw", "DB1.K_Ratio"),
                    RowSpec("閽句笂闄?, "io_rw", "DB1.K_Max"),
                ),
            ),`r`n                2,`r`n            ),`r`n            SectionSpec(
                "闃舵涓庣瓥鐣?,
                20,
                228,
                500,
                152,
                (
                    RowSpec("鐢熼暱闃舵", "symbolic", "DB1.Growth_Stage"),
                    RowSpec("闃舵鑷姩璁惧畾", "switch_rw", "DB1.Stage_Auto_SP_Enable"),
                    RowSpec("闃舵 EC 淇濇姢", "io_ro", "DB1.Stage_EC_SP"),
                    RowSpec("闃舵 pH 淇濇姢", "io_ro", "DB1.Stage_pH_SP"),
                    RowSpec("淇濇姢婵€娲?, "switch_ro", "DB1.Setpoint_Protection_Active"),
                ),
                2,
            ),
            SectionSpec(
                "澶氳偉娑查€氶亾",
                540,
                228,
                240,
                152,
                (
                    RowSpec("N 鐩爣", "io_ro", "DB1.N_Target"),
                    RowSpec("N 瀹為檯", "io_ro", "DB1.N_Actual"),
                    RowSpec("N 杈撳嚭", "io_ro", "DB1.q_n_cmd"),
                    RowSpec("P 鐩爣", "io_ro", "DB1.P_Target"),
                    RowSpec("P 瀹為檯", "io_ro", "DB1.P_Actual"),
                    RowSpec("P 杈撳嚭", "io_ro", "DB1.q_p_cmd"),
                    RowSpec("K 鐩爣", "io_ro", "DB1.K_Target"),
                    RowSpec("K 瀹為檯", "io_ro", "DB1.K_Actual"),
                    RowSpec("K 杈撳嚭", "io_ro", "DB1.q_k_cmd"),`r`n                2,`r`n            ),`r`n        ),
        ),
    ),
    "Screen_04_AlarmsDiagnostics": ScreenSpec(
        title="鐢婚潰 4锛氭姤璀︿笌璇婃柇",
        sections=(
            SectionSpec(
                "鎶ヨ鎽樿",
                20,
                60,
                360,
                120,
                (
                    RowSpec("鎶ヨ鐏?, "switch_ro", "DB1.System_Alarm_Light"),
                    RowSpec("鎬ュ仠", "switch_rw", "DB1.Emergency_Stop"),
                    RowSpec("杩滅▼閫氫俊", "switch_ro", "DB1.Remote_Comms_OK"),
                    RowSpec("閫氫俊姝ｅ父", "switch_ro", "DB1.Comm_Normal"),
                ),
                2,
            ),
            SectionSpec(
                "閫氫俊璇婃柇",
                20,
                196,
                360,
                184,
                (
                    RowSpec("杩滅▼蹇冭烦", "io_ro", "DB1.Remote_Heartbeat"),
                    RowSpec("鏈€杩戝績璺?, "io_ro", "DB1.Last_Heartbeat"),
                    RowSpec("鐪嬮棬鐙楄鏃?, "io_ro", "DB1.Watchdog_Timer"),
                    RowSpec("鐪嬮棬鐙楄鏁?, "io_ro", "DB1.Watchdog_Count"),
                    RowSpec("鏇鹃€氫俊姝ｅ父", "switch_ro", "DB1.Remote_Comms_Was_OK"),
                ),
                1,
            ),
            SectionSpec(
                "妯″紡鑱旈攣璇婃柇",
                410,
                60,
                370,
                120,
                (
                    RowSpec("鎵嬪姩妯″紡", "switch_rw", "DB1.Manual_Mode"),
                    RowSpec("鑷姩妯″紡", "switch_rw", "DB1.Auto_Mode"),
                    RowSpec("鎵嬪姩婵€娲?, "switch_ro", "DB1.Manual_Active"),
                    RowSpec("鑷姩婵€娲?, "switch_ro", "DB1.Auto_Active"),
                    RowSpec("娉甸榾浣胯兘", "switch_ro", "DB1.Manual_PumpValve_Enable"),
                ),
                2,
            ),
            SectionSpec(
                "鎵嬪姩鎵ц蹇収",
                410,
                196,
                370,
                184,
                (
                    RowSpec("鑲ユ恫璁惧畾", "io_rw", "DB1.Manual_q_f_Set"),
                    RowSpec("鑲ユ恫閫夋嫨", "io_ro", "DB1.Manual_q_f_Selected"),
                    RowSpec("閰告恫璁惧畾", "io_rw", "DB1.Manual_q_a_Set"),
                    RowSpec("閰告恫閫夋嫨", "io_ro", "DB1.Manual_q_a_Selected"),
                    RowSpec("鑲ユ恫鎸囦护", "io_ro", "DB1.q_f_cmd"),
                    RowSpec("閰告恫鎸囦护", "io_ro", "DB1.q_a_cmd"),
                ),
                1,
            ),
        ),
    ),
}


def find_item(root: ET.Element, object_name: str) -> ET.Element:
    for item in root.findall(".//Hmi.Screen.ScreenLayer/ObjectList/*"):
        attrs = item.find("AttributeList")
        if attrs is None:
            continue
        if attrs.findtext("ObjectName", "") == object_name:
            return item
    raise RuntimeError(f"Screen item not found: {object_name}")


def clone(node: ET.Element) -> ET.Element:
    return copy.deepcopy(node)


def all_ids(root: ET.Element) -> list[int]:
    values: list[int] = []
    for elem in root.iter():
        raw = elem.attrib.get("ID")
        if raw:
            try:
                values.append(int(raw, 16))
            except ValueError:
                pass
    return values


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
        text_node = node.find(f".//MultilingualText[@CompositionName='{composition}']")
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


def configure_switch(node: ET.Element, *, object_name: str, left: int, top: int, width: int, height: int, enabled: bool, caption: str = "") -> None:
    set_attr(node, "ObjectName", object_name)
    set_attr(node, "Left", str(left))
    set_attr(node, "Top", str(top))
    set_attr(node, "Width", str(width))
    set_attr(node, "Height", str(height))
    set_attr(node, "Enabled", "true" if enabled else "false")
    set_attr(node, "ShowCaption", "false")
    set_text(node, "鍏?, "TextOff")
    set_text(node, "寮€", "TextOn")
    caption_node = node.find(".//MultilingualText[@CompositionName='CaptionText']//Text")
    if caption_node is not None:
        for child in list(caption_node):
            caption_node.remove(child)
        caption_node.text = caption


def configure_button(node: ET.Element, *, object_name: str, left: int, top: int, width: int, height: int, text: str, alarm: bool = False) -> None:
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
    nav_text = f"涓荤洃鎺?| 鎵嬪姩璋冭瘯 | 鍙傛暟璁剧疆 | 鎶ヨ璇婃柇    [{active_nav}]"
    set_text(nav_item, nav_text, "Text")
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

    panel_note, next_id = build_label(
        templates["body"],
        next_id,
        object_name=f"Panel_{section.title}",
        text="",
        left=section.left,
        top=section.top + 24,
        width=section.width,
        height=section.height - 24,
        font_size="10",
        bold=False,
        fore="220, 223, 228",
    )
    set_attr(panel_note, "BorderWidth", "1")
    set_attr(panel_note, "BorderColor", "83, 90, 101")
    set_attr(panel_note, "BackFillStyle", "Solid")
    set_attr(panel_note, "BackColor", "53, 59, 67")
    layer_obj.append(panel_note)

    content_left = section.left + 10
    content_top = section.top + 36
    content_width = section.width - 20
    column_gap = 18
    columns = max(1, section.columns)
    col_width = (content_width - column_gap * (columns - 1)) // columns
    rows_per_col = (len(section.rows) + columns - 1) // columns
    usable_height = max(80, section.height - 40)`r`n    row_height = max(20, [math]::Min(24, [int]($usable_height / [math]::Max(1, $rows_per_col))))`r`n    control_width = [math]::Max(48, [math]::Min(96, [int]($col_width * 0.46)))`r`n    label_width = [math]::Max(36, $col_width - 8 - $control_width)

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
            bold=False,
        )
        layer_obj.append(label)

        control_left = left + label_width + 8
        control_top = top - 1

        if row.control in {"io_rw", "io_ro"}:
            control = clone(templates["io"])
            next_id = assign_ids(control, next_id)
            configure_io(
                control,
                object_name=f"IO_{row.tag}",
                left=control_left,
                top=control_top,
                width=control_width,`r`n                height=22,
                mode="InOutput" if row.control == "io_rw" else "Output",
            )
            layer_obj.append(control)
        elif row.control == "symbolic":
            control = clone(templates["symbolic"])
            next_id = assign_ids(control, next_id)
            configure_symbolic(
                control,
                object_name=f"Sym_{row.tag}",
                left=control_left,
                top=control_top,
                width=control_width,`r`n                height=22,
                mode="InOutput",
            )
            layer_obj.append(control)
        elif row.control in {"switch_rw", "switch_ro"}:
            control = clone(templates["switch"])
            next_id = assign_ids(control, next_id)
            configure_switch(
                control,
                object_name=f"Sw_{row.tag}",
                left=control_left + max(0, (control_width - 64) // 2),
                top=control_top - 2,
                width=64,
                height=24,
                enabled=row.control == "switch_rw",
            )
            layer_obj.append(control)
        elif row.control in {"button", "button_alarm"}:
            control = clone(templates["button"])
            next_id = assign_ids(control, next_id)
            configure_button(
                control,
                object_name=f"Btn_{row.tag}",
                left=control_left - 32,
                top=control_top - 3,
                width=128,
                height=28,
                text=row.label,
                alarm=row.control == "button_alarm",
            )
            layer_obj.append(control)

    return next_id


def build_top_buttons(layer_obj: ET.Element, next_id: int, templates: dict[str, ET.Element], buttons: tuple[RowSpec, ...]) -> int:
    if not buttons:
        return next_id
    x = 20
    top = 62
    widths = [120, 120, 120]
    gaps = 12
    for idx, row in enumerate(buttons):
        item = clone(templates["button"])
        next_id = assign_ids(item, next_id)
        configure_button(
            item,
            object_name=f"BtnTop_{row.tag}",
            left=x,
            top=top,
            width=widths[min(idx, len(widths) - 1)],
            height=30,
            text=row.label,
            alarm=row.control == "button_alarm",
        )
        layer_obj.append(item)
        x += widths[min(idx, len(widths) - 1)] + gaps
    return next_id


def build_navigation(layer_obj: ET.Element, next_id: int, templates: dict[str, ET.Element]) -> int:
    hint, next_id = build_label(
        templates["body"],
        next_id,
        object_name="NavHint",
        text="鍒囬〉锛? 涓荤洃鎺?| 3 鎵嬪姩 | 4 鍙傛暟 | 5 鎶ヨ",
        left=20,
        top=434,
        width=310,
        height=22,
        font_size="10",
        bold=False,
        fore="255, 255, 255",
    )
    layer_obj.append(hint)

    nav_label, next_id = build_label(
        templates["body"],
        next_id,
        object_name="NavScreenLabel",
        text="椤甸潰鍙?,
        left=600,
        top=434,
        width=54,
        height=22,
        font_size="10",
        bold=True,
        fore="255, 255, 255",
    )
    layer_obj.append(nav_label)

    nav = clone(templates["symbolic"])
    next_id = assign_ids(nav, next_id)
    configure_symbolic(
        nav,
        object_name="Nav_ScreenNumber",
        left=658,
        top=432,
        width=120,
        height=24,
        mode="InOutput",
    )
    obj = nav.find("ObjectList")
    if obj is None:
        raise RuntimeError("Symbolic nav ObjectList not found")
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
    screen_elem = screen_root.find(".//Hmi.Screen.Screen")`r`n    if screen_elem is None:`r`n        raise RuntimeError("Hmi.Screen.Screen not found")`r`n    link_list = screen_elem.find("LinkList")`r`n    if link_list is not None:`r`n        for child in list(link_list):`r`n            link_list.remove(child)`r`n    templates = {
        "title": find_item(template_root, "Title"),
        "nav": find_item(template_root, "NavBar"),
        "header": find_item(template_root, "Hdr_EC_pH_288"),
        "body": find_item(template_root, "Body_EC_pH_304"),
        "button": find_item(template_root, "鎸夐挳_1"),
        "io": find_item(template_root, "I/O 鍩焈1"),
        "symbolic": find_item(template_root, "绗﹀彿 I/O 鍩焈1"),
        "switch": find_item(template_root, "寮€鍏砡1"),
    }

    layer_obj = clear_layer_items(screen_root)
    next_id = max(all_ids(screen_root), default=0x100) + 1
    next_id = add_title_and_nav(layer_obj, templates["title"], templates["nav"], next_id, spec.title, spec.title.split("锛?, 1)[-1])
    next_id = build_top_buttons(layer_obj, next_id, templates, spec.top_buttons)
    for section in spec.sections:
        next_id = build_section(layer_obj, next_id, templates, section)
    next_id = build_navigation(layer_obj, next_id, templates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Redesign all HMI screens with real controls and unified layout.")
    parser.add_argument("--template-screen", required=True, help="Exported screen XML that already contains real control samples.")
    parser.add_argument("--input-dir", required=True, help="Directory of exported HMI screen XML files.")
    parser.add_argument("--output-dir", required=True, help="Directory for redesigned screen XML files.")
    args = parser.parse_args()

    template_screen = Path(args.template_screen).resolve()
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    template_root = ET.parse(template_screen).getroot()

    for screen_name in SCREEN_SPECS:
        input_path = input_dir / f"{screen_name}.xml"
        output_path = output_dir / f"{screen_name}.xml"
        tree = ET.parse(input_path)
        root = tree.getroot()
        redesign_screen(screen_name, template_root, root)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

