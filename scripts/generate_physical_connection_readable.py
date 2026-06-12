from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle


OUT_DIR = Path(r"D:\Digital Twin\results\diagrams")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PNG = OUT_DIR / "physical_connection_readable.png"
OUT_SVG = OUT_DIR / "physical_connection_readable.svg"

FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"
font_manager.fontManager.addfont(FONT_PATH)
FONT = font_manager.FontProperties(fname=FONT_PATH)


def text(ax, x, y, s, size=9, ha="center", va="center", weight=None):
    ax.text(x, y, s, fontsize=size, fontproperties=FONT, ha=ha, va=va, fontweight=weight)


def main():
    fig, ax = plt.subplots(figsize=(16, 9), dpi=180)
    ax.set_xlim(0, 160)
    ax.set_ylim(-12, 92)
    ax.axis("off")

    lw = 1.35
    thin = 1.0

    def group(x, y, w, h, title):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=1.1, ls=(0, (8, 5))))
        text(ax, x + w / 2, y + h + 2.5, title, 12)

    def box(x, y, w, h, label, n=None):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=thin))
        text(ax, x + w / 2, y + h / 2, label, 9)
        if n is not None:
            text(ax, x - 2.5, y + h + 2.0, str(n), 9)

    def line(points, arrow=False, dashed=False):
        xs, ys = zip(*points)
        ax.plot(xs, ys, color="black", lw=lw if not dashed else 0.9, ls="--" if dashed else "-")
        if arrow:
            ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="->", mutation_scale=10, lw=0, color="black"))

    def valve(x, y, vertical=True, n=None):
        if vertical:
            p1 = [[x - 1.7, y + 2.2], [x, y], [x + 1.7, y + 2.2]]
            p2 = [[x - 1.7, y - 2.2], [x, y], [x + 1.7, y - 2.2]]
        else:
            p1 = [[x - 2.2, y - 1.7], [x, y], [x - 2.2, y + 1.7]]
            p2 = [[x + 2.2, y - 1.7], [x, y], [x + 2.2, y + 1.7]]
        ax.add_patch(Polygon(p1, fill=False, lw=thin))
        ax.add_patch(Polygon(p2, fill=False, lw=thin))
        if n is not None:
            text(ax, x - 4.5, y + 4.0, str(n), 9)

    def pump(x, y, n):
        ax.add_patch(Circle((x, y), 3.7, fill=False, lw=thin))
        ax.add_patch(Polygon([[x - 1.1, y - 1.8], [x + 2.0, y], [x - 1.1, y + 1.8]], fill=False, lw=thin))
        text(ax, x, y - 5.8, "计量泵", 8)
        text(ax, x - 5.2, y + 4.8, str(n), 9)

    group(8, 36, 36, 32, "原水与预处理区")
    group(55, 35, 36, 34, "PLC 控制与混合检测区")
    group(100, 26, 52, 48, "多肥液通道 / 酸碱储液区")
    group(28, 6, 120, 18, "栽培区 / 灌溉管网")

    box(18, 62, 14, 7, "灌溉水源", 1)
    valve(25, 55, True, 2)
    box(18, 46, 14, 7, "过滤器", 3)
    box(18, 38, 14, 6, "流量计", 4)
    line([(25, 62), (25, 57)])
    line([(25, 53), (25, 46)])
    line([(25, 38), (25, 32), (60, 32), (60, 42)], arrow=True)

    box(62, 59, 22, 8, "上位机 Python\nTIA Portal / Snap7", 5)
    box(61, 47, 22, 8, "PLC 控制器", 6)
    box(61, 37, 22, 7, "I/O 模块", 7)
    line([(73, 59), (73, 55)], arrow=True)
    text(ax, 84, 57, "以太网 TCP/IP", 8, ha="left")

    ax.plot([60, 92], [32, 32], color="black", lw=lw)
    text(ax, 76, 34.5, "混合主管", 9)
    for x, label, n in [(64, "压力", 8), (74, "EC", 9), (84, "pH", 10)]:
        box(x - 3.8, 26, 7.6, 4.5, label, n)
        line([(x, 32), (x, 30.5)])
        line([(x, 30), (72, 37)], dashed=True)

    channel_data = [
        ("肥液1", 11, 68),
        ("肥液2", 12, 61),
        ("肥液3", 13, 54),
        ("肥液4", 14, 47),
        ("酸液", 15, 40),
        ("碱液", 16, 33),
    ]
    for i, (label, n, y) in enumerate(channel_data):
        box(140, y - 2.5, 8, 5, label, n)
        pump(128, y, 17 + i)
        valve(114, y, False)
        line([(140, y), (132, y)], arrow=True)
        line([(124, y), (100, y), (100, 32), (92, 32)], arrow=True)
        line([(73, 37), (128, y - 3.5)], dashed=True)
    text(ax, 114, 73, "23 手动阀组", 9)

    valve(60, 23, True, 24)
    box(50, 13, 10, 5, "持压阀", 25)
    line([(60, 32), (60, 23), (60, 15), (38, 15), (138, 15)], arrow=True)
    line([(73, 37), (60, 23)], dashed=True)

    for i, x in enumerate([48, 72, 96, 120], 1):
        line([(x, 15), (x, 21)])
        valve(x, 21, True)
        ax.plot([x - 8, x + 8], [22.5, 22.5], color="black", lw=thin)
        text(ax, x, 9.5, f"灌溉支路{i}", 8)
    text(ax, 92, 6.5, "26 灌溉管网 / 滴灌带 / 种植槽", 9)

    line([(138, 15), (154, 15), (154, 32), (84, 32)], arrow=True)
    valve(154, 24, True, 27)
    text(ax, 145, 29, "回液 / 取样支路", 8)

    text(ax, 92, 27, "实线：水肥管路", 8)
    text(ax, 92, 25, "虚线：电源 / 控制 / 采样信号", 8)

    text(ax, 80, -2.7, "图 3.1  PLC 控制水肥一体化实物连接与系统工作流程示意图", 16, weight="bold")
    legend = (
        "1.灌溉水源  2.进水电动阀  3.过滤器  4.流量计  5.上位机  6.PLC控制器  7.I/O模块  8.压力传感器  "
        "9.EC传感器  10.pH传感器  11-14.肥液通道储液罐\n"
        "15.酸液罐  16.碱液罐  17-22.计量泵组  23.手动阀组  24.主管电动阀  25.持压阀  26.灌溉管网  27.回液/取样阀"
    )
    text(ax, 80, -10.0, legend, 10, va="bottom")

    fig.savefig(OUT_PNG, bbox_inches="tight", pad_inches=0.35)
    fig.savefig(OUT_SVG, bbox_inches="tight", pad_inches=0.35)
    print(OUT_PNG)
    print(OUT_SVG)


if __name__ == "__main__":
    main()
