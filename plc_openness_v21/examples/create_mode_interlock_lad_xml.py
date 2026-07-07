from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


FLG_NS = "http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v4"
IF_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def attr(parent: ET.Element) -> ET.Element:
    node = parent.find("AttributeList")
    if node is None:
        raise RuntimeError(f"Missing AttributeList under {parent.tag}")
    return node


def text(parent: ET.Element, path: str, value: str) -> None:
    node = parent.find(path)
    if node is None:
        raise RuntimeError(f"Missing {path}")
    node.text = value


def member(name: str, datatype: str) -> ET.Element:
    return ET.Element(q(IF_NS, "Member"), {"Name": name, "Datatype": datatype})


def access(uid: int, components: list[str], scope: str = "GlobalVariable") -> ET.Element:
    node = ET.Element(q(FLG_NS, "Access"), {"Scope": scope, "UId": str(uid)})
    symbol = ET.SubElement(node, q(FLG_NS, "Symbol"))
    for component in components:
        ET.SubElement(symbol, q(FLG_NS, "Component"), {"Name": component})
    return node


def typed_constant(uid: int, value: str) -> ET.Element:
    node = ET.Element(q(FLG_NS, "Access"), {"Scope": "TypedConstant", "UId": str(uid)})
    const = ET.SubElement(node, q(FLG_NS, "Constant"))
    ET.SubElement(const, q(FLG_NS, "ConstantValue")).text = value
    return node


def part(name: str, uid: int, negated: bool = False) -> ET.Element:
    node = ET.Element(q(FLG_NS, "Part"), {"Name": name, "UId": str(uid)})
    if negated:
        ET.SubElement(node, q(FLG_NS, "Negated"), {"Name": "operand"})
    return node


def name_con(uid: int, name: str) -> ET.Element:
    return ET.Element(q(FLG_NS, "NameCon"), {"UId": str(uid), "Name": name})


def ident_con(uid: int) -> ET.Element:
    return ET.Element(q(FLG_NS, "IdentCon"), {"UId": str(uid)})


def wire(uid: int, *children: ET.Element) -> ET.Element:
    node = ET.Element(q(FLG_NS, "Wire"), {"UId": str(uid)})
    for child in children:
        node.append(child)
    return node


def compile_unit(unit_id: str, title_id: str, item_id: str, title: str, flgnet: ET.Element) -> ET.Element:
    unit = ET.Element("SW.Blocks.CompileUnit", {"ID": unit_id, "CompositionName": "CompileUnits"})
    al = ET.SubElement(unit, "AttributeList")
    ns = ET.SubElement(al, "NetworkSource")
    ns.append(flgnet)
    ET.SubElement(al, "ProgrammingLanguage").text = "LAD"

    obj = ET.SubElement(unit, "ObjectList")
    comment = ET.SubElement(obj, "MultilingualText", {"ID": f"{title_id}C", "CompositionName": "Comment"})
    comment_items = ET.SubElement(comment, "ObjectList")
    comment_item = ET.SubElement(comment_items, "MultilingualTextItem", {"ID": f"{item_id}C", "CompositionName": "Items"})
    comment_attr = ET.SubElement(comment_item, "AttributeList")
    ET.SubElement(comment_attr, "Culture").text = "zh-CN"
    ET.SubElement(comment_attr, "Text").text = ""

    mt_title = ET.SubElement(obj, "MultilingualText", {"ID": title_id, "CompositionName": "Title"})
    title_items = ET.SubElement(mt_title, "ObjectList")
    title_item = ET.SubElement(title_items, "MultilingualTextItem", {"ID": item_id, "CompositionName": "Items"})
    title_attr = ET.SubElement(title_item, "AttributeList")
    ET.SubElement(title_attr, "Culture").text = "zh-CN"
    ET.SubElement(title_attr, "Text").text = title
    return unit


