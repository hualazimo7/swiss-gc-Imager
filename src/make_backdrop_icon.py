#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 SwissBackdrop 的程序图标（现代扁平：蓝底 + 相框风景）。

    python tools/make_backdrop_icon.py
输出 tools/assets/swissbackdrop.ico / swissbackdrop_preview.png
仅构建时需要 Pillow，不参与 EXE 运行时。
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "assets"
S = 4

BLUE = (47, 111, 235, 255)
WHITE = (255, 255, 255, 255)
SKY = (206, 224, 255, 255)
SUN = (255, 205, 96, 255)
FAR = (126, 158, 208, 255)
NEAR = (74, 108, 168, 255)
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
         (128, 128), (256, 256)]


def k(v):
    return v * S


def draw_icon() -> Image.Image:
    im = Image.new("RGBA", (k(256), k(256)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((k(8), k(8), k(248), k(248)), radius=k(54), fill=BLUE)

    # 相框
    d.rounded_rectangle((k(42), k(52), k(214), k(204)), radius=k(18), fill=WHITE)
    d.rounded_rectangle((k(54), k(64), k(202), k(192)), radius=k(10), fill=SKY)

    # 太阳 + 远山 + 近山（裁到取景框内：先画在小画布再贴）
    view = Image.new("RGBA", (k(148), k(128)), (0, 0, 0, 0))
    v = ImageDraw.Draw(view)
    v.ellipse((k(98), k(14), k(134), k(50)), fill=SUN)
    v.polygon([(k(0), k(128)), (k(46), k(56)), (k(96), k(128))], fill=FAR)
    v.polygon([(k(58), k(128)), (k(106), k(72)), (k(148), k(128))], fill=NEAR)
    v.rectangle((k(0), k(112), k(148), k(128)), fill=NEAR)
    im.alpha_composite(view, (k(54), k(64)))

    # 相框底边（遮住山的锯齿，做一点厚度感）
    d.rounded_rectangle((k(42), k(192), k(214), k(204)), radius=k(8), fill=WHITE)
    return im


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw_icon()
    ico = OUT / "swissbackdrop.ico"
    big.resize((256, 256), Image.Resampling.LANCZOS).save(
        ico, format="ICO", sizes=SIZES)
    preview = OUT / "swissbackdrop_preview.png"
    big.resize((256, 256), Image.Resampling.LANCZOS).save(preview)
    print("ICO :", ico, ico.stat().st_size, "bytes")
    print("PNG :", preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
