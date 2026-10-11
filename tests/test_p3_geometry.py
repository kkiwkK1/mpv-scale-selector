# -*- coding: utf-8 -*-
"""P3 unit tests — pure geometry / sampling / coordinate oracles
(tests/test_p3_geometry.py). Fast, stdlib-only, never launches mpv.

Covers the P3 pure-function layer in tools/p3_lib.py:
  * Integer k geometry (1080p→1440p = 1× with 320/180 bars, 720p→1440p = 2×,
    k<1 honest downscale fallback, SAR-aware k, anti-feedback counter-example);
  * Sharp Bilinear AUTO/manual-2x scale oracles (floor(+0.01), scale-0
    protection, degenerate-to-bilinear note) and the reference coordinate
    mapping;
  * the xBR reference 21-point coordinate table and the CPU replica structure
    (flat-region fidelity + deterministic output);
  * NIS store-index bounds audit (non-divisible outputs MUST show OOB stores
    without the guard — proving the guard is necessary) and the coefficient
    texture audit (2×64 rgba32f, byte-identical to the forensic evidence);
  * the stdlib PNG decoder on TRUE-bitdepth PNGs (8- and 16-bit), letterbox
    border measurement and k×k block uniformity (GEO-02/03 oracles).
"""
from __future__ import annotations

import math
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p1_lib as lib  # noqa: E402
import p3_lib as p3   # noqa: E402


class TestIntegerGeometry(unittest.TestCase):
    """Integer gear pure functions (mirror of the Lua registry's math)."""

    def test_1080p_to_1440p_fullscreen_is_1x_with_bars(self):
        g = p3.integer_geometry(2560, 1440, 1920, 1080)
        self.assertEqual(g["k"], 1)
        self.assertEqual(g["mode"], "integer")
        self.assertEqual(g["zoom"], 0.0)
        self.assertEqual(g["video_unscaled"], "yes")
        # 2560x1440 window, 1920x1080 content → bars 320 left/right, 180 top/bottom
        self.assertEqual(g["bars"]["left"], 320)
        self.assertEqual(g["bars"]["right"], 320)
        self.assertEqual(g["bars"]["top"], 180)
        self.assertEqual(g["bars"]["bottom"], 180)

    def test_720p_to_1440p_fullscreen_is_2x_no_bars(self):
        g = p3.integer_geometry(2560, 1440, 1280, 720)
        self.assertEqual(g["k"], 2)
        self.assertAlmostEqual(g["zoom"], 1.0)
        self.assertEqual([g["bars"]["left"], g["bars"]["top"],
                          g["bars"]["right"], g["bars"]["bottom"]],
                         [0, 0, 0, 0])
        self.assertEqual(g["content_rect"], [2560, 1440])

    def test_k_below_one_is_honest_downscale_no_crop(self):
        g = p3.integer_geometry(640, 360, 1280, 720)
        self.assertEqual(g["k"], 0)
        self.assertEqual(g["mode"], "downscale-fallback")
        self.assertEqual(g["video_unscaled"], "no")
        self.assertEqual(g["zoom"], 0.0)
        self.assertIn("不裁切", g["note"])
        self.assertNotIn("crop", g["mode"])

    def test_k_is_floor_of_min_axis(self):
        # window 1000x800, display 640x360 → min(1.5625, 2.22) → 1
        self.assertEqual(p3.integer_k(1000, 800, 640, 360), 1)
        # window 2000x800, display 640x360 → min(3.125, 2.22) → 2
        self.assertEqual(p3.integer_k(2000, 800, 640, 360), 2)

    def test_k_uses_dw_dh_not_w_h_sar_aware(self):
        # SAR 2:1 source: display dw = 2*w → k must be computed from dw/dh
        k = p3.integer_k(2560, 1440, 1280, 360)   # dw=1280 (w=640), dh=360
        self.assertEqual(k, 2)
        g = p3.integer_geometry(2560, 1440, 1280, 360)
        self.assertEqual(g["k"], 2)
        # display aspect preserved: content 2560x720 = k × (dw, dh)
        self.assertEqual(g["content_rect"], [2560, 720])

    def test_unknown_geometry_is_none_not_zero(self):
        self.assertIsNone(p3.integer_k(None, None, 640, 360))
        self.assertIsNone(p3.integer_k(100, 100, 0, 0))
        self.assertIsNone(p3.integer_k(0, 0, 640, 360))
        self.assertEqual(p3.integer_geometry(0, 0, 640, 360)["mode"], "unknown")

    def test_anti_feedback_window_source_is_the_raw_window(self):
        """R5/GEO-01: the k inputs are the ORIGINAL window pixels; a margin
        that has already been shrunk by our own letterboxing must never be
        consumed. The pure function accepts only (win_w, win_h, dw, dh) —
        there is no margin parameter to feed back, and the journal rule
        accepts only the raw window/video-out-params family."""
        # a plugin that derived the window from its own bars would see
        # 2560-2*320 x 1440-2*180 = 1920x1080 and compute k=1 for a 720p
        # source — the honest function sees the raw window and computes 2.
        raw = p3.integer_k(2560, 1440, 1280, 720)
        fed_back = p3.integer_k(1920, 1080, 1280, 720)
        self.assertEqual(raw, 2)
        self.assertEqual(fed_back, 1)
        self.assertGreater(raw, fed_back)

    def test_integer_skip_notes(self):
        self.assertIn("k<1", p3.integer_skip_note(0))
        self.assertIn("k=1", p3.integer_skip_note(1))
        self.assertIn("320px", p3.integer_skip_note(1))
        self.assertEqual(p3.integer_skip_note(2), "")
        self.assertIn("未知", p3.integer_skip_note(None))


