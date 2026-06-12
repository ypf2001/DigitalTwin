from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle


OUT_DIR = Path(r"D:\Digital Twin\results\diagrams")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PNG = OUT_DIR / "physical_connection_detailed.png"
OUT_SVG = OUT_DIR / "physical_connection_detailed.svg"
OUT_CLEAN_PNG = OUT_DIR / "physical_connection_clean.png"
OUT_CLEAN_SVG = OUT_DIR / "physical_connection_clean.svg"

FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"
font_manager.fontManager.addfont(FONT_PATH)
FONT = font_manager.FontProperties(fname=FONT_PATH)


def add_text(ax, x, y, text, size=9, ha="center", va="center", weight=None):
    ax.text(x, y, text, fontsize=size, ha=ha, va=va, fontproperties=FONT, fontweight=weight)


def main():
    fig, ax = plt.subplots(figsize=(15, 10), dpi=180)
    ax.set_xlim(0, 150)
    ax.set_ylim(-13, 100)
    ax.axis("off")

    lw = 1.25
    thin = 0.9

    def dashed_box(x, y, w, h, label=None, num=None):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=1.2, ls=(0, (8, 5)), ec="black"))
        if label:
            add_text(ax, x + w / 2, y + h + 1.2, label, 11, va="bottom")
        if num:
            add_text(ax, x + w - 3, y + h - 4, str(num), 10)

    def pipe(points, arrow=True):
        xs, ys = zip(*points)
        ax.plot(xs, ys, color="black", lw=lw)
        if arrow and len(points) >= 2:
            p1, p2 = points[-2], points[-1]
            ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="->", mutation_scale=9, lw=0, color="black"))

    def label_num(x, y, n):
        add_text(ax, x, y, str(n), 9)

    def valve(x, y, orientation="h", n=None):
        if orientation == "h":
            ax.add_patch(Polygon([[x - 2, y - 1.4], [x, y], [x - 2, y + 1.4]], fill=False, lw=thin))
            ax.add_patch(Polygon([[x + 2, y - 1.4], [x, y], [x + 2, y + 1.4]], fill=False, lw=thin))
        else:
            ax.add_patch(Polygon([[x - 1.4, y + 2], [x, y], [x + 1.4, y + 2]], fill=False, lw=thin))
            ax.add_patch(Polygon([[x - 1.4, y - 2], [x, y], [x + 1.4, y - 2]], fill=False, lw=thin))
        if n:
            label_num(x - 4, y + 4, n)

    def pump(x, y, n=None, label="泵"):
        ax.add_patch(Circle((x, y), 3.2, fill=False, lw=thin))
        ax.add_patch(Polygon([[x - 1.2, y - 1.6], [x + 1.8, y], [x - 1.2, y + 1.6]], fill=False, lw=thin))
        add_text(ax, x, y - 5.1, label, 8)
        if n:
            label_num(x - 5.4, y + 4.6, n)

    def sensor_box(x, y, txt, n=None):
        ax.add_patch(Rectangle((x - 4.3, y - 2.0), 8.6, 4.0, fill=False, lw=thin))
        add_text(ax, x, y, txt, 8)
        if n:
            label_num(x - 6.0, y + 3.7, n)

    def tank(x, y, label, n=None):
        ax.add_patch(Rectangle((x - 4, y - 8), 8, 14, fill=False, lw=thin))
        ax.add_patch(Rectangle((x - 2.8, y + 6), 5.6, 1.4, fill=False, lw=thin))
        add_text(ax, x, y - 10.5, label, 8)
        if n:
            label_num(x - 6.3, y + 7.7, n)

    def terminal(x, y, label, n=None):
        ax.add_patch(Rectangle((x - 5, y - 2.8), 10, 5.6, fill=False, lw=thin))
        add_text(ax, x, y, label, 8.2)
        if n:
            label_num(x - 7.4, y + 4.7, n)

    dashed_box(7, 43, 30, 38, "原水与预处理区")
    dashed_box(49, 38, 45, 47, "水肥一体机 / PLC 控制柜")
    dashed_box(101, 28, 35, 56, "肥液 / 酸碱储液区")
    dashed_box(50, 8, 86, 20, "栽培区 / 灌溉管网")

    ax.add_patch(Rectangle((18, 78), 8, 6, fill=False, lw=1.2))
    add_text(ax, 16, 88, "1 灌溉水源\n水箱/自来水", 9)
    pipe([(22, 78), (22, 72)], arrow=True)
    valve(22, 70, "v", 2)
    sensor_box(22, 64.5, "砂石\n过滤", 3)
    sensor_box(22, 58.5, "叠片\n过滤", 4)
    sensor_box(22, 52.5, "流量计", 5)
    valve(22, 47.5, "v", 6)
    pipe([(22, 72), (22, 68), (22, 66.5)], arrow=False)
    pipe([(22, 62.5), (22, 60.5)], arrow=False)
    pipe([(22, 56.5), (22, 54.5)], arrow=False)
    pipe([(22, 50.5), (22, 47.5), (22, 43), (49, 43)], arrow=True)

    ax.add_patch(Rectangle((54, 48), 18, 26, fill=False, lw=1.2))
    add_text(ax, 63, 76, "7 PLC 控制器", 9)
    terminal(63, 68, "CPU\nS7-1200/1500")
    terminal(63, 61, "AI 模块\nEC/pH/压力")
    terminal(63, 54, "AO/DO 模块\n泵阀控制")
    ax.add_patch(Rectangle((76, 50), 14, 22, fill=False, lw=1.0))
    add_text(ax, 83, 74, "8 电控输出", 9)
    terminal(83, 67, "继电器/接触器")
    terminal(83, 60, "变频器/驱动器")
    terminal(83, 53, "24V DC 电源")

    ax.plot([49, 94], [43, 43], color="black", lw=lw)
    add_text(ax, 73, 45.5, "混合主管", 9)
    sensor_box(58, 39, "压力", 9)
    sensor_box(69, 39, "EC", 10)
    sensor_box(80, 39, "pH", 11)
    pipe([(58, 43), (58, 41)], arrow=False)
    pipe([(69, 43), (69, 41)], arrow=False)
    pipe([(80, 43), (80, 41)], arrow=False)
    ax.plot([58, 54], [39, 61], color="black", lw=0.8)
    ax.plot([69, 58], [39, 61], color="black", lw=0.8)
    ax.plot([80, 62], [39, 61], color="black", lw=0.8)

    ax.add_patch(Rectangle((50, 87), 24, 8, fill=False, lw=thin))
    add_text(ax, 62, 91, "12 上位机 Python\nTIA Portal / Snap7", 9)
    pipe([(62, 87), (62, 74)], arrow=True)
    add_text(ax, 66, 81, "以太网 TCP/IP", 8, ha="left")

    tank_labels = [("A肥母液罐", 13), ("B肥母液罐", 14), ("酸液罐", 15), ("碱液罐", 16), ("清水/补水罐", 17)]
    y_positions = [76, 66, 56, 46, 36]
    for (lab, n), y in zip(tank_labels, y_positions):
        tank(119, y, lab, n)
        pump(108, y - 1, n + 5, "计量泵")
        valve(102, y - 1, "h")
        pipe([(115, y - 1), (111.2, y - 1)], arrow=True)
        pipe([(104, y - 1), (94, y - 1), (94, 43)], arrow=False)
        ax.plot([108, 83], [y - 4, 60], color="black", lw=0.65)

    add_text(ax, 102, 83, "18 手动阀组", 8)
    add_text(ax, 108, 83, "19-23 计量泵组", 8)

    pipe([(94, 43), (94, 31), (50, 31), (50, 18)], arrow=True)
    valve(50, 31, "v", 24)
    sensor_box(48, 24, "持压阀", 25)
    pipe([(50, 18), (58, 18)], arrow=True)

    for i, x in enumerate([62, 78, 94, 110, 126], start=1):
        pipe([(58, 18), (x, 18), (x, 24)], arrow=True)
        valve(x, 24, "v")
        ax.plot([x - 6, x + 6], [25.5, 25.5], color="black", lw=thin)
        for dx in [-4, 0, 4]:
            ax.plot([x + dx, x + dx], [25.5, 21.5], color="black", lw=thin)
            ax.plot([x + dx - 1.5, x + dx + 1.5], [21.5, 21.5], color="black", lw=thin)
        add_text(ax, x, 12.5, f"灌溉支路{i}", 8)
    add_text(ax, 94, 9.5, "26 灌溉管网 / 滴灌带 / 种植槽", 9)

    pipe([(126, 18), (142, 18), (142, 37), (86, 37), (86, 41)], arrow=True)
    add_text(ax, 130, 35, "回液/取样支路", 8)
    valve(142, 27, "v", 27)

    ax.plot([83, 53, 63], [53, 31, 31], color="black", lw=0.7, ls="--")
    add_text(ax, 70, 30, "虚线：电源/控制信号", 8)
    add_text(ax, 86, 45, "实线：水肥管路", 8)

    add_text(ax, 75, -2.2, "图 3.1  PLC 控制水肥一体化实物连接与系统工作流程示意图", 16, weight="bold")
    legend = (
        "1.灌溉水源  2.进水电动阀  3.砂石过滤器  4.叠片过滤器  5.流量计  6.手动/止回阀  "
        "7.PLC控制器  8.继电器/变频器/电源  9.压力传感器  10.EC传感器  11.pH传感器  12.上位机\n"
        "13.A肥母液罐  14.B肥母液罐  15.酸液罐  16.碱液罐  17.清水罐  18.手动阀组  "
        "19-23.计量泵组  24.主管电动阀  25.持压阀  26.灌溉管网  27.回液/取样阀"
    )
    add_text(ax, 75, -10.5, legend, 10.5, va="bottom")

    fig.savefig(OUT_PNG, bbox_inches="tight", pad_inches=0.3)
    fig.savefig(OUT_SVG, bbox_inches="tight", pad_inches=0.3)
    print(OUT_PNG)
    print(OUT_SVG)


