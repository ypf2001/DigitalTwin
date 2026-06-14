from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = ROOT / "outputs" / "figures"
FIGURE_DIR.mkdir(parents=True, exist_ok=True)


def _font_properties() -> fm.FontProperties:
    for font_path in (
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    ):
        if font_path.exists():
            return fm.FontProperties(fname=str(font_path))
    return fm.FontProperties()


FONT = _font_properties()


CONFIG = {
    "time": {
        "duration_h": 48.0,
        "dt_min": 5.0,
    },
    "thresholds": {
        "moisture_low": 0.24,
        "moisture_high": 0.30,
        "ec_low": 1.10,
        "ec_high": 1.30,
        "ph_low": 5.80,
        "ph_high": 6.20,
        "pressure_low": 0.18,
        "pressure_high": 0.45,
    },
    "pulse": {
        "ph_pulse_min": 5.0,
        "mixing_delay_min": 20.0,
    },
    "process": {
        "initial_moisture": 0.225,
        "initial_ec": 0.86,
        "initial_ph": 6.46,
        "initial_pressure": 0.28,
        "evap_rate_h": 0.0022,
        "irrigation_gain_h": 0.032,
        "fert_ec_gain_h": 0.20,
        "clear_water_dilution_h": 0.055,
        "ec_concentration_drift_h": 0.0030,
        "acid_ph_gain_h": 0.72,
        "alkali_ph_gain_h": 0.62,
        "ph_buffer_relax_h": 0.010,
        "natural_ph": 6.55,
    },
}


@dataclass
class PLCState:
    pump: bool = False
    valve: bool = False
    fert_pump: bool = False
    acid_pump: bool = False
    alkali_pump: bool = False
    fert_ratio: float = 0.0
    alarm: bool = False
    mixing_delay_steps: int = 0


class FixedThresholdPLC:
    def __init__(self, config: dict):
        self.config = config
        self.thresholds = config["thresholds"]
        self.pulse_steps = max(1, int(round(config["pulse"]["ph_pulse_min"] / config["time"]["dt_min"])))
        self.mixing_delay_steps = max(1, int(round(config["pulse"]["mixing_delay_min"] / config["time"]["dt_min"])))
        self.state = PLCState()

    def step(self, moisture: float, ec: float, ph: float, pressure: float) -> PLCState:
        s = self.state
        th = self.thresholds

        if pressure < th["pressure_low"] or pressure > th["pressure_high"]:
            self.state = PLCState(alarm=True)
            return self.state

        s.alarm = False

        # Moisture hysteresis: keep previous pump/valve state inside the band.
        if moisture < th["moisture_low"]:
            s.pump = True
            s.valve = True
        elif moisture > th["moisture_high"]:
            s.pump = False
            s.valve = False

        # EC hysteresis: keep previous fertilizer pump state inside the band.
        if ec < th["ec_low"]:
            s.fert_pump = True
            s.fert_ratio = float(np.clip((th["ec_low"] - ec) / 0.22, 0.30, 1.00))
        elif ec > th["ec_high"]:
            s.fert_pump = False
            s.fert_ratio = 0.0
            s.pump = True
            s.valve = True
        elif not s.fert_pump:
            s.fert_ratio = 0.0
        else:
            s.fert_ratio = float(np.clip((th["ec_high"] - ec) / (th["ec_high"] - th["ec_low"]), 0.25, 1.00))

        # pH uses small pulse dosing, then waits for mixing before detecting again.
        s.acid_pump = False
        s.alkali_pump = False
        if s.mixing_delay_steps > 0:
            s.mixing_delay_steps -= 1
        elif ph > th["ph_high"]:
            s.acid_pump = True
            s.mixing_delay_steps = self.mixing_delay_steps
        elif ph < th["ph_low"]:
            s.alkali_pump = True
            s.mixing_delay_steps = self.mixing_delay_steps

        return s


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
    ax.grid(True, axis="y", color="#d8d8d8", linestyle="--", linewidth=0.5)
    ax.tick_params(direction="in")


def _pressure_from_state(state: PLCState, time_h: float, previous_pressure: float) -> float:
    if state.pump and state.valve:
        return float(0.31 + 0.012 * np.sin(2 * np.pi * time_h / 6.0))
    if state.pump and not state.valve:
        return float(0.47)
    if not state.pump and state.valve:
        return float(0.16)
    return float(0.27 + 0.004 * np.sin(2 * np.pi * time_h / 10.0) + 0.15 * (previous_pressure - 0.27))


