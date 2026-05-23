"""Matplotlib 图表生成 — 替代前端 Chart.js，与终端 main.py 同款"""
import os
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from plot_style import (
    apply_academic_style, style_axis, set_ylim_tight,
    EC_ACTUAL, EC_TARGET, THETA, QF, QA, ET_COLOR, IRRIGATION,
    FC_LINE, WP_LINE, T1, T2,
)

# ---- 中文字体 ----
try:
    simhei_path = r"C:\Windows\Fonts\simhei.ttf"
    if os.path.exists(simhei_path):
        fm.fontManager.addfont(simhei_path)
        plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False
except Exception:
    pass


def _save(fig, prefix, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d%H%M%S")
    fname = f"{prefix}_{ts}.png"
    path = os.path.join(output_dir, fname)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return fname


def make_sim_plot(time_hours, theta, ec_soil, ec_target, irrigation, etc,
                  q_f, q_a, mode_label, output_dir):
    """生成 5 天仿真 4 子图"""
    apply_academic_style()
    time_hours = np.array(time_hours)
    theta = np.array(theta); ec_soil = np.array(ec_soil)
    ec_target = np.array(ec_target); irrigation = np.array(irrigation)
    etc = np.array(etc); q_f = np.array(q_f); q_a = np.array(q_a)

    fig, axes = plt.subplots(4, 1, figsize=(9, 10), sharex=True)
    fig.subplots_adjust(hspace=0.38)

    # Subplot 1: theta
    ax = axes[0]; style_axis(ax)
    ax.plot(time_hours, theta, color=THETA, linewidth=1.5, label='θ (moisture)')
    ax.axhline(y=0.32, color=FC_LINE, linestyle='--', linewidth=1.0, alpha=0.8, label='Field capacity')
    ax.axhline(y=0.04, color=WP_LINE, linestyle=':', linewidth=1.0, alpha=0.8, label='Wilting point')
    set_ylim_tight(ax, theta, pad_pct=5, min_val=0.0)
    ax.set_ylabel('θ (m³/m³)')
    ax.set_title(f'Root-zone soil moisture [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    # Subplot 2: EC
    ax = axes[1]; style_axis(ax)
    ax.plot(time_hours, ec_soil, color=EC_ACTUAL, linewidth=1.5, label='EC_soil')
    ax.plot(time_hours, ec_target, color=EC_TARGET, linestyle='--', linewidth=1.8, label='Target EC')
    ax.fill_between(time_hours, ec_soil, ec_target, color='#d0d0d0', alpha=0.35, linewidth=0)
    set_ylim_tight(ax, np.concatenate([ec_soil, ec_target]), pad_pct=8)
    ax.set_ylabel('EC (dS/m)')
    ax.set_title(f'Root-zone EC vs target [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    # Subplot 3: Irrigation & ET
    ax = axes[2]; style_axis(ax)
    ax.fill_between(time_hours, 0, irrigation, color=IRRIGATION, alpha=0.30, linewidth=0, label='Irrigation')
    ax.plot(time_hours, etc, color=ET_COLOR, linewidth=2.0, linestyle='--', label='ET (mm/h)')
    set_ylim_tight(ax, np.concatenate([irrigation, etc]), pad_pct=10, min_val=0.0)
    ax.set_ylabel('Rate (mm/h)')
    ax.set_title(f'Irrigation and evapotranspiration [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    # Subplot 4: Actions
    ax = axes[3]; style_axis(ax)
    n = len(time_hours); mk = max(1, n // 40)
    ax.plot(time_hours, q_f, color=QF, linewidth=1.2, marker='o', markersize=3.0, markevery=mk, label='q_f (fertilizer)')
    ax.plot(time_hours, q_a, color=QA, linewidth=1.2, marker='^', markersize=3.5, markevery=mk, label='q_a (acid)')
    set_ylim_tight(ax, np.concatenate([q_f, q_a]), pad_pct=10)
    ax.set_xlabel('Time (hours)')
    ax.set_ylabel('Flow (L/min)')
    ax.set_title(f'Actions over time [{mode_label}]')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    return _save(fig, "sim", output_dir)


def make_season_plot(t1, t2, output_dir):
    """生成 T1 vs T2 对比 4 子图"""
    apply_academic_style()

    fig, axes = plt.subplots(4, 1, figsize=(9, 10), sharex=True)
    fig.subplots_adjust(hspace=0.38)

    for strategy in ["T1", "T2"]:
        d = t1 if strategy == "T1" else t2
        c = T1 if strategy == "T1" else T2
        ls = "-" if strategy == "T1" else "--"
        lbl = f"{strategy} ({'equal' if strategy == 'T1' else 'root-zone'})"

        td = np.array(d["time_day"]); th = np.array(d["theta"])
        ec = np.array(d["ec_soil"]); irr = np.array(d["irrigation_mm_h"])

        ax = axes[0]
        ax.plot(td, th, color=c, linestyle=ls, linewidth=1.5, alpha=0.85, label=lbl)

        ax = axes[1]
        ax.plot(td, ec, color=c, linestyle=ls, linewidth=1.5, alpha=0.85, label=f'{lbl} EC_soil')

        ax = axes[2]
        em = np.array(d["event_marker"]) > 0.5
        ax.fill_between(td, 0, irr, where=em, color=c, alpha=0.28, linewidth=0, label=lbl)
        ax.plot(td, irr, color=c, linewidth=0.8, alpha=0.55, drawstyle='steps-post')

        ax = axes[3]
        cum = np.cumsum(irr) * (15.0 / 60.0)
        ax.plot(td, cum, color=c, linestyle=ls, linewidth=1.5, label=lbl)

    # Subplot 1: theta
    ax = axes[0]; style_axis(ax)
    ax.axhline(y=0.32, color=FC_LINE, linestyle='--', linewidth=0.8, alpha=0.6)
    ax.axhline(y=0.04, color=WP_LINE, linestyle=':', linewidth=0.8, alpha=0.6)
    all_theta = np.concatenate([t1["theta"], t2["theta"]])
    set_ylim_tight(ax, all_theta, pad_pct=5, min_val=0.0)
    ax.set_ylabel('θ (m³/m³)')
    ax.set_title('Root-zone soil moisture — T1 vs T2')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    # Subplot 2: EC
    ax = axes[1]; style_axis(ax)
    ax.plot(np.array(t1["time_day"]), np.array(t1["target_ec"]), color='#333333', linestyle=':',
            linewidth=1.2, alpha=0.7, label='Target EC')
    all_ec = np.concatenate([t1["ec_soil"], t2["ec_soil"], t1["target_ec"]])
    set_ylim_tight(ax, all_ec, pad_pct=8)
    ax.set_ylabel('EC (dS/m)')
    ax.set_title('Root-zone EC dynamics — T1 vs T2')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    # Subplot 3: irrigation
    ax = axes[2]; style_axis(ax)
    all_irr = np.concatenate([t1["irrigation_mm_h"], t2["irrigation_mm_h"]])
    set_ylim_tight(ax, all_irr, pad_pct=10, min_val=0.0)
    ax.set_ylabel('Irrigation (mm/h)')
    ax.set_title('Irrigation event sequence')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    # Subplot 4: cumulative
    ax = axes[3]; style_axis(ax)
    ax.set_xlabel('Days after emergence')
    ax.set_ylabel('Cumulative irrigation (mm)')
    ax.set_title('Cumulative irrigation')
    ax.legend(loc='upper right', framealpha=0.55, edgecolor='#aaaaaa', fontsize=8.5, borderpad=0.5)

    return _save(fig, "season", output_dir)
