# 研究对象: Nearest Neighbor(最近邻缩放)

> **初稿归档，非最终验收依据。** 墙钟测试不能推导 GPU pass 耗时；本文性能数值与绝对不存在式断言不被最终报告采纳。请先读 [勘误说明](../勘误说明.md) 和 [整合报告](../可行性研究报告.md)。

本机: 2560×1440 屏 / RTX 2080 SUPER 8G / mpv v0.40.0-393-gad59ff1b4(libplacebo v7.357.0, D:/mpv/mpv.com)/ 常驻 RIFE 共享 GPU / 片源 1080p 为主。
上游取证: mpv master(raw)、libplacebo master(raw)、GitHub API;另含本机命令与本地渲染实测。
标注约定: 【实证】= 本地命令或上游源码/文档直接证实;【未证实】= 未找到权威出处,如实标注;【先验】= 引用项目冻结的既往实验结论;【未取得】= 访问失败。

---

## Nearest Neighbor(最近邻)

### 1. 算法本体与原理

**定义**: 输出像素直接取距离最近的源像素值,`dst(x,y) = src(round(x·Wsrc/Wdst), round(y·Hsrc/Hdst))`。等价于以 box 为核、radius 0.5 的重采样核,不产生任何新像素值。

**libplacebo 权威定义**【实证,src/filters.c L688-695】:

```c
const struct pl_filter_config pl_filter_nearest = {
    .name        = "nearest",
    .description = "Nearest neighbor",
    .kernel      = &pl_filter_function_box,
    .radius      = 0.5,
    .allowed     = PL_FILTER_UPSCALING,   // 官方仅标记为上采样核
    .recommended = PL_FILTER_UPSCALING,
};
```

**结构 / pass 数**: **0 个额外 pass**。libplacebo 对 nearest 走"直接采样"路径,`pl_shader_sample_nearest()` 生成的 GLSL 核心就一行(`textureLod` 单次取样)【实证,src/shaders/sampling.c L290-302】:

```glsl
vec4 color = vec4(scale) * textureLod(tex, pos, 0.0);
```

无 COMPUTE、无多 pass、无中间纹理、**连 scaler LUT 都不需要**(nearest 在 mpv gpu-next 的 `fixed_scalers` 表中直接映射到 `pl_filter_nearest`,与 bilinear/bicubic_fast/oversample 同组"固定缩放器",不参与参数化内核的 LUT 构建)【实证,vo_gpu_next.c L2574-2580】;vo_gpu(旧 vo)同样内建 `{"nearest", SCALER_NEAREST}`【实证,gpu/video.c L302】。

**复杂度量级**: O(1) tap/像素、0 次乘加、显存带宽 = 输入读一遍 + 输出写一遍——与 bilinear 同为整个渲染管线的成本地板。任何其他缩放核(最重的 EWA 系 ~数十 tap)都严格高于它。

**画质特性**: 完全保边、零模糊、零 ringing;代价是**分数倍缩放时像素宽度不均 + 边缘锯齿 + 运动时像素爆裂(闪烁)**。mpv 手册在 `oversample` 条目中明确点名这两类缺陷,并把 oversample 描述为"修正 nearest 缺陷、代价是轻微模糊"的变体【实证,options.rst L5997-6001】。

### 2. 权威实现 / 开源仓库与协议

