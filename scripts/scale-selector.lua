-- scale-selector.lua — mpv 缩放算法选择器
-- session p3-001（P1 状态机 + P2 真实档位 + P3 新增档位）/ 阶段 P3（隔离验证；不持久化，重启回到 off）
--
-- 范围（P3 迁移说明；P1/P2 语义全部保留，逐条理由见 docs/P3/P3实现说明.md）：
--   * P1 全部语义保留：F8 菜单、off/active/external/fallback 状态机、托管属性
--     快照与恢复、外部改动让出（外部优先，插件绝不静默覆盖）、fallback 真实原因、
--     LS1/BCAS 禁用占位原文、绝不清链（无 glsl-shaders-clr）
--   * P2 新增四个内建真实档位（链定义内建于本脚本，不受本地 conf 冒名/改写）：
--       fsr1    = AMD FidelityFX FSR v1.0.2（EASU+RCAS，LUMA，MIT；每轴≤2×，
--                 超出由 mpv scaler 接管；资源 shaders/p2-FSR1.glsl）
--       sgsr1   = Qualcomm SGSR1（LUMA 适配版，BSD-3，单 pass；资源 shaders/p2-SGSR1.glsl）
--       anime4k = 本机 stock Anime4K v4 CTRL+1..6 精确链的零改动副本
--                 （shaders/anime4k/，经 anime4k_chain=a..f 选择，默认 a=CTRL+1）
--       nearest = scale=nearest + cscale=nearest + dscale=nearest（显式三值，无 shader）
--   * 一次仅一主链（brief 纠正后的权威语义）：P2 注册档位是整 property 替换
--     （whole chain）——首次接管也一体适用：off 状态下 glsl-shaders 若已有
--     原 Anime4K 链，显式选择 FSR/SGSR/Nearest 先快照基线再整 property 替换
--     到新登记 recipe（Nearest 空shader列表），绝不 append 到原链；已有 chain
--     不等于运行中 external，runtime 外部竞争才 yield。"关"只在 glsl-shaders
--     仍等于 last_written 且仍 owned 时恢复原完整 baseline；external 修改整
--     property 后保留用户完整列表，不凭路径字符串删除同名条目。P1 测试桩的
--     历史元素级语义保留为明确兼容模式（p1-test-* 桩），不套用于注册整主链
--   * RGB/HDR 守卫：LUMA 档（fsr1/sgsr1/anime4k/nis）在 pixelformat 为 RGB 系或
--     gamma∈{pq,hlg} 时拒用并在菜单/OSD 显示真实原因；P3 新增独立的 HDR 守卫
--     （xbr/sharpbilinear/sharpbilinear2x 为 MAIN RGB 档：支持 RGB，但 HDR 输入
--     拒用——HDR 守卫独立于 LUMA 守卫）；播放中变为 RGB/HDR 时释放自有链并如实回退
--   * P3 新增五个内建档位（链定义内建于本脚本，不受本地 conf 冒名/改写）：
--       nis            = NVIDIA Image Scaling v1.0.2（compute 32×24×256 + 两张
--                        2×64 rgba32f 系数纹理；MIT；内含锐化，绝不叠 NVSharpen；
--                        原 port 的边界写入缺陷以全部 barrier 之后的逐像素 bounds
--                        guard 修复；//!WHEN 仅放大生效原样保留；资源
--                        shaders/p3-NIS.glsl）
--       xbr            = Hyllian xBR-lv2（libretro 参考 MIT 版移植为 MAIN RGB
--                        hook；参考 XBR_SCALE=3 的「3× 预缩放 + mpv 后续缩放」
--                        模式，不冒称任意比例等价，不与 xBRZ 混称；资源
--                        shaders/p3-xBR-lv2.glsl）
--       sharpbilinear  = Sharp Bilinear AUTO（Themaister public domain 参考；
--                        scale=floor(输出高/输入高+0.01)，1080→1440 得 1 即明示
--                        「退化为双线性」；scale<1（含 0）钳制为 1 防除零；资源
--                        shaders/p3-Sharp-Bilinear-AUTO.glsl）
--       sharpbilinear2x= Sharp Bilinear 手动 2×（同源参考固定 PRE_SCALE=2；
--                        与 AUTO 分别命名；资源
--                        shaders/p3-Sharp-Bilinear-2x.glsl）
--       integer        = 整数倍缩放：k=floor(min(原窗口像素/有效显示尺寸))；
--                        video-unscaled=yes + video-zoom=log2(k) + 三核 nearest；
--                        窗口来源是原窗口像素（osd-width/height）与
--                        video-out-params（含旋转/crop/SAR 后的 dw/dh），
--                        绝不从自身缩小后的 osd-margin 推导（防黑边反馈）；
--                        k<1 为诚实回退（普通 nearest 缩小，不裁切）；几何属性
--                        （video-unscaled/video-zoom）纳入所有权账本，切换/退出
--                        恢复或转移，不污染 shader 档
--   * 链验证与诚实显示：激活后轮询 vo-passes，按 //!DESC 关键字核对本链 pass
--     确实存在；≤1×（//!WHEN 不满足）显示真实"跳过"而非伪 active；
--     编译失败/未生效→回滚到上一稳定状态（无半生效/陈旧 pass）
--   * 防陈旧：观察 video-reconfig 类变化（video-out-params / video-crop /
--     current-window-scale），重估适用性并刷新导出（chain_epoch 绑定）
--
-- 明确不做（后续阶段）：NIS/xBR/SharpBilinear/Integer 档位、HDR 画质评价
-- （PIC-06 另行立项）、持久化、部署。资源哈希审计由 Python 侧工具承担
-- （Lua 无 SHA-256；本脚本仅做存在性检查并如实回退）。
-- 后端：显式由测试/启动参数固定 vo=gpu-next、gpu-api=vulkan；本脚本不改变它们。

local mp = require 'mp'
local msg = require 'mp.msg'
local utils = require 'mp.utils'
local options = require 'mp.options'

local o = {
    key_menu = "F8",
    menu_font_size = 22,
    anime4k_chain = "a",   -- stock CTRL+1..6 链选择：a..f（默认 a=CTRL+1）
}
options.read_options(o, "scale-selector")

------------------------------------------------------------------
-- 常量与托管属性
------------------------------------------------------------------

local CORE_PROPS = { "glsl-shaders", "scale", "cscale", "dscale" }

-- 防陈旧观察的守卫属性（只读观察，永不写入；GEO-01：几何只读 video-out-params）。
-- P3 迁移（逐条理由见 docs/P3/P3实现说明.md）：加入 osd-width/osd-height ——
-- Integer 档需要窗口像素变化（含全屏切换）触发 k 重算；二者本就在
-- GEO-01 只读允许集内，永不写入。
local GUARD_PROPS = { "video-out-params", "video-crop", "current-window-scale",
                      "osd-width", "osd-height" }

-- 哨兵：快照时属性不可用（例如无视频时的显示几何）；恢复时跳过，绝不写回该字符串
local UNAVAIL = "@@unavailable@@"

local OFF_ID = "off"
-- V2-01 修复：off 显示名固定为常量"关"，本地 conf 的 off_label 不可冒名保留算法名
local OFF_LABEL = "关"

------------------------------------------------------------------
-- 档位注册表
-- 三类：
--   PLACEHOLDER_GEARS：未实现占位（P3+/无源码），强制 disabled 且身份固定。
--   BUILTIN_GEARS  ：P2 内建真实档位，mode 恒为 active、链定义内建，
--                     本地 conf 的 _mode/_set/_label/_reason 一律无效（防冒名）。
--   off            ：解析器强制恒在首项且可用；显示名固定 OFF_LABEL。
-- 这是解析器层的结构保证（P1 限域修正 A 的延伸）：本地 gears conf 无论怎么写，
-- 都无法让占位档位可选、无法改内建档位的链或借它们的标签挂任意链。
------------------------------------------------------------------
local PLACEHOLDER_GEARS = {
    { id = "ls1",   label = "LS1",   reason = "无公开源码/权重/移植许可，无法原样内置；不以替代算法冒名" },
    { id = "bcas",  label = "BCAS",  reason = "算法定义身份未核实；不以CAS/Bicubic+CAS冒名" },
}
-- P3 迁移：nis/xbr/sharpbilinear/integer 四个占位档位转 BUILTIN（真实内建），
-- 并新增 sharpbilinear2x；LS1/BCAS 保持占位 disabled（P3A-01/03 对齐口径）。

-- stock Anime4K v4 CTRL+1..6 精确链（与活动配置 input.conf 逐条等效；文件为本机
-- stock 的零改动副本，位于 shaders/anime4k/；字节哈希审计由 Python 资源清单承担）
local ANIME4K_CHAINS = {
    a = { "Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_AutoDownscalePre_x2.glsl",
          "Anime4K_AutoDownscalePre_x4.glsl", "Anime4K_Upscale_CNN_x2_M.glsl" },
    b = { "Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_Soft_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_AutoDownscalePre_x2.glsl",
          "Anime4K_AutoDownscalePre_x4.glsl", "Anime4K_Upscale_CNN_x2_M.glsl" },
    c = { "Anime4K_Clamp_Highlights.glsl", "Anime4K_Upscale_Denoise_CNN_x2_VL.glsl",
          "Anime4K_AutoDownscalePre_x2.glsl", "Anime4K_AutoDownscalePre_x4.glsl",
          "Anime4K_Upscale_CNN_x2_M.glsl" },
    d = { "Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_Restore_CNN_M.glsl",
          "Anime4K_AutoDownscalePre_x2.glsl", "Anime4K_AutoDownscalePre_x4.glsl",
          "Anime4K_Upscale_CNN_x2_M.glsl" },
    e = { "Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_Soft_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_AutoDownscalePre_x2.glsl",
          "Anime4K_AutoDownscalePre_x4.glsl", "Anime4K_Restore_CNN_Soft_M.glsl",
          "Anime4K_Upscale_CNN_x2_M.glsl" },
    f = { "Anime4K_Clamp_Highlights.glsl", "Anime4K_Upscale_Denoise_CNN_x2_VL.glsl",
          "Anime4K_AutoDownscalePre_x2.glsl", "Anime4K_AutoDownscalePre_x4.glsl",
          "Anime4K_Restore_CNN_M.glsl", "Anime4K_Upscale_CNN_x2_M.glsl" },
}
local ANIME4K_MODE_LABELS = {
    a = "Mode A (HQ)", b = "Mode B (HQ)", c = "Mode C (HQ)",
    d = "Mode A+A (HQ)", e = "Mode B+B (HQ)", f = "Mode C+A (HQ)",
}
-- 链验证关键字（vo-passes //!DESC 匹配）。分两类：
--   required：无条件运行的 stock 文件（Clamp/Restore_*），缺失即视为编译失败；
--   optional：自带 //!WHEN 的 stock 文件（Upscale_*/AutoDownscalePre_*，
--             依窗口区间可能合法跳过，属 stock 设计行为；缺失时如实记录备注，
--             不作为编译失败判定）。
local ANIME4K_MODE_KEYWORDS = {
    a = { required = { "Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-(VL)" },
          optional = { "Anime4K-v3.2-Upscale-CNN-x2-(VL)", "Anime4K-v3.2-Upscale-CNN-x2-(M)" } },
    b = { required = { "Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-Soft-(VL)" },
          optional = { "Anime4K-v3.2-Upscale-CNN-x2-(VL)", "Anime4K-v3.2-Upscale-CNN-x2-(M)" } },
    c = { required = { "Anime4K-v4.0-De-Ring" },
          optional = { "Anime4K-v3.2-Upscale-Denoise-CNN-x2-(VL)", "Anime4K-v3.2-Upscale-CNN-x2-(M)" } },
    d = { required = { "Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-(VL)",
                       "Anime4K-v4.0-Restore-CNN-(M)" },
          optional = { "Anime4K-v3.2-Upscale-CNN-x2-(VL)", "Anime4K-v3.2-Upscale-CNN-x2-(M)" } },
    e = { required = { "Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-Soft-(VL)",
                       "Anime4K-v4.0-Restore-CNN-Soft-(M)" },
          optional = { "Anime4K-v3.2-Upscale-CNN-x2-(VL)", "Anime4K-v3.2-Upscale-CNN-x2-(M)" } },
    f = { required = { "Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-(M)" },
          optional = { "Anime4K-v3.2-Upscale-Denoise-CNN-x2-(VL)", "Anime4K-v3.2-Upscale-CNN-x2-(M)" } },
}

local function valid_anime4k_mode(mode)
    if type(mode) ~= "string" then return nil end
    local m = mode:lower():match("^%s*([a-f])%s*$")
    return m
end

local o_anime4k_mode = valid_anime4k_mode(o.anime4k_chain)
if not o_anime4k_mode then
    msg.warn("anime4k_chain=", tostring(o.anime4k_chain),
             "非法（允许 a..f），回退默认 a（CTRL+1 等效链）")
    o_anime4k_mode = "a"
end

local function anime4k_chain_set(mode)
    local out = {}
    for _, name in ipairs(ANIME4K_CHAINS[mode]) do
        out[#out + 1] = { prop = "glsl-shaders", op = "append",
                          value = "~~/shaders/anime4k/" .. name }
    end
    return out
end

