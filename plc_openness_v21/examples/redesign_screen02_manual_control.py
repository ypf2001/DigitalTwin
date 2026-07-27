from __future__ import annotations

import argparse
import copy
import xml.etree.ElementTree as ET
from pathlib import Path


NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("总览", "Screen_01_MainOverview"),
    ("手动", "Screen_02_ManualControl"),
    ("参数", "Screen_03_PID_Settings"),
    ("报警", "Screen_04_AlarmsDiagnostics"),
)

MODE_BUTTONS: tuple[tuple[str, str, tuple[tuple[str, int], ...], str], ...] = (
    ("BtnMode_Manual", "手动模式", (("DB1.Manual_Mode", 1), ("DB1.Auto_Mode", 0)), "manual"),
    ("BtnMode_Auto", "自动模式", (("DB1.Manual_Mode", 0), ("DB1.Auto_Mode", 1)), "auto"),
    ("BtnMode_EStop", "急停", (("DB1.Emergency_Stop", 1),), "alarm"),
    ("BtnMode_Reset", "急停复位", (("DB1.Emergency_Stop", 0),), "reset"),
)

STATUS_ITEMS: tuple[tuple[str, str, str, str, str], ...] = (
    ("手动目标", "DB1.Manual_Active", "未使用", "使用中", "green"),
    ("自动 PID", "DB1.Auto_Active", "未运行", "运行中", "green"),
    ("自动来源", "DB1.SAC_Enable", "本地模式", "联网模式", "green"),
    ("急停状态", "DB1.Emergency_Stop", "正常", "已触发", "red"),
)

SETPOINT_ITEMS: tuple[tuple[str, str, bool], ...] = (
    ("EC 人工目标 (dS/m)", "DB1.EC_Set_SP", True),
    ("pH 人工目标", "DB1.pH_Set_SP", True),
    ("EC 实际值 (dS/m)", "DB1.EC_Actual", False),
    ("pH 实际值", "DB1.pH_Actual", False),
)

OUTPUT_ITEMS: tuple[tuple[str, str], ...] = (
    ("肥液指令 (L/min)", "DB1.q_f_cmd"),
    ("酸液指令 (L/min)", "DB1.q_a_cmd"),
    ("氮肥指令 (L/min)", "DB1.q_n_cmd"),
    ("磷肥指令 (L/min)", "DB1.q_p_cmd"),
    ("钾肥指令 (L/min)", "DB1.q_k_cmd"),
)


def clone(node: ET.Element) -> ET.Element:
    return copy.deepcopy(node)


def all_ids(root: ET.Element) -> list[int]:
    result: list[int] = []
    for elem in root.iter():
        raw = elem.attrib.get("ID")
        if not raw:
            continue
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


def set_attr(node: ET.Element, name: str, value: str) -> None:
    attrs = node.find("./AttributeList")
    if attrs is None:
        raise RuntimeError("AttributeList not found")
    item = attrs.find(name)
    if item is None:
        item = ET.SubElement(attrs, name)
    item.text = value


def set_text(node: ET.Element, value: str, composition: str) -> None:
    text_node = node.find(f".//MultilingualText[@CompositionName='{composition}']//Text")
    if text_node is None:
        raise RuntimeError(f"Text node not found for {composition}")
    for child in list(text_node):
        text_node.remove(child)
    text_node.text = None
    body = ET.SubElement(text_node, "body")
    ET.SubElement(body, "p").text = value


def set_font(node: ET.Element, size: int, bold: bool = False) -> None:
    for font_attrs in node.findall(".//Hmi.Globalization.FontItem/AttributeList"):
        font_size = font_attrs.find("FontSize")
        font_style = font_attrs.find("FontStyle")
        if font_size is not None:
            font_size.text = str(size)
        if font_style is not None:
            font_style.text = "Bold" if bold else "Regular"


def remove_events(node: ET.Element) -> None:
    obj = node.find("./ObjectList")
    if obj is None:
        return
    for child in list(obj):
        if child.tag == "Hmi.Event.Event":
            obj.remove(child)


def add_process_binding(node: ET.Element, tag_name: str, next_id: int) -> int:
    obj = node.find("./ObjectList")
    if obj is None:
        obj = ET.SubElement(node, "ObjectList")
    for child in list(obj):
        if child.tag == "Hmi.Screen.Property" and child.findtext("./AttributeList/Name") == "ProcessValue":
            obj.remove(child)

    prop = ET.SubElement(obj, "Hmi.Screen.Property", {"ID": format(next_id, "X"), "CompositionName": "Properties"})
    next_id += 1
    attrs = ET.SubElement(prop, "AttributeList")
    ET.SubElement(attrs, "Name").text = "ProcessValue"
    prop_obj = ET.SubElement(prop, "ObjectList")
    dynamic = ET.SubElement(
        prop_obj,
        "Hmi.Dynamic.TagConnectionDynamic",
        {"ID": format(next_id, "X"), "CompositionName": "Dynamic"},
    )
    next_id += 1
    dynamic_attrs = ET.SubElement(dynamic, "AttributeList")
    ET.SubElement(dynamic_attrs, "Indirect").text = "false"
    links = ET.SubElement(dynamic, "LinkList")
    tag = ET.SubElement(links, "Tag", {"TargetID": "@OpenLink"})
    ET.SubElement(tag, "Name").text = f'"{tag_name}"'
    return next_id


