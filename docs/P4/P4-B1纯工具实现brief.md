# P4 B1 纯工具实现：三个串行写者单元

## 固定许可

- session=p4-001；plan SHA `5285d11293373a20523ac199de2868ac2911e550ffd48b47be164311888c822a`。
- `docs/验证/开发/p4-001/work-permit.json`：仅隔离工具与校准；production必须B4独立校准复核。
- 完整阅读已批准`docs/P4实施计划.json`、`docs/P4/P4测量方法.md`及权威`P4执行约束与验收brief.md`。计划不是已有测量结果。
- 5715已有文件、P3所有产品、旧工具/tests/guard/auth/计划/env/许可零改；本次只新增P4 tools/tests。P3未部署；TIME01真实present无源，真人自然样本缺失，全P4不得纯PASS。
- 当前dirty baseline为全部未提交P1-P4工作，不git reset/clean/stage/commit；模型固定Flash/xhigh。已失败两版计划与意见原字节保留。

## W1a：数据/合同/生成器库

写域仅`tools/p4_lib.py`、`tests/test_p4_lib.py`，以及create-only `docs/验证/开发/p4-001/build-b1/lib/`交接证据。

1. 纯Python3.9标准库，不启动mpv/GPU/VS/nvidia-smi/编码器，不生成全部高清媒体。**无import副作用**，不读凭据。明确可供后续collector调用的API，与测试/交接列签名。
2. 核心合同：trial spec（stage/session/group/clip/arm/fps/rife/expectedrect/outputsize/seed/repeat/production与calibration类型/工具plan输入hash等）；规范路径及create-only目录/文件、hash streaming、严格 bool≠number/NaN/inf 拒绝；拒绝绝对路径/..反斜杠/reparse、共享工作区外写。不要把路径检查称OS沙箱/TOCTOU防御。
3. 预注册clip四种：motion24、motion30、motion720、pixelart，全部30秒，fps/尺寸按计划。确定性media-seed派生按计划SHA公式，记录MEDIA_SEED声明常数及实际派生式，不用randomized hash()。给PNG帧生成与帧identity元数据（idx/pts/rationalfps），按需生成少量测试帧；代码高效支持后续逐行/流式输出，禁止一口气生成数GB才做单测。源YUV运动盘/标记设计参考计划；PNG RGB中间件需后续固定转换/色彩属性验证，不假称PNG天然YUV。原frame/unit fixture必须自包含/全部列入hash依赖。
4. 预注册G1/G2/G2b/G3与fps子集arm/cell枚举、n=5/3、repeat scheduling（seed20261007、相邻blockreverse以及odd5残余不完全平衡披露）、媒体长度与warmup(10..15)+window10+quit2.5预算检查。Integer1080 1x不可和全rect组排名。stock A不是测试stub。CLI/library输入禁止绕过defaultscope/生产锁；pure生成schedule不启动真实trial。
5. 采集JSON原始字段设计：fresh/redraw tables保留desc/last/avg/peak/samples/ns，不按值去重；epoch/geometry/source/frame metadata，snapshot wallmonotonic只作采集时间。采集器后做Lua单命令快照，不把多IPC读取假称原子。库可定义schema但不虚造采样成功。
6. tests含非法路径/复用目录启动前拒绝/bitdepth&尺寸与PNGdecode复核/同seed重现与不同frame变化/四clipframe数/超短媒体/odd-repeat标签/Integergroup/缺input依赖/NaN/bool负例。性能计数饱和不能阻断，设计采样状态留到W2。

## W1b：统计/分层库

前置W1a及machine gate通过后，写域仅`tools/p4_analyze.py`、`tests/test_p4_analyze.py`和`build-b1/analyze/`。只读前序API/测试，不擅改lib凑调用。

