# scale-selector — mpv 缩放算法选择器

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/kkiwkK1/mpv-scale-selector/blob/main/LICENSE)
[![Release](https://img.shields.io/badge/Release-v0.1.0-blue)](https://github.com/kkiwkK1/mpv-scale-selector/releases)
[![mpv](https://img.shields.io/badge/mpv-tested%20v0.40.0--393-green)](https://mpv.io)
[![Lua](https://img.shields.io/badge/Lua-LuaJIT%20%7C%205.2%2B-orange)](https://www.lua.org)

**F8 打开菜单，一键切换缩放档位**：关 + 9 个真实内建档位（FSR1 / NIS / SGSR1 / Anime4K / xBR / Sharp Bilinear AUTO / Sharp Bilinear 2× / Integer / Nearest），外加 LS1、BCAS 两个**诚实禁用占位**（LS1 是 Lossless Scaling 的神经网络放大模型、BCAS 身份未核实——详见「诚实显示」一节）。托管属性快照恢复、外部改动让出、着色链逐一验证——菜单如实反映真实生效状态（「诚实显示」是设计底线，由内置自测与评审持续加固，曾修复的显示缺陷见[发布说明](docs/发布说明-v0.1.0.md)）。

> 开发与验证环境：mpv `v0.40.0-393-gad59ff1b4` + libplacebo `v7.357.0`（gpu-next），Windows；更低版本未实测。机器客观验证已完成，**真人主观画质验收未做，本仓库不对画质做任何推荐**。

## 系统要求

- **操作系统**：Windows——一键安装器与全部实测验证均在 Windows 完成；其它平台未验证，仅可参考「手工三步」自行复制文件
- **mpv 版本**：全部验证在 mpv `v0.40.0-393-gad59ff1b4` + libplacebo `v7.357.0` 上完成；**不声明更低版本的兼容下限**（更低版本未实测）
- **渲染后端**：验证固定在 `vo=gpu-next` + `gpu-api=vulkan`；其它 VO（含传统 `vo=gpu`）未实测。建议在 `mpv.conf` 写 `vo=gpu-next`
- **GPU**：各档 shader 在启动时编译；NIS 档为 compute shader 实现，需要支持 compute 的 GPU/驱动。编译失败时插件自动回滚并显示真实原因（见 FAQ）
- **Lua**：mpv 需以 LuaJIT 或 Lua ≥5.2 构建（官方 Windows 构建为 LuaJIT；PUC Lua 5.1 构建存在 Integer 档 zoom 计算偏差，见[发布说明](docs/发布说明-v0.1.0.md)）
- **运行测试**：Python 3，仅用标准库（开发环境实测 3.9.1）

## 特性一览

- **12 档菜单**：9 个真实档位的链定义全部内建于脚本，本地配置无法冒名、改链或借标签挂任意链；2 个占位档位永久禁用并展示原因
- **诚实守卫**：LUMA 档在 RGB/HDR 输入自动禁用并显示真实原因；仅放大档（`//!WHEN`）非放大时如实显示「跳过」；激活后按 `vo-passes` 核对本链 pass 确实存在，编译失败/未生效自动回滚到上一稳定状态，无半生效残留
- **状态机与所有权**：off / active / external / fallback；接管前快照托管属性，「关」逐字恢复；外部修改（如你自己在 `input.conf` 里绑定的手动 Anime4K 链）优先，插件让出，不静默覆盖、不清链
- **菜单体验**：↑↓ / 滚轮导航（跳过禁用项、首尾循环）、**✓当前**标记、打开停在当前档、小键盘 Enter 确认、选档后菜单保持打开；插件消息写进菜单状态头，不再弹 OSD 与菜单重叠
- **可编程切换**：`script-message scale-selector-set <id|off>` 与 `scale-selector-cycle next|prev`，与菜单同一入口、同一守卫规则（供 input.conf / uosc / IPC 自动化）
- **一键安装器**：21 项文件清单、逐文件 sha256、三态安装（缺失复制 / 一致跳过 / 冲突先备份再覆盖）、`-Verify` 只读校验、`-Uninstall` 哈希核删、幂等重跑即升级
- **RIFE 插帧共存实测：矩阵 7/7 通过**（另含环境清理核查）：与 vapoursynth RIFE 2× 插帧同进程互不干扰（见下文）

## 档位表（12 档 × 算法 × 来源 × 许可）

| # | 菜单项 | id | 算法与实现 | 来源（上游） | 许可 |
|---|---|---|---|---|---|
| 1 | 关 | `off` | 恢复接管前托管的 `glsl-shaders` / `scale` / `cscale` / `dscale`（及 Integer 的几何属性）；**不等于**停止 mpv 必需的缩放与色彩管理 | — | — |
| 2 | LS1 | `ls1` | **禁用占位**：无公开源码/权重/移植许可，不以替代算法冒名 | — | — |
| 3 | FSR1 | `fsr1` | AMD FidelityFX Super Resolution v1.0.2（EASU+RCAS），LUMA 档，仅放大（每轴 ≤2×，超出由 mpv scaler 接管） | [GPUOpen-Effects/FidelityFX-FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR)；mpv 移植 by [agyild（gist）](https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5) | MIT |
| 4 | NIS | `nis` | NVIDIA Image Scaling v1.0.2（compute，内含锐化段，绝不叠 NVSharpen），LUMA 档，仅放大 | [NVIDIAGameWorks/NVIDIAImageScaling](https://github.com/NVIDIAGameWorks/NVIDIAImageScaling)；mpv 移植 by [agyild（gist）](https://gist.github.com/agyild/7e8951915b2bf24526a9343d951db214) | MIT |
| 5 | SGSR1 | `sgsr1` | Qualcomm SGSR1（LUMA 适配版，单 pass），仅放大 | [SnapdragonGameStudios/snapdragon-gsr](https://github.com/SnapdragonGameStudios/snapdragon-gsr)；mpv 移植 by [agyild（gist）](https://gist.github.com/agyild/7715b6b1f38427839d58f80884902cab) | BSD-3-Clause |
| 6 | BCAS | `bcas` | **禁用占位**：算法定义身份未核实；不以 CAS / Bicubic+CAS 冒名 | — | — |
| 7 | Anime4K（stock v4） | `anime4k` | 本机 stock v4 CTRL+1..6 精确链的零改动副本；`anime4k_chain=a..f` 选择（默认 a = Mode A (HQ)） | [bloc97/Anime4K](https://github.com/bloc97/Anime4K) | MIT ×8 + Unlicense ×2（以各文件内嵌许可头为准） |
| 8 | xBR | `xbr` | Hyllian xBR-lv2，**3× 预缩放 + mpv 后续缩放**模式（xBR ≠ xBRZ，不冒称任意比例等价），MAIN 档 | [libretro/glsl-shaders（xbr-lv2）](https://github.com/libretro/glsl-shaders/blob/master/xbr/shaders/xbr-lv2.glsl) | MIT |
| 9 | Sharp Bilinear AUTO | `sharpbilinear` | 自动预缩放 `floor(输出高/输入高+0.01)`；倍率不足时明示「退化为双线性」，不改公式凑锐利 | [libretro/glsl-shaders（sharp-bilinear）](https://github.com/libretro/glsl-shaders/blob/master/interpolation/shaders/sharp-bilinear.glsl)，Themaister | Public domain |
| 10 | Sharp Bilinear 2× | `sharpbilinear2x` | 固定 2× 预缩放（与 AUTO 分别命名、分别成文件） | 同上 | Public domain |
| 11 | Integer | `integer` | 整数倍缩放：`k=floor(原窗口像素/有效显示尺寸)`，`video-unscaled=yes` + `video-zoom` + 三核 nearest；k<1 诚实回退为普通 nearest 缩小，不裁切 | mpv 原生属性（无第三方 shader） | — |
| 12 | Nearest | `nearest` | `scale/cscale/dscale` 全 nearest（显式点采样，无 shader 链） | mpv 内建 | — |

菜单顺序与 `script-opts/scale-selector-gears.conf` 的 `gears=` 一致。

**Anime4K 链模式**：`script-opts/scale-selector.conf` 的 `anime4k_chain=a..f` 选择链（默认 a）；各链的文件组成见 `scripts/scale-selector.lua` 的 `ANIME4K_CHAINS` 表，模式名沿用 Anime4K stock v4 的命名：

| 值 | 作者配置中等效的手动键 | 模式 |
|---|---|---|
| a | CTRL+1 | Mode A (HQ) |
| b | CTRL+2 | Mode B (HQ) |
| c | CTRL+3 | Mode C (HQ) |
| d | CTRL+4 | Mode A+A (HQ) |
| e | CTRL+5 | Mode B+B (HQ) |
| f | CTRL+6 | Mode C+A (HQ) |

（手动键来自作者 `input.conf` 里按 Anime4K 官方模板配置的绑定，**不是本插件提供的键位**；插件档位与这些手动链共享同一组 `shaders\anime4k\` 文件。）从链文件组成可读出差别：a/b 用 Restore_CNN 变体恢复，c/f 用 Denoise 变体降噪后放大，d/e 在 a/b 基础上叠加第二段 Restore。

**`gears=` 能改什么**：这一行调整**菜单顺序**，也可定义自定义档位（`<id>_label/_mode/_reason/_set`，缺省禁用）。解析器硬保证：`off` 恒存在、恒在首项、恒可用（显示名固定「关」）；LS1/BCAS 无论怎么写都强制 disabled；内建档位的 `_label/_mode/_set/_reason` 一律无效并产生告警；重复 id 只保留首个并告警；写新 id 会按自定义档位处理（未配 `_mode=active` 时为灰显）。细节见 `scale-selector-gears.conf` 头部注释。

### 输入适用性（守卫语义）

- **LUMA 档（FSR1 / SGSR1 / NIS）**：输入为 RGB 系像素格式或 HDR（gamma ∈ {pq, hlg}）时自动禁用并显示原因；仅放大生效（`//!WHEN`），非放大时如实显示「跳过」而非伪 active
- **MAIN 档（Anime4K / xBR / Sharp Bilinear 两档）**：RGB 输入可用；HDR 输入自动禁用（独立守卫；Anime4K 归此类是因为其全部 hook 位于 MAIN/PREKERNEL 层）
- **nearest / Integer**：不受 RGB/HDR 限制；Integer 的黑边与 k<1 回退均如实注明

## 菜单操作

- **F8** 打开/关闭；**↑ / ↓ 或滚轮**移动光标（跳过灰显禁用项，首尾循环）；**Enter / 小键盘 Enter** 激活当前档（选档后菜单保持打开，可继续切换）；**Esc** 关闭
- 菜单标出 **✓当前**，打开时光标停在当前生效档；菜单打开期间 7 个键（UP / DOWN / WHEEL_UP / WHEEL_DOWN / ENTER / KP_ENTER / ESC）被强制接管，关闭后原绑定原样恢复
- 菜单打开期间的插件消息写在菜单状态头内，不另弹 OSD

不经菜单直接切档（可写进 `input.conf`，也可供 uosc / IPC 调用；与菜单 Enter 同一入口，禁用档会被拒绝并提示原因）：

```
Alt+1  script-message scale-selector-set fsr1      # 档位 id：off fsr1 sgsr1 anime4k nearest nis xbr sharpbilinear sharpbilinear2x integer
Alt+0  script-message scale-selector-set off
Alt+n  script-message scale-selector-cycle next    # 或 prev；跳过禁用档，首尾循环
```

**换菜单键**：`script-opts/scale-selector.conf` 中 `key_menu=` 改为其它键；**留空**则不绑默认键，在 `input.conf` 写 `<键> script-binding scale_selector/scale-selector-menu`。关于 F8 冲突：mpv 出厂默认键位**没有**启用 F8（官方键位模板 `etc/input.conf` 中的 `#F8 show-text ${playlist}` 是注释掉的示例——实测构建 ad59ff1b4 核对）；若你自己的 `input.conf` 或其它脚本绑定了 F8，安装器会在安装时检查 `input.conf` 并给出冲突警告。

## 安装

**第零步：获取文件**——

```
git clone https://github.com/kkiwkK1/mpv-scale-selector.git
```

没有 git 也可以：到 [Releases](https://github.com/kkiwkK1/mpv-scale-selector/releases) 下载 v0.1.0 的 *Source code (zip)* 并解压。两种方式得到的目录内容相同，均直接用于下面的安装步骤。

目标目录为 mpv 配置目录（Windows 默认 `%APPDATA%\mpv`；portable 版 mpv 见 FAQ 的 `-ConfigDir` 用法）。

### 方式一：一键安装器（推荐）

在仓库根目录（双击 `tools\install.bat` 亦可）：

```
powershell -ExecutionPolicy Bypass -File tools\install.ps1
```

- 默认安装到 `%APPDATA%\mpv`；`-ConfigDir <目录>` 指定其他目录（测试一律指向隔离目录）
- `-Yes` 跳过交互确认（自动化调用请一律带上）
- 安装器仅在 **Windows PowerShell 5.1** 下开发与实测（两轮隔离自测）；PowerShell 7（pwsh）未测
- **升级 = 重跑同一条命令**：哈希与源不一致的清单文件自动备分为 `<名>.bak-scale-install-<时间戳>` 后替换，一致则跳过（幂等，零改动）；无需先卸载
- **`-Verify`**：只读校验 21 项清单（绝不写盘、绝不确认）；**`-Uninstall`**：先逐个哈希核对，只删除与源一致的清单文件
- 安装器绝不触碰 `input.conf`、`mpv.conf`、既有脚本与既有 shader 等清单外文件；冲突才备份，从不静默覆盖

**退出码**：

| 码 | 含义 |
|---|---|
| 0 | 成功 / 校验健康（含幂等零改动、卸载完成、Verify 21/21 一致） |
| 1 | 参数 / 环境 / IO 错误（未知参数、互斥、拒绝确认、APPDATA 缺失、拷贝/备份/核对失败） |
| 2 | 预检阻断（源文件缺失、与 resource-manifest 在案 sha256 不符＝源损坏、manifest 解析失败） |
| 3 | 仅 `-Verify`：21 项一个都不存在（未安装） |
| 4 | 仅 `-Verify`：部分存在或哈希不符（不一致） |

### 方式二：手工三步

把三组文件复制到配置目录的对应位置（保持相对结构）：

| 仓库内文件 | 复制到配置目录下 |
|---|---|
| `scripts/scale-selector.lua` | `scripts\` |
| `script-opts/scale-selector.conf`、`script-opts/scale-selector-gears.conf` | `script-opts\` |
| `shaders\` 整目录（含 `anime4k\` 子目录，共 18 个文件） | `shaders\` |

档位链以 `~~/shaders/…` 相对路径引用（`~~/` 是 mpv 对「配置目录」的路径缩写）：**缺 `shaders\` 目录或对应文件时，相应档位失效**，菜单/状态行会如实显示回退原因。

### 安装后

- 启动日志固定出现 6 条「覆盖被忽略」告警——防冒名解析器的预期行为，不是配置错误，无需处理
- 想体验 LUMA 档（FSR1/SGSR1/NIS）请用 YUV 素材——yuv420p/422/444 等平面格式均可（实测 yuv420p 与经 RIFE 的 yuv444p；守卫只拒 RGB 系与 HDR）；RGB 源上这三档灰显是设计行为（见下）

## 「诚实显示」设计说明

**为什么 LS1 / BCAS 是灰的**：这两个档位**永远不会可选**。

- **LS1**：Lossless Scaling（Steam 商业软件）的 LS1 通用神经网络放大模型（官方称优化范围约 1×–2×）；未取得其源码、权重与移植/再分发许可，无法原样内置，插件拒绝用别的算法顶名（依据：[可行性研究报告 §4.4](docs/可行性研究报告.md)）。
- **BCAS**：名字来自被复刻软件的菜单，全称与算法定义未核实——仅凭字母不能认定它是 Bicubic/Bilinear/Bilateral CAS，拒绝用近邻算法冒名占位（依据：[可行性研究报告 §4.5](docs/可行性研究报告.md)）。
- 这不是「待实现」，而是解析器层硬保证：无论本地配置怎么写，这两个 id 都强制 disabled 且使用内建固定原因文案。CAS 相关研究素材未随插件分发，见 [licenses/CAS-SOURCE-NOTES.md](licenses/CAS-SOURCE-NOTES.md)。

**RGB 源上 LUMA 档灰显**：设计行为，不是故障。LUMA 档（FSR1/SGSR1/NIS）工作在 YUV 亮度通道，RGB 或 HDR 输入时守卫拒用并在菜单显示真实原因；换 YUV 素材即可激活（420/422/444 平面格式均可）。Anime4K / xBR / Sharp Bilinear 支持 RGB（HDR 仍拒用）。

**其他诚实语义**：FSR1/SGSR1/NIS 仅放大生效，非放大时明示「跳过」；Sharp Bilinear AUTO 在倍率不足时明示「退化为双线性」；Integer 的黑边与 k<1 回退均如实注明；选「关」恢复的是插件接管前记录的托管属性，不代表停止 mpv 必需的缩放与色彩管理。

## 与 RIFE 插帧共存（矩阵实测 7/7）

在 mpv.conf 级 `vf vapoursynth` RIFE 2× 插帧常驻的真实环境实测（[完整报告](docs/插件/rife兼容性报告-2026-10-11.md)）：7 个矩阵用例全部 pass，另通过环境清理核查——

- RIFE 开启时各档位（FSR1/xBR/Nearest 等）正常激活，着色链真实挂载，期间 `estimated-vf-fps` 恒为 2× 源帧率
- 档位激活状态下 F7 开/关 RIFE，插件的托管属性逐字保留；F8 菜单与 F7 互不抢键；「关」恢复基线
- 一处实测修正：LUMA 守卫只看**输出侧**像素格式——RGB 源经 RIFE 后输出 yuv444p，此时 LUMA 档可选可用；设计性禁用仅在 RGB 直通（RIFE 关闭）时触发

## 质量保障

- **测试**：`tests/` 646 个用例 + `taskflows/` 51 个用例（2026-10-12 `def test_` 静态计数）。运行（约 3 分钟）：

  ```
  python -B -X utf8 -m unittest discover -s tests -p "test_*.py"
  python -B -X utf8 -m unittest discover -s taskflows -p "test_*.py"
  ```

  干净检出（无本机证据树）实测 `Ran 646 / OK (skipped=36)`——36 个 P4 用例依赖刻意不入库的本机证据树（[证据留存策略](docs/验证/证据留存策略.md)），证据缺失时自动跳过并注明原因。当前开发分支本机另有 24 个**按设计失败**（fail-closed＝宁失败不放行）的用例：源码整改后，开发期记录的资源完整性基线尚未按内部流程重新盖章（内部称「重封」），相关测试等该流程收尾；不影响插件功能，详见[评审与改进建议（2026-10-12）](docs/评审与改进建议-2026-10-12.md)。

  **Lua 内置自测（124 例）复现**：自测经 `script-message scale-selector-selftest` 触发，逐例输出到日志（`selftest: PASS/FAIL <用例名>`），结尾汇总 `selftest finished: pass/fail cases: N failures: M`（`scripts/scale-selector.lua:2700`）。隔离复现（不碰日常配置）：

  ```bat
  powershell -ExecutionPolicy Bypass -File tools\install.ps1 -ConfigDir "%TEMP%\scale-selftest" -Yes
  mpv --config-dir="%TEMP%\scale-selftest" --idle=yes --force-window=no --input-ipc-server=scale-selftest --log-file="%TEMP%\scale-selftest.log"
  ```

  另开一个终端，把下面 4 行存为 `selftest_pipe.py` 并运行 `python selftest_pipe.py`：

  ```python
  import json
  f = open(r'\\.\pipe\scale-selftest', 'r+b', buffering=0)
  f.write((json.dumps({'command': ['script-message', 'scale-selector-selftest']}) + '\n').encode())
  print(f.readline().decode())
  ```

  结果看 `%TEMP%\scale-selftest.log` 中的 selftest 行。
- **开发期验证工具链**（`tools/`；P1–P4 是项目四个开发阶段的内部编号，对应关系见[阶段索引](docs/阶段索引.md)）：第三方资源 sha256 审计与清单（`shaders/resource-manifest.json`、`shaders/p3-resource-manifest.json`）、Lua 行为镜像校验、Integer 几何 oracle、性能采集与分析、mpv 配置备份恢复。
- **验收证据**：
  - 一键安装器：两轮隔离自测，覆盖全新安装 / 幂等重跑 / 冲突备份 / `-Verify` / 卸载往返与互斥、未知参数、源损坏等异常路径，退出码回传实测，见[安装流程（一键安装）](docs/插件/安装流程-日常mpv.md)
  - 日常 mpv 实装：21/21 哈希三重核验、既有 54 个文件零改动、GUI 实测通过（F8 菜单、FSR1 激活与链验证、恢复基线、全日志无 traceback），见[安装报告](docs/插件/安装报告-2026-10-12.md)
  - RIFE 共存矩阵 7/7：见上文
- **边界**：以上均为机器客观验证；真人主观画质验收未做，P4 画质/性能测量进行中未收口——**本仓库不对画质做任何推荐**。

## 第三方引用

本插件内嵌/适配的第三方着色器，上游、许可与本仓库归属笔记（适配版仅追加溯源注释并另立 SHA-256，主算法/指令行零改动；基文件来源 URL、抓取时间与哈希登记于 [docs/证据/移植取证索引.json](docs/证据/移植取证索引.json)）：

| 组件 | 本仓库资源 | 上游 | 许可 | 归属笔记 |
|---|---|---|---|---|
| AMD FSR 1.0.2 | `shaders/p2-FSR1.glsl`（适配版） | [GPUOpen-Effects/FidelityFX-FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR)；mpv 移植 [agyild gist](https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5) | MIT | [licenses/FSR1-LICENSE-NOTES.md](licenses/FSR1-LICENSE-NOTES.md) |
| NVIDIA Image Scaling 1.0.2 | `shaders/p3-NIS.glsl`（适配版） | [NVIDIAGameWorks/NVIDIAImageScaling](https://github.com/NVIDIAGameWorks/NVIDIAImageScaling)；mpv 移植 [agyild gist](https://gist.github.com/agyild/7e8951915b2bf24526a9343d951db214) | MIT | [licenses/NIS-LICENSE-NOTES.md](licenses/NIS-LICENSE-NOTES.md) |
| Qualcomm SGSR1 | `shaders/p2-SGSR1.glsl`（LUMA 适配版） | [SnapdragonGameStudios/snapdragon-gsr](https://github.com/SnapdragonGameStudios/snapdragon-gsr)；mpv 移植 [agyild gist](https://gist.github.com/agyild/7715b6b1f38427839d58f80884902cab) | BSD-3-Clause | [licenses/SGSR1-LICENSE-NOTES.md](licenses/SGSR1-LICENSE-NOTES.md) |
| Anime4K v4 | `shaders/anime4k/`（10 文件零改动副本） | [bloc97/Anime4K](https://github.com/bloc97/Anime4K) | MIT ×8 + Unlicense ×2（逐文件头） | [licenses/ANIME4K-LICENSE-NOTES.md](licenses/ANIME4K-LICENSE-NOTES.md) |
| Hyllian xBR-lv2 | `shaders/p3-xBR-lv2.glsl`（适配版） | [libretro/glsl-shaders](https://github.com/libretro/glsl-shaders/blob/master/xbr/shaders/xbr-lv2.glsl) | MIT | [licenses/XBR-LICENSE-NOTES.md](licenses/XBR-LICENSE-NOTES.md) |
| Sharp Bilinear | `shaders/p3-Sharp-Bilinear-AUTO.glsl`、`shaders/p3-Sharp-Bilinear-2x.glsl`（适配版） | [libretro/glsl-shaders（Themaister）](https://github.com/libretro/glsl-shaders/blob/master/interpolation/shaders/sharp-bilinear.glsl) | Public domain | [licenses/SHARP-BILINEAR-LICENSE-NOTES.md](licenses/SHARP-BILINEAR-LICENSE-NOTES.md) |

适配哈希记录于 `shaders/resource-manifest.json` 与 `shaders/p3-resource-manifest.json`（安装器预检亦以此做源损坏检测）。

> 说明：`docs/证据/` 是**随仓库保留**的取证件目录（`.gitattributes` 对其关闭换行归一化以保字节一致）；与它不同，「证据不入库」政策仅指 `docs/验证/开发/` 下的会话验证证据树（见[证据留存策略](docs/验证/证据留存策略.md)）——两者不冲突，上面的溯源链接在仓库里始终可查。

## FAQ

**F8 按了没反应？** 按序排查：

1. **脚本未加载**：确认 `scripts\scale-selector.lua` 与 `script-opts\scale-selector*.conf` 三个文件在位；看启动日志有无脚本报错（怎么看日志见下一条）。
2. **Fn / F-Lock**：笔记本 F8 被映射为媒体功能键时按 Fn+F8 或切换 F-Lock。判别法：`script-message` 能切档而真实键盘不能 → 问题在系统键盘层，不在插件。
3. **窗口焦点**：mpv 窗口必须在前台，菜单键由 mpv 进程接收。
4. **键位被改/被占**：检查 `input.conf` 是否绑定了 F8；或 `scale-selector.conf` 的 `key_menu=` 已被改动。改键/留空方法见「菜单操作」。

**怎么看启动日志？** 在 cmd/PowerShell 里直接运行 `mpv`（而不是双击快捷方式），日志即打印在控制台；或在命令行加 `--log-file=<路径>` 落盘成文件（mpv 手册选项）。核对预期告警：`findstr /c:"覆盖被忽略" <日志文件>` 应命中 6 行。

**选档后几秒内自动弹回（提示原因）？** 这是链验证失败后的自动回滚：shader 编译失败或未生效——常见于老 GPU/驱动，或没有用 `vo=gpu-next`。排查顺序：更新 GPU 驱动 → 确认 `vo=gpu-next` → 换其它档位交叉定位（LUMA 档与 MAIN 档资源不同）→ 在日志中找 libplacebo/shader 编译报错行。插件会回滚到上一稳定状态，无半生效残留。

**选档时突然变成「外部态」？** 这些键不是本插件提供的——它们来自你自己在 `input.conf` 里绑定的手动 Anime4K 链（常见如 F6、Ctrl+1..6，直接 `change-list glsl-shaders`）。此类外部改动会让插件让出（外部优先，不静默覆盖），属共存设计而非故障；没有这类绑定就不会遇到。

**启动日志 6 条「覆盖被忽略」告警？** 预期：防冒名解析器对内建/占位档位覆盖键的固定告警，无需处理。

**F8 会和别的绑定冲突吗？** mpv 出厂默认键位没有启用 F8（见「菜单操作」）。若你自己的 `input.conf` 绑定了 F8（包括用官方模板时解注释 `#F8 show-text ${playlist}`），会与默认 `key_menu=F8` 冲突——安装器安装时会检查 `input.conf` 并警告；介意就把 `key_menu=` 改为其他键，或留空改用 `script-binding scale_selector/scale-selector-menu`。

**portable 版 mpv 怎么装？** 安装、校验、卸载都支持 `-ConfigDir`，把它指向 portable 配置目录即可：`powershell -ExecutionPolicy Bypass -File tools\install.ps1 -ConfigDir "<mpv.exe 所在目录>\portable_config"`（`-Verify`/`-Uninstall` 同参数）。

**想卸载？** `powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Uninstall`——先逐个哈希核对，只删除与源一致的 21 项清单文件；哈希不符的（你改过的、或装的是旧版构建）会**拒绝删除**并逐项列出，确认不要后可按清单路径手动删除。`.bak-scale-install-<时间戳>` 备份与 `input.conf`/`mpv.conf`/既有文件从不被动，无需恢复任何配置。升级产生的备份会累积在原目录，可自行决定去留——顺带说明：`scripts\` 下的 `.bak` 备份会被 mpv 的目录扫描看到并在日志里留下一条无害的加载错误（日常安装报告实测一例），介意可删除备份。

## 文档索引

- [阶段索引](docs/阶段索引.md)：docs 下各文档的角色与现行有效性
- [用户说明（状态机、守卫与恢复语义细节）](docs/插件/缩放选择器-P3用户说明.md)
- [评审与改进建议（2026-10-12）](docs/评审与改进建议-2026-10-12.md)：43 条发现与修复记录
- [验证证据留存策略](docs/验证/证据留存策略.md)：证据树不入库、仓库外归档的默认决策

## English

**What is this?** A scaling-mode selector plugin for [mpv](https://mpv.io). Press **F8** to switch between 9 real scaling gears — AMD FSR1, NVIDIA NIS, Qualcomm SGSR1, Anime4K v4, Hyllian xBR-lv2, Sharp Bilinear (AUTO / 2×), Integer, Nearest — plus two permanently disabled honest placeholders (LS1 — the neural upscaler inside Lossless Scaling; BCAS — an algorithm name whose definition we could not verify). The menu is designed to show only the truth: guards, skip reasons, per-pass chain verification, automatic rollback.

**Features**

- 9 built-in gears with chain definitions compiled into the script; local config cannot fake labels or swap chains
- Honest guards: LUMA gears (FSR1/SGSR1/NIS) auto-disable on RGB/HDR input; MAIN gears (Anime4K/xBR/Sharp Bilinear) allow RGB and refuse HDR; upscale-only gears honestly report "skipped" instead of faking active
- Managed-property snapshot & restore on "off"; external changes win — the plugin yields instead of overwriting
- Wheel navigation with wrap-around, ✓ current-gear marker, and direct switching via `script-message`
- One-click installer: 21-file sha256 manifest, 3-state install (copy / skip / backup+overwrite), `-Verify`, `-Uninstall`, idempotent re-run upgrade
- 646 + 51 automated tests; verified co-existence with RIFE frame interpolation (7/7 matrix cases plus an environment-cleanup check)

**Install (Windows)**

```
git clone https://github.com/kkiwkK1/mpv-scale-selector.git
cd mpv-scale-selector
powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Yes
```

No git? Download the v0.1.0 *Source code (zip)* from [Releases](https://github.com/kkiwkK1/mpv-scale-selector/releases), unzip, and run the same command from the extracted folder. Targets `%APPDATA%\mpv` by default (`-ConfigDir` to override — portable users, point it at `portable_config`). Upgrade = run again. Exit codes: `0` ok · `1` param/env/IO error · `2` source precheck blocked · `3` not installed (`-Verify`) · `4` inconsistent (`-Verify`). Manual install: copy `scripts/scale-selector.lua`, the two `script-opts/*.conf`, and the whole `shaders/` tree (including `anime4k/`) into your mpv config dir, keeping relative paths — missing shaders make the corresponding gears fail honestly, never silently.

**Keybinds** — `F8` opens the menu (↑/↓ or wheel to move, skipping disabled entries, wrap-around; Enter / KP-Enter to apply; Esc to close; the menu stays open after applying; ✓ marks the current gear). Direct switching:

```
script-message scale-selector-set <off|fsr1|sgsr1|anime4k|nearest|nis|xbr|sharpbilinear|sharpbilinear2x|integer>
script-message scale-selector-cycle next|prev
```

Change the menu key in `script-opts/scale-selector.conf` (`key_menu=`; leave empty to bind via `script-binding scale_selector/scale-selector-menu`). Note: mpv's stock defaults leave F8 unused — the `#F8 show-text ${playlist}` line in upstream's `etc/input.conf` template is commented out. Conflicts can only come from your own `input.conf` or other scripts; the installer checks `input.conf` and warns if it finds one.

**License & third-party** — this project is MIT. Bundled shaders keep their own licenses: AMD FSR1 (MIT), NVIDIA NIS (MIT), Qualcomm SGSR1 (BSD-3-Clause), Anime4K (MIT ×8 + Unlicense ×2 per file header), Hyllian xBR-lv2 (MIT), Sharp Bilinear (public domain) — see `licenses/` for per-component attribution notes and `docs/证据/移植取证索引.json` for provenance. No quality claims: subjective image-quality evaluation has not been performed.
