"""母液混合可控域实验。

遍历肥料母液流量 q_f 和酸液流量 q_a，计算混合罐出口 EC、pH，
并生成热力图与综合区域分类图。该实验用于检查当前执行机构范围内，
是否存在能够同时接近配液设定 EC 和配液设定 pH 的安全控制动作。

输出目录：
- 数据：results/stock_solution_controllability/<run_id>/
- 图片：experiments/images/stock_solution_controllability/<run_id>/
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_config
from mixing_tank import MixingTank
from plot_utils import set_x_axis_origin
from setpoint_controller import SetpointToFlowController

logger = logging.getLogger(__name__)


STAGE_LABELS = {
    "emergence": "出苗期",
    "vegetative": "营养生长期",
    "tuber_init": "块茎形成期",
    "bulking": "块茎膨大期",
    "starch_accumulation": "淀粉积累期",
    "maturation": "成熟期",
}


def _json_default(value: Any):
    """将 NumPy 类型转换为 JSON 可序列化类型。"""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _configure_chinese_font() -> None:
    """配置常见中文字体，避免图片中的中文标签显示为方框。"""
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "SimHei",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def _evaluate_grid(
    q_f_values: np.ndarray,
    q_a_values: np.ndarray,
    q_w: float,
) -> tuple[np.ndarray, np.ndarray]:
    """计算每个 q_f、q_a 组合对应的混合罐出口 EC 和 pH。"""
    ec_grid = np.zeros((len(q_a_values), len(q_f_values)), dtype=float)
    ph_grid = np.zeros_like(ec_grid)

    for row, q_a in enumerate(q_a_values):
        for col, q_f in enumerate(q_f_values):
            # MixingTank 当前采用瞬时混合模型，每个网格点可独立计算。
            tank = MixingTank()
            ec_grid[row, col], ph_grid[row, col] = tank.step(
                q_f=float(q_f),
                q_a=float(q_a),
                q_w=q_w,
            )

    return ec_grid, ph_grid


def _build_q_a_values(q_a_min: float, q_a_max: float, points: int) -> np.ndarray:
    """生成酸液扫描点，并在接近 0 L/min 的关键区域加密。

    当前酸液 pH 很低，配液设定 pH 对 q_a 的变化极其敏感。若只在 0~4 L/min
    之间做等间距扫描，会直接跳过实际存在但很窄的目标控制区域。
    """
    if q_a_max <= q_a_min:
        return np.array([q_a_min], dtype=float)

    fine_end = min(q_a_max, max(q_a_min + 0.1, q_a_max * 0.025))
    fine_points = max(points * 4, 401)
    coarse_points = max(points, 161)
    fine = np.linspace(q_a_min, fine_end, fine_points)
    coarse = np.linspace(fine_end, q_a_max, coarse_points)
    return np.unique(np.concatenate([fine, coarse]))


def _write_grid_csv(
    path: Path,
    q_f_values: np.ndarray,
    q_a_values: np.ndarray,
    ec_grid: np.ndarray,
    ph_grid: np.ndarray,
    target_ec: float,
    target_ph: float,
    ec_tolerance: float,
    ph_tolerance: float,
    ec_risk_threshold: float,
    ph_burn_threshold: float,
) -> None:
    """导出每个流量组合及其分类结果，便于后续筛选和画图。"""
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "q_f_L_min",
                "q_a_L_min",
                "ec_out_dS_m",
                "ph_out",
                "ec_target_error",
                "ph_target_error",
                "target_match",
                "ec_risk",
                "ph_burn",
                "safe",
            ]
        )
        for row, q_a in enumerate(q_a_values):
            for col, q_f in enumerate(q_f_values):
                ec_out = float(ec_grid[row, col])
                ph_out = float(ph_grid[row, col])
                ec_risk = ec_out > ec_risk_threshold
                ph_burn = ph_out < ph_burn_threshold
                target_match = (
                    abs(ec_out - target_ec) <= ec_tolerance
                    and abs(ph_out - target_ph) <= ph_tolerance
                    and not ec_risk
                    and not ph_burn
                )
                writer.writerow(
                    [
                        float(q_f),
                        float(q_a),
                        ec_out,
                        ph_out,
                        ec_out - target_ec,
                        ph_out - target_ph,
                        target_match,
                        ec_risk,
                        ph_burn,
                        not ec_risk and not ph_burn,
                    ]
                )


def _plot_heatmaps(
    image_path: Path,
    q_f_values: np.ndarray,
    q_a_values: np.ndarray,
    ec_grid: np.ndarray,
    ph_grid: np.ndarray,
    stage_label: str,
    target_ec: float,
    target_ph: float,
    ec_tolerance: float,
    ph_tolerance: float,
    ec_risk_threshold: float,
    ph_burn_threshold: float,
    fixed_q_f: float,
    fixed_q_a: float,
) -> None:
    """绘制 EC、pH 热力图和综合安全可控域分类图。"""
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    _configure_chinese_font()

    q_f_grid, q_a_grid = np.meshgrid(q_f_values, q_a_values)
    ec_risk = ec_grid > ec_risk_threshold
    ph_burn = ph_grid < ph_burn_threshold
    target_match = (
        (np.abs(ec_grid - target_ec) <= ec_tolerance)
        & (np.abs(ph_grid - target_ph) <= ph_tolerance)
        & ~ec_risk
        & ~ph_burn
    )

    # 分类编码：0 安全未命中，1 配液设定可控域，2 EC 风险，3 pH 酸害，4 双重风险。
    region = np.zeros_like(ec_grid, dtype=int)
    region[target_match] = 1
    region[ec_risk] = 2
    region[ph_burn] = 3
    region[ec_risk & ph_burn] = 4

    fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
    axes = axes.ravel()

    ec_image = axes[0].pcolormesh(
        q_f_grid,
        q_a_grid,
        ec_grid,
        shading="auto",
        cmap="YlGnBu",
    )
    axes[0].contour(
        q_f_grid,
        q_a_grid,
        ec_grid,
        levels=[target_ec],
        colors=["#d62728"],
        linewidths=1.8,
    )
    axes[0].contour(
        q_f_grid,
        q_a_grid,
        ec_grid,
        levels=[ec_risk_threshold],
        colors=["#7f0000"],
        linestyles="--",
        linewidths=1.4,
    )
    axes[0].set_title(f"{stage_label}出口 EC")
    fig.colorbar(ec_image, ax=axes[0], label="EC（dS/m）")

    ph_image = axes[1].pcolormesh(
        q_f_grid,
        q_a_grid,
        ph_grid,
        shading="auto",
        cmap="viridis",
    )
    axes[1].contour(
        q_f_grid,
        q_a_grid,
        ph_grid,
        levels=[target_ph],
        colors=["#d62728"],
        linewidths=1.8,
    )
    axes[1].contour(
        q_f_grid,
        q_a_grid,
        ph_grid,
        levels=[ph_burn_threshold],
        colors=["#7f0000"],
        linestyles="--",
        linewidths=1.4,
    )
    axes[1].set_title("出口 pH")
    fig.colorbar(ph_image, ax=axes[1], label="pH")

    colors = ["#d9ead3", "#2ca02c", "#f6b26b", "#e06666", "#990000"]
    labels = ["安全但未命中设定", "配液设定可控域", "EC 超阈值", "pH 过低", "双重风险"]
    region_cmap = ListedColormap(colors)
    region_norm = BoundaryNorm(np.arange(-0.5, 5.5, 1.0), region_cmap.N)
    axes[2].pcolormesh(
        q_f_grid,
        q_a_grid,
        region,
        shading="auto",
        cmap=region_cmap,
        norm=region_norm,
    )
    axes[2].set_title("综合安全可控域（完整动作范围）")
    axes[2].legend(
        handles=[Patch(facecolor=color, label=label) for color, label in zip(colors, labels)],
        loc="upper right",
        fontsize=8,
        frameon=True,
    )

    axes[3].pcolormesh(
        q_f_grid,
        q_a_grid,
        region,
        shading="auto",
        cmap=region_cmap,
        norm=region_norm,
    )
    axes[3].set_title("综合安全可控域（低酸液流量放大）")
    axes[3].set_ylim(q_a_values.min(), min(q_a_values.max(), 0.1))
    axes[3].legend(
        handles=[Patch(facecolor=color, label=label) for color, label in zip(colors, labels)],
        loc="upper right",
        fontsize=8,
        frameon=True,
    )

    for ax in axes:
        ax.set_xlabel("肥料母液流量 q_f（L/min）")
        ax.set_ylabel("酸液流量 q_a（L/min）")
        ax.scatter(
            [fixed_q_f],
            [fixed_q_a],
            marker="X",
            s=70,
            c="#111111",
            edgecolors="white",
            linewidths=0.7,
            label="当前固定策略",
            zorder=5,
        )
    for ax in axes[:3]:
        ax.set_ylim(q_a_values.min(), q_a_values.max())
    set_x_axis_origin(axes, right=float(q_f_values.max()), left=float(q_f_values.min()))
    axes[0].legend(loc="upper left", fontsize=8, frameon=True)
    axes[1].legend(loc="upper left", fontsize=8, frameon=True)

    fig.suptitle(
        "母液混合可控域分析\n"
        f"配液设定 EC={target_ec:.2f}±{ec_tolerance:.2f} dS/m，"
        f"配液设定 pH={target_ph:.2f}±{ph_tolerance:.2f}",
        fontsize=13,
    )
    fig.savefig(image_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def run_experiment(args: argparse.Namespace) -> tuple[Path, Path]:
    """运行可控域扫描、导出数据并生成图片。"""
    cfg = load_config()
    env_cfg = cfg.env()
    action_cfg = cfg.action()
    stage_cfg = cfg.crop_stages()
    reward_cfg = cfg.reward()

    if args.stage not in stage_cfg:
        available = ", ".join(stage_cfg.keys())
        raise ValueError(f"未知生育阶段 {args.stage!r}，可选值: {available}")

    target_ec = float(stage_cfg[args.stage]["target_ec"])
    target_ph = float(reward_cfg["pH_target"])
    ec_risk_threshold = float(reward_cfg["ec_burn_threshold"])
    ph_burn_threshold = float(reward_cfg["ph_burn_threshold"])
    q_w = float(env_cfg["q_w"])
    fixed_ec_set, fixed_ph_set = (float(v) for v in action_cfg["legacy_fixed_setpoint"])
    fixed_flow = SetpointToFlowController().to_flow(fixed_ec_set, fixed_ph_set, q_w=q_w)
    fixed_q_f = fixed_flow.q_f
    fixed_q_a = fixed_flow.q_a
    fixed_tank = MixingTank()
    fixed_ec, fixed_ph = fixed_tank.step(fixed_q_f, fixed_q_a, q_w=q_w)

    q_f_values = np.linspace(
        float(action_cfg["q_f_min"]),
        float(action_cfg["q_f_max"]),
        args.points,
    )
    q_a_values = _build_q_a_values(
        float(action_cfg["q_a_min"]),
        float(action_cfg["q_a_max"]),
        args.points,
    )
    ec_grid, ph_grid = _evaluate_grid(q_f_values, q_a_values, q_w=q_w)

    ec_risk = ec_grid > ec_risk_threshold
    ph_burn = ph_grid < ph_burn_threshold
    target_match = (
        (np.abs(ec_grid - target_ec) <= args.ec_tolerance)
        & (np.abs(ph_grid - target_ph) <= args.ph_tolerance)
        & ~ec_risk
        & ~ph_burn
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    result_dir = ROOT / "results" / "stock_solution_controllability" / run_id
    image_dir = ROOT / "experiments" / "images" / "stock_solution_controllability" / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    csv_path = result_dir / "controllability_grid.csv"
    image_path = image_dir / "stock_solution_controllability.png"
    summary_path = result_dir / "summary.json"

    _write_grid_csv(
        csv_path,
        q_f_values,
        q_a_values,
        ec_grid,
        ph_grid,
        target_ec,
        target_ph,
        args.ec_tolerance,
        args.ph_tolerance,
        ec_risk_threshold,
        ph_burn_threshold,
    )
    _plot_heatmaps(
        image_path,
        q_f_values,
        q_a_values,
        ec_grid,
        ph_grid,
        STAGE_LABELS.get(args.stage, args.stage),
        target_ec,
        target_ph,
        args.ec_tolerance,
        args.ph_tolerance,
        ec_risk_threshold,
        ph_burn_threshold,
        fixed_q_f,
        fixed_q_a,
    )

    matching_indices = np.argwhere(target_match)
    matching_actions = sorted(
        [
        {
            "q_f_L_min": float(q_f_values[col]),
            "q_a_L_min": float(q_a_values[row]),
            "ec_out_dS_m": float(ec_grid[row, col]),
            "ph_out": float(ph_grid[row, col]),
            "normalized_target_error": float(
                abs(ec_grid[row, col] - target_ec) / args.ec_tolerance
                + abs(ph_grid[row, col] - target_ph) / args.ph_tolerance
            ),
        }
        for row, col in matching_indices
        ],
        key=lambda item: item["normalized_target_error"],
    )
    summary = {
        "stage": args.stage,
        "stage_label": STAGE_LABELS.get(args.stage, args.stage),
        "q_w_L_min": q_w,
        "q_f_range_L_min": [float(q_f_values.min()), float(q_f_values.max())],
        "q_a_range_L_min": [float(q_a_values.min()), float(q_a_values.max())],
        "q_f_grid_points": len(q_f_values),
        "q_a_grid_points": len(q_a_values),
        "target_ec_dS_m": target_ec,
        "target_ph": target_ph,
        "ec_tolerance_dS_m": args.ec_tolerance,
        "ph_tolerance": args.ph_tolerance,
        "ec_risk_threshold_dS_m": ec_risk_threshold,
        "ph_burn_threshold": ph_burn_threshold,
        "fixed_strategy": {
            "ec_set_dS_m": fixed_ec_set,
            "ph_set": fixed_ph_set,
            "q_f_L_min": fixed_q_f,
            "q_a_L_min": fixed_q_a,
            "ec_out_dS_m": fixed_ec,
            "ph_out": fixed_ph,
            "ec_risk": fixed_ec > ec_risk_threshold,
            "ph_burn": fixed_ph < ph_burn_threshold,
        },
        "target_match_count": int(target_match.sum()),
        "safe_count": int((~ec_risk & ~ph_burn).sum()),
        "ec_risk_count": int(ec_risk.sum()),
        "ph_burn_count": int(ph_burn.sum()),
        "best_matching_actions": matching_actions[:20],
        "note": "EC 超阈值区域是将土壤 EC 烧苗阈值用于出口配液的保守风险标记。",
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )

    logger.info("可控域实验完成: %s", result_dir)
    logger.info("图片保存至: %s", image_path)
    logger.info("配液设定可控域网格点数: %d", int(target_match.sum()))
    return result_dir, image_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成母液混合 EC/pH 可控域热力图。")
    parser.add_argument(
        "--stage",
        default="bulking",
        choices=list(STAGE_LABELS.keys()),
        help="用于确定配液设定 EC 的马铃薯生育阶段，默认 bulking。",
    )
    parser.add_argument("--points", type=int, default=161, help="每个流量轴的扫描点数。")
    parser.add_argument("--ec-tolerance", type=float, default=0.05, help="配液设定 EC 容差 dS/m。")
    parser.add_argument("--ph-tolerance", type=float, default=0.10, help="配液设定 pH 容差。")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_experiment(parse_args())
