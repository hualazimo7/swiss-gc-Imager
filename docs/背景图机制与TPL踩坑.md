# Swiss 背景图机制与 TPL 格式踩坑

> 本文摘自本项目的开发记录，保留当时的分析过程与结论。
> 文中出现的工作区路径（`tools/`、`dist/`、`D:/…`）是开发时的目录，
> 在本仓库中的对应位置请以根目录 README 的目录表为准。

#### 自定义背景图（swiss/backdrop.tpl）

Swiss 原生支持换背景，不需要改代码：

- 开机时 `main.c` 调 `DrawLoadBackdrop(启动设备)`，它会去读
  **`<启动设备>:/swiss/backdrop.tpl`**（`gui/FrameBufferMagic.c:2317`）
- 读到合法 TPL 就覆盖全局 `backdropTexObj`，主界面/文件列表的背景随之替换
  （`TEX_BACKDROP` 只在 `DrawInit()` 里画一次，铺满 640×480）
- 找不到或解析失败就静默回退到内置背景，不影响启动

**多张图会按日期轮换**（`DrawLoadBackdrop` 里的 `switch(ntextures)`）：

| TPL 里贴图数 | 选取规则 |
|---|---|
| 2 / 3 / 4 / 6 / 12 | 按月份分段 |
| 7 | 按星期（周日=0） |
| 24 | 按小时 |
| 30 / 31 | 按日 |
| 365 / 366 | 按年内第几天 |
| 其他 | 每次启动随机 |

制作：

```bash
# 单张（自动裁切到 640x480，默认 RGB5A3）
python tools/make_backdrop.py my_art.png

# 四季四张，按月份轮换
python tools/make_backdrop.py spring.png summer.png autumn.png winter.png

# 体积敏感就用 CI8（640x480 约 300 KB，RGB5A3 是 600 KB）
# 工具已固定 palfmt=2（RGB5A3 调色板）；palfmt=0 会在实机上错色，见下方说明
python tools/make_backdrop.py photo.jpg --format ci8 --fit cover
```

产出 `tmp/backdrop/backdrop.tpl`，上传到 SD 的 `swiss/` 下：

```bash
python tools/upload_file.py 192.168.1.2 tmp/backdrop/backdrop.tpl backdrop.tpl "sdb:/swiss/"
```

然后重启 Swiss。注意：

- TPL 在启动时**整块读进内存并一直占用**（RGB5A3 640×480 = 600 KB，CI8 约 300 KB），
  加上 512 KB 的中文字模，MEM1 仍有余量，但别放多张超大图
- 内置背景是 **320×240 CI4** 再放大到 640×480 的；自定义图给 640×480 最清晰
- 只在**启动设备**上找这个文件（正常就是 SD 卡），换设备启动要另放一份
- `colfmt` 支持 I4/I8/IA4/IA8/RGB565/RGB5A3/RGBA8/CI4/CI8/CMPR；
  CI4/CI8 必须先转成调色板图，且**必须用 `palfmt=2`**（工具已处理）

### 实机验证（2026-11-08）

把 `tmp/backdrop/backdrop_ci8.tpl`（源图 `test_bg.png` 其实是**深蓝紫**）上传到
`sdb:/swiss/backdrop.tpl`，wiiload 重启后抓 `/screen.bin`：背景被整屏替换成亮黄，
平均亮度 **70.5 → 203.6**，文字仍可读 —— **自定义背景通路确实生效**。
当时把亮黄误当成测试图本来的颜色；21:45 复测证明那是 CI8 调色板错色（见下节）。

过程中发现一个上游资源泄漏：`TPL_OpenTPLFromHandle()` 成功分支没有关闭 `FILE*`，
FatFs 一直把这个文件记为「已打开」，于是 `f_unlink` / `f_rename` 返回
`FR_LOCKED(16)`，`/upload` 覆盖会卡住 httpd —— 背景图一旦加载就**再也无法远程更换或删除**。
已在 `cube/swiss/source/gui/FrameBufferMagic.c` 的 `DrawLoadBackdrop()` 成功分支补上
`fclose(backdropTPL.tpl_file)`（只关流，保留 `texdesc`，GX 纹理数据不受影响），
重新编译并部署后实测：加载过背景的状态下依然可以删除，且能反复上传/删除。

附一张低饱和深灰磨砂示例：`tmp/backdrop/example_dark.png` /
`backdrop_example.tpl`（CI8 + `palfmt=2`，307,808 B），21:45 曾实测生效。
**22:00 起当前生效的是用户提供的暗色插画**（见下节）；想恢复默认直接删掉
`sdb:/swiss/backdrop.tpl` 再重启。

#### 深灰示例背景：设置与 CI8 错色修复（21:45）

1. 上传 `backdrop_example.tpl`（当时是 `palfmt=0`），`/get` 回读 SHA-256 一致；
   wiiload 推送 19:02 raw DOL 重启（11.7 s 后 httpd 恢复）→ 抓屏**仍是亮黄，亮度 203.01**，
   与深灰源图（亮度 34.5）完全不符。
