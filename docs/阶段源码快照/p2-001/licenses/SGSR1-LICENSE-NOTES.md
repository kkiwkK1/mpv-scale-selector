# SGSR1 许可归属说明（P2 / session p2-001）

- 算法：**Qualcomm Snapdragon Game Super Resolution v1（SGSR1）**，BSD-3-Clause 许可。
- 资源：`shaders/p2-SGSR1.glsl` —— 以 `docs/证据/port-SGSR.glsl`（agyild 的 mpv 移植，
  **luma 适配版**，非 RGB 原版；含 2025-12-23 hotfix）为基的适配版（p2-adapt-v1）。
- 已知差异（在案）：luma 通道适配与原版 RGB 处理存在差异，如实记录，
  不宣称与原版逐像素等价。
- 适配范围（不触及主算法）：仅文件头部追加溯源注释；`//!PARAM` 全部使用文件内
  固定值（UseEdgeDirection=1、EdgeThreshold=4.0、EdgeSharpness=2.0，均在声明
  MINIMUM/MAXIMUM 范围内，0–1 钳制项 UseEdgeDirection 核对为 1∈[0,1]）；
  保留 `//!WHEN`（仅放大时运行）。适配版另立 SHA-256，记录于
  `shaders/resource-manifest.json`；主算法未替代、未改名（DESC 保留
  "Snapdragon Game Super Resolution (GSR) v1"）。
- 基文件 SHA-256：`10a3d1ada2c439607caac32de2a5adceab1cd1580261511aaf67bafd415065fe`
  （来源 gist raw 取证：`docs/证据/移植取证索引.json`；未从网络新下载）。
- 许可文本核对记录（只读引用）：`docs/证据/sgsr-license.txt`（BSD-3-Clause 原文）。
- 归属：Copyright (c) 2023, Qualcomm Innovation Center, Inc.；mpv 移植 by agyild。
  本仓库副本完整保留原版权与 BSD-3-Clause 许可声明。
