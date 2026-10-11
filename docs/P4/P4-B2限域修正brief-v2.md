# B2 r2：先修确定性首载失败和越域写风险，再允许运行

## 保留

原candidate `build-b2/candidate.json` SHA 6d67d2b8fcae50ce2e23e9c4d7d62ef7e6fe1e1878d6c3e449a91c15eccae89a，101文件逐byte归档`build-b2/blocked-source-snapshot/`。审查实际输出high/medium/low/info违背合同，原报告已保留`contract-failed-review.raw.txt/.json`，未签safety-method-review/未授权首载。这里依据具体反例发返工，不把不合法review冒合法PASS。

单写者仅修`tools/p4_collect.py`、`tests/test_p4_collect.py`；旧B1七源、P4plan/guard/许可、5715保全、原handoff与日志不可改。新输出`docs/验证/开发/p4-001/build-b2-r2/author/`，create-only。没有真实GPU/runtime授权给写者，仍仅TEMPmock，成功后新source pin与同候选安全复核。

## 修正及真实负例

1. **F1/major：identity-probe必然失败与资源清理**。create_sandbox只建runs而CollectSession期望runs/identity已存在；使session试验dir按create-only建立。EXITED路径没关闭日志/IPC/handles就manifest，引发HandleStateError；`finally:pass`不是清理。所有EXITED/TIMEOUT/启动后异常/PNG鉴别或witness异常路径均应finally关闭IPC+own process+logs，之后才hashmanifest；失败的primaryexception与cleanup异常都保留，不把未关闭也标closed。端到端mock测试真实走run_identity_probe而非只测试低层方法，至少成功进程退出、timeout、start失败与proof阶段异常，验证noorphans/关闭顺序与证据保留；不跑真正mpv。
2. **F2/major：sandbox路径应在任何写前硬拒**。--sandbox-root可写D:/MPV/sbx-new现违背TEMPonly且witness不覆盖顶层新增。检查必须在公共create_sandbox与CLI、prepare-runtime/identity/pilot/media所有入口，sandbox规范化后只能在可信TEMP/p4-001父下，不得在DMPV/APPDATAmpv/备份/项目树，rejectroot itself/..aliases/reparse/symlink。不把newroot不存在当安全，不允许调用者env TEMP伪指向protected绕过。仅允许uniquechild新建，不删除他人目录。negative为protected新子路径，断言任何mkdir/copy/spawn前拒绝（mock，绝不真的往原树创建）。
3. **F3/minor：--trial-dir失效**。删除未支持flag和help或只允许sandbox内create-only限定子路径并实际传所有入口；不要接受后静默忽略，API调用同样保证。fixture和CLI文档一致。
4. **F4/major：退出码必须反映安全与证据失败**。pilot/capture/identity gate false或zero-write-violation不得rc0。区分NOT_ESTABLISHED（未证）与accepted，脚本调用不能以rc0冒通过；所有模式structured status与rc一致，任何检测到原树变化都hardnonzero并保留。报告条件失败无需制造异常堆栈作为唯一证据。
5. **F5/后续边界**：pilot不截图可允许pngs=None（稳态禁止扰动），但不能因此称RIFE四件套/PIC合格；capture若尚未真实输出图必须明确NOT_IMPLEMENTED/PENDING，不允以--mode capture复用timing冒图像试验完成。无需当前补整个B3，但用户清楚哪些CLI已经可用。
6. **L1/major，领导者额外复核**：CollectIpc._read_line使用同线程blocking readline；cmd无限循环，wait_sample_reply所谓deadline仅行间检查，**无法终止一个不回行的活着进程**。不能将in-loop deadline称wall cap，run_timed_trial在主线程阻塞时不会执行finally kill。实现真正可打断的读取/请求超时（例如readerthread+queueget(deadline)，并独立ownprocess watchdog硬deadline，或Windows overlapped IPC取消）；统一monotonic总trial预算包括connect/cmd/sample/quit，deadline到期必须杀自有PID、回收线程/句柄且保存TIMEOUT。禁止全局kill/根据进程名kill。unit要真实阻塞mock管道/本地python子进程(标准库、隔离env，无mpv/GPU)证明无响应仍在短测试上限返回、不会留下非daemon线程/子进程，别只mock clock在正常readbetweenlines冒超时。close不能再次卡同阻塞reader的buffer锁；有并发锁设计要验证清理不死锁。

## 交接/验收

最多50工具调用，聚焦以上根因，不重写整个2800行collector，不越域动B1凑API。

source复核保持原B1r2candidate 36pins不变；作者跑新增collector tests、全部tests(原本589=509+80，本轮允许新增不删)、48guard，TEMP/无凭据无GPU；createonly原始console。handoff格式与B2原相同，source exact2file、tests数组、unit=collector、planSHA/B1candidateSHA、gpu_started=false/live_configuration_written=false，新增resolution逐项定位F1..5/L1与未实现入口。原80测试行为保留；更正被证明错误的低层契约需记录，不删掉端到端必要覆盖。

独立机检全复跑冻结新candidate，然后单个只读安全复审限定F1..5/L1与相邻安全边界。严格JSON severity仅blocker/major/minor，不要重复上次security-reviewer默认high/medium格式；informational项放limitations/checks。任何major仍block，未跑真实GPU不是代码失败，不得为省轮次冒允。通过后才能另调只读executor做真实首载，仍不运行正式矩阵。
