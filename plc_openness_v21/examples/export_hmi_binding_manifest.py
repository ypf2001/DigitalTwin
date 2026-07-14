from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from pathlib import Path


def load_redesign_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("redesign_hmi_real_controls", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def writable_control(control: str) -> str:
    return "Yes" if control in {"io_rw", "switch_rw", "button", "button_alarm", "symbolic"} else "No"


def object_name(control: str, tag: str) -> str:
    if control in {"io_rw", "io_ro"}:
        return f"IO_{tag}"
    if control == "symbolic":
        return f"Sym_{tag}"
    if control in {"switch_rw", "switch_ro"}:
        return f"Sw_{tag}"
    if control in {"button", "button_alarm"}:
        return f"Btn_{tag}"
    return f"Obj_{tag}"


def usage_note(control: str) -> str:
    notes = {
        "io_rw": "数值输入/输出，绑定到 HMI 变量后可写",
        "io_ro": "数值显示，只读显示",
        "symbolic": "符号/枚举输入，建议绑定阶段或枚举量",
        "switch_rw": "可切换开关，绑定可写 Bool 变量",
        "switch_ro": "状态指示开关，建议只读显示",
        "button": "操作按钮，绑定可写 Bool 或事件写值",
        "button_alarm": "报警/急停按钮，绑定可写 Bool 或事件写值",
    }
    return notes.get(control, "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export HMI control binding manifest from redesigned screen spec.")
    parser.add_argument("--script", required=True, help="Path to redesign_hmi_real_controls.py")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    script_path = Path(args.script).resolve()
    output_path = Path(args.output).resolve()
    module = load_redesign_module(script_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Screen",
                "Section",
                "ControlObjectName",
                "ControlType",
                "Writable",
                "HmiVariable",
                "PlcVariable",
                "BindingNote",
            ]
        )

        for screen_name, screen_spec in module.SCREEN_SPECS.items():
            for row in screen_spec.top_buttons:
                writer.writerow(
                    [
                        screen_name,
                        "TopButtons",
                        f"BtnTop_{row.tag}",
                        row.control,
                        writable_control(row.control),
                        row.tag,
                        row.tag,
                        usage_note(row.control),
                    ]
                )

            for section in screen_spec.sections:
                for row in section.rows:
                    writer.writerow(
                        [
                            screen_name,
                            section.title,
                            object_name(row.control, row.tag),
                            row.control,
                            writable_control(row.control),
                            row.tag,
                            row.tag,
                            usage_note(row.control),
                        ]
                    )

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
