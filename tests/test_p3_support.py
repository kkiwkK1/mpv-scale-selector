# -*- coding: utf-8 -*-
"""P3 unit tests — support layer (tests/test_p3_support.py): the P3 registry
mirror vs the Lua source, plugin static audits, harness-fix regression pins
(P2R-F1/F2, P2S-01, VL-F1, P2S-04), fixtures, and synthetic media helpers.
Fast, stdlib-only, never launches mpv.

注册表迁移说明（P3，逐条；不改旧断言语义，只随注册表目标态迁移）：
  * tests/test_p2_support.py 的 test_stage_export_is_p2 断言 Lua 导出
    "P2" —— P3 目标态导出 "P3"，该断言随迁移更新（同文件在 P3 write_paths
    白名单内，逐条注释；P2 语义不被弱化：stage 导出仍必须等于当前阶段）。
  * 其余 P2 断言（stock/FSR/SGSR/守卫/整链）与 P3 无冲突，保持零改动。
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p1_lib as lib   # noqa: E402
import p2_lib as p2    # noqa: E402
import p3_lib as p3    # noqa: E402
import p1_verify as p1v  # noqa: E402

LUA_SOURCE = lib.PLUGIN_LUA.read_text(encoding="utf-8")

P3_IDS = ("nis", "xbr", "sharpbilinear", "sharpbilinear2x", "integer")


class TestP3RegistryMirror(unittest.TestCase):
    """The Python mirror must pin the Lua BUILTIN_GEARS registry."""

    def test_lua_registry_contains_five_new_builtins(self):
        start = LUA_SOURCE.index("local BUILTIN_GEARS = {")
        end = LUA_SOURCE.index("local BUILTIN_BY_ID", start)
        block = LUA_SOURCE[start:end]
        for gid in P3_IDS:
            self.assertRegex(block, rf'\{{ id = "{gid}",', msg=gid)
        for gid in ("ls1", "bcas"):
            self.assertNotRegex(block, rf'\{{ id = "{gid}",', msg=gid)

    def test_placeholder_registry_is_exactly_ls1_bcas(self):
        # 限域接续修正（brief 根因6）：原提取用 index("}", start) 停在第一条
        # 记录 ls1 的内部右括号，块内永远不含 bcas，正负断言都失真。改为用
        # 下一顶层声明（local BUILTIN_GEARS）作表终点锚，块 = 完整
        # PLACEHOLDER_GEARS 表；并新增“恰好 2 条记录”计数断言，使“exactly
        # ls1+bcas”真正可判定。新增五内建不在占位表的负断言保留。
        start = LUA_SOURCE.index("local PLACEHOLDER_GEARS = {")
        end = LUA_SOURCE.index("local BUILTIN_GEARS = {", start)
        block = LUA_SOURCE[start:end]
        self.assertRegex(block, r'\{ id = "ls1",')
        self.assertRegex(block, r'\{ id = "bcas",')
        self.assertEqual(len(re.findall(r'\{ id = "', block)), 2)
        for gid in P3_IDS:
            self.assertNotIn(f'id = "{gid}"', block)

    def test_flags(self):
        lua_block = LUA_SOURCE[LUA_SOURCE.index("local BUILTIN_GEARS = {"):
                               LUA_SOURCE.index("local BUILTIN_BY_ID")]
        self.assertRegex(lua_block, r'\{ id = "nis",.*luma = true')
        self.assertNotRegex(lua_block, r'\{ id = "nis",.*hdr = true')
        for gid in ("xbr", "sharpbilinear", "sharpbilinear2x"):
            self.assertRegex(lua_block, rf'\{{ id = "{gid}",.*hdr = true', msg=gid)
            self.assertNotRegex(lua_block, rf'\{{ id = "{gid}",.*luma = true', msg=gid)
        self.assertRegex(lua_block, r'\{ id = "integer",.*whole = true')
        self.assertIn('id = "integer"', lua_block)
        # integer geometry placeholder entries exist for snapshot coverage
        self.assertIn('{ prop = "video-unscaled", op = "integer-geom" }', LUA_SOURCE)
        self.assertIn('{ prop = "video-zoom", op = "integer-geom" }', LUA_SOURCE)
        # plan refuses to run the placeholder op outside activation
        self.assertIn("integer 几何写入值必须在激活时按 k 计算", LUA_SOURCE)

    def test_expected_chains_match_lua(self):
        chains = p3.expected_builtin_chains_p3()
        for gid, recipe in chains.items():
            for entry in recipe:
                self.assertIn(f'value = "{entry}"', LUA_SOURCE, gid)
        self.assertIn('value = "~~/shaders/p3-NIS.glsl"', LUA_SOURCE)

    def test_desc_keywords_mirror(self):
        pairs = [
            ("nis", p3.NIS_DESC_KEYWORDS[0]),
            ("xbr", p3.XBR_DESC_KEYWORDS[0]),
            ("sharpbilinear", p3.SHARP_AUTO_DESC_KEYWORDS[0]),
            ("sharpbilinear2x", p3.SHARP_2X_DESC_KEYWORDS[0]),
        ]
        for gid, kw in pairs:
            self.assertIn(f'keywords = {{ "{kw}" }}', LUA_SOURCE, msg=gid)
            self.assertIn(kw, (REPO_ROOT / dict(
                nis="shaders/p3-NIS.glsl",
                xbr="shaders/p3-xBR-lv2.glsl",
                sharpbilinear="shaders/p3-Sharp-Bilinear-AUTO.glsl",
                sharpbilinear2x="shaders/p3-Sharp-Bilinear-2x.glsl")[gid])
                .read_text(encoding="utf-8"))

    def test_default_gears_text_new_target_state(self):
        m = re.search(r"local DEFAULT_GEARS_TEXT = \[\[(.*?)\]\]", LUA_SOURCE, re.S)
        self.assertIsNotNone(m)
        text = m.group(1)
        gm = re.search(r"^gears=(.+)$", text, re.M)
        members = [t.strip() for t in gm.group(1).split(",")]
        self.assertEqual(members, ["off", "ls1", "fsr1", "nis", "sgsr1", "bcas",
                                   "anime4k", "xbr", "sharpbilinear",
                                   "sharpbilinear2x", "integer", "nearest"])
        # new builtins: NO override keys in the default text
        for gid in P3_IDS:
            for suffix in ("_mode", "_label", "_reason", "_set"):
                self.assertNotIn(gid.replace("-", "_") + suffix + "=", text)
        # placeholders keep their disabled entries
        self.assertIn("ls1_mode=disabled", text)
        self.assertIn("bcas_mode=disabled", text)

    def test_hdr_guard_is_independent_function(self):
        self.assertIn("local function hdr_guard_reason", LUA_SOURCE)
        self.assertIn("local function activation_guard_reason", LUA_SOURCE)
        # runtime guard call sites use the unified entry
        self.assertNotIn("luma_guard_reason(gear.luma, vo)", LUA_SOURCE)
        self.assertNotIn("luma_guard_reason(gear.luma, S.vo)", LUA_SOURCE)
        self.assertIn("activation_guard_reason(gear, vo)", LUA_SOURCE)
        self.assertIn("activation_guard_reason(gear, S.vo)", LUA_SOURCE)

    def test_integer_dynamic_geometry_wiring(self):
        self.assertIn("local function integer_k(vo)", LUA_SOURCE)
        self.assertIn("integer_gear_for_activation", LUA_SOURCE)
        self.assertIn("integer_reapply_geometry = function(gear)", LUA_SOURCE)
        # recompute hook fires on guard context change
        self.assertIn("if gear.integer then\n                    integer_reapply_geometry(gear)",
                      LUA_SOURCE)
        # user-data export for objective verification
        self.assertIn('user_data_set("integer_k", S.integer_k)', LUA_SOURCE)

    def test_guard_props_include_osd(self):
        self.assertIn('"osd-width", "osd-height"', LUA_SOURCE)
        # SHD-1：osd-dimensions（视频显示矩形）纳入守卫观察与 journal 允许集
        self.assertIn('"osd-width", "osd-height", "osd-dimensions" }', LUA_SOURCE)
        self.assertIn("osd-dimensions", lib.ALLOWED_JOURNAL_PROPS)

    def test_script_messages_and_menu_keys(self):
        """UX-1/UX-5/LUA-4: direct-switch messages; every forced menu binding
        added in open_menu is removed in close_menu; pending chain is nil."""
        self.assertIn('register_script_message("scale-selector-set", on_set_message)', LUA_SOURCE)
        self.assertIn('register_script_message("scale-selector-cycle", on_cycle_message)', LUA_SOURCE)
        open_body = LUA_SOURCE[LUA_SOURCE.index("open_menu = function()"):
                               LUA_SOURCE.index("close_menu = function()")]
        close_body = LUA_SOURCE[LUA_SOURCE.index("close_menu = function()"):]
        close_body = close_body[:close_body.index("\nend\n")]
        names = re.findall(r'add_forced_key_binding\("[A-Z_]+", "([a-z-]+)"', open_body)
        self.assertIn("scale-selector-activate-kp", names)
        for name in names:
            self.assertIn(f'"{name}"', close_body, name)
        self.assertNotIn("#gear.keywords > 0) and nil or true", LUA_SOURCE)

    def test_integer_plan_precedes_takeover_snapshot(self):
        """LUA-3: an Integer plan failure (e.g. idle, no video) must return
        BEFORE take_snapshot, so no takeover/baseline leaks while state=off."""
        start = LUA_SOURCE.index("activate_gear = function(gear_id, opts)")
        end = LUA_SOURCE.index("do_off = function()", start)
        body = LUA_SOURCE[start:end]
        self.assertLess(body.index("integer_gear_for_activation(gear, read_vo_params())"),
                        body.index("take_snapshot(props)"))
        # integer_k 只在计划成功时更新
        fn = LUA_SOURCE[LUA_SOURCE.index("local function integer_gear_for_activation"):]
        fn = fn[:fn.index("\nend\n")]
        self.assertLess(fn.index("if k == nil then"), fn.index("S.integer_k = k"))

    def test_stage_export_is_p3(self):
        # P3 迁移（见模块 docstring）：导出必须等于当前阶段
        self.assertIn('user_data_set("stage", "P3")', LUA_SOURCE)
        self.assertNotIn('user_data_set("stage", "P2")', LUA_SOURCE)

    def test_luma_gear_set_extended_with_nis(self):
        self.assertIn("nis", p3.LUMA_GEAR_IDS_P3)
        for gid in ("xbr", "sharpbilinear", "sharpbilinear2x", "integer"):
            self.assertNotIn(gid, p3.LUMA_GEAR_IDS_P3)
            self.assertNotIn(gid, p2.LUMA_GEAR_IDS)


class TestP3PluginSourceAudits(unittest.TestCase):
    def test_p1_static_audits_still_hold(self):
        audit = lib.audit_plugin_source()
        for key, ok in audit.items():
            self.assertTrue(ok, f"plugin source audit failed: {key}")

    def test_no_extra_key_bindings(self):
        # M-10③ 对齐：两份同名测试取并集——本拷贝此前已漂移（缺
        # CTRL+3/CTRL+6），现与 tests/test_p2_support.py 的键名单一致。
        # 刻意不做单点收敛（保留各阶段断言域），对齐本身即并集。
        self.assertEqual(LUA_SOURCE.count("add_key_binding("), 1)
        for k in ("CTRL+1", "CTRL+2", "CTRL+3", "CTRL+6", "F7", "F5"):
            self.assertNotIn(f'add_key_binding("{k}"', LUA_SOURCE)
            self.assertNotIn(f'add_forced_key_binding("{k}"', LUA_SOURCE)

    def test_no_glsl_shaders_clr(self):
        code_only = "\n".join(ln for ln in LUA_SOURCE.splitlines()
                              if not ln.strip().startswith("--"))
        self.assertNotIn("glsl-shaders-clr", code_only)
        self.assertNotIn("change-list", code_only)

    def test_no_nvsharpen_anywhere_in_plugin(self):
        # 限域接续修正（brief 根因5）：原断言对整份 Lua 源禁 “NVSharpen”
        # 字样，会误拒头部正当的禁止性说明文字（“内含锐化，绝不叠
        # NVSharpen”）。语义修为核真实产物而非说明文本：
        #   1) 真实注册 recipe（expected_builtin_chains_p3 全部条目）不得
        #      引用任何 NVSharpen 资源路径；
        #   2) 真实 DESC：NIS 注册关键词必须是 NIS 自己的 DESC，且任何注册
        #      关键词都不是 NVSharpen 的 DESC（“NVIDIA Image Sharpening
        #      v1.0.2”，docs/证据/port-NVSharpen.glsl:31）；
        #   3) 代码行（非注释行）零 NVSharpen 引用——说明注释允许，代码
        #      引用禁止。
        nvs_desc = "NVIDIA Image Sharpening v1.0.2"
        for gid, recipe in p3.expected_builtin_chains_p3().items():
            for entry in recipe:
                self.assertNotIn("NVSharpen", entry, gid)
        nis_kw = p3.NIS_DESC_KEYWORDS[0]
        self.assertEqual(nis_kw, "NVIDIA Image Scaling and Sharpening v1.0.2")
        self.assertNotEqual(nis_kw, nvs_desc)
        all_kw = (p3.NIS_DESC_KEYWORDS + p3.XBR_DESC_KEYWORDS
                  + p3.SHARP_AUTO_DESC_KEYWORDS + p3.SHARP_2X_DESC_KEYWORDS)
        for kw in all_kw:
            self.assertNotIn(nvs_desc, kw)
        code_only = "\n".join(ln for ln in LUA_SOURCE.splitlines()
                              if not ln.strip().startswith("--"))
        self.assertNotIn("NVSharpen", code_only)


class TestP3SelftestCoverage(unittest.TestCase):
    """The embedded Lua selftest must cover the P3 additions."""

    def test_selftest_has_p3_cases(self):
        for marker in ("p3-builtin:", "p3-pure:", "p3-guard:", "p3-note:",
                       "p3-plan:"):
            self.assertIn(marker, LUA_SOURCE, msg=marker)

    def test_selftest_case_count_increased(self):
        self.assertGreaterEqual(LUA_SOURCE.count('tc("'), 100)


class TestP3HarnessFixPins(unittest.TestCase):
    """Regression pins for the three P2 harness root causes + VL-F1/P2S-04."""

    def test_p2s01_user_shader_count_desc_samples(self):
        """The shared counter counts DESC keyword hits with non-empty samples
        when keywords are given; the bare substring branch is stub-only."""
        src = Path(p1v.__file__).read_text(encoding="utf-8")

        class FakeS:
            def get(self, name):
                return {"fresh": [
                    {"desc": "NVIDIA Image Scaling and Sharpening v1.0.2",
                     "count": 5, "samples": [1.0, 2.0]},
                    {"desc": "user shader", "count": 3, "samples": []},
                ], "redraw": []}

        self.assertEqual(p1v.user_shader_pass_count(FakeS(), keywords=[
            "NVIDIA Image Scaling and Sharpening v1.0.2"]), 1)
        # stub branch counts the DESC-less label (never for product gears)
        self.assertEqual(p1v.user_shader_pass_count(FakeS()), 1)
        self.assertEqual(p1v.user_shader_pass_count(FakeS(), keywords=["absent"]), 0)

    def test_p2r_f1_take_screenshot_binds_state(self):
        # P2R-F1 行为级（M-10②，brief 根因1）：不能以 p1_verify 源码含
        # seen_hashes/"before"/true_bitdepth_parser 等常见单词的存在性充当
        # 回归钉（几乎不可能失败）。改走真实 take_screenshot + 记录型 fake
        # session（截图写出真实 PNG 字节，仿同文件 same_moment 示范）：
        #   * 截图前后各观察一次观察窗：state/chain_epoch/frame_counts 同入
        #     一条 entry（frame_counts 为 fresh/redraw count 真实求和）；
        #   * PNG 尺寸/位深由真实 8/16 位解析器记录（true_bitdepth_parser），
        #     sha256 为文件真实哈希，返回仓库相对路径（非幻影）；
        #   * 重复字节 + seen_hashes → 重拍一次仍相同 → 诚实标注
        #     non_corroborative（相同字节永不冒充独立证据）；
        #   * 截图失败 → not_generated 且返回 None，不产生幻影路径。
        import p3_verify as _pv
        tmp = tempfile.TemporaryDirectory(dir=REPO_ROOT)
        self.addCleanup(tmp.cleanup)
        ev = lib.Evidence(Path(tmp.name) / "ev")
        png_a = _pv._evi_make_png(8, 6, salt=1)

        class FakeShotSession:
            """记录型 fake：vo-passes 计数序列 + 真实 PNG 截图；create-only
            预检复用 p1_lib.MpvSession 的真实实现。"""

            ensure_screenshot_target = staticmethod(
                lib.MpvSession.ensure_screenshot_target)

            def __init__(self, pngs, counts, capture_ok=True):
                self._pngs = list(pngs)      # 每次截图依次写出的字节
                self._counts = list(counts)  # 每次观察 vo-passes 的计数序列
                self._cur = (0, 0)
                self._ok = capture_ok
                self.shots = []

            def _obs_key(self, name):
                assert name in ("vo-passes", "state", "chain_epoch"), name

            def get(self, name):
                self._obs_key(name)
                if self._counts:
                    self._cur = self._counts.pop(0)
                fresh, redraw = self._cur
                return {"fresh": [{"desc": "d", "count": fresh,
                                   "samples": [1.0]}],
                        "redraw": [{"desc": "r", "count": redraw}]}

            def ud(self, key):
                self._obs_key(key)
                return {"state": "active", "chain_epoch": 3}[key]

            def screenshot(self, path, mode="subtitles"):
                self.ensure_screenshot_target(path)
                self.shots.append((str(path), mode))
                if not self._ok:
                    return False
                Path(path).write_bytes(
                    self._pngs.pop(0) if self._pngs else png_a)
                return True

        # 1) 成功路径：观察窗绑定 + 真实 PNG 解析 + 真实哈希
        s = FakeShotSession(pngs=[png_a], counts=[(5, 2), (5, 2)])
        variant = {}
        got = p1v.take_screenshot(s, ev, "p2r-f1-ok.png", variant)
        entry = variant["screenshot"]
        self.assertTrue(got)
        self.assertTrue((lib.REPO_ROOT / got).is_file())
        self.assertEqual(entry["before"],
                         {"state": "active", "chain_epoch": 3,
                          "frame_counts": {"fresh": 5, "redraw": 2}})
        self.assertEqual(entry["after"]["frame_counts"],
                         {"fresh": 5, "redraw": 2})
        self.assertEqual(entry["before"]["state"], entry["after"]["state"])
        self.assertTrue(entry["command_ok"] and entry["captured"])
        self.assertFalse(entry["not_generated"])
        self.assertEqual((entry["png"]["w"], entry["png"]["h"],
                          entry["png"]["bitdepth"]), (8, 6, 8))
        self.assertTrue(entry["png"]["true_bitdepth_parser"])
        self.assertEqual(entry["sha256"],
                         lib.sha256_file(lib.REPO_ROOT / got))
        self.assertEqual(s.shots, [(str(ev.dir / "p2r-f1-ok.png"), "subtitles")])

        # 2) 重复字节 + seen_hashes：重拍一次仍相同 → non_corroborative
        seen = {}
        s1 = FakeShotSession(pngs=[png_a], counts=[(5, 2)])
        got_a = p1v.take_screenshot(s1, ev, "p2r-f1-dup-a.png", {},
                                    seen_hashes=seen)
        self.assertTrue(got_a)
        self.assertIn("p2r-f1-dup-a.png", seen)
        # 计数在重拍等待循环前前进（第 3 次观察 6/2 ≠ before 5/2）→ 立即重拍
        s2 = FakeShotSession(pngs=[png_a, png_a], counts=[(5, 2), (5, 2), (6, 2)])
        var_b = {}
        got_b = p1v.take_screenshot(s2, ev, "p2r-f1-dup-b.png", var_b,
                                    seen_hashes=seen)
        entry_b = var_b["screenshot"]
        self.assertEqual(entry_b["duplicate_of"], "p2r-f1-dup-a.png")
        self.assertTrue(entry_b["non_corroborative"])
        self.assertFalse(entry_b.get("resolved_by_retake", False))
        self.assertEqual(len(s2.shots), 2)  # 主拍 + 重拍各一次
        self.assertTrue((ev.dir / "p2r-f1-dup-b-retake.png").is_file())
        # 返回的仍是原拍路径（重拍未被采信，原文件不冒充新证据也不隐藏）
        self.assertTrue(got_b)
        self.assertFalse(got_b.endswith("-retake.png"))

        # 3) 截图失败：not_generated，返回 None，无幻影路径
        s3 = FakeShotSession(pngs=[], counts=[(5, 2), (5, 2)], capture_ok=False)
        var_c = {}
        got_c = p1v.take_screenshot(s3, ev, "p2r-f1-failed.png", var_c)
        self.assertIsNone(got_c)
        entry_c = var_c["screenshot"]
        self.assertFalse(entry_c["captured"])
        self.assertTrue(entry_c["not_generated"])
        self.assertIn("reason", entry_c)
        self.assertFalse((ev.dir / "p2r-f1-failed.png").exists())

    def test_p2r_f2_all_sessions_collected(self):
        # P2R-F2 行为级（M-10②）：不能以源码含 all_sessions/"for s in
        # sessions" 充当回归钉。用最小 fake ctx/session 走真实
        # save_session_artifacts：
        #   * all_sessions 中每个 session 的 log/console/transcript 都被收集
        #     （含非当前 session；transcript 同名自动 -2 唯一命名）；
        #   * 当前 session 重复出现在 all_sessions 中不重复收集；
        #   * inputs 清单（桩/合成输入 sha + 媒体 sha）真实写入并列入返回；
        #   * 返回的每个路径都真实存在（无幻影）。
        tmp = tempfile.TemporaryDirectory(dir=REPO_ROOT)
        self.addCleanup(tmp.cleanup)
        ev = lib.Evidence(Path(tmp.name) / "ev")

        class FakeIpc:
            def __init__(self, transcript):
                self.transcript = transcript

        class FakeSession:
            def __init__(self, case_name, console_text=None, transcript=None):
                self.case_name = case_name
                self.log_path = Path(tmp.name) / f"{case_name}.mpv.log"
                self.log_path.write_bytes(f"log:{case_name}\n".encode("utf-8"))
                self.console_path = None
                if console_text is not None:
                    self.console_path = Path(tmp.name) / f"{case_name}.out"
                    self.console_path.write_bytes(
                        console_text.encode("utf-8"))
                self.ipc = None if transcript is None else FakeIpc(transcript)

        class FakeEnv:
            inputs = {"input.conf": "sha-input",
                      "script-opts/scale-selector.conf": "sha-opts"}

        class FakeCtx:
            def __init__(self, label, all_sessions, current):
                self.label = label
                self.all_sessions = all_sessions
                self.mpv_session = current   # M-5 后 p1 侧对象名
                self.env = FakeEnv()
                self.media_sha = "sha-media"
                self.evidence = ev

        s1 = FakeSession("CASE-a", console_text="console-a\n",
                         transcript=[{"req": ["get_property", "scale"]},
                                     {"resp": {"error": "success"}}])
        s2 = FakeSession("CASE-b", transcript=[{"req": ["x"]}])
        s3 = FakeSession("CASE-c")           # 无 console 无 transcript
        ctx = FakeCtx("P2R-F2", [s1, s2, s3], current=s1)

        files = p1v.save_session_artifacts(ctx, [])
        names = {Path(f).name for f in files}
        self.assertEqual(len(files), len(names),
                         "重复 current session 不得被收集两次")
        for name in ("CASE-a.mpv.log", "CASE-b.mpv.log", "CASE-c.mpv.log",
                     "CASE-a.out"):
            self.assertIn(name, names)
        # 两个 transcript 各自落盘（同名会自动 -2 唯一命名，此处本就不同名）
        self.assertIn("CASE-a.mpv.transcript.jsonl", names)
        self.assertIn("CASE-b.mpv.transcript.jsonl", names)
        self.assertNotIn("CASE-c.mpv.transcript.jsonl", names)
        t = ev.dir / "CASE-a.mpv.transcript.jsonl"
        self.assertEqual(len(t.read_text(encoding="utf-8").strip()
                             .splitlines()), 2)
        # inputs 清单以首个 session 的 case_name 命名并记录真实 sha
        inputs = json.loads(
            (ev.dir / "CASE-a.inputs.json").read_text(encoding="utf-8"))
        self.assertEqual(inputs["config_dir_files_sha256"], FakeEnv.inputs)
        self.assertEqual(inputs["media_sha256"], "sha-media")
        self.assertIn("CASE-a.inputs.json", names)
        # 返回的每个路径真实存在
        for f in files:
            self.assertTrue((lib.REPO_ROOT / f).is_file(), f)

    def test_same_moment_sampling_helper_exists(self):
        # VL-F1 闭环——行为级断言（brief 根因4）：不能以 docstring 含
        # “same_window” 措辞假证明关闭；必须验证真实采样顺序、返回内容、
        # 帧计数 epoch 与几何一致性。用记录型 fake session 验证：
        #   * 单次调用内按序读取 video-out-params（解码参数）→
        #     osd-dimensions（几何/窗口）→ vo-passes（帧计数）三个族；
        #   * 返回记录把三者绑定在同一观察窗（same_window 绑定字段 +
        #     observed_at），值全部来自同一份快照（几何与解码一致）；
        #   * 帧计数为 fresh/redraw 两条 vo-passes 列表 count 字段之和
        #     （下游据以断言严格递增/epoch 不变）；
        #   * 同刻截图分支：截图路径/mode/捕获成功与否/sha256/bytes 入同
        #     一记录（真实临时文件 + 真实 sha256）。
        self.assertTrue(hasattr(p3, "same_moment_sample"))

        vop = {"pixelformat": "yuv420p10", "gamma": "bt.1886",
               "w": 1920, "h": 1080, "dw": 2560, "dh": 1440}
        osd = {"w": 2560, "h": 1440}
        vp = {"fresh": [{"desc": "d", "count": 3, "samples": [1.0]},
                        {"desc": "d2", "count": 4}],
              "redraw": [{"desc": "d", "count": 5}]}

        class FakeS:
            def __init__(self):
                self.calls = []
                self.shot_calls = []

            def get(self, name):
                self.calls.append(name)
                return {"video-out-params": vop,
                        "osd-dimensions": osd,
                        "vo-passes": vp}[name]

            def screenshot(self, path, mode="window"):
                self.shot_calls.append((str(path), mode))
                Path(path).write_bytes(b"\x89PNG\r\n\x1a\n-fake")
                return True

        s = FakeS()
        rec = p3.same_moment_sample(s)
        # 采样顺序：单次调用、按固定顺序读三个族（解码→几何→帧）
        self.assertEqual(s.calls, ["video-out-params", "osd-dimensions", "vo-passes"])
        # 返回内容：解码参数、几何、帧计数在同一记录且与快照一致
        self.assertEqual(rec["pixelformat"], "yuv420p10")
        self.assertEqual(rec["gamma"], "bt.1886")
        self.assertEqual((rec["w"], rec["h"]), (1920, 1080))
        self.assertEqual((rec["dw"], rec["dh"]), (2560, 1440))
        self.assertEqual((rec["osd_w"], rec["osd_h"]), (2560, 1440))
        # 帧 epoch：count 字段求和（缺 samples 容忍为 0）
        self.assertEqual(rec["vo_passes_frame_counts"], {"fresh": 7, "redraw": 5})
        # 同一观察窗绑定 + 观察时刻在记录内
        self.assertTrue(rec["same_window"])
        self.assertTrue(rec["observed_at"])
        # 截图分支：同刻捕获入同一记录，记录哈希/字节为真实值
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "same_moment.png"
            s2 = FakeS()
            rec2 = p3.same_moment_sample(s2, shot_path=shot)
            self.assertEqual(s2.shot_calls, [(str(shot), "window")])
            self.assertTrue(rec2["screenshot"]["captured"])
            self.assertEqual(rec2["screenshot"]["bytes"], shot.stat().st_size)
            self.assertEqual(rec2["screenshot"]["sha256"],
                             lib.sha256_file(shot))

    def test_p2s04_env_files_still_enforced_by_p3_guard(self):
        # 限域接续修正（brief 根因3）：原断言写
        #   self.assertIn(...单引号...) or self.assertIn(...双引号...)
        # assertIn 成功返回 None，or 右侧仍会执行：名单实际用单引号时首查
        # 成功、第二查仍执行并误报失败。语义修为成员 OR 后 assertTrue，
        # 并用真实 import ENV_FILES 语义核对名单内容与强制点（不编辑
        # P3guard 本身）。
        guard_path = REPO_ROOT / "taskflows" / "p3_guard.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("p3_guard_p2s04_pin", guard_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        expected = ("tools/mpv_config_backup.py", "tools/check_preparation.py",
                    "taskflows/guard.py", "taskflows/p3_guard.py")
        # 真实 ENV_FILES 名单语义：四文件一个不少
        for f in expected:
            self.assertIn(f, getattr(mod, "ENV_FILES"), f)
        # 名单必须约束真实存在的路径
        for f in mod.ENV_FILES:
            self.assertTrue((REPO_ROOT / f).is_file(), f)
        # 名单必须在 guard 强制点被真实使用（哈希强制循环）
        guard = guard_path.read_text(encoding="utf-8")
        self.assertIn("ENV_FILES", guard)
        self.assertIn("for name in ENV_FILES", guard)
        # 文本层成员断言：OR 后 assertTrue（修复原 or 短路缺陷）
        for f in expected:
            self.assertTrue(f"'{f}'" in guard or f'"{f}"' in guard, f)


class TestP3Fixtures(unittest.TestCase):
    def test_negative_fixtures_exist_and_declare_themselves(self):
        base = REPO_ROOT / "tests" / "fixtures" / "p3"
        for name in ("broken-compute.glsl", "broken-syntax.glsl", "bad-param.glsl"):
            text = (base / name).read_text(encoding="utf-8")
            self.assertIn("测试桩", text, name)
            self.assertIn("负例", text, name)
        # broken-compute is a compute shader referencing an undefined symbol
        bc = (base / "broken-compute.glsl").read_text(encoding="utf-8")
        self.assertIn("//!COMPUTE 32 24 256 1", bc)
        self.assertIn("undefinedFunctionNotDeclared", bc)

    def test_no_broken_fixture_in_release_dir(self):
        release = [p for p in (REPO_ROOT / "shaders").rglob("*")
                   if p.is_file() and ("broken" in p.name or "bad-param" in p.name)]
        self.assertEqual(release, [])


class TestP3MediaHelpers(unittest.TestCase):
    def test_ppm_pattern_deterministic_with_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.ppm"
            b = Path(tmp) / "b.ppm"
            sha1, rows1 = p3.generate_ppm_pattern(a, 12, 8)
            sha2, rows2 = p3.generate_ppm_pattern(b, 12, 8)
            self.assertEqual(sha1, sha2)
            self.assertEqual(len(rows1), 8)
            self.assertEqual(len(rows1[0]), 12)
            # rows match the exact PPM bytes fed to mpv
            raw = a.read_bytes()
            header = b"P6\n12 8\n255\n"
            self.assertTrue(raw.startswith(header))
            payload = raw[len(header):]
            self.assertEqual(len(payload), 12 * 8 * 3)
            self.assertEqual(payload[0:3], bytes(rows1[0][0]))

    def test_max_abs_diff(self):
        d = p3.max_abs_diff_img([[(10, 20, 30)]], [[(12, 20, 25)]])
        self.assertEqual(d["max"], 5)
        self.assertAlmostEqual(d["mean"], 7 / 3)


class TestP3OracleSampleFixture(unittest.TestCase):
    def test_oracle_sample_exists_and_matches_helper(self):
        p = REPO_ROOT / "tests/fixtures/p3/oracle-sample.ppm"
        self.assertTrue(p.is_file())
        sha, rows = p3.generate_ppm_pattern(
            Path(tempfile.gettempdir()) / "p3-verify-sample.ppm", 24, 16)
        # the frozen fixture must be the deterministic helper output
        self.assertEqual(lib.sha256_file(p), sha)


class TestP3VerifyHarnessSupport(unittest.TestCase):
    """Pure, mpv-free pins for tools/p3_verify.py (case-harness writer,
    p3-001): id partition vs the frozen checker contract, CPU goldens, epoch
    pairing, and the EVI-01 negative-class detector coverage.  No GPU, no
    evidence trees, no candidate reads."""

    @classmethod
    def setUpClass(cls):
        import p3_verify as pv
        import p3_check_evidence as gate
        import p1_check_evidence as p1chk
        cls.pv = pv
        cls.gate = gate
        cls.p1chk = p1chk
        cls.p3 = p3

    # -- harness identity -------------------------------------------------
    def test_id_partition_equals_frozen_required_35(self):
        ids = sorted(self.pv.REUSED_P2_IDS + self.pv.P3_WRITTEN_IDS)
        self.assertEqual(ids, sorted(self.pv.P3_REQUIRED_IDS))
        self.assertEqual(ids, sorted(self.gate.P3_REQUIRED_IDS))
        self.assertEqual(ids, sorted(self.p1chk.P3_REQUIRED_IDS))
        self.assertEqual(len(set(ids)), 35)

    def test_case_registry_covers_all_35(self):
        self.assertEqual(sorted(self.pv.CASES), sorted(self.pv.P3_REQUIRED_IDS))
        reused = {cid: self.pv.CASES[cid] for cid in self.pv.REUSED_P2_IDS}
        for cid, fn in reused.items():
            # reuse is the REAL frozen p2 harness function, not a rebind
            self.assertIs(fn, self.pv.p2v.CASES[cid],
                          f"{cid} must reuse the frozen p2_verify case")

    def test_session_reuse_explicit_passing(self):
        # M-5/M-6: the reused P1/P2 cases receive the session id as an
        # EXPLICIT case-function argument; importing p3_verify must leave
        # the imported modules' globals untouched — the old "SESSION =
        # p3-001" module patch is gone and the import side effect is no
        # longer a contract.
        self.assertEqual(self.pv.SESSION, "p3-001")
        self.assertEqual(self.pv.p2v.SESSION, "p2-001")
        self.assertEqual(self.pv.p1v.SESSION, "p1-001")
        # every case in the frozen reuse chain takes the session explicitly
        for cid in self.pv.REUSED_P2_IDS:
            fn = self.pv.CASES[cid]
            self.assertIn("session", inspect.signature(fn).parameters,
                          f"{cid} must take the session id explicitly")
        # the frozen def-time default (`session: str = SESSION`) is gone:
        # CaseContext resolves None against the module global at CALL time
        # (M-5), so --session can never be bypassed by a stale default.
        self.assertIsNone(inspect.signature(p1v.CaseContext.__init__)
                          .parameters["session"].default)
        self.assertTrue(callable(p1v.resolve_session))
        self.assertTrue(callable(self.pv.p2v.resolve_session))

    # -- CPU goldens -------------------------------------------------------
    def test_golden_bilinear_known_values(self):
        pv = self.pv
        flat = [[(0.2, 0.4, 0.6)] * 8 for _ in range(8)]
        for x, y in ((0, 0), (3.5, 3.5), (7, 7)):
            self.assertEqual(pv.golden_bilinear(flat, 8, 8, x, y),
                             (0.2, 0.4, 0.6))
        checker = [[(0.0,) * 3 if (x + y) % 2 else (1.0,) * 3
                    for x in range(8)] for y in range(8)]
        # midpoint between two white texels is white; crossing the diagonal
        # edge vertically blends black/white to exactly 0.5
        self.assertEqual(pv.golden_bilinear(checker, 8, 8, 2.5, 2.5),
                         (1.0, 1.0, 1.0))
        v = pv.golden_bilinear(checker, 8, 8, 2.5, 2.0)[0]
        self.assertAlmostEqual(v, 0.5, places=6)

    def test_golden_sharp_scale1_is_plain_bilinear(self):
        pv = self.pv
        src = [[((x / 7.0), (y / 7.0), 0.5) for x in range(8)]
               for y in range(8)]
        for (ox, oy, ow, oh) in ((0, 0, 512, 288), (10, 20, 512, 288),
                                 (100, 50, 240, 135)):
            tx = (ox + 0.5) * 8 / ow
            ty = (oy + 0.5) * 8 / oh
            got = pv.golden_sharp_sample(src, 8, 8, ow, oh, 1, ox, oy)
            want = pv.golden_bilinear(src, 8, 8, tx, ty)
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, places=9)

    def test_golden_sharp_scale2_pulls_toward_texel_centre(self):
        pv = self.pv
        # 2x2 blocks: nearest-like inside a block for scale=2
        src = [[(1.0, 0.0, 0.0) if (x // 2 + y // 2) % 2 == 0 else (0.0, 1.0, 0.0)
                for x in range(8)] for y in range(8)]
        # output pixel near the START of a source texel must sample that texel
        got = pv.golden_sharp_sample(src, 8, 8, 16, 16, 2, 8, 8)
        self.assertEqual(got, src[4][4])

    # -- epoch pairing ------------------------------------------------------
    def test_finalize_epoch_pairs_and_flags_stability(self):
        pv = self.pv

        class FakeS:
            def __init__(self, epoch):
                self.e = epoch

            def ud(self, _):
                return self.e

        variant = {"same_moment": [{}]}
        fr = {"chain_epoch": 7}
        pv.finalize_epoch(variant, fr, FakeS(7))
        self.assertEqual(variant["chain_epoch"], 7)
        self.assertTrue(variant["epoch_stable_across_window"])
        pv.finalize_epoch(variant, fr, FakeS(8))
        self.assertFalse(variant["epoch_stable_across_window"])
        self.assertEqual(variant["chain_epoch"], 7)  # still the freshness epoch

    # -- EVI-01 detector coverage ------------------------------------------
    def test_evi_detectors_cover_all_canonical_classes(self):
        pv, gate = self.pv, self.gate
        self.assertEqual(set(pv.EVI_NEGATIVE_DETECTORS), set(gate.EVI_NEGATIVE_KEYS))
        for cls, kws in pv.EVI_NEGATIVE_DETECTORS.items():
            self.assertTrue(kws and all(isinstance(k, str) and k for k in kws),
                            f"{cls} detector keywords must be non-empty")

    # -- PNG helpers --------------------------------------------------------
    def test_evi_make_png_decodes_with_true_dims(self):
        pv, p3 = self.pv, self.p3
        data = pv._evi_make_png(9, 5, salt=3)
        dec = p3.decode_png(data)
        self.assertEqual((dec["w"], dec["h"]), (9, 5))
        self.assertEqual(dec["bitdepth"], 8)

    def test_compare_to_golden_accepts_exact_and_rejects_wrong(self):
        pv, p3 = self.pv, self.p3
        png = pv._evi_make_png(8, 6, salt=0)
        dec = p3.decode_png(png)
        exact = pv.compare_to_golden(
            dec, lambda x, y: tuple(v / 255.0 for v in dec["get_pixel"](x, y)),
            [(1, 1), (4, 3), (6, 5)])
        self.assertTrue(exact["ok"] and exact["mean_diff"] == 0.0)
        wrong = pv.compare_to_golden(
            dec, lambda x, y: (1.0, 0.0, 0.0), [(1, 1), (4, 3), (6, 5)])
        self.assertFalse(wrong["ok"])

    def test_edge_discriminator_prefers_exact_replica(self):
        pv = self.pv
        # discriminator METRIC test with stub rows: the captured pixels equal
        # the 'replica' truth (a sharp diagonal split), while the bilinear
        # baseline of a white source smears (the real end-to-end replica
        # comparison runs in the mpv case; here only the metric is pinned).
        # V3-Q1: capture and replica share ONE documented 8-bit quantization
        # space — the truth values are exact byte fractions b/255, so a
        # byte-captured frame must give a true byte-equality ZERO mean.  The
        # old draft used float truth 0.7 vs round(0.7*255) captured bytes
        # (and Python's banker's rounding round(178.5)==178), manufacturing
        # a fake 0.4 mean: fixed by an exact-encodable fixture, NOT by
        # relaxing the zero assertion or the oracle tolerances.
        w_in, h_in = 16, 8
        out_w, out_h = 48, 24
        red_bytes = (178, 41, 41)  # exactly encodable: round(b * 1.0) == b
        truth = []
        for Y in range(out_h):
            row = []
            for X in range(out_w):
                sx = (X + 0.5) * w_in / out_w - 0.5
                sy = (Y + 0.5) * h_in / out_h - 0.5
                row.append((1.0, 1.0, 1.0) if (sx - sy) > 4.0
                           else tuple(b / 255.0 for b in red_bytes))
            truth.append(row)
        src = [[(1.0, 1.0, 1.0)] * w_in for _ in range(h_in)]  # bilinear=white

        def pix(x, y):
            r, g, b = truth[y][x]
            return (int(round(r * 255)), int(round(g * 255)),
                    int(round(b * 255)))

        res = pv.edge_discriminator({"get_pixel": pix}, truth, src,
                                    w_in, h_in, out_w, out_h)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["mean_diff_to_xbr_replica"], 0.0)
        self.assertGreater(res["mean_diff_to_bilinear_baseline"], 0.0)

    def test_quantization_space_half_lsb_and_rejection_bounds(self):
        # V3-Q1 companion: pin the common 8-bit quantization space itself on
        # a single-capture oracle — byte-captured (178,41,41) against a
        # replica truth at 0 / +half / +1 LSB must report exactly 0.0 / 0.5
        # / 1.0 (sub-LSB truth can never manufacture phantom diffs beyond
        # the documented rounding), and a wildly wrong replica stays
        # REJECTED with the fixed gates (no tolerance inflation).
        pv = self.pv
        dec = {"get_pixel": lambda x, y: (178, 41, 41), "w": 2, "h": 1}
        pt = [(0, 0)]
        exact = pv.compare_to_golden(
            dec, lambda x, y: (178 / 255, 41 / 255, 41 / 255), pt)
        self.assertEqual(exact["mean_diff"], 0.0)      # true byte zero
        self.assertTrue(exact["ok"])
        half = pv.compare_to_golden(
            dec, lambda x, y: (178.5 / 255, 41 / 255, 41 / 255), pt)
        self.assertEqual(half["mean_diff"], 0.5)       # half-LSB == 0.5
        self.assertTrue(half["ok"])
        one = pv.compare_to_golden(
            dec, lambda x, y: (179 / 255, 41 / 255, 41 / 255), pt)
        self.assertEqual(one["mean_diff"], 1.0)        # one full LSB == 1.0
        self.assertTrue(one["ok"])
        blow = pv.compare_to_golden(
            dec, lambda x, y: (0.0, 0.0, 0.0), pt)
        self.assertFalse(blow["ok"])                   # gates unchanged
        self.assertGreater(blow["max_diff"], blow["tol_max"])

    # -- OSD residue detector on synthetic bytes ----------------------------
    def test_osd_tl_bright_px_counts_only_bright_corner(self):
        pv, p3 = self.pv, self.p3

        def png(pixels, w, h):
            import struct as _s
            import zlib as _z

            def chunk(t, d):
                return (_s.pack(">I", len(d)) + t + d
                        + _s.pack(">I", _z.crc32(t + d) & 0xFFFFFFFF))
            raw = b"".join(b"\x00" + b"".join(bytes(pixels[y][x])
                                                  for x in range(w))
                            for y in range(h))
            return (b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR", _s.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", _z.compress(raw)) + chunk(b"IEND", b""))

        black = [[(0, 0, 0)] * 40 for _ in range(20)]
        d0 = p3.decode_png(png(black, 40, 20))
        self.assertEqual(pv.osd_tl_bright_px(d0), 0)
        marked = [row[:] for row in black]
        marked[3][3] = (255, 255, 255)   # (3,3) lies on the 3px sample grid
        d1 = p3.decode_png(png(marked, 40, 20))
        self.assertGreaterEqual(pv.osd_tl_bright_px(d1), 1)

    def test_bars_fallback_scan_finds_synthetic_bars(self):
        pv, p3 = self.pv, self.p3
        # the fallback strips are pinned to the k=1 1080p->1440p geometry,
        # so the synthetic frame must be full 2560x1440: black bars with a
        # bright content rect (320,180)-(2240,1260) plus a bright cross that
        # intersects both scan strips (rows 700..1200 / cols 1300..2200).
        w, h = 2560, 1440
        px = [[(0, 0, 0)] * w for _ in range(h)]
        for y in range(180, 1260):
            row = px[y]
            for x in range(320, 2240):
                row[x] = (200, 40, 40)
        for y in range(700, 1201, 7):
            for x in range(320, 2240, 97):
                px[y][x] = (255, 255, 255)
        for y in range(180, 1260, 7):
            for x in range(1300, 2201, 7):
                px[y][x] = (255, 255, 255)
        data = self._png_bytes(px, w, h)
        dec = p3.decode_png(data)
        res = pv.bars_fallback_scan(dec)
        self.assertEqual(res["left"], 320)
        self.assertEqual(res["right"], 320)
        self.assertEqual(res["top"], 180)
        self.assertEqual(res["bottom"], 180)

    @staticmethod
    def _png_bytes(pixels, w, h):
        import struct as _s
        import zlib as _z

        def chunk(t, d):
            return (_s.pack(">I", len(d)) + t + d
                    + _s.pack(">I", _z.crc32(t + d) & 0xFFFFFFFF))
        raw = b"".join(b"\x00" + b"".join(bytes(pixels[y][x])
                                              for x in range(w))
                        for y in range(h))
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", _s.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", _z.compress(raw)) + chunk(b"IEND", b""))


class TestP3Y4mTenBitByteOracle(unittest.TestCase):
    """V3-M2: make_y4m(ten_bit=True) must emit REAL little-endian 16-bit
    10-bit planes (samples 0..1023) for ALL of Y/U/V with exact 2x lengths
    under the C420p10 header and per-frame markers.  An 8-bit body under a
    10-bit header is the old fake PASS — these byte checks reject any
    relabelled file by construction (a relabelled 8-bit body has all high
    bytes zero: no word > 255, wrong total size, wrong offsets)."""

    W, H, FRAMES = 64, 48, 3
    HDR = b"YUV4MPEG2 W64 H48 F24:1 Ip A1:1 C420p10\n"
    MARKER = 6  # b"FRAME\n"
    Y_BYTES = W * H * 2
    C_BYTES = (W // 2) * (H // 2) * 2
    FRAME_BYTES = MARKER + Y_BYTES + 2 * C_BYTES

    @classmethod
    def setUpClass(cls):
        import p3_verify as pv
        cls.pv = pv
        tmp = tempfile.TemporaryDirectory()
        cls._tmp = tmp
        base = Path(tmp.name)
        cls.p10 = pv.write_y4m(base / "a10.y4m", cls.W, cls.H,
                               frames=cls.FRAMES, ten_bit=True)
        cls.p8 = pv.write_y4m(base / "a8.y4m", cls.W, cls.H,
                              frames=cls.FRAMES)
        cls.d10 = cls.p10.read_bytes()
        cls.d8 = cls.p8.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def y_word(self, k, frame=0):
        off = len(self.HDR) + frame * self.FRAME_BYTES + self.MARKER + k * 2
        return int.from_bytes(self.d10[off:off + 2], "little")

    def test_header_frame_markers_and_exact_sizes(self):
        # header: real C420p10 declaration
        self.assertTrue(self.d10.startswith(self.HDR))
        # exact total size: header + 3 x (FRAME marker + Y + U + V planes)
        self.assertEqual(len(self.d10),
                         len(self.HDR) + self.FRAMES * self.FRAME_BYTES)
        # per-frame markers at exact offsets
        for i in range(self.FRAMES):
            off = len(self.HDR) + i * self.FRAME_BYTES
            self.assertEqual(self.d10[off:off + self.MARKER], b"FRAME\n",
                             f"frame {i}")
        # 8-bit regression: C420jpeg layout byte-identical to the frozen
        # harness (Y = W*H bytes, chroma halves, first values 30/80/140)
        hdr8 = b"YUV4MPEG2 W64 H48 F24:1 Ip A1:1 C420jpeg\n"
        frame8 = self.MARKER + self.W * self.H \
            + 2 * (self.W // 2) * (self.H // 2)
        self.assertEqual(len(self.d8), len(hdr8) + self.FRAMES * frame8)
        self.assertTrue(self.d8.startswith(hdr8))
        y0 = self.d8[len(hdr8) + self.MARKER]
        self.assertEqual(y0, 30)  # band 0 base luma, unchanged

    def test_planes_are_real_le16_tens(self):
        # first luma word: frame0/row0/band0/xx0 -> base 120 (LE 0x78 0x00)
        self.assertEqual(self.y_word(0), 120)
        # band row (yy=16 -> band 1) carries the 920 base at xx=0
        self.assertEqual(self.y_word(16 * self.W), 920)
        # U/V planes at exact offsets, neutral 10-bit chroma (LE words)
        u_off = len(self.HDR) + self.MARKER + self.Y_BYTES
        self.assertEqual(int.from_bytes(self.d10[u_off:u_off + 2], "little"),
                         513)
        v_off = u_off + self.C_BYTES
        self.assertEqual(int.from_bytes(self.d10[v_off:v_off + 2], "little"),
                         608)

    def test_all_y_words_within_10bit_range_and_word_width_pinned(self):
        for frame in range(self.FRAMES):
            for k in range(self.W * self.H):
                v = self.y_word(k, frame)
                self.assertLessEqual(v, 1023, f"frame {frame} word {k}")
                self.assertGreaterEqual(v, 0, f"frame {frame} word {k}")
        # a relabelled 8-bit body cannot produce words > 255 (high byte
        # would be zero everywhere); the moving ^0x141 detail guarantees
        # words strictly above 255 exist
        words = [self.y_word(k) for k in range(self.W * self.H)]
        self.assertTrue(any(v > 255 for v in words))

    def test_sar_header_variant(self):
        p = self.pv.write_y4m(Path(self._tmp.name) / "sar.y4m",
                              16, 16, frames=1, sar="2:1")
        self.assertTrue(p.read_bytes().startswith(
            b"YUV4MPEG2 W16 H16 F24:1 Ip A2:1 C420jpeg\n"))

    def test_p3context_make_y4m_delegates_to_pure_writer(self):
        # the harness context must produce the same real-LE16 bytes through
        # the public path and register the media sha in its inputs ledger
        ctx = self.pv.P3Context(None, "unit-y4m-delegate")
        try:
            p = ctx.make_y4m("d.y4m", self.W, self.H, frames=2, ten_bit=True)
            data = p.read_bytes()
            self.assertTrue(data.startswith(self.HDR))
            self.assertEqual(len(data),
                             len(self.HDR) + 2 * self.FRAME_BYTES)
            self.assertEqual(ctx.media_sha, lib.sha256_file(p))
            self.assertEqual(ctx.env.inputs["media/d.y4m"], ctx.media_sha)
        finally:
            ctx.cleanup()


class TestP3FreshnessR2ControlledLeg(unittest.TestCase):
    """VL3-01 (r2) freshness 修正回归钉：受控帧步进/解码像素比较/计数饱和/
    重复 pattern 盲采 alias/暂停读回与恢复等真实负例。全部无 mpv、无 GPU、
    临时目录内真实 PNG 字节，快速确定性。"""

    SALT_PIXEL_CHANGE_METRIC = ("decoded_pixel_diff 以解码 RGB 像素为准，"
                                "PNG 字节哈希永不当新像素证据")

    @classmethod
    def setUpClass(cls):
        import p3_verify as pv
        import p3_check_evidence as gate
        cls.pv = pv
        cls.gate = gate

    # -- fakes --------------------------------------------------------------
    class _FakeStepSession:
        """Recording MpvSession fake: frozen saturation-style counters,
        deterministic real-PNG screenshot queue, mpv-like pause state
        machine, verbatim IPC records.  Optional epoch flip after frame-step
        (stale-epoch negative), screenshot failure and pipe-death raise."""

        def __init__(self, payloads=None, fresh=40, redraw=7, epoch=8,
                     pause0=False, step_error="success", epoch_flip=False,
                     fail_screens=False, step_raises=None, counts_seq=None):
            self._payloads = list(payloads or [])
            self.fresh = fresh
            self.redraw = redraw
            self._epoch = epoch
            self._pause = pause0
            self.pause0 = pause0
            self._step_error = step_error
            self._epoch_flip = epoch_flip
            self._fail = fail_screens
            self._raise = step_raises
            self._counts_seq = list(counts_seq) if counts_seq else None
            self._tp = 1.0
            self.sets = []
            self.cmds = []
            self.shots = []
            self._epoch_flipped = False

        def get(self, name):
            if name == "pause":
                return self._pause
            if name == "path":
                return "X:/iso/media/geo03-720.y4m"
            if name == "video-out-params":
                return {"pixelformat": "yuv420p", "w": 1280, "h": 720,
                        "dw": 2560, "dh": 1440}
            if name == "osd-dimensions":
                return {"w": 2560, "h": 1440}
            if name == "vo-passes":
                if self._counts_seq:
                    f, r = (self._counts_seq.pop(0) if self._counts_seq
                            else (self.fresh, self.redraw))
                else:
                    f, r = self.fresh, self.redraw
                return {"fresh": [{"desc": "p", "count": f,
                                   "samples": [1.0]}],
                        "redraw": [{"desc": "r", "count": r}]}
            if name == "time-pos":
                self._tp += 1
                return round(self._tp * 0.0417, 4)
            if name == "estimated-vf-fps":
                return 24.0
            return None

        def set(self, name, value):
            self.sets.append((name, value))
            if name == "pause":
                self._pause = bool(value)
            return {"error": "success"}

        def cmd(self, *args):
            self.cmds.append(list(args))
            if args and args[0] == "frame-step":
                if self._raise is not None:
                    raise self._raise
                self._epoch_flipped = self._epoch_flip
                return {"error": self._step_error}
            return {"error": "success"}

        def ud(self, subkey):
            if subkey == "gear":
                return "integer"
            if subkey == "chain_epoch":
                return 9 if self._epoch_flipped else self._epoch
            return None

        def screenshot(self, path, mode="window"):
            self.shots.append((str(path), mode))
            if Path(path).exists():
                raise FileExistsError(f"截图目标已存在: {path}")
            if self._fail:
                return False
            Path(path).write_bytes(self._payloads.pop(0))
            return True

        def wait_until(self, predicate, timeout_s, poll=0.15):
            try:
                return bool(predicate())
            except Exception:  # noqa: BLE001 — fake mirrors real swallow
                return False

    def _ev(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return lib.Evidence(Path(tmp.name) / "ev"), Path(tmp.name)

    def _png(self, salt, w=8, h=6):
        return self.pv._evi_make_png(w, h, salt=salt)

    # -- pure pixel oracle negatives -----------------------------------------
    def test_metadata_only_png_byte_change_is_not_new_pixels(self):
        """负例：PNG 字节不同（插入 tEXt 元数据块）但解码像素完全相同——
        旧字节哈希法会假阳性，r2 契约必须判非新像素。"""
        pv = self.pv
        base = self._png(1)
        # rebuild the same pixels with an extra tEXt chunk (real chunk CRC)
        def chunk(ctype, data):
            import struct, zlib
            return (struct.pack(">I", len(data)) + ctype + data
                    + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))
        ihdr = base[8:8 + 4 + 4 + 13 + 4]      # len+type+data+crc (25 字节)
        rest = base[8 + 4 + 4 + 13 + 4:]       # IDAT+IEND 原样保留
        meta = chunk(b"tEXt", b"Comment\x00rerendered with new compressor")
        doctored = base[:8] + ihdr + meta + rest
        self.assertNotEqual(lib.sha256_bytes(base), lib.sha256_bytes(doctored))
        dec_a = p3.decode_png(base)
        dec_b = p3.decode_png(doctored)
        self.assertEqual((dec_a["w"], dec_a["h"]), (dec_b["w"], dec_b["h"]))
        ok, diff = pv.fresh_pixel_change(dec_a, dec_b)
        self.assertFalse(ok, "元数据差异必须判非新像素")
        self.assertTrue(diff["pixels_identical"])
        self.assertEqual(diff["differing_points"], 0)
        # identical pixels through byte-identical files also agree
        ok2, _ = pv.fresh_pixel_change(dec_a, p3.decode_png(self._png(1)))
        self.assertFalse(ok2)

    def test_real_decoded_pixel_change_is_detected(self):
        pv = self.pv
        ok, diff = pv.fresh_pixel_change(p3.decode_png(self._png(1)),
                                         p3.decode_png(self._png(2)))
        self.assertTrue(ok)
        self.assertGreater(diff["differing_points"], 0)
        self.assertGreater(diff["max_channel_delta"], 0)
        self.assertTrue(diff["same_dimensions"] and diff["same_bitdepth"])
        self.assertEqual(diff["sample_stride"], 1)  # 8x6 < max_points

    def test_dimension_or_bitdepth_mismatch_is_never_new_pixels(self):
        pv = self.pv
        ok, diff = pv.fresh_pixel_change(p3.decode_png(self._png(1, 8, 6)),
                                         p3.decode_png(self._png(2, 9, 5)))
        self.assertFalse(ok)
        self.assertFalse(diff["same_dimensions"])
        self.assertIn("reason", diff)
        fake16 = {"w": 8, "h": 6, "bitdepth": 16,
                  "get_pixel": lambda x, y: (0, 0, 0)}
        fake8 = {"w": 8, "h": 6, "bitdepth": 8,
                 "get_pixel": lambda x, y: (0, 0, 0)}
        ok2, diff2 = pv.fresh_pixel_change(fake8, fake16)
        self.assertFalse(ok2)
        self.assertFalse(diff2["same_bitdepth"])

    # -- counter-witness paths unchanged (270 行为保持) ----------------------
    def _freshness(self, fake, case="GEO-03-a", **kw):
        ev, _tmp = self._ev()
        return self.pv.freshness_block(fake, ev, case, **kw)[0]

    def test_counter_growth_witness_unchanged_without_controlled(self):
        fake = self._FakeStepSession(counts_seq=[(3, 2), (7, 2)])
        block = self._freshness(fake)
        self.assertTrue(block["render_fresh"])
        self.assertEqual(block["method"], "vo-passes-fresh-increase")
        self.assertEqual((block["fresh_before"], block["fresh_after"]), (3, 7))
        self.assertNotIn("controlled_leg", block)  # 无受控腿，无额外截图
        self.assertEqual(fake.shots, [])

    def test_forced_redraw_witness_unchanged_without_controlled(self):
        fake = self._FakeStepSession(counts_seq=[(40, 2), (40, 5)])
        block = self._freshness(fake)
        self.assertTrue(block["render_fresh"])
        self.assertEqual(block["method"], "forced-redraw")
        self.assertEqual((block["fresh_before"], block["fresh_after"]), (2, 5))
        self.assertEqual(fake.shots, [])

    # -- controlled leg: pixel proof + saturation witness + pause restore ----
    def test_frozen_counters_controlled_step_proves_new_pixels(self):
        payloads = [self._png(1), self._png(1), self._png(1), self._png(2)]
        fake = self._FakeStepSession(payloads=payloads)  # 冻结计数 40/7
        ev, tmp = self._ev()
        block = self.pv.freshness_block(fake, ev, "GEO-03-a",
                                        controlled=True)[0]
        self.assertTrue(block["render_fresh"])
        self.assertEqual(block["method"], "new-output-pixels")
        self.assertIn(block["method"], self.gate.RENDER_FRESH_METHODS)
        # 计数语义 0→1 仅在真实解码像素变化后成立（非伪造）
        self.assertEqual((block["fresh_before"], block["fresh_after"]), (0, 1))
        # 计数饱和见证：计数冻结 40/40 但像素前进
        self.assertEqual(block["counter_saturation_witness"]["fresh"], [40, 40])
        leg = block["controlled_leg"]
        self.assertTrue(leg["new_output_pixels"] and leg["stability_ok"])
        self.assertGreater(leg["pixel_diff"]["differing_points"], 0)
        # 盲采 alias 负例：0.5s 两采同像素（重复 pattern），仅作见证
        self.assertIsNotNone(leg["blind_alias_witness"])
        self.assertFalse(leg["blind_alias_witness"]["new_pixels"])
        # 精确 IPC 记录
        self.assertEqual(leg["ipc_records"][0]["cmd"], ["frame-step"])
        self.assertEqual(leg["ipc_records"][0]["error"], "success")
        self.assertEqual(fake.cmds[0], ["frame-step"])
        # 实际暂停读回 + finally 恢复读回
        pc = leg["pause_control"]
        self.assertEqual(pc["pause_before"], False)
        self.assertEqual(pc["paused_readback"], True)
        self.assertEqual(pc["pause_restored"], False)
        self.assertTrue(pc["restore_ok"])
        self.assertEqual(fake._pause, fake.pause0)
        # time-pos/FPS 仅旁证（确有变化，但方法不来自它们）
        self.assertNotEqual(leg["witnesses"]["pre"]["time_pos"],
                            leg["witnesses"]["post"]["time_pos"])
        self.assertNotIn("time-pos", block["method"])
        self.assertTrue((Path(tmp) / "ev" / "GEO-03-a.step-a.png").exists())
        self.assertTrue((Path(tmp) / "ev" / "GEO-03-a.step-b.png").exists())

    def test_stale_epoch_rejects_pixel_proof(self):
        payloads = [self._png(1), self._png(1), self._png(1), self._png(2)]
        fake = self._FakeStepSession(payloads=payloads, epoch_flip=True)
        block = self._freshness(fake, controlled=True)
        self.assertFalse(block["render_fresh"])
        self.assertIsNone(block["method"])
        self.assertIsNone(block["fresh_before"])  # 不虚造 0→1
        self.assertIsNone(block["fresh_after"])
        leg = block["controlled_leg"]
        self.assertTrue(leg["new_output_pixels"])   # 像素确变，但…
        self.assertFalse(leg["stability_ok"])       # epoch 不稳定 → 不采信
        self.assertFalse(leg["witnesses"]["epoch_stable"])
        self.assertIn("必须 FAIL", block["metric_note"])

    def test_no_artifact_when_screenshots_fail(self):
        fake = self._FakeStepSession(fail_screens=True)
        block = self._freshness(fake, controlled=True)
        self.assertFalse(block["render_fresh"])
        self.assertIsNone(block["method"])
        self.assertIsNone(block["fresh_before"])
        leg = block["controlled_leg"]
        self.assertFalse(leg["new_output_pixels"])
        self.assertIsNone(leg["pixel_diff"])
        # 暂停仍被 finally 恢复
        self.assertTrue(leg["pause_control"]["restore_ok"])

    def test_pre_existing_artifacts_kept_not_overwritten(self):
        ev, tmp = self._ev()
        sentinel = ev.dir / "GEO-03-a.step-a.png"
        ev.dir.mkdir(parents=True, exist_ok=True)
        sentinel.write_bytes(b"SENTINEL-NOT-A-PNG")
        fake = self._FakeStepSession(payloads=[self._png(1), self._png(1)])
        block = self.pv.freshness_block(fake, ev, "GEO-03-a",
                                        controlled=True)[0]
        self.assertEqual(sentinel.read_bytes(), b"SENTINEL-NOT-A-PNG")
        leg = block["controlled_leg"]
        self.assertFalse(leg["new_output_pixels"])
        self.assertTrue(any("pre-existed" in n for n in leg["artifact_notes"]))
        self.assertTrue(leg["pause_control"]["restore_ok"])

    def test_pause_restored_even_when_frame_step_pipe_dies(self):
        payloads = [self._png(1), self._png(1), self._png(1)]
        fake = self._FakeStepSession(payloads=payloads,
                                     step_raises=RuntimeError("pipe closed"))
        with self.assertRaises(RuntimeError):
            self._freshness(fake, controlled=True)
        # finally 恢复实际读回的原始暂停态
        self.assertEqual(fake._pause, fake.pause0)
        pause_sets = [v for (n, v) in fake.sets if n == "pause"]
        self.assertEqual(pause_sets[-1], fake.pause0)

    def test_all_emitted_methods_stay_in_checker_contract(self):
        methods = []
        for fake, kw in (
                (self._FakeStepSession(counts_seq=[(3, 2), (7, 2)]), {}),
                (self._FakeStepSession(counts_seq=[(40, 2), (40, 5)]), {}),
                (self._FakeStepSession(
                    payloads=[self._png(1), self._png(1),
                              self._png(1), self._png(2)]),
                 {"controlled": True}),
                (self._FakeStepSession(fail_screens=True),
                 {"controlled": True}),
        ):
            methods.append(self._freshness(fake, **kw)["method"])
        self.assertTrue(
            set(m for m in methods if m is not None)
            <= self.gate.RENDER_FRESH_METHODS,
            f"方法越契约: {methods}")
        self.assertIn("new-output-pixels", methods)
        self.assertIn(None, methods)  # 诚实 FAIL 也是契约内结果

    def test_case_geo03_pins_controlled_leg(self):
        src = Path(self.pv.__file__).read_text(encoding="utf-8")
        self.assertIn(
            'freshness_block(s, ev, f"{case}-a", controlled=True)', src)


if __name__ == "__main__":
    unittest.main()
