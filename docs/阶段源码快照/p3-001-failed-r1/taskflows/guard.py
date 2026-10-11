"""Machine guards for mpv-scale-dev; not an OS sandbox or live installer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
STAGES = ["P1", "P2", "P3", "P4", "P5"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slug(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value):
        raise ValueError("session/previous must be 1-64 lowercase letters, digits or hyphens")
    return value


def folder(session):
    path = PROJECT / "docs/验证/开发" / slug(session)
    for item in [path, *path.parents]:
        if item.exists() or item.is_symlink():
            if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Artifact paths must not contain links/reparse points")
    if PROJECT.resolve() not in path.resolve().parents:
        raise ValueError("Artifact path escaped project")
    return path


def source_path(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Source path must be a canonical project-relative POSIX path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name or name == ".":
        raise ValueError("Unsafe source path")
    if relative.parts[0] in (".git", ".pi", ".local", "backups"):
        raise ValueError("Private/runtime directory is not an admissible source")
    path = PROJECT / name
    for item in [path, *path.parents]:
        if item.exists() or item.is_symlink():
            if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Links/reparse paths are not admissible")
    resolved = path.resolve()
    if PROJECT.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError("Source must be a regular file below this project")
    return path


def approve(value):
    if value.strip() != "(approve)":
        raise ValueError("Explicit interactive Approve required; Reject/Edit/headless output is not permission")


def load_json(path):
    data = path.read_bytes()
    if b"\r" in data:
        raise ValueError("New stage JSON must be UTF-8/LF to preserve its Git fingerprint")
    return json.loads(data.decode("utf-8"))


def verify_files(files):
    if not isinstance(files, dict) or not files:
        raise ValueError("Candidate must fingerprint all relevant source/test/asset files")
    folded = set()
    for name, checksum in files.items():
        if name.casefold() in folded or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Duplicate/case-colliding source or invalid SHA-256")
        folded.add(name.casefold())
        if sha(source_path(name)) != checksum:
            raise ValueError(f"Candidate source changed: {name}")


def candidate(stage, session):
    directory = folder(session)
    path = directory / "candidate.json"
    snapshot = load_json(path)
    if snapshot.get("schema") != "mpv-scaler-stage/v1" or snapshot.get("stage") != stage or snapshot.get("session") != session:
        raise ValueError("Candidate identity/schema mismatch")
    verify_files(snapshot["files"])
    tests_path = directory / "tests.json"
    if sha(tests_path) != snapshot.get("tests_sha256"):
        raise ValueError("Test evidence changed after candidate freeze")
    tests = load_json(tests_path)
    if tests.get("stage") != stage or tests.get("session") != session or tests.get("status") != "PASS":
        raise ValueError("No passing objective test report for this stage")
    if tests.get("required_unmeasured") != []:
        raise ValueError("Required objective tests are missing/unmeasured")
    if tests.get("live_configuration_written") is not False:
        raise ValueError("This development flow does not authorize live configuration writes")
    cases = tests.get("cases")
    if not isinstance(cases, list) or not cases or any(not item.get("id") for item in cases):
        raise ValueError("Stage-specific test cases and evidence are required")
    if len({item["id"] for item in cases}) != len(cases):
        raise ValueError("One report entry per test ID is required; put input variants inside that entry")
    return snapshot, tests, sha(path)


def verified_backup():
    record = json.loads((PROJECT / "docs/备份记录.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("backup_tool", PROJECT / "tools/mpv_config_backup.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    _, backup = tool.verify_backup(Path(record["backup_directory"]), compare_source=True)
    if backup["manifest_sha256"] != record["manifest_sha256"] or backup["archive_sha256"] != record["archive_sha256"]:
        raise ValueError("Backup fingerprints differ from pinned receipt")
    return backup


def preflight(stage, session, previous):
    slug(session)
    if folder(session).exists():
        raise ValueError("Session already exists; select a new ID, never overwrite reviewed evidence")
    dependency = None
    if stage != "P1":
        prior = load_json(folder(previous) / "acceptance.json")
        expected_stage = STAGES[STAGES.index(stage) - 1]
        if prior.get("stage") != expected_stage or prior.get("status") != "ACCEPTED" or prior.get("user_approved") is not True:
            raise ValueError(f"An accepted {expected_stage} checkpoint is required")
        _, _, checksum = candidate(expected_stage, previous)
        if checksum != prior.get("candidate_sha256"):
            raise ValueError("Prerequisite checkpoint no longer matches its candidate")
        dependency = {"session": previous, "stage": expected_stage, "candidate_sha256": checksum}
    backup = verified_backup()
    head = subprocess.check_output(["git", "-C", str(PROJECT), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(PROJECT), "status", "--porcelain"], encoding="utf-8")
    return {"status": "PASS", "stage": stage, "session": session, "baseline_commit": head,
            "prior_dirty_changes": dirty.splitlines(), "dependency": dependency,
            "backup": backup, "live_deployment_allowed": False}


def accept(stage, session, payload):
    approve(payload["approval"])
    snapshot, tests, checksum = candidate(stage, session)
    for name in ["technical", "safety"]:
        review = payload[name]
        if review.get("verdict") != "pass" or review.get("candidate_sha256") != checksum:
            raise ValueError(f"{name} review does not approve this exact candidate")
        if any(item.get("severity") in ["blocker", "major"] for item in review.get("findings", [])):
            raise ValueError("Blocking findings remain")
    backup = verified_backup()
    result = {"status": "ACCEPTED", "stage": stage, "session": session, "user_approved": True,
              "backup_and_source_unchanged": backup,
              "candidate_sha256": checksum, "scope": "deployment-readiness" if stage == "P5" else "isolated-stage-validation",
              "pending_user_checks_confirmed_by_approval": tests.get("pending_user_checks", []),
              "live_deployment_completed": False, "files": snapshot["files"], "reviews": payload}
    with (folder(session) / "acceptance.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "approval", "check", "accept", "finish"])
    parser.add_argument("--stage", choices=STAGES, default="P1")
    parser.add_argument("--session", default="p1-001")
    parser.add_argument("--previous", default="")
    parser.add_argument("--approval", default="")
    args = parser.parse_args()
    try:
        if args.action == "preflight":
            result = preflight(args.stage, args.session, args.previous)
        elif args.action == "approval":
            approve(sys.stdin.read())
            result = {"status": "PASS", "permission": "isolated_work_only", "live_deployment_allowed": False}
        elif args.action == "check":
            _, tests, checksum = candidate(args.stage, args.session)
            plan = json.load(sys.stdin)
            required = plan.get("required_tests")
            if plan.get("stage") != args.stage or not isinstance(required, list) or not required:
                raise ValueError("Stage plan must declare its required test IDs")
            cases = {item["id"]: item for item in tests["cases"]}
            pending = tests.get("pending_user_checks", [])
            for identifier in required:
                if identifier not in cases or cases[identifier].get("status") not in ["PASS", "PENDING_USER"]:
                    raise ValueError(f"Required test has no passing/pending-human evidence: {identifier}")
                if cases[identifier]["status"] == "PENDING_USER" and identifier not in pending:
                    raise ValueError("Pending test must be explicitly presented to the human approval gate")
            result = {"status": "PASS", "candidate_sha256": checksum, "tests": tests}
        elif args.action == "accept":
            payload = json.load(sys.stdin)
            payload["approval"] = args.approval  # argv, never interpolated inside JSON text
            result = accept(args.stage, args.session, payload)
        else:
            _, _, checksum = candidate(args.stage, args.session)
            result = load_json(folder(args.session) / "acceptance.json")
            if result.get("candidate_sha256") != checksum or result.get("status") != "ACCEPTED":
                raise ValueError("Final candidate no longer matches acceptance")
            backup = verified_backup()
            result = {"status": "ACCEPTED", "stage": args.stage, "session": args.session,
                      "candidate_sha256": checksum, "scope": result["scope"],
                      "backup_and_source_unchanged": backup,
                      "live_deployment_completed": False,
                      "record": str((folder(args.session) / "acceptance.json").relative_to(PROJECT))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
