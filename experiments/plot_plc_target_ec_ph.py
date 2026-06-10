from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def plot(run_dir: Path) -> Path:
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    rows = _read_rows(csv_path)
    if not rows:
        raise RuntimeError(f"No data rows in {csv_path}")

    simhei_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if simhei_path.exists():
        fm.fontManager.addfont(str(simhei_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    day = np.array([float(row["time_day"]) for row in rows], dtype=float)
    ec_soil = np.array([float(row["ec_soil"]) for row in rows], dtype=float)
    ec_target = np.array([float(row["target_ec"]) for row in rows], dtype=float)
    ph_soil = np.array([float(row["soil_ph_est"]) for row in rows], dtype=float)
    ph_target = np.array([float(row["ph_set"]) for row in rows], dtype=float)

    ec_mae = float(np.mean(np.abs(ec_soil - ec_target)))
    ph_mae = float(np.mean(np.abs(ph_soil - ph_target)))
    ec_over = float(np.max(np.maximum(ec_soil - ec_target, 0.0)))
    ph_over = float(np.max(np.maximum(ph_soil - ph_target, 0.0)))

    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(12, 7.4), sharex=True)

    ax_ec.plot(day, ec_soil, color="#16784f", linewidth=1.4, label="实际根区 EC")
    ax_ec.step(day, ec_target, where="post", color="#0f5132", linestyle="--", linewidth=1.3, label="目标 EC")
    ax_ec.set_ylabel("EC (dS/m)")
    ax_ec.set_title(f"EC 目标跟踪  MAE={ec_mae:.4f}, 最大超调={ec_over:.4f}")
    ax_ec.grid(True, axis="y", color="#dddddd", linewidth=0.7)
    ax_ec.legend(loc="best")

    ax_ph.plot(day, ph_soil, color="#2f65a7", linewidth=1.4, label="实际/估算根区 pH")
    ax_ph.step(day, ph_target, where="post", color="#1d4e89", linestyle="--", linewidth=1.3, label="目标 pH")
    ax_ph.set_ylabel("pH")
    ax_ph.set_xlabel("生育期天数")
    ax_ph.set_title(f"pH 目标跟踪  MAE={ph_mae:.4f}, 最大超调={ph_over:.4f}")
    ax_ph.grid(True, axis="y", color="#dddddd", linewidth=0.7)
    ax_ph.legend(loc="best")

    for ax in (ax_ec, ax_ph):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlim(float(day.min()), float(day.max()))

    fig.tight_layout()
    out_path = run_dir / "target_ec_ph_tracking.png"
    fig.savefig(out_path, dpi=220)
    plt.close(fig)
    print(f"Saved: {out_path}")
    print(f"EC_MAE={ec_mae:.6f}, pH_MAE={ph_mae:.6f}, EC_over={ec_over:.6f}, pH_over={ph_over:.6f}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot PLC full-season EC/pH targets against actual curves.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    plot(args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
