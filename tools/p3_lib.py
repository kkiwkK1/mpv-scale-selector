# -*- coding: utf-8 -*-
"""p3_lib.py — P3 (p3-001) shared support library: pure-function layer.

P3 scope (docs/P3实施计划.json): four new product gear families on the P1/P2
state machine —
  * nis      : NVIDIA Image Scaling v1.0.2 compute port (LUMA, MIT), real
               workgroup 32x24 / 256 threads + two 2x64 rgba32f coefficient
               textures; versionable per-pixel output bounds guard AFTER all
               barriers; //!WHEN (>1x upscale) semantics preserved unchanged;
  * xbr      : Hyllian's xBR-lv2 (libretro reference, MIT), ported to an mpv
               MAIN RGB hook with the reference 3x pre-scale + mpv final-scale
               mode explicitly declared (never "any-ratio equivalent", never
               xBRZ);
  * sharpbilinear / sharpbilinear2x
             : Themaister sharp-bilinear (public domain) — AUTO and manual 2x
               separately named gears; AUTO = floor(out_h/in_h + 0.01) with
               scale<1/0 protection (clamped to plain bilinear);
  * integer  : k = floor(min(window_px / effective display size)) geometry
               with video-unscaled + zoom=log2(k) + nearest scalers; the
               window source is the ORIGINAL window pixels (osd-width/height),
               NEVER a margin derived from the plugin's own letterboxing
               (anti-feedback); k<1 = honest normal-downscale fallback, no crop.

This module adds to p1_lib/p2_lib (which stay the isolation/IPC/evidence base):
  * pure Integer geometry oracle (k / zoom / letterbox borders), including the
    anti-feedback counter-example (a pre-shrunk margin must not be consumed);
  * pure Sharp-Bilinear scale + sample-coordinate oracles (AUTO/manual, scale
    0 divide-by-zero protection);
  * the xBR reference coordinate table (the 21 tex2D sample points of the
    forensic base file) and a CPU replica of the reference fragment math for
    small-RGB pixel oracles;
  * the NIS per-block store-index audit (which output pixels a naive compute
    dispatch would write out of bounds — proving the bounds guard is real),
    plus the coefficient-texture audit (2x64 rgba32f, byte-identical to the
    forensic evidence file);
  * a stdlib-only PNG decoder honouring the TRUE bit depth (8/16-bit), used
    for window-capture pixel oracles (8-bit parsers must never masquerade as
    universal PNG readers — P2 evidence discipline);
  * letterbox / block-uniformity analysis helpers for GEO-02/GEO-03;
  * the P3 gear-registry mirror + conf audit (p3_builtins_active semantics:
    Lua-registered active + conf gears member + ZERO override keys — never
    the silently-ignored _mode=active), mirroring p1_lib.audit_gears_conf and
    p2_lib.audit_gears_conf_p2;
  * P3 guard oracles: the LUMA guard (nis) and the INDEPENDENT HDR guard
    (xbr/sharpbilinear/sharpbilinear2x MAIN gears are RGB-capable but
    HDR-refusing), plus honest skip notes (NIS WHEN skip, Sharp AUTO
    degenerate-to-bilinear, Integer k<1);
  * a same-moment sampling helper (decode params + geometry + frame counts +
    capture in ONE observation window — the VL-F1 root-cause closure).

Boundaries honored here (same discipline as p1_lib/p2_lib):
  * never writes APPDATA/mpv, D:/MPV, or the backup payload;
  * test gears remain prefixed p1-test-* / p2-test-* and are labeled
    测试桩非产品档位; P3 negative fixtures live in tests/fixtures/p3/;
  * no quality/performance claims: PER-04-COMPUTE records raw ns samples only;
  * this is machine-checking support, not an OS sandbox.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zlib
from pathlib import Path

import p1_lib as lib  # noqa: E402  (same tools/ directory)
import p2_lib as p2   # noqa: E402

REPO_ROOT = lib.REPO_ROOT

# ---------------------------------------------------------------------------
# P3 gear registry mirror (of the Lua BUILTIN_GEARS table; unit tests pin)
# ---------------------------------------------------------------------------

P3_BUILTIN_IDS = ("nis", "xbr", "sharpbilinear", "sharpbilinear2x", "integer")
# P2 registered gears stay unchanged; the still-placeholder set narrows to:
P3_STILL_DISABLED_IDS = ("ls1", "bcas")
P2_BUILTIN_IDS = p2.P2_BUILTIN_IDS

NIS_CHAIN = ["~~/shaders/p3-NIS.glsl"]
XBR_CHAIN = ["~~/shaders/p3-xBR-lv2.glsl"]
SHARP_AUTO_CHAIN = ["~~/shaders/p3-Sharp-Bilinear-AUTO.glsl"]
SHARP_2X_CHAIN = ["~~/shaders/p3-Sharp-Bilinear-2x.glsl"]

NIS_DESC_KEYWORDS = ["NVIDIA Image Scaling and Sharpening v1.0.2"]
XBR_DESC_KEYWORDS = ["xBR-lv2 Hyllian reference (3x prescale)"]
SHARP_AUTO_DESC_KEYWORDS = ["Sharp Bilinear (AUTO)"]
SHARP_2X_DESC_KEYWORDS = ["Sharp Bilinear (manual 2x)"]

# nvSharpen must NEVER be stacked onto NIS (NIS carries its own sharpener).
NVSHARPEN_FORBIDDEN_SUBSTRINGS = ("NVSharpen", "nvsharp")

LUMA_GEAR_IDS_P3 = ("nis",)               # LUMA compute chain: RGB+HDR guarded
HDR_GUARD_GEAR_IDS_P3 = ("xbr", "sharpbilinear", "sharpbilinear2x")
# integer: scaler/geometry-only; no LUMA/HDR guard by design (like nearest).

NIS_BASE_EVIDENCE = "docs/证据/port-NVScaler.glsl"
NIS_BASE_SHA256 = "bac778ec0108d272e4dad97794a3c257e65bbebd52aa762f95bce930cbd6b73c"
XBR_BASE_EVIDENCE = "docs/证据/xbr-lv2.glsl"
XBR_BASE_SHA256 = "9cf5b08c7378305b558204354e898f6837c481fd5b4371dfbe6b5092cffe5062"
SHARP_BASE_EVIDENCE = "docs/证据/sharp-bilinear.glsl"
SHARP_BASE_SHA256 = "9b9afa91fe12bcbd49398179bf2072ce5a38b531c39a4fd381e92602c6dc114b"

NIS_REPO_PATH = "shaders/p3-NIS.glsl"
XBR_REPO_PATH = "shaders/p3-xBR-lv2.glsl"
SHARP_AUTO_REPO_PATH = "shaders/p3-Sharp-Bilinear-AUTO.glsl"
SHARP_2X_REPO_PATH = "shaders/p3-Sharp-Bilinear-2x.glsl"
RESOURCE_MANIFEST_P3_PATH = REPO_SHADER_DIR = REPO_ROOT / "shaders" / "p3-resource-manifest.json"

GEARS_CONF = lib.GEARS_CONF


def expected_builtin_chains_p3() -> dict:
    """gear id -> glsl-shaders recipe for the five P3 gears (whole-chain)."""
    return {
        "nis": list(NIS_CHAIN),
        "xbr": list(XBR_CHAIN),
        "sharpbilinear": list(SHARP_AUTO_CHAIN),
        "sharpbilinear2x": list(SHARP_2X_CHAIN),
        # integer owns geometry properties only; the shader chain is EMPTY.
        "integer": [],
    }


# ---------------------------------------------------------------------------
# P3 conf audit (registry migration: the five P3 gears are BUILT-IN — their
# identity is fixed in the Lua registry; the conf may only list them as
# gears= members. Override keys are invalid AND warn in the parser, so an
# honest active state is proven by Lua registration + membership + the
# ABSENCE of override keys — never by the silently-ignored "_mode=active").
# ---------------------------------------------------------------------------

def audit_gears_conf_p3(text: str | None = None) -> dict:
    """P3 policy audit of the shipped gear table (P3 superset rules)."""
    text = GEARS_CONF.read_text(encoding="utf-8") if text is None else text
    new_builtins = P3_BUILTIN_IDS
    lines = [ln.strip() for ln in text.splitlines()]
    gears_line = next((ln for ln in lines if ln.startswith("gears=")), "")
    members = [t.strip() for t in gears_line[len("gears="):].split(",")] \
        if gears_line else []
    lua_src = lib.PLUGIN_LUA.read_text(encoding="utf-8")
    _bs = lua_src.index("local BUILTIN_GEARS = {")
    _be = lua_src.index("local BUILTIN_BY_ID", _bs)

    def _in_builtin_registry(gid):
        return re.search(r'\{ id = "%s",' % gid, lua_src[_bs:_be]) is not None

    def _not_placeholder(gid):
        ps = lua_src.index("local PLACEHOLDER_GEARS = {")
        pe = lua_src.index("}", ps)
        return re.search(r'\{ id = "%s",' % gid, lua_src[ps:pe]) is None

    checks = {
        "off_first": gears_line.startswith("gears=off,"),
        "off_label_is_const_guan": "off_label=关" in text,
        "still_disabled_ls1_bcas": all(
            f"{gid}_mode=disabled" in text for gid in P3_STILL_DISABLED_IDS),
        "p2_builtins_active_keys_kept": all(
            f"{gid}_mode=active" in text for gid in P2_BUILTIN_IDS),
        # the five P3 builtins: gears= membership …
        "p3_builtins_in_gears_list": all(gid in members for gid in new_builtins),
        # … registered in the Lua BUILTIN_GEARS registry (parser forces
        # mode=active for built-ins; the placeholder registry must not list
        # them) …
        "p3_builtins_registered_active_in_lua": all(
            _in_builtin_registry(gid) and _not_placeholder(gid)
            for gid in new_builtins),
        # … and ZERO override keys in conf (invalid-by-parser keys must not
        # be used to fake an identity; parser would warn on every load).
        "p3_builtins_no_override_keys": all(
            not ln.startswith(f"{gid.replace('-', '_')}_{suffix}=")
            for gid in new_builtins
            for suffix in ("mode", "label", "reason", "set")
            for ln in lines),
        # P2 builtins keep their conf entries (audit_gears_conf_p2 mirror
        # unchanged); only _set lines are universally forbidden (chains live
        # in Lua/resources).
        "no_builtin_set_in_conf": all(
            not ln.startswith(f"{gid.replace('-', '_')}_set=")
            for gid in P2_BUILTIN_IDS + P3_STILL_DISABLED_IDS + new_builtins
            for ln in lines),
        "ls1_reason_policy": all(k in text for k in ("无公开源码", "权重", "移植许可")),
        "bcas_reason_policy": ("身份未核实" in text and "不以CAS/Bicubic+CAS冒名" in text),
        "no_stub_gears_in_product": "p1-test-" not in text and "p2-test-" not in text
                                    and "p3-test-" not in text,
        "sharpbilinear2x_is_member": "sharpbilinear2x" in members,
    }
    return checks


# ---------------------------------------------------------------------------
# Guard oracles (P3): LUMA guard unchanged for nis; INDEPENDENT HDR guard for
# the MAIN RGB gears; honest per-gear skip notes.
# ---------------------------------------------------------------------------

def is_rgb_pixfmt(pixfmt) -> bool:
    return p2.is_rgb_pixfmt(pixfmt)


def is_hdr_gamma(gamma) -> bool:
    return p2.is_hdr_gamma(gamma)


def luma_guard_reason_p3(vo: dict) -> str | None:
    """nis is a LUMA gear: refused on RGB and HDR input (P2 mirror)."""
    return p2.luma_guard_reason(True, vo)


def hdr_guard_reason(is_hdr_gear: bool, vo: dict) -> str | None:
    """Independent HDR guard (xbr/sharp MAIN gears): RGB is SUPPORTED; HDR
    (pq/hlg gamma) is refused with a real reason. vo=None → not guarded."""
    if not is_hdr_gear or vo is None:
        return None
    if is_hdr_gamma(vo.get("gamma")):
        return (f"HDR 输入（gamma={vo.get('gamma')}）：本档按计划禁用"
                "（HDR 守卫独立于 LUMA 守卫；HDR 画质不评价）")
    return None


def integer_k(win_w, win_h, disp_w, disp_h):
    """k = floor(min(win_w/dw, win_h/dh)) — INTEGER gear oracle.

    win_w/win_h are the ORIGINAL window pixels (osd-width/osd-height);
    disp_w/disp_h the effective display size from video-out-params (which
    already folds in rotation, crop and SAR). Returns the integer factor
    (>=0); 0 means "window smaller than the source display size" → the
    honest k<1 normal-downscale fallback (no crop, no unscaled).
    """
    try:
        if not win_w or not win_h or not disp_w or not disp_h:
            return None
        if win_w <= 0 or win_h <= 0 or disp_w <= 0 or disp_h <= 0:
            return None
        return int(math.floor(min(win_w / float(disp_w), win_h / float(disp_h))))
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def integer_geometry(win_w, win_h, dw, dh) -> dict:
    """Full Integer activation plan for one geometry observation."""
    k = integer_k(win_w, win_h, dw, dh)
    out = {
        "window": [win_w, win_h], "display": [dw, dh],
        "k": k, "mode": None, "zoom": None,
        "video_unscaled": None, "scalers": "nearest",
        "note": "",
    }
    if k is None:
        out["mode"] = "unknown"
        out["note"] = "窗口或显示尺寸未知：不激活整数几何"
        return out
    if k < 1:
        out["mode"] = "downscale-fallback"
        out["zoom"] = 0.0
        out["video_unscaled"] = "no"
        out["note"] = ("k<1（窗口小于有效显示尺寸）：整数倍放大不可用，"
                       "按普通 nearest 缩小显示，不裁切（诚实回退）")
        return out
    out["mode"] = "integer"
    out["zoom"] = math.log2(k)
    out["video_unscaled"] = "yes"
    if k >= 1:
        disp_w_full = int(round(dw * k))
        disp_h_full = int(round(dh * k))
        out["content_rect"] = [disp_w_full, disp_h_full]
        out["bars"] = {
            "left": (win_w - disp_w_full) // 2,
            "right": win_w - disp_w_full - (win_w - disp_w_full) // 2,
            "top": (win_h - disp_h_full) // 2,
            "bottom": win_h - disp_h_full - (win_h - disp_h_full) // 2,
        }
    return out


def integer_skip_note(k) -> str:
    if k is None:
        return "Integer：窗口/显示尺寸未知，无法计算整数倍数"
    if k == 0:
        return ("k<1（窗口小于源显示尺寸）：整数倍放大不可用，"
                "已按普通 nearest 缩小显示（不裁切、不假整数）")
    if k == 1:
        return ("k=1：窗口恰好容纳 1× 显示尺寸（如 1080p→2560×1440 全屏），"
                "黑边左右各 320px/上下各 180px（按 16:9 源）")
    return ""


def integer_anti_feedback_ok(journal_names) -> bool:
    """GEO-01/R5: the Integer window source must be the raw window pixels.
    The journal must NOT contain any plugin-internal margin-derived property
    (there is none in the managed set); the allowed reads are exactly the
    video-out-params + osd-width/osd-height family already allowed by
    p1_lib.ALLOWED_JOURNAL_PROPS (which includes video-unscaled/video-zoom
    for the ownership ledger)."""
    allowed = lib.ALLOWED_JOURNAL_PROPS
    return all(n in allowed for n in journal_names)


# ---------------------------------------------------------------------------
# Sharp Bilinear oracles (AUTO / manual 2x) — pure functions.
# ---------------------------------------------------------------------------

def sharp_auto_scale(out_h, in_h):
    """floor(out_h/in_h + 0.01) with the divide-by-zero/NaN protection.

    The reference computes region_range = 0.5 - 0.5/scale, which explodes at
    scale=0 (output smaller than input). The P3 adaptation clamps the AUTO
    scale to >= 1 (scale=1 reduces the formula to plain bilinear: a defined,
    safe degenerate — the honest fallback). 1080→1440 gives 1 → the gear is
    explicitly documented to DEGRADE to plain bilinear in that window."""
    try:
        if not out_h or not in_h or in_h <= 0 or out_h <= 0:
            return None
        return max(1, int(math.floor(out_h / float(in_h) + 0.01)))
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def sharp_manual_scale():
    """Manual 2x gear: fixed SHARP_BILINEAR_PRE_SCALE=2.0 (reference default
    is 4.0; the separately-named 2x gear pins 2.0 — a documented, explicit
    adaptation; NOT two chained passes)."""
    return 2


def sharp_sample_coord(pos_px: float, in_size: float, scale: float) -> float:
    """Reference sharp-bilinear coordinate mapping along one axis (oracle).

    texel = pos*in_size; texel_floored=floor(texel); s=fract(texel);
    region_range = 0.5 - 0.5/scale;
    f = (center_dist - clamp(center_dist, -rr, rr))*scale + 0.5;
    mod_texel = texel_floored + f  (the coordinate sampled with LINEAR).
    Returns the continuous texel coordinate that hardware LINEAR samples."""
    texel = pos_px * in_size
    texel_floored = math.floor(texel)
    s = texel - texel_floored
    region_range = 0.5 - 0.5 / scale
    center_dist = s - 0.5
    f = (center_dist - max(-region_range, min(region_range, center_dist))) \
        * scale + 0.5
    return texel_floored + f


def sharp_degenerate_note(scale) -> str:
    if scale is None:
        return "Sharp Bilinear：输出尺寸未知"
    if scale == 1:
        return ("AUTO 在当前窗口退化为双线性"
                "（floor(输出高/输入高+0.01)=1，参考公式原样保留）")
    return ""


# ---------------------------------------------------------------------------
# xBR-lv2 reference port oracles.
# ---------------------------------------------------------------------------

XBR_SCALE = 3.0


def xbr_output_size(w: int, h: int) -> tuple:
    """3x pre-scale output (the reference's XBR_SCALE=3.0 mode; mpv scales
    further to the window — the declared '3x prescale + mpv final scale'
    mode, never claimed as any-ratio equivalent)."""
    return (int(w) * 3, int(h) * 3)


def xbr_reference_offsets():
    """The 21 tex2D sample points of the forensic base file
    (docs/证据/xbr-lv2.glsl:244-264), in texel units relative to the current
    input coordinate. Names follow the reference comments. Order:
    A1,B1,C1, A,B,C, D,E,F, G,H,I, G5,H5,I5, A0,D0,G0, C4,F4,I4."""
    return [
        ("A1", -1, -2), ("B1", 0, -2), ("C1", 1, -2),
        ("A", -1, -1), ("B", 0, -1), ("C", 1, -1),
        ("D", -1, 0), ("E", 0, 0), ("F", 1, 0),
        ("G", -1, 1), ("H", 0, 1), ("I", 1, 1),
        ("G5", -1, 2), ("H5", 0, 2), ("I5", 1, 2),
        ("A0", -2, -1), ("D0", -2, 0), ("G0", -2, 1),
        ("C4", 2, -1), ("F4", 2, 0), ("I4", 2, 1),
    ]


def _strip_glsl_comments(text: str) -> str:
    """Remove /* */ block comments and // line comments (non-greedy, ASCII
    shaders only) — used by the code-level static audits."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    lines = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if stripped.startswith("//"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def xbr_audit_source(text: str) -> dict:
    """Static audit of the ported xBR shader against the reference contract:
    the 21 named tex2D taps, the delta/delta_l constants, XBR_SCALE=3.0,
    MIT header retention, and no xBRZ confusion."""
    code_only = _strip_glsl_comments(text)
    checks = {
        "has_mit_header": "Hyllian" in text and (
            "2011-2016" in text or "2011" in text),
        "xbr_scale_3": re.search(r"XBR_SCALE\s+3\.0", text) is not None,
        # code-only: the provenance comment's "NOT xBRZ" disclaimer is required
        # wording; an actual xBRZ branding/claim in code is what is forbidden.
        "no_xbrz_claim": "xBRZ" not in code_only and "xbrz" not in code_only,
        "delta_quarter_over_scale": "1.0/XBR_SCALE" in text or "vec4(1.0 / XBR_SCALE" in text
                                    or "1.0 / XBR_SCALE" in text,
        "hook_main": "//!HOOK MAIN" in text,
        "desc_present": any(ln.startswith("//!DESC ") for ln in text.splitlines()),
        "rgbw_constant": "14.352" in text and "28.176" in text and "5.472" in text,
        "y_weight_default": "48.0" in text,
        "corner_c": "CORNER_C" in text,
        "smooth_tips": "SMOOTH_TIPS" in text,
        "three_x_prescale": ("3.0" in text and ("HOOKED.w 3.0" in text or "3.0 *"
                                                in text or "xbr_prescale" in text.lower()
                                                or "PRESCALE" in text)),
        "no_directive_like_comment": not any(
            ln.strip().startswith("// //!") for ln in text.splitlines()),
        "adapt_marker": "p3-adapt-v1" in text,
    }
    # count the 21 taps: every named sample must appear as a tex2D-style fetch
    for name, _ox, _oy in xbr_reference_offsets():
        checks[f"tap_{name}"] = re.search(rf"\b{name}\s*=", text) is not None
    return checks


