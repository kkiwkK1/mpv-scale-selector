# -*- coding: utf-8 -*-
"""P4 unit tests for tools/p4_analyze.py (session p4-001, batch B1-r2 unit A).

Every test really invokes the analyze rejection logic (no hand-set booleans):
truncated windows are rejected without interpolation, epoch/ordered-pass-table
changes refuse to mix, time-pos regressions reject, duplicate run IDs fail,
mixed cells / RIFE strata / HQ fingerprints / media bindings refuse
aggregation, counter resets and vo-passes-as-dropped-proxy misuse are
rejected, missing counters stay explicit, bool/NaN/inf/negative ns values are
rejected, identical values are kept verbatim (never value-deduplicated),
roll-sample counts never inflate N, present frame duration stays
NOT_MEASURED, pass sums stay labelled as never end-to-end latency, bootstrap
is deterministic seed-424242 descriptive only, insufficient n is flagged
without significance, drop-affected runs participate, excluded runs keep
reason+original_dir, Integer k=1 can never be ranked with G1, tampered
comparability rects hit the registry check, and no result status can ever
certify PASS.

B1-r2 negative/positive coverage (each counterexample really invokes the
gate):
  * F1 empty-truth: empty fresh / redraw-only / zero-timing / empty-samples /
    count==0 windows are REJECTED_PASS_TABLE_EMPTY or REJECTED_PASS_NO_TIMING
    and never join MEASURED statistics; a legal empty redraw table stays
    VALID with an unmeasured (None, never 0) redraw pass sum; twelve empty
    runs aggregate to NOT_MEASURED with zero pollution;
  * F4 window schedule: ten records are not ten seconds — strict wall
    monotonicity, warmup_end anchor requirement and alignment, 1 Hz slot
    schedule within the preregistered ±0.25s sampling tolerance (fixed
    before measurement, inclusive boundary), 8.5..9.5s span band, late-poll
    exposure, 0.001s-step and too-short-window negatives; time_pos fine
    steps never act as a wall clock;
  * F5 context cross-validation (corrected coordinates): source identity
    (clip/media/generator) required and cross-checked, video w/h vs filtered
    source size, dw/dh as square-pixel source display size (the original
    review's dw/dh==rect confusion is now a rejection), osd window vs
    expected_window_size (never legacy output_size), observed margins must
    yield the registry rect, source-domain frame index/pts legality and
    M-class RIFE frames in their own index domain;
  * F6 fps binding: rife=on without observed_output_fps is rejected from
    statistics; off runs also record the observed fps; mismatch = fake
    metadata; match is necessary, never sufficient;
  * LF10/LF11: native count+samples_ns mapping, verbatim duplicate values,
    ordinal+desc identity keeping same-named passes separate, complete
    ordered table change rejected.
Stdlib + tempfile only; pure in-memory records; no GPU/mpv/runtime; no
credentials read; no external side effects.
"""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p4_lib as lib     # noqa: E402
import p4_analyze as an  # noqa: E402

PLAN = lib.PLAN_SHA256
_GENERATOR_SHA = lib.library_sha256()


class _Auto:
    """Sentinel: derive the stratum-correct observed output fps."""


_AUTO = _Auto()


def _hq(tag):
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _media_sha(clip):
    return hashlib.sha256(("p4-001/fixture-media/" + clip).encode("utf-8")).hexdigest()


def _pass(desc, avg_ns, samples_ns=None, count="default"):
    if samples_ns is None:
        samples_ns = [avg_ns] * 5
    return {"desc": desc, "last_ns": avg_ns * 2, "avg_ns": avg_ns,
            "peak_ns": avg_ns * 3,
            "count": len(samples_ns) if count == "default" else count,
            "samples_ns": list(samples_ns)}


