from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


CROP_PH_TARGETS = {
    "INI": 6.2,
    "DEV": 6.1,
    "MID": 5.9,
    "LATE": 6.1,
}


def _load_rows(run_dir: Path) -> list[dict]:
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    return list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig")))


def _arr(rows: list[dict], key: str, default: float = 0.0) -> np.ndarray:
    return np.array([float(row.get(key, default) or default) for row in rows], dtype=float)


def _ph_crop_target(rows: list[dict]) -> np.ndarray:
    if rows and "target_ph" in rows[0]:
        return _arr(rows, "target_ph", 6.0)
    return np.array(
        [CROP_PH_TARGETS.get(str(row.get("stage", "")).upper(), float(row.get("ph_set", 6.0))) for row in rows],
        dtype=float,
    )


def _metrics(actual: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    err = actual - target
    return float(np.mean(np.abs(err))), float(np.max(np.maximum(err, 0.0)))


def plot(run_dir: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    font_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    rows = _load_rows(run_dir)
    day = _arr(rows, "time_day")

    ec = _arr(rows, "ec_soil")
    ec_target = _arr(rows, "target_ec")
    ph = _arr(rows, "soil_ph_est")
    ph_target = _ph_crop_target(rows)
    ph_cmd = _arr(rows, "ph_set")
    n = _arr(rows, "n_actual")
    p = _arr(rows, "p_actual")
    k = _arr(rows, "k_actual")
    n_target = _arr(rows, "n_target")
    p_target = _arr(rows, "p_target")
    k_target = _arr(rows, "k_target")
    q_f = _arr(rows, "q_f_cmd")
    q_a = _arr(rows, "q_a_cmd")
    q_n = _arr(rows, "q_n_cmd")
    q_p = _arr(rows, "q_p_cmd")
    q_k = _arr(rows, "q_k_cmd")

    ec_mae, ec_over = _metrics(ec, ec_target)
    ph_mae, ph_over = _metrics(ph, ph_target)
    n_mae, _ = _metrics(n, n_target)
    p_mae, _ = _metrics(p, p_target)
    k_mae, _ = _metrics(k, k_target)

    fig, axes = plt.subplots(4, 1, figsize=(13, 10), sharex=True)

    axes[0].plot(day, ec, color="#1f7a4d", linewidth=1.5, label="根区 EC")
    axes[0].step(day, ec_target, where="post", color="#1f7a4d", linestyle="--", linewidth=1.1, label="作物目标 EC")
    axes[0].set_ylabel("EC")
    axes[0].set_title(f"EC 跟踪  MAE={ec_mae:.4f}, 超调={ec_over:.4f}")
    axes[0].legend(loc="best")

    axes[1].plot(day, ph, color="#3569a8", linewidth=1.5, label="根区 pH")
    axes[1].step(day, ph_target, where="post", color="#3569a8", linestyle="--", linewidth=1.15, label="作物目标 pH")
    axes[1].step(day, ph_cmd, where="post", color="#8aa9d6", linestyle=":", linewidth=0.9, label="PLC 执行 pH")
    axes[1].set_ylabel("pH")
    axes[1].set_title(f"pH 跟踪  MAE={ph_mae:.4f}, 超调={ph_over:.4f}")
    axes[1].legend(loc="best")

    axes[2].plot(day, n, color="#d55e00", linewidth=1.4, label=f"N actual, MAE={n_mae:.3f}")
    axes[2].plot(day, p, color="#7b3294", linewidth=1.4, label=f"P actual, MAE={p_mae:.3f}")
    axes[2].plot(day, k, color="#008837", linewidth=1.4, label=f"K actual, MAE={k_mae:.3f}")
    axes[2].step(day, n_target, where="post", color="#d55e00", linestyle="--", linewidth=0.9, alpha=0.65)
    axes[2].step(day, p_target, where="post", color="#7b3294", linestyle="--", linewidth=0.9, alpha=0.65)
    axes[2].step(day, k_target, where="post", color="#008837", linestyle="--", linewidth=0.9, alpha=0.65)
    axes[2].set_ylabel("N/P/K")
    axes[2].set_title("N/P/K 根区水平")
    axes[2].legend(loc="best", ncol=3)

    axes[3].plot(day, q_f, color="#444444", linewidth=1.2, label="总肥 q_f")
    axes[3].plot(day, q_n, color="#d55e00", linewidth=1.0, label="N q_n")
    axes[3].plot(day, q_p, color="#7b3294", linewidth=1.0, label="P q_p")
    axes[3].plot(day, q_k, color="#008837", linewidth=1.0, label="K q_k")
    axes[3].plot(day, q_a, color="#3569a8", linewidth=1.0, label="酸液 q_a")
    axes[3].set_ylabel("L/min")
    axes[3].set_xlabel("天数")
    axes[3].set_title("PLC 执行量")
    axes[3].legend(loc="best", ncol=5)

    for ax in axes:
        ax.grid(True, axis="y", color="#dddddd", linewidth=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.tight_layout()
    out = run_dir / "npk_ec_ph_execution.png"
    fig.savefig(out, dpi=220)
    plt.close(fig)

    print(f"Saved: {out}")
    print(
        f"EC_MAE={ec_mae:.6f}, pH_MAE={ph_mae:.6f}, "
        f"N_MAE={n_mae:.6f}, P_MAE={p_mae:.6f}, K_MAE={k_mae:.6f}"
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot PLC N/P/K, EC, pH execution results.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    plot(args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