- 真实数据合同严格验证：每run10个1Hz采样(稳态窗口允许采集抖动但边界定义明确，不足不得自动插值补齐)、per-pass avg快照中位数→跨独立run统计；fresh/redraw分列，ns/1e6=ms；唯一run IDs，正样本/单位/DESC与上下文一致，pass变化/epoch变化拒混算。
- 完全相同数值可以是真实独立观测，不能按值去重；滚动samples/count非累计frame计数、不算独立N，禁止把sum(pass)叫总GPU时延。真实frame duration无源返回NOT_MEASURED而非IPC间隔/PTS冒present。
- n5/3：目标n未达即不足标注；run级bootstrap seed424242/n10000，拒空/NaN/inf/bool，n不足不伪显著性。不是通过CI就可宣称因果快慢。
- RIFE off/on分层匹配clip/fps/outputrect/共同HQnonalgorithmconfig；ON只有混合S/M，没有on内部每帧GPU归因，不造overallheadroom_ms。dropaffected保留参与，先验E1-E6可剔除且原因/原始目录记录不可消失。计数reset负delta无效、缺项explicit，不拿vo-passes.count做dropped累积。
- 结果schema纯结构化的comparability/measurement_kind/run_ids/cell/status与局限便于EVI语义检查，不能只靠扫描自然语言关键词支撑性能结论。`status`不能替人评分、禁止rendererstats→全P4PASS。
- 测试相同值/重复run/缺失raw/不足n/不匹配group/rife/rect/HQ/时间单位/rollingoverlap/负delta/截断窗口/无present/元数据假RIFE/非有限值。

## W1c：完整性门与阶段检查器

前置两个库machine gate通过，写域仅`tools/p4_check_evidence.py`、`tools/p4_verify.py`、`tests/test_p4_evidence.py`和`build-b1/evidence/`。

- EVI tree：全树闭合hash，仓库相对canonical键，文件都实存，symlink/reparse拒；create-only产物/目录和缺失依赖failclosed，manifest自身循环用固定小排除集+独立上级hash，不允许任意exclude逃逸。私有runtime副本正文不进repo，可绑定外部选定依赖hash但原合成PNG/media必须持久可读重核，preview不能替代。
- 硬验生产锁/calibrationpermit、stage/session/plan/candidate/sourcepins/全部精确write_paths与所有fixtures/environment/method/actualflow/guard依赖；还没生成的计划后期report可阶段声明pending，但最终candidate不能因is_file false漏查。作者/独立tree分离、禁止拼不同candidate或旧failed正证。
- 语义门基于结构化原始数据重算统计，不能只扫描『更快』字符串；核trial正确arm/完整recipe/DESC/nonemptysamples/epoch/geometry、sourcehash与PNG尺寸/frameidentity、RIFErealproof(不是FPS alone)、missingpresent/Userpending下不可全P4PASS；不混vo=image与gpu-nextshader截图。
- 支持partial honest report与需要补足的项目，但fixture/test-only绝不能成为真实stagePASS。`p4_verify`阶段未实测必须NOT_RUN/BLOCKED/PARTIAL，而不是造13个pass。默认CLI只验证既有目录，不启动GPU/实施正式测量。所有负例临时目录隔离。
- tests植入删除依赖/未创建文件/越界manifest/漏日志/伪截图或缩略代原图/错gear/window/全零pass/重复或缺窗口/RIFEfps-only/voimage冒shader/synthetic冒自然/userapproval/perpasssum冒overallheadroom/IPCsamples冒present/FAIL留痕丢失，必须实际触发门，而非断言自己构造布尔。

## 交接与独立机器检查

每写者≤45工具调用的小单元，源先完成再本地单测；必要先写API skeleton再填实现，不能把未完成TODO叫完工。安全check为`python -B -X utf8 -m unittest discover -s tests -p test_p4_<unit>.py -v`，标准库临时目录、无外部runtime。

每单元最终在对应新目录写`handoff.json`：`stage:P4,session:p4-001,unit:lib|analyze|evidence,status:BUILT|REWORK,plan_sha256,source_hashes:{repo_path:sha256},tests:{command,returncode,console_path,console_sha256},apis:[...],limitations:[...],gpu_started:false,live_configuration_written:false`。console原始输出create-only保存，失败也保留再新log，不复写。源必须与handoffSHA匹配。若依赖契约不可用，报REWORK并停止，不越域改上一个作者文件。机器gate将独立复跑P4新增全部单测及P4保护门，最终B1工具实现不代表P4测量通过。
