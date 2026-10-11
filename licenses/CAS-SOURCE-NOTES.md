# CAS 来源与归属说明（P0 研究资产）

- **资产范围**：`docs/证据/` 下三份 CAS 研究文件——`port-CAS.glsl`、
  `port-CAS-scaled.glsl`、`cas-readme.md`。三文件 SHA-256 与
  `docs/证据/移植取证索引.json` 逐字一致（本说明成文时实测核对：
  `a945e104…99823` / `fe678abb…bab217` / `c2ffd7c1…83a1a`）。
- **仅作 P0 研究对照**：CAS（FidelityFX Contrast Adaptive Sharpening）在
  本项目从未成为任何档位资源——`shaders/` 目录（含 `anime4k/` 子目录）无
  任何 CAS 文件；`shaders/resource-manifest.json` 与
  `shaders/p3-resource-manifest.json` 均无 CAS 条目（前者唯一的 "CAS"
  字符串是 FSR 条目说明文字中的 "EASU+RCAS"，与本资产无关）。
- **BCAS 身份未核实**：截图菜单项 BCAS 的准确算法定义未核实，故菜单中
  BCAS 恒为禁用占位（`script-opts/scale-selector-gears.conf` 的
  `bcas_reason`，解析器强制 disabled 防冒名）；不以 CAS 或 Bicubic+CAS
  冒名顶替 BCAS。
- **许可**：`port-CAS.glsl` 与 `port-CAS-scaled.glsl` 头部内嵌 AMD MIT
  原文（`Copyright (c) 2017-2019 Advanced Micro Devices, Inc. All rights
  reserved.` 及 MIT 许可正文，本说明成文时头部逐行核对）；`cas-readme.md`
  为 GPUOpen FidelityFX-CAS 官方 README 抓取件。来源 URL、抓取时间
  （2026-10-02 UTC）、HTTP 状态与 SHA-256 均登记于
  `docs/证据/移植取证索引.json`。
- **未产生分发资源**：P0 之后没有任何 CAS/Bicubic+CAS 移植进入交付物，
  本仓库不分发 CAS 代码。若未来立项此类档位，必须独立命名（不冒名
  BCAS）并按实施计划第 1 节第 8 条重做来源、许可与再分发条款复核。
