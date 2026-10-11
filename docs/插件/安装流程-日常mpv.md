# scale-selector 安装流程（日常 mpv：%APPDATA%\mpv）

| 项 | 值 |
|---|---|
| 文档日期 | 2026-10-12（同日定稿：一键安装器置顶为主流程，手工流程降为附录 A） |
| 适用范围 | 把仓库工作树中的 scale-selector 插件安装进日常 mpv 配置目录 |
| 源（仓库工作树） | `D:\workspace\小项目\mpv插件\缩放插件`（当前分支 dev/improvement-analysis-20261012，HEAD 622fd57；`scripts/scale-selector.lua` 为 7d2c0ec 版，2758 行） |
| 目标 | `C:\Users\kkiw\AppData\Roaming\mpv`（= `%APPDATA%\mpv`） |
| 安装器 | `tools\install.ps1`（Windows PowerShell 5.1，无外部依赖，UTF-8 with BOM）+ `tools\install.bat`（双击入口） |
| 前置状态 | 沙盒 `D:\mpv-scale-acceptance` 验收通过（含 RIFE 共存测试 8/8）；预检 `go=true`、`blockers=[]` |
| 安装前快照 | `docs/插件/安装前快照-2026-10-12.json`（54 个既有文件的 sha256 映射，回滚核对用） |

菜单速览（事实来源：`script-opts/scale-selector-gears.conf:62`、`scripts/scale-selector.lua:1236-1277` open_menu、README:32-35）：F8 打开，共 12 项，首项「关」恒可用；打开时光标停在**当前生效档**，生效档在列表中标记「✓当前」（lua:1202）；UP/DOWN 移动时跳过灰显禁用项（LS1、BCAS）且**首尾循环**（next_enabled_wrap，lua:791）；WHEEL_UP/WHEEL_DOWN 同样移动光标；ENTER 或 KP_ENTER 激活当前项；ESC 关闭；**选档后菜单保持打开**（可继续切换）。菜单打开期间，插件消息显示在菜单状态头（不再叠加独立 OSD，lua:1041-1049）；验证完成/回退/外部让出等异步变化会自动重绘菜单。当前为「关」时按 DOWN×1 次即命中 FSR1（跳过禁用的 LS1）。

不经菜单直接切档（input.conf / uosc / IPC 自动化可用，lua:1304-1305、:2750-2751）：

```
script-message scale-selector-set <档位id|off>    # 与菜单 ENTER 同入口，守卫/禁用/external 拒绝规则一致
script-message scale-selector-cycle next|prev     # 跳过禁用档，首尾循环
```

---

## 1. 一键安装（推荐）

### 1.1 运行方式

- **双击** `tools\install.bat`：cd 仓库根 → 运行 ps1 → 暂停显示退出码 → 窗口关闭前按任意键继续；进程退出码**原样回传**给调用方（install.bat:17 `exit /b %EXITCODE%`）。
- **命令行**（仓库根执行，可加参数）：

```
powershell -ExecutionPolicy Bypass -File tools\install.ps1 [-ConfigDir <目录>] [-Uninstall] [-Verify] [-Yes]
```

- 默认目标 `%APPDATA%\mpv`（APPDATA 未设时报错退出 1）；`-ConfigDir` 指定其他目录——**测试一律指向隔离目录**，绝不指向真实配置以外的生产目录。
- `-Yes` 跳过交互确认（自动化/脚本调用一律带此参数）。
- 21 项清单与目标结构见附录 A.2；与附录 A 手工流程等价：同一清单、同一目标结构、同一 `<名>.bak-scale-install-<yyyyMMdd-HHmmss>` 冲突备分纪律。

### 1.2 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功/校验健康（安装完成——含 `[幂等]` 零改动；卸载完成其语义；校验 21/21 一致） |
| 1 | 参数/环境/IO 错误（未知参数、`-Uninstall`+`-Verify` 互斥、拒绝确认、APPDATA 缺失、拷贝/备分/删除失败、拷贝后核对不符） |
| 2 | 预检阻断（源缺失/不可读不可哈希/与 resource-manifest 在案 sha256 不符＝源损坏/manifest 解析失败） |
| 3 | 仅 `-Verify`：21 项一个都不存在（`[未安装]`） |
| 4 | 仅 `-Verify`：部分存在或哈希不符（`[不一致]`） |

### 1.3 安装三态与升级语义（逐文件）

