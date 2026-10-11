# B2：隔离采集器与真实 RIFE 首载（先实现/安全复核，再执行）

## 入口、分工、保全

B1-r2专项审查通过：`docs/验证/开发/p4-001/build-b1-r2/candidate.json` SHA `929079b09d1c1ac10f262ebc05e7d311ca5943d58eeb5731890199d803d17f3b`，仅PASS_REVIEWED_BUILD_ONLY，无GPU/测量。B1源码API现固定，不得悄改以适配采集器。完整读B1新两handoff/api_delta、已批准P4计划、执行约束与环境勘察。planSHA仍5285d112…822a。

W2写者只新增`tools/p4_collect.py`、`tests/test_p4_collect.py`，证据`docs/验证/开发/p4-001/build-b2/author/`。不改前序7工具/tests/plan/auth/guard/旧5715/活动mpv/DMPV。当前所有P1-P4未提交dirty为保留基线，禁git reset/clean/stage/commit。

**本实现角色只做纯代码+mock单测，不启动mpv/GPU/VS/nvidia-smi或复制runtime。** 独立安全/方法复核同候选通过后，由独立只读执行者运行create-only短首载与采样pilot。生产仍锁住，不自动跑136矩阵或全长所有媒体。两步角色不能边改源边验。

## 新工具的有界能力

1. CLI默认help/只读预检；显式prepare-runtime/identity-probe/pilot/capture模式才执行。禁止production（即便给某json文件写pass也拒）。所有入口先P4许可真实check+B1-r2固定pincheck+路径检查+磁盘预算；试验dir必须新建，已存在在任何进程启动/clone前拒。只允许session树证据与唯一TEMP sandbox写，不允许调用者--config-dir指向活动配置/原runtime或任意删目录。
2. subprocess环境allowlist，HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/TMP/cache/watchlater全部沙箱，PYTHONDONTWRITEBYTECODE=1/PYTHONNOUSERSITE=1；PATH只cloneVS及System32/必要NVIDIA query工具绝对路径，不继承APIenv。直接`D:/MPV/mpv.exe`、固定gpu-next/Vulkan、no-config+显式临时config，fullscreenflag以真实osd宽高读回验证，不复制旧MpvSession.start中被--fullscreen=no覆盖的bug。用现p1 IPC辅助可以只读复用但检查其默认opts是否违反，禁monkeypatch项目库/全局DPI/kill-all。
3. 仅停止工具自己启动且记录的PID/process对象，timeout/异常finally关闭IPC/日志/进程；所有自有句柄结束后才manifest。日志晚flush不能绑定后漂移。dryrun/mock不产生真实测量状态。
4. 克隆勘察规定的D:/MPV/vs整树约223MB、RIFE DLL及唯一selectedmodel目录约16MB到TEMP**新**树，rejectlinks/reparse（包括内层）；禁止pip/下载/updater。从活动vpy只复制到TEMP且只重定位LoadPlugin一行，逐byte比较其余算法未变，记录原SHA/替换行范围/算法hash，但私人vpy全文不进repo。VSSCRIPT_PATH和PATH都指clone。加载前后对原DMPV/vs,rife及活动mpv全树hash/size清单差异为硬门（只存路径hash不私人正文），与勘察相关DLL/model pins匹配。缓存/pycache/引擎等只能沙箱；若不能满足安全前置则BLOCKED_ENV，不初始化试试运气。文件hash检验是前后可检测性，非系统沙箱/防同权限恶意写者。
5. GPU污染先查普通mpv进程冲突与nvidia-smi全GPUutil/memory门（WDDM逐进程N/A不是0）；不杀别人/锁频/改刷新率；记录温时钟/采样开销。blocked状态保留，不能对所有blocked循环等待。查询也必须清理env、TEMP cwd。
6. 同一基础config=profile high-quality，所有arms共享nonalgorithm设置；实际readback与B1 expected_window_size/displayrect/source dims区分。复制全shader资源/原Lua/两conf到临时config，以产品IPC切换唯一主链，Off不叠原Anime链。读原库辅助API/实际产品protocol，不猜消息名。试验sourcepins明确含全部实际运行文件及资源manifest。没有算法作用证明时pilot=NOT_ESTABLISHED非active就PASS。
7. 原子采样由TEMP Lua helper单个script-message触发，在一个mpv事件回调收集native node，再结构化传IPC；记录collector接收monotonic与回调媒体时刻，但不宣称GPU原子屏幕present。保留vo-passes raw native arrays，normalized映射`count`与`samples_ns[]`严格按B1 API，fresh/redraw+ordinal完整。source/frame身份/epoch/actualosd margins不能复制spec假观测；无法确定瞬时精确source frame则诚实缺项不伪造精准PTS/index（pilot可partial，后续静帧capture另有可证索引）。帧率实际filter-output字段先探测，container-fps不充ONoutputFPS。
8. 稳定判据与1Hz窗口按计划/B1r2容差；10..15秒预热→相对warmup_end10slot，raw值全保存，emptyfresh/zero timing不合格。采样drop计数与rollingcount分开，dropaffected计入非效果剔除。定时器采集的monotonic不是present；采样库失败→相应REJECTED，不能靠绕分析库输出pass。collector接线N1：实际媒体manifest落地后必call `lib.verify_required_inputs` **以及** `ce.gate_run_evidence`，不只走较松stage gate。截断/缺真实姿态保留。
9. 尽量复用B1生成器数据；prepare-media用于未来四种30秒clip，流式PNG生成→固定mpv FFV1 yuv420p transcode/实decoded参数核查→持久evidence原媒体/sha；不能批量生成后再测磁盘上限。W2单测只极小TEMP帧，不真生成全1080p30秒。若已批准PNG→编码路径不可行，按计划回退/blocked，不偷偷用RGBPNG测LUMA档。短首载专用Y4M合法且与production四clip不同，如下单独预注册。

