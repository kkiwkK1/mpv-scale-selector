## Integer Scaling(整数缩放)

> **初稿归档，非最终验收依据。** 本文“整数比下任何插值核近似像素复制”的旁注已撤回；严格像素块须 nearest。其余结论按 [勘误说明](../勘误说明.md) 与 [整合报告](../可行性研究报告.md) 核对。

> 研究定位:Integer Scaling 严格说**不是重建算法,而是 vo 层的几何显示策略**——只在整数倍(1×/2×/3×…)放大并居中,保证 1 个源像素映射到 n×n 个物理像素,从根上消除非整数重采样带来的模糊与像素网格错位。先验背景:本机 1080p→1440p 仅 1.33×,ewa_lanczossharp 已与重型方案感知等同(已冻结实验)。
>
> 查证日期:本节所有链接均经 curl 实际访问确认(见第 8 节)。

---

### 1. 算法本体与原理

**结构与 pass 数**
- 无多 pass、无卷积核、无神经网络。整数缩放 = 最近邻点采样(nearest / point sampling)在整数因子下的特例:**每输出像素恰取 1 个源像素**,重复 n×n 次。
- 复杂度:O(N),N 为输出像素数,常数 = 1 次采样/像素,是所有缩放方式的下界。
- 在 mpv 中若用 `--video-unscaled=yes`(1×),则**连重采样都完全跳过**,视频按物理像素 1:1 投影,仅居中留黑边。
- 理论旁注:窗函数 sinc 类核(如 lanczos)在**精确整数比**下,输出像素中心对准源像素中心,核在非零整数偏移处过零(sinc(k)=0),因此 lanczos 在 2.0× 时输出≈输入——这是"整数比下任何核都近似无损"的数学原因(**理论推断**,未做驱动级实测,未证实)。

**本机关键算例:1080p→1440p(非整数比 1.333×)**
- s = floor(min(2560/1920, 1440/1080)) = **1**(2× 需 3840×2160,超出屏幕)。
- 即 1080p 片源只能 1:1 显示:视频区 1920×1080,左右黑边各 **320 px**,上下各 **180 px**。
- 画面面积利用率 = (1920/2560)×(1080/1440) = **56.25%**(每个方向线性只用 75%)。
- 对照:720p 片源 s = 2 → 2560×1440 **完美满屏零黑边**;960×540 → 2× → 1920×1080;4K 片源 s = 0(只能缩小,须回退常规缩放)。

### 2. 权威实现 / 开源仓库与协议(curl 实际访问确认)

| 来源 | 查证结果 | URL | 状态 |
|---|---|---|---|
| mpv 官方(权威) | 无独立算法仓库,能力由内建选项提供:`--video-unscaled=<no\|yes\|downscale-big>`(options.rst L1684)、`--video-zoom`(L1730,与 unscaled 可并用)、`--video-align-x/y`(L1747)、`--scale=<filter>`(L5942,含 nearest)。mpv 主仓库 GPLv2+ | https://raw.githubusercontent.com/mpv-player/mpv/master/DOCS/man/options.rst | 200 ✅ |
| 社区 recipe(mpv issue) | mpv-player/mpv **issue #10097** "optional feature suggestion: video scaling at only to integer scales."(2022-04-14,已关闭):社区作者 hooke007 给出配方 `video-unscaled=yes` + `video-zoom=1`(2× 整数),并用 `profile-cond` + `video-unscaled=downscale-big` 处理超屏视频回退 | https://github.com/mpv-player/mpv/issues/10097 | 200 ✅ |
| mpv 开发动向 | **PR #13324** "wayland: sanitize window dimensions for integer scaling"(2024-01,Dudemanguy):wayland 窗口尺寸整数对齐尝试,**closed 未合入**(merged_at=null)——说明"严格整数设备像素对齐"在部分平台连 mpv 本体都尚未保证 | https://github.com/mpv-player/mpv/pull/13324 | 200 ✅ |
| 专用脚本仓库 | GitHub 仓库搜索 `mpv integer scaling` / `mpv integer scale` → **total_count = 0**,未发现专用的成熟 integer-scaling lua 仓库 | https://api.github.com/search/repositories?q=mpv+integer+scale | 200 ✅ |
| occivink(提示中提及) | mpv-scripts 实际内容:blur-edges / crop / encode / seek-to / misc 等,**无 integer scaling 脚本**;mpv-image-viewer README 亦无 unscaled/integer 说明 | https://github.com/occivink/mpv-scripts | 200 ✅ |
| AN3223(提示中提及) | dotfiles `.config/mpv/scripts/` 实际内容:cropmode / pickshader / lats 等,**无 integer scaling 脚本**;其 mpv.conf 无 unscaled/integer 配置。pickshader.lua(shader 挑选器)仅间接相关 | https://github.com/AN3223/dotfiles | 200 ✅ |
| libretro/slang-shaders | 存在 `scanlines/shaders/integer-scaling-scanlines.slang`,原文自述 "pixel perfect scanlines for use **only with** integer scaling mode"——**shader 本体不做缩放**,缩放由 RetroArch 核心的整数缩放选项完成,shader 只叠加扫描线;且为 slang 格式,与 mpv //!HOOK GLSL 不兼容需移植 | https://github.com/libretro/slang-shaders | 200 ✅ |
| agyild(提示中提及) | 仓库仅 cipetpet / ivirzivir / reshade-shaders,**无整数缩放相关实现** | https://github.com/users/agyild/repos | 200 ✅ |
| bloc97 | Anime4K 仓库存在(先验实验已冻结,与本题仅作对照) | https://github.com/bloc97/Anime4K | 200 ✅ |
| mpv 官方 wiki User-Scripts 列表 | 无 integer scaling 条目(grep 无命中) | https://raw.githubusercontent.com/wiki/mpv-player/mpv/User-Scripts.md | 200 ✅ |

