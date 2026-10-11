# Anime4K 许可归属说明（P2 / session p2-001）

- 算法：**Anime4K v4**（stock，bloc97/Anime4K）。10 个文件的许可以**各自文件
  内嵌头部**为准，逐文件分布见下：8 个 MIT + 2 个 Unlicense（公共领域）。
- 本仓库 `shaders/anime4k/` 下 10 个 `Anime4K_*.glsl` 文件是**本机现有 CTRL+1..6
  真实完整 stock 链的零改动字节级副本**：
  - 复制源（冻结快照）：`D:/workspace/小项目/mpv插件/_备份/缩放插件/mpv-config-20261002-233943/payload/mpv-config/shaders/`
    （`docs/备份记录.json`：manifest 232fcda3…，ZIP 207e8d3f…，`source_unchanged=true`）；
  - 只读交叉核对：`C:/Users/kkiw/AppData/Roaming/mpv/shaders/`（活动配置，逐文件 SHA-256 一致，未写入）；
  - 双哈希逐文件记录于 `shaders/resource-manifest.json`。
- 不是 ArtCNN 改造版，不含任何再分发版修改；未从网络下载任何新文件。
- 许可依据（逐文件文件头，最直接证据；M-11 整改补记）：
  - **MIT**（文件头 `// MIT License` + `Copyright (c) 2019-2021 bloc97`），8 个：
    `Anime4K_Clamp_Highlights.glsl`、`Anime4K_Restore_CNN_VL.glsl`、
    `Anime4K_Restore_CNN_Soft_VL.glsl`、`Anime4K_Restore_CNN_M.glsl`、
    `Anime4K_Restore_CNN_Soft_M.glsl`、`Anime4K_Upscale_CNN_x2_VL.glsl`、
    `Anime4K_Upscale_CNN_x2_M.glsl`、`Anime4K_Upscale_Denoise_CNN_x2_VL.glsl`；
  - **Unlicense**（公共领域，文件头 `This is free and unencumbered software
    released into the public domain`，指向 unlicense.org），2 个：
    `Anime4K_AutoDownscalePre_x2.glsl`、`Anime4K_AutoDownscalePre_x4.glsl`。
  - 链加载：默认 `anime4k_chain=a`（CTRL+1 链）即实际加载上述两个 Unlicense
    文件，a..f 六条链均引用它们；链的具体组成随 `anime4k_chain=a..f` 配置动态
    变化（定义见 `tools/p2_lib.py` 的 `ANIME4K_CHAINS`）。
  - `docs/证据/anime4k-readme.md` 仅为 P0 研究素材（只读引用），经核实不含许可
    文本，不作为上述任一许可的直接证据。
- 归属：MIT 部分由 bloc97 及贡献者开发（github.com/bloc97/Anime4K）；Unlicense
  部分的作者已将作品贡献至公共领域。本仓库副本保留原文件内的全部版权与许可
  声明，未做任何修改。
