# -*- coding: utf-8 -*-
"""P4 unit tests for the W1c evidence/stage gates (session p4-001, B1 W1c;
migrated to the B1-r2 analysis contracts by unit B).

Every negative case really invokes the gate code (no hand-set booleans):
deleted listed files fail the manifest closed, unregistered/extra tree files
are caught, out-of-bounds manifest entries (../, absolute, outside-prefix)
are rejected, symlink/junction trees are rejected, manifest tampering and
arbitrary-exclude escapes fail, missing manifests raise instead of skipping,
fake/thumbnail PNGs fail frame identity, wrong gear (arm not in the
preregistered registry) is rejected, wrong/duplicate/missing windows are
rejected, production specs stay locked, tampered stored analyses must match
recomputation from raw data, vo=image-as-shader/algorithm-A/B,
synthetic-as-natural, machine-signed user approval, per-pass-sum-as-overall
headroom, IPC-samples-as-present, and lost exclusion/FAIL traces all produce
their structured violation codes. The stage synthesizer honors the plan
status vocabulary and the pre-registered PARTIAL_MEASURED cap; p4_verify
validates existing directories only.

B1-r2 migration + new counterexamples (each really invokes the gate; the
original negative intent of every pre-r2 test is preserved, never deleted or
weakened — fixtures moved to the REAL v2 sampling contract: LF10
count+samples_ns arrays, F4 warmup_end anchor + 1 Hz slot schedule ±0.25s,
F5 source/geometry observations, F6 per-stratum observed_output_fps):
  * F1/F-run gate: blank pass tables and zero-timing windows surface as the
    analyzer's typed rejections (REJECTED_PASS_TABLE_EMPTY /
    REJECTED_PASS_NO_TIMING) in the preserved run info; a stored VALID claim
    over them is an ANALYSIS_MISMATCH; a legal empty redraw table stays
    VALID with an unmeasured (None, never 0) redraw pass sum;
  * F2: only schema-bound trials whose raw runs are rehashed, re-validated
    and RE-analyzed here can earn a per-test status; a bare trial.json, an
    unknown schema, an unbound report, tampered run/stored-analysis bytes,
    and fixture-only evidence are violations, never upgrades;
  * F3: exclusion preservation works on the REAL p4-analysis-bundle-v2 shape
    (rejected_by_analysis is a list of run entries) using real
    analyze_records output, and p4_verify.main fails closed (structured
    REWORK, rc 3) on unexpected exceptions;
  * F6: RIFE four-piece proofs are type/hash/file/pin verified through
    verify_rife_proof with root/context — garbage values ("", False, None,
    0) can never pass, files must really exist inside the evidence tree
    with matching hashes, dll/model multi-hash objects are compared against
    identity pins, and filter_fps_real must equal 2x source fps;
  * F7: the stage report discloses n_measured / measurement_status
    (NOT_RUN for the real, unmeasured repo) and ok_semantics;
  * F9: verify_stage really invokes the candidate/coverage/closed-tree
    gates; a missing candidate is BLOCKED_MISSING_CANDIDATE (never a
    fabricated pass), dependency coverage gaps are violations, and a FINAL
    candidate cannot excuse missing plan write paths.
Stdlib + tempfile only; no GPU/mpv/runtime; no credentials; no external
side effects.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p4_lib as lib              # noqa: E402
import p4_analyze as an           # noqa: E402
import p4_check_evidence as ce    # noqa: E402
import p4_verify as vf            # noqa: E402

PLAN = lib.PLAN_SHA256
TREE = "docs/验证/开发/p4-001/trial-x/"
TREE_DIR = TREE.rstrip("/")
_GENERATOR_SHA = lib.library_sha256()


def _hq(tag):
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _media_sha(clip):
    return hashlib.sha256(("p4-001/fixture-media/" + clip).encode("utf-8")
                          ).hexdigest()


# ---------------------------------------------------------------------------
# B1-r2 canonical record fixtures (real v2 sampling contract)
# ---------------------------------------------------------------------------

def _pass(desc, avg_ns, samples_ns=None, count="default"):
    """LF10 canonical pass entry: count is the native sample count,
    samples_ns the raw ns timing array (the old int 'samples' field was the
    reviewed API misreading and no longer exists)."""
    if samples_ns is None:
        samples_ns = [avg_ns] * 5
    return {"desc": desc, "last_ns": avg_ns * 2, "avg_ns": avg_ns,
            "peak_ns": avg_ns * 3,
            "count": len(samples_ns) if count == "default" else count,
            "samples_ns": list(samples_ns)}


def _snap(i, fresh_avgs=(900, 800), redraw_avgs=(380,), epoch=0,
          wall=1000.0, tpos=None, with_source=True, include_margins=True,
          frame=None, fresh_table=None, redraw_table=None):
    """One snapshot of a G1 run in the real v2 shape: F5 geometry
    observations (video_out_params = post-filter source size with
    square-pixel dw/dh == source w/h; osd = window 2560x1440 with the
    actually observed margins), F5 source identity, F4 1 Hz wall schedule
    (slots land exactly on warmup_end + k*1.0s)."""
    geo = lib.expected_geometry("G1_equalrect_main")
    vop = {"pixelformat": "yuv420p",
           "w": geo["source_w_h"][0], "h": geo["source_w_h"][1],
           "dw": geo["display_dw_dh"][0], "dh": geo["display_dw_dh"][1]}
    osd = {"w": geo["window_w_h"][0], "h": geo["window_w_h"][1]}
    if include_margins:
        ml, mt, mr, mb = geo["margins_ml_mt_mr_mb"]
        osd.update(ml=ml, mr=mr, mt=mt, mb=mb)
    snap = {
        "snapshot_index": i,
        "wall_monotonic_s": wall if not callable(wall) else wall(i),
        "time_pos_s": (12.0 + i) if tpos is None else tpos(i),
        "epoch": epoch,
        "video_out_params": vop,
        "osd_dimensions": osd,
        "vo_passes": {
            "fresh": fresh_table if fresh_table is not None else
            [_pass("pass A", fresh_avgs[0]), _pass("pass B", fresh_avgs[1])],
            "redraw": redraw_table if redraw_table is not None else
            [_pass("pass A redraw", redraw_avgs[0])],
        },
    }
    if with_source:
        snap["source"] = {"clip": "motion24",
                          "media_sha256": _media_sha("motion24"),
                          "generator_sha256": _GENERATOR_SHA}
    if frame is not None:
        snap["frame"] = dict(frame)
    return snap


def _record(run_id="run-0001", rife="off", arm="baselineHQ", repeat=1,
            start=3, count=10, n_pre=3, n_post=0,
            fresh_a=lambda i: 900, fresh_b=lambda i: 800,
            redraw=lambda i: 380, epoch=lambda i: 0,
            tpos=lambda i: 12.0 + i, wall=lambda i: 1000.0 + i,
            warmup_end=None, hq="hq-baseline", observed_fps=None,
            include_margins=True, with_source=True, frame=None,
            fresh_table=None, redraw_table=None, snapshots=None,
            run_kind="calibration", excluded=None):
    """A full G1 run record in the real v2 shape: F4 window anchor
    (warmup_end_monotonic_s aligned with slot 0), 10 in-window slots on the
    preregistered 1 Hz schedule, F6 observed_output_fps for the stratum."""
    total = n_pre + count + n_post if snapshots is None else len(snapshots)
    if snapshots is None:
        snapshots = [_snap(i, epoch=epoch(i), tpos=tpos, wall=wall,
                          with_source=with_source,
                          include_margins=include_margins, frame=frame,
                          fresh_table=None if fresh_table is None else
                          fresh_table(i),
                          redraw_table=None if redraw_table is None else
                          redraw_table(i),
                          fresh_avgs=(fresh_a(i), fresh_b(i)),
                          redraw_avgs=(redraw(i),)) for i in range(total)]
    spec = lib.make_trial_spec("G1_equalrect_main", arm, rife, repeat,
                               run_kind=run_kind, plan_sha256=PLAN)
    anchor = wall(start) if not callable(wall) else wall(start)
    if warmup_end is not None:
        anchor = warmup_end
    record = {
        "schema": an.RUN_RECORD_SCHEMA,
        "run_id": run_id,
        "spec": spec,
        "window": {"start_snapshot_index": start, "sample_count": count,
                   "warmup_end_monotonic_s": anchor},
        "snapshots": snapshots,
        "config_binding": {"hq_common_sha256": _hq(hq)},
    }
    if observed_fps is None:
        record["observed_output_fps"] = spec["rife_output_fps"]
    elif observed_fps is not False:
        record["observed_output_fps"] = observed_fps
    if excluded is not None:
        record["excluded"] = excluded
    return record


def _trial_inputs(tmp):
    """Self-contained required-input set for one trial inside tmp."""
    for rel in (lib.PLAN_REL, lib.LIB_REL):
        target = lib.resolve_under_root(rel, tmp)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(lib.resolve_under_root(rel, None)), str(target))
    media_rel = "docs/验证/开发/p4-001/media/motion24/media-manifest.json"
    target = lib.resolve_under_root(media_rel, tmp)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'{"media-manifest":"fixture","clip":"motion24"}')
    return media_rel


def _stage_inputs(tmp):
    """Plan + work permit copies for verify_stage temp-root runs."""
    for rel in (lib.PLAN_REL, vf.WORK_PERMIT_REL):
        target = lib.resolve_under_root(rel, tmp)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(lib.resolve_under_root(rel, None)), str(target))


class _TempRootCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        lib.create_only_dir(TREE_DIR, root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def wf(self, rel, data):
        parts = rel.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            if not (self.root / parent).exists():
                lib.create_only_dir(parent, root=self.root)
        lib.create_only_file(rel, data, root=self.root)


# ---------------------------------------------------------------------------
# EVI tree closed hashing
# ---------------------------------------------------------------------------

class TestTreeClosedHash(_TempRootCase):
    def test_build_and_verify_ok(self):
        self.wf(TREE + "run-1/run.jsonl", b"{}\n")
        self.wf(TREE + "run-1/console.txt", b"console bytes\n")
        manifest = ce.build_manifest(TREE, root=self.root)
        report = ce.verify_manifest(manifest, root=self.root)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual(report["files_checked"], 2)
        self.assertEqual(report["violations"], [])

    def test_deleted_dependency_fails_closed(self):
        self.wf(TREE + "run-1/run.jsonl", b"{}\n")
        self.wf(TREE + "run-1/mpv.log", b"log\n")
        manifest = ce.build_manifest(TREE, root=self.root)
        os.unlink(str(self.root / "docs/验证/开发/p4-001/trial-x/run-1/mpv.log"))
        report = ce.verify_manifest(manifest, root=self.root)
        self.assertFalse(report["ok"])
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("MISSING_FILE", codes)

    def test_hash_mismatch_detected(self):
        self.wf(TREE + "a.txt", b"original")
        manifest = ce.build_manifest(TREE, root=self.root)
        (self.root / "docs/验证/开发/p4-001/trial-x/a.txt").write_bytes(
            b"tampered")
        report = ce.verify_manifest(manifest, root=self.root)
        self.assertIn("HASH_MISMATCH",
                      {v["code"] for v in report["violations"]})

    def test_unregistered_extra_file_rejected(self):
        self.wf(TREE + "a.txt", b"a")
        manifest = ce.build_manifest(TREE, root=self.root)
        self.wf(TREE + "smuggled.txt", b"late addition")
        report = ce.verify_manifest(manifest, root=self.root)
        self.assertIn("UNREGISTERED_FILE",
                      {v["code"] for v in report["violations"]})

    def test_out_of_bounds_manifest_entries(self):
        manifest = ce.build_manifest(TREE, root=self.root)
        files = dict(manifest["files"])
        files[TREE + "../../secrets.txt"] = lib.sha256_bytes(b"x")
        files["tools/p4_lib.py"] = lib.sha256_bytes(b"x")
        files["C:/evil.txt"] = lib.sha256_bytes(b"x")
        manifest["files"] = files
        manifest["file_count"] = len(files)
        report = ce.verify_manifest(manifest, root=self.root)
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("PATH_CONTRACT", codes)      # ../ and C:/ rejected
        self.assertIn("OUT_OF_TREE", codes)        # outside evidence prefix

    def test_arbitrary_exclude_escape_rejected(self):
        self.wf(TREE + "a.txt", b"a")
        manifest = ce.build_manifest(TREE, root=self.root)
        manifest["self_excluded"][TREE + "a.txt"] = "please ignore me"
        report = ce.verify_manifest(manifest, root=self.root)
        self.assertIn("ARBITRARY_EXCLUDE_ESCAPE",
                      {v["code"] for v in report["violations"]})

    def test_manifest_keys_tamper_rejected(self):
        manifest = ce.build_manifest(TREE, root=self.root)
        del manifest["tree_sha256"]
        report = ce.verify_manifest(manifest, root=self.root)
        self.assertIn("MANIFEST_KEYS_MISMATCH",
                      {v["code"] for v in report["violations"]})

    def test_missing_manifest_raises_not_skips(self):
        with self.assertRaises(lib.MissingInputError):
            ce.verify_closed_tree(TREE, root=self.root)

    def test_verify_closed_tree_ok_and_binds_manifest_bytes(self):
        self.wf(TREE + "a.txt", b"a")
        manifest = ce.build_manifest(TREE, root=self.root)
        raw = lib.canonical_json_bytes(manifest)
        self.wf(TREE + "manifest.json", raw)
        report = ce.verify_closed_tree(TREE, root=self.root)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual(report["manifest_sha256"], lib.sha256_bytes(raw))

    def test_tree_prefix_outside_evidence_tree_rejected(self):
        for bad in ("tools/", "docs/验证/开发/p3-001/", "docs/"):
            with self.assertRaises(lib.PathContractError):
                ce.build_manifest(bad, root=self.root)

    def test_symlink_junction_in_tree_rejected(self):
        target = self.root / "outside-target"
        target.mkdir()
        link = self.root / "docs/验证/开发/p4-001/trial-x/link"
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(target), str(link))
            else:
                os.symlink(str(target), str(link))
        except (OSError, AttributeError):
            self.skipTest("cannot create symlink/junction in this environment")
        with self.assertRaises(lib.PathContractError):
            ce.build_manifest(TREE, root=self.root)


# ---------------------------------------------------------------------------
# Run-evidence gate (v2 records; typed F1 rejections; stored-analysis drift)
# ---------------------------------------------------------------------------

class TestRunEvidenceGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _trial_inputs(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_record_and_recomputed_analysis_pass(self):
        record = _record()
        stored = an.analyze_run(record)
        self.assertEqual(stored["status"], an.RUN_STATUS_VALID)
        report = ce.gate_run_evidence(record, stored_analysis=stored,
                                      root=self.root)
        self.assertTrue(report["ok"], report["violations"])

    def test_wrong_gear_arm_rejected(self):
        record = _record()
        record["spec"]["arm"] = "NonexistentGPU"          # not in registry
        report = ce.gate_run_evidence(record, root=self.root)
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("RUN_RECORD_INVALID", codes)

    def test_production_lock_enforced(self):
        record = _record()
        record["spec"]["run_kind"] = "production"
        report = ce.gate_run_evidence(record, root=self.root)
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("RUN_RECORD_INVALID", codes)
        detail = " ".join(v["detail"] for v in report["violations"]
                          if v["code"] == "RUN_RECORD_INVALID")
        self.assertIn("locked", detail.lower())

    def test_missing_window_key_rejected(self):
        record = _record()
        del record["window"]["sample_count"]
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertIn("RUN_RECORD_INVALID",
                      {v["code"] for v in report["violations"]})

    def test_missing_warmup_anchor_rejected(self):
        # F4: a window without the actual warmup_end anchor cannot be
        # schedule-checked and is a schema crime before any analysis.
        record = _record()
        del record["window"]["warmup_end_monotonic_s"]
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertIn("RUN_RECORD_INVALID",
                      {v["code"] for v in report["violations"]})

    def test_duplicate_window_snapshot_index_rejected(self):
        record = _record()
        record["snapshots"][5]["snapshot_index"] = \
            record["snapshots"][4]["snapshot_index"]
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertIn("RUN_RECORD_INVALID",
                      {v["code"] for v in report["violations"]})

    def test_missing_required_input_dependency(self):
        record = _record()
        (self.root / "docs/验证/开发/p4-001/media/motion24"
         / "media-manifest.json").unlink()
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertIn("MISSING_INPUT_DEPENDENCY",
                      {v["code"] for v in report["violations"]})

    def test_all_zero_pass_flagged(self):
        # B1-r2 mapping of the old ALL_ZERO_PASS gate: an all-zero window is
        # flagged by the analyzer's typed REJECTED_PASS_NO_TIMING rejection,
        # stays preserved (info, never crash), and can never back a stored
        # VALID claim (that drift is an ANALYSIS_MISMATCH violation).
        record = _record()

        def zero(p):
            return dict(p, last_ns=0, avg_ns=0, peak_ns=0,
                        samples_ns=[0, 0, 0], count=3)

        for snap in record["snapshots"]:
            snap["vo_passes"] = {
                "fresh": [zero(p) for p in snap["vo_passes"]["fresh"]],
                "redraw": [zero(p) for p in snap["vo_passes"]["redraw"]]}
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual(report["info"][0]["status"],
                         "REJECTED_PASS_NO_TIMING")
        stored = {"status": an.RUN_STATUS_VALID,
                  "passes": {"fresh": {}, "redraw": {}},
                  "pass_sum": {"fresh_ms": 0.0, "redraw_ms": 0.0}}
        report = ce.gate_run_evidence(record, stored_analysis=stored,
                                      root=self.root)
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("ANALYSIS_MISMATCH", codes)
        self.assertEqual(report["info"][0]["status"],
                         "REJECTED_PASS_NO_TIMING")

    def test_blank_pass_tables_rejected_never_measured(self):
        # F1: a blank window (empty fresh + empty redraw in every snapshot)
        # is the reviewed blocker counterexample — it must surface as the
        # typed REJECTED_PASS_TABLE_EMPTY rejection, never as a 0 ms window.
        record = _record(fresh_table=lambda i: [], redraw_table=lambda i: [])
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual(report["info"][0]["status"],
                         "REJECTED_PASS_TABLE_EMPTY")

    def test_redraw_empty_table_stays_valid_unmeasured(self):
        # F1: a legal empty redraw table keeps the run VALID but the redraw
        # pass sum stays None (unmeasured) — never coerced to 0 ms.
        record = _record(redraw_table=lambda i: [])
        stored = an.analyze_run(record)
        self.assertEqual(stored["status"], an.RUN_STATUS_VALID)
        self.assertIsNone(stored["pass_sum"]["redraw_ms"])
        self.assertEqual(stored["pass_sum"]["unmeasured_tables"], ["redraw"])
        report = ce.gate_run_evidence(record, stored_analysis=stored,
                                      root=self.root)
        self.assertTrue(report["ok"], report["violations"])

    def test_tampered_stored_analysis_mismatch(self):
        record = _record()
        stored = an.analyze_run(record)
        identity = "0|pass A"   # LF11 slot identity, not the bare desc
        stored["passes"]["fresh"][identity]["avg_ms_median"] += 0.5
        report = ce.gate_run_evidence(record, stored_analysis=stored,
                                      root=self.root)
        codes = {v["code"] for v in report["violations"]}
        self.assertIn("ANALYSIS_MISMATCH", codes)

    def test_rejected_run_preserved_as_info_not_crash(self):
        record = _record(snapshots=[_snap(i) for i in range(6)])
        report = ce.gate_run_evidence(record, root=self.root)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual(report["info"][0]["status"],
                         "REJECTED_WINDOW_TRUNCATED")


class TestPngIdentity(_TempRootCase):
    def _png_bytes(self, clip, index):
        for _, data in lib.iter_clip_frames(clip, [index]):
            return data
        raise AssertionError("no frame generated")

    def test_real_frame_identity_ok(self):
        data = self._png_bytes("motion24", 0)
        rel = TREE + "frames/motion24-000000.png"
        self.wf(rel, data)
        report = ce.gate_run_evidence(_record(), root=self.root,
                                      pngs={rel: {"clip": "motion24",
                                                  "index": 0}})
        self.assertNotIn("PNG_IDENTITY_MISMATCH",
                         {v["code"] for v in report["violations"]})

    def test_frame_identity_swap_rejected(self):
        data = self._png_bytes("motion24", 3)
        rel = TREE + "frames/motion24-relabeled.png"
        self.wf(rel, data)
        report = ce.gate_run_evidence(_record(), root=self.root,
                                      pngs={rel: {"clip": "motion24",
                                                  "index": 7}})
        self.assertIn("PNG_IDENTITY_MISMATCH",
                      {v["code"] for v in report["violations"]})

    def test_thumbnail_substituting_original_rejected(self):
        tiny = lib.encode_png_rgb8(32, 32, [b"\x10\x20\x30" * 32] * 32)
        rel = TREE + "frames/thumbnail-as-frame.png"
        self.wf(rel, tiny)
        report = ce.gate_run_evidence(_record(), root=self.root,
                                      pngs={rel: {"clip": "motion24",
                                                  "index": 0}})
        self.assertIn("PNG_IDENTITY_MISMATCH",
                      {v["code"] for v in report["violations"]})

    def test_missing_png_file_fail_closed(self):
        report = ce.gate_run_evidence(
            _record(), root=self.root,
            pngs={TREE + "gone.png": {"clip": "motion24", "index": 0}})
        self.assertIn("PNG_IDENTITY_MISMATCH",
                      {v["code"] for v in report["violations"]})


# ---------------------------------------------------------------------------
# F6: structural RIFE proof verification (root/context API)
# ---------------------------------------------------------------------------

class TestRifeProofVerification(_TempRootCase):
    MIDDLE_REL = TREE + "proof/middle-000042.png"
    LOG_REL = TREE + "proof/engine.log"

    def _evidence(self, dll_sha=None, write_files=True):
        dll_sha = dll_sha or _hq("rife-dll-bytes")
        evidence = {
            "observed_output_fps": 48,
            "dll_model_hash": {"dll_sha256": dll_sha,
                               "model_sha256": _hq("rife-model-bytes")},
            "filter_fps_real": 48,
            "middle_frame_sample": {
                "rel": self.MIDDLE_REL,
                "sha256": _hq("middle-frame-bytes")},
            "engine_log": {"rel": self.LOG_REL,
                           "sha256": _hq("engine-log-bytes")},
        }
        if write_files:
            self.wf(self.MIDDLE_REL, b"middle-frame-bytes")
            self.wf(self.LOG_REL, b"engine-log-bytes")
        return evidence

    def test_full_structural_proof_accepted(self):
        evidence = self._evidence()
        context = {"source_fps": 24,
                   "rife_identity_pins": {"dll_sha256": _hq("rife-dll-bytes")}}
        self.assertEqual(
            ce.verify_rife_proof(evidence, context, root=self.root), [])
        report = {"claims": [{"id": "r1", "topic": "rife",
                              "verdict": "PASS_OBJECTIVE",
                              "text": "RIFE executed with structural proof",
                              "evidence": evidence}]}
        self.assertEqual(ce.scan_performance_claims(report, context=context,
                                                    root=self.root), [])

    def test_garbage_four_keys_never_pass(self):
        # The review's F6 counterexample: all four keys present, all values
        # empty/garbage — keys alone are not proof.
        evidence = {"dll_model_hash": "", "filter_fps_real": False,
                    "middle_frame_sample": None, "engine_log": 0}
        violations = ce.verify_rife_proof(evidence, {"source_fps": 24},
                                          root=self.root)
        codes = {v["code"] for v in violations}
        self.assertIn("RIFE_PROOF_HASH_MALFORMED", codes)
        self.assertIn("RIFE_FPS_REAL_MALFORMED", codes)
        self.assertEqual(codes & {"RIFE_PROOF_BINDING_MALFORMED",
                                  "RIFE_PROOF_FILE_MISSING"},
                         {"RIFE_PROOF_BINDING_MALFORMED"})
        report = {"claims": [{"id": "r1", "topic": "rife",
                              "verdict": "PASS_OBJECTIVE", "text": "rife",
                              "evidence": evidence}]}
        self.assertTrue(ce.scan_performance_claims(
            report, context={"source_fps": 24}, root=self.root))

    def test_identity_pin_mismatch_rejected(self):
        evidence = self._evidence()
        context = {"rife_identity_pins": {"dll_sha256": _hq("other-dll")}}
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, context, root=self.root)}
        self.assertIn("RIFE_IDENTITY_PIN_MISMATCH", codes)

    def test_identity_pin_uncovered_role_rejected(self):
        evidence = self._evidence()
        context = {"rife_identity_pins": {"engine_sha256": _hq("x")}}
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, context, root=self.root)}
        self.assertIn("RIFE_IDENTITY_PIN_UNCOVERED", codes)

    def test_filter_fps_real_must_equal_2x_source(self):
        evidence = self._evidence()
        evidence["filter_fps_real"] = 60.0
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, {"source_fps": 24}, root=self.root)}
        self.assertIn("RIFE_FPS_REAL_MISMATCH", codes)
        # without a source_fps context the type check still applies
        evidence["filter_fps_real"] = "48"
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, {}, root=self.root)}
        self.assertIn("RIFE_FPS_REAL_MALFORMED", codes)

    def test_proof_file_missing_fail_closed(self):
        evidence = self._evidence(write_files=False)
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, {"source_fps": 24}, root=self.root)}
        self.assertIn("RIFE_PROOF_FILE_MISSING", codes)

    def test_proof_file_outside_tree_rejected(self):
        evidence = self._evidence()
        evidence["engine_log"]["rel"] = "tools/p4_lib.py"
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, {"source_fps": 24}, root=self.root)}
        self.assertIn("RIFE_PROOF_FILE_OUTSIDE_TREE", codes)

    def test_proof_file_hash_mismatch_rejected(self):
        evidence = self._evidence()
        (self.root / self.LOG_REL).write_bytes(b"tampered log bytes")
        codes = {v["code"] for v in ce.verify_rife_proof(
            evidence, {"source_fps": 24}, root=self.root)}
        self.assertIn("RIFE_PROOF_FILE_HASH_MISMATCH", codes)

    def test_string_sha_variant_and_flat_hash_object(self):
        # a single 64-hex string is a legal dll_model_hash; the pin must
        # match its role value.
        evidence = self._evidence(dll_sha=_hq("flat-dll"))
        evidence["dll_model_hash"] = _hq("flat-dll")
        context = {"rife_identity_pins": {"dll_model": _hq("flat-dll")}}
        self.assertEqual(
            ce.verify_rife_proof(evidence, context, root=self.root), [])

    def test_fps_only_still_rejected(self):
        report = {"claims": [{"id": "r1", "topic": "rife",
                              "verdict": "PASS_OBJECTIVE",
                              "text": "RIFE executed, fps doubled",
                              "evidence": {"observed_output_fps": 48}}]}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("RIFE_FPS_ONLY_PROOF", codes)


# ---------------------------------------------------------------------------
# Anti-metric claims (unchanged negatives) + F3 real-bundle exclusion trace
# ---------------------------------------------------------------------------

class TestAntiMetricClaims(unittest.TestCase):
    def test_speed_claim_without_run_evidence(self):
        report = {"claims": [{"id": "c1", "topic": "perf", "verdict": "PASS",
                              "text": "Anime4K 比 baselineHQ 更快",
                              "evidence": {}}]}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("CLAIM_WITHOUT_RUN_EVIDENCE", codes)

    def test_speed_claim_with_runs_and_ci_ok(self):
        report = {"claims": [{"id": "c1", "topic": "perf", "verdict": "PASS",
                              "text": "arm X slower than arm Y (descriptive)",
                              "evidence": {
                                  "run_ids": ["r1", "r2", "r3", "r4", "r5"],
                                  "ci": {"kind": "bootstrap_percentile"}}}]}
        self.assertEqual(
            [v for v in ce.scan_performance_claims(report)
             if v["code"] == "CLAIM_WITHOUT_RUN_EVIDENCE"], [])

    def test_pacing_claim_without_present_rejected(self):
        report = {"claims": [{"id": "p1", "topic": "frame_pacing",
                              "verdict": "PASS",
                              "text": "frame pacing done",
                              "evidence": {}}]}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("PACING_CLAIM_WITHOUT_PRESENT", codes)

    def test_per_pass_sum_as_overall_headroom_rejected(self):
        for payload in ({"overall_headroom_ms": 3.2},
                        {"results": [{"headroom_ms": 5}]},
                        {"summary": {"overall_headroom_ms": 1.0}}):
            codes = {v["code"] for v in ce.scan_performance_claims(payload)}
            self.assertIn("PASS_SUM_AS_OVERALL_HEADROOM", codes)

    def test_ipc_samples_as_present_rejected(self):
        report = {"present_frame_duration": 16.6}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("PRESENT_FROM_NON_PRESENT_SOURCE", codes)
        report = {"present_frame_duration": {"status": "MEASURED",
                                             "source": "IPC_polling"}}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("PRESENT_FROM_NON_PRESENT_SOURCE", codes)

    def test_not_measured_and_legal_present_accepted(self):
        report = {"present_frame_duration": an.present_frame_duration()}
        self.assertEqual(
            [v for v in ce.scan_performance_claims(report)
             if v["code"] == "PRESENT_FROM_NON_PRESENT_SOURCE"], [])
        report = {"present_frame_duration":
                  {"status": "MEASURED", "source": "PresentMon",
                   "note": "hypothetical legal future source"}}
        self.assertEqual(
            [v for v in ce.scan_performance_claims(report)
             if v["code"] == "PRESENT_FROM_NON_PRESENT_SOURCE"], [])

    def test_vo_image_as_shader_proof_rejected(self):
        report = {"captures": [{"id": "cap1", "purpose": "shader_ab",
                                "vo_backend": "image"}]}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("VO_IMAGE_AS_SHADER_PROOF", codes)

    def test_vo_image_as_algorithm_ab_rejected(self):
        report = {"captures": [{"id": "cap2", "purpose": "algorithm_ab",
                                "vo_backend": "image"}]}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("VO_IMAGE_AS_ALGORITHM_AB", codes)

    def test_gpu_next_shader_capture_accepted(self):
        report = {"captures": [{"id": "cap3", "purpose": "shader_ab",
                                "vo_backend": "gpu-next"}]}
        self.assertEqual(ce.scan_performance_claims(report), [])

    def test_synthetic_as_natural_rejected(self):
        report = {
            "materials": [{"id": "mat1", "kind": "synthetic"}],
            "claims": [{"id": "c9", "topic": "pic", "verdict": "PASS",
                        "text": "在自然实拍素材上验证完成",
                        "evidence": {"material_ids": ["mat1"]}}]}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("SYNTHETIC_AS_NATURAL", codes)

    def test_machine_signed_user_approval_rejected(self):
        report = {"user_acceptance_claimed": True}
        codes = {v["code"] for v in ce.scan_performance_claims(report)}
        self.assertIn("MACHINE_SIGNED_USER_APPROVAL", codes)
        ok = {"user_acceptance_claimed": True,
              "user_acceptance_source": "human_user_signing"}
        self.assertEqual(
            [v for v in ce.scan_performance_claims(ok)
             if v["code"] == "MACHINE_SIGNED_USER_APPROVAL"], [])


class TestExclusionPreservationRealBundle(unittest.TestCase):
    """F3: exclusion traces work on the REAL analyze_records bundle shape
    (rejected_by_analysis is a LIST of run entries), not on hand-made dicts
    that固化了 the reviewed wrong contract."""

    @staticmethod
    def _bundle():
        good = _record(run_id="run-good")
        truncated = _record(run_id="run-truncated",
                            snapshots=[_snap(i) for i in range(6)])
        excluded = _record(
            run_id="run-excluded",
            excluded={"code": "E1", "reason": "window polluted by user "
                                              "input",
                      "original_dir": "trial-x/run-excluded"})
        return an.analyze_records([good, truncated, excluded])

    def test_real_bundle_rejection_shape_is_a_list(self):
        bundle = self._bundle()
        cell = bundle["cells"]["G1_equalrect_main|baselineHQ|motion24@24|"
                              "rife=off"]
        rejected = cell["rejected_by_analysis"]
        self.assertIsInstance(rejected, list)
        self.assertEqual({e["run_id"] for e in rejected},
                         {"run-truncated"})
        self.assertEqual([e["run_id"] for e in cell["excluded_runs"]],
                         ["run-excluded"])

    def test_excluded_run_traced_through_real_bundle(self):
        bundle = self._bundle()
        report = {"excluded_runs": [{"run_id": "run-truncated",
                                     "code": "E2",
                                     "reason": "rejected by analysis",
                                     "original_dir": "trial-x/run-truncated"}]}
        self.assertEqual(ce.check_exclusion_preservation(report, bundle), [])

    def test_fail_trace_lost_rejected(self):
        bundle = self._bundle()
        report = {"excluded_runs": [{"run_id": "run-9", "code": "E1",
                                     "reason": "pollution",
                                     "original_dir": "trial-x/run-9"}]}
        codes = {v["code"] for v in ce.check_exclusion_preservation(report,
                                                                    bundle)}
        self.assertIn("EXCLUDED_RUN_TRACE_LOST", codes)


# ---------------------------------------------------------------------------
# F2: trial qualification through bound raw evidence
# ---------------------------------------------------------------------------

class TestTrialGate(_TempRootCase):
    def _write_valid_run(self, run_id="run-0001", rife="off", fixture=False,
                         trial_dir=None):
        trial_dir = trial_dir or (TREE + "trial-perf/")
        record = _record(run_id=run_id, rife=rife)
        run_rel = trial_dir + "run-%s.json" % run_id
        raw = lib.canonical_json_bytes(record)
        self.wf(run_rel, raw)
        stored = an.analyze_run(record)
        stored_rel = trial_dir + "analysis-%s.json" % run_id
        stored_raw = lib.canonical_json_bytes(stored)
        self.wf(stored_rel, stored_raw)
        binding = {"run_rel": run_rel, "run_sha256": lib.sha256_bytes(raw),
                   "stored_analysis_rel": stored_rel,
                   "stored_analysis_sha256": lib.sha256_bytes(stored_raw)}
        if fixture:
            binding["test_fixture"] = True
        return binding, record, stored

    def _trial(self, runs, **overrides):
        trial = {"schema": ce.SCHEMA_TRIAL_REPORT, "test_id": "PER-01",
                 "status": "PASS_OBJECTIVE", "claims": [],
                 "plan_sha256": PLAN, "runs": runs}
        trial.update(overrides)
        return trial

    def test_bare_trial_json_cannot_earn_pass(self):
        # The review's F2 counterexample: a bare declared-PASS trial.json.
        report = ce.gate_trial_report(
            {"test_id": "PER-01", "status": "PASS_OBJECTIVE", "claims": []},
            root=self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("TRIAL_SCHEMA_UNKNOWN",
                      {v["code"] for v in report["violations"]})
        self.assertFalse(report["measured"])

    def test_unknown_schema_is_violation_never_upgrade(self):
        trial = self._trial([], schema="p4-some-unknown-v9")
        gate = ce.gate_trial_report(trial, root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("TRIAL_SCHEMA_UNKNOWN",
                      {v["code"] for v in gate["violations"]})

    def test_unbound_report_is_violation(self):
        trial = self._trial([])
        gate = ce.gate_trial_report(trial, root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("TRIAL_NO_BOUND_EVIDENCE",
                      {v["code"] for v in gate["violations"]})

    def test_real_chain_earns_declared_pass(self):
        binding, _record_, stored = self._write_valid_run()
        gate = ce.gate_trial_report(self._trial([binding]), root=self.root)
        self.assertTrue(gate["ok"], gate["violations"])
        self.assertEqual(gate["status"], "PASS_OBJECTIVE")
        self.assertTrue(gate["measured"])
        self.assertEqual(gate["n_valid_runs"], 1)

    def test_tampered_run_sha_fails_closed(self):
        binding, _record_, _stored = self._write_valid_run()
        binding = dict(binding, run_sha256=_hq("other-bytes"))
        gate = ce.gate_trial_report(self._trial([binding]), root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("TRIAL_RUN_SHA_MISMATCH",
                      {v["code"] for v in gate["violations"]})

    def test_stored_analysis_drift_fails_closed(self):
        binding, _record_, stored = self._write_valid_run()
        stored["passes"]["fresh"]["0|pass A"]["avg_ms_median"] += 0.25
        stored_rel = binding["stored_analysis_rel"]
        stored_raw = lib.canonical_json_bytes(stored)
        (self.root / stored_rel).write_bytes(stored_raw)
        binding = dict(binding,
                       stored_analysis_sha256=lib.sha256_bytes(stored_raw))
        gate = ce.gate_trial_report(self._trial([binding]), root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("ANALYSIS_MISMATCH",
                      {v["code"] for v in gate["violations"]})

    def test_rejected_run_preserved_cannot_back_pass(self):
        truncated = _record(run_id="run-truncated",
                            snapshots=[_snap(i) for i in range(6)])
        run_rel = TREE + "trial-perf/run-truncated.json"
        raw = lib.canonical_json_bytes(truncated)
        self.wf(run_rel, raw)
        binding = {"run_rel": run_rel, "run_sha256": lib.sha256_bytes(raw)}
        gate = ce.gate_trial_report(self._trial([binding]), root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("TRIAL_STATUS_NOT_EARNED",
                      {v["code"] for v in gate["violations"]})
        self.assertFalse(gate["measured"])
        self.assertEqual(gate["info"][0]["status"],
                         "REJECTED_WINDOW_TRUNCATED")

    def test_fixture_run_zero_credit(self):
        binding, _record_, _stored = self._write_valid_run(fixture=True)
        gate = ce.gate_trial_report(self._trial([binding]), root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("FIXTURE_AS_STAGE_EVIDENCE",
                      {v["code"] for v in gate["violations"]})
        self.assertIn("TRIAL_STATUS_NOT_EARNED",
                      {v["code"] for v in gate["violations"]})
        self.assertFalse(gate["measured"])
        self.assertEqual(gate["n_fixture_runs"], 1)

    def test_fixture_never_hides_real_credit(self):
        real, _record_, _stored = self._write_valid_run(run_id="run-real")
        fixture, _record2_, _stored2 = self._write_valid_run(
            run_id="run-fixture", fixture=True)
        gate = ce.gate_trial_report(self._trial([real, fixture]),
                                    root=self.root)
        self.assertTrue(gate["ok"], gate["violations"])
        self.assertTrue(gate["measured"])
        self.assertEqual(gate["n_valid_runs"], 1)
        self.assertEqual(gate["n_fixture_runs"], 1)

    def test_rife_claim_with_structural_proof_earned(self):
        # end-to-end F6-in-trial: an rife=on run + a four-piece structural
        # claim (files really in the tree, hashes binding, pins matching).
        self.wf(TREE + "proof/middle.png", b"middle-bytes")
        self.wf(TREE + "proof/engine.log", b"engine-bytes")
        binding, record, _stored = self._write_valid_run(
            run_id="run-on", rife="on")
        trial = self._trial(
            [binding],
            claims=[{"id": "r1", "topic": "rife",
                     "verdict": "PASS_OBJECTIVE",
                     "text": "RIFE executed (structural binding only)",
                     "evidence": {
                         "observed_output_fps": 48,
                         "dll_model_hash": {"dll_sha256": _hq("dll"),
                                            "model_sha256": _hq("model")},
                         "filter_fps_real": 48,
                         "middle_frame_sample": {
                             "rel": TREE + "proof/middle.png",
                             "sha256": _hq("middle-bytes")},
                         "engine_log": {"rel": TREE + "proof/engine.log",
                                        "sha256": _hq("engine-bytes")}}}],
            rife_identity_pins={"dll_sha256": _hq("dll")})
        gate = ce.gate_trial_report(trial, root=self.root)
        self.assertTrue(gate["ok"], gate["violations"])
        self.assertEqual(gate["status"], "PASS_OBJECTIVE")

    def test_bundle_binding_with_lost_trace_fails(self):
        bundle = an.analyze_records([
            _record(run_id="run-good"),
            _record(run_id="run-truncated",
                    snapshots=[_snap(i) for i in range(6)])])
        bundle_rel = TREE + "analysis/bundle.json"
        raw = lib.canonical_json_bytes(bundle)
        self.wf(bundle_rel, raw)
        trial = self._trial(
            [], status="PARTIAL_MEASURED",
            analysis_bundle_rel=bundle_rel,
            analysis_bundle_sha256=lib.sha256_bytes(raw),
            excluded_runs=[{"run_id": "run-unknown", "code": "E3",
                            "reason": "x", "original_dir": "y"}])
        gate = ce.gate_trial_report(trial, root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("EXCLUDED_RUN_TRACE_LOST",
                      {v["code"] for v in gate["violations"]})

    def test_wrong_plan_binding_rejected(self):
        binding, _record_, _stored = self._write_valid_run()
        gate = ce.gate_trial_report(self._trial([binding], plan_sha256="9" * 64),
                                    root=self.root)
        self.assertIn("TRIAL_PLAN_BINDING",
                      {v["code"] for v in gate["violations"]})

    def test_run_outside_evidence_tree_rejected(self):
        target = lib.resolve_under_root(lib.LIB_REL, None)
        trial = self._trial([{"run_rel": "tools/p4_lib.py",
                               "run_sha256": lib.sha256_file(target)}])
        gate = ce.gate_trial_report(trial, root=self.root)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("TRIAL_RUN_OUTSIDE_TREE",
                      {v["code"] for v in gate["violations"]})


# ---------------------------------------------------------------------------
# Candidate coverage + exact write-path closure (F9)
# ---------------------------------------------------------------------------

class TestCandidateAndWritePaths(_TempRootCase):
    def _candidate(self, **overrides):
        pinned = lib.resolve_under_root(lib.LIB_REL, self.root)
        pinned.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(lib.resolve_under_root(lib.LIB_REL, None)),
                        str(pinned))
        payload = b'{"candidate":true}'
        self.wf(TREE + "candidate.json", payload)
        cand = {
            "schema": ce.SCHEMA_CANDIDATE,
            "candidate_rel": TREE + "candidate.json",
            "candidate_sha256": lib.sha256_bytes(payload),
            "source_hashes": {lib.LIB_REL: lib.sha256_file(pinned)},
            "author_tree": TREE,
            "independent_tree": "docs/验证/开发/p4-001/trial-x-independent/",
            "plan_sha256": PLAN,
        }
        cand.update(overrides)
        return cand

    def test_valid_candidate_ok(self):
        self.assertEqual(ce.gate_candidate(self._candidate(), root=self.root),
                         [])

    def test_stitched_candidate_hash_mismatch(self):
        cand = self._candidate(candidate_sha256="0" * 64)
        codes = {v["code"] for v in ce.gate_candidate(cand, root=self.root)}
        self.assertIn("CANDIDATE_HASH_MISMATCH", codes)

    def test_missing_candidate_file(self):
        cand = self._candidate()
        cand["candidate_rel"] = TREE + "never-created.json"
        cand["candidate_sha256"] = lib.sha256_bytes(b"x")
        codes = {v["code"] for v in ce.gate_candidate(cand, root=self.root)}
        self.assertIn("CANDIDATE_MISSING", codes)

    def test_missing_source_pin_fail_closed(self):
        cand = self._candidate()
        cand["source_hashes"]["tools/p4_never_written.py"] = "0" * 64
        codes = {v["code"] for v in ce.gate_candidate(cand, root=self.root)}
        self.assertIn("SOURCE_PIN_MISSING", codes)

    def test_expected_dependency_coverage_gap_rejected(self):
        # F9: a candidate that pins only its own sources while omitting an
        # expected plan dependency (e.g. the collector) cannot pass.
        deps = [lib.LIB_REL, "tools/p4_collect.py"]
        cand = self._candidate()
        codes = {v["code"] for v in ce.gate_candidate(
            cand, root=self.root, expected_dependencies=deps)}
        self.assertIn("CANDIDATE_COVERAGE_MISSING", codes)
        cand["source_hashes"]["tools/p4_collect.py"] = _hq("pinned-later")
        codes = {v["code"] for v in ce.gate_candidate(
            cand, root=self.root, expected_dependencies=deps)}
        self.assertIn("SOURCE_PIN_MISSING", codes)   # pinned but absent: fail

    def test_expected_dependency_coverage_complete_ok(self):
        dep_rel = TREE + "fixtures/fixture-frame.png"
        self.wf(dep_rel, b"fixture-bytes")
        cand = self._candidate()
        cand["source_hashes"][dep_rel] = lib.sha256_bytes(b"fixture-bytes")
        self.assertEqual(ce.gate_candidate(cand, root=self.root,
                                           expected_dependencies=[dep_rel]),
                         [])

    def test_expected_candidate_dependencies_lists_plan_bindings(self):
        plan = {"write_paths": ["tools/p4_collect.py", lib.LIB_REL],
                "binding": {"authorization": "docs/执行授权-P4.json",
                            "brief": "docs/P4/P4执行约束与验收brief.md",
                            "baseline": None}}
        deps = ce.expected_candidate_dependencies(plan)
        self.assertEqual(deps, sorted({"tools/p4_collect.py", lib.LIB_REL,
                                       "docs/执行授权-P4.json",
                                       "docs/P4/P4执行约束与验收brief.md"}))

    def test_final_candidate_cannot_excuse_missing_write_path(self):
        plan = {"write_paths": ["docs/P4/P4结果报告.md"]}
        violations = ce.gate_candidate(self._candidate(), root=self.root,
                                       final_candidate=True, plan=plan)
        codes = {v["code"] for v in violations}
        self.assertIn("CANDIDATE_WRITE_PATH_NOT_CLOSED", codes)
        self.assertTrue(any("MISSING_WRITE_PATH" in v["detail"]
                            for v in violations))

    def test_author_independent_tree_must_differ(self):
        cand = self._candidate(independent_tree=TREE)
        codes = {v["code"] for v in ce.gate_candidate(cand, root=self.root)}
        self.assertIn("AUTHOR_INDEPENDENT_TREE_NOT_SEPARATED", codes)

    def test_wrong_plan_binding(self):
        cand = self._candidate(plan_sha256="1" * 64)
        codes = {v["code"] for v in ce.gate_candidate(cand, root=self.root)}
        self.assertIn("CANDIDATE_PLAN_BINDING", codes)

    def test_write_paths_undeclared_missing(self):
        plan = {"write_paths": ["docs/P4/P4结果报告.md", lib.LIB_REL]}
        entries = ce.check_write_paths(plan, root=None)
        by_rel = {e["rel"]: e for e in entries}
        self.assertIsNotNone(by_rel["docs/P4/P4结果报告.md"]["violation"])
        self.assertIn("UNDECLARED_MISSING_WRITE_PATH",
                      by_rel["docs/P4/P4结果报告.md"]["violation"])
        self.assertIsNone(by_rel[lib.LIB_REL]["violation"])

    def test_write_paths_pending_declaration(self):
        plan = {"write_paths": ["docs/P4/P4结果报告.md"]}
        entries = ce.check_write_paths(plan, root=None,
                                       pending=["docs/P4/P4结果报告.md"])
        self.assertIsNone(entries[0]["violation"])
        self.assertIn("pending", entries[0]["note"])

    def test_final_candidate_cannot_excuse_missing_write_path_direct(self):
        plan = {"write_paths": ["docs/P4/P4结果报告.md"]}
        entries = ce.check_write_paths(plan, root=None, final_candidate=True,
                                       pending=["docs/P4/P4结果报告.md"])
        self.assertIn("MISSING_WRITE_PATH", entries[0]["violation"])


# ---------------------------------------------------------------------------
# Stage synthesis + F7 zero-measurement disclosure
# ---------------------------------------------------------------------------

class TestStageSynthesis(unittest.TestCase):
    REQUIRED = ["PIC-01", "PER-01", "TIME-01"]

    def test_all_not_run_is_partial(self):
        per = {tid: "未测" for tid in self.REQUIRED}
        status, _ = ce.synthesize_stage_status(per, self.REQUIRED)
        self.assertEqual(status, "PARTIAL_MEASURED")

    def test_any_fail_is_rework(self):
        per = {tid: "PASS_OBJECTIVE" for tid in self.REQUIRED}
        per["PER-01"] = "FAIL"
        status, _ = ce.synthesize_stage_status(per, self.REQUIRED)
        self.assertEqual(status, "REWORK")

    def test_all_pass_capped_at_partial_with_disclosure(self):
        per = {tid: "PASS_OBJECTIVE" for tid in self.REQUIRED}
        status, notes = ce.synthesize_stage_status(per, self.REQUIRED)
        self.assertEqual(status, "PARTIAL_MEASURED")
        self.assertTrue(any("cap" in n for n in notes))

    def test_invalid_status_and_coverage_rejected(self):
        with self.assertRaises(lib.ValueContractError):
            ce.synthesize_stage_status({t: "SUPER_PASS"
                                        for t in self.REQUIRED},
                                       self.REQUIRED)
        with self.assertRaises(lib.ValueContractError):
            ce.synthesize_stage_status({"PIC-01": "未测"}, self.REQUIRED)


# ---------------------------------------------------------------------------
# Stage verifier: F2 qualification, F7 disclosure, F9 gate wiring
# ---------------------------------------------------------------------------

class TestStageVerifier(unittest.TestCase):
    def test_real_repo_stage_all_not_run_partial(self):
        report = vf.verify_stage()
        self.assertTrue(report["ok"],
                        json.dumps(report["violations"], ensure_ascii=False))
        self.assertEqual(report["plan_sha256"], PLAN)
        self.assertEqual(len(report["required_tests"]), 13)
        self.assertTrue(all(s == "未测"
                            for s in report["per_test"].values()))
        self.assertEqual(report["stage_status"], "PARTIAL_MEASURED")
        self.assertEqual(report["work_permit_violations"], [])
        # F7: zero-measurement disclosure is explicit
        self.assertEqual(report["n_measured"], 0)
        self.assertEqual(report["measurement_status"], "NOT_RUN")
        self.assertTrue(any("n_measured=0" in n for n in report["notes"]))
        self.assertIn("never a measurement acceptance",
                      report["ok_semantics"])
        # F9: honest candidate/closed-tree statuses, coverage listed
        self.assertEqual(report["candidate_status"],
                         "BLOCKED_MISSING_CANDIDATE")
        self.assertEqual(report["closed_tree_status"], "NOT_CREATED")
        self.assertTrue(report["stage_pending_write_paths"])
        self.assertTrue(all(e["violation"] is None
                            for e in report["write_path_coverage"]))

    def test_cli_exit_zero_and_json_contract(self):
        rc = vf.main(["--json"])
        self.assertEqual(rc, 0)

    def test_cli_unexpected_exception_fails_closed(self):
        # F3: an unexpected internal error must produce a structured REWORK
        # report with a non-zero exit code — never a silent pass.
        original = vf.verify_stage

        def boom():
            raise RuntimeError("simulated internal error")

        vf.verify_stage = boom
        try:
            rc = vf.main(["--json"])
        finally:
            vf.verify_stage = original
        self.assertEqual(rc, 3)

    def test_tampered_plan_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = lib.resolve_under_root(lib.PLAN_REL, root)
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = lib.resolve_under_root(lib.PLAN_REL, None).read_bytes()
            target.write_bytes(raw + b" ")
            with self.assertRaises(lib.P4ContractError):
                vf.load_plan(root)

    def test_tampered_work_permit_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = lib.resolve_under_root(vf.WORK_PERMIT_REL, None).read_bytes()
            permit = json.loads(raw.decode("utf-8"))
            permit["status"] = "FAIL"
            permit["live_configuration_write_allowed"] = True
            target = lib.resolve_under_root(vf.WORK_PERMIT_REL, root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(lib.canonical_json_bytes(permit))
            codes = {v["code"] for v in vf.check_work_permit(root)}
            self.assertIn("WORK_PERMIT_NOT_PASS", codes)
            self.assertIn("WORK_PERMIT_LIVE_WRITE_LOCK", codes)

    def _stage_root(self, tmp):
        root = Path(tmp)
        _stage_inputs(root)
        return root

    def test_duplicate_trial_test_id_flags_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            for name in ("a", "b"):
                lib.create_only_dir(
                    "docs/验证/开发/p4-001/trial-%s" % name, root=root)
                lib.create_only_file(
                    "docs/验证/开发/p4-001/trial-%s/trial.json" % name,
                    lib.canonical_json_bytes(
                        {"test_id": "PER-01", "status": "PASS_OBJECTIVE",
                         "claims": []}),
                    root=root)
            report = vf.verify_stage(root=root)
            codes = {v["code"] for v in report["violations"]}
            self.assertIn("TRIAL_TEST_ID_DUPLICATE", codes)
            self.assertEqual(report["per_test"]["PER-01"], "FAIL")

    def test_unknown_trial_test_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            lib.create_only_dir("docs/验证/开发/p4-001/trial-z", root=root)
            lib.create_only_file(
                "docs/验证/开发/p4-001/trial-z/trial.json",
                lib.canonical_json_bytes({"test_id": "P5-BAK04",
                                          "status": "PASS_OBJECTIVE"}),
                root=root)
            report = vf.verify_stage(root=root)
            self.assertIn("TRIAL_TEST_ID_UNKNOWN",
                          {v["code"] for v in report["violations"]})

    # -- F2 stage-level qualification -------------------------------------

    def _write_trial_chain(self, root, run_id="run-0001", rife="off",
                           fixture=False, valid=True):
        """Real analyze output + a complete temp dependency chain as the F2
        positive control: run.json bytes + stored analysis + trial.json."""
        spec = lib.make_trial_spec("G1_equalrect_main", "baselineHQ", rife, 1,
                                   run_kind="calibration", plan_sha256=PLAN)
        record = _record(run_id=run_id, rife=rife)
        if not valid:
            record = _record(run_id=run_id, rife=rife,
                             snapshots=[_snap(i) for i in range(6)])
        trial_dir = TREE
        run_rel = trial_dir + "run.json"
        raw = lib.canonical_json_bytes(record)
        parts = run_rel.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            if not (root / parent).exists():
                lib.create_only_dir(parent, root=root)
        lib.create_only_file(run_rel, raw, root=root)
        stored = an.analyze_run(record)
        stored_rel = trial_dir + "analysis.json"
        stored_raw = lib.canonical_json_bytes(stored)
        lib.create_only_file(stored_rel, stored_raw, root=root)
        binding = {"run_rel": run_rel, "run_sha256": lib.sha256_bytes(raw),
                   "stored_analysis_rel": stored_rel,
                   "stored_analysis_sha256": lib.sha256_bytes(stored_raw)}
        if fixture:
            binding["test_fixture"] = True
        trial = {"schema": ce.SCHEMA_TRIAL_REPORT, "test_id": "PER-01",
                 "status": "PASS_OBJECTIVE", "claims": [],
                 "plan_sha256": PLAN, "runs": [binding]}
        lib.create_only_file(trial_dir + "trial.json",
                             lib.canonical_json_bytes(trial), root=root)

    def test_real_chain_earns_pass_objective_at_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            _trial_inputs(root)
            self._write_trial_chain(root)
            report = vf.verify_stage(root=root)
            self.assertEqual(report["per_test"]["PER-01"], "PASS_OBJECTIVE",
                             json.dumps(report["violations"],
                                        ensure_ascii=False))
            self.assertEqual(report["n_measured"], 1)
            self.assertEqual(report["measurement_status"],
                             an.STATUS_PARTIAL)
            self.assertEqual(report["stage_status"], "PARTIAL_MEASURED")

    def test_bare_trial_json_never_upgrades_at_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            lib.create_only_dir(TREE_DIR, root=root)
            lib.create_only_file(
                TREE + "trial.json",
                lib.canonical_json_bytes({"test_id": "PER-01",
                                          "status": "PASS_OBJECTIVE",
                                          "claims": []}),
                root=root)
            report = vf.verify_stage(root=root)
            self.assertEqual(report["per_test"]["PER-01"], "FAIL")
            self.assertIn("TRIAL_SCHEMA_UNKNOWN",
                          {v["code"] for v in report["violations"]})
            self.assertEqual(report["n_measured"], 0)
            self.assertEqual(report["measurement_status"], "NOT_RUN")

    def test_fixture_only_chain_never_earns_stage_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            _trial_inputs(root)
            self._write_trial_chain(root, fixture=True)
            report = vf.verify_stage(root=root)
            self.assertEqual(report["per_test"]["PER-01"], "FAIL")
            codes = {v["code"] for v in report["violations"]}
            self.assertIn("FIXTURE_AS_STAGE_EVIDENCE", codes)
            self.assertEqual(report["n_measured"], 0)

    def test_rejected_run_chain_never_earns_stage_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            _trial_inputs(root)
            self._write_trial_chain(root, valid=False)
            report = vf.verify_stage(root=root)
            self.assertEqual(report["per_test"]["PER-01"], "FAIL")
            codes = {v["code"] for v in report["violations"]}
            self.assertIn("TRIAL_STATUS_NOT_EARNED", codes)
            self.assertEqual(report["n_measured"], 0)

    # -- F9 stage-level gate wiring ----------------------------------------

    def test_candidate_gate_wired_and_coverage_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            plan = lib.strict_json_loads(
                lib.resolve_under_root(lib.PLAN_REL, root).read_bytes()
                .decode("utf-8"), source="plan")
            deps = ce.expected_candidate_dependencies(plan)
            # every expected dependency must exist under the temp root
            for rel in deps:
                target = lib.resolve_under_root(rel, root)
                if not os.path.lexists(str(target)):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if rel == lib.PLAN_REL:
                        data = lib.resolve_under_root(lib.PLAN_REL,
                                                      None).read_bytes()
                    else:
                        data = ("dependency-bytes:%s" % rel).encode("utf-8")
                    target.write_bytes(data)
            pinned = {rel: lib.sha256_file(lib.resolve_under_root(rel, root))
                      for rel in deps}
            payload = b'{"final-candidate":false}'
            cand_rel = TREE + "candidate.json"
            lib.create_only_dir(TREE_DIR, root=root)
            lib.create_only_file(cand_rel, payload, root=root)
            candidate = {
                "schema": ce.SCHEMA_CANDIDATE,
                "candidate_rel": cand_rel,
                "candidate_sha256": lib.sha256_bytes(payload),
                "source_hashes": pinned,
                "author_tree": TREE,
                "independent_tree": TREE + "-independent/",
                "plan_sha256": PLAN,
            }
            lib.create_only_file(
                vf.CANDIDATE_REL, lib.canonical_json_bytes(candidate),
                root=root)
            report = vf.verify_stage(root=root)
            self.assertEqual(report["candidate_status"], "VERIFIED",
                             json.dumps(report["violations"],
                                        ensure_ascii=False))
            # now drop one dependency pin: the coverage gate must fire
            candidate["source_hashes"].pop(deps[0])
            (root / vf.CANDIDATE_REL).write_bytes(
                lib.canonical_json_bytes(candidate))
            report = vf.verify_stage(root=root)
            self.assertEqual(report["candidate_status"], "VIOLATIONS")
            self.assertIn("CANDIDATE_COVERAGE_MISSING",
                          {v["code"] for v in report["violations"]})

    def test_closed_tree_gate_wired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._stage_root(tmp)
            lib.create_only_dir(TREE_DIR, root=root)
            lib.create_only_file(TREE + "a.txt", b"a", root=root)
            manifest = ce.build_manifest(ce.EVIDENCE_REL, root=root)
            lib.create_only_file(ce.EVIDENCE_REL + "manifest.json",
                                 lib.canonical_json_bytes(manifest),
                                 root=root)
            report = vf.verify_stage(root=root)
            self.assertEqual(report["closed_tree_status"], "VERIFIED",
                             json.dumps(report["violations"],
                                        ensure_ascii=False))
            # tamper with a covered file: the wired gate must flag it
            (root / TREE / "a.txt").write_bytes(b"tampered")
            report = vf.verify_stage(root=root)
            self.assertEqual(report["closed_tree_status"], "VIOLATIONS")
            self.assertIn("HASH_MISMATCH",
                          {v["code"] for v in report["violations"]})


class TestApiSelfDescription(unittest.TestCase):
    def test_api_manifests_nonempty(self):
        self.assertTrue(ce.api_manifest())
        self.assertTrue(vf.api_manifest())
        # the B1-r2 public proof/trial APIs are discoverable
        self.assertTrue(any(n.startswith("verify_rife_proof")
                            for n in ce.api_manifest()))
        self.assertTrue(any(n.startswith("gate_trial_report")
                            for n in ce.api_manifest()))


if __name__ == "__main__":
    unittest.main()
