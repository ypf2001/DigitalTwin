"""Evaluate an existing PLC decoupler A/B summary without touching the PLC."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plc_control.ab_validation import evaluate_ab_summary, load_ab_criteria, summarize_ab_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--criteria", type=Path, default=ROOT / "config" / "decoupler_ab.yaml")
    parser.add_argument("--raw-csv", type=Path, default=None,
                        help="Raw A/B CSV; defaults to ab_results.csv beside the summary.")
    args = parser.parse_args()
    previous_summary = json.loads(args.summary.read_text(encoding="utf-8"))
    criteria = load_ab_criteria(args.criteria)
    raw_csv = args.raw_csv or args.summary.with_name("ab_results.csv")
    with raw_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    summary = summarize_ab_rows(
        rows,
        baseline_window_s=float(criteria.get("baseline_window_s", 120.0)),
    )
    for key in ("point", "raw_samples"):
        if key in previous_summary:
            summary[key] = previous_summary[key]
    summary["reanalyzed_from"] = str(raw_csv)
    verdict = evaluate_ab_summary(summary, criteria)
    summary["verdict"] = verdict
    summary_output = args.summary.with_name("summary_reanalyzed.json")
    output = args.summary.with_name("ab_verdict_reanalyzed.json")
    summary_output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    output.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    print(f"Saved reanalyzed summary: {summary_output}")
    print(f"Saved verdict: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