- **缺失 → 复制**；**哈希与源一致 → 跳过**（零写盘）；**冲突（同名且内容不同）→ 先备分再覆盖**：旧文件复制为 `<名>.bak-scale-install-<yyyyMMdd-HHmmss>`，再落新文件。每次复制后立即 sha256 核对，不符 exit 1。
- **升级 = 重跑同一条安装命令**。日常 mpv 已装旧版时（如 2026-10-12 手动安装的构建落后于仓库 HEAD），重跑即把哈希不符的清单文件自动备分为 `.bak-scale-install-<时间戳>` 后替换为新版；哈希一致的文件跳过不动。无需先卸载。
- **幂等**：21 项全部与源一致时零改动，输出 `[幂等] 复制=0 跳过=21 备分=0，零改动` 后 `[安装完成]`，exit 0。
- **清单外绝不触碰**：`input.conf`/`mpv.conf`、既有 `scripts\*.lua`（playback-status.lua、rife-env.lua）、`shaders\` 根目录既有 37 个 Anime4K_*.glsl、各种 `.bak*`；install.ps1 **不写也不生成** `input.conf`（键绑定由脚本运行时完成）。

### 1.4 `-Verify` 与 `-Uninstall`

- **`-Verify`**（只读，绝不写盘、绝不确认，可无脑运行）：21/21 一致 `[校验通过]` exit 0；一个都不存在 `[未安装]` exit 3；部分存在/哈希不符 `[不一致]`（附缺失与不符清单）exit 4。清单命名空间之外的多余文件不检查不报告。
- **`-Uninstall`**：先逐个哈希核对并统计可删数，确认后删除；**只删与源哈希一致的 21 项清单文件**（哈希不符的拒绝删除，防误删用户改动）；`.bak-scale-install-*` 备份、`input.conf`/`mpv.conf`、既有 scripts 与 shaders 根目录文件绝不触碰；仅当 `script-opts\`/`shaders\anime4k\` 删后为空才删目录（非空输出「保留目录（非空）」；`scripts\`/`shaders\` 根目录任何情况下不删）。

### 1.5 预检与 F8 警告

- **预检**（所有模式最先执行，exit 2 抢占 `-Verify`/`-Uninstall` 的 3/4）：21 源缺失/不可哈希、与两个 resource-manifest 在案 sha256 不符（源损坏，覆盖 16/21：10 anime4k + p2×2 + p3×4）、manifest JSON 解析失败/结构异常（fail-closed）。如实声明覆盖面边界：`scale-selector.lua`、两个 `.conf`、两个 manifest 自身无第二哈希源，内容级损坏不可检；语义级校验属仓库 Python 验证工具（p2_lib/p3_lib）职责。
- **F8 冲突警告**：install 模式读目标 `input.conf`（跳过注释与空行，取首 token 精确等于 `F8`）命中则仅警告不阻断，绝不修改 input.conf。默认 `key_menu=F8` 会覆盖 mpv 内置的 F8（显示播放列表）——详见 §4 常见问题。

### 1.6 标记一览

| 标记 | 出现处 |
|---|---|
| `[安装完成]` | install 成功收尾（幂等时先输出 `[幂等] 复制=0 跳过=21 备分=0，零改动`） |
| `[幂等]` | install 全零改动 |
| `[已备分]` | install 冲突备分（附备份文件名） |
| `[校验通过]` | 仅 Verify，21/21 一致 |
| `[未安装]` | Verify exit 3；Uninstall 收尾（附删除/跳过/拒绝计数） |
| `[不一致]` | Verify exit 4（附缺失与哈希不符清单）；Uninstall 拒删哈希不符文件 |

### 1.7 自测记录

- **2026-10-12 安装器轮**（隔离目录 `D:\mpv-scale-acceptance\installer-test\config`，runner：`D:\mpv-scale-acceptance\run-installer-tests.ps1`，42 项断言全过）：全新装 `[安装完成]` exit 0（21 复制+21 核对）；重跑 `[幂等]` 零写盘（mtime 快照不变）；改一个已装文件再装 `[已备分]` 且目标恢复源哈希、备份保存改动前内容；`-Verify` `[校验通过]` 零写盘；`-Uninstall`（含 `.bak` 幸存、空目录删/非空保留、重复卸载零删除）后 `-Verify` `[未安装]` exit 3；互斥/未知参数/拒绝确认 exit 1；仓库副本上源损坏、源缺失、manifest 截断均 exit 2。真实 `%APPDATA%\mpv` 仅做过一次「确认处取消」的冒烟运行（零写入）。
- **2026-10-12 定稿轮**（隔离目录同上，逐条实跑）：全新装 `[安装完成]` exit 0（复制 21/跳过 0/备分 0，逐文件核对全 OK）；重跑 `[幂等]` exit 0（21 项全跳过）；篡改 `script-opts\scale-selector.conf` 后重装 `[已备分] scale-selector.conf.bak-scale-install-<ts>` → 复制+核对 OK（复制=1 跳过=20 备分=1）exit 0，备份 sha256 与篡改版逐字节一致；`-Uninstall` exit 0（删 21 文件，`.bak` 幸存、script-opts 非空保留）。install.bat 退出码回传（真实 bat 字节 + stub ps1）：stub `exit 2`/`exit 0`/`exit 4` 分别回传 2/0/4。

---

## 2. 安装后验证

### 2.1 启动独立验证实例（含 install-verify 标题与管道名）

该实例加载日常 `mpv.conf`/`input.conf`（真实环境，含 RIFE vf 与 F9 状态栏）——这正是共存验证的意义；RIFE 相关文件零改动。

```bash
# 在单独的 Git Bash 窗口执行：
"/d/MPV/mpv.exe" --title=install-verify-scale --input-ipc-server=mpv-install-verify \
  --force-window=yes --pause "D:/mpv-scale-acceptance/test-clip-yuv.avi" &
