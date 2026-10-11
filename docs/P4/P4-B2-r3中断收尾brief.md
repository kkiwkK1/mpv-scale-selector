# B2-r3 作者超时后只读收尾

原flow `mpv-scale-p4-b2-r3-real-muz4jimj-d27b2f` repair阶段3600000ms硬超时，118回合，不能盲resume写者。已归档48产物到`build-b2-r3/partial-writer-timeout/`，只读进程检查无mpv/python/pythonw残留。

当前源码固定：
- tools/p4_collect.py SHA b6e4d65bdfea23f41106da44c0ee340ce6679dcf4d6aa5d973f0b91e67833b4c。
- tests/test_p4_collect.py SHA a8bb564c78d7cdce39ec13e9e090ed38212913b3548cc3d0987f158e0d1273c4。

原unit129通过；full log未跑完，不能叫全量PASS。config-smoke前两次失败、第三次真实sentinel成功均原字节保留。实现使用--config-dir独占临时配置目录而非include：固定文档`docs/证据/mpv-options.rst:786..796`明确会忽略系统/用户/MPV_HOME其它config根，cache/state独立还需既有child环境重定向。该选择应带文档/实际log路径证据交审，不能仅口头『已隔离』。作者称load-scripts=no会挡explicit-script需按实际负控日志评估，不因本简报就当已证。

只读收尾者不能edit源码或旧证据，只能在build-b2-r3/author新建本次logs/smoke报告/handoff。按原首载修正brief复核职责：
1. 实算固定两source SHA，读源码相关入口和原smoke报告。必要对同source重新run一个config-smoke，使用新的create-only目录、无GPU/无VS、固定mpv.exe vo=null sentinel，不能跑identity推理。将本次sourcepins与smoke结果共同绑定。保留原所有尝试，不覆写。
2. 实跑全tests+48guards及collector需要的局部验证，原始stdout/stderr新日志create-only，失败=REWORK不能改tests。确认原617行为仍存及新增数，记录真实发现。
3. 写原brief规定的author/handoff.json（尚不存在）：unitcollector/sourceexact2files/tests数组/config_smoke.report_path+sha/sourcepins/gpu_startedfalse/livewritefalse；resolution映射R3-1..5，报告实际当前状态而非作者愿望。当前实现若关键门未完成要准确REWORK，不许自填BUILT。
4. 最多15工具回合，仅收尾与测试，不新开宽泛代码审查。完成后独立machine全回归+新candidate的review仍须运行，handoff不代审。

未来realidentity仅一个24fps默认入口和identity-run-002，严格继承原brief，作者/收尾者均不得提前跑GPU。
