# -*- coding: utf-8 -*-
"""P4 analysis layer — honest statistics over collected run records.
session p4-001, batch B1 unit W1b.

Scope (docs/P4/P4-B1纯工具实现brief.md, W1b; docs/P4实施计划.json sampling.*):

  * strict real-data contract: a run record carries its trial spec (validated
    by tools/p4_lib.py), an explicit window (start_snapshot_index +
    sample_count == 10 + the actual warmup_end_monotonic_s anchor), and the
    raw snapshot list. B1-r2 F4: ten records are not ten seconds — in-window
    slots must sit at warmup_end + k*1.0s within the preregistered ±0.25s
    SAMPLING-SCHEDULE tolerance (fixed before any measurement, never a
    present-timing guarantee, never tuned on results), wall_monotonic_s must
    strictly increase, and the first-to-last span must stay inside 8.5..9.5s;
    missing in-window samples are NEVER interpolated or synthesised and late
    polls are exposed, not smoothed — the run is rejected and preserved.
  * per-run honest statistic: per-pass `avg_ns` values of the in-window
    snapshots, kept verbatim (identical numeric values are real rolling-
    window re-observations and MUST NOT be value-deduplicated); run summary
    = median of those snapshot observations. This is explicitly NOT a set of
    independent frame samples; vo-passes `count`/`samples_ns` (LF10 native
    mapping) is timing evidence, never an independent frame count and never
    added into N. F1: a real performance window requires a non-empty fresh
    table with real timing in every in-window snapshot (redraw may be empty
    but can never substitute fresh; unmeasured tables stay None, never 0).
  * fresh/redraw kept strictly separate; ns/1e6 = ms.
  * cross-run: independent unit = one complete run; median of per-run
    medians + run-level percentile bootstrap (n=10000, seed 424242,
    descriptive only). Insufficient n is flagged; no significance test and
    no causal faster/slower claim is ever produced. A CI never proves
    causality.
  * epoch change / ordered pass-table change inside a window: refuse to mix
    (run rejected with reason, data preserved). LF11: pass desc text is not
    a unique ID — ordinal+desc is the stable identity; same-named passes are
    kept as separate slots with their own data (never merged/deduped/
    reordered) and the complete ordered table must match across the window.
  * F5 context cross-checks (real value checks, not field existence): source
    identity (clip/media/generator) must match the spec, clip registry and
    library revision in every in-window snapshot; video_out_params w/h must
    equal the post-filter source size; dw/dh is the square-pixel source
    DISPLAY size (== source w/h), never the window or shader output rect
    (corrects the original review's dw/dh==rect confusion); osd_dimensions
    w/h is the window and must match the group's independent
    expected_window_size (never the legacy output_size); observed osd
    margins must yield the registry rect when present; source-domain frame
    identity must be inside the clip frame range with pts==index/fps, while
    RIFE M-class output frames live in a different index naming domain and
    are never forced onto source bounds.
  * counters: run-internal first/last delta only (p4_lib.counter_delta);
    negative delta (counter reset) -> run rejected; missing bounds ->
    explicit missing entry (never zero). vo-passes count/samples are never
    accepted as dropped-frame proxies.
  * present frame duration: NOT_MEASURED (TIME-01: no present source).
    IPC polling intervals and time-pos deltas are never frame durations.
  * pass sums are labelled descriptive shader-pass aggregates and are never
    end-to-end GPU latency; end-to-end latency itself is NOT_MEASURED.
  * RIFE off/on stratification: cells only comparable on identical
    group/clip/source fps/output rect/hq-common fingerprint/media binding;
    ON runs are mixed S/M frames with no per-frame GPU attribution; an
    overall_headroom_ms figure is never produced. F6: rife=on runs without a
    real observed_output_fps never join statistics; off runs must also
    record the observed fps (source*factor); the numeric match is necessary,
    never sufficient, and never a RIFE-execution PASS.
  * drop-affected runs participate; collector exclusions (E1-E6) are
    preserved verbatim with reason + original dir; analysis-rejected runs
    are preserved with reasons. Nothing disappears.
  * result schema is pure structured data (comparability / measurement_kind /
    run_ids / cell / status / limitations) so EVI semantic checks can verify
    claims structurally. `status` is bookkeeping vocabulary
    (MEASURED / PARTIAL_MEASURED / NOT_MEASURED) — it never grades quality,
    never certifies PASS, and renderer statistics never become a P4 PASS.

Pure stdlib (Python 3.9), no import side effects, no GPU/mpv/subprocess,
no network, default-run has no external effects. Production specs remain
locked by the p4_lib revision (see its PRODUCTION_LOCK) — analysis at this
revision therefore covers calibration/pilot/identity_probe run records only.
"""
from __future__ import annotations

import copy
import inspect
import math
import random
import statistics
import sys

try:
    import p4_lib as lib
except ImportError:  # direct-file import support
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import p4_lib as lib

# ---------------------------------------------------------------------------
# Preregistered constants (docs/P4实施计划.json sampling.seed_and_order /
# rolling_window_rules; p4_lib is the single source of truth)
# ---------------------------------------------------------------------------

STAGE = lib.STAGE
SESSION = lib.SESSION
PLAN_SHA256 = lib.PLAN_SHA256
ANALYSIS_REL = "tools/p4_analyze.py"

ANALYSIS_SCHEMA = "p4-analyze-result-v2"
BUNDLE_SCHEMA = "p4-analysis-bundle-v2"
RUN_ANALYSIS_SCHEMA = "p4-run-analysis-v2"
RUN_RECORD_SCHEMA = "p4-run-record-v2"
PAIRING_SCHEMA = "p4-rife-pairing-v2"

BOOTSTRAP_N = 10000
BOOTSTRAP_SEED = lib.BOOTSTRAP_SEED          # 424242, preregistered
WINDOW_TARGET_SAMPLES = lib.SAMPLING_BUDGET["window_target_samples"]  # 10
NS_PER_MS = 1e6                              # ns / 1e6 = ms (exact divisor)

NOT_MEASURED = "NOT_MEASURED"
STATUS_MEASURED = "MEASURED"
STATUS_PARTIAL = "PARTIAL_MEASURED"
STATUS_NOT_MEASURED = "NOT_MEASURED"
STATUS_VOCABULARY = (STATUS_MEASURED, STATUS_PARTIAL, STATUS_NOT_MEASURED)
PERFORMANCE_CONCLUSION = "DESCRIPTIVE_ONLY_NO_CAUSAL_CLAIM"

EXCLUSION_CODES = ("E1", "E2", "E3", "E4", "E5", "E6")  # preregistered reasons

