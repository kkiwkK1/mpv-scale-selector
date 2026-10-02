## xBR(xBR Level 1-6 / xBRZ)

> **初稿归档，非最终验收依据。** xBR 与 xBRZ 不作同算法处理；选定源码的许可须分别核对，成本推算不是实测。以 [勘误说明](../勘误说明.md) 与 [整合报告](../可行性研究报告.md) 为准。

> 研究日期: 2026-10-02 / 环境: 2560×1440 @ RTX 2080 SUPER 8G / mpv v0.40 / 1080p 片源为主 / RIFE 常驻共享 GPU 预算
> 所有"已验证"标注的 URL 均在本次研究中实际 curl 访问过(以 api.github.com / raw / sourceforge 形式);无法核实的部分一律标注**未证实**。

---

### 1) 算法本体与原理(结构、pass 数、复杂度量级)

**起源与作者**: xBR("scale by rules")由 Hyllian(Jorge Cieslik, GitHub 用户 Hyllian,已验证存在:api.github.com/users/hyllian)于 2011 年提出,在 libretro 社区迭代出 xBR lv1→lv4、Super xBR、xBR-hybrid 等变体;xBRZ 是 Zenju 的 C++ CPU 重写版(Debian/MAME/DOSBox 系广泛使用,原发布于 SourceForge)。

**核心原理**:
- 对每个源像素取 3×3 邻域(lv1)或扩展邻域(已验证 libretro 多 pass 版 pass0 的注释网格为 A1 B1 C1 / A0 A B C C4 / D0 D E F F4 / G0 G H I I4 / G5 H5 I5,即 7×5 外扩),在 YUV 空间算颜色距离(已验证 shader 源码内嵌 yuv 矩阵 0.299/0.587/0.114 与 y/u/v 权重 48/7/6)。
- 按方向规则判断"哪条边是真实边缘"(lv2 检测 4 个对角方向,lv3 检测 6 个方向——已验证 slang-shaders/edge-smoothing/xbr/README.md 原文描述),对边缘两侧像素做受控混合(blending)或硬替换(noblend 变体),输出 2×(或 3×/4×)规则化像素块。
- 关键特性:输出像素块必须落在 3×3 邻域 min/max 内,按构造不产生振铃(与 lanczos 类插值器本质区别)。

**级别谱系(pass 数为 libretro 实现口径)**:
| 变体 | 方向数 | 典型实现结构 | 已验证出处 |
|---|---|---|---|
| xBR lv1 | 4 | 2 pass(pass0 算边缘 flag 打包进颜色通道,pass1 按 flag 混合)或单 pass | glsl-shaders/xbr/2xBR-lv1-multipass.glslp(已验证 shaders=2) |
| xBR lv2 | 4 + 角点规则 | 单 pass 2×(standalone)或 6 pass 链(linearize→flag→3×主 pass→b-spline-x/y→delinearize) | slang-shaders xbr-lv2-standalone.slang(9975B)、xbr-lv2.slangp(shaders=6,已验证) |
| xBR lv3 | 6 | 同上,主 pass 3× | xbr-lv3.slangp / xbr-lv3-multipass(pass0+pass1)已验证 |
| xBR mlv4 | 多向 lv4 | 4 pass(1×flag → 1×flag → 2×主 pass → 终 pass) | glsl-shaders/xbr/xbr-mlv4-multipass.glslp(shaders=4,已验证) |
| Super xBR | 视频向变体 | 2-6 pass + 软混合 + deposterize(专门为视频/非像素画内容设计) | glsl-shaders/xbr/super-xbr-6p.glslp 等已验证 |
| xBRZ | Zenju C++ 规则集(40+ 精调规则) | CPU 参考 2×-6×;GLSL 移植为单 pass 2×/4×/5×/6× | janisozaur/xbrz 仓库 xbrz.cpp/h(已验证);slang-shaders edge-smoothing/xbrz/{2,4,5,6}xbrz.slang(已验证,4xbrz.slang 19158B) |
| xBRZ FreeScale | 任意缩放比变体 | 单 pass,scale_type=viewport(任意目标分辨率) | xbrz-freescale.slangp(已验证:单 shader,scale_type0=viewport) |
| xBR lv5/lv6 | —— | **未证实**:libretro 仓库中未发现独立 lv5/lv6 GLSL 实现;任务标题中的 "Level 1-6" 推测混入了 xBRZ 的 2×-6× 缩放倍数谱系(2xbrz~6xbrz 已验证存在),此解释**未证实**仅合理推测 | |

