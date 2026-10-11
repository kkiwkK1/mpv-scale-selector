"""Unit tests for P2 (p2-001) support: stock-chain resources, guard oracles,
main-chain replacement policy, nearest explicit scaler policy, P2 static
source audits, and P2 synthetic media. Fast, stdlib-only, never launches mpv.

Real-mpv objective checks live in tools/p2_verify.py; the Lua-side mirror of
the guard/registry logic is exercised there via the plugin selftest + IPC
export (three-way evidence: glsl-shaders list / vo-passes / user-data).

P2 兼容迁移说明（tests/test_p1_support.py 只加注不改断言）：
  * p1_lib.audit_gears_conf 的 all_product_gears_disabled 语义随 P2 收窄为
    「仍禁用的占位档位」——P1 旧断言「全部产品档位 disabled」不再成立，
    因为 fsr1/sgsr1/anime4k/nearest 已是真实内建档位（见 p1_lib docstring）。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p1_lib as lib  # noqa: E402
import p2_lib as p2  # noqa: E402

LUA_SOURCE = lib.PLUGIN_LUA.read_text(encoding="utf-8")


class TestStockResources(unittest.TestCase):
    """Byte-level audit: repo anime4k copies == frozen backup == live config."""

    def test_stock_copy_byte_identical(self):
        """M-8: deterministic contract only — repo copies == frozen backup.
        用户活动 mpv 配置（%APPDATA%）随用户增删自己的文件而变化，不得作
        为单测的通过条件；live 交叉核对已移入真实验证阶段
        （tools/p2_verify.py main() 的 live_config_cross_check，只读）。
        cross_check_live=False 下也不得出现 live_sha256（未读活动配置）。"""
        result = p2.verify_stock_copy(cross_check_live=False)
        self.assertEqual(result["problems"], [],
                         f"stock copy audit failed: {result['problems']}")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["files"]), len(p2.ANIME4K_CHAIN_FILES))
        for name, entry in result["files"].items():
            self.assertEqual(entry["repo_sha256"], entry["backup_sha256"],
                             f"{name} differs from frozen backup")
            self.assertNotIn("live_sha256", entry,
                             f"{name}: live config must not be read here")

    def test_live_cross_check_branch_against_temp_fixture(self):
        """M-8: live 分支语义仍被钉住——但经 unittest.mock 把
        p2_lib.LIVE_SHADER_DIR 指向临时 fixture，绝不读真实 %APPDATA%：
        一致 → 记录 live_sha256 且 ok；缺文件 → 逐文件显式问题且 ok=False。"""
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "shaders"
            live.mkdir()
            for name in p2.ANIME4K_CHAIN_FILES:
                shutil.copyfile(p2.REPO_ANIME4K_DIR / name, live / name)
            with mock.patch.object(p2, "LIVE_SHADER_DIR", live):
                result = p2.verify_stock_copy(cross_check_live=True)
            self.assertTrue(result["ok"],
                            f"fixture live audit failed: {result['problems']}")
            for name, entry in result["files"].items():
                self.assertEqual(entry["live_sha256"], entry["repo_sha256"],
                                 f"{name}: fixture live copy must match repo")
        # 负例：live 目录存在但为空 → 每个文件一条显式缺文件问题（不静默通过）
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(p2, "LIVE_SHADER_DIR", Path(tmp)):
                result = p2.verify_stock_copy(cross_check_live=True)
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["problems"]),
                             len(p2.ANIME4K_CHAIN_FILES))

    def test_resource_manifest_audits_clean(self):
        result = p2.verify_resource_manifest()
        self.assertTrue(result["ok"],
                        f"resource manifest problems: {result['problems']}")
        paths = {r["path"] for r in result["resources"]}
        for rel in (p2.REPO_FSR_PATH, p2.REPO_SGSR_PATH):
            self.assertIn(rel, paths)
        stock = [r for r in result["resources"] if r["kind"] == "stock-copy"]
        self.assertEqual(len(stock), len(p2.ANIME4K_CHAIN_FILES))
        # M-11: 许可以文件内嵌头为准——8 个文件头为 MIT（bloc97），
        # 两个 AutoDownscalePre 文件头为 Unlicense（公共领域，unlicense.org）
        unlicense_files = {"Anime4K_AutoDownscalePre_x2.glsl",
                           "Anime4K_AutoDownscalePre_x4.glsl"}
        for r in stock:
            self.assertFalse(r["modified"], "stock copies must be unmodified")
            expected = ("Unlicense"
                        if Path(r["path"]).name in unlicense_files else "MIT")
            self.assertIn(expected, r["license"],
                          f"{r['path']}: license must match embedded header")

    def test_adapted_ports_are_distinct_from_base(self):
        """FSR/SGSR adapted ports: own hash/version, base evidence intact,
        original algorithm DESC lines preserved (never renamed)."""
        fsr = (REPO_ROOT / p2.REPO_FSR_PATH).read_text(encoding="utf-8")
        sgsr = (REPO_ROOT / p2.REPO_SGSR_PATH).read_text(encoding="utf-8")
        self.assertIn("p2-adapt-v1", fsr)
        self.assertIn("p2-adapt-v1", sgsr)
        self.assertIn(lib.sha256_file(REPO_ROOT / p2.FSR_BASE_EVIDENCE), fsr)
        self.assertIn(lib.sha256_file(REPO_ROOT / p2.SGSR_BASE_EVIDENCE), sgsr)
        # 主算法不可替代或改名：DESC 保留原名
        self.assertIn("//!DESC FidelityFX Super Resolution v1.0.2 (EASU)", fsr)
        self.assertIn("//!DESC FidelityFX Super Resolution v1.0.2 (RCAS)", fsr)
        self.assertIn("//!DESC Snapdragon Game Super Resolution (GSR) v1", sgsr)
        # 每轴≤2× 钳制与 WHEN 保留
        self.assertIn("//!WHEN OUTPUT.w OUTPUT.h * LUMA.w LUMA.h * / 1.0 >", fsr)
        self.assertIn("2 * < * LUMA.w 2 *", fsr)
        # 固定参数（SGSR DEFINE 参数原文为整数 1：等值整数表示均接受，
        # 不为过测试改动真实原算法或许可——brief 根因修复）
        self.assertIn("#define SHARPNESS 0.2", fsr)
        self.assertRegex(sgsr, r"//!MAXIMUM 1(?:\.0)?\r?\n1(?:\.0)?\r?\n")  # UseEdgeDirection=1 ∈ [0,1]
        # 原版权/许可头保留
        self.assertIn("Advanced Micro Devices", fsr)
        self.assertIn("Qualcomm Innovation Center", sgsr)
        self.assertIn("SPDX-License-Identifier: BSD-3-Clause", sgsr)

    def test_chains_match_live_input_conf(self):
        """The built-in chain table equals the real CTRL+1..6 stock chains
        parsed from the frozen backup input.conf (byte-derived, not hardcoded
        hope)."""
        text = p2.BACKUP_INPUT_CONF.read_text(encoding="utf-8", errors="replace")
        for idx, mode in enumerate(("a", "b", "c", "d", "e", "f"), start=1):
            m = re.search(
                rf"^CTRL\+{idx}\s+no-osd change-list glsl-shaders set \"([^\"]+)\"",
                text, re.M)
            self.assertIsNotNone(m, f"CTRL+{idx} not found in backup input.conf")
            files = [Path(tok).name for tok in m.group(1).split(";")]
            self.assertEqual(files, p2.ANIME4K_CHAINS[mode],
                             f"mode {mode} differs from live CTRL+{idx} chain")
            for f in files:
                self.assertIn(f, p2.ANIME4K_CHAIN_FILES)

    def test_required_keywords_exist_in_stock_files(self):
        """Every required verification keyword is a real //!DESC substring of
        the corresponding stock file's DESC set (compiles → passes appear)."""
        desc_re = re.compile(r"//!DESC (.+)$", re.M)
        all_descs = {}
        for name in p2.ANIME4K_CHAIN_FILES:
            text = (p2.REPO_ANIME4K_DIR / name).read_text(encoding="utf-8")
            all_descs[name] = "\n".join(desc_re.findall(text))
        # 每个模式：required 关键字必须能由该模式链内文件的 DESC 匹配
        for mode, files in p2.ANIME4K_CHAINS.items():
            joined = "\n".join(all_descs[f] for f in files)
            for kw in (p2.ANIME4K_MODE_KEYWORDS[mode]["required"]
                       + p2.ANIME4K_MODE_KEYWORDS[mode]["optional"]):
                self.assertIn(kw, joined,
                              f"mode {mode}: keyword {kw!r} not in chain DESCs")


