# 第三方组件声明（THIRD-PARTY NOTICES）

本仓库自身代码（`scripts/`、`tools/` 等）以仓库根目录 [`LICENSE`](LICENSE)（MIT）许可发布。
本文件汇总 `shaders/` 下分发的第三方 shader 组件：组件 / 上游仓库链接 / 许可名 / 本仓库路径 / 许可笔记路径，逐项对应 `licenses/` 目录的七份许可笔记。

> **许可效力声明**：各 shader 许可以其**文件头与 `licenses/` 许可笔记**为准，本表仅为索引；如与文件头有出入，以文件头为准。
>
> **License notice**: Third-party shaders bundled in `shaders/` are listed below with their upstream sources and licenses. Each shader's governing license is the one embedded in its own file header, cross-referenced by the notes under `licenses/`.

| # | 组件 | 上游仓库链接 | 许可名 | 本仓库路径 | 许可笔记路径 |
|---|------|--------------|--------|------------|--------------|
| 1 | AMD FidelityFX Super Resolution v1.0.2（FSR1，EASU+RCAS）；mpv 移植 by agyild | 上游：<https://github.com/GPUOpen-Effects/FidelityFX-FSR><br>mpv 移植：<https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5> | MIT | `shaders/p2-FSR1.glsl` | [`licenses/FSR1-LICENSE-NOTES.md`](licenses/FSR1-LICENSE-NOTES.md) |
| 2 | NVIDIA Image Scaling v1.0.2（NIS，含 NIS 锐化段）；mpv 移植 by agyild | 上游：<https://github.com/NVIDIAGameWorks/NVIDIAImageScaling><br>mpv 移植：<https://gist.github.com/agyild/7e8951915b2bf24526a9343d951db214> | MIT | `shaders/p3-NIS.glsl` | [`licenses/NIS-LICENSE-NOTES.md`](licenses/NIS-LICENSE-NOTES.md) |
| 3 | Qualcomm Snapdragon Game Super Resolution v1（SGSR1，luma 适配版）；mpv 移植 by agyild | 上游：<https://github.com/SnapdragonGameStudios/snapdragon-gsr><br>mpv 移植：<https://gist.github.com/agyild/7715b6b1f38427839d58f80884902cab> | BSD-3-Clause | `shaders/p2-SGSR1.glsl` | [`licenses/SGSR1-LICENSE-NOTES.md`](licenses/SGSR1-LICENSE-NOTES.md) |
| 4 | Anime4K v4 stock（bloc97）——MIT 文件 8 个 | <https://github.com/bloc97/Anime4K> | MIT | `shaders/anime4k/` 下 8 个文件（明细见下节） | [`licenses/ANIME4K-LICENSE-NOTES.md`](licenses/ANIME4K-LICENSE-NOTES.md) |
| 5 | **Anime4K AutoDownscalePre**（bloc97）——Unlicense 文件 2 个（与上行的 MIT 文件许可不同，单列） | <https://github.com/bloc97/Anime4K> | Unlicense（公共领域） | `shaders/anime4k/Anime4K_AutoDownscalePre_x2.glsl`<br>`shaders/anime4k/Anime4K_AutoDownscalePre_x4.glsl` | [`licenses/ANIME4K-LICENSE-NOTES.md`](licenses/ANIME4K-LICENSE-NOTES.md) |
| 6 | sharp-bilinear（Themaister）；libretro glsl-shaders 仓库 `interpolation/shaders/sharp-bilinear.glsl` | <https://github.com/libretro/glsl-shaders> | Public domain（作者声明原文内嵌于文件头） | `shaders/p3-Sharp-Bilinear-2x.glsl`<br>`shaders/p3-Sharp-Bilinear-AUTO.glsl` | [`licenses/SHARP-BILINEAR-LICENSE-NOTES.md`](licenses/SHARP-BILINEAR-LICENSE-NOTES.md) |
| 7 | Hyllian's xBR-lv2 Shader（libretro 参考版，Copyright (C) 2011-2016 Hyllian）；libretro glsl-shaders 仓库 `xbr/shaders/xbr-lv2.glsl` | <https://github.com/libretro/glsl-shaders> | MIT | `shaders/p3-xBR-lv2.glsl` | [`licenses/XBR-LICENSE-NOTES.md`](licenses/XBR-LICENSE-NOTES.md) |
| 8 | AMD FidelityFX CAS（**仅 P0 研究对照，未分发**） | 上游：<https://github.com/GPUOpen-Effects/FidelityFX-CAS><br>mpv 移植 gist：<https://gist.github.com/agyild/bbb4e58298b2f86aa24da3032a0d2ee6> | MIT（仅存于 `docs/证据/` 研究文件头部） | **无** —— `shaders/` 不含任何 CAS 文件，本仓库不分发 CAS 代码；菜单中的 BCAS 为诚实禁用占位 | [`licenses/CAS-SOURCE-NOTES.md`](licenses/CAS-SOURCE-NOTES.md) |

## Anime4K MIT 文件明细（第 4 行的 8 个文件）

以下 8 个文件文件头均为 `// MIT License` + `// Copyright (c) 2019-2021 bloc97`：

- `shaders/anime4k/Anime4K_Clamp_Highlights.glsl`
- `shaders/anime4k/Anime4K_Restore_CNN_M.glsl`
- `shaders/anime4k/Anime4K_Restore_CNN_Soft_M.glsl`
- `shaders/anime4k/Anime4K_Restore_CNN_Soft_VL.glsl`
- `shaders/anime4k/Anime4K_Restore_CNN_VL.glsl`
- `shaders/anime4k/Anime4K_Upscale_CNN_x2_M.glsl`
- `shaders/anime4k/Anime4K_Upscale_CNN_x2_VL.glsl`
- `shaders/anime4k/Anime4K_Upscale_Denoise_CNN_x2_VL.glsl`

第 5 行的两个 Unlicense 文件文件头均为 "This is free and unencumbered software released into the public domain"（指向 unlicense.org）。

## 适配版说明

`p2-*` / `p3-*` 各文件为对上游（或其 mpv 移植基文件）的适配版（p2-adapt-v1 / p3-adapt-v1）：适配范围仅限头部溯源注释、参数固定、输出边界 guard 等不触及主算法的改动，各基文件 SHA-256 与逐条差异记录于对应许可笔记；各文件内的原版权与许可声明均完整保留。

## 取证与核对

- 各基文件的来源 URL、抓取时间（2026-10-02 UTC）与 SHA-256：`docs/证据/移植取证索引.json`、`docs/证据/网络取证索引.json`。
- Anime4K 逐文件双哈希与本机活动配置的只读交叉核对：`shaders/resource-manifest.json`、`docs/备份记录.json`。
- 本仓库副本未从网络重新下载任何文件、未做除适配范围声明之外的修改。