def _update_process(row: dict[str, float], state: PLCState, config: dict, time_h: float) -> dict[str, float]:
    p = config["process"]
    th = config["thresholds"]
    dt_h = config["time"]["dt_min"] / 60.0

    moisture = row["moisture"]
    ec = row["ec"]
    ph = row["ph"]

    if state.pump and state.valve:
        moisture += p["irrigation_gain_h"] * dt_h
    moisture -= p["evap_rate_h"] * dt_h
    moisture = float(np.clip(moisture, 0.18, 0.36))

    if state.pump and state.valve and state.fert_pump:
        ec += p["fert_ec_gain_h"] * state.fert_ratio * dt_h
    elif state.pump and state.valve and ec > th["ec_low"]:
        ec -= p["clear_water_dilution_h"] * dt_h
    else:
        ec += p["ec_concentration_drift_h"] * dt_h
    ec += 0.002 * np.sin(2 * np.pi * time_h / 9.0) * dt_h
    ec = float(np.clip(ec, 0.70, 1.55))

    if state.acid_pump:
        ph -= p["acid_ph_gain_h"] * dt_h
    elif state.alkali_pump:
        ph += p["alkali_ph_gain_h"] * dt_h
    else:
        ph += p["ph_buffer_relax_h"] * (p["natural_ph"] - ph) * dt_h
    ph += 0.0015 * np.sin(2 * np.pi * time_h / 8.0) * dt_h
    ph = float(np.clip(ph, 5.55, 6.65))

    pressure = _pressure_from_state(state, time_h, row["pressure"])
    return {"moisture": moisture, "ec": ec, "ph": ph, "pressure": pressure}


def simulate(config: dict) -> list[dict[str, float]]:
    controller = FixedThresholdPLC(config)
    dt_min = config["time"]["dt_min"]
    steps = int(round(config["time"]["duration_h"] * 60.0 / dt_min)) + 1
    process = {
        "moisture": config["process"]["initial_moisture"],
        "ec": config["process"]["initial_ec"],
        "ph": config["process"]["initial_ph"],
        "pressure": config["process"]["initial_pressure"],
    }

    rows: list[dict[str, float]] = []
    for step in range(steps):
        time_h = step * dt_min / 60.0
        state = controller.step(process["moisture"], process["ec"], process["ph"], process["pressure"])
        rows.append(
            {
                "time_h": time_h,
                "moisture": process["moisture"],
                "ec": process["ec"],
                "ph": process["ph"],
                "pressure": process["pressure"],
                "pump": float(state.pump),
                "valve": float(state.valve),
                "fert_pump": float(state.fert_pump),
                "acid_pump": float(state.acid_pump),
                "alkali_pump": float(state.alkali_pump),
                "fert_ratio": state.fert_ratio,
                "alarm": float(state.alarm),
            }
        )
        process = _update_process(process, state, config, time_h)
    return rows


