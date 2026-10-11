# B1 同阶段修订 r2：真实负例修复，未测量

## 保留基线与授权

原B1候选`build-b1/candidate.json` SHA b04b3823272be91422fcf812e613bb732b538179b83bd77c170aea25e428aced，原23文件归档在`docs/验证/开发/p4-001/build-b1/blocked-source-snapshot/`；原审查`build-b1/independent-tooling-review.json`有F1 blocker、F2..6 major、F7..9 minor，原意见不能删改。P4批准plan/许可与5715旧文件继续不变。本修正只对B1新增七文件，严禁GPU/mpv/VS/产品/旧源码/许可/计划变化。

新证据命名空间`docs/验证/开发/p4-001/build-b1-r2/`，每产物create-only。两个串行写者：A修lib+analyze+两tests；A完成退出后B修evidence+verify+test。旧hand-off只对应旧归档，不覆盖旧哈希来凑通过。未来正式benchmark仍锁住。角色固定Flash/xhigh。

## A 单元（analysis）

写域：`tools/p4_lib.py`、`tools/p4_analyze.py`、`tests/test_p4_lib.py`、`tests/test_p4_analyze.py`；证据`build-b1-r2/analysis/`。只跑这两套及静态schema，B未迁移前旧evidence tests可以暂不兼容，交接列明迁移diff；不得跨域改。

- **F1：空真**。真实性能窗口必须fresh表非空且每pass有效非空采样（redraw允许空，不能把其0误当fresh0ms）。空fresh/零timing/空samples拒绝参与n_valid/MEASURED，原run连原因保留。不要仅两表相加非空就让redraw替代fresh。若某合法优化pass没有计时，标未可测，不强塞零。
- **F4：窗口**。10条不等10秒。严格递增monotonic及每个slot相对warmup_end的1秒调度检查，预注册本修复容差±0.25秒（只是采样调度容差，非present保证），实际10个slot应0..9秒，半开窗口10秒；首末跨度8.5..9.5秒，超过拒绝（nvidia-smi造成超时也应暴露，不能插值）。record必须有实际`warmup_end_monotonic_s`且与第0slot对齐。time_pos单调，不用其细步长替代墙钟；无呈现帧时长推断。未测前新增容差是收敛接口，不按性能结果调参。补相同时间/递减/0.001间隔/过短/迟poll/缺锚点/边界负例。
- **F5：上下文交叉校验，纠正原建议中的坐标混淆**。source.clip/mediahash/generatorhash与spec.input_bindings及clip注册表一致；frame.index/pts为source帧身份时必须合法范围与对应分母/分子，RIFE输出帧索引是另一命名域不可偷套source上界。只检查字段存在远不足，缺必需observations不可有效。
  - `video_out_params.w/h`与滤镜后源大小比，当前RIFE恢复源大小；**dw/dh是有效源显示尺寸/SAR，不是窗口或shader输出rect**，不能采用原F5 fix所写dw/dh==targetrect造成P2/P3老错再发。当前合成square pixels源dw/dh等源w/h；明确此边界。
  - `osd_dimensions.w/h`是窗口原像素，显示rect应由osd dimensions的ml/mr/mt/mb或单命令实际视频rect字段得出。主G1 2560×1440，G2 Integer窗口仍2560×1440但rect=(320,180,1920,1080)，G2b fullrect，G3窗口1440×1080。库现G2 output_size混作视频大小可保legacy明确字段，但必须新增独立expected_window_size，不许用其wrongsize判窗口。真实collector以后填实际margins，不允许复制spec假装observed。
  - 反例包括合法G2letterbox+错误源/窗口/rect/margins/clip/帧号/不同sourcehash，测试要invoke真实validation。
