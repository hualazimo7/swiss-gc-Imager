#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SwissBackdrop 的离线 SD 卡导出后端（不依赖网卡 / 网络 / devkitPro）。

GameCube 不一定装了 BBA 网卡，因此「生成一份能直接拷进 SD 卡的文件」
是本工具的主路径，联网直传只是可选加速项。本模块提供：

    make_package(data, dir, ...)   生成 SwissBackdrop_SD/ 文件夹 + 可选 zip
    list_drives()                  列出本机可移动磁盘（Windows）
    write_to_sd(data, "G:")        直接写 <盘符>:\\swiss\\backdrop.tpl 并回读校验
    remove_from_sd("G:")           只删除这一个文件，恢复内置默认背景

固件路径（Swiss 源码 DrawLoadBackdrop）：
    <启动设备>:/swiss/backdrop1.tpl ~ backdrop9.tpl   ← 设置里 1~9 切换
    <启动设备>:/swiss/backdrop.tpl                    ← 旧名，仅 1 号缺失时回退

本模块同时支持「逐张编号」（推荐，每张图一个 TPL 文件）和旧的
「合并单文件」（一个 TPL 内含多张贴图按日历轮换）。

安全约定：只创建/覆盖 swiss/ 下的 backdrop*.tpl，绝不递归删除；
覆盖前把旧文件备份为同名 .bak；拒绝写系统盘。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

SD_SUBDIR = "swiss"
BACKDROP_NAME = "backdrop.tpl"
MAX_BACKDROPS = 9
NUMBERED_NAMES = ["backdrop%d.tpl" % i for i in range(1, MAX_BACKDROPS + 1)]
ALL_NAMES = [BACKDROP_NAME] + NUMBERED_NAMES
NAME_RE = re.compile(r"backdrop(?:[1-9])?\.tpl\Z", re.IGNORECASE)
PACKAGE_NAME = "SwissBackdrop_SD"
README_NAME = "【必读】安装到 SD 卡.txt"
INFO_NAME = "背景图信息.txt"
BAT_NAME = "copy_to_sd.bat"

# 纯 ASCII，避免 bat 在 GBK 代码页下乱码；文件名用中文但内容不含中文。
COPY_BAT = r"""@echo off
setlocal enabledelayedexpansion
echo ============================================
echo   Swiss backdrop - copy to SD card
echo ============================================
echo.
echo This will copy backdrop*.tpl to ^<drive^>:\swiss\
echo.
set "DRV="
set /p "DRV=Enter SD card drive letter (for example G): "
if not defined DRV goto :cancelled
set "DRV=%DRV:~0,1%"
if not exist "%DRV%:\" (
    echo Drive %DRV%: not found.
    goto :failed
)
if /i "%DRV%"=="%SystemDrive:~0,1%" (
    echo Refusing to write to the system drive.
    goto :failed
)
if not exist "%~dp0swiss" (
    echo Missing folder: %~dp0swiss
    goto :failed
)
set "CNT=0"
for %%F in ("%~dp0swiss\backdrop*.tpl") do set /a CNT+=1
if "%CNT%"=="0" (
    echo No backdrop*.tpl found in %~dp0swiss
    goto :failed
)
if not exist "%DRV%:\swiss" mkdir "%DRV%:\swiss"
for %%F in ("%~dp0swiss\backdrop*.tpl") do (
    if exist "%DRV%:\swiss\%%~nxF" (
        copy /Y "%DRV%:\swiss\%%~nxF" "%DRV%:\swiss\%%~nxF.bak" >nul
    )
    copy /Y "%%~fF" "%DRV%:\swiss\%%~nxF" >nul
    if errorlevel 1 (
        echo Copy failed: %%~nxF
        goto :failed
    )
    echo   copied %%~nxF
)
echo.
echo Done: %CNT% file(s).
echo Safely eject the SD card, put it back into the GameCube.
echo In Swiss: Settings -^> UI Settings (2/6) -^> Backdrop,
echo press LEFT/RIGHT to pick 1..9. 0 = default built-in backdrop.
echo.
pause
exit /b 0
:failed
echo.
pause
exit /b 1
:cancelled
echo Cancelled.
exit /b 0
"""


