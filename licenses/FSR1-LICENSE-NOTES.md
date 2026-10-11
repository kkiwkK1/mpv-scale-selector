# FSR1 许可归属说明（P2 / session p2-001）

- 算法：**AMD FidelityFX Super Resolution v1.0.2（FSR1，EASU+RCAS）**，MIT 许可。
- 资源：`shaders/p2-FSR1.glsl` —— 以 `docs/证据/port-FSR.glsl`（agyild 的 mpv 移植，
  MIT 版权头内嵌）为基的适配版（p2-adapt-v1）。
- 适配范围（不触及主算法）：仅文件头部追加溯源注释；固定 `SHARPNESS 0.2`；
  保留 `//!WHEN`（仅放大时运行）与每轴 ≤2× 的 `//!WIDTH///!HEIGHT` 钳制，
  超出部分由 mpv scaler 接管。适配版另立 SHA-256，记录于
  `shaders/resource-manifest.json`；主算法未替代、未改名（DESC 保留
  "FidelityFX Super Resolution v1.0.2 (EASU)/(RCAS)"）。
- 基文件 SHA-256：`56d8597fc6b7bf6d13f8c3b2bdf1cdc43b06175d51746aab44cf1dca16929b9e`
  （来源 gist raw 取证：`docs/证据/移植取证索引.json`；未从网络新下载）。
- 许可文本核对记录（只读引用）：`docs/证据/fsr-license.txt`（AMD MIT 原文）。
- 归属：Copyright (c) 2021 Advanced Micro Devices, Inc.；mpv 移植 by agyild。
  本仓库副本完整保留原版权与 MIT 许可声明。
