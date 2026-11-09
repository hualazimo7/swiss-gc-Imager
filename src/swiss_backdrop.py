#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SwissBackdrop —— 专门给 GameCube Swiss 做自定义背景图的 PC 端工具。

    python tools/swiss_backdrop.py                       图形界面（默认）
    python tools/swiss_backdrop.py --selftest           编码/解码/中文路径自检
    python tools/swiss_backdrop.py --version
    python tools/swiss_backdrop.py --cli --build --images a.png b.png --out-dir out
    python tools/swiss_backdrop.py --cli --build --images a.png b.png --sd-package out/SD --zip
    python tools/swiss_backdrop.py --cli --host 192.168.1.2 --upload-dir out
    python tools/swiss_backdrop.py --cli --host 192.168.1.2 --remove
    python tools/swiss_backdrop.py --cli --host 192.168.1.2 --screen shot.png

固件在「设置 → 界面设置 (2/6) → 背景图」里用左右键选 0~9：
    1~9 → <启动设备>:/swiss/backdrop1.tpl ~ backdrop9.tpl（即时切换）
    0   → 关闭，保留内置默认背景
    编号 1 且 backdrop1.tpl 不存在时，回退旧名 swiss/backdrop.tpl

本工具默认「逐张编号」：图片列表按顺序，一张图编码成一个独立的
backdropN.tpl（最多 9 张），导出到 SD 卡包 / 文件夹 / 直写盘符 / 联网直传
都会自动排好序号。切到「合并为 backdrop.tpl」则保留旧版行为：
一个 TPL 内放多张贴图，由固件按日历轮换。

把「选图 → 裁切 → 调色 → 预览（可叠加模拟 UI）→ 编码 TPL → 生成 SD 卡文件
→ 回读校验 / 抓实机画面」收在一个窗口里，且**不需要 devkitPro / gxtexconv** ——
TPL 编码全部由 tools/tplcodec.py 用 Pillow 实现，中文路径也不会崩。

**不是每台 GameCube 都装了网卡**：主路径是纯离线的 `tools/sdcard_export.py`，
生成 `SwissBackdrop_SD/swiss/backdrop1.tpl…` 文件夹让用户自己拷进 SD 卡，
也可直接写 SD 卡盘符。联网直传（Swiss httpd(80) 的 FatFs 端点，见 swiss_client.py）
只是可选加速项，没有网络时全部离线功能照样可用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageStat, ImageTk

# 本地模块：源码运行时同目录可见；PyInstaller 里由 --hidden-import 打进去
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tplcodec import (  # noqa: E402
    FORMATS, Adjust, encode_tpl, decode_tpl, estimate_size,
    prepare_image, tpl_info,
)
from swiss_client import (  # noqa: E402
    DEFAULT_HOST, SwissClient, SwissError, quote,
)
import grab_screen  # noqa: E402
import sdcard_export as sd  # noqa: E402

APP_NAME = "SwissBackdrop"
APP_VER = "1.2"
CONFIG_PATH = Path.home() / ".swissbackdrop.json"
FROZEN = bool(getattr(sys, "frozen", False))
REMOTE_DIR = "swiss/"
REMOTE_NAME = "swiss/backdrop.tpl"          # 旧名，1 号缺失时固件会回退
MAX_BACKDROPS = 9
MODE_LABELS = {
    "numbered": "逐张编号 backdrop1~9（推荐）",
    "merged": "合并为 backdrop.tpl（旧版轮换）",
}

THEMES = {
    "light": dict(
        bg="#f4f6f8", panel="#ffffff", border="#dfe4ea", text="#222831",
        muted="#6b7280", accent="#2f6feb", accent_fg="#ffffff",
        sel="#dbe8ff", ok="#15803d", warn="#b45309", err="#dc2626",
        header="#eef1f5", field="#ffffff",
    ),
    "dark": dict(
        bg="#1c1f24", panel="#252a31", border="#343b45", text="#e6e9ee",
        muted="#98a2b3", accent="#7aa5e9", accent_fg="#151a20",
        sel="#33465f", ok="#5fbf83", warn="#d9a441", err="#e57474",
        header="#2b313a", field="#1e232a",
    ),
}

ROTATION = {
    2: "按半年（季节）轮换", 3: "按 4 个月一轮换", 4: "按季节轮换",
    6: "每 2 个月轮换", 7: "按星期轮换", 12: "按月份轮换",
    24: "按小时轮换", 30: "按日期轮换", 31: "按日期轮换",
    365: "按年内天数轮换", 366: "按年内天数轮换",
}

_TEXT_FLAGS = {"--cli", "--selftest", "--version", "--help", "-h", "--log"}


class _NullWriter:
    def write(self, s):
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


class _TeeWriter:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s):
        for f in self.streams:
            try:
                f.write(s)
                f.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        for f in self.streams:
            try:
                f.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def _setup_io(argv):
    """--windowed 产物 stdout/stderr 为 None；带 CLI 开关时附上父控制台。"""
    needs_text = any(a.split("=", 1)[0] in _TEXT_FLAGS for a in argv[1:])
    log_path = None
    for i, a in enumerate(argv):
        if a == "--log" and i + 1 < len(argv):
            log_path = argv[i + 1]
    logf = None
    if log_path:
        try:
            logf = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
        except OSError:
            logf = None
    if FROZEN:
        con = None
        if needs_text and os.name == "nt":
            try:
                import ctypes
                k32 = ctypes.windll.kernel32
                if not k32.AttachConsole(-1):
                    k32.AllocConsole()
                con = open("CONOUT$", "w", encoding="utf-8",
                           errors="replace", buffering=1)
            except Exception:
                con = None
        w = _TeeWriter(con, logf) if (con or logf) else _NullWriter()
        sys.stdout = w
        sys.stderr = w
    elif logf:
        sys.stdout = _TeeWriter(sys.stdout, logf)
        sys.stderr = _TeeWriter(sys.stderr, logf)


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except OSError:
        pass


def load_font(size: int):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def rotation_hint(n: int) -> str:
    if n <= 1:
        return "单张背景，固定显示"
    if n in ROTATION:
        return "%d 张 · %s" % (n, ROTATION[n])
    return "%d 张 · 每次开机随机选一张（用 7/12/24/31 等张数可按日历轮换）" % n


# --------------------------------------------------------------------------- 预览
def draw_ui_overlay(im: Image.Image) -> Image.Image:
    """在 640×480 背景上叠一层简化 Swiss 主界面，用来预判浅色文字的可读性。
    这是示意图，不是实机截图；真实画面请用「抓实机画面」。"""
    base = im.convert("RGBA")
    # 界面坐标按 640x480 设计；用户选 320x240 时整体缩放叠加层
    W, H = 640, 480
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f_s = load_font(13)
    f_m = load_font(16)
    f_b = load_font(19)
    WHITE = (255, 255, 255, 245)
    DIM = (215, 225, 235, 225)

    # 顶栏
    d.rectangle((0, 0, 640, 30), fill=(12, 18, 28, 150))
    d.text((14, 6), "Swiss v0.6  r2154", font=f_m, fill=WHITE)
    d.text((640 - 14, 7), "40°C   2026/11/08  22:14", font=f_s, fill=WHITE, anchor="ra")
    d.text((14, 38), "SD 卡 - 插槽 B", font=f_b, fill=WHITE)
    d.text((640 - 14, 40), "/root/game/GameCube", font=f_s, fill=DIM, anchor="ra")

    # 左栏信息卡
    d.rounded_rectangle((14, 74, 186, 196), radius=10, fill=(10, 16, 26, 105))
    for i, line in enumerate(("插槽 B", "总计   128 GB", "可用   11.8 GB",
                              "已用   116 GB", "共 65 项")):
        d.text((28, 86 + i * 21), line, font=f_s, fill=WHITE)

    # 文件列表
    d.rounded_rectangle((202, 74, 626, 424), radius=10, fill=(10, 16, 26, 80))
    names = ("Capcom vs. SNK 2 EO (USA)", "Dragon Ball Z - Budokai 2",
             "Over the Hedge", "Fantastic 4", "FireBlade",
             "Game Boy Player Startup Disc", "Mario Kart Double Dash",
             "Metroid Prime", "Super Smash Bros. Melee",
             "The Legend of Zelda - Wind Waker", "Viewtiful Joe",
             "Wario World", "Wave Race - Blue Storm", "Zelda - Four Swords")
    for i, name in enumerate(names):
        y = 86 + i * 24
        if i == 0:
            d.rounded_rectangle((210, y - 4, 618, y + 20), radius=5,
                                fill=(47, 111, 235, 160))
        d.text((220, y), name, font=f_s, fill=WHITE)

    # 底部按钮栏
    d.rounded_rectangle((14, 438, 626, 470), radius=10, fill=(10, 16, 26, 130))
    for i, label in enumerate(("A  启动", "B  返回", "X  设置", "Y  信息", "Z  设备")):
        d.text((26 + i * 122, 446), label, font=f_s, fill=WHITE)
    if base.size != (W, H):
        ov = ov.resize(base.size, Image.LANCZOS)
    return Image.alpha_composite(base, ov).convert("RGB")


