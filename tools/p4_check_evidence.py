# -*- coding: utf-8 -*-
"""P4 EVI-01 evidence integrity gate + anti-metric semantic gate (W1c).

session p4-001, plan sha256 5285d11293373a20523ac199de2868ac2911e550ffd48b47be
164311888c822a. Pure Python 3.9 stdlib; read-only over the workspace; never
starts mpv/GPU/VS, never writes live configuration.

Scope (docs/P4/P4-B1纯工具实现brief.md, W1c):
- EVI tree closed hashing: repo-relative canonical keys, every file actually
  hashed, symlink/reparse rejected, missing/unregistered files fail closed.
  The manifest's own self-referential loop is resolved with a FIXED exclusion
  set (only the manifest file itself) plus an independently recomputable
  manifest-bytes hash; no caller-supplied exclusions exist, so exclusion
  cannot be abused to escape coverage.
- Semantic gates recompute statistics from structured raw data (via the W1a/W1b
  frozen libraries) instead of scanning "faster" keywords alone; anti-metric
  negative controls (FPS-only RIFE proof, vo=image as shader proof, per-pass
  sum as overall headroom, IPC samples as present, synthetic as natural,
  machine-signed user approval, lost FAIL/exclusion traces) each have a
  structured violation code.
- Production lock and stage status synthesis follow docs/P4实施计划.json
  status_vocabulary: anything unmeasured stays 未测/NOT_RUN; a pre-registered
  stage cap of PARTIAL_MEASURED prevents a full-P4 PASS this stage (TIME-01
  real present source and natural samples are preregistered missing).

Path checks here are canonical-path + create-only evidence bookkeeping; they
are explicitly NOT an OS sandbox and NOT a TOCTOU defence.

B1-r2 (docs/P4/P4-B1限域修正brief-v2.md, unit B): the review found the stage
entry trusting self-declared PASS (F2), crashing on the real v2 analysis
bundle shape (F3), accepting garbage RIFE proof pieces (F6), an
indistinguishable zero-measurement stage (F7), and candidate gates that were
never wired into the real entry (F9). This revision: trial reports qualify
only through schema + real file/sha bindings + re-analysis here (fixture
runs carry zero measurement credit); exclusion traces read the REAL
analyze_records bundle (rejected_by_analysis is a list); RIFE proofs are
type/hash/file/pin checked through verify_rife_proof(evidence, context,
root) — strict structure only, never an authenticity claim and never an
assumption that the model must behave like linear interpolation; the stage
report discloses n_measured/measurement_status explicitly; candidate/coverage/closed-tree
gates are actually called by p4_verify, and a missing candidate is
disclosed as BLOCKED_MISSING_CANDIDATE instead of a fabricated pass.
"""
from __future__ import annotations

import inspect
import os
import re
import stat
import sys
from pathlib import Path

import p4_lib as lib       # frozen W1a dependency (read-only use)
import p4_analyze as an    # frozen W1b dependency (read-only use)

STAGE = lib.STAGE
SESSION = lib.SESSION
PLAN_SHA256 = lib.PLAN_SHA256
PLAN_REL = lib.PLAN_REL
WORK_PERMIT_REL = lib.WORK_PERMIT_REL
EVIDENCE_REL = "docs/验证/开发/p4-001/"

MANIFEST_NAME = "manifest.json"
SCHEMA_MANIFEST = "p4-evidence-manifest-v1"
SCHEMA_TREE_REPORT = "p4-evidence-tree-verify-v1"
SCHEMA_GATE_REPORT = "p4-evidence-gate-report-v1"
SCHEMA_STAGE_REPORT = "p4-stage-verify-report-v1"
SCHEMA_RUN_GATE = "p4-run-evidence-gate-v1"
SCHEMA_CANDIDATE = "p4-candidate-binding-v1"
SCHEMA_TRIAL_REPORT = "p4-trial-stage-report-v1"
SCHEMA_TRIAL_GATE = "p4-trial-gate-report-v1"
CREATED_BY = "tools/p4_check_evidence.py (W1c)"

# A trial report qualifies only when it binds real raw evidence. Keys are
# exact: unknown schemas and unbound reports are violations, never upgrades.
TRIAL_REPORT_REQUIRED = ("schema", "test_id", "status", "claims", "runs")
TRIAL_REPORT_OPTIONAL = ("materials", "captures", "excluded_runs",
                         "analysis_bundle_rel", "analysis_bundle_sha256",
                         "plan_sha256", "rife_identity_pins", "note")
TRIAL_RUN_REQUIRED = ("run_rel", "run_sha256")
TRIAL_RUN_OPTIONAL = ("stored_analysis_rel", "stored_analysis_sha256",
                      "test_fixture", "note")

# Stage status vocabulary (plan status_vocabulary, verbatim semantics).
PER_TEST_VOCAB = ("PASS_OBJECTIVE", "PARTIAL_MEASURED", "PENDING_USER",
                  "BLOCKED_ENV", "FAIL", "未测")
STAGE_VOCAB = ("PASS_OBJECTIVE_WITH_PENDING_USER", "PARTIAL_MEASURED",
               "BLOCKED_ENV", "REWORK")
# Pre-registered stage cap: TIME-01 real present source is missing and natural
# samples are missing, so this stage can never synthesize a pure full PASS.
STAGE_CAP = "PARTIAL_MEASURED"
STAGE_CAP_NOTE = ("pre-registered stage cap: TIME-01 real present frame "
                  "duration has no legal source and natural live-action/"
                  "anime material is missing; full P4 PASS is impossible by "
                  "preregistration, not by gate choice")

# Legal real-present sources (plan TIME-01); IPC polling and time-pos deltas
# are never legal present-frame sources.
LEGAL_PRESENT_SOURCES = ("ETW", "PresentMon")
PRESENT_NOT_MEASURED_NOTE = ("real present frame duration has no legal source "
                             "in this environment (PresentMon not installed, "
                             "no ETW permission); IPC intervals and time-pos "
                             "deltas are media-time proxies, never present")

# A "RIFE proven" claim needs all four preregistered proof pieces; observed
# output fps alone is necessary, never sufficient (plan RIFE-01).
RIFE_PROOF_KEYS = ("dll_model_hash", "filter_fps_real",
                   "middle_frame_sample", "engine_log")