def numbered_names(count: int) -> list[str]:
    """按列表顺序给出 backdrop1.tpl …，固件最多认 9 个。"""
    if count < 1 or count > MAX_BACKDROPS:
        raise ValueError("逐张编号模式支持 1~%d 张图片，当前 %d 张"
                         % (MAX_BACKDROPS, count))
    return NUMBERED_NAMES[:count]


def normalize_files(source) -> dict[str, bytes]:
    """输入 bytes（旧单文件）或 {文件名: bytes}（批量编号），统一成 dict。"""
    if isinstance(source, (bytes, bytearray)):
        return {BACKDROP_NAME: bytes(source)}
    if not isinstance(source, dict):
        raise ValueError("TPL 数据格式不对：需要 bytes 或 {文件名: bytes}")
    out: dict[str, bytes] = {}
    for name, data in source.items():
        base = Path(str(name)).name
        if not NAME_RE.fullmatch(base):
            raise ValueError("非法背景图文件名：%s（只允许 backdrop.tpl / backdrop1~9.tpl）" % name)
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("%s 的内容不是字节数据" % base)
        out[base.lower()] = bytes(data)
    if not out:
        raise ValueError("没有可导出的 TPL 文件")
    return out


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rotation_hint(count: int) -> str:
    rules = {
        2: "按半年（季节）轮换", 3: "每 4 个月轮换", 4: "按季节轮换",
        6: "每 2 个月轮换", 7: "按星期轮换", 12: "按月份轮换",
        24: "按小时轮换", 30: "按日期轮换", 31: "按日期轮换",
        365: "按年内天数轮换", 366: "按年内天数轮换",
    }
    if count == 1:
        return "单张背景，固定显示"
    return rules.get(count, "每次开机随机选一张（%d 张）" % count)


def _format_bytes(n: int) -> str:
    if n >= 1048576:
        return "%.2f MB (%d 字节)" % (n / 1048576, n)
    return "%.1f KB (%d 字节)" % (n / 1024, n)


