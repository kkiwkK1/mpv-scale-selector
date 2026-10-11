# =============================================================================
# scale-selector 一键安装器（tools/install.ps1）
# =============================================================================
# 用法:
#   powershell -ExecutionPolicy Bypass -File tools\install.ps1 [-ConfigDir <目录>] [-Uninstall] [-Verify] [-Yes]
#
#   -ConfigDir  mpv 配置目录（默认 %APPDATA%\mpv）
#   -Uninstall  卸载：只删除 21 项清单中与源 sha256 一致的文件（与 -Verify 互斥）
#   -Verify     只读校验：绝不写盘、绝不提示确认（与 -Uninstall 互斥）
#   -Yes        跳过交互确认（自动化测试一律带此参数）
#
# 退出码:
#   0  成功/校验健康（install 完成含 [幂等] 零改动；Uninstall 完成其语义；Verify 21/21 一致）
#   1  参数/环境/IO 错误（未知参数、互斥、拒绝确认、APPDATA 缺失、拷贝/备分/删除失败、核对不符）
#   2  预检阻断（源缺失/不可读不可哈希/与 resource-manifest 在案 sha256 不符=源损坏/manifest 解析失败）
#   3  仅 -Verify：21 项一个都不存在（[未安装]）
#   4  仅 -Verify：部分存在或哈希不符（[不一致]）
#
# 运行环境: Windows PowerShell 5.1，无外部依赖。
# 保存要求: UTF-8 with BOM（无 BOM 时 PS5.1 按 ANSI 误读，中文字面量会静默变乱码）。
# =============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# 用法说明与公共小函数
# ---------------------------------------------------------------------------
function Write-Usage {
    Write-Output '用法: powershell -ExecutionPolicy Bypass -File tools\install.ps1 [-ConfigDir <目录>] [-Uninstall] [-Verify] [-Yes]'
    Write-Output '  -ConfigDir  mpv 配置目录（默认 %APPDATA%\mpv）'
    Write-Output '  -Uninstall  卸载清单文件：只删除与源 sha256 一致者（与 -Verify 互斥）'
    Write-Output '  -Verify     只读校验安装状态：不写盘、不确认（与 -Uninstall 互斥）'
    Write-Output '  -Yes        跳过交互确认'
    Write-Output '退出码: 0=成功 1=参数/环境/IO错误 2=预检阻断(源问题) 3=未安装(仅Verify) 4=不一致(仅Verify)'
}