RUN_STATUS_VALID = "VALID"
RUN_REJECTED = {
    "REJECTED_WINDOW_TRUNCATED":
        "window did not contain the preregistered %d in-window snapshots; "
        "missing samples are never interpolated (truncated window rejected)"
        % WINDOW_TARGET_SAMPLES,
    "REJECTED_WALL_NON_MONOTONIC":
        "wall_monotonic_s did not strictly increase across the in-window "
        "slots: ten records are not ten seconds; run rejected, preserved",
    "REJECTED_WINDOW_SCHEDULE":
        "in-window slot wall times deviated from the preregistered 1 Hz "
        "schedule (warmup_end + k*1.0s, ±0.25s sampling tolerance fixed "
        "before any measurement) or the window span fell outside 8.5..9.5s; "
        "late polls (e.g. nvidia-smi stalls) are exposed, never smoothed or "
        "interpolated; run rejected, preserved",
    "REJECTED_PASS_TABLE_EMPTY":
        "a real performance window requires a non-empty fresh pass table in "
        "every in-window snapshot; empty fresh / redraw-only tables never "
        "join MEASURED statistics (an empty redraw table alone is legal but "
        "can never substitute fresh); run rejected, preserved",
    "REJECTED_PASS_NO_TIMING":
        "an in-window pass entry carried no timing evidence (avg_ns==0, "
        "empty samples_ns, or native count==0); a legal pass without timing "
        "is unmeasurable and is never coerced to 0; run rejected, preserved",
    "REJECTED_TIME_POS_REGRESS":
        "time-pos did not strictly advance across the window (loop/EOF/"
        "boundary guard); time_pos is never used as a wall clock or frame "
        "duration; run rejected, preserved",
    "REJECTED_EPOCH_MIXED":
        "render-state epoch changed inside the window; snapshots must not be "
        "mixed across epochs; run rejected, preserved",
    "REJECTED_PASS_SET_CHANGED":
        "the complete ORDERED vo-passes desc table changed inside the window "
        "(LF11: ordinal+desc identity with duplicates significant); refusing "
        "to mix different pass tables; run rejected, preserved",
    "REJECTED_SOURCE_MISMATCH":
        "source identity observations are missing or inconsistent with the "
        "trial spec / clip registry / generator revision (clip, media hash, "
        "generator hash); a window without the required source observations "
        "cannot be valid; run rejected, preserved",
    "REJECTED_GEOMETRY_MISMATCH":
        "observed geometry contradicts the preregistered group geometry: "
        "video_out_params w/h must equal the post-filter source size, dw/dh "
        "is the square-pixel source display size (never the window or "
        "shader output rect), osd_dimensions w/h is the window and must "
        "match expected_window_size (never the legacy output_size), and "
        "observed osd margins must yield the registry rect; run rejected, "
        "preserved",
    "REJECTED_FRAME_IDENTITY":
        "source-domain frame identity is illegal (index outside the clip "
        "frame range, pts not matching index/fps) or an M-class RIFE output "
        "frame appears in an off stratum; M frames live in a different index "
        "naming domain and are never forced onto source bounds; run "
        "rejected, preserved",
    "REJECTED_FAKE_RIFE_METADATA":
        "observed filter output fps does not equal source_fps*factor for the "
        "run's stratum (on: 2x source, off: source); fake metadata rejected; "
        "run rejected, preserved",
    "REJECTED_FPS_UNBOUND":
        "observed_output_fps missing: rife=on runs without a real observed "
        "filter output fps never join statistics, and off runs must also "
        "record the observed fps; the numeric match is necessary, never "
        "sufficient, and never a RIFE-execution PASS; run rejected, "
        "preserved",
    "REJECTED_COUNTER_RESET":
        "counter went backwards inside the window (reset); run-internal "
        "delta invalid per preregistration; run rejected, preserved",
}

RUN_REJECTED_ORDER = (
    "REJECTED_WINDOW_TRUNCATED", "REJECTED_EPOCH_MIXED",
    "REJECTED_WALL_NON_MONOTONIC", "REJECTED_WINDOW_SCHEDULE",
    "REJECTED_PASS_TABLE_EMPTY", "REJECTED_PASS_NO_TIMING",
    "REJECTED_PASS_SET_CHANGED", "REJECTED_TIME_POS_REGRESS",
    "REJECTED_SOURCE_MISMATCH", "REJECTED_GEOMETRY_MISMATCH",
    "REJECTED_FRAME_IDENTITY", "REJECTED_FAKE_RIFE_METADATA",
    "REJECTED_FPS_UNBOUND", "REJECTED_COUNTER_RESET")

RUN_RECORD_REQUIRED = ("schema", "run_id", "spec", "window", "snapshots",
                       "config_binding")
RUN_RECORD_OPTIONAL = ("observed_output_fps", "drop_affected", "excluded",
                       "note")
WINDOW_KEYS = ("start_snapshot_index", "sample_count",
               "warmup_end_monotonic_s")

# F4 preregistered window-schedule contract (B1-r2). The ±0.25s value is a
# SAMPLING-SCHEDULE tolerance fixed in this revision BEFORE any measurement
# (a convergence interface, never tuned on performance results); it is never
# a present-timing guarantee and never a frame-duration source.
WINDOW_SLOT_PERIOD_S = 1.0
WINDOW_SLOT_TOLERANCE_S = 0.25
WINDOW_SPAN_MIN_S = ((WINDOW_TARGET_SAMPLES - 1) * WINDOW_SLOT_PERIOD_S
                     - 2 * WINDOW_SLOT_TOLERANCE_S)          # 8.5
WINDOW_SPAN_MAX_S = ((WINDOW_TARGET_SAMPLES - 1) * WINDOW_SLOT_PERIOD_S
                     + 2 * WINDOW_SLOT_TOLERANCE_S)          # 9.5

MEASUREMENT_KIND = {
    "unit_conversion": "ns/1e6 = ms (exact division by 1e6)",
    "run_statistic":
        "median of the %d in-window per-pass avg_ns snapshot observations; "
        "rolling-window re-observations are NOT independent frame samples"
        % WINDOW_TARGET_SAMPLES,
    "cell_statistic":
        "median across independent complete runs (independent unit = one "
        "full run) + run-level percentile bootstrap interval",
    "pass_sum":
        "descriptive sum of per-pass medians; NOT end-to-end GPU latency; "
        "never an additive frame-budget term; a None table sum means the "
        "table had no timed passes in the window (unmeasured, never coerced "
        "to 0 ms)",
    "samples_field":
        "LF10 native mapping: count is the native per-pass timing-sample "
        "count and samples_ns is the raw ns timing array; timing evidence "
        "only — never an independent frame count, never added into N; the "
        "old int samples field was a native-API misreading and is rejected",
    "value_dedup":
        "forbidden: identical numeric values (including inside samples_ns "
        "arrays) are real re-observations and are kept verbatim (no value "
        "deduplication)",
    "fresh_redraw": "fresh and redraw tables are kept strictly separate; "
                    "redraw may legally be empty but never substitutes "
                    "fresh (F1)",
    "pass_identity":
        "LF11: pass desc text is not a unique ID; ordinal+desc is the "
        "stable identity; same-named passes keep separate slots and data; "
        "the complete ordered table must match across the window; full "
        "recipe/DESC identity remains the later B3 contract",
    "window_schedule":
        "slots at warmup_end + k*1.0s with preregistered ±0.25s sampling "
        "tolerance fixed before measurement; sampling-schedule tolerance "
        "only, never a present guarantee, never tuned on results",
    "causality": "no significance test, no causal faster/slower claim; a "
                 "confidence interval is descriptive, never causal evidence",
}

WINDOW_CONTRACT = {
    "rule":
        "in-window = snapshot_index in [start_snapshot_index, "
        "start_snapshot_index + sample_count); the half-open wall window is "
        "[warmup_end, warmup_end + 10s) with slots k=0..9 at warmup_end + "
        "k*1.0s; ten records are not ten seconds",
    "target_samples": WINDOW_TARGET_SAMPLES,
    "warmup_anchor":
        "record.window.warmup_end_monotonic_s is REQUIRED and must align "
        "with slot 0's wall_monotonic_s within the tolerance",
    "slot_period_s": WINDOW_SLOT_PERIOD_S,
    "slot_tolerance_s": WINDOW_SLOT_TOLERANCE_S,
    "span_bounds_s": [WINDOW_SPAN_MIN_S, WINDOW_SPAN_MAX_S],
    "tolerance_preregistration":
        "±0.25s fixed in the B1-r2 revision BEFORE any measurement (a "
        "convergence interface); a sampling-schedule tolerance only — never "
        "a present-timing guarantee, never a frame-duration source, never "
        "tuned on performance results",
    "truncation": "missing in-window samples are never interpolated; a "
                  "late poll is exposed as a schedule violation, never "
                  "smoothed; the run is rejected and preserved",
    "wall_monotonic": "wall_monotonic_s must strictly increase across the "
                      "in-window slots; time_pos_s must strictly advance but "
                      "is never used as a wall clock and never infers frame "
                      "durations (TIME-01)",
}

