from __future__ import annotations

import copy
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("总览", "Screen_01_MainOverview"),
    ("手动", "Screen_02_ManualControl"),
    ("参数", "Screen_03_PID_Settings"),
    ("报警", "Screen_04_AlarmsDiagnostics"),
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


def set_text(node: ET.Element, text: str, composition: str) -> None:
    text_node = node.find(f".//MultilingualText[@CompositionName='{composition}']//Text")
    if text_node is None:
        raise RuntimeError(f"Text node not found for composition {composition}")
    for child in list(text_node):
        text_node.remove(child)
    text_node.text = None
    body = ET.SubElement(text_node, "body")
    p = ET.SubElement(body, "p")
    p.text = text


def first_button(root: ET.Element) -> ET.Element:
    button = root.find(".//Hmi.Screen.Button")
    if button is None:
        raise RuntimeError("No button template found")
    return button


def first_textfield(root: ET.Element) -> ET.Element:
    textfield = root.find(".//Hmi.Screen.TextField")
    if textfield is None:
        raise RuntimeError("No text field template found")
    return textfield


def find_layer(root: ET.Element) -> ET.Element:
    layer = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer is None:
        raise RuntimeError("Screen layer ObjectList not found")
    return layer


def remove_named_items(layer: ET.Element, names: set[str]) -> None:
    for child in list(layer):
        object_name = child.findtext("./AttributeList/ObjectName", default="")
        if object_name in names:
            layer.remove(child)


def make_label(template: ET.Element, next_id: int) -> tuple[ET.Element, int]:
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


def append_click_event(button: ET.Element, next_id: int, target_screen: str) -> int:
    obj = button.find("ObjectList")
    if obj is None:
        raise RuntimeError("Button ObjectList not found")

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

    param_screen = ET.SubElement(
        entry_obj,
        "Hmi.Event.FunctionListEntryParameter",
        {"ID": format(next_id, "X"), "CompositionName": "Parameters"},
    )
    next_id += 1
    param_screen_attrs = ET.SubElement(param_screen, "AttributeList")
    ET.SubElement(param_screen_attrs, "Name").text = "Screen name"
    param_screen_links = ET.SubElement(param_screen, "LinkList")
    param_screen_value = ET.SubElement(param_screen_links, "Value", {"TargetID": "@OpenLink"})
    ET.SubElement(param_screen_value, "Name").text = target_screen

    param_object = ET.SubElement(
        entry_obj,
        "Hmi.Event.FunctionListEntryParameter",
        {"ID": format(next_id, "X"), "CompositionName": "Parameters"},
    )
    next_id += 1
    param_object_attrs = ET.SubElement(param_object, "AttributeList")
    ET.SubElement(param_object_attrs, "Name").text = "Object number"
    object_value = ET.SubElement(param_object_attrs, "Value", {"Type": "System.Int32"})
    object_value.text = "0"
    return next_id


def make_button(
    template: ET.Element,
    next_id: int,
    *,
    index: int,
    left: int,
    label: str,
    target_screen: str,
    active: bool,
) -> tuple[ET.Element, int]:
    item = clone(template)
    next_id = assign_ids(item, next_id)
    set_attr(item, "ObjectName", f"BtnNav_{index}")
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", "430")
    set_attr(item, "Width", "92")
    set_attr(item, "Height", "28")
    set_attr(item, "TabIndex", "50")
    set_text(item, label, "TextOff")
    set_text(item, label, "TextOn")
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
    next_id = append_click_event(item, next_id, target_screen)
    return item, next_id


def apply_navigation(screen_path: Path, button_template: ET.Element) -> None:
    tree = ET.parse(screen_path)
    root = tree.getroot()
    layer = find_layer(root)
    label_template = first_textfield(root)

    remove_named_items(layer, {"NavHint", "NavScreenLabel", "Nav_ScreenNumber"})
    remove_named_items(layer, {f"BtnNav_{i}" for i in range(1, 5)})

    next_id = max(all_ids(root), default=0x100) + 1
    label, next_id = make_label(label_template, next_id)
    layer.append(label)

    current_screen = screen_path.stem
    x = 126
    for index, (label_text, target_screen) in enumerate(NAV_ITEMS, start=1):
        button, next_id = make_button(
            button_template,
            next_id,
            index=index,
            left=x,
            label=label_text,
            target_screen=target_screen,
            active=(target_screen == current_screen),
        )
        layer.append(button)
        x += 100

    tree.write(screen_path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace dead page-number navigation with working ActivateScreen button events.")
    parser.add_argument("--screens-dir", required=True)
    args = parser.parse_args()

    screens_dir = Path(args.screens_dir).resolve()
    button_template_root = ET.parse(screens_dir / "Screen_02_ManualControl.xml").getroot()
    button_template = first_button(button_template_root)

    for _, screen_name in NAV_ITEMS:
        apply_navigation(screens_dir / f"{screen_name}.xml", button_template)
        print(screens_dir / f"{screen_name}.xml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
