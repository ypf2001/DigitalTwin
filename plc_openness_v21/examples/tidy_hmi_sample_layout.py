from __future__ import annotations

import copy
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def text_value(node: ET.Element, tag: str, default: str = "") -> str:
    child = node.find(f"./AttributeList/{tag}")
    return child.text if child is not None and child.text is not None else default


def set_attr(node: ET.Element, tag: str, value: str) -> None:
    child = node.find(f"./AttributeList/{tag}")
    if child is None:
        raise RuntimeError(f"Missing attribute {tag}")
    child.text = value


def set_text_field_text(node: ET.Element, value: str) -> None:
    text_node = node.find(".//MultilingualText[@CompositionName='Text']//Text")
    if text_node is None:
        raise RuntimeError("Text field text node not found")
    for child in list(text_node):
        text_node.remove(child)
    body = ET.SubElement(text_node, "body")
    p = ET.SubElement(body, "p")
    p.text = value


def set_font(node: ET.Element, size: str, style: str) -> None:
    font_size = node.find(".//Hmi.Globalization.FontItem/AttributeList/FontSize")
    font_style = node.find(".//Hmi.Globalization.FontItem/AttributeList/FontStyle")
    if font_size is not None:
        font_size.text = size
    if font_style is not None:
        font_style.text = style


def set_fore_color(node: ET.Element, value: str) -> None:
    fore = node.find("./AttributeList/ForeColor")
    if fore is not None:
        fore.text = value


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


def assign_new_ids(node: ET.Element, next_id: int) -> int:
    for elem in node.iter():
        if "ID" in elem.attrib:
            elem.attrib["ID"] = format(next_id, "X")
            next_id += 1
    return next_id


def add_label(layer_obj: ET.Element, template: ET.Element, next_id: int, *, name: str, text: str, left: int, top: int, width: int = 110) -> int:
    label = copy.deepcopy(template)
    next_id = assign_new_ids(label, next_id)
    set_attr(label, "ObjectName", name)
    set_attr(label, "Left", str(left))
    set_attr(label, "Top", str(top))
    set_attr(label, "Width", str(width))
    set_attr(label, "Height", "18")
    set_attr(label, "HorizontalAlignment", "Left")
    set_attr(label, "BorderWidth", "0")
    set_attr(label, "BackFillStyle", "Transparent")
    set_attr(label, "BackColor", "255, 255, 255")
    set_text_field_text(label, text)
    set_font(label, "10", "Regular")
    set_fore_color(label, "255, 255, 255")
    layer_obj.append(label)
    return next_id


def find_by_name(layer_obj: ET.Element, object_name: str) -> ET.Element:
    for item in layer_obj:
        attrs = item.find("AttributeList")
        if attrs is None:
            continue
        name = attrs.findtext("ObjectName", default="")
        if name == object_name:
            return item
    raise RuntimeError(f"Screen item not found: {object_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tidy pure layout of HMI sample controls on Screen_01_MainOverview.")
    parser.add_argument("--input", required=True, help="Exported HMI screen XML.")
    parser.add_argument("--output", required=True, help="Output XML.")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    tree = ET.parse(input_path)
    root = tree.getroot()
    layer_obj = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer_obj is None:
        raise RuntimeError("Screen layer object list not found")

    # Tighten the four description text areas to make room for control samples on the right side of each block.
    body_layouts = {
        "Body_EC_pH_304": (20, 84, 210, 126),
        "Body_Item_336": (410, 84, 205, 126),
        "Body_Item_368": (20, 249, 180, 126),
        "Body_Item_400": (410, 249, 185, 126),
    }
    for name, (left, top, width, height) in body_layouts.items():
        item = find_by_name(layer_obj, name)
        set_attr(item, "Left", str(left))
        set_attr(item, "Top", str(top))
        set_attr(item, "Width", str(width))
        set_attr(item, "Height", str(height))
        set_font(item, "10", "Regular")

    # Reposition the sample controls into a 2x4 clean grid inside the existing four logical sections.
    control_layouts = {
        "I/O 域_1": (248, 116, 108, 32),
        "日期/时间域_1": (525, 116, 190, 26),
        "开关_1": (640, 156, 76, 32),
        "棒图_1": (225, 255, 74, 112),
        "图形 I/O 域_1": (305, 302, 62, 44),
        "符号 I/O 域_1": (628, 302, 108, 32),
        "按钮_1": (628, 350, 108, 32),
    }
    for name, (left, top, width, height) in control_layouts.items():
        item = find_by_name(layer_obj, name)
        set_attr(item, "Left", str(left))
        set_attr(item, "Top", str(top))
        set_attr(item, "Width", str(width))
        set_attr(item, "Height", str(height))

    # Make the bar visually proportional after shrinking.
    bar = find_by_name(layer_obj, "棒图_1")
    if bar.find("./AttributeList/ScalePosition") is not None:
        set_attr(bar, "ScalePosition", "RightDown")

    button = find_by_name(layer_obj, "按钮_1")
    button_text_off = button.find(".//MultilingualText[@CompositionName='TextOff']//Text")
    button_text_on = button.find(".//MultilingualText[@CompositionName='TextOn']//Text")
    for node, value in [(button_text_off, "执行"), (button_text_on, "执行")]:
        if node is not None:
            for child in list(node):
                node.remove(child)
            body = ET.SubElement(node, "body")
            p = ET.SubElement(body, "p")
            p.text = value

    switch = find_by_name(layer_obj, "开关_1")
    for comp_name, value in [("CaptionText", "状态"), ("TextOff", "关"), ("TextOn", "开")]:
        text_node = switch.find(f".//MultilingualText[@CompositionName='{comp_name}']//Text")
        if text_node is not None:
            for child in list(text_node):
                text_node.remove(child)
            body = ET.SubElement(text_node, "body")
            p = ET.SubElement(body, "p")
            p.text = value

    sample_label_template = find_by_name(layer_obj, "Hdr_EC_pH_288")
    next_id = max(all_ids(root), default=0x100) + 1
    labels = [
        ("Lbl_IO", "数值设定", 248, 96, 92),
        ("Lbl_Time", "时间显示", 525, 96, 110),
        ("Lbl_Switch", "状态切换", 640, 136, 92),
        ("Lbl_Bar", "棒图样板", 225, 234, 92),
        ("Lbl_Graphic", "图形域", 305, 282, 70),
        ("Lbl_Symbolic", "符号域", 628, 282, 92),
        ("Lbl_Button", "按钮样板", 628, 330, 92),
    ]
    for label in labels:
        next_id = add_label(
            layer_obj,
            sample_label_template,
            next_id,
            name=label[0],
            text=label[1],
            left=label[2],
            top=label[3],
            width=label[4],
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