class TestGuardOracles(unittest.TestCase):
    """Python mirrors of the plugin's guard logic (Lua side via selftest)."""

    def test_rgb_detection(self):
        for fmt in ("rgb24", "rgba", "bgr0", "gbrp", "gbrp10le", "pal8", "RGB24"):
            self.assertTrue(p2.is_rgb_pixfmt(fmt), fmt)
        for fmt in ("yuv420p", "yuv420p10", "nv12", "gray", "yuv444p16le"):
            self.assertFalse(p2.is_rgb_pixfmt(fmt), fmt)
        self.assertFalse(p2.is_rgb_pixfmt(None))
        self.assertFalse(p2.is_rgb_pixfmt(123))

    def test_hdr_detection(self):
        self.assertTrue(p2.is_hdr_gamma("pq"))
        self.assertTrue(p2.is_hdr_gamma("hlg"))
        for g in ("bt.1886", "srgb", "linear", "gamma2.2", None, "pq."):
            self.assertFalse(p2.is_hdr_gamma(g))

    def test_luma_guard_reason(self):
        vo_sdr = {"pixelformat": "yuv420p", "gamma": "bt.1886"}
        vo_rgb = {"pixelformat": "rgb24", "gamma": "srgb"}
        vo_hdr = {"pixelformat": "yuv420p", "gamma": "pq"}
        self.assertIsNone(p2.luma_guard_reason(True, vo_sdr))
        self.assertIn("RGB", p2.luma_guard_reason(True, vo_rgb))
        self.assertIn("HDR", p2.luma_guard_reason(True, vo_hdr))
        # nearest：不设 LUMA 守卫
        self.assertIsNone(p2.luma_guard_reason(False, vo_rgb))
        self.assertIsNone(p2.luma_guard_reason(False, vo_hdr))
        # vo 未知不阻断
        self.assertIsNone(p2.luma_guard_reason(True, None))

    def test_upscale_ratio_uses_window_pixels(self):
        # video-out-params 的 dw/dh 与窗口无关（仅宽高比），不得用于 WHEN 判断
        vo = {"w": 1920, "h": 1080, "dw": 2560, "dh": 1440,
              "osd_w": 1920, "osd_h": 1080}
        self.assertEqual(p2.upscale_ratio(vo), 1.0)
        vo2 = {"w": 640, "h": 360, "dw": 640, "dh": 360, "osd_w": 1280, "osd_h": 720}
        self.assertEqual(p2.upscale_ratio(vo2), 4.0)
        self.assertIsNone(p2.upscale_ratio({"w": 2, "h": 2}))
        self.assertIsNone(p2.upscale_ratio(None))

    def test_upscale_ratio_uses_video_rect_when_letterboxed(self):
        # SHD-1：有黑边时 //!WHEN 的 OUTPUT 是视频显示矩形，不是整窗口
        scope = {"w": 1920, "h": 800, "osd_w": 1920, "osd_h": 1080,
                 "vid_w": 1920, "vid_h": 800}
        self.assertEqual(p2.upscale_ratio(scope), 1.0)
        self.assertFalse(p2.fsr_when_applies(scope))
        self.assertIn("跳过", p2.chain_skip_note("fsr1", scope))
        wide = {"w": 1920, "h": 1080, "osd_w": 1920, "osd_h": 1200,
                "vid_w": 1920, "vid_h": 1080}
        self.assertFalse(p2.fsr_when_applies(wide))
        up = {"w": 1280, "h": 534, "osd_w": 1920, "osd_h": 1080,
              "vid_w": 1920, "vid_h": 801}
        self.assertTrue(p2.fsr_when_applies(up))
        # 矩形未知时回退到窗口像素（视频铺满窗口时二者相等）
        self.assertEqual(p2.upscale_ratio({"w": 640, "h": 360, "osd_w": 1280,
                                           "osd_h": 720, "vid_w": None,
                                           "vid_h": None}), 4.0)

    def test_video_rect_mirror(self):
        self.assertEqual(p2.video_rect({"w": 1920, "h": 1080, "mt": 140,
                                        "mb": 140, "ml": 0, "mr": 0}),
                         (1920, 800))
        self.assertEqual(p2.video_rect({"w": 640, "h": 480}), (640, 480))
        self.assertIsNone(p2.video_rect({"w": 0, "h": 0}))
        self.assertIsNone(p2.video_rect(None))
        self.assertIsNone(p2.video_rect({}))
        self.assertIn("local function video_rect(dims)", LUA_SOURCE)
        self.assertIn("vid_w = vid_w, vid_h = vid_h", LUA_SOURCE)

    def test_fsr_when_and_skip_notes(self):
        up = {"w": 640, "h": 360, "osd_w": 1280, "osd_h": 720}
        same = {"w": 640, "h": 360, "osd_w": 640, "osd_h": 360}
        down = {"w": 640, "h": 360, "osd_w": 320, "osd_h": 180}
        over2 = {"w": 1280, "h": 720, "osd_w": 3840, "osd_h": 2160}
        self.assertTrue(p2.fsr_when_applies(up))
        self.assertFalse(p2.fsr_when_applies(same))
        self.assertFalse(p2.fsr_when_applies(down))
        self.assertIsNone(p2.fsr_when_applies({"w": 2, "h": 2}))
        # ≤1×：真实跳过说明（不报伪 active）
        self.assertIn("跳过", p2.chain_skip_note("fsr1", same))
        self.assertIn("跳过", p2.chain_skip_note("sgsr1", down))
        # >2×：钳制说明
        self.assertIn("2×", p2.chain_skip_note("fsr1", over2))
        # 正常放大：无说明
        self.assertEqual(p2.chain_skip_note("fsr1", up), "")
        # anime4k 无 WHEN 跳过语义
        self.assertEqual(p2.chain_skip_note("anime4k", same), "")