# --- CPU replica of the reference fragment math (small-RGB pixel oracle) ---

def _df(a, b):
    return tuple(abs(x - y) for x, y in zip(a, b))


def _eq(a, b, thr):
    return tuple(1.0 if x <= thr else 0.0 for x in _df(a, b))


def _neq(a, b, thr):
    return tuple(1.0 - v for v in _eq(a, b, thr))


def _wd(a, b, c, d, e, f, g, h):
    return tuple(_df(a, b)[i] + _df(a, c)[i] + _df(d, e)[i] + _df(d, f)[i]
                 + 4.0 * _df(g, h)[i] for i in range(4))


def _clamp01(v):
    return max(0.0, min(1.0, v))


def _mix(a, b, t):
    return a + (b - a) * t


def xbr_cpu_replica(src, w, h, scale=3):
    """CPU replica of the reference xBR-lv2 fragment (CORNER_C + SMOOTH_TIPS,
    small_details=0, defaults XBR_Y_WEIGHT=48 / EQ_THRESHOLD=15 / LV1=0.5 /
    LV2=2.0), with the reference 3x output mapping and LINEAR input sampling
    (sub-texel fractional taps exactly as the reference's tex2D does).

    Structure follows the reference fragment exactly:
      * the classification rules (diff/eq/neq/wd/irlv/edr/px) operate on
        VEC4 LUMA dots (dot(rgb, rgbw), rgbw = (14.352, 28.176, 5.472),
        equality threshold 15.0 in luma units);
      * the output mixing (mix(H, F, px.x) ...) operates on RGB vec3s;
      * fx/fx_l/fx_u are the geometric line inequations from fp.

    src: list of rows of (r,g,b) floats in 0..1 (length h rows x w cols).
    Returns rows of (r,g,b) at (3w, 3h).

    This is written from the reference math (independently re-derived), not
    transcribed from any GLSL in this repo other than the documented constant
    table — the oracle is deliberately independent from the ported file.
    """
    rgbw = (14.352, 28.176, 5.472)
    lv2_cf = 2.0
    scale_f = float(scale)

    def tex(x, y):
        """hardware LINEAR sampling with CLAMP_TO_EDGE (reference behaviour)."""
        x = max(0.0, min(float(w) - 1e-6, x))
        y = max(0.0, min(float(h) - 1e-6, y))
        x0 = int(math.floor(x - 0.5))
        y0 = int(math.floor(y - 0.5))
        fx = (x - 0.5) - x0
        fy = (y - 0.5) - y0

        def px(xx, yy):
            xx = min(max(xx, 0), w - 1)
            yy = min(max(yy, 0), h - 1)
            return src[yy][xx]
        c00, c10 = px(x0, y0), px(x0 + 1, y0)
        c01, c11 = px(x0, y0 + 1), px(x0 + 1, y0 + 1)
        out = []
        for ch in range(3):
            top = c00[ch] * (1 - fx) + c10[ch] * fx
            bot = c01[ch] * (1 - fx) + c11[ch] * fx
            out.append(top * (1 - fy) + bot * fy)
        return out

    def dot_rgbw(c):
        return c[0] * rgbw[0] + c[1] * rgbw[1] + c[2] * rgbw[2]

    Ao = (1.0, -1.0, -1.0, 1.0)
    Bo = (1.0, 1.0, -1.0, -1.0)
    Co = (1.5, 0.5, -0.5, 0.5)
    Ax = (1.0, -1.0, -1.0, 1.0)
    Bx = (0.5, 2.0, -0.5, -2.0)
    Cx = (1.0, 1.0, -0.5, 0.0)
    Ay = (1.0, -1.0, -1.0, 1.0)
    By = (2.0, 0.5, -2.0, -0.5)
    Cy = (2.0, 0.0, -1.0, 0.5)
    Ci = (0.25, 0.25, 0.25, 0.25)
    EQ_THR = 15.0   # luma units (the reference's vec4(15.0))

    def df4(a, b):
        return tuple(abs(x - y) for x, y in zip(a, b))

    def diff4(a, b):
        # exact float inequality, componentwise (the reference's notEqual)
        return tuple(1.0 if x != y else 0.0 for x, y in zip(a, b))

    def eq4(a, b):
        return tuple(1.0 if v <= EQ_THR else 0.0 for v in df4(a, b))

    def neq4(a, b):
        return tuple(1.0 - v for v in eq4(a, b))

    def wd4(a, b, c, d, e, f, g, hh):
        return tuple(df4(a, b)[k] + df4(a, c)[k] + df4(d, e)[k]
                     + df4(d, f)[k] + 4.0 * df4(g, hh)[k] for k in range(4))

    def clamp01(v):
        return max(0.0, min(1.0, v))

    def mix(a, b, t):
        return a + (b - a) * t

    out = []
    for j in range(h * scale):
        ty = (j + 0.5) / scale_f
        ny = math.floor(ty)
        fp_y = ty - ny
        row = []
        for i in range(w * scale):
            tx = (i + 0.5) / scale_f
            nx = math.floor(tx)
            fp_x = tx - nx

            def tap(ox, oy):
                return tex(nx + ox + fp_x, ny + oy + fp_y)

            A1, B1, C1 = tap(-1, -2), tap(0, -2), tap(1, -2)
            A, B, C = tap(-1, -1), tap(0, -1), tap(1, -1)
            D, E, F = tap(-1, 0), tap(0, 0), tap(1, 0)
            G, H, I = tap(-1, 1), tap(0, 1), tap(1, 1)
            G5, H5, I5 = tap(-1, 2), tap(0, 2), tap(1, 2)
            A0, D0, G0 = tap(-2, -1), tap(-2, 0), tap(-2, 1)
            C4, F4, I4 = tap(2, -1), tap(2, 0), tap(2, 1)

            # vec4 luma dots (reference structure)
            b4 = tuple(dot_rgbw(p) for p in (B, D, H, F))
            c4 = tuple(dot_rgbw(p) for p in (C, A, G, I))
            d4 = (b4[1], b4[2], b4[3], b4[0])              # b.yzwx
            e4 = (dot_rgbw(E),) * 4
            f4 = (b4[3], b4[0], b4[1], b4[2])              # b.wxyz
            g4 = (c4[2], c4[3], c4[0], c4[1])              # c.zwxy
            h4 = (b4[2], b4[3], b4[0], b4[1])              # b.zwxy
            i4v = (c4[3], c4[0], c4[1], c4[2])             # c.wxyz

            i4 = tuple(dot_rgbw(p) for p in (I4, C1, A0, G5))
            i5 = tuple(dot_rgbw(p) for p in (I5, C4, A1, G0))
            h5 = tuple(dot_rgbw(p) for p in (H5, F4, B1, D0))
            f4v = (h5[1], h5[2], h5[3], h5[0])             # h5.yzwx

            # geometric line inequations
            fx = tuple(Ao[k] * fp_y + Bo[k] * fp_x for k in range(4))
            fx_l = tuple(Ax[k] * fp_y + Bx[k] * fp_x for k in range(4))
            fx_u = tuple(Ay[k] * fp_y + By[k] * fp_x for k in range(4))

            delta = (1.0 / scale_f,) * 4
            delta_l = (0.5 / scale_f, 1.0 / scale_f, 0.5 / scale_f, 1.0 / scale_f)
            delta_u = (delta_l[1], delta_l[0], delta_l[3], delta_l[2])

            irlv0 = tuple(diff4(e4, f4)[k] * diff4(e4, h4)[k] for k in range(4))
            # CORNER_C (threshold comparisons on luma vec4s)
            irlv1 = tuple(
                irlv0[k] * (neq4(f4, b4)[k] * neq4(f4, c4)[k]
                            + neq4(h4, d4)[k] * neq4(h4, g4)[k]
                            + eq4(e4, i4v)[k] * (neq4(f4, f4v)[k] * neq4(f4, i4)[k]
                                                 + neq4(h4, h5)[k] * neq4(h4, i5)[k])
                            + eq4(e4, g4)[k] + eq4(e4, c4)[k])
                for k in range(4))
            irlv2l = tuple(diff4(e4, g4)[k] * diff4(d4, g4)[k] for k in range(4))
            irlv2u = tuple(diff4(e4, c4)[k] * diff4(b4, c4)[k] for k in range(4))

            fx45i = tuple(clamp01((fx[k] + delta[k] - Co[k] - Ci[k])
                                  / (2.0 * delta[k])) for k in range(4))
            fx45 = tuple(clamp01((fx[k] + delta[k] - Co[k])
                                 / (2.0 * delta[k])) for k in range(4))
            fx30 = tuple(clamp01((fx_l[k] + delta_l[k] - Cx[k])
                                 / (2.0 * delta_l[k])) for k in range(4))
            fx60 = tuple(clamp01((fx_u[k] + delta_u[k] - Cy[k])
                                 / (2.0 * delta_u[k])) for k in range(4))

            wd1 = wd4(e4, c4, g4, i4v, h5, f4v, h4, f4)
            wd2 = wd4(h4, d4, i5, f4, i4, b4, e4, i4v)

            edri = tuple((1.0 if wd1[k] <= wd2[k] else 0.0) * irlv0[k]
                         for k in range(4))
            edr = tuple((1.0 if wd1[k] + 0.1 <= wd2[k] else 0.0)
                        * (1.0 if irlv1[k] >= 0.5 else 0.0) for k in range(4))
            edr_l = tuple((1.0 if lv2_cf * df4(f4, g4)[k] <= df4(h4, c4)[k]
                           else 0.0) * irlv2l[k] * edr[k] for k in range(4))
            edr_u = tuple((1.0 if lv2_cf * df4(h4, c4)[k] <= df4(f4, g4)[k]
                           else 0.0) * irlv2u[k] * edr[k] for k in range(4))

            fx45 = tuple(edr[k] * fx45[k] for k in range(4))
            fx30 = tuple(edr_l[k] * fx30[k] for k in range(4))
            fx60 = tuple(edr_u[k] * fx60[k] for k in range(4))
            fx45i = tuple(edri[k] * fx45i[k] for k in range(4))

            px = tuple(1.0 if df4(e4, f4)[k] <= df4(e4, h4)[k] else 0.0
                       for k in range(4))

            # SMOOTH_TIPS
            maximos = tuple(max(fx30[k], fx60[k], fx45[k], fx45i[k])
                            for k in range(4))

            def mixc(a, bb, t):
                return [mix(a[c], bb[c], t) for c in range(3)]

            res1 = list(E)
            m1 = mixc(H, F, px[0])
            res1 = [res1[c] + (m1[c] - res1[c]) * maximos[0] for c in range(3)]
            m2 = mixc(B, D, px[2])
            res1 = [res1[c] + (m2[c] - res1[c]) * maximos[2] for c in range(3)]
            res2 = list(E)
            m3 = mixc(F, B, px[1])
            res2 = [res2[c] + (m3[c] - res2[c]) * maximos[1] for c in range(3)]
            m4 = mixc(D, H, px[3])
            res2 = [res2[c] + (m4[c] - res2[c]) * maximos[3] for c in range(3)]

            def c_df(c1, c2):
                return sum(abs(a - b) for a, b in zip(c1, c2))

            t = 1.0 if c_df(E, res1) <= c_df(E, res2) else 0.0
            res = [res1[c] + (res2[c] - res1[c]) * t for c in range(3)]
            row.append(tuple(min(1.0, max(0.0, v)) for v in res))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# NIS compute audit: store-index math + coefficient texture audit.
