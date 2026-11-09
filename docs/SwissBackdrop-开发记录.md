# SwissBackdrop 开发记录

> 本文摘自本项目的开发记录，保留当时的分析过程与结论。
> 文中出现的工作区路径（`tools/`、`dist/`、`D:/…`）是开发时的目录，
> 在本仓库中的对应位置请以根目录 README 的目录表为准。

## 19. SwissBackdrop：专用背景图 PC 工具（2026-11-08 22:45）

用户要求「做一个专门处理背景图的 pc 端 exe 程序」。成品 `dist/SwissBackdrop.exe`
（20.35 MiB，PyInstaller onefile / GUI 子系统，内嵌 Python 3.14 + Pillow + tkinter，
专属图标与中文版本资源，双击无黑窗）。

**核心：去掉 devkitPro 依赖**。新增 `tools/tplcodec.py`，纯 Python 实现 GX 纹理编码：
RGB5A3 / RGB565 / CI8 的 4×4、8×4 分块排布、TPL 文件头/偏移表、多贴图 TPL、
解码回预览、图片 fit 与亮度/对比度/饱和度/模糊/暗角调节。用坐标编码测试图反推
分块规则后，与 `gxtexconv` 产物逐字节比对：64×64 探针的三种格式、单张/多张 TPL、
以及 640×480 真实背景全部 **EXACT MATCH**；CI8 索引一致，仅未使用的调色板填充项
不同（不影响显示）。CI4/CI8 固定 `palfmt=2`，从工具层面杜绝 16 节的 IA8 错色。

`tools/swiss_backdrop.py` 是工作台：三栏布局，图片列表支持 2–366 张按日历轮换，
实时预览可叠加模拟 Swiss 界面并给出亮度/可读性建议，右栏输出参数与画面调节，
底部直连实机（上传并回读 SHA-256 校验、删除恢复默认、抓 `/screen.bin` 存 PNG）。
浅色 / 低饱和磨砂深色双主题，`~/.swissbackdrop.json` 保存配置；同时提供
`--cli` / `--selftest` / `--version` / `--log` 与完整 CLI 子命令。

打包链：`tools/make_backdrop_icon.py` → `tools/assets/swissbackdrop.ico`、
`tools/build_backdrop_exe.py`、`tools/version_backdrop.txt`、
`tools/启动 SwissBackdrop.bat`。沿用 SwissFTP 的 frozen I/O 处理
（`sys.stdout` 可能为 None、控制台附加、`--log`、显式 hidden-import）。

**验证**

| 项目 | 结果 |
|---|---|
| `--selftest`（EXE 内） | 7/7 PASS：三种格式往返、7 张轮换、中文路径、调节生效、与 gxtexconv 字节一致（sha `9854eaa2…`） |
| EXE `--cli --build` | 614,464 B，与 `示例背景.tpl` SHA-256 完全一致 |
| EXE `--upload` | 614,464 B 上传成功，`/get` 回读 SHA-256 一致（已加载背景下覆盖，无 FR_LOCKED） |
| EXE `--state` / `--screen` | `SD 卡 - 插槽 B`、65 项、`backdrop.tpl 存在 614464 字节`；抓屏 640×480 亮度 67.49 |
| GUI 浅色 / 深色 | 窗口实际渲染逐项复核，三栏、预览叠加、底部设备区与日志完整，无黑窗 |

过程中修了两个界面问题：① pack 分配顺序把底部设备区/日志压成 0 高度（改为主区
`grid` + 底部固定 `pack`，窗口改为 1240×850）；② clam 主题给 `readonly` 状态
映射了固定浅色 `fieldbackground`，深色主题下拉框变「白底浅字」，改为显式
`style.map` 覆盖并给弹出列表配色，滑块也统一为语义色。

README 背景章节新增「SwissBackdrop」小节。截图：
`tmp/backdrop/gui_window_light_final.png`、`gui_window_dark_fixed.png`、
`tmp/backdrop/final_screen.png`（EXE 抓的实机画面）。

---

## 20. SwissBackdrop 1.1：离线 SD 卡导出（2026-11-08 23:10）

用户指出「不是每个用户都有网卡，要能生成 SD 卡文件让用户自行拷贝到 SD 卡」。
因此把**离线路径改成主路径**，联网直传降为可选加速项。版本号 1.0 → 1.1。

新增 `tools/sdcard_export.py`（纯标准库，不依赖网卡 / 网络 / devkitPro）：

- `make_package()` 生成 `SwissBackdrop_SD/`，含
  `swiss/backdrop.tpl`、`【必读】安装到 SD 卡.txt`（正确与错误路径示例、
  恢复默认方法）、`背景图信息.txt`（时间/参数/源图/SHA-256）、
  `copy_to_sd.bat`（纯 ASCII 内容，双击输入盘符即自动建目录 + 备份 + 复制）；
  可同时产出 zip 方便转发。
- `list_drives()` / `check_drive()` / `write_to_sd()` / `remove_from_sd()`：
  Windows 盘符枚举（自动排除系统盘）、写 `<盘符>:\swiss\backdrop.tpl`
  并回读 SHA-256、覆盖前备份 `backdrop.tpl.bak`、只删除这一个文件恢复默认。
  **安全约束**：不递归删除、拒绝光驱/网络盘/系统盘、非空导出目录需 `--force`。

GUI：右栏「① 生成 SD 卡文件…」升为主按钮 + zip 勾选 +「② 只导出 backdrop.tpl…」；
底部改为两行——`① 离线 · 直接写 SD 卡`（盘符下拉/刷新/写入/移除）与
`② 可选 · 联网直传（需 GameCube 网卡）`。标题、日志、使用说明全部改为离线优先。
CLI 新增 `--sd-package/--sd-tpl/--zip/--force/--write-drive/--remove-drive/--list-drives`。
`build_backdrop_exe.py` 补 `sdcard_export` 等 hidden-import 与 1.1 版本资源。

**验证**

| 项目 | 结果 |
|---|---|
| 源码 / EXE `--selftest` | 9/9 PASS（新增离线包目录/zip/覆盖保护、盘符解析与安全校验） |
| CLI 三种入口（图片→包、现成 TPL→包、EXE→包） | 614,464 B，SHA `9854eaa2…`，与实机生效 TPL 完全一致 |
| `subst` 虚拟盘符 `Q:` 实测 | 写入 → 回读一致 → 二次覆盖自动备份 `.bak` → 移除 → 重复移除幂等 → `C:` 被拒绝 |
| 包内 `copy_to_sd.bat` | 对 `Q:` 实测复制成功，哈希一致 |
| GUI 三个离线按钮（无交互触发真实处理函数） | 导出包/zip、写卡、移除全部通过，日志与提示正确 |
| 浅色 / 深色窗口 | `tmp/backdrop/v11_final_light.png`、`v11_final_dark.png`，控件完整无裁切 |

布局上又踩了一个 pack 的坑：右栏新增三个导出控件后高度不够，最后三个按钮被压成
1 像素。把 9 个滑块从「标签一行 + 滑块一行」改成「标签 | 滑块 | 数值」单行
（每项省 16 px）、格式提示缩为单行、收紧分隔间距，窗口定在 1240×900
（1080p 屏幕也放得下），复验所有控件高度正常。

README 背景章节改写为离线优先并给出目录树与 CLI 示例；随工具附一份现成样例包
`tmp/final_sd/` / `tmp/final_sd.zip`（内容就是当前实机生效的插画背景）。
实机状态未改动：`IPL.dol` 仍是 19:02 版，`sdb:/swiss/backdrop.tpl` 仍是插画。

---