| 来源 | 状态 | 说明 |
|---|---|---|
| mpv 内建(`--scale=nearest`) | ✅ 主实现 | `--scale=help`/`--tscale=help` 38 核表中均含 `nearest`【实证,本机 v0.40】;手册 `--scale` 节列出【实证,options.rst L5942 起】 |
| libplacebo(gpu-next 后端) | ✅ 主实现 | `pl_filter_nearest`(filters.c)+ `pl_shader_sample_nearest`(sampling.c);协议 LGPL-2.1【实证,仓库 LICENSE 未逐字核验→协议按仓库常规标注,未证实逐字】 |
| mpv vo_gpu | ✅ 平行实现 | `SCALER_NEAREST` 内建【实证,gpu/video.c L302】 |
| libretro/slang-shaders | ✅ 存在但无实质算法 | `nearest.slangp` 全文仅 3 行:`shader0=stock.slang; filter_linear0=false`——连 libretro 社区都只需一个"关线性滤波"预设,无需专门 shader【实证,raw HTTP 200】 |
| libretro/slang-shaders `pixel-art-scaling/shaders/uniform-nearest.slang` | ✅ 存在 | gizmo98 (2023) GPLv2,"均匀像素的 nearest 观感 + 纹理 AA",像素风向,非视频向【实证,raw 取得头部】 |
| GitHub 搜索 `mpv user shader nearest` | ❌ 0 结果 | `total_count: 0`【实证,API】;agyild 名下仓库仅 reshade-shaders 等,无 nearest/缩放类【实证,API /users/agyild/repos】 |
| mpv wiki User-Shaders 页 | 【未取得】 | raw wiki 域名本机 curl 反复 SSL 失败(exit 35),未能复查 |

**结论**: nearest 的权威实现就是 mpv/libplacebo 本体;**不存在也不需要第三方 mpv 移植**。agyild/bloc97 一类"知名 shader 移植"生态对该算法无涉(bloc97/Anime4K 仓库在,21.4k stars,仅作对照【实证,API】)。

### 3. mpv 集成路径评估(对照 primer A–E)

**选型: D(内建 scale 内核)+ E(lua 菜单控制面)。完全不碰 A(user-shader)/B(hook 细节)/C(vf)。**

理由: 算法是 1-tap 直接采样,任何 user-shader 方案(A)只会比内建路径更慢、更复杂,且 gpu-next 会把它当普通 MAIN pass 插入,还额外占一条 `--glsl-shaders` 链位(与 RIFE/其他 shader 抢链表语义);C(vf=lavfi/libplacebo)引入帧进出 filter 图的桥接成本,对零成本算法毫无意义;B(gpu-next hook)只是 D 的执行后端,由 mpv 自动完成。

**接入要点**【除注明外均实证】:

1. **档位本体**: `scale=nearest`(全屏 1080p→1440p 恒为上采样,`--scaler-resizes-only` 默认 yes 不影响该场景;窗口恰等于源尺寸时整条 scaler 被旁路【实证,options.rst】)。
2. **cscale 跟随问题**: 手册明确 cscale 未设时"applies the filter implied by --scale"【实证,options.rst L6012-6016】→ 设 scale=nearest 后 4:2:0 源的色度上采样也变 nearest。**菜单档位应显式决策**: 视频向建议 `scale=nearest` + 保留 `cscale`(或钉为 spline36/bilinear),像素画向可连 chroma 一起 nearest。
3. **--interpolation 关系**(任务提示要求核实):
   - interpolation 只控制**帧混合器**:`frame_mixer = interpolation ? map_scaler(TSCALE) : NULL`【实证,vo_gpu_next.c L2878】,空间上采样仍由 `scale` 独立承担【实证,L2582-2585 fixed_frame_mixers 与 fixed_scalers 分表】。
   - 即 **scale=nearest 与 --interpolation 正交共存**: 开着 interpolation 时,每一参与混合的帧仍按 nearest 做空间上采样,nearest 的像素闪烁无法被 tscale(默认 oversample)修复;手册 `oversample` 条目正是以 nearest 缺陷为反例写的【实证,options.rst L5997-6001】。
   - `tscale=nearest` 合法(help 列表含)但等于不做运动补偿,不建议;`--interpolation` 需配 `--video-sync=display-*` 否则静默失效【实证,options.rst L6183-6186】。
   - **菜单建议: nearest 档位绑定"关 interpolation"或在 OSD 注明权衡。**