LIMITATIONS = (
    "analysis validates and aggregates recorded data; it never fabricates "
    "sampling success and never invents measurements",
    "run statistic = median of 10 in-window avg_ns snapshot observations of "
    "a rolling window; these are not independent frame samples",
    "end-to-end GPU latency: NOT_MEASURED (no source); pass sums are shader "
    "pass aggregates only",
    "real present frame duration: NOT_MEASURED (TIME-01: PresentMon absent, "
    "ETW not authorized); IPC intervals and time-pos deltas are never frame "
    "durations; the ±0.25s slot tolerance is a sampling-schedule tolerance, "
    "never a present guarantee",
    "no causal faster/slower claims and no significance tests; bootstrap "
    "intervals are descriptive",
    "RIFE on runs are mixed S/M frames; vo-passes has no per-frame-class "
    "granularity, so no per-frame GPU attribution and no overall_headroom_ms "
    "is ever produced",
    "production specs are locked by the current p4_lib revision; this "
    "analysis covers calibration/pilot/identity_probe records only",
    "counter semantics: run-internal first/last delta only; saturation is "
    "reported, never blocking (LF-01)",
    "F5 source binding: media_sha256 is checked for schema, in-window "
    "consistency and cross-run equality inside a cell; the per-clip media "
    "manifest pin does not exist yet, so the media BYTES cannot be verified "
    "until the collector builds and pins them (not yet probeable)",
    "F5 rect verification runs only when osd margins ml/mr/mt/mb were "
    "observed in the same single command; without them the rect stays "
    "NOT_OBSERVED (disclosed, never copied from the spec); the real "
    "collector must fill actually observed margins",
    "LF11: full recipe/DESC identity (which named pass is which shader "
    "chain) is the later B3 contract; ordinal+desc is only a stable slot "
    "identity within one record",
    "M-class RIFE output frame indexing is accepted as a separate naming "
    "domain (bounds never forced onto source frames); its exact index "
    "contract is pinned by the later B3 recipe manifest, not probeable now",
)

_PRESENT_NOT_MEASURED = {
    "status": NOT_MEASURED,
    "reason":
        "TIME-01: no real present source (PresentMon absent; ETW requires "
        "elevation and is not authorized); real present frame duration is "
        "unmeasured; IPC polling intervals and time-pos deltas are NEVER "
        "frame durations",
}

_END_TO_END_NOT_MEASURED = {
    "status": NOT_MEASURED,
    "reason":
        "no end-to-end GPU latency source in P4; per-pass vo-passes sums are "
        "shader-pass aggregates and are never labelled total GPU latency",
}

_RIFE_ON_DISCLOSURE = {
    "frame_composition":
        "ON runs render mixed S (source) and M (model middle) output frames "
        "(2x fps); vo-passes has no per-frame-class granularity",
    "per_frame_gpu_attribution":
        "NONE — no per-S/M-frame GPU attribution is computed",
    "overall_headroom_ms":
        "NOT COMPUTED — forbidden: no end-to-end/present time source; "
        "20.83/16.67ms rhythm figures are reference budgets, not additive "
        "terms; PER-03 compares whole-run OFF/ON statistics only",
    "pairing_rule":
        "OFF/ON compared only as same-arm whole-run statistics; never as "
        "per-frame attribution and never as a headroom number",
}


# ---------------------------------------------------------------------------
# Small strict helpers
# ---------------------------------------------------------------------------

def ns_to_ms(ns):
    """ns -> ms with strict non-bool finite non-negative input."""
    return lib.require_nonneg_number(ns, "ns value") / NS_PER_MS


def present_frame_duration():
    """TIME-01 truth: real present frame duration has no source in P4."""
    return dict(_PRESENT_NOT_MEASURED)


def end_to_end_gpu_latency():
    """End-to-end GPU latency is NOT_MEASURED; pass sums are never it."""
    return dict(_END_TO_END_NOT_MEASURED)


def _percentile(sorted_vals, frac):
    if not sorted_vals:
        raise lib.ValueContractError("percentile of empty list")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = frac * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bootstrap_median_ci(values, n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_SEED):
    """Run-level percentile bootstrap of the median (descriptive).

    Rejects empty input and any bool/NaN/inf value. With fewer than 2 runs
    no interval is produced (point only) — insufficient repetition is never
    dressed up as significance.
    """
    if not isinstance(values, (list, tuple)) or not values:
        raise lib.ValueContractError(
            "bootstrap: values must be a non-empty list of run statistics")
    checked = [lib.require_finite_number(v, "bootstrap value") for v in values]
    n_boot = lib.require_int(n_boot, "n_boot", minimum=1)
    seed = lib.require_int(seed, "bootstrap seed", minimum=0)
    point = float(statistics.median(checked))
    kind = ("run-level percentile bootstrap of per-run medians (descriptive "
            "interval; NOT a significance test; never causal evidence)")
    if len(checked) < 2:
        return {"point": point, "ci95_pct": None, "n_boot": 0, "seed": seed,
                "kind": kind,
                "reason": "fewer than 2 independent runs: no interval "
                          "computed, descriptive point only"}
    rng = random.Random(seed)
    n = len(checked)
    boot = []
    for _ in range(n_boot):
        sample = [checked[rng.randrange(n)] for _ in range(n)]
        boot.append(statistics.median(sample))
    boot.sort()
    return {"point": point,
            "ci95_pct": [_percentile(boot, 0.025), _percentile(boot, 0.975)],
            "n_boot": n_boot, "seed": seed, "kind": kind}


# ---------------------------------------------------------------------------
# Run-record contract
# ---------------------------------------------------------------------------

def validate_run_record(record):
    """Strict validation of one run record; returns the validated spec.

    Structural/type crimes raise; data adequacy is handled by analyze_run
    (which returns structured rejections that are preserved, never mixed).
    """
    if not isinstance(record, dict):
        raise lib.ValueContractError("run record must be a dict")
    keys = set(record)
    missing = sorted(set(RUN_RECORD_REQUIRED) - keys)
    extra = sorted(keys - set(RUN_RECORD_REQUIRED) - set(RUN_RECORD_OPTIONAL))
    if missing or extra:
        raise lib.ValueContractError(
            "run record keys mismatch; missing=%s extra=%s" % (missing, extra))
    if record["schema"] != RUN_RECORD_SCHEMA:
        raise lib.ValueContractError(
            "run record schema must be %r, got %r"
            % (RUN_RECORD_SCHEMA, record["schema"]))
    run_id = record["run_id"]
    if not isinstance(run_id, str) or not run_id:
        raise lib.ValueContractError("run_id must be a non-empty str")
    spec = lib.validate_trial_spec(record["spec"])
    window = record["window"]
    if not isinstance(window, dict) or sorted(window) != sorted(WINDOW_KEYS):
        raise lib.ValueContractError(
            "window must have exactly %s (B1-r2: the actual "
            "warmup_end_monotonic_s anchor is required; a window without it "
            "cannot be schedule-checked)" % (list(WINDOW_KEYS),))
    start = lib.require_int(window["start_snapshot_index"],
                            "window.start_snapshot_index", minimum=0)
    count = lib.require_int(window["sample_count"], "window.sample_count",
                            minimum=1)
    if count != WINDOW_TARGET_SAMPLES:
        raise lib.ValueContractError(
            "window.sample_count must be the preregistered %d, got %d"
            % (WINDOW_TARGET_SAMPLES, count))
    lib.require_finite_number(window["warmup_end_monotonic_s"],
                              "window.warmup_end_monotonic_s")
    snapshots = record["snapshots"]
    if not isinstance(snapshots, list) or not snapshots:
        raise lib.ValueContractError(
            "snapshots must be a non-empty list (missing raw snapshots are "
            "fail-closed, never interpolated)")
    prev_index = None
    for pos, snap in enumerate(snapshots):
        info = lib.validate_snapshot(snap)
        if prev_index is not None and info["snapshot_index"] <= prev_index:
            raise lib.ValueContractError(
                "snapshots[%d]: snapshot_index %d not strictly increasing"
                % (pos, info["snapshot_index"]))
        prev_index = info["snapshot_index"]
    binding = record["config_binding"]
    if not isinstance(binding, dict) or sorted(binding) != ["hq_common_sha256"]:
        raise lib.ValueContractError(
            "config_binding must have exactly hq_common_sha256")
    lib.require_sha256_hex(binding["hq_common_sha256"],
                           "config_binding.hq_common_sha256")
    if "observed_output_fps" in record:
        fps = lib.require_finite_number(record["observed_output_fps"],
                                        "observed_output_fps")
        if fps <= 0:
            raise lib.ValueContractError(
                "observed_output_fps must be > 0, got %r" % (fps,))
    if "drop_affected" in record:
        lib.require_bool(record["drop_affected"], "drop_affected")
    if "excluded" in record:
        excluded = record["excluded"]
        if not isinstance(excluded, dict) or sorted(excluded) != \
                ["code", "original_dir", "reason"]:
            raise lib.ValueContractError(
                "excluded must have exactly code/reason/original_dir")
        if excluded["code"] not in EXCLUSION_CODES:
            raise lib.ValueContractError(
                "excluded.code must be one of %s, got %r"
                % (EXCLUSION_CODES, excluded["code"]))
        for field in ("reason", "original_dir"):
            if not isinstance(excluded[field], str) or not excluded[field]:
                raise lib.ValueContractError(
                    "excluded.%s must be a non-empty str" % field)
    if "note" in record and not isinstance(record["note"], str):
        raise lib.ValueContractError("note must be a str")
    return spec


