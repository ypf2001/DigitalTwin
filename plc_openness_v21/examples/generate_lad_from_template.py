from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_replace(values: list[str]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --replace value '{value}'. Expected OLD=NEW.")
        old, new = value.split("=", 1)
        replacements[old] = new
    return replacements


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a new LAD XML file from an exported TIA XML template.")
    parser.add_argument("--template", required=True, help="Input template XML path.")
    parser.add_argument("--output", required=True, help="Generated XML output path.")
    parser.add_argument(
        "--replace",
        action="append",
        default=[],
        help="Text replacement OLD=NEW. Can be used multiple times.",
    )
    parser.add_argument("--replace-json", help="JSON file containing {\"OLD\": \"NEW\"} replacements.")
    args = parser.parse_args()

    template = Path(args.template).resolve()
    output = Path(args.output).resolve()
    if not template.exists():
        raise FileNotFoundError(template)

    replacements = parse_replace(args.replace)
    if args.replace_json:
        with Path(args.replace_json).resolve().open("r", encoding="utf-8") as f:
            replacements.update(json.load(f))

    text = template.read_text(encoding="utf-8-sig")
    for old, new in replacements.items():
        text = text.replace(old, new)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Generated LAD XML: {output}")
    print(f"Applied replacements: {len(replacements)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
