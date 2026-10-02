# mpv v0.40 渲染扩展机制实证简报(为"第三方缩放算法接入"提供机制事实)

> **初稿归档，非最终验收依据。** master文档不等于本机构建；能力矩阵、后续缩放与绝对性能预测存在过度概括。以 [勘误说明](../勘误说明.md) 与使用固定构建文档的 [整合报告](../可行性研究报告.md) 为准。

实验对象(本地): `D:/MPV/mpv.exe` → mpv v0.40.0-393-gad59ff1b4,libplacebo **v7.357.0** (v7.351.0-87-g9bffcaf-dirty),FFmpeg N-121425-g0bc54cddb (libavfilter 11.9.100)。
上游文档: mpv **master** 分支 raw 文件(options.rst / vo.rst / vf.rst / lua.rst)+ 官方 Wiki `GPU-Next-vs-GPU` + libplacebo master `src/shaders/custom_mpv.c` + mpv master `video/out/vo_gpu_next.c`(均 curl raw 后 grep/阅读取证)。
标注约定: 【实证】= 本地命令或上游源码/文档直接证实;【未证实】= 未找到权威出处,如实标注。

---

## A. 本地 ground truth(mpv 实测输出)

**A1 `--version`**: 见开头版本行。vo 列表中 gpu-next 为默认推荐(vo.rst L19-20【实证】)。

**A2 `--scale=help` / `--dscale=help` / `--cscale=help`**(三者同一张表,dscale/cscale 另有 `(passing nothing)` 空值):
38 个内建核,全部是经典重采样核:bilinear, bicubic_fast, oversample, spline16/36/64, sinc, lanczos, ginseng, bicubic, hermite, catmull_rom, mitchell, robidoux(+sharp), box, nearest, triangle, gaussian, jinc, ewa_lanczos, ewa_hanning, ewa_ginseng, ewa_lanczossharp, ewa_lanczos4sharpest, ewa_lanczossoft, haasnsoft, ewa_robidoux(+sharp), bartlett, cosine, hanning, tukey, hamming, quadric, welch, kaiser, blackman, sphinx。
→ **无任何 ML/AI/超分类内建缩放器**【实证】。

**A3 `--vo=help`**: gpu-next(libplacebo)、gpu、direct3d、sdl、libmpv、null、image、tct、kitty【实证】。

**A4 `--vf=help`**: mpv 内建 vf: format、lavfi、lavfi-bridge、sub、fingerprint、vapoursynth、vavpp、d3d11vpp、**gpu("vo_gpu as filter")**;其余全部经 libavfilter 桥(见 C3)【实证】。

**A5 `--list-options` 关键行**【实证】:
- `--glsl-shader` = `--glsl-shaders-append` 的 CLI/config 别名
- `--glsl-shaders`: String list [file],子命令 add/append/clr/del/pre/set/**toggle**/remove
- `--glsl-shader-opts`: Key/value list
- `--gpu-shader-cache`: Flag (default: yes);`--gpu-shader-cache-dir`: String [file],缺省存系统缓存目录(通常 ~/.cache/mpv,options.rst L8114-8116)
- `--video-unscaled`: Choices no/yes/downscale-big (default no)
- `--input-cmdlist` 含 `change-list name= operation= value=`(运行时改列表选项的命令)【实证】

## B. 上游文档要点

- **`DOCS/man/shaders.rst` 在 master、v0.38、v0.40 tag 均 404**(curl 实测)。user-shader 语法权威已**并入 options.rst L6569-6858** 的 `--glsl-shader` 节【实证】。官方明示 *"The syntax is not stable yet and may change any time."*(L6579-6581)。
- vo.rst L30-38: gpu-next 基于 libplacebo,与 gpu 特性"almost the same",差异见 Wiki `GPU-Next-vs-GPU`。
- Wiki 要点【实证】: gpu-next 删除 `--fbo-format`(libplacebo 强制浮点 FBO,rgba16f 以上无收益);`MAIN` 与 `MAINPRESUB` 无区别;aggressively merges shader passes;旋转在最终 pass 才做;gpu-next 新增运行时可调 PARAM、`linearize`/`delinearize` 宏,`--glsl-shader-opts` 列为 gpu-next 新选项;`ewa_lanczossoft`/`haasnsoft`/`--sharpen` 被删。

## C. 机制结论(逐条 + 证据)

### C1 user-shader(glsl-shaders)hook 机制