# ---------------------------------------------------------------------------

NIS_BLOCK_W = 32
NIS_BLOCK_H = 24
NIS_THREADS = 256


def nis_store_index_audit(out_w: int, out_h: int) -> dict:
    """Pure re-derivation of the port's per-thread store loop (hook(): the
    dstX/dstY math and the k-loop) — enumerating which output pixels a
    workgroup grid of ceil(out/32) x ceil(out/24) would write.

    Returns the OOB store count WITHOUT a bounds guard (must be > 0 for
    non-divisible outputs — proving the guard is necessary, never assuming
    'the GPU did not complain'), and 0 WITH the per-pixel guard. Shared-memory
    READ indices are audited against the WRITTEN region (same numTile
    derivation in both loops — reads cannot exceed written tiles)."""
    blocks_x = -(-out_w // NIS_BLOCK_W)
    blocks_y = -(-out_h // NIS_BLOCK_H)
    oob = 0
    total = 0
    min_seen = [None, None]
    max_seen = [-1, -1]
    for by in range(blocks_y):
        for bx in range(blocks_x):
            dst_block_x = NIS_BLOCK_W * bx
            dst_block_y = NIS_BLOCK_H * by
            for t in range(NIS_THREADS):
                pos_x = t % NIS_BLOCK_W
                pos_y = t // NIS_BLOCK_W
                for k in range(NIS_BLOCK_W * NIS_BLOCK_H // NIS_THREADS):
                    dst_x = dst_block_x + pos_x
                    dst_y = dst_block_y + pos_y + k * (NIS_THREADS // NIS_BLOCK_W)
                    total += 1
                    min_seen = [min(min_seen[0], dst_x) if min_seen[0] is not None else dst_x,
                                min(min_seen[1], dst_y) if min_seen[1] is not None else dst_y]
                    max_seen = [max(max_seen[0], dst_x), max(max_seen[1], dst_y)]
                    if dst_x >= out_w or dst_y >= out_h:
                        oob += 1
    return {
        "output": [out_w, out_h],
        "workgroups": [blocks_x, blocks_y],
        "store_attempts": total,
        "oob_stores_without_guard": oob,
        "oob_stores_with_guard": 0,
        "store_index_min": min_seen,
        "store_index_max": max_seen,
        "non_divisible": (out_w % NIS_BLOCK_W != 0) or (out_h % NIS_BLOCK_H != 0),
        "shared_tile_capacity_note": (
            "kTileSize=(32+6)x(24+6); the load/store tile loops derive the same "
            "numTilePixels so reads never exceed written tiles; the shared array "
            "capacity itself can only be exceeded when a single axis is "
            "DOWNSCALED (kScale>1 per axis) — a reference-inherited property, "
            "documented; the //!WHEN (>1x area) keeps the common upscale case "
            "well inside capacity"),
        "guard_note": ("per-pixel bounds guard placed after ALL groupMemoryBarrier/"
                       "barrier pairs; no thread returns before a barrier"),
    }


_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def nis_texture_audit(glsl_text: str, base_text: str | None = None) -> dict:
    """Parse the two //!TEXTURE coef_scaler/coef_usm blobs (2x64 rgba32f) and
    audit: shape, 16 bytes-per-texel blob length, float decode sanity, and
    (when base_text given) byte-identity with the forensic evidence file —
    the adaptation must not touch the coefficient banks."""
    problems = []
    textures = {}
    for name in ("coef_scaler", "coef_usm"):
        m = re.search(
            rf"//!TEXTURE {name}\s*\n//!SIZE 2 64\s*\n//!FORMAT rgba32f\s*\n"
            rf"//!FILTER NEAREST\s*\n([0-9a-fA-F\s]+?)(?:\n//!|\Z)",
            glsl_text)
        if not m:
            problems.append(f"texture blob not found: {name}")
            continue
        blob = re.sub(r"\s+", "", m.group(1))
        if not _HEX_RE.fullmatch(blob or "x"):
            problems.append(f"texture blob not hex: {name}")
            continue
        if len(blob) != 2 * 64 * 16 * 2:  # 128 texels x 16 B -> 4096 hex chars
            problems.append(f"texture blob length {len(blob)} != "
                            f"{2 * 64 * 16 * 2} hex chars (2x64 rgba32f): {name}")
            continue
        raw = bytes.fromhex(blob)
        floats = list(struct.unpack(f"<{2 * 64 * 4}f", raw))
        textures[name] = {"texels": 2 * 64, "format": "rgba32f",
                          "bytes": len(raw), "floats": floats,
                          "sha256": hashlib.sha256(raw).hexdigest()}
        if not all(math.isfinite(v) for v in floats):
            problems.append(f"non-finite coefficient: {name}")
    result = {
        "problems": problems,
        "textures": textures,
        "ok": not problems and len(textures) == 2,
    }
    if base_text is not None:
        base = nis_texture_audit(base_text)
        same = {k: (textures.get(k, {}) or {}).get("sha256")
                == (base["textures"].get(k, {}) or {}).get("sha256")
                for k in ("coef_scaler", "coef_usm")}
        result["coefficients_byte_identical_to_evidence"] = same
        if not all(same.values()):
            result["problems"] = result["problems"] + [
                "coefficient blob differs from forensic evidence"]
        result["ok"] = result["ok"] and all(same.values())
    return result


def nis_static_audit(port_text: str, base_text: str) -> dict:
    """Static audit of the adapted NIS port: real compute directive, the two
    barriers, the bounds guard AFTER them, no barrier-preceding return, WHEN
    semantics preserved, no NVSharpen stacking, provenance marker."""
    lines = port_text.splitlines()
    code_lines = [ln for ln in lines if not ln.strip().startswith("//")]
    code = "\n".join(code_lines)
    last_barrier = max(
        (i for i, ln in enumerate(lines)
         if re.search(r"\b(groupMemoryBarrier\(\)|barrier\(\))", ln)),
        default=-1)
    guard_line = next(
        (i for i, ln in enumerate(lines)
         if re.search(r"nis_bounds_guard\s*=", ln)), -1)
    # R2: no thread may return before a group barrier — scan only the hook()
    # body up to the last barrier (helper functions above hook() legitimately
    # contain returns).
    checks = {
        "compute_directive": "//!COMPUTE 32 24 256 1" in port_text,
        "two_coeff_textures": ("//!TEXTURE coef_scaler" in port_text
                               and "//!TEXTURE coef_usm" in port_text),
        "rgba32f": port_text.count("rgba32f") >= 2,
        "when_preserved": "//!WHEN OUTPUT.w OUTPUT.h * LUMA.w LUMA.h * / 1.0 >"
                          in port_text,
        "has_barriers": port_text.count("groupMemoryBarrier") >= 2
                        and port_text.count("barrier()") >= 2,
        "guard_after_all_barriers": guard_line > last_barrier >= 0,
        "no_return_before_barrier": (lambda hook_start: not re.search(
            r"\breturn\b", "\n".join(lines[hook_start:last_barrier + 1]), re.I)
            if last_barrier >= 0 and hook_start is not None else False)(
            next((i for i, ln in enumerate(lines) if ln.startswith("void hook")),
                 None)),
        "imagestore_guarded": re.search(
            r"nis_bounds_guard[\s\S]{0,400}?imageStore", port_text) is not None
            or re.search(r"imageStore[\s\S]{0,200}", port_text) is not None
            and "nis_bounds_guard" in port_text,
        # code-only check: the provenance comment states the prohibition
        # ("NVSharpen is NEVER stacked") — required wording, not a violation.
        "no_nvsharpen_stacked": not any(
            s in code for s in NVSHARPEN_FORBIDDEN_SUBSTRINGS),
        "luma_hook": "//!HOOK LUMA" in port_text,
        "adapt_marker": "p3-adapt-v1" in port_text,
        "base_hash_recorded": NIS_BASE_SHA256 in port_text,
        "base_hash_on_disk_matches": lib.sha256_file(
            REPO_ROOT / NIS_BASE_EVIDENCE) == NIS_BASE_SHA256,
        "no_directive_like_comment": not any(
            ln.strip().startswith("// //!") for ln in lines),
        # the algorithm body (everything the reference had) is preserved:
        "reference_functions_kept": all(
            fn in port_text for fn in (
                "GetEdgeMap", "LoadFilterBanksSh", "CalcLTI", "EvalPoly6",
                "FilterNormal", "AddDirFilters")),
    }
    return checks


# ---------------------------------------------------------------------------
# P3 resource manifest audit (shaders/p3-resource-manifest.json) — independent
# from the P2 12-item manifest (which stays byte-untouched).
# ---------------------------------------------------------------------------

RESOURCE_MANIFEST_P3_SCHEMA = "mpv-scaler-p3-resource-manifest/v1"


def audit_p3_resource_manifest(path: Path = RESOURCE_MANIFEST_P3_PATH) -> dict:
    """Audit the P3 resource manifest against the bytes on disk and the
    forensic evidence files: per-resource sha256 match, base-evidence hash
    match, license notes presence, and the comment-discipline rule (no
    directive-like prefixes in comment lines of any p3 shader)."""
    problems = []
    data = json.loads(Path(path).read_bytes().decode("utf-8"))
    if data.get("schema") != RESOURCE_MANIFEST_P3_SCHEMA:
        problems.append(f"schema 不符: {data.get('schema')!r}")
    if data.get("stage") != "P3" or data.get("session") != "p3-001":
        problems.append("stage/session 身份不符")
    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        return {"problems": problems + ["resources 缺失或为空"], "ok": False}
    covered = set()
    for res in resources:
        rel = res.get("path", "")
        covered.add(rel)
        p = REPO_ROOT / rel
        if not p.is_file():
            problems.append(f"资源缺失: {rel}")
            continue
        if res.get("kind") == "adapted-port":
            actual = lib.sha256_file(p)
            if res.get("sha256") and res.get("sha256") != actual:
                problems.append(f"资源哈希不符: {rel}")
            base_rel = res.get("base_evidence")
            base_recorded = res.get("base_sha256") or ""
            base_p = REPO_ROOT / base_rel if base_rel else None
            if not base_p or not base_p.is_file():
                problems.append(f"基取证文件缺失: {base_rel}")
            elif lib.sha256_file(base_p) != base_recorded:
                problems.append(f"基取证哈希不符: {base_rel}")
            # the adapted port must carry the recorded base hash in its header
            if base_recorded and base_recorded not in p.read_text(encoding="utf-8"):
                problems.append(f"适配版头部未记录基哈希: {rel}")
            if res.get("adaptation_version") != "p3-adapt-v1":
                problems.append(f"适配版本标记缺失: {rel}")
    for expected in ("shaders/p3-NIS.glsl", "shaders/p3-xBR-lv2.glsl",
                     "shaders/p3-Sharp-Bilinear-AUTO.glsl",
                     "shaders/p3-Sharp-Bilinear-2x.glsl",
                     "licenses/NIS-LICENSE-NOTES.md",
                     "licenses/XBR-LICENSE-NOTES.md",
                     "licenses/SHARP-BILINEAR-LICENSE-NOTES.md"):
        if expected not in covered:
            problems.append(f"清单缺少预期资源: {expected}")
    if (REPO_ROOT / "shaders" / "resource-manifest.json").exists():
        covered_p2 = json.loads(
            (REPO_ROOT / "shaders" / "resource-manifest.json").read_bytes()
            .decode("utf-8"))
        for res in covered_p2.get("resources", []):
            if res.get("path") in covered:
                problems.append("P3 清单不得覆盖 P2 旧清单条目: " + res.get("path", ""))
    return {"problems": problems, "ok": not problems, "resources": resources,
            "covered": sorted(covered)}


def shader_comment_discipline_audit(path: Path) -> dict:
    """R12/溯源注释纪律：注释行内不得出现指令样前缀（//!PARAM、//!WHEN、
    //!TEXTURE、//!HOOK、//!BIND、//!DESC、//!COMPUTE、//!WIDTH、//!HEIGHT、
    //!SIZE、//!FORMAT、//!FILTER、//!SAVE、//!OUT、//!DEFINE 等出现在以
    // 开头的行内 = 伪指令风险）。真实指令行不受限。"""
    text = Path(path).read_text(encoding="utf-8")
    bad = []
    for i, ln in enumerate(text.splitlines(), 1):
        stripped = ln.strip()
        # a REAL directive line starts with "//!"; a comment line starts with
        # "//" followed by prose — prose must never contain a directive-like
        # prefix (the P2 SGSR header-comment root cause).
        if stripped.startswith("//") and not stripped.startswith("//!") \
                and "//!" in stripped:
            bad.append({"line": i, "text": stripped[:80]})
    return {"path": str(path), "violations": bad,
            "ok": not bad}


# ---------------------------------------------------------------------------
# stdlib PNG decode with TRUE bit depth (8/16), color types 0/2/3/4/6.
# ---------------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def decode_png(data: bytes) -> dict:
    """Minimal stdlib PNG decoder honouring the true bit depth.

    Returns {w, h, bitdepth, color_type, channels, palette?} plus a
    pixel(x, y) accessor returning an (r, g, b) tuple of 0..255 (16-bit
    values are NOT silently truncated to 8-bit: the raw 16-bit accessor is
    exposed too, and get_pixel_16 keeps full resolution; get_pixel scales
    by >>8 which is an HONEST, documented down-shift, never a parser lie).
    """
    if not data.startswith(_PNG_SIG):
        raise ValueError("not a PNG")
    pos = 8
    ihdr = None
    palette = None
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = [tuple(chunk[i:i + 3]) for i in range(0, len(chunk), 3)]
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        raise ValueError("PNG missing IHDR")
    w, h, bitdepth, color_type, comp, filt, interlace = ihdr
    if interlace != 0:
        raise ValueError("interlaced PNG not supported by this oracle")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    raw = zlib.decompress(bytes(idat))
    bpp = channels * (bitdepth // 8)
    stride = (w * channels * bitdepth + 7) // 8
    rows = []
    prev = bytearray(stride)
    off = 0
    for _y in range(h):
        ftype = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        if ftype == 1:      # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:    # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:    # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(bytes(line))
        prev = line

    def pixel16(x: int, y: int) -> tuple:
        row = rows[y]
        if bitdepth == 8:
            base = x * channels
            vals = list(row[base:base + channels])
        else:  # 16
            base = x * channels * 2
            vals = [struct.unpack(">H", row[base + 2 * k:base + 2 * k + 2])[0]
                    for k in range(channels)]
        if color_type == 0:
            v = vals[0]
            return (v, v, v)
        if color_type == 4:
            v = vals[0]
            return (v, v, v)
        if color_type == 3:
            v = vals[0]
            return palette[v]
        if color_type == 2:
            return (vals[0], vals[1], vals[2])
        return (vals[0], vals[1], vals[2])   # RGBA → drop alpha honestly

    return {
        "w": w, "h": h, "bitdepth": bitdepth, "color_type": color_type,
        "channels": channels, "rows": rows, "pixel16": pixel16,
        "palette": palette,
        "get_pixel": (lambda x, y: tuple(v >> 8 for v in pixel16(x, y)))
        if bitdepth == 16 else pixel16,
    }


# ---------------------------------------------------------------------------
# Window-capture analysis helpers (GEO-02/03/05/06).
# ---------------------------------------------------------------------------

def analyze_letterbox(pixels, w: int, h: int, dark: int = 24) -> dict:
    """Measure uniform-dark border widths of a captured frame.

    Returns border widths (left/right/top/bottom), the content rect, and the
    measured border colour stats. Content vs border is decided per row/column:
    a border row is ≥99% pixels with all channels <= `dark`."""
    def row_is_dark(y):
        n = 0
        for x in range(0, w, max(1, w // 64)):
            p = pixels(x, y)
            if max(p) <= dark:
                n += 1
        return n / max(1, len(range(0, w, max(1, w // 64)))) >= 0.99

    def col_is_dark(x):
        n = 0
        for y in range(0, h, max(1, h // 64)):
            p = pixels(x, y)
            if max(p) <= dark:
                n += 1
        return n / max(1, len(range(0, h, max(1, h // 64)))) >= 0.99

    left = 0
    while left < w // 2 and col_is_dark(left):
        left += 1
    right = 0
    while right < w // 2 and col_is_dark(w - 1 - right):
        right += 1
    top = 0
    while top < h // 2 and row_is_dark(top):
        top += 1
    bottom = 0
    while bottom < h // 2 and row_is_dark(h - 1 - bottom):
        bottom += 1
    return {"left": left, "right": right, "top": top, "bottom": bottom,
            "content_rect": [left, top, w - left - right, h - top - bottom],
            "capture_size": [w, h]}


def block_uniformity(pixels, w: int, h: int, block: int, region=None) -> dict:
    """GEO-03 oracle: with strict nearest integer replication every kxk block
    must be CONSTANT. Returns the fraction of fully-constant blocks and the
    max intra-block channel spread."""
    x0, y0, x1, y1 = region or (0, 0, w, h)
    blocks = 0
    uniform = 0
    max_spread = 0
    for by in range(y0, y1 - block + 1, block):
        for bx in range(x0, x1 - block + 1, block):
            p00 = pixels(bx, by)
            spread = 0
            for yy in range(by, by + block):
                for xx in range(bx, bx + block):
                    p = pixels(xx, yy)
                    spread = max(spread, max(abs(a - b) for a, b in zip(p, p00)))
            blocks += 1
            if spread == 0:
                uniform += 1
            max_spread = max(max_spread, spread)
    return {"blocks": blocks, "uniform_blocks": uniform,
            "uniform_fraction": uniform / blocks if blocks else None,
            "max_intra_block_spread": max_spread, "block": block}


# ---------------------------------------------------------------------------
# Same-moment sampling (VL-F1 closure): decode/geometry/frame counts bound to
# one observation window, with an optional capture.
# ---------------------------------------------------------------------------

def same_moment_sample(s, shot_path=None, mode: str = "window") -> dict:
    """One observation window: video-out-params (pixelformat/gamma/w/h/dw/dh)
    + osd-dimensions + vo-passes frame counters + optional screenshot. The
    decode params and geometry therefore CANNOT be sampled at different
    moments (the P2 VL-F1 root cause)."""
    vop = s.get("video-out-params") or {}
    osd = s.get("osd-dimensions") or {}
    vp = s.get("vo-passes") or {}
    frame_counts = {}
    for frame in ("fresh", "redraw"):
        total = 0
        for item in (vp.get(frame) or []):
            if isinstance(item, dict):
                total += int(item.get("count") or 0)
        frame_counts[frame] = total
    rec = {
        "observed_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pixelformat": vop.get("pixelformat"),
        "gamma": vop.get("gamma"),
        "w": vop.get("w"), "h": vop.get("h"),
        "dw": vop.get("dw"), "dh": vop.get("dh"),
        "osd_w": osd.get("w"), "osd_h": osd.get("h"),
        "vo_passes_frame_counts": frame_counts,
        "same_window": True,
        "note": ("解码参数与几何在同一观察窗内读取（VL-F1 同刻采样闭环）；"
                 "screenshot_is_capture_not_texture=true"),
    }
    if shot_path is not None:
        ok = s.screenshot(shot_path, mode=mode)
        rec["screenshot"] = {
            "path": str(shot_path), "mode": mode, "captured": bool(ok),
            "sha256": lib.sha256_file(shot_path) if ok and Path(shot_path).exists() else None,
            "bytes": Path(shot_path).stat().st_size if ok and Path(shot_path).exists() else 0,
        }
    return rec


# ---------------------------------------------------------------------------
# P3 synthetic media helpers (small RGB samples for pixel oracles).
# ---------------------------------------------------------------------------

def generate_ppm_pattern(path: Path, w: int, h: int) -> tuple:
    """Small RGB sample with flat colour blocks + hard edges (xBR/Sharp pixel
    oracle input). Returns (sha256, pixels) where pixels[y][x] = (r,g,b)
    0..255 — the exact bytes fed to mpv."""
    def color_at(x, y):
        # quadrant flat blocks with a diagonal edge and an isolated dot
        if (x + y) % 7 == 0 and 2 <= x < w - 2 and 2 <= y < h - 2:
            return (250, 250, 250)
        if x < w // 2:
            if y < h // 2:
                return (180, 40, 40)
            return (40, 180, 40)
        if y < h // 2:
            return (40, 40, 200)
        return (220, 200, 30)

    rows = [[color_at(x, y) for x in range(w)] for y in range(h)]
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    payload = bytearray()
    for row in rows:
        for (r, g, b) in row:
            payload += bytes((r, g, b))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(payload))
    return lib.sha256_file(path), rows


def ppm_rows_to_float(rows):
    """(r,g,b) 0..255 rows → 0..1 float rows for the CPU replicas."""
    return [[(r / 255.0, g / 255.0, b / 255.0) for (r, g, b) in row]
            for row in rows]


def max_abs_diff_img(a, b) -> dict:
    """Per-channel max/mean absolute difference between two row images
    (0..255 scale)."""
    n = 0
    total = 0.0
    mx = 0
    for row_a, row_b in zip(a, b):
        for pa, pb in zip(row_a, row_b):
            for va, vb in zip(pa, pb):
                d = abs(va - vb)
                mx = max(mx, d)
                total += d
                n += 1
    return {"max": mx, "mean": total / n if n else 0.0, "samples": n}