class TestMainChainPolicy(unittest.TestCase):
    """一次仅一主链：整链替换 oracle + nearest 显式策略。"""

    def test_builtin_chains_shape(self):
        chains = p2.expected_builtin_chains("a")
        self.assertEqual(chains["fsr1"], ["~~/shaders/p2-FSR1.glsl"])
        self.assertEqual(chains["sgsr1"], ["~~/shaders/p2-SGSR1.glsl"])
        self.assertEqual(chains["nearest"], [])
        self.assertEqual(len(chains["anime4k"]), 6)
        for entry in chains["anime4k"]:
            self.assertTrue(entry.startswith("~~/shaders/anime4k/Anime4K_"))

    def test_switch_replaces_whole_property(self):
        """registered P2 gears are whole-property replacements (brief 纠正): the
        written glsl-shaders list is EXACTLY the new recipe — including the
        first takeover over a pre-existing Anime4K baseline (never appended;
        the user's original chain lives in the snapshot/baseline, restored by
        关 while unmodified). The earlier draft expectation of keeping
        user-external.glsl on top of the new main chain is superseded."""
        a4k = p2.anime4k_chain_paths("a")
        current = ["~~/user-external.glsl"] + a4k   # off 状态下已有原 Anime4K 链
        # oracle: the activation writes exactly the registered recipe
        self.assertEqual(p2.expected_builtin_chain_write("fsr1"),
                         ["~~/shaders/p2-FSR1.glsl"])
        self.assertEqual(p2.expected_builtin_chain_write("sgsr1"),
                         ["~~/shaders/p2-SGSR1.glsl"])
        # Nearest空shader列表：整 property 替换为空列表
        self.assertEqual(p2.expected_builtin_chain_write("nearest"), [])
        self.assertEqual(p2.expected_builtin_chain_write("anime4k"), a4k)
        # 静态：Lua 注册表四个内建档位均为 whole=true，plan 走整链分支
        for gid in p2.P2_BUILTIN_IDS:
            self.assertRegex(LUA_SOURCE, rf'\{{ id = "{gid}".*whole = true')
        self.assertIn('if gear.whole then', LUA_SOURCE)
        # P1 元素级 oracle 仍存在（明确兼容模式，仅用于 p1-test-* 桩）
        new_list = lib.expected_gear_list(current, a4k, adds=["~~/shaders/p2-FSR1.glsl"])
        self.assertEqual(new_list,
                         ["~~/user-external.glsl", "~~/shaders/p2-FSR1.glsl"])
        self.assertIn("compat", lib.expected_off_actions.__doc__ or "")

    def test_off_whole_chain_restore_and_external_preserve(self):
        """关 oracle (registered whole chain): unmodified → restore the complete
        baseline Anime4K chain; externally modified → keep the user's COMPLETE
        list (a re-added same-name entry must never be removed by path string)."""
        a4k = p2.anime4k_chain_paths("a")
        fsr = ["~~/shaders/p2-FSR1.glsl"]
        baseline = {"glsl-shaders": a4k, "scale": "bicubic"}
        last = {"glsl-shaders": fsr, "scale": "bilinear"}
        wrote = {"glsl-shaders": True, "scale": True}
        # still owned & equal to last_written → complete baseline restored
        restores, kept, notes = p2.expected_off_actions_whole(
            baseline, last, wrote, {"glsl-shaders": fsr, "scale": "bilinear"})
        self.assertEqual(restores["glsl-shaders"], a4k)
        self.assertEqual(restores["scale"], "bicubic")
        self.assertEqual(kept, {})
        # external whole-property modification → user's COMPLETE list kept
        ext = ["~~/shaders/p2-FSR1.glsl", "~~/user-new.glsl"]
        restores2, kept2, notes2 = p2.expected_off_actions_whole(
            baseline, last, wrote, {"glsl-shaders": ext, "scale": "spline36"})
        self.assertEqual(kept2.get("glsl-shaders"), ext)
        self.assertNotIn("glsl-shaders", restores2)
        self.assertTrue(any("完整列表" in n for n in notes2))
        self.assertEqual(kept2.get("scale"), "spline36")
        # 用户重新添加的同名条目不凭路径字符串删除：外部把列表改为
        # [用户条目, 同名条目]，与 last_written 不同 → 完整保留，同名条目幸存
        remixed = ["~~/user-other.glsl", "~~/shaders/p2-FSR1.glsl"]
        restores3, kept3, notes3 = p2.expected_off_actions_whole(
            baseline, last, wrote, {"glsl-shaders": remixed})
        self.assertEqual(kept3.get("glsl-shaders"), remixed)
        self.assertIn("~~/shaders/p2-FSR1.glsl", kept3["glsl-shaders"])
        # 与 last_written 相同的列表 = 仍 owned → 恢复基线（而非保留）
        restores4, kept4, _ = p2.expected_off_actions_whole(
            baseline, last, wrote, {"glsl-shaders": ["~~/shaders/p2-FSR1.glsl"]})
        self.assertEqual(restores4.get("glsl-shaders"), a4k)
        self.assertNotIn("glsl-shaders", kept4)

    def test_nearest_explicit_policy_in_lua_source(self):
        """nearest 内建三值显式（scale/cscale/dscale 全 nearest），非隐式。"""
        self.assertIn('value = "nearest"', LUA_SOURCE)
        for prop in ("scale", "cscale", "dscale"):
            self.assertRegex(
                LUA_SOURCE,
                rf'prop = "{prop}", op = "set", value = "nearest"')
        # p2_lib 镜像一致：nearest 无 shader、无 LUMA 守卫
        self.assertNotIn("nearest", p2.LUMA_GEAR_IDS)
        self.assertIn("nearest", p2.P2_BUILTIN_IDS)

    def test_anime4k_is_main_hdr_guarded(self):
        """SHD-2: anime4k hooks MAIN/PREKERNEL only — RGB allowed, HDR refused."""
        hooks = set()
        for f in (lib.REPO_ROOT / "shaders" / "anime4k").glob("*.glsl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("//!HOOK"):
                    hooks.add(line.split()[1])
        self.assertTrue(hooks)
        self.assertNotIn("LUMA", hooks)
        lua_block = LUA_SOURCE[LUA_SOURCE.index("local BUILTIN_GEARS"):
                               LUA_SOURCE.index("local BUILTIN_BY_ID")]
        self.assertRegex(lua_block, r'\{ id = "anime4k",.*luma = false, hdr = true')
        self.assertNotIn("anime4k", p2.LUMA_GEAR_IDS)
        self.assertIn("anime4k", p2.HDR_GUARD_GEAR_IDS)

    def test_luma_gear_sets_match_lua(self):
        """Python/Lua mirror consistency for the LUMA guard set."""
        lua_block = LUA_SOURCE[LUA_SOURCE.index("local BUILTIN_GEARS"):
                               LUA_SOURCE.index("local BUILTIN_BY_ID")]
        for gid in p2.LUMA_GEAR_IDS:
            self.assertRegex(lua_block,
                             rf'\{{ id = "{gid}".*luma = true')
        self.assertNotRegex(lua_block, r'\{ id = "nearest".*luma = true')


class TestP2StaticAudits(unittest.TestCase):
    """Static source audits (P2 extensions over p1_lib)."""

    def test_p1_audits_still_hold(self):
        audit = lib.audit_plugin_source()
        for key, ok in audit.items():
            self.assertTrue(ok, f"plugin source audit failed: {key}")

    def test_p2_gears_conf_audit(self):
        checks = lib.audit_gears_conf()
        for key, ok in checks.items():
            self.assertTrue(ok, f"gears conf audit failed: {key}")
        checks2 = p2.audit_gears_conf_p2()
        for key, ok in checks2.items():
            self.assertTrue(ok, f"P2 gears conf audit failed: {key}")

    def test_off_label_is_const_in_lua(self):
        """V2-01 修复在源码层：off 显示名为常量「关」，conf 值被忽略并告警。"""
        self.assertIn('local OFF_LABEL = "关"', LUA_SOURCE)
        self.assertIn("gear.label = OFF_LABEL", LUA_SOURCE)
        self.assertIn("off_label=" , LUA_SOURCE)  # 告警文案覆盖 off_label 覆盖
        self.assertIn("被忽略：off 显示名固定为", LUA_SOURCE)

    def test_missing_vs_not_regular_file_wording(self):
        """REV-02 同域修复：资源预检文案区分文件缺失 vs 非常规文件。"""
        self.assertIn("shader 文件缺失", LUA_SOURCE)
        self.assertIn("shader 路径是目录而非常规文件", LUA_SOURCE)

    def test_external_switch_refusal_wording(self):
        """external 状态下拒绝直接换档（提示先 Off），不静默接管。"""
        self.assertIn("请先选择〔", LUA_SOURCE)
        self.assertIn("插件不会静默覆盖", LUA_SOURCE)

    def test_guard_and_skip_wording(self):
        self.assertIn("RGB 输入", LUA_SOURCE)
        self.assertIn("HDR 输入", LUA_SOURCE)
        self.assertIn("按 //!WHEN 跳过", LUA_SOURCE)
        self.assertIn("链验证", LUA_SOURCE)

    def test_no_extra_key_bindings(self):
        """CTRL+1..6/F7 等外部键不得被插件占用；仅 F8 菜单键。"""
        self.assertEqual(LUA_SOURCE.count("add_key_binding("), 1)
        for k in ("CTRL+1", "CTRL+2", "CTRL+3", "CTRL+6", "F7", "F5"):
            self.assertNotIn(f'add_key_binding("{k}"', LUA_SOURCE)
            self.assertNotIn(f'add_forced_key_binding("{k}"', LUA_SOURCE)

    def test_stage_export_follows_stage_registry(self):
        # 原 test_stage_export_is_p2 —— P3 注册表迁移（非删除/非弱化：
        # 测试数量不变，断言严格性保留为“导出必须逐字节等于当前阶段标记”）。
        # 原断言在 P2 阶段要求导出 == "P2"；P3 阶段唯一合法目标态是 "P3"
        # （与 test_p3_support.test_stage_export_is_p3 同一目标态；旧 "P2"
        # 或任意其他值都不过）。迁移理由见 tests/test_p3_support.py 模块
        # docstring 与 docs/P3/P3实施计划.json write_path_notes(c)③。
        self.assertIn('user_data_set("stage", "P3")', LUA_SOURCE)
        self.assertNotIn('user_data_set("stage", "P2")', LUA_SOURCE)


class TestP2Media(unittest.TestCase):
    def test_y4m_10bit_wellformed_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.y4m"
            b = Path(tmp) / "b.y4m"
            s1 = p2.generate_y4m(a, w=64, h=64, frames=4, ten_bit=True)
            s2 = p2.generate_y4m(b, w=64, h=64, frames=4, ten_bit=True)
            self.assertEqual(s1, s2)
            head = a.read_bytes()[:60]
            self.assertTrue(head.startswith(b"YUV4MPEG2 W64 H64"))
            self.assertIn(b"C420p10", head)
            frame_bytes = 64 * 64 * 2 + 2 * (32 * 32 * 2)
            self.assertEqual(a.stat().st_size,
                             head.index(b"\n") + 1 + 4 * (len(b"FRAME\n") + frame_bytes))

    def test_y4m_8bit_still_p1_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.y4m"
            p2.generate_y4m(p, w=320, h=240, frames=4)
            self.assertIn(b"C420jpeg", p.read_bytes()[:60])

    def test_ppm_p6_wellformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.ppm"
            sha = p2.generate_ppm(p, w=64, h=32)
            raw = p.read_bytes()
            header = b"P6\n64 32\n255\n"
            self.assertTrue(raw.startswith(header))
            # PPM 草稿曾误断言 payload 为空（与下一行尺寸断言矛盾，brief 根因修复）:
            # 正确核法 = payload 长度 + 像素字节范围 + 确定性 sha
            payload = raw[len(header):]
            self.assertEqual(len(payload), 64 * 32 * 3)
            self.assertTrue(all(b <= 255 for b in payload[:4096]))
            self.assertNotEqual(payload[:16], bytes(16), "all-black header-only?")
            self.assertEqual(sha, lib.sha256_file(p))


class TestIsolatedP2Env(unittest.TestCase):
    def test_input_conf_stock_block_and_no_f8(self):
        text = p2.p2_input_conf_text()
        for idx in range(1, 7):
            self.assertIn(f"CTRL+{idx} ", text)
            self.assertIn("change-list glsl-shaders set", text)
        self.assertNotIn("F8", text)
        # 隔离副本路径指向隔离 shaders/anime4k/
        self.assertIn("~~/shaders/anime4k/Anime4K_Clamp_Highlights.glsl", text)
        # 与 stock 等效：每条 set 的文件序列与 ANIME4K_CHAINS 一致
        for idx, mode in enumerate(("a", "b", "c", "d", "e", "f"), start=1):
            m = re.search(rf"^CTRL\+{idx} no-osd change-list glsl-shaders set \"([^\"]+)\"",
                          text, re.M)
            self.assertEqual([Path(t).name for t in m.group(1).split(";")],
                             p2.ANIME4K_CHAINS[mode])

    def test_install_p2_resources_copies_and_can_break(self):
        env = lib.make_env("unittest-p2res", session="p2-001")
        try:
            p2.install_p2_resources(env)
            for name in p2.ANIME4K_CHAIN_FILES:
                dst = env.cfg / "shaders" / "anime4k" / name
                self.assertTrue(dst.is_file())
                self.assertEqual(lib.sha256_file(dst),
                                 lib.sha256_file(p2.REPO_ANIME4K_DIR / name))
            self.assertTrue((env.cfg / p2.REPO_FSR_PATH).is_file())
            p2.install_p2_resources(env, broken={"fsr1": p2.BROKEN_SYNTAX_GLSL})
            # 损坏 fixture 只进隔离目录，发布目录不受影响
            broken = (env.cfg / p2.REPO_FSR_PATH).read_text(encoding="utf-8")
            self.assertIn("p2-test broken", broken)
            self.assertNotIn("p2-test broken",
                             (REPO_ROOT / p2.REPO_FSR_PATH).read_text(encoding="utf-8"))
        finally:
            env.cleanup()

    def test_fixtures_outside_release_dir(self):
        fixtures = REPO_ROOT / "tests" / "fixtures" / "p2"
        self.assertTrue((fixtures / "broken-syntax.glsl").is_file())
        self.assertTrue((fixtures / "bad-param.glsl").is_file())
        for name in ("broken-syntax", "bad-param"):
            text = (fixtures / (name + ".glsl")).read_text(encoding="utf-8")
            self.assertIn("测试桩", text)
        # 发布 shaders/ 目录中不存在损坏物
        release = list((REPO_ROOT / "shaders").rglob("*broken*")) + \
            list((REPO_ROOT / "shaders").rglob("*bad-param*"))
        self.assertEqual(release, [])

    def test_broken_fixture_is_actually_broken(self):
        """缺分号 = 真实编译错误（此前探针证明 ;;;; 空语句会编译通过）。"""
        text = (REPO_ROOT / "tests/fixtures/p2/broken-syntax.glsl").read_text(encoding="utf-8")
        self.assertRegex(text, r"HOOKED_tex\(HOOKED_pos\) \}")


class TestV4FallbackDefaultRegistry(unittest.TestCase):
    """V4-FALLBACK（brief-v4）：缺失/空 gears= 两条回退路径都必须得到完整
    12 档内建默认表（含 sharpbilinear2x），与发布 conf 的 gears= 行同序同源，
    off/LS1/BCAS 身份边界不削。本类为源码层漂移门卫；行为级负例（三条回退
    路径 + 唯二 disabled）在真实 Lua selftest（V4-FALLBACK 回归用例）中运行。"""

    def test_single_default_registry_matches_shipped_conf(self):
        conf = lib.GEARS_CONF.read_text(encoding="utf-8")
        m = re.search(r"^gears=(.+)$", conf, re.M)
        self.assertIsNotNone(m, "shipped gears conf lost its gears= line")
        shipped = [t.strip() for t in m.group(1).split(",") if t.strip()]
        self.assertEqual(len(shipped), 12, f"shipped registry changed: {shipped}")
        self.assertEqual(shipped[0], "off")
        self.assertIn("sharpbilinear2x", shipped)
        lua_ids = re.search(r"local DEFAULT_GEARS_IDS = \{(.*?)\}", LUA_SOURCE, re.S)
        self.assertIsNotNone(lua_ids, "Lua DEFAULT_GEARS_IDS table missing")
        tokens = [t.strip() for t in lua_ids.group(1).split(",") if t.strip()]
        self.assertEqual(tokens[0], "OFF_ID", "first default entry must be OFF_ID")
        ids = ["off"] + re.findall(r'"([a-z0-9-]+)"', lua_ids.group(1))
        self.assertEqual(ids, shipped, "Lua fallback registry drifted from shipped conf")

    def test_both_fallback_paths_route_through_registry(self):
        self.assertIn('gears_raw = table.concat(DEFAULT_GEARS_IDS, ",")', LUA_SOURCE)
        self.assertIn(
            "for _, def_id in ipairs(DEFAULT_GEARS_IDS) do ids[#ids + 1] = def_id end",
            LUA_SOURCE)
        # 旧的 11 项字面量不得再出现（两条回退各自写死的旧根因）
        self.assertNotIn(
            '"off,ls1,fsr1,nis,sgsr1,bcas,anime4k,xbr,sharpbilinear,integer,nearest"',
            LUA_SOURCE)

    def test_selftest_covers_missing_and_empty_fallback_negatives(self):
        for marker in ("fallback: missing gears=",
                       "fallback: empty gears= value",
                       "fallback: gears= with no valid token",
                       "default_flags_ok(m_missing)"):
            self.assertIn(marker, LUA_SOURCE,
                          f"Lua selftest missing V4-FALLBACK negative: {marker}")
        # 身份边界不削：off 恒 active、LS1/BCAS 占位 disabled、sharp2x 内建 whole
        self.assertIn('m.by_id["off"].mode == "active"', LUA_SOURCE)
        self.assertIn('m.by_id["ls1"].mode == "disabled"', LUA_SOURCE)
        self.assertIn('m.by_id["bcas"].mode == "disabled"', LUA_SOURCE)
        self.assertIn('s2x.set[1].value == "~~/shaders/p3-Sharp-Bilinear-2x.glsl"',
                      LUA_SOURCE)


class _FakeVoPassSession:
    """Minimal session double for wait_new_chain_pass_positive: serves a
    scripted sequence of vo-passes fresh counts, then holds the last value."""

    def __init__(self, seq_counts, keyword="KW"):
        self._seq = list(seq_counts)
        self._n = 0
        self._last = 0
        self._keyword = keyword
        self.polls = 0

    def _frame(self, count):
        return {"fresh": [{"desc": f"{self._keyword} pass",
                           "samples": [1.0]}] * count,
                "redraw": []}

    def get(self, prop):
        assert prop == "vo-passes"
        self.polls += 1
        if self._n < len(self._seq):
            self._last = self._seq[self._n]
            self._n += 1
        return self._frame(self._last)

    def wait_until(self, predicate, timeout_s: float, poll: float = 0.0) -> bool:
        import time
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(poll)
        return False


class TestV4PassRaceNewChainProof(unittest.TestCase):
    """V4-PASS-RACE（brief-v4）：链替换后属性读回先于新链首帧渲染，过早计数
    把陈旧计数竞态误报为 FAIL（full-r1 stock 0 vs gear 20/28）。辅助函数必须
    等到新链 //!DESC + 非空 samples 的正计数出现；0==0 必须被拒绝。"""

    def test_delayed_new_pass_is_waited_for_and_counted(self):
        import p2_verify
        s = _FakeVoPassSession([0, 0, 3])
        proof = p2_verify.wait_new_chain_pass_positive(s, ("KW",), timeout_s=2.0)
        self.assertTrue(proof["new_chain_passes_present"])
        self.assertTrue(proof["count_positive"])
        self.assertEqual(proof["pass_count"], 3)
        self.assertGreaterEqual(s.polls, 3)

    def test_zero_zero_is_rejected(self):
        import p2_verify
        s = _FakeVoPassSession([0])
        proof = p2_verify.wait_new_chain_pass_positive(s, ("KW",), timeout_s=0.3)
        self.assertFalse(proof["new_chain_passes_present"])
        self.assertFalse(proof["count_positive"])
        self.assertEqual(proof["pass_count"], 0)


if __name__ == "__main__":
    unittest.main()