# ---------------------------------------------------------------------------
# Per-run analysis
# ---------------------------------------------------------------------------

def _window_snapshots(record, start, count):
    by_index = {}
    for snap in record["snapshots"]:
        by_index[snap["snapshot_index"]] = snap
    in_window = []
    for idx in range(start, start + count):
        if idx in by_index:
            in_window.append(by_index[idx])
    warmup = sum(1 for idx in by_index if idx < start)
    post = sum(1 for idx in by_index if idx >= start + count)
    return in_window, warmup, post


def _pass_values(in_window, frame_name):
    """Ordered slot identity -> [avg_ns values in snapshot order] (LF11).

    Pass desc text is NOT a unique ID: ordinal+desc is the stable identity,
    duplicate descs are legal and keep separate data (never merged, deduped
    or reordered). The complete ORDERED desc table (duplicates significant)
    must be identical in every in-window snapshot; any difference returns
    (None, ref_table, current_table) so the caller rejects with
    REJECTED_PASS_SET_CHANGED.
    """
    values = {}
    ref_table = None
    for snap in in_window:
        table = snap["vo_passes"][frame_name]
        descs = [entry["desc"] for entry in table]
        current = tuple(descs)
        if ref_table is None:
            ref_table = current
            values = {"%d|%s" % (pos, desc): []
                      for pos, desc in enumerate(descs)}
        elif current != ref_table:
            return None, list(ref_table), list(current)
        for pos, entry in enumerate(table):
            values["%d|%s" % (pos, entry["desc"])].append(
                lib.require_nonneg_number(entry["avg_ns"],
                                          "vo_passes.%s.avg_ns" % frame_name))
    return values, None, None


def _run_pass_stats(values_by_identity):
    """Per-slot stats keyed by the LF11 'ordinal|desc' identity; the original
    desc and ordinal travel inside each entry so nothing is lost by the key
    encoding."""
    out = {}
    for identity, vals in values_by_identity.items():
        slot, desc = identity.split("|", 1)
        median_ns = float(statistics.median(vals))
        out[identity] = {
            "identity": identity,
            "slot": int(slot),
            "desc": desc,
            "avg_ns_values": list(vals),          # verbatim, never deduped
            "n_observations": len(vals),
            "avg_ns_median": median_ns,
            "avg_ms_median": ns_to_ms(median_ns),
        }
    return out


def _counter_section(in_window):
    """Run-internal first/last deltas from the in-window counters family.
    Missing bounds are explicit missing entries; negative delta (reset) is
    flagged (never normalised to zero); vo-passes data inside the counters
    family is a unit misuse and rejected."""
    observed = set()
    for snap in in_window:
        observed |= set(snap.get("counters", {}))
    for name in observed:
        if name.startswith("vo_passes"):
            raise lib.ValueContractError(
                "counter %r: vo-passes count/samples must never enter the "
                "counters family or act as dropped-frame proxies" % name)
    first_snap, last_snap = in_window[0], in_window[-1]
    section = {}
    reset = False
    for name in sorted(observed):
        first = first_snap.get("counters", {}).get(name)
        last = last_snap.get("counters", {}).get(name)
        if first is None or last is None:
            section[name] = {"status": "missing", "delta": None,
                             "reason": "counter absent at window %s; missing "
                                       "items are explicit, never zero"
                                       % ("start" if first is None else "end")}
            continue
        try:
            info = lib.counter_delta(first, last, name=name)
            section[name] = {"status": "ok", "delta": info["delta"],
                             "no_growth": info["no_growth"],
                             "blocking": info["blocking"],
                             "note": info["note"]}
        except lib.ValueContractError as exc:
            reset = True
            section[name] = {"status": "counter_reset_invalid",
                             "delta": None, "detail": str(exc)}
    return section, reset


def _window_wall_checks(in_window, anchor):
    """F4: strict wall monotonicity + preregistered 1 Hz schedule check.

    Slots k=0..9 must sit at warmup_end + k*1.0s within ±0.25s (sampling
    tolerance fixed before measurement); slot 0's deviation IS the anchor
    alignment check; the first-to-last span must stay inside 8.5..9.5s.
    Returns None on success or (status, detail)."""
    walls = [snap["wall_monotonic_s"] for snap in in_window]
    if any(b <= a for a, b in zip(walls, walls[1:])):
        return ("REJECTED_WALL_NON_MONOTONIC",
                "in-window wall_monotonic_s observed %r" % (walls,))
    deviations = [walls[k] - (anchor + k * WINDOW_SLOT_PERIOD_S)
                  for k in range(len(walls))]
    worst_slot = max(range(len(deviations)), key=lambda k: abs(deviations[k]))
    if abs(deviations[worst_slot]) > WINDOW_SLOT_TOLERANCE_S:
        return ("REJECTED_WINDOW_SCHEDULE",
                "slot %d wall deviated %+.3fs from warmup_end + %d*1.0s "
                "(preregistered tolerance ±%.2fs; late polls are exposed, "
                "never interpolated); slot deviations: %r"
                % (worst_slot, deviations[worst_slot], worst_slot,
                   WINDOW_SLOT_TOLERANCE_S,
                   [round(d, 6) for d in deviations]))
    span = walls[-1] - walls[0]
    if span < WINDOW_SPAN_MIN_S or span > WINDOW_SPAN_MAX_S:
        return ("REJECTED_WINDOW_SCHEDULE",
                "first-to-last span %.3fs outside the preregistered "
                "[%.1f, %.1f]s band" % (span, WINDOW_SPAN_MIN_S,
                                        WINDOW_SPAN_MAX_S))
    return None


def _pass_timing_checks(in_window):
    """F1: a real performance window needs a non-empty fresh table with real
    timing evidence in every in-window snapshot; redraw may be empty but any
    redraw entry present must carry real timing too. Returns None or
    (status, detail)."""
    for snap in in_window:
        tables = snap["vo_passes"]
        if not tables["fresh"]:
            return ("REJECTED_PASS_TABLE_EMPTY",
                    "fresh table empty at snapshot %d (redraw=%d entries); "
                    "an empty fresh table is never a 0 ms window and redraw "
                    "can never substitute fresh"
                    % (snap["snapshot_index"], len(tables["redraw"])))
        for frame_name in ("fresh", "redraw"):
            for pos, entry in enumerate(tables[frame_name]):
                samples_ns = entry["samples_ns"]
                count = entry["count"]
                if (entry["avg_ns"] <= 0 or not samples_ns
                        or (count is not None and count == 0)):
                    return ("REJECTED_PASS_NO_TIMING",
                            "vo_passes.%s[%d] (%r) at snapshot %d carries no "
                            "timing evidence (avg_ns=%r, len(samples_ns)=%d, "
                            "count=%r); unmeasured is never coerced to 0"
                            % (frame_name, pos, entry["desc"],
                               snap["snapshot_index"], entry["avg_ns"],
                               len(samples_ns), count))
    return None


