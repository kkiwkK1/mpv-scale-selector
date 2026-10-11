# P3 独立集成/冻结负责人报告（verify-lead, session p3-001）

- 角色：独立集成验证与冻结负责人（源码只读；源码作者已退出，未参与本轮任何执行）
- 阶段/会话：P3 / p3-001；报告时间：2026-10-06T09:40+0800（本地系统时间）
- 结论（一句话）：**34/35 必测真实 PASS，GEO-03 真实 FAIL（渲染新鲜度证据缺失，harness 诚实拒绝兜底）；候选不得冻结为 PASS，按流程阻断下游、返作者 REWORK。未修任何源码，未放宽任何标准。**

## 1. 授权与输入链（执行前核验）

- 计划：`docs/P3实施计划-v1.critic-block.json`（ready=pass，35 必测唯一，write_paths 30 条）。
- 计划对抗审查：`docs/P3/验证/开发/p3-001/plan-adversarial-review.json` verdict=pass（5 项 findings 保留）；work-permit 绑定 plan/baseline/authorization sha。
- brief 链：`P3执行约束与验收brief.md` → `P3实施中断接续brief-v1.json` → `P3核心限域修正brief-v2.json` → `P3验证器限域收敛brief-v3.json` → `P3全矩阵首轮限域修正brief-v4.json`（本轮权威）。
- 作者交接：`implementer/author-delivery-r2.json`（full-r2, PASS, **作者本地 PASS 不构成集成通过**）+ `verifier-build/build-handoff-r4.json`（READY_FOR_AUTHOR）+ `evidence-tools-contract.json`。
- 源码预检（只读）：author-delivery-r2 `actual_source_sha256` 17 项逐一实算**全部匹配**当前磁盘；pre-full-r2-source 快照 28 项对比显示**且仅** 4 处差异 = brief-v4 授权限域修正（scale-selector.lua / p2_verify.py / p3_verify.py / test_p2_support.py），与其 local_delta 声明一致，无越权改动。
- P2 保全复核：`p3_guard.preserved()` PASS（2128 保留文件 + 35 个 P2 源码归档逐 sha）；P2 候选钉 `78770240f8cf15cb…`（p2-001/candidate.json 实算 == 启动基线 pin；technical-status PASS_OBJECTIVE）。旧 P2 guard 对 live 仓库的 P2 候选校验在 P3 授权写入后**设计上**不再适用（P3 启动基线已把 P2 源保全改绑快照归档），非回归。

## 2. 候选快照与漂移门（tests 从候选源码开跑前记录 hash，结束逐项比对）

- 开跑前快照：`verify-lead/pre-run-source-hashes.json`（36 文件 = 计划全部 write_path 文件 + 执行环境依赖：taskflows guard/guard 测试/p3_core_handoff_check、mpv_config_backup、check_preparation、test_mpv_config_backup）。
- 结束后逐项比对：`verify-lead/post-run-source-hashes.json` → **NO-DRIFT（36/36 一致）**。本轮全部测试在同一候选字节上执行。

## 3. 单元测试与 guard 安全 mock（全部真实重跑）

| 套件 | 命令 | 结果 | 原始输出 sha256 |
|---|---|---|---|
| 全部单测 | `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` | **270 tests OK, skipped=1**（唯一 skip=Windows symlink 权限既有披露项，非行为跳过） | `4136ae8ede399721d06f0250be95990b7a77e2577abc43f0b68e3b0bb21e1385` |
| 两个 guard 套件 | `python -X utf8 -m unittest discover -s taskflows -p "test_*.py" -v` | **27 tests OK**（原 16 + P3 新 11） | `c8eaab3bf45595dea32012570bf967393673d3a3409a2bb72f0a580b41cc8468` |

- 原 121（含历史迁移后基线）→ 现 270 全绿，无删除/无跳过/无断言放宽。

## 4. 全 35 必测矩阵（真实 gpu-next + vulkan 重跑，GPU 串行，全新证据目录）