**hook 点全集**(options.rst L6803-6853【实证】;gpu-next 经 libplacebo `custom_mpv.c` L832-871 `mp_stage_to_pl` 同名映射【实证】,个别差异见后):
- 可变尺寸 **resizable**: `RGB, LUMA, CHROMA, ALPHA, XYZ`(源平面)、`NATIVE`(合成、转 RGB 前)、`MAINPRESUB`(RGB 化后、字幕前)、`MAIN`(RGB 化后、上采样前)
- 固定尺寸 **fixed**: `CHROMA_SCALED/ALPHA_SCALED`、`LINEAR`、`SIGMOID`、`PREKERNEL`(scaler 核前一刻)、`POSTKERNEL`(核后一刻)、`SCALED`(最终上采样后、色彩管理前)、`OUTPUT`(色彩管理后、dither 前)
- **gpu vs gpu-next 差异**【实证】: ① gpu-next 无独立 `MAINPRESUB` 阶段,与 `MAIN` 同一纹理(libplacebo L852-855、L1201-1205 宏别名);② gpu-next 独有 hook 名 `PREOUTPUT`(PL_HOOK_PRE_OUTPUT,L868-869);③ PARAM 运行时调参、uint/DYNAMIC/CONSTANT 类型仅 gpu-next,vo=gpu 仅子集(options.rst L6660 注、Wiki);④ gpu-next 提供 `linearize`/`delinearize` 宏。

**块语义**(options.rst【实证】,行号同 master):
- `//!HOOK name`(L6676): 挂到某纹理,可多次;纹理被渲染保存时,挂上它的 pass 按用户添加顺序全部执行(L6803-6805)。
- `//!BIND name`(L6686): 绑定输入纹理,生成 `NAME_tex/NAME_texOff/NAME_pos/NAME_size/NAME_pt/NAME_rot/NAME_mul/NAME_raw` 宏(L6758-6776);`HOOKED` 特指触发本 pass 的纹理。
- `//!SAVE name`(L6693): 结果存入该名纹理,默认 `HOOKED`(原地覆盖)。
- `//!WIDTH/HEIGHT szexpr`(L6698-6706): **RPN 表达式**,可用 `+ - * / > < ! = %`、字面量、`MAIN.width`/`CHROMA.height`、`OUTPUT`、可调参数、`NATIVE_CROPPED`;默认 `HOOKED.w/h`。**只有 resizable 纹理可改尺寸;覆盖 fixed 纹理时必须保持默认尺寸**(L6855-6857)。
- `//!WHEN szexpr`(L6708): 条件为 0 则本 pass 静默跳过(可做"按源分辨率自动换链"的 shader 内开关)。
- `//!COMPONENTS n`(L6728): 输出有效分量数(≤4),默认同 HOOKED。
- `//!DESC title`(L6681): 显示在 `vo-passes` 属性的 pass 列表里。
- `//!COMPUTE bw bh [tw th]`(L6733): 计算着色器;写 `void hook()` 向 mpv 绑定的 writeonly 图像单元 `out_image` 做 `imageStore`;提供 `NAME_map(id)` 做 texel→纹理坐标映射(无顶点)。阈值(需要什么 GL/Vulkan 版本)文档未写【未证实】。
- `//!TEXTURE`(L6601+): 静态纹理(SIZE/FORMAT/FILTER/BORDER + hex 数据);`//!PARAM`(L6632+): 可调参数,float/int/ENUM/DEFINE 等。
- 全局 uniform: `random`(每帧随机)、`frame`(逐帧递增)、`input_size`、`target_size`、`tex_offset`(L6790-6799);`--glsl-shader-opts` 自动参数: `PTS`、`chroma_offset_x/y`、`min/max_luma`、`max_cll/fall`、`scene_max_r/g/b`(L6862+)。

**pass 输出尺寸变化由谁采样**: pass 把 resizable 纹理改成新尺寸(WIDTH/HEIGHT)后,结果作为该名纹理进入**后续固定管线**;`OFFSET` 累积的像素偏移由**下一个缩放 pass(cscale 或 scale)负责校正**(options.rst L6715-6721【实证】);`target_size`/`OUTPUT` 固定为最终输出。即: user-shader 在 MAIN/LUMA 等点自行上采样后,内建 scaler 仍会对结果再走一遍(常用 `WHEN OUTPUT.w MAIN.w /` 类技巧规避,Anime4K 模式;此技巧本身属社区用法【未证实于官方文档】)。