def _source_checks(in_window, spec):
    """F5: required source identity observations in every in-window snapshot,
    cross-checked against spec/clip registry/generator revision; media hash
    must stay consistent in-window. Returns None or (status, detail); on
    success returns the verified binding for the context block."""
    generator = lib.library_sha256()
    media_hashes = {}
    for snap in in_window:
        src = snap.get("source")
        if (not isinstance(src, dict) or not src.get("clip")
                or not src.get("media_sha256")
                or not src.get("generator_sha256")):
            return ("REJECTED_SOURCE_MISMATCH",
                    "snapshot %d lacks the required source identity "
                    "observations (clip + media_sha256 + generator_sha256); "
                    "field existence is not enough, missing required "
                    "observations cannot be valid" % snap["snapshot_index"])
        if src["clip"] != spec["clip"]:
            return ("REJECTED_SOURCE_MISMATCH",
                    "snapshot %d source.clip %r != spec.clip %r"
                    % (snap["snapshot_index"], src["clip"], spec["clip"]))
        if src["generator_sha256"] != generator:
            return ("REJECTED_SOURCE_MISMATCH",
                    "snapshot %d source.generator_sha256 does not match this "
                    "library revision %s" % (snap["snapshot_index"], generator))
        media_hashes.setdefault(src["media_sha256"], snap["snapshot_index"])
        if len(media_hashes) > 1:
            return ("REJECTED_SOURCE_MISMATCH",
                    "source.media_sha256 changed in-window (observed %s "
                    "values; first divergence by snapshot %d)"
                    % (sorted(media_hashes), snap["snapshot_index"]))
    media_sha256 = next(iter(media_hashes))
    return None, {"clip": spec["clip"], "media_sha256": media_sha256,
                  "generator_sha256": generator,
                  "generator_matches_library_revision": True,
                  "note": ("media manifest byte pin is not probeable yet; "
                           "cross-run equality is enforced per cell")}


def _geometry_checks(in_window, spec):
    """F5 real-value geometry cross-checks (corrected coordinate semantics):
    video_out_params w/h == post-filter source size; dw/dh == square-pixel
    source display size (== source w/h, NEVER the window/rect); osd w/h ==
    expected_window_size (never the legacy output_size); observed osd
    margins must yield the registry rect. Returns None or (status, detail);
    on success returns the geometry context block."""
    geo = lib.expected_geometry(spec["group"])
    for snap in in_window:
        vop = snap["video_out_params"]
        osd = snap["osd_dimensions"]
        if [vop["w"], vop["h"]] != geo["source_w_h"]:
            return ("REJECTED_GEOMETRY_MISMATCH",
                    "snapshot %d video_out_params w/h %dx%d != post-filter "
                    "source size %r (RIFE chain restores source resolution)"
                    % (snap["snapshot_index"], vop["w"], vop["h"],
                       geo["source_w_h"]))
        if [vop["dw"], vop["dh"]] != geo["display_dw_dh"]:
            return ("REJECTED_GEOMETRY_MISMATCH",
                    "snapshot %d video_out_params dw/dh %dx%d != source "
                    "display size %r; dw/dh is the square-pixel source "
                    "display size/SAR, NOT the window and NOT the shader "
                    "output rect"
                    % (snap["snapshot_index"], vop["dw"], vop["dh"],
                       geo["display_dw_dh"]))
        if [osd["w"], osd["h"]] != geo["window_w_h"]:
            return ("REJECTED_GEOMETRY_MISMATCH",
                    "snapshot %d osd_dimensions w/h %dx%d != expected "
                    "window %r (expected_window_size, never the legacy "
                    "output_size %r)"
                    % (snap["snapshot_index"], osd["w"], osd["h"],
                       geo["window_w_h"],
                       lib.get_group(spec["group"])["output_size"]))
        margin_keys = ("ml", "mr", "mt", "mb")
        if all(k in osd for k in margin_keys):
            if [osd["ml"], osd["mt"], osd["mr"], osd["mb"]] != \
                    geo["margins_ml_mt_mr_mb"]:
                return ("REJECTED_GEOMETRY_MISMATCH",
                        "snapshot %d observed margins [ml,mt,mr,mb]=%r != "
                        "preregistered %r"
                        % (snap["snapshot_index"],
                           [osd["ml"], osd["mt"], osd["mr"], osd["mb"]],
                           geo["margins_ml_mt_mr_mb"]))
            rect = [osd["w"] - osd["ml"] - osd["mr"],
                    osd["h"] - osd["mt"] - osd["mb"]]
            if rect != geo["rect_w_h"]:
                return ("REJECTED_GEOMETRY_MISMATCH",
                        "snapshot %d margins yield rect %r != registry "
                        "expected_rect %r"
                        % (snap["snapshot_index"], rect, geo["rect_w_h"]))
            rect_status = "VERIFIED_MATCHES_REGISTRY"
            observed_rect = rect
        else:
            rect_status = "NOT_OBSERVED_NO_MARGINS"
            observed_rect = None
    return None, {
        "expected": geo,
        "video_source_w_h": [vop["w"], vop["h"]],
        "display_dw_dh": [vop["dw"], vop["dh"]],
        "observed_window_w_h": [osd["w"], osd["h"]],
        "observed_margins_ml_mt_mr_mb":
            [osd["ml"], osd["mt"], osd["mr"], osd["mb"]]
            if all(k in osd for k in margin_keys) else None,
        "observed_rect_w_h": observed_rect,
        "rect_status": rect_status,
        "note": ("dw/dh boundary corrected in B1-r2: source display size, "
                 "not window/rect; margins must be actually observed, never "
                 "copied from the spec")}


def _frame_checks(in_window, spec):
    """F5 frame-identity checks. Source-domain frames (frame_class 'S' or
    unmarked, which per the schema is source identity) must lie inside the
    clip frame range with pts==index/fps; M-class RIFE output frames are a
    different index naming domain (never forced onto source bounds) and can
    only appear on rife=on runs. Returns None or (status, detail)."""
    clip_spec = lib.get_clip(spec["clip"])
    checked = 0
    for snap in in_window:
        fr = snap.get("frame")
        if fr is None:
            continue
        checked += 1
        frame_class = fr.get("frame_class")
        if frame_class == "M":
            if spec["rife"] != "on":
                return ("REJECTED_FRAME_IDENTITY",
                        "snapshot %d declares an M-class RIFE output frame "
                        "but this run's stratum is rife=off"
                        % snap["snapshot_index"])
            continue  # different index naming domain; B3 pins the exact contract
        if fr["index"] >= clip_spec["frames"]:
            return ("REJECTED_FRAME_IDENTITY",
                    "snapshot %d source-domain frame.index %d outside clip "
                    "%s range (%d frames); RIFE output indices are a "
                    "different domain and need frame_class='M'"
                    % (snap["snapshot_index"], fr["index"], spec["clip"],
                       clip_spec["frames"]))
        if fr["pts_num"] != fr["index"] or fr["pts_den"] != clip_spec["fps"]:
            return ("REJECTED_FRAME_IDENTITY",
                    "snapshot %d frame pts %d/%d does not match the source "
                    "identity contract index/fps = %d/%d"
                    % (snap["snapshot_index"], fr["pts_num"], fr["pts_den"],
                       fr["index"], clip_spec["fps"]))
    return None, {"source_domain_frames_checked": checked,
                  "note": ("frame observations are optional; when present "
                           "they are really checked, and M-class output "
                           "frames stay in their own index domain (B3 pins "
                           "the exact contract)")}