```

- `--input-ipc-server=mpv-install-verify`：裸名，客户端连 `\\.\pipe\mpv-install-verify`。
- `--pause` + `--force-window=yes`：窗口停住等验证，不自动退出。

### 2.2 IPC 冒烟脚本

保存为 `%TEMP%\install_verify_scale.py`（改编自沙盒验收脚本 `D:\mpv-scale-acceptance\ipc_yuv_test.py`）。档位切换走 `script-message scale-selector-set`（与菜单 ENTER 同入口，守卫/禁用/external 规则完全一致，lua:1304-1305）——不依赖菜单顺序与按键次数，比 keypress F8→DOWN→ENTER 更稳；真实键盘路径另见 §2.5 手测。

```python
# install_verify_scale.py —— 日常 mpv 安装后验证（管道与标题均含 install-verify）
import json, time

PIPE = r'\\.\pipe\mpv-install-verify'
PROPS = ['glsl-shaders', 'scale', 'cscale', 'dscale', 'video-params/pixelformat']

def open_pipe(retries=40):
    for _ in range(retries):
        try:
            f = open(PIPE, 'r+b', buffering=0)
            f.write(b'{"command":["get_property","mpv-version"]}\n')
            if json.loads(f.readline()).get('error') == 'success':
                print('pipe ok'); return f
        except OSError:
            time.sleep(0.25)
    raise SystemExit('pipe not available')

def cmd(f, payload):
    f.write((json.dumps({'command': payload}) + '\n').encode())
    return json.loads(f.readline())

def snapshot(f, label):
    print(f'---- {label}')
    for p in PROPS:
        print(f'  {p} = {cmd(f, ["get_property", p]).get("data")}')

f = open_pipe()
# 1) 插件已加载：菜单数据可读（lua:1112 导出 user-data/scale-selector/menu_entries）
r = cmd(f, ['get_property', 'user-data/scale-selector/menu_entries'])
print('menu_entries:', json.dumps(r.get('data'), ensure_ascii=False)[:400])
assert r.get('error') == 'success', 'scale-selector 未加载或属性不可读'
# 2) 档位切换：off → FSR1（script-message 直接切档，跳过禁用的 LS1 由插件自己处理）
cmd(f, ['script-message', 'scale-selector-set', 'fsr1']); time.sleep(1.0)
snapshot(f, 'YUV：scale-selector-set fsr1（应为 FSR1）')
# 3) 「关」恢复
cmd(f, ['script-message', 'scale-selector-set', 'off']); time.sleep(0.8)
snapshot(f, 'scale-selector-set off（应为关）')
# 4) 清理：让该实例自行退出
cmd(f, ['quit'])
print('done')
```

运行：`python "%TEMP%\install_verify_scale.py"`（Git Bash 下 `python "$LOCALAPPDATA/Temp/install_verify_scale.py"`）。

### 2.3 判读标准

- `pipe ok` → IPC 通。
- `menu_entries` 打印出菜单 JSON（12 项与禁用原因）→ 脚本已加载。
- 第一次 snapshot：`glsl-shaders` 出现 `p2-FSR1.glsl`（FSR1 档资源，gears conf 自述）；`video-params/pixelformat = yuv420p`（LUMA 守卫通过；`hwdec=auto` 不影响 LUMA 档，预检③沙盒已验）。
- 第二次 snapshot：`scale` 回到 `ewa_lanczossharp`（`profile=high-quality` 的展开值，预检①本机实测）；`glsl-shaders` 回到插件接管前的值（干净启动时通常为空——mpv.conf 无 `glsl-shaders=` 行，预检②）。
- `done` 且窗口自行关闭。

任何一步不符：先查 §4，仍不行按 §3 回滚并如实记录。

### 2.4 清理（兜底）

首选脚本末尾的 IPC `quit`（已含）。若窗口残留，在 **cmd**（非 Git Bash，斜杠参数会被 MSYS 改写）按标题精确清理：

```bat
taskkill /FI "WINDOWTITLE eq install-verify-scale" /IM mpv.exe
```

绝不执行不带 `/FI` 标题过滤的 `taskkill /IM mpv.exe`（可能杀掉正在使用或 sandbox 的 mpv 窗口，红线 3）。

### 2.5 F8 手测（真实键盘路径）

1. 日常方式打开任意视频，按 F8 → 菜单出现：首项「关」，共 12 项（`gears=off,ls1,fsr1,nis,sgsr1,bcas,anime4k,xbr,sharpbilinear,sharpbilinear2x,integer,nearest`，gears.conf:62；真实档位显示名以内建为准）。打开时光标停在当前生效档（关状态＝首项「关」，带「✓当前」标记）。
2. DOWN：光标「关」→ FSR1（跳过灰显 LS1）；继续 DOWN 依次向后（跳过灰显 BCAS），末项再 DOWN 循环回首项；UP 反向同理。WHEEL_UP/WHEEL_DOWN 也可移动光标。禁用项显示占位原因（LS1/BCAS，gears.conf:66-72）。
3. ENTER 或 KP_ENTER（小键盘回车）激活当前档位；**选档后菜单保持打开**，可继续切换；ESC 关闭菜单。菜单打开期间 UP/DOWN/WHEEL_UP/WHEEL_DOWN/ENTER/KP_ENTER/ESC 共 7 个键由 `add_forced_key_binding` 强制接管（scale-selector.lua:1268-1275；close_menu 同步移除全部 7 个，:1279-1296）——期间不落到音量/全屏等用户绑定，菜单关闭后原绑定不变。菜单打开期间插件消息显示在菜单状态头，不再叠加独立 OSD。
4. 笔记本注意 Fn/F-Lock：F8 被映射成媒体功能键时菜单打不开（见 §4）。

---

## 3. 卸载与回滚

**推荐：一键卸载**（仓库根执行；先逐文件哈希核对，只删与源一致的 21 项，语义详见 §1.4）：

```
powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Uninstall        # 交互确认
powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Uninstall -Yes   # 免确认
```

**卸载 = 删除 21 个清单文件**（§1.4 语义；手工等价命令见附录 A.5）。`input.conf`/`mpv.conf`/既有 scripts/既有 shaders 根目录文件从未被修改（F8 绑定全部由脚本运行时完成，input.conf 里没有也无需有 F8 行），因此**无需恢复任何配置文件**。运行中的 mpv 重启后插件即消失。`.bak-scale-install-*` 备份与清单外文件卸载后保留，由用户自行决定去留。

**何时用快照核对**：① 安装/使用后日常 mpv 出现异常，怀疑既有文件被误改；② 卸载完成后确认既有文件未动。核对脚本（只读，对照 `docs/插件/安装前快照-2026-10-12.json` 的 54 条 sha256）：

```bash
python - <<'EOF'
import json, hashlib, os
root = os.path.expandvars(r'%APPDATA%\mpv')
snap = json.load(open(r'D:\workspace\小项目\mpv插件\缩放插件\docs\插件\安装前快照-2026-10-12.json', encoding='utf-8'))
bad = 0
for rel, want in snap['files'].items():
    p = os.path.join(root, rel.replace('/', os.sep))
    h = hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.isfile(p) else '<missing>'
    if h != want:
        bad += 1
        print('CHANGED/MISSING', rel, h)
