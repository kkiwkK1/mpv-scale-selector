"""All restore targets are disposable temporary directories, never APPDATA/mpv."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

SPEC = importlib.util.spec_from_file_location("backup_tool", Path(__file__).resolve().parents[1] / "tools/mpv_config_backup.py")
backup_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_tool)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mpv-backup-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source" / "mpv"
        self.source.mkdir(parents=True)
        (self.source / "scripts").mkdir()
        (self.source / "shaders").mkdir()
        (self.source / "空目录").mkdir()
        (self.source / "mpv.conf").write_bytes(b"profile=high-quality\r\n")
        (self.source / "scripts" / "中文 文件.lua").write_bytes("-- UTF-8 保留\n".encode())
        (self.source / "shaders" / "binary.glsl").write_bytes(b"\x00\xff\r\n")
        self.launcher = self.source.parent / "mpv-RIFE.cmd"
        self.launcher.write_bytes(b"@echo off\r\n")
        self.backup = self.root / "snapshot"
        self.backup.mkdir()
        roots = []
        for label, source in [("mpv-config", self.source), ("mpv-launcher", self.launcher)]:
            directories, files = backup_tool.inventory(source)
            payload = self.backup / "payload" / label
            payload.mkdir(parents=True)
            for directory in directories:
                (payload / directory).mkdir(parents=True, exist_ok=True)
            records = []
            for name, (size, digest) in files.items():
                destination = payload / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name if source.is_dir() else source, destination)
                records.append({"path": name, "bytes": size, "sha256": digest})
            roots.append({"id": label, "source": str(source),
                          "source_kind": "directory" if source.is_dir() else "file",
                          "payload": f"payload/{label}", "directories": directories, "files": records})
        self.manifest = {"schema": backup_tool.SCHEMA, "roots": roots}
        self.seal()
        self.target = self.root / "mpv"

    def seal(self):
        manifest = self.backup / "manifest.json"
        manifest.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        archive = self.backup / "mpv-config.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
            zipped.write(manifest, "manifest.json")
            for root in self.manifest["roots"]:
                for directory in root["directories"]:
                    zipped.writestr(f'{root["payload"]}/{directory}/', b"")
                for entry in root["files"]:
                    name = f'{root["payload"]}/{entry["path"]}'
                    zipped.write(self.backup / name, name)
        receipt = {"status": "PASS", "manifest_sha256": backup_tool.sha256(manifest),
                   "archive_sha256": backup_tool.sha256(archive),
                   "files": sum(len(r["files"]) for r in self.manifest["roots"]),
                   "payload_bytes": sum(f["bytes"] for r in self.manifest["roots"] for f in r["files"])}
        (self.backup / "verification.json").write_text(json.dumps(receipt), encoding="utf-8")

    def reseal_manifest_only(self):
        path = self.backup / "manifest.json"
        path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        receipt_path = self.backup / "verification.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["manifest_sha256"] = backup_tool.sha256(path)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def existing_target(self):
        self.target.mkdir()
        (self.target / "old.conf").write_bytes(b"existing state")
        (self.target / "extra.lua").write_bytes(b"must be retained")
        return backup_tool.inventory(self.target)

    def test_verify_and_source_comparison(self):
        _, report = backup_tool.verify_backup(self.backup, compare_source=True)
        self.assertEqual(report["files"], 4)
        self.assertTrue(report["source_unchanged"])

    def test_payload_tamper_rejected(self):
        (self.backup / "payload/mpv-config/mpv.conf").write_bytes(b"tampered")
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_missing_payload_file_rejected(self):
        (self.backup / "payload/mpv-config/mpv.conf").unlink()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_extra_payload_file_rejected(self):
        (self.backup / "payload/mpv-config/extra.txt").write_bytes(b"unlisted")
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_empty_directory_preserved_and_verified(self):
        (self.backup / "payload/mpv-config/空目录").rmdir()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_manifest_tamper_rejected(self):
        with (self.backup / "manifest.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_archive_tamper_rejected(self):
        with (self.backup / "mpv-config.zip").open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_archive_extra_entry_rejected(self):
        archive = self.backup / "mpv-config.zip"
        with zipfile.ZipFile(archive, "a") as zipped:
            zipped.writestr("../unsafe", b"never extracted")
        receipt_path = self.backup / "verification.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["archive_sha256"] = backup_tool.sha256(archive)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_manifest_path_traversal_rejected(self):
        self.manifest["roots"][0]["files"][0]["path"] = "../outside.conf"
        self.reseal_manifest_only()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_case_colliding_paths_rejected(self):
        entry = copy.deepcopy(self.manifest["roots"][0]["files"][0])
        entry["path"] = entry["path"].upper()
        self.manifest["roots"][0]["files"].append(entry)
        self.reseal_manifest_only()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_duplicate_root_rejected(self):
        self.manifest["roots"].append(copy.deepcopy(self.manifest["roots"][0]))
        self.reseal_manifest_only()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_payload_escape_rejected(self):
        self.manifest["roots"][0]["payload"] = "../source/mpv"
        self.reseal_manifest_only()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup)

    def test_changed_source_detected_only_on_request(self):
        (self.source / "new.conf").write_bytes(b"later change")
        backup_tool.verify_backup(self.backup)
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.verify_backup(self.backup, compare_source=True)

    def test_dry_run_does_not_change_target(self):
        before = self.existing_target()
        result = backup_tool.restore_config(self.backup, self.target)
        self.assertEqual(result["action"], "DRY_RUN")
        self.assertEqual(backup_tool.inventory(self.target), before)
        self.assertFalse(list(self.root.glob(".mpv-restore-stage-*")))

    def test_apply_requires_explicit_confirmation(self):
        before = self.existing_target()
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.restore_config(self.backup, self.target, apply=True)
        self.assertEqual(backup_tool.inventory(self.target), before)

    def test_apply_restores_bytes_and_preserves_previous_state(self):
        before = self.existing_target()
        result = backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(Path(result["previous_config_preserved"])), before)
        backup_tool.check_tree(self.target, self.manifest["roots"][0])
        self.assertFalse(result["launcher_restored"])
        self.assertEqual(self.launcher.read_bytes(), b"@echo off\r\n")

    def test_apply_to_absent_target(self):
        result = backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertIsNone(result["previous_config_preserved"])
        backup_tool.check_tree(self.target, self.manifest["roots"][0])

    def test_target_inside_backup_rejected(self):
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.restore_config(self.backup, self.backup / "mpv")

    def test_target_inside_project_rejected(self):
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.restore_config(self.backup, backup_tool.PROJECT / "mpv")

    def test_wrong_target_name_rejected(self):
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.restore_config(self.backup, self.root / "wrong-name")

    def test_missing_target_parent_rejected(self):
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.restore_config(self.backup, self.root / "missing" / "mpv")

    def test_copy_failure_leaves_original_untouched(self):
        before = self.existing_target()
        with mock.patch.object(backup_tool.shutil, "copy2", side_effect=OSError("simulated copy failure")):
            with self.assertRaises(OSError):
                backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)

    def test_stage_rename_failure_rolls_back_previous_directory(self):
        before = self.existing_target()
        original = Path.rename
        def fail_stage(path, destination):
            if path.name.startswith(".mpv-restore-stage-"):
                raise OSError("simulated stage rename failure")
            return original(path, destination)
        with mock.patch.object(Path, "rename", new=fail_stage):
            with self.assertRaises(OSError):
                backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)

    def test_post_install_failure_rolls_back_and_preserves_diagnostics(self):
        before = self.existing_target()
        original = backup_tool.check_tree
        def fail_installed(path, root):
            if path == self.target:
                raise backup_tool.BackupError("simulated final verification failure")
            return original(path, root)
        with mock.patch.object(backup_tool, "check_tree", side_effect=fail_installed):
            with self.assertRaises(backup_tool.BackupError):
                backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)
        self.assertEqual(len(list(self.root.glob("mpv.failed-restore-*"))), 1)

    def test_non_appdata_restore_warns_about_process_check(self):
        result = backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(result["player_closed_check"], "NOT_CHECKED_NON_APPDATA")
        self.assertTrue(result["warnings"])

    def test_player_installation_is_not_valid_configuration_target(self):
        self.existing_target()
        (self.target / "mpv.exe").write_bytes(b"synthetic non-executable marker")
        before = backup_tool.inventory(self.target)
        with self.assertRaises(backup_tool.BackupError):
            backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)

    @unittest.skipUnless(backup_tool.os.name == "nt", "Windows process guard")
    def test_running_live_player_guard_rejects_without_mutation(self):
        before = self.existing_target()
        result = backup_tool.subprocess.CompletedProcess(["tasklist"], 0, stdout='"mpv.exe","123","Console","1","10 K"')
        with mock.patch.dict(backup_tool.os.environ, {"APPDATA": str(self.root)}):
            with mock.patch.object(backup_tool.subprocess, "run", return_value=result):
                with self.assertRaises(backup_tool.BackupError):
                    backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)
        self.assertFalse(list(self.root.glob(".mpv-restore-stage-*")))

    @unittest.skipUnless(backup_tool.os.name == "nt", "Windows process guard")
    def test_tasklist_failure_refuses_restore_without_mutation(self):
        before = self.existing_target()
        with mock.patch.dict(backup_tool.os.environ, {"APPDATA": str(self.root)}):
            with mock.patch.object(backup_tool.subprocess, "run", side_effect=OSError("mock tasklist failure")):
                with self.assertRaises(OSError):
                    backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)

    @unittest.skipUnless(backup_tool.os.name == "nt", "Windows process guard")
    def test_closed_live_player_guard_returns_checked_status(self):
        self.existing_target()
        result = backup_tool.subprocess.CompletedProcess(["tasklist"], 0, stdout="INFO: No matching tasks")
        with mock.patch.dict(backup_tool.os.environ, {"APPDATA": str(self.root)}):
            with mock.patch.object(backup_tool.subprocess, "run", return_value=result):
                report = backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(report["player_closed_check"], "APPDATA_CHECK_PASSED")
        self.assertEqual(report["warnings"], [])

    def test_secondary_rollback_failure_preserves_state_and_diagnostics(self):
        before = self.existing_target()
        original_check = backup_tool.check_tree
        original_rename = Path.rename
        def fail_final_check(path, root):
            if path == self.target:
                raise backup_tool.BackupError("simulated final verification failure")
            return original_check(path, root)
        def fail_preserve_rename(path, destination):
            if path == self.target and destination.name.startswith("mpv.failed-restore-"):
                raise OSError("simulated preserve rename failure")
            return original_rename(path, destination)
        with mock.patch.object(backup_tool, "check_tree", side_effect=fail_final_check):
            with mock.patch.object(Path, "rename", new=fail_preserve_rename):
                with self.assertRaises(backup_tool.BackupError) as caught:
                    backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertIn("simulated final verification failure", str(caught.exception))
        self.assertIn("simulated preserve rename failure", str(caught.exception))
        preserved = list(self.root.glob("mpv.before-restore-*"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(backup_tool.inventory(preserved[0]), before)
        backup_tool.check_tree(self.target, self.manifest["roots"][0])

    def test_rehearsal_is_not_live_restore(self):
        result = backup_tool.rehearse(self.backup)
        self.assertEqual(result["action"], "REHEARSAL_ONLY")
        self.assertFalse(result["live_config_restored"])
        backup_tool.verify_backup(self.backup, compare_source=True)

    def test_link_guard_rejects_before_mutation(self):
        before = self.existing_target()
        with mock.patch.object(backup_tool, "no_links", side_effect=backup_tool.BackupError("simulated reparse point")):
            with self.assertRaises(backup_tool.BackupError):
                backup_tool.restore_config(self.backup, self.target, apply=True, confirm=backup_tool.CONFIRM)
        self.assertEqual(backup_tool.inventory(self.target), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
