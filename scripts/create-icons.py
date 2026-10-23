#!/usr/bin/env python3
"""生成 AutoPower 图标：蓝色渐变圆角方块 + 电源符号 + 时钟指针。

图标作为资源提交到仓库，只有改设计时才需要重新运行：

    python3 scripts/create-icons.py

依赖 Pillow（pip install pillow）。

设计约定（参照飞牛系统图标与开发者文档的图标规范）：
- 背景是铺满画布的 squircle（超椭圆圆角方块），不留透明边，与系统图标大小一致
- 所有几何尺寸以 64 像素网格为单位定义，256 尺寸按 4 倍放大，
  直线部分（竖杠、指针）的边缘都落在整数像素上，64 像素下也清晰
- 每个尺寸单独绘制：在 SUPERSAMPLE 倍画布上画好后用 BOX（面积平均）缩小，
  对齐网格的边缘不会被插值模糊
- 电源符号按实际外框在画布中居中
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

# 以 64 像素网格为单位的设计尺寸
GRID = 64
SUPERSAMPLE = 8
TOP = (66, 160, 255)
BOTTOM = (22, 100, 228)
WHITE = (255, 255, 255, 255)
# 超椭圆指数：越大越接近方形。4.5 时与飞牛系统图标（影视、下载）的轮廓误差最小
SQUIRCLE_N = 4.5

RING_RADIUS = 17  # 圆环外半径
STROKE = 6  # 圆环与竖杠的线宽
GAP_DEGREES = 30  # 圆环顶部缺口的半角
BAR_OVERSHOOT = 4  # 竖杠超出圆环顶部的长度
BAR_BOTTOM = 7  # 竖杠底端到圆心的距离
HAND_LENGTH = 9  # 时钟指针从圆心向右的长度
HAND_WIDTH = 4
DOT_RADIUS = 3.5


def gradient(size):
    """自上而下的蓝色渐变。"""
    column = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel((0, y), tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,))
    return column.resize((size, size))


def squircle_mask(size):
    """铺满画布的超椭圆蒙版 |x|^n + |y|^n = 1。"""
    half = size / 2
    points = []
    steps = 720
    for i in range(steps):
        angle = 2 * math.pi * i / steps
        c, s = math.cos(angle), math.sin(angle)
        x = half + half * math.copysign(abs(c) ** (2 / SQUIRCLE_N), c)
        y = half + half * math.copysign(abs(s) ** (2 / SQUIRCLE_N), s)
        points.append((x, y))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def glyph_center():
    """电源符号外框居中时的圆心位置（网格单位）。

    外框上沿是竖杠顶端，下沿是圆环底部，左右由圆环决定，
    因此圆心水平居中，垂直方向下移竖杠超出部分的一半。
    """
    top = RING_RADIUS + BAR_OVERSHOOT
    bottom = RING_RADIUS
    return GRID / 2, GRID / 2 + (top - bottom) / 2


def draw_glyph(draw, unit):
    """在 unit（每网格单位的像素数）缩放下画电源符号和时钟指针。"""
    cx, cy = (value * unit for value in glyph_center())
    radius = RING_RADIUS * unit
    stroke = STROKE * unit

    # 圆环：顶部留缺口，两端圆头
    start, end = -90 + GAP_DEGREES, 270 - GAP_DEGREES
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start=start, end=end, fill=WHITE, width=round(stroke))
    middle = radius - stroke / 2
    for angle in (start, end):
        rad = math.radians(angle)
        ex, ey = cx + middle * math.cos(rad), cy + middle * math.sin(rad)
        draw.ellipse((ex - stroke / 2, ey - stroke / 2, ex + stroke / 2, ey + stroke / 2), fill=WHITE)

    # 竖杠：穿过缺口，左右边缘落在整数网格上
    draw.rounded_rectangle(
        (cx - stroke / 2, cy - radius - BAR_OVERSHOOT * unit, cx + stroke / 2, cy - BAR_BOTTOM * unit),
        radius=stroke / 2,
        fill=WHITE,
    )

    # 时钟指针（指向 3 点，表示定时）与中心圆点
    hand = HAND_WIDTH * unit
    draw.rounded_rectangle(
        (cx - hand / 2, cy - hand / 2, cx + HAND_LENGTH * unit, cy + hand / 2), radius=hand / 2, fill=WHITE
    )
    dot = DOT_RADIUS * unit
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=WHITE)


def render(size):
    """单独绘制一个尺寸：超采样画布上作图，再按面积平均缩小。"""
    canvas = size * SUPERSAMPLE
    icon = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    icon.paste(gradient(canvas), (0, 0), squircle_mask(canvas))
    draw_glyph(ImageDraw.Draw(icon), canvas / GRID)
    return icon.resize((size, size), Image.BOX)


def main():
    root = Path(__file__).resolve().parents[1]
    targets = {
        root / "fpk" / "ICON.PNG": 64,
        root / "fpk" / "ICON_256.PNG": 256,
        root / "fpk" / "app" / "ui" / "images" / "icon_64.png": 64,
        root / "fpk" / "app" / "ui" / "images" / "icon_256.png": 256,
    }
    rendered = {}
    for path, size in targets.items():
        if size not in rendered:
            rendered[size] = render(size)
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered[size].save(path, optimize=True)
        print(f"wrote {path.relative_to(root)} ({size}x{size})")


if __name__ == "__main__":
    main()
