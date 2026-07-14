from __future__ import annotations

import argparse
import copy
import xml.etree.ElementTree as ET
from pathlib import Path


STAGE_BUTTONS: tuple[tuple[str, int, int], ...] = (
    ("INI", 0, 209),
    ("DEV", 1, 251),
    ("MID", 2, 293),
    ("LATE", 3, 335),
)

REMOVE_NAMES = {
    "Lbl_Main_StageSelect",
    "Lbl_Main_StageAuto",
    "Sw_Main_Stage_Auto_SP_Enable",
    "Lbl_Main_AutoSource",
    "Sw_Main_AutoSource",
    "BtnStage_INI",
    "BtnStage_DEV",
    "BtnStage_MID",
    "BtnStage_LATE",
}


def clone(node: ET.Element) -> ET.Element:
    return copy.deepcopy(node)


def next_id_generator(root: ET.Element):
    used: list[int] = []
    for elem in root.iter():
        raw = elem.attrib.get("ID")
        if not raw:
            continue
        try:
            used.append(int(raw, 16))
        except ValueError:
            continue
    current = max(used) if used else 0x100
    while True:
        current += 1
        yield format(current, "X")


def assign_ids(node: ET.Element, ids) -> None:
    for elem in node.iter():
        if "ID" in elem.attrib:
            elem.attrib["ID"] = next(ids)


def find_layer(root: ET.Element) -> ET.Element:
    layer = root.find(".//Hmi.Screen.ScreenLayer/ObjectList")
    if layer is None:
        raise RuntimeError("Screen layer ObjectList not found")
    return layer


def first_textfield(root: ET.Element) -> ET.Element:
    node = root.find(".//Hmi.Screen.TextField")
    if node is None:
        raise RuntimeError("No TextField template found")
    return node


def first_button(root: ET.Element) -> ET.Element:
    node = root.find(".//Hmi.Screen.Button")
    if node is None:
        raise RuntimeError("No Button template found")
    return node


def first_switch(root: ET.Element) -> ET.Element:
    node = root.find(".//Hmi.Screen.Switch")
    if node is None:
        raise RuntimeError("No Switch template found")
    return node


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


def remove_named_items(layer: ET.Element, names: set[str]) -> None:
    for child in list(layer):
        object_name = child.findtext("./AttributeList/ObjectName", default="")
        if object_name in names:
            layer.remove(child)


def append_set_tag_event(button: ET.Element, ids, tag_name: str, value: int) -> None:
    obj = button.find("ObjectList")
    if obj is None:
        raise RuntimeError("Button ObjectList not found")

    event = ET.SubElement(obj, "Hmi.Event.Event", {"ID": next(ids), "CompositionName": "Events"})
    event_attrs = ET.SubElement(event, "AttributeList")
    ET.SubElement(event_attrs, "Name").text = "Click"

    event_obj = ET.SubElement(event, "ObjectList")
    handler = ET.SubElement(
        event_obj,
        "Hmi.Event.FunctionListEventHandler",
        {"ID": next(ids), "CompositionName": "EventHandler"},
    )
    handler_obj = ET.SubElement(handler, "ObjectList")
    entry = ET.SubElement(
        handler_obj,
        "Hmi.Event.FunctionListEntry",
        {"ID": next(ids), "CompositionName": "FunctionListEntries"},
    )
    entry_attrs = ET.SubElement(entry, "AttributeList")
    ET.SubElement(entry_attrs, "Name").text = "SetTag"
    ET.SubElement(entry_attrs, "Type").text = "SystemFunction"

    entry_obj = ET.SubElement(entry, "ObjectList")

    tag_param = ET.SubElement(
        entry_obj,
        "Hmi.Event.FunctionListEntryParameter",
        {"ID": next(ids), "CompositionName": "Parameters"},
    )
    tag_param_attr = ET.SubElement(tag_param, "AttributeList")
    ET.SubElement(tag_param_attr, "Name").text = "Tag"
    tag_param_links = ET.SubElement(tag_param, "LinkList")
    tag_value = ET.SubElement(tag_param_links, "Value", {"TargetID": "@OpenLink"})
    ET.SubElement(tag_value, "Name").text = f'"{tag_name}"'

    value_param = ET.SubElement(
        entry_obj,
        "Hmi.Event.FunctionListEntryParameter",
        {"ID": next(ids), "CompositionName": "Parameters"},
    )
    value_param_attr = ET.SubElement(value_param, "AttributeList")
    ET.SubElement(value_param_attr, "Name").text = "Value"
    value_node = ET.SubElement(value_param_attr, "Value", {"Type": "System.Double"})
    value_node.text = str(value)


def remove_template_events(item: ET.Element) -> None:
    """Remove events inherited from a cloned HMI control template."""
    obj = item.find("ObjectList")
    if obj is None:
        return
    for child in list(obj):
        if child.tag == "Hmi.Event.Event" and child.attrib.get("CompositionName") == "Events":
            obj.remove(child)