4. **dscale**: libplacebo 将 nearest 标记为 upscaling-only(见 §1 代码)。本机 1080p 源→720p 窗口 + `--dscale=nearest` 实测渲染 10 帧无报错无告警【实证,本机】,但缩小路径实际采样语义未逐像素核验【未证实】→ **档位不动 dscale**(默认 hermite【实证,options.rst L6029-6032 "This is the default for --dscale"】)。
5. **菜单/热切换(E 路径)**: `scale` 是运行时可切属性,`mp.set_property("scale","nearest")` 或 `cycle-values scale nearest ewa_lanczossharp ...` + `mp.add_key_binding`;亦可做成 profile `[scaler-nearest] scale=nearest`。不涉及 shader 文件,故不存在既有文档 C2 指出的"按路径缓存导致热重载不可靠"问题【实证路径 vo_gpu_next.c L2660-2683 仅针对已解析 shader】;`--interpolation-preserve`(gpu-next 默认 on)使渲染参数动态切换更平滑【实证,options.rst L6219-6222】。
6. **vo 要求**: gpu/gpu-next 均支持;direct3d/sdl 等 VO 无此内核表【先验,与既有文档 A5 结论一致】。

### 4. 难度与预估工作量

- **难度: 1/5**(5 级制)。
- **工作量: 0.5–1.5 人时**——菜单注册一个档位 + 决策 §3-2(cscale)与 §3-3(interpolation)语义 + 回归播放验证。若并入项目统一的"缩放档位注册表"(与 ewa_lanczossharp、Anime4K 档并列、按源分辨率自动换链),约 2 人时。

### 5. @1440p + RTX 2080S 性能量级(本机实测)

**方法学**: 120 帧 1920×1080 I420 原始流 → 2560×1440 窗口,`--vo=gpu-next --gpu-api=d3d11 --hwdec=no --untimed --ao=null`,`--frames=120` 墙钟计时,每配置 2 次(2026-02,本机,无其他 GPU 负载)。墙钟含解码/上传/提交,**非纯 GPU pass 时间**(本版 mpv 无 `--gpu-timing` 可用【实证,--list-options 无此项】),但各配置同法对比,相对结论稳健。

| 配置 | 墙钟 run1 / run2 | 相对 |
|---|---|---|
| `--scale=nearest` | 0.774s / 0.787s | ≈1.00×(流水线地板) |
| `--scale=bilinear`(参照) | 0.767s / 0.767s | ≈1.00×(地板) |
| `--scale=ewa_lanczossharp` | 1.957s / 1.919s | ≈2.5×(每 120 帧 +1.16s,≈+9.7ms/帧) |
| `--scale=ewa_lanczos` | 1.957s / 1.932s | ≈2.5× |

**量级结论**:
- nearest 的缩放环节在本机处于**与 bilinear 相同的地板**,GPU pass 成本 <0.1ms/帧 量级【工程估计,由 1-tap+带宽推导;墙钟无法分辨更低】;给常驻 RIFE 让出的预算与 bilinear 完全相同。
- 相对 ewa_lanczossharp: 墙钟约 **2.5 倍差距**(后者 +9.7ms/帧)——若当前 ewa 链与 RIFE 同开已接近帧预算,换 nearest 档可一次性释放该份额。
- 相对 Anime4K v4 计算链(多 pass 全分辨率 COMPUTE): 至少低 1–2 个数量级【工程估计+先验;未在本机重测 Anime4K 链】。
- **画质预期(重要)**: 1.33× 分数倍下 nearest 的像素不均/锯齿通常**劣于** ewa_lanczossharp;这与项目先验"重型神经 shader 感知收益不成立、ewa 即上限"不矛盾——先验约束的是重型上限,nearest 是成本下限。**档位定位建议: 参考对比/像素画/极限省电档,非默认档。**

### 6. 已知限制与风险

1. **分数倍缩放伪影**: 像素宽度不均、静态锯齿、横摇/滚动时像素爆裂——算法本性,不可修;缓解档是内建 `oversample`(官方"去掉 nearest 小缺陷,代价是轻微模糊")或 `bicubic_fast`【实证,options.rst】。
2. **色度连带**: `cscale` 默认跟随 `scale`(§3-2),4:2:0 源色度边缘会同步硬化,易被误判为"画质劣化 bug"。
3. **与 interpolation 的观感冲突**: 开 interpolation 时逐帧 nearest 采样会放大运动闪烁(§3-3);若用户同时开 RIFE(时域)与 nearest(空间),闪烁感可能叠加【机制推断,未实测主观评价】。
4. **缩小路径语义未逐像素核验**(§3-4)【未证实】。
5. **无信息增益**: 零模糊=零超分效果,需在菜单文案上避免被当作"画质档"。
6. **非 GPU/非 libplacebo VO 不可用**(§3-6)。
7. libplacebo 将 nearest 标记 `PL_FILTER_UPSCALING` only,若未来 mpv 收紧 dscale 校验,缩小场景回退行为可能变化【未证实,前瞻性风险】。

