"""
Academic publication-quality matplotlib style.
Provides colorblind-friendly palette and consistent styling for all figures.
"""

import matplotlib.pyplot as plt
import numpy as np

# ============================================================
# Colorblind-friendly palette
# ============================================================
EC_ACTUAL  = '#D73027'   # dark red — measured EC
EC_TARGET  = '#1A9850'   # dark green — target EC
THETA      = '#0072B2'   # blue — soil moisture
QF         = '#0072B2'   # blue — fertilizer flow
QA         = '#D55E00'   # vermilion — acid flow
ET_COLOR   = '#B35900'   # brick orange — evapotranspiration
IRRIGATION = '#56B4E9'   # sky blue — irrigation
FC_LINE    = '#888888'   # gray — field capacity line
WP_LINE    = '#D73027'   # dark red — wilting point line
T1         = '#0072B2'   # blue — T1 strategy (equal irrigation)
T2         = '#D55E00'   # vermilion — T2 strategy (root-zone weighted)

# ----------------------------------------------------------
ERROR_BAND = '#d0d0d0'   # light gray — EC error shading


def apply_academic_style():
    """Apply publication-quality rcParams globally.

    Call once before creating any figure.
    """
    plt.rcParams.update({
        # Font
        'font.family': 'sans-serif',
        'font.sans-serif': ['SimHei', 'Arial', 'Helvetica', 'DejaVu Sans'],
        'font.size': 10,
        'axes.titlesize': 11,
        'axes.labelsize': 10,
        'xtick.labelsize': 9,
        'ytick.labelsize': 9,
        'legend.fontsize': 8.5,
        # Output
        'figure.dpi': 300,
        'savefig.dpi': 300,
        'savefig.bbox': 'tight',
        # Lines & markers
        'lines.linewidth': 1.5,
        'lines.markersize': 5,
        'lines.markeredgewidth': 0.5,
        'lines.markerfacecolor': 'none',
        'lines.markeredgecolor': 'auto',
        # Axes
        'axes.linewidth': 0.8,
        'axes.grid': False,               # we set grid per-axis
        'axes.unicode_minus': False,
        # Ticks
        'xtick.major.width': 0.8,
        'ytick.major.width': 0.8,
        'xtick.major.size': 3.5,
        'ytick.major.size': 3.5,
        'xtick.minor.width': 0.5,
        'ytick.minor.width': 0.5,
        # Legend
        'legend.frameon': True,
        'legend.framealpha': 0.55,
        'legend.edgecolor': '#aaaaaa',
        'legend.fancybox': False,
        'legend.loc': 'upper right',
        'legend.borderpad': 0.5,
        'legend.labelspacing': 0.4,
    })


def style_axis(ax):
    """Apply common axis styling: clean spines, horizontal dashed grid, ticks out."""
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(0.8)
    ax.spines['bottom'].set_linewidth(0.8)
    ax.grid(True, axis='y', alpha=0.35, linestyle='--', linewidth=0.4, color='#b0b0b0')
    ax.set_axisbelow(True)
    ax.tick_params(direction='out', which='both')


def set_ylim_tight(ax, data, pad_pct=5, min_val=None, max_val=None):
    """Set y-axis limits with percentage padding around the data range.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
    data : array-like
    pad_pct : float
        Padding as percentage of data range (e.g. 5 → ±5%).
    min_val : float or None
        Clamp lower bound to this minimum.
    max_val : float or None
        Clamp upper bound to this maximum.
    """
    arr = np.asarray(data)
    lo, hi = arr.min(), arr.max()
    margin = max((hi - lo) * pad_pct / 100.0, 1e-6)
    lo, hi = lo - margin, hi + margin
    if min_val is not None:
        lo = max(lo, min_val)
    if max_val is not None:
        hi = min(hi, max_val)
    if lo < hi:
        ax.set_ylim(lo, hi)