def plot_strategy_flowchart(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 7.2), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def node(x: float, y: float, w: float, h: float, label: str) -> None:
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=1.1))
        ax.text(x + w / 2, y + h / 2, label, fontproperties=fm.FontProperties(family=plt.rcParams["font.sans-serif"][0]), fontsize=9.5, ha="center", va="center")

    def link(a: tuple[float, float], b: tuple[float, float]) -> None:
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="->", mutation_scale=11, lw=1.0, color="black"))

    node(36, 88, 28, 7, "采集土壤湿度、EC、pH、压力")
    node(36, 76, 28, 7, "压力越限？")
    node(5, 76, 22, 7, "停机并报警")
    node(36, 63, 28, 8, "湿度回差控制\n泵和灌溉阀保持上一状态")
    node(36, 49, 28, 8, "EC 回差控制\n肥液泵比例投加")
    node(36, 34, 28, 9, "pH 上下限判断\n小剂量脉冲投加")
    node(36, 20, 28, 8, "搅拌延时\n再检测")
    node(36, 7, 28, 7, "更新执行器状态并进入下一周期")

    link((50, 88), (50, 83))
    link((36, 79.5), (27, 79.5))
    ax.text(30, 81.8, "是", fontsize=9, fontproperties=FONT)
    link((50, 76), (50, 71))
    ax.text(52, 73, "否", fontsize=9, fontproperties=FONT)
    link((50, 63), (50, 57))
    link((50, 49), (50, 43))
    link((50, 34), (50, 28))
    link((50, 20), (50, 14))
    link((64, 10.5), (82, 10.5))
    link((82, 10.5), (82, 91.5))
    link((82, 91.5), (64, 91.5))

    ax.text(50, 1.5, "图 4.1 PLC 固定阈值控制策略流程图", fontsize=13.5, fontproperties=FONT, ha="center", va="bottom", fontweight="bold")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def plot_moisture(rows: list[dict[str, float]], config: dict, path: Path) -> None:
    t = np.array([r["time_h"] for r in rows])
    moisture = np.array([r["moisture"] for r in rows])
    th = config["thresholds"]
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=300)
    ax.plot(t, moisture, color="black", lw=1.35, label="实际湿度")
    ax.axhline(th["moisture_low"], color="black", lw=1.0, ls="--", label="湿度下限")
    ax.axhline(th["moisture_high"], color="black", lw=1.0, ls="-.", label="湿度上限")
    ax.fill_between(t, th["moisture_low"], th["moisture_high"], color="#dddddd", alpha=0.22)
    ax.set_title("图 4.2 土壤湿度固定阈值控制仿真结果")
    ax.set_xlabel("时间/h")
    ax.set_ylabel("土壤体积含水率/(m$^3$·m$^{-3}$)")
    ax.set_xlim(0, t.max())
    ax.set_ylim(0.20, 0.33)
    ax.legend(frameon=False, loc="best")
    _style_axis(ax)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def plot_ec_ph(rows: list[dict[str, float]], config: dict, path: Path) -> None:
    t = np.array([r["time_h"] for r in rows])
    ec = np.array([r["ec"] for r in rows])
    ph = np.array([r["ph"] for r in rows])
    th = config["thresholds"]

    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(7.0, 6.0), dpi=300, sharex=True)
    ax_ec.plot(t, ec, color="black", lw=1.25, label="实际 EC")
    ax_ec.axhline(th["ec_low"], color="black", lw=1.0, ls="--", label="EC 下限")
    ax_ec.axhline(th["ec_high"], color="black", lw=1.0, ls="-.", label="EC 上限")
    ax_ec.fill_between(t, th["ec_low"], th["ec_high"], color="#dddddd", alpha=0.22)
    ax_ec.set_ylabel("EC/(dS·m$^{-1}$)")
    ax_ec.set_ylim(0.75, 1.38)
    ax_ec.legend(frameon=False, loc="best")
    _style_axis(ax_ec)

    ax_ph.plot(t, ph, color="black", lw=1.25, label="实际 pH")
    ax_ph.axhline(th["ph_low"], color="black", lw=1.0, ls="--", label="pH 下限")
    ax_ph.axhline(th["ph_high"], color="black", lw=1.0, ls="-.", label="pH 上限")
    ax_ph.fill_between(t, th["ph_low"], th["ph_high"], color="#dddddd", alpha=0.22)
    ax_ph.set_ylabel("pH")
    ax_ph.set_xlabel("时间/h")
    ax_ph.set_ylim(5.70, 6.55)
    ax_ph.set_xlim(0, t.max())
    ax_ph.legend(frameon=False, loc="best")
    _style_axis(ax_ph)
    fig.suptitle("图 4.3 EC-pH 固定策略调控仿真结果", y=0.995)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def plot_actuators(rows: list[dict[str, float]], path: Path) -> None:
    t = np.array([r["time_h"] for r in rows])
    names = [
        ("pump", "主泵"),
        ("valve", "灌溉阀"),
        ("fert_pump", "肥液泵"),
        ("acid_pump", "酸液泵"),
        ("alkali_pump", "碱液泵"),
    ]
    fig, axes = plt.subplots(len(names), 1, figsize=(7.0, 6.4), dpi=300, sharex=True)
    for ax, (key, label) in zip(axes, names):
        values = np.array([r[key] for r in rows])
        ax.step(t, values, where="post", color="black", lw=1.15, label=label)
        ax.set_ylim(-0.15, 1.15)
        ax.set_yticks([0, 1])
        ax.set_ylabel(label)
        _style_axis(ax)
    axes[-1].set_xlabel("时间/h")
    axes[-1].set_xlim(0, t.max())
    fig.suptitle("图 4.4 执行器启停状态仿真结果", y=0.995)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def run(config: dict) -> dict[str, str]:
    _configure_fonts()
    rows = simulate(config)

    paths = {
        "flowchart": FIGURE_DIR / "figure_4_1_plc_fixed_threshold_flowchart.png",
        "moisture": FIGURE_DIR / "figure_4_2_moisture_threshold_result.png",
        "ec_ph": FIGURE_DIR / "figure_4_3_ec_ph_threshold_result.png",
        "actuators": FIGURE_DIR / "figure_4_4_actuator_status_result.png",
    }
    plot_strategy_flowchart(paths["flowchart"])
    plot_moisture(rows, config, paths["moisture"])
    plot_ec_ph(rows, config, paths["ec_ph"])
    plot_actuators(rows, paths["actuators"])

    return {key: str(value) for key, value in paths.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PLC fixed-threshold hysteresis fertigation simulation.")
    parser.add_argument("--duration-h", type=float, default=CONFIG["time"]["duration_h"])
    parser.add_argument("--dt-min", type=float, default=CONFIG["time"]["dt_min"])
    args = parser.parse_args()

    config = json.loads(json.dumps(CONFIG))
    config["time"]["duration_h"] = args.duration_h
    config["time"]["dt_min"] = args.dt_min
    summary = run(config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
