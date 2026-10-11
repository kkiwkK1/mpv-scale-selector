# Sharp Bilinear 许可归属与适配说明（P3 / session p3-001）

- 算法：**sharp-bilinear**（Themaister），Public domain（作者声明原文内嵌）。
- 资源：`shaders/p3-Sharp-Bilinear-AUTO.glsl`（AUTO 档）与
  `shaders/p3-Sharp-Bilinear-2x.glsl`（手动 2× 档，菜单 id
  sharpbilinear2x）—— 同源参考 `docs/证据/sharp-bilinear.glsl`
  （sha256 `9b9afa91fe12bcbd49398179bf2072ce5a38b531c39a4fd381e92602c6dc114b`）
  的两份适配版（p3-adapt-v1）。原 Public domain 头逐字保留。
- 来源取证：`docs/证据/移植取证索引.json`（本阶段未从网络重新下载）。

## 适配范围（逐条记录；坐标采样数学零改动）

1. **分名分文件**：AUTO 与手动 2× 按计划分别命名（sharpbilinear /
   sharpbilinear2x），分别成文件；AUTO 固定参考参数 AUTO_PRESCALE>0.5
   （自动分支），手动 2× 固定 SHARP_BILINEAR_PRE_SCALE=2.0（参考默认 4.0，
   按档位名取 2.0——显式声明的常量，非新算法）。
2. **单 pass 语义**：mpv MAIN hook 单 pass 在输出分辨率渲染，参考坐标采样
   （floor/fract 预缩放映射 + 硬件 LINEAR 插值）；**不是两个串联 pass**，
   不假造预缩放纹理。
3. **输出/输入比推导**：本 mpv/libplacebo 构建不向 user shader 暴露输出
   尺寸 uniform（实证探针：`output_size` 未声明错误）；AUTO 以
   `gl_FragCoord.y / (HOOKED_pos.y * HOOKED_size.y)` 在像素中心处还原参考
   公式 `floor(outsize.y / InputSize.y + 0.01)` 的比值（同一量的等价推导，
   +0.01 参考psilon 同时吸收浮点误差）；InputSize = HOOKED_size。
4. **scale<1/0 防护（版本化新增）**：参考 `region_range = 0.5 - 0.5/scale`
   在 scale=0（输出<输入）时除零/NaN；P3 钳制 scale ≥ 1 —— scale=1 即定义
   良好的纯双线性退化（region_range=0 ⇒ f=0.5 ⇒ 采样 texel 中心=双线性）。
   1080→1440 时 floor(1.333+0.01)=1：按参考公式本就退化为双线性，UI/OSD
   如实明示（menu reason + skip_note），不改公式凑「锐利」。
5. **许可头**：Public domain 声明+作者归属保留；适配差异注释块另立
   （p3-adapt-v1 标记+基文件哈希）；无指令样前缀注释行。
