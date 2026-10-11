-- scale-selector.lua — mpv 缩放算法选择器 P1 骨架
-- session p1-001（p1-002 限域修正同源码）/ 阶段 P1（隔离验证；不持久化，重启回到 off）
--
-- 范围（P1）：
--   * F8 菜单（UP/DOWN/Enter/Esc；F8 开关）
--   * off / active / external / fallback 状态机
--   * 托管属性快照与恢复：glsl-shaders、scale、cscale、dscale、插件设置的显示几何
--   * "关"档位：仅恢复托管且未被外部改动的属性；禁用 glsl-shaders-clr 全清
--   * 外部改链检测与让出（外部修改优先，插件永不静默覆盖）
--   * fallback：资源缺失/非法配置/档位应用失败时显示真实原因并回退上一稳定状态
--   * LS1/BCAS 禁用占位与原因文案；P2+ 条目显示"未实现/后续阶段"且不可选
--
-- 明确不做（后续阶段）：真实缩放档位、vo-passes 实际 pass 检测、持久化、部署。
-- 后端：显式由测试/启动参数固定 vo=gpu-next、gpu-api=vulkan；本脚本不改变它们。

local mp = require 'mp'
local msg = require 'mp.msg'
local utils = require 'mp.utils'
local options = require 'mp.options'

local o = {
    key_menu = "F8",
    menu_font_size = 22,
}
options.read_options(o, "scale-selector")

------------------------------------------------------------------
-- 常量与托管属性
------------------------------------------------------------------

local CORE_PROPS = { "glsl-shaders", "scale", "cscale", "dscale" }

-- 哨兵：快照时属性不可用（例如无视频时的显示几何）；恢复时跳过，绝不写回该字符串
local UNAVAIL = "@@unavailable@@"

local OFF_ID = "off"

------------------------------------------------------------------
-- P1 保留档位注册表：真实实现落地（P2+）前强制 disabled 且身份固定。
-- 这是解析器层的结构保证（限域修正 A / R1+F-03）：本地 gears conf 无论省略
-- _mode、显式写 active、配 _set 还是改 _label/_reason，都无法让这些 id 变为
-- 可选，也无法借它们的标签冒名挂任意链。off 由解析器强制恒在首项且可用。
------------------------------------------------------------------
local PRODUCT_GEARS = {
    { id = "ls1",   label = "LS1",   reason = "无公开源码/权重/移植许可，无法原样内置；不以替代算法冒名" },
    { id = "fsr1",  label = "FSR1",  reason = "未实现/后续阶段（P2：EASU+RCAS，MIT，每轴≤2×）" },
    { id = "nis",   label = "NIS",   reason = "未实现/后续阶段（P3：NVScaler compute，内含锐化）" },
    { id = "sgsr1", label = "SGSR1", reason = "未实现/后续阶段（P2：Qualcomm SGSR1 LUMA 适配，BSD-3）" },
    { id = "bcas",  label = "BCAS",  reason = "算法定义身份未核实；不以CAS/Bicubic+CAS冒名" },
    { id = "anime4k", label = "Anime4K（stock v4）", reason = "未实现/后续阶段（P2：引用本机 stock 链，零修改）" },
    { id = "xbr",   label = "xBR",   reason = "未实现/后续阶段（P3：选定版本移植，xBR≠xBRZ）" },
    { id = "sharpbilinear", label = "Sharp Bilinear", reason = "未实现/后续阶段（P3：AUTO/手动2× 分列）" },
    { id = "integer", label = "Integer（整数倍）", reason = "未实现/后续阶段（P3：Lua几何+nearest，黑边明示）" },
    { id = "nearest", label = "Nearest Neighbor", reason = "未实现/后续阶段（P2：内建 scale=nearest）" },
}
local RESERVED_GEARS = {}   -- id -> {label=..., reason=...}（固定身份）
local RESERVED_NAMES = {}   -- casefold(保留 id/label) 集合（含 off/关），防自定义档位冒名
 do
    RESERVED_NAMES["off"] = true
    RESERVED_NAMES["关"] = true
    for _, g in ipairs(PRODUCT_GEARS) do
        RESERVED_GEARS[g.id] = { label = g.label, reason = g.reason }
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