- 命令：`python -X utf8 tools/p3_verify.py --all --session p3-001 --evidence-dir docs/验证/开发/p3-001/verify-lead/integration-r1`
- 隔离：直启 D:/MPV/mpv.exe（v0.40.0-393-gad59ff1b4，--vo=gpu-next --gpu-api=vulkan），合成媒体，独立 temp config/HOME/USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/cache/watch-later/截图目录，子进程 env 无凭据，只停自启 PID，无并行 GPU（运行前后 nvidia-smi 桌面基线 1%/954MiB）。
- 产物：96 个会话 triplet（console+mpv.log+transcript）+ 56 inputs.json + 50 PNG + objective-results/source-pins/EVI sandbox 报告 + 自身 manifest 链（closed exclusion class 4 项，无循环自指）。runner stdout 副本 sha `59bfc132…`。
- 结果：**34 PASS / 1 FAIL（GEO-03）**；required_unmeasured=[]。objective-results.json sha `575e8e355222d8bf…`；source-pins.json sha `0e2b41f75e10b7f2…`（与作者报告同源同值）；integration-r1 evidence-manifest sha `bd2ba6e6cd9cd1a7…`；manifest-verify sha `dd6e5359761b712f…`。

### 4.1 重点项真实性抽查（均出自本轮新帧/新采集，非旧证据复用）

- **SHD-05 NIS**：静态审计 compute 指令/两张 2×64 rgba32f 系数纹理/原 //!WHEN 保留/全部 barrier 后 bounds guard/无 barrier 前 return/imageStore 已 guard/无 NVSharpen 叠加/LUMA hook 全 true；实跑链 `~~/shaders/p3-NIS.glsl`，DESC 计数 5 且样本行逐字出自本次会话日志；freshness=vo-passes-fresh-increase 270→295（epoch 9 配对）；等尺寸/缩小变体 skip_note_honest+chain_fallback_intact+渲染继续（诚实跳过，非凑激活）。
- **SHD-06 xBR**：3× 精确窗口 CPU replica 像素 oracle——平坦区 4229 点 mean_diff=0.08；45° 边沿判别 228 点 mean_diff_to_xbr_replica=0.15 vs 双线性基线 4.51（ok）；MAIN RGB、非 xBRZ 冒称。
- **SHD-07 Sharp**：5 变体 = AUTO floor=1 退化双线性 / AUTO 真实 2× / 手动 2× / scale0 防护 / 运动存在性；AUTO 与手动分名分截图。
- **SHD-09 位深**：12 变体（nis/xbr/sharpbilinear/sharpbilinear2x/integer/fsr1 × 8/10bit）全部 depth_matches_decode=true；10bit 真实 yuv420p10 解码身份，与 8bit 媒体 sha 集合不相交。
- **GEO-02 Integer**：1080→1440p k=1 黑边实测 left/right=320、top/bottom=180（==期望，OSD-free 回退扫描诚实标注）；720p k=2 满屏；k<1 正常缩小不裁切；同进程 loadfile 1080→720 重算配 freshness（187→194, epoch 11）。
- **GEO-04/05/06**：resize 重算 + freshness 实测配对当前 epoch；外部 zoom/zoom+shader 冲突 yield 且外值保留；rotate/crop/SAR 相位全部 active+native bool 读回；A2:1 SAR 保显示比例。
- **CTL-06**：8 变体全 PASS，菜单条目计数==发布 conf 派生 12 档（V4-FALLBACK 闭合在本轮独立复现）；禁用防 conf 冒名、Off 恒关、auth fail-closed 保持。
- **EVI-01**：10 个规范负例类全部真实植入并被 checker 检出（true×10）+ positive_control_clean=true；沙箱在证据目录之外（`EVI-01.sandbox-report.json` sha `082a4a22…`）。
- **PER-04-COMPUTE**：195 个正整数原始 fresh/redraw ns 样本 + samples_note；无任何性能收益宣称；RIFE 明示未测留 P4。
- **WINDOW-01 / SHD-13 fallback / legacy P2 档（SHD-01..04/08/12/13）**：全部真实重跑 PASS；legacy 基线 Off 恢复、重启链 console 全收。
- 反例教训未复发：无 0==0 计数、无 'user shader' 子串计数、无 decoder 活性兜底 active、无陈旧 epoch 配对、无 expected-geometry 构造空真（oracle 独立验证实际 captured rect/原图边沿/像素块）。

## 5. GEO-03 真实 FAIL（原样留给作者，未修）