if __name__ == "__main__":
    main()

    fig, ax = plt.subplots(figsize=(16, 9), dpi=180)
    ax.set_xlim(0, 160)
    ax.set_ylim(-14, 90)
    ax.axis("off")

    lw = 1.35
    thin = 1.0

    def dbox(x, y, w, h, title):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=1.2, ls=(0, (8, 5)), ec="black"))
        add_text(ax, x + w / 2, y + h + 3.2, title, 12)

    def arrow(points):
        xs, ys = zip(*points)
        ax.plot(xs, ys, color="black", lw=lw)
        if len(points) >= 2:
            ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="->", mutation_scale=10, lw=0, color="black"))

    def simple_valve(x, y, vertical=False, n=None):
        if vertical:
            pts1 = [[x - 1.8, y + 2.4], [x, y], [x + 1.8, y + 2.4]]
            pts2 = [[x - 1.8, y - 2.4], [x, y], [x + 1.8, y - 2.4]]
        else:
            pts1 = [[x - 2.4, y - 1.8], [x, y], [x - 2.4, y + 1.8]]
            pts2 = [[x + 2.4, y - 1.8], [x, y], [x + 2.4, y + 1.8]]
        ax.add_patch(Polygon(pts1, fill=False, lw=thin))
        ax.add_patch(Polygon(pts2, fill=False, lw=thin))
        if n:
            add_text(ax, x - 4.8, y + 4.5, str(n), 9)

    def box(x, y, w, h, label, n=None):
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=thin))
        add_text(ax, x + w / 2, y + h / 2, label, 9)
        if n:
            add_text(ax, x - 2.5, y + h + 2.0, str(n), 9)

    def pump2(x, y, n):
        ax.add_patch(Circle((x, y), 4.2, fill=False, lw=thin))
        ax.add_patch(Polygon([[x - 1.3, y - 2.0], [x + 2.2, y], [x - 1.3, y + 2.0]], fill=False, lw=thin))
        add_text(ax, x, y - 6.5, "计量泵", 8)
        add_text(ax, x - 6, y + 5.4, str(n), 9)

    dbox(8, 30, 33, 40, "原水与预处理区")
    dbox(55, 30, 42, 40, "水肥一体机 / PLC 控制柜")
    dbox(112, 25, 36, 48, "肥液 / 酸碱储液区")
    dbox(48, 1, 100, 18, "栽培区 / 灌溉管网")

    box(18, 72, 12, 7, "灌溉水源\n水箱/自来水", 1)
    simple_valve(24, 62, True, 2)
    box(18, 52, 12, 6, "过滤器", 3)
    box(18, 43, 12, 6, "流量计", 4)
    simple_valve(24, 34, True, 5)
    arrow([(24, 72), (24, 64.5)])
    arrow([(24, 59.5), (24, 58)])
    arrow([(24, 52), (24, 49)])
    arrow([(24, 43), (24, 36.5)])
    arrow([(24, 31.5), (55, 31.5), (55, 41)])

    box(61, 51, 14, 12, "PLC\nCPU", 6)
    box(78, 51, 14, 12, "I/O 模块\nAI AO DO", 7)
    box(61, 36, 31, 9, "继电器 / 变频器 / 24V电源", 8)
    box(66, 76, 22, 8, "上位机 Python\nTIA Portal / Snap7", 9)
    arrow([(77, 76), (77, 63)])
    add_text(ax, 84, 69, "以太网 TCP/IP", 8, ha="left")

    ax.plot([55, 97], [31.5, 31.5], color="black", lw=lw)
    add_text(ax, 76, 34, "混合主管", 9)
    for x, label, n in [(61, "压力", 10), (73, "EC", 11), (85, "pH", 12)]:
        box(x - 4, 24, 8, 5, label, n)
        ax.plot([x, x], [31.5, 29], color="black", lw=thin)
        ax.plot([x, 78], [24, 51], color="black", lw=0.7)

    fluids = [("A肥", 13), ("B肥", 14), ("酸液", 15), ("碱液", 16)]
    ys = [65, 54, 43, 32]
    for (name, n), y in zip(fluids, ys):
        box(136, y - 4, 8, 8, name + "罐", n)
        pump2(123, y, n + 4)
        simple_valve(113, y, False)
        arrow([(136, y), (127.5, y)])
        ax.plot([119, 104, 104, 97], [y, y, 31.5, 31.5], color="black", lw=lw)
        ax.plot([123, 76], [y - 4, 40], color="black", lw=0.65)
    add_text(ax, 114, 72, "17 手动阀组", 9)
    add_text(ax, 123, 72, "18-21 计量泵组", 9)

    arrow([(97, 31.5), (97, 19), (54, 19), (54, 10)])
    simple_valve(54, 19, True, 22)
    box(46, 8, 10, 5, "持压阀", 23)
    ax.plot([54, 140], [10, 10], color="black", lw=lw)

    branch_xs = [65, 85, 105, 125]
    for i, x in enumerate(branch_xs, 1):
        ax.plot([x, x], [10, 17], color="black", lw=thin)
        simple_valve(x, 17, True)
        ax.plot([x - 7, x + 7], [18.5, 18.5], color="black", lw=thin)
        add_text(ax, x, 4.2, f"灌溉支路{i}", 8)
    add_text(ax, 100, 1.8, "24 灌溉管网 / 滴灌带 / 种植槽", 9)

    ax.plot([140, 153, 153, 92], [10, 10, 31.5, 31.5], color="black", lw=lw)
    simple_valve(153, 22, True, 25)
    add_text(ax, 144, 28, "回液 / 取样支路", 8)

    ax.plot([77, 40, 54], [40, 19, 19], color="black", lw=0.8, ls="--")
    add_text(ax, 72, 16.5, "虚线：电源/控制信号", 8)
    add_text(ax, 86, 27, "实线：水肥管路", 8)

    add_text(ax, 80, -4, "图 3.1  PLC 控制水肥一体化实物连接与系统工作流程示意图", 16, weight="bold")
    legend = (
        "1.灌溉水源  2.进水电动阀  3.过滤器  4.流量计  5.手动/止回阀  6.PLC CPU  7.I/O模块  8.电控输出  9.上位机\n"
        "10.压力传感器  11.EC传感器  12.pH传感器  13.A肥罐  14.B肥罐  15.酸液罐  16.碱液罐  17.手动阀组  "
        "18-21.计量泵组  22.主管电动阀  23.持压阀  24.灌溉管网  25.回液/取样阀"
    )
    add_text(ax, 80, -11.2, legend, 10, va="bottom")

    fig.savefig(OUT_CLEAN_PNG, bbox_inches="tight", pad_inches=0.35)
    fig.savefig(OUT_CLEAN_SVG, bbox_inches="tight", pad_inches=0.35)
    print(OUT_CLEAN_PNG)
    print(OUT_CLEAN_SVG)
