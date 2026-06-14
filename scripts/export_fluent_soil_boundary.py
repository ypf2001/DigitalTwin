from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, "")
        return float(value) if value != "" else default
    except (TypeError, ValueError):
        return default


def _find_run_csv(run_dir: Path) -> Path:
    if run_dir.is_file():
        return run_dir
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Cannot find {csv_path}")
    return csv_path


def export_boundary(
    source: Path,
    output: Path,
    water_flow_l_min: float,
    fertilizer_concentration_scale: float,
) -> Path:
    csv_path = _find_run_csv(source)
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig")))
    if not rows:
        raise ValueError(f"No rows in {csv_path}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "time_s",
                "irrigation_mm_h",
                "ec_drip",
                "n_drip",
                "p_drip",
                "k_drip",
            ],
        )
        writer.writeheader()

        for row in rows:
            time_day = _float(row, "time_day")
            q_n = _float(row, "q_n_cmd", _float(row, "q_f_cmd") / 3.0)
            q_p = _float(row, "q_p_cmd", _float(row, "q_f_cmd") / 3.0)
            q_k = _float(row, "q_k_cmd", _float(row, "q_f_cmd") / 3.0)
            q_f = _float(row, "q_f_cmd", q_n + q_p + q_k)
            q_a = _float(row, "q_a_cmd")
            total_liquid = max(water_flow_l_min + q_f + q_a, 1.0e-9)

            writer.writerow(
                {
                    "time_s": f"{time_day * 86400.0:.6f}",
                    "irrigation_mm_h": f"{_float(row, 'irrigation_mm_h'):.9f}",
                    "ec_drip": f"{_float(row, 'ec_drip'):.9f}",
                    "n_drip": f"{fertilizer_concentration_scale * q_n / total_liquid:.9f}",
                    "p_drip": f"{fertilizer_concentration_scale * q_p / total_liquid:.9f}",
                    "k_drip": f"{fertilizer_concentration_scale * q_k / total_liquid:.9f}",
                }
            )

    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export PLC full-season results as Fluent drip-inlet boundary data."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Run directory or full_season_plc_timeseries.csv path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "fluent" / "fluent_soil_boundary.csv",
    )
    parser.add_argument(
        "--water-flow-l-min",
        type=float,
        default=136.0,
        help="Clean-water flow used by the project mixing tank.",
    )
    parser.add_argument(
        "--fertilizer-concentration-scale",
        type=float,
        default=1.0,
        help="Scale q_n/q_p/q_k fractions into Fluent UDS inlet concentration units.",
    )
    args = parser.parse_args()

    out = export_boundary(
        source=args.source,
        output=args.output,
        water_flow_l_min=args.water_flow_l_min,
        fertilizer_concentration_scale=args.fertilizer_concentration_scale,
    )
    print(f"Saved Fluent boundary profile: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
