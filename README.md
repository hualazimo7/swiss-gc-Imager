# SwissBackdrop（swiss-gc-Imager）

> ⚠️ **禁止商业使用 / NON-COMMERCIAL USE ONLY**：本仓库的原创内容仅限非商业用途，禁止出售、预装到售卖的硬件/存储卡、付费代刷、广告变现等。详见 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md)。
> 本仓库不含上游 GPL 源码，整个工具（含 EXE）适用该条款。

给 [Swiss](https://github.com/emukidid/swiss-gc) 制作**自定义背景图**的 Windows 工具，当前版本 **v1.2**。

核心目标：**不需要网卡也能用**。工具把图片转成 GameCube 的 TPL 纹理，直接生成可拷贝到 SD 卡的文件包；有宽带网卡的用户也可以一键批量上传到实机并抓屏验证。

配合 [swiss-gc-CN](https://github.com/hualazimo7/swiss-gc-CN) 汉化固件使用（该固件支持在设置里切换 1~9 号背景图）。

## 直接使用 EXE

下载 [`dist/SwissBackdrop.exe`](dist/SwissBackdrop.exe)（20.38 MiB，64 位 Windows 10/11），双击即可，**无需安装 Python**。也可以双击 `src/启动 SwissBackdrop.bat`。

TPL 编码由纯 Python 实现（`src/tplcodec.py`），**不依赖 devkitPro / gxtexconv**。

## v1.2：多张图片批量生成 backdrop1.tpl、backdrop2.tpl……

汉化固件在「**设置 → 界面设置 (2/6) → 背景图**」里用左右键选 **0~9**：

| 选择 | 固件读取的文件 |
|---|---|
| `0` | 关闭，使用内置默认背景 |
| `1` ~ `9` | `<启动设备>:/swiss/backdropN.tpl` |

因此工具默认改为「**逐张编号**」：图片列表的顺序就是编号，每一张图单独编码成一个 TPL。

```text
列表第 1 张  →  swiss/backdrop1.tpl   →  设置里选 1
列表第 2 张  →  swiss/backdrop2.tpl   →  设置里选 2
列表第 3 张  →  swiss/backdrop3.tpl   →  设置里选 3
```

- 「添加 / 移除 / ↑ 上移 / ↓ 下移」调整顺序，左侧列表直接显示编号对应关系
- 所有导出方式都会自动排好序号：SD 卡文件包、只导出 TPL 文件、直写 SD 卡盘符、联网批量直传
- 固件最多认 9 个编号，超过 9 张会明确报错；想放更多图可切回「合并为 backdrop.tpl（旧版轮换）」，一个 TPL 内放多张贴图由固件按日历轮换
- 选中编号即时重载贴图，并写入 `global.ini` 的 `BackdropIndex`；下次开机保持
- **编号 1 且 `backdrop1.tpl` 不存在时**，固件回退旧名 `swiss/backdrop.tpl`，老版本生成的单文件背景仍可用

> 注意：文件拷进 SD 卡之后，还要在设置里把「背景图」从 `0` 选到对应编号才会显示；光拷文件不会自动换背景。

## 功能

| 分类 | 功能 |
|---|---|
| 图片处理 | 任意 JPG/PNG/WEBP → 640×480 TPL；`cover` / `contain` / `stretch` 裁切；亮度、对比度、饱和度、模糊、暗角、水平/垂直位置 |
| 编码格式 | `RGB5A3`（默认，画质最好）、`RGB565`、`CI8`（约一半体积） |
| **批量编号** | 1~9 张图按列表顺序生成 `backdrop1.tpl` ~ `backdrop9.tpl`；设置里左右键即时切换 |
| 旧版多图轮换 | 可切换「合并为 backdrop.tpl」：2/3/4/6/12 张按月份、7 张按星期、24 张按小时、30/31 张按日等 |
| 预览 | 模拟 Swiss 主界面叠加，实时看文字可读性；浅色 / 低饱和深色主题 |
| **离线导出（一等公民）** | 生成 `swiss/backdropN.tpl` + 中文安装说明 + 背景图信息 + `copy_to_sd.bat`；可同时打包 zip；可直接写入指定盘符；可一键从 SD 卡移除 |
| 网络功能（可选） | 批量上传所有编号 TPL 到实机、逐个回读校验、删除背景、抓屏、查询状态 |
| CLI | 全套功能都有命令行开关，便于脚本化 |

## 没有网卡？走这条路

1. 打开 EXE → 添加 1~9 张图片 → 调好裁切/色调 → 点「**① 生成 SD 卡文件**」
2. 勾选「同时打包成 zip」（可选）
3. 把生成的 `SwissBackdrop_SD` 文件夹里的 `swiss` 目录整个合并到 SD 卡根目录，最终路径：

```text
SD:\swiss\backdrop1.tpl
SD:\swiss\backdrop2.tpl
SD:\swiss\backdrop3.tpl
```

4. 安全弹出 SD 卡 → 插回 GameCube → 断电重启
5. 设置 → 界面设置 (2/6) → 背景图，左右键选 1~N 即时切换

也可以双击包里的 `copy_to_sd.bat` 自动拷贝（会备份同名旧文件为 `.bak`），或在工具里选盘符点「写入 SD 卡」。「从 SD 卡移除背景」只删 `swiss/` 下枚举出的 `backdrop.tpl` 与 `backdrop1~9.tpl`，不递归、不碰 `global.ini`，并拒绝系统盘、光驱、网络盘。

## 命令行

```text
SwissBackdrop.exe --version
SwissBackdrop.exe --selftest                    # 编码/解码/批量编号/离线包自检
SwissBackdrop.exe --list-drives                # 列出可写盘符

# 3 张图 → backdrop1.tpl / backdrop2.tpl / backdrop3.tpl
SwissBackdrop.exe --cli --build --images a.jpg b.png c.webp --out-dir D:\out

# 直接生成离线 SD 卡包（可勾 zip）+ 写入盘符
SwissBackdrop.exe --cli --build --images a.jpg b.png --sd-package D:\out\SD --zip
SwissBackdrop.exe --cli --sd-tpl backdrop2.tpl --sd-package D:\out\SD
SwissBackdrop.exe --cli --sd-package D:\out\SD --write-drive E:
SwissBackdrop.exe --cli --remove-drive E:

# 旧模式：合并成单个 backdrop.tpl
SwissBackdrop.exe --cli --build --images a.jpg b.png --mode merged --out bg.tpl

# 有网卡时：批量上传目录里的全部 backdrop*.tpl
SwissBackdrop.exe --cli --host 192.168.1.2 --upload-dir D:\out
SwissBackdrop.exe --cli --host 192.168.1.2 --upload backdrop2.tpl
SwissBackdrop.exe --cli --host 192.168.1.2 --screen shot.png
SwissBackdrop.exe --cli --host 192.168.1.2 --remove
SwissBackdrop.exe --cli --host 192.168.1.2 --state
```

其它可用开关：`--mode numbered|merged`、`--size WxH`、`--brightness`、`--contrast`、`--saturation`、`--blur`、`--vignette`、`--format rgb5a3|rgb565|ci8`、`--fit cover|contain|stretch`、`--force`、`--log 文件.log`。

## 目录

```text
dist/SwissBackdrop.exe        成品，免装 Python
src/swiss_backdrop.py         GUI + CLI 主程序
src/tplcodec.py               纯 Python TPL 编解码（RGB5A3 / RGB565 / CI8）
src/sdcard_export.py          多编号离线 SD 卡包生成与安全写盘
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
3. **背景文件锁 / 贴图内存**：上游 `TPL_OpenTPLFromHandle()` 成功分支没有关闭 `FILE*`，导致背景加载后 SD 卡上的 TPL 被锁死（`FR_LOCKED(16)`）；汉化固件已补 `fclose()`。切换编号时还必须先 `TPL_CloseTPLFile()` 释放上一张贴图，否则每切一次漏 300~600 KB，固件也已修复。

另外：每张 TPL 整块读进内存（RGB5A3 640×480 ≈ 600 KB，CI8 ≈ 300 KB），别放超大图；内置背景是 320×240 CI4 放大的，所以 640×480 最清晰。详见 [`docs/背景图机制与TPL踩坑.md`](docs/背景图机制与TPL踩坑.md)。

## 校验

`SHA256SUMS.txt` 给出 EXE 与示例 TPL 的 SHA-256。v1.2 自检 **11/11 通过**，覆盖：三种格式编解码往返、批量编号与 9 张上限、合并模式、中文路径、gxtexconv 字节比对、多编号离线包（目录/zip/说明/bat/旧接口/覆盖保护）、文件名白名单防越界、盘符安全校验。

## 许可与致谢

> ⚠️ 本仓库**全部原创内容禁止商业使用**。完整条款见 [`LICENSE`](LICENSE)，
> 范围界定与商用示例见 [`NOTICE.md`](NOTICE.md)。

- **本工具**（`src/`、`dist/SwissBackdrop.exe`、`docs/`、`examples/`）：《非商业使用许可 v1.0》，**禁止商用**
- **上游 Swiss**：[emukidid/swiss-gc](https://github.com/emukidid/swiss-gc)，GPL-2.0 全文见 [`LICENSE-GPL-2.0.txt`](LICENSE-GPL-2.0.txt)；本工具仅通过其 httpd 接口通信，未复制其源码
- TPL 编码实现参考了 devkitPro 的 `gxtexconv` 产物并做过逐字节比对
- 界面依赖 [Pillow](https://python-pillow.org/)，打包使用 [PyInstaller](https://pyinstaller.org/)
- 配套：[swiss-gc-CN](https://github.com/hualazimo7/swiss-gc-CN)（汉化固件）、[swiss-gc-ftp](https://github.com/hualazimo7/swiss-gc-ftp)（文件传输）
