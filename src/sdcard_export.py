#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SwissBackdrop 的离线 SD 卡导出后端（不依赖网卡 / 网络 / devkitPro）。

GameCube 不一定装了 BBA 网卡，因此「生成一份能直接拷进 SD 卡的文件」
是本工具的主路径，联网直传只是可选加速项。本模块提供：

    make_package(data, dir, ...)   生成 SwissBackdrop_SD/ 文件夹 + 可选 zip
    list_drives()                  列出本机可移动磁盘（Windows）
    write_to_sd(data, "G:")        直接写 <盘符>:\\swiss\\backdrop.tpl 并回读校验
    remove_from_sd("G:")           只删除这一个文件，恢复内置默认背景

固定路径（Swiss 源码 DrawLoadBackdrop 硬编码）：
    <启动设备>:/swiss/backdrop.tpl

安全约定：只创建/覆盖 swiss/backdrop.tpl 这一个文件，绝不递归删除；
覆盖前把旧文件备份为 backdrop.tpl.bak；拒绝写系统盘。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

SD_SUBDIR = "swiss"
BACKDROP_NAME = "backdrop.tpl"
PACKAGE_NAME = "SwissBackdrop_SD"
README_NAME = "【必读】安装到 SD 卡.txt"
INFO_NAME = "背景图信息.txt"
BAT_NAME = "copy_to_sd.bat"
BACKUP_NAME = "backdrop.tpl.bak"

# 纯 ASCII，避免 bat 在 GBK 代码页下乱码；文件名用中文但内容不含中文。
COPY_BAT = r"""@echo off
setlocal
echo ============================================
echo   Swiss backdrop - copy to SD card
echo ============================================
echo.
echo This will create:  ^<drive^>:\swiss\backdrop.tpl
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
if not exist "%~dp0swiss\backdrop.tpl" (
    echo Missing file: %~dp0swiss\backdrop.tpl
    goto :failed
)
if not exist "%DRV%:\swiss" mkdir "%DRV%:\swiss"
if exist "%DRV%:\swiss\backdrop.tpl" (
    copy /Y "%DRV%:\swiss\backdrop.tpl" "%DRV%:\swiss\backdrop.tpl.bak" >nul
)
copy /Y "%~dp0swiss\backdrop.tpl" "%DRV%:\swiss\backdrop.tpl" >nul
if errorlevel 1 (
    echo Copy failed.
    goto :failed
)
echo.
echo Done. Safely eject the SD card, put it back into the
echo GameCube and POWER-CYCLE the console (background is read once at boot).
echo To restore the default background delete
echo %DRV%:\swiss\backdrop.tpl and reboot.
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
    size = meta.get("size", 0)
    count = meta.get("count", 1)
    return """Swiss 自定义背景图 · SD 卡安装说明
========================================

【一句话】把本文件夹里的 swiss 文件夹整个复制到 SD 卡的根目录，
然后把卡插回 GameCube，断电重启一次。全程不需要网卡、不需要网络。

----------------------------------------
一、安装步骤
----------------------------------------
1. 用读卡器把 SD 卡接到电脑，打开它的盘符（例如 G:\\）。
2. 把本文件夹中的  swiss  文件夹 复制粘贴到 SD 卡根目录。
   正确结果：G:\\swiss\\backdrop.tpl
   常见错误：
     - G:\\SwissBackdrop_SD\\swiss\\...   ← 多套了一层文件夹
     - G:\\backdrop.tpl                  ← 少了 swiss 这一层
3. SD 卡里如果本来就有 swiss 文件夹（Swiss 的配置目录），
   只把里面的 backdrop.tpl 覆盖掉即可，别删其它文件。
4. 安全弹出 SD 卡 → 插回 GameCube → 断电重启。
   背景图只在开机时读一次，热复位 / 重新进主界面不会重读。

懒人办法：双击本文件夹里的 copy_to_sd.bat，按提示输入盘符，
它会建目录、备份旧文件并复制好（英文提示，避免中文乱码）。

----------------------------------------
二、恢复默认深蓝背景
----------------------------------------
删掉 SD 卡的 swiss\\backdrop.tpl，再断电重启一次即可。
用本工具的话，也可以点「从 SD 卡移除背景」。

----------------------------------------
三、注意事项
----------------------------------------
- 路径是固件写死的 <启动设备>:/swiss/backdrop.tpl。
  从 SD 卡启动就放 SD 卡；以后若改成 SMB / FTP 启动，要在对应设备上另放一份。
- 找不到文件或 TPL 损坏时，Swiss 会静默回退内置背景，不会黑屏或变砖。
- 背景图是 SD 卡上的独立文件，不写进 IPL.dol，换图不需要重刷固件。
- TPL 在开机时整块读进内存并常驻：RGB5A3 640x480 约 600 KB，
  CI8 约 300 KB。别放一堆超大图，图文并茂的界面文字建议压暗一点。