def install_notes(meta: dict) -> str:
    files = meta.get("files") or [{"name": BACKDROP_NAME, "size": meta.get("size", 0)}]
    names = ", ".join(f["name"] for f in files)
    numbered = meta.get("mode", "legacy") == "numbered"
    pick = ("\n【重要】文件拷好后还要在 Swiss 里选一次：\n"
            "  设置 → 界面设置 (2/6) → 背景图，按左右键选 1 ~ %d。\n"
            "  选中的编号即时生效，会写进 global.ini 的 BackdropIndex，下次开机保持。\n"
            "  0 = 关闭（内置默认背景）。如果当前是 0，新背景不会自己显示出来。\n"
            % len(files)) if numbered else ""
    return """Swiss 自定义背景图 · SD 卡安装说明
========================================

【一句话】把本文件夹里的 swiss 文件夹整个复制到 SD 卡根目录，
然后在 Swiss 设置里把「背景图」选成对应编号。全程不需要网卡。

----------------------------------------
一、安装步骤
----------------------------------------
1. 用读卡器把 SD 卡接到电脑，打开它的盘符（例如 G:\\）。
2. 把本文件夹中的  swiss  文件夹 复制粘贴到 SD 卡根目录。
   正确结果：G:\\swiss\\backdrop1.tpl  （以及 2、3…）
   常见错误：
     - G:\\SwissBackdrop_SD\\swiss\\...   ← 多套了一层文件夹
     - G:\\backdrop1.tpl                 ← 少了 swiss 这一层
3. SD 卡里本来就有 swiss 文件夹（Swiss 的配置目录），
   只把 backdrop*.tpl 覆盖/新增即可，别删 global.ini 等其它文件。
4. 安全弹出 SD 卡 → 插回 GameCube → 断电重启。
%s
懒人办法：双击本文件夹里的 copy_to_sd.bat，按提示输入盘符，
它会建目录、备份同名旧文件并复制好（英文提示，避免中文乱码）。

----------------------------------------
二、切换 / 恢复默认背景
----------------------------------------
切换：设置 → 界面设置 (2/6) → 背景图，左右键选 1~9，立即重载。
      选到没有对应文件的编号会自动回退内置背景，不会黑屏。
关闭：把「背景图」选成 0，或删掉 swiss\\backdrop*.tpl 再重启。
      用本工具的话，也可以点「从 SD 卡移除背景」（会逐个列出再删）。
旧名兼容：编号 1 且 backdrop1.tpl 不存在时，固件会读旧名
      swiss\\backdrop.tpl（老版本生成的单文件背景）。

----------------------------------------
三、注意事项
----------------------------------------
- 固件最多认 9 个编号，本工具逐张编号模式也只生成 1~9。
- 从 SD 卡启动就放 SD 卡；若改成 SMB / FTP 启动，要在对应设备上另放一份。
- 背景图是 SD 卡上的独立文件，不写进 IPL.dol，换图不需要重刷固件。
- 每张 TPL 整块读进内存：RGB5A3 640x480 约 600 KB，CI8 约 300 KB；
  切图时固件会释放上一张，但别放超大分辨率的图。
- 图片太亮会盖住白色标题栏和文件列表，工具里的「叠加模拟界面」可提前预判。

----------------------------------------
四、本份文件的信息
----------------------------------------
生成时间：%s
生成模式：%s
输出文件：%s
文件数量：%d 个 / 贴图总数 %d 张
合计大小：%s
纹理格式：%s    分辨率：%s    裁切：%s
逐文件 SHA-256 见「背景图信息.txt」。
""" % (pick, meta.get("time", "-"),
       "逐张编号（backdrop1~9.tpl）" if numbered else "合并单文件（backdrop.tpl，按日历轮换）",
       names, len(files), meta.get("count", len(files)),
       _format_bytes(meta.get("size", 0)), meta.get("format", "-"),
       meta.get("size_px", "-"), meta.get("fit", "-"))


def info_notes(meta: dict) -> str:
    files = meta.get("files") or [{"name": BACKDROP_NAME,
                                   "size": meta.get("size", 0),
                                   "sha": meta.get("sha", "-"), "frames": 1}]
    lines = [
        "Swiss 背景图生成记录",
        "========================================",
        "生成时间：%s" % meta.get("time", "-"),
        "生成模式：%s" % ("逐张编号" if meta.get("mode") == "numbered"
                       else "合并单文件"),
        "合计大小：%s" % _format_bytes(meta.get("size", 0)),
        "纹理格式：%s" % meta.get("format", "-"),
        "分辨率：%s" % meta.get("size_px", "-"),
        "裁切方式：%s" % meta.get("fit", "-"),
        "",
        "输出文件（文件名即设置里的编号）：",
    ]
    for f in files:
        lines.append("  swiss/%-16s %10d 字节  贴图 %d 张  sha256=%s"
                     % (f["name"], f.get("size", 0), f.get("frames", 1),
                        f.get("sha", "-")))
    lines += ["", "源图片（按列表顺序）："]
    for i, p in enumerate(meta.get("images", []) or ["(未记录)"]):
        lines.append("  %d. %s" % (i + 1, p))
    lines += [
        "",
        "校验方法（PowerShell）：",
        '  Get-FileHash .\\swiss\\backdrop1.tpl -Algorithm SHA256',
        "",
        "目标目录：<启动设备>:/swiss/",
    ]
    return "\n".join(lines) + "\n"


def make_meta(source, *, count: int | None = None, fmt: str = "-",
              size_px: str = "-", fit: str = "-", images=None,
              mode: str | None = None) -> dict:
    """source 可以是单个 TPL 的 bytes，或 {文件名: bytes}。"""
    files = normalize_files(source)
    details = [{"name": n, "size": len(d), "sha": sha(d),
                "frames": 1} for n, d in sorted(files.items())]
    total = sum(f["size"] for f in details)
    digest = hashlib.sha256()
    for n in sorted(files):
        digest.update(n.encode("ascii"))
        digest.update(files[n])
    if mode is None:
        mode = "numbered" if any(n != BACKDROP_NAME for n in files) else "legacy"
    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "size": total,
        "sha": digest.hexdigest(),
        "count": count if count is not None else sum(f["frames"] for f in details),
        "file_count": len(details),
        "files": details,
        "mode": mode,
        "format": fmt,
        "size_px": size_px,
        "fit": fit,
        "images": list(images or []),
    }