_SPEED_CLAIM_RE = re.compile(r"更快|更慢|faster|slower", re.IGNORECASE)
_NATURAL_CLAIM_RE = re.compile(r"自然|实拍|natural|live[- ]action", re.IGNORECASE)
_PASS_LIKE_VERDICTS = ("PASS_OBJECTIVE", "PASS")
_SHADER_PURPOSES = ("shader_ab", "shader_comparison")
_SHADER_VO_BACKENDS = ("gpu-next",)


# ---------------------------------------------------------------------------
# EVI tree: closed hashing with a fixed self-exclusion set
# ---------------------------------------------------------------------------

def _normalize_tree_prefix(tree_prefix):
    tree_prefix = lib.check_rel_path(str(tree_prefix).rstrip("/")) + "/"
    if not tree_prefix.endswith("/"):
        tree_prefix += "/"
    if not (tree_prefix == EVIDENCE_REL
            or tree_prefix.startswith(EVIDENCE_REL)):
        raise lib.PathContractError(
            "tree_prefix %r is outside the P4 evidence tree %r"
            % (tree_prefix, EVIDENCE_REL))
    return tree_prefix


def _self_exclusion_rel(tree_prefix):
    return _normalize_tree_prefix(tree_prefix) + MANIFEST_NAME


def iter_tree_files(tree_prefix, root=None):
    """All regular files under the evidence tree as sorted canonical rels.

    Fails closed: the tree directory must exist, symlink/reparse components
    are rejected (real junctions included), and a file that vanishes during
    the walk raises instead of being skipped.
    """
    tree_prefix = _normalize_tree_prefix(tree_prefix)
    tree_abs = lib.resolve_under_root(tree_prefix.rstrip("/"), root)
    if not tree_abs.is_dir():
        raise lib.MissingInputError(
            "evidence tree does not exist (fail closed): %r" % tree_prefix)
    root_abs = Path(root) if root is not None else lib.workspace_root()
    out = []
    for dirpath, dirnames, filenames in os.walk(str(tree_abs),
                                                followlinks=False):
        for name in sorted(dirnames) + sorted(filenames):
            full = os.path.join(dirpath, name)
            st = os.lstat(full)
            attrs = getattr(st, "st_file_attributes", 0)
            if (attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT) \
                    or os.path.islink(full):
                raise lib.PathContractError(
                    "symlink/reparse component rejected in evidence tree: %s"
                    % full)
        for name in sorted(filenames):
            rel = Path(os.path.join(dirpath, name)).relative_to(
                root_abs).as_posix()
            out.append(lib.check_rel_path(rel))
    return sorted(out)


def build_manifest(tree_prefix, root=None):
    """Closed-hash manifest of one evidence subtree.

    Exclusions are a module-fixed set (only the manifest file itself, which
    cannot contain its own hash); there is no caller-supplied exclude
    parameter, so coverage cannot be shrunk arbitrarily. tree_sha256 is
    computed over the sorted 'rel  sha256' lines.
    """
    tree_prefix = _normalize_tree_prefix(tree_prefix)
    self_excl = _self_exclusion_rel(tree_prefix)
    files = {}
    for rel in iter_tree_files(tree_prefix, root):
        if rel == self_excl:
            continue
        files[rel] = lib.sha256_file(lib.resolve_under_root(rel, root))
    lines = "".join("%s  %s\n" % (r, files[r]) for r in sorted(files))
    return {
        "schema": SCHEMA_MANIFEST,
        "stage": STAGE,
        "session": SESSION,
        "plan_sha256": PLAN_SHA256,
        "tree_prefix": tree_prefix,
        "files": dict(sorted(files.items())),
        "self_excluded": {
            self_excl:
                "manifest self-referential loop: excluded from its own "
                "coverage; verifiers rehash the manifest bytes independently "
                "outside this structure",
        },
        "file_count": len(files),
        "tree_sha256": lib.sha256_bytes(lines.encode("utf-8")),
        "created_by": CREATED_BY,
    }


def _is_under_prefix(rel, tree_prefix):
    return rel == tree_prefix.rstrip("/") or rel.startswith(tree_prefix)


def verify_manifest(manifest, root=None):
    """Recompute-and-compare verification of a manifest. Fail-closed: a
    missing listed file is a violation, never a skip; a physical tree file
    absent from the manifest is unregistered; exclusions outside the fixed
    self set are rejected as exclusion escapes."""
    violations = []

    def bad(code, detail):
        violations.append({"code": code, "detail": detail})

    if not isinstance(manifest, dict):
        return {"schema": SCHEMA_TREE_REPORT, "ok": False,
                "violations": [{"code": "MANIFEST_NOT_DICT",
                                "detail": type(manifest).__name__}]}
    expected_keys = {"schema", "stage", "session", "plan_sha256",
                     "tree_prefix", "files", "self_excluded", "file_count",
                     "tree_sha256", "created_by"}
    if set(manifest) != expected_keys:
        bad("MANIFEST_KEYS_MISMATCH",
            "missing=%s extra=%s" % (sorted(expected_keys - set(manifest)),
                                     sorted(set(manifest) - expected_keys)))
        return {"schema": SCHEMA_TREE_REPORT, "ok": False,
                "violations": violations}
    if manifest["schema"] != SCHEMA_MANIFEST:
        bad("MANIFEST_SCHEMA", repr(manifest["schema"]))
    if manifest["stage"] != STAGE or manifest["session"] != SESSION:
        bad("MANIFEST_STAGE_SESSION",
            "%r/%r" % (manifest["stage"], manifest["session"]))
    if manifest["plan_sha256"] != PLAN_SHA256:
        bad("MANIFEST_PLAN_BINDING", repr(manifest["plan_sha256"]))
    try:
        tree_prefix = _normalize_tree_prefix(manifest["tree_prefix"])
    except lib.PathContractError as exc:
        bad("TREE_PREFIX_INVALID", str(exc))
        return {"schema": SCHEMA_TREE_REPORT, "ok": False,
                "violations": violations}

    self_excl = _self_exclusion_rel(tree_prefix)
    excluded = manifest["self_excluded"]
    if not isinstance(excluded, dict) or set(excluded) != {self_excl}:
        bad("ARBITRARY_EXCLUDE_ESCAPE",
            "self_excluded must be exactly {%r}; got %r" % (self_excl,
                                                            sorted(excluded)
                                                            if isinstance(excluded, dict) else excluded))
    files = manifest["files"]
    if not isinstance(files, dict):
        bad("FILES_NOT_DICT", type(files).__name__)
        files = {}
    listed = set()
    for rel in sorted(files):
        try:
            lib.check_rel_path(rel)
        except lib.PathContractError as exc:
            bad("PATH_CONTRACT", "%s: %s" % (rel, exc))
            continue
        if not _is_under_prefix(rel, tree_prefix):
            bad("OUT_OF_TREE", "listed file outside tree_prefix: %s" % rel)
            continue
        try:
            lib.require_sha256_hex(files[rel], "sha256 for %s" % rel)
        except lib.ValueContractError as exc:
            bad("BAD_SHA_FIELD", str(exc))
            continue
        listed.add(rel)
        try:
            actual = lib.sha256_file(lib.resolve_under_root(rel, root))
        except FileNotFoundError:
            bad("MISSING_FILE", "listed file does not exist: %s" % rel)
            continue
        except lib.P4ContractError as exc:
            bad("FILE_UNREADABLE", "%s: %s" % (rel, exc))
            continue
        if actual != files[rel]:
            bad("HASH_MISMATCH", "%s listed=%s actual=%s"
                % (rel, files[rel], actual))
    if manifest.get("file_count") != len(listed):
        bad("FILE_COUNT_MISMATCH",
            "declared %r, verified %d" % (manifest.get("file_count"),
                                          len(listed)))
    lines = "".join("%s  %s\n" % (r, files[r]) for r in sorted(files))
    if lib.sha256_bytes(lines.encode("utf-8")) != manifest["tree_sha256"]:
        bad("TREE_HASH_MISMATCH", "tree_sha256 does not match files table")
    try:
        physical = set(iter_tree_files(tree_prefix, root))
    except (lib.P4ContractError, OSError) as exc:
        bad("TREE_UNREADABLE", str(exc))
        physical = set()
    for rel in sorted(physical - listed - {self_excl}):
        bad("UNREGISTERED_FILE", "physical tree file absent from manifest: %s"
            % rel)
    return {
        "schema": SCHEMA_TREE_REPORT,
        "tree_prefix": tree_prefix,
        "ok": not violations,
        "violations": violations,
        "files_checked": len(listed & physical),
        "unregistered_count": len(physical - listed - {self_excl}),
    }


