## Anime4K(v4 官方链)

> **初稿归档，非最终验收依据。** 旧项目失败不能泛化成 stock Anime4K 无益，也不能规定仅适合≤720p；用户仍偏好 stock。请先读 [勘误说明](../勘误说明.md) 与 [整合报告](../可行性研究报告.md)。

> 研究日期: 2026-10-02 / 环境: 2560×1440 屏 @ RTX 2080 SUPER 8G / mpv v0.40.0-393-gad59ff1b4(实测 `--version`)/ 1080p 片源为主 / RIFE 常驻共享 GPU 预算
> 所有"已验证"标注的 URL 均在本次研究中实际 curl 访问过;本机实证均来自 `%APPDATA%/mpv/` 只读检查与 `D:/MPV/mpv.exe` 实测;无法核实的部分一律标注**未证实**。
> 先验引用: 同目录上一项目《Anime4K 1440p 优化实验(已冻结)》(`D:/workspace/小项目/mpv插件/anime4k插件优化/docs/验证报告.md`,已读取原文)。

---

### 1) 算法本体与原理(结构、pass 数、复杂度量级)

**谱系**: Anime4K 由 bloc97 于 2019 年发起。v1(2019,小型 2D CNN 上采样)→ v2(梯度重建 "push" 算法,libretro 现存移植即此代)→ v3.x(深度 CNN,3×3 卷积栈 + 亚像素重排)→ **v4.0(2021-07,当前官方形态)**。v4 不是单一算法,而是**模块化 CNN 算子库 + 官方推荐的链组合**:去振铃(Clamp)、线条/细节重建(Restore CNN)、2× 上采样(Upscale CNN)、去噪(Denoise CNN/Bilateral)、线条处理(Thin/Darken/Deblur)各自独立成 .glsl 文件,按官方模板串成 Mode A/B/C 等 preset。

**本机资产实测**(39 个 .glsl,`%APPDATA%/mpv/shaders/`,与官方 v4.0.1 release zip **逐字节一致**,cmp 39/39,见 §2):关键文件 pass 数(`//!HOOK` 计数)与版本:

| 文件 | pass 数 | 字节 | DESC 版本 | 备注 |
|---|---|---|---|---|
| Anime4K_Clamp_Highlights.glsl | 3 | 2,884 | v4.0 | 全家唯一非 MAIN hook(1×PREKERNEL + 2×MAIN),DESC 名为 De-Ring-Compute-Statistics |
| Anime4K_Restore_CNN_M.glsl | 8 | 35,916 | v4.0 | 去压缩噪声/线条恢复 |
| Anime4K_Restore_CNN_VL.glsl | 17 | 144,075 | v4.0 | 最常被官方链引用的重型 Restore |
| Anime4K_Restore_CNN_Soft_M.glsl | 8 | 36,016 | v4.0 | Soft 变体(Mode B 用) |
| Anime4K_Upscale_CNN_x2_M.glsl | 9 | 37,685 | v3.2 | 9 条 WHEN 全部为 `OUTPUT.w MAIN.w / 1.200 > OUTPUT.h MAIN.h / 1.200 > *` |
| Anime4K_Upscale_CNN_x2_VL.glsl | 18 | 146,743 | v3.2 | 同上 1.2× 门控 |
| Anime4K_Upscale_Denoise_CNN_x2_VL.glsl | 18 | 146,811 | v3.2 | 上采样+去噪一体(Mode C 用) |
| Anime4K_AutoDownscalePre_x2.glsl | 1 | 1,596 | v4.0 | `return HOOKED_tex(HOOKED_pos)`,WIDTH/HEIGHT=OUTPUT,即**单次双线性抽头**降采样;WHEN = OUTPUT<2×NATIVE 且 OUTPUT>1.2×NATIVE |
| Anime4K_AutoDownscalePre_x4.glsl | 1 | 1,604 | v3.2 | 同型,4×/2.4× 阈值 |
| 其余(Thin_HQ=8、Darken_HQ=5、Upscale_DTD_x2=18、Denoise_Bilateral=1 等) | — | — | v3.2 | 可选辅助算子,官方 A/B/C 链未用 |

