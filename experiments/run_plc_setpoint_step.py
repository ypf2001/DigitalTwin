"""PLC outlet EC/pH fixed-setpoint step test.

This script bypasses the field/root-zone lifecycle model. It only closes the
loop around the PLC controller with a simple outlet process:

    fixed EC/pH setpoint -> PLC nonlinear gain-scheduled PID -> q_f/q_a
    -> mixing tank + pipe dynamics -> EC_Actual/pH_Actual feedback

Use it before full-season runs to tune the PLC execution layer until the outlet
can reach and hold a target.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from mixing_tank import MixingTank
from pipe_dynamics import PipeDynamics
from plc_client import PLCClient


STAGE_INDEX = {
    "INI": 0,
    "DEV": 1,
    "MID": 2,
    "LATE": 3,
}


def _settling_time(rows: list[dict[str, float]], name: str, band: float) -> float | None:
    actual_key = f"{name}_actual"
    set_key = f"{name}_set"
    for i, _ in enumerate(rows):
        if all(abs(r[actual_key] - r[set_key]) <= band for r in rows[i:]):
            return float(rows[i]["time_s"])
    return None


def _plot(out_dir: Path, rows: list[dict[str, float]]) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    simhei_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if simhei_path.exists():
        fm.fontManager.addfont(str(simhei_path))
        plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    t = np.array([r["time_s"] for r in rows], dtype=float)
    ec = np.array([r["ec_actual"] for r in rows], dtype=float)
    ph = np.array([r["ph_actual"] for r in rows], dtype=float)
    q_f = np.array([r["q_f_cmd"] for r in rows], dtype=float)
    q_a = np.array([r["q_a_cmd"] for r in rows], dtype=float)
    ec_sp = np.array([r["ec_set"] for r in rows], dtype=float)
    ph_sp = np.array([r["ph_set"] for r in rows], dtype=float)

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(t, ec, color="#26734d", linewidth=1.5, label="EC actual")
    axes[0].step(t, ec_sp, where="post", color="#26734d", linestyle="--", linewidth=1.0, label="EC set")
    axes[0].set_ylabel("EC")
    axes[0].legend(loc="best")

    axes[1].plot(t, ph, color="#2f5f9f", linewidth=1.5, label="pH actual")
    axes[1].step(t, ph_sp, where="post", color="#2f5f9f", linestyle="--", linewidth=1.0, label="pH set")
    axes[1].set_ylabel("pH")
    axes[1].legend(loc="best")

    axes[2].plot(t, q_f, color="#6f8f2f", linewidth=1.3, label="q_f")
    axes[2].plot(t, q_a, color="#9f4f5f", linewidth=1.3, label="q_a")
    axes[2].set_ylabel("L/min")
    axes[2].set_xlabel("Time (s)")
    axes[2].legend(loc="best")

    for ax in axes:
        ax.grid(True, axis="y", color="#dddddd", linewidth=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.tight_layout()
    plot_path = out_dir / "plc_setpoint_step.png"
    fig.savefig(plot_path, dpi=220)
    plt.close(fig)
    return plot_path


def run(args: argparse.Namespace) -> tuple[Path, dict[str, float]]:
    logging.getLogger("plc_client").setLevel(logging.WARNING)

    cfg = load_config()
    q_w = float(args.q_w if args.q_w is not None else cfg.env().get("q_w", 136.0))

    # 这里保留最小过程模型，只验证 PLC 出口闭环；田间/根区模型不参与。
    tank = MixingTank()
    # sim_step_s 是仿真时间步长，plc_wait_s 是真实等待时间。
    # 设 sim_step_s > plc_wait_s 可以快速跑完 8min 管道延迟，而不用真的等 8 分钟。
    sim_step_s = float(args.sim_step_s if args.sim_step_s is not None else args.plc_wait_s)
    pipe = PipeDynamics(
        tau=args.pipe_tau_min,
        T=args.pipe_t_min,
        dt=max(sim_step_s / 60.0, 1e-6),
    )
    tank.reset()
    pipe.reset()

    plc = PLCClient(cycle_s=args.plc_wait_s)
    if not plc.connect():
        raise RuntimeError("PLC connection failed.")

    # 先建立远程通信握手，再写入 A/B 测试选择位。PLC 在通信未健康时会
    # 自动清除 Fixed_PID_Test_Enable，若连接后立即写入会造成固定 PID
    # 测试实际仍运行自适应 PID。
    if not plc.write_setpoints(
        ec_set=args.ec_set,
        ph_set=args.ph_set,
        ec_actual=float(args.ec_initial),
        ph_actual=float(args.ph_initial),
        sac_enable=True,
    ):
        raise RuntimeError("PLC remote handshake write failed.")
    time.sleep(args.plc_wait_s)
    plc.read_state()
    if not plc.write_fixed_pid_test_mode(bool(args.fixed_pid_test)):
        raise RuntimeError("PLC fixed/adaptive PID test selection failed.")
    time.sleep(args.plc_wait_s)
    pid_mode_state = plc.read_state() or {}
    if bool(pid_mode_state.get("Fixed_PID_Test_Enable", False)) != bool(args.fixed_pid_test):
        raise RuntimeError("PLC did not retain the requested fixed/adaptive PID test mode.")

    pid_args = [args.kp_ec, args.ki_ec, args.kd_ec, args.kp_ph, args.ki_ph, args.kd_ph]
    if any(v is not None for v in pid_args) or args.ec_trim_band is not None or args.ph_trim_band is not None:
        state = plc.read_state() or {}
        plc.write_pid_params(
            kp_ec=float(args.kp_ec if args.kp_ec is not None else state.get("Kp_EC_Set", 1.2)),
            ki_ec=float(args.ki_ec if args.ki_ec is not None else state.get("Ki_EC_Set", 0.0)),
            kd_ec=float(args.kd_ec if args.kd_ec is not None else state.get("Kd_EC_Set", 0.0)),
            kp_ph=float(args.kp_ph if args.kp_ph is not None else state.get("Kp_pH_Set", 1.2)),
            ki_ph=float(args.ki_ph if args.ki_ph is not None else state.get("Ki_pH_Set", 0.01)),
            kd_ph=float(args.kd_ph if args.kd_ph is not None else state.get("Kd_pH_Set", 0.0)),
            ec_trim_band=args.ec_trim_band,
            ph_trim_band=args.ph_trim_band,
        )

    out_dir = ROOT / "results" / "plc_setpoint_step" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "plc_setpoint_step.csv"

    rows: list[dict[str, float]] = []
    ec_actual = float(args.ec_initial)
    ph_actual = float(args.ph_initial)
    stage = STAGE_INDEX[args.stage.upper()]
    total_steps = max(1, int(round(args.duration_s / sim_step_s)))

    fieldnames = [
        "step",
        "time_s",
        "ec_set",
        "ph_set",
        "ec_actual",
        "ph_actual",
        "ec_feedback",
        "ph_feedback",
        "q_f_cmd",
        "q_a_cmd",
        "q_w",
        "remote_comms_ok",
        "active_ec_sp",
        "active_ph_sp",
        "setpoint_protection",
        "fixed_pid_test_enable",
        "adaptive_pid_active",
        "kp_ec_effective",
        "ki_ec_effective",
        "kd_ec_effective",
        "kp_ph_effective",
        "ki_ph_effective",
        "kd_ph_effective",
    ]

    csv_file = csv_path.open("w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    csv_file.flush()

    try:
        plc.write_growth_stage(stage)

        for step in range(total_steps):
            t_s = step * sim_step_s
            ec_set = args.ec_set
            ph_set = args.ph_set
            if args.change_at_s is not None and t_s >= args.change_at_s:
                ec_set = args.ec_set_2 if args.ec_set_2 is not None else ec_set
                ph_set = args.ph_set_2 if args.ph_set_2 is not None else ph_set

            ec_feedback = ec_set if args.disable_ec_loop else ec_actual
            ph_feedback = ph_set if args.disable_ph_loop else ph_actual
            # DB1 写入顺序：目标值 + 出口反馈 + SAC_Enable。
            # 真实部署时 ec_actual/ph_actual 应来自传感器；纯仿真时由 tank/pipe 模型回写。
            ok = plc.write_setpoints(
                ec_set=ec_set,
                ph_set=ph_set,
                ec_actual=ec_feedback,
                ph_actual=ph_feedback,
                sac_enable=True,
            )
            time.sleep(args.plc_wait_s)
            state = plc.read_state() or {}

            q_f = float(state.get("q_f_cmd", 0.0))
            q_a = float(state.get("q_a_cmd", 0.0))
            # PLC 只输出执行量 q_f/q_a；过程响应由这里模拟，再写回下一轮 DB1。
            ec_tank, ph_tank = tank.step(q_f=q_f, q_a=q_a, q_w=q_w)
            ec_actual, ph_actual = pipe.step(ec_tank, ph_tank)

            row = {
                "step": step,
                "time_s": t_s,
                "ec_set": float(ec_set),
                "ph_set": float(ph_set),
                "ec_actual": float(ec_actual),
                "ph_actual": float(ph_actual),
                "ec_feedback": float(ec_feedback),
                "ph_feedback": float(ph_feedback),
                "q_f_cmd": q_f,
                "q_a_cmd": q_a,
                "q_w": q_w,
                "remote_comms_ok": bool(state.get("Remote_Comms_OK", False)),
                "active_ec_sp": float(state.get("Active_EC_SP", args.ec_set)),
                "active_ph_sp": float(state.get("Active_pH_SP", args.ph_set)),
                "setpoint_protection": bool(state.get("Setpoint_Protection_Active", False)),
                "fixed_pid_test_enable": bool(state.get("Fixed_PID_Test_Enable", False)),
                "adaptive_pid_active": bool(state.get("Adaptive_PID_Active", False)),
                "kp_ec_effective": float(state.get("Kp_EC_Effective", 0.0)),
                "ki_ec_effective": float(state.get("Ki_EC_Effective", 0.0)),
                "kd_ec_effective": float(state.get("Kd_EC_Effective", 0.0)),
                "kp_ph_effective": float(state.get("Kp_pH_Effective", 0.0)),
                "ki_ph_effective": float(state.get("Ki_pH_Effective", 0.0)),
                "kd_ph_effective": float(state.get("Kd_pH_Effective", 0.0)),
            }
            rows.append(row)
            writer.writerow(row)
            csv_file.flush()

            if step % max(args.log_every, 1) == 0:
                print(
                    f"t={t_s:6.1f}s EC={ec_actual:.3f}/{ec_set:.3f} "
                    f"pH={ph_actual:.3f}/{ph_set:.3f} "
                    f"q_f={q_f:.3f} q_a={q_a:.3f}",
                    flush=True,
                )

    finally:
        csv_file.close()
        try:
            plc.write_fixed_pid_test_mode(False)
            plc.write_setpoints(args.ec_set, args.ph_set, ec_actual, ph_actual, sac_enable=False)
        finally:
            plc.disconnect()

    plot_path = _plot(out_dir, rows)

    tail = rows[max(0, len(rows) - max(3, int(round(30.0 / sim_step_s)))) :]
    ec_errors = [r["ec_actual"] - r["ec_set"] for r in rows]
    ph_errors = [r["ph_actual"] - r["ph_set"] for r in rows]
    ph_tail_drop = float(tail[0]["ph_actual"] - tail[-1]["ph_actual"])
    metrics = {
        "ec_final": rows[-1]["ec_actual"],
        "ph_final": rows[-1]["ph_actual"],
        "ec_tail_mae": float(np.mean([abs(r["ec_actual"] - r["ec_set"]) for r in tail])),
        "ph_tail_mae": float(np.mean([abs(r["ph_actual"] - r["ph_set"]) for r in tail])),
        "ec_max_overshoot": float(max(ec_errors)),
        "ec_max_undershoot": float(min(ec_errors)),
        "ph_max_overshoot": float(max(ph_errors)),
        "ph_max_undershoot": float(min(ph_errors)),
        "ec_settle_s": _settling_time(rows, "ec", args.ec_settle_band),
        "ph_settle_s": _settling_time(rows, "ph", args.ph_settle_band),
        "ph_tail_drop": ph_tail_drop,
        "q_f_final": rows[-1]["q_f_cmd"],
        "q_a_final": rows[-1]["q_a_cmd"],
    }
    passed = (
        metrics["ec_tail_mae"] <= args.ec_mae_max
        and metrics["ph_tail_mae"] <= args.ph_mae_max
        and abs(rows[-1]["ec_actual"] - rows[-1]["ec_set"]) <= args.ec_final_band
        and abs(rows[-1]["ph_actual"] - rows[-1]["ph_set"]) <= args.ph_final_band
        and metrics["ph_tail_drop"] <= args.ph_tail_drop_max
    )
    print(f"Saved CSV: {csv_path}", flush=True)
    print(f"Saved plot: {plot_path}", flush=True)
    print(
        "Tail MAE: "
        f"EC={metrics['ec_tail_mae']:.4f}, pH={metrics['ph_tail_mae']:.4f}",
        flush=True,
    )
    print(
        "Final error: "
        f"EC={rows[-1]['ec_actual'] - rows[-1]['ec_set']:+.4f}, "
        f"pH={rows[-1]['ph_actual'] - rows[-1]['ph_set']:+.4f}",
        flush=True,
    )
    print(
        "Settling time: "
        f"EC={metrics['ec_settle_s'] if metrics['ec_settle_s'] is not None else 'not settled'}s, "
        f"pH={metrics['ph_settle_s'] if metrics['ph_settle_s'] is not None else 'not settled'}s",
        flush=True,
    )
    print(f"pH tail drop: {metrics['ph_tail_drop']:+.4f}", flush=True)
    (out_dir / "metrics.json").write_text(
        __import__("json").dumps({"passed": passed, "metrics": metrics}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Outlet control verdict: {'PASS' if passed else 'FAIL'}", flush=True)
    if args.strict and not passed:
        raise RuntimeError("Outlet control metrics did not meet thresholds.")
    return out_dir, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PLC fixed EC/pH outlet setpoint step test.")
    parser.add_argument("--ec-set", type=float, default=1.5)
    parser.add_argument("--ph-set", type=float, default=5.9)
    parser.add_argument("--change-at-s", type=float, default=None, help="Switch to second target after this many seconds.")
    parser.add_argument("--ec-set-2", type=float, default=None)
    parser.add_argument("--ph-set-2", type=float, default=None)
    parser.add_argument("--ec-initial", type=float, default=0.0)
    parser.add_argument("--ph-initial", type=float, default=7.2)
    parser.add_argument("--stage", choices=["INI", "DEV", "MID", "LATE"], default="MID")
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--plc-wait-s", type=float, default=1.0)
    parser.add_argument("--sim-step-s", type=float, default=None, help="Simulated seconds advanced per PLC exchange. Defaults to --plc-wait-s.")
    parser.add_argument("--pipe-tau-min", type=float, default=None, help="Pipe pure delay in minutes. Default uses config.")
    parser.add_argument("--pipe-t-min", type=float, default=None, help="Pipe first-order time constant in minutes. Default uses config.")
    parser.add_argument("--q-w", type=float, default=None)
    parser.add_argument("--log-every", type=int, default=5)
    parser.add_argument("--disable-ec-loop", action="store_true", help="Feed EC setpoint back to PLC to isolate pH loop.")
    parser.add_argument("--disable-ph-loop", action="store_true", help="Feed pH setpoint back to PLC to isolate EC loop.")
    parser.add_argument("--kp-ec", type=float, default=None, help="Optional online EC Kp override.")
    parser.add_argument("--ki-ec", type=float, default=None, help="Optional online EC Ki override.")
    parser.add_argument("--kd-ec", type=float, default=None, help="Optional online EC Kd override.")
    parser.add_argument("--kp-ph", type=float, default=None, help="Optional online pH Kp override.")
    parser.add_argument("--ki-ph", type=float, default=None, help="Optional online pH Ki override.")
    parser.add_argument("--kd-ph", type=float, default=None, help="Optional online pH Kd override.")
    parser.add_argument("--ec-trim-band", type=float, default=None, help="Optional EC fine-trim band override, e.g. 0.08.")
    parser.add_argument("--ph-trim-band", type=float, default=None, help="Optional pH fine-trim band override, e.g. 0.08.")
    parser.add_argument("--ec-mae-max", type=float, default=0.03)
    parser.add_argument("--ph-mae-max", type=float, default=0.05)
    parser.add_argument("--ec-final-band", type=float, default=0.05)
    parser.add_argument("--ph-final-band", type=float, default=0.08)
    parser.add_argument("--ec-settle-band", type=float, default=0.05)
    parser.add_argument("--ph-settle-band", type=float, default=0.08)
    parser.add_argument("--ph-tail-drop-max", type=float, default=0.02, help="Max allowed pH decrease over the tail window.")
    parser.add_argument("--fixed-pid-test", action="store_true", help="Use fixed base PID gains for PLC A/B comparison.")
    parser.add_argument("--strict", action="store_true", help="Exit with error if outlet metrics fail thresholds.")
    args = parser.parse_args()

    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