### 7. 可行性结论

**可行** —— 零依赖、内建、成本处于渲染管线地板(与 bilinear 同级、约为 ewa_lanczossharp 墙钟的 1/2.5),唯一工作量是菜单档位接线及 cscale/interpolation 两处语义决策;唯一真正要"研究"的是把它当**参考/像素画/省电档**而非画质档来定位。

### 8. 证据链接列表(全部本会话实际访问,2026-02)

1. https://raw.githubusercontent.com/mpv-player/mpv/master/DOCS/man/options.rst — `--scale` 节(含 oversample 对 nearest 缺陷的描述、ewa_lanczossharp/high-quality 默认)、`--cscale`(跟随 scale)、`--dscale`(hermite 默认)、`--tscale`、`--interpolation`(video-sync 警告)、`--interpolation-preserve`、`--scaler-resizes-only`
2. https://raw.githubusercontent.com/mpv-player/mpv/master/video/out/vo_gpu_next.c — `fixed_scalers` {"nearest"→&pl_filter_nearest} L2574-2580;`fixed_frame_mixers` L2582-2585;`frame_mixer = interpolation ? ... : NULL` L2878;shader 按路径缓存 L2660-2683
3. https://raw.githubusercontent.com/mpv-player/mpv/master/video/out/gpu/video.c — vo_gpu 内核表 {"nearest", SCALER_NEAREST} L302
4. https://api.github.com/repos/mpv-player/mpv/contents/video/out — 目录清单(确认 vo_libplacebo.c 已不存在、现名 vo_gpu_next.c;首次 404 的原因)
5. https://raw.githubusercontent.com/haasn/libplacebo/master/src/filters.c — `pl_filter_nearest` 定义(box/radius 0.5/仅上采样) L688-695
6. https://raw.githubusercontent.com/haasn/libplacebo/master/src/shaders/sampling.c — `pl_shader_sample_nearest` 单 textureLod 实现 L290-302
7. https://api.github.com/repos/libretro/slang-shaders/git/trees/master?recursive=1 — 命中 nearest.slangp、pixel-art-scaling/uniform-nearest.slang
8. https://raw.githubusercontent.com/libretro/slang-shaders/master/nearest.slangp — HTTP 200,全文 3 行预设(filter_linear0=false)
9. https://raw.githubusercontent.com/libretro/slang-shaders/master/pixel-art-scaling/shaders/uniform-nearest.slang — gizmo98 GPLv2 头部与说明
10. https://api.github.com/users/agyild/repos?per_page=100 — agyild 名下无 nearest/缩放类仓库
11. https://api.github.com/search/repositories?q=mpv+user+shader+nearest&per_page=8 — total_count 0
12. https://api.github.com/repos/bloc97/Anime4K — 仓库在,21,454 stars(对照用)
13. 本机: `D:/mpv/mpv.com --version / --scale=help / --tscale=help / --list-options`(nearest 在表、无 --gpu-timing、scaler-resizes-only 默认 yes)
14. 本机实测: 120 帧 1080p→2560×1440 窗口 --untimed 墙钟(§5 表);1080p→720p + dscale=nearest 渲染无报错
15. 访问失败如实记录: https://raw.githubusercontent.com/wiki/mpv-player/mpv/User-Shaders.md 与 GPU-Next-vs-GPU.md 本机 curl SSL 失败(exit 35)【未取得】(GPU-Next-vs-GPU 的要点以项目既有文档 `mpv机制.md` 之完整取证为准);`lavfi://` 协议本机 mpv 编译未启用(实测报错,故改用 raw YUV 测试源)