def append_bool_tag_event(node: ET.Element, assignments: tuple[tuple[str, int], ...], next_id: int) -> int:
    remove_events(node)
    obj = node.find("./ObjectList")
    if obj is None:
        obj = ET.SubElement(node, "ObjectList")

    event = ET.SubElement(obj, "Hmi.Event.Event", {"ID": format(next_id, "X"), "CompositionName": "Events"})
    next_id += 1
    event_attrs = ET.SubElement(event, "AttributeList")
    ET.SubElement(event_attrs, "Name").text = "Click"
    event_obj = ET.SubElement(event, "ObjectList")
    handler = ET.SubElement(
        event_obj,
        "Hmi.Event.FunctionListEventHandler",
        {"ID": format(next_id, "X"), "CompositionName": "EventHandler"},
    )
    next_id += 1
    handler_obj = ET.SubElement(handler, "ObjectList")

    for tag_name, value in assignments:
        entry = ET.SubElement(
            handler_obj,
            "Hmi.Event.FunctionListEntry",
            {"ID": format(next_id, "X"), "CompositionName": "FunctionListEntries"},
        )
        next_id += 1
        entry_attrs = ET.SubElement(entry, "AttributeList")
        ET.SubElement(entry_attrs, "Name").text = "SetBit" if value else "ResetBit"
        ET.SubElement(entry_attrs, "Type").text = "SystemFunction"
        entry_obj = ET.SubElement(entry, "ObjectList")

        tag_param = ET.SubElement(
            entry_obj,
            "Hmi.Event.FunctionListEntryParameter",
            {"ID": format(next_id, "X"), "CompositionName": "Parameters"},
        )
        next_id += 1
        tag_attrs = ET.SubElement(tag_param, "AttributeList")
        ET.SubElement(tag_attrs, "Name").text = "Tag"
        tag_links = ET.SubElement(tag_param, "LinkList")
        tag_value = ET.SubElement(tag_links, "Value", {"TargetID": "@OpenLink"})
        ET.SubElement(tag_value, "Name").text = f'"{tag_name}"'
    return next_id


def append_activate_screen_event(node: ET.Element, target_screen: str, next_id: int) -> int:
    remove_events(node)
    obj = node.find("./ObjectList")
    if obj is None:
        obj = ET.SubElement(node, "ObjectList")
    event = ET.SubElement(obj, "Hmi.Event.Event", {"ID": format(next_id, "X"), "CompositionName": "Events"})
    next_id += 1
    attrs = ET.SubElement(event, "AttributeList")
    ET.SubElement(attrs, "Name").text = "Click"
    event_obj = ET.SubElement(event, "ObjectList")
    handler = ET.SubElement(
        event_obj,
        "Hmi.Event.FunctionListEventHandler",
        {"ID": format(next_id, "X"), "CompositionName": "EventHandler"},
    )
    next_id += 1
    handler_obj = ET.SubElement(handler, "ObjectList")
    entry = ET.SubElement(
        handler_obj,
        "Hmi.Event.FunctionListEntry",
        {"ID": format(next_id, "X"), "CompositionName": "FunctionListEntries"},
    )
    next_id += 1
    entry_attrs = ET.SubElement(entry, "AttributeList")
    ET.SubElement(entry_attrs, "Name").text = "ActivateScreen"
    ET.SubElement(entry_attrs, "Type").text = "SystemFunction"
    entry_obj = ET.SubElement(entry, "ObjectList")

    screen_param = ET.SubElement(
        entry_obj,
        "Hmi.Event.FunctionListEntryParameter",
        {"ID": format(next_id, "X"), "CompositionName": "Parameters"},
    )
    next_id += 1
    screen_attrs = ET.SubElement(screen_param, "AttributeList")
    ET.SubElement(screen_attrs, "Name").text = "Screen name"
    screen_links = ET.SubElement(screen_param, "LinkList")
    screen_value = ET.SubElement(screen_links, "Value", {"TargetID": "@OpenLink"})
    ET.SubElement(screen_value, "Name").text = target_screen

    object_param = ET.SubElement(
        entry_obj,
        "Hmi.Event.FunctionListEntryParameter",
        {"ID": format(next_id, "X"), "CompositionName": "Parameters"},
    )
    next_id += 1
    object_attrs = ET.SubElement(object_param, "AttributeList")
    ET.SubElement(object_attrs, "Name").text = "Object number"
    ET.SubElement(object_attrs, "Value", {"Type": "System.Int32"}).text = "0"
    return next_id