print(f"checked={len(snap['files'])} mismatch={bad}")   # 期望：checked=54 mismatch=0
EOF
```

---

## 4. 常见问题

**F8 无反应，按了没菜单**——按顺序排查：

1. **脚本未加载**：
   - 文件在位吗：`ls "$APPDATA/mpv/scripts/scale-selector.lua" "$APPDATA/mpv/script-opts/"scale-selector*.conf`（三个都应在）；
   - IPC 验证：跑 §2.2 脚本，`user-data/scale-selector/menu_entries` 能读到即已加载；读不到则看 mpv 启动日志（控制台启动 mpv 观察脚本报错）。
2. **Fn/F-Lock 键**：笔记本 F8 被映射为媒体功能键 → 按 Fn+F8 或切换 F-Lock。判别法：§2.2 用 IPC 能切档（或 keypress F8 能开菜单）而真实键盘不能 → 问题在系统键盘层，不在插件。
3. **窗口焦点**：mpv 窗口必须是前台（菜单键由 mpv 进程接收；焦点在别的窗口时无效）。
4. **键位被改/被占**：`scale-selector.conf:3` 的 `key_menu=F8`（默认值同，scale-selector.lua:71）；`grep -n "F8" "$APPDATA/mpv/input.conf"` 复核用户侧仍无绑定。

**默认 F8 覆盖 mpv 内置 F8（显示播放列表）**——预期行为：插件按 `key_menu=F8` 注册键绑定（lua:2749），覆盖 mpv 内置的 F8 播放列表。介意者把 `scale-selector.conf` 的 `key_menu=` 改为其他键；或**留空**＝不绑默认键，只注册命名绑定，在 `input.conf` 写 `<键> script-binding scale_selector/scale-selector-menu` 调用（mpv 脚本名仅含字母数字与下划线，`scale-selector.lua` 的脚本名是 `scale_selector`；README:32 同口径）。

**RGB 源上 LUMA 档灰显、不可选**——设计行为，不是故障：fsr1/sgsr1/nis 为 LUMA 档，输入为 RGB 系或 HDR（gamma∈{pq,hlg}）时守卫拒用并在菜单显示真实原因；anime4k/xbr/sharpbilinear/sharpbilinear2x 为 MAIN 档：**支持 RGB 输入**，但设独立 HDR 守卫（gamma∈{pq,hlg} 拒用）——其中 anime4k 于 2026-10-12（SHD-2）由 LUMA 档改归 MAIN 档，RGB 源不再误拒（lua:202 `luma=false, hdr=true`）。LUMA 档用 yuv420p 素材（如 test-clip-yuv.avi）即可激活。

**按过 F6/Ctrl+1..6 后插件档位显示「外部态」**——预期行为：这些手动 Anime4K 链直接 `change-list glsl-shaders`，插件 external 状态机让出并不静默覆盖（scale-selector.lua:5；预检 warning）。属共存设计而非故障。

**启动日志出现 6 条「覆盖被忽略」告警**——预期：防冒名解析器对内建档位/占位键的固定告警，不是配置错误，无需处理（gears.conf:46-49）。

**换了 portable 版 mpv 后插件失效**——portable 存在 `portable_config` 时 mpv 不读 `%APPDATA%\mpv`（预检实测当前无 portable_config；此为备案）。

---

## 附录 A：手动安装（Git Bash；一键安装器的手工等价流程）

> 一般情况直接用 §1 一键安装。本附录保留手工流程供核对、排障或在无 PowerShell 环境时使用。

### A.0 安装纪律（红线，违反即失败）

1. `%APPDATA%\mpv` 只允许【新增文件】与【新建目录】；对既有文件（`input.conf`、`mpv.conf`、`scripts\` 既有 *.lua、`shaders\` 既有文件、各种 `.bak*`）**绝不修改/删除/重命名**。若安装文件与既有文件同名：先把既有文件复制为 `<名>.bak-scale-install-<yyyymmdd-HHMMSS>` 再落新文件，并如实记录（一键安装器已内置同一纪律，见 §1.3）。
2. `D:\MPV\rife`、`D:\MPV\vs` 只读；仓库 `docs\验证\开发\` 绝不写。
3. **绝不 kill** 标题含 sandbox 或正在使用的 mpv 窗口；自己的验证实例统一用含 `install-verify` 的窗口标题与 IPC 管道名，测完先 IPC `quit`，兜底按标题 taskkill（见 §2.4）。
4. 所有文本 UTF-8；如实报告，查不到就说查不到，禁止伪造。

### A.1 前置条件

- **mpv 本体**：`D:\MPV\mpv.exe`（本文撰写时实测在位；同目录有 `mpv\`、`installer\`、`updater.bat`、`mpv-RIFE.cmd`）。
- **配置目录判定**：`D:\MPV\portable_config` 不存在（本文实测 `dir` 返回 No such file or directory；预检同结论）→ mpv 读 `%APPDATA%\mpv` = `C:\Users\kkiw\AppData\Roaming\mpv`。
  ⚠️ 若日后改用 portable 版（出现 portable_config），本安装不生效（预检 warning 备案）。
- **日常配置现状**（预检结论 + 本文实测目录列表）：
  - `mpv.conf`（55 行，预检通读）：line 15 `profile=high-quality`（本机 `--show-profile=high-quality` 实测展开含 `scale=ewa_lanczossharp`）；line 12 `hwdec=auto`；line 54 `vf-add=@rife:vapoursynth=...`（RIFE 插帧默认开启）；无任何显式 `scale=/cscale=/dscale=/glsl-shaders=/glsl-shaders-clr=/icc-profile=` 行，`vo=` 未设置。
  - `input.conf`（90 行，预检通读）：F8 未绑定（F1/F2/F3/F5/F6/F7/F9、Ctrl+0..6 有绑定）。UP/DOWN=音量±10、ENTER/KP_ENTER=全屏——菜单打开期间由 `add_forced_key_binding` 强制接管共 7 键（UP/DOWN/WHEEL_UP/WHEEL_DOWN/ENTER/KP_ENTER/ESC，scale-selector.lua:1268-1275；KP_ENTER 被菜单显式绑定为确认，不再落到全屏键），不冲突；安装前仍需复核（§A.3 步骤 0）。
  - `scripts\`：`playback-status.lua`（F9）、`rife-env.lua`（F7）——既有，不动。
  - `shaders\`：根目录 37 个 `Anime4K_*.glsl`（既有，F5/F6/Ctrl+1..6 手动链在用）；**无** `p2-*`/`p3-*`/两个 manifest/`anime4k\` 子目录（本文实测）。
  - `script-opts\`：不存在（本文实测）→ 本次新建。
- **RIFE 已在日常生活可用**（`D:\MPV\mpv-RIFE.cmd`）。本次绝不动 RIFE 相关任何文件：`mpv.conf` line 54 的 vf、`rife-env.lua`、`%APPDATA%\mpv\rife\`、`D:\MPV\rife`、`D:\MPV\vs`。插件有 external 状态机应对 vf/glsl-shaders 的外部改动（`scripts/scale-selector.lua:5`）。
- **工具链**（本文实测可用）：Git Bash（`P:\Git\usr\bin\bash.exe`，含 `cygpath`/`sha256sum`/`cmp`）、python（IPC 客户端）、`taskkill`。
- **验证素材**（本文实测在位）：`D:\mpv-scale-acceptance\ipc_yuv_test.py`（IPC 参考脚本）、`D:\mpv-scale-acceptance\test-clip-yuv.avi`（yuv420p，LUMA 档可用）。

判定命令（Git Bash，只读，可照抄）：

```bash
DST="$(cygpath "$APPDATA")/mpv"   # 本文实测展开为 /c/Users/kkiw/AppData/Roaming/mpv

