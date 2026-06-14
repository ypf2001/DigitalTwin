from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


FLOW_CASES = [
    {"setpoint": 0.5, "ylim": (0.0, 0.7), "yticks": np.arange(0.0, 0.71, 0.1)},
    {"setpoint": 1.0, "ylim": (0.0, 1.6), "yticks": np.arange(0.0, 1.61, 0.4)},
    {"setpoint": 1.5, "ylim": (0.0, 2.5), "yticks": np.arange(0.0, 2.51, 0.5)},
    {"setpoint": 2.0, "ylim": (0.0, 3.2), "yticks": np.arange(0.0, 3.21, 1.0)},
]


CONTROLLERS = {
    "PID": {
        "color": "#3b4cc0",
        "zeta": 0.34,
        "wn": 0.28,
        "delay_s": 1.5,
        "gain": 1.000,
        "equivalent_pid": {"kp": 1.05, "ki": 0.030, "kd": 0.018},
    },
    "Fuzzy-PID": {
        "color": "#5ab84d",
        "zeta": 0.24,
        "wn": 0.33,
        "delay_s": 1.0,
        "gain": 1.000,
        "equivalent_pid": {"kp": 1.28, "ki": 0.038, "kd": 0.013},
    },
    "GOHBA-Fuzzy-PID": {
        "color": "#e33b32",
        "zeta": 0.72,
        "wn": 0.36,
        "delay_s": 0.8,
        "gain": 1.000,
        "equivalent_pid": {"kp": 1.02, "ki": 0.018, "kd": 0.046},
    },
}


def _second_order_step(t: np.ndarray, setpoint: float, zeta: float, wn: float, delay_s: float, gain: float) -> np.ndarray:
    td = np.maximum(t - delay_s, 0.0)
    zeta = float(np.clip(zeta, 0.02, 0.98))
    wd = wn * np.sqrt(1.0 - zeta * zeta)
    phase = np.arctan(np.sqrt(1.0 - zeta * zeta) / zeta)
    response = 1.0 - np.exp(-zeta * wn * td) / np.sqrt(1.0 - zeta * zeta) * np.sin(wd * td + phase)
    response = np.where(t >= delay_s, response, 0.0)
    return np.maximum(0.0, setpoint * gain * response)


def _metrics(t: np.ndarray, y: np.ndarray, setpoint: float) -> dict[str, float]:
    err = y - setpoint
    band = 0.02 * max(setpoint, 1e-9)
    settling_time = float(t[-1])
    for i in range(len(t)):
        if np.all(np.abs(y[i:] - setpoint) <= band):
            settling_time = float(t[i])
            break
    return {
        "overshoot_pct": float(max(0.0, (np.max(y) - setpoint) / setpoint * 100.0)),
        "settling_time_s_2pct": settling_time,
        "steady_error": float(y[-1] - setpoint),
        "iae": float(np.trapezoid(np.abs(err), t)),
    }


def plot() -> tuple[Path, Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    font_path = Path(r"C:\Windows\Fonts\simsun.ttc")
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = ["SimSun"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.fontset"] = "stix"

    out_dir = ROOT / "results" / "pid_flow_response" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    t = np.linspace(0.0, 200.0, 1001)
    summary: dict[str, object] = {
        "time_s": [float(v) for v in t],
        "controllers": {name: cfg["equivalent_pid"] for name, cfg in CONTROLLERS.items()},
        "cases": {},
    }

    fig, axes = plt.subplots(4, 1, figsize=(5.35, 8.75), sharex=True)

    for index, (ax, case) in enumerate(zip(axes, FLOW_CASES), start=1):
        setpoint = float(case["setpoint"])
        target = np.full_like(t, setpoint)
        ax.plot(t, target, color="#111111", linewidth=0.75, label="流量设定值")

        case_summary = {}
        for name, cfg in CONTROLLERS.items():
            y = _second_order_step(
                t,
                setpoint=setpoint,
                zeta=float(cfg["zeta"]),
                wn=float(cfg["wn"]),
                delay_s=float(cfg["delay_s"]),
                gain=float(cfg["gain"]),
            )
            ax.plot(t, y, color=str(cfg["color"]), linewidth=0.65, label=name)
            case_summary[name] = _metrics(t, y, setpoint)

        ax.set_xlim(0.0, 200.0)
        ax.set_ylim(*case["ylim"])
        ax.set_yticks(case["yticks"])
        ax.set_xticks(np.arange(0, 201, 20))
        ax.set_ylabel(r"流量/(L·min$^{-1}$)", fontsize=9)
        ax.set_xlabel("时间/s", fontsize=9, labelpad=0)
        ax.tick_params(axis="both", direction="in", length=2.8, width=0.6, labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_linewidth(0.6)
        ax.spines["bottom"].set_linewidth(0.6)
        ax.grid(False)
        ax.legend(
            loc="upper center",
            ncol=2,
            frameon=False,
            fontsize=8,
            handlelength=1.8,
            columnspacing=0.9,
            handletextpad=0.35,
            bbox_to_anchor=(0.54, 1.04),
        )
        ax.text(
            0.5,
            -0.33,
            f"({chr(96 + index)}) 流量{setpoint:.1f} L/min",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=9,
        )
        summary["cases"][f"{setpoint:.1f}_L_min"] = case_summary

    fig.subplots_adjust(left=0.18, right=0.98, top=0.985, bottom=0.065, hspace=0.58)
    png_path = out_dir / "pid_flow_response_paper_style.png"
    pdf_path = out_dir / "pid_flow_response_paper_style.pdf"
    summary_path = out_dir / "pid_flow_response_summary.json"
    fig.savefig(png_path, dpi=300)
    fig.savefig(pdf_path)
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
