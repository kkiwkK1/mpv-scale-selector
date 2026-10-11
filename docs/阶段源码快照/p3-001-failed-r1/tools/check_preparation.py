"""Preparation-only checks. No mpv playback or live configuration restore."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCOPE = [
    ".gitignore", ".gitattributes", "README.md",
    "docs/实施计划.md", "docs/测试计划.md", "docs/备份与恢复.md", "docs/备份记录.json",
    "tools/mpv_config_backup.py", "tools/check_preparation.py", "tests/test_mpv_config_backup.py",
]


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(PROJECT), *args], stderr=subprocess.STDOUT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]+", args.attempt):
        parser.error("attempt must be v followed by digits")
    output = PROJECT / "docs/验证"
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Preparation only; no shader runtime, playback, quality or performance acceptance",
              "attempt": args.attempt, "python_version": sys.version.split()[0],
              "checks": {}, "status": "FAIL"}
    try:
        before = {path: fingerprint(PROJECT / path) for path in SCOPE}
        spec = importlib.util.spec_from_file_location("backup_tool", PROJECT / "tools/mpv_config_backup.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        record = json.loads((PROJECT / "docs/备份记录.json").read_text(encoding="utf-8"))
        backup = Path(record["backup_directory"])
        manifest, verification = tool.verify_backup(backup, compare_source=True)
        assert verification["manifest_sha256"] == record["manifest_sha256"]
        assert verification["archive_sha256"] == record["archive_sha256"]
        assert verification["files"] == record["files_total"]
        assert verification["bytes"] == record["payload_bytes"]
        report["checks"]["backup"] = verification
        rehearsal = tool.rehearse(backup)
        assert rehearsal["restore_files"] == record["config_files"]
        assert rehearsal["live_config_restored"] is False
        report["checks"]["rehearsal"] = rehearsal

        stream = io.StringIO()
        suite = unittest.defaultTestLoader.discover(str(PROJECT / "tests"), pattern="test_*.py")
        started = time.monotonic()
        results = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        report["checks"]["unit_tests"] = {"total": results.testsRun, "failed": len(results.failures),
                                           "errors": len(results.errors), "skipped": len(results.skipped),
                                           "duration_s": round(time.monotonic() - started, 3),
                                           "status": "PASS" if results.wasSuccessful() else "FAIL"}
        (output / f"准备单元测试-{args.attempt}.txt").write_text(stream.getvalue(), encoding="utf-8")
        if not results.wasSuccessful():
            raise RuntimeError("Preparation unit tests failed")

        plan = (PROJECT / "docs/实施计划.md").read_text(encoding="utf-8")
        tests = (PROJECT / "docs/测试计划.md").read_text(encoding="utf-8")
        for name in ["FSR", "NIS", "SGSR", "Anime4K", "LS1", "BCAS", "Integer", "xBR", "Sharp Bilinear", "Nearest"]:
            if name not in plan:
                raise RuntimeError(f"Algorithm missing from implementation plan: {name}")
        for milestone in ["P0", "P1", "P2", "P3", "P4", "P5"]:
            if milestone not in plan:
                raise RuntimeError(f"Missing milestone: {milestone}")
        for group in ["BAK-", "CTL-", "SHD-", "GEO-", "PIC-", "PER-", "INS-"]:
            if group not in tests:
                raise RuntimeError(f"Missing test group: {group}")
        for document in ["README.md", "docs/实施计划.md", "docs/测试计划.md", "docs/备份与恢复.md"]:
            content = (PROJECT / document).read_text(encoding="utf-8")
            for url in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
                if "://" in url or url.startswith("#") or url.startswith("mailto:"):
                    continue
                destination = (PROJECT / document).parent / url.split("#", 1)[0]
                if not destination.exists():
                    raise RuntimeError(f"Broken local link in {document}: {url}")
        report["checks"]["document_structure_and_links"] = "PASS"

        research = json.loads((PROJECT / "docs/交叉审查/候选快照-v1.json").read_text(encoding="utf-8"))
        for filename, digest in research["files"].items():
            relative = Path(filename).as_posix()
            if fingerprint(PROJECT / filename) != digest:
                raise RuntimeError(f"Prior reviewed research changed: {filename}")
            if hashlib.sha256(git("show", "HEAD:" + relative)).hexdigest() != digest:
                raise RuntimeError(f"Git normalized a reviewed evidence file: {filename}")
        report["checks"]["prior_research_worktree_and_git_hashes"] = "PASS"
        tracked = git("ls-files", "-z").decode("utf-8").split("\0")
        if any(name.startswith((".pi/", "backups/", ".local/")) for name in tracked):
            raise RuntimeError("Private data tracked by Git")
        ignored = subprocess.run(["git", "-C", str(PROJECT), "check-ignore", "--", ".pi/private-probe", "backups/private-probe"],
                                 capture_output=True, check=False)
        if ignored.returncode != 0 or len(ignored.stdout.splitlines()) != 2:
            raise RuntimeError("Private backup/session ignore rules missing")
        git("fsck", "--no-dangling")
        report["checks"]["git_integrity_and_privacy_rules"] = "PASS"
        tool.verify_backup(backup, compare_source=True)
        after = {path: fingerprint(PROJECT / path) for path in SCOPE}
        if after != before:
            raise RuntimeError("Preparation candidate changed during checks")
        report["checks"]["source_configuration_unchanged_after_tests"] = "PASS"
        report["checks"]["candidate_unchanged_during_tests"] = "PASS"
        report["status"] = "PASS"
        candidate = {"candidate": f"preparation-{args.attempt}", "baseline_commit": git("rev-parse", "HEAD").decode().strip(),
                     "files": after, "backup_manifest_sha256": record["manifest_sha256"],
                     "model_request": "zai-coding-cn/glm-5.3-flash", "thinking_request": "xhigh",
                     "acceptance_scope": report["scope"]}
        candidate_path = output / f"准备候选-{args.attempt}.json"
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
        report["candidate"] = candidate["candidate"]
        report["candidate_sha256"] = fingerprint(candidate_path)
        report["candidate_snapshot"] = candidate_path.relative_to(PROJECT).as_posix()
    except Exception as error:
        report["error"] = str(error)
    (output / f"准备检查-{args.attempt}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