**复杂度量级**: 单 pass xBR lv2 每输出像素约 7-12 次邻域采样 + 分支方向规则 + 少量 YUV 距离运算,约为 bilinear 每像素成本的 10-20 倍(量级估计,非实测);xBRZ GLSL 版规则更多(4xbrz 19KB 源码),分支更重;多 pass 版把 flag 计算与着色拆开后单 pass 更轻但增加一次全屏纹理读写。总体属"规则型 shader 中等偏重",远轻于 FSRCNNX/Anime4K CNN 类神经 shader。

---

### 2) 权威实现/开源仓库与协议(全部实际访问验证)+ 社区 mpv 移植查证

**权威实现(已验证存在)**:
- libretro/glsl-shaders(GLSL 老仓库):`xbr/` 目录含 2xBR-lv1-multipass、xbr-lv2、xbr-lv2-noblend、xbr-lv3、xbr-lv3-multipass、xbr-mlv4-multipass、super-xbr-{2p,3p-smoother,6p,6p-adaptive,6p-small-details}、super-{2,4,8}xbr-3d、xbr-hybrid 等 glslp。已验证:
  - https://api.github.com/repos/libretro/glsl-shaders(HTTP 200)
  - https://api.github.com/repos/libretro/glsl-shaders/contents/xbr(目录清单)
  - https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/xbr-lv2.glsl(10536B,Hyllian xBR-lv2,#version 130)
  - https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/2xBR-multipass/2xbr-lv1-c-pass0.glsl(pass0 邻域网格与 flag 打包)
  - https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/2xBR-multipass/2xbr-lv1-c-pass1.glsl(unpack_info + mix 混合,绑 OrigTexture)
  - https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/xbr-mlv4-multipass.glslp(shaders=4 全文)
- libretro/slang-shaders(slang 新仓库):`edge-smoothing/xbr/`(xbr-lv1/lv2/lv3-standalone、xbr-lv2-hd[XBR_RES 1.0-5.0 任意内部倍率,13517B]、multipass 目录、super-xbr、hybrid-jinc2-xbr-lv2)与 `edge-smoothing/xbrz/`(2x/4x/5x/6xbrz + xbrz-freescale + freescale-multipass)。已验证:
  - https://api.github.com/repos/libretro/slang-shaders(HTTP 200)
  - https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr 与 .../xbrz(目录清单)
  - https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/shaders/xbr-lv2-standalone.slang(9975B,MIT 许可证头,PARAM 化阈值)
  - https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/shaders/xbr-lv2-hd.slang(13517B)
  - https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbrz/shaders/2xbrz.slang(13578B,含 Zenju xBRZ GPL 许可证头,注明取自 Desmume 源码)
- xBRZ 参考 C++(Zenju):SourceForge 原发布页 https://sourceforge.net/projects/xbrz/(HTTP 200 已验证);git 镜像 https://api.github.com/repos/janisozaur/xbrz(已验证含 xbrz.cpp/xbrz.h/Changelog.txt)
- C 语言参考实现:https://api.github.com/repos/Treeki/libxbr-standalone(HTTP 200 已验证)
- 注:raw.githubusercontent.com 在本机环境间歇性 TLS 失败(curl exit 35,已实测发生),批量拉取建议走 api.github.com contents 接口(base64)或重试。

**协议**: libretro 端为 glslp/slangp 预设描述多 pass 链(shader0..N,scale_type/scale/filter_linear/alias,float_framebuffer),slang 端额外支持 push_constant 参数与 `#pragma parameter`。mpv 端协议见第 3 节。

**社区 mpv 移植查证结果**:
- GitHub 仓库搜索 `mpv xBR`、`xbr glsl`、`xbr user shader mpv`、`xbr pixel art scaling`(api.github.com/search/repositories,已验证执行):**未发现 Hyllian xBR lv1-lv4 / xBRZ 全功能版的现成 mpv user-shader 移植**。唯一 xBR 家族命中:kostyk348/fca(1 star)的 `shaders/fca_xbr2.glsl`(3033B,已验证内容)——这是一个**xBR 启发的模糊细胞规则 2× 上采样**(//!HOOK MAIN 单 pass,//!WIDTH HOOKED.w 2 *),非 Hyllian xBR 本体。
- bjin/mpv-prescalers(已验证目录):nnedi3/ravu 系列,无 xBR。
- 注意:GitHub code search API 需要认证、gist/HTML 搜索页被反爬拦截,本次未能做全量代码级搜索——"mpv 无现成 xBR 移植"这一结论仅覆盖仓库级搜索,**未证实为穷尽性结论**。
- agyild(已知 mpv shader 移植作者)名下仓库(api.github.com/search/repositories?q=user:agyild 已验证):未发现 xBR 相关(其 Bloom 等为其他算法)。bloc97 为 Anime4K 作者,与 xBR 无关。

---

### 3) mpv 集成路径评估

**结论:选路径 A(user-shader 多 pass 链)+ E(lua 按源分辨率热切换);vo=gpu 与 gpu-next 双兼容。**

mpv user-shader 协议要点(全部对照 mpv master 手册 options.rst 原文验证,https://raw.githubusercontent.com/mpv-player/mpv/master/DOCS/man/options.rst,403KB 已拉取):
- 单文件多 pass:一个 .glsl 文件可含多个 HOOK 块;同一 hook 点的多个 pass 按添加顺序依次执行(手册原文:"all of the passes that have hooked into it will run, in the order they were added by the user")。→ libretro 的 pass0→pass1 链**可逐 pass 直译**。
- `SAVE <name>` / `BIND <name>`:pass 结果可存为命名纹理供后续 pass 绑定。→ **libretro 多 pass 版的 c1..c4/flag 信息纹理(即 pass0 打包的边缘 flag,rgba8 足够,libretro 正是 8bit 打包)在 mpv 下可完整表达**,这是本算法移植的核心可行性问题,答案为"能"。
- `WIDTH/HEIGHT` 支持 RPN 表达式(如 `HOOKED.w 2 *`),且只有标注 resizable 的纹理可被 pass 变换尺寸:RGB/LUMA/CHROMA/NATIVE/MAINPRESUB/MAIN resizable;PREKERNEL/POSTKERNEL/SCALED/OUTPUT **fixed**。→ xBR 的 2×/3× 预放大必须挂在 **MAIN**(RGB、上采样前、resizable)而非 OUTPUT/POSTKERNEL。Anime4K 系已长期采用同型挂点模式,模式成熟。
- "OrigTexture"(原始 1× 源)等价物:pass0 HOOK MAIN 只 SAVE 到自定义名(不覆盖 MAIN),后续 pass 即可同时 `BIND MAIN`(1× 原始)+ `BIND XBRFLAGS`,与 libretro alias 机制语义一致。
- `//!COMPUTE` 存在但非必需;xBR 规则分支重、邻域仅 3×3~7×5,fragment shader 在 2080S 上足够,compute 化收益低、风险高,不建议。
- PARAM 块支持可调参数(gpu-next 支持更多特性),对应 libretro `#pragma parameter` 的阈值暴露。

**挂点与链结构建议(1080p→1440p)**:
1. 推荐:单 pass 移植 `xbr-lv2-hd`(XBR_RES 可调)或 `xbrz-freescale`(任意目标比原生支持,已验证 scale_type=viewport)——天然适配 1.33× 非整数链;挂 MAIN,`//!WIDTH HOOKED.w` 与目标比联动或直接 2× + 交回内建 scale。
2. 备选:xBRZ 4×/6× 整数预放大 + 内建 ewa 收尾(适合低分辨率真像素画源,如 240p/480p,1080p→1440p 不适用整数链)。
3. 多 pass lv3/mlv4 链可直译(SAVE/BIND 已验证可行),但对本机 1.33× 场景收益存疑,优先级最低。
- 不选 B(仅靠 gpu-next 内建):内建无任何 xBR 类内核(已验证 --scale 列表:bilinear/lanczos/ewa_lanczos[sharp/4sharpest]/mitchell/hermite/catmull_rom/oversample/linear 等,无 xBR);B 的价值仅是"user-shader 在 gpu-next 下同样生效",作为运行环境而非集成路径。
- 不选 C(--vf=libplacebo/lavfi):libplacebo/lavfi 滤镜链中**未证实**存在 xBR 滤镜(lavfi 无此 filter 的说法**未证实**,未见任何证据);且 vf 路径无法热切换、性能/延迟更差。
- 不选 D(内建内核):同上,无此内核。
- E(lua):负责按源分辨率门控(仅 <1440p 源启用)、RIFE 冲突时的链切换、键位菜单;与既有 anime4k 冻结实验的 lua 框架可复用。

---

### 4) 难度与工作量

| 任务 | 难度(1-5) | 人时 |
|---|---|---|
| 单 pass 移植:xbr-lv2-standalone / xbrz-freescale → mpv hook(纹理 API 换名 NAME_texOff、uniform 映射、hook() 包装) | 2 | 3-5h(含 gpu/gpu-next 双验证) |
| 多 pass 直译:lv1-c(2 pass)或 mlv4(4 pass),SAVE/BIND flag 纹理 | 3 | 4-8h |
| xBRZ 4×/6× slang 移植(19KB 分支重源码) | 3 | 4-8h |
| 1080p→1440p 非整数适配(XBR_RES/freescale 调参、阈值 PARAM 化) | 2-3 | 2-4h |
| lua 门控/热切换/菜单接入(复用既有框架) | 1-2 | 2-3h |
| A/B 盲测与冻结决策 | 1 | 2-4h |
| **合计(单 pass 最小可用)** | **2/5** | **≈1 人天** |
| **合计(完整家族 + lua + 评测)** | 3/5 | **≈2-3 人天** |

前置知识门槛低:无神经 shader 权重搬运问题(对比 Anime4K/FSRCNNX),纯 GLSL 规则代码直译。

---

### 5) @1440p + RTX 2080S 性能量级估计(与 ewa_lanczossharp、Anime4K v4 相对比较)

以下为**量级推算,非实测**(标记:全部为估计):
- xBR lv2 单 pass(1080p→2× 预放大至 3840×2160 再收 1440p):每输出像素 ~10 采样+分支,2080S 估计 **1.5-3 ms/帧**;
- xBR lv3 多 pass 链:估计 **3-6 ms/帧**;xBRZ 4×(27MP 输出、重分支):估计 **5-10 ms/帧**,接近超支;
- xbrz-freescale(直出 1440p):估计 **2-4 ms/帧**;
- 参照系:ewa_lanczossharp 1080p→1440p ≈ 1-2 ms(内建,已冻结实验背景);Anime4K v4 Mode A/B 1080p→1440p ≈ 3-6 ms(社区经验值,**未证实**精确数)。
- 判断:xBR 单 pass 成本 ≈ ewa 的 2-3 倍、≈ Anime4K v4 的一半,与 RIFE 同开 8G/2080S 预算**可容纳**(RIFE 仍占大头);但按已冻结先验(1080p→1440p 仅 1.33×、重型方案感知等同 ewa),xBR 的**感知收益同样大概率不成立**——除非源是真·低分辨率像素画风格(见第 6 节)。

---

### 6) 已知限制与风险

1. **非整数缩放错配(最大风险)**:xBR 全家族按整数倍规则设计,1.33×(1080p→1440p)直接套用会产生不均匀像素块/摩尔纹;必须用 xbr-lv2-hd(XBR_RES)或 xbrz-freescale 类任意比变体,或 2× 预放大+平滑收尾(引入额外模糊,违背 xBR 初衷)。
2. **内容假设错配**:xBR 假设输入是干净的 1px 网格像素画;对 1080p 动画/实拍(压缩噪声、胶片颗粒、抗锯齿边缘)会把噪声判为边缘,产生描边化/色渗伪影。Super xBR(软混合+deposterize)正是为此设计的缓解方案,但代价是更"糊"。
3. **与既有先验冲突**:本机冻结结论"重型方案感知收益不成立"对 xBR 大概率同样适用;xBR 的生态位应是"真像素画/低分辨率源"门控启用,而非默认链。
4. **许可证混装**:Hyllian xBR 系为 MIT(已验证许可证头),xBRZ 为 GPL(Zenju,已验证头注)——GPL shader 源码引入个人配置无碍,若随插件仓库分发需注意传染性。
5. **gpu/gpu-next 行为差异**:手册明确 gpu-next 不存在 MAINPRESUB(按 MAIN 处理)且 PARAM 特性子集不同;直译 libretro slang(push_constant)时需改写为 mpv PARAM/常量。gpu-next 下需实测一轮。
6. **环境风险**:本机到 raw.githubusercontent.com 的 TLS 间歇失败(实测 exit 35),shader 获取需重试或镜像;github 搜索接口对 code/gist 级检索不可用,"无现成移植"结论存在盲区(见第 2 节)。
7. **参数敏感**:XBR_EQ_THRESHOLD/XBR_LV2_COEFFICIENT 等阈值按像素画调校,视频内容需重新调参并 PARAM 化暴露,调参工作量易被低估。

---

### 7) 可行性结论

**有条件可行** —— SAVE/BIND 对 c1..c4 flag 纹理传递的表达已被 mpv 协议原文证实、移植本身是机械劳动(≈1-3 人天),但它只对"真·低分辨率像素画源"有明确收益,在 1080p 动画默认链上受 1.33× 非整数与既有冻结先验双重压制,只能作为 lua 门控的场景化 preset 存在。

---

### 8) 证据链接列表(全部实际访问过)

**libretro GLSL(glsl-shaders)** — 均以 api.github.com 端点访问(HTTP 200):
1. https://api.github.com/repos/libretro/glsl-shaders
2. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr
3. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/xbr-lv2.glsl
4. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/2xBR-multipass/2xbr-lv1-c-pass0.glsl
5. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/2xBR-multipass/2xbr-lv1-c-pass1.glsl
6. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/shaders/super-xbr/super-xbr-pass0.glsl / super-xbr-pass1.glsl
7. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/xbr-mlv4-multipass.glslp
8. https://api.github.com/repos/libretro/glsl-shaders/contents/xbr/xbr-lv2.glslp(经 raw 成功拉取过一次:2xBR 同仓库 raw 在另一次访问中返回过 xbr-lv2.glslp 内容)

**libretro slang(slang-shaders)**:
9. https://api.github.com/repos/libretro/slang-shaders
10. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr
11. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/shaders(xbr-lv1/lv2/lv3-standalone、xbr-lv2-hd、multipass 目录清单)
12. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/shaders/xbr-lv2-standalone.slang
13. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/shaders/xbr-lv2-hd.slang
14. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/README.md
15. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/xbr-lv2.slangp(6 pass 链全文)
16. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbr/shaders/xbr-lv3-multipass/xbr-lv3-pass0.slang
17. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbrz(2x/4x/5x/6xbrz + freescale 预设清单)
18. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbrz/shaders/2xbrz.slang / 4xbrz.slang
19. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbrz/xbrz-freescale.slangp(单 pass、scale_type=viewport 全文)
20. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing/xbrz/xbrz-freescale-multipass.slangp(3 pass 全文)

**xBRZ 参考实现(C++)**:
21. https://sourceforge.net/projects/xbrz/(HTTP 200)
22. https://api.github.com/repos/janisozaur/xbrz 与 /contents/(xbrz.cpp、xbrz.h、Changelog.txt)
23. https://api.github.com/repos/Treeki/libxbr-standalone(HTTP 200)
24. https://api.github.com/users/hyllian(作者账号存在)

**mpv 协议依据**:
25. https://raw.githubusercontent.com/mpv-player/mpv/master/DOCS/man/options.rst(--glsl-shaders 全协议:HOOK/BIND/SAVE/WIDTH-HEIGHT RPN/WHEN/COMPONENTS/COMPUTE/PARAM、hook 点 resizable/fixed 清单、vo=gpu-next 差异注记;--scale 内核清单无 xBR)

**mpv 移植查证(搜索执行记录)**:
26. https://api.github.com/search/repositories?q=mpv+xBR(唯一 xBR 家族命中 kostyk348/fca)
27. https://api.github.com/repos/kostyk348/fca 与 /contents/shaders/fca_xbr2.glsl(现存的 xBR 启发 mpv user-shader,//!HOOK MAIN 单 pass 2×)
28. https://api.github.com/repos/bjin/mpv-prescalers(确认无 xBR)
29. https://api.github.com/search/repositories?q=xbrz、q=xbr+glsl、q=user:agyild(均无 Hyllian xBR / xBRZ 的 mpv 移植)

**环境观测(非仓库)**:
30. raw.githubusercontent.com 本机间歇 TLS 失败(curl exit 35,多次复现;成功与失败均有记录)→ 建议 api.github.com contents 兜底。

**未证实事项汇总**: ① "mpv 全网无现成 Hyllian xBR/xBRZ 移植"仅为仓库级搜索结论,代码/gist 级检索不可用;② lavfi/libplacebo 滤镜链无 xBR;③ xBR lv5/lv6 作为独立 GLSL 实现的存在性;④ 第 5 节全部性能数字(推算值);⑤ Anime4K v4 的精确毫秒数。