ls "/d/MPV/mpv.exe"                                   # 应列出 mpv.exe
[ -e "/d/MPV/portable_config" ] && echo "存在 portable_config：本流程不适用" || echo "OK：无 portable_config，读 %APPDATA%\\mpv"
ls "$DST/scripts"                                     # 应见 playback-status.lua / rife-env.lua
ls "$DST/script-opts" 2>/dev/null || echo "OK：script-opts 不存在，将新建"
```

### A.2 文件清单表

共 **21 个文件 + 2 个新建目录**。目标列的绝对前缀为 `C:\Users\kkiw\AppData\Roaming\mpv`（下表省略写作 `%AR%` = `C:\Users\kkiw\AppData\Roaming`）。

| # | 源（仓库绝对路径） | 目标（绝对路径） | 作用 | 新增/备分 |
|---|---|---|---|---|
| 1 | `D:\workspace\小项目\mpv插件\缩放插件\scripts\scale-selector.lua` | `%AR%\mpv\scripts\scale-selector.lua` | 插件本体：F8 菜单 + off/active/external/fallback 状态机 + 托管属性快照恢复 + script-message 直切档（2758 行） | 新增 |
| 2 | `...\script-opts\scale-selector.conf` | `%AR%\mpv\script-opts\scale-selector.conf` | 标量选项：`key_menu=F8`（留空＝不绑默认键，见 §4）、菜单字号、`anime4k_chain`（a..f 对应 CTRL+1..6 链，默认 a） | 新增 |
| 3 | `...\script-opts\scale-selector-gears.conf` | `%AR%\mpv\script-opts\scale-selector-gears.conf` | 档位表：`gears=` 12 项顺序 + LS1/BCAS 禁用占位（真实档位定义内建于脚本，防冒名） | 新增 |
| 4 | `...\shaders\p2-FSR1.glsl` | `%AR%\mpv\shaders\p2-FSR1.glsl` | FSR1 档 shader（AMD FSR v1.0.2，LUMA，MIT） | 新增 |
| 5 | `...\shaders\p2-SGSR1.glsl` | `%AR%\mpv\shaders\p2-SGSR1.glsl` | SGSR1 档 shader（Qualcomm SGSR1 LUMA 适配版，BSD-3） | 新增 |
| 6 | `...\shaders\p3-NIS.glsl` | `%AR%\mpv\shaders\p3-NIS.glsl` | NIS 档 shader（NVIDIA Image Scaling v1.0.2 移植，LUMA，MIT） | 新增 |
| 7 | `...\shaders\p3-xBR-lv2.glsl` | `%AR%\mpv\shaders\p3-xBR-lv2.glsl` | xbr 档 shader（Hyllian xBR-lv2，MAIN RGB hook，MIT） | 新增 |
| 8 | `...\shaders\p3-Sharp-Bilinear-AUTO.glsl` | `%AR%\mpv\shaders\p3-Sharp-Bilinear-AUTO.glsl` | sharpbilinear 档 shader（AUTO 预缩放倍数） | 新增 |
| 9 | `...\shaders\p3-Sharp-Bilinear-2x.glsl` | `%AR%\mpv\shaders\p3-Sharp-Bilinear-2x.glsl` | sharpbilinear2x 档 shader（手动 2× 预缩放） | 新增 |
| 10 | `...\shaders\resource-manifest.json` | `%AR%\mpv\shaders\resource-manifest.json` | P2 资源审计清单（sha256 在案；运行时仅存在性检查，哈希审计由仓库 Python 工具承担——其 note 字段自述） | 新增 |
| 11 | `...\shaders\p3-resource-manifest.json` | `%AR%\mpv\shaders\p3-resource-manifest.json` | P3 新资源审计清单（四个 p3-*.glsl 适配移植的基文件/适配哈希） | 新增 |
| 12 | `...\shaders\anime4k\Anime4K_Clamp_Highlights.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Clamp_Highlights.glsl` | Anime4K 档链文件（stock v4 零改动副本） | 新增 |
| 13 | `...\shaders\anime4k\Anime4K_AutoDownscalePre_x2.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_AutoDownscalePre_x2.glsl` | 同上 | 新增 |
| 14 | `...\shaders\anime4k\Anime4K_AutoDownscalePre_x4.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_AutoDownscalePre_x4.glsl` | 同上 | 新增 |
| 15 | `...\shaders\anime4k\Anime4K_Restore_CNN_M.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Restore_CNN_M.glsl` | 同上 | 新增 |
| 16 | `...\shaders\anime4k\Anime4K_Restore_CNN_Soft_M.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Restore_CNN_Soft_M.glsl` | 同上 | 新增 |
| 17 | `...\shaders\anime4k\Anime4K_Restore_CNN_Soft_VL.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Restore_CNN_Soft_VL.glsl` | 同上 | 新增 |
| 18 | `...\shaders\anime4k\Anime4K_Restore_CNN_VL.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Restore_CNN_VL.glsl` | 同上 | 新增 |
| 19 | `...\shaders\anime4k\Anime4K_Upscale_CNN_x2_M.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Upscale_CNN_x2_M.glsl` | 同上 | 新增 |
| 20 | `...\shaders\anime4k\Anime4K_Upscale_CNN_x2_VL.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Upscale_CNN_x2_VL.glsl` | 同上 | 新增 |
| 21 | `...\shaders\anime4k\Anime4K_Upscale_Denoise_CNN_x2_VL.glsl` | `%AR%\mpv\shaders\anime4k\Anime4K_Upscale_Denoise_CNN_x2_VL.glsl` | 同上 | 新增 |

补充说明：

- **新建目录 2 个**：`script-opts\`（整个目录新建）、`shaders\anime4k\`（子目录新建；`shaders\` 本身已存在）。
- **不安装**：仓库 `shaders\.gitattributes`（任务要求；本文实测存在于仓库，`ls -a` 可见）。§A.3 的拷贝通配符只匹配 `*.glsl`，不会带上点开头文件。
- **basename 级同名 10 项**（#12–#21 装往 `shaders\anime4k\` 子目录，`shaders\` 根目录存在同名文件）：路径不同故**不覆盖、无需备分**，且预检 sha256 逐字节全部 SAME。将来若手动更新根目录 Anime4K 而不同步子目录，两套副本会漂移（插件读子目录、F6/Ctrl+1..6 读根目录）——见 §A.4 步骤 5。

### A.3 手动安装步骤（Git Bash，逐条注释）

```bash
# ===== 变量 =====
SRC="/d/workspace/小项目/mpv插件/缩放插件"     # 仓库工作树（源）
DST="$(cygpath "$APPDATA")/mpv"               # 日常 mpv 配置目录（目标）