def make_label(template: ET.Element, next_id: int, *, name: str, text: str, left: int, top: int, width: int, height: int, size: int = 11, bold: bool = False, align: str = "Left") -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", str(top))
    set_attr(item, "Width", str(width))
    set_attr(item, "Height", str(height))
    set_attr(item, "HorizontalAlignment", align)
    set_attr(item, "VerticalAlignment", "Middle")
    set_attr(item, "BackFillStyle", "Transparent")
    set_attr(item, "BorderWidth", "0")
    set_attr(item, "ForeColor", "238, 241, 245")
    set_text(item, text, "Text")
    set_font(item, size, bold)
    return item, next_id


def make_panel(template: ET.Element, next_id: int, *, name: str, left: int, top: int, width: int, height: int) -> tuple[ET.Element, int]:
    panel, next_id = make_label(
        template,
        next_id,
        name=name,
        text="",
        left=left,
        top=top,
        width=width,
        height=height,
    )
    set_attr(panel, "BackFillStyle", "Solid")
    set_attr(panel, "BackColor", "48, 55, 63")
    set_attr(panel, "BorderColor", "83, 93, 105")
    set_attr(panel, "BorderWidth", "1")
    set_attr(panel, "CornerRadius", "3")
    return panel, next_id


def make_button(template: ET.Element, next_id: int, *, name: str, text: str, left: int, top: int, width: int, style: str, assignments: tuple[tuple[str, int], ...] | None = None, target_screen: str | None = None) -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", str(top))
    set_attr(item, "Width", str(width))
    set_attr(item, "Height", "30")
    set_attr(item, "Enabled", "true")
    set_text(item, text, "TextOff")
    set_text(item, text, "TextOn")
    set_font(item, 12, True)

    colors = {
        "manual": ("47, 112, 165", "76, 144, 198", "35, 86, 128"),
        "auto": ("43, 126, 96", "70, 156, 124", "31, 94, 70"),
        "alarm": ("170, 48, 55", "205, 72, 78", "126, 33, 39"),
        "reset": ("91, 98, 108", "126, 134, 145", "66, 72, 80"),
        "nav": ("80, 88, 99", "111, 120, 132", "59, 65, 73"),
        "nav_active": ("47, 112, 165", "76, 144, 198", "35, 86, 128"),
    }
    middle, first, second = colors[style]
    set_attr(item, "BackColor", middle)
    set_attr(item, "FirstGradientColor", first)
    set_attr(item, "MiddleGradientColor", middle)
    set_attr(item, "SecondGradientColor", second)

    if assignments is not None:
        next_id = append_bool_tag_event(item, assignments, next_id)
    elif target_screen is not None:
        next_id = append_activate_screen_event(item, target_screen, next_id)
    return item, next_id


def make_switch(template: ET.Element, next_id: int, *, name: str, tag: str, left: int, top: int, off_text: str, on_text: str, color: str) -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", str(top))
    set_attr(item, "Width", "84")
    set_attr(item, "Height", "24")
    set_attr(item, "Enabled", "false")
    set_attr(item, "ShowCaption", "false")
    set_text(item, off_text, "TextOff")
    set_text(item, on_text, "TextOn")
    set_font(item, 10, True)
    if color == "red":
        set_attr(item, "InnerBackColorOn", "205, 72, 78")
    else:
        set_attr(item, "InnerBackColorOn", "70, 156, 124")
    set_attr(item, "InnerBackColorOff", "215, 219, 224")
    next_id = add_process_binding(item, tag, next_id)
    return item, next_id


def make_io(template: ET.Element, next_id: int, *, name: str, tag: str, left: int, top: int, writable: bool) -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", str(top))
    set_attr(item, "Width", "118")
    set_attr(item, "Height", "24")
    set_attr(item, "Mode", "InOutput" if writable else "Output")
    set_attr(item, "Enabled", "true" if writable else "false")
    set_attr(item, "FormatPattern", "99.99999")
    set_attr(item, "FieldLength", "8")
    set_attr(item, "HorizontalAlignment", "Right")
    set_attr(item, "BackColor", "250, 251, 252" if writable else "222, 227, 232")
    set_attr(item, "ForeColor", "20, 27, 34")
    next_id = add_process_binding(item, tag, next_id)
    return item, next_id