def make_package(source, package_dir, *, meta: dict | None = None,
                 make_zip: bool = False, force: bool = False) -> dict:
    """生成可整体拷进 SD 卡的文件夹；source 为 bytes 或 {文件名: bytes}。"""
    files = normalize_files(source)
    pkg = Path(package_dir).resolve()
    meta = meta or make_meta(files)

    # 防止误把一堆说明文件写进桌面 / 磁盘根目录 / 用户主目录
    if pkg == pkg.anchor or pkg == Path.home().resolve():
        raise ValueError("请选择一个单独的文件夹，不要直接用磁盘根目录或用户主目录")
    if pkg.name == SD_SUBDIR:
        raise ValueError("请选一个父文件夹，工具会自己创建 swiss 子目录")
    if pkg.exists():
        if not pkg.is_dir():
            raise ValueError("目标已存在且不是文件夹：%s" % pkg)
        if any(pkg.iterdir()) and not force:
            raise ValueError("目标文件夹不是空的：%s\n请换一个空文件夹，或勾选覆盖。" % pkg)
    pkg.mkdir(parents=True, exist_ok=True)

    swiss = pkg / SD_SUBDIR
    swiss.mkdir(exist_ok=True)
    written: dict[str, Path] = {}
    for name, data in sorted(files.items()):
        tpl = swiss / name
        tpl.write_bytes(data)
        if tpl.read_bytes() != data:
            raise OSError("写入后回读不一致：%s" % tpl)
        written[name] = tpl

    (pkg / README_NAME).write_text(install_notes(meta), encoding="utf-8")
    (pkg / INFO_NAME).write_text(info_notes(meta), encoding="utf-8")
    (pkg / BAT_NAME).write_bytes(COPY_BAT.replace("\n", "\r\n").encode("ascii"))

    first = sorted(files)[0]
    result = {
        "dir": str(pkg),
        "tpl": str(written[first]),
        "tpls": {n: str(p) for n, p in written.items()},
        "names": sorted(files),
        "size": sum(len(d) for d in files.values()),
        "sha": sha(files[first]),
        "files": [str(p) for _, p in sorted(written.items())]
                 + [str(pkg / README_NAME), str(pkg / INFO_NAME),
                    str(pkg / BAT_NAME)],
        "zip": None,
    }
    if make_zip:
        zpath = pkg.parent / (pkg.name + ".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(pkg.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(pkg).as_posix())
        result["zip"] = str(zpath)
        result["files"].append(str(zpath))
    return result


# --------------------------------------------------------------------- 本地磁盘
def normalize_drive(drive: str) -> str:
    """'g' / 'G:' / 'G:\\' / 'G:/' → 'G:\\'"""
    s = str(drive).strip().strip('"').replace("/", "\\")
    if not s:
        raise ValueError("盘符不能为空")
    letter = s[0].upper()
    if not letter.isalpha():
        raise ValueError("盘符格式不对：%s（示例：G:）" % drive)
    return letter + ":\\"


def coerce_drive(value: str) -> str:
    """同时接受 'G:' 和下拉框里的 'G:\\  可移动 · 可用 11.8 GB'。"""
    s = str(value).strip()
    if not s:
        raise ValueError("请先选择或输入 SD 卡盘符（例如 G:）")
    return normalize_drive(s.split()[0])


def drive_type(root: str) -> int:
    """Windows GetDriveTypeW；非 Windows 返回 3。2=可移动 3=固定 5=光驱。"""
    if os.name != "nt":
        return 3
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))


