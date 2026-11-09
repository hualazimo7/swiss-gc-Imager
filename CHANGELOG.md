# 更新记录

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
