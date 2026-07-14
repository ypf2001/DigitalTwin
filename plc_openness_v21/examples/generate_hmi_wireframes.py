from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT))

from plc_hmi_codegen import (
    SCREEN_SPECS,
    db1_field_map,
    default_scl_path,
    section_lines,
    validate_screen_tags,
    write_hmi_tag_manifest_csv,
    write_symbol_manifest_csv,
)


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
    ET.SubElement(font_attrs, "FontFamily").text = "SimSun"
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
    *,
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
        lines=["主监控 | 手动调试 | 参数设置 | 报警诊断"],
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
    parser = argparse.ArgumentParser(description="Generate KTP900 HMI wireframe screens and tag manifests from the PLC DB1 source.")
    parser.add_argument("--base", required=True, help="Exported HMI screen XML used as template.")
    parser.add_argument("--output-dir", required=True, help="Directory for generated screen XML files.")
    parser.add_argument("--scl", default=str(default_scl_path()), help="Path to xiaweiji.scl.")
    args = parser.parse_args()

    base = Path(args.base).resolve()
    out_dir = Path(args.output_dir).resolve()
    field_map = db1_field_map(args.scl)
    validate_screen_tags(field_map)

    for screen in SCREEN_SPECS:
        sections = [
            (section.title, section_lines(field_map, section.tags), section.rect)
            for section in screen.sections
        ]
        build_screen(
            base,
            out_dir / f"{screen.name}.xml",
            screen_name=screen.name,
            screen_title=screen.title,
            sections=sections,
        )
        print(f"Generated {out_dir / f'{screen.name}.xml'}")

    symbol_manifest = write_symbol_manifest_csv(field_map, out_dir / "DB1_symbol_map.csv")
    tag_manifest = write_hmi_tag_manifest_csv(field_map, out_dir / "HMI_tags_from_DB1.csv")
    print(f"Generated {symbol_manifest}")
    print(f"Generated {tag_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
