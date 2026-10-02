# 研究对象: Sharp Bilinear(锐利双线性)

> **初稿归档，非最终验收依据。** OUTPUT 重采 MAIN、RetroArch 参数接口、绝对性能预测与“无任何port”等结论未被最终报告采用。请先读 [勘误说明](../勘误说明.md) 与 [整合报告](../可行性研究报告.md)。

本机: 2560×1440 屏 / RTX 2080 SUPER 8G / mpv v0.40 / 常驻 RIFE 插帧共享 GPU / 片源以 1080p 为主。
上游取证: libretro/glsl-shaders、libretro/slang-shaders、rsn8887/Sharp-Bilinear-Shaders(raw + GitHub API)、haasn/libplacebo(raw)、mpv master 手册(API raw)、GitHub 搜索 API。
标注约定: 【实证】= 本地 curl 实际取得(正文给出原文/HTTP 状态);【未证实】= 未找到权威出处,如实标注;【先验】= 引用项目冻结的既往实验结论(含 docs/研究素材/nearest.md 内部实证);【估计】= 数量级推算,非实测。

---

## Sharp Bilinear(锐利双线性)

### 1. 算法本体与原理

**定义**: 先对源做 **N× 整数倍 nearest 预放大**(N 为 ≥ 目标缩放比的整数),再用**双线性**从中间分辨率缩放到最终输出。等价于"最近邻的纯像素块 + 短过渡带"的重采样: 像素主体保持锐利,过渡均匀铺开,消除纯 nearest 在非整数倍下的像素宽度不均/抖动(pixel wobble),又远比纯 bilinear 清晰。

**权威单 pass 实现(Themaister,公共领域)【实证,sharp-bilinear.glsl 原文】**: 不真的生成中间纹理,而是**扭曲采样坐标 + 借用硬件双线性插值器**,一次 tap 等价完成"预缩放+双线性":

```glsl
vec2 texel = vTexCoord * SourceSize.xy;   // 源 texel 坐标
vec2 s = fract(texel);
float scale = (AUTO_PRESCALE > 0.5) ? floor(outsize.y / InputSize.y + 0.01)
                                    : SHARP_BILINEAR_PRE_SCALE;   // 预缩放倍数 P
float region_range = 0.5 - 0.5 / scale;   // 每个源 texel 中"纯像素"半宽
vec2 center_dist = s - 0.5;
vec2 f = (center_dist - clamp(center_dist, -region_range, region_range)) * scale + 0.5;
vec2 mod_texel = floor(texel) + f;        // 扭曲后的采样点
FragColor = texture(Source, mod_texel / SourceSize.xy);
```

几何含义【实证,由上式推导】: 当 `|s-0.5| ≤ 0.5-0.5/P`(占 texel 宽度的 `1-1/P`)时 `f≡0.5`,采到 texel 正中心 → 输出纯像素色;两侧各 `1/(2P)` 宽的过渡带内,权重以 P 倍斜率线性混入邻 texel。P=2 时每个源像素 50% 纯色 + 两侧 25% 过渡。

**pass 数与结构(三个变体)**【实证,均取得原文】:

| 变体 | pass 数 | 自定义代码 | 说明 |
|---|---|---|---|
| `sharp-bilinear-2x-prescale`(prescale 变体) | **2** | **0 行**(两遍 stock.glsl) | `.glslp` 预设全文: pass1 `filter_linear0=false, scale=2.0`(nearest 2×)→ pass2 `filter_linear1=true`(硬件双线性到屏) |
| `sharp-bilinear`(自动/手动 P) | **1** | fragment ~15 行 ALU | 上述坐标扭曲,1 次 tap,依赖硬件 LINEAR 采样 |
| `sharp-bilinear-simple`(rsn8887) | **1** | 同公式,顶点着色器预计算 | 自动取 `max(floor(outsize/in), 1)` |

**复杂度量级**: O(1) tap/像素(≤4 tap 若不依赖硬件滤波器,见 §3)、~15 次标量 ALU、1 读 1 写。与 nearest/bilinear 同属成本地板级;严格低于 EWA 系(数十 tap)与任何 CNN 链。

### 2. 权威实现 / 开源仓库与协议