local BUILTIN_GEARS = {
    { id = "fsr1", label = "FSR1", luma = true, whole = true,
      reason = "AMD FidelityFX FSR v1.0.2（EASU+RCAS，MIT；每轴≤2×，超出由 mpv 接管）",
      chain = { { prop = "glsl-shaders", op = "append", value = "~~/shaders/p2-FSR1.glsl" } },
      keywords = { "FidelityFX Super Resolution v1.0.2 (EASU)",
                   "FidelityFX Super Resolution v1.0.2 (RCAS)" },
      when_ratio = true },
    { id = "sgsr1", label = "SGSR1", luma = true, whole = true,
      reason = "Qualcomm SGSR1（LUMA 适配版，BSD-3，单 pass）",
      chain = { { prop = "glsl-shaders", op = "append", value = "~~/shaders/p2-SGSR1.glsl" } },
      keywords = { "Snapdragon Game Super Resolution" },
      when_ratio = true },
    { id = "anime4k", label = "Anime4K（stock v4）", luma = true, whole = true,
      reason = "stock Anime4K v4 " .. ANIME4K_MODE_LABELS[o_anime4k_mode]
               .. "（CTRL+" .. ({a=1,b=2,c=3,d=4,e=5,f=6})[o_anime4k_mode] .. " 等效链，零改动副本）",
      chain = anime4k_chain_set(o_anime4k_mode),
      keywords = ANIME4K_MODE_KEYWORDS[o_anime4k_mode].required,
      optional_keywords = ANIME4K_MODE_KEYWORDS[o_anime4k_mode].optional,
      when_ratio = false },
    { id = "nearest", label = "Nearest Neighbor", luma = false, whole = true,
      reason = "scale/cscale/dscale 全 nearest（显式点采样，无 shader 链）",
      chain = {},
      props = { { prop = "scale", op = "set", value = "nearest" },
                { prop = "cscale", op = "set", value = "nearest" },
                { prop = "dscale", op = "set", value = "nearest" } },
      keywords = {},
      when_ratio = false },
    -- P3 新增五个内建档位（P3A-01 唯一目标态：身份/链全部内建固定，
    -- conf 任何 _mode/_set/_label/_reason 覆盖无效并告警）。
    { id = "nis", label = "NIS", luma = true, whole = true,
      reason = "NVIDIA Image Scaling v1.0.2（compute 32×24×256+系数纹理，MIT，"
               .. "内含锐化；仅放大生效，非放大时按 WHEN 诚实跳过）",
      chain = { { prop = "glsl-shaders", op = "append", value = "~~/shaders/p3-NIS.glsl" } },
      keywords = { "NVIDIA Image Scaling and Sharpening v1.0.2" },
      when_ratio = true },
    { id = "xbr", label = "xBR", luma = false, hdr = true, whole = true,
      reason = "Hyllian xBR-lv2（MIT 参考移植，MAIN RGB；参考 3× 预缩放+mpv"
               .. "后续缩放模式；xBR≠xBRZ）",
      chain = { { prop = "glsl-shaders", op = "append", value = "~~/shaders/p3-xBR-lv2.glsl" } },
      keywords = { "xBR-lv2 Hyllian reference (3x prescale)" },
      when_ratio = false },
    { id = "sharpbilinear", label = "Sharp Bilinear（AUTO）", luma = false, hdr = true, whole = true,
      reason = "Sharp Bilinear AUTO（floor(输出高/输入高+0.01)；1080→1440 得 1"
               .. "即明示退化为双线性；不足 1× 钳制为 1 防除零）",
      chain = { { prop = "glsl-shaders", op = "append", value = "~~/shaders/p3-Sharp-Bilinear-AUTO.glsl" } },
      keywords = { "Sharp Bilinear (AUTO)" },
      when_ratio = false },
    { id = "sharpbilinear2x", label = "Sharp Bilinear（手动 2×）", luma = false, hdr = true, whole = true,
      reason = "Sharp Bilinear 手动 2×（同源参考固定预缩放 2×；与 AUTO 分别命名；"
               .. "参考坐标采样语义，非两 pass 串联）",
      chain = { { prop = "glsl-shaders", op = "append", value = "~~/shaders/p3-Sharp-Bilinear-2x.glsl" } },
      keywords = { "Sharp Bilinear (manual 2x)" },
      when_ratio = false },
    { id = "integer", label = "Integer（整数倍）", luma = false, whole = true,
      integer = true,
      reason = "整数倍缩放（video-unscaled + zoom=log2 k + 三核 nearest；k 取自"
               .. "原窗口像素与有效显示尺寸；黑边明示；k<1 正常缩小不裁切）",
      chain = {},
      -- integer-geom：占位标记，仅用于把 video-unscaled/video-zoom 纳入托管
      -- 快照/所有权账本；真正的写入值在每次激活/几何变化时按 k 动态计算，
      -- 本条目永远不会原样进入写入计划（activate_gear 会替换）。
      props = { { prop = "scale", op = "set", value = "nearest" },
                { prop = "cscale", op = "set", value = "nearest" },
                { prop = "dscale", op = "set", value = "nearest" },
                { prop = "video-unscaled", op = "integer-geom" },
                { prop = "video-zoom", op = "integer-geom" } },
      keywords = {},
      when_ratio = false },
}
local BUILTIN_BY_ID = {}
local RESERVED_GEARS = {}   -- 占位档位固定身份
local RESERVED_NAMES = {}   -- casefold(保留 id/label/off/关)，防自定义档位冒名
do
    RESERVED_NAMES["off"] = true
    RESERVED_NAMES[OFF_LABEL] = true
    for _, g in ipairs(PLACEHOLDER_GEARS) do
        RESERVED_GEARS[g.id] = { label = g.label, reason = g.reason }
        RESERVED_NAMES[g.id] = true
        RESERVED_NAMES[g.label:lower()] = true
    end
    for _, g in ipairs(BUILTIN_GEARS) do
        BUILTIN_BY_ID[g.id] = g
        RESERVED_NAMES[g.id] = true
        RESERVED_NAMES[g.label:lower()] = true
    end
end

------------------------------------------------------------------
-- 纯函数（可被 selftest 直接测试；不触碰 mpv 状态）
------------------------------------------------------------------

local function values_equal(a, b)
    if type(a) == "table" and type(b) == "table" then
        if #a ~= #b then return false end
        for i = 1, #a do
            if a[i] ~= b[i] then return false end
        end
        return true
    end
    return a == b
end

-- mpv 会把数值属性规范化为 number（如 "0.25"→0.25），把 yes/no 选择项
-- 规范化为 boolean（如 video-unscaled 写入 "yes" 后读回 true）。CORE-R1 限域
-- 修正：这类「同一 property 语义值」的规范化比较只对该 property 类型成立，
-- 不再作为全局宽松比较进入所有托管属性（旧全局宽松比较会让任意属性的
-- true 等于 "yes"，污染通用语义）。values_equal_tol 保留为底层规范化原语
-- （数值读回 + yes/no↔boolean），实际状态路径统一走按 property 语义的
-- values_equal_prop（激活读回/last_written/off/transfer/observer 一致）。
local function values_equal_tol(a, b)
    if a == true and b == "yes" then return true end
    if a == false and b == "no" then return true end
    if a == "yes" and b == true then return true end
    if a == "no" and b == false then return true end
    if type(a) == "number" and type(b) == "string" then
        local nb = tonumber(b)
        return nb ~= nil and math.abs(a - nb) < 1e-9
    end
    if type(b) == "number" and type(a) == "string" then
        return values_equal_tol(b, a)
    end
    if type(a) == "number" and type(b) == "number" then
        return math.abs(a - b) < 1e-9
    end
    return values_equal(a, b)
end

-- yes/no 选项型 property（mpv 选项类型 choice yes/no：native 写 "yes"/"no"，
-- 读回 boolean true/false——同一语义值的两种表示）。CORE-R1 实证根因：
-- Integer 档写 video-unscaled="yes"，native 读回 true，通用严格比较判不一致
-- 导致激活误失败。仅此表内属性启用该规范化，其余属性不借用。
local YES_NO_OPTION_PROPS = {
    ["video-unscaled"] = true,
}

-- 按 property 语义的统一比较（激活读回/last_written/off/transfer/observer/读回）。
--   * yes/no 选项型属性：bool ↔ "yes"/"no" 按该 property 语义相等；
--   * 其余属性：一旦有 boolean 参与一律严格类型相等（true 不等于 "yes"、
--     true 不等于 1——通用 True!=1 仍严格，旧 P2 scalars（scale/cscale/dscale
--     等字符串档）不受影响）；
--   * 数值读回规范化（number↔数字串）保留（mpv 对数值属性的既定规范化）。
local function values_equal_prop(prop, a, b)
    if YES_NO_OPTION_PROPS[prop] then
        return values_equal_tol(a, b)
    end
    if type(a) == "boolean" or type(b) == "boolean" then
        return values_equal(a, b)
    end
    return values_equal_tol(a, b)
end

local function list_contains(list, value)
    for _, v in ipairs(list) do
        if v == value then return true end
    end
    return false
end

