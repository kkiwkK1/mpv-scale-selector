"""Unit tests for the P1 (p1-001) verification support library.

These tests are fast, stdlib-only, and never launch mpv. They guard:
  * deterministic synthetic media generation,
  * the temp-env isolation rules,
  * the ownership oracles used to cross-check the plugin's "关"/gear math,
  * static policy audits over the SHIPPED plugin source and gear table
    (LS1/BCAS disabled with real reasons, no glsl-shaders-clr, F8-only key),
  * evidence-file hygiene (UTF-8/LF, valid JSON).

Real-mpv objective checks live in tools/p1_verify.py (see
docs/验证/开发/p1-001/README.md); they are not part of unit tests.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p1_lib as lib  # noqa: E402


class TestCloseEnough(unittest.TestCase):
    def test_scalars(self):
        self.assertTrue(lib.close_enough("bicubic", "bicubic"))
        self.assertFalse(lib.close_enough("bicubic", "bilinear"))

    def test_floats(self):
        self.assertTrue(lib.close_enough(0.25, 0.25))
        self.assertTrue(lib.close_enough(0.25, 0.25 + 1e-12))
        self.assertFalse(lib.close_enough(0.25, 0.5))

    def test_lists(self):
        self.assertTrue(lib.close_enough(["a", "b"], ["a", "b"]))
        self.assertFalse(lib.close_enough(["a"], ["a", "b"]))
        self.assertTrue(lib.close_enough([0.1, 0.2], [0.1, 0.2 + 1e-12]))

    def test_bool_not_1(self):
        self.assertTrue(lib.close_enough(True, True))
        # bool must not silently equal 1
        self.assertFalse(lib.close_enough(True, 1))


class TestY4mGenerator(unittest.TestCase):
    def test_deterministic_and_wellformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.y4m"
            p2 = Path(tmp) / "b.y4m"
            s1 = lib.generate_y4m(p1)
            s2 = lib.generate_y4m(p2, )
            self.assertEqual(s1, s2, "same parameters must yield identical bytes")
            head = p1.read_bytes()[:44]
            self.assertTrue(head.startswith(b"YUV4MPEG2 W320 H240 F24:1"))
            size = p1.stat().st_size
            frames = 48
            frame_bytes = 320 * 240 + 2 * (160 * 120)
            header_len = head.index(b"\n") + 1
            self.assertEqual(size, header_len + frames * (len(b"FRAME\n") + frame_bytes))

    def test_parameters_change_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.y4m"
            p2 = Path(tmp) / "b.y4m"
            s1 = lib.generate_y4m(p1, frames=4)
            s2 = lib.generate_y4m(p2, frames=8)
            self.assertNotEqual(s1, s2)


class TestIsolatedEnv(unittest.TestCase):
    def test_env_isolation(self):
        env = lib.make_env("unittest-env")
        try:
            self.assertIn("p1-001-unittest-env", str(env.root))
            for d in (env.cfg, env.home, env.appdata, env.cache,
                      env.watch_later, env.shots):
                self.assertTrue(d.exists())
            e = env.env()
            self.assertEqual(e["HOME"], str(env.home))
            self.assertEqual(e["APPDATA"], str(env.appdata))
            allowed = set(lib.SAFE_ENV_KEYS) | {"HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
            self.assertTrue(set(e.keys()) <= allowed,
                            "child env must be a minimal allowlist (no credentials)")
        finally:
            env.cleanup()
        self.assertFalse(env.root.exists())

    def test_env_and_pipe_session_param(self):
        """限域修正：显式 session 参数使命名空间（临时根/IPC 管道）随会话变化。"""
        env = lib.make_env("unittest-session", session="p1-002")
        try:
            self.assertIn("p1-002-unittest-session", str(env.root))
            s = lib.MpvSession(env, "caseX", env.root, session="p1-002")
            self.assertTrue(s.pipe_name.startswith("p1-002-caseX"))
            self.assertEqual(s.session, "p1-002")
        finally:
            env.cleanup()

    def test_write_mpv_conf_pins_backend(self):
        env = lib.make_env("unittest-conf")
        try:
            env.write_mpv_conf(baseline_shaders=["~~/x.glsl"])
            text = (env.cfg / "mpv.conf").read_text(encoding="utf-8")
            self.assertIn("vo=gpu-next", text)
            self.assertIn("gpu-api=vulkan", text)
            self.assertIn("glsl-shaders=~~/x.glsl", text)
        finally:
            env.cleanup()

    def test_input_conf_has_no_f8_and_has_external_paths(self):
        env = lib.make_env("unittest-input")
        try:
            env.write_input_conf()
            text = (env.cfg / "input.conf").read_text(encoding="utf-8")
            self.assertNotIn("F8", text, "F8 must stay free for the plugin menu")
            for marker in ("CTRL+1", "CTRL+0", "F5", "F6", "change-list glsl-shaders"):
                self.assertIn(marker, text)
        finally:
            env.cleanup()

    def test_stub_gears_are_named_and_rendered(self):
        env = lib.make_env("unittest-gears")
        try:
            product = lib.GEARS_CONF.read_text(encoding="utf-8")
            stubs = [{"id": "p1-test-shader", "label": "stub",
                      "set": ["scale=bilinear", "glsl-shaders+=~~/s.glsl"]}]
            env.write_gears_conf(product, stub_gears=stubs)
            text = (env.cfg / "script-opts" / "scale-selector-gears.conf").read_text(encoding="utf-8")
            self.assertIn("p1-test-shader", text)
            self.assertIn("p1_test_shader_set=scale=bilinear;glsl-shaders+=~~/s.glsl", text)
        finally:
            env.cleanup()

    def test_stub_gear_guard(self):
        env = lib.make_env("unittest-guard")
        try:
            product = lib.GEARS_CONF.read_text(encoding="utf-8")
            with self.assertRaises(AssertionError):
                env.write_gears_conf(product, stub_gears=[{"id": "fsr1", "label": "x"}])
        finally:
            env.cleanup()


class TestOracles(unittest.TestCase):
    BASE = {"glsl-shaders": ["~~/user.glsl"], "scale": "bicubic"}
    LAST = {"glsl-shaders": ["~~/user.glsl", "~~/a.glsl"], "scale": "bilinear"}
    WROTE = {"glsl-shaders": True, "scale": True}

    def test_untouched_restores_baseline(self):
        restores, kept = lib.expected_off_actions(
            self.BASE, self.LAST, self.WROTE, ["~~/a.glsl"],
            {"glsl-shaders": ["~~/user.glsl", "~~/a.glsl"], "scale": "bilinear"})
        self.assertEqual(kept, {})
        self.assertEqual(restores["scale"], "bicubic")
        self.assertEqual(restores["glsl-shaders"], ["~~/user.glsl"])

    def test_external_scalar_kept(self):
        restores, kept = lib.expected_off_actions(
            self.BASE, self.LAST, self.WROTE, ["~~/a.glsl"],
            {"glsl-shaders": ["~~/user.glsl", "~~/a.glsl"], "scale": "spline36"})
        self.assertEqual(kept.get("scale"), "spline36")
        self.assertNotIn("scale", restores)

    def test_external_list_element_level(self):
        restores, kept = lib.expected_off_actions(
            self.BASE, self.LAST, self.WROTE, ["~~/a.glsl"],
            {"glsl-shaders": ["~~/user.glsl", "~~/a.glsl", "~~/ext.glsl"],
             "scale": "bilinear"})
        self.assertIn("glsl-shaders", kept)
        self.assertEqual(restores["glsl-shaders"], ["~~/user.glsl", "~~/ext.glsl"])

    def test_external_clr_not_overridden(self):
        restores, kept = lib.expected_off_actions(
            self.BASE, self.LAST, self.WROTE, ["~~/a.glsl"],
            {"glsl-shaders": [], "scale": "bilinear"})
        self.assertIn("glsl-shaders", kept)
        self.assertEqual(restores["glsl-shaders"], [])

    def test_never_written_prop_ignored(self):
        restores, kept = lib.expected_off_actions(
            self.BASE, {}, {}, [],
            {"glsl-shaders": ["~~/user.glsl"], "scale": "spline36"})
        self.assertEqual(restores, {})
        self.assertEqual(kept, {})

    def test_expected_gear_list(self):
        current = ["~~/user.glsl", "~~/old.glsl"]
        out = lib.expected_gear_list(current, ["~~/old.glsl"], adds=["~~/new.glsl"])
        self.assertEqual(out, ["~~/user.glsl", "~~/new.glsl"])


class TestStaticPolicyAudits(unittest.TestCase):
    """Guard the shipped product files directly (no copies)."""

    def test_plugin_source_audit(self):
        audit = lib.audit_plugin_source()
        for key, ok in audit.items():
            self.assertTrue(ok, f"plugin source audit failed: {key}")

    def test_gears_conf_audit(self):
        audit = lib.audit_gears_conf()
        for key, ok in audit.items():
            self.assertTrue(ok, f"gears conf audit failed: {key}")

    def test_pipe_namespace(self):
        self.assertEqual(lib.PIPE_NAMESPACE, "\\\\" + ".\\" + "pipe" + "\\")


class TestEvidenceWriter(unittest.TestCase):
    def test_json_utf8_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = lib.Evidence(Path(tmp))
            p = ev.write_json("x.json", {"状态": "pass", "list": [1, 2]})
            raw = p.read_bytes()
            self.assertNotIn(b"\r", raw)
            data = json.loads(raw.decode("utf-8"))
            self.assertEqual(data["状态"], "pass")

    def test_transcript_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = lib.Evidence(Path(tmp))
            p = ev.save_transcript("t.jsonl", [{"req": ["get_property", "scale"]},
                                               {"resp": {"error": "success"}}])
            raw = p.read_bytes()
            self.assertNotIn(b"\r", raw)
            lines = raw.decode("utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["req"][1], "scale")

    def test_write_text_lf_normalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.txt"
            lib.write_text_lf(p, "a\r\nb\n")
            self.assertEqual(p.read_bytes(), b"a\nb\n")


if __name__ == "__main__":
    unittest.main()
