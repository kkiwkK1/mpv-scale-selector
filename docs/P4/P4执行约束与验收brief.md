# P4 执行约束与验收 brief（隔离研究与测量，不部署）

## 授权与基线

用户本轮请求：『P4：公平画质与性能 A/B、帧节奏和真实 RIFE 余量测试；』，据此直接推进隔离 P4，不再等启动确认。仅继承 P3 **PASS_OBJECTIVE**，不伪造任何 P1/P2/P3 真人验收或 approval。

- P3 固定候选：`docs/验证/开发/p3-001/revision-r2/candidate.json`，SHA `0b70e6644f5eb47dc0c3ad1b86db759e062ba0c162acdf074783533ba2185e67`。
- P3 tests、技术状态、53 文件源码归档、收口936文件清单、历史失败与意见原字节保持。
- 新 session：`p4-001`。所有已有产品源码、工具、测试、研究、证据和 stage guards 本阶段初始为只读。P4 新增 tools/p4*、tests/test_p4*、docs/P4/ 与本阶段证据；若发现 P3 产品缺陷，停止并限域新修订，不临时改产品再测试或覆盖旧 PASS。
- 原 282 单测（1 Windows 权限 skip）及 35 guard 测试行为保留。P3 fixture `tests/fixtures/p3/oracle-sample.ppm` 必须从启动起正式绑定实际哈希，不留『计划路径未创建便跳过』的候选门洞。P4 计划用精确文件写域，目录只允许明确的证据树且最终递归全绑定。

## 角色与可恢复流程

指定所有子代理 `zai-coding-cn/glm-5.3-flash`，请求 thinking=xhigh，不是异质模型审查。

依赖链：只读环境/可用测量方法勘察 → 单计划写者 → 实施前方法学/安全对抗审查 → 机器许可 → 单一测量工具写者 → 原/新增单测与校准 → 独立方法与校准复核 → 单 GPU 串行测量 → 独立复跑 → 固定候选技术+安全双路只读审查 → 机器客观结果。任何 major/blocker 阻断，原意见保留，限域修正、新目录/候选后复核。

不让单个代理承担数小时大包：数据层、采集层、分析层可串行交接，源码写者只有一个。硬中断先看实际工件/源码SHA/自有PID，归档部分，禁止盲重放非幂等写者。测试/测量负责人不边修源边验。每个 JSON 决策用合同及机器门，不能靠叙述就绪。

## 安全前置

1. 活动 `%APPDATA%/mpv`、`D:/MPV`、私人备份 payload 零写；不真实恢复/安装/卸载、改系统DPI、锁GPU时钟、改驱动设置、全局kill、Git提交/推送。
2. 直接 `D:/MPV/mpv.exe`，固定 gpu-next/Vulkan。独立 HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/cache/watch-later/截图目录、无 API 凭据环境，仅终止自有子进程PID。测试中普通用户 mpv/其他 GPU 重负载若存在，记录污染并暂停/拒绝测量，不杀别人的进程。
3. RIFE 必须是真实本机 VapourSynth + Vulkan RIFE DLL/模型推理，不用插帧桩或仅 FPS metadata 标签。当前活动脚本静态事实：540p 上限工作图、model=70、factor=2、gpu_thread=2，保留源帧并插入中间帧；不是全1080p神经网络插帧。脚本与启动器只读相关代码，不复制私人配置正文到Git。若使用其测试副本，记录算法段哈希/限定路径重定向差异，不『优化』算法。
4. 只读勘察 `D:/MPV/vs`、`D:/MPV/rife` 的版本/选定依赖路径/模型。真正加载前必须证明缓存/引擎/pycache/模型下载写入均落 TEMP：优先 clone 运行时/选定模型到隔离树并重定位 DLL/脚本引用，或有证据证明可读原库零写。禁 pip安装/自动下载/改原runtime。不能安全初始化则 RIFE 记 BLOCKED_ENV，不能假称已测。记录所加载 exe/DLL/模型/runtime hash、扩展自身缓存行为和运行前后源清单差异。
5. 只用合成或已获授权的测试媒体。不得扫描整个私人视频库。当前无明确提供的动画/实拍片段，需把自然样本可用性查明：合成线条/纹理/运动用于机器校准，不冒充真实动画/实拍主观测试；不足时提供待用户素材入口/保持 PENDING_USER，不自动下载版权样本。

## 公平 A/B 与输出语义

