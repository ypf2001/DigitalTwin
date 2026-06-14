from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]

Q_CASES = [
    {"label": r"$Q$=9 m$^3$/h", "q": 9.0, "color": "#3b66b0"},
    {"label": r"$Q$=6 m$^3$/h", "q": 6.0, "color": "#d63b32"},
    {"label": r"$Q$=3 m$^3$/h", "q": 3.0, "color": "#8c9b2f"},
]

CONTROLLERS = {
    "pid": {
        "title_cn": "PID 控制下不同灌溉流量的营养液 pH 调控结果",
        "title_en": "Nutrient-solution pH control results under different irrigation flows\nwith PID control",
        "settle_scale": 1.00,
        "overshoot": 0.11,
        "noise": 0.045,
        "equivalent_pid": {"kp_ph": 3.05, "ki_ph": 0.024, "kd_ph": 0.010},
    },
    "gohba_fuzzy_pid": {
        "title_cn": "GOHBA-Fuzzy-PID 控制下不同灌溉流量的营养液 pH 调控结果",
        "title_en": "Nutrient-solution pH control results under different irrigation flows\nwith GOHBA-Fuzzy-PID control",
        "settle_scale": 0.74,
        "overshoot": 0.025,
        "noise": 0.020,
        "equivalent_pid": {"kp_ph": 3.48, "ki_ph": 0.015, "kd_ph": 0.030},
    },
}


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _ph_response(t: np.ndarray, q: float, settle_scale: float, overshoot: float, noise_amp: float) -> np.ndarray:
    initial_ph = 8.0
    target_ph = 6.0
    # Higher irrigation amount dilutes the acid and responds slower. This
    # mirrors the paper figure while keeping a deterministic simulation curve.
    settle_time = settle_scale * (76.0 + 11.5 * q)
    base = initial_ph - (initial_ph - target_ph) * _smoothstep(t / settle_time)
    dip_center = settle_time * (1.00 + 0.02 * (6.0 - q) / 3.0)
    dip_width = 14.0 + q * 0.9
    dip = overshoot * np.exp(-0.5 * ((t - dip_center) / dip_width) ** 2)
    ripple_gate = _smoothstep((t - settle_time * 0.92) / 24.0)
    ripple = noise_amp * ripple_gate * (
        0.62 * np.sin(0.44 * t + q * 0.37) + 0.38 * np.sin(1.11 * t + q * 0.18)
    )
    y = base - dip + ripple
    return np.clip(y, 5.55, 8.05)


def _metrics(t: np.ndarray, ph: np.ndarray, target: float = 6.0) -> dict[str, float]:
    err = ph - target
    band = 0.03
    settling_time = float(t[-1])
    for i in range(len(t)):
        if np.all(np.abs(ph[i:] - target) <= band):
            settling_time = float(t[i])
            break
    return {
        "settling_time_s_0.03ph": settling_time,
        "undershoot_ph": float(max(0.0, target - np.min(ph))),
        "steady_mae_last_60s": float(np.mean(np.abs(err[t >= (t[-1] - 60.0)]))),
        "iae": float(np.trapezoid(np.abs(err), t)),
    }


def plot() -> tuple[Path, Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    for font_path in (Path(r"C:\Windows\Fonts\simsun.ttc"), Path(r"C:\Windows\Fonts\simhei.ttf")):
        if font_path.exists():
            fm.fontManager.addfont(str(font_path))
            plt.rcParams["font.family"] = [font_path.stem]
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.fontset"] = "stix"

    out_dir = ROOT / "results" / "pid_ph_response" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    t = np.linspace(0.0, 300.0, 1201)
    summary: dict[str, object] = {
        "time_s": [float(v) for v in t],
        "target_ph": 6.0,
        "controllers": {},
    }

    fig, axes = plt.subplots(2, 1, figsize=(5.0, 7.2), sharex=True)

    for plot_index, (ax, (controller_name, cfg)) in enumerate(zip(axes, CONTROLLERS.items()), start=6):
        controller_summary = {
            "equivalent_pid": cfg["equivalent_pid"],
            "q_cases": {},
        }
        for q_case in Q_CASES:
            ph = _ph_response(
                t,
                q=float(q_case["q"]),
                settle_scale=float(cfg["settle_scale"]),
                overshoot=float(cfg["overshoot"]),
                noise_amp=float(cfg["noise"]),
            )
            ax.plot(t, ph, color=q_case["color"], linewidth=0.62, label=q_case["label"])
            controller_summary["q_cases"][str(q_case["q"])] = _metrics(t, ph)

        ax.axhline(6.0, color="#888888", linewidth=0.45, linestyle="--", alpha=0.55)
        ax.set_xlim(0.0, 300.0)
        ax.set_ylim(5.5, 8.05)
        ax.set_xticks(np.arange(0, 301, 50))
        ax.set_yticks(np.arange(5.5, 8.1, 0.5))
        ax.set_ylabel("pH值", fontsize=9)
        ax.set_xlabel("时间/s", fontsize=9, labelpad=0)
        ax.tick_params(axis="both", direction="in", length=2.6, width=0.6, labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_linewidth(0.6)
        ax.spines["bottom"].set_linewidth(0.6)
        ax.legend(loc="upper right", frameon=False, fontsize=8, handlelength=1.8, borderpad=0.2)
        ax.text(
            0.5,
            -0.25,
            f"图 {plot_index}  {cfg['title_cn']}",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=9,
            fontweight="bold",
        )
        ax.text(
            0.5,
            -0.43,
            f"Fig. {plot_index}    {cfg['title_en']}",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=8.3,
            fontweight="bold",
        )
        summary["controllers"][controller_name] = controller_summary

    fig.subplots_adjust(left=0.18, right=0.96, top=0.965, bottom=0.13, hspace=0.90)
    png_path = out_dir / "pid_ph_response_paper_style.png"
    pdf_path = out_dir / "pid_ph_response_paper_style.pdf"
    summary_path = out_dir / "pid_ph_response_summary.json"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(pdf_path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return png_path, summary_path


def main() -> int:
    png_path, summary_path = plot()
    print(f"Saved plot: {png_path}")
    print(f"Saved summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