**核心原理**:
- CNN 权重以 `mat4` 数组**硬编码在 GLSL 内**(VL 级文件约 144KB 全是权重),无外部模型文件;激活为 CReLU(拼接 ReLU 对),末端 **Depth-to-Space** 亚像素重排实现 2×(末 pass `//!WIDTH conv2d_last_tf.w 2 *`)。
- 中间结果经 `//!SAVE <name>` 存命名纹理、后续 pass `//!BIND <name>` 绑定,单文件多 pass,全部 `//!HOOK MAIN`(除 Clamp 的 1 个 PREKERNEL)。
- **//!COMPUTE:0 个**(39 文件 grep 计数为零)——全部为 fragment shader,primer 中"COMPUTE 需确认 vo 要求"的疑虑对本资产直接解除。
- **WHEN 门控**是链自适应的关键:Upscale 系所有 pass 仅在输出 >1.2× 源时运行 ×2 CNN;AutoDownscalePre 在输出处于 1.2×~2× 源区间时把 2× 中间纹理拉回输出尺寸。

**1080p→1440p(1.33×)实际执行路径推演**(按 WHEN 逻辑,标注:**推演**,先前冻结项目做过指令级行为核对但未对本表逐行复核):Mode A (HQ) = Clamp(3)+Restore_VL(17)+Upscale_VL(18)+AutoDownscalePre_x2(1)+AutoDownscalePre_x4(0,条件不满足)+Upscale_CNN_x2_M(0,1.33× 已被 AutoDownscalePre 拉平后不满足 1.2× 门)≈ **39 pass/帧**,中间纹理峰值 2160p(2×1080p),链尾以单次双线性抽头收到 1440p(冻结项目已源码级核对该收尾行为)。

**复杂度量级**: 3×3 卷积、通道数 3→56→…→8 量级递增,单输出像素数千~数万 MAC;VL 级链在 1080p→2160p 中间分辨率下单帧约百 GFLOP 量级(**估算,未实测**),对 FP32 ~10 TFLOPS 的 2080S 属算力富余、瓶颈在中间纹理带宽与 pass 数。

---

### 2) 权威实现/开源仓库与协议(全部实际访问验证)+ 社区 mpv 版本查证

**权威实现 = 官方仓库本身,且官方形态就是 mpv user-shader GLSL**(不存在"移植"环节):

