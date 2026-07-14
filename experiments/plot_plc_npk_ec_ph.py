from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def _load_rows(run_dir: Path) -> list[dict]:
    csv_path = run_dir / "full_season_plc_timeseries.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _arr(rows: list[dict], key: str, default: float = 0.0) -> np.ndarray:
    def numeric(value) -> float:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "on"}:
                return 1.0
            if lowered in {"false", "no", "off"}:
                return 0.0
        return float(value)

    return np.array([numeric(row.get(key, default)) for row in rows], dtype=float)


def _rolling_mean(values: np.ndarray, window: int = 5) -> np.ndarray:
    if len(values) == 0 or window <= 1:
        return values
    kernel = np.ones(min(window, len(values)), dtype=float)
    kernel /= kernel.sum()
    return np.convolve(values, kernel, mode="same")


def _metrics(actual: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    error = actual - target
    return float(np.mean(np.abs(error))), float(np.max(np.abs(error)))


def _setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    font_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _style(axes) -> None:
    for ax in axes:
        ax.grid(True, axis="y", color="#dddddd", linewidth=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


def plot(run_dir: Path) -> Path:
    plt = _setup_matplotlib()
    rows = _load_rows(run_dir)
    if not rows:
        raise RuntimeError("CSV contains no rows")

    day = _arr(rows, "time_day")
    ec = _rolling_mean(_arr(rows, "ec_soil"), 5)
    ec_target = _arr(rows, "target_ec")
    ph = _rolling_mean(_arr(rows, "soil_ph_est", 7.0), 5)
    ph_target = _arr(rows, "target_ph", 6.0)
    n = _rolling_mean(_arr(rows, "n_actual"), 5)
    p = _rolling_mean(_arr(rows, "p_actual"), 5)
    k = _rolling_mean(_arr(rows, "k_actual"), 5)
    n_target = _arr(rows, "n_target")
    p_target = _arr(rows, "p_target")
    k_target = _arr(rows, "k_target")
    q_f = _arr(rows, "q_f_cmd")
    q_a = _arr(rows, "q_a_cmd")
    q_n = _arr(rows, "q_n_cmd")
    q_p = _arr(rows, "q_p_cmd")
    q_k = _arr(rows, "q_k_cmd")

    ec_mae, ec_max = _metrics(ec, ec_target)
    ph_mae, ph_max = _metrics(ph, ph_target)
    n_mae, n_max = _metrics(n, n_target)
    p_mae, p_max = _metrics(p, p_target)
    k_mae, k_max = _metrics(k, k_target)

    fig, axes = plt.subplots(4, 1, figsize=(13, 10.5), sharex=True)
    axes[0].plot(day, ec, color="#1f7a4d", linewidth=1.5, label="土壤 EC")
    axes[0].plot(day, ec_target, color="#1f7a4d", linestyle="--", linewidth=1.1, label="EC 目标")
    axes[0].set_ylabel("EC")
    axes[0].set_title(f"EC 跟踪：MAE={ec_mae:.4f}，最大绝对误差={ec_max:.4f}")
    axes[0].legend(loc="best")

    axes[1].plot(day, ph, color="#3569a8", linewidth=1.5, label="估算土壤 pH")
    axes[1].plot(day, ph_target, color="#3569a8", linestyle="--", linewidth=1.1, label="pH 目标")
    axes[1].set_ylabel("pH")
    axes[1].set_title(f"pH 跟踪：MAE={ph_mae:.4f}，最大绝对误差={ph_max:.4f}")
    axes[1].legend(loc="best")

    axes[2].plot(day, n, color="#d55e00", label=f"N actual, MAE={n_mae:.3f}")
    axes[2].plot(day, p, color="#7b3294", label=f"P actual, MAE={p_mae:.3f}")
    axes[2].plot(day, k, color="#008837", label=f"K actual, MAE={k_mae:.3f}")
    axes[2].plot(day, n_target, color="#d55e00", linestyle="--", alpha=0.65)
    axes[2].plot(day, p_target, color="#7b3294", linestyle="--", alpha=0.65)
    axes[2].plot(day, k_target, color="#008837", linestyle="--", alpha=0.65)
    axes[2].set_ylabel("N / P / K")
    axes[2].set_title(f"N/P/K 跟踪（最大误差 N={n_max:.3f}, P={p_max:.3f}, K={k_max:.3f}）")
    axes[2].legend(loc="best", ncol=3)

    axes[3].plot(day, q_f, color="#222222", linewidth=1.3, label="总肥液 q_f")
    axes[3].plot(day, q_n, color="#d55e00", label="q_n")
    axes[3].plot(day, q_p, color="#7b3294", label="q_p")
    axes[3].plot(day, q_k, color="#008837", label="q_k")
    axes[3].plot(day, q_a, color="#3569a8", label="酸液 q_a")
    axes[3].set_ylabel("L/min")
    axes[3].set_xlabel("天数")
    axes[3].set_title("PLC 最终执行量与 N/P/K 总预算分配")
    axes[3].legend(loc="best", ncol=5)
    _style(axes)
    fig.tight_layout()
    out = run_dir / "npk_ec_ph_execution.png"
    fig.savefig(out, dpi=220)
    plt.close(fig)

    fig, axes = plt.subplots(4, 1, figsize=(13, 11.5), sharex=True)
    axes[0].plot(day, _arr(rows, "kp_ec_base"), "--", color="#1f77b4", label="EC Kp base")
    axes[0].plot(day, _arr(rows, "kp_ec_effective"), color="#1f77b4", label="EC Kp effective")
    axes[0].plot(day, _arr(rows, "ki_ec_effective"), color="#ff7f0e", label="EC Ki effective")
    axes[0].plot(day, _arr(rows, "kd_ec_effective"), color="#2ca02c", label="EC Kd effective")
    axes[0].set_ylabel("EC gains")
    axes[0].set_title("EC 基准/有效 PID 参数（自适应可见性）")
    axes[0].legend(loc="best", ncol=4)

    axes[1].plot(day, _arr(rows, "kp_ph_base"), "--", color="#1f77b4", label="pH Kp base")
    axes[1].plot(day, _arr(rows, "kp_ph_effective"), color="#1f77b4", label="pH Kp effective")
    axes[1].plot(day, _arr(rows, "ki_ph_effective"), color="#ff7f0e", label="pH Ki effective")
    axes[1].plot(day, _arr(rows, "kd_ph_effective"), color="#2ca02c", label="pH Kd effective")
    axes[1].set_ylabel("pH gains")
    axes[1].set_title("pH 基准/有效 PID 参数")
    axes[1].legend(loc="best", ncol=4)

    axes[2].plot(day, _arr(rows, "q_f_feedforward"), label="q_f feedforward", color="#555555")
    axes[2].plot(day, _arr(rows, "q_f_pid_correction"), label="q_f PID correction", color="#d62728")
    axes[2].plot(day, _arr(rows, "q_f_raw"), label="q_f raw", color="#9467bd")
    axes[2].plot(day, q_f, label="q_f cmd", color="#111111")
    axes[2].plot(day, _arr(rows, "q_a_feedforward"), label="q_a feedforward", color="#76a5d5")
    axes[2].plot(day, _arr(rows, "q_a_pid_correction"), label="q_a PID correction", color="#e377c2")
    axes[2].plot(day, _arr(rows, "q_a_raw"), label="q_a raw", color="#17becf")
    axes[2].plot(day, q_a, label="q_a cmd", color="#1f4e79")
    axes[2].set_ylabel("L/min")
    axes[2].set_title("前馈、PID 修正、原始需求和保护后输出")
    axes[2].legend(loc="best", ncol=4)

    axes[3].plot(day, _arr(rows, "ec_pid_error"), label="EC PID error", color="#1f7a4d")
    axes[3].plot(day, _arr(rows, "ph_pid_error"), label="pH PID error", color="#3569a8")
    axes[3].plot(day, _arr(rows, "npk_optimization_weight"), label="NPK optimization weight", color="#d55e00")
    axes[3].step(day, _arr(rows, "npk_feedback_valid"), where="post", label="feedback valid", color="#008837", alpha=0.7)
    axes[3].step(day, _arr(rows, "npk_capacity_limited"), where="post", label="capacity limited", color="#c51b7d", alpha=0.7)
    axes[3].axhline(0.02, color="#999999", linestyle=":", linewidth=0.8)
    axes[3].axhline(-0.02, color="#999999", linestyle=":", linewidth=0.8)
    axes[3].set_ylabel("error / state")
    axes[3].set_xlabel("天数")
    axes[3].set_title("EC/pH 安全优先级与 N/P/K 优化状态")
    axes[3].legend(loc="best", ncol=3)
    _style(axes)
    fig.tight_layout()
    diag_out = run_dir / "adaptive_pid_npk_diagnostics.png"
    fig.savefig(diag_out, dpi=220)
    plt.close(fig)

    print(f"Saved: {out}")
    print(f"Saved: {diag_out}")
    print(
        f"EC_MAE={ec_mae:.6f}, pH_MAE={ph_mae:.6f}, "
        f"N_MAE={n_mae:.6f}, P_MAE={p_mae:.6f}, K_MAE={k_mae:.6f}"
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot PLC adaptive PID and N/P/K execution results.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    plot(args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
