# -*- coding: utf-8 -*-
"""P4 pure contract / media / schedule library — session p4-001, batch B1 unit W1a.

Scope (docs/P4/P4-B1纯工具实现brief.md, W1a):
  * trial-spec contract (stage/session/group/clip/arm/fps/rife/rect/size/seeds/
    repeat/run-kind/plan-input-hash), strict types (bool is NOT a number;
    NaN/inf rejected);
  * canonical repo-relative path contract + create-only dirs/files + streaming
    SHA-256 (NOT an OS sandbox and NOT a TOCTOU defence — a canonical-path and
    create-only convention for evidence bookkeeping; no absolute paths, no
    "..", no backslashes, no symlink/reparse components, nothing resolved
    outside the workspace root passed in);
  * four preregistered synthetic clips (motion24 / motion30 / motion720 /
    pixelart), deterministic MEDIA_SEED derivation (SHA-256 formula, never
    Python's randomized hash()), streaming PNG frame generation with frame
    identity metadata (index / pts rational / fps), PNG is an RGB intermediate
    — YUV conversion happens later via the fixed-build mpv FFV1 transcode;
    PNG is never claimed to be natively YUV;
  * preregistered cell enumeration (G1/G2/G2b/G3 + fps subset, n=5/3),
    fixed per-block permutation + adjacent-block reversal run orders
    (LF-07: odd n residual imbalance disclosed), RIFE off/on pair
    alternation, sampling-window budget check;
  * collection JSON schema — B1-r2 native-API mapping (LF10): per pass entry
    {desc,last_ns,avg_ns,peak_ns,count,samples_ns[,raw_node]}; per the
    authoritative docs/证据/mpv-input.rst vo-passes node, `count` is the
    native per-pass TIMING-SAMPLE COUNT and `samples_ns` is the raw
    nanosecond timing ARRAY (the old int `samples` field was an LF10
    misreading of the native API and is rejected); all sample values and
    duplicates kept verbatim, count==len(samples_ns) when count is present
    (count:null records an API-omitted count, never fabricated);
    duplicate pass descs are legal and kept as separate ordinal slots
    (LF11: ordinal+desc is the stable identity, never merged/deduped);
    epoch/geometry/source/frame metadata; wall-monotonic is collection
    timestamp only. This library defines the schema; it NEVER fabricates
    sampling success.

Pure stdlib (Python 3.9), no import side effects, no credentials read, no
mpv/GPU/encoder/VS started, no sockets, no subprocess. Production lock is a
constant of this revision: no API input can create production run specs
(work-permit p4-001: production requires B4 calibration review).

Generator constants below (disk radius 200px, per-frame displacement (4,2)px,
luma16/luma235 grays, 8px marker strip, slow gradient band, pixelart 8x8
palette blocks scrolling 2px/frame) follow docs/P4实施计划.json
resource_budget.media; where docs/P4/P4测量方法.md §6 differs (300px/(6,3)),
the plan JSON prevails per its plan_notes conflict rule.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import re
import stat
import struct
import sys
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Session constants (preregistered; plan sha from docs/P4/P4-B1纯工具实现brief.md)
# ---------------------------------------------------------------------------

STAGE = "P4"
SESSION = "p4-001"
PLAN_SHA256 = "5285d11293373a20523ac199de2868ac2911e550ffd48b47be164311888c822a"
PLAN_REL = "docs/P4实施计划.json"
LIB_REL = "tools/p4_lib.py"
WORK_PERMIT_REL = "docs/验证/开发/p4-001/work-permit.json"

MEDIA_SEED = 20261007          # preregistered media-seed base constant (F-07)
ORDER_SEED = 20261007          # run-order seed
BOOTSTRAP_SEED = 424242        # run-level bootstrap seed (W1b consumer)
MEDIA_SEED_DERIVATION = (
    "int(sha256(('p4-001/' + clip_id).encode('utf-8')).digest()[:8].hex(), 16) "
    "% (2**32)   # digest[:8] big-endian == int(hexdigest()[:16], 16)"
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class P4ContractError(Exception):
    """Base class of every p4_lib contract violation."""


class PathContractError(P4ContractError):
    """Canonical-path / create-only convention violation.

    NOTE: this is a path-canonicalisation convention for evidence bookkeeping.
    It is NOT an OS sandbox and NOT a TOCTOU defence.
    """


class ValueContractError(P4ContractError):
    """Strict value violation: bool-as-number, NaN/inf, bad types, bad JSON."""


class TrialSpecError(P4ContractError):
    """Trial spec / cell / group contract violation."""


class CreateOnlyError(PathContractError):
    """Target already exists (create-only evidence convention)."""


class ProductionLockedError(TrialSpecError):
    """Production run specs are locked at this library revision."""


class ScheduleBudgetError(TrialSpecError):
    """Media length cannot cover warmup + window + quit margin."""


class MissingInputError(P4ContractError):
    """A required input binding does not exist on disk."""


# ---------------------------------------------------------------------------
# Strict numbers / JSON (bool is never accepted where a number is required)
# ---------------------------------------------------------------------------


def require_finite_number(value, field):
    """Return value unchanged iff it is a non-bool int/float and finite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueContractError(
            "%s: expected finite number, got %r (%s); bool is never a number"
            % (field, value, type(value).__name__))
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueContractError("%s: NaN/inf rejected" % field)
    return value


def require_nonneg_number(value, field):
    v = require_finite_number(value, field)
    if v < 0:
        raise ValueContractError("%s: negative value %r rejected" % (field, v))
    return v


def require_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueContractError(
            "%s: expected int (bool rejected), got %r (%s)"
            % (field, value, type(value).__name__))
    if minimum is not None and value < minimum:
        raise ValueContractError("%s: %r < minimum %r" % (field, value, minimum))
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise ValueContractError(
            "%s: expected bool, got %r (%s)" % (field, value, type(value).__name__))
    return value


def require_sha256_hex(value, field):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueContractError("%s: expected 64-char lowercase sha256 hex" % field)
    return value


