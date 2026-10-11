# B2 只读首载执行：真正运行，但不改候选、不声称性能通过

## 固定输入与安全门

- candidate `docs/验证/开发/p4-001/build-b2-r2/candidate-r2.json`，SHA `0d0bf8e8f24b03ae04107bf1f439ad34cb01f187aa2e97f88a4fd8198d5dcb2a`；114个pins，复核`build-b2-r2/safety-method-review.json`同SHA/pass无major后方可执行。
- 源`tools/p4_collect.py`、所有B1库、测试、plan、flow、guard一律只读。author退出，执行者不得临时修源或patch导入模块绕gate。
- 实际mpv/VS/GPU只本执行者串行。用户授权涵盖真实RIFE隔离测试；活动APPDATAmpv、D:/MPV、备份payload不写、不部署。runtime必须clone至工具认可TEMP/p4-001/<newunique>。禁pip/下载/updater/提权/全局kill/改DPI或频率。
- 整轮GPU墙钟10分钟硬预算；collector identity≤160s，CLI外层supervisor timeout 300s含clone/hash/收尾(非GPU运行窗)。外层超时应只清理本轮记录的selfpid，保留原现场，不盲重跑/改上限。

## 按次序执行

1. create-only本轮输出目录`docs/验证/开发/p4-001/identity-run-001/`；已存在则拒绝本assignment，不能覆盖或自动把失败隐去。读入口CLI/help，实算candidate/pins+许可。使用stdout/stderr文件绑定，而不是只保存terminal摘要。
2. 无GPU的preflight，检测其它mpv/负载。预检拒绝则记录BLOCKED_ENV结束，不杀别人、不持续等待。执行工具cmd必须由无API凭据子环境+专用TEMP cwd调用，但repo_root/产品路径以工具真实要求保持（不要改变temp约束base的含义）。可以TEMP小runner包装subprocess环境/日志/超时，runner字节纳入本轮清单；不能做sourcepatch/伪造方法返回值。
3. 新sandbox路径执行`--mode identity-probe --fps 24`。不要先同路径prepare-runtime再identity（create-only复用会拒绝）；identity自行clone/load。必须用R2版已审CLI。短样本为预注册rife-identity-short-v1 12源帧，仅证明真实RIFE首载/输出，不作GPU性能数据；vo=image不等shader pipeline画质。
4. 如24fps成功加载真实推理且能产出足够实际结果（即使model名字未打印导致NOT_ESTABLISHED也可如实测另一fps），再用另一个**全新**sandbox执行fps30。若24遇确定性接口/安全/启动失败，停止并精确上报REWORK/BLOCKED_ENV，不盲重试掩盖；不允临改rife参数/素材/判据凑通过。
5. collector所有自有PID终止/文件句柄结束后，把合成源Y4M、原分辨率输出PNG、mpv/console日志、runtime来源hash/前后witness、normalized参数/实际vf/PTS/状态、试验manifest等**非私密**正负原始产物持久复制到本轮证据树，逐文件sha与TEMP原件一致。私人vpy/python runtime/模型binary不复制入repo，保留哈希/路径重定向证据；不伪称private正文已纳Git。日志只必要路径可保留，若含private正文必须原件留明确外部持久artifacts并记录隐私限制，不用删除/掩盖错误日志。
6. 复制旧manifest若键仍TEMP路径只作为raworiginal，不重写冒仓库路径；新仓库相对联合清单额外绑定copy相同byte，并记录source_location→retained_location/hash。不要覆盖工具原manifest以适应收集器路径。
7. 末尾再次实算候选pins、P4 preserved/permit、原runtime witness、55文件备份/活动源，记录源/运行时零漂移（若不符忠实FAIL）。不要执行create-only结果脚本或P3全GPU套件。备份是只读verify，不restore。

## 报告合同

`identity-run-001/execution-report.json`：stage/session/candidate_sha256/status=MEASURED_IDENTITY_ONLY|NOT_ESTABLISHED|BLOCKED_ENV|REWORK、attempts[]含exactcommand/rc/sandbox/PIDs/实际mpv启动与真实输出/推理证明局限/framescount/fps/proof日志引用；gpu_started布尔按事实、live_configuration_written=false仅经verify、production_unlocked=false、performance_measured=false、source_unchanged布尔；source_hashes、runtime_before_after、retained_artifacts、limitations。`evidence-manifest.json`绑定全部已关闭文件（自排除本manifest，由独立机器gate补hash）。任何model身份/FPS/PTS/原帧类不够明确要如实NOT_ESTABLISHED，不因初始写者宣称代码可执行而强PASS。

本轮最多35工具调用，失败精确定位并结束，不修bug、不另开review、不制造性能数据。最后交接报告/sha/实际GPU是否启动/原tree差异/明确下一步阻断。