def readability(im: Image.Image) -> tuple:
    """返回 (平均亮度, 文字区域平均亮度, 建议文字)。"""
    g = im.convert("L")
    mean = ImageStat.Stat(g).mean[0]
    sx, sy = im.width / 640.0, im.height / 480.0
    boxes = ((14, 74, 186, 196), (202, 74, 626, 424), (14, 438, 626, 470),
             (0, 0, 640, 30))
    vals = []
    for x0, y0, x1, y1 in boxes:
        crop = im.crop((int(x0 * sx), int(y0 * sy),
                        max(1, int(x1 * sx)), max(1, int(y1 * sy))))
        vals.append(ImageStat.Stat(crop.convert("L")).mean[0])
    text_l = sum(vals) / len(vals)
    if text_l < 70:
        advice = "文字对比充足，适合直接使用"
    elif text_l < 110:
        advice = "对比尚可，亮部略多"
    elif text_l < 155:
        advice = "偏亮，建议把亮度降到 80% 左右"
    else:
        advice = "太亮，浅色文字会看不清，请压暗或加暗角"
    return mean, text_l, advice


# --------------------------------------------------------------------------- 业务
def build_tpl(image_paths, width, height, fit, fmt, adj: Adjust) -> bytes:
    """旧模式：所有图片合并进一个多贴图 TPL，由固件按日历轮换。"""
    imgs = [prepare_image(p, width, height, fit, adj) for p in image_paths]
    return encode_tpl(imgs, fmt)


def build_numbered(image_paths, width, height, fit, fmt, adj: Adjust) -> dict[str, bytes]:
    """新模式：一张图一个独立的单贴图 TPL，按列表顺序编号 1~9。"""
    if not 1 <= len(image_paths) <= MAX_BACKDROPS:
        raise ValueError("逐张编号模式支持 1~%d 张图片，当前 %d 张。\n"
                         "请删掉多余图片，或改用「合并为 backdrop.tpl」模式。"
                         % (MAX_BACKDROPS, len(image_paths)))
    files = {}
    for i, p in enumerate(image_paths, 1):
        im = prepare_image(p, width, height, fit, adj)
        files["backdrop%d.tpl" % i] = encode_tpl([im], fmt)
    return files


def build_set(image_paths, width, height, fit, fmt, adj: Adjust,
              mode: str = "numbered") -> dict[str, bytes]:
    """统一入口：返回 {文件名: TPL 字节}，供所有导出/上传路径复用。"""
    if mode == "merged":
        return {sd.BACKDROP_NAME: build_tpl(image_paths, width, height, fit, fmt, adj)}
    return build_numbered(image_paths, width, height, fit, fmt, adj)


def numbering_hint(n: int, mode: str = "numbered") -> str:
    if mode == "merged":
        return rotation_hint(n) + "\n（单个 backdrop.tpl，固件按贴图数轮换）"
    if n == 0:
        return "添加图片后按顺序生成 backdrop1.tpl、backdrop2.tpl…"
    if n > MAX_BACKDROPS:
        return ("⚠ 共 %d 张，固件最多认 %d 个编号。\n请删到 %d 张以内或改用合并模式。"
                % (n, MAX_BACKDROPS, MAX_BACKDROPS))
    return ("共 %d 张 → backdrop1.tpl ~ backdrop%d.tpl\n"
            "Swiss 设置 → 界面设置(2/6) → 背景图选 1~%d"
            % (n, n, n))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote_path(client: SwissClient, name: str | None = None) -> str:
    vol = client.detect_volume()
    return vol + REMOTE_DIR + (name or sd.BACKDROP_NAME)


def _upload_one(c: SwissClient, data: bytes, target: str, st: dict,
                progress=None) -> dict:
    tmpdir = tempfile.mkdtemp(prefix="swissbg_")
    local = os.path.join(tmpdir, os.path.basename(target))
    with open(local, "wb") as fh:
        fh.write(data)
    reply = c.upload(local, target, progress=progress)
    # 回读校验（走 /get，确认固件确实落盘且字节一致）
    back = os.path.join(tmpdir, "readback.tpl")
    c.download(target, back)
    with open(back, "rb") as fh:
        got = fh.read()
    if got != data:
        raise SwissError("回读校验失败：%s 上是 %d 字节 / %s，本地是 %d 字节 / %s"
                         % (target, len(got), sha(got)[:12], len(data), sha(data)[:12]))
    try:
        os.remove(local)
        os.remove(back)
        os.rmdir(tmpdir)
    except OSError:
        pass
    return {"target": target, "size": len(data), "sha": sha(data),
            "reply": reply, "state": st}


def upload_tpl(host: str, data: bytes, progress=None, name: str | None = None) -> dict:
    """上传单个 TPL + 回读 SHA-256 校验，返回诊断信息。"""
    c = SwissClient(host)
    if not c.ping():
        raise SwissError("连不上 %s 的 Swiss httpd（80 端口）" % host)
    st = c.state()
    if st.get("busy") == "1":
        raise SwissError("Swiss 正在扫描目录，稍等几秒再试")
    return _upload_one(c, data, remote_path(c, name), st, progress)


def upload_tpls(host: str, files, progress=None) -> dict:
    """批量上传 backdrop1.tpl…；一次 ping/state，逐个上传并回读校验。"""
    files = sd.normalize_files(files)
    c = SwissClient(host)
    if not c.ping():
        raise SwissError("连不上 %s 的 Swiss httpd（80 端口）" % host)
    st = c.state()
    if st.get("busy") == "1":
        raise SwissError("Swiss 正在扫描目录，稍等几秒再试")
    vol = c.detect_volume()
    names = sorted(files)
    total = sum(len(files[n]) for n in names)
    done = 0
    results = []
    for n in names:
        base = done

        def sub(sent, part, speed, _base=base):
            if progress:
                progress(_base + sent, total, speed)

        results.append(_upload_one(c, files[n], vol + REMOTE_DIR + n, st, sub))
        done += len(files[n])
    return {"files": results, "names": names, "size": total,
            "targets": [r["target"] for r in results]}


def remove_tpl(host: str) -> str:
    """远端删除旧名 + 1~9 号背景图；不存在的文件跳过，不碰其它文件。"""
    c = SwissClient(host)
    if not c.ping():
        raise SwissError("连不上 %s 的 Swiss httpd（80 端口）" % host)
    vol = c.detect_volume()
    removed = []
    for name in [sd.BACKDROP_NAME] + sd.NUMBERED_NAMES:
        try:
            c.delete(vol + REMOTE_DIR + name)
            removed.append(name)
        except (SwissError, OSError, ValueError):
            pass
    if not removed:
        return "远端没有 backdrop*.tpl（本来就是内置默认背景）"
    return "已删除 %d 个：%s" % (len(removed), "、".join(removed))


def grab_frame(host: str) -> Image.Image:
    """抓 /screen.bin（YUY2）并转成 PIL RGB 图。"""
    payload = grab_screen.fetch(host)
    if len(payload) < 16 or payload[:4] != b"SWSC":
        raise SwissError("Swiss 没有返回有效的画面数据（需要带 /screen.bin 的固件）")
    w, h, fmt, size = struct.unpack("<HHII", payload[4:16])
    body = payload[16:16 + size]
    # decode_yuy2 产出的是 BMP 用的 BGR 行，交换回 RGB 后直接喂给 Pillow，
    # 避免 grab_screen.write_bmp() 只接受文件路径的限制。
    rows = grab_screen.decode_yuy2(body, w, h)
    data = b"".join(bytes(r) for r in rows)
    im = Image.frombytes("RGB", (w, h), data)
    b, g, r = im.split()
    return Image.merge("RGB", (r, g, b))