def verify_closed_tree(tree_prefix, root=None):
    """Load <tree_prefix>manifest.json (create-only closeout artifact) and
    verify it; the manifest bytes are rehashed independently (the 'independent
    parent hash' duty sits with the closeout report, which binds this value)."""
    tree_prefix = _normalize_tree_prefix(tree_prefix)
    manifest_rel = _self_exclusion_rel(tree_prefix)
    target = lib.resolve_under_root(manifest_rel, root)
    if not os.path.lexists(str(target)):
        raise lib.MissingInputError(
            "manifest not created (fail closed): %r" % manifest_rel)
    with open(str(target), "rb") as fh:
        raw = fh.read()
    manifest = lib.strict_json_loads(raw.decode("utf-8"), source=manifest_rel)
    report = verify_manifest(manifest, root)
    report["manifest_rel"] = manifest_rel
    report["manifest_sha256"] = lib.sha256_bytes(raw)
    return report


# ---------------------------------------------------------------------------
# Semantic gates: recompute from structured data, structured violation codes
# ---------------------------------------------------------------------------

def _walk_items(obj):
    """Yield (container, key, value) for every dict member at any depth."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield obj, key, value
            for item in _walk_items(value):
                yield item
    elif isinstance(obj, list):
        for element in obj:
            for item in _walk_items(element):
                yield item


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value == value and value not in (float("inf"), float("-inf"))


def _require_legal_present(value, violations):
    """present_frame_duration must be the analyzer's NOT_MEASURED struct, or
    a MEASURED struct bound to a legal ETW/PresentMon source; any bare number
    (IPC-derived or otherwise) is a structured violation."""
    ok = False
    if isinstance(value, dict) and "status" in value:
        if value["status"] == an.NOT_MEASURED:
            ok = True
        elif value["status"] == an.STATUS_MEASURED \
                and value.get("source") in LEGAL_PRESENT_SOURCES:
            ok = True
    if not ok:
        violations.append({
            "code": "PRESENT_FROM_NON_PRESENT_SOURCE",
            "detail": "present_frame_duration %r is neither the "
                      "NOT_MEASURED struct nor MEASURED with a legal source "
                      "in %s; IPC samples / time-pos deltas are never present "
                      "evidence" % (value, LEGAL_PRESENT_SOURCES)})


def verify_rife_proof(evidence, context, root=None):
    """F6 (B1-r2): structural verification of one RIFE proof bundle.

    Type + hash + real-file bindings + identity-pin comparison — keys that
    are present but empty (""/False/None/0) never pass, a hash without the
    actual file is not enough, and dll/model hashes may be a multi-hash
    object {role: sha256} compared against context['rife_identity_pins']
    (the survey pins runtime identities; sha pins arrive with the closeout
    flow). filter_fps_real must be a finite non-bool number equal to
    2x context['source_fps'] when the context provides it.

    This is deliberately STRICT STRUCTURE ONLY: it does not authenticate the
    dll/model bytes against a third party, it is never a RIFE-execution
    PASS by itself (fps is necessary-never-sufficient), and it deliberately
    does NOT assume the model must behave like linear interpolation — the
    real-inference negative controls stay defined by the approved plan
    (RIFE-01/B2), not invented here.

    context keys: source_fps (number), rife_identity_pins ({role: sha256}).
    Returns a list of structured violations.
    """
    violations = []
    if not isinstance(evidence, dict):
        return [{"code": "RIFE_PROOF_NOT_DICT",
                 "detail": "claim evidence must be a dict, got %s"
                           % type(evidence).__name__}]
    context = context if isinstance(context, dict) else {}
    source_fps = context.get("source_fps")
    pins = context.get("rife_identity_pins")

    hash_values = {}
    dmh = evidence.get("dll_model_hash")
    if isinstance(dmh, str):
        try:
            lib.require_sha256_hex(dmh, "dll_model_hash")
        except lib.ValueContractError as exc:
            violations.append({"code": "RIFE_PROOF_HASH_MALFORMED",
                               "detail": str(exc)})
        else:
            hash_values["dll_model"] = dmh
    elif isinstance(dmh, dict) and dmh:
        for role in sorted(dmh):
            try:
                lib.require_sha256_hex(dmh[role],
                                       "dll_model_hash[%s]" % role)
            except lib.ValueContractError as exc:
                violations.append({"code": "RIFE_PROOF_HASH_MALFORMED",
                                   "detail": str(exc)})
            else:
                hash_values[role] = dmh[role]
    else:
        violations.append({
            "code": "RIFE_PROOF_HASH_MALFORMED",
            "detail": "dll_model_hash must be a 64-hex sha256 string or a "
                      "non-empty {role: sha256} object; got %r" % (dmh,)})
    if isinstance(pins, dict) and pins:
        for role in sorted(pins):
            if role not in hash_values:
                violations.append({
                    "code": "RIFE_IDENTITY_PIN_UNCOVERED",
                    "detail": "identity pin role %r is not covered by the "
                              "dll_model_hash object (roles present: %s)"
                              % (role, sorted(hash_values))})
            elif hash_values[role] != pins[role]:
                violations.append({
                    "code": "RIFE_IDENTITY_PIN_MISMATCH",
                    "detail": "dll_model_hash[%s]=%s does not match the "
                              "pinned survey identity %s"
                              % (role, hash_values[role], pins[role])})

    ffr = evidence.get("filter_fps_real")
    if not _is_finite_number(ffr) or ffr <= 0:
        violations.append({
            "code": "RIFE_FPS_REAL_MALFORMED",
            "detail": "filter_fps_real must be a finite non-bool number "
                      "> 0 (real observed filter fps), got %r" % (ffr,)})
    elif _is_finite_number(source_fps) and ffr != 2 * source_fps:
        violations.append({
            "code": "RIFE_FPS_REAL_MISMATCH",
            "detail": "filter_fps_real=%r != 2x source fps %r"
                      % (ffr, source_fps)})

    for key in ("middle_frame_sample", "engine_log"):
        binding = evidence.get(key)
        if (not isinstance(binding, dict)
                or not isinstance(binding.get("rel"), str)
                or not isinstance(binding.get("sha256"), str)):
            violations.append({
                "code": "RIFE_PROOF_BINDING_MALFORMED",
                "detail": "%s must be a {rel, sha256} binding to a real "
                          "file inside the evidence tree, got %r"
                          % (key, binding)})
            continue
        rel = binding["rel"]
        try:
            lib.check_rel_path(rel)
            if not (rel == EVIDENCE_REL.rstrip("/")
                    or rel.startswith(EVIDENCE_REL)):
                raise lib.PathContractError(
                    "binding outside the evidence tree: %r" % rel)
        except lib.PathContractError as exc:
            violations.append({"code": "RIFE_PROOF_FILE_OUTSIDE_TREE",
                               "detail": "%s: %s" % (key, exc)})
            continue
        try:
            actual = lib.sha256_file(lib.resolve_under_root(rel, root))
        except (lib.P4ContractError, OSError) as exc:
            violations.append({"code": "RIFE_PROOF_FILE_MISSING",
                               "detail": "%s binding %r unreadable/absent "
                                         "(fail closed): %s" % (key, rel, exc)})
            continue
        if actual != binding["sha256"]:
            violations.append({
                "code": "RIFE_PROOF_FILE_HASH_MISMATCH",
                "detail": "%s binding %r declared=%s actual=%s"
                          % (key, rel, binding["sha256"], actual)})
    return violations


def scan_performance_claims(report, context=None, root=None):
    """Structured anti-metric scan of a result/report object (PER-05/EVI-01).

    Every rule is a structured contract check, not a natural-language verdict:
    speed-word claims without run_ids+CI, FPS-only RIFE proof, pacing claims
    without a legal present source, numeric 'overall headroom', vo=image
    masquerading as gpu-next shader proof or algorithm A/B, synthetic material
    masquerading as natural, machine-signed user acceptance.
    """
    violations = []
    if not isinstance(report, dict):
        return [{"code": "REPORT_NOT_DICT", "detail": type(report).__name__}]

    materials = {m.get("id"): m for m in report.get("materials", [])
                 if isinstance(m, dict)} \
        if isinstance(report.get("materials"), list) else {}
    for material in materials.values():
        if "kind" not in material or material["kind"] not in (
                "synthetic", "natural_licensed"):
            violations.append({
                "code": "MATERIAL_KIND_INVALID",
                "detail": "material %r kind must be 'synthetic' or "
                          "'natural_licensed'" % (material.get("id"),)})

    claims = report.get("claims", [])
    if not isinstance(claims, list):
        violations.append({"code": "CLAIMS_NOT_LIST",
                           "detail": type(claims).__name__})
        claims = []
    for claim in claims:
        if not isinstance(claim, dict):
            violations.append({"code": "CLAIM_NOT_DICT",
                               "detail": repr(claim)[:120]})
            continue
        text = str(claim.get("text", ""))
        topic = claim.get("topic", "")
        verdict = claim.get("verdict", "")
        evidence = claim.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        pass_like = verdict in _PASS_LIKE_VERDICTS
        if _SPEED_CLAIM_RE.search(text):
            run_ids = evidence.get("run_ids")
            has_ci = isinstance(evidence.get("ci"), dict) \
                and evidence["ci"]
            if not (isinstance(run_ids, list) and run_ids
                    and (has_ci or evidence.get("claim_kind")
                         == "no_difference")):
                violations.append({
                    "code": "CLAIM_WITHOUT_RUN_EVIDENCE",
                    "detail": "speed claim %r lacks run_ids + CI (or "
                              "claim_kind=no_difference)" % text[:120]})
        if topic == "rife" and pass_like:
            missing = [k for k in RIFE_PROOF_KEYS if k not in evidence]
            if missing:
                violations.append({
                    "code": "RIFE_FPS_ONLY_PROOF",
                    "detail": "RIFE PASS claim missing proof pieces %s; "
                              "observed fps alone is never sufficient"
                              % missing})
            else:
                violations += verify_rife_proof(evidence, context, root)
        if topic == "frame_pacing" and pass_like:
            present = evidence.get("present_frame_duration")
            legal = isinstance(present, dict) \
                and present.get("status") == an.STATUS_MEASURED \
                and present.get("source") in LEGAL_PRESENT_SOURCES
            if not legal:
                violations.append({
                    "code": "PACING_CLAIM_WITHOUT_PRESENT",
                    "detail": "frame-pacing PASS claim without a legal "
                              "present source %s" % (LEGAL_PRESENT_SOURCES,)})
        material_ids = evidence.get("material_ids", [])
        if _NATURAL_CLAIM_RE.search(text) and material_ids:
            kinds = [materials.get(mid, {}).get("kind") for mid in material_ids]
            if material_ids and all(k == "synthetic" for k in kinds):
                violations.append({
                    "code": "SYNTHETIC_AS_NATURAL",
                    "detail": "claim %r cites natural-sample semantics but "
                              "all referenced materials are synthetic"
                              % text[:120]})

    for container, key, value in _walk_items(report):
        if key in ("overall_headroom_ms", "headroom_ms") \
                and _is_finite_number(value):
            violations.append({
                "code": "PASS_SUM_AS_OVERALL_HEADROOM",
                "detail": "numeric %s=%r: no end-to-end/present time source "
                          "exists; per-pass sums are never an additive "
                          "RIFE headroom" % (key, value)})
        if key == "present_frame_duration":
            _require_legal_present(value, violations)
        if key in ("user_acceptance_claimed", "user_approval_claimed") \
                and value is True \
                and container.get("user_acceptance_source") != "human_user_signing":
            violations.append({
                "code": "MACHINE_SIGNED_USER_APPROVAL",
                "detail": "%s=true without user_acceptance_source="
                          "'human_user_signing'; scoring/default-choice "
                          "cannot be machine-signed" % key})

    captures = report.get("captures", [])
    if not isinstance(captures, list):
        captures = []
    for cap in captures:
        if not isinstance(cap, dict):
            continue
        purpose = cap.get("purpose")
        backend = cap.get("vo_backend")
        if purpose in ("algorithm_ab", "rife_ab") and backend == "image":
            violations.append({
                "code": "VO_IMAGE_AS_ALGORITHM_AB",
                "detail": "capture %r uses --vo=image for algorithm A/B; "
                          "plan PIC-04 requires a real gpu-next frame plus "
                          "same-source S-frame comparison" % cap.get("id")})
        if purpose in _SHADER_PURPOSES and backend not in _SHADER_VO_BACKENDS:
            violations.append({
                "code": "VO_IMAGE_AS_SHADER_PROOF",
                "detail": "capture %r purpose=%r must come from a real %s "
                          "screen frame, got vo_backend=%r (vo=image dumps "
                          "are never shader A/B evidence)"
                          % (cap.get("id"), purpose,
                             "/".join(_SHADER_VO_BACKENDS), backend)})
    return violations


def _rejected_run_ids(value):
    """Extract run_ids from one cell's rejected_by_analysis field.

    The REAL analyze_records/aggregate_cell schema (p4-analyze-result-v2)
    is a LIST of {run_id, status, reason, ...} entries (F3: treating it as
    a dict crashed on every real bundle). Legacy dict shapes are still
    traced by key so old archives stay checkable, but the canonical shape
    is the list and new tests bind the real analyzer output.
    """
    ids = set()
    if isinstance(value, dict):  # legacy shape, kept for old archives
        ids |= set(value.keys())
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict) and "run_id" in entry:
                ids.add(entry["run_id"])
            elif isinstance(entry, str):
                ids.add(entry)
    return ids


def check_exclusion_preservation(report, bundle):
    """Excluded/failed runs must stay visible in the analysis bundle; a
    report whose exclusions cannot be traced in the bundle loses the FAIL
    trail (EVI-01 negative control). Works on the REAL p4-analysis-bundle-v2
    shape (cells.rejected_by_analysis is a list of run entries; F3)."""
    violations = []
    exclusions = report.get("excluded_runs", [])
    if not isinstance(exclusions, list):
        return [{"code": "EXCLUDED_RUNS_NOT_LIST",
                 "detail": type(exclusions).__name__}]
    if not exclusions:
        return violations
    trace = set()
    for cell in (bundle or {}).get("cells", {}).values():
        trace |= set(cell.get("run_ids", ()))
        for run in cell.get("excluded_runs", []):
            trace.add(run.get("run_id") if isinstance(run, dict)
                      else run)
        trace |= _rejected_run_ids(cell.get("rejected_by_analysis"))
    for entry in exclusions:
        run_id = entry.get("run_id") if isinstance(entry, dict) else entry
        if run_id not in trace:
            violations.append({
                "code": "EXCLUDED_RUN_TRACE_LOST",
                "detail": "excluded run %r has no trace in the analysis "
                          "bundle (run_ids/excluded_runs/"
                          "rejected_by_analysis); failures are never "
                          "silently dropped" % (run_id,)})
    return violations


# ---------------------------------------------------------------------------
# Run-evidence gate: recompute + identity + fail-closed bindings
# ---------------------------------------------------------------------------

def _compare_analysis(stored, recomputed, violations):
    if stored.get("status") != recomputed.get("status"):
        violations.append({
            "code": "ANALYSIS_MISMATCH",
            "detail": "stored status %r vs recomputed %r"
                      % (stored.get("status"), recomputed.get("status"))})
    for frame in ("fresh", "redraw"):
        stored_passes = (stored.get("passes") or {}).get(frame, {})
        recomputed_passes = (recomputed.get("passes") or {}).get(frame, {})
        for desc in sorted(set(stored_passes) | set(recomputed_passes)):
            s = stored_passes.get(desc, {}).get("avg_ms_median")
            r = recomputed_passes.get(desc, {}).get("avg_ms_median")
            if s != r:
                violations.append({
                    "code": "ANALYSIS_MISMATCH",
                    "detail": "stored median %s/%s=%r vs recomputed %r — "
                              "stored results must be recomputable from the "
                              "raw structured data" % (frame, desc, s, r)})
    for key in ("fresh_ms", "redraw_ms"):
        s = (stored.get("pass_sum") or {}).get(key)
        r = (recomputed.get("pass_sum") or {}).get(key)
        if s != r:
            violations.append({
                "code": "ANALYSIS_MISMATCH",
                "detail": "pass_sum.%s stored=%r recomputed=%r"
                          % (key, s, r)})


def _load_bound_file(rel, declared_sha, violations, code_prefix, root):
    """Read one sha-bound file fail-closed: path contract + bytes + strict
    JSON. Returns the parsed object or None (violation already recorded)."""
    try:
        target = lib.resolve_under_root(rel, root)
        with open(str(target), "rb") as fh:
            raw = fh.read()
    except (lib.P4ContractError, OSError) as exc:
        violations.append({"code": code_prefix + "_UNREADABLE",
                           "detail": "%r: %s" % (rel, exc)})
        return None
    actual = lib.sha256_bytes(raw)
    if declared_sha is not None and actual != declared_sha:
        violations.append({
            "code": code_prefix + "_SHA_MISMATCH",
            "detail": "%r declared=%s actual=%s — bindings are rehashed, "
                      "never trusted" % (rel, declared_sha, actual)})
        return None
    try:
        return lib.strict_json_loads(raw.decode("utf-8"), source=rel), raw
    except lib.P4ContractError as exc:
        violations.append({"code": code_prefix + "_NOT_STRICT_JSON",
                           "detail": "%r: %s" % (rel, exc)})
        return None


def gate_trial_report(report, root=None):
    """F2 (B1-r2): qualify one trial stage report against its bound raw
    evidence. A self-declared status is never trusted:

    - the report must carry the known schema p4-trial-stage-report-v1
      (unknown schema / bare trial.json is a violation, never an upgrade);
    - every run binding is rehashed (declared sha must match the real
      bytes), the record is re-validated and RE-ANALYZED here via the W1b
      library, and an optional stored analysis must match the
      recomputation byte-for-struct (ANALYSIS_MISMATCH on drift);
    - a trial with NO bound evidence (no runs, no analysis bundle) is a
      violation — missing raw evidence can never upgrade any test item;
    - runs marked test_fixture carry ZERO measurement credit (they exist
      only to exercise code branches) and can never back a pass;
    - the declared status is earned only when at least one real
      (non-fixture) run re-analyzes VALID here and no violations exist.

    Returns {schema, ok, status (earned per-test status), violations,
    info (preserved rejected/fixture runs), n_valid_runs,
    n_fixture_runs, measured (bool: real non-fixture valid runs exist)}.
    """
    violations = []
    info = []
    if not isinstance(report, dict):
        return {"schema": SCHEMA_TRIAL_GATE, "ok": False, "status": "FAIL",
                "violations": [{"code": "TRIAL_REPORT_NOT_DICT",
                                "detail": type(report).__name__}],
                "info": [], "n_valid_runs": 0, "n_fixture_runs": 0,
                "measured": False}
    if report.get("schema") != SCHEMA_TRIAL_REPORT:
        violations.append({
            "code": "TRIAL_SCHEMA_UNKNOWN",
            "detail": "schema %r is not %r; a trial without the known "
                      "schema and bound raw evidence cannot upgrade any "
                      "test item"
                      % (report.get("schema"), SCHEMA_TRIAL_REPORT)})
        return {"schema": SCHEMA_TRIAL_GATE, "ok": False, "status": "FAIL",
                "violations": violations, "info": [], "n_valid_runs": 0,
                "n_fixture_runs": 0, "measured": False}
    keys = set(report)
    missing = sorted(set(TRIAL_REPORT_REQUIRED) - keys)
    extra = sorted(keys - set(TRIAL_REPORT_REQUIRED)
                   - set(TRIAL_REPORT_OPTIONAL))
    if missing or extra:
        violations.append({"code": "TRIAL_REPORT_KEYS_MISMATCH",
                           "detail": "missing=%s extra=%s"
                                     % (missing, extra)})
    if "plan_sha256" in report and report["plan_sha256"] != PLAN_SHA256:
        violations.append({"code": "TRIAL_PLAN_BINDING",
                           "detail": repr(report["plan_sha256"])})

    runs = report.get("runs", [])
    if not isinstance(runs, list):
        violations.append({"code": "TRIAL_RUNS_NOT_LIST",
                           "detail": type(runs).__name__})
        runs = []
    n_valid = 0
    n_fixture = 0
    pins = report.get("rife_identity_pins")
    context = {"rife_identity_pins": pins} if isinstance(pins, dict) else {}
    for pos, binding in enumerate(runs):
        if not isinstance(binding, dict):
            violations.append({"code": "TRIAL_RUN_BINDING_NOT_DICT",
                               "detail": "runs[%d]: %r" % (pos, binding)})
            continue
        entry_keys = set(binding)
        if (sorted(set(TRIAL_RUN_REQUIRED) - entry_keys)
                or sorted(entry_keys - set(TRIAL_RUN_REQUIRED)
                          - set(TRIAL_RUN_OPTIONAL))):
            violations.append({
                "code": "TRIAL_RUN_KEYS_MISMATCH",
                "detail": "runs[%d] missing=%s extra=%s"
                          % (pos, sorted(set(TRIAL_RUN_REQUIRED)
                                         - entry_keys),
                             sorted(entry_keys - set(TRIAL_RUN_REQUIRED)
                                    - set(TRIAL_RUN_OPTIONAL)))})
            continue
        is_fixture = binding.get("test_fixture") is True
        rel = binding["run_rel"]
        if not (rel == EVIDENCE_REL.rstrip("/")
                or rel.startswith(EVIDENCE_REL)):
            violations.append({"code": "TRIAL_RUN_OUTSIDE_TREE",
                               "detail": "runs[%d] %r is outside the "
                                         "evidence tree" % (pos, rel)})
            continue
        loaded = _load_bound_file(rel, binding["run_sha256"], violations,
                                  "TRIAL_RUN", root)
        if loaded is None:
            continue
        record, _raw = loaded
        try:
            spec = an.validate_run_record(record)
        except lib.P4ContractError as exc:
            violations.append({"code": "RUN_RECORD_INVALID",
                               "detail": "%s: %s" % (rel, exc)})
            continue
        try:
            analysis = an.analyze_run(record)
        except lib.P4ContractError as exc:
            violations.append({"code": "RUN_ANALYSIS_RAISED",
                               "detail": "%s: %s" % (rel, exc)})
            continue
        if analysis["status"] == an.RUN_STATUS_VALID:
            if is_fixture:
                n_fixture += 1
                info.append({"run_rel": rel, "run_id": record["run_id"],
                             "test_fixture": True,
                             "note": "fixture run: zero measurement credit, "
                                     "never stage-qualifying"})
            else:
                n_valid += 1
                context.setdefault("source_fps", spec["source_fps"])
        else:
            info.append({"run_rel": rel, "run_id": record["run_id"],
                         "status": analysis["status"],
                         "reason": analysis.get("reason"),
                         "test_fixture": is_fixture,
                         "note": "rejected run preserved; cannot back any "
                                 "pass claim"})
        stored_rel = binding.get("stored_analysis_rel")
        if stored_rel is not None:
            stored = _load_bound_file(
                stored_rel, binding.get("stored_analysis_sha256"),
                violations, "TRIAL_STORED_ANALYSIS", root)
            if stored is not None:
                _compare_analysis(stored[0], analysis, violations)

    bundle_rel = report.get("analysis_bundle_rel")
    if bundle_rel is not None:
        loaded = _load_bound_file(bundle_rel,
                                  report.get("analysis_bundle_sha256"),
                                  violations, "TRIAL_ANALYSIS_BUNDLE", root)
        if loaded is not None:
            bundle, _raw = loaded
            if bundle.get("schema") != an.BUNDLE_SCHEMA:
                violations.append({
                    "code": "BUNDLE_SCHEMA_UNKNOWN",
                    "detail": "analysis bundle schema %r is not %r"
                              % (bundle.get("schema"), an.BUNDLE_SCHEMA)})
            else:
                violations += check_exclusion_preservation(report, bundle)

    if not runs and bundle_rel is None:
        violations.append({
            "code": "TRIAL_NO_BOUND_EVIDENCE",
            "detail": "no raw run records and no analysis bundle are "
                      "bound; a trial without raw evidence can never "
                      "upgrade any test item"})
    if n_fixture and not n_valid:
        violations.append({
            "code": "FIXTURE_AS_STAGE_EVIDENCE",
            "detail": "%d bound run(s) are marked test_fixture and zero "
                      "real runs re-analyzed VALID; fixture runs exercise "
                      "code branches and never qualify a stage item"
                      % n_fixture})

    declared = report.get("status")
    measured = n_valid > 0
    if declared in _PASS_LIKE_VERDICTS and not measured:
        violations.append({
            "code": "TRIAL_STATUS_NOT_EARNED",
            "detail": "declared %r but zero real (non-fixture) runs "
                      "re-analyzed VALID; declared status is never "
                      "trusted over recomputation" % (declared,)})
    if violations:
        status = "FAIL"
    elif not measured:
        # e.g. all bound runs rejected/preserved, or only fixtures: nothing
        # measured here, so a non-pass declared status can stand honestly.
        status = declared if declared in PER_TEST_VOCAB else "PARTIAL_MEASURED"
    elif declared in PER_TEST_VOCAB:
        status = declared
    else:
        status = "PARTIAL_MEASURED"
    return {"schema": SCHEMA_TRIAL_GATE, "ok": not violations,
            "status": status, "violations": violations, "info": info,
            "n_valid_runs": n_valid, "n_fixture_runs": n_fixture,
            "measured": measured}


def gate_run_evidence(record, stored_analysis=None, pngs=None, root=None):
    """Full gate for one trial run's evidence.

    Recomputes the W1b analysis from the raw structured record, enforces the
    production lock, checks required input bindings fail-closed, verifies
    PNG frame identity via the W1a decoder recheck, and (optionally)
    compares a stored analysis result against the recomputation. Structural
    crimes from the frozen libraries surface as structured violations, never
    as silent skips. Zero-timing/empty-table windows are flagged by the
    analyzer's typed rejections (REJECTED_PASS_NO_TIMING /
    REJECTED_PASS_TABLE_EMPTY, F1) which travel in `info` as preserved,
    never-measured run statuses — a stored VALID claim over them is an
    ANALYSIS_MISMATCH violation. (The old local ALL_ZERO_PASS duplicate was
    superseded by these typed rejections.)
    """
    violations = []
    info = []
    spec = None
    try:
        spec = an.validate_run_record(record)
    except lib.P4ContractError as exc:
        violations.append({"code": "RUN_RECORD_INVALID",
                           "detail": str(exc)})
    if spec is not None:
        if spec["run_kind"] == "production":
            violations.append({
                "code": "PRODUCTION_LOCK_VIOLATED",
                "detail": "run_kind='production' is locked at this library "
                          "revision; unlocking requires a later "
                          "pre-registered revision with B4 evidence"})
        try:
            lib.verify_required_inputs(spec, root)
        except lib.P4ContractError as exc:
            violations.append({
                "code": "MISSING_INPUT_DEPENDENCY",
                "detail": "required trial inputs absent (fail closed): %s"
                          % exc})
        try:
            analysis = an.analyze_run(record)
        except lib.P4ContractError as exc:
            violations.append({"code": "RUN_ANALYSIS_RAISED",
                               "detail": str(exc)})
        else:
            if analysis["status"] != an.RUN_STATUS_VALID:
                info.append({"run_id": record.get("run_id"),
                             "status": analysis["status"],
                             "reason": analysis.get("reason")})
            if stored_analysis is not None:
                _compare_analysis(stored_analysis, analysis, violations)
    for rel, want in sorted((pngs or {}).items()):
        try:
            with open(str(lib.resolve_under_root(rel, root)), "rb") as fh:
                data = fh.read()
            lib.verify_png_frame(data, want["clip"], want["index"])
        except (lib.P4ContractError, OSError) as exc:
            violations.append({
                "code": "PNG_IDENTITY_MISMATCH",
                "detail": "%s (clip=%r index=%r): %s"
                          % (rel, want.get("clip"), want.get("index"), exc)})
    return {"schema": SCHEMA_RUN_GATE, "ok": not violations,
            "violations": violations, "info": info}


# ---------------------------------------------------------------------------
# Candidate binding + exact write-path closure
# ---------------------------------------------------------------------------

def expected_candidate_dependencies(plan):
    """F9 (B1-r2): the explicit dependency list every candidate must pin
    beyond author-chosen source pins — every plan write path plus the
    plan-bound inputs (authorization brief, baseline, authorization).
    Reconciled by gate_candidate; a candidate that pins only its own sources
    while omitting plan attachments/fixtures cannot pass."""
    rels = set(plan.get("write_paths", [])) if isinstance(plan, dict) else set()
    binding = plan.get("binding", {}) if isinstance(plan, dict) else {}
    if isinstance(binding, dict):
        for key in ("authorization", "brief", "baseline"):
            rel = binding.get(key)
            if isinstance(rel, str):
                rels.add(rel)
    return sorted(rels)


def gate_candidate(candidate, root=None, expected_dependencies=None,
                  final_candidate=False, plan=None):
    """Candidate/source-pin binding gate: the candidate file must exist with
    the declared sha (no stitching a different candidate or an old failed
    positive), every pinned source file is rehashed, plan binding matches,
    and author/independent trees are separate directories.

    F9 (B1-r2): non-empty source_pins is no longer enough — when
    expected_dependencies (rels or {rel: sha256}) is given, every listed
    dependency must be pinned in candidate.source_hashes (checked against
    the real file bytes); with final_candidate=True and the plan object,
    the exact plan write-path closure is enforced here too, so a FINAL
    candidate can never skip a planned file with is_file()==False."""
    violations = []
    expected_keys = {"schema", "candidate_rel", "candidate_sha256",
                     "source_hashes", "author_tree", "independent_tree",
                     "plan_sha256"}
    if not isinstance(candidate, dict) or set(candidate) != expected_keys:
        missing = sorted(expected_keys - set(candidate or {}))
        extra = sorted(set(candidate or {}) - expected_keys)
        return [{"code": "CANDIDATE_KEYS_MISMATCH",
                 "detail": "missing=%s extra=%s" % (missing, extra)}]
    try:
        target = lib.resolve_under_root(candidate["candidate_rel"], root)
        if not target.is_file():
            raise lib.MissingInputError("not a file")
        actual = lib.sha256_file(target)
    except (lib.P4ContractError, OSError) as exc:
        violations.append({"code": "CANDIDATE_MISSING",
                           "detail": "%s: %s" % (candidate["candidate_rel"],
                                                 exc)})
    else:
        if actual != candidate["candidate_sha256"]:
            violations.append({
                "code": "CANDIDATE_HASH_MISMATCH",
                "detail": "declared %s actual %s (stitching a different "
                          "candidate is forbidden)"
                          % (candidate["candidate_sha256"], actual)})
    if candidate["plan_sha256"] != PLAN_SHA256:
        violations.append({"code": "CANDIDATE_PLAN_BINDING",
                           "detail": repr(candidate["plan_sha256"])})
    if candidate["author_tree"] == candidate["independent_tree"]:
        violations.append({
            "code": "AUTHOR_INDEPENDENT_TREE_NOT_SEPARATED",
            "detail": "author tree and independent re-run tree must be "
                      "distinct create-only directories"})
    source_hashes = candidate["source_hashes"]
    if not isinstance(source_hashes, dict) or not source_hashes:
        violations.append({"code": "SOURCE_PINS_EMPTY",
                           "detail": repr(source_hashes)})
    else:
        if expected_dependencies:
            for rel in sorted(expected_dependencies):
                if rel not in source_hashes:
                    violations.append({
                        "code": "CANDIDATE_COVERAGE_MISSING",
                        "detail": "%s is an expected dependency (plan write "
                                  "path / plan-bound input / fixture) but is "
                                  "not pinned in candidate.source_hashes"
                                  % rel})
        for rel in sorted(source_hashes):
            try:
                target = lib.resolve_under_root(rel, root)
                actual = lib.sha256_file(target)
            except (lib.P4ContractError, OSError) as exc:
                violations.append({"code": "SOURCE_PIN_MISSING",
                                   "detail": "%s: %s" % (rel, exc)})
                continue
            if actual != source_hashes[rel]:
                violations.append({
                    "code": "SOURCE_PIN_HASH_MISMATCH",
                    "detail": "%s declared=%s actual=%s (any change "
                              "invalidates bound evidence)"
                              % (rel, source_hashes[rel], actual)})
    if final_candidate and isinstance(plan, dict):
        for entry in check_write_paths(plan, root=root, final_candidate=True):
            if entry["violation"]:
                violations.append({
                    "code": "CANDIDATE_WRITE_PATH_NOT_CLOSED",
                    "detail": "%s: %s" % (entry["rel"], entry["violation"])})
    return violations


def check_write_paths(plan, root=None, final_candidate=False, pending=()):
    """Exact write-path closure against the plan. A not-yet-created path may
    only be declared pending in a stage report; a FINAL candidate can never
    excuse a missing write path with is_file()==False (fail closed)."""
    entries = []
    pending = set(pending)
    for rel in plan.get("write_paths", []):
        try:
            target = lib.resolve_under_root(rel, root)
            exists = os.path.lexists(str(target))
        except lib.P4ContractError as exc:
            entries.append({"rel": rel, "exists": False,
                            "violation": "PATH_CONTRACT: %s" % exc})
            continue
        if exists:
            entries.append({"rel": rel, "exists": True, "violation": None})
        elif final_candidate:
            entries.append({
                "rel": rel, "exists": False,
                "violation": "MISSING_WRITE_PATH: final candidate cannot "
                             "skip a plan write path that was never created"})
        elif rel in pending:
            entries.append({"rel": rel, "exists": False,
                            "violation": None,
                            "note": "declared pending in stage report"})
        else:
            entries.append({
                "rel": rel, "exists": False,
                "violation": "UNDECLARED_MISSING_WRITE_PATH: declare it "
                             "pending in the stage report or create it"})
    return entries


def synthesize_stage_status(per_test, required_tests):
    """Plan status_vocabulary rule: any FAIL -> REWORK; any 未测/PENDING/
    BLOCKED/PARTIAL -> PARTIAL_MEASURED; even all-PASS cannot exceed the
    pre-registered stage cap (TIME-01 present source + natural material)."""
    if set(per_test) != set(required_tests):
        raise lib.ValueContractError(
            "per_test statuses must cover exactly %s" % (sorted(required_tests),))
    for test_id, status in per_test.items():
        if status not in PER_TEST_VOCAB:
            raise lib.ValueContractError(
                "per-test status %r for %s outside vocabulary %s"
                % (status, test_id, PER_TEST_VOCAB))
    notes = []
    if any(s == "FAIL" for s in per_test.values()):
        return "REWORK", notes
    if all(s == "PASS_OBJECTIVE" for s in per_test.values()):
        notes.append(STAGE_CAP_NOTE)
        return STAGE_CAP, notes
    if any(s in ("未测", "PARTIAL_MEASURED", "PENDING_USER", "BLOCKED_ENV")
           for s in per_test.values()):
        return "PARTIAL_MEASURED", notes
    return "REWORK", notes  # unreachable given the vocabulary


def api_manifest():
    """Sorted 'name(signature)' list of this module's public functions."""
    module = sys.modules[__name__]
    out = []
    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if inspect.isfunction(obj) and obj.__module__ == __name__:
            out.append("%s%s" % (name, inspect.signature(obj)))
    return out
