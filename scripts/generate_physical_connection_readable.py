from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PNG = OUT_DIR / "figure_3_1_plc_fertigation_workflow.png"
OUT_SVG = OUT_DIR / "figure_3_1_plc_fertigation_workflow.svg"


def _load_font() -> font_manager.FontProperties:
    for font_path in (
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    ):
        if font_path.exists():
            font_manager.fontManager.addfont(str(font_path))
            return font_manager.FontProperties(fname=str(font_path))
    return font_manager.FontProperties()


FONT = _load_font()


def main() -> None:
    fig, ax = plt.subplots(figsize=(16.5, 9.2), dpi=240)
    ax.set_xlim(0, 170)
    ax.set_ylim(-14, 108)
    ax.axis("off")

    lw = 1.45
    thin = 1.0

    def text(x, y, s, size=9.0, ha="center", va="center", weight=None):
        ax.text(x, y, s, fontsize=size, fontproperties=FONT, ha=ha, va=va, fontweight=weight)

    def group(x, y, w, h, label):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=1.05, ls=(0, (7, 4))))
        text(x + w / 2, y + h + 2.0, label, 11.2, weight="bold")

    def box(x, y, w, h, label, n=None, size=8.6):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=thin))
        text(x + w / 2, y + h / 2, label, size)
        if n:
            text(x - 2.0, y + h + 1.6, n, 8.0)

    def arrow(points, dashed=False):
        xs, ys = zip(*points)
        ax.plot(xs, ys, color="black", lw=0.85 if dashed else lw, ls="--" if dashed else "-")
        if len(points) >= 2:
            ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="->", mutation_scale=10, lw=0, color="black"))

    def valve(x, y, n=None, vertical=False):
        if vertical:
            p1 = [[x - 1.4, y + 2.0], [x, y], [x + 1.4, y + 2.0]]
            p2 = [[x - 1.4, y - 2.0], [x, y], [x + 1.4, y - 2.0]]
        else:
            p1 = [[x - 2.0, y - 1.4], [x, y], [x - 2.0, y + 1.4]]
            p2 = [[x + 2.0, y - 1.4], [x, y], [x + 2.0, y + 1.4]]
        ax.add_patch(Polygon(p1, fill=False, lw=thin))
        ax.add_patch(Polygon(p2, fill=False, lw=thin))
        if n:
            text(x - 4.0, y + 3.7, n, 8.0)

    # Top control structure.
    group(10, 92, 150, 11, "上位机监控与仿真层")
    box(21, 95, 34, 5.5, "Python / 数字孪生 / 配方管理", "1")
    box(69, 95, 28, 5.5, "TIA Portal", "2")
    box(116, 95, 28, 5.5, "Snap7", "3")

    group(10, 76, 150, 11, "PLC 控制柜")
    box(21, 79, 24, 5.5, "PLC CPU", "4")
    box(55, 79, 25, 5.5, "I/O 模块", "5")
    box(91, 79, 24, 5.5, "继电器", "6")
    box(126, 79, 26, 5.5, "变频器 / 24V 电源", "7")
    arrow([(130, 95), (68, 84.5)], dashed=True)
    text(105, 89.5, "以太网 TCP/IP", 8.8)

    # Field layout groups.
    group(9, 37, 43, 21, "清水与预处理区")
    group(59, 32, 57, 28, "混合主管与检测区")
    group(124, 31, 38, 31, "肥液 / 酸碱液区")
    group(52, 7, 102, 15, "灌溉主管 / 支路")

    # Water line.
    box(14, 48, 12, 6, "清水水源", "8")
    box(32, 48, 12, 6, "过滤器", "9")
    valve(50, 51, "10")
    arrow([(26, 51), (32, 51)])
    arrow([(44, 51), (50, 51), (62, 51)])
    text(48, 45.0, "清水主管", 8.2)

    # Fertilizer branches and pump group.
    tanks = [("A肥液罐", "11", "17"), ("B肥液罐", "12", "18"), ("酸液罐", "13", "19"), ("碱液罐", "14", "20")]
    for (label, tank_no, valve_no), y in zip(tanks, (57, 51, 45, 39)):
        box(146, y - 2.5, 10, 5, label, tank_no, 7.9)
        valve(136, y, valve_no)
        arrow([(146, y), (138, y)])
        ax.plot([134, 126, 126], [y, y, 51], color="black", lw=thin)
    box(120, 63, 24, 6, "计量泵组", "21")
    arrow([(132, 63), (132, 55), (116, 51)])

    # Mixing, sensing, and irrigation.
    box(64, 47, 22, 8, "混合主管", "15")
    arrow([(62, 51), (64, 51)])
    arrow([(86, 51), (96, 51)])
    text(75, 57.2, "清水主管 + 肥液支路 + 酸/碱液支路", 8.0)

    for x, label, n in ((99, "压力", "22"), (109, "EC", "23"), (119, "pH", "24")):
        box(x - 3.5, 43, 7, 5, label, n, 7.8)
        ax.plot([x, x], [51, 48], color="black", lw=thin)
    text(109, 39.0, "压力 / EC / pH 检测", 8.0)

    valve(130, 51, "25")
    text(130, 46.5, "持压阀", 8.0)
    arrow([(122, 51), (130, 51), (143, 51)])
    text(143, 54.5, "灌溉主管", 8.6)

    arrow([(143, 51), (143, 15), (60, 15)])
    for i, x in enumerate((68, 91, 114, 137), start=1):
        ax.plot([x, x], [15, 21], color="black", lw=thin)
        valve(x, 21, vertical=True)
        ax.plot([x - 7, x + 7], [22.3, 22.3], color="black", lw=thin)
        for dx in (-4, 0, 4):
            ax.plot([x + dx, x + dx], [22.3, 19.0], color="black", lw=thin)
        text(x, 10.5, f"灌溉支路{i}", 8.0)
    text(103, 5.6, "26 灌溉主管 / 支路 / 滴灌带", 8.4)

    # Signal path, intentionally simplified to avoid crossing the hydraulic drawing.
    arrow([(68, 79), (68, 67), (132, 67)], dashed=True)
    arrow([(132, 67), (132, 57)], dashed=True)
    arrow([(68, 67), (109, 67), (109, 48)], dashed=True)
    text(76, 69.2, "控制 / 采样信号", 8.0, ha="left")
    text(15, 31.0, "实线：水肥管路流向", 8.2, ha="left")
    text(15, 27.5, "虚线：控制与采样信号", 8.2, ha="left")

    title = "图 3.1 PLC 控制水肥一体化实物连接与系统工作流程示意图"
    text(85, -1.0, title, 14.0, weight="bold")
    legend = (
        "1.Python/数字孪生/配方管理  2.TIA Portal  3.Snap7  4.PLC CPU  5.I/O模块  6.继电器  7.变频器/24V电源  "
        "8.清水水源  9.过滤器  10.清水主管阀\n"
        "11.A肥液罐  12.B肥液罐  13.酸液罐  14.碱液罐  15.混合主管  17.A肥液支路阀  18.B肥液支路阀  "
        "19.酸液支路阀  20.碱液支路阀  21.计量泵组  22.压力传感器  23.EC传感器  24.pH传感器  25.持压阀  26.灌溉主管/支路"
    )
    text(85, -9.3, legend, 8.4, va="bottom")

    fig.savefig(OUT_PNG, bbox_inches="tight", pad_inches=0.32)
    fig.savefig(OUT_SVG, bbox_inches="tight", pad_inches=0.32)
    print(OUT_PNG)
    print(OUT_SVG)


if __name__ == "__main__":
    main()