-- mpv 会把数值属性规范化为 number（如 "0.25"→0.25），比较需容忍类型/精度差异
local function values_equal_tol(a, b)
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

-- 解析档位表文本（script-opts/scale-selector-gears.conf）。
-- 返回 { order={id...}, by_id={id=gear}, warnings={...} }
-- gear = { id, label, mode, reason, broken, set={{prop,op,value}...} }
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
        gears_raw = "off,ls1,fsr1,nis,sgsr1,bcas,anime4k,xbr,sharpbilinear,integer,nearest"
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
        ids = { OFF_ID, "ls1", "fsr1", "nis", "sgsr1", "bcas", "anime4k", "xbr", "sharpbilinear", "integer", "nearest" }
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
        local raw_label = kv[prefix .. "_label"]
        local raw_mode = kv[prefix .. "_mode"]
        local raw_reason = kv[prefix .. "_reason"]
        local gear = { id = id, label = id, mode = "disabled", reason = "", broken = false, set = {} }
        if id == OFF_ID then
            -- off 不变式：可用性由插件强制，conf 不能禁用；显示名可定制
            gear.label = raw_label or "关"
            gear.reason = raw_reason or ""
            gear.mode = "active"
            if raw_mode and raw_mode ~= "active" then
                warn("off_mode=" .. tostring(raw_mode) .. " 被忽略：off 始终存在且可用，不能被配置禁用")
            end
        elseif reserved then
            -- 保留档位（P1 无真实实现）：身份固定、强制 disabled；
            -- _mode/_set/_label/_reason 的任何覆盖一律无效（防冒名）
            gear.label = reserved.label
            gear.reason = reserved.reason
            if raw_label or raw_reason then
                warn("保留档位 " .. id .. " 的 _label/_reason 覆盖被忽略（使用内建固定标签/原因，防冒名）")
            end
            if raw_mode and raw_mode ~= "disabled" then
                warn("保留档位 " .. id .. " 强制 disabled（P1 未实现，忽略 _mode=" .. tostring(raw_mode) .. "）")
                gear.broken = true
            end
            local rs = kv[prefix .. "_set"]
            if rs and rs ~= "" then
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
        local set_raw = kv[prefix .. "_set"]
        if set_raw and set_raw ~= "" then
            if id == OFF_ID then
                warn("档位 off 不接受 _set（内建恢复语义），已忽略")
            elseif reserved then
                -- 保留档位的 _set 已在上面拒绝并告警，不再解析
            else
                for entry in set_raw:gmatch("[^;]+") do
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
--   gear           档位对象
--   current_list   当前 glsl-shaders 列表
--   owned_shaders  插件此前添加的 shader（将被替换）
--   last / baseline / wrote  所有权表（见状态机）
-- 返回 writes={{prop,value}...}, new_list, adds, removes, err
-- 规则：一次仅一档；换档先归还上一档写过的属性（仅限仍归插件所有者），
--       glsl-shaders 按元素级替换（保留外部条目），绝不使用 clr。
local function plan_gear_writes(gear, current_list, owned_shaders, last, baseline, wrote)
    if gear.id == OFF_ID then
        return nil, nil, nil, nil, "off 档位走内建恢复语义，不走 plan_gear_writes"
    end
    local target = {}
    local adds, removes = {}, {}
    for _, e in ipairs(gear.set) do
        if e.prop == "glsl-shaders" then
            if e.op == "append" then
                adds[#adds + 1] = e.value
            elseif e.op == "remove" then
                removes[#removes + 1] = e.value
            else
                return nil, nil, nil, nil, "禁止对 glsl-shaders 直接赋值（请用 +=/-=）"
            end
        else
            if e.op ~= "set" then
                return nil, nil, nil, nil, "仅 glsl-shaders 支持 +=/-=（" .. e.prop .. "）"
            end
            target[e.prop] = e.value
        end
    end

    local writes = {}
    -- 归还上一档写过、且本档不再设置的属性（恢复到基线；外部改动
    -- 在进入本函数前已由 external 状态拦截，不会走到这里）
    for prop, _ in pairs(wrote) do
        if prop ~= "glsl-shaders" and target[prop] == nil then
            writes[#writes + 1] = { prop, baseline[prop] }
        end
    end
    for prop, v in pairs(target) do
        writes[#writes + 1] = { prop, v }
    end

    local new_list = {}
    for _, s in ipairs(current_list) do
        if not list_contains(owned_shaders, s) and not list_contains(removes, s) then
            new_list[#new_list + 1] = s
        end
    end
    for _, s in ipairs(adds) do
        new_list[#new_list + 1] = s
    end
    writes[#writes + 1] = { "glsl-shaders", new_list }
    return writes, new_list, adds, removes
end

-- 计算"关"的恢复动作（仅恢复插件拥有且未被外部改动的属性）。
--   current: {prop=value}（仅需包含 wrote 中的属性）
-- 返回 restores={{prop,value}...}, kept={prop...}, notes={...}
-- glsl-shaders 特殊：被外部改动时按元素级移除插件添加项、保留外部条目；
-- 未被外部改动时精确恢复基线。绝不输出"清空列表"语义。
local function compute_off_actions(baseline, last, wrote, owned_shaders, current)
    local restores, kept, notes = {}, {}, {}
    for prop, was_written in pairs(wrote) do
        if was_written then
            local cur = current[prop]
            if prop == "glsl-shaders" then
                local cur_list = type(cur) == "table" and cur or {}
                if values_equal_tol(cur_list, last[prop]) then
                    restores[#restores + 1] = { "glsl-shaders", baseline[prop] or {} }
                else
                    local new_list = {}
                    for _, s in ipairs(cur_list) do
                        if not list_contains(owned_shaders, s) then
                            new_list[#new_list + 1] = s
                        end
                    end
                    restores[#restores + 1] = { "glsl-shaders", new_list }
                    kept[#kept + 1] = prop
                    notes[#notes + 1] = "glsl-shaders：外部改动保留，仅移除本插件添加的条目"
                end
            else
                if values_equal_tol(cur, last[prop]) then
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

local DEFAULT_GEARS_TEXT = [[
gears=off,ls1,fsr1,nis,sgsr1,bcas,anime4k,xbr,sharpbilinear,integer,nearest
off_label=关
ls1_label=LS1
ls1_mode=disabled
ls1_reason=无公开源码/权重/移植许可，无法原样内置；不以替代算法冒名
fsr1_label=FSR1
fsr1_mode=disabled
fsr1_reason=未实现/后续阶段（P2：EASU+RCAS，MIT，每轴≤2×）
nis_label=NIS
nis_mode=disabled
nis_reason=未实现/后续阶段（P3：NVScaler compute，内含锐化）
sgsr1_label=SGSR1
sgsr1_mode=disabled
sgsr1_reason=未实现/后续阶段（P2：Qualcomm SGSR1 LUMA 适配，BSD-3）
bcas_label=BCAS
bcas_mode=disabled
bcas_reason=算法定义身份未核实；不以CAS/Bicubic+CAS冒名
anime4k_label=Anime4K（stock v4）
anime4k_mode=disabled
anime4k_reason=未实现/后续阶段（P2：引用本机 stock 链，零修改）
xbr_label=xBR
xbr_mode=disabled
xbr_reason=未实现/后续阶段（P3：选定版本移植，xBR≠xBRZ）
sharpbilinear_label=Sharp Bilinear
sharpbilinear_mode=disabled
sharpbilinear_reason=未实现/后续阶段（P3：AUTO/手动2× 分列）
integer_label=Integer（整数倍）
integer_mode=disabled
integer_reason=未实现/后续阶段（P3：Lua几何+nearest，黑边明示）
nearest_label=Nearest Neighbor
nearest_mode=disabled
nearest_reason=未实现/后续阶段（P2：内建 scale=nearest）
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
    owned = {},               -- 插件添加的 shader 列表
    takeover = false,
    off_report = nil,
    shutting = false,
    menu_open = false,
    cursor = 1,
    entries = {},
    journal = {},             -- 属性读取审计（GEO-01）
    model = nil,
}

local overlay = nil
local open_menu, close_menu, activate_gear, do_off

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

------------------------------------------------------------------
-- user-data 导出（IPC 客观验证接口）
------------------------------------------------------------------

local function current_menu_entries_export()
    local out = {}
    for i, e in ipairs(S.entries) do
        out[i] = {
            id = e.id, label = e.label, enabled = e.enabled, reason = e.reason,
            selected = (S.menu_open and i == S.cursor),
        }
    end
    return out
end

local function sync_user_data()
    user_data_set("stage", "P1")
    user_data_set("state", S.state)
    user_data_set("stable_gear", S.stable or "off")
    user_data_set("gear", S.active or "")
    user_data_set("reason", S.reason or "")
    user_data_set("menu_open", S.menu_open)
    user_data_set("menu_entries", current_menu_entries_export())
    user_data_set("off_report", S.off_report or {})
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
end

------------------------------------------------------------------
-- 菜单（ASS overlay）
------------------------------------------------------------------

local function state_header_text()
    if S.state == "off" then
        return "状态: off（未接管）"
    elseif S.state == "active" then
        local g = S.model.by_id[S.active]
        return string.format("状态: active（%s）", g and g.label or S.active or "?")
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
    parts[#parts + 1] = string.format("{\\fs%d}{\\b1}缩放选择器 [P1骨架]{\\b0}\\N{\\fs%d}%s\\N\\N",
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
    parts[#parts + 1] = "\\N{\\fs" .. math.floor(fs * 0.66) .. "}{\\c&HBBBBBB&}↑/↓ 选择 · Enter 确认 · Esc/F8 关闭\\N关＝恢复接管前配置（不停止mpv必需的缩放/色彩管理）{\\c}"
    overlay.data = "{\\an7}{\\bord1}{\\shad1}{\\1c&HFFFFFF&}{\\3c&H000000&}" .. table.concat(parts)
    overlay:update()
end

local function export_menu_entries()
    S.entries = build_entries(S.model)
end

open_menu = function()
    if S.menu_open then return end
    export_menu_entries()
    S.cursor = next_enabled(S.entries, 0, 1) or 1
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
        export_menu_entries()
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
-- 状态迁移
------------------------------------------------------------------

local function enter_fallback(gear_id, reason, released)
    S.state = "fallback"
    S.reason = reason
    if released then
        S.stable = "off"
        S.active = nil
        S.takeover = false
        S.baseline = {}
        S.last = {}
        S.wrote = {}
        S.owned = {}
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
    S.state = "external"
    S.reason = "检测到外部修改: " .. prop .. "（插件已让出，不会覆盖）"
    msg.info("external change on", prop, "- yielding")
    osd_message("检测到外部修改（" .. prop .. "），已让出")
    sync_user_data()
end

activate_gear = function(gear_id)
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
        osd_message("外部修改中：请先选择〔关〕处理差异，插件不会静默覆盖")
        return
    end

    local props = managed_props(S.model)
    local first = not S.takeover
    if first then
        if not take_snapshot(props) then
            osd_message("接管失败：接管期间属性被外部修改，请重试")
            return
        end
    end

    local cur_list = jget("glsl-shaders")
    if type(cur_list) ~= "table" then cur_list = {} end
    local writes, _new_list, adds, _removes, plan_err =
        plan_gear_writes(gear, cur_list, S.owned, S.last, S.baseline, S.wrote)
    if not writes then
        if first then
            enter_fallback(gear_id, "档位计划失败: " .. tostring(plan_err), true)
        else
            enter_fallback(gear_id, "档位计划失败: " .. tostring(plan_err), false)
        end
        return
    end

    -- 资源预检（在写入前完成，失败不产生半生效）
    for _, p in ipairs(adds) do
        local expanded = expand_path(p)
        local fi = utils.file_info(expanded)
        if not fi or fi.is_dir then
            if first then
                enter_fallback(gear_id, "shader 文件缺失: " .. p, true)
            else
                enter_fallback(gear_id, "shader 文件缺失: " .. p, false)
            end
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
    local written = {}
    local failed = nil
    for _, w in ipairs(writes) do
        local ok, err = write_owned(w[1], w[2])
        if not ok then
            failed = w[1] .. ": " .. tostring(err or "?")
            break
        end
        -- 读回校验（mpv 可能静默丢弃/改写非法值）
        local cur = jget(w[1])
        if not values_equal_tol(cur, w[2]) then
            failed = "读回不一致: " .. w[1]
            break
        end
        written[w[1]] = true
    end
    if failed then
        for p, v in pairs(prev_values) do
            if written[p] and v ~= UNAVAIL then pcall(mp.set_property_native, p, v) end
        end
        S.last = prev_last
        S.wrote = prev_wrote
        S.owned = prev_owned
        if first then
            enter_fallback(gear_id, failed, true)
        else
            enter_fallback(gear_id, failed, false)
        end
        return
    end

    S.owned = adds
    S.state = "active"
    S.stable = gear_id
    S.active = gear_id
    S.reason = ""
    msg.info("active gear:", gear_id)
    osd_message("已应用档位: " .. gear.label)
    sync_user_data()
end

do_off = function()
    if not S.takeover then
        osd_message("当前未接管，无需恢复")
        return
    end
    local current = {}
    for prop, _ in pairs(S.wrote) do
        current[prop] = jget(prop)
    end
    local restores, kept, notes = compute_off_actions(S.baseline, S.last, S.wrote, S.owned, current)
    local restored_list = {}
    for _, r in ipairs(restores) do
        if r[2] ~= UNAVAIL then
            local ok, err = pcall(mp.set_property_native, r[1], r[2])
            if ok then
                restored_list[#restored_list + 1] = r[1]
                journal_add(r[1])
                -- 同步账本，观察者按值比较不会把恢复写误判为外部修改
                S.last[r[1]] = r[2]
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
    msg.info("off: restored", #restored_list, "props; kept external:", #kept)
    local summary = "关：已恢复 " .. #restored_list .. " 项托管属性"
    if #kept > 0 then
        summary = summary .. "；外部改动保留: " .. table.concat(kept, ", ")
    end
    osd_message(summary)
    sync_user_data()
end

------------------------------------------------------------------
-- 属性观察（外部检测；自身写入靠"值==last_written"天然屏蔽）
------------------------------------------------------------------

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
            if not values_equal_tol(value, reference) then
                external_changed(p)
            end
        end)
    end
end

------------------------------------------------------------------
-- GEO-01：几何目标尺寸唯一来源（P1 仅为审计基础，P3 的 Integer 档使用）
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
    tc("parse: label", model.by_id["off"].label == "关")
    tc("parse: set entries", #model.by_id["p1-test-shader"].set == 2)
    tc("parse: set ops", model.by_id["p1-test-shader"].set[1].op == "set"
        and model.by_id["p1-test-shader"].set[2].op == "append")
    tc("parse: broken set flagged", model.by_id["p1-test-broken"].broken == true)
    tc("parse: badmode -> disabled+broken",
        model.by_id["badmode"].mode == "disabled" and model.by_id["badmode"].broken)
    tc("parse: unknown key warned", #model.warnings > 0)

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

    -- 5. compute_off_actions
    local r1, k1 = compute_off_actions(base, last1, wrote1, { "~~/a.glsl" },
        { scale = "bilinear", ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl" } })
    local has_scale, has_glsl = false, false
    for _, r in ipairs(r1) do
        if r[1] == "scale" and r[2] == "bicubic" then has_scale = true end
        if r[1] == "glsl-shaders" and values_equal(r[2], { "~~/user.glsl" }) then has_glsl = true end
    end
    tc("off: untouched restores baseline", has_scale and has_glsl and #k1 == 0)

    local ext_last = { ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl" }, scale = "bilinear" }
    local r2, k2, n2b = compute_off_actions(base, ext_last, wrote1, { "~~/a.glsl" },
        { ["glsl-shaders"] = { "~~/user.glsl", "~~/a.glsl", "~~/ext.glsl" }, scale = "spline36" })
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
        { ["glsl-shaders"] = {}, scale = "bilinear" })
    local off_list_ok = false
    for _, r in ipairs(r3) do
        if r[1] == "glsl-shaders" and type(r[2]) == "table" and #r[2] == 0 then off_list_ok = true end
    end
    tc("off: external clr not overridden", off_list_ok)

    -- 7. 几何来源（GEO-01）：read_display_geometry 只读 video-out-params
    local before = #S.journal
    local geo = read_display_geometry()
    local new_reads = {}
    for i = before + 1, #S.journal do new_reads[#new_reads + 1] = S.journal[i] end
    local only_vop = true
    for _, n in ipairs(new_reads) do if n ~= "video-out-params" then only_vop = false end end
    tc("geo01: geometry reads video-out-params only", only_vop, "available=" .. tostring(geo ~= nil))

    -- 8. 保留档位身份与 fail-closed（限域修正 A / R1+F-03）：
    --    本地 conf 无论缺 _mode、显式 active、配 _set 还是改 _label/_reason，
    --    LS1/BCAS 等保留 id 都必须保持 disabled 且使用固定标签/原因。
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
    local rsv2 = parse_gears_conf("gears=off,ls1,fsr1\n")
    tc("reserved: missing _mode stays disabled (not broken)",
        rsv2.by_id["ls1"].mode == "disabled" and not rsv2.by_id["ls1"].broken
        and rsv2.by_id["fsr1"].mode == "disabled")

    -- 9. off 不变式（限域修正 A）：恒存在、恒首项、恒可用
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

    -- 11. 自定义档位缺 _mode 默认 disabled（桩须显式 active，P1 桩语义）
    local mdef = parse_gears_conf("gears=off,p1-test-m\n")
    tc("custom: missing _mode defaults disabled",
        mdef.by_id["p1-test-m"].mode == "disabled" and not build_entries(mdef)[2].enabled)

    -- 12. 内建默认表与保留注册表一致（防漂移）
    local defm = parse_gears_conf(DEFAULT_GEARS_TEXT)
    local drift_ok = defm.order[1] == "off"
    for _, g in ipairs(PRODUCT_GEARS) do
        local d = defm.by_id[g.id]
        if d == nil or d.mode ~= "disabled" or d.label ~= g.label or d.reason ~= g.reason then
            drift_ok = false
        end
    end
    tc("registry: default table matches reserved registry", drift_ok)

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
    close_menu()
    msg.info("shutdown, final state:", S.state, "gear:", S.active or "none",
        "(P1 不持久化，重启回到 off；本插件未写任何状态文件)")
end

local function main()
    S.model = load_gears_model()
    for _, w in ipairs(S.model.warnings) do
        msg.warn("config:", w)
    end
    local props = managed_props(S.model)
    msg.info("managed properties:", table.concat(props, ", "))
    msg.info("binding menu key:", o.key_menu)
    install_observers(props)
    mp.add_key_binding(o.key_menu, "scale-selector-menu", toggle_menu)
    mp.register_script_message("scale-selector-selftest", run_selftest)
    mp.register_event("shutdown", shutdown_handler)
    sync_user_data()
    msg.info("scale-selector P1 loaded; state=off; vo/gpu-api 由启动参数固定（gpu-next/vulkan）")
end

main()