def redesign(src: Path, dst: Path) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    layer = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer is None:
        raise RuntimeError("Screen layer not found")

    text_template = root.find(".//Hmi.Screen.TextField")
    button_template = root.find(".//Hmi.Screen.Button")
    switch_template = root.find(".//Hmi.Screen.Switch")
    io_template = root.find(".//Hmi.Screen.IOField")
    if text_template is None or button_template is None or switch_template is None or io_template is None:
        raise RuntimeError("Required HMI templates are missing")

    for child in list(layer):
        layer.remove(child)

    next_id = max(all_ids(root), default=0x100) + 1

    title, next_id = make_label(
        text_template,
        next_id,
        name="Title",
        text="手动调试与点动",
        left=20,
        top=10,
        width=760,
        height=32,
        size=17,
        bold=True,
        align="Center",
    )
    layer.append(title)

    x = 20
    widths = (122, 122, 102, 112)
    for (name, label, assignments, style), width in zip(MODE_BUTTONS, widths):
        button, next_id = make_button(
            button_template,
            next_id,
            name=name,
            text=label,
            left=x,
            top=50,
            width=width,
            style=style,
            assignments=assignments,
        )
        layer.append(button)
        x += width + 10

    status_panel, next_id = make_panel(text_template, next_id, name="Panel_Status", left=20, top=90, width=760, height=54)
    layer.append(status_panel)
    status_x = (34, 220, 406, 592)
    for index, ((label, tag, off_text, on_text, color), left) in enumerate(zip(STATUS_ITEMS, status_x), start=1):
        label_item, next_id = make_label(
            text_template,
            next_id,
            name=f"LblStatus_{index}",
            text=label,
            left=left,
            top=97,
            width=84,
            height=20,
            size=10,
        )
        layer.append(label_item)
        switch, next_id = make_switch(
            switch_template,
            next_id,
            name=f"SwStatus_{index}",
            tag=tag,
            left=left + 92,
            top=103,
            off_text=off_text,
            on_text=on_text,
            color=color,
        )
        layer.append(switch)

    left_panel, next_id = make_panel(text_template, next_id, name="Panel_Setpoints", left=20, top=156, width=368, height=246)
    right_panel, next_id = make_panel(text_template, next_id, name="Panel_Outputs", left=412, top=156, width=368, height=246)
    layer.extend((left_panel, right_panel))

    left_header, next_id = make_label(text_template, next_id, name="Hdr_Setpoints", text="人工 EC / pH 目标", left=34, top=164, width=330, height=24, size=13, bold=True)
    right_header, next_id = make_label(text_template, next_id, name="Hdr_Outputs", text="实时输出", left=426, top=164, width=330, height=24, size=13, bold=True)
    set_attr(left_header, "ForeColor", "111, 185, 234")
    set_attr(right_header, "ForeColor", "105, 201, 158")
    layer.extend((left_header, right_header))

    for index, (label, tag, writable) in enumerate(SETPOINT_ITEMS):
        top = 198 + index * 38
        label_item, next_id = make_label(text_template, next_id, name=f"LblSet_{index}", text=label, left=38, top=top, width=184, height=24, size=11)
        io_item, next_id = make_io(io_template, next_id, name=f"IO_{tag}", tag=tag, left=244, top=top, writable=writable)
        layer.extend((label_item, io_item))

    for index, (label, tag) in enumerate(OUTPUT_ITEMS):
        top = 198 + index * 38
        label_item, next_id = make_label(text_template, next_id, name=f"LblOut_{index}", text=label, left=430, top=top, width=184, height=24, size=11)
        io_item, next_id = make_io(io_template, next_id, name=f"IO_{tag}", tag=tag, left=636, top=top, writable=False)
        layer.extend((label_item, io_item))

    nav_label, next_id = make_label(text_template, next_id, name="NavLabel", text="画面", left=20, top=430, width=70, height=28, size=11, bold=True)
    layer.append(nav_label)
    nav_x = 96
    for index, (label, target) in enumerate(NAV_ITEMS, start=1):
        button, next_id = make_button(
            button_template,
            next_id,
            name=f"BtnNav_{index}",
            text=label,
            left=nav_x,
            top=430,
            width=92,
            style="nav_active" if target == "Screen_02_ManualControl" else "nav",
            target_screen=target,
        )
        set_attr(button, "Height", "28")
        layer.append(button)
        nav_x += 100

    ET.indent(root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tree.write(dst, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Redesign Screen_02_ManualControl with working mode commands and bindings.")
    parser.add_argument("--source", required=True, help="Source Screen_02 XML used for HMI control templates.")
    parser.add_argument("--output", required=True, help="Output Screen_02 XML.")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    redesign(Path(args.source).resolve(), output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