- 事实：像素语义全部达标——严格 2× nearest 块均匀度 230400/230400（fraction=1.0, max_intra_block_spread=0），对照基线 0.615 非均匀，integer vs control 截图像素不同，native video-unscaled bool true，k=2，全屏 gate ok。
- FAIL 原因：freshness 记录 `render_fresh=false, method=null, fresh_before=null, fresh_after=null`——采样窗内呈现/链计数完全冻结（暂停 blip 或进程停摆），按契约**解码活性不得兜底 active 断言，必须 FAIL**。harness 的诚实性机制正确工作，拒绝产出空真 PASS。
- 定性：疑似 GEO-03 驱动时序问题（pause-blip 结束态落在 paused、或新鲜度探针窗口未覆盖恢复后的新帧），属实现层缺陷判断，**由作者返工**；verify-lead 无源码写权限，不边修边验。
- 复现命令：`python -X utf8 tools/p3_verify.py --case GEO-03 --session p3-001 --evidence-dir <全新目录>`
- 证据：`integration-r1/GEO-03-a-integer-nearest-2x.*` triplet + `GEO-03.a-p0..p3.png` + 对照基线 4 张 + `integration-r1/objective-results.json` cases[GEO-03]。session：GEO-03-a-integer-nearest-2x；chain_epoch=8；same_moment pixelformat=yuv420p 1280x720（同刻采样正常在案）。

## 6. 机器门禁（只读 checker）

1. 结构门：`p3_check_evidence.py --evidence-dir integration-r1 --session p3-001` → **exit 0, PASS, problems=0**（清单链/会话 triplet/desc 同刻/freshness 形状/native bool/SHD-09 位深/EVI 负例全覆盖结构合规）——sha `f7c4f2aa08f79a87…`。
2. --require-tests --write-gate：**exit 1，唯一 problem「必需测试非 PASS: GEO-03 ('FAIL')」**，FAIL gate create-only 落盘（sha `19177259c8603a56…`）——真实失败原样保留，未洗白。
3. 冻结后全链门（在本报告与 tests/candidate 写盘后执行，日志落 `final-gate-p1-chain.txt` / `final-gate-p3-guard-check.txt`）：
   - `p1_check_evidence.py --stage P3 --session p3-001` 全 P3 manifest 链 + tests + candidate --require-tests；
   - `p3_guard.py check`（预期 FAIL：GEO-03 非 PASS → 冻结门诚实阻断，下游两审不启动）。

## 7. Findings

| ID | 级别 | 内容 | 处置 |
|---|---|---|---|
| VL3-01 | major（返作者） | GEO-03 渲染新鲜度证据缺失（见 §5）。像素语义已达标，唯 active 断言的新帧证据不可得。 | 真实 FAIL 留场；作者修复后须全新目录全 35 重跑 |
| VL3-02 | 信息 | `core-checks` 12 项 smoke 钉的是 pre-full-r2 源（scale-selector.lua=53d985aa…）；现候选 Lua=85f13b49… 为 brief-v4 授权修正（build-handoff-r4）。旧 core 证据原字节保留未改写；其结论仅适用旧源，不作为当前候选的矩阵证明（接续 brief 已预授权此差异）。 | 记录；不重放 core 写者 |
| VL3-03 | 信息 | `p3_core_handoff_check.py` 对当前源因上述授权差异 FAIL（预期内）；该脚本作为执行环境依赖已纳入 candidate 指纹。 | 记录 |
| VL3-04 | 信息 | build-handoff.json（旧）generated_at=2025-12-27 外部时间勘误：原字节保留，新记录 build-handoff-r4 用实际系统时间；两日期均不作候选证据。 | 已由 brief-v4 nonblocking_correction_note 记录，本轮不重述 |

无漏项需联合补绑：本轮全部 restart console / 截图 / inputs / log / transcript 均已由 integration-r1 自身清单全目录覆盖（EVI-01 目录覆盖校验 PASS），verify-lead 级清单（见下）绑定全部 verify-lead 产物。

## 8. 边界与诚实声明

- live_configuration_written=false；未写活动 APPDATA/mpv、D:/MPV、备份 payload；无全局 kill / DPI 修改 / install / restore / deploy / git commit；无 API 凭据入子进程 env。
- human_subjective_acceptance_claimed=false；真人项 pending：GEO-04-MANUAL DPI/跨屏实操、P3 菜单/像素风偏好、P1-UC-1..4 / P2-UC-1/2 沿用 pending。
- 无 P4 收益宣称（性能/RIFE 未触碰）；HDR 证据=合成源 metadata override，非真实 HDR 片，不作 HDR 画质结论。
- 本报告不构成验收；候选冻结被 GEO-03 阻断，同候选技术+对抗两审待返工后新候选再启动。

## 9. 下游

1. 本报告 + tests.json + candidate.json + verify-lead 清单冻结为 **FAIL 场景完整证据包**（create-only，UTF-8/LF）。
2. 返作者：修复 VL3-01 → 全新目录全 35 重跑 + 机器门禁 → 再独立集成 → 双审 → 客观状态。
3. 本轮所有旧证据（core/full-r1/full-r2/rework-v4/partial…）原字节零改动。
