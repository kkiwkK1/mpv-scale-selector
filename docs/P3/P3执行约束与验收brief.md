# P3 执行约束与验收 brief

此文件是领导者对最新用户请求的范围解释；与 `docs/执行授权-P3.json` 共同约束规划、实施、验证和审查。原准备期“不开始P1”不适用于当前明确阶段启动。只开发 P3，不部署、恢复、提交或自动进入 P4。

## 基线与流程

- P2 客观候选 `78770240f8cf15cbf837c792c6ccf9206af1cddf69f0c18fc36c42c36b142a66`、24必测、独立集成和两审通过。35源码的旧字节已在 `docs/阶段源码快照/p2-001/`。
- 所有既有研究/准备/开发证据、授权/计划/旧Taskflow/阶段快照保护；本阶段可编辑的共享源码由新计划**具体枚举**，不得用宽泛 tests/tools 前缀授权重写备份工具或旧P2说明。
- Taskflow：只读前检 → 单写者计划 → 机器检查 → 独立计划对抗审核 → permit → 唯一源码写者及自测 → 单测 → 独立集成/冻结 → 机器证据门 → 同候选技术与对抗两审 → 客观状态。发现blocker/major立即REWORK，保存原意见后限域修正、新候选、受影响检查再复审。
- 全部LLM子角色 `zai-coding-cn/glm-5.3-flash`，请求xhigh；同一模型独立上下文，不冒充异质审查。源码/证据写者 `idempotent=false`、cache off、无自动retry；连接失败或用户中断先保存部分状态再决定接续，不盲目resume。

## 产品实现约束

1. **单主链与所有权**：P2整property替换语义延续；首次接管已有stock也不能append。Integer为空shader链+几何/核明确托管；退出Integer切换其他档位须恢复/转移几何，不能留 unscaled/zoom 污染 shader 档。外部改shader、zoom、unscaled、pan等冲突后yield，Off只恢复仍owned且等于last_written者，不能陈旧覆写。
2. **NIS**：用取证 `docs/证据/port-NVScaler.glsl` 固定MIT版本，已有锐化，绝不叠NVSharpen。真实compute workgroup 32×24 / 256线程和两张2×64 rgba32f系数纹理。注意原port最后直接imageStore而无显式边界guard，非整块输出必须审计共享内存读与写界限；可版本化增加位于全部barrier之后的每像素bounds guard，但不能在组barrier前让部分线程return。明确原值/差异/hashes，不拿GPU不报错当无越界的证明。SDR LUMA适配，RGB/HDR guard。
3. **xBR**：把已取证Hyllian xBR-lv2/libretro参考移植为mpv MAIN RGB hook，保留MIT许可和数学/邻域/坐标映射。参考XBR_SCALE=3，若用3×预缩放+mpv后续缩放，必须明确此模式，不能冒称任意比例等价或xBRZ。可以保守按参考3×，用小RGB合成样本验证真实像素/参考坐标与pass；vf=xbr不当作GPU版实测。HDR guard独立于LUMA guard，RGB MAIN可以支持。
4. **Sharp Bilinear**：AUTO与手动2×在菜单中**分别命名**（建议sharpbilinear与sharpbilinear2x）。按Themaister public-domain参考移植MAIN，实际硬件linear采样要确认。AUTO floor(output_h/input_h+0.01) 在1080→1440为1，明确“退化为双线性”；不足1×须避免scale=0导致除零并回退/说明。手动2×是参考坐标采样/预缩放语义，不是假造两个串联pass，源码/CPU采样oracle/实际截图小样本均核对。
5. **Integer**：k=floor(min(独立可用窗口像素/有效显示源尺寸))。可用窗口**不能**从自己缩小后的osd-margin推导（黑边导致反馈）；video-out-params的源/显示尺寸及旋转、crop、SAR与原窗口像素是依据。video-unscaled+zoom(log2 k)与三核nearest；1080→2560×1440为1×，边320/180；720→同输出2×满屏；k<1是正常缩小/明确回退，不裁切。显示参数pan/align/zoom均需合法所有权和恢复。SAR非方形需保持显示比例，若不能兼得严格每像素整数复制需明确边界而非假方形；不能以“未支持”跳过全部SAR/旋转/crop机器检查。
6. 守卫idle/未知、8/10bit、RGB、HDR合成元数据变化；WHEN合法跳过须真实文案，实际链验证关联当前帧/epoch，不能仅加载路径或旧vo-passes报告active。保持LS1/BCAS禁用、防conf冒名、Off恒为关、CTRL+1..6/F7/F8键域。
7. fallback真实语义：失败释放回关/原基线，非自动恢复上一档。原主计划措辞差异在新P3计划明确，不编辑旧计划掩盖。
8. 保留 stock十文件和FSR/SGSR资源原字节；新资源独立manifest（可p3-resource-manifest）避免必须改旧12项清单和旧测试。禁止在溯源注释行中放指令样前缀导致伪shader指令；原SGSR错误来自P2新增头注释，不是取证原算法。

