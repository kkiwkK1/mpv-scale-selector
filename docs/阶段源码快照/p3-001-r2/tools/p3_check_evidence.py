# -*- coding: utf-8 -*-
"""p3_check_evidence.py — P3 (p3-001) EVI-01 full-tree evidence machine gate.

Independently re-verifies ONE P3 evidence directory produced by the case
harness (``tools/p3_verify.py`` per
docs/验证/开发/p3-001/verifier-build/evidence-tools-contract.json) — the
downstream integration lead re-runs the SAME checker frozen against its own
rerun.  This module is a checker ONLY: it adds no product feature and never
fabricates a PASS; any real problem exits non-zero.

Machine schema facts (verified against tools/p1_lib.py — do NOT guess):
  * lib.build_evidence_manifest keys are CANONICAL **repo-relative** POSIX
    paths under ``docs/验证/开发/<session>/…`` (NOT evidence-dir-relative —
    comparing evidence-relative names against them would flag every file as
    漏项).  This gate projects repo-relative keys onto the evidence dir and
    additionally rejects any key bound OUTSIDE this evidence dir (全目录
    coverage could not be honest otherwise).
  * Every bound path re-validates through lib.safe_manifest_relpath:
    canonical, in-session, no symlink/reparse point, no private top dir,
    inside the repo — and is re-hashed (tamper/forgery detection).

Checks (all machine-checked, never doc-word checks):

  1. manifest integrity — schema/session; every bound path canonical,
     in-session, on disk, SHA-256 matching (p1_lib.verify_evidence_manifest).
  2. FULL-DIRECTORY coverage — every file under the evidence dir must be
     bound in the manifest, EXCEPT a small CLOSED exclusion class written
     after the manifest and/or embedding its hash (circular self-reference):
       evidence-manifest.json (the manifest itself),
       manifest-verify.json    (pins manifest+runner hashes → circular),
       evidence-gate.json      (pins manifest-verify hash → circular),
       runner.console.txt      (runner's own progress console).
     The class is CLOSED: the excluded members are still machine-checked via
     the hash chain (runner.console.txt is pinned by manifest-verify.json,
     manifest-verify.json is pinned by evidence-gate.json) — exclusion never
     means "unchecked", and any other on-disk file must be bound (漏项=FAIL).
  3. required-ID coverage — every required test id present and PASS in
     objective-results.json (with --require-tests); no required_unmeasured.
  4. per-case artifact triplets — every case that ran real mpv must declare
     its session names, and each session must have NON-EMPTY
     <session>.console.txt + <session>.mpv.log + <session>.mpv.transcript.jsonl
     bound in the manifest (restart console/log/IPC coverage; P2R-F2 closure).
     Conversely every on-disk <stem>.console.txt must be declared by some
     case (orphaned/dropped-session detection = restart_missing class).
  5. DESC+samples honesty — algorithm presence is only accepted from
     structured DESC-hit fields; P3 cases (SHD-05/06/07) must carry
     desc_evidence{count≥1, sample_hits with non-empty verbatim excerpts}
     and every excerpt is cross-checked as a substring of the case's real
     session console/mpv.log bytes (fabricated samples = FAIL); the legacy
     P2 integer/dict shapes (desc_keyword_pass_hits / required_desc_hits)
     keep their 0==0 rejection for SHD-01/02/04.
  6. same-moment decode+geometry — geometry/PER cases must carry STRUCTURED
     same_moment records matching the p3_lib.same_moment_sample producer
     shape (pixelformat + w/h/dw/dh + osd_w/osd_h + vo-passes frame counts +
     same_window=true in ONE observation window).  Prose claiming
     "same-moment" without the structured record is a FAIL (VL-F1 class).
  7. render-freshness vs decoder-liveness — freshness blocks must win by an
     ALLOWED render method (vo-passes fresh-count increase / forced redraw /
     new output pixels) with fresh_before < fresh_after (0==0 rejected) and
     freshness.chain_epoch == the variant's chain_epoch (陈旧 epoch pairing
     rejected).  A "decoder-only" method can never satisfy an active claim
     (core run-004 lesson; recorded honestly, never counted as render proof).
  8. PNG captures — non-empty, real PNG (decoded with the p3_lib stdlib
     decoder honouring true bit depth), declared w/h equal the decoded IHDR,
     declared sha256 equal disk bytes; every PNG bound in the manifest;
     duplicate-content PNG groups (same SHA-256) must be honestly listed in
     non_corroborative_png (重复图标不具佐证力).
  9. Integer native-bool readback — Integer/geometry cases must record the
     NATIVE video-unscaled readback type (bool), not string "yes"/"no"
     (CORE-R1 class evidence).
 10. SHD-09 bit-depth honesty — 8bit AND 10bit must each be really measured
     (same_moment pixelformat agreeing with the claimed depth, e.g.
     yuv420p10 for 10bit) or explicitly refused with a reason; claiming
     10bit while the decode identity says 8bit is a FAIL.
 11. PER-04-COMPUTE honesty — PASS requires raw positive-integer ns samples
     (≥2) plus a samples_note; no performance-gain claim is implied.
 12. EVI-01 self-negatives — the EVI-01 report must show every canonical
     planted-negative class detected and the positive control clean.

Deliberately NOT provided: OS sandbox / cross-process transaction guarantees
(same discipline as p1_check_evidence.py).  Structural integrity (hashes,
sizes, dup-SHA honesty, epoch pairing) is checked here; pixel-level oracles
remain the per-case CPU replica checks' job.

Usage:
    python -X utf8 tools/p3_check_evidence.py \
        --evidence-dir docs/验证/开发/p3-001/implementer/full-r1 \
        --session p3-001 [--results PATH] [--manifest PATH] [--require-tests]
        [--write-gate]
Exit code 0 = all checks pass; 1 = problems found (printed as JSON).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1_lib as lib  # noqa: E402
import p1_check_evidence as p1chk  # noqa: E402  (P3 REQUIRED ids live there)
import p3_lib  # noqa: E402  (stdlib PNG decoder honouring true bit depth)

# Files written AFTER the manifest or embedding its hash (circular class).
# CLOSED class: the members are hash-chained via manifest-verify.json /
# evidence-gate.json instead; anything else on disk must be inside
# manifest.files.
EXCLUDED_FROM_MANIFEST = frozenset({
    "evidence-manifest.json",
    "manifest-verify.json",
    "evidence-gate.json",
    "runner.console.txt",
})

MANIFEST_VERIFY_SCHEMA = "p3-manifest-verify/v1"
EVIDENCE_GATE_SCHEMA = "p3-evidence-gate/v1"

P3_REQUIRED_IDS = list(p1chk.P3_REQUIRED_IDS)

# Cases that never spawn mpv (no artifact-triplet requirement).
NO_MPV_CASES = {"UNIT-P2-01", "UNIT-P3-01", "EVI-01"}

# Cases whose PASS claims require real shader-pass DESC + samples evidence.
LEGACY_DESC_REQUIRED = {
    "SHD-01": "desc_keyword_pass_hits",   # int > 0 (P2 shape)
    "SHD-02": "desc_keyword_pass_hits",
    "SHD-04": "required_desc_hits",       # dict with any True (stock Anime4K)
}
P3_DESC_CASES = {"SHD-05", "SHD-06", "SHD-07"}

# Cases that must carry structured same-moment records (decode + geometry +
# frame counts in one observation window) — never prose-only.
SAME_MOMENT_CASES = (P3_DESC_CASES
                     | {"GEO-02", "GEO-03", "GEO-04", "GEO-05", "GEO-06",
                        "WINDOW-01", "PER-04-COMPUTE"})

# Cases whose active-effect claims must carry render-freshness evidence
# (decoder activity alone is NOT render proof — core run-004 lesson).
RENDER_FRESH_CASES = SAME_MOMENT_CASES

# Integer-geometry cases must record the native video-unscaled readback type.
INTEGER_NATIVE_BOOL_CASES = {"GEO-02", "GEO-03", "GEO-04", "GEO-05", "GEO-06"}

# Render-freshness methods that constitute REAL new-frame render evidence.
# Anything else (e.g. any "*decoder*" liveness) is not render proof.
RENDER_FRESH_METHODS = frozenset({
    "vo-passes-fresh-increase",   # vo-passes 'fresh' frame counter increased
    "forced-redraw",              # forced redraw counter increased
    "new-output-pixels",          # newly rendered output pixels observed
})

# Canonical EVI-01 planted-negative classes (each must be really exercised
# against this checker in a sandbox and reported detected).
EVI_NEGATIVE_KEYS = frozenset({
    "path_traversal",
    "manifest_omission",
    "wrong_hash",
    "replaced_png",
    "fake_desc_samples",
    "zero_zero_counting",
    "decoder_fake_freshness",
    "stale_epoch",
    "native_bool_violation",
    "restart_missing",
})

STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json_lf(path: Path):
    return p1chk.load_json_lf(path)


def _case_variants(case: dict) -> list:
    v = case.get("variants")
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _flat_variant_facts(case: dict) -> list:
    """Variants plus any structured fact dicts at case level (facts/records)."""
    out = _case_variants(case)
    facts = case.get("facts")
    if isinstance(facts, dict):
        for v in facts.values():
            if isinstance(v, dict):
                out.append(v)
    records = case.get("records")
    if isinstance(records, list):
        out.extend(x for x in records if isinstance(x, dict))
    return out


def _case_session_log_bytes(case: dict, evidence_dir: Path) -> list:
    """Raw bytes of the case's declared session console/mpv.log files
    (used to cross-check DESC sample excerpts against real log content)."""
    out: list = []
    for stem in case.get("sessions") or []:
        if not isinstance(stem, str):
            continue
        for suffix in (".console.txt", ".mpv.log"):
            p = evidence_dir / (stem + suffix)
            if p.is_file():
                out.append(p.read_bytes())
    return out


def scan_evidence_dir(evidence_dir: Path) -> tuple:
    """Inventory the evidence dir: ({rel name: path}, {console stems}, problems).
    Rejects symlink/reparse entries and __pycache__ anywhere inside."""
    on_disk: dict = {}
    console_stems: set = set()
    problems: list = []
    for p in sorted(evidence_dir.rglob("*")):
        if p.is_symlink() or getattr(p.lstat(), "st_file_attributes", 0) & 0x400:
            problems.append(f"证据目录内出现链接/reparse点（拒绝）: "
                            f"{p.relative_to(evidence_dir).as_posix()}")
            continue
        if not p.is_file():
            continue
        if p.parent.name == "__pycache__":
            problems.append(f"证据目录内出现字节码缓存目录（不应存在）: "
                            f"{p.relative_to(evidence_dir).as_posix()}")
            continue
        rel = p.relative_to(evidence_dir).as_posix()
        on_disk[rel] = p
        if (rel.endswith(".console.txt") and rel.count("/") == 0
                and rel not in EXCLUDED_FROM_MANIFEST):
            console_stems.add(rel[:-len(".console.txt")])
    return on_disk, console_stems, problems


# ---------------------------------------------------------------------------
# 2. full-directory coverage vs the closed exclusion class
# ---------------------------------------------------------------------------

def check_full_directory_coverage(manifest: dict, evidence_dir: Path,
                                  repo_root: Path) -> list:
    """Manifest keys are REPO-relative (lib.build_evidence_manifest shape);
    they are projected onto this evidence dir for coverage.  A key bound
    outside the evidence dir breaks full-tree coverage and is a FAIL."""
    problems: list = []
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return ["manifest files 缺失或为空，无法做全目录覆盖检查"]
    session = manifest.get("session")
    try:
        ev_rel = evidence_dir.resolve().relative_to(
            Path(repo_root).resolve()).as_posix()
    except ValueError:
        return [f"证据目录不在仓库内: {evidence_dir}"]
    prefix = f"{lib.SESSIONS_ROOT}/{session}/"
    if not ev_rel.startswith(prefix):
        problems.append(f"证据目录不在会话树 {prefix}** 内: {ev_rel}")
    ev_prefix = ev_rel + "/"
    bound_names: dict = {}
    for rel in files:
        if not rel.startswith(ev_prefix):
            problems.append(
                f"清单绑定了证据目录之外的路径（全目录覆盖无法成立）: {rel}")
            continue
        name = rel[len(ev_prefix):]
        if "/" not in name and name in EXCLUDED_FROM_MANIFEST:
            problems.append(
                f"排除类文件不得进入清单（自身/循环自指）: {name}")
            continue
        bound_names[name] = rel
    on_disk, _, scan_problems = scan_evidence_dir(evidence_dir)
    problems += scan_problems
    excluded_on_disk = {rel for rel in on_disk
                        if "/" not in rel and rel in EXCLUDED_FROM_MANIFEST}
    for rel in sorted(set(on_disk) - set(bound_names) - excluded_on_disk):
        problems.append(f"全目录覆盖漏项（磁盘存在但清单未绑定）: {rel}")
    for rel in sorted(set(bound_names) - set(on_disk)):
        problems.append(f"清单条目在证据目录中缺失: {rel}")
    return problems


# ---------------------------------------------------------------------------
# chain over the closed exclusion class (excluded ≠ unchecked)
# ---------------------------------------------------------------------------

def check_chain(evidence_dir: Path, session: str, manifest_sha: str) -> list:
    """runner.console.txt must exist non-empty and be pinned by
    manifest-verify.json (which pins the manifest bytes too);
    evidence-gate.json, when present, must pin manifest-verify.json."""
    problems: list = []
    runner = evidence_dir / "runner.console.txt"
    runner_sha = None
    if not runner.is_file():
        problems.append("缺 runner.console.txt（运行控制台必须留痕并独立钉扎）")
    elif runner.stat().st_size == 0:
        problems.append("runner.console.txt 为空文件")
    else:
        runner_sha = sha256_bytes(runner.read_bytes())

    mv_path = evidence_dir / "manifest-verify.json"
    if not mv_path.is_file():
        problems.append("缺 manifest-verify.json（清单与运行控制台的独立哈希钉扎）")
        return problems
    mv, mv_bytes, problem = p1chk._load_json_problem(mv_path)
    if problem:
        problems.append(problem)
        return problems
    if mv.get("schema") != MANIFEST_VERIFY_SCHEMA:
        problems.append(f"manifest-verify schema 不符: {mv.get('schema')!r}")
    if mv.get("session") != session:
        problems.append(f"manifest-verify session 不符: {mv.get('session')!r}")
    if mv.get("evidence_manifest_sha256") != manifest_sha:
        problems.append("manifest-verify 未钉住当前 evidence-manifest.json 字节"
                        f"（期望 {manifest_sha[:12]}…, 记录 "
                        f"{str(mv.get('evidence_manifest_sha256'))[:12]}…）")
    if runner_sha is not None and mv.get("runner_console_sha256") != runner_sha:
        problems.append("manifest-verify 的 runner_console_sha256 与磁盘"
                        " runner.console.txt 不符")

    gate_path = evidence_dir / "evidence-gate.json"
    if gate_path.is_file():
        gate, _, g_problem = p1chk._load_json_problem(gate_path)
        if g_problem:
            problems.append(g_problem)
            return problems
        if gate.get("schema") != EVIDENCE_GATE_SCHEMA:
            problems.append(f"evidence-gate schema 不符: {gate.get('schema')!r}")
        if gate.get("session") != session:
            problems.append(f"evidence-gate session 不符: {gate.get('session')!r}")
        if gate.get("evidence_manifest_sha256") != manifest_sha:
            problems.append("evidence-gate 钉扎的 evidence-manifest 哈希与当前"
                            "清单不符")
        if gate.get("manifest_verify_sha256") != sha256_bytes(mv_bytes):
            problems.append("evidence-gate 钉扎的 manifest-verify 哈希与当前"
                            "manifest-verify.json 不符")
        if gate.get("status") not in ("PASS", "FAIL"):
            problems.append(f"evidence-gate status 非法: {gate.get('status')!r}")
    return problems


# ---------------------------------------------------------------------------
# 4. per-case artifact triplets (restart console / mpv log / IPC transcript)
# ---------------------------------------------------------------------------

def check_case_artifacts(case: dict, evidence_dir: Path, bound_names: set,
                         cid: str) -> list:
    problems: list = []
    if cid in NO_MPV_CASES:
        return problems
    sessions = case.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        problems.append(f"case {cid}: 未声明任何真实 mpv 会话名（sessions 为空）")
        return problems
    if len(set(sessions)) != len(sessions):
        problems.append(f"case {cid}: sessions 含重复名: {sessions}")
    for stem in sessions:
        if not isinstance(stem, str) or not STEM_RE.fullmatch(stem or ""):
            problems.append(f"case {cid}: 非法会话名 {stem!r}")
            continue
        for suffix in (".console.txt", ".mpv.log", ".mpv.transcript.jsonl"):
            rel_name = stem + suffix
            p = evidence_dir / rel_name
            if not p.exists():
                problems.append(f"case {cid}: 会话 {stem} 缺少 {suffix} 产物"
                                "（restart/console/IPC 漏收）")
                continue
            if p.stat().st_size == 0:
                problems.append(f"case {cid}: 会话 {stem} 的 {suffix} 为空文件")
            if rel_name not in bound_names:
                problems.append(f"case {cid}: 产物未进清单: {rel_name}")
    return problems


def check_orphan_sessions(console_stems: set, results: dict) -> list:
    """Every on-disk <stem>.console.txt must be declared by some case —
    catches silently dropped cases / un-collected restart sessions."""
    declared: set = set()
    for case in results.get("cases") or []:
        if isinstance(case, dict):
            declared.update(s for s in case.get("sessions") or []
                            if isinstance(s, str))
    return [f"会话产物存在但无 case 声明（漏项/被删 case）: {stem}.console.txt"
            for stem in sorted(console_stems - declared)]


# ---------------------------------------------------------------------------
# 5. DESC + samples honesty (reject 0==0 / label-substring / fabricated lines)
# ---------------------------------------------------------------------------

def _check_p3_desc_evidence(de: dict, log_bytes: list | None) -> list:
    """Structured-only acceptance of algorithm presence for the P3 shape."""
    problems: list = []
    count = de.get("count")
    if not isinstance(count, int) or count < 1:
        problems.append(f"desc_evidence.count 非 ≥1 整数（0==0 计数拒绝）: {count!r}")
    hits = de.get("sample_hits")
    if not isinstance(hits, dict) or not hits:
        problems.append(f"desc_evidence.sample_hits 缺失或为空: {hits!r}")
        return problems
    excerpts: list = []
    for key, val in hits.items():
        items = val if isinstance(val, list) else [val]
        for item in items:
            if isinstance(item, str) and item.strip():
                excerpts.append(item)
            else:
                problems.append(f"desc_evidence.sample_hits[{key!r}] 含空/非字符串样本: {item!r}")
    if not excerpts:
        problems.append("desc_evidence.sample_hits 无任何非空真实样本行")
    if isinstance(count, int) and count < len(excerpts):
        problems.append(f"desc_evidence.count={count} 小于样本行数 {len(excerpts)}"
                        "（样本必须是命中子集）")
    if log_bytes is not None:
        for text in excerpts:
            needle = text.encode("utf-8")
            if not any(needle in blob for blob in log_bytes):
                problems.append(f"desc 样本行未在任何会话 console/mpv.log 中出现"
                                f"（伪造样本）: {text[:80]!r}")
    return problems


def check_desc_honesty(case: dict, cid: str,
                       log_bytes: list | None = None) -> list:
    if cid not in P3_DESC_CASES and cid not in LEGACY_DESC_REQUIRED:
        return []
    if case.get("status") != "PASS":
        return []  # a FAIL case needs no presence proof; coverage gate handles it
    legacy_ok = False
    p3_problems: list = []
    p3_valid = False
    p3_seen = False
    for variant in _flat_variant_facts(case):
        if "desc_evidence" in variant:
            p3_seen = True
            bad = _check_p3_desc_evidence(variant["desc_evidence"], log_bytes)
            if bad:
                p3_problems.extend(bad)
            else:
                p3_valid = True
        elif "desc_keyword_pass_hits" in variant:
            value = variant["desc_keyword_pass_hits"]
            if isinstance(value, int) and value > 0:
                legacy_ok = True
        elif "required_desc_hits" in variant:
            value = variant["required_desc_hits"]
            if isinstance(value, dict) and any(bool(v) for v in value.values()):
                legacy_ok = True
    if cid in P3_DESC_CASES:
        if not p3_seen:
            return [f"case {cid}: PASS 缺少结构化 desc_evidence"
                    "（count+真实 sample_hits；'user shader' 子串计数不生效）"]
        if not p3_valid:
            return [f"case {cid}: PASS 的 desc_evidence 全部无效（反 0==0/伪造样本门）: "
                    + "; ".join(p3_problems[:4])]
        # invalid extra blocks are fabricated evidence — still reported
        if p3_problems:
            return [f"case {cid}: 存在无效 desc_evidence 块: "
                    + "; ".join(p3_problems[:4])]
        return []
    # legacy shapes (SHD-01/02/04): at least one variant with a real hit
    if legacy_ok:
        return []
    return [f"case {cid}: PASS 缺少 DESC 结构化命中证据（反 0==0 门）"]


# ---------------------------------------------------------------------------
# 6. structured same-moment records (not doc words)
# ---------------------------------------------------------------------------

def _same_moment_record_ok(rec: dict) -> list:
    missing = []
    fmt = rec.get("pixelformat")
    if not isinstance(fmt, str) or not fmt.strip():
        missing.append("pixelformat 缺失（解码身份必须同窗采样）")
    for key in ("w", "h", "dw", "dh", "osd_w", "osd_h"):
        v = rec.get(key)
        if not isinstance(v, int) or v <= 0:
            missing.append(f"{key} 非正整数: {v!r}")
    counts = rec.get("vo_passes_frame_counts")
    if not isinstance(counts, dict) or \
            not all(isinstance(counts.get(k), int) and counts.get(k) >= 0
                    for k in ("fresh", "redraw")):
        missing.append(f"vo_passes_frame_counts 非合法 fresh/redraw 计数: {counts!r}")
    if rec.get("same_window") is not True:
        missing.append("same_window 非 true（非同一观察窗=VL-F1 类）")
    return missing


def check_same_moment(case: dict, cid: str) -> list:
    if cid not in SAME_MOMENT_CASES:
        return []
    if case.get("status") != "PASS":
        return []
    defects: list = []
    valid = False
    seen = False
    for variant in _flat_variant_facts(case):
        recs = variant.get("same_moment")
        if not isinstance(recs, list) or not recs:
            continue
        for rec in recs:
            if not isinstance(rec, dict):
                defects.append(f"same_moment 含非对象记录: {rec!r}")
                continue
            seen = True
            bad = _same_moment_record_ok(rec)
            if bad:
                defects.extend(bad)
            else:
                valid = True
    if not seen:
        return [f"case {cid}: PASS 缺少结构化 same_moment 记录"
                "（vop 解码+几何+frame_counts 同刻；文字声明不算数）"]
    if not valid:
        return [f"case {cid}: same_moment 记录全部无效: " + "; ".join(defects[:4])]
    if defects:
        return [f"case {cid}: 存在无效 same_moment 记录: " + "; ".join(defects[:4])]
    return []


# ---------------------------------------------------------------------------
# 7. render freshness vs decoder liveness (0==0 and stale-epoch rejection)
# ---------------------------------------------------------------------------

def _freshness_defects(fr: dict, variant: dict) -> list:
    defects: list = []
    if fr.get("render_fresh") is not True:
        defects.append(f"render_fresh 非 true: {fr.get('render_fresh')!r}")
    method = fr.get("method")
    if method not in RENDER_FRESH_METHODS:
        defects.append(f"method={method!r} 不是真实渲染新帧证据"
                       "（解码活性不能兜底 GPU 渲染证明）")
    before, after = fr.get("fresh_before"), fr.get("fresh_after")
    if not (isinstance(before, int) and isinstance(after, int)
            and 0 <= before < after):
        defects.append(f"fresh_before/fresh_after 不满足 0≤before<after"
                       f"（0==0 拒绝）: {before!r}/{after!r}")
    v_epoch = variant.get("chain_epoch")
    if not isinstance(v_epoch, int) or v_epoch < 0:
        defects.append(f"variant 缺非负 int chain_epoch: {v_epoch!r}")
    elif fr.get("chain_epoch") != v_epoch:
        defects.append(f"freshness.chain_epoch={fr.get('chain_epoch')!r} ≠ "
                       f"variant.chain_epoch={v_epoch!r}（陈旧 epoch 配对）")
    return defects


def check_render_freshness(case: dict, cid: str) -> list:
    if cid not in RENDER_FRESH_CASES:
        return []
    if case.get("status") != "PASS":
        return []
    defects: list = []
    valid = False
    seen = False
    for variant in _flat_variant_facts(case):
        fr = variant.get("freshness")
        if not isinstance(fr, dict):
            continue
        seen = True
        bad = _freshness_defects(fr, variant)
        if bad:
            defects.extend(bad)
        else:
            valid = True
    if not seen:
        return [f"case {cid}: PASS 的 active 断言缺少 freshness 结构化证据"
                "（vo-passes 计数/强制重绘/新输出像素三选一）"]
    if not valid:
        return [f"case {cid}: freshness 证据全部无效: " + "; ".join(defects[:4])]
    if defects:
        return [f"case {cid}: 存在无效 freshness 块: " + "; ".join(defects[:4])]
    return []


# ---------------------------------------------------------------------------
# 8. PNG captures & duplicate-hash honesty (true bit depth, real dimensions)
# ---------------------------------------------------------------------------

def check_png_captures(evidence_dir: Path, manifest_files: dict, results: dict,
                       repo_root: Path | None = None) -> list:
    repo_root = Path(repo_root or lib.REPO_ROOT)
    session = results.get("session")
    try:
        ev_rel = evidence_dir.resolve().relative_to(repo_root.resolve()).as_posix()
        ev_prefix = ev_rel + "/"
    except ValueError:
        ev_prefix = None
    problems: list = []
    captures = results.get("png_captures")
    if not isinstance(captures, list):
        return ["objective-results.png_captures 缺失或非列表"]
    by_rel: dict = {}
    for cap in captures:
        if not isinstance(cap, dict) or "path" not in cap:
            problems.append(f"png_captures 条目缺少 path: {cap!r}")
            continue
        rel = cap["path"]
        try:
            path = lib.safe_manifest_relpath(rel, session, repo_root)
        except ValueError as e:
            problems.append(f"png_captures 路径非法（canonical/in-session/无链接）: {rel}: {e}")
            continue
        if ev_prefix is not None and not rel.startswith(ev_prefix):
            problems.append(f"png_captures 指向证据目录之外: {rel}")
            continue
        by_rel[rel] = cap
        w, h = cap.get("w"), cap.get("h")
        if not (isinstance(w, int) and w > 0 and isinstance(h, int) and h > 0):
            problems.append(f"png_captures 条目缺真实尺寸: {rel}")
    # every PNG in the manifest must be registered with a size
    for rel in manifest_files:
        name = rel.rsplit("/", 1)[-1]
        if name.lower().endswith(".png") and rel not in by_rel:
            problems.append(f"清单内 PNG 未登记 png_captures（尺寸/来源不明）: {rel}")
    # non-empty + real PNG + hash + declared-dims vs decoded IHDR
    groups: dict = {}
    for rel, cap in sorted(by_rel.items()):
        p = repo_root / rel
        if not p.exists():
            problems.append(f"png_captures 指向缺失文件: {rel}")
            continue
        data = p.read_bytes()
        if len(data) == 0:
            problems.append(f"PNG 为空文件: {rel}")
            continue
        digest = sha256_bytes(data)
        if str(cap.get("sha256") or "") != digest:
            problems.append(f"png_captures 哈希与磁盘不符（疑似替换 PNG）: {rel}")
        try:
            decoded = p3_lib.decode_png(data)
            if (decoded.get("w"), decoded.get("h")) != (cap.get("w"), cap.get("h")) \
                    and isinstance(cap.get("w"), int):
                problems.append(
                    f"png_captures 声明尺寸与真实解码不符: {rel} 声明 "
                    f"{cap.get('w')}x{cap.get('h')} 实际 "
                    f"{decoded.get('w')}x{decoded.get('h')}")
        except ValueError as e:
            problems.append(f"png_captures 不是可解码 PNG（真实字节校验失败）: {rel}: {e}")
        groups.setdefault(digest, []).append(rel)
    marked: dict = {}
    for entry in results.get("non_corroborative_png") or []:
        if isinstance(entry, dict):
            for rel in entry.get("files") or []:
                marked[str(rel)] = entry.get("reason") or ""
    for digest, rels in sorted(groups.items()):
        if len(rels) > 1:
            unmarked = [r for r in rels if r not in marked]
            if unmarked:
                problems.append(
                    f"重复内容 PNG（sha256={digest[:12]}…）未诚实标注 "
                    f"non-corroborative: {unmarked}")
    for rel in marked:
        if rel not in by_rel:
            problems.append(f"non_corroborative_png 引用了未登记的 PNG: {rel}")
    return problems


# ---------------------------------------------------------------------------
# 9. Integer native-bool readback (CORE-R1 class)
# ---------------------------------------------------------------------------

def check_integer_native_bool(case: dict, cid: str) -> list:
    if cid not in INTEGER_NATIVE_BOOL_CASES:
        return []
    if case.get("status") != "PASS":
        return []
    defects: list = []
    valid = False
    for variant in _flat_variant_facts(case):
        nb = variant.get("native_unscaled")
        if not isinstance(nb, dict):
            continue
        if nb.get("native_type") == "bool" and nb.get("value") in (True, False):
            valid = True
        else:
            defects.append(
                f"native_unscaled 非原生 bool 读回: type={nb.get('native_type')!r} "
                f"value={nb.get('value')!r}（CORE-R1：true/false 而非 yes/no）")
    if defects:
        return [f"case {cid}: 存在非原生 bool 的 video-unscaled 读回记录: "
                + "; ".join(defects[:2])]
    if valid:
        return []
    return [f"case {cid}: PASS 缺少 video-unscaled 原生 bool 读回记录"
            "（true/false 类型断言，非 yes/no 字符串）"]


# ---------------------------------------------------------------------------
# 10. SHD-09 8/10bit decode honesty
# ---------------------------------------------------------------------------

def check_bitdepth_coverage(case: dict, cid: str) -> list:
    if cid != "SHD-09" or case.get("status") != "PASS":
        return []
    problems: list = []
    covered: set = set()
    refused: set = set()
    for variant in _flat_variant_facts(case):
        bd = variant.get("bitdepth")
        if bd not in (8, 10):
            continue
        if variant.get("refused") is True:
            if not str(variant.get("reason") or "").strip():
                problems.append(f"case SHD-09: bitdepth={bd} 声明拒用但无理由")
            else:
                refused.add(bd)
            continue
        recs = [r for r in variant.get("same_moment") or [] if isinstance(r, dict)]
        if not recs:
            problems.append(f"case SHD-09: bitdepth={bd} 变体缺 same_moment"
                            " 解码证据（不得无测称支持）")
            continue
        fmts = [str(r.get("pixelformat") or "") for r in recs]
        mismatch = [f for f in fmts if not f or (("10" in f) != (bd == 10))]
        if mismatch:
            problems.append(
                f"case SHD-09: bitdepth={bd} 的解码身份不符（声明 {bd}bit，"
                f"pixelformat={mismatch[:2]}）——10bit 未真实解码不得谎报")
            continue
        covered.add(bd)
    for bd in (8, 10):
        if bd not in covered and bd not in refused:
            problems.append(f"case SHD-09: PASS 缺少 {bd}bit 实测证据"
                            "（真实 same_moment 解码身份或明确拒用理由）")
    return problems


# ---------------------------------------------------------------------------
# 11. PER-04-COMPUTE raw samples honesty
# ---------------------------------------------------------------------------

def _valid_perf_samples(value) -> bool:
    return (isinstance(value, list) and len(value) >= 2
            and all(isinstance(x, int) and x > 0 for x in value))


def check_perf_samples(case: dict, cid: str) -> list:
    if cid != "PER-04-COMPUTE" or case.get("status") != "PASS":
        return []
    facts = case.get("facts") if isinstance(case.get("facts"), dict) else {}
    samples = facts.get("perf_samples_ns")
    note = facts.get("samples_note")
    if not _valid_perf_samples(samples):
        for variant in _flat_variant_facts(case):
            if _valid_perf_samples(variant.get("perf_samples_ns")):
                samples = variant["perf_samples_ns"]
                note = note or variant.get("samples_note")
                break
    if not _valid_perf_samples(samples):
        return ["case PER-04-COMPUTE: PASS 缺少 ≥2 个正整数原始 fresh-redraw "
                "ns 样本（perf_samples_ns）"]
    if not str(note or "").strip():
        return ["case PER-04-COMPUTE: PASS 缺少 samples_note（样本数/口径说明）"]
    return []


# ---------------------------------------------------------------------------
# 12. EVI-01 self-negative report
# ---------------------------------------------------------------------------

def check_evi01(case: dict) -> list:
    if case.get("status") != "PASS":
        return []
    facts = case.get("facts") or {}
    detected = facts.get("negatives_detected")
    if not isinstance(detected, dict) or not detected:
        return ["EVI-01: 缺少 negatives_detected 结构化负例清单"]
    missing_keys = sorted(EVI_NEGATIVE_KEYS - set(detected))
    if missing_keys:
        return [f"EVI-01: 规定负例类别未覆盖: {missing_keys}"]
    not_fired = sorted(k for k, v in detected.items() if v is not True)
    if not_fired:
        return [f"EVI-01: 合成负例未被检出: {not_fired}"]
    positive = facts.get("positive_control_clean")
    if positive is not True:
        return ["EVI-01: 阳性对照（合法迷你证据树）未通过或缺失"]
    return []


# ---------------------------------------------------------------------------
# results-level checks
# ---------------------------------------------------------------------------

def check_results(results: dict, evidence_dir: Path, manifest_files: dict,
                  require_tests: bool, required_ids=None,
                  repo_root: Path | None = None) -> list:
    repo_root = Path(repo_root or lib.REPO_ROOT)
    session = results.get("session")
    problems: list = []
    if results.get("stage") != "P3" or not session:
        problems.append(f"objective-results 身份不符: stage={results.get('stage')!r} "
                        f"session={session!r}")
    cases = results.get("cases")
    if not isinstance(cases, list) or not cases:
        return problems + ["objective-results.cases 缺失或为空"]
    by_id: dict = {}
    for case in cases:
        if not isinstance(case, dict) or not case.get("id"):
            problems.append(f"objective-results 存在无名 case 条目: {case!r}")
            continue
        cid = case["id"]
        if cid in by_id:
            problems.append(f"case id 重复: {cid}")
        by_id[cid] = case
    need = list(required_ids) if required_ids else P3_REQUIRED_IDS
    if require_tests:
        for rid in need:
            case = by_id.get(rid)
            if case is None:
                problems.append(f"必需测试缺少报告条目: {rid}")
            elif case.get("status") != "PASS":
                problems.append(f"必需测试非 PASS: {rid} ({case.get('status')!r})")
        if results.get("required_unmeasured") not in ([], None):
            problems.append(f"required_unmeasured 非空: {results.get('required_unmeasured')!r}")
    for cid, case in sorted(by_id.items()):
        # files[] referenced by the case must exist on disk and in manifest
        for rel in case.get("files") or []:
            try:
                path = lib.safe_manifest_relpath(rel, session, repo_root)
            except ValueError as e:
                problems.append(f"case {cid}: 非法证据引用 {rel}: {e}")
                continue
            if rel not in manifest_files:
                problems.append(f"case {cid}: 证据文件未进清单: {rel}")
            elif not path.exists():
                problems.append(f"case {cid}: 证据文件缺失: {rel}")
        # bound names projected to evidence-dir-relative for triplet checks
        try:
            ev_prefix = evidence_dir.resolve().relative_to(
                repo_root.resolve()).as_posix() + "/"
            bound_names = {rel[len(ev_prefix):] if rel.startswith(ev_prefix)
                           else rel for rel in manifest_files}
        except ValueError:
            bound_names = set(manifest_files)
        problems += check_case_artifacts(case, evidence_dir, bound_names, cid)
        log_bytes = (_case_session_log_bytes(case, evidence_dir)
                     if cid in P3_DESC_CASES else None)
        problems += check_desc_honesty(case, cid, log_bytes)
        problems += check_same_moment(case, cid)
        problems += check_render_freshness(case, cid)
        problems += check_integer_native_bool(case, cid)
        problems += check_bitdepth_coverage(case, cid)
        problems += check_perf_samples(case, cid)
        if cid == "EVI-01":
            problems += check_evi01(case)
    problems += check_png_captures(evidence_dir, manifest_files, results,
                                   repo_root)
    _, console_stems, _ = scan_evidence_dir(evidence_dir)
    problems += check_orphan_sessions(console_stems, results)
    if results.get("live_configuration_written") not in (False, None):
        problems.append("live_configuration_written 必须为 false")
    return problems


# ---------------------------------------------------------------------------
# full gate
# ---------------------------------------------------------------------------

def run_full_gate(evidence_dir: Path, session: str, results_path: Path,
                  manifest_path: Path, require_tests: bool,
                  repo_root: Path | None = None, required_ids=None) -> list:
    repo_root = Path(repo_root or lib.REPO_ROOT)
    problems: list = []
    if not evidence_dir.is_dir():
        return [f"证据目录不存在: {evidence_dir}"]
    if evidence_dir.is_symlink():
        return [f"证据目录是链接（拒绝）: {evidence_dir}"]
    if not manifest_path.is_file():
        return [f"证据清单缺失: {manifest_path}"]
    manifest, manifest_bytes, parse_problem = p1chk._load_json_problem(manifest_path)
    if parse_problem:
        return [parse_problem]
    problems += lib.verify_evidence_manifest(manifest, session, repo_root)
    problems += check_full_directory_coverage(manifest, evidence_dir, repo_root)
    problems += check_chain(evidence_dir, session, sha256_bytes(manifest_bytes))
    manifest_files: dict = manifest.get("files") or {}
    if results_path is not None and results_path.is_file():
        results, _, r_problem = p1chk._load_json_problem(results_path)
        if r_problem:
            problems.append(r_problem)
        else:
            if results.get("session") != session:
                problems.append(f"objective-results session 与 --session 不符: "
                                f"{results.get('session')!r} ≠ {session!r}")
            problems += check_results(results, evidence_dir, manifest_files,
                                      require_tests, required_ids, repo_root)
    elif require_tests:
        problems.append(f"objective-results 缺失: {results_path}")
    return problems


# ---------------------------------------------------------------------------
# gate artifact writer (create-only; the terminal pin of the chain)
# ---------------------------------------------------------------------------

def write_gate_file(evidence_dir: Path, session: str, manifest_path: Path,
                    problems: list, repo_root: Path | None = None) -> Path:
    """Write evidence-gate.json create-only, pinning manifest-verify.json.
    FAIL results are recorded verbatim and preserved (create-only: a rerun
    needs a NEW evidence directory, never an overwrite)."""
    repo_root = Path(repo_root or lib.REPO_ROOT)
    gate_path = evidence_dir / "evidence-gate.json"
    mv_path = evidence_dir / "manifest-verify.json"
    data = {
        "schema": EVIDENCE_GATE_SCHEMA,
        "session": session,
        "stage": "P3",
        "evidence_dir": evidence_dir.resolve().relative_to(
            repo_root.resolve()).as_posix(),
        "checker": "tools/p3_check_evidence.py run_full_gate",
        "evidence_manifest_sha256": lib.sha256_file(manifest_path),
        "manifest_verify_sha256": lib.sha256_file(mv_path) if mv_path.is_file() else None,
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "human_subjective_acceptance_claimed": False,
        "live_configuration_written": False,
        "note": "create-only 门禁产物；FAIL 原样保留，复跑须用全新证据目录",
    }
    return lib.Evidence._write_create_only(
        gate_path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True,
                        help="P3 evidence directory (…/p3-001/implementer/<run>)")
    parser.add_argument("--session", default="p3-001")
    parser.add_argument("--manifest", default=None,
                        help="default <evidence-dir>/evidence-manifest.json")
    parser.add_argument("--results", default=None,
                        help="default <evidence-dir>/objective-results.json")
    parser.add_argument("--require-tests", action="store_true",
                        help="require all 35 P3 ids present and PASS")
    parser.add_argument("--required-ids", nargs="*", default=None,
                        help="override the required id list (checker self-tests)")
    parser.add_argument("--write-gate", action="store_true",
                        help="write evidence-gate.json create-only (pins "
                             "manifest-verify.json; FAIL preserved verbatim)")
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir).resolve()
    try:
        evidence_dir.relative_to(lib.REPO_ROOT)
    except ValueError:
        parser.error(f"--evidence-dir must live inside the repo ({lib.REPO_ROOT})")
    expected_prefix = f"{lib.SESSIONS_ROOT}/{args.session}/"
    ev_rel = evidence_dir.relative_to(lib.REPO_ROOT).as_posix()
    if not ev_rel.startswith(expected_prefix):
        parser.error(f"--evidence-dir must live inside {expected_prefix}**; got {ev_rel}")
    manifest_path = Path(args.manifest) if args.manifest \
        else evidence_dir / "evidence-manifest.json"
    results_path = Path(args.results) if args.results \
        else evidence_dir / "objective-results.json"
    required_ids = args.required_ids if args.required_ids else None

    problems = run_full_gate(evidence_dir, args.session, results_path,
                             manifest_path, args.require_tests,
                             required_ids=required_ids)
    gate_note = None
    if args.write_gate:
        try:
            gate_path = write_gate_file(evidence_dir, args.session,
                                        manifest_path, problems)
            gate_note = str(gate_path)
        except FileExistsError as e:
            problems = list(problems) + [f"create-only 拒绝: {e}"]
    verdict = {
        "status": "PASS" if not problems else "FAIL",
        "session": args.session,
        "evidence_dir": evidence_dir.name,
        "manifest": str(manifest_path),
        "results": str(results_path),
        "excluded_from_manifest": sorted(EXCLUDED_FROM_MANIFEST),
        "gate_written": gate_note,
        "problems": problems,
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