# ===== 步骤 0：安装前复核（只读）=====
# F8 在 input.conf 中未绑定（预检已通读 90 行；输出应为空）
grep -n "F8" "$DST/input.conf"
# 快照在案（回滚核对依据）
ls -l "$SRC/docs/插件/安装前快照-2026-10-12.json"

# ===== 步骤 1：冲突探测（只读；期望全部 clear，与预检"零路径冲突"一致）=====
for f in scripts/scale-selector.lua \
         script-opts/scale-selector.conf script-opts/scale-selector-gears.conf \
         shaders/p2-FSR1.glsl shaders/p2-SGSR1.glsl shaders/p3-NIS.glsl \
         shaders/p3-Sharp-Bilinear-2x.glsl shaders/p3-Sharp-Bilinear-AUTO.glsl \
         shaders/p3-xBR-lv2.glsl shaders/resource-manifest.json \
         shaders/p3-resource-manifest.json shaders/anime4k; do
  [ -e "$DST/$f" ] && echo "exists: $f" || echo "clear: $f"
done
# 若出现 exists：按红线 1 先备分既有文件再拷贝，模板：
#   cp -p "$DST/<路径>/<名>" "$DST/<路径>/<名>.bak-scale-install-$(date +%Y%m%d-%H%M%S)"
# 并把备分情况如实记录进安装结果。（一键安装器自动做同一件事，见 §1.3。）

