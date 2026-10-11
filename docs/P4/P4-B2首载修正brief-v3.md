# B2-r3：修真实入口，然后只跑24fps/12源帧

用户本轮明确授权『按照这个计划开始执行吧』。不再做宽泛方案审计、不跑性能矩阵；解决identity-run-001实证问题→独立安全复核→一个新目录的24fps短样本。原RIFE算法、样本、阈值、活动配置与部署边界不变。

## 基线/角色/写域

- `P4-B2-r3修订基线.json`钉当前114文件归档和349个既有P4文档/证据；旧候选0d0bf8…、identity-run-001失败日志/12JPEG/错误manifest原样保留。原617单测（skip1）+48guard不能删弱。
- 单写者只edit `tools/p4_collect.py`、`tests/test_p4_collect.py`；新证据`docs/验证/开发/p4-001/build-b2-r3/author/`。全部前序B1工具、plan/许可/guard、原DMPV/活动APPDATAmpv与备份零改；无Git操作。agent固定Flash/xhigh，非幂等写者不得盲重放。
- 源作者结束后，机器独立全回归→固定候选→不同上下文只读复审→不同只读执行者真实RIFE。GPU操作只能最后执行者单独串行，无部署/主观代签。

## 限域修复验收

**R3-1 自动沙箱**：new_sandbox_root不能先mkdtemp创建最终root再交给create_sandbox拒绝。仅选择不可预测唯一的不存在名称，由唯一create-only入口原子建；保留TEMP/p4-001 child限定、protected root与alias/link拒绝。补不传--sandbox-root的完整CLI路径测试，不只测手填新路径。

**R3-2 真正加载隔离配置**：查identity-run-001真实日志，--no-config+config-dir不会加载临时mpv.conf。保留不读活动/系统配置的隔离性，显式加载受控沙箱内配置（例如经验证的--include=<临时mpv.conf>或显式安全argv），不直接--config=yes恢复自动读全局。明确Lua脚本是否显式加载（sampler与产品），不要依赖被禁的自动扫描。RIFE vf/PNG设置/HQ共同基线都应真正生效，而不是argv字符串存在。

为阻止再次只mock通过，本轮**允许作者一个非GPU、非VS真实mpv配置加载smoke**：固定D:/MPV/mpv.exe，临时无凭据env/cwd/config；强制vo=null、ao=null、无媒体或小合成媒体；仅加载临时sentinel Lua读取两个不寻常配置值/脚本消息并立即quit，10秒超时自有PID；不加载RIFE/DLL，不初始化图形设备，不读私有正文。stdout/log/argv/配置和sentinel作为新author证据，证明实际include路径生效+未误加载trap配置。普通unittest保持TEMP mock，不把此smoke当RIFE证明。允许在这同一受控smoke对旧参数作负控，所有尝试新目录留证，不增加真实GPU测试。

**R3-3 真实log与状态**：启动argv/session/结果引用唯一实际log路径，日志文件必须存在且关闭后实hash；空/缺/错log、仅rc0、仅命令行vf字符串、无有效vapoursynth链、12帧原样passthrough均不能initialization=EVIDENCED。依据运行期初始化/有效vf/真实输出与模型证据分别给加载、帧率/帧序、模型身份状态，不能混成一个绿灯。PNG以实际magic/尺寸判而非扩展名；JPEG失配要明示，不按png glob空表装成功。输出PTS若不可获应NOT_ESTABLISHED，不能按目标48fps自己生成PTS当实测。

**R3-4 安全收尾与真实性字段**：进程结束且句柄关闭后再最终witness/log分析/hash/manifest（timeout同样），primary与cleanup异常保留。gpu_started不能永远写false，也不能见配置行就true：实际Vulkan RIFE运行证据可true，未知用明确UNKNOWN/NOT_ESTABLISHED补充字段；无GPU证据不可声称模型执行。connect deadline统一monotonic，保持真正可打断IPC/watchdog与only-own-PID规则。

**R3-5 非混帧负控准确命名**：nonblend_all_unique当前仅帧hash不重复，不是非blend证明。改成诚实all_frames_unique，并对同一S-M-S像素实际计算50%blend差异，保留误差分布/判据来源；如果计划没规定可判阈值，就标NOT_ESTABLISHED而非临定阈值后宣布过。既有noncopy阈值/样本/model70/540pwork/factor2/gpu_thread2不改；不能见输出差再换样本/调整参数。

测试必须有默认CLI、真实config-smoke证据、rc0+空log/仅argv配置/无vf/错格式/passthrough、timeout后witness顺序、未知GPU状态、等邻帧/纯blend负控。修改被证明错误的旧测试契约要记录，不删正常行为测试凑过。不要顺手重构整个collector，也不补capture/B3尚未实现功能。

## 作者交接

`build-b2-r3/author/handoff.json`：stage=P4/session=p4-001/unit=collector/status=BUILT|REWORK/plan_sha256/b1_candidate_sha256/source_hashes exact2files/tests数组{command,returncode,console_path,console_sha256}/resolution R3-1..5/known_limits/gpu_started=false/live_configuration_written=false/config_smoke{command,report_path,sha256,gpu_started:false}。全部日志create-only，先关闭再hash。实际跑新增collector+全tests+48guard；没有smoke证据不能BUILT。≤50工具回合软限，不做宽泛研究。

## 独立只读安全复核

仅R3-1..5和相邻边界，同一新candidate。重点看真实config-smoke及捕获路径/字段证明链而不只617+测试数。不得修改源或运行GPU/VS；小TEMP反例可。JSON severity只能blocker/major/minor，informational进checks/limitations；major必须block，原意见留档。校准与真实推理尚未执行不得代签。

## 唯一真实执行：identity-run-002

独立执行者在review通过后：

1. create-only `docs/验证/开发/p4-001/identity-run-002/`；固定candidate全部pins+许可确认；不改源、不patch任何返回值。preflight负载检查拒绝则BLOCKED_ENV，不杀别人。
2. 只运行修复后原生CLI的**默认自动沙箱路径** `--mode identity-probe --fps 24`，由无凭据TEMP supervisor调用，内部160秒上限、外部300秒含clone/hash；总GPU10分钟。不要先prepare-runtime同路径。默认入口失败就停，不改用显式路径额外重试；本轮不跑30fps/性能矩阵。
3. 用源12帧合成Y4M，核真实vf生效/真实日志/输出PNG、可得的帧率PTS、插值帧证据；模型名不打印就如实身份未证，不能把24输出帧数独自当模型证明。不能改样本或阈值。失败要精确定位到本次真实报错，保留而不现场修源。
4. 所有owned PID与句柄结束后持久保留非私密原Y4M/PNG/log/stdout/witness/manifest；私有vpy全文/runtime/model binary不进repo，仅hash与必要路径差异。原TEMPmanifest作为raworiginal不重写，新联合清单仓库相对files映射全树除自身。绑定本brief/实际flow/gate/supervisor源码。
5. `execution-report.json`字段：stage/session/candidate_sha256/status=MEASURED_IDENTITY_ONLY|NOT_ESTABLISHED|BLOCKED_ENV|REWORK、attempts、gpu_started按事实（不能看旧hardcodedflag）、live_configuration_written=false且有witness、production_unlocked=false、performance_measured=false、source_unchanged=true、runtime_before_after、retained_artifacts、limitations。末尾独立machine gate只确认报告完整性/原tree/备份，不把流程completed当RIFE成功。