- **F6上游**：rife ON缺真实observed_output_fps拒绝参与统计；OFF也实读原fps，以数值非bool有限且应匹配source*factor。此项必要不充分，不能因为fps够就RIFE执行PASS。
- **LF10新发现/major：vo-passes samples类型错**。权威`docs/证据/mpv-input.rst:3657..3715`及P3真实raw可只读：`count`才是本pass样本数，`samples`是纳秒耗时array。现lib require_int(samples)与analyze文案均错。统一映射normalized `{desc,last_ns,avg_ns,peak_ns,count,samples_ns}`（或保持samples原名但必须array，交接写清），保留全部raw样本值和重复值，count==len(array)，正数/有限数/bool拒，不能按值去重。std attrs readonly参考，不修改P3。若count字段API省略必须映射时记录缺失，不伪造未知nativecount；库契约应能保留原node及normalized映射关系，后续collector校准实测。
- **相邻边界LF11**：pass desc不是唯一ID；原代码拒重复可能误杀合法重复名。原序号+desc作为稳定身份，检查epoch内完整有序表，保留同名pass各自数据，不合并/去重/重排。新tests包含两个相同desc不同slot，完整recipe/DESC身份后续B3独立契约提供不能仅字符串有无。
- F8当前production恒拒保留，未来解锁另建许可修订和新candidate，不为当前测试偷开门。

A交接`handoff.json`: stage/session/unit=analysis/status=BUILT或REWORK/plan_sha256/source_hashes{exact4files}/tests[{command,returncode,console_path,console_sha256}]/apis,api_delta,limitations,gpu_started=false,live_configuration_written=false。真实日志原样新建。

## B 单元（evidence）

前置A单元gate，写域`tools/p4_check_evidence.py`、`tools/p4_verify.py`、`tests/test_p4_evidence.py`及`build-b1-r2/evidence/`。实读A更新的公开API，不能回改A源凑fixture。

- **F2**：stage report不能信自declaredPASS。trial须已知schema、绑定raw run/analysis/plan/sourcepins，必须实读文件/实sha/重新analyze并过gate。无raw或未知schema标违规，不能升级任何单项。测试用真实analyze输出+完整临时依赖链作为正控，裸trial.json为负控。明确calibration与生产及各test判据，不凭一个run或测试fixture声称PIC/CAL等所有项通过。stage最大partial、人/present必须未测；合成mock只验证代码分支，字段标test_fixture者绝不进实际stage合格项。
- **F3**：使用真实analyze_records输出的rejected_by_analysis list，遍历run_id（必要兼容必须有明确schema），不是tests自己造dict。E1..6剔除与analysis拒绝均保持原文件绑定和原因，缺任何失败原件违规。CLI意外异常结构化FAIL并非静默pass；别用tryexcept吞错误转ok。
- **F6本层**：RIFE四件套类型+hash实存+相互身份验证，dll/model可多hash对象且比对勘察钉值；实fps=2source，middleframe/log绑定tree文件与真实bundle标志(只是严格结构并不声称防恶意伪造)。空字符串/False/None/0四键不能过；仅键非空或任意hash无文件不够。将proof解析API扩成可传root/context而不是自然语言断言。真实推理负控判据按已批准plan，不为模型强加线性插值。
- **F7**：stage明确`n_measured=0`与`measurement_status=NOT_RUN`，可保计划词表下stage PARTIAL_MEASURED但必须注解它不是存在部分实测，ok仅表示验证器未违规不是测量验收。
- **F9覆盖**：gate_candidate必须按明确依赖清单+plan.write_paths+source fixtures等对账；终版任何预定文件不存在failclosed，不能is_file跳过，阶段工具候选可显式stage/scope/pending列但绝不冒final。verify_stage调用对应candidate/closedtree/coverage门，不能公开有严门但真实入口不调用。还没有collector/candidate终版的现实输出NOT_RUN/BLOCKED_MISSING_CANDIDATE，不造空pass。
- 迁移原evidence fixtures到A真实新版采样合同包括时序/geometry/fps/arrays，原功能负例保留，不删测试或弱化预期为了凑绿。

B交接同A结构，unit=evidence、source_hashes exact3files、tests数组；必须跑全部P4新增+原282单测及48guard，日志create-only。后续领导者机器gate独立全复跑、冻结新candidate，再同候选只读限域复审F1..9/LF10..11及相邻边界。两写者每个≤60工具调用；卡在契约请REWORK交接，禁止盲完成、GPU、跑完整媒体生成。