function Test-YesAnswer {
    param([string]$Answer)
    $a = $Answer.Trim()
    return ($a -eq 'y' -or $a -eq 'yes')
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

# ---------------------------------------------------------------------------
# 参数解析（手动解析 $args：让 [Console]::OutputEncoding 保持第一语句，
#           且未知参数能输出用法说明后 exit 1，而不是 PS 报原生绑定错误）
# ---------------------------------------------------------------------------
$OptConfigDir = $null
$OptUninstall = $false
$OptVerify    = $false
$OptYes       = $false

$RawArgs = @($args)
for ($i = 0; $i -lt $RawArgs.Count; $i++) {
    $tok = [string]$RawArgs[$i]
    $configValue = $null
    if ($tok -eq '-ConfigDir') {
        if (($i + 1) -ge $RawArgs.Count) {
            Write-Output '[错误] -ConfigDir 缺少参数值'
            Write-Usage
            exit 1
        }
        $i++
        $configValue = [string]$RawArgs[$i]
    }
    elseif ($tok -like '-ConfigDir=*') {
        $configValue = $tok.Substring(11)
    }
    elseif ($tok -eq '-Uninstall') { $OptUninstall = $true; continue }
    elseif ($tok -eq '-Verify')    { $OptVerify    = $true; continue }
    elseif ($tok -eq '-Yes')       { $OptYes       = $true; continue }
    else {
        Write-Output "[错误] 未知参数: $tok"
        Write-Usage
        exit 1
    }
    # -ConfigDir 取值校验（属参数合法性，先于预检）
    if ($null -eq $configValue -or $configValue.Trim().Length -eq 0) {
        Write-Output "[错误] -ConfigDir 参数值为空: $tok"
        Write-Usage
        exit 1
    }
    if ($configValue.Trim() -like '-*') {
        Write-Output "[错误] -ConfigDir 参数值无效（看起来是另一个开关）: $configValue"
        Write-Usage
        exit 1
    }
    $OptConfigDir = $configValue
}

if ($OptUninstall -and $OptVerify) {
    Write-Output '[错误] -Uninstall 与 -Verify 互斥，只能选其一'
    Write-Usage
    exit 1
}

# ---------------------------------------------------------------------------
# 安装清单（21 项；数组顺序即处理顺序；src/dst 以 '/' 记录，使用前统一转 '\'）
# ---------------------------------------------------------------------------
$Manifest = @(
    [pscustomobject]@{ Src = 'scripts/scale-selector.lua';                 Dst = 'scripts/scale-selector.lua' }
    [pscustomobject]@{ Src = 'script-opts/scale-selector.conf';            Dst = 'script-opts/scale-selector.conf' }
    [pscustomobject]@{ Src = 'script-opts/scale-selector-gears.conf';      Dst = 'script-opts/scale-selector-gears.conf' }
    [pscustomobject]@{ Src = 'shaders/p2-FSR1.glsl';                       Dst = 'shaders/p2-FSR1.glsl' }
    [pscustomobject]@{ Src = 'shaders/p2-SGSR1.glsl';                      Dst = 'shaders/p2-SGSR1.glsl' }
    [pscustomobject]@{ Src = 'shaders/p3-NIS.glsl';                        Dst = 'shaders/p3-NIS.glsl' }
    [pscustomobject]@{ Src = 'shaders/p3-xBR-lv2.glsl';                    Dst = 'shaders/p3-xBR-lv2.glsl' }
    [pscustomobject]@{ Src = 'shaders/p3-Sharp-Bilinear-AUTO.glsl';        Dst = 'shaders/p3-Sharp-Bilinear-AUTO.glsl' }
    [pscustomobject]@{ Src = 'shaders/p3-Sharp-Bilinear-2x.glsl';          Dst = 'shaders/p3-Sharp-Bilinear-2x.glsl' }
    [pscustomobject]@{ Src = 'shaders/resource-manifest.json';             Dst = 'shaders/resource-manifest.json' }
    [pscustomobject]@{ Src = 'shaders/p3-resource-manifest.json';          Dst = 'shaders/p3-resource-manifest.json' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_AutoDownscalePre_x2.glsl';        Dst = 'shaders/anime4k/Anime4K_AutoDownscalePre_x2.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_AutoDownscalePre_x4.glsl';        Dst = 'shaders/anime4k/Anime4K_AutoDownscalePre_x4.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Clamp_Highlights.glsl';           Dst = 'shaders/anime4k/Anime4K_Clamp_Highlights.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Restore_CNN_M.glsl';              Dst = 'shaders/anime4k/Anime4K_Restore_CNN_M.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Restore_CNN_Soft_M.glsl';         Dst = 'shaders/anime4k/Anime4K_Restore_CNN_Soft_M.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Restore_CNN_Soft_VL.glsl';        Dst = 'shaders/anime4k/Anime4K_Restore_CNN_Soft_VL.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Restore_CNN_VL.glsl';             Dst = 'shaders/anime4k/Anime4K_Restore_CNN_VL.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Upscale_CNN_x2_M.glsl';           Dst = 'shaders/anime4k/Anime4K_Upscale_CNN_x2_M.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Upscale_CNN_x2_VL.glsl';          Dst = 'shaders/anime4k/Anime4K_Upscale_CNN_x2_VL.glsl' }
    [pscustomobject]@{ Src = 'shaders/anime4k/Anime4K_Upscale_Denoise_CNN_x2_VL.glsl';  Dst = 'shaders/anime4k/Anime4K_Upscale_Denoise_CNN_x2_VL.glsl' }
)
$Total = $Manifest.Count

# ---------------------------------------------------------------------------
# 源根自定位（tools\install.ps1 -> 仓库根，与 CWD 无关）
# ---------------------------------------------------------------------------
try {
    $repoRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath)
}
catch {
    Write-Output "[错误] 无法定位仓库根（$PSScriptRoot\..）: $($_.Exception.Message)"
    exit 1
}

# ---------------------------------------------------------------------------
# 预检（所有模式统一最先执行，exit 2 抢占 -Verify/-Uninstall 的 3/4）
#   ① 21 个源文件存在性  ② 逐个可读可哈希  ③ 与两个 resource-manifest 在案
#   sha256 交叉校验（源损坏检测）  ④ ConfigDir 解析（APPDATA 缺失属环境错误 exit 1）
# ---------------------------------------------------------------------------
# ① 存在性
$missingSources = @()
foreach ($item in $Manifest) {
    $srcRel = $item.Src.Replace('/', '\')
    $srcPath = Join-Path $repoRoot $srcRel
    if (-not (Test-Path -LiteralPath $srcPath -PathType Leaf)) {
        $missingSources += $srcPath
    }
}
if ($missingSources.Count -gt 0) {
    Write-Output '[预检失败] 以下源文件缺失（exit 2）:'
    foreach ($p in $missingSources) { Write-Output "  $p" }
    exit 2
}

# ② 逐个计算 sha256（不可读即失败）
$SrcHash = @{}
$hashFailed = @()
foreach ($item in $Manifest) {
    $srcRel = $item.Src.Replace('/', '\')
    $srcPath = Join-Path $repoRoot $srcRel
    try {
        $SrcHash[$srcRel] = Get-FileSha256 -Path $srcPath
    }
    catch {
        $hashFailed += "$srcRel（$($_.Exception.Message)）"
    }
}
if ($hashFailed.Count -gt 0) {
    Write-Output '[预检失败] 以下源文件不可读/哈希计算失败（exit 2）:'
    foreach ($p in $hashFailed) { Write-Output "  $p" }
    exit 2
}

# ③ 源完整性交叉校验：manifest 在案 sha256 vs 实算
#    覆盖 16/21：resource-manifest.json 12 项（10 anime4k + p2-FSR1/p2-SGSR1）+
#    p3-resource-manifest.json 4 项（p3-*.glsl）；licenses/* 无 sha256 且不在安装清单，跳过。
function Read-IntegrityManifest {
    param([string]$ManifestAbsPath, [string]$ManifestRel)
    # 返回 @{ Ok; Err; Entries }：错误消息由调用方（顶层）负责 Write-Output 并 exit。
    # 不能在函数内 Write-Output 后 exit——函数内的输出会进入函数返回流被赋值语句
    # 捕获，进程随即退出，消息永远到不了 stdout（实测会得到"exit 2 但零输出"）。
    try {
        $rawText = Get-Content -LiteralPath $ManifestAbsPath -Raw -Encoding UTF8
        $parsed = ConvertFrom-Json -InputObject $rawText
    }
    catch {
        return @{ Ok = $false; Entries = @(); Err = "[预检失败] $ManifestRel JSON 解析失败（fail-closed，exit 2）: $($_.Exception.Message)" }
    }
    if ($null -eq $parsed -or $null -eq $parsed.resources) {
        return @{ Ok = $false; Entries = @(); Err = "[预检失败] $ManifestRel 结构异常（缺少 resources 数组，fail-closed，exit 2）" }
    }
    $entries = @()
    foreach ($res in @($parsed.resources)) {
        $p = [string]$res.path
        if ($res.PSObject.Properties['sha256'] -and -not [string]::IsNullOrEmpty([string]$res.sha256)) {
            $entries += [pscustomobject]@{ Path = $p; Sha256 = [string]$res.sha256 }
        }
        # 无 sha256 的项（licenses/*）按规格跳过，不参与交叉校验
    }
    return @{ Ok = $true; Entries = $entries; Err = '' }
}

$p2Read = Read-IntegrityManifest -ManifestAbsPath (Join-Path $repoRoot 'shaders\resource-manifest.json')    -ManifestRel 'shaders/resource-manifest.json'
if (-not $p2Read.Ok) { Write-Output $p2Read.Err; exit 2 }
$p3Read = Read-IntegrityManifest -ManifestAbsPath (Join-Path $repoRoot 'shaders\p3-resource-manifest.json') -ManifestRel 'shaders/p3-resource-manifest.json'
if (-not $p3Read.Ok) { Write-Output $p3Read.Err; exit 2 }
$p2Entries = @($p2Read.Entries)
$p3Entries = @($p3Read.Entries)
if ($p2Entries.Count -ne 12) {
    Write-Output "[预检失败] shaders/resource-manifest.json 结构异常：带 sha256 的资源应 12 项，实得 $($p2Entries.Count)（fail-closed，exit 2）"
    exit 2
}
if ($p3Entries.Count -ne 4) {
    Write-Output "[预检失败] shaders/p3-resource-manifest.json 结构异常：带 sha256 的资源应 4 项，实得 $($p3Entries.Count)（fail-closed，exit 2）"
    exit 2
}
$crossChecked = 0
$corruptSources = @()
foreach ($entry in (@($p2Entries) + @($p3Entries))) {
    $key = $entry.Path.Replace('/', '\')
    if (-not $SrcHash.ContainsKey($key)) {
        Write-Output "[预检失败] manifest 引用的资源不在 21 项安装清单内: $($entry.Path)（结构异常，fail-closed，exit 2）"
        exit 2
    }
    $crossChecked++
    if ($SrcHash[$key] -ne $entry.Sha256) {
        $corruptSources += "$key（实算 $($SrcHash[$key])，manifest 在案 $($entry.Sha256)）"
    }
}
if ($corruptSources.Count -gt 0) {
    Write-Output '[预检失败] 源损坏：以下文件实算 sha256 与 resource-manifest 在案值不符（exit 2）:'
    foreach ($c in $corruptSources) { Write-Output "  $c" }
    exit 2
}

# ④ ConfigDir 解析
if ($null -eq $OptConfigDir) {
    if ([string]::IsNullOrEmpty($env:APPDATA)) {
        Write-Output '[错误] 未提供 -ConfigDir 且 APPDATA 环境变量为空/未设，无法确定默认 mpv 配置目录（exit 1）'
        exit 1
    }
    $OptConfigDir = Join-Path $env:APPDATA 'mpv'
}
try {
    $configRoot = [System.IO.Path]::GetFullPath($OptConfigDir.Trim())
}
catch {
    Write-Output "[错误] -ConfigDir 路径非法: $OptConfigDir（$($_.Exception.Message)，exit 1）"
    exit 1
}

Write-Output "预检通过: 源 $Total/$Total 在位可哈希；交叉校验 $crossChecked/$Total 与 manifest 在案 sha256 一致"
Write-Output "（交叉校验覆盖面声明: scale-selector.lua、两个 .conf 与两个 manifest 自身无第二哈希源，其内容级损坏不可检；哈希一致但语义损坏属仓库 Python 验证工具职责）"

# ---------------------------------------------------------------------------
# 模式分派
# ---------------------------------------------------------------------------
if ($OptVerify) {
    # -----------------------------------------------------------------------
    # -Verify：只读，绝不写盘、绝不确认
    #   目标侧清单命名空间之外的多余文件不检查、不报告、不删除（只对 21 项负责）
    # -----------------------------------------------------------------------
    Write-Output "校验模式: 目标目录 $configRoot"
    $existing = 0
    $matching = 0
    $missingList = @()
    $mismatchList = @()
    $consistentLines = @()
    foreach ($item in $Manifest) {
        $srcRel = $item.Src.Replace('/', '\')
        $dstRel = $item.Dst.Replace('/', '\')
        $dstPath = Join-Path $configRoot $dstRel
        if (Test-Path -LiteralPath $dstPath -PathType Leaf) {
            $existing++
            try {
                if ((Get-FileSha256 -Path $dstPath) -eq $SrcHash[$srcRel]) {
                    $matching++
                    $consistentLines += "一致  $dstRel"
                }
                else {
                    $mismatchList += $dstRel
                }
            }
            catch {
                $mismatchList += "$dstRel（读取失败: $($_.Exception.Message)）"
            }
        }
        else {
            $missingList += $dstRel
        }
    }
    if ($existing -eq $Total -and $matching -eq $Total) {
        foreach ($line in $consistentLines) { Write-Output $line }
        Write-Output "[校验通过] $matching/$Total 哈希一致"
        exit 0
    }
    elseif ($existing -eq 0) {
        Write-Output "[未安装] 0/$Total 存在"
        exit 3
    }
    else {
        $missingStr = '无'
        if ($missingList.Count -gt 0) { $missingStr = $missingList -join ', ' }
        $mismatchStr = '无'
        if ($mismatchList.Count -gt 0) { $mismatchStr = $mismatchList -join ', ' }
        Write-Output "[不一致] 存在=$existing/$Total 一致=$matching 缺失=$missingStr 哈希不符=$mismatchStr"
        exit 4
    }
}
elseif ($OptUninstall) {
    # -----------------------------------------------------------------------
    # -Uninstall：先逐个哈希核对并确认清单内可删文件数，再删除
    #   只删与源哈希一致的清单文件；.bak-scale-install-* 备份、清单外文件、
    #   input.conf/mpv.conf、scripts\ 与 shaders\ 根目录绝不触碰
    # -----------------------------------------------------------------------
    Write-Output "卸载模式: 目标目录 $configRoot"
    $plan = @()
    foreach ($item in $Manifest) {
        $srcRel = $item.Src.Replace('/', '\')
        $dstRel = $item.Dst.Replace('/', '\')
        $dstPath = Join-Path $configRoot $dstRel
        $action = 'absent'
        if (Test-Path -LiteralPath $dstPath -PathType Leaf) {
            try {
                if ((Get-FileSha256 -Path $dstPath) -eq $SrcHash[$srcRel]) { $action = 'delete' }
                else { $action = 'refuse' }
            }
            catch {
                Write-Output "[错误] 无法读取目标文件以核对哈希: $dstPath : $($_.Exception.Message)"
                exit 1
            }
        }
        $plan += [pscustomobject]@{ Rel = $dstRel; Path = $dstPath; Action = $action }
    }
    $deletableCount = @($plan | Where-Object { $_.Action -eq 'delete' }).Count
    $refuseCount = @($plan | Where-Object { $_.Action -eq 'refuse' }).Count
    $absentCount = @($plan | Where-Object { $_.Action -eq 'absent' }).Count
    if (-not $OptYes) {
        $answer = Read-Host "确认卸载 $configRoot ？清单 $Total 项：哈希一致可删除 $deletableCount、哈希不符拒绝删除 $refuseCount、不存在 $absentCount（y/yes 继续）"
        if (-not (Test-YesAnswer $answer)) {
            Write-Output '已取消'
            exit 1
        }
    }
    $deletedCount = 0
    $refusedOut = 0
    $skippedOut = 0
    foreach ($e in $plan) {
        if ($e.Action -eq 'delete') {
            try {
                Remove-Item -LiteralPath $e.Path
            }
            catch {
                Write-Output "[错误] 删除失败: $($e.Rel) : $($_.Exception.Message)"
                exit 1
            }
            $deletedCount++
            Write-Output "删除  $($e.Rel)"
        }
        elseif ($e.Action -eq 'refuse') {
            $refusedOut++
            Write-Output "[不一致] $($e.Rel) 与源哈希不同，未删除"
        }
        else {
            $skippedOut++
        }
    }
    # 目录收尾：仅 script-opts\ 与 shaders\anime4k\ 删后为空才删；scripts\ 与 shaders\ 根目录绝不删
    foreach ($dirRel in @('script-opts', 'shaders\anime4k')) {
        $dirPath = Join-Path $configRoot $dirRel
        if (Test-Path -LiteralPath $dirPath -PathType Container) {
            $children = @(Get-ChildItem -LiteralPath $dirPath -Force)
            if ($children.Count -eq 0) {
                try {
                    Remove-Item -LiteralPath $dirPath
                }
                catch {
                    Write-Output "[错误] 空目录删除失败: $dirPath : $($_.Exception.Message)"
                    exit 1
                }
                Write-Output "删除空目录  $dirRel"
            }
            else {
                Write-Output "保留目录 $dirRel（非空）"
            }
        }
    }
    Write-Output "[未安装] 已删除 $deletedCount 个文件，跳过 $skippedOut，拒绝删除 $refusedOut"
    exit 0
}
else {
    # -----------------------------------------------------------------------
    # install（默认）：F8 警告 -> 确认 -> 建目录 -> 三态安装 -> 逐文件核对 -> 摘要
    # -----------------------------------------------------------------------
    Write-Output "安装模式: 目标目录 $configRoot"

    # F8 绑定检查（仅警告不阻断；绝不修改/生成 input.conf）
    $inputConfPath = Join-Path $configRoot 'input.conf'
    if (Test-Path -LiteralPath $inputConfPath -PathType Leaf) {
        try {
            $inputLines = @(Get-Content -LiteralPath $inputConfPath)
        }
        catch {
            Write-Output "注意: input.conf 存在但不可读（$($_.Exception.Message)），跳过 F8 绑定检查"
            $inputLines = @()
        }
        foreach ($line in $inputLines) {
            $t = "$line".Trim()
            if ($t.Length -eq 0) { continue }
            if ($t.StartsWith('#')) { continue }
            $firstToken = ($t -split '\s+')[0]
            if ($firstToken -eq 'F8') {
                Write-Output '警告: input.conf 已绑定 F8，与 scale-selector 菜单键（scale-selector.conf key_menu=F8）可能冲突，请自行确认'
            }
        }
    }

    if (-not $OptYes) {
        $answer = Read-Host "确认安装到 $configRoot ？共 $Total 个文件（y/yes 继续）"
        if (-not (Test-YesAnswer $answer)) {
            Write-Output '已取消'
            exit 1
        }
    }

    # 目录创建（目标侧只允许新增文件与新建目录；对已存在目录为无害 no-op）
    # 注：PS5.1 的 New-Item 无 -LiteralPath 参数，故用 .NET CreateDirectory 规避通配符语义
    $dirsToEnsure = @(
        $configRoot,
        (Join-Path $configRoot 'scripts'),
        (Join-Path $configRoot 'script-opts'),
        (Join-Path $configRoot 'shaders'),
        (Join-Path $configRoot 'shaders\anime4k')
    )
    foreach ($d in $dirsToEnsure) {
        if (Test-Path -LiteralPath $d -PathType Container) { continue }
        try {
            [void][System.IO.Directory]::CreateDirectory($d)
        }
        catch {
            Write-Output "[错误] 目录创建失败: $d : $($_.Exception.Message)"
            exit 1
        }
    }

    # 三态安装（缺失->复制 / 哈希一致->跳过 / 冲突->先备分再覆盖）+ 拷贝后逐文件核对
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $copiedCount = 0
    $skippedCount = 0
    $backedUpCount = 0
    foreach ($item in $Manifest) {
        $srcRel = $item.Src.Replace('/', '\')
        $dstRel = $item.Dst.Replace('/', '\')
        $srcPath = Join-Path $repoRoot $srcRel
        $dstPath = Join-Path $configRoot $dstRel
        $expectedHash = $SrcHash[$srcRel]
        try {
            if (-not (Test-Path -LiteralPath $dstPath -PathType Leaf)) {
                Copy-Item -LiteralPath $srcPath -Destination $dstPath
                $copiedCount++
                Write-Output "复制  $dstRel"
            }
            elseif ((Get-FileSha256 -Path $dstPath) -eq $expectedHash) {
                $skippedCount++
                Write-Output "跳过  $dstRel（哈希一致）"
                continue
            }
            else {
                $leafName = [System.IO.Path]::GetFileName($dstPath)
                $backupName = $leafName + '.bak-scale-install-' + $timestamp
                $backupPath = Join-Path ([System.IO.Path]::GetDirectoryName($dstPath)) $backupName
                if (Test-Path -LiteralPath $backupPath) {
                    Write-Output "[错误] 备份目标名已存在（同秒重跑）: $backupPath"
                    exit 1
                }
                Copy-Item -LiteralPath $dstPath -Destination $backupPath
                $backedUpCount++
                Write-Output "[已备分] $dstRel -> $backupName"
                Copy-Item -LiteralPath $srcPath -Destination $dstPath -Force
                $copiedCount++
                Write-Output "复制  $dstRel"
            }
            $afterHash = Get-FileSha256 -Path $dstPath
            if ($afterHash -ne $expectedHash) {
                Write-Output "[错误] 拷贝后哈希核对不符: $dstRel（期望 $expectedHash 实得 $afterHash）——拷贝损坏或被安全软件篡改"
                exit 1
            }
            Write-Output "核对  $dstRel OK"
        }
        catch {
            Write-Output "[错误] IO 失败: $dstRel : $($_.Exception.Message)"
            exit 1
        }
    }

    if (($copiedCount + $backedUpCount) -gt 0) {
        Write-Output "复制=$copiedCount 跳过=$skippedCount 备分=$backedUpCount"
    }
    else {
        Write-Output "[幂等] 复制=$copiedCount 跳过=$skippedCount 备分=$backedUpCount，零改动"
    }
    Write-Output '[安装完成]'
    exit 0
}
