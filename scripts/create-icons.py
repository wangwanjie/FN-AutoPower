#!/usr/bin/env python3
"""生成 AutoPower 图标：蓝色渐变圆角方块 + 电源符号 + 时钟指针。

图标作为资源提交到仓库，只有改设计时才需要重新运行：

    python3 scripts/create-icons.py

依赖 Pillow（pip install pillow）。
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 4  # 超采样倍数，缩小时得到平滑边缘
BASE = 256
TOP = (66, 160, 255)
BOTTOM = (22, 100, 228)
WHITE = (255, 255, 255, 255)


def render_master() -> Image.Image:
    size = BASE * SCALE
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        t = y / (size - 1)
        color = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)
        for x in range(size):
            pixels[x, y] = color

    mask = Image.new("L", (size, size), 0)
    margin = 12 * SCALE
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, size - margin, size - margin), radius=56 * SCALE, fill=255
    )
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(icon)
    cx = cy = size / 2 + 6 * SCALE
    radius = 74 * SCALE
    stroke = 20 * SCALE

    # 电源符号外圈：顶部留缺口
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.arc(box, start=-60, end=240, fill=WHITE, width=stroke)
    for angle in (-60, 240):
        rad = math.radians(angle)
        ex = cx + (radius - stroke / 2) * math.cos(rad)
        ey = cy + (radius - stroke / 2) * math.sin(rad)
        draw.ellipse((ex - stroke / 2, ey - stroke / 2, ex + stroke / 2, ey + stroke / 2), fill=WHITE)

    # 电源竖杠，穿过缺口
    top_y = cy - radius - 18 * SCALE
    bar_bottom = cy - 30 * SCALE
    draw.rounded_rectangle(
        (cx - stroke / 2, top_y, cx + stroke / 2, bar_bottom), radius=stroke / 2, fill=WHITE
    )

    # 时钟指针（指向 3 点，表示定时）
    hand = 14 * SCALE
    draw.rounded_rectangle((cx - hand / 2, cy - hand / 2, cx + 44 * SCALE, cy + hand / 2), radius=hand / 2, fill=WHITE)
    dot = 13 * SCALE
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=WHITE)
    return icon


def main():
    root = Path(__file__).resolve().parents[1]
    master = render_master()
    targets = {
        root / "fpk" / "ICON.PNG": 64,
        root / "fpk" / "ICON_256.PNG": 256,
        root / "fpk" / "app" / "ui" / "images" / "icon_64.png": 64,
        root / "fpk" / "app" / "ui" / "images" / "icon_256.png": 256,
    }
    for path, size in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        master.resize((size, size), Image.LANCZOS).save(path, optimize=True)
        print(f"wrote {path.relative_to(root)} ({size}x{size})")


if __name__ == "__main__":
    main()