class TestSharpBilinearOracle(unittest.TestCase):
    def test_auto_floor_formula(self):
        self.assertEqual(p3.sharp_auto_scale(1440, 1080), 1)   # 退化为双线性
        self.assertEqual(p3.sharp_auto_scale(1440, 720), 2)
        self.assertEqual(p3.sharp_auto_scale(2160, 720), 3)
        self.assertEqual(p3.sharp_auto_scale(1435, 1080), 1)   # +0.01 epsilon band
        self.assertEqual(p3.sharp_auto_scale(1070, 1080), 0 + 1)  # floor(0.9907+0.01)=1 clamped
        self.assertEqual(p3.sharp_auto_scale(540, 1080), 1)    # scale 0 → clamped 1

    def test_manual_2x_is_fixed_two(self):
        self.assertEqual(p3.sharp_manual_scale(), 2)

    def test_scale_one_is_plain_bilinear_passthrough(self):
        """scale=1 → region_range=0 → f = s → mod_texel == texel exactly: the
        unmodified sample position, i.e. plain hardware bilinear (the defined
        degenerate; 1080→1440 behaves exactly like this)."""
        for i in range(16):
            pos = (i + 0.5) / 16.0          # output grid at 1x window of 8 texels
            c = p3.sharp_sample_coord(pos, 8, 1)
            self.assertAlmostEqual(c, pos * 8, places=12)

    def test_scale_two_nn_pregrid(self):
        """At the exact 2x output grid the reference maps to texel centers
        (pure nearest pre-scale) — the classic sharp-bilinear behaviour."""
        for i in range(16):
            pos = (i + 0.5) / 16.0          # 2x window over 8 texels
            c = p3.sharp_sample_coord(pos, 8, 2)
            texel = pos * 8
            self.assertAlmostEqual(c, math.floor(texel) + 0.5, places=12,
                                   msg=f"i={i} texel={texel}")

    def test_scale_two_offgrid_blends_toward_neighbor(self):
        """Off-grid output positions inside the blend band sample between
        texels (|center_dist| > region_range = 0.25)."""
        pos = 0.117     # texel = 0.9375, s = 0.9375 → cd = 0.4375 > 0.25 → blend
        c = p3.sharp_sample_coord(pos, 8, 2)
        self.assertGreater(c, math.floor(pos * 8) + 0.5)
        pos = 0.047     # texel = 0.375, s = 0.375 → cd = -0.125 → within band
        c = p3.sharp_sample_coord(pos, 8, 2)
        self.assertAlmostEqual(c, math.floor(pos * 8) + 0.5, places=12)

    def test_degenerate_note_mentions_bilinear(self):
        note = p3.sharp_degenerate_note(1)
        self.assertIn("退化为双线性", note)
        self.assertEqual(p3.sharp_degenerate_note(2), "")


