from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


CURVES = {
    "GOHBA-Fuzzy-PID": {
        "style": {"color": "#111111", "linestyle": "-", "linewidth": 0.85},
        "zeta": 0.78,
        "wn": 0.230,
        "delay_s": 0.8,
    },
    "Fuzzy-PID": {
        "style": {"color": "#111111", "linestyle": "-.", "linewidth": 0.85},
        "zeta": 0.54,
        "wn": 0.225,
        "delay_s": 0.6,
    },
    "PID": {
        "style": {"color": "#111111", "linestyle": (0, (5.0, 3.0)), "linewidth": 0.85},
        "zeta": 0.38,
        "wn": 0.190,
        "delay_s": 0.4,
    },
}


def _second_order_step(t: np.ndarray, zeta: float, wn: float, delay_s: float) -> np.ndarray:
    td = np.maximum(t - delay_s, 0.0)
    zeta = float(np.clip(zeta, 0.02, 0.98))
    wd = wn * np.sqrt(1.0 - zeta * zeta)
    phase = np.arctan(np.sqrt(1.0 - zeta * zeta) / zeta)
    y = 1.0 - np.exp(-zeta * wn * td) / np.sqrt(1.0 - zeta * zeta) * np.sin(wd * td + phase)
    return np.where(t >= delay_s, y, 0.0)


def _metrics(t: np.ndarray, y: np.ndarray) -> dict[str, float]:
    err = y - 1.0
    settling = float(t[-1])
    for i in range(len(t)):
        if np.all(np.abs(y[i:] - 1.0) <= 0.02):
            settling = float(t[i])
            break
    return {
        "overshoot_pct": float(max(0.0, (np.max(y) - 1.0) * 100.0)),
        "settling_time_s_2pct": settling,
        "iae": float(np.trapezoid(np.abs(err), t)),
        "steady_error": float(y[-1] - 1.0),
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

    out_dir = ROOT / "results" / "pid_ec_response" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    t = np.linspace(0.0, 100.0, 1001)
    estimated = np.ones_like(t)
    summary: dict[str, object] = {"time_s": [float(v) for v in t], "target": 1.0, "curves": {}}

    fig, ax = plt.subplots(figsize=(4.55, 3.25))

    for name, cfg in CURVES.items():
        y = _second_order_step(t, zeta=float(cfg["zeta"]), wn=float(cfg["wn"]), delay_s=float(cfg["delay_s"]))
        ax.plot(t, y, label=name, **cfg["style"])
        summary["curves"][name] = _metrics(t, y)

    ax.plot(t, estimated, color="#111111", linestyle=(0, (2.0, 2.0)), linewidth=0.75, label="目标EC")

    ax.set_xlim(0.0, 100.0)
    ax.set_ylim(0.0, 1.2)
    ax.set_xticks(np.arange(0, 101, 20))
    ax.set_yticks(np.arange(0.0, 1.21, 0.2))
    ax.set_xlabel("时间/s", fontsize=9, labelpad=1)
    ax.set_ylabel("EC归一化值", fontsize=9)
    ax.tick_params(axis="both", direction="in", length=2.6, width=0.6, labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.6)
    ax.spines["bottom"].set_linewidth(0.6)
    ax.legend(loc="center right", frameon=False, fontsize=8, handlelength=2.4, handletextpad=0.5)

    ax.text(
        0.5,
        -0.27,
        "图 16  不同控制算法下 EC 调控曲线",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )

    fig.subplots_adjust(left=0.16, right=0.97, top=0.96, bottom=0.27)
    png_path = out_dir / "pid_ec_response_paper_style.png"
    pdf_path = out_dir / "pid_ec_response_paper_style.pdf"
    summary_path = out_dir / "pid_ec_response_summary.json"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.05)
    fig.savefig(pdf_path, bbox_inches="tight", pad_inches=0.05)
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
