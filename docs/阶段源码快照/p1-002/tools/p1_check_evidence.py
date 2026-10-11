"""p1_check_evidence.py — evidence-integrity machine gate (限域修正 C / R3+F-02).

Verifies one P1 session's frozen evidence chain:

  1. evidence-manifest.json (one or more, one per evidence subdir):
     schema/session valid; every bound path is a canonical repo-relative POSIX
     path inside docs/验证/开发/<session>/ (no traversal, absolute/backslash/
     drive paths, links/reparse points, private top dirs, out-of-repo paths);
     every file exists and matches its SHA-256 (detects modified files and
     forged checksums).
  2. tests.json (if present): every case's evidence_files/evidence reference
     is canonical, in-session, present on disk AND covered by the manifest
     with a matching hash (detects manifest omissions and dangling refs).
     If tests.json records an evidence_manifest binding {path, sha256}, the
     manifest bytes must match (detects silent manifest swaps).
  3. candidate.json (if present): schema/stage/session identity; tests_sha256
     pins tests.json bytes; every fingerprinted source file matches disk.

Deliberately NOT provided: OS sandbox or cross-process transaction guarantees.
A same-user process able to rewrite the repo can rewrite files AND manifests;
the pinning chain candidate→tests→manifest exists to make silent drift and
omission machine-detectable, complementing (never replacing) taskflows/guard.py.

Usage:
    python -X utf8 tools/p1_check_evidence.py \
        --session-dir docs/验证/开发/p1-002 \
        --manifest docs/验证/开发/p1-002/implementer/evidence-manifest.json \
        [--manifest docs/验证/开发/p1-002/verify-lead/evidence-manifest.json] \
        [--tests docs/验证/开发/p1-002/tests.json] \
        [--candidate docs/验证/开发/p1-002/candidate.json] \
        [--require-tests]
Exit code 0 = all checks pass; 1 = problems found (printed as JSON).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1_lib as lib  # noqa: E402

CANDIDATE_SCHEMA = "mpv-scaler-stage/v1"
DEFAULT_REQUIRED_P1 = ["CTL-01", "CTL-02", "CTL-03", "CTL-04", "CTL-05",
                       "CTL-06", "CTL-07", "CTL-08", "GEO-01", "GEO-07",
                       "SHD-12", "PIC-05"]


def load_json_lf(path: Path):
    """Parse UTF-8/LF JSON; reject CRLF (preserves the Git fingerprint)."""
    data = path.read_bytes()
    if b"\r" in data:
        raise ValueError(f"JSON 必须为 UTF-8/LF（发现 CRLF）: {path}")
    return json.loads(data.decode("utf-8")), data


def _load_json_problem(path: Path):
    """load_json_lf with errors folded into a (obj, data, problem) triple."""
    try:
        obj, data = load_json_lf(path)
        return obj, data, None
    except (ValueError, json.JSONDecodeError) as e:
        return None, None, f"JSON 解析失败: {path}: {e}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_source_path(name: str, repo_root: Path) -> Path:
    """Candidate source paths: canonical project-relative POSIX regular files
    below the repo, outside private/runtime dirs (mirrors taskflows/guard)."""
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError(f"候选源码路径必须是规范仓库相对 POSIX 路径: {name!r}")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts \
            or relative.as_posix() != name or name == ".":
        raise ValueError(f"不安全的候选路径: {name!r}")
    if relative.parts[0] in (".git", ".pi", ".local", "backups"):
        raise ValueError(f"私有/运行时目录不可作为候选源码: {name!r}")
    path = repo_root / name
    for item in [path, *path.parents]:
        if item.exists() or item.is_symlink():
            if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError(f"候选路径包含链接/reparse点: {name}")
    resolved = path.resolve()
    if repo_root.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError(f"候选必须是仓库内常规文件: {name}")
    return path


def check_tests_binding(tests: dict, manifest_files: dict, session: str,
                        repo_root: Path) -> list:
    problems: list = []
    if tests.get("session") != session:
        problems.append(f"tests.json session 不符: {tests.get('session')!r} ≠ {session!r}")
    cases = tests.get("cases")
    if not isinstance(cases, list) or not cases:
        return problems + ["tests.json 缺少 cases"], set()
    referenced: set = set()
    for case in cases:
        cid = case.get("id", "?")
        refs = list(case.get("evidence_files") or [])
        if case.get("evidence"):
            refs.append(case["evidence"])
        if not refs:
            problems.append(f"case {cid}: 无任何证据引用")
        for rel in refs:
            try:
                lib.safe_manifest_relpath(rel, session, repo_root)
            except ValueError as e:
                problems.append(f"case {cid}: {e}")
                continue
            referenced.add(rel)
            if rel not in manifest_files:
                problems.append(f"case {cid}: 证据清单缺少条目: {rel}")
                continue
            digest = manifest_files[rel]
            path = repo_root / rel
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                problems.append(f"case {cid}: 伪造/非法 SHA-256: {rel}")
                continue
            if not path.exists():
                problems.append(f"case {cid}: 引用文件缺失: {rel}")
                continue
            if lib.sha256_file(path) != digest:
                problems.append(f"case {cid}: 文件被改动（与清单不符）: {rel}")
    return problems, referenced


def check_manifest_binding_field(tests: dict, manifests: list, session: str,
                                 repo_root: Path) -> list:
    problems: list = []
    binding = tests.get("evidence_manifest")
    if binding is None:
        problems.append("tests.json 未记录 evidence_manifest 绑定（{path, sha256}）")
        return problems
    bindings = binding if isinstance(binding, list) else [binding]
    expected_rel = f"{lib.SESSIONS_ROOT}/{session}"
    for b in bindings:
        if not isinstance(b, dict) or "path" not in b or "sha256" not in b:
            problems.append(f"evidence_manifest 绑定字段不完整: {b!r}")
            continue
        rel, sha = b["path"], b["sha256"]
        try:
            path = lib.safe_manifest_relpath(rel, session, repo_root)
        except ValueError as e:
            problems.append(f"evidence_manifest 绑定路径非法: {e}")
            continue
        if not rel.startswith(expected_rel + "/"):
            problems.append(f"evidence_manifest 绑定路径不在会话树内: {rel}")
            continue
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            problems.append(f"evidence_manifest sha256 非法: {rel}")
            continue
        if not path.exists():
            problems.append(f"evidence_manifest 绑定的清单文件缺失: {rel}")
            continue
        if lib.sha256_file(path) != sha:
            problems.append(f"evidence_manifest 清单被改动（与 tests.json 绑定不符）: {rel}")
            continue
        bound_names = {str(m.get("path")) for m in manifests}
        if rel not in bound_names:
            problems.append(f"evidence_manifest 绑定的清单未被 --manifest 提供: {rel}")
    return problems


def check_candidate(candidate: dict, tests_data: bytes, tests: dict,
                    stage: str, session: str, repo_root: Path) -> list:
    problems: list = []
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        problems.append(f"candidate schema 不符: {candidate.get('schema')!r}")
    if candidate.get("stage") != stage or candidate.get("session") != session:
        problems.append(
            f"candidate 身份不符: stage={candidate.get('stage')!r} "
            f"session={candidate.get('session')!r}")
    if sha256_bytes(tests_data) != candidate.get("tests_sha256"):
        problems.append("candidate tests_sha256 与 tests.json 实际哈希不符")
    files = candidate.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("candidate 缺少 files 指纹")
        return problems
    folded = set()
    for name, checksum in files.items():
        if name.casefold() in folded:
            problems.append(f"candidate 存在大小写冲突路径: {name}")
            continue
        folded.add(name.casefold())
        try:
            path = check_source_path(name, repo_root)
        except ValueError as e:
            problems.append(str(e))
            continue
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            problems.append(f"伪造/非法 SHA-256: {name}")
            continue
        if lib.sha256_file(path) != checksum:
            problems.append(f"候选源码已被改动: {name}")
    if tests.get("stage") != stage:
        problems.append("tests.json stage 与 candidate 不符")
    return problems


def run_checks(session_dir: Path, session: str, stage: str,
               manifest_paths: list, tests_path: Path | None,
               candidate_path: Path | None, require_tests: bool,
               repo_root: Path) -> list:
    problems: list = []
    manifests = []
    manifest_files: dict = {}
    for mp in manifest_paths:
        if not mp.is_file():
            problems.append(f"证据清单缺失: {mp}")
            continue
        manifest, _, parse_problem = _load_json_problem(mp)
        if parse_problem:
            problems.append(parse_problem)
            continue
        problems.extend(lib.verify_evidence_manifest(manifest, session, repo_root))
        try:
            mp_rel = mp.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            problems.append(f"清单路径不在仓库内: {mp}")
            continue
        manifests.append({"path": mp_rel, "data": manifest})
        for rel, digest in (manifest.get("files") or {}).items():
            if rel in manifest_files and manifest_files[rel] != digest:
                problems.append(f"多份清单对同一文件给出不同哈希: {rel}")
            manifest_files[rel] = digest

    tests, tests_data = None, None
    if tests_path is not None:
        if not tests_path.is_file():
            if require_tests:
                problems.append(f"--require-tests 已指定但 tests.json 缺失: {tests_path}")
        else:
            tests, tests_data, parse_problem = _load_json_problem(tests_path)
            if parse_problem:
                problems.append(parse_problem)
                tests = None
            else:
                t_problems, _referenced = check_tests_binding(
                    tests, manifest_files, session, repo_root)
                problems.extend(t_problems)
                problems.extend(check_manifest_binding_field(
                    tests, manifests, session, repo_root))
                if require_tests:
                    case_ids = [c.get("id") for c in (tests.get("cases") or [])]
                    required = DEFAULT_REQUIRED_P1 if stage == "P1" else []
                    for rid in required:
                        if rid not in case_ids:
                            problems.append(f"必需测试缺少报告条目: {rid}")
                    if tests.get("required_unmeasured") not in ([], None):
                        if tests.get("required_unmeasured") != []:
                            problems.append("required_unmeasured 非空: "
                                            f"{tests.get('required_unmeasured')!r}")

    if candidate_path is not None:
        if not candidate_path.is_file():
            problems.append(f"candidate 缺失: {candidate_path}")
        elif tests is None or tests_data is None:
            problems.append("校验 candidate 需要 tests.json 同时存在且可解析")
        else:
            candidate, _, parse_problem = _load_json_problem(candidate_path)
            if parse_problem:
                problems.append(parse_problem)
            else:
                problems.extend(check_candidate(
                    candidate, tests_data, tests, stage, session, repo_root))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir",
                        default=None,
                        help="session evidence root (default: docs/验证/开发/<session>)")
    parser.add_argument("--session", default=None,
                        help="session id (default: basename of --session-dir)")
    parser.add_argument("--stage", default="P1")
    parser.add_argument("--manifest", action="append", default=None,
                        help="evidence-manifest.json path (repeatable; default "
                             "<session-dir>/evidence-manifest.json)")
    parser.add_argument("--tests", default=None,
                        help="tests.json path (default <session-dir>/tests.json; "
                             "skipped when absent unless --require-tests)")
    parser.add_argument("--candidate", default=None,
                        help="candidate.json path (default <session-dir>/candidate.json; "
                             "checked only when present)")
    parser.add_argument("--require-tests", action="store_true",
                        help="fail if tests.json is missing or does not cover "
                             "all required test ids")
    args = parser.parse_args()

    session = args.session or (Path(args.session_dir).name if args.session_dir else None)
    if not session or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", session):
        parser.error("cannot derive a valid --session (lowercase/digits/hyphens)")
    session_dir = Path(args.session_dir) if args.session_dir \
        else lib.REPO_ROOT / lib.SESSIONS_ROOT / session
    try:
        session_dir_rel = session_dir.resolve().relative_to(lib.REPO_ROOT).as_posix()
    except ValueError:
        parser.error(f"--session-dir must live inside the repo; got {session_dir}")
    expected_root = f"{lib.SESSIONS_ROOT}/{session}"
    if session_dir_rel != expected_root and not session_dir_rel.startswith(expected_root + "/"):
        parser.error(f"--session-dir must be inside {expected_root}/; got {session_dir_rel}")

    manifest_paths = [Path(p) for p in args.manifest] if args.manifest \
        else [session_dir / "evidence-manifest.json"]
    tests_path = Path(args.tests) if args.tests else session_dir / "tests.json"
    candidate_path = Path(args.candidate) if args.candidate else session_dir / "candidate.json"
    if not args.candidate and not candidate_path.is_file():
        candidate_path = None  # candidate is a later (lead) stage artifact; optional here

    problems = run_checks(session_dir, session, args.stage, manifest_paths,
                          tests_path, candidate_path, args.require_tests,
                          lib.REPO_ROOT)
    verdict = {"status": "PASS" if not problems else "FAIL",
               "session": session,
               "session_dir": session_dir_rel,
               "manifests": [str(p) for p in manifest_paths],
               "problems": problems}
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
