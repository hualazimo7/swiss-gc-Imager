#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 的 GameCube TPL 编解码器 —— 专门给 Swiss 自定义背景图用。

Swiss 开机时从 `<启动设备>:/swiss/backdrop.tpl` 读一张（或多张）GX 纹理当主界面
背景。以前生成这个文件必须调 devkitPro 的 gxtexconv.exe，本模块把那条链路整个
换成 Pillow，于是打包出来的 EXE 完全自包含、中文路径也不再崩。

格式规则是拿 gxtexconv 的产物逐字节反推 + 实机验证过的：

* TPL 头   : 0x0020AF30 / 贴图数 / 偏移表位置(0x0C)
* 偏移表   : 每贴图 8 字节 (纹理头偏移, 调色板头偏移)
* 纹理头   : 36 字节，高/宽/格式/数据偏移/… ；调色板头 12 字节
* 各段一律 32 字节对齐，顺序为 表 → 所有纹理头 → 所有调色板头 → 所有纹理数据 → 所有调色板数据
* RGB5A3 (GX_TF_RGB5A3=5) : 4x4 分块，每像素 2 字节大端，不透明时 0x8000|RGB555
* RGB565  (GX_TF_RGB565=4) : 4x4 分块，每像素 2 字节大端
* CI8     (GX_TF_CI8=9)   : 8x4 分块，每像素 1 字节索引；TLUT 必须 fmt=2 (RGB5A3)。
  palfmt=0 (IA8) 会命中 Swiss 里内置 CI4 背景专用的 TEV 分支，彩色图被渲成亮黄，
  这是实机踩过的坑，绝对不能用。

分块顺序都是「按块行 → 块列 → 块内逐行」，也就是 GX 的 native tiled 布局。

    from tplcodec import prepare_image, encode_tpl, decode_tpl
    im = prepare_image("D:/图片/背景.png", 640, 480, "cover")
    open("backdrop.tpl", "wb").write(encode_tpl([im], "rgb5a3"))
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter

__all__ = [
    "FORMATS", "Adjust", "TPL_MAGIC", "prepare_image", "encode_tpl",
    "decode_tpl", "tpl_info", "estimate_size", "format_label",
]

TPL_MAGIC = 0x0020AF30
GX_TF_RGB565 = 4
GX_TF_RGB5A3 = 5
GX_TF_CI8 = 9
GX_TL_RGB5A3 = 2          # palfmt=2 —— 千万不要改成 0

FORMATS = {
    # key: (GX format id, tile 宽, tile 高, 每像素字节, 说明)
    "rgb5a3": (GX_TF_RGB5A3, 4, 4, 2, "RGB5A3 · 画质最好，640×480 约 600 KB（推荐）"),
    "rgb565": (GX_TF_RGB565, 4, 4, 2, "RGB565 · 无透明通道，与 RGB5A3 同体积"),
    "ci8":    (GX_TF_CI8,   8, 4, 1, "CI8 · 256 色，约 300 KB，省一半内存"),
}


def format_label(key: str) -> str:
    return FORMATS[key][4]


def _align32(n: int) -> int:
    return (n + 31) & ~31


def estimate_size(count: int, width: int, height: int, fmt: str) -> int:
    """粗略估算 TPL 字节数（用于界面提示，不含零头）。"""
    _, tw, th, bpp, _ = FORMATS[fmt]
    px = count * width * height
    pal = count * 512 if fmt == "ci8" else 0
    return 12 + count * 8 + count * 36 + (count * 12 if fmt == "ci8" else 0) + px * bpp + pal + 128


@dataclass
class Adjust:
    """图像调节；全部保持默认值时不做任何 Pillow 处理，保证与 gxtexconv 产物字节一致。"""
    brightness: float = 1.0     # 0.30 ~ 1.60
    contrast: float = 1.0       # 0.30 ~ 1.80
    saturation: float = 1.0     # 0.00 ~ 1.60
    blur: float = 0.0           # 高斯半径 px，0 = 关闭
    vignette: float = 0.0       # 0 ~ 1，四周压暗
    offset_x: float = 0.5       # cover 裁切窗口水平位置 0=左 1=右
    offset_y: float = 0.5       # cover 裁切窗口垂直位置 0=上 1=下

    @property
    def neutral(self) -> bool:
        return (self.brightness == 1.0 and self.contrast == 1.0
                and self.saturation == 1.0 and self.blur == 0.0
                and self.vignette == 0.0)


