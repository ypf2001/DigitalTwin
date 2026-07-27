from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


SCREENS = (
    "Screen_01_MainOverview",
    "Screen_02_ManualControl",
    "Screen_03_PID_Settings",
    "Screen_04_AlarmsDiagnostics",
)

THREE_DECIMAL_TAGS = {
    "DB1.Kp_EC_Set",
    "DB1.Ki_EC_Set",
    "DB1.Kd_EC_Set",
    "DB1.Kp_pH_Set",
    "DB1.Ki_pH_Set",
    "DB1.Kd_pH_Set",
    "DB1.EC_Trim_Band",
    "DB1.pH_Trim_Band",
    "DB1.N_Ratio",
    "DB1.P_Ratio",
    "DB1.K_Ratio",
    "DB1.N_Target",
    "DB1.P_Target",
    "DB1.K_Target",
    "DB1.N_Actual",
    "DB1.P_Actual",
    "DB1.K_Actual",
}

INTEGER_TAG_KEYWORDS = (
    "AQ_Valve_",
    "Heartbeat",
    "Watchdog",
)

INTEGER_EXACT_TAGS = {
    "DB1.Growth_Stage",
}


def object_to_tag(object_name: str) -> str | None:
    for prefix in ("IO_DB1.", "Sw_DB1.", "Sym_DB1."):
        if object_name.startswith(prefix):
            return "DB1." + object_name.split("DB1.", 1)[1]
    return None


def pattern_for_tag(tag_name: str) -> str | None:
    if tag_name in INTEGER_EXACT_TAGS:
        return None
    for keyword in INTEGER_TAG_KEYWORDS:
        if keyword in tag_name:
            return "99999"
    if tag_name in THREE_DECIMAL_TAGS:
        return "0.000"
    return "0.00"


def patch_screen(src: Path, dst: Path) -> int:
    tree = ET.parse(src)
    root = tree.getroot()
    changed = 0

    for elem in root.iter():
        if elem.tag != "Hmi.Screen.IOField" or elem.get("CompositionName") != "ScreenItems":
            continue
        object_name = elem.findtext("./AttributeList/ObjectName")
        if not object_name:
            continue
        tag_name = object_to_tag(object_name)
        if not tag_name:
            continue
        pattern = pattern_for_tag(tag_name)
        if pattern is None:
            continue
        pattern_elem = elem.find("./AttributeList/FormatPattern")
        if pattern_elem is None:
            continue
        if pattern_elem.text != pattern:
            pattern_elem.text = pattern
            changed += 1

    ET.indent(root)
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Update HMI IOField decimal display for REAL tags.")
    parser.add_argument("--src-dir", required=True, help="Source directory of screen XML files.")
    parser.add_argument("--dst-dir", required=True, help="Output directory for patched screen XML files.")
    args = parser.parse_args()

    src_dir = Path(args.src_dir).resolve()
    dst_dir = Path(args.dst_dir).resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)

    for screen_name in SCREENS:
        src = src_dir / f"{screen_name}.xml"
        dst = dst_dir / f"{screen_name}.xml"
        changed = patch_screen(src, dst)
        print(f"{screen_name}: changed={changed}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