def flgnet_comm_normal() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["DB1", "Remote_Comms_OK"]),
            access(22, ["DB1", "Emergency_Stop"]),
            access(23, ["DB1", "Comm_Normal"]),
            part("Contact", 24),
            part("Contact", 25, negated=True),
            part("Coil", 26),
        ]
    )
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(27, ET.Element(q(FLG_NS, "Powerrail")), name_con(24, "in")),
            wire(28, ident_con(21), name_con(24, "operand")),
            wire(29, name_con(24, "out"), name_con(25, "in")),
            wire(30, ident_con(22), name_con(25, "operand")),
            wire(31, name_con(25, "out"), name_con(26, "in")),
            wire(32, ident_con(23), name_con(26, "operand")),
        ]
    )
    return net


def flgnet_manual_active() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["DB1", "Emergency_Stop"]),
            access(22, ["DB1", "Manual_Mode"]),
            access(23, ["DB1", "Manual_Active"]),
            part("Contact", 24, negated=True),
            part("Contact", 25),
            part("Coil", 26),
        ]
    )
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(27, ET.Element(q(FLG_NS, "Powerrail")), name_con(24, "in")),
            wire(28, ident_con(21), name_con(24, "operand")),
            wire(29, name_con(24, "out"), name_con(25, "in")),
            wire(30, ident_con(22), name_con(25, "operand")),
            wire(31, name_con(25, "out"), name_con(26, "in")),
            wire(32, ident_con(23), name_con(26, "operand")),
        ]
    )
    return net


def flgnet_auto_active() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["DB1", "Emergency_Stop"]),
            access(22, ["DB1", "Manual_Mode"]),
            access(23, ["DB1", "Auto_Mode"]),
            access(26, ["DB1", "Auto_Active"]),
            part("Contact", 24, negated=True),
            part("Contact", 25, negated=True),
            part("Contact", 27),
            part("Coil", 28),
        ]
    )
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(29, ET.Element(q(FLG_NS, "Powerrail")), name_con(24, "in")),
            wire(30, ident_con(21), name_con(24, "operand")),
            wire(31, name_con(24, "out"), name_con(25, "in")),
            wire(32, ident_con(22), name_con(25, "operand")),
            wire(33, name_con(25, "out"), name_con(27, "in")),
            wire(34, ident_con(23), name_con(27, "operand")),
            wire(35, name_con(27, "out"), name_con(28, "in")),
            wire(36, ident_con(26), name_con(28, "operand")),
        ]
    )
    return net


def flgnet_manual_pump_valve_enable() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["DB1", "Manual_Active"]),
            access(22, ["DB1", "Comm_Normal"]),
            access(23, ["DB1", "Manual_PumpValve_Enable"]),
            part("Contact", 24),
            part("Contact", 25),
            part("Coil", 26),
        ]
    )
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(27, ET.Element(q(FLG_NS, "Powerrail")), name_con(24, "in")),
            wire(28, ident_con(21), name_con(24, "operand")),
            wire(29, name_con(24, "out"), name_con(25, "in")),
            wire(30, ident_con(22), name_con(25, "operand")),
            wire(31, name_con(25, "out"), name_con(26, "in")),
            wire(32, ident_con(23), name_con(26, "operand")),
        ]
    )
    return net


def flgnet_alarm_light() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["DB1", "Comm_Normal"]),
            access(22, ["DB1", "System_Alarm_Light"]),
            part("Contact", 23, negated=True),
            part("Coil", 24),
        ]
    )
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(25, ET.Element(q(FLG_NS, "Powerrail")), name_con(23, "in")),
            wire(26, ident_con(21), name_con(23, "operand")),
            wire(27, name_con(23, "out"), name_con(24, "in")),
            wire(28, ident_con(22), name_con(24, "operand")),
        ]
    )
    return net