2. 定位：`gxtexconv` 默认 `palfmt=0` 生成 **IA8 TLUT**，而 `FrameBufferMagic.c:500`
   的 `TEX_BACKDROP` 分支遇到 IA8 会走内置 CI4 背景专用的 TEV 设置，彩色图被渲成
   残留的亮黄 —— 这解释了为什么两张不同源图都显示同一个亮黄。
3. 换 `palfmt=2`（RGB5A3 TLUT，TPL lutdesc 的 fmt 字段 `0 → 2`）重传、重启、抓屏：
   **亮度 61.08，整屏 RGB ≈ (57, 62, 68)，深灰磨砂背景正确显示**；中文「插槽 B /
   总计 / 可用 / 已用」、标题栏、封面、温度与日期同行都清晰可读。
   RGB5A3（无调色板，614,464 B）作为对照同样通过，亮度 61.07，观感一致。
4. 顺带复验文件锁修复：Swiss **已加载背景的状态下**仍能 `/upload` 覆盖
   （307,808 → 614,464 → 307,808 B），每次 `/get` 回读 SHA-256 一致。

截图：`tmp/backdrop_verify/screen_ci8_palfmt2.png`（最终生效）、
`screen_rgb5a3.png`（RGB5A3 对照）、`screen_ci8_wrongcolor.png`（错色对照）。
`tools/make_backdrop.py` 已把 CI4/CI8 的 `palfmt` 固定为 2。

#### 用户插画背景（22:00，当前生效）

用户给出一张 1920×1177 暗色人物插画，用


## 16. 深灰自定义背景实机设置 + CI8 调色板错色修复（2026-11-08 21:42-21:50）

用户要求把 `example_dark.png` 的低饱和深灰磨砂背景实际装上并抓屏验证。

### 16.1 操作与结果

| 步骤 | 结果 |
|---|---|
| `/ls sdb:/swiss/` 预检 | 无 `backdrop.tpl`（默认深蓝背景，亮度 70.5） |
| 上传 `backdrop_example.tpl` 307,808 B | `ok 307808/307808`，`/get` 回读 SHA-256 `62191fbd…` 一致 |
| wiiload 推送 19:02 raw DOL（3,245,536 B） | 11.7 s 后 httpd 恢复，`/state` 正常 |
| 抓 `/screen.bin` | **亮黄，亮度 203.01，RGB (221, 220.5, 64.7)** ← 不是深灰 |
| 改用 RGB5A3（614,464 B）重传 + 重启 | **深灰，亮度 61.07，RGB (56.7, 61.6, 68.3)**，UI 清晰 |
| 改用 CI8 `palfmt=2`（307,808 B）重传 + 重启 | **深灰，亮度 61.08，RGB (57, 62, 68)**，最终采用 |

最终状态：`sdb:/swiss/backdrop.tpl` = CI8 / RGB5A3 调色板，307,808 B，
SHA-256 `5f349ddb…`；主界面中文「插槽 B / 总计 / 可用 / 已用」、标题栏、
封面、顶部 40°C 与日期同行均清晰可读。

### 16.2 更正 15.3 的误判：CI8 的 IA8 调色板会错色

`test_bg.png` 源图其实是**深蓝紫**（平均 RGB ≈ 32, 36, 74），`example_dark.png`
是**深灰**（30, 36, 43），但两者用 `gxtexconv colfmt=9 palfmt=0` 生成的 TPL
在实机上都渲染成同一片亮黄 (254, 255, 37)。15.3 把亮黄误当成了测试图本来的颜色。

根因：`palfmt=0` 输出 **IA8 TLUT**，而 `FrameBufferMagic.c:500` 的 `TEX_BACKDROP`
分支对 `GX_TL_IA8` 走内置 CI4 背景专用的 TEV 设置（`GX_SetTevColorIn` + 蓝色常量），
彩色图因此被错误着色。改用 `palfmt=2`（RGB5A3 TLUT）后，TPL `lutdesc` 的 fmt
字段由 `0` 变 `2`，Swiss 走正常分支，颜色正确，且 CI8 只占 300 KB（RGB5A3 是 600 KB）。

`tools/make_backdrop.py` 已把 CI4/CI8 的 `palfmt` 从 0 固定为 2，并重新生成
`tmp/backdrop/backdrop_example.tpl`（SHA-256 与实机生效文件一致）；README
背景图章节同步更正。

### 16.3 顺带复验文件锁修复

19:02 的 `fclose(backdropTPL.tpl_file)` 修复在本次反复生效：Swiss 已经加载
`backdrop.tpl` 的状态下，仍能连续 3 次 `/upload` 覆盖
（307,808 → 614,464 → 307,808 B），没有 `FR_LOCKED(16)`，httpd 无卡死。

截图：`tmp/backdrop_verify/screen_ci8_wrongcolor.png`、
`screen_rgb5a3.png`、`screen_ci8_palfmt2.png`（最终生效版）。

---
