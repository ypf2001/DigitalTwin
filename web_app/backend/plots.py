"""Matplotlib 图表生成 — 替代前端 Chart.js，与终端 main.py 同款"""
import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 添加项目根目录到 sys.path，确保能导入 plot_style
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from plot_style import (
    apply_academic_style, set_ylim_tight,
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
    fig.savefig(path, dpi=200, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    return fname


def make_sim_plot(time_hours, theta, ec_soil, ec_target, irrigation, etc,
                  q_f, q_a, mode_label, output_dir):
    """生成 5 天仿真 4 子图 - 美化版"""
    apply_academic_style()
    time_hours = np.array(time_hours)
    theta = np.array(theta); ec_soil = np.array(ec_soil)
    ec_target = np.array(ec_target); irrigation = np.array(irrigation)
    etc = np.array(etc); q_f = np.array(q_f); q_a = np.array(q_a)

    fig, axes = plt.subplots(4, 1, figsize=(10, 11), sharex=True)
    fig.patch.set_facecolor('#f8f9fa')
    fig.subplots_adjust(hspace=0.40, left=0.12, right=0.95, top=0.94, bottom=0.08)

    # 标题
    fig.suptitle(f'马铃薯施肥灌溉仿真 [{mode_label}]', fontsize=16, fontweight='bold', y=0.98, color='#2c3e50')

    # 子图样式
    subplot_style = {
        'facecolor': '#ffffff',
        'edgecolor': '#dee2e6',
        'linewidth': 1,
        'borderpad': 0.8,
    }

    # Subplot 1: 土壤含水率
    ax = axes[0]
    ax.set_facecolor('#ffffff')
    ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
    ax.plot(time_hours, theta, color='#3498db', linewidth=2.0, label='θ (含水率)', zorder=3)
    ax.fill_between(time_hours, theta, alpha=0.15, color='#3498db', zorder=2)
    ax.axhline(y=0.32, color='#27ae60', linestyle='--', linewidth=1.5, alpha=0.8, label='田间持水量 (FC)')
    ax.axhline(y=0.04, color='#e74c3c', linestyle=':', linewidth=1.5, alpha=0.8, label='凋萎点 (WP)')
    set_ylim_tight(ax, theta, pad_pct=8, min_val=0.0)
    ax.set_ylabel('θ (m³/m³)', fontsize=11, fontweight='medium')
    ax.set_title('① 根区土壤含水率', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Subplot 2: EC 动态
    ax = axes[1]
    ax.set_facecolor('#ffffff')
    ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
    ax.plot(time_hours, ec_soil, color='#e74c3c', linewidth=2.0, label='EC_soil (实际)', zorder=3)
    ax.plot(time_hours, ec_target, color='#9b59b6', linestyle='--', linewidth=2.2, label='Target EC (目标)', zorder=3)
    ax.fill_between(time_hours, ec_soil, ec_target, color='#f39c12', alpha=0.25, linewidth=0, zorder=1)
    set_ylim_tight(ax, np.concatenate([ec_soil, ec_target]), pad_pct=12)
    ax.set_ylabel('EC (dS/m)', fontsize=11, fontweight='medium')
    ax.set_title('② 根区电导率 vs 目标值', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Subplot 3: 灌溉与蒸散发
    ax = axes[2]
    ax.set_facecolor('#ffffff')
    ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
    ax.fill_between(time_hours, 0, irrigation, color='#3498db', alpha=0.40, linewidth=0, label='灌溉量', zorder=2)
    ax.plot(time_hours, irrigation, color='#2980b9', linewidth=0.8, alpha=0.7, zorder=3)
    ax.plot(time_hours, etc, color='#e67e22', linewidth=2.0, linestyle='-.', label='ET (蒸散发)', zorder=3)
    set_ylim_tight(ax, np.concatenate([irrigation, etc]), pad_pct=15, min_val=0.0)
    ax.set_ylabel('流量 (mm/h)', fontsize=11, fontweight='medium')
    ax.set_title('③ 灌溉与蒸散发速率', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Subplot 4: 动作
    ax = axes[3]
    ax.set_facecolor('#ffffff')
    ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
    n = len(time_hours); mk = max(1, n // 30)
    ax.plot(time_hours, q_f, color='#2ecc71', linewidth=1.8, marker='o', markersize=4, markevery=mk,
            label='q_f (施肥流量)', zorder=3)
    ax.plot(time_hours, q_a, color='#f39c12', linewidth=1.8, marker='s', markersize=4, markevery=mk,
            label='q_a (酸液流量)', zorder=3)
    set_ylim_tight(ax, np.concatenate([q_f, q_a]), pad_pct=15)
    ax.set_xlabel('时间 (小时)', fontsize=11, fontweight='medium')
    ax.set_ylabel('流量 (L/min)', fontsize=11, fontweight='medium')
    ax.set_title('④ 控制动作', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    return _save(fig, "sim", output_dir)


def make_season_plot(t1, t2, output_dir):
    """生成 T1 vs T2 对比 4 子图 - 美化版"""
    apply_academic_style()

    fig, axes = plt.subplots(4, 1, figsize=(10, 11), sharex=True)
    fig.patch.set_facecolor('#f8f9fa')
    fig.subplots_adjust(hspace=0.40, left=0.12, right=0.95, top=0.94, bottom=0.08)

    # 标题
    fig.suptitle('马铃薯完整生育期 T1 vs T2 对比仿真', fontsize=16, fontweight='bold', y=0.98, color='#2c3e50')

    for strategy in ["T1", "T2"]:
        d = t1 if strategy == "T1" else t2
        c = '#3498db' if strategy == "T1" else '#e74c3c'
        ls = "-" if strategy == "T1" else "--"
        lbl = 'T1 (等量灌溉)' if strategy == "T1" else 'T2 (根系分布灌溉)'
        mfc = 'white' if strategy == "T1" else 'white'

        td = np.array(d["time_day"]); th = np.array(d["theta"])
        ec = np.array(d["ec_soil"]); irr = np.array(d["irrigation_mm_h"])

        # Subplot 1: theta
        ax = axes[0]
        ax.set_facecolor('#ffffff')
        ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
        ax.plot(td, th, color=c, linestyle=ls, linewidth=1.8, alpha=0.9, label=lbl, zorder=3)

        # Subplot 2: EC
        ax = axes[1]
        ax.set_facecolor('#ffffff')
        ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
        ax.plot(td, ec, color=c, linestyle=ls, linewidth=1.8, alpha=0.9, label=lbl, zorder=3)

        # Subplot 3: irrigation
        ax = axes[2]
        ax.set_facecolor('#ffffff')
        ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
        em = np.array(d["event_marker"]) > 0.5
        ax.fill_between(td, 0, irr, where=em, color=c, alpha=0.35, linewidth=0, label=lbl, zorder=2)
        ax.plot(td, irr, color=c, linewidth=0.6, alpha=0.5, drawstyle='steps-post', zorder=2)

        # Subplot 4: cumulative
        ax = axes[3]
        ax.set_facecolor('#ffffff')
        ax.grid(True, linestyle='--', alpha=0.4, color='#bdc3c7', linewidth=0.5)
        cum = np.cumsum(irr) * (15.0 / 60.0)
        ax.plot(td, cum, color=c, linestyle=ls, linewidth=2.0, label=lbl, zorder=3)

    # Subplot 1: theta
    ax = axes[0]
    ax.axhline(y=0.32, color='#27ae60', linestyle='--', linewidth=1.5, alpha=0.7, label='田间持水量')
    ax.axhline(y=0.04, color='#e74c3c', linestyle=':', linewidth=1.5, alpha=0.7, label='凋萎点')
    all_theta = np.concatenate([t1["theta"], t2["theta"]])
    set_ylim_tight(ax, all_theta, pad_pct=8, min_val=0.0)
    ax.set_ylabel('θ (m³/m³)', fontsize=11, fontweight='medium')
    ax.set_title('① 根区土壤含水率', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              ncol=3, fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Subplot 2: EC
    ax = axes[1]
    ax.plot(np.array(t1["time_day"]), np.array(t1["target_ec"]), color='#8e44ad', linestyle=':',
            linewidth=2.0, alpha=0.8, label='目标 EC', zorder=4)
    all_ec = np.concatenate([t1["ec_soil"], t2["ec_soil"], t1["target_ec"]])
    set_ylim_tight(ax, all_ec, pad_pct=12)
    ax.set_ylabel('EC (dS/m)', fontsize=11, fontweight='medium')
    ax.set_title('② 根区电导率动态', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              ncol=3, fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Subplot 3: irrigation
    ax = axes[2]
    all_irr = np.concatenate([t1["irrigation_mm_h"], t2["irrigation_mm_h"]])
    set_ylim_tight(ax, all_irr, pad_pct=15, min_val=0.0)
    ax.set_ylabel('灌溉 (mm/h)', fontsize=11, fontweight='medium')
    ax.set_title('③ 灌溉事件序列', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              ncol=2, fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Subplot 4: cumulative
    ax = axes[3]
    ax.set_xlabel('出苗后天数', fontsize=11, fontweight='medium')
    ax.set_ylabel('累计灌溉量 (mm)', fontsize=11, fontweight='medium')
    ax.set_title('④ 累计灌溉量对比', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
    ax.legend(loc='lower right', framealpha=0.9, edgecolor='#bdc3c7', fontsize=9, borderpad=0.6,
              ncol=2, fancybox=True, shadow=True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    return _save(fig, "season", output_dir)