def fit_image(im: Image.Image, width: int, height: int, mode: str,
              offset_x: float = 0.5, offset_y: float = 0.5) -> Image.Image:
    """与 tools/make_backdrop.py 完全一致的缩放/裁切算法，额外支持裁切窗口位置。"""
    im = im.convert("RGB")
    if mode == "stretch":
        return im.resize((width, height), Image.LANCZOS)
    src_ratio = im.width / im.height
    dst_ratio = width / height
    if mode == "contain":
        scale = min(width / im.width, height / im.height)
        im = im.resize((max(1, round(im.width * scale)),
                        max(1, round(im.height * scale))), Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(im, ((width - im.width) // 2, (height - im.height) // 2))
        return canvas
    # cover
    if src_ratio > dst_ratio:
        new_w = round(height * src_ratio)
        im = im.resize((new_w, height), Image.LANCZOS)
        # 用截断而不是 round：offset=0.5 时要和 make_backdrop.py 的
        # (new_w - width)//2 完全一致（差值为奇数时两者会差 1 像素）。
        left = int((new_w - width) * min(1.0, max(0.0, offset_x)))
        return im.crop((left, 0, left + width, height))
    new_h = round(width / src_ratio)
    im = im.resize((width, new_h), Image.LANCZOS)
    top = int((new_h - height) * min(1.0, max(0.0, offset_y)))
    return im.crop((0, top, width, top + height))


def _vignette(im: Image.Image, strength: float) -> Image.Image:
    """径向压暗，边缘最多降到 (1-strength)。用较低分辨率的 L 图放大，速度更快。"""
    w, h = im.size
    small = Image.new("L", (64, 48), 0)
    px = small.load()
    for y in range(48):
        for x in range(64):
            dx = (x - 31.5) / 31.5
            dy = (y - 23.5) / 23.5
            d = min(1.0, (dx * dx + dy * dy) ** 0.5 / 1.35)
            px[x, y] = int(255 * (1.0 - strength * d * d))
    mask = small.resize((w, h), Image.BICUBIC)
    return Image.composite(im, Image.new("RGB", im.size, (0, 0, 0)), mask)


def apply_adjust(im: Image.Image, a: Adjust) -> Image.Image:
    if a.neutral:
        return im
    if a.brightness != 1.0:
        im = ImageEnhance.Brightness(im).enhance(a.brightness)
    if a.contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(a.contrast)
    if a.saturation != 1.0:
        im = ImageEnhance.Color(im).enhance(a.saturation)
    if a.blur > 0:
        im = im.filter(ImageFilter.GaussianBlur(a.blur))
    if a.vignette > 0:
        im = _vignette(im, a.vignette)
    return im


def prepare_image(source, width: int = 640, height: int = 480,
                  fit: str = "cover", adjust: Adjust | None = None) -> Image.Image:
    """从路径 / 文件对象 / PIL Image 得到一张可直接编码的 640×480 RGB 图。"""
    a = adjust or Adjust()
    if isinstance(source, Image.Image):
        im = source
    else:
        im = Image.open(source)
        im.load()
    im = fit_image(im, width, height, fit, a.offset_x, a.offset_y)
    return apply_adjust(im, a)


# --------------------------------------------------------------------------- 编码
def _rgb_pixels(im: Image.Image) -> bytes:
    return im.tobytes("raw", "RGB")


def _encode_rgb(im: Image.Image, code: int, tw: int, th: int) -> bytes:
    """4×4 分块，把 RGB 打包成 RGB5A3 / RGB565 大端 16 位。"""
    w, h = im.size
    src = _rgb_pixels(im)
    out = bytearray(w * h * 2)
    for by in range(0, h, th):
        for bx in range(0, w, tw):
            base = (by // th * (w // tw) + bx // tw) * (tw * th)
            for y in range(th):
                row = ((by + y) * w + bx) * 3
                o = (base + y * tw) * 2
                for x in range(tw):
                    p = row + x * 3
                    r, g, b = src[p], src[p + 1], src[p + 2]
                    if code == GX_TF_RGB5A3:
                        v = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
                    else:
                        v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    out[o] = v >> 8
                    out[o + 1] = v & 0xFF
                    o += 2
    return bytes(out)


def _encode_ci8(im: Image.Image, tw: int, th: int):
    """返回 (索引数据, 256×RGB5A3 调色板数据)。"""
    w, h = im.size
    # 已经是调色板图（例如用户直接打开的 P-mode PNG）就别再量化一次，
    # 否则索引会整体重排；RGB 图才走 ADAPTIVE 256 色量化。
    if im.mode == "P" and im.getpalette():
        pim = im
    else:
        pim = im.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256)
    src = pim.tobytes()
    out = bytearray(w * h)
    for by in range(0, h, th):
        for bx in range(0, w, tw):
            base = (by // th * (w // tw) + bx // tw) * (tw * th)
            for y in range(th):
                row = (by + y) * w + bx
                out[base + y * tw: base + y * tw + tw] = src[row:row + tw]
    pal = pim.getpalette() or []
    pal = list(pal[:768]) + [0] * max(0, 768 - len(pal))
    tlut = bytearray(512)
    for i in range(256):
        r, g, b = pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]
        v = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        tlut[i * 2] = v >> 8
        tlut[i * 2 + 1] = v & 0xFF
    return bytes(out), bytes(tlut)


def encode_tpl(images, fmt: str = "rgb5a3") -> bytes:
    """把一张或多张 PIL RGB 图编成 Swiss 可直接读的 TPL。

    多张图会按日历轮换（Swiss 侧逻辑见 DrawLoadBackdrop）：
    2/3/4/6/12 按季节或月份、7 按星期、24 按小时、30/31 按日、
    365/366 按年内天数，其它张数每次开机随机。
    """
    if fmt not in FORMATS:
        raise ValueError("不支持的格式：%s" % fmt)
    images = list(images)
    if not images:
        raise ValueError("至少要有一张图片")
    code, tw, th, bpp, _ = FORMATS[fmt]
    is_ci = fmt == "ci8"
    for im in images:
        if im.width % tw or im.height % th:
            raise ValueError("尺寸 %dx%d 不是 %dx%d 分块的整数倍"
                             % (im.width, im.height, tw, th))
    if len(images) > 366:
        raise ValueError("最多 366 张（按年内天数轮换）")

    payloads = []
    for im in images:
        if is_ci and im.mode == "P" and im.getpalette():
            # 用户/上游已经量化好的调色板图：索引必须原样保留
            payloads.append(_encode_ci8(im, tw, th))
            continue
        im = im.convert("RGB")
        if is_ci:
            payloads.append(_encode_ci8(im, tw, th))
        else:
            payloads.append((_encode_rgb(im, code, tw, th), None))

    n = len(payloads)
    table_off = 12
    tex_hdr_off = [table_off + 8 * n + i * 36 for i in range(n)]
    pos = _align32(table_off + 8 * n + 36 * n)
    pal_hdr_off = [pos + i * 12 for i in range(n)] if is_ci else [0] * n
    pos = _align32(pos + (12 * n if is_ci else 0))

    tex_off = []
    for tex, _ in payloads:
        tex_off.append(pos)
        pos = _align32(pos + len(tex))
    pal_off = [0] * n
    if is_ci:
        for i, (_, pal) in enumerate(payloads):
            pal_off[i] = pos
            pos = _align32(pos + len(pal))

    buf = bytearray(pos)
    struct.pack_into(">III", buf, 0, TPL_MAGIC, n, table_off)
    def _is_pot(v: int) -> bool:
        return v > 0 and not (v & (v - 1))

    for i, im in enumerate(images):
        struct.pack_into(">II", buf, table_off + i * 8,
                         tex_hdr_off[i], pal_hdr_off[i])
        # gxtexconv 对 2 的幂尺寸用 REPEAT(1)，非 2 的幂（640x480）用 CLAMP(0)；
        # 照抄它的规则才能让产物与已实机验证过的 TPL 逐字节一致。
        wrap = 1 if _is_pot(im.width) and _is_pot(im.height) else 0
        struct.pack_into(">HHIIIIIIfBBBB", buf, tex_hdr_off[i],
                         im.height, im.width, code, tex_off[i],
                         wrap, wrap, 1, 1, 0.0, 0, 0, 0, 0)
        if is_ci:
            struct.pack_into(">HBBII", buf, pal_hdr_off[i],
                             256, 0, 0, GX_TL_RGB5A3, pal_off[i])
        buf[tex_off[i]:tex_off[i] + len(payloads[i][0])] = payloads[i][0]
        if is_ci:
            buf[pal_off[i]:pal_off[i] + len(payloads[i][1])] = payloads[i][1]
    return bytes(buf)


# --------------------------------------------------------------------------- 解码
def tpl_info(data: bytes) -> dict:
    if len(data) < 12:
        raise ValueError("不是 TPL：文件太短")
    magic, n, table = struct.unpack_from(">III", data, 0)
    if magic != TPL_MAGIC or not 0 < n <= 4096:
        raise ValueError("不是有效的 TPL 文件")
    out = {"count": n, "textures": []}
    for i in range(n):
        th, ph = struct.unpack_from(">II", data, table + i * 8)
        h, w, fmt, off = struct.unpack_from(">HHII", data, th)
        item = {"width": w, "height": h, "format": fmt, "data": off}
        if ph:
            ne, _, _, pf, po = struct.unpack_from(">HBBII", data, ph)
            item["palette"] = {"entries": ne, "format": pf, "data": po}
        out["textures"].append(item)
    return out


def decode_tpl(data: bytes, index: int = 0) -> Image.Image:
    """把 TPL 里的一张贴图解回 RGB 图，用于「打开 TPL 看效果」和自检。"""
    info = tpl_info(data)
    t = info["textures"][index]
    w, h, fmt, off = t["width"], t["height"], t["format"], t["data"]
    if fmt == GX_TF_RGB5A3 or fmt == GX_TF_RGB565:
        tw = th = 4
        raw = data[off:off + w * h * 2]
        if len(raw) < w * h * 2:
            raise ValueError("TPL 纹理数据不完整")
        img = Image.new("RGB", (w, h))
        px = img.load()
        for by in range(0, h, th):
            for bx in range(0, w, tw):
                base = (by // th * (w // tw) + bx // tw) * (tw * th)
                for y in range(th):
                    o = (base + y * tw) * 2
                    for x in range(tw):
                        v = (raw[o] << 8) | raw[o + 1]
                        o += 2
                        if fmt == GX_TF_RGB5A3 and v & 0x8000:
                            px[bx + x, by + y] = (((v >> 10) & 31) * 255 // 31,
                                                  ((v >> 5) & 31) * 255 // 31,
                                                  (v & 31) * 255 // 31)
                        elif fmt == GX_TF_RGB5A3:
                            px[bx + x, by + y] = (((v >> 8) & 15) * 17,
                                                  ((v >> 4) & 15) * 17,
                                                  (v & 15) * 17)
                        else:
                            px[bx + x, by + y] = (((v >> 11) & 31) * 255 // 31,
                                                  ((v >> 5) & 63) * 255 // 63,
                                                  (v & 31) * 255 // 31)
        return img
    if fmt == GX_TF_CI8:
        tw, th = 8, 4
        raw = data[off:off + w * h]
        pal = t.get("palette")
        if not pal:
            raise ValueError("CI8 贴图缺少调色板")
        po = pal["data"]
        colors = []
        for i in range(256):
            v = (data[po + i * 2] << 8) | data[po + i * 2 + 1]
            if v & 0x8000:
                colors.append((((v >> 10) & 31) * 255 // 31,
                               ((v >> 5) & 31) * 255 // 31,
                               (v & 31) * 255 // 31))
            else:
                colors.append((((v >> 8) & 15) * 17,
                               ((v >> 4) & 15) * 17,
                               (v & 15) * 17))
        img = Image.new("RGB", (w, h))
        px = img.load()
        for by in range(0, h, th):
            for bx in range(0, w, tw):
                base = (by // th * (w // tw) + bx // tw) * (tw * th)
                for y in range(th):
                    o = base + y * tw
                    for x in range(tw):
                        px[bx + x, by + y] = colors[raw[o + x]]
        return img
    raise ValueError("暂不支持解码 GX 格式 %d" % fmt)
