from __future__ import annotations

import argparse
import copy
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


def member(name: str, datatype: str, version: str | None = None) -> ET.Element:
    kwargs = {"Name": name, "Datatype": datatype}
    if version:
        kwargs["Version"] = version
    return ET.Element(q(IF_NS, "Member"), kwargs)


def access(uid: int, components: list[str], scope: str = "LocalVariable") -> ET.Element:
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


def part(name: str, uid: int, version: str | None = None) -> ET.Element:
    kwargs = {"Name": name, "UId": str(uid)}
    if version:
        kwargs["Version"] = version
    return ET.Element(q(FLG_NS, "Part"), kwargs)


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
    mt_comment = ET.SubElement(obj, "MultilingualText", {"ID": f"{title_id}C", "CompositionName": "Comment"})
    comment_items = ET.SubElement(mt_comment, "ObjectList")
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


def flgnet_ne() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["Remote_Heartbeat"]),
            access(22, ["Last_Heartbeat"]),
            access(23, ["Heartbeat_Changed"]),
        ]
    )
    ne = part("Ne", 24)
    ET.SubElement(ne, q(FLG_NS, "TemplateValue"), {"Name": "SrcType", "Type": "Type"}).text = "Int"
    parts.append(ne)
    parts.append(part("Coil", 25))
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(20, ET.Element(q(FLG_NS, "Powerrail")), name_con(24, "pre")),
            wire(26, ident_con(21), name_con(24, "in1")),
            wire(27, ident_con(22), name_con(24, "in2")),
            wire(28, name_con(24, "out"), name_con(25, "in")),
            wire(29, ident_con(23), name_con(25, "operand")),
        ]
    )
    return net


def flgnet_move() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend(
        [
            access(21, ["Heartbeat_Changed"]),
            access(22, ["Remote_Heartbeat"]),
            access(23, ["Last_Heartbeat"]),
            part("Contact", 24),
        ]
    )
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


def flgnet_ton() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend([access(21, ["Heartbeat_Changed"]), typed_constant(22, "T#3s")])
    contact = part("Contact", 23)
    ET.SubElement(contact, q(FLG_NS, "Negated"), {"Name": "operand"})
    parts.append(contact)
    ton = part("TON", 24, "1.0")
    inst = ET.SubElement(ton, q(FLG_NS, "Instance"), {"Scope": "LocalVariable", "UId": "25"})
    ET.SubElement(inst, q(FLG_NS, "Component"), {"Name": "tWatchdog"})
    ET.SubElement(ton, q(FLG_NS, "TemplateValue"), {"Name": "time_type", "Type": "Type"}).text = "Time"
    parts.append(ton)
    wires = ET.SubElement(net, q(FLG_NS, "Wires"))
    wires.extend(
        [
            wire(26, ET.Element(q(FLG_NS, "Powerrail")), name_con(23, "in")),
            wire(27, ident_con(21), name_con(23, "operand")),
            wire(28, name_con(23, "out"), name_con(24, "IN")),
            wire(29, ident_con(22), name_con(24, "PT")),
            wire(30, name_con(24, "ET"), ET.Element(q(FLG_NS, "OpenCon"), {"UId": "31"})),
        ]
    )
    return net


def flgnet_ok() -> ET.Element:
    net = ET.Element(q(FLG_NS, "FlgNet"))
    parts = ET.SubElement(net, q(FLG_NS, "Parts"))
    parts.extend([access(21, ["tWatchdog", "Q"]), access(22, ["Remote_Comms_OK"])])
    contact = part("Contact", 23)
    ET.SubElement(contact, q(FLG_NS, "Negated"), {"Name": "operand"})
    parts.append(contact)
    parts.append(part("Coil", 24))
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Create FB_CommsWatchdog_LAD XML from an exported empty FB shell.")
    parser.add_argument("--base", required=True, help="Exported FB_CommsWatchdog_LAD XML shell.")
    parser.add_argument("--output", required=True, help="Generated XML output path.")
    args = parser.parse_args()

    tree = ET.parse(args.base)
    root = tree.getroot()
    fb = root.find("SW.Blocks.FB")
    if fb is None:
        raise RuntimeError("Expected SW.Blocks.FB root object.")

    al = attr(fb)
    text(al, "Name", "FB_CommsWatchdog_LAD")
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
    input_section.append(member("Remote_Heartbeat", "Int"))
    output_section = ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Output"})
    output_section.append(member("Remote_Comms_OK", "Bool"))
    output_section.append(member("Watchdog_Timer", "Int"))
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "InOut"})
    static_section = ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Static"})
    static_section.append(member("Last_Heartbeat", "Int"))
    static_section.append(member("Heartbeat_Changed", "Bool"))
    static_section.append(member("tWatchdog", "TON_TIME", "1.0"))
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Temp"})
    ET.SubElement(sections, q(IF_NS, "Section"), {"Name": "Constant"})

    obj = fb.find("ObjectList")
    if obj is None:
        obj = ET.SubElement(fb, "ObjectList")

    for child in list(obj):
        if child.tag == "SW.Blocks.CompileUnit":
            obj.remove(child)

    obj.insert(1, compile_unit("100", "101", "102", "Heartbeat changed", flgnet_ne()))
    obj.insert(2, compile_unit("110", "111", "112", "Store heartbeat", flgnet_move()))
    obj.insert(3, compile_unit("120", "121", "122", "Communication watchdog", flgnet_ton()))
    obj.insert(4, compile_unit("130", "131", "132", "Communication OK", flgnet_ok()))

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
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
    output.write_text("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" + raw, encoding="utf-8")
    print(f"Generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