def make_label(template: ET.Element, ids, *, name: str, left: int, top: int, width: int, text: str) -> ET.Element:
    item = clone(template)
    assign_ids(item, ids)
    set_attr(item, "ObjectName", name)
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", str(top))
    set_attr(item, "Width", str(width))
    set_attr(item, "Height", "20")
    set_attr(item, "BackFillStyle", "Transparent")
    set_attr(item, "BorderWidth", "0")
    set_attr(item, "ForeColor", "255, 255, 255")
    set_attr(item, "UseDesignColorSchema", "false")
    set_attr(item, "VerticalAlignment", "Middle")
    set_attr(item, "HorizontalAlignment", "Left")

    font_item = item.find(".//Hmi.Globalization.FontItem/AttributeList")
    if font_item is not None:
        font_size = font_item.find("FontSize")
        if font_size is not None:
            font_size.text = "10"
        font_style = font_item.find("FontStyle")
        if font_style is not None:
            font_style.text = "Regular"

    set_text(item, text, "Text")
    return item


def make_stage_button(template: ET.Element, ids, *, label: str, value: int, left: int) -> ET.Element:
    item = clone(template)
    assign_ids(item, ids)
    remove_template_events(item)
    set_attr(item, "ObjectName", f"BtnStage_{label}")
    set_attr(item, "Left", str(left))
    set_attr(item, "Top", "168")
    set_attr(item, "Width", "38" if label != "LATE" else "44")
    set_attr(item, "Height", "22")
    set_attr(item, "TabIndex", "11")
    set_attr(item, "BackColor", "99, 101, 113")
    set_attr(item, "FirstGradientColor", "131, 132, 142")
    set_attr(item, "MiddleGradientColor", "99, 101, 113")
    set_attr(item, "SecondGradientColor", "88, 90, 103")
    set_attr(item, "ForeColor", "255, 255, 255")
    set_attr(item, "UseDesignColorSchema", "false")
    set_text(item, label, "TextOff")
    set_text(item, label, "TextOn")
    append_set_tag_event(item, ids, "DB1.Growth_Stage", value)
    return item


def make_auto_source_status(template: ET.Element, ids) -> ET.Element:
    item = clone(template)
    assign_ids(item, ids)
    set_attr(item, "ObjectName", "Sw_Main_AutoSource")
    set_attr(item, "Left", "296")
    set_attr(item, "Top", "193")
    set_attr(item, "Width", "88")
    set_attr(item, "Height", "24")
    set_attr(item, "TabIndex", "12")
    set_attr(item, "Enabled", "false")
    set_attr(item, "ShowCaption", "false")
    set_attr(item, "UseDesignColorSchema", "false")

    prop = None
    for candidate in item.findall(".//Hmi.Screen.Property"):
        if candidate.findtext("./AttributeList/Name") == "ProcessValue":
            prop = candidate
            break
    if prop is None:
        raise RuntimeError("Switch ProcessValue property not found")
    dyn = prop.find(".//Hmi.Dynamic.TagConnectionDynamic/LinkList/Tag/Name")
    if dyn is None:
        raise RuntimeError("Switch tag connection not found")
    dyn.text = '"DB1.SAC_Enable"'

    set_text(item, "本地模式", "TextOff")
    set_text(item, "联网模式", "TextOn")
    return item


def normalize_integer_formats(root: ET.Element) -> None:
    integer_objects = {"IO_DB1.AQ_Valve_F_Raw", "IO_DB1.AQ_Valve_A_Raw"}
    for item in root.findall(".//Hmi.Screen.IOField"):
        if item.findtext("./AttributeList/ObjectName") not in integer_objects:
            continue
        set_attr(item, "FormatPattern", "99999")


def patch_screen(screen_path: Path, button_template_path: Path, switch_template_path: Path) -> None:
    tree = ET.parse(screen_path)
    root = tree.getroot()
    normalize_integer_formats(root)
    ids = next_id_generator(root)
    layer = find_layer(root)
    remove_named_items(layer, REMOVE_NAMES)

    button_root = ET.parse(button_template_path).getroot()
    switch_root = ET.parse(switch_template_path).getroot()
    text_template = first_textfield(root)
    button_template = first_button(button_root)
    switch_template = first_switch(switch_root)

    for label, value, left in STAGE_BUTTONS:
        layer.append(make_stage_button(button_template, ids, label=label, value=value, left=left))
    layer.append(make_label(text_template, ids, name="Lbl_Main_AutoSource", left=209, top=194, width=79, text="自动来源"))
    layer.append(make_auto_source_status(switch_template, ids))

    ET.indent(root)
    tree.write(screen_path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Add growth stage buttons and a read-only online/local source status.")
    parser.add_argument("--screen", required=True, help="Path to Screen_01_MainOverview.xml")
    parser.add_argument("--button-template", required=True, help="Path to a screen XML containing a button template")
    parser.add_argument("--switch-template", required=True, help="Path to a screen XML containing an editable switch template")
    args = parser.parse_args()

    patch_screen(
        Path(args.screen).resolve(),
        Path(args.button_template).resolve(),
        Path(args.switch_template).resolve(),
    )
    print(Path(args.screen).resolve(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