def _snap(i, group="G1_equalrect_main", fresh_avgs=(900, 800),
          redraw_avgs=(380,), epoch=0, time_pos=12.0, wall=1000.0,
          include_margins=True, with_source=True, frame=None,
          fresh_table=None, redraw_table=None):
    geo = lib.expected_geometry(group)
    clip = lib.get_group(group)["clip"]
    vop = {"pixelformat": "yuv420p",
           "w": geo["source_w_h"][0], "h": geo["source_w_h"][1],
           "dw": geo["display_dw_dh"][0], "dh": geo["display_dw_dh"][1]}
    osd = {"w": geo["window_w_h"][0], "h": geo["window_w_h"][1]}
    if include_margins:
        ml, mt, mr, mb = geo["margins_ml_mt_mr_mb"]
        osd.update(ml=ml, mr=mr, mt=mt, mb=mb)
    snap = {
        "snapshot_index": i,
        "wall_monotonic_s": wall,
        "time_pos_s": time_pos,
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
        snap["source"] = {"clip": clip, "media_sha256": _media_sha(clip),
                          "generator_sha256": _GENERATOR_SHA}
    if frame is not None:
        snap["frame"] = dict(frame)
    return snap


def _record(run_id="run-1", rife="off", arm="baselineHQ",
            group="G1_equalrect_main", repeat=1, start=3, count=10,
            n_pre=3, n_post=0, fresh_a=lambda i: 900, fresh_b=lambda i: 800,
            redraw=lambda i: 380, epoch=lambda i: 0,
            tpos=lambda i: 12.0 + i, wall=lambda i: 1000.0 + i,
            warmup_end=_AUTO, hq="hq-base", observed_fps=_AUTO,
            drop_affected=None, excluded=None, replace_snap=None,
            include_margins=True, with_source=True, frame=None,
            fresh_table=None, redraw_table=None, run_kind="calibration"):
    total = n_pre + count + n_post
    anchor = wall(start) if warmup_end is _AUTO else warmup_end
    snaps = []
    for i in range(total):
        s = _snap(i, group=group, fresh_avgs=(fresh_a(i), fresh_b(i)),
                  redraw_avgs=(redraw(i),), epoch=epoch(i),
                  time_pos=tpos(i), wall=wall(i),
                  include_margins=include_margins, with_source=with_source,
                  frame=frame(i) if callable(frame) else frame,
                  fresh_table=fresh_table, redraw_table=redraw_table)
        if replace_snap is not None:
            s = replace_snap(i, s)
        snaps.append(s)
    spec = lib.make_trial_spec(group, arm, rife, repeat, run_kind=run_kind,
                               plan_sha256=PLAN)
    rec = {
        "schema": an.RUN_RECORD_SCHEMA,
        "run_id": run_id,
        "spec": spec,
        "window": {"start_snapshot_index": start, "sample_count": count,
                   "warmup_end_monotonic_s": anchor},
        "snapshots": snaps,
        "config_binding": {"hq_common_sha256": _hq(hq)},
    }
    if observed_fps is _AUTO:
        rec["observed_output_fps"] = spec["rife_output_fps"]
    elif observed_fps is not None:
        rec["observed_output_fps"] = observed_fps
    if drop_affected is not None:
        rec["drop_affected"] = drop_affected
    if excluded is not None:
        rec["excluded"] = excluded
    return rec


def _cell_records(rife="off", arm="baselineHQ", hq="hq-base",
                  fresh_ms=(10, 20, 30, 40, 50), prefix="run",
                  group="G1_equalrect_main"):
    """n runs whose pass-A fresh medians are fresh_ms[i] milliseconds."""
    return [
        _record(run_id="%s-%d" % (prefix, k + 1), rife=rife, arm=arm,
                group=group, repeat=k + 1, hq=hq,
                fresh_a=lambda i, v=(fresh_ms[k] * 1000000): v)
        for k in range(len(fresh_ms))]


def _empty_run(run_id, repeat=None):
    """A structurally valid record whose in-window vo-passes tables are all
    empty (the F1 blank-run counterexample from the independent review)."""
    return _record(run_id=run_id,
                   repeat=(repeat % 5) + 1 if repeat is not None else 1,
                   fresh_table=[], redraw_table=[])


class RunAnalysisTests(unittest.TestCase):
    def test_run_median_units_and_fresh_redraw_separate(self):
        rec = _record(run_id="run-1",
                      fresh_a=lambda i: max(0, i - 2) * 10000000)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        pass_a = analysis["passes"]["fresh"]["0|pass A"]
        # window values 10..100 million ns -> median 55,000,000 ns = 55.0 ms
        self.assertEqual(pass_a["avg_ms_median"], 55.0)
        self.assertEqual(pass_a["avg_ns_median"], 55000000.0)
        self.assertEqual(pass_a["identity"], "0|pass A")
        self.assertEqual(pass_a["slot"], 0)
        self.assertEqual(pass_a["desc"], "pass A")
        # fresh/redraw strictly separated tables
        self.assertIn("0|pass A redraw", analysis["passes"]["redraw"])
        self.assertNotIn("0|pass A redraw", analysis["passes"]["fresh"])
        self.assertNotEqual(pass_a["avg_ms_median"],
                            analysis["passes"]["redraw"]["0|pass A redraw"]
                            ["avg_ms_median"])

    def test_identical_values_kept_verbatim_not_deduped(self):
        rec = _record(run_id="run-1", fresh_a=lambda i: 900)
        analysis = an.analyze_run(rec)
        pass_a = analysis["passes"]["fresh"]["0|pass A"]
        self.assertEqual(pass_a["n_observations"], 10)   # not deduplicated to 1
        self.assertEqual(pass_a["avg_ns_values"], [900] * 10)
        self.assertEqual(pass_a["avg_ms_median"], 900 / 1e6)

    def test_bool_nan_inf_negative_avg_rejected(self):
        for bad in (True, False, float("nan"), float("inf"), float("-inf"),
                    -5):
            def rebuild(value=bad):
                return _record(
                    run_id="run-bad",
                    replace_snap=lambda i, s, v=value: (
                        dict(s, vo_passes=dict(
                            s["vo_passes"],
                            fresh=[_pass("pass A", v),
                                   _pass("pass B", 800)]))
                        if i == 5 else s))
            with self.assertRaises(lib.ValueContractError):
                an.analyze_run(rebuild())

    def test_missing_raw_snapshots_fail_closed(self):
        rec = _record(run_id="run-empty")
        rec["snapshots"] = []
        with self.assertRaises(lib.ValueContractError):
            an.analyze_run(rec)

    def test_duplicate_run_ids_rejected_globally(self):
        recs = [_record(run_id="run-1", repeat=1),
                _record(run_id="run-1", repeat=2)]
        with self.assertRaises(lib.ValueContractError):
            an.analyze_records(recs)


class WindowContractTests(unittest.TestCase):
    def test_slot_jitter_within_tolerance_and_warmup_excluded(self):
        # uniform +0.2s offset from the nominal warmup_end anchor: inside the
        # preregistered ±0.25s sampling tolerance
        rec = _record(
            run_id="run-1",
            wall=lambda i: 1000.0 + i + 0.2,
            warmup_end=1003.0,
            fresh_a=lambda i: 9999999 if i < 3 else 900)  # warmup spikes
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        self.assertEqual(analysis["window"]["observed_in_window"], 10)
        self.assertEqual(analysis["window"]["warmup_polls_before_window"], 3)
        self.assertAlmostEqual(
            max(abs(d) for d in analysis["window"]["slot_deviations_s"]),
            0.2, places=9)
        # warmup values must not leak into the window statistic
        self.assertEqual(analysis["passes"]["fresh"]["0|pass A"]["avg_ns_median"],
                         900.0)

    def test_post_window_polls_ignored(self):
        rec = _record(run_id="run-1", n_post=2,
                      fresh_a=lambda i: 900 if i < 13 else 9999999)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["window"]["post_window_polls"], 2)
        self.assertEqual(analysis["passes"]["fresh"]["0|pass A"]["avg_ns_median"],
                         900.0)

    def test_window_sample_count_is_preregistered_10(self):
        rec = _record(run_id="run-1", count=7)
        with self.assertRaises(lib.ValueContractError):
            an.analyze_run(rec)

    def test_window_requires_actual_warmup_end_anchor(self):
        rec = _record(run_id="run-1")
        del rec["window"]["warmup_end_monotonic_s"]
        with self.assertRaises(lib.ValueContractError) as ctx:
            an.validate_run_record(rec)
        self.assertIn("warmup_end_monotonic_s", str(ctx.exception))
        rec2 = _record(run_id="run-2", warmup_end="1003.0")  # not a number
        with self.assertRaises(lib.ValueContractError):
            an.validate_run_record(rec2)
        rec3 = _record(run_id="run-3", warmup_end=True)      # bool never
        with self.assertRaises(lib.ValueContractError):
            an.validate_run_record(rec3)

    def test_anchor_misaligned_with_slot_zero_rejected(self):
        rec = _record(run_id="run-1", warmup_end=1003.5)  # slot0 sits at 1003.0
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WINDOW_SCHEDULE")
        self.assertIn("slot 0", analysis["detail"])
        self.assertIsNone(analysis["medians"])

    def test_truncated_window_rejected_without_interpolation(self):
        rec = _record(run_id="run-trunc", n_pre=3, count=10)
        rec["snapshots"] = rec["snapshots"][:10]   # only indices 0..9 exist
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WINDOW_TRUNCATED")
        self.assertIsNone(analysis["medians"])     # never synthesised
        self.assertIn("never interpolated", analysis["reason"])
        self.assertEqual(analysis["window"]["observed_in_window"], 7)
        cell = an.aggregate_cell([rec])
        self.assertEqual(cell["n_rejected"], 1)
        self.assertEqual(cell["n_valid"], 0)
        self.assertEqual(cell["status"], an.STATUS_NOT_MEASURED)
        self.assertTrue(cell["insufficient"]["insufficient"])
        self.assertEqual(cell["rejected_by_analysis"][0]["run_id"], "run-trunc")

    def test_time_pos_regress_rejected(self):
        rec = _record(run_id="run-1",
                      tpos=lambda i: 5.0 if i == 8 else 12.0 + i)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_TIME_POS_REGRESS")

    def test_time_pos_fine_steps_never_act_as_wall_clock(self):
        # 0.001 s time_pos steps with a correct wall schedule stay valid:
        # time_pos is monotonic-only and never a wall-clock substitute
        rec = _record(run_id="run-1", tpos=lambda i: 12.0 + 0.001 * i)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)

    def test_epoch_change_refused_to_mix(self):
        rec = _record(run_id="run-1", epoch=lambda i: 0 if i < 8 else 1)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_EPOCH_MIXED")
        self.assertIsNone(analysis["medians"])

    def test_ordered_pass_table_change_refused_to_mix(self):
        rec = _record(
            run_id="run-1",
            replace_snap=lambda i, s: (
                dict(s, vo_passes=dict(s["vo_passes"],
                                       fresh=s["vo_passes"]["fresh"][:1]))
                if i == 8 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_PASS_SET_CHANGED")
        self.assertIn("fresh ordered desc table changed", analysis["detail"])


class WindowScheduleTests(unittest.TestCase):
    """F4: ten records are not ten seconds — real schedule invocation."""

    def test_boundary_deviation_exactly_tolerance_is_valid(self):
        # every slot +0.25s against the nominal anchor (inclusive bound)
        rec = _record(run_id="run-1",
                      wall=lambda i: 1000.0 + i + 0.25,
                      warmup_end=1003.0)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        self.assertAlmostEqual(analysis["window"]["slot_deviations_s"][0],
                               0.25, places=9)

    def test_boundary_deviation_beyond_tolerance_rejected(self):
        rec = _record(run_id="run-1",
                      wall=lambda i: 1000.0 + i + 0.26,
                      warmup_end=1003.0)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WINDOW_SCHEDULE")
        self.assertIn("±0.25", analysis["detail"])

    def test_identical_wall_times_rejected(self):
        rec = _record(run_id="run-1", wall=lambda i: 1000.0,
                      warmup_end=1003.0)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WALL_NON_MONOTONIC")
        self.assertIn("ten records are not ten seconds", analysis["reason"])

    def test_decreasing_wall_times_rejected(self):
        rec = _record(run_id="run-1", wall=lambda i: 1000.0 - i,
                      warmup_end=997.0)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WALL_NON_MONOTONIC")

    def test_0_001_intervals_not_a_window(self):
        rec = _record(run_id="run-1", wall=lambda i: 1000.0 + 0.001 * i,
                      warmup_end=1003.0)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WINDOW_SCHEDULE")

    def test_too_short_window_rejected(self):
        # 0.5 s polling period: ten records span only 4.5 seconds — the
        # slot schedule check fires (and the explicit 8.5..9.5s span band in
        # the preregistration is the belt-and-braces guard)
        rec = _record(run_id="run-1", wall=lambda i: 1000.0 + 0.5 * i,
                      warmup_end=1001.5)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WINDOW_SCHEDULE")
        self.assertIn("late polls are exposed", analysis["detail"])
        self.assertEqual(an.WINDOW_SPAN_MIN_S, 8.5)
        self.assertEqual(an.WINDOW_SPAN_MAX_S, 9.5)

    def test_single_late_poll_exposed_never_smoothed(self):
        # slot 5 (snapshot index 8) polls 0.6 s late, e.g. an nvidia-smi stall
        rec = _record(run_id="run-1",
                      wall=lambda i: 1000.0 + i + (0.6 if i == 8 else 0.0))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_WINDOW_SCHEDULE")
        self.assertIn("slot 5", analysis["detail"])
        self.assertIn("late poll", analysis["detail"])

    def test_full_window_span_boundary_9_5_is_valid(self):
        # slot 0 at -0.25s, slot 9 at +0.25s, all intermediate slots exact:
        # span exactly 9.5s stays inside the inclusive band
        def wall(i):
            if i == 3:
                return 1000.0 + i - 0.25
            if i == 12:
                return 1000.0 + i + 0.25
            return 1000.0 + i
        rec = _record(run_id="run-1", wall=wall, warmup_end=1003.0)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        self.assertAlmostEqual(analysis["window"]["span_s"], 9.5, places=9)

    def test_schedule_contract_is_preregistered_not_tuned(self):
        contract = an.WINDOW_CONTRACT
        self.assertEqual(contract["slot_tolerance_s"], 0.25)
        self.assertEqual(contract["slot_period_s"], 1.0)
        self.assertEqual(contract["span_bounds_s"], [8.5, 9.5])
        self.assertIn("BEFORE any measurement",
                      contract["tolerance_preregistration"])
        self.assertIn("never tuned on performance results",
                      contract["tolerance_preregistration"])
        self.assertIn("never a present-timing guarantee",
                      contract["tolerance_preregistration"])
        self.assertIn("half-open", contract["rule"])
        self.assertIn("ten records are not ten seconds", contract["rule"])
        self.assertIn("REQUIRED", contract["warmup_anchor"])
        self.assertEqual(an.MEASUREMENT_KIND["window_schedule"].count("never"), 2)


class EmptyTruthTests(unittest.TestCase):
    """F1: blank runs can never masquerade as measured."""

    def test_empty_fresh_table_rejected_even_with_redraw(self):
        rec = _record(run_id="blank",
                      replace_snap=lambda i, s: (
                          dict(s, vo_passes={"fresh": [], "redraw": [
                              _pass("pass A redraw", 380)]})
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_PASS_TABLE_EMPTY")
        self.assertIn("redraw", analysis["detail"])
        self.assertIn("substitute", analysis["detail"])
        self.assertIsNone(analysis["medians"])

    def test_all_empty_tables_rejected(self):
        analysis = an.analyze_run(_empty_run("blank"))
        self.assertEqual(analysis["status"], "REJECTED_PASS_TABLE_EMPTY")
        self.assertIn("never a 0 ms window", analysis["detail"])

    def test_zero_avg_ns_entry_rejected(self):
        rec = _record(run_id="zero",
                      replace_snap=lambda i, s: (
                          dict(s, vo_passes=dict(
                              s["vo_passes"],
                              fresh=[_pass("pass A", 0),
                                     _pass("pass B", 800)]))
                          if i == 6 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_PASS_NO_TIMING")
        self.assertIn("avg_ns=0", analysis["detail"])

    def test_empty_samples_ns_entry_rejected(self):
        rec = _record(run_id="nosamples",
                      replace_snap=lambda i, s: (
                          dict(s, vo_passes=dict(
                              s["vo_passes"],
                              fresh=[_pass("pass A", 900, samples_ns=[]),
                                     _pass("pass B", 800)]))
                          if i == 6 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_PASS_NO_TIMING")
        self.assertIn("len(samples_ns)=0", analysis["detail"])

    def test_native_count_zero_entry_rejected(self):
        rec = _record(run_id="count0",
                      replace_snap=lambda i, s: (
                          dict(s, vo_passes=dict(
                              s["vo_passes"],
                              redraw=[_pass("pass A redraw", 380, samples_ns=[],
                                            count=0)]))
                          if i == 6 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_PASS_NO_TIMING")
        self.assertIn("count=0", analysis["detail"])

    def test_count_null_with_real_samples_is_valid(self):
        rec = _record(run_id="countnull",
                      replace_snap=lambda i, s: (
                          dict(s, vo_passes=dict(
                              s["vo_passes"],
                              fresh=[_pass("pass A", 900, count=None),
                                     _pass("pass B", 800)]))
                          if i == 6 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)

    def test_legal_empty_redraw_keeps_unmeasured_never_zero(self):
        rec = _record(run_id="noredraw", redraw_table=[])
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        self.assertEqual(analysis["passes"]["redraw"], {})
        self.assertAlmostEqual(analysis["pass_sum"]["fresh_ms"],
                               (900 + 800) / 1e6)   # (900+800)ns in ms
        self.assertIsNone(analysis["pass_sum"]["redraw_ms"])     # never 0.0
        self.assertEqual(analysis["pass_sum"]["unmeasured_tables"], ["redraw"])
        self.assertIn("never coerced to 0",
                      analysis["pass_sum"]["measurement_kind"])

    def test_twelve_blank_runs_never_reach_measured(self):
        recs = [_empty_run("blank-%d" % k, repeat=k) for k in range(1, 13)]
        cell = an.aggregate_cell(recs)
        self.assertEqual(cell["status"], an.STATUS_NOT_MEASURED)
        self.assertEqual(cell["n_valid"], 0)
        self.assertEqual(cell["n_rejected"], 12)
        self.assertEqual(cell["passes"], {"fresh": {}, "redraw": {}})
        self.assertIsNone(cell["pass_sum"]["fresh_ms_median_across_runs"])
        self.assertIsNone(cell["pass_sum"]["redraw_ms_median_across_runs"])
        self.assertNotIn(0.0, (cell["pass_sum"]["fresh_ms_median_across_runs"],
                               cell["pass_sum"]["redraw_ms_median_across_runs"]))
        for entry in cell["rejected_by_analysis"]:
            self.assertEqual(entry["status"], "REJECTED_PASS_TABLE_EMPTY")
            self.assertIsNotNone(entry["reason"])
        bundle = an.analyze_records(recs)
        self.assertEqual(len(bundle["cells"]), 1)


class GeometryContextTests(unittest.TestCase):
    """F5 with the corrected coordinate semantics."""

    def test_valid_g1_context_verified(self):
        analysis = an.analyze_run(_record(run_id="run-1"))
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        geo = analysis["context"]["geometry"]
        self.assertEqual(geo["video_source_w_h"], [1920, 1080])
        self.assertEqual(geo["display_dw_dh"], [1920, 1080])
        self.assertEqual(geo["observed_window_w_h"], [2560, 1440])
        self.assertEqual(geo["observed_margins_ml_mt_mr_mb"], [0, 0, 0, 0])
        self.assertEqual(geo["observed_rect_w_h"], [2560, 1440])
        self.assertEqual(geo["rect_status"], "VERIFIED_MATCHES_REGISTRY")
        self.assertEqual(geo["expected"]["rect_w_h"], [2560, 1440])

    def test_wrong_video_size_rejected(self):
        # 64x64 render params in a 1920x1080 motion24 run (review counterexample)
        rec = _record(run_id="geo",
                      replace_snap=lambda i, s: (
                          dict(s, video_out_params=dict(
                              s["video_out_params"], w=64, h=64, dw=32, dh=32))
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_GEOMETRY_MISMATCH")
        self.assertIn("post-filter", analysis["detail"])
        self.assertIn("64x64", analysis["detail"])

    def test_dw_dh_as_window_rect_is_rejected(self):
        # the ORIGINAL (wrong) F5-fix interpretation: dw/dh == display rect
        # 2560x1440. The corrected contract: dw/dh is the square-pixel source
        # display size (1920x1080) — the old confusion is now a rejection.
        rec = _record(run_id="geo",
                      replace_snap=lambda i, s: (
                          dict(s, video_out_params=dict(
                              s["video_out_params"], dw=2560, dh=1440))
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_GEOMETRY_MISMATCH")
        self.assertIn("NOT the window", analysis["detail"])

    def test_video_size_used_as_window_rejected(self):
        # osd 1920x1080 is the VIDEO size, not the G1 window (legacy mixing)
        rec = _record(run_id="geo",
                      replace_snap=lambda i, s: (
                          dict(s, osd_dimensions={"w": 1920, "h": 1080,
                                                  "ml": 0, "mr": 0,
                                                  "mt": 0, "mb": 0})
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_GEOMETRY_MISMATCH")
        self.assertIn("expected_window", analysis["detail"])

    def test_wrong_observed_margins_rejected(self):
        rec = _record(run_id="geo",
                      replace_snap=lambda i, s: (
                          dict(s, osd_dimensions=dict(s["osd_dimensions"],
                                                      ml=100))
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_GEOMETRY_MISMATCH")
        self.assertIn("margins", analysis["detail"])

    def test_missing_margins_disclosed_not_faked(self):
        rec = _record(run_id="nomargins", include_margins=False)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        geo = analysis["context"]["geometry"]
        self.assertIsNone(geo["observed_margins_ml_mt_mr_mb"])
        self.assertIsNone(geo["observed_rect_w_h"])
        self.assertEqual(geo["rect_status"], "NOT_OBSERVED_NO_MARGINS")
        self.assertIn("never", geo["note"])

    def test_g2_letterbox_positive_and_wrong_margins_negative(self):
        analysis = an.analyze_run(_record(run_id="g2", group="G2_integer_display",
                                          arm="Integer"))
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        geo = analysis["context"]["geometry"]
        self.assertEqual(geo["observed_window_w_h"], [2560, 1440])
        self.assertEqual(geo["observed_margins_ml_mt_mr_mb"], [320, 180, 320, 180])
        self.assertEqual(geo["observed_rect_w_h"], [1920, 1080])
        self.assertEqual(geo["rect_status"], "VERIFIED_MATCHES_REGISTRY")
        bad = _record(run_id="g2bad", group="G2_integer_display", arm="Integer",
                      replace_snap=lambda i, s: (
                          dict(s, osd_dimensions=dict(s["osd_dimensions"],
                                                      ml=0, mr=0, mt=0, mb=0))
                          if i == 5 else s))
        analysis = an.analyze_run(bad)
        self.assertEqual(analysis["status"], "REJECTED_GEOMETRY_MISMATCH")
        self.assertIn("margins", analysis["detail"])

    def test_g2b_and_g3_groups_verified(self):
        g2b = an.analyze_run(_record(run_id="g2b", group="G2b_integer_k2",
                                     arm="nearest"))
        self.assertEqual(g2b["status"], an.RUN_STATUS_VALID)
        self.assertEqual(g2b["context"]["geometry"]["observed_window_w_h"],
                         [2560, 1440])
        g3 = an.analyze_run(_record(run_id="g3", group="G3_pixelart",
                                    arm="xBR-lv2"))
        self.assertEqual(g3["status"], an.RUN_STATUS_VALID)
        self.assertEqual(g3["context"]["geometry"]["video_source_w_h"],
                         [480, 360])
        self.assertEqual(g3["context"]["geometry"]["observed_window_w_h"],
                         [1440, 1080])


class SourceIdentityTests(unittest.TestCase):
    def test_missing_source_observations_rejected(self):
        rec = _record(run_id="nosource", with_source=False)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_SOURCE_MISMATCH")
        self.assertIn("lacks the required source", analysis["detail"])

    def test_source_missing_in_one_snapshot_rejected(self):
        rec = _record(run_id="partial-source",
                      replace_snap=lambda i, s: (
                          {k: v for k, v in s.items() if k != "source"}
                          if i == 7 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_SOURCE_MISMATCH")

    def test_wrong_clip_rejected(self):
        rec = _record(run_id="wrongclip",
                      replace_snap=lambda i, s: (
                          dict(s, source=dict(s["source"], clip="pixelart"))
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_SOURCE_MISMATCH")
        self.assertIn("pixelart", analysis["detail"])

    def test_wrong_generator_revision_rejected(self):
        other = hashlib.sha256(b"another-lib-revision").hexdigest()
        rec = _record(run_id="wronggen",
                      replace_snap=lambda i, s: (
                          dict(s, source=dict(s["source"],
                                              generator_sha256=other))
                          if i == 5 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_SOURCE_MISMATCH")
        self.assertIn("library revision", analysis["detail"])

    def test_media_hash_change_in_window_rejected(self):
        rec = _record(run_id="mediachange",
                      replace_snap=lambda i, s: (
                          dict(s, source=dict(
                              s["source"],
                              media_sha256=hashlib.sha256(b"other").hexdigest()))
                          if i >= 8 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_SOURCE_MISMATCH")
        self.assertIn("changed in-window", analysis["detail"])

    def test_cell_mixing_different_media_hashes_refused(self):
        recs = _cell_records(fresh_ms=(10, 20))
        recs[1] = _record(run_id="run-2", repeat=2,
                          replace_snap=lambda i, s: dict(
                              s, source=dict(s["source"],
                                             media_sha256=hashlib.sha256(
                                                 b"different-media").hexdigest())))
        with self.assertRaises(lib.TrialSpecError) as ctx:
            an.aggregate_cell(recs)
        self.assertIn("media_sha256", str(ctx.exception))

    def test_source_binding_travels_to_cell_comparability(self):
        res = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30)))
        self.assertEqual(res["comparability"]["media_sha256"],
                         _media_sha("motion24"))


class FrameIdentityTests(unittest.TestCase):
    FRAME = {"index": 5, "pts_num": 5, "pts_den": 24, "frame_class": "S"}

    def test_valid_source_frame_identity(self):
        rec = _record(run_id="fr", frame=self.FRAME)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        self.assertEqual(analysis["context"]["frames"]
                         ["source_domain_frames_checked"], 10)

    def test_index_out_of_source_range_rejected(self):
        rec = _record(run_id="fr", frame=dict(self.FRAME, index=10 ** 9,
                                              pts_num=10 ** 9))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_FRAME_IDENTITY")
        self.assertIn("outside clip", analysis["detail"])

    def test_index_at_range_boundary(self):
        ok = an.analyze_run(_record(run_id="fr", frame=dict(self.FRAME,
                                                            index=719,
                                                            pts_num=719)))
        self.assertEqual(ok["status"], an.RUN_STATUS_VALID)
        bad = an.analyze_run(_record(run_id="fr", frame=dict(self.FRAME,
                                                             index=720,
                                                             pts_num=720)))
        self.assertEqual(bad["status"], "REJECTED_FRAME_IDENTITY")

    def test_pts_not_matching_index_fps_rejected(self):
        rec = _record(run_id="fr", frame=dict(self.FRAME, pts_den=999))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_FRAME_IDENTITY")
        rec2 = _record(run_id="fr2", frame=dict(self.FRAME, pts_num=6))
        analysis2 = an.analyze_run(rec2)
        self.assertEqual(analysis2["status"], "REJECTED_FRAME_IDENTITY")

    def test_m_class_rife_frame_is_a_different_index_domain(self):
        mframe = {"index": 50000, "pts_num": 25000, "pts_den": 48,
                  "frame_class": "M"}
        on = an.analyze_run(_record(run_id="on", rife="on", frame=mframe))
        self.assertEqual(on["status"], an.RUN_STATUS_VALID)  # own domain
        off = an.analyze_run(_record(run_id="off", rife="off", frame=mframe))
        self.assertEqual(off["status"], "REJECTED_FRAME_IDENTITY")
        self.assertIn("rife=off", off["detail"])

    def test_frames_absent_is_legal_and_disclosed(self):
        rec = _record(run_id="nofr", frame=None)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        self.assertEqual(analysis["context"]["frames"]
                         ["source_domain_frames_checked"], 0)


class RifeFpsBindingTests(unittest.TestCase):
    def test_on_without_observed_fps_never_joins_statistics(self):
        rec = _record(run_id="unbound", rife="on", observed_fps=None)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_FPS_UNBOUND")
        self.assertIn("necessary", analysis["reason"])
        cell = an.aggregate_cell([_record(run_id="ok", rife="on", repeat=1),
                                  rec])
        self.assertEqual(cell["n_valid"], 1)
        self.assertEqual(cell["n_rejected"], 1)
        self.assertEqual(cell["rejected_by_analysis"][0]["status"],
                         "REJECTED_FPS_UNBOUND")

    def test_on_with_matching_fps_is_necessary_never_sufficient(self):
        ok = an.analyze_run(_record(run_id="ok", rife="on", observed_fps=48))
        self.assertEqual(ok["status"], an.RUN_STATUS_VALID)
        self.assertIn("never sufficient", ok["rife_execution_proof"])

    def test_off_stratum_also_records_observed_fps(self):
        ok = an.analyze_run(_record(run_id="off-ok", rife="off",
                                    observed_fps=24))
        self.assertEqual(ok["status"], an.RUN_STATUS_VALID)
        self.assertIn("necessary", ok["rife_execution_proof"])
        fake = an.analyze_run(_record(run_id="off-fake", rife="off",
                                      observed_fps=30))
        self.assertEqual(fake["status"], "REJECTED_FAKE_RIFE_METADATA")
        self.assertIn("observed_output_fps=30", fake["detail"])

    def test_observed_fps_type_contract(self):
        for bad in (True, 48.5, "48"):
            rec = _record(run_id="bad", rife="on", observed_fps=bad)
            if bad == 48.5:
                analysis = an.analyze_run(rec)  # finite number, wrong value
                self.assertEqual(analysis["status"],
                                 "REJECTED_FAKE_RIFE_METADATA")
            else:
                with self.assertRaises(lib.ValueContractError):
                    an.analyze_run(rec)


class PassIdentityTests(unittest.TestCase):
    """LF10 native mapping + LF11 ordinal+desc identity."""

    def _dup_record(self, run_id="dup"):
        # same-named passes are legal when the ORDERED table is constant
        # across the window; slot 1 values vary per snapshot (real data)
        def dup(i, s):
            fresh = [_pass("pass A", 900), _pass("pass A", 1000 + i),
                     _pass("pass B", 800)]
            return dict(s, vo_passes=dict(s["vo_passes"], fresh=fresh))
        return _record(run_id=run_id, replace_snap=dup)

    def test_same_named_passes_keep_separate_slots_and_data(self):
        analysis = an.analyze_run(self._dup_record())
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        fresh = analysis["passes"]["fresh"]
        self.assertIn("0|pass A", fresh)
        self.assertIn("1|pass A", fresh)
        self.assertNotEqual(fresh["0|pass A"]["avg_ns_median"],
                            fresh["1|pass A"]["avg_ns_median"])
        # in-window slot values 1003..1012 ns -> median 1007.5
        self.assertEqual(fresh["1|pass A"]["avg_ns_median"], 1007.5)
        self.assertEqual(fresh["0|pass A"]["n_observations"], 10)
        self.assertEqual(fresh["1|pass A"]["n_observations"], 10)  # own slot data
        self.assertEqual(analysis["pass_order"]["fresh"][:3],
                         ["pass A", "pass A", "pass B"])

    def test_pass_table_order_change_rejected_even_with_same_multiset(self):
        def swapped(i, s):
            if i != 5:
                return s
            fresh = list(reversed(s["vo_passes"]["fresh"]))
            return dict(s, vo_passes=dict(s["vo_passes"], fresh=fresh))
        rec = _record(run_id="swap", replace_snap=swapped)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_PASS_SET_CHANGED")

    def test_native_samples_arrays_kept_verbatim_in_record(self):
        rec = _record(run_id="raw")
        entry = rec["snapshots"][5]["vo_passes"]["fresh"][0]
        self.assertEqual(entry["samples_ns"], [900] * 5)
        self.assertEqual(entry["count"], 5)
        lib.validate_snapshot(rec["snapshots"][5])  # schema keeps them as-is

    def test_aggregate_keys_are_slot_identities(self):
        res = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30, 40, 50)))
        self.assertIn("0|pass A", res["passes"]["fresh"])
        entry = res["passes"]["fresh"]["0|pass A"]
        self.assertEqual(entry["median_of_run_medians_ms"], 30.0)
        self.assertEqual(entry["desc"], "pass A")
        self.assertEqual(res["pass_order"]["fresh"], ["pass A", "pass B"])
        pairing = an.rife_pairing(
            an.aggregate_cell(_cell_records(rife="off", prefix="off",
                                            fresh_ms=(20,) * 5)),
            an.aggregate_cell(_cell_records(rife="on", prefix="on",
                                            fresh_ms=(25,) * 5)))
        self.assertEqual(pairing["passes"]["fresh"]["0|pass A"]["off_ms"], 20.0)
        self.assertEqual(pairing["passes"]["fresh"]["0|pass A"]["on_ms"], 25.0)

    def test_old_int_samples_fixture_shape_is_rejected(self):
        # the pre-r2 mock shape (samples:int) encoded the native-API misreading
        rec = _record(run_id="old")
        rec["snapshots"][5]["vo_passes"]["fresh"][0] = {
            "desc": "pass A", "last_ns": 1, "avg_ns": 900, "peak_ns": 3,
            "samples": 5}
        with self.assertRaises(lib.ValueContractError) as ctx:
            an.analyze_run(rec)
        self.assertIn("LF10", str(ctx.exception))


class CellAggregationTests(unittest.TestCase):
    def test_cross_run_median_and_bootstrap_deterministic(self):
        recs = _cell_records(fresh_ms=(10, 20, 30, 40, 50))
        res = an.aggregate_cell(recs)
        self.assertEqual(res["status"], an.STATUS_MEASURED)
        self.assertEqual(res["n_valid"], 5)
        self.assertEqual(res["n_target"], 5)
        entry = res["passes"]["fresh"]["0|pass A"]
        self.assertEqual(entry["median_of_run_medians_ms"], 30.0)
        self.assertEqual(entry["per_run_avg_ms_medians"]["run-1"], 10.0)
        boot = entry["bootstrap"]
        self.assertEqual(boot["n_boot"], 10000)
        self.assertEqual(boot["seed"], 424242)
        self.assertTrue(boot["ci95_pct"][0] <= 30.0 <= boot["ci95_pct"][1])
        # deterministic bootstrap: identical bytes on recompute
        res2 = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30, 40, 50)))
        self.assertEqual(an.result_json_bytes(res), an.result_json_bytes(res2))

    def test_insufficient_n_flagged_no_significance(self):
        recs = _cell_records(fresh_ms=(10, 20)) + [
            _record(run_id="ex-%d" % k, repeat=k,
                    excluded={"code": "E2", "reason": "temperature gate",
                              "original_dir": "docs/验证/开发/p4-001/x/run-%d" % k})
            for k in (1, 2, 3)]
        res = an.aggregate_cell(recs)
        self.assertEqual(res["status"], an.STATUS_PARTIAL)
        self.assertTrue(res["insufficient"]["insufficient"])
        self.assertEqual(res["n_valid"], 2)
        self.assertEqual(res["n_target"], 5)
        self.assertIn("NOT_ASSESSED", res["significance"])
        self.assertIn("insufficient n", res["significance"])
        # excluded runs preserved verbatim with reason + original dir
        self.assertEqual(len(res["excluded_runs"]), 3)
        self.assertEqual(res["excluded_runs"][0]["code"], "E2")
        self.assertEqual(res["excluded_runs"][0]["reason"], "temperature gate")
        self.assertTrue(res["excluded_runs"][0]["original_dir"].endswith("run-1"))

    def test_all_runs_rejected_cell_not_measured(self):
        recs = []
        for k in (1, 2):
            rec = _record(run_id="trunc-%d" % k, repeat=k, n_pre=3, count=10)
            rec["snapshots"] = rec["snapshots"][:6]
            recs.append(rec)
        res = an.aggregate_cell(recs)
        self.assertEqual(res["status"], an.STATUS_NOT_MEASURED)
        self.assertEqual(res["passes"], {"fresh": {}, "redraw": {}})
        self.assertIsNone(res["pass_sum"]["fresh_ms_median_across_runs"])
        self.assertTrue(res["pass_sum"]["unmeasured_pass_sums"]["fresh"])

    def test_mixed_cells_refused(self):
        recs = [_record(run_id="g1", group="G1_equalrect_main"),
                _record(run_id="g3", group="G3_pixelart", arm="xBR-lv2",
                        repeat=1)]
        with self.assertRaises(lib.TrialSpecError):
            an.aggregate_cell(recs)

    def test_mixed_rife_strata_refused(self):
        recs = [_record(run_id="off", rife="off", repeat=1),
                _record(run_id="on", rife="on", repeat=1)]
        with self.assertRaises(lib.TrialSpecError):
            an.aggregate_cell(recs)

    def test_hq_common_fingerprint_mismatch_refused(self):
        recs = [_record(run_id="a", hq="hq-config-A", repeat=1),
                _record(run_id="b", hq="hq-config-B", repeat=2)]
        with self.assertRaises(lib.TrialSpecError):
            an.aggregate_cell(recs)

    def test_drop_affected_runs_participate(self):
        recs = _cell_records(fresh_ms=(10, 20, 30, 40, 50))
        recs[2] = _record(run_id="run-3", repeat=3, drop_affected=True,
                          fresh_a=lambda i: 30000000)
        res = an.aggregate_cell(recs)
        self.assertIn("run-3", res["run_ids"])
        self.assertEqual(res["drop_affected_run_ids"], ["run-3"])
        self.assertEqual(res["status"], an.STATUS_MEASURED)

    def test_bundle_run_index_unique_and_grouped(self):
        g1 = _cell_records(fresh_ms=(10, 20, 30, 40, 50))
        g2b = [_record(run_id="g2b-%d" % k, group="G2b_integer_k2",
                       arm="nearest", repeat=k)
               for k in (1, 2, 3)]
        bundle = an.analyze_records(g1 + g2b)
        self.assertEqual(set(bundle["cells"]),
                         {"G1_equalrect_main|baselineHQ|motion24@24|rife=off",
                          "G2b_integer_k2|nearest|motion720@24|rife=off"})
        self.assertEqual(bundle["run_index"]["run-1"],
                         "G1_equalrect_main|baselineHQ|motion24@24|rife=off")
        self.assertEqual(len(bundle["run_index"]), 8)


class CounterSemanticsTests(unittest.TestCase):
    def test_counter_delta_and_saturation_never_blocking(self):
        def mk(a, b):
            return _record(
                run_id="run-1",
                replace_snap=lambda i, s, a=a, b=b: (
                    dict(s, counters={"dropped-frame-count": a if i == 3 else b})
                    if i in (3, 12) else s))
        growth = an.analyze_run(mk(5, 8))
        entry = growth["counters"]["dropped-frame-count"]
        self.assertEqual(entry["delta"], 3)
        self.assertFalse(entry["no_growth"])
        self.assertFalse(entry["blocking"])
        flat = an.analyze_run(mk(5, 5))
        entry = flat["counters"]["dropped-frame-count"]
        self.assertEqual(entry["delta"], 0)
        self.assertTrue(entry["no_growth"])
        self.assertFalse(entry["blocking"])

    def test_negative_counter_delta_rejected(self):
        rec = _record(
            run_id="run-1",
            replace_snap=lambda i, s: (
                dict(s, counters={"dropped-frame-count": 5 if i == 3 else 3})
                if i in (3, 12) else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_COUNTER_RESET")
        self.assertIsNone(analysis["medians"])
        entry = analysis["counters"]["dropped-frame-count"]
        self.assertEqual(entry["status"], "counter_reset_invalid")
        self.assertIsNone(entry["delta"])
        cell = an.aggregate_cell([rec])
        self.assertEqual(cell["n_valid"], 0)
        self.assertEqual(cell["rejected_by_analysis"][0]["status"],
                         "REJECTED_COUNTER_RESET")

    def test_missing_counter_explicit_never_zero(self):
        rec = _record(
            run_id="run-1",
            replace_snap=lambda i, s: (
                dict(s, counters={"dropped-frame-count": 4}) if i == 3 else s))
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], an.RUN_STATUS_VALID)
        entry = analysis["counters"]["dropped-frame-count"]
        self.assertEqual(entry["status"], "missing")
        self.assertIsNone(entry["delta"])   # explicitly missing, not 0

    def test_vo_passes_count_never_dropped_proxy(self):
        rec = _record(
            run_id="run-1",
            replace_snap=lambda i, s: (
                dict(s, counters={"vo_passes.fresh.count": 100})
                if i == 3 else s))
        with self.assertRaises(lib.ValueContractError):
            an.analyze_run(rec)


class PresentAndLatencyLabelTests(unittest.TestCase):
    def test_present_frame_duration_not_measured(self):
        analysis = an.analyze_run(_record(run_id="run-1"))
        present = analysis["present_frame_duration"]
        self.assertEqual(present["status"], an.NOT_MEASURED)
        self.assertEqual(set(present), {"status", "reason"})
        self.assertIn("time-pos", present["reason"])
        e2e = analysis["end_to_end_gpu_latency"]
        self.assertEqual(e2e["status"], an.NOT_MEASURED)

    def test_pass_sum_labelled_never_total_gpu_latency(self):
        res = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30, 40, 50)))
        self.assertIn("NOT end-to-end GPU latency",
                      res["pass_sum"]["measurement_kind"])
        self.assertEqual(res["end_to_end_gpu_latency"]["status"],
                         an.NOT_MEASURED)
        self.assertIn("never an independent frame count",
                      res["measurement_kind"]["samples_field"])
        self.assertIn("no value deduplication",
                      res["measurement_kind"]["value_dedup"])
        self.assertIn("LF10", res["measurement_kind"]["samples_field"])
        self.assertIn("ordinal+desc", res["measurement_kind"]["pass_identity"])
        self.assertEqual(res["performance_conclusion"],
                         an.PERFORMANCE_CONCLUSION)


class RifeStrataTests(unittest.TestCase):
    def test_fake_rife_metadata_rejected_by_observed_fps(self):
        rec = _record(run_id="fake", rife="on", repeat=1, observed_fps=24)
        analysis = an.analyze_run(rec)
        self.assertEqual(analysis["status"], "REJECTED_FAKE_RIFE_METADATA")
        self.assertIn("rife_output_fps=48", analysis["detail"])

    def test_pairing_structure_no_headroom_number(self):
        off = an.aggregate_cell(_cell_records(
            rife="off", fresh_ms=(20, 20, 20, 20, 20), prefix="off"))
        on = an.aggregate_cell(_cell_records(
            rife="on", fresh_ms=(25, 25, 25, 25, 25), prefix="on"))
        for res in (on,):
            self.assertIn("rife_on_disclosure", res)
        pairing = an.rife_pairing(off, on)
        self.assertEqual(pairing["passes"]["fresh"]["0|pass A"]["off_ms"], 20.0)
        self.assertEqual(pairing["passes"]["fresh"]["0|pass A"]["on_ms"], 25.0)
        self.assertEqual(
            pairing["passes"]["fresh"]["0|pass A"]["delta_ms_on_minus_off"],
            5.0)
        self.assertIn("mixed S", pairing["on_frame_composition"])
        self.assertIn("NONE", pairing["per_frame_gpu_attribution"])
        serialized = an.result_json_bytes(pairing)
        self.assertNotIn(b"overall_headroom_ms", serialized)
        self.assertNotIn(b"headroom_ms", serialized)
        self.assertIn(b"headroom_semantics", serialized)  # prohibition note

    def test_pairing_arm_mismatch_refused(self):
        off = an.aggregate_cell([_record(run_id="o", rife="off", repeat=1,
                                         arm="baselineHQ")])
        on = an.aggregate_cell([_record(run_id="n", rife="on", repeat=1,
                                        arm="FSR1")])
        with self.assertRaises(lib.TrialSpecError):
            an.rife_pairing(off, on)

    def test_pairing_same_stratum_refused(self):
        off1 = an.aggregate_cell([_record(run_id="o1", rife="off", repeat=1)])
        off2 = an.aggregate_cell([_record(run_id="o2", rife="off", repeat=2)])
        with self.assertRaises(lib.TrialSpecError):
            an.rife_pairing(off1, off2)

    def test_integer_k1_never_ranked_with_g1_fullrect(self):
        g1 = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30, 40, 50)))
        g2 = an.aggregate_cell([
            _record(run_id="int-%d" % k, group="G2_integer_display",
                    arm="Integer", repeat=k) for k in (1, 2)])
        with self.assertRaises(lib.TrialSpecError):
            an.assert_cell_results_comparable(g1, g2)

    def test_tampered_rect_hits_registry_revalidation(self):
        res = an.aggregate_cell([_record(run_id="run-1", repeat=1)])
        self.assertEqual(res["comparability"]["expected_rect"],
                         lib.GROUPS["G1_equalrect_main"]["expected_rect"])
        tampered = copy.deepcopy(res)
        tampered["comparability"]["expected_rect"] = [123, 456]
        with self.assertRaises(lib.TrialSpecError):
            an.assert_cell_results_comparable(res, tampered)

    def test_tampered_media_binding_hits_comparability(self):
        res = an.aggregate_cell([_record(run_id="run-1", repeat=1)])
        tampered = copy.deepcopy(res)
        tampered["comparability"]["media_sha256"] = "f" * 64
        with self.assertRaises(lib.TrialSpecError):
            an.assert_cell_results_comparable(res, tampered)

    def test_hq_fingerprint_mismatch_between_cells_refused(self):
        a = an.aggregate_cell([_record(run_id="a", hq="cfg-1", repeat=1)])
        b = an.aggregate_cell([_record(run_id="b", hq="cfg-2", repeat=1)])
        with self.assertRaises(lib.TrialSpecError):
            an.assert_cell_results_comparable(a, b)


class ResultIntegrityTests(unittest.TestCase):
    def test_status_vocabulary_never_certifies_pass(self):
        res = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30, 40, 50)))
        self.assertIn(res["status"], an.STATUS_VOCABULARY)
        self.assertTrue(an.assert_no_pass_verdict(res))
        for fake in ("PASS", "PASS_OBJECTIVE", "全P4PASS"):
            bad = copy.deepcopy(res)
            bad["status"] = fake
            with self.assertRaises(lib.ValueContractError):
                an.assert_no_pass_verdict(bad)
        bad = copy.deepcopy(res)
        bad["performance_conclusion"] = "CAUSAL_FASTER_CLAIM"
        with self.assertRaises(lib.ValueContractError):
            an.assert_no_pass_verdict(bad)

    def test_result_json_canonical_strict_roundtrip(self):
        res = an.aggregate_cell(_cell_records(fresh_ms=(10, 20, 30, 40, 50)))
        raw = an.result_json_bytes(res)
        self.assertNotIn(b"NaN", raw)
        self.assertNotIn(b"Infinity", raw)
        self.assertEqual(lib.strict_json_loads(raw), res)
        # every rejection status is documented and ordered deterministically
        for status in an.RUN_REJECTED_ORDER:
            self.assertIn(status, an.RUN_REJECTED)
        self.assertEqual(set(an.RUN_REJECTED), set(an.RUN_REJECTED_ORDER))

    def test_result_writes_via_create_only_evidence_convention(self):
        res = an.aggregate_cell([_record(run_id="run-1", repeat=1)])
        raw = an.result_json_bytes(res)
        with tempfile.TemporaryDirectory(prefix="p4analyze-test-") as tmp:
            lib.create_only_dir("cell/result", root=tmp)
            lib.create_only_file("cell/result/analysis.json", raw, root=tmp)
            with self.assertRaises(lib.PathContractError):
                lib.create_only_file("cell/result/analysis.json", raw, root=tmp)


if __name__ == "__main__":
    unittest.main()
