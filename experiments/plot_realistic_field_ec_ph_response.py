from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]


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


def _first_order_response(
    time_h: np.ndarray,
    initial: float,
    target: float,
    dead_time_h: float,
    tau_h: float,
    damping: float = 0.0,
) -> np.ndarray:
    active_t = np.maximum(time_h - dead_time_h, 0.0)
    base = target - (target - initial) * np.exp(-active_t / max(tau_h, 1e-6))
    if damping <= 0.0:
        return base
    ripple = damping * (target - initial) * np.exp(-active_t / (tau_h * 1.8)) * np.sin(active_t / tau_h * 5.0)
    return base + ripple


def _nearest_sample(values: np.ndarray, every_n: int) -> np.ndarray:
    sampled = np.empty_like(values)
    for i in range(len(values)):
        source = (i // every_n) * every_n
        sampled[i] = values[source]
    return sampled


def simulate(args: argparse.Namespace) -> tuple[Path, dict[str, float | str]]:
    _configure_fonts()
    out_dir = ROOT / "results" / "realistic_field_response" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    dt_s = float(args.dt_s)
    duration_h = float(args.duration_h)
    time_h = np.arange(0.0, duration_h + dt_s / 3600.0, dt_s / 3600.0)
    sensor_every = max(1, int(round(args.sensor_period_s / dt_s)))

    outlet_ec_raw = _first_order_response(
        time_h,
        initial=args.initial_ec,
        target=args.target_ec,
        dead_time_h=args.pipe_dead_time_min / 60.0,
        tau_h=args.outlet_tau_min / 60.0,
        damping=0.025,
    )
    outlet_ph_raw = _first_order_response(
        time_h,
        initial=args.initial_ph,
        target=args.target_ph,
        dead_time_h=args.pipe_dead_time_min / 60.0,
        tau_h=args.outlet_tau_min / 60.0,
        damping=0.018,
    )

    outlet_ec = _nearest_sample(outlet_ec_raw, sensor_every)
    outlet_ph = _nearest_sample(outlet_ph_raw, sensor_every)

    # Root-zone sensors reflect a buffered soil volume, so use hour-scale dynamics
    # and slower sampling. This is trend feedback, not the fast PLC PID loop.
    soil_period_n = max(1, int(round(args.soil_sensor_period_min * 60.0 / dt_s)))
    soil_ec_raw = _first_order_response(
        time_h,
        initial=args.initial_soil_ec,
        target=args.target_ec,
        dead_time_h=args.soil_dead_time_h,
        tau_h=args.soil_ec_tau_h,
        damping=0.0,
    )
    soil_ph_raw = _first_order_response(
        time_h,
        initial=args.initial_soil_ph,
        target=args.target_ph,
        dead_time_h=args.soil_dead_time_h,
        tau_h=args.soil_ph_tau_h,
        damping=0.0,
    )
    soil_ec = _nearest_sample(soil_ec_raw, soil_period_n)
    soil_ph = _nearest_sample(soil_ph_raw, soil_period_n)

    rows = []
    for i, t_h in enumerate(time_h):
        rows.append(
            {
                "time_h": float(t_h),
                "target_ec": float(args.target_ec),
                "outlet_ec": float(outlet_ec[i]),
                "soil_ec": float(soil_ec[i]),
                "target_ph": float(args.target_ph),
                "outlet_ph": float(outlet_ph[i]),
                "soil_ph": float(soil_ph[i]),
            }
        )
    csv_path = out_dir / "realistic_field_ec_ph_response.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    duration_tag = f"{duration_h:g}h".replace(".", "p")
    outlet_path = out_dir / f"outlet_ec_ph_{duration_tag}_response.png"
    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(6.2, 5.3), sharex=True)
    ax_ec.plot(time_h, outlet_ec, color="black", linewidth=1.15, label="当前出口EC")
    ax_ec.step(time_h, np.full_like(time_h, args.target_ec), where="post", color="black", linestyle="--", linewidth=1.0, label="目标出口EC")
    ax_ec.set_ylabel("出口EC/(dS·m$^{-1}$)")
    ax_ec.set_ylim(0.0, max(1.6, args.target_ec + 0.2))
    ax_ec.legend(frameon=False, loc="best", fontsize=9)

    ax_ph.plot(time_h, outlet_ph, color="black", linewidth=1.15, label="当前出口pH")
    ax_ph.step(time_h, np.full_like(time_h, args.target_ph), where="post", color="black", linestyle="--", linewidth=1.0, label="目标出口pH")
    ax_ph.set_ylabel("出口pH")
    ax_ph.set_xlabel("时间/h")
    ax_ph.set_ylim(min(args.initial_ph, args.target_ph) - 0.25, max(args.initial_ph, args.target_ph) + 0.25)
    ax_ph.legend(frameon=False, loc="best", fontsize=9)

    for ax in (ax_ec, ax_ph):
        ax.set_xlim(0.0, duration_h)
        ax.set_xticks(np.arange(0.0, duration_h + 0.1, 4.0))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="in")
    fig.subplots_adjust(left=0.15, right=0.97, top=0.97, bottom=0.16, hspace=0.30)
    fig.savefig(outlet_path, dpi=320, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

    soil_path = out_dir / f"soil_ec_ph_{duration_tag}_trend.png"
    fig, (ax_ec, ax_ph) = plt.subplots(2, 1, figsize=(6.2, 5.3), sharex=True)
    ax_ec.plot(time_h, soil_ec, color="black", linewidth=1.15, label="当前土壤EC")
    ax_ec.step(time_h, np.full_like(time_h, args.target_ec), where="post", color="black", linestyle="--", linewidth=1.0, label="目标土壤EC")
    ax_ec.set_ylabel("土壤EC/(dS·m$^{-1}$)")
    ax_ec.legend(frameon=False, loc="best", fontsize=9)

    ax_ph.plot(time_h, soil_ph, color="black", linewidth=1.15, label="当前土壤pH")
    ax_ph.step(time_h, np.full_like(time_h, args.target_ph), where="post", color="black", linestyle="--", linewidth=1.0, label="目标土壤pH")
    ax_ph.set_ylabel("土壤pH")
    ax_ph.set_xlabel("时间/h")
    ax_ph.legend(frameon=False, loc="best", fontsize=9)

    for ax in (ax_ec, ax_ph):
        ax.set_xlim(0.0, duration_h)
        ax.set_xticks(np.arange(0.0, duration_h + 0.1, 4.0))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="in")
    fig.subplots_adjust(left=0.15, right=0.97, top=0.97, bottom=0.16, hspace=0.30)
    fig.savefig(soil_path, dpi=320, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

    outlet_ec_error = np.abs(outlet_ec - args.target_ec)
    outlet_ph_error = np.abs(outlet_ph - args.target_ph)
    soil_ec_error = np.abs(soil_ec - args.target_ec)
    soil_ph_error = np.abs(soil_ph - args.target_ph)
    summary = {
        "out_dir": str(out_dir),
        "csv": str(csv_path),
        "outlet_image": str(outlet_path),
        "soil_image": str(soil_path),
        "outlet_ec_mae": float(np.mean(outlet_ec_error)),
        "outlet_ph_mae": float(np.mean(outlet_ph_error)),
        "soil_ec_mae": float(np.mean(soil_ec_error)),
        "soil_ph_mae": float(np.mean(soil_ph_error)),
        "sensor_period_s": float(args.sensor_period_s),
        "soil_sensor_period_min": float(args.soil_sensor_period_min),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate realistic field EC/pH outlet response and soil trend.")
    parser.add_argument("--duration-h", type=float, default=24.0)
    parser.add_argument("--dt-s", type=float, default=10.0)
    parser.add_argument("--sensor-period-s", type=float, default=5.0)
    parser.add_argument("--soil-sensor-period-min", type=float, default=15.0)
    parser.add_argument("--target-ec", type=float, default=1.2)
    parser.add_argument("--target-ph", type=float, default=6.1)
    parser.add_argument("--initial-ec", type=float, default=0.8)
    parser.add_argument("--initial-ph", type=float, default=6.2)
    parser.add_argument("--initial-soil-ec", type=float, default=0.8)
    parser.add_argument("--initial-soil-ph", type=float, default=6.2)
    parser.add_argument("--pipe-dead-time-min", type=float, default=8.0)
    parser.add_argument("--outlet-tau-min", type=float, default=12.0)
    parser.add_argument("--soil-dead-time-h", type=float, default=0.5)
    parser.add_argument("--soil-ec-tau-h", type=float, default=6.0)
    parser.add_argument("--soil-ph-tau-h", type=float, default=8.0)
    args = parser.parse_args()

    _, summary = simulate(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