# --------------------------------------------------------------------------- GUI
class App(tk.Tk):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.theme_name = cfg.get("theme", "light")
        if self.theme_name not in THEMES:
            self.theme_name = "light"
        self.t = THEMES[self.theme_name]

        self.images: list[str] = [p for p in cfg.get("images", []) if os.path.isfile(p)]
        self.host_var = tk.StringVar(value=cfg.get("host", DEFAULT_HOST))
        self.mode_var = tk.StringVar(
            value=MODE_LABELS.get(cfg.get("mode", "numbered"), MODE_LABELS["numbered"]))
        self.fmt_var = tk.StringVar(value=cfg.get("format", "rgb5a3"))
        self.size_var = tk.StringVar(value=cfg.get("size", "640x480"))
        self.fit_var = tk.StringVar(value=cfg.get("fit", "cover"))
        self.overlay_var = tk.BooleanVar(value=cfg.get("overlay", True))
        self.zip_var = tk.BooleanVar(value=cfg.get("zip", False))
        self.drive_var = tk.StringVar(value=cfg.get("drive", ""))
        self.adj = {k: tk.DoubleVar(value=cfg.get("adj", {}).get(k, d))
                    for k, d in (("brightness", 1.0), ("contrast", 1.0),
                                 ("saturation", 1.0), ("blur", 0.0),
                                 ("vignette", 0.0), ("offset_x", 0.5),
                                 ("offset_y", 0.5))}
        self.preview_raw: Image.Image | None = None
        self.preview_photo = None
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self._preview_job = None
        self._last_files: dict[str, bytes] | None = None

        self.title("%s  ·  Swiss 自定义背景图工作台" % APP_NAME)
        self.geometry("1240x900")
        self.minsize(1080, 780)
        self._style()
        self._build()
        self.after(80, self._poll)
        self.after(150, self._refresh_preview)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("就绪。添加图片后点「生成 SD 卡文件」即可离线使用（不需要网卡）；联网直传是可选功能。")

    # ------------------------------------------------------------------ 样式/布局
    def _style(self):
        t = self.t
        self.configure(bg=t["bg"])
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=t["bg"], foreground=t["text"],
                    font=("Microsoft YaHei UI", 10))
        s.configure("TFrame", background=t["bg"])
        s.configure("Card.TFrame", background=t["panel"], relief="flat",
                    borderwidth=1)
        s.configure("TLabel", background=t["panel"], foreground=t["text"])
        s.configure("Top.TLabel", background=t["bg"], foreground=t["text"])
        s.configure("Muted.TLabel", background=t["panel"], foreground=t["muted"])
        s.configure("Bg.TLabel", background=t["bg"], foreground=t["muted"])
        s.configure("Title.TLabel", background=t["bg"], foreground=t["text"],
                    font=("Microsoft YaHei UI", 15, "bold"))
        s.configure("Head.TLabel", background=t["panel"], foreground=t["text"],
                    font=("Microsoft YaHei UI", 11, "bold"))
        s.configure("TButton", background=t["panel"], foreground=t["text"],
                    bordercolor=t["border"], borderwidth=1, padding=(10, 6))
        s.map("TButton", background=[("active", t["sel"])])
        s.configure("Accent.TButton", background=t["accent"],
                    foreground=t["accent_fg"], borderwidth=0, padding=(12, 7),
                    font=("Microsoft YaHei UI", 10, "bold"))
        s.map("Accent.TButton", background=[("active", t["accent"])])
        s.configure("TEntry", fieldbackground=t["field"], foreground=t["text"],
                    bordercolor=t["border"], borderwidth=1, padding=5)
        # clam 主题会给 readonly 状态映射一个固定的浅色 fieldbackground，
        # 深色主题下会变成「白底浅字」，必须在 map 里一并覆盖。
        s.configure("TCombobox", fieldbackground=t["field"],
                    foreground=t["text"], background=t["panel"],
                    arrowcolor=t["text"], bordercolor=t["border"], padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly", t["field"]), ("disabled", t["field"])],
              foreground=[("readonly", t["text"]), ("disabled", t["muted"])],
              arrowcolor=[("disabled", t["muted"])])
        for opt, val in (("background", t["field"]), ("foreground", t["text"]),
                         ("selectBackground", t["sel"]),
                         ("selectForeground", t["text"])):
            self.option_add("*TCombobox*Listbox.%s" % opt, val)
        s.configure("TCheckbutton", background=t["panel"], foreground=t["text"])
        s.configure("TScale", background=t["accent"], troughcolor=t["header"])
        s.configure("TProgressbar", background=t["accent"],
                    troughcolor=t["header"], borderwidth=0)
        s.configure("Status.TLabel", background=t["bg"], foreground=t["muted"])
        s.configure("Listbox", background=t["field"], foreground=t["text"])

    def _card(self, parent, title=None, **kw):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=14, **kw)
        if title:
            ttk.Label(outer, text=title, style="Head.TLabel").pack(anchor="w", pady=(0, 10))
        return outer

    def _build(self):
        t = self.t
        # ---- 顶部
        top = ttk.Frame(self, padding=(18, 12, 18, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Swiss 背景图工作台", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  选图 · 调色 · 预览 · 生成 SD 卡文件（无需网卡）",
                  style="Bg.TLabel").pack(side="left", padx=(8, 0))
        ttk.Button(top, text="使用说明", command=self._help).pack(side="right", padx=4)
        ttk.Button(top, text="☾ 深色" if self.theme_name == "light" else "☀ 浅色",
                   command=self._toggle_theme).pack(side="right", padx=4)

        body = ttk.Frame(self, padding=(18, 4, 18, 0))
        # body 最后才 pack（见 _build 末尾）：让底部设备条和日志先拿到
        # 自己的自然高度，否则 expand=True 会把它们压成 1 像素。
        body.columnconfigure(0, weight=0, minsize=228)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=0, minsize=300)
        body.rowconfigure(0, weight=1)

        # ---- 左：图片列表
        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(left, text="图片列表（顺序 = 编号）", style="Head.TLabel").pack(anchor="w")
        self.lb = tk.Listbox(left, height=11, activestyle="none", bd=0,
                             highlightthickness=1,
                             highlightbackground=t["border"],
                             highlightcolor=t["accent"],
                             bg=t["field"], fg=t["text"],
                             selectbackground=t["sel"],
                             selectforeground=t["text"],
                             font=("Microsoft YaHei UI", 10))
        self.lb.pack(fill="both", expand=True, pady=(8, 8))
        self.lb.bind("<<ListboxSelect>>", lambda e: self._schedule_preview())
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Button(row, text="添加", command=self._add_images).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(row, text="移除", command=self._remove_image).pack(side="left", expand=True, fill="x", padx=2)
        row2 = ttk.Frame(left)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Button(row2, text="↑ 上移", command=lambda: self._move(-1)).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(row2, text="↓ 下移", command=lambda: self._move(1)).pack(side="left", expand=True, fill="x", padx=2)
        self.rot_label = ttk.Label(left, text="", style="Muted.TLabel", wraplength=195,
                                   justify="left")
        self.rot_label.pack(anchor="w", pady=(12, 0))
        ttk.Button(left, text="打开已有 TPL 预览", command=self._open_tpl).pack(fill="x", pady=(10, 0))
        self._sync_images()

        # ---- 中：预览
        mid = self._card(body)
        mid.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        hdr = ttk.Frame(mid)
        hdr.pack(fill="x")
        ttk.Label(hdr, text="预览", style="Head.TLabel").pack(side="left")
        ttk.Checkbutton(hdr, text="叠加模拟界面（判断文字是否看得清）",
                        variable=self.overlay_var,
                        command=self._refresh_preview).pack(side="left", padx=14)
        self.preview_box = tk.Frame(mid, bg=t["header"], highlightthickness=0)
        self.preview_box.pack(fill="both", expand=True, pady=(10, 8))
        self.preview_label = tk.Label(self.preview_box, bg=t["header"],
                                      text="添加图片后在这里预览", fg=t["muted"],
                                      font=("Microsoft YaHei UI", 11))
        self.preview_label.pack(expand=True)
        self.preview_box.bind("<Configure>", self._on_preview_resize)
        self.stat_label = ttk.Label(mid, text="—", style="Muted.TLabel",
                                    wraplength=520, justify="left")
        self.stat_label.pack(anchor="w")
        self.advice_label = ttk.Label(mid, text="", style="Muted.TLabel",
                                      wraplength=520, justify="left")
        self.advice_label.pack(anchor="w", pady=(2, 0))
        ttk.Label(mid, text="提示：模拟界面只是示意，真实效果请用下方「抓实机画面」。",
                  style="Muted.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(6, 0))

        # ---- 右：参数
        right = self._card(body)
        right.grid(row=0, column=2, sticky="nsew")
        ttk.Label(right, text="输出参数", style="Head.TLabel").pack(anchor="w", pady=(0, 10))

        def combo(label, var, values, width=16):
            f = ttk.Frame(right)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=label, width=9).pack(side="left")
            cb = ttk.Combobox(f, textvariable=var, values=values,
                              state="readonly", width=width)
            cb.pack(side="right", fill="x", expand=True)
            cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_preview())
            return cb

        mode_cb = combo("生成方式", self.mode_var, list(MODE_LABELS.values()), width=20)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._sync_images())
        combo("分辨率", self.size_var, ["640x480", "320x240"])
        combo("裁切", self.fit_var, ["cover", "contain", "stretch"])
        combo("纹理格式", self.fmt_var, list(FORMATS))
        self.fmt_hint = ttk.Label(right, text="", style="Muted.TLabel",
                                  wraplength=260, justify="left")
        self.fmt_hint.pack(anchor="w", pady=(0, 6))
        self.fmt_var.trace_add("write", lambda *_: self._update_hints())

        ttk.Separator(right).pack(fill="x", pady=4)
        ttk.Label(right, text="画面调节", style="Head.TLabel").pack(anchor="w", pady=(0, 6))

        def slider(label, key, lo, hi, step, fmt="%.2f"):
            # 单行：标签 | 滑块 | 数值。比「标签一行 + 滑块一行」省 16px/项，
            # 右栏才有空间放完整的离线导出按钮。
            f = ttk.Frame(right)
            f.pack(fill="x", pady=1)
            ttk.Label(f, text=label, width=9).pack(side="left")
            val = ttk.Label(f, text=fmt % self.adj[key].get(), width=5,
                            anchor="e", style="Muted.TLabel")
            val.pack(side="right")

            def on_move(v, k=key, lab=val, fstr=fmt):
                lab.configure(text=fstr % float(v))
                self._schedule_preview()

            sc = ttk.Scale(f, from_=lo, to=hi, variable=self.adj[key],
                           orient="horizontal", command=on_move)
            sc.pack(side="left", fill="x", expand=True, padx=6)
            return sc

        slider("亮度", "brightness", 0.30, 1.60, 0.01)
        slider("对比度", "contrast", 0.30, 1.80, 0.01)
        slider("饱和度", "saturation", 0.00, 1.60, 0.01)
        slider("高斯模糊", "blur", 0.0, 6.0, 0.1, "%.1f")
        slider("四周压暗", "vignette", 0.0, 0.9, 0.01)
        ttk.Separator(right).pack(fill="x", pady=4)
        slider("水平位置", "offset_x", 0.0, 1.0, 0.01)
        slider("垂直位置", "offset_y", 0.0, 1.0, 0.01)
        ttk.Button(right, text="重置调节", command=self._reset_adj).pack(fill="x", pady=(6, 0))
        ttk.Separator(right).pack(fill="x", pady=5)
        ttk.Button(right, text="① 生成 SD 卡文件…", style="Accent.TButton",
                   command=self._export_sd_package).pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(right, text="同时打包成 zip",
                        variable=self.zip_var).pack(anchor="w", pady=(4, 0))
        ttk.Button(right, text="② 只导出 TPL 文件…（自动编号）",
                   command=self._save_tpl).pack(fill="x", pady=(6, 0))

        # ---- 底部：离线优先（无需网卡），联网直传只是可选
        bottom = ttk.Frame(self, padding=(18, 10, 18, 4))
        bottom.pack(fill="x", side="bottom")
        card = self._card(bottom)
        card.pack(fill="x")

        # ① 离线：直接写 SD 卡盘符
        off = ttk.Frame(card)
        off.pack(fill="x")
        ttk.Label(off, text="① 离线 · 直接写 SD 卡", style="Head.TLabel").pack(side="left")
        self.drive_cb = ttk.Combobox(off, textvariable=self.drive_var, width=28,
                                     state="normal")
        self.drive_cb.pack(side="left", padx=(10, 3))
        ttk.Button(off, text="刷新盘符", command=self._refresh_drives).pack(side="left", padx=2)
        ttk.Button(off, text="写入 SD 卡", style="Accent.TButton",
                   command=self._write_drive).pack(side="left", padx=(10, 2))
        ttk.Button(off, text="从 SD 卡移除背景", command=self._remove_drive).pack(side="left", padx=2)
        ttk.Label(off, text="写完后断电重启 Swiss", style="Muted.TLabel").pack(side="left", padx=10)

        # ② 可选：联网
        net = ttk.Frame(card)
        net.pack(fill="x", pady=(10, 0))
        ttk.Label(net, text="② 可选 · 联网直传（需 GameCube 网卡）",
                  style="Head.TLabel").pack(side="left")
        ttk.Entry(net, textvariable=self.host_var, width=18).pack(side="left", padx=(10, 4))
        ttk.Button(net, text="检测连接", command=self._check).pack(side="left", padx=3)
        self.conn_label = ttk.Label(net, text="未检测", style="Muted.TLabel")
        self.conn_label.pack(side="left", padx=10)
        ttk.Button(net, text="上传到 Swiss 并生效",
                   command=self._upload).pack(side="right", padx=3)
        ttk.Button(net, text="抓实机画面", command=self._grab).pack(side="right", padx=3)
        ttk.Button(net, text="恢复默认背景（远端）",
                   command=self._remove).pack(side="right", padx=3)
        self.prog = ttk.Progressbar(card, mode="determinate", maximum=100)
        self.prog.pack(fill="x", pady=(10, 0))
        self._refresh_drives()

        # ---- 日志 / 状态
        foot = ttk.Frame(self, padding=(18, 2, 18, 12))
        foot.pack(fill="x", side="bottom")
        self.status = ttk.Label(foot, text="就绪", style="Status.TLabel", anchor="w")
        self.status.pack(fill="x")
        self.log = tk.Text(foot, height=2, bd=0, bg=t["panel"], fg=t["muted"],
                           font=("Consolas", 9), wrap="word",
                           highlightthickness=1,
                           highlightbackground=t["border"])
        self.log.pack(fill="x", pady=(4, 0))
        self.log.configure(state="disabled")
        # 最后才放可伸缩的主体，保证上面三块都已分到空间
        body.pack(fill="both", expand=True, side="top")
        self._update_hints()

    # ------------------------------------------------------------------ 图片列表
    def _mode(self) -> str:
        label = self.mode_var.get()
        return next((k for k, v in MODE_LABELS.items() if v == label), "numbered")

    def _sync_images(self):
        mode = self._mode()
        self.lb.delete(0, "end")
        for i, p in enumerate(self.images):
            tag = ("%d → backdrop%d.tpl  " % (i + 1, i + 1)
                   if mode == "numbered" else "%d. " % (i + 1))
            self.lb.insert("end", tag + os.path.basename(p))
        if self.images and not self.lb.curselection():
            self.lb.selection_set(0)
        n = len(self.images)
        self.rot_label.configure(
            text=numbering_hint(n, mode),
            foreground=self.t["warn"] if (mode == "numbered" and n > MAX_BACKDROPS)
            else self.t["muted"])

    def _add_images(self):
        files = filedialog.askopenfilenames(
            title="选择背景图片（可多选，按顺序生成 backdrop1.tpl、backdrop2.tpl…）",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                       ("所有文件", "*.*")])
        added = 0
        for f in files:
            if f not in self.images:
                self.images.append(f)
                added += 1
        if added:
            self._sync_images()
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(len(self.images) - 1)
            self._refresh_preview()
            self._log("添加 %d 张图片，共 %d 张。" % (added, len(self.images)))

    def _remove_image(self):
        sel = list(self.lb.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self.images.pop(i)
        self._sync_images()
        self._refresh_preview()

    def _move(self, delta):
        sel = list(self.lb.curselection())
        if len(sel) != 1:
            return
        i = sel[0]
        j = i + delta
        if not 0 <= j < len(self.images):
            return
        self.images[i], self.images[j] = self.images[j], self.images[i]
        self._sync_images()
        self.lb.selection_set(j)

    def _current_image(self):
        sel = list(self.lb.curselection())
        if not sel or sel[0] >= len(self.images):
            return self.images[0] if self.images else None
        return self.images[sel[0]]

    def _open_tpl(self):
        p = filedialog.askopenfilename(title="打开 TPL 查看实际纹理",
                                       filetypes=[("TPL 纹理", "*.tpl"), ("所有文件", "*.*")])
        if not p:
            return
        try:
            data = Path(p).read_bytes()
            info = tpl_info(data)
            im = decode_tpl(data, 0)
            self.preview_raw = None
            self._show_image(draw_ui_overlay(im) if self.overlay_var.get() else im)
            self.stat_label.configure(
                text="TPL：%d 张贴图中的第 1 张 · %dx%d · GX 格式 %d · %d 字节"
                     % (info["count"], im.width, im.height,
                        info["textures"][0]["format"], len(data)))
            self.advice_label.configure(text="这是从 TPL 解码出的实际纹理（不含 Swiss 界面元素）。")
            self._log("打开 TPL：%s" % p)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    # ------------------------------------------------------------------ 参数/预览
    def _reset_adj(self):
        for k, d in (("brightness", 1.0), ("contrast", 1.0), ("saturation", 1.0),
                     ("blur", 0.0), ("vignette", 0.0), ("offset_x", 0.5),
                     ("offset_y", 0.5)):
            self.adj[k].set(d)
        self._refresh_preview()

    def _update_hints(self):
        f = self.fmt_var.get()
        hint = FORMATS.get(f, ("", "", "", "", ""))[4]
        # 单行显示，详细体积已在中栏预览统计里给出
        self.fmt_hint.configure(text=hint.split("，")[0])
        w, h = (int(x) for x in self.size_var.get().split("x"))
        n = max(1, len(self.images))
        sz = estimate_size(n, w, h, f)
        self._est = sz

    def _get_adjust(self) -> Adjust:
        return Adjust(**{k: float(v.get()) for k, v in self.adj.items()})

    def _on_preview_resize(self, event):
        key = (event.width, event.height)
        if not self.images or getattr(self, "_last_box", None) == key:
            return
        self._last_box = key
        self._schedule_preview()

    def _schedule_preview(self):
        self._update_hints()
        if self._preview_job:
            try:
                self.after_cancel(self._preview_job)
            except tk.TclError:
                pass
        self._preview_job = self.after(160, self._refresh_preview)

    def _refresh_preview(self):
        self._preview_job = None
        path = self._current_image()
        if not path or not os.path.isfile(path):
            self.preview_raw = None
            self.preview_label.configure(image="", text="添加图片后在这里预览")
            self.preview_photo = None
            self.stat_label.configure(text="—")
            self.advice_label.configure(text="")
            return
        w, h = (int(x) for x in self.size_var.get().split("x"))
        try:
            im = prepare_image(path, w, h, self.fit_var.get(), self._get_adjust())
        except Exception as exc:
            self.stat_label.configure(text="图片读取失败：%s" % exc)
            return
        self.preview_raw = im
        mean, text_l, advice = readability(im)
        shown = draw_ui_overlay(im) if self.overlay_var.get() else im
        self._show_image(shown)
        sz = estimate_size(max(1, len(self.images)), w, h, self.fmt_var.get())
        tag = ("%d 个编号 TPL" % len(self.images) if self._mode() == "numbered"
               else "%d 张贴图 / 1 个 TPL" % len(self.images))
        self.stat_label.configure(
            text="%dx%d · 平均亮度 %.1f · 文字区 %.1f · 预计合计约 %.0f KB · %s"
                 % (w, h, mean, text_l, sz / 1024, tag))
        self.advice_label.configure(text="可读性：" + advice)

    def _show_image(self, im: Image.Image):
        box_w = max(320, self.preview_box.winfo_width() - 16)
        box_h = max(240, self.preview_box.winfo_height() - 16)
        scale = min(box_w / im.width, box_h / im.height, 1.0)
        dw, dh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
        disp = im.resize((dw, dh), Image.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(disp)
        self.preview_label.configure(image=self.preview_photo, text="")

    # ------------------------------------------------------------------ 日志/线程
    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ") + msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status.configure(text=msg)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.prog.configure(value=0 if not busy else self.prog["value"])

    def _run(self, label, fn, on_ok=None):
        if self.busy:
            return
        self._set_busy(True)
        self._log(label + "…")

        def worker():
            try:
                result = fn()
                self.q.put(("ok", label, result, on_ok))
            except Exception as exc:
                self.q.put(("err", label, "%s: %s" % (type(exc).__name__, exc), None))
                self.q.put(("trace", "", traceback.format_exc(), None))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, label, payload, cb = self.q.get_nowait()
                if kind == "trace":
                    print(payload)
                    continue
                if kind == "prog":
                    self.prog.configure(value=payload)
                    continue
                if kind == "info":
                    self._log(str(payload))
                    continue
                self._set_busy(False)
                if kind == "err":
                    self._log("✗ %s 失败：%s" % (label, payload))
                    messagebox.showerror("%s 失败" % label, payload)
                else:
                    self._log("✓ %s 完成" % label)
                    if cb:
                        cb(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ------------------------------------------------------------------ 生成/传输
    def _build_files(self) -> dict[str, bytes]:
        if not self.images:
            raise ValueError("请先添加至少一张图片")
        for p in self.images:
            if not os.path.isfile(p):
                raise ValueError("图片不存在：%s" % p)
        w, h = (int(x) for x in self.size_var.get().split("x"))
        return build_set(self.images, w, h, self.fit_var.get(),
                         self.fmt_var.get(), self._get_adjust(), self._mode())

    def _expected_names(self) -> list[str]:
        """仅用于覆盖确认/文案预估；真正的张数校验在 _build_files 里。"""
        if not self.images:
            return []
        if self._mode() == "merged":
            return [sd.BACKDROP_NAME]
        return sd.numbered_names(min(len(self.images), MAX_BACKDROPS))

    def _save_tpl(self):
        if not self.images:
            messagebox.showwarning("没有图片", "请先添加至少一张图片。")
            return
        out = filedialog.askdirectory(
            title="选一个文件夹，在里面生成 backdrop1.tpl、backdrop2.tpl…",
            initialdir=str(Path.home() / "Desktop"))
        if not out:
            return
        names = self._expected_names()
        exist = [n for n in names if (Path(out) / n).is_file()]
        if exist and not messagebox.askyesno(
                "确认覆盖", "这个文件夹里已有同名文件：\n\n%s\n\n将被覆盖，继续？"
                % "、".join(exist)):
            return

        def work():
            files = self._build_files()
            for name, data in files.items():
                p = Path(out) / name
                p.write_bytes(data)
                if p.read_bytes() != data:
                    raise OSError("写入后回读不一致：%s" % p)
            self._last_files = files
            return {"dir": out, "names": sorted(files),
                    "size": sum(len(d) for d in files.values())}

        def done(r):
            self._log("已导出 %d 个 TPL 到 %s（合计 %d 字节）"
                      % (len(r["names"]), r["dir"], r["size"]))
            messagebox.showinfo(
                "生成完成",
                "已在下面这个文件夹生成 %d 个 TPL：\n\n%s\n\n%s\n\n合计 %d 字节。\n\n"
                "把 swiss/ 目录里的这些文件放到 <启动设备>:/swiss/，\n"
                "再到 Swiss「设置 → 界面设置 (2/6) → 背景图」选对应编号即可切换。"
                % (len(r["names"]), r["dir"], "、".join(r["names"]), r["size"]))

        self._run("生成 TPL 文件", work, done)

    # ------------------------------------------------------------ 离线 SD 卡导出
    def _refresh_drives(self):
        drives = sd.list_drives(include_fixed=True)
        self._drives = drives
        self.drive_cb.configure(values=[sd.describe_drive(d) for d in drives])
        cur = self.drive_var.get().strip()
        if not cur:
            pick = next((d["root"] for d in drives if d["removable"]), None)
            if pick is None and drives:
                pick = drives[0]["root"]
            self.drive_var.set(pick or "")

    @staticmethod
    def _open_in_explorer(path: str):
        try:
            os.startfile(path)  # noqa: S606 (Windows-only, 由用户点击触发)
        except Exception:
            pass

    def _export_sd_package(self):
        desktop = Path.home() / "Desktop"
        parent = filedialog.askdirectory(
            title="选一个位置，工具会在里面创建 SwissBackdrop_SD 文件夹",
            initialdir=str(desktop if desktop.is_dir() else Path.home()))
        if not parent:
            return
        pkg = Path(parent) / sd.PACKAGE_NAME
        n = 2
        while pkg.exists() and any(pkg.iterdir()):
            pkg = Path(parent) / ("%s_%d" % (sd.PACKAGE_NAME, n))
            n += 1
        do_zip = self.zip_var.get()

        def work():
            files = self._build_files()
            self._last_files = files
            meta = sd.make_meta(
                files, count=sum(tpl_info(d)["count"] for d in files.values()),
                fmt=self.fmt_var.get(), size_px=self.size_var.get(),
                fit=self.fit_var.get(), images=self.images, mode=self._mode())
            return sd.make_package(files, pkg, meta=meta, make_zip=do_zip)

        def done(r):
            extra = "\n同时打包：%s" % r["zip"] if r["zip"] else ""
            self._log("离线包已生成：%s · %d 个 TPL · 合计 %d 字节%s"
                      % (r["dir"], len(r["names"]), r["size"], extra))
            numbered = self._mode() == "numbered"
            step = ("\n拷好后到 Swiss「设置 → 界面设置 (2/6) → 背景图」\n"
                    "按左右键选 1~%d 即可切换（0 = 关闭）。" % len(r["names"])) if numbered \
                else "\n这是旧版单文件模式，按贴图数由固件按日历轮换。"
            msg = ("已生成可直接拷贝的文件夹：\n\n%s\n\n"
                   "目录结构：\n"
                   "  swiss\\%s  ← 把这整个 swiss 文件夹\n"
                   "  【必读】安装到 SD 卡.txt     复制到 SD 卡根目录\n"
                   "  背景图信息.txt\n"
                   "  copy_to_sd.bat（可选一键复制）%s\n\n"
                   "%d 个 TPL，合计 %d 字节。%s\n\n"
                   "全程不需要网卡。"
                   % (r["dir"], ("backdrop1.tpl ~ %s" % r["names"][-1])
                      if numbered else "backdrop.tpl",
                      extra, len(r["names"]), r["size"], step))
            if messagebox.askyesno("生成完成", msg + "\n\n现在打开这个文件夹？"):
                self._open_in_explorer(r["dir"])

        self._run("生成 SD 卡文件", work, done)

    def _drivedata(self):
        """返回 (盘符根路径, swiss 目录)；输入不合法时弹窗并返回 None。"""
        raw = self.drive_var.get().strip()
        try:
            root = sd.check_drive(raw)
        except ValueError as exc:
            messagebox.showerror("盘符有误", str(exc))
            return None
        return root, str(Path(root) / sd.SD_SUBDIR)

    def _write_drive(self):
        if not self.images:
            messagebox.showwarning("没有图片", "请先添加至少一张图片。")
            return
        got = self._drivedata()
        if not got:
            return
        root, folder = got
        names = self._expected_names()
        if not messagebox.askyesno(
                "确认写入 SD 卡",
                "将把 %d 个背景图写到：\n\n%s\\\n\n%s\n\n"
                "• 只写这些 backdrop*.tpl，不动 SD 卡上的其它内容\n"
                "• 同名旧文件会先备份成 .bak\n"
                "• 写完后逐个回读校验\n\n"
                "请确认 %s 确实是 SD 卡盘符。继续？"
                % (len(names), folder, "、".join(names), root)):
            return

        def work():
            files = self._build_files()
            self._last_files = files
            return sd.write_to_sd(files, root)

        def done(r):
            self._log("已写入 %d 个 TPL 到 %s · 合计 %d 字节%s"
                      % (len(r["names"]), folder, r["size"],
                         " · 旧文件已备份" if r["backup"] else ""))
            messagebox.showinfo(
                "写入成功",
                "已写入 %d 个文件：\n%s\n\n合计 %d 字节，逐个回读一致。%s\n\n"
                "安全弹出 SD 卡插回 GameCube，断电重启后到\n"
                "「设置 → 界面设置 (2/6) → 背景图」选对应编号切换。"
                % (len(r["names"]), "、".join(r["names"]), r["size"],
                   "旧文件已备份为 .bak。" if r["backup"] else ""))

        self._run("写入 SD 卡", work, done)

    def _remove_drive(self):
        got = self._drivedata()
        if not got:
            return
        root, folder = got
        allnames = [sd.BACKDROP_NAME] + sd.NUMBERED_NAMES
        if not messagebox.askyesno(
                "确认移除",
                "将只删除 %s\\ 下这些背景图文件（存在的才删）：\n\n%s\n\n"
                "global.ini 等其它文件、以及 .bak 备份都不会动。\n\n继续？"
                % (folder, "、".join(allnames))):
            return
        self._run("从 SD 卡移除背景",
                  lambda: sd.remove_from_sd(root),
                  lambda r: (self._log("移除背景：%s" % r["message"].replace("\n", " ")),
                             messagebox.showinfo("完成", r["message"])))

    def _check(self):
        host = self.host_var.get().strip()

        def work():
            c = SwissClient(host)
            if not c.ping():
                raise SwissError("80 端口无响应，请确认 Swiss 已开机且在主界面")
            st = c.state()
            vol = c.detect_volume()
            return {"state": st, "vol": vol}

        def done(r):
            st = r["state"]
            self.conn_label.configure(text="已连接 · %s · %s" % (
                st.get("dev", "?"), st.get("path", "?")), foreground=self.t["ok"])
            self._log("连接正常：设备=%s 路径=%s 卷=%s" %
                      (st.get("dev", "?"), st.get("path", "?"), r["vol"]))
            try:
                c = SwissClient(host)
                found = []
                for name in [sd.BACKDROP_NAME] + sd.NUMBERED_NAMES:
                    e = c.exists(r["vol"] + REMOTE_DIR, name)
                    if e:
                        found.append("%s(%d B)" % (name, e.size))
                self._log("SD 上已有背景图：%s" % ("、".join(found)
                                              if found else "无，使用内置默认背景"))
            except Exception:
                pass

        self._run("检测 Swiss 连接", work, done)

    def _upload(self):
        host = self.host_var.get().strip()

        def work():
            files = self._build_files()
            self._last_files = files
            self.q.put(("info", "", "已生成 %d 个 TPL（合计 %d 字节），开始上传…"
                        % (len(files), sum(len(d) for d in files.values())), None))

            def progress(sent, total, speed):
                self.q.put(("prog", "", min(99, int(sent / max(1, total) * 100)), None))

            return upload_tpls(host, files, progress)

        def done(r):
            self.prog.configure(value=100)
            self._log("上传完成：%d 个文件 · %s · 合计 %d 字节（逐个回读一致）"
                      % (len(r["names"]), "、".join(r["names"]), r["size"]))
            messagebox.showinfo(
                "上传成功",
                "已上传 %d 个文件：\n%s\n\n合计 %d 字节，逐个回读一致。\n\n"
                "现在到 Swiss「设置 → 界面设置 (2/6) → 背景图」按左右键选\n"
                "1~%d，选中即立刻切换（0 = 关闭/内置默认背景）。"
                % (len(r["names"]), "、".join(r["names"]), r["size"],
                   len(r["names"])))

        self._run("上传背景到 Swiss", work, done)

    def _remove(self):
        if not messagebox.askyesno(
                "恢复默认背景",
                "将删除 SD 卡上的这些背景图（不存在的跳过）：\n\n%s\n\n"
                "其它文件不动。删除后在设置里把「背景图」选成 0 即恢复内置背景。\n\n确定继续？"
                % "、".join([sd.BACKDROP_NAME] + sd.NUMBERED_NAMES)):
            return
        host = self.host_var.get().strip()
        self._run("删除 SD 上的背景图",
                  lambda: remove_tpl(host),
                  lambda r: self._log("远端移除背景：%s" % r))

    def _grab(self):
        host = self.host_var.get().strip()

        def work():
            im = grab_frame(host)
            out = filedialog.asksaveasfilename(
                title="保存实机画面", defaultextension=".png",
                initialfile="swiss_screen.png",
                filetypes=[("PNG 图片", "*.png")])
            return {"im": im, "out": out}

        def done(r):
            im = r["im"]
            if r["out"]:
                im.save(r["out"])
                self._log("实机画面已保存：%s" % r["out"])
            self._show_image(im)
            mean = ImageStat.Stat(im.convert("L")).mean[0]
            self.stat_label.configure(text="实机画面 %dx%d · 平均亮度 %.2f" %
                                            (im.width, im.height, mean))
            self.advice_label.configure(text="这是 /screen.bin 抓到的真实画面。")

        self._run("抓取实机画面", work, done)

    # ------------------------------------------------------------------ 其它
    def _help(self):
        messagebox.showinfo(
            "使用说明",
            "【不需要网卡】本工具默认走离线路径，GameCube 没装网卡也完全可用。\n\n"
            "1. 添加 1~9 张图片（PNG/JPG/WEBP 均可，中文路径没问题）。\n"
            "   列表顺序就是编号：第 1 张 → backdrop1.tpl，第 2 张 → backdrop2.tpl…\n"
            "   用「添加 / 移除 / 上移 / 下移」调整顺序。\n"
            "2. 用右侧参数裁切、压暗；勾选「叠加模拟界面」预判白色文字是否看得清。\n"
            "3. 生成方式默认「逐张编号」，每张图一个独立 TPL；\n"
            "   改选「合并为 backdrop.tpl」则回到旧版：一个文件多张贴图按日历轮换。\n"
            "4. 选一种导出方式：\n"
            "   ① 生成 SD 卡文件：得到 SwissBackdrop_SD 文件夹，含 swiss\\ 下的\n"
            "      backdrop1.tpl…、中文安装说明、一键复制 bat（可勾 zip）。\n"
            "   ② 只导出 TPL 文件：选一个文件夹，直接吐出编号好的 tpl。\n"
            "   ③ SD 卡插在电脑上：底部选盘符 →「写入 SD 卡」，自动备份并回读校验。\n"
            "5. 把 swiss 文件夹整个拷进 SD 卡根目录 → 插回 GameCube → 断电重启。\n"
            "6. 【关键】设置 → 界面设置 (2/6) → 背景图，左右键选 1~N 即时切换；\n"
            "   选中的编号会存进 global.ini，下次开机保持。0 = 关闭/内置默认背景。\n\n"
            "固件路径：<启动设备>:/swiss/backdrop1.tpl ~ backdrop9.tpl（最多 9 个）\n"
            "旧名 backdrop.tpl 仅在「编号 1 且 1 号文件缺失」时被回退读取。\n"
            "恢复默认：设置里选 0，或删掉 swiss\\backdrop*.tpl（本工具「从 SD 卡移除背景」）。\n"
            "背景图是独立文件，不写进 IPL.dol，换图不用重刷固件。\n\n"
            "【可选】装了网卡时，可填主机 IP 用「上传到 Swiss 并生效」批量直传，\n"
            "或「抓实机画面」看真实效果；没有网络时这些按钮不用管。\n\n"
            "格式建议：RGB5A3 画质最好（约 600 KB/张）；CI8 省一半内存（约 300 KB），"
            "渐变特别细腻的图可能有轻微色带。\n"
            "工具内置 TPL 编码器，不需要 devkitPro / gxtexconv。")

    def _toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.cfg["theme"] = self.theme_name
        save_config(self.cfg)
        messagebox.showinfo("主题已切换", "关闭并重新打开程序即可应用新主题。")

    def _on_close(self):
        self.cfg.update({
            "host": self.host_var.get().strip(),
            "mode": self._mode(),
            "format": self.fmt_var.get(),
            "size": self.size_var.get(),
            "fit": self.fit_var.get(),
            "overlay": self.overlay_var.get(),
            "zip": self.zip_var.get(),
            "drive": self.drive_var.get().strip(),
            "images": self.images[:50],
            "adj": {k: float(v.get()) for k, v in self.adj.items()},
            "theme": self.theme_name,
        })
        save_config(self.cfg)
        self.destroy()


# --------------------------------------------------------------------------- CLI
def project_root() -> Path:
    """源码运行时取 tools/ 的上级；EXE 在 dist/ 里，同样取它的上级。"""
    if FROZEN:
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent


def selftest() -> int:
    print("SwissBackdrop %s 自检" % APP_VER)
    failures = []

    def check(name, fn):
        try:
            fn()
            print("  PASS  %s" % name)
        except Exception as exc:
            failures.append(name)
            print("  FAIL  %s : %s" % (name, exc))

    # 造一张有渐变和色块的图
    im = Image.new("RGB", (640, 480))
    px = im.load()
    for y in range(480):
        for x in range(640):
            px[x, y] = ((x * 3 + y) % 256, (y * 2 + 40) % 256, (x + y * 2) % 256)

    for fmt in FORMATS:
        def one(fmt=fmt):
            d = encode_tpl([im], fmt)
            info = tpl_info(d)
            assert info["count"] == 1
            assert info["textures"][0]["width"] == 640
            out = decode_tpl(d)
            assert out.size == (640, 480)
            a = ImageStat.Stat(im).mean
            b = ImageStat.Stat(out).mean
            assert max(abs(x - y) for x, y in zip(a, b)) < 12, (a, b)
        check("编码/解码往返 %s" % fmt, one)

    def multi():
        d = encode_tpl([im] * 7, "ci8")
        assert tpl_info(d)["count"] == 7
        assert decode_tpl(d, 6).size == (640, 480)
    check("7 张按星期轮换 TPL（合并模式）", multi)

    def batch_numbered():
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        with tempfile.TemporaryDirectory(prefix="swissbg_batch_") as td:
            paths = []
            for i, c in enumerate(colors):
                p = os.path.join(td, "背景 %d.png" % (i + 1))
                Image.new("RGB", (64, 48), c).save(p)
                paths.append(p)
            files = build_set(paths, 64, 48, "cover", "rgb5a3", Adjust())
            assert sorted(files) == ["backdrop1.tpl", "backdrop2.tpl", "backdrop3.tpl"], sorted(files)
            for name, c in zip(sorted(files), colors):
                assert tpl_info(files[name])["count"] == 1, name
                mean = ImageStat.Stat(decode_tpl(files[name])).mean
                assert max(abs(x - y) for x, y in zip(mean, c)) < 20, (name, mean, c)
            # 固件只认 1~9，超出必须明确报错
            try:
                build_set(paths * 4, 64, 48, "cover", "rgb5a3", Adjust())
            except ValueError:
                pass
            else:
                raise AssertionError("超过 9 张应被拒绝")
            # 合并模式保持旧行为：一个文件 3 张贴图
            merged = build_set(paths, 64, 48, "cover", "rgb5a3", Adjust(), "merged")
            assert list(merged) == [sd.BACKDROP_NAME]
            assert tpl_info(merged[sd.BACKDROP_NAME])["count"] == 3
    check("批量编号 backdrop1~N / 9 张上限 / 合并模式", batch_numbered)

    def rgb_exact():
        root = project_root()
        ref = root / "examples/reference_rgb5a3.tpl"
        src = root / "examples/reference.png"
        if ref.exists() and src.exists():
            mine = build_tpl([str(src)], 640, 480, "cover", "rgb5a3", Adjust())
            assert mine == ref.read_bytes(), "与 gxtexconv 产物不一致"
            print("       (与 gxtexconv 产物逐字节一致: %s)" % sha(mine)[:16])
        else:
            print("       (项目内无参考 TPL，跳过字节比对；编解码自检仍有效)")
    check("与 gxtexconv 产物字节一致", rgb_exact)

    def unicode_path():
        with tempfile.TemporaryDirectory(prefix="swissbg_测试_") as td:
            p = os.path.join(td, "背景 图.png")
            im.save(p)
            d = build_tpl([p], 640, 480, "cover", "rgb5a3", Adjust())
            assert len(d) > 600000
    check("中文路径图片", unicode_path)

    def adjust():
        a = Adjust(brightness=0.8, vignette=0.4, blur=1.0)
        out = prepare_image(im, 640, 480, "cover", a)
        assert ImageStat.Stat(out.convert("L")).mean[0] < ImageStat.Stat(im.convert("L")).mean[0]
    check("压暗/暗角调节生效", adjust)

    def offline_package():
        d1 = encode_tpl([im], "rgb5a3")
        d2 = encode_tpl([Image.new("RGB", (640, 480), (30, 60, 90))], "rgb5a3")
        files = {"backdrop1.tpl": d1, "backdrop2.tpl": d2}
        meta = sd.make_meta(files, count=2, fmt="rgb5a3", size_px="640x480",
                            fit="cover", images=["测试图1.png", "测试图2.png"],
                            mode="numbered")
        with tempfile.TemporaryDirectory(prefix="swissbg_sd_") as td:
            pkg = Path(td) / sd.PACKAGE_NAME
            r = sd.make_package(files, pkg, meta=meta, make_zip=True)
            assert r["names"] == ["backdrop1.tpl", "backdrop2.tpl"]
            assert (pkg / sd.SD_SUBDIR / "backdrop1.tpl").read_bytes() == d1
            assert (pkg / sd.SD_SUBDIR / "backdrop2.tpl").read_bytes() == d2
            assert not (pkg / sd.SD_SUBDIR / sd.BACKDROP_NAME).exists()
            readme = (pkg / sd.README_NAME).read_text(encoding="utf-8")
            assert "backdrop1.tpl" in readme and "界面设置" in readme
            assert "backdrop1.tpl" in (pkg / sd.INFO_NAME).read_text(encoding="utf-8")
            assert (pkg / sd.BAT_NAME).read_bytes().startswith(b"@echo off")
            assert Path(r["zip"]).exists()
            with zipfile.ZipFile(r["zip"]) as z:
                assert z.read("swiss/backdrop1.tpl") == d1
                assert z.read("swiss/backdrop2.tpl") == d2
            # 覆盖保护
            try:
                sd.make_package(files, pkg, meta=meta)
            except ValueError:
                pass
            else:
                raise AssertionError("非空目录应拒绝覆盖")
            # 旧接口（bytes → backdrop.tpl）仍可用
            pkg2 = Path(td) / "legacy"
            r2 = sd.make_package(d1, pkg2, meta=sd.make_meta(d1))
            assert r2["names"] == [sd.BACKDROP_NAME]
            assert (pkg2 / sd.SD_SUBDIR / sd.BACKDROP_NAME).read_bytes() == d1
            # 拒绝磁盘根目录 / 主目录
            for bad in (Path(td).anchor, Path.home()):
                try:
                    sd.make_package(files, bad, meta=meta)
                except ValueError:
                    pass
                else:
                    raise AssertionError("应拒绝写到 %s" % bad)
    check("离线 SD 卡包（多编号/zip/旧接口/覆盖保护）", offline_package)

    def file_names():
        assert sd.numbered_names(3) == ["backdrop1.tpl", "backdrop2.tpl", "backdrop3.tpl"]
        for bad in (0, 10):
            try:
                sd.numbered_names(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("应拒绝 %d 张" % bad)
        assert sd.normalize_files(b"x") == {sd.BACKDROP_NAME: b"x"}
        for bad in ("../../evil.tpl", "global.ini", "backdrop10.tpl"):
            try:
                sd.normalize_files({bad: b"x"})
            except ValueError:
                pass
            else:
                raise AssertionError("应拒绝文件名 %s" % bad)
    check("编号与文件名白名单（防越界写入）", file_names)

    def drive_guard():
        assert sd.coerce_drive("g") == "G:\\"
        assert sd.coerce_drive("G:\\  可移动 · 可用 11.8 GB") == "G:\\"
        assert sd.coerce_drive("H:/") == "H:\\"
        for bad in ("1:", "", "C:"):
            try:
                sd.check_drive(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("应拒绝盘符 %r" % bad)
    check("SD 卡盘符解析与安全校验", drive_guard)

    print("\n结果：%s" % ("全部通过" if not failures else "失败项：" + ", ".join(failures)))
    return 1 if failures else 0


def _cli_files(args) -> dict[str, bytes]:
    """离线导出用的 TPL 集合：优先 --sd-tpl 现成文件，否则从 --images 生成。"""
    if args.sd_tpl:
        p = Path(args.sd_tpl)
        name = p.name.lower() if sd.NAME_RE.fullmatch(p.name) else sd.BACKDROP_NAME
        return {name: p.read_bytes()}
    if not args.images:
        raise ValueError("需要 --images 图片列表，或用 --sd-tpl 指定现成的 TPL")
    w, h = (int(x) for x in args.size.split("x"))
    adj = Adjust(brightness=args.brightness, contrast=args.contrast,
                 saturation=args.saturation, blur=args.blur,
                 vignette=args.vignette)
    return build_set(args.images, w, h, args.fit, args.format, adj, args.mode)


def cli(args) -> int:
    host = args.host

    if args.list_drives:
        drives = sd.list_drives(include_fixed=True)
        if not drives:
            print("未检测到可写盘符。也可以手动指定，例如 --write-drive G:")
        for d in drives:
            print("  " + sd.describe_drive(d))
        return 0
    if args.remove_drive:
        r = sd.remove_from_sd(args.remove_drive)
        print(r["message"])
        return 0

    if args.sd_package or args.write_drive:
        files = _cli_files(args)
        meta = sd.make_meta(
            files, count=sum(tpl_info(d)["count"] for d in files.values()),
            fmt="现成 TPL" if args.sd_tpl else args.format,
            size_px=args.size, fit=args.fit,
            images=[] if args.sd_tpl else (args.images or []),
            mode=None if args.sd_tpl else args.mode)
        if args.sd_package:
            r = sd.make_package(files, args.sd_package, meta=meta,
                                make_zip=args.zip, force=args.force)
            print("离线包：%s" % r["dir"])
            for n in r["names"]:
                print("  swiss/%s" % n)
            print("  共 %d 个 TPL / %d 字节" % (len(r["names"]), r["size"]))
            print("  说明文件：%s" % sd.README_NAME)
            if r["zip"]:
                print("  zip：%s" % r["zip"])
            print("  把 swiss 文件夹整个拷进 SD 卡根目录，重启后在")
            print("  设置 → 界面设置 (2/6) → 背景图 选 1~%d。" % len(r["names"]))
        if args.write_drive:
            r = sd.write_to_sd(files, args.write_drive)
            for p in r["paths"]:
                print("写入 %s" % p)
            print("共 %d 个文件 / %d 字节（逐个回读一致）%s" %
                  (len(r["names"]), r["size"],
                   "，旧文件已备份为 .bak" if r["backup"] else ""))
        return 0

    if args.build:
        if not args.images and not args.sd_tpl:
            print("--build 需要 --images 或 --sd-tpl", file=sys.stderr)
            return 2
        files = _cli_files(args)
        if args.out_dir:
            out = Path(args.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            for n, d in sorted(files.items()):
                (out / n).write_bytes(d)
                print("生成 %s：%d 字节  sha256=%s" % (out / n, len(d), sha(d)))
        else:
            if len(files) > 1:
                raise ValueError("生成了 %d 个编号 TPL，请用 --out-dir 指定输出文件夹" % len(files))
            name, data = next(iter(files.items()))
            target = Path(args.out or name)
            target.write_bytes(data)
            print("生成 %s：%d 字节  sha256=%s" % (target, len(data), sha(data)))
        print("提示：用 --sd-package 目录 可生成可直接拷进 SD 卡的文件夹（无需网卡）。")
        return 0
    if args.upload_dir:
        folder = Path(args.upload_dir)
        files = {p.name.lower(): p.read_bytes()
                 for p in sorted(folder.glob("backdrop*.tpl"))
                 if sd.NAME_RE.fullmatch(p.name)}
        if not files:
            raise ValueError("%s 里没有 backdrop*.tpl" % folder)
        r = upload_tpls(host, files)
        print("批量上传 %d 个文件 / %d 字节：" % (len(r["names"]), r["size"]))
        for t in r["targets"]:
            print("  " + t)
        print("完成（逐个回读一致）。到设置 → 界面设置 (2/6) → 背景图选编号切换。")
        return 0
    if args.upload:
        p = Path(args.upload)
        data = p.read_bytes()
        name = p.name.lower() if sd.NAME_RE.fullmatch(p.name) else sd.BACKDROP_NAME
        info = tpl_info(data)
        print("上传 %s：%d 字节 / %d 张贴图 -> %s" % (name, len(data), info["count"], host))
        r = upload_tpl(host, data, name=name)
        print("完成：%s  sha=%s（回读一致）" % (r["target"], r["sha"]))
        return 0
    if args.remove:
        print("删除远端背景：", remove_tpl(host))
        return 0
    if args.screen:
        im = grab_frame(host)
        im.save(args.screen)
        print("实机画面已保存：%s  %dx%d  平均亮度 %.2f" %
              (args.screen, im.width, im.height,
               ImageStat.Stat(im.convert("L")).mean[0]))
        return 0
    if args.state:
        c = SwissClient(host)
        print("ping:", c.ping())
        print("state:", c.state())
        vol = c.detect_volume()
        for name in [sd.BACKDROP_NAME] + sd.NUMBERED_NAMES:
            e = c.exists(vol + REMOTE_DIR, name)
            if e:
                print("  %s%s  存在  %d 字节" % (vol, REMOTE_DIR + name, e.size))
        return 0
    print("什么都没做。离线用 --sd-package 目录 / --write-drive G: / --build --out-dir，"
          "联网用 --upload-dir / --upload / --remove / --screen / --state。")
    return 2


def main(argv=None) -> int:
    argv = argv or sys.argv
    _setup_io(argv)
    ap = argparse.ArgumentParser(description="%s %s - Swiss 自定义背景图工具" %
                                             (APP_NAME, APP_VER))
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--log", help="把输出同时写到日志文件")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--images", nargs="+")
    ap.add_argument("--mode", default="numbered", choices=("numbered", "merged"),
                    help="numbered=逐张生成 backdrop1~9.tpl；merged=合并成单个 backdrop.tpl")
    ap.add_argument("--out", help="--build 且只有一个 TPL 时的输出文件名")
    ap.add_argument("--out-dir", metavar="DIR",
                    help="--build 批量输出目录，自动命名 backdrop1.tpl…")
    ap.add_argument("--upload", metavar="TPL")
    ap.add_argument("--upload-dir", metavar="DIR",
                    help="批量上传目录里的 backdrop*.tpl")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--screen", metavar="PNG")
    ap.add_argument("--state", action="store_true")
    # 离线导出（不需要网卡）
    ap.add_argument("--sd-package", metavar="DIR",
                    help="生成可拷进 SD 卡的 SwissBackdrop_SD 文件夹")
    ap.add_argument("--sd-tpl", metavar="TPL",
                    help="用现成 TPL 做离线包，代替 --images 重新生成")
    ap.add_argument("--zip", action="store_true", help="配合 --sd-package 同时打包 zip")
    ap.add_argument("--force", action="store_true", help="允许覆盖非空的 --sd-package 目录")
    ap.add_argument("--write-drive", metavar="DRIVE",
                    help="直接写 <盘符>:\\swiss\\backdrop*.tpl 并逐个回读校验")
    ap.add_argument("--remove-drive", metavar="DRIVE",
                    help="只删除 <盘符>:\\swiss\\ 下的 backdrop*.tpl，恢复默认背景")
    ap.add_argument("--list-drives", action="store_true", help="列出可用盘符")
    ap.add_argument("--format", default="rgb5a3", choices=list(FORMATS))
    ap.add_argument("--fit", default="cover", choices=("cover", "contain", "stretch"))
    ap.add_argument("--size", default="640x480")
    ap.add_argument("--brightness", type=float, default=1.0)
    ap.add_argument("--contrast", type=float, default=1.0)
    ap.add_argument("--saturation", type=float, default=1.0)
    ap.add_argument("--blur", type=float, default=0.0)
    ap.add_argument("--vignette", type=float, default=0.0)
    a = ap.parse_args(argv[1:])

    if a.version:
        print("%s %s  (frozen=%s, Python %s)" %
              (APP_NAME, APP_VER, FROZEN, sys.version.split()[0]))
        return 0
    if a.selftest:
        return selftest()
    if a.cli:
        try:
            return cli(a)
        except (SwissError, OSError, ValueError) as exc:
            print("错误：%s" % exc, file=sys.stderr)
            return 1

    cfg = load_config()
    app = App(cfg)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