# ===== 步骤 2：新建目录（仅新增，绝不触碰既有文件）=====
mkdir -p "$DST/script-opts"        # 预检实测不存在
mkdir -p "$DST/shaders/anime4k"    # 预检实测不存在（shaders\ 本身不动）

# ===== 步骤 3：复制脚本与配置（3 个文件）=====
cp "$SRC/scripts/scale-selector.lua"            "$DST/scripts/"
cp "$SRC/script-opts/scale-selector.conf"       "$DST/script-opts/"
cp "$SRC/script-opts/scale-selector-gears.conf" "$DST/script-opts/"

# ===== 步骤 4：复制 shader 与清单（18 个文件）=====
# 通配符只匹配 *.glsl，不含点开头文件（.gitattributes 不会被带上），也不含子目录
cp "$SRC"/shaders/p2-*.glsl "$SRC"/shaders/p3-*.glsl "$DST/shaders/"
cp "$SRC"/shaders/resource-manifest.json "$SRC"/shaders/p3-resource-manifest.json "$DST/shaders/"
cp "$SRC"/shaders/anime4k/*.glsl "$DST/shaders/anime4k/"

# ===== 步骤 5：落盘核对（源↔目标逐文件字节比对；期望 checked=21 diff=0）=====
cd "$SRC"
n=0; bad=0
for f in scripts/scale-selector.lua \
         script-opts/scale-selector.conf script-opts/scale-selector-gears.conf \
         shaders/p2-FSR1.glsl shaders/p2-SGSR1.glsl shaders/p3-NIS.glsl \
         shaders/p3-Sharp-Bilinear-2x.glsl shaders/p3-Sharp-Bilinear-AUTO.glsl \
         shaders/p3-xBR-lv2.glsl shaders/resource-manifest.json \
         shaders/p3-resource-manifest.json shaders/anime4k/*.glsl; do
  n=$((n+1))
  cmp -s "$f" "$DST/$f" || { bad=$((bad+1)); echo "DIFF $f"; }
done
echo "checked=$n diff=$bad"    # 期望：checked=21 diff=0
```

### A.4 手动版本升级流程（更新插件时）

> **推荐直接重跑一键安装**（§1.3：哈希不符的清单文件自动 `.bak-scale-install-<ts>` 备分后替换，重跑即升级）。以下为手工等价流程。

前提：新版源仍取自本仓库已验收的工作树/分支（升级前 `git -C "D:/workspace/小项目/mpv插件/缩放插件" status --porcelain` 确认源状态符合预期）。

1. **重拷三个位置**（插件自有文件，先按红线 1 备分再覆盖；清单之外的文件仍绝不动）：
   ```bash
   SRC="/d/workspace/小项目/mpv插件/缩放插件"
   DST="$(cygpath "$APPDATA")/mpv"
   for f in scripts/scale-selector.lua script-opts/scale-selector.conf script-opts/scale-selector-gears.conf; do
     cmp -s "$SRC/$f" "$DST/$f" || cp -p "$DST/$f" "$DST/$f.bak-scale-install-$(date +%Y%m%d-%H%M%S)"
     cp "$SRC/$f" "$DST/$f"
   done
   ```
2. **shaders 增量**：只看本插件命名空间（`p2-*.glsl`/`p3-*.glsl`/两个 manifest/`anime4k\`）：
   ```bash
   diff <(cd "$SRC/shaders" && ls -1 p2-*.glsl p3-*.glsl *resource-manifest.json anime4k/*.glsl 2>/dev/null | sort) \
        <(cd "$DST/shaders" && ls -1 p2-*.glsl p3-*.glsl *resource-manifest.json anime4k/*.glsl 2>/dev/null | sort)
   ```
   - 仅在源侧出现的文件（新增）→ 直接 `cp`；
   - 两侧都有但内容已变（`cmp` 不一致）→ 先按红线 1 备分目标：`cp -p "$DST/x" "$DST/x.bak-scale-install-$(date +%Y%m%d-%H%M%S)"`，再 `cp`；
   - 仅在目标侧出现的旧文件（新版已删）→ 可选删除，但仅限本命名空间内的文件。
3. **哈希核对**：重跑 §A.3 步骤 5 的 cmp 循环（期望 `diff=0`，`checked=` 当次清单文件数）；需要哈希留档时用 `sha256sum` 双侧各生成一份再 `diff`。
4. **既有文件未被波及**：跑 §3 的快照核对（期望 `checked=54 mismatch=0`）。
5. **两套 Anime4K 副本的漂移提醒**（预检 warning）：插件档位读 `shaders\anime4k\` 子目录，F6/Ctrl+1..6 手动链读 `shaders\` 根目录。升级只改子目录（我们的文件）；若想同步更新根目录副本，那属于修改既有文件，须自行决定并另行备分，超出本流程纪律范围。

### A.5 手动卸载（一键 `-Uninstall` 的手工等价）

```bash
DST="$(cygpath "$APPDATA")/mpv"

# 21 个文件（全部是本流程安装的；绝不匹配 shaders 根目录的 Anime4K_*.glsl——那是既有文件）
rm "$DST/scripts/scale-selector.lua"
rm "$DST/script-opts/scale-selector.conf" "$DST/script-opts/scale-selector-gears.conf"
rmdir "$DST/script-opts" 2>/dev/null || echo "script-opts 非空（内含其他插件配置或 .bak），保留目录"
rm "$DST/shaders/p2-FSR1.glsl" "$DST/shaders/p2-SGSR1.glsl" "$DST/shaders/p3-NIS.glsl" \
   "$DST/shaders/p3-Sharp-Bilinear-2x.glsl" "$DST/shaders/p3-Sharp-Bilinear-AUTO.glsl" \
   "$DST/shaders/p3-xBR-lv2.glsl" \
   "$DST/shaders/resource-manifest.json" "$DST/shaders/p3-resource-manifest.json"
rm -r "$DST/shaders/anime4k"
```

（与 `-Uninstall` 的差异：手工 `rm` 不做哈希核对，前提是确信这些文件未被自己改过；`-Uninstall` 只删哈希一致者，更安全。）

---

## 附录 B：本文事实出处索引

- 任务书与预检结论（安装前快照同轮）：目录现状、F8 未绑定、零路径冲突、10 项 basename 同名 sha256 全 SAME、`profile=high-quality` 展开值、`hwdec=auto`、mpv.conf/input.conf 行数与 RIFE vf 位置、沙盒验收 8/8、菜单操作序列、IPC 用法、测试片与参考脚本。
- 首版本文实测（2026-10-12）：仓库三处源目录文件清单与 `.gitattributes` 存在；`D:\MPV\portable_config`、`%APPDATA%\mpv\script-opts`、`shaders\anime4k\` 均不存在；`D:\MPV\mpv.exe` 在位；验证素材两文件在位；Git Bash `cygpath "$APPDATA"`、`sha256sum`、`cmp`、`taskkill` 可用；快照 JSON 为 54 文件 sha256 映射。
- 定稿轮实测（2026-10-12，本会话）：`wc -l scripts/scale-selector.lua` = 2758；`grep/sed` 核对 `key_menu` 默认（lua:71，注释「留空＝不绑默认键」）、默认键注册（lua:2747-2749 `mp.add_key_binding(o.key_menu, "scale-selector-menu", toggle_menu)`）、菜单 7 个强制绑定（lua:1268-1275，UP/DOWN/WHEEL_UP/WHEEL_DOWN/ENTER/KP_ENTER/ESC）、close_menu 同步移除全部 7 个（lua:1279-1296）、首尾循环 next_enabled_wrap（lua:791 定义、:1250 使用）、打开时光标停在当前档（lua:1240-1243）、「✓当前」标记（lua:1202）、菜单打开期间 osd_message 写状态头不弹独立 OSD（lua:1041-1049）、script-message 注册与用法（lua:1304-1305、:2750-2752：`scale-selector-set <id|off>` / `scale-selector-cycle [next|prev]` / `scale-selector-selftest`）、menu_entries 导出仍在（lua:1112）、anime4k 档位定义 `luma=false, hdr=true`（lua:202，SHD-2）；`script-opts/scale-selector.conf:3` key_menu=F8；gears.conf `gears=` 顺序（:62）、LS1/BCAS 占位（:66-72）、预期告警（:46-49）；README:32（key_menu 留空与 script-binding 下划线写法、F8 覆盖内置键）、:33-35（LUMA/MAIN 档守卫口径）；`tools/install.bat:17` `exit /b %EXITCODE%`（退出码回传）。
- 安装器行为与自测：§1.7 两轮记录（2026-10-12 安装器轮 42 项断言；定稿轮隔离四场景 + bat 退出码回传 stub 0/2/4，均本会话实跑）。
- 参考脚本 `D:\mpv-scale-acceptance\ipc_yuv_test.py`：`\\.\pipe\` 连接方式（:5,12）、`user-data/scale-selector/menu_entries`（:37）。
