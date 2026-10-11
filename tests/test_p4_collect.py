# -*- coding: utf-8 -*-
"""P4 unit tests for tools/p4_collect.py (session p4-001, batch B2, unit W2).

Mock tests that REALLY invoke the safe collector entries (no hand-set
booleans, no fabricated passes):
  * preflight: reuse-dir refusal BEFORE any spawn (subprocess is patched to
    explode so a spawn would fail the test), work-permit gate, B1-r2
    candidate pin re-hash (real repo + tamper), disk budget gate;
  * runtime hygiene: tree inventory hash/size + change detection, dirty
    runtime findings, zero-write witness violation/clean, clone with missing
    DLL / wrong sha / reparse components;
  * environment allowlist: credential-shaped keys never pass through,
    profiles inside the sandbox, write-protection flags, rebuilt PATH;
  * private vpy relocation: exactly one LoadPlugin line rewritten, algorithm
    hash identical for path-only differences and different for any
    non-path difference, record carries hashes/line numbers only;
  * identity sample rife-identity-short-v1: Y4M payload completeness,
    12 frames, marker ordinal, (8,3) displacement, U/V=128, truncation and
    byte-flip detection, 24/30 fps variants;
  * LF10 native mapping + atomic snapshot assembly validated through the
    frozen lib.validate_snapshot;
  * run records through the REAL p4_analyze/p4_check_evidence gates:
    VALID pilot, no-samples honesty (REJECTED_PASS_NO_TIMING),
    REJECTED_FPS_UNBOUND, REJECTED_FAKE_RIFE_METADATA,
    REJECTED_GEOMETRY_MISMATCH, REJECTED_WINDOW_TRUNCATED,
    REJECTED_WINDOW_SCHEDULE (late slot), and the N1 wiring
    (lib.verify_required_inputs + ce.gate_run_evidence) both missing and
    planted;
  * process ownership: a real python sleeper child is spawned, recorded in
    pid.json, quit on success and killed through a finally on exceptions;
    the manifest is refused while own handles are open;
  * launch args never contain a hardcoded --fullscreen=no (the old p1 bug
    is not inherited; the real osd readback owns the verification);
  * scheduling loops with injected clocks: warmup consecutive-stabilisation,
    flaky non-stabilisation, slot targets, late slots recorded as-is;
  * GPU pollution decision gates (memory/util/foreign mpv/unverifiable);
  * production refusal at the CLI argv level; CLI help + real preflight;
  * B2-r3 scoped repairs (brief P4-B2首载修正brief-v3.md): R3-1 the auto
    sandbox root is a NON-EXISTING unpredictable name created only by
    create_sandbox (incl. the FULL CLI default path without --sandbox-root
    on a fake pinned runtime); R3-2 launch args never carry --no-config —
    --config-dir is the only config root, user scripts load only via
    explicit --script entries from the never-scanned cfg/p4-scripts dir
    (real-mpv smoke evidence: --load-scripts=no also suppresses explicit
    --script, so it must not be used), proven by a real-argv config-smoke
    (fake-mpv child in tests, real mpv.exe vo=null smoke as author
    evidence); R3-3 verdict
    gates bind to the unique real log (missing/empty/argv-only/passthrough
    never EVIDENCED) and magic-classified output images; R3-4 gpu_started
    UNKNOWN when the log is missing, failure manifests carry
    NOT_ESTABLISHED, proof stage runs only after handles close; R3-5
    all_frames_unique honesty + the 50% blend difference distribution with
    judgement NOT_ESTABLISHED (no preregistered threshold).

Stdlib + tempfile only; no mpv/GPU/VS/nvidia-smi is started; the only real
child processes are short python sleepers owned and reaped by the tests; no
credentials are read; all writes stay inside temp dirs.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p4_collect as col  # noqa: E402
import p4_lib as lib  # noqa: E402
import p4_analyze as an  # noqa: E402

def _tmp(self, prefix="p4col-test-"):
    path = Path(tempfile.mkdtemp(prefix=prefix))
    self.addCleanup(shutil.rmtree, str(path), True)
    return path


def _no_spawn(self):
    """Patch both spawn surfaces so a test that must never start a process
    fails loudly if it tries (the safe entries must refuse BEFORE spawn)."""
    boom = unittest.mock.Mock(
        side_effect=AssertionError("a process was spawned in a no-spawn test"))
    p1 = unittest.mock.patch.object(col.subprocess, "Popen", boom)
    p2 = unittest.mock.patch.object(col.subprocess, "run", boom)
    p1.start()
    p2.start()
    self.addCleanup(p1.stop)


def _fake_run(results):
    """Fake subprocess.run keyed by the executable name."""
    def run(cmd, **kwargs):
        exe = str(cmd[0]).lower()
        for key, (rc, out, err) in results.items():
            if key in exe:
                return subprocess.CompletedProcess(cmd, rc,
                                                   out.encode("utf-8"),
                                                   err.encode("utf-8"))
        raise AssertionError("unexpected command in test: %r" % (cmd,))
    return run


def _pass_node(desc, avg, count=5, samples="default", omit_count=False):
    node = {"desc": desc, "last": avg * 2, "avg": avg, "peak": avg * 3,
            "samples": ([avg] * count if samples == "default"
                        else list(samples))}
    if not omit_count:
        node["count"] = count
    return node


def _payload(i, osd=None, fresh="default", epoch=0, time_pos=None,
             fps=24.0):
    if fresh == "default":
        fresh = [_pass_node("pass A", 900 + i), _pass_node("pass A", 800)]
    return {
        "epoch": epoch,
        "vop": {"pixelformat": "yuv420p", "w": 1920.0, "h": 1080.0,
                "dw": 1920.0, "dh": 1080.0},
        "osd": osd if osd is not None else
        {"w": 2560.0, "h": 1440.0,
         "margins": {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}},
        "vo_passes": {"fresh": fresh,
                      "redraw": [_pass_node("pass A redraw", 380)]},
        "counters": {"dropped-frame-count": 0, "decoder-frame-drop-count": 0},
        "time_pos": (12.0 + i) if time_pos is None else time_pos,
        "fps_fields": {"estimated_vf_fps": fps, "fps": fps,
                       "container_fps": fps},
    }


_MEDIA_SHA = "b" * 64


def _snapshots(walls=None, payload_fn=None, anchor=1000.0, n=10, start=0):
    src = col.source_block_for("motion24", _MEDIA_SHA)
    payload_fn = payload_fn or (lambda i: _payload(i))
    walls = walls if walls is not None else [anchor + k for k in range(n)]
    return [col.payload_to_snapshot(start + k, walls[k], payload_fn(k),
                                    source_block=src)
            for k in range(n)]


def _window_record(anchor=1000.0, start=0, count=10):
    return {"start_snapshot_index": start, "sample_count": count,
            "warmup_end_monotonic_s": anchor}


def _pilot_spec(rife="off", arm="baselineHQ"):
    return lib.make_trial_spec("G1_equalrect_main", arm, rife, 1,
                               run_kind="pilot",
                               plan_sha256=lib.PLAN_SHA256)


def _record(snaps, spec=None, observed=24.0, window=None, hq=None):
    return col.build_run_record(
        spec or _pilot_spec(), snaps, window or _window_record(),
        hq or ("c" * 64), observed_output_fps=observed,
        media_sha256=_MEDIA_SHA)


# ---------------------------------------------------------------------------
# sandbox subprocess environment
# ---------------------------------------------------------------------------


class TestSandboxEnv(unittest.TestCase):
    def test_env_allowlist_strips_credentials(self):
        root = _tmp(self)
        layout = col.create_sandbox(root / "p4-001" / "sbx", temp_base=root)
        seeded = {"P4_TEST_API_KEY": "sk-secret", "MY_SERVICE_TOKEN": "t",
                  "OPENAI_API_KEY": "x", "SOME_SECRET": "y"}
        for key, value in seeded.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)
        env = col.build_subprocess_env(layout)
        for key in seeded:
            self.assertNotIn(key, env)
        col.assert_env_has_no_credentials(env)

    def test_env_profiles_inside_sandbox_and_flags_set(self):
        root = _tmp(self)
        layout = col.create_sandbox(root / "p4-001" / "sbx", temp_base=root)
        env = col.build_subprocess_env(layout)
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                    "TEMP", "TMP"):
            self.assertTrue(env[key].startswith(str(root)),
                            "%s escaped the sandbox: %s" % (key, env[key]))
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertIn(col.SAMPLER_MSG_REQUEST, col.SAMPLER_LUA_TEMPLATE)
        self.assertIn(col.SAMPLER_MSG_REPLY, col.SAMPLER_LUA_TEMPLATE)
        self.assertTrue(env["VSSCRIPT_PATH"].endswith(
            col.VSSCRIPT_REL.replace("/", os.sep)))
        self.assertTrue(env["PYTHONPYCACHEPREFIX"].startswith(str(root)))

    def test_env_path_is_rebuilt_not_inherited(self):
        root = _tmp(self)
        layout = col.create_sandbox(root / "p4-001" / "sbx", temp_base=root)
        os.environ["PATH"] = str(root / "somewhere-else")
        self.addCleanup(os.environ.__setitem__, "PATH", os.environ["PATH"])
        env = col.build_subprocess_env(layout)
        entries = env["PATH"].split(os.pathsep)
        self.assertIn(str(layout["clone_vs"]), entries)
        self.assertNotIn(str(root / "somewhere-else"), entries)
        self.assertTrue(entries[-1].lower().endswith("system32"))

    def test_audit_catches_leaked_env(self):
        root = _tmp(self)
        layout = col.create_sandbox(root / "p4-001" / "sbx", temp_base=root)
        env = col.build_subprocess_env(layout)
        bad = dict(env)
        bad["DEPLOY_TOKEN"] = "leak"
        with self.assertRaises(col.CredentialLeakError):
            col.assert_env_has_no_credentials(bad)


# ---------------------------------------------------------------------------
# preflight gates
# ---------------------------------------------------------------------------


class TestPreflight(unittest.TestCase):
    def test_existing_trial_dir_refused_before_any_spawn(self):
        root = _tmp(self)
        existing = root / "trial"
        existing.mkdir()
        _no_spawn(self)
        with self.assertRaises(col.SpawnRefused):
            col.ensure_fresh_trial_dir(existing)
        with self.assertRaises(col.SpawnRefused):
            col.preflight_collect("pilot", evidence_dir=existing,
                                  sandbox_parent=root)

    def test_fresh_trial_dir_created_once_only(self):
        root = _tmp(self)
        fresh = col.ensure_fresh_trial_dir(root / "t1")
        self.assertTrue(fresh.is_dir())
        with self.assertRaises(col.SpawnRefused):
            col.ensure_fresh_trial_dir(fresh)

    def test_existing_sandbox_root_refused(self):
        root = _tmp(self)
        (root / "p4-001" / "sbx").mkdir(parents=True)
        with self.assertRaises(col.SpawnRefused):
            col.create_sandbox(root / "p4-001" / "sbx", temp_base=root)

    def test_work_permit_gate_missing_tree_blocked(self):
        root = _tmp(self)
        with self.assertRaises(col.PreflightBlocked) as ctx:
            col.check_work_permit_or_raise(root)
        self.assertIn("work_permit", str(ctx.exception))

    def test_work_permit_gate_passes_on_real_repo(self):
        result = col.check_work_permit_or_raise(None)
        self.assertTrue(result["ok"])

    def test_b1_candidate_pins_pass_on_real_repo(self):
        result = col.check_b1_candidate_pins(None)
        self.assertEqual(result["sha256"], col.B1_CANDIDATE_SHA256)
        self.assertGreater(result["pinned_files"], 30)

    def test_b1_candidate_tamper_detected(self):
        root = _tmp(self)
        target = root / col.B1_CANDIDATE_REL
        target.parent.mkdir(parents=True)
        target.write_bytes(b'{"files": {}, "tampered": true}')
        with self.assertRaises(col.PreflightBlocked):
            col.check_b1_candidate_pins(root)

    def test_b1_candidate_missing_blocked(self):
        root = _tmp(self)
        with self.assertRaises(col.PreflightBlocked):
            col.check_b1_candidate_pins(root)

    def test_disk_budget_insufficient_blocked(self):
        root = _tmp(self)
        usage = shutil.disk_usage(str(root))
        fake = shutil._ntuple_diskusage(usage.total, usage.used, 10)
        with unittest.mock.patch.object(col.shutil, "disk_usage",
                                        return_value=fake):
            with self.assertRaises(col.PreflightBlocked):
                col.check_disk_budget(root)
        with unittest.mock.patch.object(col.shutil, "disk_usage",
                                        return_value=usage):
            ok = col.check_disk_budget(root, required_bytes=1024)
            self.assertTrue(ok["ok"])

    def test_unknown_mode_refused_as_production(self):
        with self.assertRaises(col.ProductionRefused):
            col.preflight_collect("production")
        with self.assertRaises(col.ProductionRefused):
            col.preflight_collect("matrix-benchmark")


# ---------------------------------------------------------------------------
# runtime hygiene / clone / zero-write witness
# ---------------------------------------------------------------------------


class TestRuntimeWitness(unittest.TestCase):
    def _mini_tree(self, root):
        src = root / "rt"
        (src / "sub").mkdir(parents=True)
        (src / "a.dll").write_bytes(b"AA")
        (src / "sub" / "b.txt").write_bytes(b"BB")
        return src

    def test_inventory_hashes_and_detects_change(self):
        root = _tmp(self)
        src = self._mini_tree(root)
        inv1 = col.tree_inventory(src)
        self.assertEqual(set(inv1), {"a.dll", "sub/b.txt"})
        self.assertEqual(inv1["a.dll"]["sha256"],
                         lib.sha256_bytes(b"AA"))
        (src / "c.bin").write_bytes(b"C")
        diff = col.inventory_diff(inv1, col.tree_inventory(src))
        self.assertFalse(diff["clean"])
        self.assertEqual(diff["added"], ["c.bin"])

    def test_dirty_runtime_findings_reported(self):
        root = _tmp(self)
        src = self._mini_tree(root)
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "x.pyc").write_bytes(b"P")
        (src / "vs-temp-dl").mkdir()
        (src / "vs-temp-dl" / "dl.zip").write_bytes(b"Z")
        report = col.check_runtime_tree_hygiene(col.tree_inventory(src))
        self.assertEqual(report["n_findings"], 2)
        self.assertTrue(report["clone_required"])
        kinds = {f["kind"] for f in report["findings"]}
        self.assertEqual(kinds, {"pycache/pyc", "historical download dir"})

    def test_zero_write_witness_clean_and_violation(self):
        root = _tmp(self)
        src = self._mini_tree(root)
        before = col.tree_inventory(src)
        self.assertTrue(col.zero_write_witness("rt", before,
                                               col.tree_inventory(src))
                        ["clean"])
        (src / "late.bin").write_bytes(b"L")
        with self.assertRaises(col.ZeroWriteViolation):
            col.zero_write_witness("rt", before, col.tree_inventory(src))

    def test_clone_copies_and_verifies(self):
        root = _tmp(self)
        src = self._mini_tree(root)
        manifest = col.clone_tree(src, root / "clone")
        self.assertEqual(manifest["files"], 2)
        self.assertEqual(manifest["sha256"]["a.dll"],
                         lib.sha256_bytes(b"AA"))
        self.assertTrue((root / "clone" / "sub" / "b.txt").is_file())

    def test_clone_refuses_existing_destination(self):
        root = _tmp(self)
        src = self._mini_tree(root)
        (root / "clone").mkdir()
        with self.assertRaises(col.RuntimeIdentityBlocked):
            col.clone_tree(src, root / "clone")

    def test_clone_missing_dll_blocked(self):
        root = _tmp(self)
        vs_src = self._mini_tree(root / "vs")
        # a real-shaped vs tree also needs the pinned runtime files; without
        # them the pin validation lists them as missing
        rife_src = root / "rife"
        rife_src.mkdir()
        with self.assertRaises(col.RuntimeIdentityBlocked) as ctx:
            col.clone_runtime(root / "sbx", vs_src=vs_src, rife_src=rife_src,
                              mpv_exe=self._fake_mpv(root))
        failures = ctx.exception.args[0]["failures"]
        self.assertTrue(any("missing" in f["reason"] for f in failures),
                        "the missing rife/vs pin files must be listed")

    def test_clone_wrong_sha_blocked(self):
        root = _tmp(self)
        vs_src = self._mini_tree(root / "vs")
        rife_src = root / "rife"
        dll = rife_src / col.RIFE_DLL_REL
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"not-the-real-dll")
        with self.assertRaises(col.RuntimeIdentityBlocked) as ctx:
            col.clone_runtime(root / "sbx", vs_src=vs_src, rife_src=rife_src,
                              mpv_exe=self._fake_mpv(root))
        failures = ctx.exception.args[0]["failures"]
        self.assertTrue(any("sha" in f["reason"] for f in failures),
                        "the wrong-sha pin must be listed")

    def _fake_mpv(self, root):
        # any content that is not the survey preimage must be refused; a
        # sha256 preimage is impossible, so the pin check fails on purpose
        fs = root / "mpv.exe"
        fs.write_bytes(b"fake-mpv")
        return fs

    def test_mpv_pin_enforced(self):
        root = _tmp(self)
        vs_src = self._mini_tree(root / "vs")
        rife_src = root / "rife"
        with self.assertRaises(col.RuntimeIdentityBlocked) as ctx:
            col.clone_runtime(root / "sbx", vs_src=vs_src, rife_src=rife_src,
                              mpv_exe=self._fake_mpv(root))
        text = json.dumps(ctx.exception.args[0])
        self.assertIn("mpv.exe", text)
        self.assertIn(col.MPV_EXE_SHA256[:16], text)

    def test_clone_rejects_reparse_component(self):
        root = _tmp(self)
        src = self._mini_tree(root)
        link = root / "junction"
        made = False
        if sys.platform == "win32":
            try:
                import _winapi
                _winapi.CreateJunction(str(src), str(link))
                made = link.exists()
            except (OSError, ImportError):
                made = False
        if not made:
            self.skipTest("junction creation unavailable on this host")
        with self.assertRaises(col.PreflightBlocked):
            col.tree_inventory(link)
        with self.assertRaises(col.RuntimeIdentityBlocked):
            col.clone_tree(link, root / "clone")
        os.rmdir(str(link))   # junction removal, no target content touched


# ---------------------------------------------------------------------------
# private vpy relocation
# ---------------------------------------------------------------------------

_VPY_BODY = """import vapoursynth as vs
core = vs.get_core()
core.std.LoadPlugin('{dll}')
clip = core.std.BlankClip(width=640, height=360, format=vs.RGBS, length=100)
rgb = core.resize.Bicubic(clip, format=vs.RGBS)
inter = core.rife.RIFE(rgb, model=70, factor_num=2, factor_den=1,
                       gpu_thread=2)