**多 pass 链**: 支持——单文件内多个 HOOK 块 + 多文件按列表顺序串联(pass 执行顺序=用户添加顺序,L6803-6805【实证】)。文件之间通过 SAVE/BIND 的命名纹理传递。

**上一帧反馈**: 文档只提供 `frame`/`random`/`PTS` 等标量,无任何"读取上一帧输出纹理"的机制;saved 纹理是否跨帧保留无文档保证【未证实 → 按"不可行"设计】。

### C2 Lua 动态增删与热切换(可行【实证】)

- `glsl-shaders` 是字符串列表属性: `--glsl-shaders-append/-toggle/...` 子命令存在(A5),`change-list` 命令存在(A5),故 Lua 侧 `mp.set_property_native("glsl-shaders", {...})` / `mp.commandv("change-list","glsl-shaders","append",path)` 可运行时改链(lua.rst L249 起为属性 API【实证】)。
- 键位/OSD 菜单: `mp.add_key_binding`(lua.rst L285【实证】)+ `toggle` 子命令。
- 按源分辨率自动换链: Lua 监听 `width/height` 属性变化 → 重写 glsl-shaders 列表;shader 内亦可用 `WHEN input_size ...` 条件启用(WHEN 证据 L6708)。
- 注意: gpu-next 对已解析 shader 按**路径**缓存(`load_hook` 按路径查重,vo_gpu_next.c L2660-2683【实证】)→ 同路径文件改内容后热重载不可靠;换链应换路径或重载文件触发。链切换本身即时生效。

### C3 `--vf=libplacebo` 与 `--vf=lavfi`

**vf=libplacebo**(FFmpeg 桥,`--vf=help` 列出 "Apply various GPU filters from libplacebo")【实证】。本地 `--vf=libplacebo=help` 共 77 选项,关键: `w/h`(输出尺寸表达式)、`fit_mode/force_original_aspect_ratio/normalize_sar`、**`upscaler/downscaler/frame_mixer`(string)**、antiringing、sigmoid、deband、tonemapping 全套、dithering、`lut/lut_type`、**`custom_shader_path`(说明原文 "Path to custom user shader (mpv .hook format)")、`custom_shader_bin`**、`shader_cache`。
→ **mpv .hook 用户着色器也能喂给 vf=libplacebo**(同一 libplacebo mpv-shader 解析器)。upscaler 的合法值清单 help 未展开【未证实】。
代价: 走 filter 管线意味着帧进出 libavfilter 图、可能格式转换/回读桥接;精度与 hook 点受 FFmpeg 封装限制,远不如 vo 内 hook 细【机制推断+未证实细节】。

**vf=lavfi**(vf.rst L398-447【实证】): 完整 libavfilter 图。可用像素级缩放/超分类: `scale`(sws/zimg,`force-scaler`)、`zscale`、`scale_cuda/vulkan/vaapi/qsv/d3d11`、`sr_amf`、`xbr/hqx/epx/super2xsai`(像素风)、`nnedi`、`minterpolate` 等(A4 列表实证)。能力= 任意图组合、多节点、时间域反馈(tmix/tblend/lagfun 等);代价= 多为 CPU 滤镜,1080p 量级可达数 ms~数十 ms【工程经验估计,未实测】;GPU 变体依赖硬解帧路径(hwupload/hwmap)。
**vf=gpu**("vo_gpu as filter",vf.rst L895-940): 官方警告 highly experimental、性能差、与 vo=gpu 同用会双重滤波【实证】。

### C4 gpu-next(libplacebo v7.357)有无内建超分缩放器

**没有**【实证】。证据: ① `--scale=help` 全表为经典核(A2);② options.rst `--scale` 节(L5942-6010)只记载经典核并注明"更多见 help";③ Wiki 明确 gpu-next 反而删除了 `ewa_lanczossoft`/`haasnsoft`/`--sharpen`。第三方"超分"(FSRCNNX/Anime4K/RIFE 类)在 mpv 的唯一一等公民入口是 **user-shader(.hook)**;libplacebo 本体不带 ML 缩放器【实证: 无任何相关选项/文档】。

### C5 限制清单

