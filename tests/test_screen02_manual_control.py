import xml.etree.ElementTree as ET
from pathlib import Path

from plc_openness_v21.examples.redesign_screen02_manual_control import redesign


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plc_openness_v21" / "generated_hmi" / "live_screen2_after_nav_events.xml"


def _find_by_name(root: ET.Element, object_name: str) -> ET.Element:
    for node in root.findall(".//*[@CompositionName='ScreenItems']"):
        if node.findtext("./AttributeList/ObjectName") == object_name:
            return node
    raise AssertionError(f"Missing HMI object: {object_name}")


def _bit_actions(node: ET.Element) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    for entry in node.findall(".//Hmi.Event.FunctionListEntry"):
        function_name = entry.findtext("./AttributeList/Name") or ""
        if function_name not in {"SetBit", "ResetBit"}:
            continue
        tag = ""
        for param in entry.findall(".//Hmi.Event.FunctionListEntryParameter"):
            name = param.findtext("./AttributeList/Name")
            if name == "Tag":
                tag = param.findtext("./LinkList/Value/Name") or ""
        actions.append((function_name, tag.strip('"')))
    return actions


def test_screen02_mode_buttons_and_bindings(tmp_path):
    output = tmp_path / "Screen_02_ManualControl.xml"
    redesign(SOURCE, output)
    root = ET.parse(output).getroot()

    assert _bit_actions(_find_by_name(root, "BtnMode_Manual")) == [
        ("SetBit", "DB1.Manual_Mode"),
        ("ResetBit", "DB1.Auto_Mode"),
    ]
    assert _bit_actions(_find_by_name(root, "BtnMode_Auto")) == [
        ("ResetBit", "DB1.Manual_Mode"),
        ("SetBit", "DB1.Auto_Mode"),
    ]
    assert _bit_actions(_find_by_name(root, "BtnMode_EStop")) == [
        ("SetBit", "DB1.Emergency_Stop")
    ]
    assert _bit_actions(_find_by_name(root, "BtnMode_Reset")) == [
        ("ResetBit", "DB1.Emergency_Stop")
    ]

    expected_bindings = {
        "DB1.Manual_Active",
        "DB1.Auto_Active",
        "DB1.SAC_Enable",
        "DB1.Emergency_Stop",
        "DB1.EC_Set_SP",
        "DB1.pH_Set_SP",
        "DB1.EC_Actual",
        "DB1.pH_Actual",
        "DB1.q_f_cmd",
        "DB1.q_a_cmd",
        "DB1.q_n_cmd",
        "DB1.q_p_cmd",
        "DB1.q_k_cmd",
    }
    actual_bindings: set[str] = set()
    for prop in root.findall(".//Hmi.Screen.Property"):
        if prop.findtext("./AttributeList/Name") != "ProcessValue":
            continue
        tag_name = prop.findtext(".//Tag/Name")
        if tag_name:
            actual_bindings.add(tag_name.strip('"'))
    assert actual_bindings == expected_bindings

    xml_text = ET.tostring(root, encoding="unicode")
    assert "本地模式" in xml_text
    assert "联网模式" in xml_text