inter.set_output()
"""


class TestVpyRelocation(unittest.TestCase):
    def _vpy(self, dll_path, extra_line=None):
        text = _VPY_BODY.format(dll=dll_path)
        if extra_line:
            text = text.replace("inter.set_output()",
                                extra_line + "\ninter.set_output()")
        return text.encode("utf-8")

    def test_only_loadplugin_line_rewritten(self):
        root = _tmp(self)
        clone_dll = root / "clone" / "rife" / col.RIFE_DLL_REL
        relocated, record = None, None
        out = col.relocate_vpy(self._vpy("D:/MPV/rife/librife_windows_x86-64"
                                         ".dll"), clone_dll)
        relocated = out["relocated_bytes"]
        record = out["record"]
        self.assertEqual(record["replaced_line_count"], 1)
        self.assertEqual(record["replaced_line_no"], 3)
        self.assertIn(str(clone_dll).replace("\\", "/"),
                      relocated.decode("utf-8"))
        self.assertNotIn("D:/MPV/rife", relocated.decode("utf-8"))
        self.assertIs(record["private_text_in_repo"], False)
        self.assertNotIn("text", {k.lower() for k in record})
        # line count unchanged
        self.assertEqual(len(relocated.split(b"\n")),
                         len(self._vpy("x").split(b"\n")))

    def test_algorithm_hash_same_for_path_only_difference(self):
        root = _tmp(self)
        a = self._vpy("D:/MPV/rife/librife_windows_x86-64.dll")
        b = self._vpy("E:/elsewhere/librife_windows_x86-64.dll")
        self.assertNotEqual(lib.sha256_bytes(a), lib.sha256_bytes(b))
        self.assertEqual(col.vpy_algorithm_sha256(a),
                         col.vpy_algorithm_sha256(b))

    def test_algorithm_hash_differs_for_non_path_difference(self):
        root = _tmp(self)
        a = self._vpy("D:/MPV/rife/librife_windows_x86-64.dll")
        b = self._vpy("D:/MPV/rife/librife_windows_x86-64.dll",
                      extra_line="# algorithm tweak")
        self.assertNotEqual(col.vpy_algorithm_sha256(a),
                            col.vpy_algorithm_sha256(b))
        # relocation must refuse when the algorithm identity is tampered
        out = col.relocate_vpy(a, root / "clone.dll")
        tampered = out["relocated_bytes"].replace(
            b"factor_num=2", b"factor_num=3")
        self.assertNotEqual(col.vpy_algorithm_sha256(tampered),
                            out["record"]["algorithm_sha256"])

    def test_zero_or_multiple_loadplugin_lines_refused(self):
        root = _tmp(self)
        none = self._vpy("x").replace(b"core.std.LoadPlugin", b"# removed")
        with self.assertRaises(col.RuntimeIdentityBlocked):
            col.relocate_vpy(none, root / "c.dll")
        twice = self._vpy("x").replace(b"clip = core.std.BlankClip",
                                       b"core.std.LoadPlugin('q')\n"
                                       b"clip = core.std.BlankClip")
        with self.assertRaises(col.RuntimeIdentityBlocked):
            col.relocate_vpy(twice, root / "c.dll")


# ---------------------------------------------------------------------------
# identity sample rife-identity-short-v1
# ---------------------------------------------------------------------------


class TestIdentitySample(unittest.TestCase):
    def test_generation_payload_and_reproducibility(self):
        root = _tmp(self)
        p = root / "id24.y4m"
        rec = col.write_identity_sample_y4m(p, 24)
        self.assertEqual(rec["frames"], 12)
        frame_payload = 1920 * 1080 + 2 * (960 * 540)
        self.assertEqual(rec["frame_payload_bytes"], frame_payload)
        self.assertEqual(rec["bytes"], p.stat().st_size)
        self.assertEqual(rec["generator_sha256"], lib.library_sha256())
        verify = col.verify_identity_sample_y4m(p, 24)
        self.assertTrue(verify["reproducible"])
        self.assertTrue(verify["marker_ok"])
        self.assertEqual(verify["sha256"], rec["sha256"])
        # deterministic regeneration
        p2 = root / "id24-again.y4m"
        rec2 = col.write_identity_sample_y4m(p2, 24)
        self.assertEqual(rec2["sha256"], rec["sha256"])

    def test_marker_strip_and_displacement(self):
        y0, u0, v0 = col.identity_frame_planes(24, 0)
        y11, _, _ = col.identity_frame_planes(24, 11)
        self.assertEqual(col.identity_marker_index(y0), 0)
        self.assertEqual(col.identity_marker_index(y11), 11)
        p = col.IDENTITY_PARAMS
        # disk center (600+8k, 500+3k) carries a stripe value (180/235)
        for k in (0, 3, 11):
            y, _, _ = col.identity_frame_planes(24, k)
            cx = p["disk_center_initial"][0] + p["disk_delta_px"][0] * k
            cy = p["disk_center_initial"][1] + p["disk_delta_px"][1] * k
            self.assertIn(y[cy * 1920 + cx], (180, 235),
                          "disk center must move (8,3) px/frame")
        # background stays at the limited-range floor
        self.assertEqual(y0[1000 * 1920 + 100], 16)
        # diagonal stripes: 180/235 with period 12 along (x+y)
        self.assertEqual(y0[500 * 1920 + 600], 180)      # (600+500)%12 = 8
        self.assertEqual(y0[500 * 1920 + 606], 235)      # +6 -> other phase
        self.assertEqual(y0[500 * 1920 + 612], 180)      # +12 -> same phase

    def test_uv_constant_and_texture_square(self):
        y, u, v = col.identity_frame_planes(24, 5)
        self.assertEqual(set(u), {128})
        self.assertEqual(set(v), {128})
        p = col.IDENTITY_PARAMS
        ox, oy = p["texture_square_origin"]
        # 8px checker 64/144, static across frames (same bytes at frame 5)
        y0, _, _ = col.identity_frame_planes(24, 0)
        self.assertEqual(y[oy * 1920 + ox], y0[oy * 1920 + ox])
        self.assertIn(y[oy * 1920 + ox], p["texture_luma"])

    def test_truncation_and_corruption_detected(self):
        root = _tmp(self)
        p = root / "id.y4m"
        col.write_identity_sample_y4m(p, 24)
        data = p.read_bytes()
        trunc = root / "trunc.y4m"
        trunc.write_bytes(data[:-100])
        with self.assertRaises(col.SamplingPayloadError):
            col.verify_identity_sample_y4m(trunc, 24)
        flipped = bytearray(data)
        flipped[len(flipped) // 2] ^= 0xFF
        corrupt = root / "flip.y4m"
        corrupt.write_bytes(bytes(flipped))
        with self.assertRaises(col.SamplingPayloadError):
            col.verify_identity_sample_y4m(corrupt, 24)
        trailing = root / "trail.y4m"
        trailing.write_bytes(data + b"\x00")
        with self.assertRaises(col.SamplingPayloadError):
            col.verify_identity_sample_y4m(trailing, 24)

    def test_fps_variants_share_frames_differ_in_header(self):
        root = _tmp(self)
        p24 = root / "v24.y4m"
        p30 = root / "v30.y4m"
        r24 = col.write_identity_sample_y4m(p24, 24)
        r30 = col.write_identity_sample_y4m(p30, 30)
        self.assertNotEqual(r24["sha256"], r30["sha256"])
        h24 = p24.read_bytes()[:len(col.identity_y4m_header(24))]
        h30 = p30.read_bytes()[:len(col.identity_y4m_header(30))]
        self.assertIn(b"F24:1", h24)
        self.assertIn(b"F30:1", h30)
        # frames identical apart from the header
        body24 = p24.read_bytes()[len(h24):]
        body30 = p30.read_bytes()[len(h30):]
        self.assertEqual(body24, body30)
        col.verify_identity_sample_y4m(p30, 30)
        with self.assertRaises((col.SamplingPayloadError, lib.ValueContractError)):
            col.write_identity_sample_y4m(root / "v60.y4m", 60)

    def test_existing_target_refused(self):
        root = _tmp(self)
        p = root / "s.y4m"
        col.write_identity_sample_y4m(p, 24)
        with self.assertRaises(col.SpawnRefused):
            col.write_identity_sample_y4m(p, 24)


# ---------------------------------------------------------------------------
# LF10 native mapping + atomic snapshot assembly
# ---------------------------------------------------------------------------


class TestIpcMapping(unittest.TestCase):
    def test_parse_ipc_line_kinds(self):
        kind, key, obj = col.parse_ipc_line(
            b'{"error":"success","request_id":7}')
        self.assertEqual(kind, "response")
        self.assertEqual(key, 7)
        self.assertEqual(obj["error"], "success")
        kind, token, args = col.parse_ipc_line(json.dumps({
            "event": "client-message",
            "args": [col.SAMPLER_MSG_REPLY, "s3",
                     json.dumps({"epoch": 0})]}).encode())
        self.assertEqual((kind, token), ("client-message", "s3"))
        kind, _, _ = col.parse_ipc_line(b'{"event":"seek"}')
        self.assertEqual(kind, "event")
        kind, _, _ = col.parse_ipc_line(b"not json at all")
        self.assertIsNone(kind)

    def test_native_pass_entry_lf10_verbatim(self):
        node = {"desc": "pass A", "last": 100, "avg": 90, "peak": 110,
                "count": 5, "samples": [90, 90, 90, 90, 90]}
        entry = col.map_native_pass_entry(node, 0)
        self.assertEqual(entry["desc"], "pass A")
        self.assertEqual(entry["last_ns"], 100)
        self.assertEqual(entry["avg_ns"], 90)
        self.assertEqual(entry["peak_ns"], 110)
        self.assertEqual(entry["count"], 5)
        self.assertEqual(entry["samples_ns"], [90, 90, 90, 90, 90])
        self.assertEqual(entry["raw_node"], node)
        # duplicates kept verbatim (no value dedup)
        node2 = {"desc": "p", "last": 1, "avg": 1, "peak": 1, "count": 3,
                 "samples": [7, 7, 7]}
        self.assertEqual(col.map_native_pass_entry(node2, 1)["samples_ns"],
                         [7, 7, 7])

    def test_count_omitted_is_none_not_fabricated(self):
        node = {"desc": "p", "last": 1, "avg": 1, "peak": 1,
                "samples": [1, 1]}
        entry = col.map_native_pass_entry(node, 0)
        self.assertIsNone(entry["count"])
        snaps = _snapshots(payload_fn=lambda i: _payload(
            i, fresh=[node]), n=1)
        lib.validate_snapshot(snaps[0])   # count None is schema-legal

    def test_missing_samples_is_honest_empty_array(self):
        node = {"desc": "p", "last": 1, "avg": 1, "peak": 1}
        entry = col.map_native_pass_entry(node, 0)
        self.assertEqual(entry["samples_ns"], [])
        self.assertIsNone(entry["count"])

    def test_native_count_array_mismatch_crimes(self):
        bad = {"desc": "p", "last": 1, "avg": 1, "peak": 1, "count": 3,
               "samples": [1, 1]}
        with self.assertRaises(lib.ValueContractError):
            col.payload_to_snapshot(0, 1.0, _payload(0, fresh=[bad]))

    def test_payload_to_snapshot_validates_and_normalises(self):
        src = col.source_block_for("motion24", _MEDIA_SHA)
        snap = col.payload_to_snapshot(4, 100.5, _payload(4), source_block=src)
        lib.validate_snapshot(snap)
        self.assertEqual(snap["video_out_params"]["w"], 1920)  # 1920.0 -> int
        self.assertEqual(snap["osd_dimensions"]["ml"], 0)
        self.assertTrue(snap["same_window"])
        self.assertEqual(snap["counters"]["dropped-frame-count"], 0)
        self.assertEqual(snap["source"]["clip"], "motion24")
        self.assertEqual(snap["source"]["media_sha256"], _MEDIA_SHA)
        self.assertEqual(snap["source"]["generator_sha256"],
                         lib.library_sha256())

    def test_missing_vop_and_partial_margins_raise(self):
        with self.assertRaises(col.SamplingPayloadError):
            col.payload_to_snapshot(0, 1.0, {"epoch": 0, "osd": {}})
        partial = _payload(0)
        partial["osd"] = {"w": 2560.0, "h": 1440.0,
                          "margins": {"left": 0.0, "right": 0.0}}
        with self.assertRaises(col.SamplingPayloadError):
            col.payload_to_snapshot(0, 1.0, partial)
        bad_epoch = _payload(0)
        bad_epoch["epoch"] = None
        with self.assertRaises(col.SamplingPayloadError):
            col.payload_to_snapshot(0, 1.0, bad_epoch)

    def test_observed_fps_uses_estimated_vf_field(self):
        snaps = _snapshots()
        median, prov = col.observed_output_fps_from_snapshots(snaps, 0, 10)
        self.assertEqual(median, 24.0)
        self.assertIn("estimated-vf-fps", prov)
        snaps_none = _snapshots(payload_fn=lambda i: {
            **_payload(i), "fps_fields": {}})
        median2, prov2 = col.observed_output_fps_from_snapshots(
            snaps_none, 0, 10)
        self.assertIsNone(median2)
        self.assertIn("absent", prov2)


# ---------------------------------------------------------------------------
# records through the real analysis + N1 wiring
# ---------------------------------------------------------------------------


class TestRecordsGates(unittest.TestCase):
    def test_valid_pilot_record_analyzes_valid(self):
        record = _record(_snapshots())
        an.validate_run_record(record)
        result = an.analyze_run(record)
        self.assertEqual(result["status"], an.RUN_STATUS_VALID)

    def test_missing_samples_rejected_not_coerced(self):
        def no_samples(i):
            # a real pass entry with NO timing evidence at all (empty
            # samples array, omitted count) — never coerced to a number
            return _payload(i, fresh=[_pass_node("pass A", 900, samples=[],
                                                 omit_count=True)])
        record = _record(_snapshots(payload_fn=no_samples))
        result = an.analyze_run(record)
        self.assertEqual(result["status"], "REJECTED_PASS_NO_TIMING")

    def test_empty_fresh_table_rejected(self):
        record = _record(_snapshots(payload_fn=lambda i: _payload(
            i, fresh=[])))
        result = an.analyze_run(record)
        self.assertIn(result["status"], ("REJECTED_PASS_TABLE_EMPTY",
                                         "REJECTED_PASS_NO_TIMING"))

    def test_fps_unbound_when_never_observed(self):
        record = _record(_snapshots(), observed=None)
        result = an.analyze_run(record)
        self.assertEqual(result["status"], "REJECTED_FPS_UNBOUND")

    def test_fake_rife_metadata_on_on_stratum(self):
        spec = _pilot_spec(rife="on")
        record = _record(_snapshots(), spec=spec, observed=24.0)
        result = an.analyze_run(record)
        self.assertEqual(result["status"], "REJECTED_FAKE_RIFE_METADATA")
        good = _record(_snapshots(), spec=spec, observed=48.0)
        self.assertEqual(an.analyze_run(good)["status"],
                         an.RUN_STATUS_VALID)

    def test_geometry_window_mismatch_rejected(self):
        bad_osd = {"w": 1920.0, "h": 1080.0,
                   "margins": {"left": 0.0, "right": 0.0, "top": 0.0,
                               "bottom": 0.0}}
        record = _record(_snapshots(payload_fn=lambda i: _payload(
            i, osd=bad_osd)))
        result = an.analyze_run(record)
        self.assertEqual(result["status"], "REJECTED_GEOMETRY_MISMATCH")

    def test_window_truncation_rejected(self):
        record = _record(_snapshots(n=9))
        result = an.analyze_run(record)
        self.assertEqual(result["status"], "REJECTED_WINDOW_TRUNCATED")

    def test_late_slot_schedule_rejection(self):
        # slot 5 lands +0.5s late (still monotonic) -> schedule violation
        anchor = 1000.0
        walls = [anchor + k for k in range(10)]
        walls[5] = anchor + 5.5
        record = _record(_snapshots(walls=walls))
        result = an.analyze_run(record)
        self.assertEqual(result["status"], "REJECTED_WINDOW_SCHEDULE")

    def test_record_builder_cross_checks_media_hash(self):
        snaps = _snapshots()
        with self.assertRaises(lib.ValueContractError):
            col.build_run_record(_pilot_spec(), snaps, _window_record(),
                                 "c" * 64, observed_output_fps=24.0,
                                 media_sha256="d" * 64)

    def test_n1_wiring_missing_media_manifest(self):
        root = _tmp(self)
        record = _record(_snapshots())
        with self.assertRaises(lib.MissingInputError):
            col.n1_gate_wiring(record, root=root)

    def test_n1_wiring_with_planted_manifest_gates_for_real(self):
        root = _tmp(self)
        (root / "docs").mkdir()
        shutil.copyfile(lib.workspace_root() / "docs/P4实施计划.json",
                        root / "docs" / "P4实施计划.json")
        (root / "tools").mkdir()
        shutil.copyfile(lib.workspace_root() / "tools" / "p4_lib.py",
                        root / "tools" / "p4_lib.py")
        media_dir = root / "docs" / "验证" / "开发" / "p4-001" / "media" / \
            "motion24"
        media_dir.mkdir(parents=True)
        (media_dir / "media-manifest.json").write_bytes(lib.strict_json_bytes(
            {"clip": "motion24", "media_sha256": _MEDIA_SHA}))
        record = _record(_snapshots())
        gate = col.n1_gate_wiring(record, root=root)
        self.assertIn("ok", gate)
        self.assertIsInstance(gate["violations"], list)
        self.assertEqual(gate.get("info"), [])

    def test_production_run_kind_refused(self):
        with self.assertRaises(col.ProductionRefused):
            col.run_timed_trial(
                Path(tempfile.gettempdir()) / "p4-001-never",
                "G1_equalrect_main", "baselineHQ", "off", 1,
                run_kind="production")
        with self.assertRaises(lib.ProductionLockedError):
            lib.make_trial_spec("G1_equalrect_main", "baselineHQ", "off", 1,
                                run_kind="production",
                                plan_sha256=lib.PLAN_SHA256)


# ---------------------------------------------------------------------------
# process ownership (real python sleeper children)
# ---------------------------------------------------------------------------


class TestSessionLifecycle(unittest.TestCase):
    def _sleeper_args(self):
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    def test_spawn_records_pid_and_quit_closes(self):
        root = _tmp(self)
        (root / "trial").mkdir()
        session = col.CollectSession(root / "trial", self._sleeper_args(),
                                     pipe_name=None, cwd=str(root))
        session.start(connect_ipc=False)
        # handles are open while the child runs
        self.assertFalse(session.handles_closed())
        pid = session.proc.pid
        self.assertTrue(session.pid_path.is_file())
        pid_doc = json.loads(session.pid_path.read_text("utf-8"))
        self.assertEqual(pid_doc["pid"], pid)
        self.assertEqual(pid_doc["owned_by"], col.COLLECT_REL)
        self.assertTrue(session.console_path.is_file())
        self.assertTrue(session.quit(timeout_s=10))
        self.assertIsNotNone(session.proc.poll())
        session.close()
        self.assertTrue(session.handles_closed())

    def test_exception_in_body_still_kills_child(self):
        root = _tmp(self)
        (root / "trial").mkdir()
        session = col.CollectSession(root / "trial", self._sleeper_args(),
                                     pipe_name=None, cwd=str(root))
        with self.assertRaises(RuntimeError):
            with session:
                session.start(connect_ipc=False)
                raise RuntimeError("body crime")
        self.assertIsNotNone(session.proc.poll())
        self.assertTrue(session.killed_by_tool or
                        session.proc.poll() is not None)
        self.assertTrue(session.handles_closed())

    def test_manifest_refused_while_handles_open(self):
        root = _tmp(self)
        (root / "trial").mkdir()
        session = col.CollectSession(root / "trial", self._sleeper_args(),
                                     pipe_name=None, cwd=str(root))
        session.start(connect_ipc=False)
        with self.assertRaises(col.HandleStateError):
            session.write_manifest({"mode": "unit-test"})
        session.quit(timeout_s=10)
        session.close()
        result = session.write_manifest({"mode": "unit-test",
                                         "gpu_started": False})
        self.assertTrue(session.manifest_path.is_file())
        doc = json.loads(session.manifest_path.read_text("utf-8"))
        self.assertTrue(doc["handles_closed_before_manifest"])
        self.assertIn("pid.json", doc["files"])
        with self.assertRaises(col.SpawnRefused):
            session.write_manifest({"mode": "again"})

    def test_manifest_reused_target_refused_at_construction(self):
        root = _tmp(self)
        trial = root / "trial"
        trial.mkdir()
        (trial / "console.txt").write_bytes(b"x")
        with self.assertRaises(col.SpawnRefused):
            col.CollectSession(trial, self._sleeper_args(), pipe_name=None)


class TestLaunchArgs(unittest.TestCase):
    def test_no_hardcoded_fullscreen_no_ever(self):
        args = col.build_mpv_launch_args("cfg", "pipe", "log.log",
                                         window=(2560, 1440))
        self.assertNotIn("--fullscreen=no", args)
        self.assertIn("--geometry=2560x1440", args)
        self.assertIn("--vo=gpu-next", args)
        self.assertIn("--gpu-api=vulkan", args)
        self.assertIn("--config-dir=cfg", args)
        full = col.build_mpv_launch_args("cfg", "pipe", "log.log",
                                         fullscreen=True)
        self.assertIn("--fullscreen=yes", full)
        image = col.build_mpv_launch_args("cfg", None, "log.log",
                                          vo="image")
        self.assertIn("--vo=image", args if False else image)
        self.assertNotIn("--gpu-api=vulkan", image)

    def test_r3_2_real_config_load_never_no_config(self):
        """R3-2 regression: --no-config neutralised the WHOLE sandbox config
        (identity-run-001); the argv must load the isolated config instead
        and load every Lua script explicitly from the never-scanned
        cfg/p4-scripts dir."""
        args = col.build_mpv_launch_args(
            "cfg", None, "log.log", vo="image",
            scripts=("cfg/p4-scripts/scale-selector.lua",
                     "cfg/p4-scripts/p4_collect_sampler.lua"))
        self.assertNotIn("--no-config", args)
        self.assertIn("--config-dir=cfg", args)
        self.assertIn("--script=%s"
                      % Path("cfg/p4-scripts/scale-selector.lua"), args)
        self.assertIn("--script=%s"
                      % Path("cfg/p4-scripts/p4_collect_sampler.lua"), args)
        probe = col.build_mpv_launch_args("cfg", None, "log.log",
                                          vo="image")
        self.assertNotIn("--no-config", probe)
        self.assertFalse([a for a in probe if a.startswith("--script=")],
                         "the identity probe loads NO script at all — and "
                         "says so explicitly, never by silence")

    def test_transcode_args_fixed_ffv1_yuv420p(self):
        args = col.build_transcode_args("D:/MPV/mpv.exe", ["a.png", "b.png"],
                                        "out.mkv", 24)
        text = " ".join(args)
        self.assertIn("ffv1", text)
        self.assertIn("yuv420p", text)
        self.assertIn("--fps=24", text)
        self.assertNotIn("fullscreen", text)


# ---------------------------------------------------------------------------
# scheduling loops (injected clocks)
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


def _warm_payload(i, fresh="default"):
    return {"epoch": 0,
            "vop": {"pixelformat": "yuv420p", "w": 1920, "h": 1080,
                    "dw": 1920, "dh": 1080},
            "osd": {"w": 2560, "h": 1440},
            "vo_passes": {"fresh": [_pass_node("p", 9)] if fresh == "default"
                          else fresh, "redraw": []},
            "counters": {}, "time_pos": 10.0 + i}


class TestScheduling(unittest.TestCase):
    def test_slot_targets_preregistered(self):
        targets = col.slot_targets(500.0)
        self.assertEqual(len(targets), 10)
        self.assertEqual(targets[0], 500.0)
        self.assertAlmostEqual(targets[9], 509.0)
        self.assertEqual(col.lib.SAMPLING_BUDGET["poll_period_s"], 1.0)

    def test_warmup_stabilizes_with_consecutive_rule(self):
        clock = _Clock()
        state = {"n": 0}

        def sample():
            state["n"] += 1
            return _warm_payload(state["n"])
        warm = col.run_warmup_loop(sample, clock=clock, sleep=clock.sleep)
        self.assertTrue(warm["stabilized"])
        self.assertGreaterEqual(warm["warmup_end_monotonic_s"],
                                lib.SAMPLING_BUDGET["warmup_min_s"])
        self.assertLessEqual(warm["warmup_end_monotonic_s"],
                             lib.SAMPLING_BUDGET["warmup_max_s"])
        self.assertIn("temp_unavailable", warm["disclosures"])

    def test_warmup_flapping_never_stabilizes_within_budget(self):
        clock = _Clock()
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] % 2 == 0:
                return _warm_payload(state["n"], fresh=[])
            return _warm_payload(state["n"])
        warm = col.run_warmup_loop(flaky, clock=clock, sleep=clock.sleep)
        self.assertFalse(warm["stabilized"])
        self.assertIsNone(warm["warmup_end_monotonic_s"])
        self.assertLessEqual(clock.t, lib.SAMPLING_BUDGET["warmup_max_s"])

    def test_warmup_never_fabricates_anchor_on_failed_polls(self):
        clock = _Clock()
        state = {"n": 0}

        def failing():
            state["n"] += 1
            raise col.SamplingPayloadError({"reason": "ipc dead"})
        warm = col.run_warmup_loop(failing, clock=clock, sleep=clock.sleep)
        self.assertFalse(warm["stabilized"])
        self.assertIsNone(warm["warmup_end_monotonic_s"])
        self.assertTrue(any("error" in p for p in warm["polls"]))
        self.assertGreaterEqual(len(warm["polls"]), 3,
                                "failed polls must be recorded, not hidden")

    def test_window_slots_record_actual_wall_as_is(self):
        clock = _Clock(2000.0)
        state = {"n": 0}

        def stalled_sample():
            state["n"] += 1
            if state["n"] == 5:
                clock.t += 2.0    # e.g. an nvidia-smi stall inside the slot
            return _warm_payload(100 + state["n"])
        slots = col.run_window_slots(stalled_sample, 2000.0, clock=clock,
                                     sleep=clock.sleep)
        self.assertEqual(len(slots), 10)
        late = slots[4]
        self.assertAlmostEqual(late["actual_s"] - late["target_s"], 2.0,
                               places=6,
                               msg="late poll must be recorded as-is")
        ontime = slots[0]
        self.assertAlmostEqual(ontime["actual_s"], ontime["target_s"],
                               places=6)

    def test_window_stops_honestly_at_deadline(self):
        clock = _Clock(3000.0)
        slots = col.run_window_slots(lambda: _warm_payload(1), 3000.0,
                                     clock=clock, sleep=clock.sleep,
                                     deadline=3002.5)
        self.assertLess(len(slots), 10,
                        "deadline must stop the window (truncation is "
                        "handled by the analyzer, never interpolated)")

    def test_stabilization_criteria_contract(self):
        a = _warm_payload(1)
        b = _warm_payload(2)
        checks = col.stabilization_criteria(a, b)
        self.assertTrue(checks["all_ok"])
        changed = _warm_payload(3)
        changed["vop"] = dict(changed["vop"], w=1280)
        self.assertFalse(col.stabilization_criteria(a, changed)["all_ok"])
        empty = _warm_payload(4, fresh=[])
        self.assertFalse(col.stabilization_criteria(a, empty)["all_ok"])
        # GPU temperature criterion: only evaluable when observed
        with_temp = col.stabilization_criteria(a, b, temp_drift_c=0.5)
        self.assertTrue(with_temp["gpu_temp"])
        too_hot = col.stabilization_criteria(a, b, temp_drift_c=5.0)
        self.assertFalse(too_hot["all_ok"])


# ---------------------------------------------------------------------------
# GPU pollution probe + decision
# ---------------------------------------------------------------------------


class TestGpuPollution(unittest.TestCase):
    def test_probe_parses_and_reports_foreign_mpv(self):
        root = _tmp(self)
        run = _fake_run({
            "nvidia-smi": (0, "1004, 1, 54, 1650\n", ""),
            "tasklist": (0, '"mpv.exe","4242","Console","1","1,000 K"\n',
                         ""),
        })
        report = col.probe_gpu_state({}, str(root), nvidia_smi="nvidia-smi",
                                     run=run)
        self.assertTrue(report["nvidia_smi_available"])
        self.assertEqual(report["gpu_samples"][0]["memory_used_mib"], 1004.0)
        self.assertEqual(report["other_mpv_processes"][0]["pid"], "4242")
        decision = col.pollution_decision(report)
        self.assertTrue(decision["blocked"])
        self.assertIn("foreign mpv.exe", decision["reasons"][0])

    def test_memory_gate_blocks(self):
        report = {"nvidia_smi_available": True,
                  "gpu_samples": [{"memory_used_mib": 1501.0,
                                   "util_pct": 1.0}],
                  "other_mpv_processes": []}
        decision = col.pollution_decision(report)
        self.assertTrue(decision["blocked"])
        self.assertIn("1501", decision["reasons"][0])
        ok = col.pollution_decision({"nvidia_smi_available": True,
                                     "gpu_samples": [{"memory_used_mib":
                                                      1004.0}],
                                     "other_mpv_processes": []})
        self.assertFalse(ok["blocked"])

    def test_missing_smi_is_unverifiable_not_zero(self):
        root = _tmp(self)
        # force the not-found branch even on hosts with a real nvidia-smi
        with unittest.mock.patch.object(col.shutil, "which", return_value=None):
            report = col.probe_gpu_state({}, str(root), nvidia_smi=None,
                                         run=_fake_run({}))
        self.assertTrue(report.get("unverifiable"))
        decision = col.pollution_decision(report)
        self.assertTrue(decision["blocked"])
        self.assertIn("unverifiable", decision["reasons"][0])
        self.assertIn("N/A", decision["note"])


# ---------------------------------------------------------------------------
# vo=image identity frame controls (real p3 decoder + real MAE math)
# ---------------------------------------------------------------------------


class TestIdentityDecode(unittest.TestCase):
    def _png(self, path, gray):
        rows = [bytes([gray]) * (16 * 3)] * 16
        data = lib.encode_png_rgb8(16, 16, rows)
        Path(path).write_bytes(data)

    def test_noncopy_and_duplicate_controls(self):
        root = _tmp(self)
        frames = root / "frames"
        frames.mkdir()
        # S0=flat100, M1=flat140 (true motion), S2=flat100, M3=flat140 —
        # M3 is a bitwise duplicate of M1: the uniqueness control must catch
        # it (the plan's duplicate control is scoped to M frames vs all
        # earlier output frames; S-frame repetition is legal, e.g. static
        # scenes)
        for name, gray in (("f0.png", 100), ("f1.png", 140),
                           ("f2.png", 100), ("f3.png", 140)):
            self._png(frames / name, gray)
        report = col.decode_identity_frames(sorted(frames.glob("*.png")))
        self.assertEqual(report["frames"], 4)
        self.assertTrue(all(m["noncopy_gt_2over255"]
                            for m in report["mae_noncopy"]),
                        "genuinely different M frames must clear the "
                        "preregistered 2/255 noncopy threshold vs BOTH "
                        "neighbouring S frames")
        self.assertFalse(report["all_frames_unique"],
                         "M3 == M1 bitwise; the duplicate must be reported")
        self.assertEqual(report["duplicate_frames"],
                         [{"frame": 3, "identical_to_frame": 1}])
        self.assertIn("even=S odd=M", report["parity_note"])

    def test_r3_5_blend_distribution_preserved_judgement_not_established(self):
        """R3-5: the 50% blend difference is really computed (M vs the
        pixelwise mean of both neighbouring S frames) and preserved as a
        distribution — but the judgement stays NOT_ESTABLISHED because the
        plan preregisters no blend threshold (inventing one is forbidden)."""
        root = _tmp(self)
        frames = root / "frames"
        frames.mkdir()
        for name, gray in (("f0.png", 100), ("f1.png", 140),
                           ("f2.png", 100), ("f3.png", 140)):
            self._png(frames / name, gray)
        report = col.decode_identity_frames(sorted(frames.glob("*.png")))
        blend = report["blend_check"]
        self.assertEqual(blend["judgement"], "NOT_ESTABLISHED")
        self.assertIn("NO numeric threshold", blend["judgement_note"])
        row = blend["per_frame"][0]   # M1 between S0(100) and S2(100)
        self.assertEqual(row["frame"], 1)
        self.assertEqual(row["mean"], 40.0,
                         "|140 - 0.5*(100+100)| must be exactly 40 on the "
                         "sampled grid")
        self.assertGreater(row["max"], 0)
        tail = blend["per_frame"][1]   # M3 has a single S neighbour
        self.assertIsNone(tail["mean"])
        self.assertIn("single S neighbour", tail["note"])
        # uniqueness stays the honest duplicate statement, never a blend
        # proof (the key name nonblend_all_unique was a lie and is gone)
        self.assertNotIn("nonblend_all_unique", report)

    def test_output_images_classified_by_magic_not_extension(self):
        root = _tmp(self) / "out"
        root.mkdir(parents=True)
        (root / "a.png").write_bytes(col.PNG_MAGIC + b"rest-of-png")
        (root / "b.png").write_bytes(col.JPEG_MAGIC + b"actually-jpeg")
        (root / "c.dat").write_bytes(b"\x00\x01\x02")
        rep = col.classify_output_images(root)
        self.assertEqual([p.name for p in rep["png"]], ["a.png"])
        self.assertEqual(rep["jpeg"], ["b.png"],
                         "a JPEG wearing a .png name must be caught by "
                         "magic bytes (the identity-run-001 silent glob)")
        self.assertEqual(rep["other"], ["c.dat"])
        self.assertIn("FORMAT MISMATCH", rep["note"])
        missing = col.classify_output_images(_tmp(self) / "nope")
        self.assertEqual(missing["png"], [])

    def test_neighbouring_m_frames_must_differ_from_both_s(self):
        root = _tmp(self)
        frames = root / "frames"
        frames.mkdir()
        self._png(frames / "f0.png", 100)
        self._png(frames / "f1.png", 101)   # M nearly identical to S0
        self._png(frames / "f2.png", 200)
        report = col.decode_identity_frames(sorted(frames.glob("*.png")))
        self.assertFalse(report["mae_noncopy"][0]["noncopy_gt_2over255"],
                         "an M frame that could be a near-copy (MAE 1/255 "
                         "< 2/255 vs S0) must FAIL the noncopy control")

    def test_no_frames_is_honest_error(self):
        root = _tmp(self)
        with self.assertRaises(col.SamplingPayloadError):
            col.decode_identity_frames([])


# ---------------------------------------------------------------------------
# identity log honesty
# ---------------------------------------------------------------------------


class TestIdentityLog(unittest.TestCase):
    def test_model_identity_not_established_without_log_proof(self):
        report = col.parse_identity_log(
            "vo: [image] ... \n[VapourSynth] core started\n"
            "vf_vapoursynth: script applied\n")
        self.assertEqual(report["model_identity"], "NOT_ESTABLISHED")
        self.assertTrue(report["vs_load_evidence"])
        self.assertIn("NOT_ESTABLISHED", report["model_identity_note"])

    def test_named_model_is_only_pass_when_logged(self):
        report = col.parse_identity_log(
            "rife: model rife-v4.25-lite_ensembleFalse loaded\n")
        self.assertEqual(report["model_identity"], "NAMED_IN_LOG")

    def test_effective_chain_states_from_real_log(self):
        engaged = col.parse_identity_log(
            "[vf] User filter list:\n"
            "[vf]   @rife: vapoursynth file=rife.vpy (engaged)\n")
        self.assertEqual(engaged["effective_vf_chain"]["state"],
                         "ENGAGED")
        empty = col.parse_identity_log(
            "[vf] User filter list:\n[vf]   (empty)\n")
        self.assertEqual(empty["effective_vf_chain"]["state"],
                         "NOT_IN_CHAIN")
        missing = col.parse_identity_log("nothing relevant here\n")
        self.assertEqual(missing["effective_vf_chain"]["state"],
                         "NOT_ESTABLISHED")

    def test_argv_echo_never_counts_as_chain_evidence(self):
        """R3-3: an engagement line that only exists as a command-line echo
        (or any argv string) with an (empty) effective chain must stay
        NOT_IN_CHAIN — this is exactly the identity-run-001 trap."""
        report = col.parse_identity_log(
            "[cplayer] Command line options: '--no-config' "
            "'--vf-add=@rife:vapoursynth=file=rife.vpy'\n"
            "[vf] User filter list:\n[vf]   (empty)\n")
        self.assertEqual(report["effective_vf_chain"]["state"],
                         "NOT_IN_CHAIN")

    def test_gpu_markers_ignore_build_feature_list(self):
        report = col.parse_identity_log(
            "List of enabled features: build-date vulkan vapoursynth zimg\n"
            "[cplayer] Command line options: '--gpu-api=vulkan'\n"
            "[   0.002][v][cplayer]    libavdevice     62.2.100\n"
            "[   0.002][v][cplayer] List of enabled features: cplugins "
            "cuda-hwaccel d3d-hwaccel d3d11 d3d9-hwaccel debug direct3d "
            "dos-paths dvdnav dxgi-debug-d3d11 egl-angle-win32 ffmpeg "
            "ffnvcodec gl gl-dxinterop gl-dxinterop-d3d9 gl-win32 glob "
            "glob-win32 gpl iconv javascript jpeg lcms2 libarchive libass "
            "libavdevice libbluray libplacebo luajit openal rubberband\n"
            "[vo/gpu/vulkan] Created device 0 (adapter 0)\n")
        self.assertEqual(len(report["gpu_init_evidence"]), 1)
        self.assertIn("Created device", report["gpu_init_evidence"][0])

    def test_gpu_started_states(self):
        missing = {"present": False, "bytes": 0}
        empty = {"present": True, "bytes": 0}
        real = {"present": True, "bytes": 100}
        clean = {"gpu_init_evidence": []}
        gpu = {"gpu_init_evidence": ["[vo/gpu] created device"]}
        self.assertEqual(
            col.gpu_started_from_log(missing, clean)[0], "NOT_ESTABLISHED")
        self.assertEqual(
            col.gpu_started_from_log(empty, clean)[0], "NOT_ESTABLISHED")
        self.assertIs(col.gpu_started_from_log(real, clean)[0], False)
        self.assertIs(col.gpu_started_from_log(real, gpu)[0], True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_default_help(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main([])
        self.assertEqual(rc, 0)
        self.assertIn("preflight", out.getvalue())
        self.assertIn("prepare-media", out.getvalue())

    def test_production_refused_at_argv(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main(["--mode", "production"])
        self.assertEqual(rc, 2)
        self.assertIn("PRODUCTION_REFUSED", out.getvalue())
        self.assertIn("no pass-json writing option", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main(["--mode", "preflight", "--unlock-production"])
        self.assertEqual(rc, 2)
        self.assertIn("PRODUCTION_REFUSED", out.getvalue())
        # a hypothetical pass-json flag does not exist: argparse refuses the
        # unknown option with rc 2 (the CLI has no such option at all)
        out = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(out):
                col.main(["--mode", "capture", "--write-pass", "pass.json"])
        self.assertEqual(ctx.exception.code, 2)

    def test_preflight_mode_real_repo(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main(["--mode", "preflight"])
        self.assertEqual(rc, 0)
        report = json.loads(out.getvalue())
        self.assertTrue(report["ok"])
        self.assertTrue(report["production_locked"])
        self.assertTrue(report["work_permit"]["ok"])
        self.assertEqual(report["b1_candidate"]["sha256"],
                         col.B1_CANDIDATE_SHA256)

    def test_prepare_media_requires_evidence_dir(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main(["--mode", "prepare-media"])
        self.assertEqual(rc, 2)

    def test_config_smoke_requires_smoke_dir(self):
        out = io.StringIO()
        _no_spawn(self)
        with redirect_stdout(out):
            rc = col.main(["--mode", "config-smoke"])
        self.assertEqual(rc, col.RC_REFUSED)
        self.assertIn("CONFIG_SMOKE_NEEDS_SMOKE_DIR", out.getvalue())

    def test_pilot_without_media_manifest_refused_before_spawn(self):
        root = _tmp(self)
        sandbox = root / "sbx"
        _no_spawn(self)
        with self.assertRaises(lib.MissingInputError) as ctx:
            col.run_timed_trial(sandbox, "G1_equalrect_main", "baselineHQ",
                                "off", 1, run_kind="pilot")
        self.assertIn("prepare-media first", str(ctx.exception))


# ---------------------------------------------------------------------------
# F2: sandbox/staging location hard gate (TEMP-only; protected-tree refusal
# before any mkdir/copy/spawn)
# ---------------------------------------------------------------------------


class TestSandboxTempSafety(unittest.TestCase):
    def test_sandbox_under_protected_tree_refused_before_any_write(self):
        root = _tmp(self)
        _no_spawn(self)
        protected_target = Path("D:/MPV") / "sbx-new"      # never created
        with self.assertRaises(col.SpawnRefused) as ctx:
            col.create_sandbox(protected_target)
        self.assertFalse(protected_target.exists())
        self.assertIn("protected", str(ctx.exception))
        # the repo/project tree is protected too (new subpath refused)
        repo_target = (lib.workspace_root() / "docs" / "p4col-sbx-refused")
        self.assertFalse(repo_target.exists())
        with self.assertRaises(col.SpawnRefused):
            col.create_sandbox(repo_target)
        self.assertFalse(repo_target.exists())

    def test_active_mpv_config_tree_is_protected(self):
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            self.skipTest("APPDATA not set")
        target = Path(appdata) / "mpv" / "sbx-refused"
        _no_spawn(self)
        with self.assertRaises(col.SpawnRefused) as ctx:
            col.assert_sandbox_temp_safe(target)
        self.assertFalse(target.exists())
        self.assertIn("protected", str(ctx.exception))

    def test_trusted_parent_itself_and_nonchildren_refused(self):
        root = _tmp(self)
        base = root / "p4-001"
        _no_spawn(self)
        for bad in (base, root):     # the parent itself / outside the parent
            with self.assertRaises(col.SpawnRefused):
                col.create_sandbox(bad, temp_base=base)
        self.assertFalse(base.exists())   # nothing was created anywhere

    def test_dotdot_alias_refused(self):
        root = _tmp(self)
        base = root / "p4-001"
        _no_spawn(self)
        with self.assertRaises(col.SpawnRefused):
            col.create_sandbox(base / ".." / "p4-001" / "sbx",
                               temp_base=base)
        self.assertFalse((root / "sbx").exists())

    def test_poisoned_env_temp_refused(self):
        root = _tmp(self)
        _no_spawn(self)
        # a caller-poisoned TEMP parent pointing into a protected tree is
        # refused — a non-existing new root under it is NOT safe
        with self.assertRaises(col.SpawnRefused) as ctx:
            col.assert_sandbox_temp_safe(root / "x",
                                         temp_base="D:/MPV/p4-001")
        self.assertIn("poisoned", str(ctx.exception))

    def test_reparse_component_in_sandbox_path_refused(self):
        root = _tmp(self)
        base = root / "p4-001"
        elsewhere = root / "elsewhere"
        elsewhere.mkdir(parents=True)
        made = False
        link = base / "lnk"
        if sys.platform == "win32":
            try:
                import _winapi
                base.mkdir(parents=True)
                _winapi.CreateJunction(str(elsewhere), str(link))
                made = link.exists()
            except (OSError, ImportError):
                made = False
        if not made:
            self.skipTest("junction creation unavailable on this host")
        _no_spawn(self)
        with self.assertRaises(col.SpawnRefused):
            col.create_sandbox(link / "child", temp_base=base)
        self.assertFalse((link / "child").exists())
        self.assertTrue(elsewhere.is_dir())   # never deletes others' dirs

    def test_unique_child_under_trusted_parent_is_allowed(self):
        root = _tmp(self)
        layout = col.create_sandbox(root / "p4-001" / "sbx-a",
                                    temp_base=root)
        self.assertTrue(layout["runs"].is_dir())
        with self.assertRaises(col.SpawnRefused):   # create-only
            col.create_sandbox(root / "p4-001" / "sbx-a", temp_base=root)

    def test_run_entry_refuses_protected_sandbox_before_spawn(self):
        protected_sandbox = lib.workspace_root() / "docs" / "p4col-sbx-r"
        _no_spawn(self)
        with self.assertRaises(col.SpawnRefused) as ctx:
            col.run_identity_probe(protected_sandbox)
        self.assertFalse(protected_sandbox.exists())
        self.assertIn("protected", str(ctx.exception))

    def test_prepare_media_staging_location_checked_before_writes(self):
        root = _tmp(self)
        _no_spawn(self)
        bad = lib.workspace_root() / "docs" / "p4col-media-refused"
        with self.assertRaises(col.SpawnRefused) as ctx:
            col.prepare_media("motion24", bad, root / "ev")
        self.assertFalse(bad.exists())
        self.assertIn("protected", str(ctx.exception))


# ---------------------------------------------------------------------------
# F1/F3/F4: identity-probe end-to-end (mock spawn + fake pinned runtime;
# no real mpv/GPU/VS; everything stays inside TEMP)
# ---------------------------------------------------------------------------


class _FakeRuntimeMixin:
    """Shared: a tiny fake pinned runtime + TEMP sandbox locations, so the
    end-to-end entries exercise the real code without touching D:/MPV."""
    def _fake_runtime(self):
        root = _tmp(self)
        vs = root / "vs-src"
        vs_files = {}
        for rel, data in ((col.VSSCRIPT_REL, b"vsscript-fake"),
                          ("Lib/site-packages/vapoursynth/"
                           "libvapoursynth.dll", b"vs-core-fake"),
                          ("Lib/site-packages/vapoursynth/"
                           "vapoursynth.pyd", b"vs-pyd-fake"),
                          ("python313.dll", b"py313-fake")):
            fs = vs / rel
            fs.parent.mkdir(parents=True, exist_ok=True)
            fs.write_bytes(data)
            vs_files[rel] = (lib.sha256_bytes(data), len(data))
        rife = root / "rife-src"
        rife_files = {}
        for rel, data in ((col.RIFE_DLL_REL, b"rife-dll-fake"),
                          (col.RIFE_MODEL_DIR_REL + "/flownet.bin",
                           b"flownet-fake"),
                          (col.RIFE_MODEL_DIR_REL + "/flownet.param",
                           b"param-fake")):
            fs = rife / rel
            fs.parent.mkdir(parents=True, exist_ok=True)
            fs.write_bytes(data)
            rife_files[rel] = (lib.sha256_bytes(data), len(data))
        mpv = root / "mpv.exe"
        mpv.write_bytes(b"mpv-fake")
        vpy = rife / "rife.vpy"
        vpy.write_bytes(_VPY_BODY.format(
            dll="D:/MPV/rife/librife_windows_x86-64.dll").encode("utf-8"))
        for target, value in (
                ("SURVEY_RUNTIME_PINS", vs_files),
                ("SURVEY_RIFE_PINS", rife_files),
                ("MPV_EXE_SHA256", lib.sha256_bytes(b"mpv-fake")),
                ("MPV_EXE_DEFAULT", mpv),
                ("ACTIVE_VPY_SHA256",
                 lib.sha256_bytes(vpy.read_bytes())),
                ("VS_TREE_DEFAULT", vs),
                ("RIFE_DIR_DEFAULT", rife)):
            patcher = unittest.mock.patch.object(col, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = unittest.mock.patch.object(col, "resolve_active_vpy",
                                             lambda: vpy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return {"vs": vs, "rife": rife, "mpv": mpv, "vpy": vpy}

    def _new_sandbox_path(self, prefix):
        base = Path(tempfile.gettempdir()) / "p4-001"
        sbx = base / ("%s-%x-%d"
                      % (prefix, time.time_ns(), len(self._sandboxes)))
        self._sandboxes.append(sbx)
        self.addCleanup(shutil.rmtree, str(sbx), True)
        return sbx

    def _python_spawn(self, recorder, code):
        def spawn(exe_args, **kwargs):
            child = subprocess.Popen([sys.executable, "-c", code], **kwargs)
            recorder.append(child)
            return child
        return spawn

    def _manifest(self, result):
        return json.loads((Path(result["trial_dir"]) / "manifest.json")
                          .read_text("utf-8"))

    def _tiny_pngs(self, d, n=2):
        """A few REAL tiny PNGs the fake mpv child copies as probe output."""
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        rows = [bytes([100]) * (16 * 3)] * 16
        data = lib.encode_png_rgb8(16, 16, rows)
        for i in range(n):
            (d / ("src%02d.png" % i)).write_bytes(data)
        return d

    def _fake_mpv_spawn(self, recorder, kind, scenario="", frames_dir=None):
        """A REAL local python child emulating the mpv surface the collector
        binds to (log file at --log-file, frame copies into
        --vo-image-outdir, script-opts config read for the smoke). The exact
        argv the SOURCE built is injected via env, so the child reacts to
        the real launch path — no re-implemented argv."""
        real_popen = subprocess.Popen

        def spawn(exe_args, **kwargs):
            env = dict(kwargs.get("env") or {})
            env["P4_FAKE_ARGV"] = json.dumps([str(a) for a in exe_args])
            env["P4_FAKE_KIND"] = kind
            env["P4_FAKE_SCENARIO"] = scenario
            if frames_dir is not None:
                env["P4_FAKE_FRAMES_DIR"] = str(frames_dir)
            kwargs = dict(kwargs, env=env)
            child = real_popen([sys.executable, "-c", _FAKE_MPV_CHILD],
                               **kwargs)
            recorder.append(child)
            return child
        return spawn


class TestIdentityProbeEndToEnd(_FakeRuntimeMixin, unittest.TestCase):
    def setUp(self):
        self._sandboxes = []

    def _sandbox(self):
        return self._new_sandbox_path("sbx-p4col-e2e")

    def test_exit_status_manifest_evidence_no_orphans(self):
        self._fake_runtime()
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._python_spawn(children, "import sys; sys.exit(0)"))
        self.assertEqual(result["status"], "EXITED")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(children and children[0].poll() is not None,
                        "the own child must be reaped, never orphaned")
        doc = self._manifest(result)
        self.assertTrue(doc["handles_closed_before_manifest"])
        self.assertEqual(doc["result_status"], "EXITED")
        self.assertEqual(doc["cleanup_errors"], [])
        self.assertTrue(all(w["clean"]
                            for w in result["zero_write_witness"]))
        # a mock child proves nothing: model identity NOT_ESTABLISHED must
        # never yield an accepted rc (F4), even with a clean EXITED run
        self.assertEqual(result["verdict"]["model_identity"],
                         "NOT_ESTABLISHED")
        self.assertEqual(col.identity_probe_rc(result),
                         col.RC_NOT_ESTABLISHED)

    def test_timeout_kills_own_pid_and_preserves_timeout_evidence(self):
        self._fake_runtime()
        children = []
        with unittest.mock.patch.object(col, "IDENTITY_PROBE_WALL_S", 2.0):
            result = col.run_identity_probe(
                self._sandbox(),
                spawn=self._python_spawn(
                    children, "import time; time.sleep(60)"))
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIsNotNone(children[0].poll(),
                             "deadline expiry must kill the OWN pid")
        doc = self._manifest(result)
        self.assertEqual(doc["result_status"], "TIMEOUT")
        self.assertEqual(doc["cleanup_errors"], [])
        self.assertEqual(col.identity_probe_rc(result),
                         col.RC_NOT_ESTABLISHED)
        # R3-4: even on timeout the proof stage ran only after the own
        # process was stopped and the handles were closed, and gpu_started
        # is honest UNKNOWN (the sleeper wrote no log to analyse)
        self.assertTrue(result["proof_stage_after_handles_closed"])
        self.assertEqual(result["gpu_started"], "NOT_ESTABLISHED")
        self.assertEqual(doc["gpu_started"], "NOT_ESTABLISHED")

    def test_start_failure_closes_handles_and_records_primary(self):
        self._fake_runtime()
        children = []

        def boom(exe_args, **kwargs):
            raise RuntimeError("spawn exploded")

        with self.assertRaises(RuntimeError):
            col.run_identity_probe(
                self._sandbox(), spawn=boom)
        trial = self._sandboxes[-1] / "runs" / "identity"
        doc = json.loads((trial / "manifest.json").read_text("utf-8"))
        self.assertEqual(doc["result_status"], "ERROR")
        self.assertEqual(doc["primary_exception"]["type"], "RuntimeError")
        self.assertEqual(doc["cleanup_errors"], [])
        # the manifest could only be written because every handle was closed
        self.assertTrue(doc["handles_closed_before_manifest"])
        self.assertEqual(children, [])

    def test_proof_stage_exception_still_cleans_and_preserves(self):
        self._fake_runtime()
        children = []
        with unittest.mock.patch.object(
                col, "parse_identity_log",
                unittest.mock.Mock(side_effect=RuntimeError("proof crime"))):
            with self.assertRaises(RuntimeError):
                col.run_identity_probe(
                    self._sandbox(),
                    spawn=self._python_spawn(children,
                                             "import sys; sys.exit(0)"))
        self.assertIsNotNone(children[0].poll(), "no orphan after a "
                             "proof-stage exception")
        trial = self._sandboxes[-1] / "runs" / "identity"
        doc = json.loads((trial / "manifest.json").read_text("utf-8"))
        self.assertEqual(doc["primary_exception"]["type"], "RuntimeError")
        self.assertIn("proof crime", doc["primary_exception"]["detail"])
        self.assertEqual(doc["cleanup_errors"], [])

    def test_zero_write_violation_is_hard_refused_with_evidence(self):
        rt = self._fake_runtime()
        children = []
        orig = col.tree_inventory
        seen = {"n": 0}

        def spy(tree):
            if Path(tree) == rt["vs"]:
                seen["n"] += 1
                if seen["n"] == 2:   # the after-witness pass
                    (rt["vs"] / "planted.bin").write_bytes(b"P")
            return orig(tree)

        with unittest.mock.patch.object(col, "tree_inventory", spy):
            result = col.run_identity_probe(
                self._sandbox(),
                spawn=self._python_spawn(children,
                                         "import sys; sys.exit(0)"))
        self.assertIsNotNone(result.get("zero_write_violation"))
        self.assertEqual(result["verdict"]["initialization"], "BLOCKED_ENV")
        self.assertEqual(col.identity_probe_rc(result), col.RC_REFUSED)
        doc = self._manifest(result)
        self.assertIn("zero_write_violation", doc)
        self.assertIsNotNone(children[0].poll())

    def test_trial_dir_outside_sandbox_refused_inside_honoured(self):
        self._fake_runtime()
        children = []
        outside = _tmp(self) / "outside-trial"
        with self.assertRaises(col.SpawnRefused) as ctx:
            col.run_identity_probe(
                self._sandbox(), trial_dir=outside,
                spawn=self._python_spawn(children,
                                         "import sys; sys.exit(0)"))
        self.assertFalse(outside.exists())
        self.assertIn("INSIDE", str(ctx.exception))
        # inside the sandbox runs dir the trial dir IS honoured, create-only
        result = col.run_identity_probe(
            self._sandbox(), trial_dir=self._sandboxes[-1] / "runs" / "custom",
            spawn=self._python_spawn(children, "import sys; sys.exit(0)"))
        self.assertEqual(Path(result["trial_dir"]).name, "custom")
        self.assertTrue((Path(result["trial_dir"]) /
                         "manifest.json").is_file())

    def test_cli_identity_probe_end_to_end_rc_not_established(self):
        self._fake_runtime()
        children = []
        real_popen = subprocess.Popen

        def fake_popen(exe_args, **kwargs):
            child = real_popen([sys.executable, "-c",
                                "import sys; sys.exit(0)"], **kwargs)
            children.append(child)
            return child

        sbx = self._sandbox()
        out = io.StringIO()
        with unittest.mock.patch.object(col.subprocess, "Popen", fake_popen):
            with redirect_stdout(out):
                rc = col.main(["--mode", "identity-probe",
                               "--sandbox-root", str(sbx)])
        self.assertEqual(rc, col.RC_NOT_ESTABLISHED)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["status"], "EXITED")
        self.assertEqual(doc["model_identity"], "NOT_ESTABLISHED")
        self.assertIsNone(doc["zero_write_violation"])
        self.assertTrue((Path(sbx) / "runs" / "identity" /
                         "manifest.json").is_file())
        self.assertIsNotNone(children[0].poll())

    # ---- B2-r3 R3-1: the FULL CLI default path (no --sandbox-root) ----

    def test_r3_1_cli_default_sandbox_full_path_without_sandbox_root(self):
        """Exactly the invocation that died deterministically in
        identity-run-001 attempt 1 ('sandbox root already exists') must now
        reach the spawn on the full default CLI path (auto name chosen
        NON-existing under the trusted parent, created by create_sandbox
        only). Runs on the fake pinned runtime; the 'mpv' is a local python
        child — no real mpv/GPU/VS."""
        self._fake_runtime()
        children = []
        base = Path(tempfile.gettempdir()) / "p4-001"
        out = io.StringIO()
        with unittest.mock.patch.object(
                col.subprocess, "Popen",
                self._fake_mpv_spawn(children, "probe", scenario="no_log")):
            with redirect_stdout(out):
                rc = col.main(["--mode", "identity-probe", "--fps", "24"])
        self.assertEqual(rc, col.RC_NOT_ESTABLISHED)
        doc = json.loads(out.getvalue())
        trial = Path(doc["trial_dir"])
        sbx = trial.parents[1]
        self.assertEqual(sbx.parent, base)
        self.assertTrue(sbx.name.startswith("p4-001-id-"))
        self.assertTrue(sbx.is_dir(),
                        "create_sandbox must have created the auto root")
        self.addCleanup(shutil.rmtree, str(sbx), True)
        self.assertIsNotNone(children[0].poll())

    # ---- B2-r3 R3-3: verdict binds to the unique REAL log + chain ----

    def test_r3_3_engaged_chain_evidenced_model_unnamed_rc1(self):
        self._fake_runtime()
        frames = self._tiny_pngs(_tmp(self))
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="engaged",
                                       frames_dir=frames))
        self.assertEqual(result["status"], "EXITED")
        self.assertEqual(result["exit_code"], 0)
        log = result["log"]
        self.assertTrue(log["present"] and log["bytes"] > 0)
        self.assertTrue(log["sha256"])
        self.assertEqual(Path(log["path"]).parent,
                         Path(result["trial_dir"]),
                         "the argv --log-file and the analysed log must be "
                         "the SAME unique path inside the trial dir")
        self.assertEqual(result["launch"]["no_config_flag"], False)
        self.assertNotIn("--no-config", result["argv"])
        self.assertIn("p4-scripts", result["launch"]["auto_script_scan"])
        self.assertEqual(
            result["log_analysis"]["effective_vf_chain"]["state"],
            "ENGAGED")
        verdict = result["verdict"]
        self.assertEqual(verdict["initialization"], "EVIDENCED")
        self.assertTrue(verdict["initialization_gates"][
            "effective_vf_engaged"])
        self.assertEqual(verdict["model_identity"], "NOT_ESTABLISHED")
        self.assertEqual(verdict["frame_rate_order"]["status"],
                         "NOT_ESTABLISHED")
        self.assertEqual(col.identity_probe_rc(result),
                         col.RC_NOT_ESTABLISHED,
                         "EVIDENCED initialisation with an unnamed model is "
                         "still rc 1 (no RIFE-01 pass is claimable)")
        doc = self._manifest(result)
        self.assertIs(doc["gpu_started"], False)
        self.assertIn("gpu_started_basis", doc)

    def test_r3_3_model_named_reaches_rc0_contract(self):
        """The only shape that can produce rc 0 (mock plumbing contract — a
        mock child proves the CONTRACT, never real RIFE identity)."""
        self._fake_runtime()
        frames = self._tiny_pngs(_tmp(self))
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="model_named",
                                       frames_dir=frames))
        self.assertEqual(result["verdict"]["initialization"], "EVIDENCED")
        self.assertEqual(result["verdict"]["model_identity"],
                         "NAMED_IN_LOG")
        self.assertEqual(col.identity_probe_rc(result), col.RC_OK)

    def test_r3_3_argv_only_vf_string_never_evidenced(self):
        self._fake_runtime()
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="argv_only"))
        self.assertEqual(
            result["log_analysis"]["effective_vf_chain"]["state"],
            "NOT_IN_CHAIN")
        self.assertEqual(result["verdict"]["initialization"],
                         "NOT_ESTABLISHED")
        self.assertEqual(col.identity_probe_rc(result),
                         col.RC_NOT_ESTABLISHED)

    def test_r3_3_passthrough_12_source_frames_never_evidenced(self):
        self._fake_runtime()
        frames = self._tiny_pngs(_tmp(self))
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="passthrough",
                                       frames_dir=frames))
        self.assertEqual(result["verdict"]["initialization"],
                         "NOT_ESTABLISHED",
                         "12 un-interpolated source frames (empty chain) "
                         "are a passthrough, never an initialization")
        self.assertEqual(result["frame_report"]["frames"], 12)
        self.assertEqual(result["frame_report"]["expected_output_frames"],
                         24)
        self.assertNotEqual(result["verdict"]["frame_evidence"],
                            "EVIDENCED")
        self.assertEqual(col.identity_probe_rc(result),
                         col.RC_NOT_ESTABLISHED)

    def test_r3_3_rc0_with_empty_log_is_never_evidenced(self):
        """The identity-run-001 REWORK-3 trap: rc 0 + an empty/never-written
        log must NOT read as initialization (the old code even looked at a
        log path mpv never wrote)."""
        self._fake_runtime()
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="empty_log"))
        self.assertEqual(result["status"], "EXITED")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["log"]["present"])
        self.assertEqual(result["log"]["bytes"], 0)
        self.assertEqual(result["verdict"]["initialization"],
                         "NOT_ESTABLISHED")
        self.assertFalse(result["verdict"]["initialization_gates"]
                         ["real_log_present"])
        self.assertEqual(result["gpu_started"], "NOT_ESTABLISHED")
        self.assertEqual(col.identity_probe_rc(result),
                         col.RC_NOT_ESTABLISHED)

    def test_r3_4_missing_log_gpu_state_unknown_not_false(self):
        self._fake_runtime()
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="no_log"))
        self.assertEqual(result["gpu_started"], "NOT_ESTABLISHED")
        doc = self._manifest(result)
        self.assertEqual(doc["gpu_started"], "NOT_ESTABLISHED",
                         "without a real log the GPU state is UNKNOWN — "
                         "never a hardcoded false")

    def test_r3_3_frames_classified_by_magic_jpeg_stated(self):
        self._fake_runtime()
        frames = self._tiny_pngs(_tmp(self))
        children = []
        result = col.run_identity_probe(
            self._sandbox(),
            spawn=self._fake_mpv_spawn(children, "probe",
                                       scenario="jpeg_mismatch",
                                       frames_dir=frames))
        self.assertEqual(result["output_images"]["jpeg"],
                         ["%08d.png" % i for i in range(1, 25)],
                         "JPEG bytes wearing .png names must be caught by "
                         "magic, not extension (the identity-run-001 "
                         "silent *.png glob)")
        self.assertIn("FORMAT MISMATCH", result["output_images"]["note"])
        self.assertEqual(result["verdict"]["frame_evidence"],
                         "FORMAT_MISMATCH")


# ---------------------------------------------------------------------------
# R3-1: auto sandbox generation (non-existing unpredictable name; the
# create-only entry is the ONLY creator)
# ---------------------------------------------------------------------------


class TestSandboxGeneration(unittest.TestCase):
    def test_generated_root_does_not_exist_and_is_unique(self):
        base = Path(tempfile.gettempdir()) / "p4-001"
        seen = set()
        for _ in range(3):
            p = col.new_sandbox_root("p4-001-t3st-")
            self.assertFalse(p.exists(),
                             "R3-1: the auto root must NOT be pre-created "
                             "(tempfile.mkdtemp did, and create_sandbox "
                             "then refused it — identity-run-001 attempt1)")
            self.assertFalse(p.is_symlink())
            self.assertEqual(p.parent, base)
            self.assertNotIn(p, seen)
            seen.add(p)

    def test_create_sandbox_accepts_the_generated_name(self):
        p = col.new_sandbox_root("p4-001-t3st-")
        layout = col.create_sandbox(p)
        self.addCleanup(shutil.rmtree, str(p), True)
        self.assertTrue(layout["root"].is_dir())


# ---------------------------------------------------------------------------
# R3-2: real config-load smoke (fake-mpv python child here; the REAL mpv
# vo=null smoke runs once as create-only author evidence, never in tests)
# ---------------------------------------------------------------------------


class TestConfigSmoke(unittest.TestCase):
    def _fake_mpv(self):
        root = _tmp(self)
        mpv = root / "mpv.exe"
        mpv.write_bytes(b"mpv-fake")
        for target, value in (
                ("MPV_EXE_SHA256", lib.sha256_bytes(b"mpv-fake")),
                ("MPV_EXE_DEFAULT", mpv)):
            patcher = unittest.mock.patch.object(col, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return mpv

    def _spawn(self, children, scenario=""):
        real_popen = subprocess.Popen

        def spawn(exe_args, **kwargs):
            env = dict(kwargs.get("env") or {})
            env["P4_FAKE_ARGV"] = json.dumps([str(a) for a in exe_args])
            env["P4_FAKE_KIND"] = "smoke"
            env["P4_FAKE_SCENARIO"] = scenario
            kwargs = dict(kwargs, env=env)
            child = real_popen([sys.executable, "-c", _FAKE_MPV_CHILD],
                               **kwargs)
            children.append(child)
            return child
        return spawn

    def test_pass_proves_config_load_and_no_config_negative(self):
        mpv = self._fake_mpv()
        smoke_dir = _tmp(self) / "smoke"
        children = []
        doc = col.run_config_smoke(
            smoke_dir, mpv_exe=mpv,
            spawn=self._spawn(children, scenario=""))
        self.assertEqual(doc["status"], "PASS")
        self.assertTrue(doc["config_load_proven"])
        self.assertTrue(doc["negative_no_config_proven"])
        self.assertIs(doc["gpu_started"], False)
        self.assertIs(doc["live_configuration_written"], False)
        load, neg = doc["attempts"]
        # the source's actual argv shape: config-dir + explicit sentinel
        # script from the never-scanned p4-scripts dir + vo=null, never
        # --no-config, never --load-scripts=no (real mpv gates explicit
        # --script entries with it too — author smoke evidence)
        argv = load["argv"]
        self.assertNotIn("--no-config", argv)
        self.assertNotIn("--load-scripts=no", argv)
        self.assertIn("--vo=null", argv)
        self.assertTrue(any(a.startswith("--script=") and
                            "p4-scripts" in a and
                            a.endswith(col.CONFIG_SMOKE_SENTINEL_NAME)
                            for a in argv))
        self.assertTrue(any(a.startswith("--config-dir=") for a in argv))
        self.assertEqual(load["sentinel_report"]["a"], "1701")
        self.assertEqual(load["sentinel_report"]["b"], "74656")
        self.assertTrue(load["config_loaded"])
        self.assertIn("--no-config", neg["argv"],
                      "the negative control must reuse the OLD failing "
                      "argv shape")
        self.assertEqual(neg["sentinel_report"]["a"], "nil",
                         "with --no-config the conf values cannot load — "
                         "the sentinel writes tostring(nil) = 'nil'")
        self.assertFalse(neg["config_loaded"])
        # per-attempt create-only manifests + non-empty real logs
        for name in ("config-load", "negative-no-config"):
            self.assertTrue((smoke_dir / name / "manifest.json").is_file())
            self.assertGreater((smoke_dir / name / "mpv.log")
                               .stat().st_size, 0)
        report = Path(doc["report_path"])
        self.assertTrue(report.is_file())
        self.assertEqual(doc["report_sha256"],
                         lib.sha256_bytes(report.read_bytes()))
        self.assertEqual(col.config_smoke_rc(doc), col.RC_OK)

    def test_conf_present_but_not_loaded_is_failed_rc1(self):
        mpv = self._fake_mpv()
        smoke_dir = _tmp(self) / "smoke"
        doc = col.run_config_smoke(
            smoke_dir, mpv_exe=mpv,
            spawn=self._spawn([], scenario="conf_not_loaded"))
        self.assertEqual(doc["status"], "FAILED")
        self.assertFalse(doc["config_load_proven"])
        self.assertEqual(col.config_smoke_rc(doc), col.RC_NOT_ESTABLISHED)

    def test_timeout_kills_own_pid_and_fails(self):
        mpv = self._fake_mpv()
        smoke_dir = _tmp(self) / "smoke"
        children = []
        real_popen = subprocess.Popen

        def spawn(exe_args, **kwargs):
            child = real_popen([sys.executable, "-c",
                                "import time; time.sleep(60)"], **kwargs)
            children.append(child)
            return child

        with unittest.mock.patch.object(col, "CONFIG_SMOKE_WALL_S", 2.0):
            doc = col.run_config_smoke(smoke_dir, mpv_exe=mpv, spawn=spawn)
        self.assertEqual(doc["status"], "FAILED")
        self.assertEqual(doc["attempts"][0]["status"], "TIMEOUT")
        self.assertIsNotNone(children[0].poll(),
                             "the 10s/own-PID cap must stop the own child")
        self.assertEqual(col.config_smoke_rc(doc), col.RC_NOT_ESTABLISHED)


# ---------------------------------------------------------------------------
# L1: real blocking-IPC wall-clock deadlines (local python children only;
# no mpv, no mocked clocks for the timeout proof)
# ---------------------------------------------------------------------------


class _StdioPipe:
    """File-like duplex over a REAL local python child's stdin/stdout:
    write() feeds the child, readline() blocks on the OS pipe until the
    child answers or dies — a genuine blocking pipe, not a mocked clock."""

    def __init__(self, child):
        self.child = child

    def write(self, data):
        self.child.stdin.write(data)
        self.child.stdin.flush()

    def readline(self):
        return self.child.stdout.readline()

    def flush(self):
        pass

    def close(self):
        for handle in (self.child.stdin, self.child.stdout):
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass


_SILENT_CHILD = "import sys, time\nsys.stdin.readline()\ntime.sleep(60)\n"

_FAKE_MPV_CHILD = r"""
import json, os, shutil, sys
args = json.loads(os.environ.get('P4_FAKE_ARGV', '[]'))
def opt(name):
    for a in args:
        if a.startswith(name + '='):
            return a[len(name) + 1:]
    return None