def _no_duplicate_keys(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueContractError("duplicate JSON object key %r" % k)
        seen[k] = v
    return seen


def _reject_json_constant(name):
    raise ValueContractError("non-finite JSON constant %r rejected" % name)


def strict_json_loads(text, source="<json>"):
    """json.loads with: NaN/Infinity rejected, duplicate keys rejected."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    if not isinstance(text, str):
        raise ValueContractError("%s: expected str/bytes JSON text" % source)
    try:
        return json.loads(text, parse_constant=_reject_json_constant,
                          object_pairs_hook=_no_duplicate_keys)
    except P4ContractError:
        raise
    except ValueError as exc:
        raise ValueContractError("%s: invalid JSON: %s" % (source, exc)) from exc


def strict_json_bytes(obj):
    """Canonical deterministic JSON bytes: sorted keys, tight separators,
    ASCII-escaped, NaN/inf rejected by allow_nan=False."""
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except ValueError as exc:
        raise ValueContractError("strict_json_bytes: %s" % exc) from exc


# ---------------------------------------------------------------------------
# Hashing (streaming) + canonical path contract + create-only writers
# ---------------------------------------------------------------------------


def sha256_bytes(data):
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_file(path, chunk_bytes=1 << 20):
    """Streaming SHA-256 — never loads whole files into memory."""
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        while True:
            block = fh.read(chunk_bytes)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def canonical_json_bytes(obj):
    """Alias kept explicit for evidence writers: canonical JSON bytes."""
    return strict_json_bytes(obj)


def workspace_root():
    """Repo root (parent of tools/), derived from this file's location."""
    return Path(__file__).resolve().parents[1]


_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    "COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def check_rel_path(rel):
    """Canonical repo-relative POSIX path; returns rel unchanged.

    Rejects: non-str, empty, absolute paths, drive letters, backslashes,
    leading/trailing/duplicated slashes, '.'/'..' segments, Windows reserved
    device names. This is canonicalisation for evidence bookkeeping — NOT an
    OS sandbox / TOCTOU defence.
    """
    if not isinstance(rel, str) or not rel:
        raise PathContractError("rel path must be a non-empty str")
    if "\\" in rel:
        raise PathContractError("backslash rejected in rel path: %r" % rel)
    if os.path.isabs(rel) or rel.startswith("/") or rel.startswith(":"):
        raise PathContractError("absolute path rejected: %r" % rel)
    if re.match(r"^[A-Za-z]:", rel):
        raise PathContractError("drive-letter path rejected: %r" % rel)
    parts = rel.split("/")
    for part in parts:
        if part == "":
            raise PathContractError("empty path segment in %r" % rel)
        if part in (".", ".."):
            raise PathContractError("'%s' segment rejected in %r" % (part, rel))
        if part.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise PathContractError("reserved device name %r in %r" % (part, rel))
    return rel


def _reject_reparse(path):
    """Reject symlink/reparse-point components (canonical-tree contract)."""
    st = os.lstat(str(path))
    attrs = getattr(st, "st_file_attributes", 0)
    if (attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT) or os.path.islink(str(path)):
        raise PathContractError(
            "symlink/reparse component rejected: %s" % path)


def _is_under(child, root):
    child_s = os.path.normcase(str(child))
    root_s = os.path.normcase(str(root))
    if child_s == root_s:
        return True
    try:
        common = os.path.commonpath([child_s, root_s])
    except ValueError:
        return False
    return common == root_s


def resolve_under_root(rel, root=None):
    """Resolve a canonical rel path under root; rejects symlink/reparse
    components among existing ancestors and verifies (textually and via
    realpath) that the target stays under root."""
    rel = check_rel_path(rel)
    rootp = Path(root) if root is not None else workspace_root()
    if not rootp.is_dir():
        raise PathContractError("root is not a directory: %s" % rootp)
    cur = rootp
    for part in rel.split("/"):
        cur = cur / part
        if os.path.lexists(str(cur)):
            _reject_reparse(cur)
    abspath = Path(os.path.abspath(str(cur)))
    real = Path(os.path.realpath(str(abspath)))
    root_real = Path(os.path.realpath(str(rootp)))
    if not _is_under(abspath, root_real) or not _is_under(real, root_real):
        raise PathContractError(
            "resolution escapes workspace root: %r -> %s" % (rel, real))
    return real


def create_only_dir(rel, root=None):
    """Create a new directory; refuses if anything already exists there."""
    target = resolve_under_root(rel, root)
    if os.path.lexists(str(target)):
        raise CreateOnlyError("create-only violation: %r already exists" % rel)
    os.makedirs(str(target))
    return target


def create_only_file(rel, data, root=None):
    """Create a new file with bytes data; refuses to overwrite."""
    target = resolve_under_root(rel, root)
    if os.path.lexists(str(target)):
        raise CreateOnlyError("create-only violation: %r already exists" % rel)
    if not target.parent.is_dir():
        raise PathContractError(
            "parent directory missing for %r (create it via create_only_dir)"
            % rel)
    payload = bytes(data)
    with open(str(target), "wb") as fh:
        fh.write(payload)
    return {"path": check_rel_path(rel), "sha256": sha256_bytes(payload),
            "bytes": len(payload)}


def file_binding(rel, root=None):
    """Binding record for an existing file: canonical path + streamed sha256."""
    target = resolve_under_root(rel, root)
    if not target.is_file():
        raise MissingInputError("not an existing file: %r" % rel)
    return {"path": check_rel_path(rel), "sha256": sha256_file(target),
            "bytes": target.stat().st_size}


def library_sha256():
    """SHA-256 of this generator file itself (a required manifest binding)."""
    return sha256_file(Path(__file__))


# ---------------------------------------------------------------------------
# Preregistered clips (plan JSON resource_budget.media; JSON prevails on the
# 300px-vs-200px conflict — see module docstring) and media-seed derivation
# ---------------------------------------------------------------------------

_CLIP_DEFS = {
    "motion24": dict(width=1920, height=1080, fps=24, family="motion_disk"),
    "motion30": dict(width=1920, height=1080, fps=30, family="motion_disk"),
    "motion720": dict(width=1280, height=720, fps=24, family="motion_disk"),
    "pixelart": dict(width=480, height=360, fps=24, family="pixelart_palette"),
}

_MOTION_PARAMS = {
    "bg_luma": 16,              # dark background (RGB gray 16; YUV-equivalent target)
    "disk_luma": 235,           # bright disk
    "disk_radius_px": 200,      # plan JSON family value (200px, delta (4,2)px)
    "delta_px": [4, 2],         # per-frame displacement, bouncing triangle wave
    "marker_strip_px": 8,       # bottom 8px frame-number binary marker strip
    "marker_cells": 32,         # 32 bits LSB-first, cell width = width // 32
    "gradient_band_rows": 12,   # slow gradient band, top at h//3, moves 1px/frame
    "gradient_span": 220,
}

_PIXELART_PARAMS = {
    "block_px": 8,
    "scroll_px_per_frame": 2,
    "palette_size": 16,
    "lcg_a": 1103515245,
    "lcg_c": 12345,
    "lcg_m": 2 ** 31,
}


def _media_seed_raw(clip_id):
    digest = hashlib.sha256((SESSION + "/" + clip_id).encode("utf-8")).digest()
    return int(digest[:8].hex(), 16) % (2 ** 32)


def derive_media_seed(clip_id):
    """Preregistered SHA-256 media-seed derivation (F-07).

    MEDIA_SEED=20261007 is the declared base constant; the per-clip seed is
    int(sha256('p4-001/'+clip_id).digest()[:8] as hex, 16) mod 2**32.
    Python's process-randomized hash() is never used.
    """
    get_clip(clip_id)  # only preregistered clips may seed media
    return _media_seed_raw(clip_id)


def _build_clips():
    clips = {}
    for clip_id, d in _CLIP_DEFS.items():
        params = (dict(_MOTION_PARAMS) if d["family"] == "motion_disk"
                  else dict(_PIXELART_PARAMS))
        clips[clip_id] = {
            "clip": clip_id,
            "width": d["width"],
            "height": d["height"],
            "fps": d["fps"],
            "duration_s": 30.0,
            "frames": d["fps"] * 30,
            "family": d["family"],
            "params": params,
            "seed": _media_seed_raw(clip_id),
            "note": ("PNG frames are RGB intermediates; YUV conversion happens "
                     "later via the fixed-build mpv FFV1 transcode — PNG is "
                     "never claimed to be natively YUV"),
        }
    return clips


CLIPS = _build_clips()


def get_clip(clip_id):
    if not isinstance(clip_id, str) or clip_id not in CLIPS:
        raise TrialSpecError("unknown clip %r; preregistered: %s"
                             % (clip_id, sorted(CLIPS)))
    return CLIPS[clip_id]


# ---------------------------------------------------------------------------
# PNG encode (pure stdlib) + frame identity + streaming generation
# ---------------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def encode_png_rgb8(width, height, rows):
    """Encode RGB8 rows (iterable of width*3 bytes each) into PNG bytes.
    Filter 0 per row; deterministic bytes for deterministic rows."""
    if not (require_int(width, "width", minimum=1)
            and require_int(height, "height", minimum=1)):
        raise ValueContractError("bad PNG dimensions")
    raw = bytearray()
    n = 0
    for row in rows:
        row = bytes(row)
        if len(row) != width * 3:
            raise ValueContractError("row length %d != width*3 %d"
                                     % (len(row), width * 3))
        raw += b"\x00" + row
        n += 1
    if n != height:
        raise ValueContractError("got %d rows, expected %d" % (n, height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (_PNG_SIG + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _png_chunk(b"IEND", b""))


def _triangle_pos(t, lo, hi):
    span = hi - lo
    if span <= 0:
        return lo
    m = t % (2 * span)
    return lo + (m if m <= span else 2 * span - m)


def _motion_rows(spec, idx):
    p = spec["params"]
    w, h = spec["width"], spec["height"]
    r = p["disk_radius_px"]
    dx, dy = p["delta_px"]
    bg3 = bytes([p["bg_luma"]] * 3)
    fg3 = bytes([p["disk_luma"]] * 3)
    strip = p["marker_strip_px"]
    cells = p["marker_cells"]
    cell_w = w // cells
    band_top = h // 3
    band_rows = p["gradient_band_rows"]
    span = p["gradient_span"]
    cx = _triangle_pos(idx * dx, r, w - r)
    cy = _triangle_pos(idx * dy, r, h - strip - r)
    bits = [(idx >> i) & 1 for i in range(cells)]
    r2 = r * r
    for y in range(h):
        row = bytearray(bg3 * w)
        if band_top <= y < band_top + band_rows:
            for x in range(w):
                v = p["bg_luma"] + ((x + idx) % w) * span // w
                row[3 * x] = v
                row[3 * x + 1] = v
                row[3 * x + 2] = v
        if y >= h - strip:
            for c in range(cells):
                if bits[c]:
                    row[3 * c * cell_w: 3 * (c + 1) * cell_w] = fg3 * cell_w
        else:
            dy2 = (y - cy) ** 2
            if dy2 <= r2:
                half = math.isqrt(r2 - dy2)
                x0 = max(0, cx - half)
                x1 = min(w, cx + half + 1)
                if x1 > x0:
                    row[3 * x0:3 * x1] = fg3 * (x1 - x0)
        yield bytes(row)


def _pixelart_palette(spec):
    p = spec["params"]
    x = spec["seed"] % p["lcg_m"]
    colors = []
    for _ in range(p["palette_size"]):
        chan = []
        for _ in range(3):
            x = (x * p["lcg_a"] + p["lcg_c"]) % p["lcg_m"]
            chan.append((x >> 16) & 255)
        colors.append(tuple(chan))
    return colors


def _pixelart_rows(spec, idx):
    p = spec["params"]
    w, h = spec["width"], spec["height"]
    nb = p["block_px"]
    pal = _pixelart_palette(spec)
    psize = p["palette_size"]
    off = idx * p["scroll_px_per_frame"]
    b0 = off // nb
    rem = nb - (off % nb)
    for y in range(h):
        by = y // nb
        row = bytearray(w * 3)
        pos = 0
        b = b0
        while pos < w:
            color = bytes(pal[(b * 7 + by * 13) % psize])
            n = min(rem, w - pos)
            row[3 * pos:3 * (pos + n)] = color * n
            pos += n
            b += 1
            rem = nb
        yield bytes(row)


def _rows_for(spec, idx):
    if spec["family"] == "motion_disk":
        return _motion_rows(spec, idx)
    if spec["family"] == "pixelart_palette":
        return _pixelart_rows(spec, idx)
    raise TrialSpecError("unknown generator family %r" % spec["family"])


def frame_identity(clip_id, index):
    """Frame identity metadata: index, exact rational pts, integer-rational
    fps, S frame class (source frames of a preregistered clip)."""
    spec = get_clip(clip_id)
    index = require_int(index, "frame index", minimum=0)
    if index >= spec["frames"]:
        raise ValueContractError("frame index %d out of range for %s (%d frames)"
                                 % (index, clip_id, spec["frames"]))
    return {
        "clip": clip_id,
        "index": index,
        "pts_num": index,
        "pts_den": spec["fps"],
        "pts_exact": "%d/%d" % (index, spec["fps"]),
        "fps_num": spec["fps"],
        "fps_den": 1,
        "frame_class": "S",
        "media_seed": spec["seed"],
        "generator": LIB_REL,
    }


def rife_output_frame_class(output_index):
    """S/M frame class of a RIFE 2x --vo=image output frame.
    Interleave([source, middle]) semantics (survey): even output index = S
    (source frame), odd = M (model middle frame). M frames are never claimed
    to be 'the same frame' as any S frame."""
    output_index = require_int(output_index, "output index", minimum=0)
    return "S" if output_index % 2 == 0 else "M"


def iter_clip_frames(clip_id, indices=None):
    """Lazy generator of (index, png_bytes) — streams frame by frame; never
    materialises a whole clip in memory."""
    spec = get_clip(clip_id)
    if indices is None:
        indices = range(spec["frames"])
        start = 0
        count = spec["frames"]
    else:
        indices = list(indices)
        start = indices[0] if indices else 0
        count = len(indices)
    for k in range(count):
        idx = indices[k] if indices is not None else start + k
        yield idx, encode_png_rgb8(spec["width"], spec["height"],
                                   _rows_for(spec, idx))


def write_clip_frames(clip_id, out_dir, indices=None):
    """Write selected frames as create-only PNG files into an existing
    directory (caller chooses the directory: %TEMP% staging is legitimate —
    evidence-tree placement is the collector's duty, not this function's)."""
    out = Path(out_dir)
    if not out.is_dir():
        raise PathContractError("out_dir must be an existing directory: %s" % out)
    records = []
    for idx, data in iter_clip_frames(clip_id, indices):
        name = "%s-%06d.png" % (clip_id, idx)
        target = out / name
        if os.path.lexists(str(target)):
            raise CreateOnlyError("create-only violation: %s exists" % target)
        with open(str(target), "wb") as fh:
            fh.write(data)
        records.append({"file": name, "index": idx,
                        "sha256": sha256_bytes(data), "bytes": len(data)})
    return records


def decode_marker_index(decoded, clip_id):
    """Decode the 32-bit LSB-first frame-number marker strip from a decoded
    PNG (p3_lib.decode_png result) of a motion_disk clip."""
    spec = get_clip(clip_id)
    if spec["family"] != "motion_disk":
        raise TrialSpecError("marker strip only defined for motion_disk clips")
    h, w = spec["height"], spec["width"]
    p = spec["params"]
    cell_w = w // p["marker_cells"]
    strip = p["marker_strip_px"]
    idx = 0
    for c in range(p["marker_cells"]):
        x = c * cell_w + cell_w // 2
        votes = sum(1 for y in range(h - strip, h)
                    if decoded["pixel16"](x, y)[0] > 128)
        if votes * 2 > strip:
            idx |= 1 << c
    return idx


def verify_png_frame(png_bytes, clip_id, index):
    """Bit-depth / size / decode recheck + frame identity via marker strip.
    Uses tools/p3_lib.decode_png (read-only prior-handoff API, reviewed)."""
    spec = get_clip(clip_id)
    index = require_int(index, "frame index", minimum=0)
    import p3_lib  # read-only reuse of the frozen prior-handoff decoder
    dec = p3_lib.decode_png(bytes(png_bytes))
    if dec["bitdepth"] != 8 or dec["color_type"] != 2:
        raise ValueContractError(
            "expected RGB8 PNG, got bitdepth=%r color_type=%r"
            % (dec["bitdepth"], dec["color_type"]))
    if dec["w"] != spec["width"] or dec["h"] != spec["height"]:
        raise ValueContractError(
            "size mismatch for %s: PNG %dx%d, clip %dx%d"
            % (clip_id, dec["w"], dec["h"], spec["width"], spec["height"]))
    identity = frame_identity(clip_id, index)
    identity["width"] = dec["w"]
    identity["height"] = dec["h"]
    identity["bit_depth"] = 8
    if spec["family"] == "motion_disk":
        marker = decode_marker_index(dec, clip_id)
        if marker != index:
            raise ValueContractError(
                "frame identity mismatch for %s: marker=%d expected=%d"
                % (clip_id, marker, index))
        identity["decoded_marker_index"] = marker
    return identity


# ---------------------------------------------------------------------------
# Preregistered groups / arms / cells (fairness.groups) + n=5/3 + scheduling
# ---------------------------------------------------------------------------

GROUPS = {
    "G1_equalrect_main": {
        "clip": "motion24",
        "arms": ["baselineHQ", "nearest", "FSR1", "SGSR1", "NIS",
                 "SharpBilinear-AUTO", "SharpBilinear-2x", "Anime4K-ModeA"],
        "expected_rect": [2560, 1440],
        "output_size": [2560, 1440],
        "expected_window_size": [2560, 1440],
        "expected_margins": [0, 0, 0, 0],
        "n": 5,
        "note": ("equal-rect main group, full screen 2560x1440; "
                 "SharpBilinear-AUTO degenerates to bilinear here (disclosed)"),
    },
    "G2_integer_display": {
        "clip": "motion24",
        "arms": ["Integer"],
        "expected_rect": [1920, 1080],
        "output_size": [1920, 1080],
        "expected_window_size": [2560, 1440],
        "expected_margins": [320, 180, 320, 180],
        "n": 5,
        "note": ("native integer display k=1; NEVER ranked together with the "
                 "G1 full-rect group (assert_cells_comparable enforces); the "
                 "window stays 2560x1440 with letterbox margins (320,180," 
                 "320,180) — expected_window_size is the independent window "
                 "contract, the legacy output_size field is the video size "
                 "and must never be used to judge the window"),
    },
    "G2b_integer_k2": {
        "clip": "motion720",
        "arms": ["Integer", "nearest", "baselineHQ"],
        "expected_rect": [2560, 1440],
        "output_size": [2560, 1440],
        "expected_window_size": [2560, 1440],
        "expected_margins": [0, 0, 0, 0],
        "n": 3,
        "note": "equal-rect k=2 reference group; media=motion720 (F-01)",
    },
    "G3_pixelart": {
        "clip": "pixelart",
        "arms": ["xBR-lv2", "SharpBilinear-AUTO", "nearest", "Integer"],
        "expected_rect": [1440, 1080],
        "output_size": [1440, 1080],
        "expected_window_size": [1440, 1080],
        "expected_margins": [0, 0, 0, 0],
        "n": 3,
        "note": "pixel-art group, window 1440x1080 (k=3)",
    },
}

# F5 coordinate-boundary contract (B1-r2; corrects the original review's
# dw/dh==target-rect confusion):
GEOMETRY_SEMANTICS = (
    "video_out_params.w/h is the POST-FILTER SOURCE size (the RIFE chain "
    "restores source resolution, so both strata expect the clip size); "
    "video_out_params.dw/dh is the effective source DISPLAY size (w/h times "
    "sample aspect ratio) — for the square-pixel synthetic sources dw/dh "
    "EQUALS source w/h; dw/dh is NEVER the window and NEVER the shader "
    "output rect; osd_dimensions.w/h is the WINDOW in native pixels and must "
    "match expected_window_size (not the legacy output_size); the display "
    "rect is derived from the same single-command osd margins ml/mr/mt/mb "
    "(rect = [osd.w-ml-mr, osd.h-mt-mb]) and must match expected_rect when "
    "margins are observed; real collectors fill ACTUALLY observed margins "
    "and must never copy the spec pretending they were observed")


def expected_geometry(group_id):
    """Preregistered geometry contract of one group (F5, B1-r2).

    Returns the independent source / display / window / rect / margins
    expectations used by the analysis cross-checks. dw/dh is the source
    display size (square-pixel SAR=1 => equals source w/h), NOT the window
    and NOT the output rect (the original F5 fix suggestion was wrong and is
    corrected here; see GEOMETRY_SEMANTICS)."""
    group = get_group(group_id)
    clip = get_clip(group["clip"])
    return {
        "source_w_h": [clip["width"], clip["height"]],
        "display_dw_dh": [clip["width"], clip["height"]],
        "window_w_h": list(group["expected_window_size"]),
        "rect_w_h": list(group["expected_rect"]),
        "margins_ml_mt_mr_mb": list(group["expected_margins"]),
        "semantics": GEOMETRY_SEMANTICS,
    }

FPS_SUBSET_ARMS = ["baselineHQ", "Anime4K-ModeA", "FSR1"]  # off@30 / on@60 only
ALLOWED_RUN_KINDS = ("calibration", "pilot", "identity_probe")
PRODUCTION_LOCK = {
    "locked": True,
    "reason": ("work-permit p4-001: production_measurement_requires_"
               "calibration_review=true; B4 review not passed at this "
               "library revision"),
    "unlock_path": ("a later pre-registered revision of tools/p4_lib.py with "
                    "new plan binding — never a runtime/API argument"),
}


def get_group(group_id):
    if not isinstance(group_id, str) or group_id not in GROUPS:
        raise TrialSpecError("unknown group %r; preregistered: %s"
                             % (group_id, sorted(GROUPS)))
    return GROUPS[group_id]


def _cell(group, arm, clip, source_fps, rife, n):
    out_fps = source_fps * 2 if rife == "on" else source_fps
    return {
        "cell": "%s|%s|%s@%d|rife=%s" % (group, arm, clip, source_fps, rife),
        "group": group, "arm": arm, "clip": clip,
        "source_fps": source_fps, "rife": rife, "rife_output_fps": out_fps,
        "n": n,
    }


def enumerate_cells():
    """Preregistered cell enumeration. Totals MUST equal the plan's B5 timed
    budget: G1 off@24 8x5=40, G1 on24->48 8x5=40, fps subset off@30 3x5=15 +
    on@60 3x5=15, G2 1x5=5, G2b 3x3=9, G3 4x3=12 => 30 cells / 136 runs."""
    cells = []
    g1 = GROUPS["G1_equalrect_main"]
    for arm in g1["arms"]:
        cells.append(_cell("G1_equalrect_main", arm, "motion24", 24, "off", 5))
        cells.append(_cell("G1_equalrect_main", arm, "motion24", 24, "on", 5))
    for arm in FPS_SUBSET_ARMS:
        if arm not in g1["arms"]:
            raise TrialSpecError("fps-subset arm %r not in G1" % arm)
        cells.append(_cell("G1_equalrect_main", arm, "motion30", 30, "off", 5))
        cells.append(_cell("G1_equalrect_main", arm, "motion30", 30, "on", 5))
    for arm in GROUPS["G2_integer_display"]["arms"]:
        cells.append(_cell("G2_integer_display", arm, "motion24", 24, "off", 5))
    for arm in GROUPS["G2b_integer_k2"]["arms"]:
        cells.append(_cell("G2b_integer_k2", arm, "motion720", 24, "off", 3))
    for arm in GROUPS["G3_pixelart"]["arms"]:
        cells.append(_cell("G3_pixelart", arm, "pixelart", 24, "off", 3))
    return cells


def cell_run_totals():
    cells = enumerate_cells()
    return {"cells": len(cells),
            "runs": sum(c["n"] for c in cells)}


def get_cell(cell_key):
    for c in enumerate_cells():
        if c["cell"] == cell_key:
            return c
    raise TrialSpecError("unknown cell %r (not preregistered)" % cell_key)


def assert_cells_comparable(cell_a, cell_b):
    """Two cells may only be ranked together when group, clip, source fps,
    RIFE stratum and output rect all match (Integer k=1 can never enter a
    full-rect G1 ranking)."""
    for field in ("group", "clip", "source_fps", "rife"):
        if cell_a[field] != cell_b[field]:
            raise TrialSpecError(
                "cells not comparable: %s differs (%r vs %r)"
                % (field, cell_a[field], cell_b[field]))
    rect_a = GROUPS[cell_a["group"]]["expected_rect"]
    rect_b = GROUPS[cell_b["group"]]["expected_rect"]
    if rect_a != rect_b:
        raise TrialSpecError(
            "cells not comparable: expected_rect differs (%r vs %r)"
            % (rect_a, rect_b))
    return True


class _Sha256Prng:
    """Deterministic SHA-256 counter-mode PRNG (never Python hash())."""

    def __init__(self, seed_int):
        self._seed = require_int(seed_int, "prng seed", minimum=0)
        self._counter = 0
        self._buf = b""

    def _refill(self):
        data = (self._seed.to_bytes(8, "big")
                + self._counter.to_bytes(8, "big"))
        self._buf += hashlib.sha256(data).digest()
        self._counter += 1

    def next_u64(self):
        if len(self._buf) < 8:
            self._refill()
        (v,) = struct.unpack(">Q", self._buf[:8])
        self._buf = self._buf[8:]
        return v

    def below(self, k):
        k = require_int(k, "prng bound", minimum=1)
        limit = ((1 << 64) // k) * k
        while True:
            v = self.next_u64()
            if v < limit:
                return v % k


def _derived_seed(base_seed, label):
    digest = hashlib.sha256(("%s:%d" % (label, base_seed)).encode("utf-8"))
    return int(digest.hexdigest()[:16], 16) % (2 ** 32)


def _fisher_yates(items, seed_int):
    prng = _Sha256Prng(seed_int)
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = prng.below(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


ORDER_DISCLOSURE = (
    "fixed per-block Fisher-Yates permutation + adjacent-block reversal; "
    "NOT a strict ABBA complete-balancing design (LF-07); odd n leaves the "
    "last block unreversed — the residual order imbalance is disclosed, not "
    "hidden")


def run_order_for_group(group_id, n=None, seed=ORDER_SEED):
    """Deterministic run order: block 0 = seeded Fisher-Yates permutation of
    the group arms; odd blocks = reversal of the previous block; even blocks
    >0 = fresh seeded permutation. Returns blocks + honest disclosure."""
    group = get_group(group_id)
    seed = require_int(seed, "order seed", minimum=0)
    n = group["n"] if n is None else require_int(n, "n", minimum=1)
    blocks = []
    for k in range(n):
        if k % 2 == 1:
            blocks.append(list(reversed(blocks[k - 1])))
        else:
            blocks.append(_fisher_yates(group["arms"],
                                        _derived_seed(seed,
                                                      "%s/block/%d" % (group_id, k))))
    return {
        "group": group_id,
        "seed": seed,
        "n": n,
        "blocks": blocks,
        "balanced": n % 2 == 0,
        "n_parity": "even" if n % 2 == 0 else "odd",
        "residual_imbalance_disclosure": (None if n % 2 == 0 else
                                          "odd n: last block has no reversed "
                                          "successor; residual order imbalance "
                                          "disclosed (LF-07)"),
        "design": ORDER_DISCLOSURE,
    }


def rife_calibration_pair_order(n_pairs):
    """RIFE off/on calibration pairs alternate with reversal:
    [off,on], [on,off], [off,on], ..."""
    n_pairs = require_int(n_pairs, "n_pairs", minimum=1)
    return [["off", "on"] if i % 2 == 0 else ["on", "off"]
            for i in range(n_pairs)]


# ---------------------------------------------------------------------------
# Sampling-window budget (warmup 10..15 + window 10 + quit 2.5, media 30s)
# ---------------------------------------------------------------------------

SAMPLING_BUDGET = {
    "preregistered_media_s": 30.0,
    "warmup_min_s": 10.0,
    "warmup_max_s": 15.0,
    "window_s": 10.0,
    "quit_margin_s": 2.5,
    "poll_period_s": 1.0,
    "window_target_samples": 10,
}
WARMUP_MIN_CONSECUTIVE_POLLS = 3
WARMUP_CRITERIA = [
    "pass desc list identical across consecutive polls",
    "every pass last/avg/peak/samples non-empty (>0)",
    "video-out-params render state stable (no reinit)",
    "time-pos monotonically advancing, frame count no regress",
    "GPU temperature drift <= 2C",
]
# vo-passes count/samples saturation (~10s rolling window) is known behaviour:
# it must never be used as a liveness/stability gate and never blocks a run.
SATURATION_NOTE = (
    "vo-passes/dropped counters are rolling-window values; saturation or "
    "zero growth around ~10s is known behaviour, never by itself evidence of "
    "stall and never a blocking failure (LF-01)")
WARMUP_STATE_NOTE = ("warmup stabilisation state machine is W2 scope; W1a "
                     "publishes only the preregistered criteria above")


def sampling_budget_check(media_s=None):
    """Media must cover warmup max (15) + window (10) + quit margin (2.5)."""
    if media_s is None:
        media_s = SAMPLING_BUDGET["preregistered_media_s"]
    media_s = float(require_finite_number(media_s, "media_s"))
    required = (SAMPLING_BUDGET["warmup_max_s"] + SAMPLING_BUDGET["window_s"]
                + SAMPLING_BUDGET["quit_margin_s"])
    if media_s < required:
        raise ScheduleBudgetError(
            "media %.3fs cannot cover warmup<=15 + window 10 + quit 2.5 "
            "(requires >= %.3fs)" % (media_s, required))
    return {"media_s": media_s, "required_min_media_s": required, "ok": True}


def assert_clip_covers_sampling(clip_id):
    return sampling_budget_check(get_clip(clip_id)["duration_s"])


def counter_delta(first, last, name="counter"):
    """Run-internal first/last delta for counters (preregistered semantics).
    Negative delta => counter reset => run-internal delta invalid (rejected).
    Zero growth (saturation) is reported, never blocking."""
    a = require_int(first, name + ".first", minimum=0)
    b = require_int(last, name + ".last", minimum=0)
    delta = b - a
    if delta < 0:
        raise ValueContractError(
            "%s: negative delta %d->%d (counter reset); run-internal delta "
            "invalid per preregistration" % (name, a, b))
    return {"delta": delta, "no_growth": delta == 0, "blocking": False,
            "note": SATURATION_NOTE}


# ---------------------------------------------------------------------------
# Collection JSON schema (design only — never fabricates sampling success)
# ---------------------------------------------------------------------------

SNAPSHOT_REQUIRED_FIELDS = ("snapshot_index", "wall_monotonic_s", "time_pos_s",
                            "epoch", "video_out_params", "osd_dimensions",
                            "vo_passes")
SNAPSHOT_OPTIONAL_FIELDS = ("counters", "frame", "source", "same_window",
                            "note")
# LF10 (B1-r2): native mpv vo-passes node per docs/证据/mpv-input.rst —
# `count` is the native per-pass timing-sample count, `samples_ns` is the raw
# ns timing array. The old int `samples` field was a misreading and is
# rejected. `count: null` records an API-omitted count (never fabricated).
# Optional `raw_node` preserves the unmapped native node verbatim alongside
# the normalized mapping. Duplicate descs are legal (LF11) and are kept as
# separate ordinal slots.
SNAPSHOT_PASS_FIELDS = ("desc", "last_ns", "avg_ns", "peak_ns", "count",
                        "samples_ns")
SNAPSHOT_PASS_OPTIONAL_FIELDS = ("raw_node",)
SINGLE_COMMAND_NOTE = (
    "one snapshot MUST be obtained with ONE Lua IPC command (single reply "
    "containing every field); several sequential IPC property reads are NOT "
    "atomic and MUST NOT be labelled same-moment/atomic")
FIELD_SEMANTICS = {
    "wall_monotonic_s":
        "time.monotonic() at capture: collection-order timestamp ONLY; never "
        "a present time and never a frame-duration source",
    "time_pos_s":
        "media clock seconds; NOT screen present time; IPC sampling intervals "
        "and time-pos deltas are never frame durations (TIME-01)",
    "epoch":
        "render-state epoch int>=0; analysis must not mix snapshots across "
        "epoch changes",
    "video_out_params":
        "decoder/render geometry captured in the same single window "
        "(pixelformat/gamma/w/h/dw/dh) — the VL-F1 same-moment closure; "
        "aligned with p3_lib.same_moment_sample semantics (single window), "
        "extended with per-pass fresh/redraw tables and counters",
    "osd_dimensions":
        "window output geometry w/h from the same snapshot window, in native "
        "pixels; optional same-command margins ml/mr/mt/mb (all-or-none) "
        "yield the actual display rect [w-ml-mr, h-mt-mb]; the rect is never "
        "taken from video_out_params.dw/dh (those are the source display "
        "size) and never copied from the spec (F5)",
    "vo_passes":
        "raw rolling-window per-pass tables, fresh/redraw separated, ns "
        "units; entries kept verbatim; identical values are real "
        "re-observations and MUST NOT be value-deduplicated; per LF10 the "
        "native node maps to count (native timing-sample count) + samples_ns "
        "(raw ns timing array); the old int samples field was an LF10 "
        "misreading of the native API and is rejected",
    "counters":
        "counter family (dropped/mistimed/vsync...); run-internal first/last "
        "delta only (counter_delta); saturation never blocks (LF-01)",
    "frame":
        "optional source frame metadata (index/pts_num/pts_den) from "
        "frame_identity; present-source truth is NOT claimable from it",
    "source":
        "optional media binding (clip id + media sha256 + generator sha256); "
        "analysis requires these observations inside the performance window "
        "and cross-checks them against the spec/clip registry/library "
        "revision (F5)",
}


def snapshot_schema():
    return {
        "required": list(SNAPSHOT_REQUIRED_FIELDS),
        "optional": list(SNAPSHOT_OPTIONAL_FIELDS),
        "pass_fields": list(SNAPSHOT_PASS_FIELDS),
        "field_semantics": dict(FIELD_SEMANTICS),
        "single_command": SINGLE_COMMAND_NOTE,
        "no_value_dedup": True,
        "units": {"last_ns": "ns", "avg_ns": "ns", "peak_ns": "ns",
                  "samples_ns": "ns (raw timing array, LF10)",
                  "count": "native per-pass timing-sample count (LF10)",
                  "time_pos_s": "s", "wall_monotonic_s": "s (monotonic)"},
        "sampling_state_note": WARMUP_STATE_NOTE,
        "fabrication": ("this library validates schema only; it never "
                        "pretends samples were taken"),
    }


def validate_snapshot(snap):
    """Strict validation of one collection snapshot record."""
    if not isinstance(snap, dict):
        raise ValueContractError("snapshot must be a dict")
    allowed = set(SNAPSHOT_REQUIRED_FIELDS) | set(SNAPSHOT_OPTIONAL_FIELDS)
    for field in SNAPSHOT_REQUIRED_FIELDS:
        if field not in snap:
            raise ValueContractError("snapshot missing required field %r" % field)
    for field in snap:
        if field not in allowed:
            raise ValueContractError("snapshot has unknown field %r" % field)
    require_int(snap["snapshot_index"], "snapshot_index", minimum=0)
    require_finite_number(snap["wall_monotonic_s"], "wall_monotonic_s")
    require_nonneg_number(snap["time_pos_s"], "time_pos_s")
    require_int(snap["epoch"], "epoch", minimum=0)
    vop = snap["video_out_params"]
    if not isinstance(vop, dict):
        raise ValueContractError("video_out_params must be a dict")
    for k in ("w", "h", "dw", "dh"):
        require_int(vop.get(k), "video_out_params.%s" % k, minimum=1)
    pf = vop.get("pixelformat")
    if not isinstance(pf, str) or not pf:
        raise ValueContractError("video_out_params.pixelformat must be non-empty str")
    osd = snap["osd_dimensions"]
    if not isinstance(osd, dict):
        raise ValueContractError("osd_dimensions must be a dict")
    for k in ("w", "h"):
        require_int(osd.get(k), "osd_dimensions.%s" % k, minimum=1)
    margin_keys = ("ml", "mr", "mt", "mb")
    present_margins = [k for k in margin_keys if k in osd]
    if present_margins:
        if len(present_margins) != len(margin_keys):
            raise ValueContractError(
                "osd_dimensions margins are all-or-none: ml/mr/mt/mb, got %s"
                % sorted(present_margins))
        for k in margin_keys:
            require_int(osd[k], "osd_dimensions.%s" % k, minimum=0)
    vp = snap["vo_passes"]
    if not isinstance(vp, dict) or set(vp) != {"fresh", "redraw"}:
        raise ValueContractError(
            "vo_passes must have exactly fresh/redraw lists")
    counts = {}
    for frame_name in ("fresh", "redraw"):
        table = vp[frame_name]
        if not isinstance(table, list):
            raise ValueContractError("vo_passes.%s must be a list" % frame_name)
        for entry in table:
            if not isinstance(entry, dict):
                raise ValueContractError("vo_passes.%s entry must be a dict"
                                         % frame_name)
            allowed_pass = set(SNAPSHOT_PASS_FIELDS) | set(
                SNAPSHOT_PASS_OPTIONAL_FIELDS)
            if set(entry) - allowed_pass or not set(SNAPSHOT_PASS_FIELDS) <= set(entry):
                raise ValueContractError(
                    "vo_passes.%s entry must have exactly %s (optional: %s); "
                    "the old int 'samples' field was an LF10 misreading of the "
                    "native API (count + samples_ns array is the canonical "
                    "mapping)"
                    % (frame_name, "/".join(SNAPSHOT_PASS_FIELDS),
                       "/".join(SNAPSHOT_PASS_OPTIONAL_FIELDS)))
            if not isinstance(entry["desc"], str) or not entry["desc"]:
                raise ValueContractError("pass desc must be non-empty str")
            for ns_field in ("last_ns", "avg_ns", "peak_ns"):
                require_nonneg_number(entry[ns_field],
                                      "vo_passes.%s.%s" % (frame_name, ns_field))
            samples_ns = entry["samples_ns"]
            if not isinstance(samples_ns, list):
                raise ValueContractError(
                    "vo_passes.%s.samples_ns must be a list of raw ns timing "
                    "values (LF10), got %s"
                    % (frame_name, type(samples_ns).__name__))
            for k, v in enumerate(samples_ns):
                require_nonneg_number(v, "vo_passes.%s.samples_ns[%d]"
                                      % (frame_name, k))
            count = entry["count"]
            if count is None:
                pass  # API-omitted native count recorded as missing, never fabricated
            else:
                require_int(count, "vo_passes.%s.count" % frame_name, minimum=0)
                if count != len(samples_ns):
                    raise ValueContractError(
                        "vo_passes.%s.count %r != len(samples_ns) %d"
                        % (frame_name, count, len(samples_ns)))
            if "raw_node" in entry and not isinstance(entry["raw_node"], dict):
                raise ValueContractError(
                    "vo_passes.%s.raw_node must be a dict when present"
                    % frame_name)
        counts[frame_name] = len(table)  # kept verbatim — never deduplicated
    if "counters" in snap:
        counters = snap["counters"]
        if not isinstance(counters, dict):
            raise ValueContractError("counters must be a dict")
        for name, value in counters.items():
            require_int(value, "counters.%s" % name, minimum=0)
    if "frame" in snap:
        fr = snap["frame"]
        if not isinstance(fr, dict):
            raise ValueContractError("frame metadata must be a dict")
        require_int(fr.get("index"), "frame.index", minimum=0)
        require_int(fr.get("pts_num"), "frame.pts_num", minimum=0)
        require_int(fr.get("pts_den"), "frame.pts_den", minimum=1)
        if "frame_class" in fr and fr["frame_class"] not in ("S", "M"):
            raise ValueContractError(
                "frame.frame_class must be 'S' (source) or 'M' (RIFE middle "
                "output, a different index naming domain), got %r"
                % (fr["frame_class"],))
    if "source" in snap:
        src = snap["source"]
        if not isinstance(src, dict):
            raise ValueContractError("source metadata must be a dict")
        get_clip(src.get("clip"))
        require_sha256_hex(src.get("media_sha256"), "source.media_sha256")
        require_sha256_hex(src.get("generator_sha256"),
                           "source.generator_sha256")
    if "same_window" in snap:
        require_bool(snap["same_window"], "same_window")
    return {"snapshot_index": snap["snapshot_index"], "fresh": counts["fresh"],
            "redraw": counts["redraw"]}


def validate_run_jsonl(text, source="<run.jsonl>"):
    """Validate a JSONL stream of snapshots; indices strictly increasing
    (jitter allowed, regressions not). Returns the parsed snapshot list."""
    snapshots = []
    prev_index = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        snap = strict_json_loads(line, source="%s:%d" % (source, line_no))
        info = validate_snapshot(snap)
        if prev_index is not None and info["snapshot_index"] <= prev_index:
            raise ValueContractError(
                "%s:%d snapshot_index %d not strictly increasing"
                % (source, line_no, info["snapshot_index"]))
        prev_index = info["snapshot_index"]
        snapshots.append(snap)
    if not snapshots:
        raise ValueContractError("%s: no snapshot records" % source)
    return snapshots


# ---------------------------------------------------------------------------
# Trial spec contract
# ---------------------------------------------------------------------------

SPEC_KEYS = ("stage", "session", "group", "clip", "arm", "source_fps",
             "rife", "rife_output_fps", "expected_rect", "output_size",
             "order_seed", "media_seed", "n", "repeat_index", "run_kind",
             "plan_sha256", "cell", "generated_by")


def _validate_stratum(group_id, arm, clip, source_fps, rife):
    group = get_group(group_id)
    if arm not in group["arms"]:
        raise TrialSpecError("arm %r is not registered in group %r"
                             % (arm, group_id))
    if rife not in ("off", "on"):
        raise TrialSpecError("rife must be 'off'/'on', got %r" % (rife,))
    default_clip = group["clip"]
    if clip is None:
        if (group_id == "G1_equalrect_main" and source_fps == 30
                and arm in FPS_SUBSET_ARMS):
            clip = "motion30"
        else:
            clip = default_clip
    if clip != default_clip:
        # only exception: G1 fps-subset stratum uses motion30
        if not (group_id == "G1_equalrect_main" and clip == "motion30"
                and arm in FPS_SUBSET_ARMS and source_fps == 30):
            raise TrialSpecError(
                "clip %r not valid for group %r in this stratum" % (clip, group_id))
    fps = get_clip(clip)["fps"]
    if source_fps is None:
        source_fps = fps
    if source_fps != fps:
        raise TrialSpecError("source_fps %r does not match clip %r fps %d"
                             % (source_fps, clip, fps))
    if rife == "on":
        if not (group_id == "G1_equalrect_main"
                and (source_fps == 24 or arm in FPS_SUBSET_ARMS)):
            raise TrialSpecError(
                "rife=on only preregistered for G1 (24->48 all arms; 30->60 "
                "fps subset %s)" % FPS_SUBSET_ARMS)
    if rife == "off" and group_id == "G1_equalrect_main" and source_fps == 30 \
            and arm not in FPS_SUBSET_ARMS:
        raise TrialSpecError(
            "off@30 is a fps-subset stratum limited to %s" % FPS_SUBSET_ARMS)
    return clip, source_fps


def make_trial_spec(group, arm, rife, repeat_index, run_kind="calibration",
                    source_fps=None, plan_sha256=None, clip=None):
    """Build one validated trial spec. Production is locked at this revision:
    run_kind='production' always raises, no matter what inputs are passed."""
    get_group(group)
    if run_kind == "production":
        raise ProductionLockedError(
            "production specs cannot be created via API input at this "
            "revision: %s; unlock path: %s"
            % (PRODUCTION_LOCK["reason"], PRODUCTION_LOCK["unlock_path"]))
    if run_kind not in ALLOWED_RUN_KINDS:
        raise TrialSpecError("run_kind must be one of %s, got %r"
                             % (ALLOWED_RUN_KINDS, run_kind))
    require_sha256_hex(plan_sha256, "plan_sha256")
    if plan_sha256 != PLAN_SHA256:
        raise TrialSpecError("plan_sha256 does not bind this session's plan")
    clip, source_fps = _validate_stratum(group, arm, clip, source_fps, rife)
    n = get_group(group)["n"]
    repeat_index = require_int(repeat_index, "repeat_index", minimum=1)
    if repeat_index > n:
        raise TrialSpecError("repeat_index %d exceeds cell n=%d"
                             % (repeat_index, n))
    g = GROUPS[group]
    spec = {
        "stage": STAGE,
        "session": SESSION,
        "group": group,
        "clip": clip,
        "arm": arm,
        "source_fps": source_fps,
        "rife": rife,
        "rife_output_fps": source_fps * 2 if rife == "on" else source_fps,
        "expected_rect": list(g["expected_rect"]),
        "output_size": list(g["output_size"]),
        "order_seed": ORDER_SEED,
        "media_seed": derive_media_seed(clip),
        "n": n,
        "repeat_index": repeat_index,
        "run_kind": run_kind,
        "plan_sha256": plan_sha256,
        "cell": "%s|%s|%s@%d|rife=%s" % (group, arm, clip, source_fps, rife),
        "generated_by": "%s (W1a)" % LIB_REL,
    }
    return validate_trial_spec(spec)


def validate_trial_spec(spec):
    """Strict validation of a trial spec dict (exact key set, strict types,
    derived fields recomputed and compared)."""
    if not isinstance(spec, dict):
        raise TrialSpecError("trial spec must be a dict")
    if set(spec) != set(SPEC_KEYS):
        missing = sorted(set(SPEC_KEYS) - set(spec))
        extra = sorted(set(spec) - set(SPEC_KEYS))
        raise TrialSpecError("trial spec keys mismatch; missing=%s extra=%s"
                             % (missing, extra))
    if spec["stage"] != STAGE or spec["session"] != SESSION:
        raise TrialSpecError("stage/session mismatch: %r/%r"
                             % (spec["stage"], spec["session"]))
    group = get_group(spec["group"])
    if spec["arm"] not in group["arms"]:
        raise TrialSpecError("arm %r not in group %r"
                             % (spec["arm"], spec["group"]))
    clip_spec = get_clip(spec["clip"])
    source_fps = require_int(spec["source_fps"], "source_fps", minimum=1)
    if source_fps != clip_spec["fps"]:
        raise TrialSpecError("source_fps mismatch with clip")
    if spec["rife"] not in ("off", "on"):
        raise TrialSpecError("rife must be off/on")
    expected_out = source_fps * 2 if spec["rife"] == "on" else source_fps
    if require_int(spec["rife_output_fps"], "rife_output_fps") != expected_out:
        raise TrialSpecError("rife_output_fps mismatch")
    clip2, fps2 = _validate_stratum(spec["group"], spec["arm"], spec["clip"],
                                    source_fps, spec["rife"])
    if (clip2, fps2) != (spec["clip"], source_fps):
        raise TrialSpecError("stratum revalidation mismatch")
    for field in ("expected_rect", "output_size"):
        value = spec[field]
        if (not isinstance(value, list) or len(value) != 2
                or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
                       for v in value)):
            raise TrialSpecError("%s must be [w, h] positive ints" % field)
    if list(spec["expected_rect"]) != list(group["expected_rect"]):
        raise TrialSpecError("expected_rect does not match group registry")
    if list(spec["output_size"]) != list(group["output_size"]):
        raise TrialSpecError("output_size does not match group registry")
    require_int(spec["order_seed"], "order_seed", minimum=0)
    if spec["order_seed"] != ORDER_SEED:
        raise TrialSpecError("order_seed must be the preregistered %d"
                             % ORDER_SEED)
    if require_int(spec["media_seed"], "media_seed", minimum=0) != \
            derive_media_seed(spec["clip"]):
        raise TrialSpecError("media_seed does not match SHA derivation")
    n = require_int(spec["n"], "n", minimum=1)
    if n != group["n"]:
        raise TrialSpecError("n does not match group registry")
    repeat = require_int(spec["repeat_index"], "repeat_index", minimum=1)
    if repeat > n:
        raise TrialSpecError("repeat_index > n")
    if spec["run_kind"] == "production":
        raise ProductionLockedError("production run specs are locked")
    if spec["run_kind"] not in ALLOWED_RUN_KINDS:
        raise TrialSpecError("run_kind not allowed: %r" % spec["run_kind"])
    require_sha256_hex(spec["plan_sha256"], "plan_sha256")
    if spec["plan_sha256"] != PLAN_SHA256:
        raise TrialSpecError("plan_sha256 does not bind this session's plan")
    cell = "%s|%s|%s@%d|rife=%s" % (spec["group"], spec["arm"], spec["clip"],
                                    source_fps, spec["rife"])
    if spec["cell"] != cell:
        raise TrialSpecError("cell key mismatch")
    get_cell(cell)  # must be one of the preregistered cells
    if not isinstance(spec["generated_by"], str) or not spec["generated_by"]:
        raise TrialSpecError("generated_by must be non-empty str")
    return spec


def required_input_rels(spec):
    """Repo-relative input bindings every trial depends on: the plan JSON,
    this generator library, and the clip's media manifest (created later in
    the create-only evidence tree by the media builder)."""
    spec = validate_trial_spec(spec)
    media_manifest = "docs/验证/开发/p4-001/media/%s/media-manifest.json" % spec["clip"]
    return [PLAN_REL, LIB_REL, media_manifest]


def verify_required_inputs(spec, root=None):
    """Fail-closed check that every required input exists under root."""
    rels = required_input_rels(spec)
    missing = []
    for rel in rels:
        try:
            target = resolve_under_root(rel, root)
        except PathContractError:
            raise
        if not os.path.lexists(str(target)):
            missing.append(rel)
    if missing:
        raise MissingInputError("missing required input bindings: %s"
                                % ", ".join(missing))
    return {"ok": True, "checked": rels}


# ---------------------------------------------------------------------------
# API self-description (for tests + handoff)
# ---------------------------------------------------------------------------

PUBLIC_EXCEPTIONS = ("P4ContractError", "PathContractError",
                     "ValueContractError", "TrialSpecError", "CreateOnlyError",
                     "ProductionLockedError", "ScheduleBudgetError",
                     "MissingInputError")


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