class TestXBRReferenceOracle(unittest.TestCase):
    def test_21_reference_sample_points(self):
        offsets = p3.xbr_reference_offsets()
        names = [n for n, _, _ in offsets]
        self.assertEqual(len(names), 21)
        self.assertEqual(names, ["A1", "B1", "C1", "A", "B", "C", "D", "E", "F",
                                 "G", "H", "I", "G5", "H5", "I5",
                                 "A0", "D0", "G0", "C4", "F4", "I4"])
        by_name = {n: (ox, oy) for n, ox, oy in offsets}
        # the reference t1..t7 tables (xbr-lv2.glsl:244-264), texel units:
        self.assertEqual(by_name["A1"], (-1, -2))
        self.assertEqual(by_name["E"], (0, 0))
        self.assertEqual(by_name["I5"], (1, 2))
        self.assertEqual(by_name["A0"], (-2, -1))
        self.assertEqual(by_name["I4"], (2, 1))

    def test_output_is_3x(self):
        self.assertEqual(p3.xbr_output_size(16, 12), (48, 36))

    def test_cpu_replica_flat_regions_are_exact(self):
        """On a fully-flat image every output pixel must equal the flat colour
        (classification has no edges to follow; LINEAR taps all return it)."""
        flat = [[(0.4, 0.2, 0.6) for _ in range(6)] for _ in range(5)]
        out = p3.xbr_cpu_replica(flat, 6, 5, 3)
        self.assertEqual((len(out), len(out[0])), (15, 18))
        for row in out:
            for px in row:
                for a, b in zip(px, (0.4, 0.2, 0.6)):
                    self.assertAlmostEqual(a, b, places=12)

    def test_cpu_replica_deterministic_and_bounded(self):
        sha, rows = p3.generate_ppm_pattern(
            Path(tempfile.gettempdir()) / f"p3-xbr-{lib.sha256_bytes(b'x')[:8]}.ppm",
            24, 16)
        f = p3.ppm_rows_to_float(rows)
        a = p3.xbr_cpu_replica(f, 24, 16, 3)
        b = p3.xbr_cpu_replica(f, 24, 16, 3)
        d = p3.max_abs_diff_img(a, b)
        self.assertEqual(d["max"], 0)
        for row in a:
            for (r, g, bl) in row:
                self.assertTrue(0.0 <= r <= 1.0 and 0.0 <= g <= 1.0
                                and 0.0 <= bl <= 1.0)


