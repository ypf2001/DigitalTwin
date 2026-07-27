from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _resolve_csv(input_path: Path) -> Path:
    if input_path.is_dir():
        for name in ("lifecycle_outlet_stability.csv", "plc_setpoint_step.csv", "full_season_plc_timeseries.csv"):
            candidate = input_path / name
            if candidate.exists():
                return candidate
    if input_path.exists():
        return input_path
    raise FileNotFoundError(input_path)


def _column(rows: list[dict[str, str]], *names: str, default: float = 0.0) -> np.ndarray:
    for name in names:
        if rows and name in rows[0]:
            return np.array([float(row.get(name, default) or default) for row in rows], dtype=float)
    return np.full(len(rows), default, dtype=float)


def plot(input_path: Path, output_path: Path | None = None) -> Path:
    csv_path = _resolve_csv(input_path)
    rows = _read_rows(csv_path)
    if not rows:
        raise RuntimeError(f"No rows in {csv_path}")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    font_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"

    time_s = _column(rows, "time_s", default=np.nan)
    if np.isnan(time_s).all():
        time_s = np.arange(len(rows), dtype=float)
        x_label = "采样次数"
    else:
        x_label = "时间 (s)"

    ec_set = _column(rows, "ec_set", "target_ec")
    ec_actual = _column(rows, "ec_actual", "ec_drip", "ec_soil")
    ph_set = _column(rows, "ph_set", "target_ph")
    ph_actual = _column(rows, "ph_actual", "ph_drip", "soil_ph_est")

    ec_band = 0.1
    ph_band = 0.2

    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(10.5, 7.2), sharex=True)

    ax_ec.fill_between(
        time_s,
        ec_set - ec_band,
        ec_set + ec_band,
        color="#d9ead3",
        alpha=0.75,
        label="允许误差带 ±0.1 mS/cm",
        linewidth=0,
    )
    ax_ec.step(time_s, ec_set, where="post", color="#1b5e20", linestyle="--", linewidth=1.4, label="目标设定值")
    ax_ec.plot(time_s, ec_actual, color="#2e7d32", linewidth=1.8, label="实际测量值")
    ax_ec.set_ylabel("EC (mS/cm)")
    ax_ec.set_title("EC 控制精度")

    ax_ph.fill_between(
        time_s,
        ph_set - ph_band,
        ph_set + ph_band,
        color="#dbe8f6",
        alpha=0.8,
        label="允许误差带 ±0.2 pH",
        linewidth=0,
    )
    ax_ph.step(time_s, ph_set, where="post", color="#174a7c", linestyle="--", linewidth=1.4, label="目标设定值")
    ax_ph.plot(time_s, ph_actual, color="#2f6da5", linewidth=1.8, label="实际测量值")
    ax_ph.set_ylabel("pH 值")
    ax_ph.set_xlabel(x_label)
    ax_ph.set_title("pH 控制精度")

    stage_starts: dict[str, float] = {}
    if rows and "stage" in rows[0]:
        for row, x in zip(rows, time_s):
            stage = str(row.get("stage", "")).strip()
            if stage and stage not in stage_starts:
                stage_starts[stage] = float(x)

    for ax in (ax_ec, ax_ph):
        for stage, x in stage_starts.items():
            ax.axvline(x, color="#999999", linestyle=":", linewidth=0.8)
            ax.text(x, 0.98, stage, transform=ax.get_xaxis_transform(), va="top", ha="left", fontsize=9, color="#555555")
        ax.grid(True, axis="y", color="#dddddd", linewidth=0.7)
        ax.legend(loc="best", frameon=True, framealpha=0.92, edgecolor="#cccccc")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out")

    fig.tight_layout()
    if output_path is None:
        output_path = csv_path.parent / "ec_ph_control_precision.png"
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot thesis-style EC/pH control precision with tolerance bands.")
    parser.add_argument("input", type=Path, help="Run directory or CSV path.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    plot(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
