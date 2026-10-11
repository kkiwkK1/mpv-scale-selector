"""Workflow-guard tests use synthetic temporary projects, not live mpv data."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("flow_guard", Path(__file__).with_name("guard.py"))
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def make_dir_link(target, link):
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


def remove_link_only(link):
    """Delete the link entry itself, never its target. Idempotent: a
    TemporaryDirectory teardown may already have removed it."""
    try:
        if os.name == "nt":
            os.rmdir(link)   # a junction is a directory reparse point
        else:
            os.unlink(link)  # a dir symlink is removed via unlink, not rmdir
    except FileNotFoundError:
        pass


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mpv-flow-guard-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch = mock.patch.object(guard, "PROJECT", self.root)
        patch.start()
        self.addCleanup(patch.stop)
        backup = mock.patch.object(guard, "verified_backup", return_value={"status": "PASS", "source_unchanged": True})
        backup.start()
        self.addCleanup(backup.stop)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/scaler.lua").write_bytes(b"-- synthetic source; never executed\n")
        self.directory = guard.folder("s1")
        self.directory.mkdir(parents=True)
        self.tests = {"stage": "P1", "session": "s1", "status": "PASS", "required_unmeasured": [],
                      "live_configuration_written": False, "pending_user_checks": [],
                      "cases": [{"id": "CTL-01", "status": "PASS", "evidence": "synthetic"}]}
        self.seal()

    def write_json(self, path, data):
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream)
            stream.write("\n")

    def seal(self):
        self.write_json(self.directory / "tests.json", self.tests)
        snapshot = {"schema": "mpv-scaler-stage/v1", "stage": "P1", "session": "s1",
                    "files": {"scripts/scaler.lua": guard.sha(self.root / "scripts/scaler.lua")},
                    "tests_sha256": guard.sha(self.directory / "tests.json")}
        self.write_json(self.directory / "candidate.json", snapshot)
        self.checksum = guard.sha(self.directory / "candidate.json")

    def payload(self):
        review = {"verdict": "pass", "candidate_sha256": self.checksum, "findings": []}
        return {"approval": "(approve)", "technical": dict(review), "safety": dict(review)}

    def test_only_explicit_approve_is_permission(self):
        guard.approve("(approve)\n")
        for value in ["", "(reject)", "edit this", "approved", "(approve)\nextra"]:
            with self.assertRaises(ValueError):
                guard.approve(value)

    def test_approve_accepts_whitespace_wrapped_token(self):
        # U-2 残余现状钉子：approve 按 strip 后比较，" (approve) " 目前会
        # 通过。该行为是否符合『精确 (approve)』待项目决策——本测试只钉住
        # 现状，不修改 guard.py（它在 p3_guard 的 ENV_FILES 哈希保护名单内，
        # 行为变更须走修订流程重新封链）。
        guard.approve(" (approve) ")
        guard.approve("\t\n(approve)\n ")
        # strip 之外的边界保持收紧：strip 后内容仍不精确即拒绝
        with self.assertRaises(ValueError):
            guard.approve(" (approve)x ")

    def test_folder_rejects_junction_session_dir(self):
        # U-2 残余：folder 的链接/reparse 拒绝分支此前没有真实触发过的负例
        #（junction 在 Windows 免管理员即可构造，见 test_p4_lib 先例）。
        target = self.root / "elsewhere"
        target.mkdir()
        link = self.root / "docs/验证/开发/s2"
        if not make_dir_link(target, link):
            self.skipTest("neither junction nor symlink available on this host")
        self.addCleanup(remove_link_only, link)
        with self.assertRaises(ValueError):
            guard.folder("s2")

    def test_source_path_rejects_absolute_posix_and_backslash(self):
        # U-2 残余：反斜杠与绝对 POSIX 路径分支补钉（驱动器号形态
        # "D:/secret" 已由既有负例覆盖，两者走的是同一前置检查）。
        for name in ["/etc/passwd", "a\\b"]:
            with self.assertRaises(ValueError):
                guard.source_path(name)

    def test_invalid_session_names(self):
        for value in ["../escape", "X", "with space", "a/b", "", "x" * 65]:
            with self.assertRaises(ValueError):
                guard.slug(value)

    def test_candidate_matches(self):
        _, _, checksum = guard.candidate("P1", "s1")
        self.assertEqual(checksum, self.checksum)

    def test_source_tamper_detected(self):
        (self.root / "scripts/scaler.lua").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            guard.candidate("P1", "s1")

    def test_report_tamper_detected(self):
        with (self.directory / "tests.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaises(ValueError):
            guard.candidate("P1", "s1")

    def test_required_unmeasured_rejected(self):
        self.tests["required_unmeasured"] = ["CTL-01"]
        self.seal()
        with self.assertRaises(ValueError):
            guard.candidate("P1", "s1")

    def test_live_write_report_rejected(self):
        self.tests["live_configuration_written"] = True
        self.seal()
        with self.assertRaises(ValueError):
            guard.candidate("P1", "s1")

    def test_empty_cases_rejected(self):
        self.tests["cases"] = []
        self.seal()
        with self.assertRaises(ValueError):
            guard.candidate("P1", "s1")

    def test_private_or_traversal_source_rejected(self):
        for name in ["../outside", ".pi/auth.json", "D:/secret", "./scripts/scaler.lua"]:
            with self.assertRaises(ValueError):
                guard.source_path(name)

    def test_existing_session_not_overwritten(self):
        with self.assertRaises(ValueError):
            guard.preflight("P1", "s1", "")

    def test_both_reviews_bind_same_candidate(self):
        payload = self.payload()
        payload["safety"]["candidate_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            guard.accept("P1", "s1", payload)
        self.assertFalse((self.directory / "acceptance.json").exists())

    def test_major_finding_rejected_even_with_pass_verdict(self):
        payload = self.payload()
        payload["technical"]["findings"] = [{"severity": "major"}]
        with self.assertRaises(ValueError):
            guard.accept("P1", "s1", payload)

    def test_acceptance_is_create_only_and_not_live_installation(self):
        result = guard.accept("P1", "s1", self.payload())
        self.assertFalse(result["live_deployment_completed"])
        self.assertTrue(result["user_approved"])
        with self.assertRaises(FileExistsError):
            guard.accept("P1", "s1", self.payload())

    def test_previous_stage_must_be_accepted_and_unchanged(self):
        guard.accept("P1", "s1", self.payload())
        with mock.patch.object(guard.subprocess, "check_output", side_effect=["fake-commit\n", ""]):
            result = guard.preflight("P2", "s2", "s1")
        self.assertEqual(result["dependency"]["stage"], "P1")
        self.assertFalse(guard.folder("s2").exists())
        (self.root / "scripts/scaler.lua").write_bytes(b"changed after acceptance")
        with self.assertRaises(ValueError):
            guard.preflight("P2", "s2", "s1")

    def test_json_approval_cannot_override_explicit_argv_permission(self):
        payload = self.payload()
        for argv, expected in [(["guard.py", "accept", "--session", "s1"], 1),
                               (["guard.py", "accept", "--session", "s1", "--approval", 'edit","approval":"(approve)'], 1),
                               (["guard.py", "accept", "--session", "s1", "--approval", "(approve)"], 0)]:
            with mock.patch.object(guard.sys, "argv", argv):
                with mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))):
                    with mock.patch.object(guard.sys, "stdout", io.StringIO()):
                        self.assertEqual(guard.main(), expected)

    def test_machine_gate_requires_planned_test_ids(self):
        for planned, expected in [(["CTL-01"], 0), (["CTL-02"], 1)]:
            stdin = io.StringIO(json.dumps({"stage": "P1", "required_tests": planned}))
            with mock.patch.object(guard.sys, "argv", ["guard.py", "check", "--session", "s1"]):
                with mock.patch.object(guard.sys, "stdin", stdin), mock.patch.object(guard.sys, "stdout", io.StringIO()):
                    self.assertEqual(guard.main(), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