def _fps_binding_checks(record, spec):
    """F6: the observed filter output fps is required for BOTH strata (on:
    2x source, off: source) as a finite non-bool number; mismatch rejects as
    fake metadata; absence rejects as unbound. Necessary, never sufficient."""
    observed = record.get("observed_output_fps")
    expected = spec["rife_output_fps"]
    if observed is None:
        return ("REJECTED_FPS_UNBOUND",
                "observed_output_fps missing (rife=%s expects %r); a run "
                "without the real observed filter output fps never joins "
                "statistics" % (spec["rife"], expected))
    if observed != expected:
        return ("REJECTED_FAKE_RIFE_METADATA",
                "spec rife_output_fps=%r, observed_output_fps=%r"
                % (expected, observed))
    return None


def analyze_run(record):
    """Analyse one run record. Returns a run-analysis dict.

    Structural/type violations raise p4_lib contract errors. Data-adequacy
    failures return a structured REJECTED_* result with medians=None —
    preserved, never silently mixed into statistics. Checks run in the
    documented deterministic order (truncation, epoch, wall monotonic,
    schedule/anchor/span, table emptiness, pass timing, ordered pass table,
    time_pos, source, geometry, frame identity, fps binding, counters).
    """
    spec = validate_run_record(record)
    start = record["window"]["start_snapshot_index"]
    count = record["window"]["sample_count"]
    anchor = record["window"]["warmup_end_monotonic_s"]
    base = {
        "schema": RUN_ANALYSIS_SCHEMA,
        "run_id": record["run_id"],
        "cell": spec["cell"],
        "group": spec["group"],
        "arm": spec["arm"],
        "rife": spec["rife"],
        "drop_affected": record.get("drop_affected", False),
        "config_binding": dict(record["config_binding"]),
        "spec": spec,
    }

    def _rejected(status, extra=None):
        out = dict(base)
        out["status"] = status
        out["reason"] = RUN_REJECTED[status]
        out["medians"] = None
        if extra:
            out.update(extra)
        return out

    in_window, warmup, post = _window_snapshots(record, start, count)
    window_info = {"start_snapshot_index": start, "sample_count": count,
                   "warmup_end_monotonic_s": anchor,
                   "observed_in_window": len(in_window),
                   "warmup_polls_before_window": warmup,
                   "post_window_polls": post}
    if len(in_window) != count:
        return _rejected("REJECTED_WINDOW_TRUNCATED",
                         {"window": window_info,
                          "detail": "expected %d in-window snapshots, found %d"
                                    % (count, len(in_window))})

    if len({snap["epoch"] for snap in in_window}) != 1:
        return _rejected("REJECTED_EPOCH_MIXED", {"window": window_info})

    verdict = _window_wall_checks(in_window, anchor)
    if verdict is not None:
        return _rejected(verdict[0], {"window": window_info,
                                      "detail": verdict[1]})

    verdict = _pass_timing_checks(in_window)
    if verdict is not None:
        return _rejected(verdict[0], {"window": window_info,
                                      "detail": verdict[1]})

    fresh_vals, a, b = _pass_values(in_window, "fresh")
    if fresh_vals is None:
        return _rejected("REJECTED_PASS_SET_CHANGED",
                         {"window": window_info,
                          "detail": "fresh ordered desc table changed: "
                                    "%s -> %s" % (a, b)})
    redraw_vals, a, b = _pass_values(in_window, "redraw")
    if redraw_vals is None:
        return _rejected("REJECTED_PASS_SET_CHANGED",
                         {"window": window_info,
                          "detail": "redraw ordered desc table changed: "
                                    "%s -> %s" % (a, b)})

    time_positions = [snap["time_pos_s"] for snap in in_window]
    if any(y <= x for x, y in zip(time_positions, time_positions[1:])):
        return _rejected("REJECTED_TIME_POS_REGRESS",
                         {"window": window_info,
                          "detail": "time_pos_s must strictly advance; "
                                    "observed %r" % (time_positions,)})

    verdict, source_binding = _source_checks(in_window, spec)
    if verdict is not None:
        return _rejected(verdict, {"window": window_info,
                                   "detail": source_binding})

    verdict, geometry = _geometry_checks(in_window, spec)
    if verdict is not None:
        return _rejected(verdict, {"window": window_info,
                                   "detail": geometry})

    verdict, frames = _frame_checks(in_window, spec)
    if verdict is not None:
        return _rejected(verdict, {"window": window_info,
                                   "detail": frames})

    verdict = _fps_binding_checks(record, spec)
    if verdict is not None:
        return _rejected(verdict[0], {"window": window_info,
                                      "detail": verdict[1]})

    counters, reset = _counter_section(in_window)
    if reset:
        return _rejected("REJECTED_COUNTER_RESET",
                         {"window": window_info, "counters": counters})

    fresh_stats = _run_pass_stats(fresh_vals)
    redraw_stats = _run_pass_stats(redraw_vals)
    walls = [snap["wall_monotonic_s"] for snap in in_window]
    pass_sum = {
        "fresh_ms": (float(sum(s["avg_ms_median"]
                               for s in fresh_stats.values()))
                     if fresh_stats else None),
        "redraw_ms": (float(sum(s["avg_ms_median"]
                                for s in redraw_stats.values()))
                      if redraw_stats else None),
        "unmeasured_tables": [name for name, stats in
                              (("fresh", fresh_stats),
                               ("redraw", redraw_stats)) if not stats],
        "measurement_kind": MEASUREMENT_KIND["pass_sum"],
    }
    out = dict(base)
    out["status"] = RUN_STATUS_VALID
    out["window"] = dict(window_info, span_s=walls[-1] - walls[0],
                         slot_deviations_s=[
                             round(w - (anchor + k * WINDOW_SLOT_PERIOD_S), 9)
                             for k, w in enumerate(walls)],
                         slot_tolerance_s=WINDOW_SLOT_TOLERANCE_S)
    out["passes"] = {"fresh": fresh_stats, "redraw": redraw_stats}
    out["pass_order"] = {
        "fresh": [e["desc"] for e in in_window[0]["vo_passes"]["fresh"]],
        "redraw": [e["desc"] for e in in_window[0]["vo_passes"]["redraw"]],
    }
    out["pass_sum"] = pass_sum
    out["context"] = {"source": source_binding, "geometry": geometry,
                      "frames": frames}
    out["end_to_end_gpu_latency"] = end_to_end_gpu_latency()
    out["present_frame_duration"] = present_frame_duration()
    out["counters"] = counters
    if spec["rife"] == "on":
        out["rife_execution_proof"] = (
            "OBSERVED_FPS_MATCHES_2X_SOURCE (necessary, never sufficient; "
            "full RIFE-01 four-piece bundle is the collector's duty)")
        out["on_frame_composition"] = _RIFE_ON_DISCLOSURE["frame_composition"]
    else:
        out["rife_execution_proof"] = (
            "OBSERVED_FPS_MATCHES_SOURCE (off stratum; fps match is "
            "necessary, never sufficient for any performance claim)")
    return out


# ---------------------------------------------------------------------------
# Cell aggregation (cross-run statistics)
# ---------------------------------------------------------------------------

def _comparability(spec, hq_common):
    group = lib.get_group(spec["group"])
    return {
        "group": spec["group"],
        "arm": spec["arm"],
        "clip": spec["clip"],
        "source_fps": spec["source_fps"],
        "rife": spec["rife"],
        "rife_output_fps": spec["rife_output_fps"],
        "expected_rect": list(group["expected_rect"]),
        "output_size": list(group["output_size"]),
        "hq_common_sha256": hq_common,
        "rule": "comparable only within identical group/clip/source fps/"
                "RIFE stratum/output rect/hq-common fingerprint; Integer "
                "k=1 is never ranked with a full-rect G1 group",
    }


