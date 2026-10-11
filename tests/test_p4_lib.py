# -*- coding: utf-8 -*-
"""P4 unit tests for tools/p4_lib.py (session p4-001, batch B1-r2 unit A).

Real invocations of the contract/rejection logic (no hand-set booleans):
illegal paths, create-only reuse refusal, symlink/junction component
rejection, bool≠number and NaN/inf rejection, strict JSON, media-seed
determinism, four preregistered clip frame counts, PNG decode + bit-depth +
size + marker frame-identity rechecks, same-seed reproducibility and
cross-frame variation, ultra-short-media budget refusal, odd-n residual
imbalance disclosure, Integer-group comparability lock, missing required
inputs, snapshot schema negatives (bool/NaN/negative-ns/dedup-free tables,
strictly increasing indices), counter saturation never blocking, production
lock un-bypassable.

B1-r2 additions (P4-B1限域修正brief-v2.md):
  * LF10 native vo-passes mapping: `count` is the native per-pass
    timing-sample count and `samples_ns` is the raw ns timing array (per
    docs/证据/mpv-input.rst); the old int `samples` field is rejected as the
    native-API misreading it was; sample arrays keep every value and
    duplicate verbatim; count==len(samples_ns) enforced; count:null records
    an API-omitted count (never fabricated); optional raw_node preserved;
  * LF11: duplicate pass descs are legal and kept verbatim (the analysis
    layer owns ordinal+desc identity);
  * F5 corrected geometry contract: groups carry independent
    expected_window_size + expected_margins (the legacy G2 output_size is
    the video size and must never judge the window); dw/dh is the
    square-pixel source display size, never the window/rect; osd margins are
    all-or-none non-negative ints; source metadata carries a generator hash;
    frames may declare S/M class.
Stdlib + tempfile only; no GPU/mpv/runtime is started; no credentials are
read; all writes inside temp dirs (no external side effects).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p4_lib as lib  # noqa: E402


def _tmp_root(self):
    return Path(tempfile.mkdtemp(prefix="p4lib-test-"))


def _pass_entry(desc, avg_ns, samples_ns="default", count="default", **extra):
    if samples_ns == "default":
        samples_ns = [avg_ns, avg_ns, avg_ns, avg_ns, avg_ns]
    entry = {"desc": desc, "last_ns": avg_ns * 2, "avg_ns": avg_ns,
             "peak_ns": avg_ns * 3,
             "count": len(samples_ns) if count == "default" else count,
             "samples_ns": list(samples_ns) if samples_ns is not None else None}
    if entry["samples_ns"] is None:
        entry["samples_ns"] = []  # count stays None => recorded API omission
    entry.update(extra)
    return entry


def _snap(i=0, **overrides):
    base = {
        "snapshot_index": i,
        "wall_monotonic_s": 1000.25 + i,
        "time_pos_s": 12.0 + i,
        "epoch": 0,
        "video_out_params": {"pixelformat": "yuv420p", "w": 1920, "h": 1080,
                             "dw": 1920, "dh": 1080},
        "osd_dimensions": {"w": 2560, "h": 1440,
                           "ml": 0, "mr": 0, "mt": 0, "mb": 0},
        "vo_passes": {
            "fresh": [_pass_entry("pass A", 900),
                      _pass_entry("pass B", 800)],
            "redraw": [_pass_entry("pass A redraw", 380)],
        },
    }
    for key, value in overrides.items():
        if value is _DELETE:
            base.pop(key, None)
        else:
            base[key] = value
    return base


class _Delete:
    pass


_DELETE = _Delete()


class TestStrictNumbers(unittest.TestCase):
    def test_bool_is_never_a_number(self):
        for bad in (True, False):
            with self.assertRaises(lib.ValueContractError):
                lib.require_finite_number(bad, "f")
            with self.assertRaises(lib.ValueContractError):
                lib.require_nonneg_number(bad, "f")
            with self.assertRaises(lib.ValueContractError):
                lib.require_int(bad, "f")

    def test_nan_inf_and_non_numbers_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(lib.ValueContractError):
                lib.require_finite_number(bad, "f")
        for bad in ("3", None, 3j, [3]):
            with self.assertRaises(lib.ValueContractError):
                lib.require_finite_number(bad, "f")
        with self.assertRaises(lib.ValueContractError):
            lib.require_nonneg_number(-0.5, "f")
        with self.assertRaises(lib.ValueContractError):
            lib.require_int(5.0, "f")  # floats are not ints under this contract
        self.assertEqual(lib.require_finite_number(3, "f"), 3)
        self.assertEqual(lib.require_finite_number(2.5, "f"), 2.5)
        self.assertEqual(lib.require_int(7, "f"), 7)


class TestStrictJson(unittest.TestCase):
    def test_nan_infinity_tokens_rejected(self):
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.assertRaises(lib.ValueContractError):
                lib.strict_json_loads(text)

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(lib.ValueContractError):
            lib.strict_json_loads('{"a": 1, "a": 2}')

    def test_invalid_json_rejected_and_valid_roundtrip(self):
        with self.assertRaises(lib.ValueContractError):
            lib.strict_json_loads("{not json}")
        obj = {"b": 1, "a": [1, 2, {"c": "x"}]}
        raw = lib.strict_json_bytes(obj)
        self.assertEqual(lib.strict_json_loads(raw), obj)
        self.assertEqual(raw, lib.strict_json_bytes(obj))  # canonical/deterministic
        with self.assertRaises(lib.ValueContractError):
            lib.strict_json_bytes({"a": float("nan")})


class TestPathContract(unittest.TestCase):
    def test_illegal_rel_paths_rejected(self):
        for bad in ("", None, 5, "/abs/path", "C:/x/y", "D:\\x", "a\\b",
                    "../escape", "a/../../b", "a/./b", "a//b", "dir/",
                    "\\\\server\\share", "CON", "aux.png"):
            with self.assertRaises(lib.PathContractError):
                lib.check_rel_path(bad)
        self.assertEqual(lib.check_rel_path("docs/验证/开发/x.json"),
                         "docs/验证/开发/x.json")

    def test_create_only_dir_rejects_reuse(self):
        root = _tmp_root(self)
        rel = "docs/验证/开发/p4-001/b1-lib-test/trial-1"
        lib.create_only_dir(rel, root=root)
        self.assertTrue((root / rel).is_dir())
        with self.assertRaises(lib.CreateOnlyError):
            lib.create_only_dir(rel, root=root)

    def test_create_only_file_refuses_overwrite(self):
        root = _tmp_root(self)
        lib.create_only_dir("evidence", root=root)
        rec = lib.create_only_file("evidence/a.bin", b"\x00\x01", root=root)
        self.assertEqual(rec["sha256"], hashlib.sha256(b"\x00\x01").hexdigest())
        with self.assertRaises(lib.CreateOnlyError):
            lib.create_only_file("evidence/a.bin", b"\x00\x01", root=root)
        with self.assertRaises(lib.PathContractError):
            lib.create_only_file("missing-dir/a.bin", b"x", root=root)

    def test_symlink_reparse_component_rejected(self):
        root = _tmp_root(self)
        outside = root / "outside"
        outside.mkdir()
        link = root / "linkdir"
        if os.name == "nt":
            import _winapi  # stdlib on CPython-Windows; junction needs no admin
            _winapi.CreateJunction(str(outside), str(link))
        else:
            os.symlink(str(outside), str(link))
        with self.assertRaises(lib.PathContractError):
            lib.resolve_under_root("linkdir/file.txt", root=root)
        (outside / "f.bin").write_bytes(b"x")
        with self.assertRaises(lib.PathContractError):
            lib.create_only_file("linkdir/f.bin", b"y", root=root)

    def test_escaping_resolution_rejected(self):
        root = _tmp_root(self)
        # ".." is rejected textually before any resolution happens
        with self.assertRaises(lib.PathContractError):
            lib.resolve_under_root("a/../..", root=root)
        # a canonical rel path under a real root resolves inside it
        target = lib.resolve_under_root("docs/x/y.json", root=root)
        self.assertTrue(str(target).startswith(str(root.resolve())))


class TestMediaSeedAndClips(unittest.TestCase):
    def test_media_seed_derivation_matches_preregistered_formula(self):
        for clip_id in lib.CLIPS:
            expected = int(
                hashlib.sha256(("p4-001/" + clip_id).encode("utf-8"))
                .hexdigest()[:16], 16) % (2 ** 32)
            seed = lib.derive_media_seed(clip_id)
            self.assertEqual(seed, expected)
            self.assertEqual(seed, lib.derive_media_seed(clip_id))  # stable
            self.assertTrue(0 <= seed < 2 ** 32)
        seeds = {c: lib.derive_media_seed(c) for c in lib.CLIPS}
        self.assertEqual(len(set(seeds.values())), len(seeds))  # per-clip distinct
        with self.assertRaises(lib.TrialSpecError):
            lib.derive_media_seed("invented-clip")

    def test_four_preregistered_clips_frame_counts(self):
        expected = {"motion24": (1920, 1080, 24, 720),
                    "motion30": (1920, 1080, 30, 900),
                    "motion720": (1280, 720, 24, 720),
                    "pixelart": (480, 360, 24, 720)}
        self.assertEqual(set(lib.CLIPS), set(expected))
        for clip_id, (w, h, fps, frames) in expected.items():
            spec = lib.get_clip(clip_id)
            self.assertEqual((spec["width"], spec["height"]), (w, h))
            self.assertEqual(spec["fps"], fps)
            self.assertEqual(spec["frames"], frames)  # 30 s @ fps
            self.assertEqual(spec["duration_s"], 30.0)
        with self.assertRaises(lib.TrialSpecError):
            lib.get_clip("motion60")

    def test_frame_identity_metadata(self):
        ident = lib.frame_identity("motion24", 7)
        self.assertEqual((ident["pts_num"], ident["pts_den"]), (7, 24))
        self.assertEqual(ident["pts_exact"], "7/24")
        self.assertEqual(ident["fps_num"], 24)
        self.assertEqual(ident["frame_class"], "S")
        with self.assertRaises(lib.ValueContractError):
            lib.frame_identity("motion24", 720)   # out of range
        with self.assertRaises(lib.ValueContractError):
            lib.frame_identity("motion24", True)  # bool is not an index
        self.assertEqual(lib.rife_output_frame_class(0), "S")
        self.assertEqual(lib.rife_output_frame_class(1), "M")
        self.assertEqual(lib.rife_output_frame_class(5), "M")


class TestPngFrames(unittest.TestCase):
    def test_motion24_frame_roundtrip_identity_and_variation(self):
        png7 = lib.encode_png_rgb8(1920, 1080, lib._rows_for(
            lib.get_clip("motion24"), 7))
        identity = lib.verify_png_frame(png7, "motion24", 7)
        self.assertEqual(identity["width"], 1920)
        self.assertEqual(identity["height"], 1080)
        self.assertEqual(identity["bit_depth"], 8)
        self.assertEqual(identity["decoded_marker_index"], 7)
        png7_again = lib.encode_png_rgb8(1920, 1080, lib._rows_for(
            lib.get_clip("motion24"), 7))
        self.assertEqual(png7, png7_again)  # same seed/index => byte-identical
        png8 = lib.encode_png_rgb8(1920, 1080, lib._rows_for(
            lib.get_clip("motion24"), 8))
        self.assertNotEqual(png7, png8)     # different frame varies
        # tampered frame content must fail the marker identity check
        with self.assertRaises(lib.ValueContractError):
            lib.verify_png_frame(png8, "motion24", 7)
        with self.assertRaises(ValueError):
            lib.verify_png_frame(b"not a png", "motion24", 7)

    def test_motion720_and_pixelart_decode_rechecks(self):
        spec = lib.get_clip("motion720")
        png = lib.encode_png_rgb8(spec["width"], spec["height"],
                                  lib._rows_for(spec, 3))
        identity = lib.verify_png_frame(png, "motion720", 3)
        self.assertEqual((identity["width"], identity["height"]), (1280, 720))
        pspec = lib.get_clip("pixelart")
        ppng = lib.encode_png_rgb8(pspec["width"], pspec["height"],
                                   lib._rows_for(pspec, 5))
        ppng_again = lib.encode_png_rgb8(pspec["width"], pspec["height"],
                                         lib._rows_for(pspec, 5))
        self.assertEqual(ppng, ppng_again)
        pident = lib.verify_png_frame(ppng, "pixelart", 5)
        self.assertEqual((pident["width"], pident["height"]), (480, 360))
        ppng6 = lib.encode_png_rgb8(pspec["width"], pspec["height"],
                                    lib._rows_for(pspec, 6))
        self.assertNotEqual(ppng, ppng6)
        # wrong-size PNG against the clip spec is rejected (size recheck)
        small = lib.encode_png_rgb8(8, 8, [b"\x10" * 24] * 8)
        with self.assertRaises(lib.ValueContractError):
            lib.verify_png_frame(small, "motion24", 0)


class TestStreamingGeneration(unittest.TestCase):
    def test_iter_clip_frames_is_lazy_generator(self):
        it = lib.iter_clip_frames("pixelart", indices=[0, 1, 2])
        self.assertTrue(hasattr(it, "__next__"))       # streaming iterator
        self.assertFalse(isinstance(it, list))         # never a materialised list
        pairs = list(it)
        self.assertEqual([i for i, _ in pairs], [0, 1, 2])

    def test_write_clip_frames_create_only(self):
        out = Path(tempfile.mkdtemp(prefix="p4lib-frames-"))
        records = lib.write_clip_frames("pixelart", out, indices=[0, 1, 2])
        self.assertEqual(len(records), 3)
        for rec in records:
            self.assertTrue((out / rec["file"]).is_file())
            self.assertEqual(rec["sha256"],
                             lib.sha256_file(out / rec["file"]))
        with self.assertRaises(lib.CreateOnlyError):
            lib.write_clip_frames("pixelart", out, indices=[0])
        with self.assertRaises(lib.PathContractError):
            lib.write_clip_frames("pixelart", out / "nope", indices=[0])


class TestBudgetAndSchedule(unittest.TestCase):
    def test_budget_check_passes_for_preregistered_media(self):
        result = lib.sampling_budget_check()  # 30 s preregistered
        self.assertEqual(result["required_min_media_s"], 27.5)
        for clip_id in lib.CLIPS:
            lib.assert_clip_covers_sampling(clip_id)  # must not raise

    def test_ultra_short_media_refused(self):
        for short in (5.0, 27.4):
            with self.assertRaises(lib.ScheduleBudgetError):
                lib.sampling_budget_check(short)

    def test_run_order_deterministic_with_adjacent_reversal(self):
        order1 = lib.run_order_for_group("G1_equalrect_main")
        order2 = lib.run_order_for_group("G1_equalrect_main")
        self.assertEqual(order1, order2)               # seed-deterministic

        blocks = order1["blocks"]
        self.assertEqual(len(blocks), 5)
        arms = lib.GROUPS["G1_equalrect_main"]["arms"]
        for block in blocks:
            self.assertEqual(sorted(block), sorted(arms))  # permutations
        self.assertEqual(blocks[1], list(reversed(blocks[0])))
        self.assertEqual(blocks[3], list(reversed(blocks[2])))
        self.assertNotEqual(blocks[2], blocks[0])      # fresh permutations
        # odd-n residual imbalance must be disclosed, not hidden
        self.assertEqual(order1["n_parity"], "odd")
        self.assertFalse(order1["balanced"])
        self.assertIn("residual order imbalance",
                      order1["residual_imbalance_disclosure"])
        order3 = lib.run_order_for_group("G3_pixelart")  # n=3 odd
        self.assertEqual(len(order3["blocks"]), 3)
        self.assertIsNotNone(order3["residual_imbalance_disclosure"])

    def test_rife_calibration_pair_alternation(self):
        pairs = lib.rife_calibration_pair_order(4)
        self.assertEqual(pairs, [["off", "on"], ["on", "off"],
                                 ["off", "on"], ["on", "off"]])

    def test_counter_delta_saturation_never_blocks_negative_rejected(self):
        sat = lib.counter_delta(1000, 1000, "vo-passes.count")
        self.assertEqual(sat["delta"], 0)
        self.assertTrue(sat["no_growth"])
        self.assertFalse(sat["blocking"])  # saturation reported, not raised
        self.assertIn("never", sat["note"])
        self.assertEqual(lib.counter_delta(10, 15)["delta"], 5)
        with self.assertRaises(lib.ValueContractError):
            lib.counter_delta(15, 10)  # counter reset => negative delta invalid


class TestCellEnumeration(unittest.TestCase):
    def test_preregistered_cells_match_plan_totals(self):
        totals = lib.cell_run_totals()
        # plan B5 timed budget: 40+40+15+15+5+9+12 = 136 runs in 30 cells
        self.assertEqual(totals, {"cells": 30, "runs": 136})
        cells = lib.enumerate_cells()
        g1_off = [c for c in cells if c["group"] == "G1_equalrect_main"
                  and c["clip"] == "motion24" and c["rife"] == "off"]
        self.assertEqual(len(g1_off), 8)
        g1_on = [c for c in cells if c["group"] == "G1_equalrect_main"
                 and c["rife"] == "on" and c["clip"] == "motion24"]
        self.assertEqual(len(g1_on), 8)
        fps_cells = [c for c in cells if c["clip"] == "motion30"]
        self.assertEqual(len(fps_cells), 6)  # 3 arms x (off@30, on@60)
        for c in fps_cells:
            self.assertIn(c["arm"], lib.FPS_SUBSET_ARMS)
            expected_out = c["source_fps"] * 2 if c["rife"] == "on" else c["source_fps"]
            self.assertEqual(c["rife_output_fps"], expected_out)

    def test_integer_k1_never_ranked_with_full_rect_group(self):
        g2 = lib.get_cell("G2_integer_display|Integer|motion24@24|rife=off")
        g1 = lib.get_cell("G1_equalrect_main|baselineHQ|motion24@24|rife=off")
        with self.assertRaises(lib.TrialSpecError):
            lib.assert_cells_comparable(g2, g1)   # different groups/rects
        same = lib.get_cell("G1_equalrect_main|nearest|motion24@24|rife=off")
        self.assertTrue(lib.assert_cells_comparable(g1, same))
        with self.assertRaises(lib.TrialSpecError):
            lib.get_cell("G2_integer_display|Integer|motion24@24|rife=on")
        with self.assertRaises(lib.TrialSpecError):
            lib.get_cell("G1_equalrect_main|baselineHQ|motion24@24|rife=nope")

    def test_stock_anime4k_is_registered_real_arm_not_stub(self):
        arms = lib.GROUPS["G1_equalrect_main"]["arms"]
        self.assertIn("Anime4K-ModeA", arms)   # stock six-chain identity, Mode A
        self.assertEqual(len(arms), 8)
        self.assertNotIn("stub", [a.lower() for a in arms])
        spec = lib.make_trial_spec("G1_equalrect_main", "Anime4K-ModeA", "off", 1,
                                   plan_sha256=lib.PLAN_SHA256)
        self.assertEqual(spec["clip"], "motion24")


class TestGroupGeometryRegistry(unittest.TestCase):
    """F5 (B1-r2): corrected coordinate-boundary contract."""

    def test_every_group_has_independent_window_and_margins(self):
        expected = {
            "G1_equalrect_main": ([2560, 1440], [2560, 1440], [2560, 1440],
                                  [0, 0, 0, 0]),
            "G2_integer_display": ([1920, 1080], [1920, 1080], [2560, 1440],
                                   [320, 180, 320, 180]),
            "G2b_integer_k2": ([2560, 1440], [2560, 1440], [2560, 1440],
                               [0, 0, 0, 0]),
            "G3_pixelart": ([1440, 1080], [1440, 1080], [1440, 1080],
                            [0, 0, 0, 0]),
        }
        for group_id, (rect, output, window, margins) in expected.items():
            group = lib.get_group(group_id)
            self.assertEqual(group["expected_rect"], rect)
            self.assertEqual(group["output_size"], output)
            self.assertEqual(group["expected_window_size"], window)
            self.assertEqual(group["expected_margins"], margins)

    def test_g2_window_is_independent_of_legacy_output_size(self):
        # the legacy output_size mixed the video size with the window; the
        # corrected contract keeps the legacy field but the WINDOW of the G2
        # Integer letterbox group stays 2560x1440 (never the 1920x1080 video
        # size) — expected_window_size must differ from output_size here.
        g2 = lib.GROUPS["G2_integer_display"]
        self.assertEqual(g2["expected_window_size"], [2560, 1440])
        self.assertEqual(g2["output_size"], [1920, 1080])
        self.assertNotEqual(g2["expected_window_size"], g2["output_size"])
        self.assertIn("never be used to judge the window", g2["note"])

    def test_expected_geometry_contract_values(self):
        geo = lib.expected_geometry("G2_integer_display")
        self.assertEqual(geo["source_w_h"], [1920, 1080])       # motion24
        self.assertEqual(geo["display_dw_dh"], [1920, 1080])    # square pixels
        self.assertEqual(geo["window_w_h"], [2560, 1440])
        self.assertEqual(geo["rect_w_h"], [1920, 1080])
        self.assertEqual(geo["margins_ml_mt_mr_mb"], [320, 180, 320, 180])
        # margins + rect must reconstruct the window (letterbox consistency)
        ml, mt, mr, mb = geo["margins_ml_mt_mr_mb"]
        self.assertEqual([geo["window_w_h"][0] - ml - mr,
                          geo["window_w_h"][1] - mt - mb], geo["rect_w_h"])
        for group_id in lib.GROUPS:
            g = lib.expected_geometry(group_id)
            clip = lib.get_clip(lib.get_group(group_id)["clip"])
            self.assertEqual(g["source_w_h"], [clip["width"], clip["height"]])
            # dw/dh equals source w/h for the square-pixel synthetic sources
            self.assertEqual(g["display_dw_dh"], g["source_w_h"])

    def test_dw_dh_boundary_is_explicit_never_window_or_rect(self):
        text = lib.GEOMETRY_SEMANTICS
        self.assertIn("dw/dh", text)
        self.assertIn("NEVER the window", text)
        self.assertIn("NEVER the shader output rect", text)
        self.assertIn("ACTUALLY observed margins", text)
        geo = lib.expected_geometry("G1_equalrect_main")
        self.assertIn("semantics", geo)

    def test_source_metadata_contract_fields(self):
        # FIELD_SEMANTICS documents the F5 source identity + osd margin rules
        semantics = lib.snapshot_schema()["field_semantics"]
        self.assertIn("generator", semantics["source"])
        self.assertIn("ml/mr/mt/mb", semantics["osd_dimensions"])
        self.assertIn("never", semantics["osd_dimensions"])


class TestTrialSpecContract(unittest.TestCase):
    PLAN = lib.PLAN_SHA256

    def test_valid_calibration_spec_roundtrip(self):
        spec = lib.make_trial_spec("G2b_integer_k2", "nearest", "off", 2,
                                   run_kind="pilot", plan_sha256=self.PLAN)
        self.assertEqual(spec["clip"], "motion720")
        self.assertEqual(spec["expected_rect"], [2560, 1440])
        self.assertEqual(spec["media_seed"], lib.derive_media_seed("motion720"))
        self.assertEqual(spec["cell"],
                         "G2b_integer_k2|nearest|motion720@24|rife=off")
        self.assertEqual(lib.validate_trial_spec(spec), spec)
        fps_spec = lib.make_trial_spec("G1_equalrect_main", "FSR1", "on", 5,
                                       source_fps=30, plan_sha256=self.PLAN)
        self.assertEqual(fps_spec["clip"], "motion30")
        self.assertEqual(fps_spec["rife_output_fps"], 60)

    def test_production_lock_cannot_be_bypassed_by_inputs(self):
        with self.assertRaises(lib.ProductionLockedError):
            lib.make_trial_spec("G1_equalrect_main", "nearest", "off", 1,
                                plan_sha256=self.PLAN, run_kind="production")
        with self.assertRaises(lib.ProductionLockedError):
            lib.validate_trial_spec(dict(
                lib.make_trial_spec("G3_pixelart", "nearest", "off", 1,
                                    plan_sha256=self.PLAN),
                run_kind="production"))

    def test_spec_rejections(self):
        with self.assertRaises(lib.P4ContractError):  # bool where int required
            lib.make_trial_spec("G1_equalrect_main", "nearest", "off", True,
                                plan_sha256=self.PLAN)
        with self.assertRaises(lib.TrialSpecError):   # wrong plan hash
            lib.make_trial_spec("G1_equalrect_main", "nearest", "off", 1,
                                plan_sha256="0" * 64)
        with self.assertRaises(lib.TrialSpecError):   # arm not in group
            lib.make_trial_spec("G2_integer_display", "nearest", "off", 1,
                                plan_sha256=self.PLAN)
        with self.assertRaises(lib.TrialSpecError):   # rife=on outside G1
            lib.make_trial_spec("G3_pixelart", "nearest", "on", 1,
                                plan_sha256=self.PLAN)
        with self.assertRaises(lib.TrialSpecError):   # off@30 outside fps subset
            lib.make_trial_spec("G1_equalrect_main", "nearest", "off", 1,
                                source_fps=30, plan_sha256=self.PLAN)
        with self.assertRaises(lib.TrialSpecError):   # repeat beyond n
            lib.make_trial_spec("G3_pixelart", "nearest", "off", 4,
                                plan_sha256=self.PLAN)
        with self.assertRaises(lib.TrialSpecError):   # unknown group
            lib.make_trial_spec("G9", "nearest", "off", 1,
                                plan_sha256=self.PLAN)
        spec = lib.make_trial_spec("G1_equalrect_main", "nearest", "off", 1,
                                   plan_sha256=self.PLAN)
        with self.assertRaises(lib.TrialSpecError):   # unknown extra key
            lib.validate_trial_spec(dict(spec, evil="x"))
        with self.assertRaises(lib.TrialSpecError):   # tampered cell key
            lib.validate_trial_spec(dict(spec, cell="G1|nearest|motion24@24|rife=on"))
        with self.assertRaises(lib.TrialSpecError):   # tampered media seed
            lib.validate_trial_spec(dict(spec, media_seed=1))

    def test_missing_required_inputs_fail_closed(self):
        root = _tmp_root(self)
        spec = lib.make_trial_spec("G3_pixelart", "nearest", "off", 1,
                                   plan_sha256=self.PLAN)
        with self.assertRaises(lib.MissingInputError) as ctx:
            lib.verify_required_inputs(spec, root=root)
        for rel in lib.required_input_rels(spec):
            self.assertIn(rel, str(ctx.exception))
            parent = (root / rel).parent
            if not parent.is_dir():
                parent.mkdir(parents=True)
            (root / rel).write_bytes(b"placeholder")
        result = lib.verify_required_inputs(spec, root=root)
        self.assertTrue(result["ok"])


class TestSnapshotSchema(unittest.TestCase):
    def test_valid_snapshot_keeps_duplicate_values_verbatim(self):
        snap = _snap(0)
        info = lib.validate_snapshot(snap)  # two passes share identical numbers
        self.assertEqual(info["fresh"], 2)  # NOT value-deduplicated
        self.assertEqual(info["redraw"], 1)
        schema = lib.snapshot_schema()
        self.assertIn("never", schema["field_semantics"]["wall_monotonic_s"])
        self.assertIn("ONE Lua IPC command", schema["single_command"])
        self.assertFalse(schema["no_value_dedup"] is False)
        # LF10 units contract
        self.assertEqual(schema["units"]["samples_ns"], "ns (raw timing array, LF10)")
        self.assertIn("native", schema["units"]["count"])
        self.assertIn("count", schema["field_semantics"]["vo_passes"])
        self.assertIn("samples_ns", schema["field_semantics"]["vo_passes"])
        self.assertIn("misreading", schema["field_semantics"]["vo_passes"])

    def test_snapshots_are_validated_without_mutation_and_keep_duplicates(self):
        snap = _snap(0)
        frozen = json.dumps(snap, sort_keys=True)
        lib.validate_snapshot(snap)
        self.assertEqual(json.dumps(snap, sort_keys=True), frozen)
        # duplicate raw sample values are real observations, kept verbatim
        snap["vo_passes"]["fresh"][0]["samples_ns"] = [777, 777, 777, 777]
        snap["vo_passes"]["fresh"][0]["count"] = 4
        lib.validate_snapshot(snap)  # no dedup, no coercion, no raise

    def test_lf10_native_count_and_samples_array_contract(self):
        # count == len(samples_ns) is enforced
        entry = _pass_entry("p", 900, samples_ns=[5, 5], count=3)
        snap = _snap(0)
        snap["vo_passes"]["fresh"] = [entry]
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(snap)
        # count may be explicitly null ONLY as a recorded API omission
        snap2 = _snap(0)
        snap2["vo_passes"]["fresh"] = [_pass_entry("p", 900, count=None,
                                                   samples_ns=[5, 5])]
        lib.validate_snapshot(snap2)  # missing count recorded, never fabricated
        # the old int `samples` field was an LF10 native-API misreading
        snap3 = _snap(0)
        snap3["vo_passes"]["fresh"][0] = {
            "desc": "p", "last_ns": 1, "avg_ns": 1, "peak_ns": 1, "samples": 5}
        with self.assertRaises(lib.ValueContractError) as ctx:
            lib.validate_snapshot(snap3)
        self.assertIn("LF10", str(ctx.exception))
        # samples_ns must be an array, never an int
        snap4 = _snap(0)
        snap4["vo_passes"]["fresh"][0]["samples_ns"] = 5
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(snap4)

    def test_lf11_duplicate_pass_descs_are_legal_verbatim(self):
        snap = _snap(0)
        snap["vo_passes"]["fresh"] = [_pass_entry("pass A", 900),
                                      _pass_entry("pass A", 950),
                                      _pass_entry("pass B", 800)]
        info = lib.validate_snapshot(snap)
        self.assertEqual(info["fresh"], 3)  # same-named passes all kept

    def test_optional_raw_node_and_pass_entry_types(self):
        snap = _snap(0)
        native = {"desc": "p", "last": 1, "avg": 2, "peak": 3,
                  "count": 2, "samples": [1, 2]}
        snap["vo_passes"]["fresh"] = [_pass_entry("p", 2, raw_node=native)]
        lib.validate_snapshot(snap)  # raw node preserved alongside mapping
        snap["vo_passes"]["fresh"] = [_pass_entry("p", 2, raw_node="not-a-dict")]
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(snap)
        for bad in (True, float("nan"), -3):
            snap_bad = _snap(0)
            snap_bad["vo_passes"]["fresh"] = [
                _pass_entry("p", 900, samples_ns=[bad])]
            with self.assertRaises(lib.ValueContractError):
                lib.validate_snapshot(snap_bad)

    def test_snapshot_negatives(self):
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, samples=True))        # unknown field
        with self.assertRaises(lib.ValueContractError):
            bad = _snap(0)
            bad["vo_passes"]["fresh"] = [{
                "desc": "p", "last_ns": 1, "avg_ns": float("nan"),
                "peak_ns": 2, "count": 1, "samples_ns": [1]}]
            lib.validate_snapshot(bad)
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, last_ns=-5))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, epoch=-1))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, wall_monotonic_s=True))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, unknown_field=1))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, snapshot_index="0"))
        broken = _snap(0)
        del broken["epoch"]
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(broken)
        # both tables empty is schema-legal raw data (warmup); the analysis
        # layer owns the real-window rejection (F1)
        lib.validate_snapshot(_snap(0, vo_passes={"fresh": [], "redraw": []}))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, vo_passes={"fresh": []}))  # missing redraw
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, vo_passes={"fresh": [], "redraw": [],
                                                      "extra": []}))

    def test_osd_margins_all_or_none_non_negative(self):
        snap = _snap(0)
        del snap["osd_dimensions"]["mr"]
        with self.assertRaises(lib.ValueContractError) as ctx:
            lib.validate_snapshot(snap)
        self.assertIn("all-or-none", str(ctx.exception))
        snap2 = _snap(0)
        snap2["osd_dimensions"]["ml"] = -1
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(snap2)
        snap3 = _snap(0)
        snap3["osd_dimensions"]["ml"] = True  # bool is never an int here
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(snap3)

    def test_source_and_frame_metadata_contract(self):
        gen = lib.library_sha256()
        src = {"clip": "motion24",
               "media_sha256": hashlib.sha256(b"m").hexdigest(),
               "generator_sha256": gen}
        lib.validate_snapshot(_snap(0, source=src))
        bad = dict(src, generator_sha256="zz" * 32)
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, source=bad))
        bad2 = dict(src, media_sha256=True)
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, source=bad2))
        frame = {"index": 5, "pts_num": 5, "pts_den": 24, "frame_class": "S"}
        lib.validate_snapshot(_snap(0, frame=frame))
        lib.validate_snapshot(_snap(0, frame=dict(frame, frame_class="M",
                                                  index=1000)))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_snapshot(_snap(0, frame=dict(frame,
                                                      frame_class="X")))

    def test_run_jsonl_strictly_increasing_and_nan_rejected(self):
        text = "\n".join(json.dumps(_snap(i)) for i in (0, 1, 2))
        snaps = lib.validate_run_jsonl(text)
        self.assertEqual(len(snaps), 3)
        with self.assertRaises(lib.ValueContractError):
            lib.validate_run_jsonl("\n".join(json.dumps(_snap(i))
                                             for i in (0, 1, 1)))
        with self.assertRaises(lib.ValueContractError):
            lib.validate_run_jsonl('{"snapshot_index": 0, "time_pos_s": NaN}')
        with self.assertRaises(lib.ValueContractError):
            lib.validate_run_jsonl("\n \n")

    def test_same_moment_semantics_documented(self):
        schema = lib.snapshot_schema()
        blob = json.dumps(schema)
        self.assertIn("pixelformat", blob)     # geometry in same window
        self.assertIn("epoch", blob)
        self.assertIn("fresh", blob)


class TestApiManifest(unittest.TestCase):
    def test_api_manifest_lists_public_contract(self):
        manifest = lib.api_manifest()
        joined = "\n".join(manifest)
        for expected in ("make_trial_spec", "validate_trial_spec",
                         "enumerate_cells", "derive_media_seed",
                         "iter_clip_frames", "verify_png_frame",
                         "create_only_dir", "create_only_file",
                         "resolve_under_root", "sha256_file",
                         "validate_snapshot", "counter_delta",
                         "run_order_for_group", "sampling_budget_check",
                         "expected_geometry"):
            self.assertIn(expected, joined)
        self.assertTrue(all("(" in entry for entry in manifest))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
