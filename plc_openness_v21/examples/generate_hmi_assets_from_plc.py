from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT))

from plc_hmi_codegen import default_scl_path
from create_mode_interlock_lad_xml import generate_mode_interlock_xml
from generate_hmi_wireframes import build_screen
from plc_hmi_codegen import (
    SCREEN_SPECS,
    db1_field_map,
    section_lines,
    validate_screen_tags,
    write_hmi_tag_manifest_csv,
    write_symbol_manifest_csv,
)


def generate_hmi_screens(base_xml: Path, output_dir: Path, scl_path: Path) -> list[Path]:
    field_map = db1_field_map(scl_path)
    validate_screen_tags(field_map)
    outputs: list[Path] = []
    for screen in SCREEN_SPECS:
        sections = [
            (section.title, section_lines(field_map, section.tags), section.rect)
            for section in screen.sections
        ]
        output_path = output_dir / f"{screen.name}.xml"
        build_screen(
            base_xml,
            output_path,
            screen_name=screen.name,
            screen_title=screen.title,
            sections=sections,
        )
        outputs.append(output_path)
    write_symbol_manifest_csv(field_map, output_dir / "DB1_symbol_map.csv")
    write_hmi_tag_manifest_csv(field_map, output_dir / "HMI_tags_from_DB1.csv")
    return outputs


def write_summary(output_path: Path, screen_files: list[Path], lad_file: Path, scl_path: Path) -> Path:
    summary = output_path.resolve()
    summary.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HMI/LAD generation summary",
        "",
        f"SCL source: `{scl_path}`",
        "",
        "Generated HMI screens:",
    ]
    for screen in screen_files:
        lines.append(f"- `{screen}`")
    lines.extend(
        [
            "",
            "Generated manifests:",
            f"- `{output_path.parent / 'DB1_symbol_map.csv'}`",
            f"- `{output_path.parent / 'HMI_tags_from_DB1.csv'}`",
            "",
            "Generated LAD block:",
            f"- `{lad_file}`",
            "",
            "Next import steps:",
            "1. Import the generated HMI screens with `import_hmi_screens.py`.",
            "2. Import the generated LAD block with `import_lad_xml.py`.",
            "3. In TIA Portal, refine control styles and replace wireframe text with final IO controls.",
        ]
    )
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate HMI wireframes, DB1 tag manifests, and HMI-related LAD from xiaweiji.scl.")
    parser.add_argument("--scl", default=str(default_scl_path()), help="Path to xiaweiji.scl.")
    parser.add_argument("--screen-base", required=True, help="Exported HMI screen XML template.")
    parser.add_argument("--screen-output-dir", required=True, help="Directory for generated HMI screen XML files.")
    parser.add_argument("--lad-base", required=True, help="Base FC XML used to regenerate FC_ModeInterlock_LAD.")
    parser.add_argument("--lad-output", required=True, help="Output XML for regenerated FC_ModeInterlock_LAD.")
    parser.add_argument("--summary", required=True, help="Summary markdown output path.")
    args = parser.parse_args()

    scl_path = Path(args.scl).resolve()
    screen_base = Path(args.screen_base).resolve()
    screen_output_dir = Path(args.screen_output_dir).resolve()
    lad_base = Path(args.lad_base).resolve()
    lad_output = Path(args.lad_output).resolve()
    summary = Path(args.summary).resolve()

    screen_files = generate_hmi_screens(screen_base, screen_output_dir, scl_path)
    lad_file = generate_mode_interlock_xml(lad_base, lad_output)
    summary_file = write_summary(summary, screen_files, lad_file, scl_path)

    for screen in screen_files:
        print(f"Generated {screen}")
    print(f"Generated {lad_file}")
    print(f"Generated {screen_output_dir / 'DB1_symbol_map.csv'}")
    print(f"Generated {screen_output_dir / 'HMI_tags_from_DB1.csv'}")
    print(f"Generated {summary_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