def aggregate_cell(records):
    """Aggregate run records of ONE preregistered cell into the structured
    cell result. Refuses mixed cells / RIFE strata / HQ fingerprints, keeps
    drop-affected runs participating, preserves excluded + rejected runs
    with their reasons, and flags insufficient n honestly."""
    if not isinstance(records, (list, tuple)) or not records:
        raise lib.ValueContractError("aggregate_cell: no run records")
    cell_key = None
    hq_common = None
    excluded_runs = []
    analyses = []
    seen_ids = set()
    for record in records:
        spec = validate_run_record(record)
        if cell_key is None:
            cell_key = spec["cell"]
            hq_common = record["config_binding"]["hq_common_sha256"]
        else:
            if spec["cell"] != cell_key:
                raise lib.TrialSpecError(
                    "aggregate_cell: mixed cells %r vs %r — refusing to mix"
                    % (cell_key, spec["cell"]))
            if record["config_binding"]["hq_common_sha256"] != hq_common:
                raise lib.TrialSpecError(
                    "aggregate_cell: hq_common fingerprint differs between "
                    "runs of cell %r — common non-algorithm HQ config must "
                    "match for comparability" % cell_key)
        run_id = record["run_id"]
        if run_id in seen_ids:
            raise lib.ValueContractError(
                "duplicate run_id %r — run IDs must be unique" % run_id)
        seen_ids.add(run_id)
        if "excluded" in record:
            entry = {"run_id": run_id}
            entry.update(copy.deepcopy(record["excluded"]))
            excluded_runs.append(entry)
            continue
        analyses.append(analyze_run(record))

    cell = lib.get_cell(cell_key)  # must be preregistered
    n_target = cell["n"]
    valid = [a for a in analyses if a["status"] == RUN_STATUS_VALID]
    rejected = [a for a in analyses if a["status"] != RUN_STATUS_VALID]
    valid.sort(key=lambda a: a["run_id"])

    # LF11: the complete ORDERED pass table (duplicates significant) must be
    # identical across the valid runs of the cell.
    order_sets = {(tuple(a["pass_order"]["fresh"]),
                   tuple(a["pass_order"]["redraw"])) for a in valid}
    if len(order_sets) > 1:
        raise lib.TrialSpecError(
            "aggregate_cell: ordered pass tables differ across valid runs of "
            "cell %r — refusing to mix different pass tables (LF11: "
            "ordinal+desc identity, duplicates significant)" % cell_key)

    # F5: every valid run of a cell must bind the same media and generator
    # identity (a cell mixes one clip only).
    media_hashes = {a["context"]["source"]["media_sha256"] for a in valid}
    generator_hashes = {a["context"]["source"]["generator_sha256"]
                        for a in valid}
    if len(media_hashes) > 1:
        raise lib.TrialSpecError(
            "aggregate_cell: runs of cell %r bind different source "
            "media_sha256 values %s — refusing to mix different media"
            % (cell_key, sorted(media_hashes)))
    if len(generator_hashes) > 1:
        raise lib.TrialSpecError(
            "aggregate_cell: runs of cell %r name different generator "
            "revisions %s" % (cell_key, sorted(generator_hashes)))

    run_ids = [a["run_id"] for a in valid]
    drop_affected_ids = [a["run_id"] for a in valid if a["drop_affected"]]

    passes = {"fresh": {}, "redraw": {}}
    fresh_sum_ms = []
    redraw_sum_ms = []
    for frame_name in ("fresh", "redraw"):
        slot_names = sorted(valid[0]["passes"][frame_name]) if valid else []
        for identity in slot_names:
            proto = valid[0]["passes"][frame_name][identity]
            per_run = {}
            for a in valid:
                per_run[a["run_id"]] = a["passes"][frame_name][identity][
                    "avg_ms_median"]
            values = [lib.require_finite_number(v, "run median ms")
                      for v in per_run.values()]
            passes[frame_name][identity] = {
                "identity": identity,
                "slot": proto["slot"],
                "desc": proto["desc"],
                "unit": "ms (ns/1e6)",
                "per_run_avg_ms_medians": per_run,
                "median_of_run_medians_ms":
                    float(statistics.median(values)) if values else None,
                "bootstrap": bootstrap_median_ci(values) if values else None,
            }
        sums = [a["pass_sum"][frame_name + "_ms"] for a in valid
                if a["pass_sum"][frame_name + "_ms"] is not None]
        if frame_name == "fresh":
            fresh_sum_ms = sums
        else:
            redraw_sum_ms = sums

    if n_target == 0:  # cannot happen for preregistered cells; fail closed
        raise lib.TrialSpecError("cell %r declares n=0" % cell_key)
    n_valid = len(valid)
    if n_valid >= n_target:
        status = STATUS_MEASURED
    elif n_valid == 0:
        status = STATUS_NOT_MEASURED
    else:
        status = STATUS_PARTIAL
    insufficient = {
        "insufficient": n_valid < n_target,
        "n_valid": n_valid,
        "n_target": n_target,
    }
    if n_valid < n_target:
        insufficient["reason"] = (
            "valid runs %d < preregistered target n=%d; cell is flagged "
            "insufficient; no significance is assessed and no absolute "
            "ranking is supported" % (n_valid, n_target))

    spec0 = valid[0]["spec"] if valid else lib.validate_trial_spec(
        records[0]["spec"])
    comparability = _comparability(spec0, hq_common)
    comparability["media_sha256"] = (
        next(iter(media_hashes)) if len(media_hashes) == 1 else None)
    comparability["comparable_rule_note"] = (
        "cells with a None media_sha256 have no valid runs and carry no "
        "measurement; media binding equality is enforced per cell (F5)")

    if spec0["rife"] == "on":
        significance = ("NOT_ASSESSED (descriptive bootstrap only; ON runs "
                        "are mixed S/M frames; no per-frame attribution)")
    elif n_valid < n_target:
        significance = ("NOT_ASSESSED (n_valid %d < target %d; preregistration "
                        "forbids significance claims at insufficient n)"
                        % (n_valid, n_target))
    else:
        significance = ("DESCRIPTIVE_CI_ONLY (percentile bootstrap interval; "
                        "no significance test performed; no causal "
                        "faster/slower claim)")

    result = {
        "schema": ANALYSIS_SCHEMA,
        "stage": STAGE,
        "session": SESSION,
        "plan_sha256": PLAN_SHA256,
        "analysis_generated_by": "%s (W1b)" % ANALYSIS_REL,
        "cell": cell_key,
        "comparability": comparability,
        "measurement_kind": dict(MEASUREMENT_KIND),
        "window_contract": dict(WINDOW_CONTRACT),
        "run_ids": run_ids,
        "drop_affected_run_ids": drop_affected_ids,
        "excluded_runs": excluded_runs,
        "rejected_by_analysis": [
            {"run_id": a["run_id"], "status": a["status"],
             "reason": a["reason"], "detail": a.get("detail"),
             "window": a.get("window")}
            for a in rejected],
        "n_target": n_target,
        "n_valid": n_valid,
        "n_excluded": len(excluded_runs),
        "n_rejected": len(rejected),
        "status": status,
        "insufficient": insufficient,
        "significance": significance,
        "passes": passes,
        "pass_order": (dict(valid[0]["pass_order"]) if valid
                       else {"fresh": [], "redraw": []}),
        "pass_sum": {
            "fresh_ms_median_across_runs":
                float(statistics.median(fresh_sum_ms)) if fresh_sum_ms else None,
            "redraw_ms_median_across_runs":
                float(statistics.median(redraw_sum_ms)) if redraw_sum_ms else None,
            "unmeasured_pass_sums": {
                "fresh": not fresh_sum_ms, "redraw": not redraw_sum_ms},
            "measurement_kind": MEASUREMENT_KIND["pass_sum"],
        },
        "end_to_end_gpu_latency": end_to_end_gpu_latency(),
        "present_frame_duration": present_frame_duration(),
        "counters": {
            "scope": "run-internal first/last delta only; saturation never "
                     "blocks (LF-01)",
            "per_run": {a["run_id"]: a["counters"] for a in valid},
        },
        "performance_conclusion": PERFORMANCE_CONCLUSION,
        "status_semantics":
            "analyze status is structural bookkeeping "
            "(MEASURED/PARTIAL_MEASURED/NOT_MEASURED); it never grades "
            "quality, never certifies PASS, and renderer statistics never "
            "make a P4 PASS; PIC scoring and default-profile choices are "
            "user-only",
        "limitations": list(LIMITATIONS),
    }
    if spec0["rife"] == "on":
        result["rife_on_disclosure"] = dict(_RIFE_ON_DISCLOSURE)
    return result


