# mpv缩放插件开发 Taskflow

已创建项目级可复用流程 **`mpv-scale-dev`**。本轮只保存、静态校验及测试门禁工具，**没有运行开发agent、开始P1、安装插件或写活动配置**。

## 定义与入口

- 可纳入Git的规范定义：[taskflows/mpv-scale-dev.json](../taskflows/mpv-scale-dev.json)。
- 注册副本：`.pi/taskflows/mpv-scale-dev.json`；`.pi`仍保持忽略，不把会话记录混入Git。
- 机器门禁：[taskflows/guard.py](../taskflows/guard.py)。
- 门禁单测：[taskflows/test_guard.py](../taskflows/test_guard.py)。
- 依据：[实施计划](实施计划.md)、[测试计划](测试计划.md)、[备份与恢复](备份与恢复.md)。

规范定义与注册副本需同步：修改JSON后先verify/plan，再通过taskflow的save动作以project scope重新保存。本版本phase.cwd固定当前项目；搬迁仓库/切到别的工作区时应更新cwd并重新校验、注册。

## 如何使用

在本项目内查看、预检与启动：

```text
/tf show mpv-scale-dev
/tf compile mpv-scale-dev
/tf:mpv-scale-dev stage=P1 session=p1-001
```

启动会先只读前检/规划，再弹出人工确认；**批准之后才实现本阶段**。默认stage=P1、session=p1-001、gpuApi=vulkan。不要同时在同一工作区启动两个开发流程。

每次只运行一个里程碑，不会在P1完成后自动跑完P2–P5。上一阶段已验收、候选源码仍匹配时再开始下一阶段，例如：

```text
/tf:mpv-scale-dev stage=P2 session=p2-001 previous=p1-001
/tf:mpv-scale-dev stage=P3 session=p3-001 previous=p2-001
/tf:mpv-scale-dev stage=P4 session=p4-001 previous=p3-001
/tf:mpv-scale-dev stage=P5 session=p5-001 previous=p4-001
```

- `session`必须从未使用；1–64位小写字母/数字/连字符，不允许路径。
- `previous`指上一阶段的已验收session，不是runId。P2–P5必填。
- `gpuApi`可选`vulkan`/`opengl`，固定`vo=gpu-next`。不支持时停下或明确重新选择，不能自动换后端伪装成功。
- 该模板采用严格P1→P2→P3→P4→P5线性依赖，比计划中P4可只依赖P2的最小路径更保守。
- **P5只产出部署就绪包，不执行真实安装。** 最终scope为deployment-readiness，live_deployment_completed始终false。真正部署/卸载/完整配置恢复需另一次明确授权、部署前新快照及INS-02/04实际验收。

## 13节点与责任划分

```text
备份/前序检查 → 只读阶段计划 → 人工批准 → 精确授权门
  → 唯一源码实施者 → 机器单测 → 集成验证/冻结候选 → 机器绑定检查
  → [技术审核 ∥ 安全审核] → 用户阶段验收 → 只创建验收记录 → 最终再检查
```

全部5个模型阶段请求 `zai-coding-cn/glm-5.3-flash`、`thinking=xhigh`（对应max意图）；不是供应商内部推理预算的实测证明。角色是planner、executor-code、test-engineer、reviewer、security-reviewer；审核者非作者，两个审核上下文独立但用同一模型。

- 只有实施者修改源码；验证者只写本session证据/临时数据；审核者只读。
- 本地检查交实施者，所有共享验证交单一集成负责人；审核并行时不重跑GPU基准。
- 缓存关闭；文件写入阶段标为非幂等，不自动重试源码变更；只读JSON模型阶段最多一次格式/暂态重试。
- 全流程maxTokens=600000，每个agent调用有有限墙钟上限；这是按已报告用量止损，不是零超额的硬保证。

## 关键安全/验收门

1. 前检验证仓库外55文件备份、固定manifest/ZIP指纹和当前源配置；不创建或覆盖备份。
2. 人工门后机器只接受精确`(approve)`。Reject、Edit、空输出或headless自动拒绝均不是授权；即使宿主approval异常继续，机器门仍拒绝进入写入。
3. 候选及测试证据必须UTF-8/LF；源文件、测试报告与快照逐SHA-256绑定；缺少计划必测ID、必需未测或报告live写入则拒绝。
4. 两路审查必须pass且绑定同一快照；任何blocker/major不能仅凭pass字符串放行。源码/证据变化使检查失效。
5. 用户完成交互/主观画质等pending_user_checks后才批准阶段；模型不能替用户评分。没有完成就拒绝/暂停。
6. 验收记录用create-only写入，不覆盖既有session；最终再核对源、报告及活动配置未变。
7. 这是协作规约加机器检查，**不是OS沙箱、加密签名或跨进程事务**；脚本不能防止同权限恶意程序、外部并发改文件或人为伪造审批字符串。

应**前台交互运行**，不要detach/headless。Edit只表示修改意见，不能当批准；调整后重新确认。遇到阻断/超时/部分写入，不无脑resume（非幂等写者可能重跑）；先检查工作区、保留旧候选与findings、准备限域修正brief，再用新session复核。后续阶段前检会拒绝已改变的前序候选。

如果日常mpv配置有意改变，旧快照的源比较失败是正常的安全阻断，不要覆盖旧备份或强行跳过。先做新快照、另存元数据，并在另一个经校验的flow版本中调整备份收据入口。

## 运行时证据协议

未来执行阶段才生成 `docs/验证/开发/<session>/`：

- `tests.json`：stage/session、客观PASS/FAIL、required_unmeasured、pending_user_checks、live_configuration_written=false、逐测试ID/状态/证据/复现命令；每ID一个条目，多输入用variants。
- `candidate.json`：schema=mpv-scaler-stage/v1、stage/session、所有相关源/共享模块/测试/shader/许可的相对路径SHA，以及tests.json的SHA。
- `acceptance.json`：精确用户批准、两路原始结论、同候选SHA、scope、未发生真实部署的事实。

JSON必须用UTF-8/LF（Python可用open(..., encoding='utf-8', newline='\n')）。这些产物当前未生成；不能用流程静态PASS、门禁测试或原32项备份测试冒充产品验收。

## 本轮已验证

- taskflow verify/plan/compile：13节点，0错误/警告。
- 新门禁16项临时项目单测通过；原32项备份工具回归通过。
- P1只读preflight smoke通过，备份55文件及源配置保持一致；没有启动任何开发agent或mpv播放。

复现门禁单测：

```powershell
python -B -X utf8 -m unittest discover -s taskflows -p test_guard.py -v
python -B -X utf8 -m unittest discover -s tests -v
```
