from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from .create_mode_interlock_lad_xml import (
        FLG_NS,
        IF_NS,
        access,
        attr,
        compile_unit,
        ident_con,
        member,
        name_con,
        normalize_xml,
        part,
        q,
        text,
        wire,
    )
except ImportError:
    from create_mode_interlock_lad_xml import (
        FLG_NS,
        IF_NS,
        access,
        attr,
        compile_unit,
        ident_con,
        member,
        name_con,
        normalize_xml,
        part,
        q,
        text,
        wire,
    )


INPUT_NAMES = (
    "Emergency_Stop",
    "Manual_Mode",
    "Auto_Mode",
    "SAC_Enable",
    "Stage_Auto_SP_Enable",
)

OUTPUT_NAMES = (
    "Mode_EStop",
    "Mode_Manual",
    "Mode_Remote_Auto",
    "Mode_Stage_Auto",
    "Mode_Local_Auto",
    "Mode_Standby",
)

NETWORK_SPECS = (
    ("Emergency stop mode", (("Emergency_Stop", False),), "Mode_EStop"),
    ("Manual mode", (("Emergency_Stop", True), ("Manual_Mode", False)), "Mode_Manual"),
    (
        "Remote automatic mode",
        (("Emergency_Stop", True), ("Manual_Mode", True), ("Auto_Mode", False), ("SAC_Enable", False)),
        "Mode_Remote_Auto",
    ),
    (
        "Stage automatic mode",
        (
            ("Emergency_Stop", True),
            ("Manual_Mode", True),
            ("Auto_Mode", False),
            ("SAC_Enable", True),
            ("Stage_Auto_SP_Enable", False),
        ),
        "Mode_Stage_Auto",
    ),
    (
        "Local setpoint automatic mode",
        (
            ("Emergency_Stop", True),
            ("Manual_Mode", True),
            ("Auto_Mode", False),
            ("SAC_Enable", True),
            ("Stage_Auto_SP_Enable", True),
        ),
        "Mode_Local_Auto",
    ),
    (
        "Standby mode",
        (("Emergency_Stop", True), ("Manual_Mode", True), ("Auto_Mode", True)),
        "Mode_Standby",
    ),
)


def flgnet_series_coil(conditions: tuple[tuple[str, bool], ...], output_name: str) -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))

    input_access_ids: list[int] = []
    next_uid = 21
    for input_name, _ in conditions:
        input_access_ids.append(next_uid)
        parts.append(access(next_uid, [input_name], scope="LocalVariable"))
        next_uid += 1

    output_access_uid = next_uid
    parts.append(access(output_access_uid, [output_name], scope="LocalVariable"))
    next_uid += 1

    contact_ids: list[int] = []
    for _, negated in conditions:
        contact_ids.append(next_uid)
        parts.append(part("Contact", next_uid, negated=negated))
        next_uid += 1

    coil_uid = next_uid
    parts.append(part("Coil", coil_uid))
    next_uid += 1

    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.append(wire(next_uid, ET.Element(q(FLG_NS, "Powerrail")), name_con(contact_ids[0], "in")))
    next_uid += 1

    for index, (access_uid, contact_uid) in enumerate(zip(input_access_ids, contact_ids)):
        wires.append(wire(next_uid, ident_con(access_uid), name_con(contact_uid, "operand")))
        next_uid += 1
        destination_uid = contact_ids[index + 1] if index + 1 < len(contact_ids) else coil_uid
        wires.append(wire(next_uid, name_con(contact_uid, "out"), name_con(destination_uid, "in")))
        next_uid += 1

    wires.append(wire(next_uid, ident_con(output_access_uid), name_con(coil_uid, "operand")))
    return net


def generate_mode_selector_xml(base: str | Path, output: str | Path, number: str = "3") -> Path:
    tree = ET.parse(base)
    root = tree.getroot()
    fc = root.find("SW.Blocks.FC")
    if fc is None:
        raise RuntimeError("Expected SW.Blocks.FC root object.")

    al = attr(fc)
    text(al, "Name", "FC_ModeSelector_LAD")
    text(al, "Number", str(number))
    text(al, "ProgrammingLanguage", "LAD")

    iface = al.find("Interface")
    if iface is None:
        raise RuntimeError("Missing Interface")
    sections = iface.find(q(IF_NS, "Sections"))
    if sections is None:
        raise RuntimeError("Missing Sections")
    for section in list(sections):
        sections.remove(section)

    input_section = ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Input"})
    for name in INPUT_NAMES:
        input_section.append(member(name, "Bool"))

    output_section = ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Output"})
    for name in OUTPUT_NAMES:
        output_section.append(member(name, "Bool"))

    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "InOut"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Temp"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Constant"})
    return_section = ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Return"})
    return_section.append(member("Ret_Val", "Void"))

    obj = fc.find("ObjectList")
    if obj is None:
        obj = ET.SubElement(fc, "ObjectList")
    for child in list(obj):
        if child.tag == "SW.Blocks.CompileUnit":
            obj.remove(child)

    for index, (title, conditions, output_name) in enumerate(NETWORK_SPECS):
        base_id = 100 + index * 10
        obj.insert(
            index + 1,
            compile_unit(
                str(base_id),
                str(base_id + 1),
                str(base_id + 2),
                title,
                flgnet_series_coil(conditions, output_name),
            ),
        )

    output_path = Path(output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(normalize_xml(root), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create FC_ModeSelector_LAD XML from an exported FC shell.")
    parser.add_argument("--base", required=True, help="Exported FC XML shell.")
    parser.add_argument("--output", required=True, help="Generated LAD FC XML output path.")
    parser.add_argument("--number", default="3", help="FC block number to assign.")
    args = parser.parse_args()

    output = generate_mode_selector_xml(args.base, args.output, args.number)
    print(f"Generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