- 图片太亮会盖住白色标题栏和文件列表，工具里的「叠加模拟界面」可提前预判。

----------------------------------------
四、本份文件的信息
----------------------------------------
生成时间：%s
贴图数量：%d 张（%s）
文件大小：%s
SHA-256 ：%s
纹理格式：%s    分辨率：%s    裁切：%s
""" % (meta.get("time", "-"), count, rotation_hint(count), _format_bytes(size),
       meta.get("sha", "-"), meta.get("format", "-"), meta.get("size_px", "-"),
       meta.get("fit", "-"))


def info_notes(meta: dict) -> str:
    lines = [
        "Swiss 背景图生成记录",
        "========================================",
        "生成时间：%s" % meta.get("time", "-"),
        "文件：swiss/%s" % BACKDROP_NAME,
        "大小：%s" % _format_bytes(meta.get("size", 0)),
        "SHA-256：%s" % meta.get("sha", "-"),
        "纹理格式：%s" % meta.get("format", "-"),
        "分辨率：%s" % meta.get("size_px", "-"),
        "裁切方式：%s" % meta.get("fit", "-"),
        "贴图数量：%d（%s）" % (meta.get("count", 1),
                             rotation_hint(meta.get("count", 1))),
        "源图片：",
    ]
    for p in meta.get("images", []) or ["(未记录)"]:
        lines.append("  - %s" % p)
    lines += [
        "",
        "校验方法（PowerShell）：",
        '  Get-FileHash .\\swiss\\backdrop.tpl -Algorithm SHA256',
        "",
        "目标路径：<启动设备>:/swiss/backdrop.tpl",
    ]
    return "\n".join(lines) + "\n"


def make_meta(data: bytes, *, count: int = 1, fmt: str = "-", size_px: str = "-",
              fit: str = "-", images=None) -> dict:
    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "size": len(data),
        "sha": sha(data),
        "count": count,
        "format": fmt,
        "size_px": size_px,
        "fit": fit,
        "images": list(images or []),
    }


def make_package(data: bytes, package_dir, *, meta: dict | None = None,
                 make_zip: bool = False, force: bool = False) -> dict:
    """生成可整体拷进 SD 卡的文件夹，返回路径与校验信息。"""
    pkg = Path(package_dir).resolve()
    meta = meta or make_meta(data)

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
    tpl = swiss / BACKDROP_NAME
    tpl.write_bytes(data)
    if tpl.read_bytes() != data:
        raise OSError("写入后回读不一致：%s" % tpl)

    (pkg / README_NAME).write_text(install_notes(meta), encoding="utf-8")
    (pkg / INFO_NAME).write_text(info_notes(meta), encoding="utf-8")
    (pkg / BAT_NAME).write_bytes(COPY_BAT.replace("\n", "\r\n").encode("ascii"))

    result = {
        "dir": str(pkg),
        "tpl": str(tpl),
        "size": len(data),
        "sha": sha(data),
        "files": [str(tpl), str(pkg / README_NAME),
                  str(pkg / INFO_NAME), str(pkg / BAT_NAME)],
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


def write_to_sd(data: bytes, drive: str, *, allow_system: bool = False,
                backup: bool = True) -> dict:
    """把 TPL 写到 <盘符>:\\swiss\\backdrop.tpl，并回读校验 SHA-256。"""
    root = _guard(drive, allow_system)
    folder = Path(root) / SD_SUBDIR
    folder.mkdir(exist_ok=True)
    target = folder / BACKDROP_NAME
    replaced = target.exists()
    backup_path = None
    if replaced and backup:
        backup_path = folder / BACKUP_NAME
        shutil.copy2(target, backup_path)
    target.write_bytes(data)
    if target.read_bytes() != data:
        raise OSError("写入后回读不一致：%s" % target)
    return {
        "path": str(target),
        "root": root,
        "size": len(data),
        "sha": sha(data),
        "replaced": replaced,
        "backup": str(backup_path) if backup_path else None,
    }


def remove_from_sd(drive: str, *, allow_system: bool = False) -> dict:
    """只删除 <盘符>:\\swiss\\backdrop.tpl；不递归、不碰其它文件。"""
    root = _guard(drive, allow_system)
    target = Path(root) / SD_SUBDIR / BACKDROP_NAME
    if not target.exists():
        return {"path": str(target), "removed": False,
                "message": "该文件本来就不存在，Swiss 当前用的就是内置默认背景。"}
    size = target.stat().st_size
    target.unlink()
    return {"path": str(target), "removed": True, "size": size,
            "message": "已删除，断电重启 Swiss 后恢复内置深蓝背景。"}


def describe_drive(d: dict) -> str:
    kind = "可移动" if d["removable"] else "固定"
    return "%s  %s · 可用 %.1f GB" % (d["root"], kind, d["free"] / 1073741824)