- 基线必须含 high-quality/ewa_lanczossharp 的实际属性，不能拿默认bicubic偷换用户原高质量基线。stock Anime4K 保持原文件和六链身份，可主矩阵选固定Mode A、另列其它模式的适用范围，不能把单模式外推全家族。
- 预注册固定样本hash、段落/帧序号/PTS、输入format与位深/色彩矩阵/范围、输出显示视频rect/窗口实际像素、backend、shader参数、RIFE状态、refresh/vsync设置。同一组不能以不同源帧或输出大小拼图。源24→RIFE48、源30→RIFE60分层，不能把RIFE开关的不同中间帧硬称同帧；原帧对齐比较和插值帧单独标注。
- 同一主链，不叠多个算法，参数语义独立列。不同算法锐度数字并不等价：报告默认值、可调范围、机制差异；不要声称统一数字=相同锐化强度。锐化扫档作为PIC03分层实验，不在看到结果后挑最佳参数作为全体默认。
- 主场景1080p→2560×1440。Integer该场景显示rect为1920×1080而非2560×1440，不能混入全屏等尺寸排名；单独『原生整数显示』类别或用720p→1440的k2共同目标。像素艺术独立组，xBR/Nearest不默认适用实拍。SharpAUTO退化如实分类。
- 帧图PNG先检查尺寸/位深/实际视频rect、OSD-free及对应帧身份，再建立盲标签/随机顺序评分材料。无模型替用户评分；默认档维持不变。若只有合成素材，客观样本集可交付，但PIC01主观/自然视频代表性仍pending。HDR/RGB画质不扩范围，SDR主测，格式守卫不冒充HDR质量。

## 性能、帧节奏与真实 RIFE

### 预注册与公平性

- 明确主要终点、固定预热时间/编译完成判据、测量窗口/重复次数、固定随机种子且平衡ABBA/拉丁方或随机配对顺序；独立重复的单位是一次完整run，不是同一滚动buffer内每个值。
- 记录 GPU温度、实际时钟、显存、utilization、其它负载、显示refresh、mpv构建、CPU/存储/decoder设置。不能自动改电源/频率/风扇。给污染阈值/失败或剔除标准，预先定义，失败与被剔除原始run不删。
- 规划资源和时长预算：先短校准验证链路，再主矩阵；不默认超大跨档/6mode×2RIFE×2fps×多样本×长时长爆炸。缩减范围必须预注册并明确未测组合，不在结果之后删失败。代理调用超时不能截短到数据不足还PASS。

### GPU耗时

- `vo-passes` last/avg/peak/samples 单位ns，除1e6转ms；fresh/redraw分列，不混 shader总和与端到端GPU时延，不把pass count/FPS/启动墙钟当GPU时间。读取频率与IPC开销须校准/空载对照。
- P3采样滚动窗口重叠/值重复，P4不能把重采当独立样本，也不能按数值去重（相同值可是真实不同帧）。观察到32ns倍数不能单独断言硬件timer分辨率。
- 需用可验证窗口边界/独立run抽样策略防重叠：若无真正逐帧身份，保留明确的单run快照分布及『末N计时样本』含义，而非自造独立逐帧数据。分位数以可解释单位计算，估计置信区间以独立run重抽样；重复不足不做显著性/绝对优劣外推。

### 帧节奏

- dropped-frame-count/decoder-frame-drop-count、mistimed/delayed/vo-delayed、vsync等具体字段先在固定构建实际探测，计数有reset/累计差值语义。
- IPC观察时间间隔不等于实际屏幕present间隔；`time-pos`是媒体时间不是呈现时间。真实呈现帧时长若需要ETW/PresentMon等，应探测合法可用采集源与权限，不自动安装/提权/改系统；不可用时报告renderer指标和媒体节奏proxy局限，帧时长分布未测不能称已完成。
- 固定48fps/60fps的20.83/16.67ms只是节奏预算，RIFE与shader非独立可加预算。真实RIFE余量须同一播放pipeline上RIFE OFF/ON×各档匹配实验与稳态实测；不能CPU walltime减shader GPU平均凑余量。
- 证明确实执行RIFE：所加载DLL/model、输入与滤镜输出帧率/PTS、真实中间帧（与邻源帧差异）的可复核样本、VapourSynth日志/filter状态；仅FPS翻倍不足。模型对某些静态或规则合成运动输出等邻帧不能一概否定/假造，应选择有鉴别力校准样本并解释。

## 证据、状态和门

- 原矩阵PIC01..04/PER01..05保留语义（PER04从P3后端扩为RIFE竞争观察）；主观与客观分栏。新增CAL-01（测量校准/滚动窗口/观测开销）、TIME-01（呈现来源/局限）、RIFE-01（真实模型身份和执行）、EVI-01（完整性和反指标负例）。BAK04安装器/真实恢复路径留P5，不偷塞本阶段。
- 每trial独立create-only目录；任何证据目录重用启动mpv前拒绝，所有selfPID和日志句柄结束后才manifest；失败保留。全树覆盖input/media/runtimehashes/命令/console/transcript/passes/telemetry/PTS/PNG/分析参数/表格，每产物SHA实际算；作者/独立复跑分别新目录，单一GPU owner，不并行测GPU。
- 所有当前执行工具/测试/fixture/分析代码/参数seed/plan/实际flow与环境依赖明确绑定；候选固定后两审同SHA，改动使受影响证据失效。不泛抓旧失败manifest作新正证。
- 报告可能是PASS_OBJECTIVE_WITH_PENDING_USER、PARTIAL_MEASURED、BLOCKED_ENV或REWORK；『没有提升』『某档更慢』『某些原指标无法获取』都是有效实测结论，但未测必需项不得包装全P4 PASS。PIC评分、用户默认档选择不可机器代签。