| 来源 | 状态 | 说明 |
|---|---|---|
| libretro/glsl-shaders `interpolation/shaders/sharp-bilinear.glsl` | ✅ 原始权威实现 | **Themaister,Public domain**【实证,raw HTTP 200,头部原文 "Author: Themaister / License: Public domain"】 |
| 同仓库 `interpolation/shaders/sharp-bilinear-simple.glsl` | ✅ 变体 | rsn8887 (based on TheMaister),顶点预计算【实证,raw 200】 |
| 同仓库 `interpolation/sharp-bilinear-2x-prescale.glslp` | ✅ prescale 变体 | 两遍 stock 配置(nearest 2×→bilinear),原文已取【实证,raw 200】 |
| 同仓库另有 `sharp-bilinear-scanlines` / `-simple` 预设 | ✅ 存在 | 文件树 grep 确认【实证,API tree 200】 |
| libretro/slang-shaders `pixel-art-scaling/shaders/sharp-bilinear.slang` | ✅ slang 移植 | 公式与 glsl 版一致(Push constant 传参),公共领域【实证,raw 200】;`pixel-art-scaling/*.slangp` 预设族存在【实证,API tree 200】 |
| rsn8887/Sharp-Bilinear-Shaders | ✅ 作者自维护合集 | RetroPie/RetroArch 向;README 原文: 固定 2× prescale 是"两遍配置: 先整数 2× 预缩放,再 bilinear 到全屏";simple 版"自动最佳整数预缩放";卖点"sharp pixels without pixel wobble and minimal blurring"【实证,raw README 200 + API tree 200】 |
| GitHub 仓库搜索 `mpv sharp-bilinear` / `sharp bilinear mpv` | ❌ **total_count: 0**(两次) | 【实证,API】 |
| GitHub 仓库搜索 `sharp-bilinear` | 7 个结果,均非 mpv | rsn8887 合集、Vita 插件归档等【实证,API】 |
| GitHub 全站 issue 搜索 `"sharp-bilinear" mpv` | 7 个结果,无一为 mpv 移植 | 命中的是 mpv 的 MKS/cscale 提案等无关项【实证,API】 |
| gist.github.com 搜索 `sharp-bilinear mpv` | 无结果页 | HTML 搜索页可能受 JS 限制,**未证实为穷尽**【实证,页面无可解析结果;标注局限】 |
| occivink/mpv-image-viewer(知名 .hook 合集) | ❌ 0 命中 | tree 全量 grep "sharp/bilinear" = 0【实证,API 200】 |
| agyild 名下 | ❌ 无涉 | `/users/agyild/repos` 仅 3 仓库(reshade-shaders 等),无缩放类;传闻的 `agyild/postscale-shaders` **404 Not Found**【实证,API】。agyild/bloc97 生态与该算法无关(bloc97=Anime4K 系,见 nearest.md 对照【先验】) |
| mpv/libplacebo 内建 | ❌ 无此内核 | mpv `--scale` 核表(38 核)无 sharp-bilinear【先验,nearest.md 内部实证 `--scale=help`】;libplacebo `renderer.h` 全文 grep "prescal" = **0 命中**(HTTP 200)【实证】 |

**结论**: 权威实现即 libretro 双仓库(公共领域,可自由改写),**不存在现成的、有维护的 mpv 移植版**——mpv 版需自写(工作量极小,见 §3/§4)。

### 3. mpv 集成路径评估(对照 primer A–E)

**选型: A(user-shader 自写单 pass)+ E(lua 键位/菜单热切换)。不碰 B 内建、C、D。**

理由: D 内建无此内核;B 的后端 libplacebo renderer 无 prescale 概念(§2 实证),也无对应选项;C(lavfi/libplacebo vf)无现成 filter,理论可用 `vf lavfi=[scale=flags=neighbor:2x,scale=flags=bilinear]` 在 CPU 侧模仿,但引入 swscale CPU 开销与帧桥接,**未证实、不推荐**。A 是唯一正道: 算法就十几行 GLSL,user-shader 体系(本机已跑 RIFE/anime4k 链)原生支持热切换。

**接入要点**【除注明外均实证于 mpv master 手册 options.rst(API raw 200,403KB)】:

