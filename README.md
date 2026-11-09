# SwissBackdrop（swiss-gc-Imager）

给 [Swiss](https://github.com/emukidid/swiss-gc) 制作**自定义背景图**的 Windows 工具，当前版本 **v1.1**。

核心目标：**不需要网卡也能用**。工具把图片转成 GameCube 的 TPL 纹理，直接生成可拷贝到 SD 卡的 `swiss/backdrop.tpl` 文件包；有宽带网卡的用户也可以一键上传到实机并抓屏验证。

配合 [swiss-gc-CN](https://github.com/hualazimo7/swiss-gc-CN) 汉化固件使用。

## 直接使用 EXE

下载 [`dist/SwissBackdrop.exe`](dist/SwissBackdrop.exe)（20.37 MiB，64 位 Windows 10/11），双击即可，**无需安装 Python**。也可以双击 `src/启动 SwissBackdrop.bat`。

TPL 编码由纯 Python 实现（`src/tplcodec.py`），**不依赖 devkitPro / gxtexconv**。

## 功能

| 分类 | 功能 |
|---|---|
| 图片处理 | 任意 JPG/PNG → 640×480 TPL；`cover` / `contain` / `stretch` 裁切；亮度、对比度、饱和度、模糊、暗角；多图列表 |
| 编码格式 | `RGB5A3`（默认，画质最好）、`RGB565`、`CI8`（约一半体积） |
| 多图轮换 | 2/3/4/6/12 张按月份、7 张按星期、24 张按小时、30/31 张按日、365/366 张按年内天数，其它数量每次启动随机 |
| 预览 | 模拟 Swiss 主界面叠加，实时看文字可读性；浅色 / 低饱和深色主题 |
| **离线导出（一等公民）** | 生成 `swiss/backdrop.tpl` + 中文安装说明 + `copy_to_sd.bat`；可同时打包 zip；可直接写入指定盘符；可一键从 SD 卡移除 |
| 网络功能（可选） | 生成/上传 TPL 到实机、回读 SHA-256、删除背景、抓屏、查询状态 |
| CLI | 全套功能都有命令行开关，便于脚本化 |

## 没有网卡？走这条路

1. 打开 EXE → 选图片 → 调好裁切/色调 → 点「**① 生成 SD 卡文件**」
2. 勾选「同时打包成 zip」（可选）
3. 把生成的 `SwissBackdrop_SD` 文件夹里的 `swiss` 目录整个合并到 SD 卡根目录，最终路径：

```
SD:\swiss\backdrop.tpl
```

也可以双击包里的 `copy_to_sd.bat` 自动拷贝，或在工具里选盘符点「写入 SD 卡」。

离线包只改这一个文件；已存在时会先备份成 `backdrop.tpl.bak`，写入后回读 SHA-256 校验。「从 SD 卡移除背景」只删 `swiss/backdrop.tpl`，并拒绝系统盘、光驱、网络盘。

装好后开机（或重启 Swiss）即可生效；删除该文件并重启就回到 Swiss 默认背景。

## 命令行

```text
SwissBackdrop.exe --version
SwissBackdrop.exe --selftest                    # 编码/解码/离线包自检
SwissBackdrop.exe --list-drives                # 列出可写盘符

# 由图片生成离线 SD 卡包
SwissBackdrop.exe --cli --images art.jpg --sd-package D:\out\SD --zip --format rgb5a3 --fit cover

# 用现成 TPL 生成离线包
SwissBackdrop.exe --cli --sd-tpl bg.tpl --sd-package D:\out\SD

# 写入 / 移除
SwissBackdrop.exe --cli --sd-package D:\out\SD --write-drive E:
SwissBackdrop.exe --cli --remove-drive E:

# 有网卡时：生成、上传、回读、抓屏
SwissBackdrop.exe --cli --host 192.168.1.2 --build --images art.jpg --out bg.tpl
SwissBackdrop.exe --cli --host 192.168.1.2 --upload bg.tpl
SwissBackdrop.exe --cli --host 192.168.1.2 --screen shot.png
SwissBackdrop.exe --cli --host 192.168.1.2 --remove
SwissBackdrop.exe --cli --host 192.168.1.2 --state
```

其它可用开关：`--size WxH`、`--brightness`、`--contrast`、`--saturation`、`--blur`、`--vignette`、`--format rgb5a3|rgb565|ci8`、`--fit cover|contain|stretch`、`--force`、`--log 文件.log`。

## 目录

```
dist/SwissBackdrop.exe        成品，免装 Python
src/swiss_backdrop.py         GUI + CLI 主程序
src/tplcodec.py               纯 Python TPL 编解码（RGB5A3 / RGB565 / CI8）
src/sdcard_export.py          离线 SD 卡包生成与安全写盘
src/swiss_client.py           Swiss httpd 协议层（纯标准库）
src/grab_screen.py            实机抓屏
src/make_backdrop.py          基于 gxtexconv 的参考实现（可选，需 devkitPro）
src/build_backdrop_exe.py     重新打包 EXE
src/make_backdrop_icon.py     生成图标
src/SwissBackdrop.spec        PyInstaller 配置
src/assets/                   图标与预览
examples/backdrop_example.tpl 深灰磨砂示例背景（CI8 + palfmt=2）
docs/                         背景图机制、TPL 格式踩坑、开发记录
SHA256SUMS.txt                二进制产物校验值
```

## 从源码运行 / 重新打包

```bash
pip install -r requirements.txt
py -3 src/swiss_backdrop.py                 # GUI
py -3 src/swiss_backdrop.py --selftest     # 自检
py -3 src/build_backdrop_exe.py            # 重新生成 dist/SwissBackdrop.exe
```

打包脚本会把 `dist/SwissBackdrop.exe` 输出到仓库根的 `dist/`，并内嵌中文版本资源与图标。注意 EXE 是打包那一刻的源码快照，改过 `src/*.py` 后必须重新打包。

## TPL 格式的三个关键坑

1. **CI8 的 `palfmt` 必须是 `2`**。`gxtexconv` 默认 `palfmt=0` 生成 IA8 调色板，而 Swiss 的 `TEX_BACKDROP` 分支会套用内置 CI4 背景的 TEV 设置，彩色图被渲成**亮黄**（实测亮度 61 → 203）。工具已把 CI4/CI8 固定为 `palfmt=2`（RGB5A3 TLUT）。不确定时用默认的 RGB5A3。
2. **GX tiling**：RGB5A3 / RGB565 按 4×4 块，CI8 按 8×4 块重排，不能按线性像素写。
3. **背景文件锁**：上游 `TPL_OpenTPLFromHandle()` 成功分支没有关闭 `FILE*`，导致背景加载后 SD 卡上的 `backdrop.tpl` 被锁死，无法远程覆盖或删除（`FR_LOCKED(16)`）。汉化固件已补 `fclose()`，本工具配合该固件可反复上传/删除。

另外：TPL 在启动时整块读进内存并常驻（RGB5A3 640×480 ≈ 600 KB，CI8 ≈ 300 KB），别放超大图；内置背景是 320×240 CI4 放大的，所以 640×480 最清晰。详见 [`docs/背景图机制与TPL踩坑.md`](docs/背景图机制与TPL踩坑.md)。

## 校验

`SHA256SUMS.txt` 给出 EXE 与示例 TPL 的 SHA-256。v1.1 自检 **9/9 通过**，覆盖：图片 → 包、现成 TPL → 包、EXE → 包三条链路，以及 `subst` 虚拟盘上的写入/回读/二次备份/删除/重复删除幂等/拒绝系统盘。

## 许可与致谢

- 上游 Swiss：[emukidid/swiss-gc](https://github.com/emukidid/swiss-gc)，GPL-2.0，详见 [`LICENSE`](LICENSE)
- 本工具以 GPL-2.0 发布；TPL 编码实现参考了 devkitPro 的 `gxtexconv` 产物并做过逐字节比对
- 界面依赖 [Pillow](https://python-pillow.org/)，打包使用 [PyInstaller](https://pyinstaller.org/)
- 配套：[swiss-gc-CN](https://github.com/hualazimo7/swiss-gc-CN)（汉化固件）、[swiss-gc-ftp](https://github.com/hualazimo7/swiss-gc-ftp)（文件传输）