> 结论:**不存在需要移植的"权威第三方算法实现"**——整数缩放的权威实现就是 mpv 内建选项本身;社区全部实践(issue #10097 等)都是围绕 `video-unscaled + video-zoom(+ lua 动态计算)` 的组合。occivink / AN3223 存在整数缩放脚本的提示**未获证实**。

### 3. mpv 集成路径评估(对照 primer A–E)

**选择:E(lua 脚本)+ D(mpv 内建几何选项与 nearest 内核)。**

- ❌ A(user-shader / --glsl-shaders):user shader 只处理像素 pass,**无法改变 vo 的输出几何/位置/缩放因子**;整数缩放恰恰是纯几何问题,shader 方案无意义。libretro 的先例也印证:shader 只做配套效果(扫描线),缩放由播放器核心完成。
- ❌ C(--vf=lavfi/libplacebo):用 `scale=iw*n:ih*n:flags=neighbor` 可行但多一次全帧拷贝、与 vo 几何语义叠加易乱,收益为零,徒增链路复杂度。
- ❌ B(vo=gpu-next):unscaled/zoom 走 vo 层,gpu-next 与 gpu 行为一致,无增益点。
- ✅ D+E:`--video-unscaled` / `--video-zoom` / `--video-align-x/y` 原生支持(issue #10097 已验证配方),lua 负责按源分辨率×窗口尺寸动态计算整数因子并热切换、提供键位/自动档。

**接入要点(实现蓝图)**
1. file-load 时读 `width`/`height`(视频)与 `osd-width`/`osd-height`(窗口),算 `s = floor(min(win_w/w, win_h/h))`。
2. `s >= 1` → `video-unscaled=downscale-big` + `video-zoom = log2(s)`(zoom 是以 2 为底的加性值:1=2×)+ `video-align-x/y=0` 居中;可选同时设 `scale=nearest`(或保留 lanczos,见第 1 节旁注,稳妥起见切 nearest)。
3. `s == 0`(如 4K 源)或 `s == 1` 且用户不想要黑边 → 恢复常规档(`video-unscaled=no` + ewa_lanczossharp),即 hooke007 的 `profile-cond` 回退思路。
4. 观测 `osd-width/height` 变化(窗口拖动)重算;提供键位循环:默认(1.33× lanczos)→ 整数 1× → 整数 2×(720p 源满屏)。
5. 严格像素对齐的前提:全屏原生分辨率、DPI 100%、无边框/合成器不缩放;窗口化时按窗口像素尺寸计算但仍受 mpv 定位舍入影响(**未证实 mpv 保证整数设备坐标对齐**,参见 PR #13324 未合入)。

### 4. 难度与预估工作量

- **难度:1 / 5**。无算法,纯选项组合 + ~60 行 lua(读两个属性、一次除法、设三个属性、恢复现场)。
- 工作量:最小可用版(手动键位切换)**1–2 人时**;含自动档(按源分辨率决策 480p/720p→启用、1080p→可选、4K→回退)+ 窗口 resize 响应 + 与现有 RIFE 链回归测试,**3–5 人时**。

### 5. 性能量级 @1440p + RTX 2080 SUPER(全部为估算,未实测)

| 方案 | 每 pass 采样 | GPU 开销量级(1080p 源→1440p 屏) |
|---|---|---|
| video-unscaled=yes(1×) | 0(跳过重采样) | ≈0,仅带宽拷贝 |
| nearest 整数 n×(如 720p 2×) | 1 / 输出像素 | ≈0(毫秒以下) |
| ewa_lanczossharp(现状默认) | 每输出像素数十次 EWA 采样,1 pass | 毫秒级(粗估 1–3 ms/帧) |
| Anime4K v4(先验已冻结) | 多 pass CNN | 先验实验:感知无增益,不重评 |

- 与 RIFE 插帧共享 GPU 预算:整数/unscaled 档相对 lanczossharp 是**净释放**(省下的重采样时间全部让给 RIFE),利于帧节奏稳定;收益幅度毫秒级(**估算,未实测**)。
- 无显存压力(无新分配),无功耗/热设计顾虑,反而略降。

### 6. 已知限制与风险

1. **主力场景 UX 折损(最大风险)**:1080p 片源在本机只能 1×,面积利用率 56.25%、四周黑边 320/180 px——"为了像素完美看小一圈"与观影需求直接冲突;结合先验(1.33× 下 lanczossharp 已感知足够),**对 1080p 动画源收益边际很小**。
2. 收益区间窄:主要惠及 480p/720p、像素风/复古游戏录像(720p 在 1440p 屏恰好 2× 完美满屏)。
3. 严格像素对齐依赖全屏原生分辨率 + DPI 100%;窗口化及部分平台下 mpv 不保证整数设备像素对齐(PR #13324 wayland 整数对齐未合入为证;Windows 下行为**未证实**)。
4. 非方形像素源(DVD anamorphic)在 unscaled 下仍会被一维缩放(mpv 手册明示);旋转视频需特判。
5. `scale=nearest` 若在非整数比或半像素偏移下误用,会出现锯齿/不均匀像素——脚本必须严格守卫 s 的计算与回退。
6. 与常驻 RIFE 链的共存需回归测试(切换的是 vo 几何属性,理论上不触碰 shader 链,**未实测**)。

### 7. 可行性结论

**有条件可行** —— 实现近乎零成本(mpv 原生选项 + 60 行 lua,难度 1/5)、GPU 开销≈0,但 1080p→1440p 只能 1× 显示(面积利用率 56.25%),对以 1080p 为主的本机片源感知收益有限,应做成 480p/720p/像素风片源自动启用、1080p 手动可选的**非默认档**,而非替代 ewa_lanczossharp 的主力方案。

### 8. 证据链接列表(全部经 curl 实际访问)

| # | URL | 访问方式 | 确认内容 |
|---|---|---|---|
| 1 | https://raw.githubusercontent.com/mpv-player/mpv/master/DOCS/man/options.rst | curl raw | L1684 `--video-unscaled=<no\|yes\|downscale-big>` 完整语义;L1730 `--video-zoom`;L1747 `--video-align-x/y`;L5942 `--scale` |
| 2 | https://github.com/mpv-player/mpv/issues/10097 | GitHub API(/issues + /comments) | integer scaling 建议 issue(2022-04,closed);hooke007 给出 `video-unscaled=yes`+`video-zoom=1` 配方与 `downscale-big` 回退 profile |
| 3 | https://github.com/mpv-player/mpv/pull/13324 | GitHub API(/pulls) | "wayland: sanitize window dimensions for integer scaling",2024-01,closed 未合入 |
| 4 | https://github.com/occivink/mpv-scripts | GitHub API(/contents/scripts) | 脚本清单无 integer scaling;含 UNLICENSE(public domain) |
| 5 | https://github.com/occivink/mpv-image-viewer | curl HEAD 200 + README raw | 无 unscaled/integer 相关说明 |
| 6 | https://github.com/AN3223/dotfiles | GitHub API(.config/mpv/scripts + mpv.conf raw) | 无 integer scaling 脚本;mpv.conf 无 unscaled 配置 |
| 7 | https://raw.githubusercontent.com/wiki/mpv-player/mpv/User-Scripts.md | curl raw | 官方 wiki 脚本列表无 integer 条目 |
| 8 | https://github.com/libretro/slang-shaders | GitHub API(git trees recursive) + shader 文件 raw | `scanlines/shaders/integer-scaling-scanlines.slang` 存在,自述仅配合整数缩放模式使用;另有 koko-aio IntegerScaling 预设路径 |
| 9 | https://github.com/users/agyild/repos (api.github.com/users/agyild/repos) | GitHub API | 仅 cipetpet/ivirzivir/reshade-shaders,无整数缩放实现 |
| 10 | https://github.com/bloc97/Anime4K | curl HEAD | 200 存在(对照参考) |
| 11 | https://api.github.com/search/repositories?q=mpv+integer+scaling 及 ?q=mpv+integer+scale | GitHub 搜索 API | total_count = 0,无专用成熟仓库 |
| 12 | https://api.github.com/search/issues?q=repo:mpv-player/mpv+integer+scaling+in:title | GitHub 搜索 API | 命中 issue #10097 与 PR #13324(另有零星重复项) |
