# 更新记录

## 发布规则（2026-11-10 起）

- 本库与 `swiss-gc-CN` 一样采用**不可变发布**：已发布的 tag / 附件 / Release 说明一律冻结，
  每次改动发新的 `vX.Y`，旧版本永久保留；禁止 `gh release upload --clobber`、
  `delete-asset`、改写已发布说明、强推 tag
- 完整规则见 [swiss-gc-CN 的发布规则](https://github.com/hualazimo7/swiss-gc-CN/blob/main/docs/RELEASE_POLICY.md)
- 现有 Release：`v1.2`（Latest）、`v1.1`（历史版，仍可下载）

## v1.2（2026-11-09）— 多图批量生成 backdrop1.tpl、backdrop2.tpl……

汉化固件新增「设置 → 界面设置 (2/6) → 背景图」0~9 即时切换，工具同步改造：

- **默认模式改为「逐张编号」**：图片列表顺序即编号，一张图编码成一个独立的单贴图 TPL，自动生成 `swiss/backdrop1.tpl` ~ `backdrop9.tpl`（最多 9 个，超出明确报错）
- 列表项直接显示 `1 → backdrop1.tpl`；上移 / 下移即调整编号；新增「生成方式」下拉框，可切回旧版「合并为 backdrop.tpl」（多贴图按日历轮换）
- 四条导出链路全部支持批量编号：SD 卡文件包、只导出 TPL 文件（选文件夹）、直写 SD 卡盘符、联网批量直传（一次 ping/state，逐个上传 + 回读校验）
- 安装说明 / 背景图信息 / `copy_to_sd.bat` 同步重写：`for` 循环复制全部 `backdrop*.tpl`、逐个备份 `.bak`，并写明「拷完还要在设置里选 1~N，0 = 关闭」、编号 1 回退旧名
- 「写入 SD 卡」「从 SD 卡移除背景」「恢复默认背景（远端）」改为枚举操作 `backdrop.tpl` + `backdrop1~9.tpl`，不递归、不动 `global.ini`；文件名白名单校验防越界写入
- CLI 新增 `--mode numbered|merged`、`--out-dir`、`--upload-dir`；`--build` / `--sd-package` / `--write-drive` 支持多图
- 自检从 9 项扩到 11 项（11/11 通过）：批量编号顺序与内容、9 张上限、合并模式、多编号离线包与 zip、旧 `bytes` 接口兼容、非法文件名拒绝
- 版本号与 Windows 版本资源升到 1.2.0.0；`dist/SwissBackdrop.exe` 重新打包

> 兼容：旧版生成的 `swiss/backdrop.tpl` 在「编号 1 且 backdrop1.tpl 缺失」时仍会被固件读取；工具保留合并模式，老用法不受影响。

## 2026-11-09 — 增加禁止商用许可（非商业使用许可 v1.0）

- 仓库主许可改为《非商业使用许可 v1.0》：本工具全部源码、EXE、图标与文档仅限非商业用途，禁止出售、预装到售卖的硬件/存储卡、付费代刷、广告变现等商业使用
- 新增 [`LICENSE`](LICENSE) 正文与 [`NOTICE.md`](NOTICE.md)（范围界定、商用示例、授权申请方式）；原 GPL-2.0 全文原样留存为 `LICENSE-GPL-2.0.txt`
- 依 GPL-2.0 第 6 条，不对上游 Swiss / GNU Unifont 的 GPL 材料追加任何限制，该部分权利（含商业使用）不受影响
- 已按 GPL-2.0 分发的历史版本与既有 Release 附件，其授权不可撤销；本次变更对当前及后续版本生效
- README 顶部与许可章节已同步标注禁止商用

## v1.1（2026-11-08）— 离线 SD 卡导出成为一等公民

用户反馈「不是每个用户都有网卡」，因此把**不依赖网络**的路径做成主流程：

- 新增 `src/sdcard_export.py`：生成 `swiss/backdrop.tpl` + 中文安装说明 + 背景图信息 + `copy_to_sd.bat`，可选同时打 zip
- GUI 新增「① 生成 SD 卡文件…」「同时打包成 zip」「② 只导出 backdrop.tpl…」「写入 SD 卡」「从 SD 卡移除背景」
- CLI 新增 `--sd-package` / `--sd-tpl` / `--zip` / `--force` / `--write-drive` / `--remove-drive` / `--list-drives`
- 写入安全：只改 `swiss/backdrop.tpl`，覆盖前备份为 `backdrop.tpl.bak`，写入后回读 SHA-256；拒绝系统盘 / 光驱 / 网络盘
- 用 `subst` 虚拟盘符实测：写入、回读、二次备份、删除、重复删除幂等、拒绝 `C:`；包内 `copy_to_sd.bat` 实测通过
- 自检 9/9 通过，覆盖「图片 → 包」「现成 TPL → 包」「EXE → 包」三条链路

## v1.0（2026-11-08）— 专用背景图工具

- 纯 Python 实现 TPL 编解码（`src/tplcodec.py`）：`RGB5A3` / `RGB565` / `CI8`、GX 4×4 / 8×4 tiling、多贴图 TPL、调色/裁切；与 devkitPro `gxtexconv` 关键产物逐字节比对通过，**不依赖 devkitPro**
- GUI：三栏布局、浅色 / 低饱和深色主题、模拟 Swiss 界面叠加预览、图片列表、亮度/对比度/饱和度/模糊/暗角
- 网络功能：生成 TPL、上传到实机、回读、删除、抓屏、查询状态
- 打包为单文件 `dist/SwissBackdrop.exe`（20.37 MiB），内嵌中文版本资源与图标，免装 Python
- 自检 7/7；`--build` 产物与 SD 卡生效 TPL 的 SHA 一致

## 关键技术结论

- **CI8 的 `palfmt` 必须为 2**：`palfmt=0` 生成 IA8 TLUT，Swiss 的 `TEX_BACKDROP` 套用内置 CI4 的 TEV 设置，彩色图被渲成亮黄（亮度 61 → 203）。工具已把 CI4/CI8 固定为 `palfmt=2`
- 推荐默认 `RGB5A3` 640×480；CI8 体积约一半（≈300 KB vs ≈600 KB）
- TPL 多贴图按日历轮换：2/3/4/6/12 按月、7 按星期、24 按小时、30/31 按日、365/366 按年内第几天
- 上游 `TPL_OpenTPLFromHandle()` 成功分支未关 `FILE*` 会锁死 `backdrop.tpl`；汉化固件已补 `fclose()`，配合后可反复上传/删除

## 实机验证

深灰示例（CI8 + `palfmt=2`，307,808 B）与用户插画背景（RGB5A3，614,464 B）均通过 wiiload 重启与断电冷启动验证，中文界面、温度/日期、文件列表正常。
