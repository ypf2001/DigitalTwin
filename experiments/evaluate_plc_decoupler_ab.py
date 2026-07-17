"""Evaluate an existing PLC decoupler A/B summary without touching the PLC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_control.ab_validation import evaluate_ab_summary, load_ab_criteria


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--criteria", type=Path, default=ROOT / "config" / "decoupler_ab.yaml")
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    verdict = evaluate_ab_summary(summary, load_ab_criteria(args.criteria))
    output = args.summary.with_name("ab_verdict.json")
    output.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    print(f"Saved verdict: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