1. **hook 点**: 推荐 `//!HOOK OUTPUT`(最终输出,颜色管理后、抖动前;**fixed**,不得写 //!WIDTH///!HEIGHT,默认即目标尺寸)+ `//!BIND MAIN`(缩放前的 RGB 主图)+ `//!BIND OUTPUT`(仅为取 `OUTPUT_size` 作输出尺寸 uniform)。备选 `//!HOOK MAIN`(resizable,可 `//!WIDTH OUTPUT.w //!HEIGHT OUTPUT.h` 一步到位,Anime4K 风格;在色度升格/色彩管理前完成,与现链共存语义更干净)。
2. **坐标**: fragment 内用 `OUTPUT_pos`([0,1],手册明示每个绑定纹理提供 `NAME_pos/_size/_pt/_rot`)或 `gl_FragCoord`;源 texel 坐标 `= pos * MAIN_size`,套 §1 公式后 `MAIN_tex((floor(texel)+f) * MAIN_pt)`。注意: pos 在 MAIN/OUTPUT 间按同一归一化矩形映射,`--video-pan-x/y`、`--video-align-x/y`、裁切会破坏恒等假设(手册全局提供 `tex_offset`,需修正;风险见 §6)。
3. **采样滤波**: 依赖"MAIN_tex 即硬件双线性"的 1-tap 写法最省,但 mpv 绑定纹理的默认滤波模式**未证实**;稳妥写法是**手动 4 tap**(对 n、n+1 两个 texel 中心各按权重 mix,≤4 次 `MAIN_tex`,不依赖滤波器状态),仍是地板成本。两种都写、参数切换,实测定夺。
4. **参数 P**: 经 `#pragma parameter` + `--glsl-shader-opts=...` 暴露(手册明示 `--glsl-shader-opts` 与 `/shader/param=value` 定向语法)【实证】。**关键修正: 1.33× 下 auto 公式 `floor(1440/1080+0.01)=1`,`region_range=0`,坐标扭曲退化为恒等 → 等价普通 bilinear**【实证,公式推导】。因此本机必须**手动 P=2**(或把公式改为 `ceil`),即 nearest 2×(1080p→"4K")后 1.5:1 双线性降采样。
5. **lua/E**: 与现有插件同机制——`mp.commandv("change-list","glsl-shaders","append",path)` 热挂/摘,按源分辨率自动启用(≤1080p 或 retro 风片源)【先验,项目内 anime4k/RIFE lua 已验证该原语】。

### 4. 难度与预估工作量

**难度: 2/5**(算法数学一页纸,风险全在 mpv hook 坐标语义与滤波器假设,均有手册兜底)。

| 项 | 人时 |
|---|---|
| 自写单 pass .hook(手动 4-tap 版 + 1-tap 版,auto/manual P 参数) | 1–1.5 |
| lua 键位热切换 + OSD 提示(复用现有插件骨架) | 0.5–1 |
| 1.33× A/B 观感评测(P=2 vs ewa_lanczossharp vs 关链)+ 微调 | 1–1.5 |
| **合计** | **2.5–4 人时**;若加"按源分辨率自动换链"规则 +0.5–1 |

### 5. @1440p + RTX2080S 性能量级估计

均为**数量级估计【估计】,非实测**:

- **本算法**: 1440p 全屏 ≈ 3.7M 像素 × (1–4 tap + ~15 ALU) ≈ 亚 0.1 ms 级,显存带宽 1 读(1080p 纹理)+ 1 写(1440p R8G8B8A8/F16);相对 RIFE(多路径 CNN 推理,帧耗数十 ms 级)增量**可忽略(<1% 预算)【估计】**。
- **ewa_lanczossharp**: EWA 极坐标核 radius≈3,每像素数十 tap + LUT 查表,ALU/tap 量级高本算法 1–2 个数量级;但绝对值也仅毫秒级以下,2080S 上两者都远够 165Hz。**性能不构成选型差异,选型只看观感。**
- **Anime4K v4 现有链**: 3–8 个 CNN pass、每 pass 数十 tap,比本算法贵 2 个数量级级;与 ewa_lanczossharp 感知等同【先验,项目冻结实验: 1080p→1440p 1.33× 重型方案感知收益不成立】。
- **观感预判(核心风险)**: sharp-bilinear 的卖点是"像素纯 + 无 wobble",针对**像素画**;1080p 动画本身已是平滑抗锯齿图像,1.33× 下 P=2 路线 = nearest 2× 再 1.5:1 双线性降采样,线条过渡带更窄、可能比 ewa_lanczossharp 更"脆"但**更易出锯齿/摩尔纹**【未证实,须 A/B】;对低分辨率/像素风片源(如 240p–720p retro 风)才是其主场。

### 6. 已知限制与风险

1. **auto 参数在 1.33× 退化为普通 bilinear**【实证,公式推导】——必须手动 P=2 或改 ceil,否则挂了等于没挂(白白多一 pass)。
2. **P 为单一标量**(经典实现 x/y 共用),且 auto 只按 **y 轴**比值计算(`outsize.y/InputSize.y`)【实证,源码】;非等比视窗(黑边/拉伸)时 x 轴比例失配。
3. **prescale 后降采样比 1.5:1** 下 bilinear 每 1.5 源 texel 才 1 tap,细密 1px 纹理(疏密纹理/字幕边缘)可能走样闪烁【未证实,感知层面】。
4. 对**非像素画源**(1080p 实拍/动画)的收益前提不成立,可能观感劣于 ewa_lanczossharp【未证实】。
5. **坐标映射**: pan/align/裁切/crop 需处理 `tex_offset`,恒等映射假设会被破坏【实证,手册有该原语;具体修正代码未写→未证实】。
6. mpv 绑定纹理默认滤波模式未证实(缓解: 手动 4-tap 版不依赖)【未证实】。
7. hook OUTPUT 在颜色管理之后采样,若与 HDR/色调映射链组合,需确认作用域语义;hook MAIN 变体可规避【未证实,本机 SDR 场景影响小】。
8. 无现成 mpv 移植可白嫖,兼容性(regression)全靠自己测——但代码量小,风险可控。
9. 社区检索存在覆盖盲区: GitHub 代码搜索 API 需鉴权未用,gist 搜索页受 JS 限制,"不存在 mpv 移植版"是**有界结论**(基于仓库/issue/已知合集检索)【未证实为穷尽】。

### 7. 可行性结论

**有条件可行** —— 技术上极易(公共领域源码 + 自写单 pass ≈ 2.5–4 人时、GPU 成本地板级),但 auto 参数在 1.33× 退化为普通双线性、须手动 P=2 实测,且对 1080p 动画源相对 ewa_lanczossharp 的观感收益未证实,只应作为"像素风/低分辨率片源"的可选预设按 A/B 定夺,而非 1080p 主链替换。

### 8. 证据链接列表(全部本次实际访问)

| # | URL | 取证结果 |
|---|---|---|
| 1 | https://raw.githubusercontent.com/libretro/glsl-shaders/master/interpolation/shaders/sharp-bilinear.glsl | HTTP 200,全文取得;Themaister/公共领域/核心公式 |
| 2 | https://raw.githubusercontent.com/libretro/glsl-shaders/master/interpolation/shaders/sharp-bilinear-simple.glsl | HTTP 200,全文取得;rsn8887 顶点预计算变体 |
| 3 | https://raw.githubusercontent.com/libretro/glsl-shaders/master/interpolation/sharp-bilinear-2x-prescale.glslp | HTTP 200,全文取得;两遍 stock: nearest 2×→linear |
| 4 | https://raw.githubusercontent.com/libretro/slang-shaders/master/pixel-art-scaling/shaders/sharp-bilinear.slang | HTTP 200,全文取得;公式同源 |
| 5 | https://api.github.com/repos/libretro/glsl-shaders | HTTP 200,仓库存在 |
| 6 | https://api.github.com/repos/libretro/glsl-shaders/git/trees/master?recursive=1 | HTTP 200,sharp-bilinear 族路径全列 |
| 7 | https://api.github.com/repos/libretro/slang-shaders/git/trees/master?recursive=1 | HTTP 200,pixel-art-scaling 路径族 |
| 8 | https://raw.githubusercontent.com/rsn8887/Sharp-Bilinear-Shaders/master/README.md | HTTP 200,作者对两遍/自动变体的权威描述 |
| 9 | https://api.github.com/repos/rsn8887/Sharp-Bilinear-Shaders/git/trees/HEAD?recursive=1 | HTTP 200,合集文件树 |
| 10 | https://api.github.com/search/repositories?q=mpv+sharp-bilinear | HTTP 200,total_count 0 |
| 11 | https://api.github.com/search/repositories?q=sharp+bilinear+mpv | HTTP 200,total_count 0 |
| 12 | https://api.github.com/search/repositories?q=sharp-bilinear | HTTP 200,7 结果均非 mpv |
| 13 | https://api.github.com/search/issues?q=%22sharp-bilinear%22+mpv | HTTP 200,7 结果无一为 mpv 移植 |
| 14 | https://api.github.com/repos/agyild/postscale-shaders | HTTP 404 Not Found |
| 15 | https://api.github.com/users/agyild/repos?per_page=100 | HTTP 200,仅 3 仓库,无缩放类 |
| 16 | https://raw.githubusercontent.com/haasn/libplacebo/master/src/include/libplacebo/renderer.h | HTTP 200,grep "prescal" 0 命中 → 无内建 prescale |
| 17 | https://api.github.com/repos/mpv-player/mpv/contents/DOCS/man/options.rst | HTTP 200(403KB),user-shader 接口/HOOK 点/OUTPUT fixed/--glsl-shader-opts 实证 |
| 18 | https://api.github.com/repos/occivink/mpv-image-viewer/git/trees/master?recursive=1 | HTTP 200,grep sharp/bilinear 0 命中 |
| 19 | https://gist.github.com/search?q=sharp-bilinear+mpv | HTTP 200,无可解析结果(JS 限制,标注局限) |
| 20 | 本仓库 docs/研究素材/nearest.md | 内部先验: mpv 38 核表无 sharp-bilinear、bloc97/Anime4K 对照 |

*未访问/未取得: GitHub 代码搜索(需鉴权)、sharp-bilinear-scanlines 原文(仅树中确认存在)——均已在正文标注。*
