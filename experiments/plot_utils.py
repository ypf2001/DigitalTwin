"""experiments 绘图通用工具。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np


def _as_axes_list(axes: Any) -> list[Any]:
    """把单个 Axes、list 或 ndarray 统一转成一维列表。"""
    if isinstance(axes, np.ndarray):
        return list(axes.ravel())
    if isinstance(axes, Iterable) and not hasattr(axes, "plot"):
        return list(axes)
    return [axes]


def set_x_axis_origin(axes: Any, right: float | None = None, left: float = 0.0) -> None:
    """统一横轴原点，让 0 刻度贴合纵轴。

    Matplotlib 默认会给横轴留白，导致 0 点看起来不在原点。实验图统一调用
    这个函数关闭横向边距，并显式设置横轴左边界。
    """
    for ax in _as_axes_list(axes):
        ax.set_xlim(left=left, right=right)
        ax.margins(x=0.0)


def set_time_axis_origin(axes: Any, *time_series: Any, left: float = 0.0) -> None:
    """根据一个或多个时间序列统一设置时间轴范围。

    参数
    ----
    axes:
        单个 Axes 或多个 Axes。
    *time_series:
        一个或多个时间数组，自动忽略空数组和 NaN。
    left:
        时间轴左边界，默认 0。
    """
    max_values: list[float] = []
    for series in time_series:
        arr = np.asarray(series, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if len(arr):
            max_values.append(float(arr.max()))

    right = max(max_values) if max_values else None
    set_x_axis_origin(axes, right=right, left=left)
