from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


STAGE_ORDER = ("INI", "DEV", "MID", "LATE")


def _latest_run_dir(root: Path) -> Path:
    runs = [p for p in root.iterdir() if p.is_dir() and (p / "full_season_plc_timeseries.csv").exists()]
    if not runs:
        raise FileNotFoundError(f"No full-season PLC runs found under {root}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _col(rows: list[dict[str, str]], name: str) -> np.ndarray:
    return np.array([float(row[name]) for row in rows], dtype=float)


def _stage_step_target(rows: list[dict[str, str]], column: str) -> np.ndarray:
    """Draw paper targets as hard stage setpoints, separate from controller ramps."""
    raw = _col(rows, column)
    stage_series = [str(row.get("stage", "")).upper() for row in rows]
    seen_stages = [stage for stage in STAGE_ORDER if stage in stage_series]
    if not seen_stages:
        return raw

    stage_values: dict[str, float] = {}
    for stage in seen_stages:
        idx = np.array([i for i, row_stage in enumerate(stage_series) if row_stage == stage], dtype=int)
        stable_idx = idx[len(idx) // 2 :]
        stage_values[stage] = float(np.median(raw[stable_idx if stable_idx.size else idx]))

    return np.array([stage_values.get(stage, raw[i]) for i, stage in enumerate(stage_series)], dtype=float)


def _smooth(values: np.ndarray, window: int = 5) -> np.ndarray:
    if window <= 1 or values.size < window:
        return values
    kernel = np.ones(window, dtype=float) / window
    pad_left = window // 2
    pad_right = window - 1 - pad_left
    padded = np.pad(values, (pad_left, pad_right), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _configure_fonts() -> None:
    for font_path in (
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    ):
        if font_path.exists():
            fm.fontManager.addfont(str(font_path))
    plt.rcParams["font.sans-serif"] = ["SimSun", "SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["font.family"] = ["sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.fontset"] = "dejavuserif"


def _style_axis(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(direction="in", width=0.8, length=3.5, labelsize=9)
    ax.grid(False)


def _set_day_axis(ax: plt.Axes, day: np.ndarray) -> None:
    upper = float(np.ceil(day.max() / 20.0) * 20.0)
    ax.set_xlim(0.0, upper)
    ax.set_xticks(np.arange(0.0, upper + 0.1, 20.0))


def _plot_single(
    *,
    day: np.ndarray,
    actual: np.ndarray,
    target: np.ndarray,
    ylabel: str,
    actual_label: str,
    target_label: str,
    caption_cn: str,
    out_path: Path,
    ylim: tuple[float, float],
    yticks: np.ndarray,
) -> None:
    fig, ax = plt.subplots(figsize=(5.3, 3.35))

    ax.plot(day, actual, color="black", linewidth=1.15, label=actual_label)
    ax.step(day, target, where="post", color="black", linestyle="--", linewidth=1.0, label=target_label)

    _set_day_axis(ax, day)
    ax.set_ylim(*ylim)
    ax.set_yticks(yticks)
    ax.set_xlabel("生育期天数/d", fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    _style_axis(ax)
    ax.legend(frameon=False, loc="best", fontsize=9, handlelength=2.6)

    fig.subplots_adjust(left=0.15, right=0.97, top=0.95, bottom=0.29)
    fig.text(0.5, 0.055, caption_cn, ha="center", va="center", fontsize=10)
    fig.savefig(out_path, dpi=320, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def plot(run_dir: Path) -> dict[str, str | float]:
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    rows = _read_rows(csv_path)
    if not rows:
        raise RuntimeError(f"No data rows in {csv_path}")

    _configure_fonts()

    day = _col(rows, "time_day")
    ec_actual = _smooth(_col(rows, "ec_soil"), window=5)
    ec_target = _stage_step_target(rows, "target_ec")
    ph_actual = _smooth(_col(rows, "soil_ph_est"), window=5)
    ph_target = _stage_step_target(rows, "target_ph")

    ec_mae = float(np.mean(np.abs(ec_actual - ec_target)))
    ph_mae = float(np.mean(np.abs(ph_actual - ph_target)))
    ec_max_abs = float(np.max(np.abs(ec_actual - ec_target)))
    ph_max_abs = float(np.max(np.abs(ph_actual - ph_target)))

    ec_path = run_dir / "soil_ec_current_target_paper_style.png"
    ph_path = run_dir / "soil_ph_current_target_paper_style.png"
    combined_path = run_dir / "soil_ec_ph_current_target_paper_style.png"

    _plot_single(
        day=day,
        actual=ec_actual,
        target=ec_target,
        ylabel="土壤EC/(dS·m$^{-1}$)",
        actual_label="当前土壤EC",
        target_label="目标土壤EC",
        caption_cn="图 16  当前土壤EC与目标土壤EC对比",
        out_path=ec_path,
        ylim=(0.0, 1.6),
        yticks=np.arange(0.0, 1.61, 0.2),
    )

    _plot_single(
        day=day,
        actual=ph_actual,
        target=ph_target,
        ylabel="土壤pH",
        actual_label="当前土壤pH",
        target_label="目标土壤pH",
        caption_cn="图 17  当前土壤pH与目标土壤pH对比",
        out_path=ph_path,
        ylim=(5.5, 6.5),
        yticks=np.arange(5.5, 6.51, 0.1),
    )

    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(6.1, 6.2), sharex=True)
    ax_ec.plot(day, ec_actual, color="black", linewidth=1.15, label="当前土壤EC")
    ax_ec.step(day, ec_target, where="post", color="black", linestyle="--", linewidth=1.0, label="目标土壤EC")
    ax_ec.set_ylabel("土壤EC/(dS·m$^{-1}$)", fontsize=10)
    ax_ec.set_ylim(0.0, 1.6)
    ax_ec.set_yticks(np.arange(0.0, 1.61, 0.2))
    ax_ec.legend(frameon=False, loc="best", fontsize=9, handlelength=2.6)

    ax_ph.plot(day, ph_actual, color="black", linewidth=1.15, label="当前土壤pH")
    ax_ph.step(day, ph_target, where="post", color="black", linestyle="--", linewidth=1.0, label="目标土壤pH")
    ax_ph.set_ylabel("土壤pH", fontsize=10)
    ax_ph.set_xlabel("生育期天数/d", fontsize=10)
    ax_ph.set_ylim(5.5, 6.5)
    ax_ph.set_yticks(np.arange(5.5, 6.51, 0.1))
    ax_ph.legend(frameon=False, loc="best", fontsize=9, handlelength=2.6)

    for ax in (ax_ec, ax_ph):
        _set_day_axis(ax, day)
        _style_axis(ax)

    fig.subplots_adjust(left=0.16, right=0.97, top=0.97, bottom=0.12, hspace=0.32)
    fig.savefig(combined_path, dpi=320, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

    summary = {
        "run_dir": str(run_dir),
        "ec_image": str(ec_path),
        "ph_image": str(ph_path),
        "combined_image": str(combined_path),
        "ec_mae": ec_mae,
        "ph_mae": ph_mae,
        "ec_max_abs_error": ec_max_abs,
        "ph_max_abs_error": ph_max_abs,
    }
    summary_path = run_dir / "soil_current_target_metrics.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot current soil EC/pH against stage target soil EC/pH.")
    parser.add_argument(
        "run_dir",
        nargs="?",
        type=Path,
        help="Full-season PLC result directory. Defaults to the latest run.",
    )
    args = parser.parse_args()
    run_dir = args.run_dir or _latest_run_dir(Path("results/full_season_plc"))
    summary = plot(run_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
