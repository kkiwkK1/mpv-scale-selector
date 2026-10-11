"""Synthetic (mpv-free) unit tests for the 限域修正 C evidence-integrity gate.

Covers:
  * evidence-dir freshness guard (ensure_fresh_evidence_dir), including the
    frozen-dir-always-refuses rule;
  * create-only Evidence writes (write_json / save_transcript / copy_file);
  * create-only per-case targets (MpvSession.check_targets_unused) and
    screenshot precheck — without launching any process;
  * safe_manifest_relpath path-safety rules (traversal/absolute/backslash/
    private/out-of-session/links);
  * evidence manifest build/verify round-trip and tamper detection;
  * tools/p1_check_evidence.run_checks against synthetic session fixtures:
    missing manifest entries, modified files, forged hashes, illegal paths,
    dangling tests.json refs, manifest-swap detection, candidate pinning.

These tests never touch the real evidence trees and never spawn mpv.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p1_lib as lib  # noqa: E402
import p1_check_evidence as checker  # noqa: E402

TEST_SESSION = "p1-test-ev"


def make_dir_link(target: Path, link: Path) -> bool:
    """Create `link` as a directory junction on Windows (no admin rights
    needed, see test_p4_lib precedent) or a directory symlink elsewhere;
    False = the platform allows neither form."""
    if os.name == "nt":
        try:
            import _winapi  # stdlib on CPython-Windows; junction needs no admin
            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, OSError):
            pass  # fall back to the privileged symlink form below
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


def remove_link_only(link: Path) -> None:
    """Delete the link entry itself, never its target (M-9 cleanup rule).
    Idempotent: a TemporaryDirectory teardown may already have removed it."""
    try:
        if os.name == "nt":
            os.rmdir(link)   # a junction is a directory reparse point
        else:
            os.unlink(link)  # a dir symlink is removed via unlink, not rmdir
    except FileNotFoundError:
        pass


class FreshDirGuard(unittest.TestCase):
    def test_fresh_dir_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib.ensure_fresh_evidence_dir(Path(tmp) / "new")  # absent → ok
            (Path(tmp) / "empty").mkdir()
            lib.ensure_fresh_evidence_dir(Path(tmp) / "empty")  # empty → ok

    def test_used_dir_refused_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "used"
            d.mkdir()
            (d / "objective-results.json").write_bytes(b"{}")
            with self.assertRaises(FileExistsError):
                lib.ensure_fresh_evidence_dir(d)
            (d / "objective-results.json").unlink()
            (d / "some-leftover.txt").write_bytes(b"x")
            with self.assertRaises(FileExistsError):
                lib.ensure_fresh_evidence_dir(d)

    def test_used_dir_with_force_allowed_but_frozen_never(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "used"
            d.mkdir()
            (d / "objective-results.json").write_bytes(b"{}")
            lib.ensure_fresh_evidence_dir(d, force=True)  # explicit ack only
            frozen = Path(tmp) / "frozen"
            frozen.mkdir()
            (frozen / "candidate.json").write_bytes(b"{}")
            (frozen / "tests.json").write_bytes(b"{}")
            with self.assertRaises(FileExistsError):
                lib.ensure_fresh_evidence_dir(frozen, force=True)

    def test_frozen_marker_alone_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "f2"
            d.mkdir()
            (d / "tests.json").write_bytes(b"{}")
            with self.assertRaises(FileExistsError):
                lib.ensure_fresh_evidence_dir(d, force=True)


class CreateOnlyEvidence(unittest.TestCase):
    def test_write_json_create_only_and_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = lib.Evidence(Path(tmp))
            p = ev.write_json("x.json", {"状态": "pass"})
            self.assertNotIn(b"\r", p.read_bytes())
            with self.assertRaises(FileExistsError):
                ev.write_json("x.json", {"状态": "pass2"})
            self.assertEqual(json.loads(p.read_bytes().decode("utf-8"))["状态"], "pass")

    def test_save_transcript_create_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = lib.Evidence(Path(tmp))
            p = ev.save_transcript("t.jsonl", [{"req": ["get_property", "scale"]}])
            self.assertNotIn(b"\r", p.read_bytes())
            with self.assertRaises(FileExistsError):
                ev.save_transcript("t.jsonl", [{"req": ["quit"]}])

    def test_copy_file_create_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.bin"
            src.write_bytes(b"\x00\x01")
            ev = lib.Evidence(Path(tmp) / "ev")
            dst = ev.copy_file(src, "copy.bin")
            self.assertEqual(dst.read_bytes(), b"\x00\x01")
            with self.assertRaises(FileExistsError):
                ev.copy_file(src, "copy.bin")

    def test_session_targets_create_only_no_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = lib.make_env("unittest-targets", session="p1-test-ev")
            try:
                s = lib.MpvSession(env, "caseA", Path(tmp) / "ev",
                                   session="p1-test-ev")
                s.check_targets_unused()  # clean → ok (mpv NOT launched)
                (Path(tmp) / "ev").mkdir(parents=True, exist_ok=True)
                s.console_path.write_bytes(b"stale")
                with self.assertRaises(FileExistsError):
                    s.check_targets_unused()
                s.console_path.unlink()
                s.log_path.write_bytes(b"stale")
                with self.assertRaises(FileExistsError):
                    s.check_targets_unused()
            finally:
                env.cleanup()

    def test_screenshot_target_precheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "shot.png"
            lib.MpvSession.ensure_screenshot_target(p)  # absent → ok
            p.write_bytes(b"png")
            with self.assertRaises(FileExistsError):
                lib.MpvSession.ensure_screenshot_target(p)

    def test_pipe_and_temp_roots_use_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = lib.make_env("unittest-pipe", session="p1-test-ev")
            try:
                s = lib.MpvSession(env, "caseB", Path(tmp), session="p1-test-ev")
                self.assertTrue(s.pipe_name.startswith("p1-test-ev-caseB"))
                self.assertIn("p1-test-ev", str(env.root))
            finally:
                env.cleanup()


class SafeManifestPaths(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.ev = self.repo / "docs" / "验证" / "开发" / TEST_SESSION
        self.ev.mkdir(parents=True)
        (self.ev / "a.log").write_bytes(b"log")

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_path(self):
        p = lib.safe_manifest_relpath(
            f"docs/验证/开发/{TEST_SESSION}/a.log", TEST_SESSION, self.repo)
        self.assertTrue(p.is_file())

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            lib.safe_manifest_relpath(
                f"docs/验证/开发/{TEST_SESSION}/../x/a.log", TEST_SESSION, self.repo)

    def test_rejects_absolute_backslash_drive(self):
        for bad in (str(self.ev / "a.log"), str(self.ev / "a.log").replace("/", "\\"),
                    "C:/x/a.log"):
            with self.assertRaises(ValueError):
                lib.safe_manifest_relpath(bad, TEST_SESSION, self.repo)

    def test_rejects_out_of_session_tree(self):
        (self.repo / "docs" / "验证" / "开发" / "other-session").mkdir(parents=True)
        (self.repo / "docs" / "验证" / "开发" / "other-session" / "f.txt").write_bytes(b"x")
        with self.assertRaises(ValueError):
            lib.safe_manifest_relpath(
                "docs/验证/开发/other-session/f.txt", TEST_SESSION, self.repo)

    def test_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            lib.safe_manifest_relpath(
                f"docs/验证/开发/{TEST_SESSION}/nope.bin", TEST_SESSION, self.repo)

    def test_rejects_junction_component(self):
        """M-9: the link check must fire on a DIRECTORY junction inside the
        session tree (reachable on Windows without admin) even though the
        requested file really exists behind the junction."""
        outside = self.repo / "outside"
        outside.mkdir()
        (outside / "x.log").write_bytes(b"escaped")
        link = self.ev / "linkdir"
        if not make_dir_link(outside, link):
            self.skipTest("neither junction nor symlink available on this host")
        self.addCleanup(remove_link_only, link)
        with self.assertRaises(ValueError):
            lib.safe_manifest_relpath(
                f"docs/验证/开发/{TEST_SESSION}/linkdir/x.log",
                TEST_SESSION, self.repo)

    def test_rejects_file_symlink(self):
        """Supplementary coverage: the original plain file-symlink form
        (needs privilege on Windows, runs everywhere else)."""
        target = self.ev / "a.log"
        link = self.ev / "a-link.log"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not permitted on this host")
        with self.assertRaises(ValueError):
            lib.safe_manifest_relpath(
                f"docs/验证/开发/{TEST_SESSION}/a-link.log", TEST_SESSION, self.repo)


class ManifestRoundtrip(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.ev = self.repo / "docs" / "验证" / "开发" / TEST_SESSION
        self.ev.mkdir(parents=True)
        (self.ev / "a.log").write_bytes(b"hello")
        (self.ev / "b.json").write_bytes(b"{}")

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_and_verify_roundtrip(self):
        paths = [self.ev / "a.log", self.ev / "b.json"]
        manifest = lib.build_evidence_manifest(TEST_SESSION, paths, self.repo,
                                               generated_at="2026-10-03T00:00:00+0800")
        self.assertEqual(manifest["schema"], lib.EVIDENCE_MANIFEST_SCHEMA)
        self.assertEqual(len(manifest["files"]), 2)
        self.assertEqual(lib.verify_evidence_manifest(manifest, TEST_SESSION, self.repo), [])

    def test_rejects_out_of_repo_paths(self):
        outside = Path(tempfile.gettempdir()) / "p1-test-outside.bin"
        outside.write_bytes(b"x")
        try:
            with self.assertRaises(ValueError):
                lib.build_evidence_manifest(TEST_SESSION, [outside], self.repo)
        finally:
            outside.unlink(missing_ok=True)

    def test_verify_detects_modified_file(self):
        manifest = lib.build_evidence_manifest(TEST_SESSION, [self.ev / "a.log"], self.repo)
        (self.ev / "a.log").write_bytes(b"tampered")
        problems = lib.verify_evidence_manifest(manifest, TEST_SESSION, self.repo)
        self.assertTrue(any("被改动" in p for p in problems), problems)

    def test_verify_detects_missing_file(self):
        manifest = lib.build_evidence_manifest(TEST_SESSION, [self.ev / "a.log"], self.repo)
        (self.ev / "a.log").unlink()
        problems = lib.verify_evidence_manifest(manifest, TEST_SESSION, self.repo)
        # either wording is a valid rejection of the now-missing file
        self.assertTrue(any("缺失" in p or "不是常规文件" in p for p in problems),
                        problems)

    def test_verify_detects_forged_hash_and_bad_path(self):
        manifest = lib.build_evidence_manifest(TEST_SESSION, [self.ev / "a.log"], self.repo)
        rel = next(iter(manifest["files"]))
        manifest["files"][rel] = "z" * 64
        manifest["files"] = {"../evil": "a" * 64, **manifest["files"]}
        problems = lib.verify_evidence_manifest(manifest, TEST_SESSION, self.repo)
        self.assertTrue(any("伪造" in p for p in problems), problems)
        self.assertTrue(any("不允许穿越" in p or "非法证据路径" in p for p in problems),
                        problems)

    def test_verify_detects_wrong_session_and_schema(self):
        manifest = lib.build_evidence_manifest(TEST_SESSION, [self.ev / "a.log"], self.repo)
        manifest["session"] = "p1-other"
        problems = lib.verify_evidence_manifest(manifest, TEST_SESSION, self.repo)
        self.assertTrue(any("session 不符" in p for p in problems), problems)
        manifest["session"] = TEST_SESSION
        manifest["schema"] = "bogus/v1"
        problems = lib.verify_evidence_manifest(manifest, TEST_SESSION, self.repo)
        self.assertTrue(any("schema 不符" in p for p in problems), problems)


class CheckerFixtures(unittest.TestCase):
    """End-to-end synthetic fixtures for tools/p1_check_evidence.run_checks."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.sd = self.repo / "docs" / "验证" / "开发" / TEST_SESSION
        (self.sd / "implementer").mkdir(parents=True)
        # a candidate-source stand-in inside the synthetic repo
        tools_dir = self.repo / "tools"
        tools_dir.mkdir()
        (tools_dir / "p1_lib.py").write_bytes(b"# synthetic stand-in\n")
        # synthetic evidence artifacts
        (self.sd / "implementer" / "CTL-99.mpv.log").write_bytes(b"log-bytes")
        (self.sd / "implementer" / "CTL-99.console.txt").write_bytes(b"console")
        (self.sd / "implementer" / "objective-results.json").write_bytes(b"{}\n")
        self.obj_results = f"docs/验证/开发/{TEST_SESSION}/implementer/objective-results.json"
        self.manifest = lib.build_evidence_manifest(
            TEST_SESSION,
            [self.sd / "implementer" / "CTL-99.mpv.log",
             self.sd / "implementer" / "CTL-99.console.txt",
             self.sd / "implementer" / "objective-results.json"],
            self.repo, generated_at="2026-10-03T00:00:00+0800")
        self.manifest_path = self.sd / "implementer" / "evidence-manifest.json"
        self.manifest_path.write_bytes(
            (json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def _tests_obj(self, manifest_binding=True, full_ids=False):
        ev_root = f"docs/验证/开发/{TEST_SESSION}"
        ctl99 = {
            "id": "CTL-99", "status": "PASS",
            "evidence": f"{ev_root}/implementer/objective-results.json",
            "evidence_files": [
                f"{ev_root}/implementer/CTL-99.mpv.log",
                f"{ev_root}/implementer/CTL-99.console.txt",
            ],
        }
        cases = [ctl99]
        if full_ids:
            # the remaining required ids, each bound to the (existing) summary
            cases += [{"id": rid, "status": "PASS", "evidence": self.obj_results,
                       "evidence_files": []}
                      for rid in checker.DEFAULT_REQUIRED_P1 if rid != "CTL-99"]
        tests = {
            "stage": "P1", "session": TEST_SESSION, "status": "PASS",
            "required_unmeasured": [],
            "cases": cases,
        }
        if manifest_binding:
            tests["evidence_manifest"] = {
                "path": f"{ev_root}/implementer/evidence-manifest.json",
                "sha256": lib.sha256_file(self.manifest_path),
            }
        tests_path = self.sd / "tests.json"
        tests_path.write_bytes(
            (json.dumps(tests, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return tests, tests_path

    def _candidate_obj(self, tests_path: Path, tests: dict):
        candidate = {
            "schema": "mpv-scaler-stage/v1", "stage": "P1", "session": TEST_SESSION,
            "files": {"tools/p1_lib.py":
                      lib.sha256_file(self.repo / "tools" / "p1_lib.py")},
            "tests_sha256": lib.sha256_file(tests_path),
        }
        cpath = self.sd / "candidate.json"
        cpath.write_bytes(
            (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return candidate, cpath

    def test_clean_fixture_passes_without_tests(self):
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], None, None,
            False, self.repo)
        self.assertEqual(problems, [])

    def test_clean_fixture_passes_with_tests_and_candidate(self):
        tests, tests_path = self._tests_obj(full_ids=True)
        _, cpath = self._candidate_obj(tests_path, tests)
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            cpath, True, self.repo)
        self.assertEqual(problems, [])

    def test_manifest_entry_missing_for_referenced_file(self):
        tests, tests_path = self._tests_obj()
        ev_root = f"docs/验证/开发/{TEST_SESSION}"
        (self.sd / "implementer" / "extra.bin").write_bytes(b"unbound")
        tests["cases"][0]["evidence_files"].append(f"{ev_root}/implementer/extra.bin")
        tests_path.write_bytes((json.dumps(tests, ensure_ascii=False, indent=2) + "\n")
                               .encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            None, False, self.repo)
        self.assertTrue(any("缺少条目" in p for p in problems), problems)

    def test_modified_evidence_detected(self):
        tests, tests_path = self._tests_obj()
        (self.sd / "implementer" / "CTL-99.mpv.log").write_bytes(b"CHANGED")
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            None, False, self.repo)
        self.assertTrue(any("被改动" in p for p in problems), problems)

    def test_dangling_reference_detected(self):
        tests, tests_path = self._tests_obj()
        tests["cases"][0]["evidence_files"].append(
            f"docs/验证/开发/{TEST_SESSION}/implementer/ghost.png")
        tests_path.write_bytes((json.dumps(tests, ensure_ascii=False, indent=2) + "\n")
                               .encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            None, False, self.repo)
        # P2 兼容迁移（REV-02 同域修复）：会话内缺失文件现在短路给出
        # 「清单文件缺失」文案（更明确）；拒绝能力不变，两种文案均有效。
        self.assertTrue(any("清单文件缺失" in p or "不是常规文件" in p for p in problems),
                        problems)

    def test_illegal_reference_paths_detected(self):
        tests, tests_path = self._tests_obj()
        bad_refs = [
            f"..\\escape.png",                          # backslash
            f"docs/验证/开发/{TEST_SESSION}/../../etc.png",  # traversal
            "C:/abs/path.png",                           # drive/absolute
            f"docs/验证/开发/p1-other-session/f.png",    # other session tree
        ]
        for ref in bad_refs:
            tests["cases"][0]["evidence_files"] = [ref]
            tests_path.write_bytes((json.dumps(tests, ensure_ascii=False, indent=2) + "\n")
                                   .encode("utf-8"))
            problems = checker.run_checks(
                self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
                None, False, self.repo)
            self.assertTrue(problems, f"expected rejection for {ref!r}")

    def test_manifest_swap_detected_via_binding(self):
        tests, tests_path = self._tests_obj()
        self.manifest["files"] = {}  # forged empty manifest
        self.manifest_path.write_bytes(
            (json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            None, False, self.repo)
        self.assertTrue(any("被改动" in p or "缺失或为空" in p for p in problems), problems)

    def test_candidate_tests_sha_mismatch(self):
        tests, tests_path = self._tests_obj()
        _, cpath = self._candidate_obj(tests_path, tests)
        candidate = json.loads(cpath.read_bytes().decode("utf-8"))
        candidate["tests_sha256"] = "b" * 64
        cpath.write_bytes((json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
                          .encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            cpath, False, self.repo)
        self.assertTrue(any("tests_sha256" in p for p in problems), problems)

    def test_candidate_modified_source_detected(self):
        tests, tests_path = self._tests_obj()
        _, cpath = self._candidate_obj(tests_path, tests)
        candidate = json.loads(cpath.read_bytes().decode("utf-8"))
        candidate["files"]["tools/p1_lib.py"] = "c" * 64
        cpath.write_bytes((json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
                          .encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            cpath, False, self.repo)
        self.assertTrue(any("被改动" in p for p in problems), problems)

    def test_candidate_illegal_source_path_detected(self):
        tests, tests_path = self._tests_obj()
        _, cpath = self._candidate_obj(tests_path, tests)
        candidate = json.loads(cpath.read_bytes().decode("utf-8"))
        candidate["files"][".git/config"] = "d" * 64
        cpath.write_bytes((json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
                          .encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            cpath, False, self.repo)
        self.assertTrue(any("私有" in p for p in problems), problems)

    def test_require_tests_missing_id(self):
        tests, tests_path = self._tests_obj()
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            None, True, self.repo)
        self.assertTrue(any("必需测试缺少报告条目" in p for p in problems), problems)

    def test_crlf_json_rejected(self):
        tests, tests_path = self._tests_obj()
        tests_path.write_bytes(
            json.dumps(tests, ensure_ascii=False, indent=2).replace("\n", "\r\n")
            .encode("utf-8"))
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.manifest_path], tests_path,
            None, False, self.repo)
        self.assertTrue(any("CRLF" in p for p in problems), problems)

    def test_missing_manifest_file_detected(self):
        problems = checker.run_checks(
            self.sd, TEST_SESSION, "P1", [self.sd / "nope" / "evidence-manifest.json"],
            None, None, False, self.repo)
        self.assertTrue(any("清单缺失" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
