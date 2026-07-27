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

SCREEN_FILES: tuple[str, ...] = tuple(target for _, target in NAV_ITEMS)


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
            continue
    return result


def assign_ids(node: ET.Element, next_id: int) -> int:
    for elem in node.iter():
        if "ID" in elem.attrib:
            elem.attrib["ID"] = format(next_id, "X")
            next_id += 1
    return next_id


def set_attr(node: ET.Element, tag: str, value: str) -> None:
    attr_list = node.find("./AttributeList")
    if attr_list is None:
        raise RuntimeError("AttributeList not found")
    attr = attr_list.find(tag)
    if attr is None:
        attr = ET.SubElement(attr_list, tag)
    attr.text = value


def set_text(node: ET.Element, value: str, composition: str = "TextOff") -> None:
    text_node = node.find(f".//MultilingualText[@CompositionName='{composition}']//Text")
    if text_node is None:
        raise RuntimeError(f"Text node not found for composition {composition}")
    for child in list(text_node):
        text_node.remove(child)
    text_node.text = None
    body = ET.SubElement(text_node, "body")
    p = ET.SubElement(body, "p")
    p.text = value


def find_layer(root: ET.Element) -> ET.Element:
    layer = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer is None:
        raise RuntimeError("Screen layer ObjectList not found")
    return layer


def first_button(root: ET.Element) -> ET.Element:
    button = root.find(".//Hmi.Screen.Button")
    if button is None:
        raise RuntimeError("No Hmi.Screen.Button template found")
    return button


def first_textfield(root: ET.Element) -> ET.Element:
    field = root.find(".//Hmi.Screen.TextField")
    if field is None:
        raise RuntimeError("No Hmi.Screen.TextField template found")
    return field


def remove_items(layer: ET.Element, names: set[str]) -> None:
    for child in list(layer):
        object_name = child.findtext("./AttributeList/ObjectName", default="")
        if object_name in names:
            layer.remove(child)


def build_nav_label(template: ET.Element, next_id: int) -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", "NavScreenLabel")
    set_attr(item, "Left", "20")
    set_attr(item, "Top", "434")
    set_attr(item, "Width", "96")
    set_attr(item, "Height", "22")
    set_attr(item, "BackFillStyle", "Transparent")
    set_attr(item, "BorderWidth", "0")
    set_attr(item, "HorizontalAlignment", "Left")
    set_attr(item, "VerticalAlignment", "Middle")
    set_attr(item, "ForeColor", "255, 255, 255")
    set_text(item, "画面切换", "Text")
    return item, next_id


def build_nav_button(
    template: ET.Element,
    next_id: int,
    *,
    object_name: str,
    left: int,
    text: str,
    target_screen: str,
    active: bool,
) -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", object_name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", "430")
    set_attr(item, "Width", "92")
    set_attr(item, "Height", "28")
    set_attr(item, "PictureName", target_screen)
    set_attr(item, "TabIndex", "50")
    set_text(item, text, "TextOff")
    set_text(item, text, "TextOn")
    if active:
        set_attr(item, "BackColor", "56, 124, 201")
        set_attr(item, "FirstGradientColor", "86, 150, 222")
        set_attr(item, "MiddleGradientColor", "56, 124, 201")
        set_attr(item, "SecondGradientColor", "40, 95, 160")
    else:
        set_attr(item, "BackColor", "99, 101, 113")
        set_attr(item, "FirstGradientColor", "131, 132, 142")
        set_attr(item, "MiddleGradientColor", "99, 101, 113")
        set_attr(item, "SecondGradientColor", "88, 90, 103")
    return item, next_id


def apply_navigation(screen_path: Path, button_template: ET.Element) -> None:
    tree = ET.parse(screen_path)
    root = tree.getroot()
    layer = find_layer(root)
    label_template = first_textfield(root)

    remove_items(layer, {"NavHint", "NavScreenLabel", "Nav_ScreenNumber"})
    for i in range(1, 5):
        remove_items(layer, {f"BtnNav_{i}"})

    next_id = max(all_ids(root), default=0x100) + 1
    label, next_id = build_nav_label(label_template, next_id)
    layer.append(label)

    x = 126
    current_screen = screen_path.stem
    for index, (label_text, target_screen) in enumerate(NAV_ITEMS, start=1):
        button, next_id = build_nav_button(
            button_template,
            next_id,
            object_name=f"BtnNav_{index}",
            left=x,
            text=label_text,
            target_screen=target_screen,
            active=(target_screen == current_screen),
        )
        layer.append(button)
        x += 100

    tree.write(screen_path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace dead page-number navigation with screen buttons.")
    parser.add_argument("--screens-dir", required=True, help="Directory containing the four exported HMI screen XML files.")
    args = parser.parse_args()

    screens_dir = Path(args.screens_dir).resolve()
    button_source = screens_dir / "Screen_02_ManualControl.xml"
    button_template = first_button(ET.parse(button_source).getroot())

    for screen_name in SCREEN_FILES:
        apply_navigation(screens_dir / f"{screen_name}.xml", button_template)
        print(screens_dir / f"{screen_name}.xml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