kind = os.environ.get('P4_FAKE_KIND', 'probe')
scenario = os.environ.get('P4_FAKE_SCENARIO', '')
log = opt('--log-file')
lines = ['[   0.001][v][cplayer] Command line options: '
         + ' '.join(chr(39) + a + chr(39) for a in args[1:])]
if kind == 'probe':
    if scenario in ('engaged', 'jpeg_mismatch'):
        lines += ['[   0.010][v][vf] User filter list:',
                  '[   0.010][v][vf]   @rife: vapoursynth file=rife.vpy',
                  '[   0.011][v][vf_vapoursynth] script applied']
    elif scenario == 'model_named':
        lines += ['[   0.010][v][vf] User filter list:',
                  '[   0.010][v][vf]   @rife: vapoursynth file=rife.vpy',
                  '[   0.012][i][rife] model rife-v4.25-lite_ensembleFalse']
    elif scenario in ('argv_only', 'passthrough'):
        if scenario == 'argv_only':
            lines.append('[   0.002][v][cplayer] config echo: '
                         'vf-add=@rife:vapoursynth=file=rife.vpy')
        lines += ['[   0.010][v][vf] User filter list:',
                  '[   0.010][v][vf]   (empty)']
    if log and scenario != 'no_log':
        payload = b'' if scenario == 'empty_log' else (
            (chr(10).join(lines) + chr(10)).encode('utf-8'))
        with open(log, 'wb') as fh:
            fh.write(payload)
    counts = {'engaged': 24, 'model_named': 24, 'passthrough': 12,
              'jpeg_mismatch': 24}
    n = counts.get(scenario, 0)
    src = os.environ.get('P4_FAKE_FRAMES_DIR')
    outdir = opt('--vo-image-outdir')
    if src and n and outdir:
        names = sorted(os.listdir(src))
        os.makedirs(outdir, exist_ok=True)
        for i in range(n):
            shutil.copyfile(os.path.join(src, names[i % len(names)]),
                            os.path.join(outdir, '%08d.png' % (i + 1)))
        if scenario == 'jpeg_mismatch':
            for i in range(1, n + 1):
                p = os.path.join(outdir, '%08d.png' % i)
                d = open(p, 'rb').read()
                open(p, 'wb').write(b'\xff\xd8\xff' + d)
    sys.exit(0)