def list_drives(include_fixed: bool = False) -> list[dict]:
    """列出盘符；默认只给可移动磁盘，避免用户误选系统盘。"""
    out: list[dict] = []
    if os.name != "nt":
        return out
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    sys_letter = os.environ.get("SystemDrive", "C:")[:1].upper()
    for i in range(26):
        if not (mask & (1 << i)):
            continue
        root = "%c:\\" % (65 + i)
        if root[0] == sys_letter:
            continue  # 系统盘永不出现在可选列表里
        dtype = drive_type(root)
        if dtype == 2 or (include_fixed and dtype == 3):
            try:
                free = shutil.disk_usage(root).free
            except OSError:
                continue
            out.append({"root": root, "type": dtype, "removable": dtype == 2,
                        "free": free})
    out.sort(key=lambda d: (not d["removable"], d["root"]))
    return out


def _guard(drive: str, allow_system: bool = False) -> str:
    root = coerce_drive(drive)
    if not os.path.isdir(root):
        raise ValueError("盘符不存在或无法访问：%s" % root)
    dtype = drive_type(root)
    if dtype in (4, 5, 6):
        raise ValueError("%s 不是普通磁盘（光驱/网络盘/内存盘），已拒绝写入" % root)
    sys_drive = os.environ.get("SystemDrive", "C:")[:1].upper()
    if root[0] == sys_drive and not allow_system:
        raise ValueError("%s 是系统盘，已拒绝写入。请改选 SD 卡盘符。" % root)
    return root


def check_drive(drive: str, allow_system: bool = False) -> str:
    """校验并返回规范化的盘符根路径（不写任何东西）。"""
    return _guard(drive, allow_system)


def write_to_sd(source, drive: str, *, allow_system: bool = False,
                backup: bool = True) -> dict:
    """把一个或多个 TPL 写到 <盘符>:\\swiss\\，逐个回读校验。"""
    files = normalize_files(source)
    root = _guard(drive, allow_system)
    folder = Path(root) / SD_SUBDIR
    folder.mkdir(exist_ok=True)
    paths, backups = [], []
    for name, data in sorted(files.items()):
        target = folder / name
        if target.exists() and backup:
            bak = folder / (name + ".bak")
            shutil.copy2(target, bak)
            backups.append(str(bak))
        target.write_bytes(data)
        if target.read_bytes() != data:
            raise OSError("写入后回读不一致：%s" % target)
        paths.append(str(target))
    first = sorted(files)[0]
    return {
        "path": str(folder / first),
        "paths": paths,
        "names": sorted(files),
        "root": root,
        "size": sum(len(d) for d in files.values()),
        "sha": sha(files[first]),
        "replaced": bool(backups),
        "backup": backups[0] if backups else None,
        "backups": backups,
    }


def remove_from_sd(drive: str, *, allow_system: bool = False,
                   names=None) -> dict:
    """只删除 swiss/ 下枚举到的 backdrop*.tpl；不递归、不碰其它文件。"""
    root = _guard(drive, allow_system)
    folder = Path(root) / SD_SUBDIR
    wanted = list(names) if names else list(ALL_NAMES)
    for n in wanted:
        if not NAME_RE.fullmatch(Path(n).name):
            raise ValueError("拒绝删除非背景图文件：%s" % n)
    removed = []
    for n in wanted:
        target = folder / Path(n).name
        if target.is_file():
            target.unlink()
            removed.append(target.name)
    if not removed:
        msg = "SD 卡 swiss/ 下没有 backdrop*.tpl，当前本来就是内置默认背景。"
    else:
        msg = ("已删除 %d 个背景图文件：%s\n\n"
               "断电重启 Swiss 后恢复内置默认背景（也可在设置里把「背景图」选成 0）。"
               % (len(removed), "、".join(removed)))
    return {"path": str(folder), "removed": removed, "count": len(removed),
            "message": msg}


def describe_drive(d: dict) -> str:
    kind = "可移动" if d["removable"] else "固定"
    return "%s  %s · 可用 %.1f GB" % (d["root"], kind, d["free"] / 1073741824)