1. **COMPUTE 对 vo 的要求**: 仅 vo=gpu / gpu-next 这类着色器渲染器有 glsl-shaders 机制(A5 选项属 GPU renderer options;direct3d/sdl 等 VO 无此管线);COMPUTE 需 GPU 支持计算着色器,具体 API 版本阈值文档未写【未证实】。
2. **FBO 精度**: vo=gpu 由 `--fbo-format` 控制,rgb8…rgba32f,默认 auto→rgba16f 优先(options.rst L7304【实证】);gpu-next 无此选项,libplacebo 强制浮点 FBO(≥rgba16f),更高无收益(Wiki【实证】)。shader 可用 `//!TEXTURE FORMAT rgba16f/rgba32f` 自选中间纹理精度(options.rst TEXTURE 节【实证】)。
3. **hook 点分辨率语义**: fixed 点(PREKERNEL/POSTKERNEL/SCALED/OUTPUT/LINEAR/SIGMOID/CHROMA_SCALED)禁止改尺寸;resizable 点(MAIN/LUMA/CHROMA/RGB/ALPHA/XYZ/NATIVE/MAINPRESUB)才能由 pass 改尺寸(L6855-6857【实证】)。`MAIN` 在上采样之前(即源分辨率级),`POSTKERNEL` 在内建 scaler 之后=target 级;gpu-next 里 MAIN==MAINPRESUB。
4. **语法稳定性**: 官方明示 user-shader 语法"not stable yet"(L6579-6581【实证】);gpu-next 会激进合并 pass(Wiki【实证】),影响 vo-passes 观测粒度,不影响语义。
5. **跨帧状态**: 见 C1 末条【未证实】。

## D. 机制×能力矩阵

| 能力 | user-shader (glsl-shaders) | vf=libplacebo | vf=lavfi (桥) | 内建 scale= | lua (控制面) |
|---|---|---|---|---|---|
| 任意输出尺寸 | ✔ WIDTH/HEIGHT RPN,OUTPUT/NATIVE_CROPPED 可引用 | ✔ w/h+fit_mode(需在 filter 图内指定) | ✔ scale=w:h 表达式/多级 | ✘ 尺寸=窗口/target,不可自定 | —(不产像素) |
| 多 pass | ✔ 文件内多块+多文件串联 | ✘ 单节点(内部固定管线) | ✔ 图内多节点串联 | ✘ | — |
| 逐帧反馈(读上一帧) | ✘ 无文档机制【未证实】 | ✘【未证实】 | ◐ 时间域滤波器(tmix/tblend 等)可近似 | ✘ | — |
| COMPUTE | ✔ gpu/gpu-next(//!COMPUTE) | ✘ 未暴露 | ✘(仅 _cuda/_vulkan 独立滤镜,需硬解帧) | ✘ | — |
| 运行时热切换 | ✔ 列表属性/toggle;按路径缓存,换链宜换路径 | ✔ vf 属性/命令 | ✔ 同左 | ✔ scale 属性/cycle-values | ✔ 本体即控制面 |
| 键位/OSD 菜单 | ✔ add_key_binding+toggle+vo-passes 观测 | ✔ 同左 | ✔ 同左 | ✔ 同左 | ✔ |
| 每帧成本量级(1080p,工程估计,未实测) | GPU ~0.1ms–数 ms(算力随算法) | 桥接拷贝+GPU 滤镜 ~≥1ms | CPU 滤镜数 ms–数十 ms;GPU 变体视路径 | 次 ms–数 ms(EWA 系最重) | ≈0 |

**结论(一句话)**: 第三方缩放算法接入 mpv v0.40 的主通道是 **`--glsl-shaders` user-shader(可选 COMPUTE),挂 resizable hook 点(MAIN/LUMA),Lua 按源分辨率热切链**;vf=libplacebo 可作为"同一 .hook 语法的离线/filter 路径"备选;vf=lavfi 适合 CPU/现成 FFmpeg 算法;内建 scale 无超分。

## 证据文件

- 本地命令输出: `--version/--scale=help/--dscale=help/--cscale=help/--vo=help/--vf=help/--vf=libplacebo=help/--list-options/--input-cmdlist`(见上文引用,均已留存于会话记录)
- master options.rst: L6569-6858(glsl-shader 全节)、L5942-6011(scale)、L1684(video-unscaled)、L7304(fbo-format)、L8114(gpu-shader-cache-dir)
- vo.rst L15-45;vf.rst L26/L398-447/L895-940;lua.rst L249-285
- Wiki GPU-Next-vs-GPU.md(79 行,全读)
- mpv `video/out/vo_gpu_next.c` L2660-2683/L2978-2987;libplacebo `src/shaders/custom_mpv.c` L832-898/L1201-1205
- `DOCS/man/shaders.rst`: master/v0.38/v0.40 均 404【实证】;v0.36 存档拉取三次均连接失败【未取得】
