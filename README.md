# mpv 缩放算法选择器

**状态（2026-10-11）：P1–P3 插件已实现，客观隔离验证收口通过，但真人主观验收未做；P4 画质性能测量进行中、未收口；P5 部署未开始。全部验证仅在 `--config-dir` 隔离临时配置中运行，活动 mpv 配置零改动（live_configuration_written=false）。**

菜单共 **12 项**：关 + **9 个真实内建档位** + LS1/BCAS 两个**禁用占位**。9 个真实内建档位为：FSR1、SGSR1、Anime4K（本机 stock v4 链零改动副本）、Nearest Neighbor（P2 期）与 NIS、xBR、Sharp Bilinear AUTO、Sharp Bilinear 手动 2×、Integer（P3 期）。LS1（无公开源码/权重/移植许可）与 BCAS（算法定义身份未核实）恒为禁用占位并在菜单展示原因。P3 最终以 `docs/验证/开发/p3-001/revision-r2/交付收口检查.json` 的 `PASS_OBJECTIVE_CLOSEOUT` 收口（客观口径）。

## 安装

> 注意：正式部署属 P5，**尚未开始**（安装/卸载工具与用户许可流程均未建）。以下说明描述的是隔离验证过的部署形态，供了解与部署前自查；验证所用构建为 mpv `v0.40.0-393-gad59ff1b4` + libplacebo `v7.357.0`（gpu-next 后端）。

把三组文件复制到 mpv 配置目录（Windows 默认 `%APPDATA%\mpv`）的对应位置：

| 仓库内文件 | 复制到配置目录下 |
|---|---|
| `scripts/scale-selector.lua` | `scripts/` |
| `script-opts/scale-selector.conf`、`script-opts/scale-selector-gears.conf` | `script-opts/` |
| `shaders/` 整目录（含 `anime4k/` 子目录） | `shaders/` |

- 档位链以 `~~/shaders/…` 相对路径引用（内建链定义见 `scripts/scale-selector.lua` 中 `~~/shaders/p2-*.glsl`、`p3-*.glsl`、`anime4k/` 等条目）；**缺 `shaders/` 目录或对应文件时，相应档位失效**，菜单/状态行如实显示回退原因。
- 标量选项（菜单键等）在 `script-opts/scale-selector.conf`（默认 `key_menu=F8`）；档位表在 `script-opts/scale-selector-gears.conf`。
- 启动日志中固定 6 条「覆盖被忽略」告警为**预期行为**，说明见 [docs/插件/缩放选择器-P3用户说明.md](docs/插件/缩放选择器-P3用户说明.md)。

## 使用

- **F8** 打开菜单，↑/↓ 选择，Enter 确认，Esc/F8 关闭；选「关」恢复插件接管前记录的托管属性（off 不等于停止 mpv 必需的缩放与色彩管理）。
- 档位守卫语义（菜单/状态行如实显示真实生效状态，不冒充）：
  - LUMA 档（FSR1 / SGSR1 / Anime4K / NIS）：SDR RGB 与 HDR 输入自动禁用并显示原因；
  - MAIN RGB 档（xBR / Sharp Bilinear 两档）：RGB 可用，HDR 禁用（独立守卫）；
  - nearest / Integer：不受上述 LUMA/HDR 限制；
  - NIS 仅放大生效（`//!WHEN`），非放大时诚实跳过并注明；Sharp Bilinear AUTO 无放大时明示「退化为双线性」；Integer 的黑边与 k<1 回退均如实注明。
- 用户说明（按阶段）：
  - [P1 骨架用户说明](docs/插件/缩放选择器-P1用户说明.md)（状态机与菜单框架）
  - [P2 真实档位用户说明](docs/插件/缩放选择器-P2用户说明.md)（FSR1 / SGSR1 / Anime4K / Nearest）
  - [P3 新增档位用户说明](docs/插件/缩放选择器-P3用户说明.md)（NIS / xBR / Sharp Bilinear / Integer）
- 现状提醒：以上行为均只经**机器客观**验证；真人主观画质验收未做，本仓库不对画质做任何推荐。

## 文档入口

- [阶段索引](docs/阶段索引.md)：docs 下各阶段计划/brief/授权/快照/证据文档的角色与现行有效性索引。
- [评审与修改意见（2026-10-11）](docs/评审与修改意见-2026-10-11.md)：六领域评审结论与整改依据。
- [实施计划](docs/实施计划.md)：P0–P5 阶段定义与验收门槛（**P0 历史版本**，见文首标注）。
- [验证证据留存策略](docs/验证/证据留存策略.md)：证据日志不入库、仓库外归档的默认决策。
- [备份与恢复](docs/备份与恢复.md)：仓库外配置快照与 dry-run 恢复工具。

## 历史：可行性研究（P0）

以下为 P0 期（插件实现之前）的研究结论与阅读入口，仅作背景；其中「推荐下一步」等前瞻内容已被 P1–P3 的实际实施取代，不反映现状。

针对 `Snipaste_2026-10-02_20-23-55.jpg` 中的方法菜单，P0 结论为：

- **八项有明确 mpv 路线**：FSR1、NIS、SGSR1、Anime4K、xBR、Sharp Bilinear、Integer、Nearest Neighbor。
- FSR1/NIS/SGSR1 已有源码可读取的 mpv port；Anime4K 官方即支持 mpv，本机已有 stock 链。
- **LS1**：没有取得原网络源码、权重和移植授权，不能承诺原样内置。
- **BCAS**：准确算法定义未核实；CAS 或 Bicubic+CAS 只能作为独立命名的候选。
- “关”应恢复用户原配置，不代表停止 mpv 所有缩放。

P0 期阅读入口：

1. [可行性研究报告](docs/可行性研究报告.md)：十项结论、接入路线、工期估计、风险与验证计划。
2. [交叉审查结果](docs/交叉审查/审查结果.md)：技术事实与集成风险均 PASS，限定可行性研究。
3. [初稿勘误](docs/勘误说明.md)：算法归属、Gist 遗漏、性能推导及历史试验泛化的纠正。
4. `docs/证据/`：实际下载的官方说明/许可、mpv shader、固定构建文档、只读选项输出与 SHA-256 索引。
5. `docs/研究素材/`：早期六份归档初稿及补证汇总，不能直接作为终审证据。
6. [测试计划](docs/测试计划.md)：验证矩阵总纲（P1–P4 各阶段在其下细化执行）。

P0 期基线：Git `main`、研究基线标签 `research-baseline-20261002`；个人配置副本和 `.pi` 记录不纳入 Git。**取得源码不等于本机跑通，工程可行不等于画质必然提升，更不等于与 Lossless Scaling 逐像素一致。**