def analyze_records(records):
    """Analyse a set of run records from one or more cells.

    Enforces globally unique run IDs, groups records by cell, and returns a
    bundle of per-cell results. Every record is preserved somewhere in its
    cell result (run_ids / excluded_runs / rejected_by_analysis).
    """
    if not isinstance(records, (list, tuple)) or not records:
        raise lib.ValueContractError("analyze_records: no run records")
    seen = {}
    groups = {}
    for record in records:
        spec = validate_run_record(record)
        run_id = record["run_id"]
        if run_id in seen:
            raise lib.ValueContractError(
                "duplicate run_id %r (%s vs %s) — run IDs must be globally "
                "unique" % (run_id, seen[run_id], spec["cell"]))
        seen[run_id] = spec["cell"]
        groups.setdefault(spec["cell"], []).append(record)
    return {
        "schema": BUNDLE_SCHEMA,
        "stage": STAGE,
        "session": SESSION,
        "plan_sha256": PLAN_SHA256,
        "analysis_generated_by": "%s (W1b)" % ANALYSIS_REL,
        "run_index": dict(seen),
        "cells": {cell: aggregate_cell(recs)
                  for cell, recs in groups.items()},
        "limitations": list(LIMITATIONS),
    }


# ---------------------------------------------------------------------------
# Cross-cell comparability + RIFE OFF/ON pairing
# ---------------------------------------------------------------------------

def assert_cell_results_comparable(res_a, res_b, rife_relation="same"):
    """Two cell results may only be compared on identical group/arm/clip/
    source fps/output rect/output size/hq-common fingerprint. Rects are
    revalidated against the preregistered group registry, so tampered or
    fabricated comparability blocks cannot slip through. Integer k=1 can
    never enter a full-rect ranking (registry rects differ)."""
    for name, res in (("a", res_a), ("b", res_b)):
        if not isinstance(res, dict) or res.get("schema") != ANALYSIS_SCHEMA:
            raise lib.TrialSpecError(
                "assert_cell_results_comparable: %s is not a %s result"
                % (name, ANALYSIS_SCHEMA))
        comp = res.get("comparability")
        if not isinstance(comp, dict):
            raise lib.TrialSpecError(
                "assert_cell_results_comparable: %s has no comparability "
                "block" % name)
        group = comp.get("group")
        if group not in lib.GROUPS:
            raise lib.TrialSpecError(
                "assert_cell_results_comparable: unknown group %r" % (group,))
        if list(comp.get("expected_rect")) != \
                list(lib.GROUPS[group]["expected_rect"]):
            raise lib.TrialSpecError(
                "assert_cell_results_comparable: %s expected_rect %r does "
                "not match the preregistered registry %r for %s"
                % (name, comp.get("expected_rect"),
                   lib.GROUPS[group]["expected_rect"], group))
    ca, cb = res_a["comparability"], res_b["comparability"]
    for field in ("group", "arm", "clip", "source_fps", "expected_rect",
                  "output_size", "hq_common_sha256", "media_sha256"):
        if ca.get(field) != cb.get(field):
            raise lib.TrialSpecError(
                "cells not comparable: %s differs (%r vs %r)"
                % (field, ca.get(field), cb.get(field)))
    if ca.get("media_sha256") is None and (res_a["run_ids"] or res_b["run_ids"]):
        raise lib.TrialSpecError(
            "cells not comparable: a cell with measured runs must carry its "
            "source media_sha256 binding (F5)")
    ra, rb = ca["rife"], cb["rife"]
    if rife_relation == "same" and ra != rb:
        raise lib.TrialSpecError(
            "cells not comparable: RIFE stratum differs (%r vs %r) and this "
            "comparison requires the same stratum" % (ra, rb))
    if rife_relation == "opposite" and ra == rb:
        raise lib.TrialSpecError(
            "pairing requires opposite RIFE strata, got %r vs %r" % (ra, rb))
    return True


def rife_pairing(off_result, on_result):
    """PER-03 whole-run OFF/ON paired view for the same arm.

    Purely structural: per-pass OFF/ON medians + delta, mixed-S/M
    disclosure, no per-frame GPU attribution, and never an
    overall_headroom_ms number (no end-to-end/present source exists).
    """
    assert_cell_results_comparable(off_result, on_result, rife_relation="opposite")
    if off_result["comparability"]["rife"] != "off" \
            or on_result["comparability"]["rife"] != "on":
        raise lib.TrialSpecError(
            "rife_pairing expects (off, on) results in that order")
    passes = {"fresh": {}, "redraw": {}}
    for frame_name in ("fresh", "redraw"):
        for identity in sorted(off_result["passes"][frame_name]):
            if identity not in on_result["passes"][frame_name]:
                raise lib.TrialSpecError(
                    "rife_pairing: pass slot %r missing from ON result (%s)"
                    % (identity, frame_name))
            off_ms = off_result["passes"][frame_name][identity][
                "median_of_run_medians_ms"]
            on_ms = on_result["passes"][frame_name][identity][
                "median_of_run_medians_ms"]
            if off_ms is None or on_ms is None:
                delta = None
            else:
                delta = lib.require_finite_number(
                    on_ms - off_ms, "paired delta ms")
            passes[frame_name][identity] = {
                "identity": identity,
                "desc": off_result["passes"][frame_name][identity]["desc"],
                "off_ms": off_ms, "on_ms": on_ms,
                "delta_ms_on_minus_off": delta,
            }
    comp = off_result["comparability"]
    return {
        "schema": PAIRING_SCHEMA,
        "stage": STAGE,
        "session": SESSION,
        "plan_sha256": PLAN_SHA256,
        "cell_off": off_result["cell"],
        "cell_on": on_result["cell"],
        "comparability_note":
            "same arm/clip/source fps/output rect/hq-common fingerprint; "
            "RIFE off vs on; whole-run statistics only (PER-03)",
        "group": comp["group"], "arm": comp["arm"], "clip": comp["clip"],
        "source_fps": comp["source_fps"],
        "passes": passes,
        "on_frame_composition": _RIFE_ON_DISCLOSURE["frame_composition"],
        "per_frame_gpu_attribution":
            _RIFE_ON_DISCLOSURE["per_frame_gpu_attribution"],
        "headroom_semantics":
            "a headroom figure in ms is never produced: no end-to-end/present "
            "time source; rhythm budgets are not additive; the paired delta "
            "is a descriptive whole-run difference, not a headroom",
        "causal_claim":
            "NONE — descriptive paired difference only; never proof of "
            "causal faster/slower",
    }


# ---------------------------------------------------------------------------
# Result guards + serialization + API self-description
# ---------------------------------------------------------------------------

def assert_no_pass_verdict(result):
    """The analyzer's status vocabulary never certifies PASS. Raises if a
    result (or tampered copy) claims a PASS-like verdict."""
    if not isinstance(result, dict) or "status" not in result:
        raise lib.ValueContractError("result must be a dict with status")
    status = result["status"]
    if status not in STATUS_VOCABULARY:
        raise lib.ValueContractError(
            "status %r outside analyze vocabulary %s; analyze never "
            "certifies PASS" % (status, STATUS_VOCABULARY))
    if result.get("performance_conclusion") != PERFORMANCE_CONCLUSION:
        raise lib.ValueContractError(
            "performance_conclusion must be %r" % PERFORMANCE_CONCLUSION)
    return True


def result_json_bytes(result):
    """Canonical strict JSON bytes for evidence writing (sorted keys,
    NaN/inf rejected)."""
    return lib.canonical_json_bytes(result)


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