class TestNISBoundsAndCoefficients(unittest.TestCase):
    def test_non_divisible_outputs_have_oob_stores_without_guard(self):
        """R1 evidence: for outputs not divisible by the 32x24 workgroup tile,
        the naive dispatch writes out of bounds — the guard is NECESSARY
        (never 'the GPU did not complain'). With the guard the count is 0."""
        for (w, h) in [(100, 70), (960, 540), (1000, 640), (2559, 1439)]:
            audit = p3.nis_store_index_audit(w, h)
            self.assertTrue(audit["non_divisible"], (w, h))
            self.assertGreater(audit["oob_stores_without_guard"], 0, (w, h))
            self.assertEqual(audit["oob_stores_with_guard"], 0, (w, h))

    def test_divisible_outputs_have_no_oob(self):
        audit = p3.nis_store_index_audit(640, 360)   # 20x15 tiles exactly
        self.assertFalse(audit["non_divisible"])
        self.assertEqual(audit["oob_stores_without_guard"], 0)

    def test_coefficient_audit_shape_and_evidence_identity(self):
        port = (REPO_ROOT / "shaders/p3-NIS.glsl").read_text(encoding="utf-8")
        base = (REPO_ROOT / "docs/证据/port-NVScaler.glsl").read_text(encoding="utf-8")
        audit = p3.nis_texture_audit(port, base)
        self.assertTrue(audit["ok"], audit["problems"])
        self.assertEqual(audit["textures"]["coef_scaler"]["texels"], 128)
        self.assertEqual(audit["textures"]["coef_usm"]["format"], "rgba32f")
        self.assertTrue(audit["coefficients_byte_identical_to_evidence"]["coef_scaler"])
        self.assertTrue(audit["coefficients_byte_identical_to_evidence"]["coef_usm"])

    def test_coefficient_audit_rejects_tampered_blob(self):
        port = (REPO_ROOT / "shaders/p3-NIS.glsl").read_text(encoding="utf-8")
        tampered = port.replace("0000803f", "00008040", 1)
        audit = p3.nis_texture_audit(
            tampered, (REPO_ROOT / "docs/证据/port-NVScaler.glsl").read_text(encoding="utf-8"))
        self.assertFalse(audit["coefficients_byte_identical_to_evidence"]["coef_scaler"])
        self.assertFalse(audit["ok"])

    def test_nis_static_audit(self):
        port = (REPO_ROOT / "shaders/p3-NIS.glsl").read_text(encoding="utf-8")
        base = (REPO_ROOT / "docs/证据/port-NVScaler.glsl").read_text(encoding="utf-8")
        checks = p3.nis_static_audit(port, base)
        for key, ok in checks.items():
            self.assertTrue(ok, f"NIS static audit failed: {key}")

    def test_nis_static_audit_flags_guard_before_barrier(self):
        port = (REPO_ROOT / "shaders/p3-NIS.glsl").read_text(encoding="utf-8")
        # inject a fake guard ASSIGNMENT right after hook() opens → the first
        # assignment now sits BEFORE any barrier → the audit must flag the
        # ordering (negative control for the R2 rule).
        mutated = port.replace("void hook()\n{",
                               "void hook()\n{\n\tconst bool nis_bounds_guard = false;", 1)
        self.assertNotEqual(mutated, port)
        checks = p3.nis_static_audit(mutated, "")
        self.assertFalse(checks["guard_after_all_barriers"])