## 必测与证据

- 保留原121单测全部行为覆盖，必要注册表迁移逐条注释，不删/skip或降低断言；加入P3纯几何/采样/资源/负例/证据测试。
- 必需矩阵：P2原24项+SHD-05/06/07、GEO-02/03/04/05/06、PER-04-COMPUTE、EVI-01、UNIT-P3-01。GEO-04机器部分为窗口尺寸/比例/可观察属性变化；全局DPI/跨屏真人动作仍pending，不修改系统设置。
- SHD-09在各新增算法分别测8/10bit SDR（可明确安全拒用/降级理由，但不得无测称支持）；SHD-10/11逐档RGB/HDR边界。真实10bit decode与几何必须同刻采样，避免P2的VL-F1。
- NIS非块整除的输出/边缘图案、放大/等尺寸/缩小、系数格式/hash/binding、实际GPU日志/DESC/新帧，失败compute/资源变体。xBR/Sharp RGB小样本要有采样和图像客观oracle，不以主观画质评分代替。
- GEO-02/03需真实window capture像素对照与黑边/块分布，不把subtitles模式视频尺寸截图用于显示几何。采集前后状态/帧关联、PNG尺寸和hash；重复图标non-corroborative，不假造“重采成功”。纯STD库PNG解析可处理mpv截图的真实bitdepth，不能把8bit解析器误当所有PNG。
- **自动收集本轮所有落盘证据**含每次restart console/mpv log/IPC/input/media记录，create-only；清单在产物全部写完后收集，排除manifest自身和循环自指产物。EVI-01检验额外/漏项、变体/日志覆盖、非空图片与相同hash诚实标注，合成负例也测试。
- 对照pass计数按实际DESC命中+samples而非“user shader”子串0==0。旧P2harness三根因若修改其共享模块，在新P3候选冻结tools/p2_verify.py及tests并实测关闭，不改旧清单。无需重复整份研究或大GPU性能矩阵。
- 独立集成：新p3-001/verify-lead目录，不改源，发现实证FAIL保存并返作者，不边改边验。tests唯一ID、variants合并、计划必测全部PASS、无客观未测；candidate包含所有执行的源码/测试/shader/资源许可/文档，及被测备份工具、old/P3guard等环境hash（解决P2S-04），避免执行依赖游离冻结。

## 验证安全与性能边界

真实播放器只直接启动D:/MPV/mpv.exe，gpu-next/vulkan；独立临时config/HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/cache/watch-later/截图位置；子进程env不带API凭据。只停止自己的PID，禁止全局taskkill。

不写活动APPDATA/mpv、D:/MPV、备份payload；不读取私有媒体。RIFE重量级完整共存余量与公平A/B仍属P4。PER-04-COMPUTE只检查后端compute可行性/原始fresh-redraw样本（纳秒、samples说明），不冒称性能收益；RIFE竞争若无法在此阶段证明依赖无受保护路径写入则明示未测留P4，而不是传给真人签字替代机器测试。

P1/P2主观检查保留pending；P3菜单/像素风真人偏好与系统DPI实操另列pending；无画质/速度收益、真实部署验收或用户批准宣称。