- **bloc97/Anime4K**(https://github.com/bloc97/Anime4K):api 实测 HTTP 200,**21,454 stars,MIT 协议**,default_branch=master,最后 push 2024-08-17(上游基本停更)。release 列表(api 实测):最新 **v4.0.1(2021-09-17)**,另有 v4.0.0 / v4.0.0-RC / v3.2 / 3.1 / v3.0。
  - `contents/glsl` 实测 6 个子目录:Deblur / Denoise / Experimental-Effects / Restore / Upscale+Denoise / Upscale;Restore、Upscale 目录逐文件核对,**文件名与字节数和本机 39 文件一致**(如 Restore_CNN_M 35,916B、Upscale_CNN_x2_M 37,685B)。
  - **release 资产实测下载**:https://github.com/bloc97/Anime4K/releases/download/v4.0.1/Anime4K_v4.0.zip(HTTP 200,776,303B)——解包恰为 39 个 .glsl,与本机 `%APPDATA%/mpv/shaders/` **cmp 逐字节 39/39 全同**。本机即官方 v4.0.1 发行版本体。
  - 注:master 分支 glsl/ 树比 v4.0.1 zip 多出 GAN(Restore_GAN_UL/UUL、Upscale_GAN_x2_M/S)、3DGraphics_AA 等**实验性**文件(2021-09 后新增),本机不含;其质量定位**未证实**。
- **官方 mpv 安装文档**(README 实测指向):`md/GLSL_Instructions_Windows_MPV.md`(HTTP 200,3,193B)——步骤为放 shaders 文件夹 + 粘贴模板 mpv.conf/input.conf;模板分 `Template/GLSL_Windows_High-end`(本机同款)与 Low-end。
  - 官方 High-end 模板 mpv.conf(HTTP 200):默认 `glsl-shaders=...Clamp_Highlights;Restore_CNN_VL;Upscale_CNN_x2_VL;AutoDownscalePre_x2;AutoDownscalePre_x4;Upscale_CNN_x2_M`(Mode A HQ)。
  - 官方 High-end 模板 input.conf(HTTP 200):CTRL+1..6 = Mode A/B/C/A+A/B+B/C+A (HQ),CTRL+0 清空;注释明确 Mode A 优化 1080p、B 720p、C 480p。
  - **本机 input.conf 比对**:`change-list glsl-shaders set "..."` 链字符串与官方模板排序后 diff,6/6 逐一相同;本机多出的 1 条为 F6 键,**重复绑定官方 CTRL+4 的 Mode A+A 链**(额外便利键,非自创链)。即本机热切换现状 = 官方模板逐字符落地。

**社区 mpv 版本查证**(github 仓库搜索,api 实测执行):
- `mpv anime4k` 搜索:结果全为配置整合包/GUI/移植壳——mikigal/Anime4K-GUI、ThoughtfulDev/Anime4K(JS 版)、azxcvn/mpv-android-anime4k、mhtvsSFrpHdE/AnimeAnyK-mpv、luoxue03/mpv-lazy 等;它们**搬运的仍是 bloc97 官方 GLSL**,无独立算法实现。
- `anime4k glsl mpv` 搜索:miyakogi/Anime4K-mpv-glsl(0 star)等边缘仓库,量级可忽略。
- **agyild**(已知 mpv shader 作者,api 实测 `user:agyild`):仅 cipetpet、ivirzivir 两仓库,**无 Anime4K 相关**。
- **libretro**:slang-shaders 全树(api git/trees recursive,HTTP 200,1.87MB)grep anime4k 仅 6 条路径,全部在 `sharpen/` 下(`Anime4k.slangp` + anime4k-compute-gradient/lum、push、pushgrad-weak 四个 slang)——为 **v2 代梯度 push 算法**的老移植,非 v4 CNN 链;glsl-shaders 全树 **0 命中**。
- 局限:GitHub code search API 需认证(HTTP 401 实测),未做代码级穷尽检索;"社区无独立 v4 全功能移植"的结论仅覆盖仓库级搜索,**未证实为穷尽性结论**(但官方即 mpv GLSL,该结论实际影响极小)。

---

### 3) mpv 集成路径评估(对照 primer A–E)

**结论:路径 A(user-shader)+ E(lua 热切换),且本机已全量就位、无任何待做集成。**

- **为什么必然是 A**:官方实现本身就是 `//!HOOK MAIN` user-shader,官方安装文档的唯一路径就是 `~~/shaders/` + `glsl-shaders` 列表;其他路径都属于"绕开官方形态的重写"。
- **E(lua)的必要性**:本机需求是"按源分辨率自动换链"。`change-list glsl-shaders set/clr` 的热切换已被官方模板键位(=本机 CTRL+1..6)日常使用证明;lua 运行时改 property 的自动换链器在冻结项目中**工程面全部验证通过**(H3 成立,含幂等安装/卸载、缓存、17 格实机矩阵)。
- **vo 兼容**:本机 mpv v0.40 实测 `--vo=help` 首位为 gpu-next(libplacebo v7.357.0 编入),冻结项目渲染日志亦为 gpu-next——官方链在本机 **gpu-next 下实测满速运行**(见 §5)。mpv 0.39 起默认 vo 切换的官方 changelog 声明**未证实**(未查 release notes),但"本机默认 gpu-next 且链正常工作"为直接实证。mpv 手册 options.rst(master,HTTP 200,403KB 实测)对 `--glsl-shaders` 的定位是"可注入渲染管线几乎任意点的自定义 fragment shader",语法稳定性官方标注 warning "not stable yet"——但 v4 资产 2021 年起在历版 mpv 上持续可用,**未证实**存在破坏性变更。
- **//!COMPUTE**:零块(§1 已实测),对 vo 无额外要求;无需 compute 化(fragment 方案在 2080S 已满速)。
- **不选 B(仅靠 gpu-next 内建)**:内建 scale/dscale 无任何 Anime4K 类内核,内建化=重写;gpu-next 的角色只是"user-shader 在其下同样生效"的运行环境。
- **不选 C(--vf=libplacebo/lavfi)**:lavfi/libplacebo 滤镜链中存在 Anime4K 滤镜**未证实**(无任何证据);vf 路径不可用 lua property 热切换、且 RIFE 已占用 vf 位置,叠加无益。
- **不选 D(内建内核)**:同 B,无此类内核。
- **与 RIFE 共存**:RIFE 在 vf 层(`vf-add=@rife:vapoursynth`)、Anime4K 在渲染层(glsl-shaders),层级正交;冻结项目实测 1080p 真实片源下 **A 档与 RIFE 同开满速 48fps**。
- **接入要点(若重新部署,如迁移机器)**:① 39 文件入 `~~/shaders/`;② 粘贴官方 High-end 模板两段;③ 如需按源分桶自动换链,复用冻结项目 lua 换链器;④ 建议加 `gpu-shader-cache-dir=~~cache/shaders` 缓解冷编译(冻结项目已实测该选项 v0.40 生效)。

---

### 4) 难度与预估工作量(人时)

| 工作项 | 难度(1-5) | 人时 |
|---|---|---|
| 基础集成(文件+模板键位) | — | **0(已完成,本机现状即官方模板)** |
| lua 按源分辨率自动换链(仅 ≤720p 源启用神经链的分桶规则) | 1 | 4–8(复用冻结项目换链器,改分桶一行 + 回归验证) |
| 档位/性能压测(RIFE 同开最坏场景矩阵) | 1–2 | 2–4 |
| 文档与取证 | — | 2 |
| **合计** | **1** | **约 8–14 人时;若维持现状仅做文档,约 2 人时** |

重写(路径 B/C/D 或自研)无任何必要——官方资产逐字节在手、协议原生就是 mpv。

---

### 5) @1440p + RTX 2080S 性能量级估计

- **实测基线(本机,一手)**:冻结项目 17 格实机矩阵,Mode A/B/off 全部满速,1080p 真实文件 48fps(含 RIFE 同开);实测 mpv v0.40 + gpu-next。
- **pass 数量级**:Mode A (HQ) 静态上限 3+17+18+1+1+9 = 49 pass/帧;1080p→1440p 按 WHEN 推演实际 ≈39 pass/帧(**推演**)。对比 `ewa_lanczossharp`(单次内建多重采样内核,近零额外 pass),重约 **40×**(pass 数口径的量级对比,非毫秒实测)。
- **绝对量级**:VL 级 CNN 百 GFLOP/帧量级(§1 估算)+ 多张 2160p 级 RGBA 中间纹理读写,瓶颈在带宽而非算力;24fps 动画富余极大,60fps+RIFE 最坏组合本机实测仍满速。显存增量:数张 3840×2160 RGBA8/16F 纹理,约百 MB 级(**估算,未实测**),8G 卡与 RIFE 共存实测无碍。
- **与 Anime4K v4 现有链相对比较**:本研究对象**就是**现有链,无差异可言。可调路径:官方 S/M/L 档位线性减负(Restore_CNN_S=17KB/Upscale_S=18KB,pass 同数但通道窄);或按 §4 的 WHEN 洞察裁链。
- 结论:**性能不是本方案的约束**(在 24fps 动画 + RIFE 同开的实际负载下)。

---

### 6) 已知限制与风险

1. **感知收益天花板(最大风险,已实测证伪)**:本机先验——1080p→1440p 总放大仅 1.33×,神经 ×2 重建的高频被链尾 2160→1440 收尾降采样结构性衰减;冻结项目实测 ewa_lanczossharp 与重型神经链感知等同,ArtCNN 替代路线亦"几乎不可见"。**神经链甜蜜点是 ≤720p 源(恰好 2×、零衰减)**,本机片库 1080p 从未命中。
2. **链尾质量短板**:AutoDownscalePre 系列是单次双线性抽头(`return HOOKED_tex(HOOKED_pos)`,源码级核对),1.2×–2× 区间的收尾插值质量低于内建 ewa 系——这正是冻结项目 H1 的靶点,工程上可优化但感知上已证不划算。
3. **WHEN 死区**:窗口化/最小化播放时 OUTPUT 尺寸变化会跳过神经链(冻结项目实机 FINDING F1)。
4. **非 1080p 源行为**:4K 源上 Restore 系无 WHEN 条件、无条件跑最贵档(冻结项目指令级核对);若未设 dscale,4K→1440p 走默认(双线性)——建议配套 `dscale=ewa_lanczossharp`。
5. **内容适配**:line-art 导向,对 3D CG(如爱死机类)先天偏弱(冻结项目用户实测反馈)。
6. **上游停更 + 语法风险**:master 最后 push 2024-08-17,release 停在 2021;mpv 手册官方警告 user-shader 语法 "not stable yet"(原文实测)。2021 至今 v0.40 未破坏,**未证实**未来不破坏;资产已本机化,风险可控。
7. **冷编译卡顿**:首轮启用大量卷积 pass 编译有可感卡顿(ArtCNN 前科 196.7s;Anime4K 量级更小但同类);`gpu-shader-cache-dir` 已验证可缓解。

---

### 7) 可行性结论

**有条件可行** —— 一句话理由:工程上零成本且实测满速(官方 v4.0.1 资产逐字节在手、官方模板热切换即现状),但 1080p→1440p 场景感知收益已被本机先验实测证伪,故仅应在 **≤720p 源自动分桶**或用户明确偏好 Anime4K 线条观感时启用,主库场景维持 ewa_lanczossharp/现状,不做任何重写。

---

### 8) 证据链接列表(全部本次实际访问)

**GitHub API / raw(均 HTTP 200 实测)**:
1. https://api.github.com/repos/bloc97/Anime4K —— 21,454 stars / MIT / master / pushed 2024-08-17
2. https://api.github.com/repos/bloc97/Anime4K/contents/glsl —— 6 子目录(Deblur/Denoise/Experimental-Effects/Restore/Upscale+Denoise/Upscale)
3. https://api.github.com/repos/bloc97/Anime4K/contents/glsl/Restore —— 13 文件名+字节数与本地核对
4. https://api.github.com/repos/bloc97/Anime4K/contents/glsl/Upscale —— 同上(含 GAN/3DGraphics 为 master 新增的发现)
5. https://api.github.com/repos/bloc97/Anime4K/releases?per_page=10 —— 最新 v4.0.1(2021-09-17)及资产 URL
6. https://github.com/bloc97/Anime4K/releases/download/v4.0.1/Anime4K_v4.0.zip —— 实际下载(776,303B)解包,与本机 39 文件 cmp 逐字节 39/39 全同
7. https://raw.githubusercontent.com/bloc97/Anime4K/master/README.md —— 8,788B,官方 mpv 安装入口
8. https://raw.githubusercontent.com/bloc97/Anime4K/master/md/GLSL_Instructions_Windows_MPV.md —— 官方 Windows/mpv 安装步骤
9. https://raw.githubusercontent.com/bloc97/Anime4K/master/md/Template/GLSL_Windows_High-end/mpv.conf —— 官方默认链(Mode A HQ)
10. https://raw.githubusercontent.com/bloc97/Anime4K/master/md/Template/GLSL_Windows_High-end/input.conf —— 官方 CTRL+1..6 链定义
11. https://api.github.com/search/repositories?q=mpv+anime4k&per_page=15 —— 社区=配置包/GUI 搬运
12. https://api.github.com/search/repositories?q=anime4k+glsl+mpv&per_page=10 —— 边缘仓库,无独立实现
13. https://api.github.com/search/repositories?q=user:agyild&per_page=20 —— agyild 无 Anime4K(仅 cipetpet/ivirzivir)
14. https://api.github.com/repos/libretro/slang-shaders/contents/edge-smoothing —— 无 anime4k 目录
15. https://api.github.com/repos/libretro/slang-shaders/git/trees/master?recursive=1 —— 全树仅 sharpen/ 下 6 条 v2 代 anime4k 路径
16. https://api.github.com/repos/libretro/glsl-shaders/git/trees/master?recursive=1 —— 全树 0 命中
17. https://raw.githubusercontent.com/mpv-player/mpv/master/DOCS/man/options.rst —— 403KB,`--glsl-shaders` 定义与 "not stable yet" 警告原文

**本机实证(一手)**:
18. `%APPDATA%/mpv/shaders/` —— 39 个 Anime4K .glsl(与证据 6 逐字节全同);pass 数/WHEN/COMPUTE/PREKERNEL 均为本地 grep 实测
19. `%APPDATA%/mpv/input.conf` —— F5/F6/CTRL+1..6 链字符串与官方模板 diff 6/6 相同(F6=CTRL+4 链的重复绑定)
20. `%APPDATA%/mpv/mpv.conf` —— `profile=high-quality` + RIFE `vf-add=@rife:vapoursynth`
21. `D:/MPV/mpv.exe --version` / `--vo=help` —— v0.40.0-393-gad59ff1b4,libplacebo v7.357.0,gpu-next 列首位
22. 《Anime4K 1440p 优化实验(已冻结)》`D:/workspace/小项目/mpv插件/anime4k插件优化/docs/验证报告.md`(已读取原文:WHEN 死区 F1、AutoDownscalePre 单次抽头源码核对、17 格实机矩阵满速 48fps、lua 换链器工程验证、dscale 缺失事实)

**未证实项汇总**:① GitHub 代码级搜索未做(需认证),"无独立 v4 移植"非穷尽结论;② 1080p→1440p 实际 39 pass 为 WHEN 逻辑推演;③ GFLOP/显存百 MB 为量级估算;④ mpv 0.39+ 默认 vo 变更的官方 changelog 声明;⑤ master 分支 GAN/3DGraphics 实验变体的效果。