## 首载专用短样本（现在预注册，未看模型输出）

本B2独立首载不是性能矩阵；原四clip参数与图像不改变。选定唯一鉴别样本：`rife-identity-short-v1`，源1920×1080、SDR BT709 limited yuv420p、源24fps与30fps各一版本，**12源帧**。Y plane底16，半径120px亮盘中心初始(600,500)，每源帧位移(8,3)px；盘内斜向条纹亮度180/235(周期12px)，另一固定细纹方块提供非刚性差异，U/V常128。源索引用顶端8px二进制条luma64/192编码；算法纯bytearray/std Python按行写，Y4M完整frame marker+payload长度逐检。源sha/生成器sha/完整参数入证据，不使用偷拍媒体。短片12帧只用于证明加载与filter输出，不套30秒/10秒窗口来判无效。

真实RIFE活动算法仍上限960×540 work、model70/factor2/gpu_thread2、source+middle交错。路径改动外不改模型参数。不得因为结果差临换鉴别素材/阈值。优先独立`vo=image`落filter-output帧鉴别与实际输出PTS（但它不运行gpu-next shader，绝不供PIC算法A/B或voGPU计时）；日志必须辨识真实VS/RIFE加载/模型参数，若插件不打印modelname，使用选定唯一模型hash+目录/成功初始化等能证明什么写什么，无法证明索引映射则NOT_ESTABLISHED，不捏造日志。

沿批准plan的noncopy/nonblend判据与四件套：实际DLL/model/runtime hash、realvf/输出fpsPTS、持久源/中间帧PNG、真实engine日志。对预定连续S-M-S三元组逐项记录decoded RGB MAE，查M不是邻帧复制，记录与逐像素50%blend的差异；阈值按批准plan若有精确值遵从，没有硬阈值则原始数值+负控结果、NOT_ESTABLISHED，不偷偷临定阈值算PASS。vo=image若尾部多/少帧/奇偶与Interleave未能锚定必须如实不足，不能仅输出count翻倍判推理已证。

可以只完成真实初始化与可用性证明，不自动宣称RIFE-01完整PASS。完整B3校准/production仍需后续实证与独立门。B2总GPU≤10min，CLI每trial有timeout；常规pilot≤40秒，首载进程≤160秒（校准4倍40），超过保留TIMEOUT，不提高直到看起来成功。

## 测试、交接

mock tests真实调用安全入口，覆盖复用dir启动前拒绝、越root/linkedtree、dirtyruntime检测、clone缺DLL/model/错sha、vpy非路径差异、env无凭据、PIDown/finally关闭、production拒、无rawsamples数组、错framefps/几何、窗截断/迟采样、原件missing和N1接线，短Y4M真载荷完整与12帧/位移可重现。不要用mock只返回你想要的PASS。collector函数签名/CLI必须documented可执行，前序缺接口请REWORK不能回改B1。

写者最终`build-b2/author/handoff.json`：stage/session/unit=collector/status=BUILT|REWORK、plan_sha256/b1_candidate_sha256/source_hashes exact2files、tests数组{command,returncode,console_path,console_sha256}、apis、safe_cli_examples、known_limits、gpu_started=false、live_configuration_written=false。实际跑本套+全509原/新增tests+48guards，日志create-only。最多60工具调用，不把代码尚未执行说已经校准。独立机检冻结候选后安全复核，再交只读执行者做首载，任何blocker留原证据限域修订。
