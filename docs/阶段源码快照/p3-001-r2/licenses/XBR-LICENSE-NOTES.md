# xBR 许可归属与适配说明（P3 / session p3-001）

- 算法：**Hyllian's xBR-lv2 Shader**（libretro 参考版），MIT 许可
  （Copyright (C) 2011-2016 Hyllian）。
- 资源：`shaders/p3-xBR-lv2.glsl` —— 以 `docs/证据/xbr-lv2.glsl`
  （sha256 `9cf5b08c7378305b558204354e898f6837c481fd5b4371dfbe6b5092cffe5062`）
  为基的适配版（p3-adapt-v1）。原 MIT 头逐字保留。
- 来源取证：`docs/证据/移植取证索引.json`（本阶段未从网络重新下载）。
- 身份声明：xBR ≠ xBRZ；本档不冒称任意比例等价——参考 XBR_SCALE=3.0，
  明示为 **「3× 预缩放 + mpv 后续缩放」模式**（hook 输出恰为源 3×3 倍，
  mpv scaler 完成到窗口；窗口恰为 3× 时即纯参考结果）。`vf=xbr` 本机滤镜
  与本 GPU 档无涉，不作为 GPU 版实测证据。

## 适配范围（逐条记录；数学/邻域/坐标映射零改动）

1. **mpv MAIN RGB hook 化**：基文件为 libretro 格式（无任何 //!HOOK 指令）；
   适配为 `//!HOOK MAIN` + `//!BIND HOOKED` + `//!SAVE HOOKED`，
   `//!WIDTH/HEIGHT HOOKED.w/h 3.0 *`（3× 预缩放输出）。
2. **邻域采样**：基文件 VERTEX 段预计算的 t1..t7 偏移（**21 个 tex2D 采样
   点** A1,B1,C1,A,B,C,D,E,F,G,H,I,G5,H5,I5,A0,D0,G0,C4,F4,I4，基文件
   244-264 行）在片元内按同一坐标表逐点重 derive（`HOOKED_pos + 偏移×
   HOOKED_pt`），delta/delta_l/eq_threshold/rgbw/Ao..Ci/Y 常数与 wd/edr/
   irlv1(CORNER_C)/maximos(SMOOTH_TIPS) 数学逐行照抄，参数固定为参考默认
   （XBR_Y_WEIGHT 48.0 / EQ_THRESHOLD 15.0 / LV1 0.5 / LV2 2.0 /
   small_details 0.0）。
3. **许可头**：MIT 原文+归属保留；适配差异以注释块另立（p3-adapt-v1 标记
   +基文件哈希）；无指令样前缀注释行。