if kind == 'smoke':
    conf_dir = opt('--config-dir')
    script = opt('--script')
    a = b = None
    if '--no-config' not in args and conf_dir and scenario != 'conf_not_loaded':
        try:
            with open(os.path.join(conf_dir, 'mpv.conf'), 'rb') as fh:
                text = fh.read().decode('utf-8')
        except OSError:
            text = ''
        for line in text.splitlines():
            if line.startswith('script-opts='):
                for kv in line[len('script-opts='):].split(','):
                    k, _, v = kv.partition('=')
                    if k == 'p4smoke_a':
                        a = v
                    elif k == 'p4smoke_b':
                        b = v
    out = os.path.join(os.path.dirname(script), '..', '..',
                       'sentinel-report.txt')
    with open(out, 'wb') as fh:
        nl = chr(10)
        fh.write(('p4smoke_a=%s' % (a if a is not None else 'nil'))
                 .encode('utf-8'))
        fh.write(nl.encode('utf-8'))
        fh.write(('p4smoke_b=%s' % (b if b is not None else 'nil'))
                 .encode('utf-8'))
        fh.write(nl.encode('utf-8'))
    if log:
        with open(log, 'wb') as fh:
            fh.write((chr(10).join(lines) + chr(10)).encode('utf-8'))
    sys.exit(0)
