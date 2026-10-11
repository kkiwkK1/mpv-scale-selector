# -*- coding: utf-8 -*-
"""P4 stage verifier CLI (W1c): required-test coverage + status vocabulary +
binding consistency for session p4-001.

Contract (docs/P4/P4-B1纯工具实现brief.md, W1c):
- Validates EXISTING directories only. It never starts mpv/GPU/VS, never
  performs the official measurement, and never writes live configuration.
- Loads the plan JSON fail-closed: the file bytes must hash exactly to the
  session plan sha (lib.PLAN_SHA256) before anything else is trusted.
- Checks the machine work permit (status/plan binding/test-id set/locks).
- Discovers trial.json evidence files under the create-only evidence tree;
  every discovered report is pushed through the p4_check_evidence semantic
  gates. Anything not actually measured stays 未测 (NOT_RUN) — this CLI can
  never fabricate thirteen passes.
- Synthesizes the stage status per plan status_vocabulary, honoring the
  pre-registered PARTIAL_MEASURED cap; TIME-01 can only pass with a legal
  present source (ETW/PresentMon), never from IPC samples.

B1-r2 (docs/P4/P4-B1限域修正brief-v2.md, unit B):
- F2: every trial.json is qualified through p4_check_evidence.
  gate_trial_report — known schema + sha-bound raw run records that are
  re-analyzed here; a self-declared PASS is never trusted; fixture runs
  carry zero credit; unknown schema / unbound reports are violations.
- F7: the stage report discloses n_measured and measurement_status; a
  zero-measurement stage says so (PARTIAL_MEASURED is the plan-vocabulary
  floor, NOT evidence of partial measurement; ok=true only means the
  verifier found no violations, never a measurement acceptance).
- F9: the candidate/coverage/closed-tree gates are actually invoked by
  this entry; with no candidate present the honest output is
  BLOCKED_MISSING_CANDIDATE (NOT_RUN), never a fabricated pass; missing
  plan write paths are declared stage-pending explicitly (a FINAL
  candidate would fail closed instead).
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys

import p4_lib as lib              # frozen W1a dependency (read-only use)
import p4_analyze as an           # frozen W1b dependency (read-only use)
import p4_check_evidence as ce    # W1c gate library (this unit)

STAGE = lib.STAGE
SESSION = lib.SESSION
PLAN_SHA256 = lib.PLAN_SHA256
PLAN_REL = lib.PLAN_REL
WORK_PERMIT_REL = lib.WORK_PERMIT_REL
EVIDENCE_REL = ce.EVIDENCE_REL
TRIAL_FILENAME = "trial.json"
SCHEMA_STAGE_REPORT = ce.SCHEMA_STAGE_REPORT
VERIFIED_BY = "tools/p4_verify.py (W1c)"
CLI_CONTRACT = ("validates existing directories only; never starts mpv/GPU/"
                "VS; never performs the official measurement; never writes "
                "live configuration")
CANDIDATE_REL = ce.EVIDENCE_REL + "candidate.json"
OK_SEMANTICS = ("ok=true only means the verifier found no violations in "
                "what exists; it is never a measurement acceptance and "
                "never a P4 PASS")
ZERO_MEASUREMENT_NOTE = (
    "n_measured=0: the PARTIAL_MEASURED stage status reflects the plan "
    "status-vocabulary floor, NOT the existence of partial measurements; "
    "nothing has been measured yet")


def load_plan(root=None):
    """Read the session plan fail-closed: byte hash must equal PLAN_SHA256."""
    target = lib.resolve_under_root(PLAN_REL, root)
    with open(str(target), "rb") as fh:
        raw = fh.read()
    actual = lib.sha256_bytes(raw)
    if actual != PLAN_SHA256:
        raise lib.P4ContractError(
            "plan bytes sha256 %s do not bind session plan %s (fail closed)"
            % (actual, PLAN_SHA256))
    return lib.strict_json_loads(raw.decode("utf-8"), source=PLAN_REL)


def check_work_permit(root=None):
    """Machine work-permit gate: status PASS, plan/stage/session binding,
    identical required-test id set, and the live-write/human-claim locks."""
    violations = []
    try:
        target = lib.resolve_under_root(WORK_PERMIT_REL, root)
        with open(str(target), "rb") as fh:
            raw = fh.read()
        permit = lib.strict_json_loads(raw.decode("utf-8"),
                                       source=WORK_PERMIT_REL)
    except (lib.P4ContractError, OSError) as exc:
        return [{"code": "WORK_PERMIT_UNREADABLE", "detail": str(exc)}]
    if permit.get("status") != "PASS":
        violations.append({"code": "WORK_PERMIT_NOT_PASS",
                           "detail": repr(permit.get("status"))})
    if permit.get("plan_sha256") != PLAN_SHA256:
        violations.append({"code": "WORK_PERMIT_PLAN_BINDING",
                           "detail": repr(permit.get("plan_sha256"))})
    if permit.get("stage") != STAGE or permit.get("session") != SESSION:
        violations.append({"code": "WORK_PERMIT_STAGE_SESSION",
                           "detail": "%r/%r" % (permit.get("stage"),
                                                permit.get("session"))})
    if permit.get("live_configuration_write_allowed") is not False:
        violations.append({"code": "WORK_PERMIT_LIVE_WRITE_LOCK",
                           "detail": "live_configuration_write_allowed must "
                                     "be false"})
    if permit.get("human_subjective_acceptance_claimed") is not False:
        violations.append({"code": "WORK_PERMIT_HUMAN_CLAIM_LOCK",
                           "detail": "human_subjective_acceptance_claimed "
                                     "must be false"})
    return violations


def discover_trial_reports(root=None):
    """Find trial.json files in the evidence tree (symlink/reparse rejected
    by the tree walker). Returns sorted rel paths; a missing tree yields []
    (nothing measured yet), but a corrupt/hostile tree propagates fail-closed."""
    try:
        rels = ce.iter_tree_files(EVIDENCE_REL, root)
    except lib.MissingInputError:
        return []
    return [rel for rel in rels
            if rel.rsplit("/", 1)[-1] == TRIAL_FILENAME]


def verify_stage(root=None):
    """Full stage report: plan gate, work-permit gate, per-test statuses
    from REAL re-qualified trial evidence (default: every required test
    未测), candidate/coverage/closed-tree gates, stage synthesis under the
    pre-registered cap with explicit zero-measurement disclosure.
    Read-only over the workspace."""
    violations = []
    notes = []
    plan = load_plan(root)
    required = list(plan["required_tests"])
    per_test = {test_id: "未测" for test_id in required}
    trial_reports = {}
    measured_tests = set()
    for rel in discover_trial_reports(root):
        try:
            with open(str(lib.resolve_under_root(rel, root)), "rb") as fh:
                raw = fh.read()
            report = lib.strict_json_loads(raw.decode("utf-8"), source=rel)
        except (lib.P4ContractError, OSError) as exc:
            violations.append({"code": "TRIAL_REPORT_UNREADABLE",
                               "detail": "%s: %s" % (rel, exc)})
            continue
        test_id = report.get("test_id") if isinstance(report, dict) else None
        if test_id not in per_test:
            violations.append({
                "code": "TRIAL_TEST_ID_UNKNOWN",
                "detail": "%s declares test_id %r outside the plan's "
                          "required tests" % (rel, test_id)})
            continue
        if per_test[test_id] != "未测":
            violations.append({
                "code": "TRIAL_TEST_ID_DUPLICATE",
                "detail": "%s re-reports %s which already has trial "
                          "evidence; stitching multiple reports per test is "
                          "forbidden" % (rel, test_id)})
            per_test[test_id] = "FAIL"
            trial_reports[rel] = {"test_id": test_id, "status": "FAIL",
                                  "violations": []}
            continue
        # F2: the trial qualifies only through bound raw evidence that is
        # rehashed, re-validated and re-analyzed here (never the declared
        # status); the anti-metric scan runs with the trial's own context.
        gate = ce.gate_trial_report(report, root=root)
        gate_violations = list(gate["violations"])
        gate_violations += ce.scan_performance_claims(
            report, context={"rife_identity_pins":
                             report.get("rife_identity_pins")}, root=root)
        status = gate["status"]
        if gate_violations:
            status = "FAIL"
        if status == "PASS_OBJECTIVE" and test_id == "TIME-01":
            # Real present source is preregistered-missing; only a legal
            # ETW/PresentMon-sourced MEASURED struct can keep the PASS.
            present = report.get("present_frame_duration")
            legal = isinstance(present, dict) \
                and present.get("status") == an.STATUS_MEASURED \
                and present.get("source") in ce.LEGAL_PRESENT_SOURCES
            if not legal:
                status = "PARTIAL_MEASURED"
        if gate["measured"] and status != "FAIL":
            measured_tests.add(test_id)
        per_test[test_id] = status
        trial_reports[rel] = {"test_id": test_id, "status": status,
                              "violations": gate_violations,
                              "n_valid_runs": gate["n_valid_runs"],
                              "n_fixture_runs": gate["n_fixture_runs"],
                              "info": gate["info"]}
        violations += [{"code": v["code"],
                        "detail": "%s: %s" % (rel, v["detail"])}
                       for v in gate_violations]

    # F9: candidate gate — BLOCKED_MISSING_CANDIDATE until the collector /
    # closeout flow writes the candidate (never a fabricated pass), full
    # rehash + dependency-coverage reconciliation when it exists.
    candidate_violations = []
    candidate_status = "BLOCKED_MISSING_CANDIDATE"
    try:
        target = lib.resolve_under_root(CANDIDATE_REL, root)
    except lib.PathContractError as exc:
        candidate_violations.append({"code": "CANDIDATE_PATH_CONTRACT",
                                     "detail": str(exc)})
        target = None
    if target is not None and os.path.lexists(str(target)):
        try:
            with open(str(target), "rb") as fh:
                raw_bytes = fh.read()
            candidate = lib.strict_json_loads(raw_bytes.decode("utf-8"),
                                              source=CANDIDATE_REL)
            candidate_violations = ce.gate_candidate(
                candidate, root=root,
                expected_dependencies=ce.expected_candidate_dependencies(plan))
            candidate_status = ("VERIFIED" if not candidate_violations
                                else "VIOLATIONS")
        except (lib.P4ContractError, OSError) as exc:
            candidate_violations.append({"code": "CANDIDATE_UNREADABLE",
                                         "detail": str(exc)})
            candidate_status = "VIOLATIONS"

    # F9: exact write-path coverage; stage scope explicitly declares the
    # not-yet-created paths pending (a FINAL candidate would fail closed).
    coverage = ce.check_write_paths(plan, root=root, final_candidate=False)
    stage_pending = [e["rel"] for e in coverage if not e["exists"]]
    if stage_pending:
        coverage = ce.check_write_paths(plan, root=root, final_candidate=False,
                                        pending=stage_pending)

    # F9: closed-tree gate — verified when the closeout manifest exists,
    # honestly NOT_CREATED before that (create-only; this CLI creates
    # nothing).
    closedtree_status = "NOT_CREATED"
    closedtree_violations = []
    try:
        closedtree = ce.verify_closed_tree(ce.EVIDENCE_REL, root=root)
    except lib.MissingInputError:
        closedtree = None
    except lib.P4ContractError as exc:
        closedtree = None
        closedtree_violations.append({"code": "CLOSED_TREE_UNREADABLE",
                                      "detail": str(exc)})
    if closedtree is not None:
        closedtree_status = "VERIFIED" if closedtree["ok"] else "VIOLATIONS"
        closedtree_violations += closedtree["violations"]

    stage_status, notes = ce.synthesize_stage_status(per_test, required)
    permit_violations = check_work_permit(root)
    n_measured = len(measured_tests)
    measurement_status = ("NOT_RUN" if n_measured == 0
                          else an.STATUS_PARTIAL)
    if n_measured == 0:
        notes.append(ZERO_MEASUREMENT_NOTE)
    report = {
        "schema": SCHEMA_STAGE_REPORT,
        "stage": STAGE,
        "session": SESSION,
        "plan_sha256": PLAN_SHA256,
        "verified_by": VERIFIED_BY,
        "cli_contract": CLI_CONTRACT,
        "required_tests": required,
        "per_test": per_test,
        "trial_reports": trial_reports,
        "stage_status": stage_status,
        "n_measured": n_measured,
        "measurement_status": measurement_status,
        "ok_semantics": OK_SEMANTICS,
        "candidate_rel": CANDIDATE_REL,
        "candidate_status": candidate_status,
        "closed_tree_status": closedtree_status,
        "write_path_coverage": coverage,
        "stage_pending_write_paths": stage_pending,
        "notes": notes,
        "work_permit_violations": permit_violations,
        "violations": violations + candidate_violations
                      + closedtree_violations,
        "ok": not violations and not permit_violations
              and not candidate_violations and not closedtree_violations,
        "performance_conclusion": an.PERFORMANCE_CONCLUSION,
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="P4 stage verifier: read-only existing-directory "
                    "validation (no GPU, no measurement, no config writes)")
    parser.add_argument("--json", action="store_true",
                        help="print the full stage report JSON (default)")
    args = parser.parse_args(argv)
    try:
        report = verify_stage()
    except (lib.P4ContractError, OSError) as exc:
        sys.stderr.write("p4_verify: fail-closed: %s\n" % exc)
        return 3
    except Exception as exc:  # F3: unexpected errors fail closed, loudly
        fallback = {
            "schema": SCHEMA_STAGE_REPORT,
            "stage": STAGE,
            "session": SESSION,
            "plan_sha256": PLAN_SHA256,
            "verified_by": VERIFIED_BY,
            "stage_status": "REWORK",
            "ok": False,
            "ok_semantics": OK_SEMANTICS,
            "measurement_status": "NOT_RUN",
            "n_measured": 0,
            "unexpected_exception": {"type": type(exc).__name__,
                                     "detail": str(exc)[:400]},
        }
        print(json.dumps(fallback, ensure_ascii=False, indent=1,
                         sort_keys=True))
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    bad = bool(report["violations"]) or bool(report["work_permit_violations"])
    return 2 if bad else 0


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


if __name__ == "__main__":
    sys.exit(main())