class TestPNGDecoder(unittest.TestCase):
    @staticmethod
    def _make_png(w, h, bitdepth, color_type, writer):
        """Minimal stdlib PNG encoder for 8/16-bit RGB/RGBA/Gray test data."""
        channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
        raw = bytearray()
        for y in range(h):
            raw.append(0)  # filter 0
            for x in range(w):
                for v in writer(x, y):
                    if bitdepth == 8:
                        raw.append(v & 0xFF)
                    else:
                        raw += struct.pack(">H", v & 0xFFFF)

        def chunk(t, data):
            c = t + data
            return struct.pack(">I", len(data)) + c + struct.pack(
                ">I", zlib.crc32(c) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", w, h, bitdepth, color_type, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))

    def test_decode_8bit_rgb(self):
        png = self._make_png(4, 3, 8, 2, lambda x, y: (x * 60, y * 80, 128))
        dec = p3.decode_png(png)
        self.assertEqual((dec["w"], dec["h"], dec["bitdepth"]), (4, 3, 8))
        self.assertEqual(dec["pixel16"](2, 1), (120, 80, 128))

    def test_decode_16bit_rgb_is_not_silently_truncated(self):
        png = self._make_png(3, 2, 16, 2, lambda x, y: (x * 20000 + 1000,
                                                        y * 30000 + 777, 4242))
        dec = p3.decode_png(png)
        self.assertEqual(dec["bitdepth"], 16)
        r, g, b = dec["pixel16"](2, 1)
        self.assertEqual((r, g, b), (41000, 30777, 4242))
        # the 8-bit accessor is an HONEST documented down-shift, not a parser lie
        self.assertEqual(dec["get_pixel"](2, 1), (41000 >> 8, 30777 >> 8, 4242 >> 8))

    def test_rejects_non_png(self):
        with self.assertRaises(ValueError):
            p3.decode_png(b"not a png at all")

    def test_decode_handles_up_filter(self):
        # row 1 = row 0 (filter 2 = Up with zero deltas)
        w, h = 2, 2
        channels, bd = 3, 8
        stride = w * channels
        raw = bytes([0]) + bytes([10, 20, 30, 40, 50, 60]) \
            + bytes([2]) + bytes([0, 0, 0, 0, 0, 0])
        png = self._assemble_png(w, h, bd, 2, raw)
        dec = p3.decode_png(png)
        self.assertEqual(dec["pixel16"](0, 1), (10, 20, 30))
        self.assertEqual(dec["pixel16"](1, 1), (40, 50, 60))

    @staticmethod
    def _assemble_png(w, h, bd, ct, raw):
        def chunk(t, data):
            c = t + data
            return struct.pack(">I", len(data)) + c + struct.pack(
                ">I", zlib.crc32(c) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", w, h, bd, ct, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class TestCaptureAnalysis(unittest.TestCase):
    def test_letterbox_bars_measured(self):
        w, h = 32, 18
        grid = [[(0, 0, 0)] * w for _ in range(h)]
        for y in range(3, 15):
            for x in range(8, 24):
                grid[y][x] = (200, 100, 50)
        dec = p3.decode_png(TestPNGDecoder._assemble_png(
            w, h, 8, 2,
            b"".join(bytes([0]) + b"".join(bytes(px) for px in row)
                     for row in grid)))
        res = p3.analyze_letterbox(dec["get_pixel"], w, h)
        self.assertEqual(res["left"], 8)
        self.assertEqual(res["right"], 8)
        self.assertEqual(res["top"], 3)
        self.assertEqual(res["bottom"], 3)
        self.assertEqual(res["content_rect"], [8, 3, 16, 12])

    def test_block_uniformity_nearest_vs_bilinear(self):
        """A strict 2x nearest replication has 0 intra-block spread; a linear
        ramp has non-zero spread on every block."""
        w, h = 8, 8
        nn = [[(0, 0, 0)] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                v = (x // 2) * 30
                for dy in range(2):
                    for dx in range(2):
                        nn[y][x] = (v, v, v)
        # build proper 2x blocks
        grid = [[(0, 0, 0)] * w for _ in range(h)]
        for by in range(0, h, 2):
            for bx in range(0, w, 2):
                v = (bx // 2) * 30
                for dy in range(2):
                    for dx in range(2):
                        grid[by + dy][bx + dx] = (v, v, v)
        png = TestPNGDecoder._assemble_png(
            w, h, 8, 2,
            b"".join(bytes([0]) + b"".join(bytes(px) for px in row)
                     for row in grid))
        dec = p3.decode_png(png)
        u = p3.block_uniformity(dec["get_pixel"], w, h, 2)
        self.assertEqual(u["max_intra_block_spread"], 0)
        self.assertEqual(u["uniform_fraction"], 1.0)

    def test_block_uniformity_flags_gradient(self):
        w, h = 8, 8
        grid = [[(x * 30, x * 30, x * 30) for x in range(w)] for _ in range(h)]
        png = TestPNGDecoder._assemble_png(
            w, h, 8, 2,
            b"".join(bytes([0]) + b"".join(bytes(px) for px in row)
                     for row in grid))
        dec = p3.decode_png(png)
        u = p3.block_uniformity(dec["get_pixel"], w, h, 2)
        self.assertGreater(u["max_intra_block_spread"], 0)
        self.assertLess(u["uniform_fraction"], 1.0)


class TestRegistryAndConfAudit(unittest.TestCase):
    def test_p3_conf_audit_clean_on_shipped_conf(self):
        checks = p3.audit_gears_conf_p3()
        for key, ok in checks.items():
            self.assertTrue(ok, f"p3 conf audit failed: {key}")

    def test_p3_conf_audit_rejects_override_key_faking_identity(self):
        text = p3.audit_gears_conf_p3.__doc__ or ""
        shipped = (lib.GEARS_CONF).read_text(encoding="utf-8")
        attacked = shipped + "\nnis_mode=active\n"
        checks = p3.audit_gears_conf_p3(attacked)
        self.assertFalse(checks["p3_builtins_no_override_keys"])

    def test_p1_audit_migration(self):
        checks = lib.audit_gears_conf()
        for key, ok in checks.items():
            self.assertTrue(ok, f"p1 conf audit failed: {key}")
        import p2_lib as p2
        checks2 = p2.audit_gears_conf_p2()
        for key, ok in checks2.items():
            self.assertTrue(ok, f"p2 conf audit failed: {key}")

    def test_expected_chains(self):
        chains = p3.expected_builtin_chains_p3()
        self.assertEqual(chains["nis"], ["~~/shaders/p3-NIS.glsl"])
        self.assertEqual(chains["xbr"], ["~~/shaders/p3-xBR-lv2.glsl"])
        self.assertEqual(chains["sharpbilinear"],
                         ["~~/shaders/p3-Sharp-Bilinear-AUTO.glsl"])
        self.assertEqual(chains["sharpbilinear2x"],
                         ["~~/shaders/p3-Sharp-Bilinear-2x.glsl"])
        self.assertEqual(chains["integer"], [])   # geometry-only gear


class TestXBRStaticAudit(unittest.TestCase):
    def test_port_passes_all_reference_checks(self):
        text = (REPO_ROOT / "shaders/p3-xBR-lv2.glsl").read_text(encoding="utf-8")
        checks = p3.xbr_audit_source(text)
        for key, ok in checks.items():
            self.assertTrue(ok, f"xBR static audit failed: {key}")

    def test_tampered_scale_flagged(self):
        text = (REPO_ROOT / "shaders/p3-xBR-lv2.glsl").read_text(encoding="utf-8")
        mutated = text.replace("XBR_SCALE 3.0", "XBR_SCALE 4.0")
        checks = p3.xbr_audit_source(mutated)
        self.assertFalse(checks["xbr_scale_3"])


class TestResourceManifestAudit(unittest.TestCase):
    def test_manifest_clean_and_p2_disjoint(self):
        res = p3.audit_p3_resource_manifest()
        self.assertTrue(res["ok"], res["problems"])
        self.assertEqual(len(res["covered"]), 7)

    def test_comment_discipline(self):
        for rel in ("shaders/p3-NIS.glsl", "shaders/p3-xBR-lv2.glsl",
                    "shaders/p3-Sharp-Bilinear-AUTO.glsl",
                    "shaders/p3-Sharp-Bilinear-2x.glsl"):
            d = p3.shader_comment_discipline_audit(REPO_ROOT / rel)
            self.assertTrue(d["ok"], f"{rel}: {d['violations'][:3]}")

    def test_comment_discipline_flags_directive_in_comment(self):
        """Negative control for the R12 comment discipline: a prose comment
        embedding a directive-like prefix must be flagged by the REAL
        p3.shader_comment_discipline_audit (same tamper-then-feed paradigm
        as test_nis_static_audit_flags_guard_before_barrier)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-comment.glsl"
            path.write_bytes(
                "// see the line //!TEXTURE coef for details\n"
                "//!TEXTURE x\n".encode("utf-8"))
            d = p3.shader_comment_discipline_audit(path)
        self.assertFalse(d["ok"], d)
        self.assertEqual([v["line"] for v in d["violations"]], [1])
        self.assertIn("//!TEXTURE", d["violations"][0]["text"])


class TestGuardMirrors(unittest.TestCase):
    def test_hdr_guard_independent_of_luma_guard(self):
        vo_rgb = {"pixelformat": "rgb24", "gamma": "srgb"}
        vo_hdr = {"pixelformat": "rgb24", "gamma": "pq"}
        self.assertIsNone(p3.hdr_guard_reason(True, vo_rgb))       # RGB supported
        self.assertIsNotNone(p3.hdr_guard_reason(True, vo_hdr))    # HDR refused
        # 独立性：HDR 理由不得借用 LUMA 档的拒绝措辞（“LUMA 档不可用”）
        self.assertNotIn("LUMA 档不可用", p3.hdr_guard_reason(True, vo_hdr))
        self.assertIsNone(p3.hdr_guard_reason(False, vo_hdr))
        self.assertIsNone(p3.hdr_guard_reason(True, None))

    def test_nis_luma_guard_uses_p2_semantics(self):
        vo_rgb = {"pixelformat": "rgb24", "gamma": "srgb"}
        self.assertIn("RGB", p3.luma_guard_reason_p3(vo_rgb))


if __name__ == "__main__":
    unittest.main()