local function shallow_copy(list)
    local out = {}
    for _, v in ipairs(list or {}) do out[#out + 1] = v end
    return out
end

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- gear id [a-z0-9-]+；script-opts 键名中 "-" 写作 "_"
local function gear_id_to_key_prefix(id)
    return (id:gsub("%-", "_"))
end

-- RGB/HDR 守卫纯函数（与 p2_lib.py 的 oracle 镜像；单测两路对齐）
local function is_rgb_pixfmt(fmt)
    if type(fmt) ~= "string" then return false end
    local p = fmt:lower()
    return p:find("rgb", 1, true) ~= nil or p:find("bgr", 1, true) ~= nil
        or p:find("gbr", 1, true) ~= nil or p == "pal8"
end

local function is_hdr_gamma(gamma)
    return gamma == "pq" or gamma == "hlg"
end

-- LUMA 档守卫：返回拒绝原因或 nil（非 LUMA 档 / vo 未知不阻断）
local function luma_guard_reason(is_luma, vo)
    if not is_luma or vo == nil then return nil end
    if is_rgb_pixfmt(vo.pixelformat) then
        return "RGB 输入（pixelformat=" .. tostring(vo.pixelformat)
            .. "）：LUMA 档不可用（RGB 源无 LUMA hook，链不会生效）"
    end
    if is_hdr_gamma(vo.gamma) then
        return "HDR 输入（gamma=" .. tostring(vo.gamma)
            .. "）：P2 按计划禁用 LUMA 档（仅守卫不评画质，HDR 画质属 PIC-06）"
    end
    return nil
end

-- 放大倍率：窗口像素相对源尺寸（video-out-params 的 dw/dh 与窗口无关，
-- 仅反映显示宽高比，不能用于 //!WHEN 判断；osd-width/height 才是窗口像素）。
-- 未知返回 nil。
local function upscale_ratio(vo)
    if type(vo) ~= "table" then return nil end
    local w, h = vo.w, vo.h
    local ow, oh = vo.osd_w, vo.osd_h
    if not (w and h and ow and oh) or w <= 0 or h <= 0 then return nil end
    return (ow * oh) / (w * h)
end

-- 单轴放大倍率（FSR 每轴≤2× 钳制说明用）；未知返回 nil
local function axis_scales(vo)
    if type(vo) ~= "table" then return nil end
    local w, h = vo.w, vo.h
    local ow, oh = vo.osd_w, vo.osd_h
    if not (w and h and ow and oh) or w <= 0 or h <= 0 then return nil end
    return ow / w, oh / h
end

-- FSR/SGSR 的 //!WHEN（仅放大时运行）是否满足；nil=未知
local function when_applies(gear, vo)
    if not gear.when_ratio then return true end
    local r = upscale_ratio(vo)
    if r == nil then return nil end
    return r > 1.0
end

-- P3 独立 HDR 守卫（MAIN RGB 档：支持 RGB，HDR 拒用；与 LUMA 守卫分开，
-- 互不借用）
local function hdr_guard_reason(needs_hdr_guard, vo)
    if not needs_hdr_guard or vo == nil then return nil end
    if is_hdr_gamma(vo.gamma) then
        return "HDR 输入（gamma=" .. tostring(vo.gamma)
            .. "）：本档按计划禁用（HDR 守卫独立于 LUMA 守卫；不评 HDR 画质）"
    end
    return nil
end

-- 激活侧/运行侧统一守卫入口：LUMA 档走 luma_guard_reason，MAIN HDR 档走
-- hdr_guard_reason；nearest/integer（纯缩放档）无守卫。
local function activation_guard_reason(gear, vo)
    if gear == nil or vo == nil then return nil end
    if gear.luma then
        return luma_guard_reason(true, vo)
    end
    if gear.hdr then
        return hdr_guard_reason(true, vo)
    end
    return nil
end

-- Integer 几何纯函数（与 p3_lib.integer_k 镜像；单测两路对齐）：
-- k = floor(min(原窗口像素/有效显示尺寸))；dw/dh 已含旋转/crop/SAR；
-- 窗口来源是 osd-width/height（原窗口像素），绝不从自身缩小后的 margin 推导。
local function integer_k(vo)
    if type(vo) ~= "table" then return nil end
    local dw, dh = vo.dw, vo.dh
    local ww, wh = vo.osd_w, vo.osd_h
    if not (dw and dh and ww and wh) then return nil end
    if dw <= 0 or dh <= 0 or ww <= 0 or wh <= 0 then return nil end
    return math.floor(math.min(ww / dw, wh / dh))
end

-- Sharp Bilinear AUTO 纯函数镜像（p3_lib.sharp_auto_scale）：
-- scale = floor(输出高/输入高 + 0.01)，不足 1×（含 0）钳制为 1（防除零；
-- 1 即纯双线性退化）。
local function sharp_auto_scale(vo)
    if type(vo) ~= "table" then return nil end
    local oh, ih = vo.osd_h, vo.h
    if not (oh and ih) or ih <= 0 or oh <= 0 then return nil end
    return math.max(1, math.floor(oh / ih + 0.01))
end

-- 诚实跳过/钳制说明（空串=当前几何下链应完整生效）
local function chain_skip_note(gear, vo)
    if gear.when_ratio then
        local r = upscale_ratio(vo)
        if r ~= nil and r <= 1.0 then
            return "非放大（≤1×）：" .. gear.label .. " 的 LUMA hook 按 //!WHEN 跳过，"
                .. "本链当前无实际 pass，缩放由 mpv scaler 完成"
        end
        if gear.id == "fsr1" and r ~= nil then
            local sx, sy = axis_scales(vo)
            if (sx and sx > 2.0) or (sy and sy > 2.0) then
                return "单轴放大 >2×：" .. gear.label .. " 按每轴≤2× 钳制运行，超出部分由 mpv scaler 接管"
            end
        end
        if gear.id == "nis" and r ~= nil then
            local sx, sy = axis_scales(vo)
            if (sx and sx > 4.0) or (sy and sy > 4.0) then
                return "单轴放大 >4×：" .. gear.label
                    .. " 参考实现按常规质量区间设计，超出部分由 mpv scaler 接管（诚实说明，非性能宣称）"
            end
        end
    end
    if gear.id == "sharpbilinear" and vo ~= nil then
        local sc = sharp_auto_scale(vo)
        if sc == 1 then
            return "AUTO 在当前窗口退化为双线性（floor(输出高/输入高+0.01)=1，"
                .. "参考公式原样保留）"
        end
    end
    if gear.id == "integer" and vo ~= nil then
        local k = integer_k(vo)
        if k == 0 then
            return "k<1（窗口小于有效显示尺寸）：整数倍放大不可用，已按普通 nearest "
                .. "缩小显示（不裁切、不假整数）"
        end
        if k == 1 then
            return "k=1：1× 显示（黑边按窗口比例明示；如 1080p→2560×1440 全屏时 "
                .. "左右各 320px/上下各 180px）"
        end
    end
    return ""
end

-- cscale 基线哨兵恢复：cscale 未设置时值为 0（表示"跟随 --scale"，
-- mpv 拒绝写回 0）；恢复时改写为基线 scale 的实际值（等效于 unset 语义）。
-- 返回规范化后的值与说明（无修正时说明为 nil）。
local function normalize_restorable(prop, value, baseline)
    if prop == "cscale" and (value == nil or value == UNAVAIL or value == 0 or value == "0") then
        local sc = baseline and baseline["scale"]
        if type(sc) == "string" and sc ~= "" then
            return sc, "cscale: 基线为未设置（跟随 scale），已按 scale 基线值恢复为 " .. sc
        end
        return "bilinear", "cscale: 基线为未设置，已恢复为 bilinear"
    end
    return value, nil
end

-- 解析档位表文本（script-opts/scale-selector-gears.conf）。
-- 返回 { order={id...}, by_id={id=gear}, warnings={...} }
-- gear = { id, label, mode, reason, broken, set={{prop,op,value}...},
--          luma=bool, keywords={...}, when_ratio=bool }
-- V4-FALLBACK（brief-v4 根因 1）：内建默认档位表唯一来源 = 完整 12 档注册表
-- （与发布 script-opts/scale-selector-gears.conf 的 gears= 行逐项一致）。
-- 此前 parse_gears_conf 的缺失/空两条回退路径各写死 11 项（漏 sharpbilinear2x），
-- 与发布 12 档 conf 计数不一致导致 CTL-06-a FAIL；现统一从本表回退，
-- off 恒在首项且可用、LS1/BCAS 保持占位 disabled、内建链/身份固定均不变。
local DEFAULT_GEARS_IDS = { OFF_ID, "ls1", "fsr1", "nis", "sgsr1", "bcas",
                            "anime4k", "xbr", "sharpbilinear",
                            "sharpbilinear2x", "integer", "nearest" }

local function parse_gears_conf(text)
    local result = { order = {}, by_id = {}, warnings = {} }
    local warn = function(s) result.warnings[#result.warnings + 1] = s end

    local kv = {}           -- key -> value
    for line in (text or ""):gmatch("([^\r\n]*)\r?\n?") do
        local l = trim(line)
        if l ~= "" and not l:match("^#") then
            local key, value = l:match("^([^=]+)=(.*)$")
            if key then
                key = trim(key)
                if kv[key] ~= nil then
                    -- 与告警文字一致：保留首个值，忽略后续重复键（限域修正 A）
                    warn("重复键被忽略: " .. key)
                else
                    kv[key] = trim(value)
                end
            else
                warn("无法解析的行（缺少 =）: " .. l:sub(1, 60))
            end
        end
    end

    local gears_raw = kv["gears"]
    if not gears_raw or gears_raw == "" then
        warn("缺少 gears= 列表，回退内建默认档位表")
        gears_raw = table.concat(DEFAULT_GEARS_IDS, ",")
    end

    local ids = {}
    local seen_ids = {}
    for token in gears_raw:gmatch("[^,]+") do
        local id = trim(token)
        if id:match("^[a-z0-9%-]+$") then
            if seen_ids[id] then
                -- 重复 id 只产生一个菜单条目（限域修正 A 邻近情况）
                warn("重复档位 id 已合并（不产生重复条目）: " .. id)
            else
                seen_ids[id] = true
                ids[#ids + 1] = id
            end
        else
            warn("非法档位 id（仅允许小写字母/数字/连字符）: " .. id)
        end
    end
    if #ids == 0 then
        warn("gears 列表为空，回退内建默认档位表")
        ids = {}
        for _, def_id in ipairs(DEFAULT_GEARS_IDS) do ids[#ids + 1] = def_id end
    end
    -- off 不变式：始终存在、在首项、可用（限域修正 A）
    local off_index = nil
    for i, id in ipairs(ids) do
        if id == OFF_ID then off_index = i end
    end
    if not off_index then
        warn("gears 缺少 off：已自动补在首位（off 始终存在、在首项且可用）")
        table.insert(ids, 1, OFF_ID)
    elseif off_index > 1 then
        table.remove(ids, off_index)
        table.insert(ids, 1, OFF_ID)
        warn("off 不在首位：已移到首位（off 始终在首项）")
    end

    for _, id in ipairs(ids) do
        local prefix = gear_id_to_key_prefix(id)
        local reserved = RESERVED_GEARS[id]
        local builtin = BUILTIN_BY_ID[id]
        local raw_label = kv[prefix .. "_label"]
        local raw_mode = kv[prefix .. "_mode"]
        local raw_reason = kv[prefix .. "_reason"]
        local raw_set = kv[prefix .. "_set"]
        local gear = { id = id, label = id, mode = "disabled", reason = "", broken = false, set = {} }
        if id == OFF_ID then
            -- off 不变式：可用性由插件强制；显示名固定为 OFF_LABEL（V2-01 修复，
            -- conf 的 off_label 不能借保留算法名冒名"关"）
            if raw_label and raw_label ~= OFF_LABEL then
                warn("off_label=" .. tostring(raw_label) .. " 被忽略：off 显示名固定为「" .. OFF_LABEL .. "」（防冒名）")
            end
            gear.label = OFF_LABEL
            gear.reason = ""
            gear.mode = "active"
            if raw_mode and raw_mode ~= "active" then
                warn("off_mode=" .. tostring(raw_mode) .. " 被忽略：off 始终存在且可用，不能被配置禁用")
            end
        elseif builtin then
            -- P2 内建真实档位：mode/链/标签/原因全部内建固定，conf 覆盖一律无效
            --（防冒名/防换链；链的字节哈希审计在 Python 资源清单侧）。
            -- whole = 注册整主链语义（整 property 替换，见头部说明）
            gear.label = builtin.label
            gear.reason = builtin.reason
            gear.mode = "active"
            gear.luma = builtin.luma
            gear.hdr = builtin.hdr and true or false
            gear.integer = builtin.integer and true or false
            gear.whole = builtin.whole and true or false
            gear.keywords = builtin.keywords
            gear.when_ratio = builtin.when_ratio
            gear.set = {}
            for _, e in ipairs(builtin.chain or {}) do
                gear.set[#gear.set + 1] = e
            end
            for _, e in ipairs(builtin.props or {}) do
                gear.set[#gear.set + 1] = e
            end
            local overrides = {}
            if raw_label then overrides[#overrides + 1] = prefix .. "_label" end
            if raw_reason then overrides[#overrides + 1] = prefix .. "_reason" end
            if raw_mode and raw_mode ~= "active" then overrides[#overrides + 1] = prefix .. "_mode=" .. tostring(raw_mode) end
            if raw_set and raw_set ~= "" then overrides[#overrides + 1] = prefix .. "_set" end
            if #overrides > 0 then
                warn("内建档位 " .. id .. " 的 conf 覆盖被忽略（" .. table.concat(overrides, ", ")
                    .. "）：链与身份内建固定，防冒名/防换链")
            end
        elseif reserved then
            -- 占位档位（无真实实现）：身份固定、强制 disabled；
            -- _mode/_set/_label/_reason 的任何覆盖一律无效（防冒名）
            gear.label = reserved.label
            gear.reason = reserved.reason
            if raw_label or raw_reason then
                warn("保留档位 " .. id .. " 的 _label/_reason 覆盖被忽略（使用内建固定标签/原因，防冒名）")
            end
            if raw_mode and raw_mode ~= "disabled" then
                warn("保留档位 " .. id .. " 强制 disabled（未实现，忽略 _mode=" .. tostring(raw_mode) .. "）")
                gear.broken = true
            end
            if raw_set and raw_set ~= "" then
                warn("保留档位 " .. id .. " 不接受 _set（无真实实现，防止以保留标签挂任意链冒名）")
                gear.broken = true
            end
        else
            gear.label = raw_label or id
            gear.reason = raw_reason or ""
            if raw_label and RESERVED_NAMES[raw_label:lower()] then
                warn("档位 " .. id .. " 的 label「" .. raw_label .. "」与保留算法名冲突，已禁用（不允许冒名）")
                gear.broken = true
                gear.label = id
            elseif raw_mode then
                gear.mode = raw_mode
            else
                -- 缺省不再等同 active（限域修正 A/R1）：显式声明才可用
                warn("档位 " .. id .. " 缺少 _mode：默认 disabled（如需启用请显式 _mode=active）")
            end
        end
        if gear.mode ~= "active" and gear.mode ~= "disabled" then
            warn("档位 " .. id .. " 的 mode 非法: " .. tostring(gear.mode) .. "，按 disabled 处理")
            gear.mode = "disabled"
            gear.broken = true
        end
        -- 自定义档位的 _set 解析（off/保留/内建档位不解析 _set）
        if id ~= OFF_ID and not reserved and not builtin then
            if raw_set and raw_set ~= "" then
                for entry in raw_set:gmatch("[^;]+") do
                    local prop, op, value
                    local p1, v1 = entry:match("^(.-)%+%=(.+)$")
                    local p2, v2 = entry:match("^(.-)%-%=(.+)$")
                    local p3, v3 = entry:match("^(.-)%=(.+)$")
                    if p1 then
                        prop, op, value = trim(p1), "append", trim(v1)
                    elseif p2 then
                        prop, op, value = trim(p2), "remove", trim(v2)
                    elseif p3 then
                        prop, op, value = trim(p3), "set", trim(v3)
                    end
                    if not prop or prop == "" then
                        warn("档位 " .. id .. " 的 set 条目无法解析: " .. entry:sub(1, 60))
                        gear.broken = true
                    elseif op == "set" and value == "" then
                        warn("档位 " .. id .. " 的 set 条目缺少值: " .. entry:sub(1, 60))
                        gear.broken = true
                    else
                        gear.set[#gear.set + 1] = { prop = prop, op = op, value = value }
                    end
                end
            end
        end
        result.order[#result.order + 1] = id
        result.by_id[id] = gear
    end

    -- 收集所有键，报告未匹配任何档位的键（如拼写错误）
    local suffixes = { "_label", "_mode", "_reason", "_set" }
    for key, _ in pairs(kv) do
        if key ~= "gears" then
            local matched = false
            for _, id in ipairs(ids) do
                local prefix = gear_id_to_key_prefix(id)
                for _, suffix in ipairs(suffixes) do
                    if key == prefix .. suffix then matched = true end
                end
            end
            if not matched then
                warn("未匹配任何档位的配置键（被忽略）: " .. key)
            end
        end
    end

    return result
end

-- 菜单条目模型：{ id, label, enabled, reason }
local function build_entries(model)
    local entries = {}
    for _, id in ipairs(model.order) do
        local gear = model.by_id[id]
        if gear then
            entries[#entries + 1] = {
                id = id,
                label = gear.label,
                enabled = (gear.mode == "active") and (not gear.broken),
                reason = gear.broken and ("配置错误（见日志）" .. (gear.reason ~= "" and "；" .. gear.reason or ""))
                         or gear.reason or "",
            }
        end
    end
    return entries
end

-- 运行时可用性（P2）：在静态条目上叠加 RGB/HDR 守卫与视频存在性。
-- vo=nil（无视频）时不阻断任何档位（激活后按实际状态显示）。
local function apply_runtime_availability(entries, model, vo)
    for _, e in ipairs(entries) do
        local gear = model.by_id[e.id]
        if e.enabled and gear and (gear.luma or gear.hdr) then
            local reason = activation_guard_reason(gear, vo)
            if reason then
                e.enabled = false
                e.reason = reason
                e.guard_blocked = true
            end
        end
    end
    return entries
end

-- 从 index 开始按 dir（1/-1）找下一个可选条目；找不到返回 nil
local function next_enabled(entries, index, dir)
    local i = index
    while true do
        i = i + dir
        if i < 1 or i > #entries then return nil end
        if entries[i].enabled then return i end
    end
end

-- 计算激活某档位需要写入的属性序列。
--   gear           档位对象（gear.whole = 注册整主链语义）
--   current_list   当前 glsl-shaders 列表
--   owned_shaders  插件此前添加的 shader
--   last / baseline / wrote  所有权表（见状态机）
-- 返回 writes={{prop,value}...}, new_list, adds, removes, err
-- 规则（brief 纠正）：一次仅一主链。
--   * whole（P2 注册档位）：写入的新列表 = 恰为该档登记 recipe（整 property
--     替换；首次接管含已有 Anime4K/用户链也一样——原链已在接管时快照进
--     baseline，由"关"恢复），不 append 到既有链；Nearest recipe = 空列表。
--   * compat（p1-test-* 桩，历史元素级语义，明确兼容模式）：元素级移除旧
--     owned + 追加新链，保留非自有条目。
--   * 上一档写过的非 glsl 属性归还基线（仅限仍归插件所有者）；绝不使用 clr。
local function plan_gear_writes(gear, current_list, owned_shaders, last, baseline, wrote)
    if gear.id == OFF_ID then
        return nil, nil, nil, nil, "off 档位走内建恢复语义，不走 plan_gear_writes"
    end
    local target = {}
    local adds, removes = {}, {}
    for _, e in ipairs(gear.set or {}) do
        if e.prop == "glsl-shaders" then
            if e.op == "append" then
                adds[#adds + 1] = e.value
            elseif e.op == "remove" then
                removes[#removes + 1] = e.value
            else
                return nil, nil, nil, nil, "禁止对 glsl-shaders 直接赋值（请用 +=/-=）"
            end
        else
            if e.op == "integer-geom" then
                return nil, nil, nil, nil,
                    "integer 几何写入值必须在激活时按 k 计算（不得使用占位条目）"
            end
            if e.op ~= "set" then
                return nil, nil, nil, nil, "仅 glsl-shaders 支持 +=/-=（" .. e.prop .. "）"
            end
            target[e.prop] = e.value
        end
    end

    local writes = {}
    -- 归还上一档写过、且本档不再设置的属性（恢复到基线；外部改动
    -- 在进入本函数前已由 external 状态拦截，不会走到这里）。
    -- cscale 基线哨兵（0=未设置）按"跟随 scale"规范化（mpv 拒绝写回 0）。
    for prop, _ in pairs(wrote) do
        if prop ~= "glsl-shaders" and target[prop] == nil then
            local nv = normalize_restorable(prop, baseline[prop], baseline)
            writes[#writes + 1] = { prop, nv }
        end
    end
    for prop, v in pairs(target) do
        writes[#writes + 1] = { prop, v }
    end

    local new_list = {}
    if gear.whole then
        -- 注册整主链：写入列表恰为新 recipe（整 property 替换，不保留/不叠加
        -- 当前列表内容；用户原链由 baseline 快照承载，"关"时恢复）
        for _, s in ipairs(adds) do
            new_list[#new_list + 1] = s
        end
    else
        -- 兼容模式（p1-test-* 桩的历史元素级语义）：仅移除自有条目
        for _, s in ipairs(current_list) do
            if not list_contains(owned_shaders, s) and not list_contains(removes, s) then
                new_list[#new_list + 1] = s
            end
        end
        for _, s in ipairs(adds) do
            new_list[#new_list + 1] = s
        end
    end
    writes[#writes + 1] = { "glsl-shaders", new_list }
    return writes, new_list, adds, removes
end

-- 计算"关"的恢复动作（仅恢复插件拥有且未被外部改动的属性）。
--   current: {prop=value}（仅需包含 wrote 中的属性）
--   whole_chain: 本次接管的主链是否为 P2 注册整主链（brief 纠正语义）
-- glsl-shaders：
--   仍等于 last_written（仍 owned）→ 精确恢复基线完整列表；
--   被外部改动 + whole_chain → 保留用户完整外部列表（不凭路径字符串删除
--     用户重新添加的同名条目）；
--   被外部改动 + 兼容模式（p1-test-* 桩历史语义）→ 按元素级移除插件添加项、
--     保留外部条目。
-- 绝不输出"清空列表"语义。
local function compute_off_actions(baseline, last, wrote, owned_shaders, current, whole_chain)
    local restores, kept, notes = {}, {}, {}
    for prop, was_written in pairs(wrote) do
        if was_written then
            local cur = current[prop]
            if prop == "glsl-shaders" then
                local cur_list = type(cur) == "table" and cur or {}
                -- 按 property 语义比较（video-unscaled 等 yes/no 选项 bool↔yes/no）
                if values_equal_prop(prop, cur_list, last[prop]) then
                    restores[#restores + 1] = { "glsl-shaders", baseline[prop] or {} }
                elseif whole_chain then
                    -- 外部改动后保留用户完整列表（整链所有权）
                    restores[#restores + 1] = { "glsl-shaders", cur_list }
                    kept[#kept + 1] = prop
                    notes[#notes + 1] = "glsl-shaders：外部改动后保留用户完整列表"
                        .. "（整链所有权，不按路径字符串删除条目）"
                else
                    local new_list = {}
                    for _, s in ipairs(cur_list) do
                        if not list_contains(owned_shaders, s) then
                            new_list[#new_list + 1] = s
                        end
                    end
                    restores[#restores + 1] = { "glsl-shaders", new_list }
                    kept[#kept + 1] = prop
                    notes[#notes + 1] = "glsl-shaders：外部改动保留（兼容模式元素级移除插件添加项）"
                end
            else
                if values_equal_prop(prop, cur, last[prop]) then
                    restores[#restores + 1] = { prop, baseline[prop] }
                else
                    kept[#kept + 1] = prop
                end
            end
        end
    end
    return restores, kept, notes
end

------------------------------------------------------------------
-- 内建默认档位表（gears 文件缺失/为空时使用，与随附 conf 内容一致）
------------------------------------------------------------------

-- P3 唯一目标态（P3A-01）：真实内建档位（fsr1/sgsr1/anime4k/nearest +
-- nis/xbr/sharpbilinear/sharpbilinear2x/integer）在本表中只保留 gears= 成员
-- 与 # 解释注释，不写任何 _mode/_set/_label/_reason 覆盖键（转内建后这些键
-- 一律无效并告警）；仅仍占位的 ls1/bcas 保留其 disabled 条目。
local DEFAULT_GEARS_TEXT = [[
# scale-selector 内建默认档位表（P3；与随附 conf 唯一目标态一致）
gears=off,ls1,fsr1,nis,sgsr1,bcas,anime4k,xbr,sharpbilinear,sharpbilinear2x,integer,nearest
off_label=关
ls1_label=LS1
ls1_mode=disabled
ls1_reason=无公开源码/权重/移植许可，无法原样内置；不以替代算法冒名
bcas_label=BCAS
bcas_mode=disabled
bcas_reason=算法定义身份未核实；不以CAS/Bicubic+CAS冒名
# 以下九档为真实内建：身份/链定义全部内建于脚本（防冒名/防换链），对本文件
# 写它们的 _mode/_set/_label/_reason 无效并告警：
#   fsr1/sgsr1/anime4k/nearest —— P2 档位（语义不变）
#   nis —— NVIDIA Image Scaling v1.0.2（compute，MIT，内含锐化；仅放大生效）
#   xbr —— Hyllian xBR-lv2（MIT 参考；3× 预缩放+mpv 后续缩放；xBR≠xBRZ）
#   sharpbilinear —— Sharp Bilinear AUTO（floor(输出高/输入高+0.01)；退化/防除零明示）
#   sharpbilinear2x —— Sharp Bilinear 手动 2×（与 AUTO 分别命名）
#   integer —— 整数倍缩放（原窗口像素+video-out-params 防反馈几何；k<1 正常缩小）
]]

------------------------------------------------------------------
-- 运行时状态机
------------------------------------------------------------------

local S = {
    state = "off",            -- off | active | external | fallback
    stable = "off",           -- 上一稳定档位 id
    active = nil,             -- 当前生效档位 id（active 时 = stable）
    reason = "",              -- fallback 原因 / external 提示
    baseline = {},            -- prop -> 接管时快照
    last = {},                -- prop -> 插件最后写入值（仅 wrote 的属性）
    wrote = {},               -- prop -> true（插件本会话写过）
    owned = {},               -- 插件添加的 shader 列表（整主链）
    takeover = false,
    off_report = nil,
    shutting = false,
    menu_open = false,
    cursor = 1,
    entries = {},
    journal = {},             -- 属性读取审计（GEO-01）
    model = nil,
    -- P2：链验证与诚实显示
    chain_epoch = 0,          -- 主链/环境变化代数（激活/回退/视频参数变化时递增）
    chain_verified = nil,     -- true | false(验证失败) | "skipped-when" | "no-video" | nil(验证中/未知)
    chain_keywords = {},      -- 当前档位的 vo-passes //!DESC 必备关键字
    optional_missing = {},    -- //!WHEN 门控 pass 的缺失列表（诚实备注，不判失败）
    skip_note = "",           -- ≤1× / >2× 等真实跳过/钳制说明
    vo = nil,                 -- 最近一次 video-out-params 子集（pixelformat/gamma/w/h/dw/dh）
    verify_fails = 0,         -- 验证失败计数（防回退循环）
    anime4k_mode = o_anime4k_mode,
    chain_kind = nil,         -- 本次接管主链类别："whole"（注册整主链）|"compat"（p1-test-* 桩历史语义）
    integer_k = nil,          -- P3：Integer 档当前生效的整数倍数（激活/重算时更新）
}

local overlay = nil
local open_menu, close_menu, activate_gear, do_off
local verify_timer = nil
-- 前置声明（P2 链验证/回退/守卫释放；实现见下方同名赋值）
local verify_chain_tick, rollback_after_verify_failure,
    release_all_to_fallback, release_for_guard, enter_fallback
-- P3 前置声明（Integer 动态几何重算；实现见下方同名赋值）
local integer_reapply_geometry

local function journal_add(name)
    S.journal[#S.journal + 1] = name
    if #S.journal > 512 then
        table.remove(S.journal, 1)
    end
end

-- 所有属性读取统一走这里（审计用；GEO-01 防反馈路径的证据基础）
local function jget(name)
    journal_add(name)
    local ok, value = pcall(mp.get_property_native, name)
    if not ok then return nil end
    return value
end

local function expand_path(p)
    if type(p) ~= "string" then return p end
    local r = mp.command_native({ "expand-path", p })
    return type(r) == "string" and r or p
end

local function managed_props(model)
    local props = {}
    local seen = {}
    for _, p in ipairs(CORE_PROPS) do
        props[#props + 1] = p
        seen[p] = true
    end
    for _, id in ipairs(model.order) do
        local gear = model.by_id[id]
        for _, e in ipairs(gear.set or {}) do
            if not seen[e.prop] then
                -- 插件可能写入的显示几何等属性纳入托管/观察
                props[#props + 1] = e.prop
                seen[e.prop] = true
            end
        end
    end
    return props
end

local function osd_message(text)
    mp.osd_message("缩放选择器: " .. text, 3)
end

local function user_data_set(key, value)
    pcall(mp.set_property_native, "user-data/scale-selector/" .. key, value)
end

-- video-out-params 子集 + 窗口像素（GEO-01：几何/适用性唯一只读来源）
local function read_vo_params()
    local vop = jget("video-out-params")
    if type(vop) ~= "table" then return nil end
    return {
        w = vop.w, h = vop.h, dw = vop.dw, dh = vop.dh,
        pixelformat = vop.pixelformat, gamma = vop.gamma,
        osd_w = jget("osd-width"), osd_h = jget("osd-height"),
    }
end

------------------------------------------------------------------
-- user-data 导出（IPC 客观验证接口）
------------------------------------------------------------------

local function current_menu_entries_export()
    local out = {}
    for i, e in ipairs(S.entries) do
        out[i] = {
            id = e.id, label = e.label, enabled = e.enabled, reason = e.reason,
            selected = (S.menu_open and i == S.cursor),
            guard_blocked = e.guard_blocked or false,
        }
    end
    return out
end

local function sync_user_data()
    user_data_set("stage", "P3")
    user_data_set("state", S.state)
    user_data_set("stable_gear", S.stable or "off")
    user_data_set("gear", S.active or "")
    user_data_set("reason", S.reason or "")
    user_data_set("menu_open", S.menu_open)
    user_data_set("menu_entries", current_menu_entries_export())
    user_data_set("off_report", S.off_report or {})
    user_data_set("chain_epoch", S.chain_epoch)
    user_data_set("chain_verified", S.chain_verified)
    user_data_set("chain_keywords", S.chain_keywords)
    user_data_set("optional_missing", S.optional_missing or {})
    user_data_set("skip_note", S.skip_note)
    user_data_set("vo_params", S.vo)
    user_data_set("anime4k_mode", S.anime4k_mode)
    local active_gear = S.active and S.model and S.model.by_id[S.active] or nil
    user_data_set("gear_luma", active_gear and active_gear.luma or false)
    local chain_files = {}
    if active_gear then
        for _, e in ipairs(active_gear.set or {}) do
            if e.prop == "glsl-shaders" and e.op == "append" then
                chain_files[#chain_files + 1] = e.value
            end
        end
    end
    user_data_set("gear_chain", chain_files)
    local j = {}
    local from = math.max(1, #S.journal - 63)
    for i = from, #S.journal do j[#j + 1] = S.journal[i] end
    user_data_set("read_journal", j)
    local baseline_export, last_export, wrote_export = {}, {}, {}
    for p, v in pairs(S.baseline) do baseline_export[p] = (v == UNAVAIL) and false or v end
    for p, v in pairs(S.last) do last_export[p] = v end
    for p, v in pairs(S.wrote) do wrote_export[p] = v end
    user_data_set("baseline", baseline_export)
    user_data_set("last_written", last_export)
    user_data_set("wrote", wrote_export)
    user_data_set("owned_shaders", S.owned)
    user_data_set("chain_kind", S.chain_kind)
    user_data_set("integer_k", S.integer_k)
end

------------------------------------------------------------------
-- 菜单（ASS overlay）
------------------------------------------------------------------

local function state_header_text()
    if S.state == "off" then
        return "状态: off（未接管）"
    elseif S.state == "active" then
        local g = S.model.by_id[S.active]
        local line = string.format("状态: active（%s）", g and g.label or S.active or "?")
        -- 诚实显示：链验证状态与真实跳过/钳制说明（SHD-08）
        if S.chain_verified == false then
            line = line .. "\\N链验证: 失败（将回退）"
        elseif S.chain_verified == nil and g and g.keywords and #g.keywords > 0 then
            line = line .. "\\N链验证: 进行中…"
        elseif S.chain_verified == "skipped-when" then
            line = line .. "\\N链验证: 本链按 //!WHEN 跳过（未生效）"
        elseif S.chain_verified == "no-video" then
            line = line .. "\\N链验证: 无视频（未验证）"
        end
        if S.skip_note ~= "" then
            line = line .. "\\N" .. S.skip_note
        end
        return line
    elseif S.state == "external" then
        return string.format("状态: external（外部修改已让出；稳定档位: %s）", S.stable or "off")
    elseif S.state == "fallback" then
        return string.format("状态: fallback（%s；已回退到: %s）", S.reason or "?", S.stable or "off")
    end
    return "状态: " .. S.state
end

local function render_menu()
    if not overlay then return end
    local fs = o.menu_font_size
    local parts = {}
    parts[#parts + 1] = string.format("{\\fs%d}{\\b1}缩放选择器 [P3]{\\b0}\\N{\\fs%d}%s\\N\\N",
        fs, math.floor(fs * 0.75), state_header_text())
    for i, e in ipairs(S.entries) do
        local marker = (i == S.cursor) and "▶ " or "　"
        local text
        if e.enabled then
            text = string.format("%s%s", marker, e.label)
        else
            text = string.format("{\\c&H999999&}%s%s〔禁用〕%s{\\c}", marker, e.label, e.reason)
        end
        parts[#parts + 1] = text .. "\\N"
    end
    parts[#parts + 1] = "\\N{\\fs" .. math.floor(fs * 0.66) .. "}{\\c&HBBBBBB&}↑/↓ 选择 · Enter 确认 · Esc/F8 关闭\\N关＝恢复接管前配置（不停止mpv必需的缩放/色彩管理）\\NP3：LUMA 档（FSR1/SGSR1/Anime4K/NIS）RGB/HDR 自动禁用；xBR/Sharp 档支持 RGB、HDR 自动禁用；Integer 黑边明示{\\c}"
    overlay.data = "{\\an7}{\\bord1}{\\shad1}{\\1c&HFFFFFF&}{\\3c&H000000&}" .. table.concat(parts)
    overlay:update()
end

local function refresh_entries()
    S.entries = build_entries(S.model)
    apply_runtime_availability(S.entries, S.model, S.vo)
end

local function refresh_cursor()
    local current = S.entries[S.cursor]
    if current and current.enabled then return end
    S.cursor = next_enabled(S.entries, 0, 1) or 1
end

open_menu = function()
    if S.menu_open then return end
    S.vo = read_vo_params()
    refresh_entries()
    refresh_cursor()
    S.menu_open = true
    overlay = mp.create_osd_overlay("ass-events")
    mp.add_forced_key_binding("UP", "scale-selector-up", function()
        local i = next_enabled(S.entries, S.cursor, -1)
        if i then S.cursor = i; render_menu(); sync_user_data() end
    end, { repeatable = true })
    mp.add_forced_key_binding("DOWN", "scale-selector-down", function()
        local i = next_enabled(S.entries, S.cursor, 1)
        if i then S.cursor = i; render_menu(); sync_user_data() end
    end, { repeatable = true })
    mp.add_forced_key_binding("ENTER", "scale-selector-activate", function()
        local e = S.entries[S.cursor]
        if not e then return end
        if not e.enabled then
            -- 双重保险：光标不应停在禁用项上；到达也绝不激活
            osd_message(e.label .. " 不可用： " .. e.reason)
            return
        end
        if e.id == OFF_ID then
            do_off()
        else
            activate_gear(e.id)
        end
        refresh_entries()
        refresh_cursor()
        render_menu()
        sync_user_data()
    end)
    mp.add_forced_key_binding("ESC", "scale-selector-close", function() close_menu() end)
    render_menu()
    sync_user_data()
    msg.info("menu opened")
end

close_menu = function()
    if not S.menu_open then return end
    S.menu_open = false
    for _, name in ipairs({ "scale-selector-up", "scale-selector-down", "scale-selector-activate", "scale-selector-close" }) do
        pcall(mp.remove_forced_key_binding, name)
    end
    if overlay then
        pcall(function() overlay:remove() end)
        overlay = nil
    end
    sync_user_data()
    msg.info("menu closed")
end

local function toggle_menu()
    if S.menu_open then close_menu() else open_menu() end
end

------------------------------------------------------------------
-- 所有权写入
------------------------------------------------------------------

local function write_owned(prop, value)
    if value == UNAVAIL then
        return false, "快照值不可用，无法写回"
    end
    local ok, err = pcall(mp.set_property_native, prop, value)
    if not ok then
        return false, tostring(err)
    end
    -- last_written 记录 mpv 实际接受的值（可能被类型规范化，如 "0.25"→0.25），
    -- 观察者按值比较即可屏蔽自身写入
    local cur = jget(prop)
    S.last[prop] = (cur == nil) and value or cur
    S.wrote[prop] = true
    return true
end

------------------------------------------------------------------
-- P2 链验证（vo-passes //!DESC 关键字核对；失败回滚，无半生效）
------------------------------------------------------------------

local function chain_desc_map()
    -- 收集 fresh+redraw 的全部 pass 描述（paused 时 fresh 可能冻结，
    -- redraw 仍可更新；两路都计入，陈旧数据不会误判为缺失）
    local descs = {}
    local vp = jget("vo-passes")
    if type(vp) ~= "table" then return descs end
    for _, frame in ipairs({ "fresh", "redraw" }) do
        for _, item in ipairs(vp[frame] or {}) do
            if type(item) == "table" and type(item.desc) == "string" then
                descs[#descs + 1] = item.desc
            end
        end
    end
    return descs
end

local function chain_keywords_missing(gear)
    local descs = chain_desc_map()
    local missing = {}
    for _, kw in ipairs(gear.keywords or {}) do
        local found = false
        for _, d in ipairs(descs) do
            if d:find(kw, 1, true) then found = true break end
        end
        if not found then missing[#missing + 1] = kw end
    end
    return missing
end

-- 可选（//!WHEN 门控）pass 的在场情况；缺失列表用于诚实备注，不触发回退
local function chain_optional_missing(gear)
    local descs = chain_desc_map()
    local missing = {}
    for _, kw in ipairs(gear.optional_keywords or {}) do
        local found = false
        for _, d in ipairs(descs) do
            if d:find(kw, 1, true) then found = true break end
        end
        if not found then missing[#missing + 1] = kw end
    end
    return missing
end

local function clear_verify_timer()
    if verify_timer then
        verify_timer:stop()
        verify_timer = nil
    end
end

local function schedule_verify_tick(delay)
    clear_verify_timer()
    verify_timer = mp.add_timeout(delay or 0.6, verify_chain_tick)
end

-- 激活后轮询 vo-passes：本链的 //!DESC 关键字确实出现→verified；
-- 超时报验证失败并回滚（无半生效/陈旧 pass/循环接管）
verify_chain_tick = function()
    verify_timer = nil
    if not S.takeover or S.state ~= "active" or S.shutting then return end
    local gear = S.model.by_id[S.active]
    if not gear then return end
    if not (gear.keywords and #gear.keywords > 0) then
        -- nearest 等无 shader 链：无 pass 可验证
        S.chain_verified = true
        sync_user_data()
        return
    end
    local vo = read_vo_params()
    S.vo = vo or S.vo
    if vo == nil then
        S.chain_verified = "no-video"
        sync_user_data()
        return
    end
    -- 守卫复核（视频在验证期间切换到 RGB/HDR 的情形）
    local guard = activation_guard_reason(gear, vo)
    if guard then
        release_for_guard(guard)
        return
    end
    local applies = when_applies(gear, vo)
    if applies == false then
        -- ≤1×：链按 //!WHEN 合法跳过；如实显示，绝不报伪 active 生效
        S.chain_verified = "skipped-when"
        S.skip_note = chain_skip_note(gear, vo)
        S.chain_epoch = S.chain_epoch + 1
        sync_user_data()
        return
    end
    local missing = chain_keywords_missing(gear)
    if #missing == 0 then
        S.chain_verified = true
        S.skip_note = chain_skip_note(gear, vo)
        -- stock 链的 //!WHEN 门控 pass（如 AutoDownscalePre/Upscale-M）在特定
        -- 窗口区间合法跳过：缺失时如实备注，不判失败（stock 设计行为）
        local opt_missing = chain_optional_missing(gear)
        S.optional_missing = opt_missing
        if #opt_missing > 0 then
            S.skip_note = (S.skip_note ~= "" and S.skip_note .. "；" or "")
                .. "部分 stock pass 按 //!WHEN 跳过（窗口尺寸区间外，stock 设计行为）："
                .. table.concat(opt_missing, ", ")
        end
        S.chain_epoch = S.chain_epoch + 1
        S.verify_fails = 0
        refresh_entries()
        if S.menu_open then render_menu() end
        sync_user_data()
        return
    end
    S.pending_verify_attempts = (S.pending_verify_attempts or 0) + 1
    if S.pending_verify_attempts >= 8 then
        msg.error("chain verification failed; missing DESC:", table.concat(missing, ", "))
        rollback_after_verify_failure("链验证失败（shader 编译失败或未生效；缺失: " .. missing[1] .. "）")
        return
    end
    schedule_verify_tick(0.6)
end

-- 验证失败回滚：回到上一稳定档（有真实链则重放其写入），无半生效残留
rollback_after_verify_failure = function(reason)
    clear_verify_timer()
    S.verify_fails = S.verify_fails + 1
    local stable_id = S.stable or "off"
    -- 回滚目标与当前档相同（或连续失败）：直接释放回 off，防循环接管
    if S.verify_fails > 2 or stable_id == S.active or stable_id == OFF_ID
        or not S.model.by_id[stable_id] then
        release_all_to_fallback(reason)
        return
    end
    -- 回到上一稳定档：重放其写入（本函数结束后显示 fallback 原因）
    activate_gear(stable_id, { from_rollback = true })
    if S.state == "active" or S.state == "fallback" then
        enter_fallback(S.active or stable_id, reason, false)
    end
end

-- 释放全部托管写入到基线，然后如实 fallback（stable=off）
release_all_to_fallback = function(reason)
    clear_verify_timer()
    -- 先把插件写过的属性恢复到基线（自身写入记账，观察者不会误判外部）；
    -- cscale 基线哨兵按"跟随 scale"规范化
    for prop, was in pairs(S.wrote) do
        if was then
            local nv, note = normalize_restorable(prop, S.baseline[prop], S.baseline)
            if note then msg.warn(note) end
            if nv and nv ~= UNAVAIL then
                local ok = pcall(mp.set_property_native, prop, nv)
                if ok then
                    S.last[prop] = nv
                    journal_add(prop)
                else
                    msg.error("release: restore failed for", prop)
                end
            end
        end
    end
    enter_fallback(S.active or "off", reason, true)
end

-- 播放中守卫触发（RGB/HDR）：释放自有链并如实回退（绝不在 RGB 上留半生效链）
release_for_guard = function(guard_reason)
    clear_verify_timer()
    msg.warn("guard triggered while active:", guard_reason)
    release_all_to_fallback(guard_reason)
end

------------------------------------------------------------------
-- P3：Integer 动态几何（激活时按 k 计算；几何/窗口变化时重算重写）
-- 所有权：video-unscaled/video-zoom 走 write_owned，与其它托管属性同一
-- 账本（last/written），Off/切换照常恢复或转移；窗口来源是原窗口像素
-- （osd-width/height）与 video-out-params 的 dw/dh，绝不从自身缩小后的
-- osd-margin 推导（防黑边反馈，GEO-01/R5）。
------------------------------------------------------------------

-- 由 vo（read_vo_params 结果）生成本次激活的 Integer 写入计划。
-- 返回替换后的 gear 副本（或 nil+原因）。
local function integer_gear_for_activation(gear, vo)
    local k = integer_k(vo)
    S.integer_k = k
    if k == nil then
        return nil, "窗口/显示尺寸未知，无法计算整数倍数（不假整数激活）"
    end
    local g = {}
    for key, v in pairs(gear) do g[key] = v end
    g.set = {}
    for _, e in ipairs(gear.set or {}) do
        if e.op ~= "integer-geom" then g.set[#g.set + 1] = e end
    end
    if k < 1 then
        -- k<1 是正常缩小/明确回退：video-unscaled 恢复 no，nearest 缩小，不裁切
        g.set[#g.set + 1] = { prop = "video-unscaled", op = "set", value = "no" }
        g.set[#g.set + 1] = { prop = "video-zoom", op = "set", value = 0 }
        return g
    end
    g.set[#g.set + 1] = { prop = "video-unscaled", op = "set", value = "yes" }
    g.set[#g.set + 1] = { prop = "video-zoom", op = "set", value = math.log(k, 2) }
    return g
end

-- 运行中几何变化：重算 k；k 变化则重写自有几何属性（防陈旧；外部改动
-- 在进入本函数前已由 external 状态拦截）。
integer_reapply_geometry = function(gear)
    local vo = read_vo_params()
    if vo == nil then return end
    local k = integer_k(vo)
    if k == S.integer_k then
        S.skip_note = chain_skip_note(gear, vo)
        return
    end
    local g, err = integer_gear_for_activation(gear, vo)
    if not g then
        msg.warn("integer recompute failed:", err)
        return
    end
    local want = {}
    for _, e in ipairs(g.set or {}) do
        if e.prop == "video-unscaled" or e.prop == "video-zoom" then
            want[e.prop] = e.value
        end
    end
    local failed = nil
    for prop, value in pairs(want) do
        local cur = jget(prop)
        if not values_equal_prop(prop, cur, value) then
            local ok = write_owned(prop, value)
            if not ok then failed = prop end
        end
    end
    S.skip_note = chain_skip_note(gear, vo)
    if failed then
        msg.warn("integer geometry rewrite failed for", failed)
    end
    S.chain_epoch = S.chain_epoch + 1
    sync_user_data()
end

------------------------------------------------------------------
-- 状态迁移
------------------------------------------------------------------

enter_fallback = function(gear_id, reason, released)
    clear_verify_timer()
    S.state = "fallback"
    S.reason = reason
    S.chain_verified = nil
    S.skip_note = ""
    S.chain_epoch = S.chain_epoch + 1
    if released then
        S.stable = "off"
        S.active = nil
        S.takeover = false
        S.baseline = {}
        S.last = {}
        S.wrote = {}
        S.owned = {}
        S.chain_kind = nil
    end
    msg.warn("fallback at gear", gear_id, ":", reason)
    osd_message(string.format("fallback：%s（已回退到 %s）", reason, S.stable))
    sync_user_data()
end

-- 接管：快照托管基线；期间检测外部竞争，失败则不接管
local function take_snapshot(props)
    local snap = {}
    for _, p in ipairs(props) do
        local v = jget(p)
        snap[p] = (v == nil) and UNAVAIL or v
    end
    for _, p in ipairs(props) do
        local v = jget(p)
        local norm = (v == nil) and UNAVAIL or v
        if not values_equal(norm, snap[p]) then
            msg.warn("takeover race detected on", p)
            return nil
        end
    end
    S.baseline = snap
    S.last = {}
    S.wrote = {}
    S.owned = {}
    S.takeover = true
    msg.info("takeover: baseline snapshot taken for", #props, "properties")
    return snap
end

local function external_changed(prop)
    if not S.takeover or S.shutting then return end
    clear_verify_timer()
    S.state = "external"
    S.reason = "检测到外部修改: " .. prop .. "（插件已让出，不会覆盖）"
    S.chain_verified = nil
    S.skip_note = ""
    msg.info("external change on", prop, "- yielding")
    osd_message("检测到外部修改（" .. prop .. "），已让出")
    sync_user_data()
end

activate_gear = function(gear_id, opts)
    opts = opts or {}
    local gear = S.model.by_id[gear_id]
    if not gear then
        osd_message("未知档位: " .. tostring(gear_id))
        return
    end
    if gear.broken or gear.mode == "disabled" then
        osd_message(gear.label .. " 不可用： " .. (gear.reason ~= "" and gear.reason or "未实现"))
        return
    end
    if S.state == "external" then
        -- 外部改动优先：拒绝直接换档（不静默接管、不追加到外部链）
        osd_message("外部修改中：请先选择〔" .. OFF_LABEL .. "〕处理差异，插件不会静默覆盖")
        return
    end
    if not opts.from_rollback then
        -- RGB/HDR 守卫（激活侧）：LUMA 档在 RGB/HDR 输入、MAIN HDR 档在 HDR
        -- 输入上拒用并显示真实原因
        local vo = read_vo_params()
        local guard = activation_guard_reason(gear, vo)
        if guard then
            osd_message(gear.label .. " 不可用： " .. guard)
            msg.warn("activation refused by guard:", guard)
            sync_user_data()
            return
        end
    end

    local props = managed_props(S.model)
    local first = not S.takeover
    if first then
        if not take_snapshot(props) then
            osd_message("接管失败：接管期间属性被外部修改，请重试")
            return
        end
    end

    if gear.integer then
        local vg, ierr = integer_gear_for_activation(gear, read_vo_params())
        if not vg then
            osd_message(gear.label .. " 不可用： " .. ierr)
            msg.warn("activation refused:", ierr)
            sync_user_data()
            return
        end
        gear = vg
    end
    local cur_list = jget("glsl-shaders")
    if type(cur_list) ~= "table" then cur_list = {} end
    local writes, _new_list, adds, _removes, plan_err =
        plan_gear_writes(gear, cur_list, S.owned, S.last, S.baseline, S.wrote)
    if not writes then
        enter_fallback(gear_id, "档位计划失败: " .. tostring(plan_err), first)
        return
    end

    -- 资源预检（在写入前完成，失败不产生半生效）；
    -- 文案区分"文件缺失"与"路径是目录等非常规文件"（REV-02 同域修复）
    for _, p in ipairs(adds) do
        local expanded = expand_path(p)
        local fi = utils.file_info(expanded)
        if not fi then
            enter_fallback(gear_id, "shader 文件缺失: " .. p, first)
            return
        end
        if fi.is_dir then
            enter_fallback(gear_id, "shader 路径是目录而非常规文件: " .. p, first)
            return
        end
    end

    -- 逐项写入（带回滚；回滚写回值后同步所有权账本，观察者按值比较不会误判）
    local prev_values, prev_last, prev_wrote = {}, {}, {}
    for _, w in ipairs(writes) do
        prev_values[w[1]] = S.wrote[w[1]] and S.last[w[1]] or S.baseline[w[1]]
    end
    for p, v in pairs(S.last) do prev_last[p] = v end
    for p, v in pairs(S.wrote) do prev_wrote[p] = v end
    local prev_owned = shallow_copy(S.owned)
    -- CORE-R1 独立 written 账本：set 实际成功即入账（先于读回校验）。
    -- 初次 set 成功但读回不一致时也必须回滚「所有已成功写入」的 property——
    -- 不能靠读回通过（或已 commit 的 S.wrote 所有权）才记账，否则失败路径会
    -- 把已写入的值留在基线上（实机 fallback 后 video-unscaled 残留 true 的
    -- 真实根因）。
    local written = {}
    local failed = nil
    for _, w in ipairs(writes) do
        local ok, err = write_owned(w[1], w[2])
        if not ok then
            failed = w[1] .. ": " .. tostring(err or "?")
            break
        end
        written[w[1]] = true
        -- 读回校验（mpv 可能静默丢弃/改写非法值；按该 property 的选项类型
        -- 语义比较，如 video-unscaled 写 "yes" 读回 true）
        local cur = jget(w[1])
        if not values_equal_prop(w[1], cur, w[2]) then
            failed = "读回不一致: " .. w[1]
            break
        end
    end
    if failed then
        -- 按 written 账本回滚全部已写（含读回不一致的那一项）
        for p, v in pairs(prev_values) do
            if written[p] and v ~= UNAVAIL then pcall(mp.set_property_native, p, v) end
        end
        S.last = prev_last
        S.wrote = prev_wrote
        S.owned = prev_owned
        enter_fallback(gear_id, failed, first)
        return
    end

    S.owned = adds
    S.chain_kind = gear.whole and "whole" or "compat"
    S.state = "active"
    S.stable = gear_id
    S.active = gear_id
    S.reason = ""
    S.chain_epoch = S.chain_epoch + 1
    S.chain_keywords = gear.keywords or {}
    S.optional_missing = {}
    S.skip_note = chain_skip_note(gear, S.vo)
    S.chain_verified = (gear.keywords and #gear.keywords > 0) and nil or true
    S.pending_verify_attempts = 0
    msg.info("active gear:", gear_id)
    osd_message("已应用档位: " .. gear.label)
    -- 有 shader 链的档位：异步核对 vo-passes 中本链 //!DESC 确实存在
    --（编译失败/不兼容 PARAM 时 mpv 静默丢弃 pass，属性仍显示已设置）
    if gear.keywords and #gear.keywords > 0 then
        schedule_verify_tick(0.6)
    else
        S.chain_verified = true
    end
    sync_user_data()
end

do_off = function()
    if not S.takeover then
        osd_message("当前未接管，无需恢复")
        return
    end
    clear_verify_timer()
    local current = {}
    for prop, _ in pairs(S.wrote) do
        current[prop] = jget(prop)
    end
    local restores, kept, notes = compute_off_actions(
        S.baseline, S.last, S.wrote, S.owned, current, S.chain_kind == "whole")
    local restored_list = {}
    for _, r in ipairs(restores) do
        if r[2] ~= UNAVAIL then
            local nv, note = normalize_restorable(r[1], r[2], S.baseline)
            if note then notes[#notes + 1] = note end
            local ok, err = pcall(mp.set_property_native, r[1], nv)
            if ok then
                restored_list[#restored_list + 1] = r[1]
                journal_add(r[1])
                -- 同步账本，观察者按值比较不会把恢复写误判为外部修改
                S.last[r[1]] = nv
            else
                msg.error("off: restore failed for", r[1], ":", tostring(err))
            end
        end
    end

    local kept_export = {}
    for _, p in ipairs(kept) do
        if current[p] ~= nil then kept_export[p] = current[p] end
    end
    S.off_report = {
        restored = restored_list,
        kept_external = kept_export,
        notes = notes,
    }
    S.takeover = false
    S.state = "off"
    S.stable = "off"
    S.active = nil
    S.reason = ""
    S.baseline = {}
    S.last = {}
    S.wrote = {}
    S.owned = {}
    S.chain_kind = nil
    S.chain_verified = nil
    S.chain_keywords = {}
    S.skip_note = ""
    S.chain_epoch = S.chain_epoch + 1
    msg.info("off: restored", #restored_list, "props; kept external:", #kept)
    local summary = "关：已恢复 " .. #restored_list .. " 项托管属性"
    if #kept > 0 then
        summary = summary .. "；外部改动保留: " .. table.concat(kept, ", ")
    end
    osd_message(summary)
    sync_user_data()
end

------------------------------------------------------------------
-- 属性观察（外部检测 + P2 防陈旧重估）
------------------------------------------------------------------

-- 守卫属性变化（视频/窗口/裁剪变化）：重估适用性并刷新导出（防陈旧 pass 显示）
local function on_guard_context_changed()
    if S.shutting then return end
    S.vo = read_vo_params()
    S.chain_epoch = S.chain_epoch + 1
    if S.state == "active" and S.active then
        local gear = S.model.by_id[S.active]
        if gear then
            local guard = activation_guard_reason(gear, S.vo)
            if guard then
                -- 播放中变为 RGB/HDR：释放自有链，如实回退（不覆盖外部）
                release_for_guard(guard)
            else
                -- P3：Integer 档在几何/窗口变化上重算 k 并重写几何（防陈旧）
                if gear.integer then
                    integer_reapply_geometry(gear)
                end
                -- 几何变化：mpv 依 //!WHEN 自动重建 pass；插件刷新诚实显示。
                -- 验证尚未通过（或已 skipped）时重新核对新几何下的 pass 状态。
                if gear.keywords and #gear.keywords > 0 then
                    local applies = when_applies(gear, S.vo)
                    if applies == false then
                        S.chain_verified = "skipped-when"
                        S.skip_note = chain_skip_note(gear, S.vo)
                        clear_verify_timer()
                    else
                        S.pending_verify_attempts = 0
                        S.chain_verified = nil
                        S.skip_note = ""
                        schedule_verify_tick(0.6)
                    end
                else
                    S.skip_note = chain_skip_note(gear, S.vo)
                end
            end
        end
    end
    if S.menu_open then
        refresh_entries()
        refresh_cursor()
        render_menu()
    end
    sync_user_data()
end

local function install_observers(props)
    for _, p in ipairs(props) do
        mp.observe_property(p, "native", function(_, value)
            journal_add(p)
            if not S.takeover or S.shutting then return end
            if value == nil then return end -- 属性不可用（如关闭瞬间），不视为外部修改
            local reference
            if S.wrote[p] then
                reference = S.last[p]
            else
                reference = S.baseline[p]
            end
            if reference == nil or reference == UNAVAIL then
                -- 插件尚未拥有该属性且基线不可用：无从比较，忽略
                return
            end
            if not values_equal_prop(p, value, reference) then
                external_changed(p)
            end
        end)
    end
    -- 守卫属性：只读观察（不在基线快照内，永不触发 external），驱动防陈旧重估
    for _, p in ipairs(GUARD_PROPS) do
        mp.observe_property(p, "native", function(_, value)
            journal_add(p)
            if value == nil then return end
            on_guard_context_changed()
        end)
    end
end

------------------------------------------------------------------
-- GEO-01：几何目标尺寸唯一来源（P2 仅审计与守卫，P3 的 Integer 档使用）
------------------------------------------------------------------

-- 只允许从 video-out-params（vo 实际输出参数）取显示几何；
-- 禁止读取解码参数或任何被 shader 缩放过的中间尺寸（防反馈循环）。
local function read_display_geometry()
    local vop = jget("video-out-params")
    if type(vop) ~= "table" then return nil end
    return { w = vop.w, h = vop.h, dw = vop.dw, dh = vop.dh }
end

------------------------------------------------------------------
-- selftest（Lua 逻辑级测试；结果导出到 user-data 供 IPC 取证）
------------------------------------------------------------------

local function run_selftest()
    local cases = {}
    local function tc(name, ok, detail)
        cases[#cases + 1] = { name = name, pass = not not ok, detail = tostring(detail or "") }
    end

    -- 1. values_equal
    tc("values_equal: scalars", values_equal("a", "a") and not values_equal("a", "b"))
    tc("values_equal: lists", values_equal({ "x", "y" }, { "x", "y" }) and not values_equal({ "x" }, { "x", "y" }))
    tc("values_equal: nil", not values_equal(nil, ""))
    tc("values_equal_tol: number vs numeric string",
        values_equal_tol(0.25, "0.25") and values_equal_tol("0.25", 0.25))
    tc("values_equal_tol: precision",
        values_equal_tol(0.25, 0.25 + 1e-12) and not values_equal_tol(0.25, 0.5))
    tc("values_equal_tol: non-numeric stays strict",
        not values_equal_tol("bilinear", 1))
    -- CORE-R1：按 property 语义的统一比较（激活读回/observer/off 同源）
    tc("values_equal_prop: video-unscaled bool vs yes/no by PROPERTY semantics",
        values_equal_prop("video-unscaled", true, "yes")
        and values_equal_prop("video-unscaled", false, "no")
        and values_equal_prop("video-unscaled", "yes", true)
        and values_equal_prop("video-unscaled", "no", false)
        and not values_equal_prop("video-unscaled", true, "no")
        and not values_equal_prop("video-unscaled", false, "yes"))
    tc("values_equal_prop: generic bool stays strict (True != yes / True != 1)",
        not values_equal_prop("scale", true, "yes")
        and not values_equal_prop("dscale", false, "no")
        and not values_equal_prop("scale", true, 1)
        and not values_equal_prop("video-zoom", 1, true))
    tc("values_equal_prop: numeric readback normalization kept for numeric props",
        values_equal_prop("video-zoom", 1, "1")
        and values_equal_prop("video-zoom", 0, 0.0)
        and not values_equal_prop("video-zoom", 1, 2))
    tc("values_equal_prop: yes/no normalization is scoped, not global",
        not values_equal_prop("some-other-prop", true, "yes")
        and values_equal_prop("video-unscaled", true, "yes"))

    -- 2. parse_gears_conf（含合法/损坏/未知键混合）
    local conf = "gears=off,p1-test-shader,p1-test-broken,badmode\n" ..
        "# 注释行\n" ..
        "off_label=关\n" ..
        "p1_test_shader_label=p1-test-shader（测试桩）\n" ..
        "p1_test_shader_mode=active\n" ..
        "p1_test_shader_set=scale=bilinear;glsl-shaders+=~~/x.glsl\n" ..
        "p1_test_broken_set=scale\n" ..
        "badmode_mode=sometimes\n" ..
        "unknown_key=1\n"
    local model = parse_gears_conf(conf)
    tc("parse: order", #model.order == 4, table.concat(model.order, ","))
    tc("parse: off label is const 关", model.by_id["off"].label == OFF_LABEL)
    tc("parse: set entries", #model.by_id["p1-test-shader"].set == 2)
    tc("parse: set ops", model.by_id["p1-test-shader"].set[1].op == "set"
        and model.by_id["p1-test-shader"].set[2].op == "append")
    tc("parse: broken set flagged", model.by_id["p1-test-broken"].broken == true)
    tc("parse: badmode -> disabled+broken",
        model.by_id["badmode"].mode == "disabled" and model.by_id["badmode"].broken)
    tc("parse: unknown key warned", #model.warnings > 0)

    -- 2b. V4-FALLBACK 回归：缺失 gears=、空 gears= 值、无有效 token 三条回退
    --     路径都必须得到同一份完整 12 档内建默认表（含 sharpbilinear2x），
    --     顺序与发布 conf 注册表一致；off 恒 active，仅 LS1/BCAS 占位 disabled，
    --     sharpbilinear2x 必须是内建真实档（whole 整链固定）。
    local want_default_ids = { "off", "ls1", "fsr1", "nis", "sgsr1", "bcas",
                               "anime4k", "xbr", "sharpbilinear",
                               "sharpbilinear2x", "integer", "nearest" }
    local function default_ids_match(m)
        if #m.order ~= #want_default_ids then return false end
        for i = 1, #want_default_ids do
            if m.order[i] ~= want_default_ids[i] then return false end
        end
        return true
    end
    local m_missing = parse_gears_conf("# 注释行，无 gears= 行\nunknown_key=1\n")
    tc("fallback: missing gears= -> complete 12 defaults in registry order (V4-FALLBACK)",
        default_ids_match(m_missing), table.concat(m_missing.order, ","))
    local m_empty_val = parse_gears_conf("gears=\n")
    tc("fallback: empty gears= value -> complete 12 defaults in registry order (V4-FALLBACK)",
        default_ids_match(m_empty_val), table.concat(m_empty_val.order, ","))
    local m_no_tokens = parse_gears_conf("gears=,,,\n")
    tc("fallback: gears= with no valid token -> complete 12 defaults in registry order (V4-FALLBACK)",
        default_ids_match(m_no_tokens), table.concat(m_no_tokens.order, ","))
    local function default_flags_ok(m)
        local n_active, n_disabled = 0, 0
        for _, id in ipairs(m.order) do
            local g = m.by_id[id]
            if not g then return false end
            if g.mode == "active" then n_active = n_active + 1 else n_disabled = n_disabled + 1 end
        end
        local s2x = m.by_id["sharpbilinear2x"]
        return n_active == 10 and n_disabled == 2
            and m.by_id["off"].mode == "active" and m.by_id["off"].label == OFF_LABEL
            and m.by_id["ls1"].mode == "disabled" and m.by_id["bcas"].mode == "disabled"
            and s2x and s2x.mode == "active" and s2x.whole == true
            and #s2x.set == 1
            and s2x.set[1].value == "~~/shaders/p3-Sharp-Bilinear-2x.glsl"
    end
    tc("fallback: default flags — off active, only ls1/bcas disabled, sharp2x builtin whole chain (V4-FALLBACK)",
        default_flags_ok(m_missing) and default_flags_ok(m_empty_val)
        and default_flags_ok(m_no_tokens))

    -- 3. build_entries / next_enabled 跳过禁用项
    local entries = build_entries(model)
    tc("entries: off enabled", entries[1].enabled == true)
    tc("entries: broken disabled with reason",
        entries[3].enabled == false and entries[3].reason ~= "" and entries[3].reason:find("配置错误") ~= nil)
    local skip = next_enabled(entries, 1, 1)
    tc("entries: next enabled ok", skip == 2)
    local d2 = {
        { id = "a", label = "a", enabled = true, reason = "" },
        { id = "d1", label = "d1", enabled = false, reason = "x" },
        { id = "d2", label = "d2", enabled = false, reason = "y" },
        { id = "b", label = "b", enabled = true, reason = "" },
    }
    tc("entries: skip disabled", next_enabled(d2, 1, 1) == 4 and next_enabled(d2, 4, -1) == 1)
    tc("entries: skip end", next_enabled(d2, 4, 1) == nil)

    -- 4. plan_gear_writes：换档替换 shader、归还旧属性
    local g1 = { id = "p1-test-a", mode = "active", set = {
        { prop = "scale", op = "set", value = "bilinear" },
        { prop = "glsl-shaders", op = "append", value = "~~/a.glsl" } } }
    local g2 = { id = "p1-test-b", mode = "active", set = {
        { prop = "glsl-shaders", op = "append", value = "~~/b.glsl" } } }
    local base = { scale = "bicubic", ["glsl-shaders"] = { "~~/user.glsl" } }
    local last1 = { scale = "bilinear", ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl" } }
    local wrote1 = { scale = true, ["glsl-shaders"] = true }
    local w1, n1 = plan_gear_writes(g1, { "~~/user.glsl" }, {}, {}, base, {})
    tc("plan: first gear list", values_equal(n1, { "~~/user.glsl", "~~/a.glsl" }))
    local g1_scale = nil
    for _, w in ipairs(w1) do if w[1] == "scale" then g1_scale = w[2] end end
    tc("plan: first gear scale", g1_scale == "bilinear")
    local w2, n2 = plan_gear_writes(g2, { "~~/user.glsl", "~~/a.glsl" }, { "~~/a.glsl" }, last1, base, wrote1)
    tc("plan: switch removes old shader", values_equal(n2, { "~~/user.glsl", "~~/b.glsl" }))
    local restored_scale = nil
    for _, w in ipairs(w2) do
        if w[1] == "scale" then restored_scale = w[2] end
    end
    tc("plan: switch restores previous prop", restored_scale == "bicubic")
    local _, _, _, _, plan_err = plan_gear_writes(
        { id = "bad", set = { { prop = "glsl-shaders", op = "set", value = "x" } } },
        {}, {}, {}, base, {})
    tc("plan: direct glsl-shaders write rejected", plan_err ~= nil)

    -- 4b. P2 注册整主链 oracle（brief 纠正）：整 property 替换——首次接管
    -- 含已有 Anime4K 基线也一样整链替换，不 append；Nearest recipe = 空列表；
    -- 用户原链由接管时 baseline 快照承载，"关"恢复。兼容模式（桩）仍元素级。
    local a4k = BUILTIN_BY_ID["anime4k"]
    local fsr = BUILTIN_BY_ID["fsr1"]
    local near = BUILTIN_BY_ID["nearest"]
    local a4k_files, fsr_files = {}, {}
    for _, e in ipairs(a4k.chain) do a4k_files[#a4k_files + 1] = e.value end
    for _, e in ipairs(fsr.chain) do fsr_files[#fsr_files + 1] = e.value end
    -- 模拟首次接管：当前列表 = 用户外部门 + 原 Anime4K 基线（off 状态已有）
    local first_takeover_current = { "~~/user.glsl" }
    for _, s in ipairs(a4k_files) do first_takeover_current[#first_takeover_current + 1] = s end
    local w3, n3 = plan_gear_writes({ id = "fsr1", whole = true, set = fsr.chain },
        first_takeover_current, {}, {}, base, {})
    local no_residue = (#n3 == #fsr_files)
    for _, s in ipairs(n3) do
        if list_contains(a4k_files, s) or s == "~~/user.glsl" then no_residue = false end
    end
    tc("plan: builtin whole-chain replaces the ENTIRE property (first takeover, no append/residue)",
        no_residue and values_equal(n3, fsr_files), table.concat(n3, ","))
    -- 兼容模式（非 whole）保留元素级语义（p1-test-* 桩历史行为）
    local compat_expect = { "~~/user.glsl" }
    for _, s in ipairs(a4k_files) do compat_expect[#compat_expect + 1] = s end
    for _, e in ipairs(fsr.chain) do compat_expect[#compat_expect + 1] = e.value end
    local _, nc = plan_gear_writes({ id = "p1-test-c", set = fsr.chain },
        first_takeover_current, {}, {}, base, {})
    tc("plan: compat mode keeps element-level semantics for stubs",
        values_equal(nc, compat_expect), table.concat(nc, ","))
    -- Nearest：整 property 替换为空列表（已有 Anime4K 基线也被替换）
    local _, nn = plan_gear_writes({ id = "nearest", whole = true, set = {} },
        first_takeover_current, {}, {}, base, {})
    tc("plan: nearest whole-chain recipe is the empty shader list",
        values_equal(nn, {}), table.concat(nn, ","))
    tc("plan: fsr1 chain is exactly the adapted port file",
        #fsr_files == 1 and fsr_files[1] == "~~/shaders/p2-FSR1.glsl")
    tc("plan: nearest builtin policy (registry form)",
        #near.props == 3 and #near.chain == 0 and near.luma == false
        and near.props[1].value == "nearest" and near.props[3].prop == "dscale")
    tc("plan: nearest sets scale/cscale/dscale explicitly (parsed form)",
        (function()
            local pn = parse_gears_conf("gears=off,nearest\n")
            local s = pn.by_id["nearest"].set
            return pn.by_id["nearest"].mode == "active" and #s == 3
                and s[1].prop == "scale" and s[1].value == "nearest"
                and s[2].prop == "cscale" and s[2].value == "nearest"
                and s[3].prop == "dscale" and s[3].value == "nearest"
        end)())

    -- 5. compute_off_actions（兼容模式：p1-test-* 桩历史元素级语义）
    local r1, k1 = compute_off_actions(base, last1, wrote1, { "~~/a.glsl" },
        { scale = "bilinear", ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl" } }, false)
    local has_scale, has_glsl = false, false
    for _, r in ipairs(r1) do
        if r[1] == "scale" and r[2] == "bicubic" then has_scale = true end
        if r[1] == "glsl-shaders" and values_equal(r[2], { "~~/user.glsl" }) then has_glsl = true end
    end
    tc("off: untouched restores baseline", has_scale and has_glsl and #k1 == 0)

    local ext_last = { ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl" }, scale = "bilinear" }
    local r2, k2, n2b = compute_off_actions(base, ext_last, wrote1, { "~~/a.glsl" },
        { ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl", "~~/ext.glsl" }, scale = "spline36" }, false)
    local glsl_kept_ext = false
    for _, r in ipairs(r2) do
        if r[1] == "glsl-shaders" and values_equal(r[2], { "~~/user.glsl", "~~/ext.glsl" }) then glsl_kept_ext = true end
    end
    local scale_kept = false
    for _, p in ipairs(k2) do if p == "scale" then scale_kept = true end end
    tc("off: external list element-level", glsl_kept_ext)
    tc("off: external scalar kept", scale_kept and #n2b >= 1)

    -- 6. off 绝不清空/陈旧覆盖：外部已清链时保留外部状态，只按元素级记账
    local r3 = compute_off_actions(base, ext_last, wrote1, { "~~/a.glsl" },
        { ["glsl-shaders"] = {}, scale = "bilinear" }, false)
    local off_list_ok = false
    for _, r in ipairs(r3) do
        if r[1] == "glsl-shaders" and type(r[2]) == "table" and #r[2] == 0 then off_list_ok = true end
    end
    tc("off: external clr not overridden", off_list_ok)

    -- 6b. off 整主链 oracle（brief 纠正）：仍 owned 且等于 last_written →
    -- 恢复原完整 baseline（用户原 Anime4K 链）；external 修改整 property 后
    -- 保留用户完整列表（含重新添加的同名条目，不凭路径字符串删除）。
    local r4, k4, n4 = compute_off_actions(
        { ["glsl-shaders"] = first_takeover_current, scale = "bicubic" },
        { ["glsl-shaders"] = fsr_files, scale = "bilinear" },
        { ["glsl-shaders"] = true, scale = true },
        fsr_files,
        { ["glsl-shaders"] = fsr_files, scale = "bilinear" },
        true)
    local whole_restore_ok = false
    for _, r in ipairs(r4) do
        if r[1] == "glsl-shaders" and values_equal(r[2], first_takeover_current) then
            whole_restore_ok = true
        end
    end
    tc("off: whole-chain unmodified restores COMPLETE baseline anime chain",
        whole_restore_ok and #k4 == 0, table.concat(n4, ";"))
    -- external 后（用户外部把列表改成 [fsr同名, 新条目]）→ 完整保留，不删同名条目
    local ext_whole = { "~~/shaders/p2-FSR1.glsl", "~~/user-new.glsl" }
    local r5, k5, n5 = compute_off_actions(
        { ["glsl-shaders"] = first_takeover_current },
        { ["glsl-shaders"] = fsr_files },
        { ["glsl-shaders"] = true },
        fsr_files,
        { ["glsl-shaders"] = ext_whole },
        true)
    local whole_keep_ok = false
    for _, r in ipairs(r5) do
        if r[1] == "glsl-shaders" and values_equal(r[2], ext_whole) then whole_keep_ok = true end
    end
    tc("off: whole-chain external keeps user's COMPLETE list (same-name entry survives)",
        whole_keep_ok and #k5 == 1 and #n5 >= 1, table.concat(n5, ";"))
    -- 用户重新添加的同名条目（混入新列表）也完整保留；与 last_written 相同
    -- 的列表 = 仍 owned → 恢复基线而非保留
    local r6 = compute_off_actions(
        { ["glsl-shaders"] = first_takeover_current },
        { ["glsl-shaders"] = fsr_files },
        { ["glsl-shaders"] = true },
        fsr_files,
        { ["glsl-shaders"] = { "~~/user-other.glsl", "~~/shaders/p2-FSR1.glsl" } },
        true)
    local same_name_ok = false
    for _, r in ipairs(r6) do
        if r[1] == "glsl-shaders"
            and values_equal(r[2], { "~~/user-other.glsl", "~~/shaders/p2-FSR1.glsl" }) then
            same_name_ok = true
        end
    end
    tc("off: whole-chain re-added same-name entry is not removed by path string",
        same_name_ok)
    local r7 = compute_off_actions(
        { ["glsl-shaders"] = first_takeover_current },
        { ["glsl-shaders"] = fsr_files },
        { ["glsl-shaders"] = true },
        fsr_files,
        { ["glsl-shaders"] = fsr_files },
        true)
    local still_owned_ok = false
    for _, r in ipairs(r7) do
        if r[1] == "glsl-shaders" and values_equal(r[2], first_takeover_current) then
            still_owned_ok = true
        end
    end
    tc("off: whole-chain list equal to last_written restores baseline (still owned)",
        still_owned_ok)

    -- 7. 几何来源（GEO-01）：read_display_geometry 只读 video-out-params
    local before = #S.journal
    local geo = read_display_geometry()
    local new_reads = {}
    for i = before + 1, #S.journal do new_reads[#new_reads + 1] = S.journal[i] end
    local only_vop = true
    for _, n in ipairs(new_reads) do if n ~= "video-out-params" then only_vop = false end end
    tc("geo01: geometry reads video-out-params only", only_vop, "available=" .. tostring(geo ~= nil))

    -- 8. 占位档位身份与 fail-closed（限域修正 A）：本地 conf 无论怎么写，
    --    LS1/BCAS 等未实现 id 都必须保持 disabled 且使用固定标签/原因。
    local rsv = parse_gears_conf("gears=off,ls1,bcas\n" ..
        "ls1_mode=active\n" ..
        "ls1_set=scale=bilinear;glsl-shaders+=~~/p1-test-x.glsl\n" ..
        "ls1_label=超级LS1\n" ..
        "ls1_reason=已被替代\n" ..
        "bcas_mode=active\n" ..
        "bcas_label=Bicubic+CAS\n")
    tc("reserved: ls1 forced disabled+broken on active&_set",
        rsv.by_id["ls1"].mode == "disabled" and rsv.by_id["ls1"].broken)
    tc("reserved: ls1 label/reason fixed",
        rsv.by_id["ls1"].label == "LS1"
        and rsv.by_id["ls1"].reason:find("无公开源码") ~= nil)
    tc("reserved: bcas forced disabled fixed label",
        rsv.by_id["bcas"].mode == "disabled" and rsv.by_id["bcas"].label == "BCAS")
    tc("reserved: bcas carries real policy reason",
        rsv.by_id["bcas"].reason:find("不以CAS/Bicubic+CAS冒名", 1, true) ~= nil)
    local rsv_entries = build_entries(rsv)
    tc("reserved: entries not selectable",
        rsv_entries[1].enabled and not rsv_entries[2].enabled and not rsv_entries[3].enabled)
    local rsv2 = parse_gears_conf("gears=off,ls1,nis\n")
    -- P3 注册表迁移（P3A-01）：原断言后半要求 nis 缺省 _mode 时 disabled——
    -- 那是 nis 还是占位档的旧行为；转内建后 nis 恒 active 且链固定，
    -- "缺 _mode 强制 disabled 且非 broken" 的语义现在仅适用于保留占位 ls1。
    -- 断言严格性保留：占位侧不变，内建侧改为恒 active + 链固定。
    tc("reserved: missing _mode stays disabled (not broken); builtin nis unaffected",
        rsv2.by_id["ls1"].mode == "disabled" and not rsv2.by_id["ls1"].broken
        and rsv2.by_id["nis"].mode == "active"
        and rsv2.by_id["nis"].set[1].value == "~~/shaders/p3-NIS.glsl")

    -- 9. off 不变式（限域修正 A）：恒存在、恒首项、恒可用；显示名恒为「关」（V2-01）
    local noff = parse_gears_conf("gears=ls1,p1-test-x\np1_test_x_mode=active\n")
    tc("off: missing off auto-prepended first",
        noff.order[1] == "off" and noff.by_id["off"] ~= nil)
    local lateoff = parse_gears_conf("gears=ls1,off,fsr1\n")
    tc("off: late off moved to first", lateoff.order[1] == "off" and lateoff.order[2] == "ls1")
    local offdis = build_entries(parse_gears_conf("gears=off\noff_mode=disabled\n"))
    tc("off: cannot be disabled by conf", #offdis == 1 and offdis[1].enabled == true)
    local dupg = parse_gears_conf("gears=off,off,p1-test-d,p1-test-d\n")
    tc("off: duplicate ids merged to single entries",
        #dupg.order == 2 and dupg.order[1] == "off" and dupg.order[2] == "p1-test-d")
    local offimp = parse_gears_conf("gears=off\noff_label=LS1\n")
    tc("off: off_label cannot impersonate reserved name (fixed 关)",
        offimp.by_id["off"].label == OFF_LABEL and offimp.by_id["off"].mode == "active")

    -- 10. 重复键与告警一致（保留首个）；自定义档位不得用保留名冒名
    local dupk = parse_gears_conf("gears=off,p1-test-k\n" ..
        "p1_test_k_mode=active\n" ..
        "p1_test_k_label=first\n" ..
        "p1_test_k_label=second\n")
    tc("dup key: first value wins (matches warning)",
        dupk.by_id["p1-test-k"].label == "first")
    local imp = parse_gears_conf("gears=off,p1-test-imp\n" ..
        "p1_test_imp_mode=active\n" ..
        "p1_test_imp_label=LS1\n")
    tc("impersonation: reserved label rejected+disabled",
        imp.by_id["p1-test-imp"].broken and imp.by_id["p1-test-imp"].mode == "disabled"
        and imp.by_id["p1-test-imp"].label == "p1-test-imp")
    local imp_entries = build_entries(imp)
    tc("impersonation: entry not selectable", #imp_entries == 2 and not imp_entries[2].enabled)

    -- 11. 自定义档位缺 _mode 默认 disabled（桩须显式 active，测试桩语义）
    local mdef = parse_gears_conf("gears=off,p1-test-m\n")
    tc("custom: missing _mode defaults disabled",
        mdef.by_id["p1-test-m"].mode == "disabled" and not build_entries(mdef)[2].enabled)

    -- 12. 内建默认表与注册表一致（防漂移；P2：占位 disabled + 内建 active）
    local defm = parse_gears_conf(DEFAULT_GEARS_TEXT)
    local drift_ok = defm.order[1] == "off" and defm.by_id["off"].label == OFF_LABEL
    for _, g in ipairs(PLACEHOLDER_GEARS) do
        local d = defm.by_id[g.id]
        if d == nil or d.mode ~= "disabled" or d.label ~= g.label or d.reason ~= g.reason then
            drift_ok = false
        end
    end
    for _, g in ipairs(BUILTIN_GEARS) do
        local d = defm.by_id[g.id]
        if d == nil or d.mode ~= "active" or d.label ~= g.label or d.reason ~= g.reason then
            drift_ok = false
        end
    end
    -- 限域接续修正（brief 根因1 邻近项）：该漂移检查自 P3 起同时遍历
    -- PLACEHOLDER_GEARS 与 BUILTIN_GEARS（含五个 P3 新档），名称如实标注。
    tc("registry: default table matches gear registries (P2/P3)", drift_ok)

    -- 13. P2 内建档位防冒名/防换链：conf 的 _mode/_set/_label/_reason 全部无效
    local atk = parse_gears_conf("gears=off,fsr1,sgsr1,anime4k,nearest\n" ..
        "fsr1_mode=active\n" ..
        "fsr1_set=scale=bilinear;glsl-shaders+=~~/p1-test-fake.glsl\n" ..
        "fsr1_label=超级FSR\n" ..
        "fsr1_reason=已被替代\n" ..
        "sgsr1_mode=disabled\n" ..
        "anime4k_set=glsl-shaders+=~~/p1-test-fake2.glsl\n" ..
        "anime4k_label=ArtCNN\n" ..
        "nearest_mode=disabled\n" ..
        "nearest_set=scale=bilinear\n")
    tc("builtin: fsr1 keeps builtin chain (conf _set ignored)",
        #atk.by_id["fsr1"].set == 1 and atk.by_id["fsr1"].set[1].value == "~~/shaders/p2-FSR1.glsl")
    tc("builtin: fsr1 forced active with fixed identity",
        atk.by_id["fsr1"].mode == "active" and atk.by_id["fsr1"].label == "FSR1"
        and not atk.by_id["fsr1"].broken)
    tc("builtin: sgsr1 cannot be disabled by conf",
        atk.by_id["sgsr1"].mode == "active" and atk.by_id["sgsr1"].label == "SGSR1")
    tc("builtin: anime4k chain not replaceable, label not substitutable (no ArtCNN)",
        #atk.by_id["anime4k"].set == #ANIME4K_CHAINS[o_anime4k_mode]
        and atk.by_id["anime4k"].label == "Anime4K（stock v4）")
    tc("builtin: nearest keeps explicit nearest policy",
        atk.by_id["nearest"].mode == "active" and #atk.by_id["nearest"].set == 3
        and atk.by_id["nearest"].set[1].value == "nearest")
    local atk_entries = build_entries(atk)
    local builtin_all_enabled = #atk_entries == 5 and atk_entries[1].id == "off"
    for i = 2, 5 do
        builtin_all_enabled = builtin_all_enabled and atk_entries[i].enabled
    end
    tc("builtin: all four selectable with fixed labels", builtin_all_enabled)

    -- 14. RGB/HDR 守卫纯函数（与 Python oracle 镜像）
    tc("guard: yuv420p sdr allowed", luma_guard_reason(true,
        { pixelformat = "yuv420p", gamma = "bt.1886" }) == nil)
    tc("guard: yuv420p10 allowed", luma_guard_reason(true,
        { pixelformat = "yuv420p10", gamma = "bt.1886" }) == nil)
    tc("guard: rgb24 refused", (luma_guard_reason(true,
        { pixelformat = "rgb24", gamma = "srgb" }) or ""):find("RGB", 1, true) ~= nil)
    tc("guard: gbrp refused", (luma_guard_reason(true,
        { pixelformat = "gbrp", gamma = "srgb" }) or ""):find("RGB", 1, true) ~= nil)
    tc("guard: pq refused", (luma_guard_reason(true,
        { pixelformat = "yuv420p", gamma = "pq" }) or ""):find("HDR", 1, true) ~= nil)
    tc("guard: hlg refused", (luma_guard_reason(true,
        { pixelformat = "yuv420p", gamma = "hlg" }) or ""):find("HDR", 1, true) ~= nil)
    tc("guard: nearest has no luma guard", luma_guard_reason(false,
        { pixelformat = "rgb24", gamma = "pq" }) == nil)
    tc("guard: unknown vo does not block", luma_guard_reason(true, nil) == nil)

    -- 15. WHEN/跳过说明纯函数（诚实显示；比例用窗口像素 osd_w/osd_h）
    local up2x = { w = 1920, h = 1080, osd_w = 2560, osd_h = 1440, pixelformat = "yuv420p", gamma = "bt.1886" }
    local same1x = { w = 1920, h = 1080, osd_w = 1920, osd_h = 1080, pixelformat = "yuv420p", gamma = "bt.1886" }
    local over2x = { w = 1280, h = 720, osd_w = 3840, osd_h = 2160, pixelformat = "yuv420p", gamma = "bt.1886" }
    local aspect1x = { w = 1920, h = 1080, dw = 2560, dh = 1440, osd_w = 1920, osd_h = 1080, pixelformat = "yuv420p", gamma = "bt.1886" }
    tc("when: upscale >1 applies", when_applies(BUILTIN_BY_ID["fsr1"], up2x) == true)
    tc("when: 1x skipped", when_applies(BUILTIN_BY_ID["fsr1"], same1x) == false)
    tc("when: dw/dh is aspect-only (not upscale)", upscale_ratio(aspect1x) == 1.0)
    tc("when: unknown window -> unknown", when_applies(BUILTIN_BY_ID["fsr1"], { w = 2, h = 2 }) == nil)
    tc("when: anime4k has no ratio condition", when_applies(BUILTIN_BY_ID["anime4k"], same1x) == true)
    tc("skip note: 1x honest skip", chain_skip_note(BUILTIN_BY_ID["fsr1"], same1x):find("跳过", 1, true) ~= nil)
    tc("skip note: 2x no note", chain_skip_note(BUILTIN_BY_ID["fsr1"], up2x) == "")
    tc("skip note: fsr >2x clamp note",
        chain_skip_note(BUILTIN_BY_ID["fsr1"], over2x):find("2×", 1, true) ~= nil)
    tc("skip note: anime4k never when-skipped", chain_skip_note(BUILTIN_BY_ID["anime4k"], same1x) == "")

    -- 16. 内建链定义与 stock CTRL+1..6 一致（防漂移；字节级对照在 Python 资源审计）
    tc("builtin: anime4k chains complete for all modes",
        (function()
            for m, files in pairs(ANIME4K_CHAINS) do
                if #files < 5 then return false end
                if not (ANIME4K_MODE_KEYWORDS[m]
                        and #(ANIME4K_MODE_KEYWORDS[m].required or {}) >= 1
                        and #(ANIME4K_MODE_KEYWORDS[m].optional or {}) >= 1) then
                    return false
                end
                for _, f in ipairs(files) do
                    if not f:match("^Anime4K_.*%.glsl$") then return false end
                end
            end
            return true
        end)())
    tc("builtin: default anime4k mode is a", o_anime4k_mode == "a")
    tc("builtin: fsr1/sgsr1 marked luma, nearest not",
        BUILTIN_BY_ID["fsr1"].luma and BUILTIN_BY_ID["sgsr1"].luma
        and BUILTIN_BY_ID["anime4k"].luma and not BUILTIN_BY_ID["nearest"].luma)

    -- 17. P3 新增内建档位：防冒名/防换链（conf 覆盖一律无效并告警）
    -- 限域接续修正（brief 根因1）：上一草稿把换行写成了双引号串内的真实
    -- 换行（Lua 语法非法）；按原意改为 \n 转义连接，断言集合不变。
    local p3atk = parse_gears_conf("gears=off,nis,xbr,sharpbilinear,sharpbilinear2x,integer\n" ..
        "nis_mode=active\n" ..
        "nis_set=scale=bilinear;glsl-shaders+=~~/p1-test-fake.glsl\n" ..
        "nis_label=超级NIS\n" ..
        "xbr_mode=disabled\n" ..
        "xbr_set=glsl-shaders+=~~/p1-test-fake2.glsl\n" ..
        "sharpbilinear_label=ArtCNN\n" ..
        "sharpbilinear2x_mode=disabled\n" ..
        "integer_mode=active\n" ..
        "integer_set=video-zoom=8\n")
    tc("p3-builtin: nis keeps builtin chain (conf _set ignored)",
        #p3atk.by_id["nis"].set == 1 and p3atk.by_id["nis"].set[1].value == "~~/shaders/p3-NIS.glsl")
    tc("p3-builtin: nis forced active with fixed label",
        p3atk.by_id["nis"].mode == "active" and p3atk.by_id["nis"].label == "NIS"
        and not p3atk.by_id["nis"].broken)
    tc("p3-builtin: xbr cannot be disabled by conf",
        p3atk.by_id["xbr"].mode == "active"
        and p3atk.by_id["xbr"].set[1].value == "~~/shaders/p3-xBR-lv2.glsl")
    tc("p3-builtin: sharpbilinear label not substitutable (no ArtCNN)",
        p3atk.by_id["sharpbilinear"].label == "Sharp Bilinear（AUTO）"
        and p3atk.by_id["sharpbilinear"].set[1].value == "~~/shaders/p3-Sharp-Bilinear-AUTO.glsl")
    tc("p3-builtin: sharpbilinear2x cannot be disabled",
        p3atk.by_id["sharpbilinear2x"].mode == "active"
        and p3atk.by_id["sharpbilinear2x"].set[1].value == "~~/shaders/p3-Sharp-Bilinear-2x.glsl")
    -- 限域接续修正（brief 根因1）：原断言写 #p3atk.by_id["integer"].chain ==
    -- nil，对 nil 取长会运行时异常；且解析结果本就不含 .chain 字段。
    -- 按语义改为：注册表 integer.chain 为空表 + 解析 set 恰为 5 条托管项
    -- （3 nearest + 两个 integer-geom 几何占位），conf 的 integer_set=
    -- video-zoom=8 未渗入（set[5] 无 value、不出现 "8"），证明 _set 被忽略。
    tc("p3-builtin: integer chain empty, geometry placeholder kept, conf _set ignored",
        #(BUILTIN_BY_ID["integer"].chain or {}) == 0
        and #p3atk.by_id["integer"].set == 5
        and p3atk.by_id["integer"].set[1].prop == "scale"
        and p3atk.by_id["integer"].set[1].value == "nearest"
        and p3atk.by_id["integer"].set[4].prop == "video-unscaled"
        and p3atk.by_id["integer"].set[4].op == "integer-geom"
        and p3atk.by_id["integer"].set[5].prop == "video-zoom"
        and p3atk.by_id["integer"].set[5].op == "integer-geom"
        and p3atk.by_id["integer"].set[5].value == nil)
    tc("p3-builtin: all five selectable with fixed labels",
        (function()
            local es = build_entries(p3atk)
            local ids = {}
            for _, e in ipairs(es) do ids[e.id] = e.enabled end
            return ids["nis"] and ids["xbr"] and ids["sharpbilinear"]
                and ids["sharpbilinear2x"] and ids["integer"]
        end)())

    -- 18. P3 纯函数镜像：integer_k / sharp_auto_scale / 守卫 / 诚实说明
    tc("p3-pure: integer k 1080p@1440p fullscreen = 1",
        integer_k({ dw = 1920, dh = 1080, osd_w = 2560, osd_h = 1440 }) == 1)
    tc("p3-pure: integer k 720p@1440p fullscreen = 2",
        integer_k({ dw = 1280, dh = 720, osd_w = 2560, osd_h = 1440 }) == 2)
    tc("p3-pure: integer k<1 = 0 (window smaller than display)",
        integer_k({ dw = 1280, dh = 720, osd_w = 640, osd_h = 360 }) == 0)
    tc("p3-pure: integer k SAR-aware (uses dw/dh, not w/h)",
        integer_k({ w = 640, h = 360, dw = 1280, dh = 360, osd_w = 2560, osd_h = 1440 }) == 2)
    tc("p3-pure: integer k unknown geometry = nil",
        integer_k({ dw = 0, dh = 0 }) == nil and integer_k(nil) == nil)
    tc("p3-pure: sharp auto 1080→1440 degenerates to 1",
        sharp_auto_scale({ h = 1080, osd_h = 1440 }) == 1)
    tc("p3-pure: sharp auto 720→1440 = 2",
        sharp_auto_scale({ h = 720, osd_h = 1440 }) == 2)
    tc("p3-pure: sharp auto <1x clamped to 1 (scale-0 protection)",
        sharp_auto_scale({ h = 720, osd_h = 600 }) == 1
        and sharp_auto_scale({ h = 720, osd_h = 0 }) == nil)
    tc("p3-guard: nis refuses RGB (LUMA gear)",
        (luma_guard_reason(true,
            { pixelformat = "rgb24", gamma = "srgb" }) or ""):find("RGB", 1, true) ~= nil)
    tc("p3-guard: xbr allows RGB (MAIN gear)",
        hdr_guard_reason(true, { pixelformat = "rgb24", gamma = "srgb" }) == nil)
    tc("p3-guard: xbr refuses HDR via INDEPENDENT hdr guard",
        (hdr_guard_reason(true, { pixelformat = "rgb24", gamma = "pq" }) or "")
            :find("HDR", 1, true) ~= nil)
    -- 限域接续修正：原断言要求 HDR 拒用文案不含字样 "LUMA"，但守卫文案中
    -- “HDR 守卫独立于 LUMA 守卫”是正当的独立性说明，会被误伤。按语义改为：
    -- 同一 HDR 输入下两守卫都触发、文案互不相同（不借用）、HDR 文案不含
    -- LUMA 档专属措辞（“LUMA 档不可用”）、且包含独立性声明。
    tc("p3-guard: hdr guard does not borrow luma wording",
        (function()
            local vo = { pixelformat = "rgb24", gamma = "hlg" }
            local h = hdr_guard_reason(true, vo)
            local l = luma_guard_reason(true, vo)
            return h ~= nil and l ~= nil and h ~= l
                and h:find("LUMA 档不可用", 1, true) == nil
                and h:find("独立于 LUMA", 1, true) ~= nil
        end)())
    tc("p3-guard: integer/nearest have no guard",
        activation_guard_reason({ id = "integer" },
            { pixelformat = "rgb24", gamma = "pq" }) == nil)
    tc("p3-note: nis honest WHEN skip at ≤1x",
        chain_skip_note(BUILTIN_BY_ID["nis"],
            { w = 1920, h = 1080, dw = 1920, dh = 1080,
              osd_w = 1920, osd_h = 1080 }):find("跳过", 1, true) ~= nil)
    tc("p3-note: sharpbilinear honest degenerate note at scale=1",
        chain_skip_note(BUILTIN_BY_ID["sharpbilinear"],
            { h = 1080, osd_h = 1440 }):find("退化为双线性", 1, true) ~= nil)
    tc("p3-note: integer honest k<1 note",
        chain_skip_note(BUILTIN_BY_ID["integer"],
            { dw = 1280, dh = 720, osd_w = 640, osd_h = 360 }):find("k<1", 1, true) ~= nil)

    -- 19. P3 Integer 激活写入计划：整 property 替换 + 几何托管占位拒绝
    tc("p3-plan: integer placeholder op rejected outside activation",
        (function()
            local _, _, _, _, perr = plan_gear_writes(
                { id = "integer", whole = true, set = {
                    { prop = "video-zoom", op = "integer-geom" } } },
                {}, {}, {}, {}, {})
            return perr ~= nil
        end)())
    tc("p3-plan: integer k>=1 activation writes unscaled=yes zoom=log2 k",
        (function()
            local vo = { dw = 1280, dh = 720, osd_w = 2560, osd_h = 1440 }
            local k = integer_k(vo)
            local g = { id = "integer", whole = true, set = {
                { prop = "scale", op = "set", value = "nearest" },
                { prop = "video-unscaled", op = "set", value = "yes" },
                { prop = "video-zoom", op = "set", value = math.log(k, 2) } } }
            local writes, nl = plan_gear_writes(g, { "~~/old.glsl" }, {}, {}, {}, {})
            local zoom = nil
            for _, w in ipairs(writes) do
                if w[1] == "video-zoom" then zoom = w[2] end
            end
            return k == 2 and zoom == 1.0 and #nl == 0
        end)())
    tc("p3-plan: integer k<1 fallback writes unscaled=no zoom=0 (no crop)",
        (function()
            local g = { id = "integer", whole = true, set = {
                { prop = "video-unscaled", op = "set", value = "no" },
                { prop = "video-zoom", op = "set", value = 0 } } }
            local writes, nl = plan_gear_writes(g, { "~~/old.glsl" }, {}, {}, {}, {})
            local unscaled = nil
            for _, w in ipairs(writes) do
                if w[1] == "video-unscaled" then unscaled = w[2] end
            end
            return unscaled == "no" and #nl == 0
        end)())

    tc("guard: cscale sentinel normalized to baseline scale",
        (function()
            local nv, note = normalize_restorable("cscale", 0, { scale = "bicubic" })
            return nv == "bicubic" and note ~= nil
        end)())
    tc("guard: cscale normal value untouched",
        select(1, normalize_restorable("cscale", "spline36", {})) == "spline36")

    local all_pass = true
    local fail_count = 0
    for _, c in ipairs(cases) do
        if not c.pass then
            all_pass = false
            fail_count = fail_count + 1
        end
        msg.info("selftest:", c.pass and "PASS" or "FAIL", c.name,
            c.detail ~= "" and ("[" .. c.detail .. "]") or "")
    end
    user_data_set("selftest", { status = all_pass and "pass" or "fail", cases = cases })
    msg.info("selftest finished:", all_pass and "pass" or "fail", "cases:", #cases, "failures:", fail_count)
end

------------------------------------------------------------------
-- 配置装载与启动
------------------------------------------------------------------

local function load_gears_model()
    local path = mp.command_native({ "expand-path", "~~/script-opts/scale-selector-gears.conf" })
    local text = nil
    if type(path) == "string" and path ~= "" then
        local f = io.open(path, "r")
        if f then
            text = f:read("*a")
            f:close()
        end
    end
    if text then
        msg.info("gears conf loaded:", path)
        return parse_gears_conf(text)
    end
    msg.warn("gears conf not found, using built-in defaults")
    return parse_gears_conf(DEFAULT_GEARS_TEXT)
end

local function shutdown_handler()
    S.shutting = true
    clear_verify_timer()
    close_menu()
    msg.info("shutdown, final state:", S.state, "gear:", S.active or "none",
        "(不持久化，重启回到 off；本插件未写任何状态文件)")
end

local function main()
    S.model = load_gears_model()
    for _, w in ipairs(S.model.warnings) do
        msg.warn("config:", w)
    end
    local props = managed_props(S.model)
    msg.info("managed properties:", table.concat(props, ", "))
    msg.info("guard watch properties:", table.concat(GUARD_PROPS, ", "))
    msg.info("anime4k chain mode:", o_anime4k_mode, "(" .. ANIME4K_MODE_LABELS[o_anime4k_mode] .. ")")
    msg.info("binding menu key:", o.key_menu)
    install_observers(props)
    mp.add_key_binding(o.key_menu, "scale-selector-menu", toggle_menu)
    mp.register_script_message("scale-selector-selftest", run_selftest)
    mp.register_event("shutdown", shutdown_handler)
    sync_user_data()
    msg.info("scale-selector P3 loaded; state=off; vo/gpu-api 由启动参数固定（gpu-next/vulkan）")
end

main()