"""


def _responder_code(payload_template, max_samples):
    return (
        "import sys, json, time\n"
        "n = 0\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    cmd = req.get('command') or []\n"
        "    if cmd and cmd[0] == 'quit':\n"
        "        break\n"
        "    if cmd[:2] == ['script-message', 'p4-collect-sample']:\n"
        "        n += 1\n"
        "        if n > %d:\n"
        "            time.sleep(60)\n"          # live peer goes silent forever
        "        payload = %s\n"
        "        payload['time_pos'] = 10.0 + n\n"
        "        sys.stdout.write(json.dumps({\n"
        "            'event': 'client-message',\n"
        "            'args': ['p4-collect-reply', cmd[2],\n"
        "                     json.dumps(payload)]}) + chr(10))\n"
        # real mpv also answers the command itself with a response object
        "        sys.stdout.write(json.dumps({'error': 'success',\n"
        "            'request_id': req.get('request_id')}) + chr(10))\n"
        "    else:\n"
        "        sys.stdout.write(json.dumps({'error': 'success',\n"
        "            'request_id': req.get('request_id'), 'data': 7})\n"
        "                         + chr(10))\n"
        "    sys.stdout.flush()\n"
    ) % (max_samples, json.dumps(payload_template))


class TestIpcWallClockDeadline(unittest.TestCase):
    def _child(self, code):
        child = subprocess.Popen([sys.executable, "-c", code],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE)
        self.addCleanup(child.kill)
        return child

    @staticmethod
    def _open_func(child):
        return lambda *a, **k: _StdioPipe(child)

    def test_silent_live_process_cannot_outlive_the_deadline(self):
        baseline = threading.active_count()
        child = self._child(_SILENT_CHILD)
        ipc = col.CollectIpc("p4col-silent-1", timeout_s=5,
                             open_func=self._open_func(child))
        t0 = time.monotonic()
        with self.assertRaises(col.SamplingPayloadError):
            ipc.cmd("get_property", "x", timeout_s=1.0)
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 8.0,
                        "a live silent peer must not hold the caller past "
                        "the wall deadline (the old code blocked forever in "
                        "readline between two lines)")
        child.terminate()
        child.wait(timeout=10)
        ipc.close()   # the dead child EOFs the pipe; reclaim must not hang
        self.assertLessEqual(threading.active_count(), baseline)
        self.assertIsNotNone(child.poll())

    def test_close_refuses_to_lie_closed_while_reader_blocked(self):
        child = self._child(_SILENT_CHILD)
        ipc = col.CollectIpc("p4col-silent-2", timeout_s=5,
                             open_func=self._open_func(child))
        with self.assertRaises(col.CollectError):
            ipc.close(join_timeout_s=0.5)
        self.assertIsNotNone(ipc.f,
                             "a blocked reader keeps the handle open; "
                             "closed is never claimed falsely")
        child.terminate()
        child.wait(timeout=10)
        ipc.close()
        self.assertIsNone(ipc.f)

    def test_responder_roundtrip_through_reader_thread(self):
        child = self._child(_responder_code(_payload(0), 999))
        ipc = col.CollectIpc("p4col-resp-1", timeout_s=5,
                             open_func=self._open_func(child))
        try:
            reply = ipc.cmd("get_property", "osd-width")
            self.assertEqual(reply.get("data"), 7)
            snap = ipc.sample_once("s0", timeout_s=5)
            self.assertEqual(snap["time_pos"], 11.0)
        finally:
            child.terminate()
            child.wait(timeout=10)
            ipc.close()


class TestSessionWatchdog(unittest.TestCase):
    def test_deadline_expiry_kills_own_pid_and_reclaims_everything(self):
        baseline = threading.active_count()
        root = _tmp(self)
        (root / "trial").mkdir()
        children = []

        def spawn(exe_args, **kwargs):
            # the "pipe" child must talk on stdio, not inherit the console
            kwargs["stdin"] = subprocess.PIPE
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.DEVNULL
            child = subprocess.Popen([sys.executable, "-c", _SILENT_CHILD],
                                     **kwargs)
            children.append(child)
            return child

        def open_func(*a, **k):
            return _StdioPipe(children[0])

        session = col.CollectSession(root / "trial", ["unused-mpv"],
                                     pipe_name="p4col-watchdog",
                                     cwd=str(root), spawn=spawn,
                                     ipc_open_func=open_func)
        session.start(connect_ipc=True, ipc_timeout_s=5)
        t0 = time.monotonic()
        with self.assertRaises(col.SamplingPayloadError):
            session.get_property("x", timeout_s=1.0)
        self.assertLess(time.monotonic() - t0, 8.0)
        session.quit(timeout_s=5)
        self.assertIsNotNone(session.proc.poll(),
                             "the OWN pid must be stopped, never orphaned")
        self.assertTrue(session.handles_closed())
        self.assertLessEqual(threading.active_count(), baseline)
        self.assertIsNotNone(children[0].poll())


# ---------------------------------------------------------------------------
# F1/F4/F5: timed pilot end-to-end (responder child + real analysis/gates)
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, t=None):
        self.t = time.monotonic() if t is None else t

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


class TestTimedTrialEndToEnd(_FakeRuntimeMixin, unittest.TestCase):
    def setUp(self):
        self._sandboxes = []

    def _fake_repo(self):
        root = _tmp(self)
        ws = lib.workspace_root()
        (root / "tools").mkdir()
        (root / "docs").mkdir()
        shutil.copyfile(ws / "docs" / "P4实施计划.json",
                        root / "docs" / "P4实施计划.json")
        shutil.copyfile(ws / "tools" / "p4_lib.py",
                        root / "tools" / "p4_lib.py")
        for asset in ("scripts/scale-selector.lua",
                      "script-opts/scale-selector.conf",
                      "script-opts/scale-selector-gears.conf"):
            dst = root / asset
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ws / asset, dst)
        media_dir = (root / "docs" / "验证" / "开发" / "p4-001" / "media" /
                     "motion24")
        media_dir.mkdir(parents=True)
        media = media_dir / "motion24.mkv"
        media.write_bytes(b"M" * 8192)
        (media_dir / "media-manifest.json").write_bytes(lib.strict_json_bytes({
            "clip": "motion24",
            "media_sha256": lib.sha256_bytes(b"M" * 8192),
            "media_bytes": 8192}))
        return root

    def _patches(self):
        budget = dict(lib.SAMPLING_BUDGET, warmup_min_s=0.0,
                      warmup_max_s=5.0, poll_period_s=0.1)
        patches = [
            unittest.mock.patch.object(
                col, "preflight_collect",
                unittest.mock.Mock(return_value={"ok": True,
                                                 "note": "covered by "
                                                 "TestPreflight"})),
            unittest.mock.patch.object(
                col, "select_arm_via_menu",
                unittest.mock.Mock(return_value={"ok": True,
                                                 "gear": "off",
                                                 "chain_epoch": 1,
                                                 "chain_verified": True})),
            unittest.mock.patch.object(
                col, "probe_gpu_state",
                unittest.mock.Mock(return_value={
                    "nvidia_smi_available": True,
                    "gpu_samples": [{"memory_used_mib": 100.0,
                                     "util_pct": 1.0, "temp_c": 30.0}],
                    "other_mpv_processes": []})),
            unittest.mock.patch.object(lib, "SAMPLING_BUDGET", budget),
            unittest.mock.patch.object(col, "PILOT_WALL_S", 30.0),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _sandbox(self):
        return self._new_sandbox_path("sbx-p4col-pilot")

    def _spawn_factory(self, recorder, code):
        def spawn(exe_args, **kwargs):
            # the responder child must talk on stdio, not inherit consoles
            kwargs["stdin"] = subprocess.PIPE
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.DEVNULL
            child = subprocess.Popen([sys.executable, "-c", code], **kwargs)
            recorder.append(child)
            return child
        return spawn

    def test_pilot_full_run_gates_and_rc_contract(self):
        self._patches()
        repo = self._fake_repo()
        children = []
        sbx = self._sandbox()
        clock = _FakeClock()
        result = col.run_timed_trial(
            sbx, "G1_equalrect_main", "baselineHQ", "off", 1,
            run_kind="pilot", repo_root=repo,
            spawn=self._spawn_factory(
                children, _responder_code(_payload(0), 999)),
            clock=clock, sleep=clock.sleep,
            ipc_open_func=lambda *a, **k: _StdioPipe(children[0]))
        self.assertEqual(result["n_snapshots"], 10)
        self.assertIs(result["gate"]["ok"], True)
        self.assertEqual(col.timed_trial_rc(result), col.RC_OK)
        # F5: a pilot never claims the PNG four-piece identity
        self.assertTrue(result["png_identity"].startswith(
            "NOT_ESTABLISHED"))
        self.assertEqual(result["cleanup_errors"], [])
        run_dir = sbx / "runs" / "pilot-r1"
        self.assertTrue((run_dir / "run.jsonl").is_file())
        manifest = json.loads(
            (run_dir / "manifest.json").read_text("utf-8"))
        self.assertTrue(manifest["handles_closed_before_manifest"])
        self.assertEqual(manifest["png_identity"], col.PILOT_PNG_DISCLOSURE)
        self.assertEqual(manifest["cleanup_errors"], [])
        self.assertIsNotNone(children[0].poll(),
                             "own child reaped after quit (never orphaned)")

    def test_pilot_silence_failure_preserves_primary_and_cleans(self):
        baseline = threading.active_count()
        self._patches()
        repo = self._fake_repo()
        children = []
        sbx = self._sandbox()
        clock = _FakeClock()
        with unittest.mock.patch.object(col, "PILOT_WALL_S", 1.5):
            with self.assertRaises(col.SamplingPayloadError):
                col.run_timed_trial(
                    sbx, "G1_equalrect_main", "baselineHQ", "off", 1,
                    run_kind="pilot", repo_root=repo,
                    spawn=self._spawn_factory(
                        children, _responder_code(_payload(0), 4)),
                    clock=clock, sleep=clock.sleep,
                    ipc_open_func=lambda *a, **k: _StdioPipe(children[0]))
        self.assertIsNotNone(children[0].poll(),
                             "own child stopped by the finally cleanup")
        self.assertLessEqual(threading.active_count(), baseline,
                             "reader threads must be reclaimed, never left")
        run_dir = sbx / "runs" / "pilot-r1"
        self.assertFalse((run_dir / "run.jsonl").exists(),
                         "no timing stream may survive a failed run")
        doc = json.loads((run_dir / "manifest.json").read_text("utf-8"))
        self.assertEqual(doc["result_status"], "ERROR")
        self.assertEqual(doc["primary_exception"]["type"],
                         "SamplingPayloadError")
        self.assertEqual(doc["cleanup_errors"], [])


# ---------------------------------------------------------------------------
# F3/F4/F5: CLI contract (rc mapping, capture refusal, help consistency)
# ---------------------------------------------------------------------------


class TestCaptureAndRcContract(unittest.TestCase):
    def test_cli_capture_refused_before_spawn(self):
        _no_spawn(self)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main(["--mode", "capture"])
        self.assertEqual(rc, col.RC_REFUSED)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["status"], "NOT_IMPLEMENTED")
        self.assertIn("B3", doc["reason"])

    def test_api_capture_refused_structured(self):
        root = _tmp(self)
        _no_spawn(self)
        with self.assertRaises(col.CollectError) as ctx:
            col.run_timed_trial(root / "p4-001" / "sbx",
                                "G1_equalrect_main", "baselineHQ", "off", 1,
                                run_kind="capture")
        self.assertEqual(ctx.exception.args[0]["status"], "NOT_IMPLEMENTED")

    def test_identity_probe_rc_table(self):
        base = {"status": "EXITED",
                "verdict": {"initialization": "EVIDENCED",
                            "model_identity": "NAMED_IN_LOG"}}
        self.assertEqual(col.identity_probe_rc(base), col.RC_OK)
        cases = [
            ({"status": "TIMEOUT"}, col.RC_NOT_ESTABLISHED),
            ({"verdict": {"initialization": "NOT_ESTABLISHED",
                          "model_identity": "NAMED_IN_LOG"}},
             col.RC_NOT_ESTABLISHED),
            ({"verdict": {"initialization": "EVIDENCED",
                          "model_identity": "NOT_ESTABLISHED"}},
             col.RC_NOT_ESTABLISHED),
            ({"verdict": {"initialization": "BLOCKED_ENV",
                          "model_identity": "NAMED_IN_LOG"}},
             col.RC_REFUSED),
            ({"zero_write_violation": "vs changed"}, col.RC_REFUSED),
            ({"status": "EXITED", "verdict": None}, col.RC_NOT_ESTABLISHED),
        ]
        for mutation, expected in cases:
            doc = json.loads(json.dumps(base))
            doc.update(mutation)
            self.assertEqual(col.identity_probe_rc(doc), expected, mutation)

    def test_timed_trial_rc_table(self):
        self.assertEqual(col.timed_trial_rc({"gate": {"ok": True}}), col.RC_OK)
        self.assertEqual(col.timed_trial_rc({"gate": {"ok": False}}),
                         col.RC_NOT_ESTABLISHED)
        self.assertEqual(col.timed_trial_rc({"gate": {"ok": True},
                                             "zero_write_violation": "x"}),
                         col.RC_REFUSED)
        self.assertEqual(col.timed_trial_rc({"gate": {}}),
                         col.RC_NOT_ESTABLISHED)

    def test_cli_pilot_missing_media_is_structured_nonzero(self):
        _no_spawn(self)
        base = Path(tempfile.gettempdir()) / "p4-001"
        sbx = base / ("sbx-p4col-cli-%x" % time.time_ns())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = col.main(["--mode", "pilot", "--sandbox-root", str(sbx)])
        self.assertEqual(rc, col.RC_REFUSED)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["error"], "MissingInputError")
        self.assertIn("prepare-media first", doc["detail"])
        self.assertFalse(sbx.exists(),
                         "refused before any write (F2/F4 at the CLI)")

    def test_help_and_cli_consistent_no_trial_dir(self):
        # F3: the unsupported flag is gone from parser AND help text
        self.assertNotIn("--trial-dir", col._HELP)
        self.assertIn("--sandbox-root", col._HELP)
        self.assertIn("NOT_IMPLEMENTED", col._HELP)
        parser = col.build_arg_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--mode", "pilot", "--trial-dir", "x"])
        self.assertEqual(ctx.exception.code, 2)


# ---------------------------------------------------------------------------
# API self-description
# ---------------------------------------------------------------------------


class TestApiManifest(unittest.TestCase):
    def test_manifest_lists_public_functions(self):
        manifest = col.api_manifest()
        joined = "\n".join(manifest)
        for expected in ("preflight_collect(", "clone_runtime(",
                         "relocate_vpy(", "payload_to_snapshot(",
                         "build_run_record(", "n1_gate_wiring(",
                         "run_identity_probe(", "run_timed_trial(",
                         "write_identity_sample_y4m(", "main("):
            self.assertIn(expected, joined)
        self.assertNotIn(" _", joined)


if __name__ == "__main__":
    unittest.main()