def flgnet_move_manual_value(source: str, target: str, enabled: bool) -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.append(access(21, ["DB1", "Manual_PumpValve_Enable"]))
    if enabled:
        parts.append(access(22, ["DB1", source]))
    else:
        parts.append(typed_constant(22, "0.0"))
    parts.append(access(23, ["DB1", target]))
    parts.append(part("Contact", 24, negated=not enabled))
    move = part("Move", 25)
    ET.SubElement(move, q(FLG_NS, "TemplateValue"), {"Name": "Card", "Type": "Cardinality"}).text = "1"
    parts.append(move)
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(26, ET.Element(q(FLG_NS, "Powerrail")), name_con(24, "in")),
            wire(27, ident_con(21), name_con(24, "operand")),
            wire(28, name_con(24, "out"), name_con(25, "en")),
            wire(29, ident_con(22), name_con(25, "in")),
            wire(30, ident_con(23), name_con(25, "out")),
        ]
    )
    return net


def normalize_xml(root: ET.Element) -> str:
    raw = ET.tostring(root, encoding="unicode")
    raw = raw.replace(f' xmlns:ns0="{IF_NS}"', "")
    raw = raw.replace(f' xmlns:ns1="{FLG_NS}"', "")
    raw = raw.replace("<ns0:Sections>", f'<Sections xmlns="{IF_NS}">')
    raw = raw.replace("</ns0:Sections>", "</Sections>")
    raw = raw.replace("<ns0:Section", "<Section")
    raw = raw.replace("</ns0:Section>", "</Section>")
    raw = raw.replace("<ns0:Member", "<Member")
    raw = raw.replace("</ns0:Member>", "</Member>")
    raw = raw.replace("<ns1:FlgNet>", f'<FlgNet xmlns="{FLG_NS}">')
    raw = raw.replace("</ns1:FlgNet>", "</FlgNet>")
    raw = raw.replace("ns1:", "")
    raw = raw.replace(":ns1", "")
    return "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" + raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Create FC_ModeInterlock_LAD XML from an exported FC shell.")
    parser.add_argument("--base", required=True, help="Exported FC XML shell.")
    parser.add_argument("--output", required=True, help="Generated LAD FC XML output path.")
    parser.add_argument("--number", default="2", help="FC block number to assign.")
    args = parser.parse_args()

    tree = ET.parse(args.base)
    root = tree.getroot()
    fc = root.find("SW.Blocks.FC")
    if fc is None:
        raise RuntimeError("Expected SW.Blocks.FC root object.")

    al = attr(fc)
    text(al, "Name", "FC_ModeInterlock_LAD")
    text(al, "Number", str(args.number))
    text(al, "ProgrammingLanguage", "LAD")

    iface = al.find("Interface")
    if iface is None:
        raise RuntimeError("Missing Interface")
    sections = iface.find(q(IF_NS, "Sections"))
    if sections is None:
        raise RuntimeError("Missing Sections")
    for section in list(sections):
        sections.remove(section)

    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Input"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Output"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "InOut"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Temp"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Constant"})
    ret = ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Return"})
    ret.append(member("Ret_Val", "Void"))

    obj = fc.find("ObjectList")
    if obj is None:
        obj = ET.SubElement(fc, "ObjectList")
    for child in list(obj):
        if child.tag == "SW.Blocks.CompileUnit":
            obj.remove(child)

    obj.insert(1, compile_unit("100", "101", "102", "Communication normal", flgnet_comm_normal()))
    obj.insert(2, compile_unit("110", "111", "112", "Manual active interlock", flgnet_manual_active()))
    obj.insert(3, compile_unit("120", "121", "122", "Auto active interlock", flgnet_auto_active()))
    obj.insert(4, compile_unit("130", "131", "132", "Manual pump valve enable", flgnet_manual_pump_valve_enable()))
    obj.insert(5, compile_unit("140", "141", "142", "Alarm light", flgnet_alarm_light()))
    obj.insert(6, compile_unit("150", "151", "152", "Select manual q_f", flgnet_move_manual_value("Manual_q_f_Set", "Manual_q_f_Selected", True)))
    obj.insert(7, compile_unit("160", "161", "162", "Select manual q_a", flgnet_move_manual_value("Manual_q_a_Set", "Manual_q_a_Selected", True)))

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(normalize_xml(root), encoding="utf-8")
    print(f"Generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
