# -*- coding: utf-8 -*-
"""p3_verify.py — P3 (p3-001) 35-ID objective case harness (real mpv + IPC).

Serial case-harness writer deliverable (docs/P3/P3验证工具中断接续brief-v1.json;
schema contract:
docs/验证/开发/p3-001/verifier-build/evidence-tools-contract.json).  Covers
ALL 35 P3 REQUIRED ids (taskflows/p3_guard.py REQUIRED ==
tools/p1_check_evidence.py P3_REQUIRED_IDS):

  * 20 P2-frozen ids are REUSED read-only from tools/p2_verify.py /
    tools/p1_verify.py case functions on the CURRENT P3 candidate sources —
    the frozen P2 harness file is never modified, no old behaviour is
    deleted or skipped (121+ unit behaviours stay intact; UNIT-P2-01
    re-runs the whole suite live);
  * 15 P3 ids are implemented here:
      - SHD-05  NIS compute port (32x24/256, two 2x64 rgba32f coefficient
                textures byte-identical to the forensic evidence, bounds
                guard AFTER all barriers, //!WHEN preserved; real upscale
                pass at a non-block-divisible 1366x768 target + honest
                <=1x skipped-when variants; no NVSharpen stacking);
      - SHD-06  xBR-lv2 MAIN RGB port (21 reference taps audited, 3x
                prescale mode declared, never xBRZ; RGB pixel oracle vs
                the independently re-derived CPU replica AND a bilinear
                baseline on an exactly-3x window; yuv-source presence;
                downscaled-window still-pass variant);
      - SHD-07  Sharp Bilinear AUTO vs manual 2x (floor formula real
                hardware LINEAR sampling, CPU golden via the reference
                coordinate mapping, degenerate floor=1 -> plain bilinear,
                scale0 clamp, pixel oracles; menu/labels are NOT accepted
                as effect proof);
      - SHD-09  real 8bit AND 10bit decode identity for every NEW gear
                (nis/xbr/sharpbilinear/sharpbilinear2x/integer), same-
                moment pixelformat recorded, never claimed without decode;
      - SHD-10/11  per-gear RGB / HDR guard matrix including the P3 gears
                (nis LUMA guard; xbr/sharp MAIN RGB-capable; INDEPENDENT
                HDR guard with distinct wording; integer/nearest
                unaffected; HDR evidence = vf metadata override on a
                synthetic SDR source, explicitly annotated, never an HDR
                encode, no quality claims);
      - GEO-02  Integer letterbox (fullscreen 1080->1440p k=1 bars
                320/180 with OSD-free fallback scan honestly flagged;
                720p->1440p k=2 full; k<1 normal downscale, no crop;
                same-process loadfile 1080->720 with k 1->2 + epoch
                advance — never stale-k empty truth);
      - GEO-03 Integer x nearest strict pixel blocks (block-uniformity
                oracle) against a baseline control capture;
      - GEO-04 window resize/DPI machine part (resize -> k/epoch recompute
                with a recorded pause-blip fallback), external zoom/GLSL
                priority (plugin yields, external values kept), Integer->
                shader transfer and Off with ZERO geometry residue;
      - GEO-05 rotate/crop effective display geometry (k derived from the
                OBSERVED video-out-params dw/dh each phase; crop via
                video-crop; phases all state=active+integer — never the
                run-001 stale-k empty truth);
      - GEO-06 SAR non-square (A2:1 synthetic source; k must use dw/dh,
                dw != w asserted; display aspect preserved);
      - WINDOW-01 resize/pause/aspect/loadfile/restart chain health with
                structured same-moment + render-freshness records;
      - PER-04-COMPUTE  compute backend feasibility + RAW fresh/redraw GPU
                ns samples + samples_note (NEVER a performance-gain claim;
                RIFE competition explicitly untested, left to P4);
      - UNIT-P3-01  the P3 pure-function unit suites re-run for real;
      - EVI-01  the evidence machine gate exercised against itself: a full
                positive-control mini evidence tree must pass cleanly, and
                each of the 10 canonical negative classes must be really
                planted in a throwaway sandbox and DETECTED by
                tools/p3_check_evidence.py (never planted inside the
                evidence directory).

Contract obligations honoured for every PASS claim:
  * structured same-moment records (p3_lib.same_moment_sample producer
    shape) for every SAME_MOMENT_CASE id — decode identity + geometry +
    vo-passes frame counts in ONE observation window (VL-F1 closure);
  * render freshness won ONLY by vo-passes fresh increase / forced redraw
    / new output pixels — decoder liveness never backfills an active
    claim; freshness.chain_epoch is paired with the variant's chain_epoch;
  * Integer geometry records the NATIVE video-unscaled readback type
    (bool true/false, never "yes"/"no" strings — CORE-R1);
  * desc presence = structured desc_evidence{count, sample_hits} whose
    excerpt lines are verbatim substrings of the case's real session
    console/mpv.log bytes (fabricated samples impossible; 'user shader'
    substring counting is never used for product gears);
  * screenshots are registered with true decoded dimensions (p3_lib
    stdlib PNG decoder honouring real bit depth) and duplicate-content
    PNG groups are honestly listed as non-corroborative.

Runner discipline (same as p1/p2 verify, no relaxations):
  * --evidence-dir must be a FRESH directory inside the session tree;
    reuse is refused BEFORE any mpv starts; there is no --force;
  * every artifact is create-only; failures are recorded as FAIL and
    never silently retried into PASS; a case without a real executed
    result is never PASS; real product bugs are reported (REWORK), the
    oracle is never loosened to pass;
  * live configuration written = false; only throwaway temp configs with
    sandboxed HOME/APPDATA/TEMP, credential-free child env, self-spawned
    PIDs only; D:/MPV/mpv.exe directly with gpu-next/vulkan (mpv.com
    wrapper never used);
  * fullscreen is passed AFTER mpv_session start()'s hardcoded
    --fullscreen=no on the command line (last-wins), and every fullscreen
    case READS BACK fullscreen==true + osd 2560x1440 and checks the real
    window PNG size — a conf-only write never counts (run-001 root cause);
  * this build role runs the tool build plus small per-feature smokes; the
    full 35-ID long GPU matrix belongs to the independent read-only
    author-verification role downstream.

Usage:
    python -X utf8 tools/p3_verify.py --list
    python -X utf8 tools/p3_verify.py --all  --session p3-001 \
        --evidence-dir docs/验证/开发/p3-001/implementer/full-r1
    python -X utf8 tools/p3_verify.py --only SHD-05,GEO-02 --session p3-001 \
        --evidence-dir docs/验证/开发/p3-001/implementer/smoke-shd05
    python -X utf8 tools/p3_verify.py --probe --session p3-001 \
        --evidence-dir docs/验证/开发/p3-001/implementer/probe-r1

Downstream gate (independent role):
    python -X utf8 tools/p3_check_evidence.py \
        --evidence-dir <dir> --session p3-001 [--require-tests] [--write-gate]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1_lib as lib          # noqa: E402
import p2_lib as p2           # noqa: E402
import p3_lib as p3           # noqa: E402
import p1_verify as p1v       # noqa: E402  (read-only reuse of scaffolding)
import p2_verify as p2v       # noqa: E402  (read-only reuse of P2 cases)
import p3_check_evidence as gate  # noqa: E402  (EVI-01 sandbox target)

SESSION = "p3-001"
STAGE = "P3"
P3_REQUIRED_IDS = list(gate.P3_REQUIRED_IDS)

# P2-frozen ids reused READ-ONLY from the frozen p2_verify/p1_verify harness
# (window/SHD-09/SHD-10/SHD-11 get P3-shaped supersets below because the P3
# checker demands structured same-moment / bitdepth / P3-guard evidence that
# the frozen P2 case output predates; their P2 semantics are preserved
# inside the P3 implementations).
REUSED_P2_IDS = [
    "CTL-01", "CTL-02", "CTL-03", "CTL-04", "CTL-05", "CTL-06", "CTL-07",
    "CTL-08", "CTL-09",
    "SHD-01", "SHD-02", "SHD-03", "SHD-04", "SHD-08", "SHD-12", "SHD-13",
    "GEO-01", "GEO-07", "PIC-05", "UNIT-P2-01",
]
P3_WRITTEN_IDS = [
    "SHD-05", "SHD-06", "SHD-07", "SHD-09", "SHD-10", "SHD-11",
    "GEO-02", "GEO-03", "GEO-04", "GEO-05", "GEO-06",
    "WINDOW-01", "PER-04-COMPUTE", "UNIT-P3-01", "EVI-01",
]
assert sorted(REUSED_P2_IDS + P3_WRITTEN_IDS) == sorted(P3_REQUIRED_IDS), \
    "harness id partition must equal the frozen 35-id required set"

# The pinned real fullscreen desktop (read back and verified per case; the
# value is also cross-checked against the actual osd-dimensions at runtime).
DISP_W, DISP_H = 2560, 1440

# Real shader resources installed byte-identically into each isolated config
# (src/dst sha256 both recorded as inputsha evidence; activation pre-checks
# need the files to exist under ~~/shaders/).
SHADER_RESOURCES = [
    "shaders/p3-NIS.glsl", "shaders/p3-xBR-lv2.glsl",
    "shaders/p3-Sharp-Bilinear-AUTO.glsl", "shaders/p3-Sharp-Bilinear-2x.glsl",
    "shaders/p2-FSR1.glsl", "shaders/p2-SGSR1.glsl",
]
GEAR_CHAIN_SHADER = {
    "nis": "p3-NIS.glsl",
    "xbr": "p3-xBR-lv2.glsl",
    "sharpbilinear": "p3-Sharp-Bilinear-AUTO.glsl",
    "sharpbilinear2x": "p3-Sharp-Bilinear-2x.glsl",
    "fsr1": "p2-FSR1.glsl",
}
GEAR_DESC_KEYWORDS = {
    "nis": p3.NIS_DESC_KEYWORDS,
    "xbr": p3.XBR_DESC_KEYWORDS,
    "sharpbilinear": p3.SHARP_AUTO_DESC_KEYWORDS,
    "sharpbilinear2x": p3.SHARP_2X_DESC_KEYWORDS,
}
MANAGED_SNAPSHOT_PROPS = ["video-unscaled", "video-zoom", "scale", "cscale",
                          "dscale", "glsl-shaders"]

METADATA_OVERRIDE_NOTE = p2v.METADATA_OVERRIDE_NOTE

SOURCE_PINS = [
    "scripts/scale-selector.lua", "script-opts/scale-selector-gears.conf",
    "shaders/p3-NIS.glsl", "shaders/p3-xBR-lv2.glsl",
    "shaders/p3-Sharp-Bilinear-AUTO.glsl", "shaders/p3-Sharp-Bilinear-2x.glsl",
    "shaders/p3-resource-manifest.json",
    "tools/p1_lib.py", "tools/p2_lib.py", "tools/p3_lib.py",
    "tools/p1_verify.py", "tools/p2_verify.py", "tools/p3_verify.py",
    "tools/p3_check_evidence.py",
]


# ---------------------------------------------------------------------------
# runner console tee
# ---------------------------------------------------------------------------

class RunnerConsole:
    """Runner progress console, teed to stdout AND
    <evidence-dir>/runner.console.txt (create-only; pinned later by
    manifest-verify.json — the checker's closed exclusion class)."""

    def __init__(self, evidence_dir: Path):
        self.path = evidence_dir / "runner.console.txt"
        self._fh = open(self.path, "xb")

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self._fh.write((line + "\n").encode("utf-8", errors="replace"))
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def relp(p) -> str:
    """Canonical repo-relative POSIX path (evidence lives inside the repo)."""
    return Path(p).resolve().relative_to(lib.REPO_ROOT).as_posix()


# ---------------------------------------------------------------------------
# shared P3 case context (isolated env with the real P3 resources)
# ---------------------------------------------------------------------------

# Every MpvSession this harness spawns is registered here so the runner can
# sweep orphans after each case (own PIDs only).  Lesson from smoke-r3: an
# exception raised inside a case's finally (create-only transcript collision)
# skipped the cleanup and left an mpv alive; the NEXT run's identical pipe name
# then connected to the STALE instance and recorded its state (r4's SHD-10/11
# "already active" reads were r3's orphan).  create-only discipline: a rerun
# with a lingering same-named pipe is a hard error, never silent reuse.
_ALL_SESSIONS: list = []


def sweep_orphan_sessions(console=None) -> list:
    killed = []
    for s in list(_ALL_SESSIONS):
        proc = getattr(s, "proc", None)
        if proc is not None and proc.poll() is None:
            try:
                s.kill()
                killed.append(getattr(s, "case_name", str(s)))
            except Exception:  # noqa: BLE001
                pass
        try:
            _ALL_SESSIONS.remove(s)
        except ValueError:
            pass
    if killed and console is not None:
        console.log(f"orphan session sweep (own PIDs only): {killed}")
    return killed


def write_y4m(path: Path, w: int, h: int, frames: int = 48,
              ten_bit: bool = False, sar: str | None = None) -> Path:
    """Pure stdlib synthetic moving-band y4m writer (V3-M2 root-cause fix).

    ten_bit=False -> C420jpeg 8-bit, byte layout UNCHANGED from the frozen
    harness (P1-compatible luma bands 30/200, chroma 80/140).
    ten_bit=True  -> C420p10 with REAL little-endian 16-bit words for ALL
    three planes (10-bit samples 0..1023: luma bands 120/920 with the same
    16-px moving pattern and ^0x141 detail bit, chroma u=513/v=608 exactly
    like the frozen P2 writer) and EXACT 2x plane lengths.  The old draft
    wrote an 8-bit body under a C420p10 header; a decoder may still swallow
    that, so the old SHD-09 PASS is invalid as bit-depth proof and the unit
    byte-oracle tests reject any relabelled-8bit file by construction.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    aspect = sar or "1:1"
    comp = "C420p10" if ten_bit else "C420jpeg"
    half_w, half_h = w // 2, h // 2
    with open(path, "wb") as f:
        f.write(f"YUV4MPEG2 W{w} H{h} F24:1 Ip A{aspect} {comp}\n"
                .encode("ascii"))
        if ten_bit:
            u_plane = int.to_bytes(513, 2, "little") * (half_w * half_h)
            v_plane = int.to_bytes(608, 2, "little") * (half_w * half_h)
        else:
            u_plane = bytes([80] * (half_w * half_h))
            v_plane = bytes([140] * (half_w * half_h))
        for i in range(frames):
            f.write(b"FRAME\n")
            phase = i % 2
            y = bytearray(w * h * (2 if ten_bit else 1))
            stride = w * (2 if ten_bit else 1)
            for yy in range(h):
                band = (yy // 16 + phase) & 1
                base = (120 + (800 if band else 0)) if ten_bit \
                    else (30 + (200 if band else 0))
                for xx in range(w // 16):
                    val = base if (xx + i) % 2 == 0 \
                        else base ^ (0x141 if ten_bit else 0x50)
                    run = (int.to_bytes(val, 2, "little") * 16) if ten_bit \
                        else (bytes([val]) * 16)
                    y[yy * stride + xx * len(run):
                      yy * stride + xx * len(run) + len(run)] = run
            f.write(bytes(y))
            f.write(u_plane)
            f.write(v_plane)
    return path


class P3Context:
    """Isolated env with the real P3/P2 shader resources, product gears conf,
    external-yield stub shaders and stdlib-synthetic media (8/10bit, SAR).
    Modeled on the proven core-checks run-004 start_case() plumbing, bound to
    the create-only evidence directory."""

    def __init__(self, ev: lib.Evidence, label: str):
        self.evidence = ev
        self.label = label
        self.env = lib.make_env(label, session=SESSION)
        env = self.env
        env.write_mpv_conf(scale_baseline="bicubic")
        env.write_input_conf()
        env.write_scalar_opts()
        env.install_plugin(lib.PLUGIN_LUA)
        env.write_gears_conf(lib.GEARS_CONF.read_text(encoding="utf-8"))
        # byte-identical shader resources (inputsha evidence; activation
        # pre-check requires the files to exist in the isolated cfg)
        self.inputsha: dict = {}
        for rel in SHADER_RESOURCES:
            src = lib.REPO_ROOT / rel
            dst = env.cfg / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            payload = src.read_bytes()
            dst.write_bytes(payload)
            src_sha = lib.sha256_bytes(payload)
            dst_sha = lib.sha256_file(dst)
            self.inputsha[rel] = {"src_sha256": src_sha, "dst_sha256": dst_sha,
                                  "match": src_sha == dst_sha,
                                  "bytes": len(payload)}
            env.inputs[rel] = dst_sha
        # real loadable external shader for external-change/yield variants
        env.write_stub_shaders(["p1-test-ext-a"])
        self.media = None
        self.media_sha = None
        self.session = None

    # -- media -------------------------------------------------------------
    def make_y4m(self, name: str, w: int, h: int, frames: int = 48,
                 ten_bit: bool = False, sar: str | None = None) -> Path:
        """stdlib-synthetic moving-band y4m (8bit C420jpeg / 10bit REAL LE16
        C420p10 via the pure write_y4m writer, optional non-square SAR header
        A<w>:<h> for GEO-06).  The FIRST media created becomes the default
        start media (explicit start media_path= overrides for multi-clip
        cases)."""
        path = write_y4m(self.env.root / "media" / name, w, h, frames,
                         ten_bit=ten_bit, sar=sar)
        self.media_sha = lib.sha256_file(path)
        if self.media is None:
            self.media = path
        self.env.inputs[f"media/{name}"] = self.media_sha
        return path

    def make_ppm(self, name: str, w: int, h: int,
                 quadrants: bool = True) -> tuple:
        """RGB sample for the pixel oracles; returns (path, rows).  A STILL
        image: mpv renders it once, so presence/freshness claims must come
        from the motion (y4m) variants, never from a still variant.  The
        dot-free quadrant pattern keeps the flat interior genuinely flat."""
        path = self.env.root / "media" / name
        if quadrants:
            sha, rows = generate_ppm_quadrants(path, w, h)
        else:
            sha, rows = p3.generate_ppm_pattern(path, w, h)
        self.media_sha = sha
        if self.media is None:
            self.media = path
        self.env.inputs[f"media/{name}"] = sha
        self.ppm_rows = rows
        return path, rows

    # -- sessions ----------------------------------------------------------
    def start(self, variant: str, window: tuple | None = None,
              fullscreen: bool = False, extra_args: list | None = None,
              media_path: Path | None = None):
        name = f"{self.label}-{variant}"
        pipe = f"{lib.PIPE_NAMESPACE}{SESSION}-{name}-ipc"
        try:
            probe = open(pipe, "r+b")
            probe.close()
        except OSError:
            pass
        else:
            # a live server already owns this pipe name: a stale orphaned mpv
            # from an earlier interrupted run (smoke-r3/r4 lesson — connecting
            # to it would record ANOTHER process's state as this case's).
            raise FileExistsError(
                f"陈旧 IPC 管道已存在（疑似此前中断遗留的 mpv 孤儿）: {pipe}; "
                "请先清理孤儿进程并改用全新证据目录")
        self.session = lib.MpvSession(self.env, name, self.evidence.dir,
                                      session=SESSION)
        _ALL_SESSIONS.append(self.session)
        args = ["--no-border", "--osd-duration=800", "--osc=no",
                "--loop-file=inf"]
        if fullscreen:
            # mpv keeps the LAST occurrence of an option: start() hardcodes
            # --fullscreen=no, so appending --fullscreen=yes here is what
            # actually engages fullscreen (run-001 root cause; conf alone
            # never counts — read-back gates verify it below).
            args.append("--fullscreen=yes")
        if window:
            args.append(f"--geometry={window[0]}x{window[1]}")
        args += extra_args or []
        self.session.start(media=media_path if media_path is not None
                           else self.media, extra_args=args)
        return self.session

    def save_inputsha(self) -> dict | None:
        if not self.inputsha:
            return None
        p = self.evidence.write_json(
            f"{self.label}.inputsha.json",
            {"note": "隔离 cfg 的真实 shader 资源字节级副本（src/dst sha 一致）",
             "resources": self.inputsha,
             "media_sha256": self.media_sha})
        return relp(p)

    def cleanup(self):
        if self.session is not None and self.session.proc is not None \
                and self.session.proc.poll() is None:
            self.session.kill()
        self.env.cleanup()


# ---------------------------------------------------------------------------
# shared probes (structure-contract producers)
# ---------------------------------------------------------------------------

def native_unscaled(s) -> dict:
    """CORE-R1 witness: the NATIVE video-unscaled readback value AND type."""
    v = s.get("video-unscaled")
    return {"value": v, "native_type": type(v).__name__}


def native_bool_ok(nb: dict, want: bool) -> bool:
    return (nb.get("native_type") == "bool" and nb.get("value") is want)


def fullscreen_gate(s, timeout_s: float = 20.0) -> dict:
    """Fullscreen is only real when READ BACK: fullscreen==true AND the true
    window/osd output rectangle 2560x1440 (never a conf-write claim)."""
    ok = s.wait_until(lambda: s.get("osd-width") == DISP_W
                      and s.get("osd-height") == DISP_H, timeout_s)
    fs = s.get("fullscreen")
    osd = {"w": s.get("osd-width"), "h": s.get("osd-height")}
    return {"fullscreen_property": fs, "osd": osd, "expected": [DISP_W, DISP_H],
            "ok": bool(ok and fs is True
                       and osd["w"] == DISP_W and osd["h"] == DISP_H)}


def window_gate(s, w: int, h: int, timeout_s: float = 15.0) -> dict:
    ok = s.wait_until(lambda: s.get("osd-width") == w
                      and s.get("osd-height") == h, timeout_s)
    return {"expected": [w, h], "osd": {"w": s.get("osd-width"),
                                        "h": s.get("osd-height")},
            "ok": bool(ok)}


def wait_video_out_params(s, timeout_s: float = 20.0,
                          need_gamma: bool = False) -> bool:
    """V3-M1: loaded/off is NOT media ready — video-out-params can still be
    empty right after wait_state(off) (a still decodes asynchronously;
    leader-r8 recorded pixfmt empty / gamma None).  Wait for the REAL decode
    identity — non-empty pixelformat plus source w/h, and gamma in pq/hlg
    where the case requires it — BEFORE any same-moment decode/guard
    sampling.  Metadata is read back, never invented."""
    def ready() -> bool:
        vop = s.get("video-out-params") or {}
        base = bool(vop.get("pixelformat")) and bool(vop.get("w")) \
            and bool(vop.get("h"))
        if need_gamma:
            return bool(base) and vop.get("gamma") in ("pq", "hlg")
        return bool(base)
    return bool(s.wait_until(ready, timeout_s))


def force_present_still(s) -> None:
    """Still-image repaint countermeasure (the documented pause blip, same
    lever as wait_osd_gone): a still renders ONCE, so after a shader switch
    the vo-pass may still be the PRIOR gear's — pause True/False forces one
    genuine re-present under the CURRENT glsl chain before DESC/samples are
    read.  Never touches the product controller."""
    s.set("pause", True)
    time.sleep(0.25)
    s.set("pause", False)
    time.sleep(0.5)


def wait_desc_pass_samples(s, keywords, timeout_s: float = 12.0) -> dict:
    """V3-M1: a shader switch races the OLD/no vo-pass — the gear's DESC
    keywords must appear in a pass WITH non-empty GPU samples (p1_verify
    honest hit map) before the evidence is sampled, and the chain_epoch at
    that moment must be stable (exact gear's own epoch; no prior-pass
    sampling so xBR/Sharp2x never inherit another pass's samples)."""
    epoch_before = s.ud("chain_epoch")
    hits_ok = s.wait_until(
        lambda: bool(keywords)
        and all(p1v.desc_sample_hits(s, keywords).values()), timeout_s)
    hits = p1v.desc_sample_hits(s, keywords)
    epoch_after = s.ud("chain_epoch")
    return {"desc_hits": hits,
            "all_desc_with_samples": bool(hits_ok),
            "chain_epoch_before": epoch_before,
            "chain_epoch_at_samples": epoch_after,
            "epoch_stable": epoch_before == epoch_after}


def snapshot_props(s) -> dict:
    return {p: s.get(p) for p in MANAGED_SNAPSHOT_PROPS}


def residue_vs_baseline(after: dict, baseline: dict) -> list:
    """Zero-residue comparison after Off/transfer; cscale==0 is the documented
    'follow scale' sentinel (allowed to restore to the baseline scale)."""
    residue = []
    for p in MANAGED_SNAPSHOT_PROPS:
        a, b = after.get(p), baseline.get(p)
        if p == "cscale" and (b in (0, "0", None)):
            if a == b or a == baseline.get("scale"):
                continue
        if a != b:
            residue.append(f"{p}={a!r}!={b!r}")
    return residue


def dump_transcript(ev: lib.Evidence, s) -> str:
    name = f"{s.case_name}.mpv.transcript.jsonl"
    target = ev.dir / name
    try:
        tr = list(s.ipc.transcript)
    except Exception:  # noqa: BLE001 — transcript loss is recorded, not hidden
        tr = [{"note": "transcript unavailable"}]
    try:
        p = ev.save_transcript(name, tr)
    except FileExistsError:
        # already collected by this case (e.g. p1v.save_session_artifacts);
        # create-only discipline: never overwrite, never duplicate-write
        return relp(target) if target.exists() else name
    return relp(p)


def wait_osd_gone(s, blip: bool = False):
    """The plugin pins its activation OSD to 3 seconds (mp.osd_message text,3)
    — every pixel screenshot must wait it out; the optional pause blip also
    forces one fresh present so a frozen stale OSD cannot survive."""
    time.sleep(3.6)
    if blip:
        s.set("pause", True)
        time.sleep(0.25)
        s.set("pause", False)
        time.sleep(1.5)   # pause OSD indicator lasts ~0.8s (--osd-duration)


def activate(s, gear: str) -> dict:
    ok = s.navigate_and_activate(gear)
    reached = s.wait_state("active", 8.0) and s.ud("gear") == gear
    verified = s.wait_until(lambda: s.ud("chain_verified") is True, 12.0)
    return {"navigated": bool(ok), "state_active": bool(reached),
            "state": s.ud("state"), "gear": s.ud("gear"),
            "chain_verified": bool(verified),
            "chain_verified_raw": s.ud("chain_verified"),
            "reason": s.ud("reason")}


def chain_files(s) -> list:
    return list(s.ud("gear_chain") or [])


def state_facts(s) -> dict:
    return {
        "state": s.ud("state"), "gear": s.ud("gear"),
        "chain_verified": s.ud("chain_verified"),
        "chain_epoch": s.ud("chain_epoch"),
        "skip_note": s.ud("skip_note"), "reason": s.ud("reason"),
        "integer_k": s.ud("integer_k"),
        "chain_keywords": s.ud("chain_keywords"),
    }


def vo_passes_totals(s) -> tuple:
    vp = s.get("vo-passes") or {}
    totals = {}
    descs = []
    for frame in ("fresh", "redraw"):
        total = 0
        for item in (vp.get(frame) or []):
            if isinstance(item, dict):
                total += int(item.get("count") or 0)
                if isinstance(item.get("desc"), str):
                    descs.append(item)
        totals[frame] = total
    return totals, descs


def decoded_pixel_diff(dec_a: dict, dec_b: dict, max_points: int = 8192) -> dict:
    """VL3-01 (r2): compare DECODED RGB pixels of two captures — NEVER raw
    PNG bytes (a metadata/compression-only byte difference is not a new
    rendered output).  Requires identical dimensions AND identical true bit
    depth (both from the real stdlib decoder); pixels are then compared on a
    deterministic stride grid (bounded sample count, no randomness)."""
    res = {"same_dimensions": (dec_a.get("w"), dec_a.get("h"))
           == (dec_b.get("w"), dec_b.get("h")),
           "same_bitdepth": dec_a.get("bitdepth") == dec_b.get("bitdepth"),
           "compared_points": 0, "differing_points": 0,
           "max_channel_delta": None, "sample_stride": None}
    if not (res["same_dimensions"] and res["same_bitdepth"]):
        res["reason"] = ("尺寸/真实位深不一致——解码像素比较无定义，"
                         "绝不能凭 PNG 字节差异冒充新像素")
        return res
    w, h = dec_a["w"], dec_a["h"]
    ga, gb = dec_a["get_pixel"], dec_b["get_pixel"]
    area = max(1, w * h)
    stride = max(1, int(math.isqrt(max(1, area // max(1, max_points)))))
    res["sample_stride"] = stride
    diff_points = 0
    compared = 0
    max_delta = 0
    for y in range(0, h, stride):
        for x in range(0, w, stride):
            pa, pb = ga(x, y), gb(x, y)
            compared += 1
            d = max(abs(ca - cb) for ca, cb in zip(pa, pb))
            if d:
                diff_points += 1
                max_delta = max(max_delta, d)
    res["compared_points"] = compared
    res["differing_points"] = diff_points
    res["max_channel_delta"] = max_delta
    res["pixels_identical"] = diff_points == 0
    return res


def fresh_pixel_change(dec_a: dict, dec_b: dict) -> tuple:
    """Verdict pair (new_pixels, diff): True only when the two real decodes
    share dimensions/bit depth AND at least one sampled decoded RGB pixel
    differs.  Metadata/compression-only byte changes return False."""
    diff = decoded_pixel_diff(dec_a, dec_b)
    ok = bool(diff.get("same_dimensions") and diff.get("same_bitdepth")
              and diff.get("differing_points", 0) > 0)
    return ok, diff


def controlled_frame_step_leg(s, ev: lib.Evidence, case: str) -> dict:
    """VL3-01 (r2) controlled source-frame change leg.

    Replaces the blind 0.5s re-capture byte-hash fallback, which had BOTH
    flaws: (a) the parity-period synthetic pattern aliases at 24 fps — two
    captures 12 frames apart show the same pixels even while the source
    presents (false negative), and (b) unequal PNG bytes alone could be
    metadata/compression-only (false positive).

    Procedure (all IPC commands recorded verbatim; NO managed zoom/
    video-unscaled writes — those would trip the plugin's external-yield
    path and contaminate the very claim under test):
      1. blind pair while playing, 0.5s apart — decoded-pixel compared and
         recorded ONLY as the repeated-pattern alias witness (never proof);
      2. ACTUAL pause state readback -> pause set -> paused readback;
      3. sleep > --osd-duration (OSD cleared), same-moment snapshot of
         source/gear/chain_epoch/video-out-params, capture A;
      4. exact IPC frame-step (seek fallback, both recorded) advances the
         synthetic source to the ADJACENT frame;
      5. sleep > --osd-duration, post snapshot (stability vs pre), capture B;
      6. decoded RGB pixel comparison of A/B decides new-output-pixels;
      7. FINALLY: pause restored to the read-back original state + readback.
    time-pos / estimated-vf-fps are recorded as witnesses only and can never
    prove freshness by themselves."""
    leg = {"leg": "controlled-frame-step", "new_output_pixels": False,
           "stability_ok": False, "pixel_diff": None,
           "png_bytes_differ_but_pixels_identical": None,
           "blind_alias_witness": None, "ipc_records": [],
           "pause_control": {}, "witnesses": {}, "artifact_notes": [],
           "screenshot_files": []}

    def snap():
        vop = s.get("video-out-params") or {}
        return {"path": s.get("path"), "gear": s.ud("gear"),
                "chain_epoch": s.ud("chain_epoch"),
                "pixelformat": vop.get("pixelformat"),
                "vop_wh": [vop.get("w"), vop.get("h")],
                "time_pos": s.get("time-pos"),
                "estimated_vf_fps": s.get("estimated-vf-fps")}

    blind_a = ev.dir / f"{case}.fresh-a.png"
    blind_b = ev.dir / f"{case}.fresh-b.png"
    step_a = ev.dir / f"{case}.step-a.png"
    step_b = ev.dir / f"{case}.step-b.png"

    def shot_ref(p: Path) -> str:
        """Repo-relative when possible (real evidence trees); absolute POSIX
        fallback for non-repo locations (unit fakes / sandboxes)."""
        try:
            return relp(p)
        except ValueError:
            return Path(p).resolve().as_posix()

    # -- blind 0.5s pair: recorded as the ALIAS witness, never as proof ----
    try:
        if s.screenshot(blind_a, mode="window"):
            time.sleep(0.5)
            if s.screenshot(blind_b, mode="window"):
                try:
                    ok_blind, d_blind = fresh_pixel_change(
                        p3.decode_png(blind_a.read_bytes()),
                        p3.decode_png(blind_b.read_bytes()))
                    leg["blind_alias_witness"] = {
                        "new_pixels": ok_blind, "pixel_diff": d_blind,
                        "note": ("盲采 0.5s≈12帧(24fps) 与合成源奇偶周期对齐——"
                                 "即使源在呈现也可能同像素；此对照仅解释为何需要"
                                 "受控帧步进，绝不作为新鲜度证明")}
                    leg["screenshot_files"] += [shot_ref(blind_a),
                                                shot_ref(blind_b)]
                except (ValueError, OSError) as exc:
                    leg["artifact_notes"].append(f"blind decode failed: {exc}")
    except FileExistsError:
        leg["artifact_notes"].append("blind pair pre-existed (create-only: "
                                     "kept, not overwritten; witness skipped)")

    # -- controlled pause -> step -> compare -> restore ---------------------
    pause0 = s.get("pause")            # ACTUAL pause state readback
    leg["pause_control"]["pause_before"] = pause0
    ok_a = ok_b = False
    pre = post = None
    try:
        s.set("pause", True)
        s.wait_until(lambda: s.get("pause") is True, 2.0)
        leg["pause_control"]["paused_readback"] = s.get("pause")
        time.sleep(1.1)                # > --osd-duration: OSD cleared
        pre = snap()
        ok_a = s.screenshot(step_a, mode="window")
        r_step = s.cmd("frame-step")   # exact adjacent synthetic frame
        leg["ipc_records"].append({"cmd": ["frame-step"],
                                   "error": r_step.get("error")})
        if r_step.get("error") != "success":
            r_seek = s.cmd("seek", "0.5", "relative")
            leg["ipc_records"].append({"cmd": ["seek", "0.5", "relative"],
                                       "error": r_seek.get("error")})
        time.sleep(1.1)                # > --osd-duration: OSD cleared
        post = snap()
        ok_b = s.screenshot(step_b, mode="window")
    except FileExistsError:
        leg["artifact_notes"].append("step pair pre-existed (create-only: "
                                     "kept, not overwritten; no pixel claim)")
    finally:
        s.set("pause", pause0)         # restore the READ-BACK original state
        restored = s.get("pause")
        leg["pause_control"]["pause_restored"] = restored
        leg["pause_control"]["restore_ok"] = bool(restored == pause0)

    leg["witnesses"] = {
        "pre": pre, "post": post,
        "note": ("time-pos/estimated-vf-fps/路径/档位/epoch 为同刻旁证；"
                 "时间属性绝不能单独证明渲染新鲜度")}
    if pre is not None and post is not None:
        leg["stability_ok"] = bool(
            pre["path"] == post["path"]          # same source
            and pre["gear"] == post["gear"]      # same gear
            and isinstance(pre["chain_epoch"], int)
            and pre["chain_epoch"] == post["chain_epoch"]  # same epoch
            and pre["pixelformat"] == post["pixelformat"]
            and pre["vop_wh"] == post["vop_wh"])  # native props stable
        leg["witnesses"]["epoch_stable"] = bool(
            pre["chain_epoch"] == post["chain_epoch"])
    if ok_a and ok_b:
        leg["screenshot_files"] += [shot_ref(step_a), shot_ref(step_b)]
        try:
            dec_a = p3.decode_png(step_a.read_bytes())
            dec_b = p3.decode_png(step_b.read_bytes())
            ok, diff = fresh_pixel_change(dec_a, dec_b)
            leg["pixel_diff"] = diff
            bytes_differ = (lib.sha256_file(step_a) != lib.sha256_file(step_b))
            if bytes_differ and not ok and diff.get("pixels_identical"):
                leg["png_bytes_differ_but_pixels_identical"] = True
                leg["artifact_notes"].append(
                    "负例对照成立：PNG 字节不同但解码像素相同（元数据/压缩差异）"
                    "——按 r2 契约必须判非新像素")
            leg["new_output_pixels"] = ok
        except (ValueError, OSError) as exc:
            leg["artifact_notes"].append(f"step decode failed: {exc}")
    return leg


def freshness_block(s, ev: lib.Evidence, case: str, gap_s: float = 1.3,
                    force_redraw: bool = True,
                    controlled: bool = False) -> tuple:
    """REAL render-freshness evidence for an ACTIVE claim.

    Samples vo-passes frame counts in one window, optionally forces a redraw
    (pause blip — the documented countermeasure against present stalls), then
    samples again.  Method selection is honest and exhaustive:
      * vo-passes-fresh-increase : fresh counter strictly increased;
      * forced-redraw            : redraw counter strictly increased after
                                   the pause blip (a real forced present);
      * new-output-pixels        : decoded RGB pixels of two window captures
                                   differ after a CONTROLLED source-frame
                                   step (0 -> 1 distinct rendered outputs —
                                   only ever set when real decoded pixels
                                   changed; PNG byte inequality alone is
                                   NEVER new pixels, VL3-01 r2).
    Counter growth stays a witness ONLY when true: vo-passes counts are
    bounded samplecount sums and can SATURATE, so frozen counters cannot
    alone prove a dead player.  Whenever counters are frozen (or the caller
    passes controlled=True, e.g. GEO-03), the controlled frame-step leg runs
    and decides; a still-dead player yields render_fresh=False -> the caller
    must FAIL the case; decoder activity/FPS/time-pos NEVER satisfies this.
    Returns (block, same_moment_a, same_moment_b)."""
    a = p3.same_moment_sample(s)
    blip = None
    if force_redraw:
        s.set("pause", True)
        time.sleep(0.25)
        s.set("pause", False)
        blip = True
    time.sleep(gap_s)
    b = p3.same_moment_sample(s)
    epoch = s.ud("chain_epoch")
    fb_a = a["vo_passes_frame_counts"]["fresh"]
    fb_b = b["vo_passes_frame_counts"]["fresh"]
    rd_a = a["vo_passes_frame_counts"]["redraw"]
    rd_b = b["vo_passes_frame_counts"]["redraw"]
    block = {"render_fresh": False, "method": None,
             "chain_epoch": epoch if isinstance(epoch, int) else -1,
             "fresh_before": None, "fresh_after": None,
             "forced_redraw_blip": bool(blip),
             "metric_note": ""}
    if fb_b > fb_a:
        block.update({"render_fresh": True,
                      "method": "vo-passes-fresh-increase",
                      "fresh_before": fb_a, "fresh_after": fb_b,
                      "metric_note": "vo-passes fresh 帧计数在采样窗内严格递增"})
        if not controlled:
            return block, a, b
    if rd_b > rd_a:
        block.update({"render_fresh": True, "method": "forced-redraw",
                      "fresh_before": rd_a, "fresh_after": rd_b,
                      "metric_note": "pause 一拍强制重绘后 redraw 计数严格递增"
                                     "（present 停摆场景的真实强制新帧证据）"})
        if not controlled:
            return block, a, b
    # VL3-01 (r2): counter-frozen is NOT proof of a dead player — vo-passes
    # counts are bounded samplecount sums that can saturate, and blind 0.5s
    # re-captures alias against the parity-period synthetic pattern.  The
    # CONTROLLED source-frame leg decides (or honestly keeps render_fresh
    # False; decoder liveness/FPS/time-pos can never backfill the claim).
    ctl = controlled_frame_step_leg(s, ev, case)
    block["controlled_leg"] = ctl
    pixel_ok = bool(ctl.get("new_output_pixels") and ctl.get("stability_ok"))
    if block["render_fresh"]:
        # controlled=True with true counter growth: the leg is recorded as
        # CORROBORATION only — the counter method is never overwritten.
        if pixel_ok:
            block["controlled_corroboration"] = (
                "受控帧步进解码 RGB 像素对照佐证成立（方法保持计数递增，不覆写）")
        return block, a, b
    if pixel_ok:
        block.update({"render_fresh": True,
                      "method": "new-output-pixels",
                      "fresh_before": 0, "fresh_after": 1,
                      "metric_note": ("IPC frame-step 控制源帧前进到相邻合成帧后，"
                                      "两次窗口捕获的解码 RGB 像素真实不同"
                                      "（新输出像素；计数语义=真实新输出帧事件 "
                                      "0→1，非伪造、非 PNG 字节哈希；"
                                      "源/档位/epoch 稳定已配对）"),
                      "counter_saturation_witness": {
                          "fresh": [fb_a, fb_b], "redraw": [rd_a, rd_b],
                          "note": ("计数为有界 samplecount 之和，可能饱和；"
                                   "采样窗内计数不动而受控帧步进产出新像素，"
                                   "二者并存即为饱和见证，不能反推播放器死亡")}})
        return block, a, b
    block["metric_note"] = ("呈现/链计数完全冻结且受控帧步进未能产出新解码像素"
                                f"（new_output_pixels={ctl.get('new_output_pixels')}, "
                                f"stability_ok={ctl.get('stability_ok')}, "
                                f"ipc={ctl.get('ipc_records')}）——"
                                "解码活性不能兜底 active 断言，必须 FAIL")
    return block, a, b


def log_lines_containing(ev: lib.Evidence, stems: list, keywords: list) -> dict:
    """Verbatim (trimmed) lines from the case's REAL session console/mpv.log
    bytes that contain one of the DESC keywords — the only honest source for
    desc_evidence.sample_hits (the checker cross-checks these byte-for-byte)."""
    hits: dict = {}
    for stem in stems:
        for suffix in (".mpv.log", ".console.txt"):
            p = ev.dir / f"{stem}{suffix}"
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln in text.splitlines():
                for kw in keywords:
                    if kw in ln:
                        trimmed = ln.strip()
                        bucket = hits.setdefault(kw, [])
                        if trimmed not in bucket:
                            bucket.append(trimmed)
    return hits


def desc_evidence(ev: lib.Evidence, s, keywords: list, stems: list) -> dict:
    """Structured desc_evidence{count, sample_hits} + the vo-passes truth.

    count = number of verbatim keyword-bearing lines actually found in the
    session logs (>= len(sample excerpt lines) by construction);
    vo_passes_hit_count = passes whose desc hits a keyword AND carry non-empty
    GPU samples (p1_verify keyword mode — never the 'user shader' substring)."""
    vo_count = p1v.user_shader_pass_count(s, keywords)
    sample_map = p1v.desc_sample_hits(s, keywords)
    log_hits = log_lines_containing(ev, stems, keywords)
    sample_hits = {kw: (log_hits.get(kw) or [])[:3] for kw in keywords}
    total_lines = sum(len(v) for v in log_hits.values())
    excerpts = [x for v in sample_hits.values() for x in v]
    block = {
        "count": total_lines,
        "sample_hits": {k: v for k, v in sample_hits.items() if v},
        "vo_passes_hit_count": max(0, int(vo_count)),
        "vo_passes_samples_nonempty": bool(vo_count >= 1),
        "keywords_hit_in_vo_passes": {k: bool(v) for k, v in sample_map.items()},
        "note": "count=会话日志中含 DESC 关键词的逐字行数；样本行均逐字出自该 case "
                "会话 console/mpv.log 字节；vo-passes 命中要求非空 GPU samples",
    }
    block["pass"] = bool(total_lines >= 1 and excerpts
                         and block["vo_passes_hit_count"] >= 1
                         and all(sample_map.values()))
    return block


def same_moment_variant(s, case: str, ev: lib.Evidence, gear: str | None = None,
                        shot_tag: str | None = None) -> dict:
    """One structured variant: same-moment record (+optional capture),
    chain epoch pairing and the native-bool witness for Integer gears."""
    shot_path = ev.dir / f"{case}.{shot_tag}.png" if shot_tag else None
    rec = p3.same_moment_sample(s, shot_path=shot_path, mode="window")
    variant = {"same_moment": [rec], "chain_epoch": s.ud("chain_epoch")}
    if gear is not None:
        variant["native_unscaled"] = native_unscaled(s)
        variant["gear"] = gear
    files = []
    if shot_path is not None and shot_path.exists():
        files.append(relp(shot_path))
    return variant, files


def finish_session(ev: lib.Evidence, result: dict, ctx: P3Context) -> None:
    """Clean quit FIRST (so a later artifact write can never orphan the
    player), then the transcript artifact (create-only, collision-tolerant).
    Only self-spawned PIDs are ever terminated."""
    if ctx.session is not None:
        try:
            ctx.session.quit(timeout_s=10)
        except Exception:  # noqa: BLE001 — a dead session is recorded, not fatal
            pass
        if ctx.session.proc is not None and ctx.session.proc.poll() is None:
            ctx.session.kill()
        try:
            result["files"].append(dump_transcript(ev, ctx.session))
        except Exception:  # noqa: BLE001 — artifact loss is recorded upstream
            pass


def finalize_epoch(variant: dict, fr: dict, s) -> dict:
    """Pair the variant's chain_epoch with the freshness block's epoch (the
    checker rejects stale-epoch pairings) and record window stability."""
    variant["chain_epoch"] = fr.get("chain_epoch")
    cur = s.ud("chain_epoch")
    variant["epoch_stable_across_window"] = (cur == fr.get("chain_epoch"))
    return variant


# ---------------------------------------------------------------------------
# pixel oracles (stdlib only)
# ---------------------------------------------------------------------------

def png_size_fast(data: bytes):
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return (int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"))


def shot_analysis(shot_path: Path) -> dict:
    data = Path(shot_path).read_bytes()
    dec = p3.decode_png(data)
    return {"path": str(shot_path), "sha256": lib.sha256_bytes(data),
            "png": {"w": dec["w"], "h": dec["h"],
                    "bitdepth": dec["bitdepth"]},
            "decoded": dec}


def capture_window(s, ev: lib.Evidence, case: str, tag: str,
                   mode: str = "window") -> dict | None:
    shot = ev.dir / f"{case}.{tag}.png"
    try:
        ok = s.screenshot(shot, mode=mode)
    except FileExistsError:
        return None
    if not ok or not shot.exists() or shot.stat().st_size == 0:
        return None
    out = shot_analysis(shot)
    out["relp"] = relp(shot)
    return out


def bars_measure(dec: dict) -> dict:
    """Primary full-frame letterbox scan + the geometry-constructed
    OSD-free fallback strips (honestly flagged when used)."""
    letter = p3.analyze_letterbox(dec["get_pixel"], dec["w"], dec["h"])
    out = {"primary": {k: letter[k] for k in
                       ("left", "right", "top", "bottom")},
           "fallback_used": False}
    return out


def bars_fallback_scan(dec: dict) -> dict:
    """Scan strips that CANNOT contain the plugin OSD for the pinned k=1
    1080p->1440p geometry: left/right bars scanned only across
    y in [700,1200] (video vertical mid-band; OSD text ends by y~620);
    top/bottom bars scanned only across x in [1300,2200]."""
    gp, w, h = dec["get_pixel"], dec["w"], dec["h"]
    rows = list(range(700, 1201, 7))
    cols = list(range(1300, 2201, 7))

    def col_bright(x):
        return any(max(gp(x, y)) > 40 for y in rows)

    def row_bright(y):
        return any(max(gp(x, y)) > 40 for x in cols)

    left = next((x for x in range(w) if col_bright(x)), None)
    right = next((x for x in range(w) if col_bright(w - 1 - x)), None) \
        if left is not None else None
    top = next((y for y in range(h) if row_bright(y)), None)
    bottom = next((y for y in range(h) if row_bright(h - 1 - y)), None) \
        if top is not None else None
    return {"left": left, "right": right, "top": top, "bottom": bottom,
            "scan_strips": {"lr_rows": "700..1200", "tb_cols": "1300..2200"},
            "osd_free_by_construction": True}


def osd_tl_bright_px(dec: dict) -> int:
    """Bright-pixel sample count in the pure black-bar corner region
    (0..319, 0..179) — frozen-OSD residue detector for the k=1 case."""
    gp, w, h = dec["get_pixel"], dec["w"], dec["h"]
    n = 0
    for y in range(0, min(180, h), 3):
        for x in range(0, min(320, w), 3):
            if max(gp(x, y)) > 40:
                n += 1
    return n


def full_frame_out_of_bound(dec: dict, sample_fn, tol_max: float = 90.0,
                            step: int = 2) -> dict:
    """V3-C1 INDEPENDENT OSD-free witness: a DENSE grid scan (step px) of the
    WHOLE decoded raw window against the CPU replica, counting pixels that
    deviate beyond the FIXED oracle tol_max.  Notification/ASS overlay pixels
    cannot hide between the sparse oracle points (leader-r8: mean 0.95 but
    max 220 on a few overlay pixels).  The oracle's own mean/max gates and
    thresholds stay UNCHANGED; this scan only witnesses OSD-freeness — no
    masking away differences, no tol_max inflation, no ignoring worst
    pixels."""
    gp, w, h = dec["get_pixel"], dec["w"], dec["h"]
    out = 0
    checked = 0
    worst = 0.0
    for y in range(0, h, step):
        for x in range(0, w, step):
            got = tuple(v / 255.0 for v in gp(x, y))
            want = sample_fn(x, y)
            d = max(abs(a - b) for a, b in zip(got, want)) * 255.0
            checked += 1
            worst = max(worst, d)
            if d > tol_max:
                out += 1
    return {"checked_px": checked, "out_of_bound_px": out,
            "worst_diff": round(worst, 2), "tol_max": tol_max,
            "grid_step": step, "ok": out == 0}


# -- CPU goldens ------------------------------------------------------------

def golden_bilinear(src, w: int, h: int, fx: float, fy: float) -> tuple:
    """Hardware-LINEAR bilinear sample of src (rows of (r,g,b) floats) at the
    continuous texel coordinate (fx, fy); texel centres at +0.5;
    CLAMP_TO_EDGE (reference behaviour)."""
    def clamp_axis(fv, n):
        return max(0.0, min(float(n) - 1e-6, fv))
    fx = clamp_axis(fx, w)
    fy = clamp_axis(fy, h)
    x0 = int(math.floor(fx - 0.5))
    y0 = int(math.floor(fy - 0.5))
    tx = fx - 0.5 - x0
    ty = fy - 0.5 - y0

    def px(xx, yy):
        xx = max(0, min(w - 1, xx))
        yy = max(0, min(h - 1, yy))
        return src[yy][xx]

    a, b = px(x0, y0), px(x0 + 1, y0)
    c, d = px(x0, y0 + 1), px(x0 + 1, y0 + 1)
    return tuple(_lerp(_lerp(a[i], b[i], tx), _lerp(c[i], d[i], tx), ty)
                 for i in range(3))


def _lerp(a, b, t):
    return a + (b - a) * t


def golden_sharp_sample(src, w_in: int, h_in: int, out_w: int, out_h: int,
                        scale: int, x: int, y: int) -> tuple:
    """CPU golden for one OUTPUT pixel of the sharp-bilinear mapping:
    uv = ((x+0.5)/out, (y+0.5)/out) -> texel = uv*in -> the reference's
    mod_texel correction (p3_lib.sharp_sample_coord) -> hardware LINEAR."""
    texel_x = (x + 0.5) * w_in / float(out_w)
    texel_y = (y + 0.5) * h_in / float(out_h)
    mx = p3.sharp_sample_coord(texel_x / w_in, w_in, scale)
    my = p3.sharp_sample_coord(texel_y / h_in, h_in, scale)
    return golden_bilinear(src, w_in, h_in, mx, my)


def compare_to_golden(dec: dict, golden_fn, points, tol_mean=10.0,
                      tol_max=90) -> dict:
    """Compare decoded window pixels against a CPU golden on a sample point
    list; returns the honest diff stats and the per-point verdicts."""
    gp = dec["get_pixel"]
    diffs = []
    for (x, y) in points:
        got = tuple(v / 255.0 for v in gp(x, y))
        want = golden_fn(x, y)
        d = max(abs(a - b) for a, b in zip(got, want)) * 255.0
        diffs.append(d)
    mean = sum(diffs) / len(diffs) if diffs else 999.0
    mx = max(diffs) if diffs else 999.0
    return {"points": len(diffs), "mean_diff": round(mean, 2),
            "max_diff": round(mx, 2), "tol_mean": tol_mean, "tol_max": tol_max,
            "ok": bool(mean <= tol_mean and mx <= tol_max)}


def ppm_flat_points(w: int, h: int, margin: int = 6, step: int = 7) -> list:
    """Interior sample points that sit in flat colour blocks of the
    p3.generate_ppm_pattern quadrant pattern (away from the half/diagonal
    edges)."""
    pts = []
    for y in range(margin, h - margin, step):
        for x in range(margin, w - margin, step):
            if x in (w // 2 - 1, w // 2, w // 2 + 1):
                continue
            if y in (h // 2 - 1, h // 2, h // 2 + 1):
                continue
            if abs((x + y) - (w // 2 + h // 2)) < 4:
                continue
            pts.append((x, y))
    return pts


def edge_band_points(w: int, h: int) -> list:
    """Sample points hugging the pattern's hard vertical edge (colour changes
    across x = w//2): the discriminator between xBR (sharp steps) and plain
    bilinear (spread ramps)."""
    pts = []
    ex = w // 2
    for y in range(4, h - 4, 3):
        for dx in (-3, -2, -1, 0, 1, 2, 3):
            x = ex + dx
            if 0 <= x < w:
                pts.append((x, y))
    return pts


def replica_at(replica, rw: int, x: int, y: int) -> tuple:
    return replica[y][x]


def _out_to_src(x, y, in_w, in_h, out_w, out_h):
    return ((x + 0.5) * in_w / float(out_w) - 0.5,
            (y + 0.5) * in_h / float(out_h) - 0.5)


def ppm_quadrant_flat_points(in_w, in_h, out_w, out_h, step: int = 3) -> list:
    """Interior output points whose SOURCE footprint is a pure flat colour of
    the quadrant+diagonal pattern: >=2 source texels away from the quadrant
    boundaries AND from the TL diagonal edge."""
    pts = []
    for Y in range(4, out_h - 4, step):
        for X in range(4, out_w - 4, step):
            sx, sy = _out_to_src(X, Y, in_w, in_h, out_w, out_h)
            if abs(sx - in_w / 2.0) < 2.0 or abs(sy - in_h / 2.0) < 2.0:
                continue
            if abs((sx - sy) - 4.0) / 1.4142 < 2.0:
                continue
            pts.append((X, Y))
    return pts


def ppm_quadrant_diagonal_band(in_w, in_h, out_w, out_h, step: int = 2) -> list:
    """Output points hugging the TL quadrant's 45-degree edge (source-space
    perpendicular distance in [0.6, 1.9] texels): the discriminator band where
    bilinear smears and xBR keeps steps."""
    pts = []
    for Y in range(2, out_h - 2, step):
        for X in range(2, out_w - 2, step):
            sx, sy = _out_to_src(X, Y, in_w, in_h, out_w, out_h)
            if sx < 1 or sy < 1 or sx > in_w / 2.0 - 1 or sy > in_h / 2.0 - 1:
                continue
            d = abs((sx - sy) - 4.0) / 1.4142
            if 0.6 <= d <= 1.9:
                pts.append((X, Y))
    return pts


def generate_ppm_quadrants(path: Path, w: int, h: int) -> tuple:
    """Dot-free quadrant RGB sample (same four flat colours as
    p3.generate_ppm_pattern but WITHOUT the isolated white-dot pixels): the
    dots sit on dense %7 diagonals whose blending tails pollute every flat
    interior sample (smoke-r2/r4 evidence).  The hard vertical edge at w/2
    stays — the xBR edge discriminator needs it.  Returns (sha256, rows)."""
    def color_at(x, y):
        if x < w // 2:
            if y < h // 2:
                # 45-degree diagonal split inside the TL quadrant: bilinear
                # smears a diagonal edge across texels while xBR keeps steps,
                # so the edge discriminator actually bites at exact 3x.
                return (240, 240, 240) if (x - y) > 4 else (180, 40, 40)
            return (40, 180, 40)
        return (40, 40, 200) if y < h // 2 else (220, 200, 30)

    rows = [[color_at(x, y) for x in range(w)] for y in range(h)]
    header = (f"P6\n{w} {h}\n255\n").encode("ascii")
    payload = bytearray()
    for row in rows:
        for (r, g, b) in row:
            payload += bytes((r, g, b))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(payload))
    return lib.sha256_file(path), rows


def edge_discriminator(dec: dict, replica, src, w_in: int, h_in: int,
                       out_w: int, out_h: int) -> dict:
    """The xBR pixel oracle: on the hard-edge band the captured window must be
    STRICTLY closer to the independently re-derived xBR CPU replica than to
    the plain-bilinear baseline (a real effect proof, not a menu/SHA claim)."""
    gp = dec["get_pixel"]
    band = ppm_quadrant_diagonal_band(w_in, h_in, out_w, out_h)
    d_xbr = []
    d_bil = []
    for (x, y) in band:
        got = tuple(v / 255.0 for v in gp(x, y))
        want_xbr = replica_at(replica, out_w, x, y)
        texel_x = (x + 0.5) * w_in / float(out_w)
        texel_y = (y + 0.5) * h_in / float(out_h)
        want_bil = golden_bilinear(src, w_in, h_in, texel_x, texel_y)
        d_xbr.append(max(abs(a - b) for a, b in zip(got, want_xbr)) * 255.0)
        d_bil.append(max(abs(a - b) for a, b in zip(got, want_bil)) * 255.0)
    closer = sum(1 for a, b in zip(d_xbr, d_bil) if a < b)
    mean_xbr = sum(d_xbr) / max(1, len(d_xbr))
    mean_bil = sum(d_bil) / max(1, len(d_bil))
    return {"edge_points": len(d_xbr),
            "band": "45-degree diagonal edge of the TL quadrant",
            "mean_diff_to_xbr_replica": round(mean_xbr, 2),
            "mean_diff_to_bilinear_baseline": round(mean_bil, 2),
            "closer_to_xbr_fraction": round(closer / max(1, len(d_xbr)), 3),
            "ok": bool(len(d_xbr) >= 12
                       # on the diagonal band bilinear smears while xBR keeps
                       # steps: strictly closer to the xBR replica...
                       and mean_xbr + 1.0 < mean_bil
                       # ...AND actually close to the replica (real effect,
                       # not merely "both wrong"):
                       and mean_xbr <= 15.0)}


# ---------------------------------------------------------------------------
# static audits recorded as evidence (real files, real functions)
# ---------------------------------------------------------------------------

def shader_static_audits() -> dict:
    out = {}
    nis_text = (lib.REPO_ROOT / "shaders/p3-NIS.glsl").read_text(encoding="utf-8")
    base_text = (lib.REPO_ROOT / p3.NIS_BASE_EVIDENCE).read_text(encoding="utf-8")
    audits = p3.nis_static_audit(nis_text, base_text)
    audits["store_index_1366x768"] = p3.nis_store_index_audit(1366, 768)
    audits["coeff_textures"] = p3.nis_texture_audit(nis_text, base_text)
    out["nis"] = audits
    xbr_text = (lib.REPO_ROOT / "shaders/p3-xBR-lv2.glsl").read_text(encoding="utf-8")
    out["xbr"] = p3.xbr_audit_source(xbr_text)
    out["xbr_reference_taps"] = [
        {"name": n, "offset": [ox, oy]}
        for (n, ox, oy) in p3.xbr_reference_offsets()]
    auto_text = (lib.REPO_ROOT / "shaders/p3-Sharp-Bilinear-AUTO.glsl") \
        .read_text(encoding="utf-8")
    out["sharp_auto_static"] = {
        "hook_main": "//!HOOK MAIN" in auto_text,
        "desc": "//!DESC Sharp Bilinear (AUTO)" in auto_text,
        "auto_formula_floor": "floor(out_over_in + 0.01)" in auto_text,
        "scale_clamp_ge_1": "max(scale, 1.0)" in auto_text,
        "linear_via_HOOKED_tex": "HOOKED_tex(mod_texel / HOOKED_size)" in auto_text,
        "no_directive_like_comment": not any(
            ln.strip().startswith("// //!")
            for ln in auto_text.splitlines()),
        "adapt_marker": "p3-adapt-v1" in auto_text,
    }
    out["resource_manifest"] = p3.audit_p3_resource_manifest()
    out["gears_conf_p3"] = p3.audit_gears_conf_p3()
    out["sharp_oracle"] = {
        "auto_scale_720_to_1440": p3.sharp_auto_scale(1440, 1080),
        "auto_scale_degenerate_note_1": p3.sharp_degenerate_note(1),
        "auto_scale_90_to_180": p3.sharp_auto_scale(180, 90),
        "auto_scale_180_to_135_clamped": p3.sharp_auto_scale(135, 180),
        "manual_scale": p3.sharp_manual_scale(),
        "degenerate_note_scale0_clamped": p3.sharp_degenerate_note(
            max(1, p3.sharp_auto_scale(135, 180) or 1)),
    }
    return out


def log_clean(ev: lib.Evidence, stems: list) -> bool:
    for stem in stems:
        p = ev.dir / f"{stem}.mpv.log"
        if not p.is_file():
            return False
        txt = p.read_text(encoding="utf-8", errors="replace")
        if "panicked" in txt or "lua error" in txt.lower():
            return False
    return True


# ---------------------------------------------------------------------------
# SHD-05 — NIS compute port (32x24/256, coef textures, bounds guard, WHEN)
# ---------------------------------------------------------------------------

def case_shd05(ev: lib.Evidence) -> dict:
    case = "SHD-05"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    audits = shader_static_audits()
    result["facts"]["static_audits"] = {
        "nis_core": {k: audits["nis"][k] for k in (
            "compute_directive", "two_coeff_textures", "rgba32f",
            "when_preserved", "has_barriers", "guard_after_all_barriers",
            "no_return_before_barrier", "imagestore_guarded",
            "no_nvsharpen_stacked", "luma_hook", "adapt_marker",
            "base_hash_recorded", "base_hash_on_disk_matches",
            "no_directive_like_comment", "reference_functions_kept")},
        "store_index_1366x768_non_divisible": {
            "oob_stores_without_guard":
                audits["nis"]["store_index_1366x768"]["oob_stores_without_guard"],
            "oob_stores_with_guard":
                audits["nis"]["store_index_1366x768"]["oob_stores_with_guard"],
            "workgroups": audits["nis"]["store_index_1366x768"]["workgroups"],
            "note": "非块整除目标(1366x768)无 guard 必有越界写——guard 真实性"
                    "由静态推导证明，绝不拿 GPU 不报错当无越界"},
        "coeff_byte_identical_to_evidence":
            audits["nis"]["coeff_textures"].get(
                "coefficients_byte_identical_to_evidence"),
    }
    ok_all = all(result["facts"]["static_audits"]["nis_core"].values())
    ok_all = ok_all and all(
        result["facts"]["static_audits"]["coeff_byte_identical_to_evidence"]
        .values())

    # -- variant a: real upscale pass at a non-block-divisible target -------
    stems_a = []
    ctx = P3Context(ev, case)
    try:
        ctx.make_y4m("shd05-up.y4m", 640, 360, frames=24)
        s = ctx.start("a-upscale-1366x768", window=(1366, 768))
        stems_a.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, 1366, 768)
        act = activate(s, "nis")
        time.sleep(1.5)
        de = desc_evidence(ev, s, p3.NIS_DESC_KEYWORDS, stems_a)
        fr, sm_a, sm_b = freshness_block(s, ev, f"{case}-a")
        chain = chain_files(s)
        shot = capture_window(s, ev, case, "a-window")
        inputsha = ctx.save_inputsha()
        clean = log_clean(ev, stems_a)
        vok = bool(win["ok"] and act["chain_verified"] and de["pass"]
                   and fr["render_fresh"] and clean
                   and len(chain) == 1 and "p3-NIS.glsl" in str(chain[0]))
        variant = {
            "name": "nis-upscale-non-divisible-1366x768",
            "window_gate": win, "activation": act,
            "desc_evidence": de, "freshness": fr,
            "same_moment": [sm_a, sm_b],
            "chain": chain, "chain_single_file": len(chain) == 1,
            "mpv_log_clean": clean,
            "render_pass_has_gpu_samples": de["vo_passes_samples_nonempty"],
        }
        finalize_epoch(variant, fr, s)
        result["variants"].append(variant)
        files = [f for f in (inputsha,) if f]
        files += [f["relp"] for f in (shot,) if f]
        files += [relp(ev.dir / f"{stem}.console.txt") for stem in stems_a]
        result["files"] += files
        ok_all = ok_all and vok and variant["epoch_stable_across_window"]
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems_a

    # -- variant b: equal-size -> legal //!WHEN skip with honest wording ----
    ok_b = _nis_when_skip_variant(result, ev, "b-equal-size", 640, 360,
                                  window=(640, 360))
    # -- variant c: downscale -> same honest skip semantics -----------------
    ok_c = _nis_when_skip_variant(result, ev, "c-downscale", 640, 360,
                                  window=(480, 270))
    result["facts"]["when_note"] = (
        "//!WHEN（仅 >1× 放大生效）为取证 port 原语义，原样保留；"
        "≤1× 时链合法跳过并以真实文案关联当前帧/epoch，绝不改 WHEN 凑激活")
    result["status"] = "PASS" if (ok_all and ok_b and ok_c) else "FAIL"
    return result


def _nis_when_skip_variant(result: dict, ev: lib.Evidence, variant_name: str,
                           media_w: int, media_h: int, window: tuple) -> bool:
    case = "SHD-05"
    stems = []
    ctx = P3Context(ev, case)
    ok = False
    try:
        ctx.make_y4m(f"shd05-{variant_name}.y4m", media_w, media_h, frames=24)
        s = ctx.start(variant_name, window=window)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, window[0], window[1])
        act = activate(s, "nis")
        time.sleep(1.2)
        ud = state_facts(s)
        fr, sm_a, sm_b = freshness_block(s, ev, f"{case}-{variant_name}",
                                         force_redraw=False)
        chain = chain_files(s)
        note = str(ud.get("skip_note") or "")
        skipped_honestly = (
            ud.get("chain_verified") == "skipped-when"
            and ("WHEN" in note and "跳过" in note))
        still_rendering = fr["render_fresh"]
        epoch = ud.get("chain_epoch")
        variant = {
            "name": f"nis-{variant_name}-when-skip",
            "window_gate": win, "activation": act,
            "state": ud.get("state"), "gear": ud.get("gear"),
            "chain_verified": ud.get("chain_verified"),
            "skip_note": note,
            "skip_note_honest": skipped_honestly,
            "chain": chain, "chain_fallback_intact": len(chain) == 1,
            "chain_epoch": epoch,
            "same_moment": [sm_a, sm_b],
            "freshness": fr,
            "render_continues_after_skip": still_rendering,
        }
        finalize_epoch(variant, fr, s)
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(win["ok"] and act["navigated"] and skipped_honestly
                  and len(chain) == 1 and still_rendering
                  and variant["epoch_stable_across_window"])
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    return ok


# ---------------------------------------------------------------------------
# SHD-06 — xBR-lv2 MAIN RGB (21 taps, 3x prescale mode, never xBRZ)
# ---------------------------------------------------------------------------

def case_shd06(ev: lib.Evidence) -> dict:
    case = "SHD-06"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    audits = shader_static_audits()
    xbr_audit = audits["xbr"]
    missing_taps = [k for k, v in xbr_audit.items()
                    if k.startswith("tap_") and not v]
    result["facts"]["static_audits"] = {
        "xbr_core": {k: v for k, v in xbr_audit.items()
                     if not k.startswith("tap_")},
        "tap_21_all_present": not missing_taps,
        "missing_taps": missing_taps,
        "tap_table": audits["xbr_reference_taps"],
        "mode_declaration": "参考 3× 预缩放 + mpv 后续缩放模式；"
                            "绝不冒称任意比例等价或 xBRZ（xbr_audit.no_xbrz_claim）",
    }
    core_ok = all(v for k, v in result["facts"]["static_audits"]["xbr_core"].items()
                  if k != "no_xbrz_claim") and not missing_taps
    ok_all = core_ok

    # -- variant a: RGB still image in an exactly-3x window + pixel oracle ---
    # (a still renders ONCE: presence/liveness proof lives in the motion
    #  variants below; this variant proves the PIXEL-LEVEL effect)
    stems_a = []
    ctx = P3Context(ev, case)
    try:
        w_in, h_in = 96, 54
        out_w, out_h = p3.xbr_output_size(w_in, h_in)
        ctx.make_ppm("shd06-rgb.ppm", w_in, h_in)
        src = p3.ppm_rows_to_float(ctx.ppm_rows)
        s = ctx.start("a-rgb-3x", window=(out_w, out_h))
        stems_a.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, out_w, out_h)
        act = activate(s, "xbr")
        # THE decisive still-image lesson (smoke-r2..r7 + brief-v3 C1):
        # navigate_and_activate leaves the full-menu ASS overlay AND the
        # 3s-pinned activation OSD drawn; a still never re-presents, so both
        # stay burned into every window capture (leader-r8: max 220 at the
        # overlay pixels).  close_menu() removes the menu overlay;
        # wait_osd_gone waits the REAL >3s notification lifetime from the
        # final activation and its pause blip forces one genuine repaint of
        # the still BEFORE the raw window capture.
        assert s.close_menu(), "close_menu failed"
        wait_osd_gone(s, blip=True)
        chain = chain_files(s)
        shot = capture_window(s, ev, case, "a-window")
        # exact dimension gate BEFORE any sampling: a wrong-size capture is a
        # clearly-named hard failure — never clamp/resample/crop it (C1).
        dims_ok = bool(shot and (shot["png"]["w"], shot["png"]["h"])
                       == (out_w, out_h))
        oracle = None
        osd_free = None
        replica = p3.xbr_cpu_replica(src, w_in, h_in, scale=3)
        if shot and dims_ok:
            oracle = {
                "flat_blocks": compare_to_golden(
                    shot["decoded"],
                    lambda x, y: replica_at(replica, out_w, x, y),
                    ppm_quadrant_flat_points(w_in, h_in, out_w, out_h)),
                "edge_discriminator": edge_discriminator(
                    shot["decoded"], replica, src, w_in, h_in, out_w, out_h),
            }
            # independent OSD-free pixel witness over the FULL window grid
            osd_free = full_frame_out_of_bound(
                shot["decoded"],
                lambda x, y: replica_at(replica, out_w, x, y))
        oracle_ok = bool(oracle and oracle["flat_blocks"]["ok"]
                         and oracle["edge_discriminator"]["ok"])
        clean = log_clean(ev, stems_a)
        variant = {
            "name": "xbr-rgb-exact-3x-window-pixel-oracle",
            "window_gate": win, "activation": act,
            "same_moment": [p3.same_moment_sample(s)],
            "window_is_exact_3x": [out_w, out_h],
            "png_dims": shot["png"] if shot else None,
            "png_dims_exact_ok": dims_ok,
            "pixel_oracle": oracle,
            "osd_free_scan": osd_free,
            "mpv_log_clean": clean,
            "still_image_note": "静帧只证像素效果；在场/新帧证据由 y4m 动帧变体"
                                "（b/c）以 DESC+GPU samples+fresh 递增承担",
        }
        result["variants"].append(variant)
        result["files"] += [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems_a]
        ok_all = ok_all and bool(win["ok"] and dims_ok and oracle_ok
                                 and osd_free and osd_free["ok"] and clean)
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems_a

    # -- variant b: yuv source through the same MAIN RGB hook (motion) ------
    ok_b = _shd06_presence_variant(result, ev, "b-yuv-main", yuv=True)
    # -- variant c: downscaled window still a real pass (motion) ------------
    ok_c = _shd06_presence_variant(result, ev, "c-downscale-window", yuv=False,
                                   window=(160, 90))
    ok_all = ok_all and ok_b and ok_c
    result["status"] = "PASS" if ok_all else "FAIL"
    return result


def _shd06_presence_variant(result: dict, ev: lib.Evidence, name: str,
                            yuv: bool, window: tuple = (288, 162)) -> bool:
    case = "SHD-06"
    stems = []
    ctx = P3Context(ev, case)
    ok = False
    try:
        # presence variants must use MOTION media (a still renders once, so
        # vo-passes samples/fresh frames cannot honestly flow); y4m 8bit is
        # the yuv path -- the RGB-source pixel evidence lives in variant a
        ctx.make_y4m(f"shd06-{name}.y4m", 96, 54, frames=24)
        s = ctx.start(name, window=window)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, window[0], window[1])
        act = activate(s, "xbr")
        wait_osd_gone(s)
        de = desc_evidence(ev, s, p3.XBR_DESC_KEYWORDS, stems)
        fr, sm_a, sm_b = freshness_block(s, ev, f"{case}-{name}")
        chain = chain_files(s)
        variant = {
            "name": f"xbr-{name}", "source_kind": "y4m8-yuv-motion",
            "window_gate": win, "activation": act,
            "desc_evidence": de, "freshness": fr,
            "same_moment": [sm_a, sm_b],
            "chain": chain, "chain_single_file": len(chain) == 1,
        }
        finalize_epoch(variant, fr, s)
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(win["ok"] and act["chain_verified"] and de["pass"]
                  and fr["render_fresh"] and len(chain) == 1
                  and variant["epoch_stable_across_window"])
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    return ok


def case_shd07(ev: lib.Evidence) -> dict:
    case = "SHD-07"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    audits = shader_static_audits()
    result["facts"]["static_audits"] = audits["sharp_auto_static"]
    result["facts"]["oracle_scales"] = audits["sharp_oracle"]
    result["facts"]["effect_proof_rule"] = (
        "菜单命名/SHA 相异不作为效用证明：像素变体以 CPU golden 对真实截图做"
        "采样坐标对照；在场/新帧证据由动帧变体 e 以 DESC+GPU samples+fresh "
        "递增承担")
    ok_all = all(audits["sharp_auto_static"].values())

    # still-image pixel-oracle variants (16:9 windows, no letterbox):
    #   a: floor(288/180+0.01)=1 -> degenerate plain bilinear (honest note)
    #   b: floor(180/90+0.01)=2  -> real sharp-bilinear pre-scale
    #   c: manual 2x at the same geometry
    #   d: floor(135/180+0.01)=0 -> scale<1 clamped to 1 (no divide-by-zero)
    plan = [
        ("a-auto-degenerate-floor1", 320, 180, 512, 288,
         "sharpbilinear", 1, "退化"),
        ("b-auto-real-2x", 160, 90, 320, 180,
         "sharpbilinear", 2, None),
        ("c-manual-2x", 160, 90, 320, 180,
         "sharpbilinear2x", 2, None),
        ("d-auto-scale0-clamp", 320, 180, 240, 135,
         "sharpbilinear", 1, "退化"),
    ]
    for (name, iw, ih, ow, oh, gear, scale, note_kw) in plan:
        ok_v, stems = _shd07_variant(result, ev, name, iw, ih, ow, oh,
                                     gear, scale, note_kw)
        ok_all = ok_all and ok_v
    # motion presence variant (freshness/desc for the case-level PASS claim)
    ok_all = ok_all and _shd07_presence_variant(result, ev)
    result["status"] = "PASS" if ok_all else "FAIL"
    return result


def _shd07_variant(result: dict, ev: lib.Evidence, name: str, iw: int, ih: int,
                   ow: int, oh: int, gear: str, scale: int,
                   note_kw: str | None) -> tuple:
    case = "SHD-07"
    stems = []
    ctx = P3Context(ev, case)
    ok = False
    try:
        ctx.make_ppm(f"shd07-{name}.ppm", iw, ih)
        src = p3.ppm_rows_to_float(ctx.ppm_rows)
        s = ctx.start(name, window=(ow, oh))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, ow, oh)
        act = activate(s, gear)
        # same still-image OSD lesson as SHD-06 (brief-v3 C1): close the ASS
        # menu, wait the REAL >3s notification expiry from the final
        # activation and force one genuine repaint BEFORE the raw capture.
        assert s.close_menu(), "close_menu failed"
        wait_osd_gone(s, blip=True)
        ud = state_facts(s)
        chain = chain_files(s)
        shot = capture_window(s, ev, case, f"{name}-window")
        dims_ok = bool(shot and (shot["png"]["w"], shot["png"]["h"])
                       == (ow, oh))
        oracle = None
        osd_free = None
        if shot and dims_ok:
            golden = lambda x, y: golden_sharp_sample(src, iw, ih, ow, oh,
                                                      scale, x, y)
            oracle = compare_to_golden(
                shot["decoded"], golden,
                ppm_quadrant_flat_points(iw, ih, ow, oh))
            osd_free = full_frame_out_of_bound(shot["decoded"], golden)
        note = str(ud.get("skip_note") or "")
        note_ok = True if note_kw is None else (note_kw in note)
        variant = {
            "name": f"sharp-{name}",
            "gear": gear,
            "expected_scale_after_formula": scale,
            "auto_formula_value": p3.sharp_auto_scale(oh, ih),
            "window_gate": win, "activation": act,
            "same_moment": [p3.same_moment_sample(s)],
            "skip_note": note, "note_keyword_expected": note_kw,
            "note_ok": note_ok,
            "png_dims": shot["png"] if shot else None,
            "png_dims_exact_ok": dims_ok,
            "chain": chain, "chain_single_file": len(chain) == 1,
            "pixel_oracle": oracle,
            "osd_free_scan": osd_free,
            "still_image_note": "静帧只证像素效果；在场/新帧证据由动帧变体 e 承担",
        }
        result["variants"].append(variant)
        result["files"] += [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(win["ok"] and len(chain) == 1 and dims_ok
                  and osd_free and osd_free["ok"]
                  and note_ok and oracle and oracle["ok"])
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    return ok, stems


def _shd07_presence_variant(result: dict, ev: lib.Evidence) -> bool:
    """Motion (y4m) variant: DESC + non-empty GPU samples + real fresh frames
    for the AUTO gear — the case-level presence/liveness evidence."""
    case = "SHD-07"
    stems = []
    ctx = P3Context(ev, case)
    ok = False
    try:
        ctx.make_y4m("shd07-e-motion.y4m", 160, 90, frames=24)
        s = ctx.start("e-motion-presence", window=(320, 180))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, 320, 180)
        act = activate(s, "sharpbilinear")
        wait_osd_gone(s)
        de = desc_evidence(ev, s, p3.SHARP_AUTO_DESC_KEYWORDS, stems)
        fr, sm_a, sm_b = freshness_block(s, ev, f"{case}-e")
        chain = chain_files(s)
        variant = {
            "name": "sharp-e-motion-presence",
            "gear": "sharpbilinear",
            "source_kind": "y4m8-yuv-motion",
            "window_gate": win, "activation": act,
            "desc_evidence": de, "freshness": fr,
            "same_moment": [sm_a, sm_b],
            "chain": chain, "chain_single_file": len(chain) == 1,
        }
        finalize_epoch(variant, fr, s)
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(win["ok"] and act["chain_verified"] and de["pass"]
                  and fr["render_fresh"] and len(chain) == 1
                  and variant["epoch_stable_across_window"])
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    return ok


def case_shd09(ev: lib.Evidence) -> dict:
    case = "SHD-09"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    # The five P3 gear identities x 8/10bit real decode.  fsr1 preserves the
    # ORIGINAL P2 SHD-09 semantics (10-bit fsr1 really decoded + real chain)
    # inside this P3 wrapper structure, so the new P3 SHD-09 cannot
    # overwrite/drop the frozen P2 8/10bit coverage (brief-v3 M2: "P2
    # original 8/10 coverage must still hold alongside five new P3
    # identities"); the old fake-8bit-body PASS is void — the media writer
    # now emits real LE16 planes (write_y4m) with byte-oracle unit pins.
    gears = ["nis", "xbr", "sharpbilinear", "sharpbilinear2x", "integer",
             "fsr1"]
    ok_all = True
    for gear in gears:
        for ten_bit in (False, True):
            ok_v, variant, files = _shd09_variant(ev, gear, ten_bit)
            result["variants"].append(variant)
            result["files"] += files
            result["sessions"] += variant.get("_stems", [])
            variant.pop("_stems", None)
            ok_all = ok_all and ok_v
    result["facts"]["rule"] = (
        "每个新增档位（含 P2 语义保留的 fsr1 包装档）8/10bit SDR 各自真实解码"
        "（same_moment pixelformat 与声明位数一致；10bit 需含 '10'，8bit 不得含 "
        "'10'/'16'；媒体为 write_y4m 真实 LE16 平面，字节级 unit oracle 钉死）；"
        "无测不得称支持")
    result["status"] = "PASS" if ok_all else "FAIL"
    return result


def _shd09_variant(ev: lib.Evidence, gear: str, ten_bit: bool) -> tuple:
    name = f"SHD-09-{gear}-{'10bit' if ten_bit else '8bit'}"
    ctx = P3Context(ev, name)
    stems = []
    ok = False
    try:
        ctx.make_y4m("src.y4m", 640, 360, frames=16, ten_bit=ten_bit)
        s = ctx.start("run", window=(1366, 768))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, 1366, 768)
        act = activate(s, gear)
        # V3-M1/M2: the same observation window requires REAL media readiness
        # first (video-out-params non-empty), and the shader gears need their
        # OWN desc pass with non-empty GPU samples at a stable chain epoch
        # (motion media presents continuously; only the activation race is
        # waited out — no forced blip needed).
        params_ok = wait_video_out_params(s)
        dp = None
        if gear != "integer":
            dp = wait_desc_pass_samples(
                s, GEAR_DESC_KEYWORDS.get(gear, p2.FSR_DESC_KEYWORDS))
        rec = p3.same_moment_sample(s)
        epoch = s.ud("chain_epoch")
        pixfmt = str(rec.get("pixelformat") or "")
        depth_ok = (("10" in pixfmt) == ten_bit)
        native = native_unscaled(s) if gear == "integer" else None
        k_ok = True
        if gear == "integer":
            k = s.ud("integer_k")
            k_ok = (k == 2) and native_bool_ok(native, True)
        chain = chain_files(s)
        chain_ok = True if gear == "integer" else (
            len(chain) == 1 and GEAR_CHAIN_SHADER[gear] in str(chain[0]))
        variant = {
            "bitdepth": 10 if ten_bit else 8,
            "media": "stdlib C420p10 y4m (real LE16 planes)" if ten_bit
                    else "stdlib C420jpeg y4m",
            "media_sha256": ctx.media_sha,
            "same_moment": [rec],
            "video_out_params_ready": params_ok,
            "desc_pass": ({"desc_hits": dp["desc_hits"],
                           "with_samples_epoch_stable":
                               bool(dp["all_desc_with_samples"]
                                    and dp["epoch_stable"]),
                           "chain_epoch_at_samples": dp["chain_epoch_at_samples"]}
                          if dp is not None else None),
            "pixelformat": pixfmt,
            "depth_matches_decode": depth_ok,
            "gear": gear, "state": s.ud("state"), "activation": act,
            "chain_epoch": epoch, "window_gate": win,
        }
        if gear == "integer":
            variant["native_unscaled"] = native
            variant["integer_k"] = s.ud("integer_k")
        files = [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(win["ok"] and params_ok and act["chain_verified"]
                  and depth_ok and k_ok and chain_ok
                  and (dp is None or (dp["all_desc_with_samples"]
                                      and dp["epoch_stable"])))
        variant["_stems"] = stems
        try:
            s.quit(timeout_s=10)
        except Exception:  # noqa: BLE001
            pass
        return ok, variant, files
    finally:
        if ctx.session is not None:
            result_local = None
            try:
                dump_transcript(ev, ctx.session)
            except Exception:  # noqa: BLE001
                pass
        ctx.cleanup()


# ---------------------------------------------------------------------------
# SHD-10 — RGB guard matrix including the P3 gears
# ---------------------------------------------------------------------------

def case_shd10(ev: lib.Evidence) -> dict:
    case = "SHD-10"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    result["facts"]["scope_note"] = (
        "P2 语义保留（fsr1/sgsr1/anime4k LUMA 档 RGB 拒用 + nearest 不受影响），"
        "并逐档覆盖 P3 档：nis 为 LUMA 档 RGB 拒用；xbr/sharpbilinear/"
        "sharpbilinear2x 为 MAIN RGB 档，RGB 下必须真实激活生效")
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        ctx.make_ppm("shd10-rgb.ppm", 640, 360)
        s = ctx.start("a-rgb-guard-matrix", window=(960, 540))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        # V3-M1: loaded/off is NOT media ready — wait for the REAL
        # video-out-params before the same-moment decode/guard sampling
        # (leader-r8 recorded pixfmt empty here).
        params_ok = wait_video_out_params(s)
        geo = p3.same_moment_sample(s)
        pixfmt = str(geo.get("pixelformat") or "")
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        luma_gears = ("fsr1", "sgsr1", "anime4k", "nis")
        blocked = {g: {"blocked": bool(by_id.get(g, {}).get("guard_blocked")),
                       "reason": by_id.get(g, {}).get("reason") or ""}
                   for g in luma_gears}
        all_blocked = all(v["blocked"] and "RGB" in v["reason"]
                          for v in blocked.values())
        # Refusal witness is STATE-based (race-free): after each activation
        # attempt the gear must NOT be active and must not own a chain.
        # (navigate_and_activate may return True while the activation itself
        # is refused by the guard -- smoke-r3 evidence.)
        refusal_detail = {}
        refused = True
        for g in luma_gears:
            nav = s.navigate_and_activate(g)
            time.sleep(0.8)
            st, gr, cv = s.ud("state"), s.ud("gear"), s.ud("chain_verified")
            glsl_now = s.get("glsl-shaders") or []
            ok_refused = (st != "active") and gr != g and cv is not True                 and not glsl_now
            refusal_detail[g] = {"navigated": bool(nav), "state": st,
                                 "gear": gr, "chain_verified": cv,
                                 "glsl": glsl_now, "refused": ok_refused}
            refused = refused and ok_refused
        near_ok = s.navigate_and_activate("nearest") \
            and s.wait_state("active", 6.0)
        main_rgb = {}
        for g in ("xbr", "sharpbilinear", "sharpbilinear2x"):
            ok_act = s.navigate_and_activate(g) and s.wait_state("active", 8.0) \
                and s.wait_until(lambda: s.ud("chain_verified") is True, 12.0)
            # V3-M1: after a shader switch the vo-pass can still show the
            # PRIOR pass (or none) — the source is a STILL image, so force
            # one genuine repaint and then require the NEW gear's DESC in a
            # pass with non-empty GPU samples at the new chain epoch, so
            # xBR/Sharp2x never sample a prior pass.
            force_present_still(s)
            dp = wait_desc_pass_samples(s, GEAR_DESC_KEYWORDS[g])
            main_rgb[g] = {
                "activated": bool(ok_act),
                "state": s.ud("state"),
                "chain": chain_files(s),
                "desc_hits": dp["desc_hits"],
                "desc_with_samples_epoch_stable":
                    bool(dp["all_desc_with_samples"] and dp["epoch_stable"]),
                "chain_epoch_at_samples": dp["chain_epoch_at_samples"],
            }
        main_ok = all(v["activated"] and all(v["desc_hits"].values())
                      and v["desc_with_samples_epoch_stable"]
                      and len(v["chain"]) == 1 for v in main_rgb.values())
        s.close_menu()
        variant = {
            "name": "rgb-source-guard-matrix-p2-plus-p3",
            "video_out_params_ready": params_ok,
            "pixelformat": pixfmt,
            "is_rgb_pixfmt": p2.is_rgb_pixfmt(pixfmt),
            "luma_gears_blocked": blocked,
            "all_luma_blocked_with_rgb_reason": all_blocked,
            "all_luma_activations_refused": refused,
            "refusal_detail": refusal_detail,
            "nearest_active_on_rgb": bool(near_ok),
            "p3_main_rgb_gears": main_rgb,
            "p3_main_rgb_all_active_with_desc": main_ok,
            "menu_open_ok": opened,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-10-rgb-guard-menu.png", variant)
        variant["note"] = "菜单截图仅作过程留痕；RGB 生效证明=DESC+GPU samples+真实新帧"
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = bool(params_ok and opened and all_blocked and refused and near_ok
                  and main_ok and p2.is_rgb_pixfmt(pixfmt))
    finally:
        if ctx.session is not None:
            result["files"].append(dump_transcript(ev, ctx.session))
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-11 — HDR guard matrix (metadata override synthetic; P3 gears)
# ---------------------------------------------------------------------------

def case_shd11(ev: lib.Evidence) -> dict:
    case = "SHD-11"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    result["facts"]["metadata_override_note"] = METADATA_OVERRIDE_NOTE
    result["facts"]["guard_independence_rule"] = (
        "HDR 守卫独立于 LUMA 守卫：nis 走 LUMA 档拒绝；xbr/sharpbilinear/"
        "sharpbilinear2x 的 HDR 拒绝理由必须独立成立（与 LUMA 拒绝文案不同源），"
        "仅守卫测试不冒编码 HDR，不做 HDR 画质评价")
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        ctx.make_y4m("shd11-sdr.y4m", 640, 360, frames=16)
        s = ctx.start("a-hdr-override-guard",
                      extra_args=["--vf=format:gamma=pq:primaries=bt.2020"])
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        # V3-M1: wait for the REAL video-out-params INCLUDING gamma before
        # the same-moment sample (leader-r8 recorded gamma None while the
        # media was still loading) — never invent metadata.
        params_ok = wait_video_out_params(s, need_gamma=True)
        geo = p3.same_moment_sample(s)
        gamma = geo.get("gamma")
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        hdr_gears = ("fsr1", "sgsr1", "anime4k", "nis",
                     "xbr", "sharpbilinear", "sharpbilinear2x")
        blocked = {g: {"blocked": bool(by_id.get(g, {}).get("guard_blocked")),
                       "reason": by_id.get(g, {}).get("reason") or ""}
                   for g in hdr_gears}
        all_blocked = all(v["blocked"] and "HDR" in v["reason"]
                          for v in blocked.values())
        # Refusal witness is STATE-based (race-free; smoke-r3 evidence).
        refusal_detail = {}
        refused = True
        for g in hdr_gears:
            nav = s.navigate_and_activate(g)
            time.sleep(0.8)
            st, gr, cv = s.ud("state"), s.ud("gear"), s.ud("chain_verified")
            glsl_now = s.get("glsl-shaders") or []
            unscaled_now = s.get("video-unscaled")
            ok_refused = ((st != "active") and gr != g and cv is not True
                          and not glsl_now and unscaled_now in (False, None))
            refusal_detail[g] = {"navigated": bool(nav), "state": st,
                                 "gear": gr, "chain_verified": cv,
                                 "glsl": glsl_now, "refused": ok_refused}
            refused = refused and ok_refused
        # independence witness: the MAIN RGB gears' HDR refusal must be its own
        # wording — NOT the LUMA-guard refusal text (which names the LUMA
        # hook/chain), and carrying the HDR guard's own independence marker.
        p3_reasons = {g: blocked[g]["reason"]
                      for g in ("xbr", "sharpbilinear", "sharpbilinear2x")}
        independent_wording = all(
            ("HDR" in r) and ("LUMA 档不可用" not in r)
            and ("禁用 LUMA 档" not in r) and ("LUMA hook" not in r)
            and ("守卫独立于" in r)
            for r in p3_reasons.values())
        integer_ok = s.navigate_and_activate("integer") \
            and s.wait_state("active", 8.0) \
            and s.wait_until(lambda: s.ud("chain_verified") is True, 12.0)
        integer_state = {"state": s.ud("state"), "k": s.ud("integer_k"),
                         "native_unscaled": native_unscaled(s),
                         "chain": chain_files(s)}
        near_ok = s.navigate_and_activate("nearest") \
            and s.wait_state("active", 6.0)
        s.close_menu()
        variant = {
            "name": "hdr-metadata-override-guard-matrix-p2-plus-p3",
            "metadata_override_note": METADATA_OVERRIDE_NOTE,
            "video_out_params_ready": params_ok,
            "gamma": gamma,
            "pixelformat": geo.get("pixelformat"),
            "gears_blocked_with_hdr_reason": blocked,
            "all_blocked_with_hdr_reason": all_blocked,
            "all_activations_refused": refused,
            "refusal_detail": refusal_detail,
            "p3_main_hdr_reasons_independent_of_luma": independent_wording,
            "p3_main_hdr_reasons": p3_reasons,
            "integer_still_active": bool(integer_ok),
            "integer_state": integer_state,
            "nearest_active_no_guard": bool(near_ok),
            "no_hdr_quality_claim": "仅守卫测试；不冒编码 HDR 源，不做画质评价",
            "menu_open_ok": opened,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-11-hdr-guard-menu.png", variant)
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = bool(params_ok and opened and gamma in ("pq", "hlg")
                  and all_blocked and refused
                  and independent_wording and integer_ok and near_ok)
    finally:
        if ctx.session is not None:
            result["files"].append(dump_transcript(ev, ctx.session))
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# GEO-02 — Integer letterbox / k matrix / same-process loadfile
# ---------------------------------------------------------------------------

def case_geo02(ev: lib.Evidence) -> dict:
    case = "GEO-02"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    ok_all = True

    # -- v1: fullscreen 1080p -> k=1, bars 320/180 (OSD-free fallback honest)
    ok_all &= _geo02_bars_variant(result, ev)

    # -- v2: fullscreen 720p -> k=2, no bars ---------------------------------
    ctx = P3Context(ev, case)
    stems = []
    try:
        ctx.make_y4m("geo02-720.y4m", 1280, 720, frames=24)
        s = ctx.start("b-2x-full", fullscreen=True)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        act = activate(s, "integer")
        time.sleep(3.6)   # plugin OSD is pinned to 3s; never shoot through it
        _clear_osd_blip(s)
        k = s.ud("integer_k")
        native = native_unscaled(s)
        v_variant, files = same_moment_variant(s, f"{case}-b", ev,
                                               gear="integer", shot_tag="window")
        fr, _, _ = freshness_block(s, ev, f"{case}-b")
        shot = capture_window(s, ev, case, "b-window")
        lb = p3.analyze_letterbox(shot["decoded"]["get_pixel"],
                                  shot["decoded"]["w"], shot["decoded"]["h"]) \
            if shot else {}
        no_bars = all(lb.get(k_, 0) == 0 for k_ in ("left", "right", "top", "bottom"))
        shot_ok = bool(shot and (shot["png"]["w"], shot["png"]["h"])
                       == (DISP_W, DISP_H))
        variant = {
            "name": "integer-720p-1440p-k2-fullscreen",
            "fullscreen_gate": fsg,
            "activation": act,
            "integer_k": k,
            "k_expected": 2,
            "native_unscaled": native,
            "same_moment": v_variant["same_moment"],
            "freshness": fr,
            "chain_epoch": v_variant["chain_epoch"],
            "letterbox": lb,
            "no_bars": no_bars,
            "window_png_size_ok": shot_ok,
            "zoom": s.get("video-zoom"),
        }
        result["variants"].append(variant)
        result["files"] += files + [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        v_ok = bool(fsg["ok"] and act["chain_verified"] and k == 2
                    and native_bool_ok(native, True) and no_bars
                    and shot_ok and fr["render_fresh"]
                    and abs(float(s.get("video-zoom") or -9) - 1.0) < 1e-6
                    and v_variant["chain_epoch"] == fr["chain_epoch"]
                    and isinstance(v_variant["chain_epoch"], int))
        variant["chain_epoch"] = fr["chain_epoch"]
        ok_all = ok_all and v_ok
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems

    # -- v3: k<1 normal downscale, no crop, honest note ----------------------
    ctx = P3Context(ev, case)
    stems = []
    try:
        ctx.make_y4m("geo02-720b.y4m", 1280, 720, frames=24)
        s = ctx.start("c-k-lt-1", window=(640, 360))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win = window_gate(s, 640, 360)
        act = activate(s, "integer")
        time.sleep(1.5)
        k = s.ud("integer_k")
        native = native_unscaled(s)
        note = str(s.ud("skip_note") or "")
        vop = s.get("video-out-params") or {}
        v_variant, files = same_moment_variant(s, f"{case}-c", ev, gear="integer")
        fr, _, _ = freshness_block(s, ev, f"{case}-c")
        variant = {
            "name": "integer-k-lt-1-normal-downscale-no-crop",
            "window_gate": win, "activation": act,
            "integer_k": k, "k_expected": 0,
            "native_unscaled": native,
            "skip_note": note, "note_has_k_lt_1": "k<1" in note,
            "no_crop": (vop.get("w"), vop.get("h")) == (1280, 720),
            "video_unscaled": s.get("video-unscaled"),
            "same_moment": v_variant["same_moment"],
            "freshness": fr, "chain_epoch": v_variant["chain_epoch"],
        }
        result["variants"].append(variant)
        result["files"] += files
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        v_ok = bool(win["ok"] and act["chain_verified"] and k == 0
                    and native_bool_ok(native, False)
                    and "k<1" in note
                    and (vop.get("w"), vop.get("h")) == (1280, 720)
                    and fr["render_fresh"]
                    and v_variant["chain_epoch"] == fr["chain_epoch"]
                    and isinstance(v_variant["chain_epoch"], int))
        variant["chain_epoch"] = fr["chain_epoch"]
        ok_all = ok_all and v_ok
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems

    # -- v4: same-process loadfile 1080->720 (k 1->2, epoch advance) ---------
    ok_all &= _geo02_loadfile_variant(result, ev)
    result["status"] = "PASS" if ok_all else "FAIL"
    return result


def _clear_osd_blip(s):
    """Pause blip to force one fresh present (frozen/stale OSD countermeasure
    from the core-checks run-003/004 lessons)."""
    s.set("pause", True)
    time.sleep(0.25)
    s.set("pause", False)
    time.sleep(0.6)


def _geo02_bars_variant(result: dict, ev: lib.Evidence) -> bool:
    case = "GEO-02"
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        ctx.make_y4m("geo02-1080.y4m", 1920, 1080, frames=24)
        s = ctx.start("a-1x-bars", fullscreen=True)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        baseline = snapshot_props(s)
        act = activate(s, "integer")
        time.sleep(3.6)   # OSD pinned 3s (mp.osd_message text,3)
        _clear_osd_blip(s)
        k = s.ud("integer_k")
        native = native_unscaled(s)
        shot = capture_window(s, ev, case, "a-window")
        exp = {"left": 320, "right": 320, "top": 180, "bottom": 180}
        bars = None
        fallback = None
        osd_residue = None
        shot_ok = bool(shot and (shot["png"]["w"], shot["png"]["h"])
                       == (DISP_W, DISP_H))
        if shot:
            primary = p3.analyze_letterbox(shot["decoded"]["get_pixel"],
                                           shot["decoded"]["w"],
                                           shot["decoded"]["h"])
            bars = {k_: primary[k_] for k_ in exp}
            bars_ok = all(bars[k_] is not None and abs(bars[k_] - exp[k_]) <= 2
                          for k_ in exp)
            if not bars_ok:
                osd_residue = osd_tl_bright_px(shot["decoded"])
                if osd_residue > 200:
                    fb = bars_fallback_scan(shot["decoded"])
                    fallback = fb
                    bars2 = {k_: fb.get(k_) for k_ in exp}
                    bars_ok = all(bars2[k_] is not None
                                  and abs(bars2[k_] - exp[k_]) <= 2
                                  for k_ in exp)
                    bars = bars2
        else:
            bars_ok = False
        v_variant, files = same_moment_variant(s, f"{case}-a", ev, gear="integer")
        fr, _, _ = freshness_block(s, ev, f"{case}-a")
        # Off rollback positive witness inside this variant
        off_ok = s.navigate_and_activate("off") and s.wait_state("off", 8.0)
        time.sleep(0.8)
        after = snapshot_props(s)
        off_report = s.ud("off_report")
        native_after = native_unscaled(s)
        residue = residue_vs_baseline(after, baseline)
        restored = list((off_report or {}).get("restored") or [])
        rollback = {
            "state": s.ud("state"),
            "off_report_restored_contains_written": (
                "video-unscaled" in restored and "video-zoom" in restored),
            "native_unscaled_after": native_after,
            "unscaled_native_bool_false": native_bool_ok(native_after, False),
            "residue": residue,
            "residue_zero": not residue,
        }
        bars_ok = bool(bars_ok) and bool(shot)
        variant = {
            "name": "integer-1080p-1440p-k1-bars-320-180",
            "fullscreen_gate": fsg,
            "activation": act,
            "integer_k": k, "k_expected": 1,
            "native_unscaled": native,
            "bars_expected": exp,
            "bars_measured": bars,
            "bars_fallback": fallback,
            "fallback_used_honest_flag": fallback is not None,
            "osd_tl_bright_px": osd_residue,
            "window_png_size_ok": shot_ok,
            "same_moment": v_variant["same_moment"],
            "freshness": fr,
            "off_rollback": rollback,
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += files + [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(fsg["ok"] and act["chain_verified"] and k == 1
                  and native_bool_ok(native, True) and bars_ok and shot_ok
                  and fr["render_fresh"]
                  and rollback["state"] == "off"
                  and rollback["residue_zero"]
                  and rollback["off_report_restored_contains_written"]
                  and rollback["unscaled_native_bool_false"]
                  and v_variant["chain_epoch"] == fr["chain_epoch"]
                  and isinstance(v_variant["chain_epoch"], int))
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    return ok


def _geo02_loadfile_variant(result: dict, ev: lib.Evidence) -> bool:
    case = "GEO-02"
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        m1080 = ctx.make_y4m("geo02-load-1080.y4m", 1920, 1080, frames=24)
        m720 = ctx.make_y4m("geo02-load-720.y4m", 1280, 720, frames=24)
        # start on the 1080p clip EXPLICITLY (the default start media is the
        # FIRST created file; a later make_y4m must not silently swap it)
        s = ctx.start("d-loadfile-same-process", fullscreen=True,
                      media_path=m1080)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        act = activate(s, "integer")
        time.sleep(1.0)
        pa = {"media": "1920x1080", "state": s.ud("state"),
              "gear": s.ud("gear"), "integer_k": s.ud("integer_k"),
              "zoom": s.get("video-zoom"),
              "native_unscaled": native_unscaled(s),
              "epoch": s.ud("chain_epoch")}
        s.set("pause", True)
        loaded = s.cmd("loadfile", str(m720), "replace")
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("w") == 1280
                     and (s.get("video-out-params") or {}).get("h") == 720, 12.0)
        time.sleep(1.5)
        pb = {"media": "1280x720", "state": s.ud("state"),
              "gear": s.ud("gear"), "integer_k": s.ud("integer_k"),
              "zoom": s.get("video-zoom"),
              "native_unscaled": native_unscaled(s),
              "epoch": s.ud("chain_epoch"),
              "vop": s.get("video-out-params"), "pause": s.get("pause")}
        s.set("pause", False)
        rec = p3.same_moment_sample(s)
        fr, _, _ = freshness_block(s, ev, f"{case}-d")
        shot = capture_window(s, ev, case, "d-window")
        shot_ok = bool(shot and (shot["png"]["w"], shot["png"]["h"])
                       == (DISP_W, DISP_H))

        def zoom_is(v, expect):
            return v is not None and abs(float(v) - expect) < 1e-6
        both_active = (pa["state"] == "active" and pa["gear"] == "integer"
                       and pb["state"] == "active" and pb["gear"] == "integer")
        k_ok = pa["integer_k"] == 1 and pb["integer_k"] == 2
        zoom_ok = zoom_is(pa["zoom"], 0.0) and zoom_is(pb["zoom"], 1.0)
        epoch_ok = (isinstance(pb["epoch"], int)
                    and pb["epoch"] > (pa["epoch"] or 0))
        native_ok = native_bool_ok(pa["native_unscaled"], True) \
            and native_bool_ok(pb["native_unscaled"], True)
        variant = {
            "name": "integer-same-process-loadfile-1080-to-720",
            "fullscreen_gate": fsg, "activation": act,
            "loadfile_error": loaded.get("error"),
            "phase_a": pa, "phase_b": pb,
            "phases_both_active_integer": both_active,
            "k_recomputed_1_to_2": k_ok,
            "zoom_rewritten_0_to_1": zoom_ok,
            "epoch_advanced": epoch_ok,
            "native_bool_both_true": native_ok,
            "same_moment": [rec],
            "freshness": fr,
            "window_png_size_ok": shot_ok,
            "note": "fallback 空真被非空真门纠正：两相必须 state=active+gear="
                    "integer，k/zoom/epoch 全部实测（run-001 教训）",
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(fsg["ok"] and act["chain_verified"] and both_active
                  and k_ok and zoom_ok and epoch_ok and native_ok
                  and fr["render_fresh"] and shot_ok)
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    return ok


# ---------------------------------------------------------------------------
# GEO-03 — Integer x nearest strict pixel blocks (uniformity oracle)
# ---------------------------------------------------------------------------

def osd_quadrant_bright_px(dec: dict) -> int:
    """Bright-pixel sample count over the TOP-LEFT half of a capture — the
    plugin/mpv OSD anchor region (smoke-r3/r4: a frozen pause/activation OSD
    sits exactly there and would pollute a full-frame pixel oracle)."""
    gp, w, h = dec["get_pixel"], dec["w"], dec["h"]
    n = 0
    for y in range(0, h // 2, 4):
        for x in range(0, w // 2, 4):
            if max(gp(x, y)) > 40:
                n += 1
    return n


def capture_uniform_frame(s, ev: lib.Evidence, case: str, tag: str,
                          attempts: int = 4) -> tuple:
    """Capture a present-fresh, OSD-free window frame: pause-blip to force
    presents (run-003 stall countermeasure), re-shoot until the OSD anchor
    quadrant is clean (honestly flagged when it never cleans)."""
    last = None
    for i in range(attempts):
        s.set("pause", True)
        time.sleep(0.25)
        s.set("pause", False)
        time.sleep(1.5)
        last = capture_window(s, ev, case, f"{tag}-p{i}")
        if last is None:
            continue
        if osd_quadrant_bright_px(last["decoded"]) == 0:
            return last, True
    return last, False


def case_geo03(ev: lib.Evidence) -> dict:
    case = "GEO-03"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    result["facts"]["dither_note"] = (
        "--dither-depth=no 仅用于本 case（gpu-next 默认抖动会让完美 nearest "
        "2× 块在像素级非恒定，smoke-r2 实测）；本 case 断言的是档位像素语义，"
        "不是 mpv 抖动级")
    result["facts"]["osd_note"] = (
        "OSD 冻结/暂停指示落在左上象限（run-003 停摆教训）：多次 pause-blip "
        "驱散；若仍不洁，则如实标记并在右下象限（构造上无 OSD）做严格块均匀度")
    ok_all = True
    control_stats = None
    ctx = P3Context(ev, case)
    stems = []
    try:
        ctx.make_y4m("geo03-720.y4m", 1280, 720, frames=24)
        s = ctx.start("a-integer-nearest-2x", fullscreen=True,
                      extra_args=["--dither-depth=no"])
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        act = activate(s, "integer")
        wait_osd_gone(s, blip=True)
        k = s.ud("integer_k")
        native = native_unscaled(s)
        scalers = {p: s.get(p) for p in ("scale", "cscale", "dscale")}
        shot, clean = capture_uniform_frame(s, ev, case, "a")
        stats = None
        region_used = "full-frame"
        if shot:
            dec = shot["decoded"]
            if clean:
                stats = p3.block_uniformity(dec["get_pixel"], dec["w"],
                                            dec["h"], block=2)
            else:
                region_used = "bottom-right quadrant (OSD-free by construction)"
                stats = p3.block_uniformity(dec["get_pixel"], dec["w"],
                                            dec["h"], block=2,
                                            region=(dec["w"] // 2,
                                                    dec["h"] // 2,
                                                    dec["w"], dec["h"]))
        v_variant, files = same_moment_variant(s, f"{case}-a", ev, gear="integer")
        # VL3-01 (r2): controlled=True — the frame-step leg ALWAYS runs for
        # GEO-03 so each fresh evidence dir carries the counter-saturation /
        # repeated-pattern alias / pause-restore records, and the winning
        # method is corroborated (counter method itself is never overwritten).
        fr, _, _ = freshness_block(s, ev, f"{case}-a", controlled=True)
        # control capture: gear OFF (baseline bicubic), same procedure/region
        off_ok = s.navigate_and_activate("off") and s.wait_state("off", 8.0)
        time.sleep(1.2)
        control, control_clean = capture_uniform_frame(s, ev, case,
                                                       "a-control-baseline")
        if control:
            cdec = control["decoded"]
            if clean and control_clean:
                control_stats = p3.block_uniformity(cdec["get_pixel"], cdec["w"],
                                                    cdec["h"], block=2)
            else:
                control_stats = p3.block_uniformity(cdec["get_pixel"], cdec["w"],
                                                    cdec["h"], block=2,
                                                    region=(cdec["w"] // 2,
                                                            cdec["h"] // 2,
                                                            cdec["w"], cdec["h"]))
        strict_ok = bool(stats and stats["uniform_blocks"] == stats["blocks"]
                         and stats["uniform_fraction"] == 1.0)
        control_ok = bool(control_stats
                          and control_stats["uniform_fraction"] is not None
                          and control_stats["uniform_fraction"] < 1.0)
        shots_differ = bool(shot and control
                            and shot["sha256"] != control["sha256"])
        variant = {
            "name": "integer-nearest-strict-2x-blocks",
            "fullscreen_gate": fsg, "activation": act,
            "integer_k": k, "native_unscaled": native,
            "scalers": scalers,
            "scalers_all_nearest": all(v == "nearest" for v in scalers.values()),
            "osd_quadrant_clean": clean,
            "uniformity_region_used": region_used,
            "block_uniformity_integer": stats,
            "block_uniformity_baseline_control": control_stats,
            "strict_uniform_fraction_1": strict_ok,
            "control_not_uniform": control_ok,
            "integer_vs_control_shots_differ": shots_differ,
            "same_moment": v_variant["same_moment"],
            "freshness": fr,
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += files
        result["files"] += [f["relp"] for f in (shot, control) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok_all = bool(fsg["ok"] and act["chain_verified"] and k == 2
                      and native_bool_ok(native, True)
                      and all(v == "nearest" for v in scalers.values())
                      and strict_ok and control_ok and shots_differ
                      and fr["render_fresh"] and off_ok
                      and v_variant["chain_epoch"] == fr["chain_epoch"]
                      and isinstance(v_variant["chain_epoch"], int))
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok_all else "FAIL"
    return result


# ---------------------------------------------------------------------------
# GEO-04 — window resize/DPI machine part + external priority + transfer
# ---------------------------------------------------------------------------

def case_geo04(ev: lib.Evidence) -> dict:
    case = "GEO-04"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    result["facts"]["dpi_note"] = (
        "机器部分=窗口尺寸/比例/可观察属性变化+暂停后 k/几何重算；"
        "系统全局 DPI/跨屏真人实操 pending，不改系统设置")
    ok_all = True

    # -- v1: windowed resize recompute (resize applies while PLAYING; the
    #     paused-state consistency is then verified — a paused window-scale
    #     write provably does not resize the window, smoke-r2 evidence) -----
    ctx = P3Context(ev, case)
    stems = []
    try:
        ctx.make_y4m("geo04-720.y4m", 1280, 720, frames=24)
        s = ctx.start("a-resize-recompute", window=(640, 360))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        win0 = window_gate(s, 640, 360)
        act = activate(s, "integer")
        time.sleep(1.0)
        k0 = s.ud("integer_k")
        epoch0 = s.ud("chain_epoch")
        native0 = native_unscaled(s)
        # resize while PLAYING; the plugin must recompute k/epoch from the
        # ORIGINAL window pixels (never its own shrunken margin — anti-
        # feedback).  A lost window-manager event is a real flake (smoke-r3):
        # retry with VALUE ALTERNATION so mpv re-applies instead of no-opping.
        resize_attempts = []
        win_resized = False
        for attempt, scale_value in ((1, 1.25), (2, 1.0), (3, 1.25)):
            set_resp = s.set("current-window-scale", scale_value)
            win_resized = s.wait_until(
                lambda: s.get("osd-width") == 1600
                and s.get("osd-height") == 900, 5.0)
            resize_attempts.append({"attempt": attempt, "scale": scale_value,
                                    "set_error": set_resp.get("error"),
                                    "resized": bool(win_resized),
                                    "osd": [s.get("osd-width"),
                                            s.get("osd-height")]})
            if win_resized:
                break
            time.sleep(1.0)
        recomputed = s.wait_until(
            lambda: isinstance(s.ud("chain_epoch"), int)
            and s.ud("chain_epoch") != epoch0, 6.0)
        time.sleep(1.0)
        win1 = window_gate(s, 1600, 900)
        k1 = s.ud("integer_k")
        epoch1 = s.ud("chain_epoch")
        native1 = native_unscaled(s)
        zoom1 = s.get("video-zoom")
        # paused-state consistency: pause must NOT leave a stale k/geometry
        s.set("pause", True)
        time.sleep(0.6)
        paused_ok = (s.ud("state") == "active" and s.ud("gear") == "integer"
                     and s.ud("integer_k") == k1)
        rec = p3.same_moment_sample(s)
        s.set("pause", False)
        # V4-GEO-CONTRACT: REAL render-freshness proof for the ACTIVE window,
        # measured NOW — after the resize/k/epoch recompute and the paused-
        # consistency leg — at the CURRENT epoch (never copied from a prior
        # case; metadata alone is never render proof).
        fr_a, _, _ = freshness_block(s, ev, f"{case}-a")
        freshness_epoch_matches_recompute = (
            isinstance(fr_a["chain_epoch"], int)
            and fr_a["chain_epoch"] == epoch1)
        # k expectation from the OBSERVED original window pixels & vop
        vop = s.get("video-out-params") or {}
        exp_k = p3.integer_k(s.get("osd-width"), s.get("osd-height"),
                             vop.get("dw"), vop.get("dh"))
        variant = {
            "name": "window-resize-recompute-then-paused-consistency",
            "window_gate_initial": win0,
            "activation": act,
            "before": {"k": k0, "epoch": epoch0, "native": native0},
            "after": {"window": win1, "k": k1, "epoch": epoch1,
                      "native": native1, "zoom": zoom1,
                      "expected_k_from_observed": exp_k},
            "window_resized": bool(win_resized),
            "resize_attempts": resize_attempts,
            "native_unscaled": native1,
            "freshness": fr_a,
            "chain_epoch": fr_a["chain_epoch"],
            "freshness_epoch_matches_recompute": freshness_epoch_matches_recompute,
            "k_epoch_recomputed": bool(recomputed
                                       and epoch1 not in (None, epoch0)),
            "paused_state_consistent": paused_ok,
            "k_matches_oracle": (exp_k is not None and k1 == exp_k),
            "k1_expected_1": k1 == 1,
            "no_crop": (vop.get("w"), vop.get("h")) == (1280, 720),
            "same_moment": [rec],
            "note": "resize 在播放中应用；暂停下 window-scale 写入不会改变窗口"
                    "（smoke-r2 实测），暂停后一致性另证（k/epoch 无陈旧）",
        }
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        v_ok = bool(win0["ok"] and act["chain_verified"] and k0 == 0
                    and win_resized and recomputed and win1["ok"] and k1 == 1
                    and native_bool_ok(native1, True)
                    and (exp_k is not None and k1 == exp_k)
                    and paused_ok
                    and fr_a["render_fresh"]
                    and freshness_epoch_matches_recompute)
        ok_all = ok_all and v_ok
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems

    # -- v2: external zoom/GLSL priority -> transfer -> Off zero residue -----
    ctx = P3Context(ev, case)
    stems = []
    try:
        ctx.make_y4m("geo04-720b.y4m", 1280, 720, frames=24)
        s = ctx.start("b-external-priority-transfer", fullscreen=True)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        baseline = snapshot_props(s)
        act = activate(s, "integer")
        time.sleep(1.0)
        int_state = {"k": s.ud("integer_k"),
                     "native": native_unscaled(s)}
        # external zoom change while integer is active -> plugin must yield
        s.set("video-zoom", 3)
        yielded = s.wait_state("external", 8.0)
        ext_zoom = {"yielded": bool(yielded), "state": s.ud("state"),
                    "zoom_kept": s.get("video-zoom"),
                    "reason": s.ud("reason")}
        ext_zoom["kept_ok"] = ext_zoom["zoom_kept"] is not None \
            and abs(float(ext_zoom["zoom_kept"]) - 3.0) < 1e-6
        # external GLSL append -> still external, never silently overwritten
        cur = s.get("glsl-shaders") or []
        s.set("glsl-shaders", list(cur) + ["~~/p1-test-ext-a.glsl"])
        time.sleep(1.0)
        ext_shader = {"state": s.ud("state"),
                      "chain_now": s.get("glsl-shaders")}
        ext_shader["kept_ok"] = any("p1-test-ext-a" in str(p)
                                    for p in (ext_shader["chain_now"] or []))
        # Off must NOT roll back the external user values — only owned+equal
        off_nav = s.navigate_and_activate("off")
        off_ok_state = s.wait_state("off", 8.0)
        time.sleep(0.8)
        off_state = {"state": s.ud("state"),
                     "zoom_after_off": s.get("video-zoom"),
                     "chain_after_off": s.get("glsl-shaders"),
                     "native_after": native_unscaled(s)}
        # external zoom 3.0 and the external shader must survive Off
        ext_preserved = (off_state["zoom_after_off"] is not None
                         and abs(float(off_state["zoom_after_off"]) - 3.0) < 1e-6
                         and any("p1-test-ext-a" in str(p)
                                 for p in (off_state["chain_after_off"] or [])))
        # restore externals, then Integer->shader transfer with zero residue
        s.set("video-zoom", baseline.get("video-zoom"))
        s.set("glsl-shaders", [])
        time.sleep(0.8)
        act_int2 = activate(s, "integer")
        time.sleep(0.8)
        act_xbr = activate(s, "xbr")
        time.sleep(1.0)
        xbr_state = {"state": s.ud("state"), "gear": s.ud("gear"),
                     "chain": chain_files(s),
                     "zoom": s.get("video-zoom"),
                     "unscaled": s.get("video-unscaled"),
                     "native": native_unscaled(s),
                     "epoch": s.ud("chain_epoch")}
        geom_restored = (xbr_state["zoom"] == baseline.get("video-zoom")
                         and native_bool_ok(xbr_state["native"], False))
        chain_ok = len(xbr_state["chain"]) == 1 \
            and "p3-xBR-lv2.glsl" in str(xbr_state["chain"][0])
        # V4-GEO-CONTRACT: REAL render-freshness proof for the ACTIVE xbr
        # window AFTER the geometry-restoring transfer, measured at the
        # transfer's current epoch (paired below; no borrowed freshness).
        fr_b, _, _ = freshness_block(s, ev, f"{case}-b")
        freshness_epoch_matches_transfer = (
            isinstance(fr_b["chain_epoch"], int)
            and fr_b["chain_epoch"] == xbr_state["epoch"])
        off2 = s.navigate_and_activate("off") and s.wait_state("off", 8.0)
        time.sleep(0.8)
        after = snapshot_props(s)
        residue = residue_vs_baseline(after, baseline)
        rec = p3.same_moment_sample(s)
        variant = {
            "name": "external-priority-then-transfer-then-off-zero-residue",
            "fullscreen_gate": fsg,
            "integer_activation": act,
            "integer_state": int_state,
            "external_zoom": ext_zoom,
            "external_shader": ext_shader,
            "off_keeps_external_values": ext_preserved,
            "off_state_external_phase": off_state,
            "integer_reactivation": act_int2,
            "xbr_transfer": {**xbr_state,
                             "geom_restored": geom_restored,
                             "chain_single_xbr": chain_ok},
            "native_unscaled": xbr_state["native"],
            "freshness": fr_b,
            "chain_epoch": fr_b["chain_epoch"],
            "freshness_epoch_matches_transfer": freshness_epoch_matches_transfer,
            "final_off": {"state": s.ud("state"), "residue": residue,
                          "residue_zero": not residue,
                          "native": native_unscaled(s)},
            "same_moment": [rec],
        }
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        v_ok = bool(fsg["ok"] and act["chain_verified"]
                    and ext_zoom["yielded"] and ext_zoom["kept_ok"]
                    and ext_shader["state"] == "external"
                    and ext_shader["kept_ok"] and ext_preserved
                    and act_int2["chain_verified"] and act_xbr["chain_verified"]
                    and geom_restored and chain_ok and off2
                    and not residue
                    and fr_b["render_fresh"]
                    and freshness_epoch_matches_transfer)
        ok_all = ok_all and v_ok
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok_all else "FAIL"
    return result


# ---------------------------------------------------------------------------
# GEO-05 — rotate/crop effective display geometry (observed-vop oracle)
# ---------------------------------------------------------------------------

def case_geo05(ev: lib.Evidence) -> dict:
    case = "GEO-05"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        media = ctx.make_y4m("geo05-1080.y4m", 1920, 1080, frames=24)
        sar_media = ctx.make_y4m("geo05-sar.y4m", 640, 360, sar="2:1")
        s = ctx.start("rotate-crop-sar", fullscreen=True)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        act = activate(s, "integer")
        osd_w, osd_h = s.get("osd-width"), s.get("osd-height")

        def observe(tag):
            time.sleep(1.0)
            vop = s.get("video-out-params") or {}
            return {"tag": tag, "vop": vop, "state": s.ud("state"),
                    "gear": s.ud("gear"), "integer_k": s.ud("integer_k"),
                    "zoom": s.get("video-zoom"),
                    "native_unscaled": native_unscaled(s),
                    "epoch": s.ud("chain_epoch")}

        phases = {"base_1080": observe("base_1080")}
        s.set("video-rotate", 90)
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("rotate") == 90,
                     8.0)
        phases["rotate90"] = observe("rotate90")
        s.set("video-rotate", 0)
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("rotate") in (0, None),
                     8.0)
        crop_set = s.set("video-crop", "1280x720+320+180")
        crop_method = "video-crop"
        if crop_set.get("error") != "success":
            crop_method = "vf-crop"
            s.cmd("vf", "add", "crop=w=1280:h=720:x=320:y=180")
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("w") == 1280, 8.0)
        phases["crop720"] = observe("crop")
        if crop_method == "video-crop":
            s.set("video-crop", "")
        else:
            s.cmd("vf", "remove", "crop")
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("w") == 1920, 8.0)
        s.cmd("loadfile", str(sar_media), "replace")
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("w") == 640, 12.0)
        time.sleep(1.2)
        phases["sar2x"] = observe("sar2x")
        fr, sm_a, sm_b = freshness_block(s, ev, f"{case}-final")
        consistency = []
        for tag in ("base_1080", "rotate90", "crop720", "sar2x"):
            ph = phases[tag]
            exp = p3.integer_k(osd_w, osd_h,
                               (ph["vop"] or {}).get("dw"),
                               (ph["vop"] or {}).get("dh"))
            consistency.append({"phase": tag,
                                "expected_k_from_observed_vop": exp,
                                "plugin_k": ph["integer_k"],
                                "match": exp == ph["integer_k"]})
        phases_active = all(phases[t]["state"] == "active"
                            and phases[t]["gear"] == "integer"
                            for t in phases)
        k_match = all(c["match"] and c["expected_k_from_observed_vop"] is not None
                      for c in consistency)
        sar_vop = phases["sar2x"]["vop"] or {}
        sar_dw_differs = sar_vop.get("dw") != sar_vop.get("w")
        native_ok = all(native_bool_ok(phases[t]["native_unscaled"], True)
                        for t in phases)
        variant = {
            "name": "integer-rotate-crop-sar-observed-vop-oracle",
            "fullscreen_gate": fsg, "activation": act,
            "osd": {"w": osd_w, "h": osd_h},
            "crop_method": crop_method,
            "crop_set_error": crop_set.get("error"),
            "phases": phases,
            "native_unscaled": phases["sar2x"]["native_unscaled"],
            "phases_all_active_integer": phases_active,
            "k_consistency": consistency,
            "k_match_ok": k_match,
            "sar_dw_differs_from_w": sar_dw_differs,
            "same_moment": [sm_a, sm_b],
            "freshness": fr,
            "note": "每相 k 必须与该相观察到的 vop(dw,dh) 推导一致；"
                    "fallback 里仅比较 k 是空真（run-001 教训）",
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(fsg["ok"] and act["chain_verified"] and phases_active
                  and k_match and sar_dw_differs and native_ok
                  and fr["render_fresh"])
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# GEO-06 — SAR non-square display (k from dw/dh; aspect preserved)
# ---------------------------------------------------------------------------

def case_geo06(ev: lib.Evidence) -> dict:
    case = "GEO-06"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        ctx.make_y4m("geo06-sar.y4m", 640, 360, frames=24, sar="2:1")
        s = ctx.start("sar-2x1", fullscreen=True)
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        fsg = fullscreen_gate(s)
        act = activate(s, "integer")
        time.sleep(3.6)
        _clear_osd_blip(s)
        k = s.ud("integer_k")
        native = native_unscaled(s)
        vop = s.get("video-out-params") or {}
        osd_w, osd_h = s.get("osd-width"), s.get("osd-height")
        exp_k = p3.integer_k(osd_w, osd_h, vop.get("dw"), vop.get("dh"))
        exp_k_wh = p3.integer_k(osd_w, osd_h, vop.get("w"), vop.get("h"))
        aspect = None
        if vop.get("dw") and vop.get("dh"):
            aspect = round(vop["dw"] / float(vop["dh"]), 4)
        shot = capture_window(s, ev, case, "window")
        bars = None
        if shot:
            dec = shot["decoded"]
            fb = bars_fallback_scan(dec)
            bars = {k2: fb.get(k2) for k2 in ("left", "right", "top", "bottom")}
        # expected geometry: display 1280x360 * k=2 -> 2560x720 content,
        # top/bottom bars 360 each, left/right 0.
        bars_ok = bool(bars) and all([
            bars.get("left") is not None and bars["left"] <= 2,
            bars.get("right") is not None and bars["right"] <= 2,
            bars.get("top") is not None and abs(bars["top"] - 360) <= 3,
            bars.get("bottom") is not None and abs(bars["bottom"] - 360) <= 3,
        ])
        v_variant, files = same_moment_variant(s, case, ev, gear="integer",
                                               shot_tag="sm")
        fr, _, _ = freshness_block(s, ev, f"{case}-final")
        variant = {
            "name": "integer-sar-2x1-k-from-dw-dh",
            "fullscreen_gate": fsg, "activation": act,
            "integer_k": k,
            "expected_k_from_observed_dw_dh": exp_k,
            "naive_k_from_w_h_would_be": exp_k_wh,
            "dw_differs_from_w": vop.get("dw") != vop.get("w"),
            "display_aspect": aspect,
            "aspect_matches_dw_dh": aspect is not None
                                    and abs(aspect - 1280 / 360.0) < 0.01,
            "native_unscaled": native,
            "bars_expected": {"left": 0, "right": 0, "top": 360, "bottom": 360},
            "bars_measured": bars,
            "bars_ok": bars_ok,
            "same_moment": v_variant["same_moment"],
            "freshness": fr,
            "note": "k 必须取 dw/dh（SAR 感知），非 w/h；显示比例正确、"
                    "无拉伸黑边错误",
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += files + [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        ok = bool(fsg["ok"] and act["chain_verified"] and k == 2
                  and exp_k == 2 and k != exp_k_wh
                  and vop.get("dw") != vop.get("w")
                  and native_bool_ok(native, True)
                  and aspect is not None and abs(aspect - 1280 / 360.0) < 0.01
                  and bars_ok and fr["render_fresh"]
                  and v_variant["chain_epoch"] == fr["chain_epoch"]
                  and isinstance(v_variant["chain_epoch"], int))
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# WINDOW-01 — resize/pause/aspect/loadfile/restart with P3 structured records
# ---------------------------------------------------------------------------

def case_window01(ev: lib.Evidence) -> dict:
    case = "WINDOW-01"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        ctx.make_y4m("window01-a.y4m", 640, 360, frames=24)
        s = ctx.start("resize-pause-aspect-clip", window=(960, 540))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        act = activate(s, "fsr1")
        epoch0 = s.ud("chain_epoch")
        # 1) pause + resize: state stays active, desc present (same window)
        s.set("pause", True)
        time.sleep(0.4)
        s.set("current-window-scale", 2.0)
        time.sleep(1.2)
        paused_rec = p3.same_moment_sample(s)
        paused_desc = desc_evidence(ev, s, p2.FSR_DESC_KEYWORDS, stems)
        paused_ok = (s.ud("state") == "active"
                     and s.ud("chain_keywords") is not None)
        s.set("pause", False)
        time.sleep(0.6)
        # 2) aspect override — geometry re-evaluation, epoch non-decreasing
        s.set("video-aspect-override", "4:3")
        time.sleep(1.2)
        aspect_rec = p3.same_moment_sample(s)
        epoch_a = s.ud("chain_epoch")
        s.set("video-aspect-override", "16:9")
        # 3) clip change 640x360 -> 320x240 — reconfig, no stale passes
        media2 = ctx.env.root / "media" / "window01-b.y4m"
        ctx.make_y4m("window01-b.y4m", 320, 240, frames=12)
        s.cmd("loadfile", str(media2), "replace")
        s.wait_until(lambda: (s.get("video-out-params") or {}).get("w") == 320,
                     12.0)
        time.sleep(1.5)
        clip_rec = p3.same_moment_sample(s)
        clip_desc = desc_evidence(ev, s, p2.FSR_DESC_KEYWORDS, stems)
        epoch_c = s.ud("chain_epoch")
        glsl_still = s.get("glsl-shaders")
        fr, sm_a, sm_b = freshness_block(s, ev, f"{case}-steps")
        alive = s.proc.poll() is None
        clean = log_clean(ev, stems)
        epochs = [e for e in (epoch0, epoch_a, epoch_c)
                  if isinstance(e, int)]
        nondec = all(b >= a for a, b in zip(epochs, epochs[1:])) if epochs else False
        shot = capture_window(s, ev, case, "after-steps")
        variant = {
            "name": "resize-pause-aspect-clipchange",
            "activation": act,
            "paused_same_moment": paused_rec,
            "paused_desc_hit": paused_desc["vo_passes_hit_count"] >= 1,
            "paused_state_active_consistent": paused_ok,
            "aspect_same_moment": aspect_rec,
            "clip_same_moment": clip_rec,
            "clip_desc_still_hit": clip_desc["vo_passes_hit_count"] >= 1,
            "glsl_unchanged": glsl_still == ["~~/shaders/p2-FSR1.glsl"],
            "epochs_recorded": epochs,
            "epochs_non_decreasing": nondec,
            "same_moment": [sm_a, sm_b],
            "freshness": fr,
            "mpv_alive": alive, "mpv_log_clean": clean,
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += [f["relp"] for f in (shot,) if f]
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        part_a = bool(act["chain_verified"] and paused_ok
                      and paused_desc["vo_passes_hit_count"] >= 1
                      and clip_desc["vo_passes_hit_count"] >= 1
                      and glsl_still == ["~~/shaders/p2-FSR1.glsl"]
                      and nondec and alive and clean and fr["render_fresh"])
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems

    # restart-clean session (P2 semantics preserved)
    ctx = P3Context(ev, case)
    stems_b = []
    s2 = None
    try:
        ctx.make_y4m("window01-r.y4m", 320, 240, frames=12)
        s = ctx.start("quit-restart-clean", window=(640, 480))
        stems_b.append(s.case_name)
        s.wait_state("off", 12.0)
        quit_ok = activate(s, "fsr1")["chain_verified"]
        s.quit()
        exit_code = s.wait_exit(20.0)
        s2 = lib.MpvSession(ctx.env, f"{case}-restart", ev.dir, session=SESSION)
        stems_b.append(s2.case_name)
        s2.start(media=ctx.media, extra_args=["--loop-file=inf"])
        restarted_off = s2.wait_state("off", 8.0)
        clean2 = s2.get("glsl-shaders") == [] and s2.get("scale") == "bicubic"
        variant = {
            "name": "quit-restart-no-residue",
            "quit_ok": bool(quit_ok), "exit_code": exit_code,
            "restarted_state_off": bool(restarted_off),
            "restarted_clean": bool(clean2),
            "backend": p1v.backend_facts(s2),
        }
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt")
                            for stem in stems_b]
        part_b = bool(quit_ok and exit_code == 0 and restarted_off and clean2)
    finally:
        if ctx.session is not None:
            finish_session(ev, result, ctx)
        if s2 is not None:
            try:
                s2.quit(timeout_s=10)
            except Exception:  # noqa: BLE001
                pass
            try:
                result["files"].append(dump_transcript(ev, s2))
            except Exception:  # noqa: BLE001
                pass
            if s2.proc is not None and s2.proc.poll() is None:
                s2.kill()
        ctx.cleanup()
    result["sessions"] += stems_b
    result["status"] = "PASS" if (part_a and part_b) else "FAIL"
    return result


# ---------------------------------------------------------------------------
# PER-04-COMPUTE — raw ns samples only, never a performance-gain claim
# ---------------------------------------------------------------------------

def case_per04(ev: lib.Evidence) -> dict:
    case = "PER-04-COMPUTE"
    result = {"id": case, "variants": [], "files": [], "facts": {}, "sessions": []}
    ctx = P3Context(ev, case)
    stems = []
    ok = False
    try:
        ctx.make_y4m("per04.y4m", 640, 360, frames=48)
        s = ctx.start("nis-compute-samples", window=(1366, 768))
        stems.append(s.case_name)
        s.wait_state("off", 12.0)
        act = activate(s, "nis")
        time.sleep(1.5)
        samples_ns: list = []
        note_windows = 0
        for _ in range(3):
            vp = s.get("vo-passes") or {}
            got_any = False
            for frame in ("fresh", "redraw"):
                for item in (vp.get(frame) or []):
                    if not isinstance(item, dict):
                        continue
                    desc = str(item.get("desc", ""))
                    if any(kw in desc for kw in p3.NIS_DESC_KEYWORDS):
                        for v in (item.get("samples") or []):
                            if isinstance(v, (int, float)) and v > 0:
                                samples_ns.append(int(v))
                                got_any = True
            if got_any:
                note_windows += 1
            time.sleep(1.0)
        fr, sm_a, sm_b = freshness_block(s, ev, case)
        variant = {
            "name": "nis-compute-fresh-redraw-raw-samples",
            "activation": act,
            "backend_compute": "gpu-next + vulkan（//!COMPUTE compute pass）",
            "same_moment": [sm_a, sm_b],
            "freshness": fr,
        }
        variant["chain_epoch"] = fr["chain_epoch"]
        result["variants"].append(variant)
        result["files"] += [relp(ev.dir / f"{stem}.console.txt") for stem in stems]
        result["facts"] = {
            "perf_samples_ns": samples_ns,
            "samples_note": (
                f"原始 fresh/redraw GPU ns 样本（NIS compute pass，{note_windows} 个"
                "采样窗逐值收集，无聚合/无取舍）；本阶段仅记录后端 compute 可行性"
                "与原始样本，绝不宣称性能收益；RIFE 竞争依赖无受保护路径写入的"
                "证明不可得 → 如实未测，留 P4"),
            "rife_untested_left_to_p4": True,
            "no_performance_gain_claim": True,
        }
        ok = bool(act["chain_verified"] and fr["render_fresh"]
                  and len(samples_ns) >= 2
                  and all(isinstance(x, int) and x > 0 for x in samples_ns)
                  and isinstance(fr.get("chain_epoch"), int)
                  and fr["chain_epoch"] >= 0)
    finally:
        finish_session(ev, result, ctx)
        ctx.cleanup()
    result["sessions"] += stems
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# UNIT-P3-01 — the P3 pure-function unit suites, re-run for real
# ---------------------------------------------------------------------------

P3_UNIT_MODULES = ["test_p3_geometry", "test_p3_support", "test_p3_evidence"]


def case_unit_p3_01(ev: lib.Evidence) -> dict:
    result = {"id": "UNIT-P3-01", "variants": [], "files": [], "facts": {},
              "sessions": []}
    ok_all = True
    total = 0
    for mod in P3_UNIT_MODULES:
        cmd = [sys.executable, "-B", "-X", "utf8", "-m", "unittest", mod]
        proc = subprocess.run(cmd, cwd=str(lib.REPO_ROOT / "tests"),
                              capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env={**{k: v for k, v in os.environ.items()
                                      if k in lib.SAFE_ENV_KEYS},
                                   "SYSTEMROOT": os.environ.get("SystemRoot", ""),
                                   "PATH": os.environ.get("PATH", "")})
        tail = (proc.stdout or "") + "\n" + (proc.stderr or "")
        m = re.search(r"Ran (\d+) tests? in", tail)
        n = int(m.group(1)) if m else 0
        total += n
        mod_ok = proc.returncode == 0 and bool(re.search(r"^OK\b", tail, re.M))
        result["variants"].append({
            "name": mod, "command": " ".join(cmd), "returncode": proc.returncode,
            "tests": n, "ok": mod_ok, "tail": tail[-1200:],
        })
        p = ev.write_json(f"UNIT-P3-01.{mod}.log", {
            "module": mod, "returncode": proc.returncode, "tests": n,
            "output_tail": tail[-4000:]})
        result["files"].append(relp(p))
        ok_all = ok_all and mod_ok
    result["facts"]["total_p3_unit_tests"] = total
    result["facts"]["includes_evidence_gate_negative_matrix"] = True
    result["status"] = "PASS" if (ok_all and total >= 100) else "FAIL"
    return result


# ---------------------------------------------------------------------------
# EVI-01 — the evidence machine gate exercised against itself (sandbox)
# ---------------------------------------------------------------------------

EVI_NEGATIVE_DETECTORS = {
    "path_traversal": ["路径非法", "证据目录之外", "非法证据引用", "逃逸仓库"],
    "manifest_omission": ["全目录覆盖漏项", "清单条目在证据目录中缺失",
                          "无 case 声明", "未进清单"],
    "wrong_hash": ["SHA-256 不符", "哈希与磁盘不符"],
    "replaced_png": ["疑似替换 PNG", "声明尺寸与真实解码不符", "不是可解码 PNG"],
    "fake_desc_samples": ["伪造样本", "样本行未在任何会话"],
    "zero_zero_counting": ["0==0"],
    "decoder_fake_freshness": ["不是真实渲染新帧证据", "解码活性不能兜底"],
    "stale_epoch": ["陈旧 epoch 配对"],
    "native_bool_violation": ["非原生 bool"],
    "restart_missing": ["缺少", "漏收", "无 case 声明"],
}


def _evi_make_png(w: int, h: int, salt: int = 0) -> bytes:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + ctype + data
                + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(((x * 7 + salt) % 256, (y * 11 + salt) % 256,
                          (x * y + salt) % 256))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def _evi_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2)
                      + "\n").encode("utf-8"))


def _evi_desc_line(kw_line: str) -> str:
    return f"[vo/gpu-next/libplacebo] Registering hook pass: {kw_line}"


def _evi_build_positive_control(repo: Path, session: str) -> Path:
    """A complete honest mini evidence tree for the 35 required ids inside a
    THROWAWAY synthetic repo (never the real evidence trees)."""
    run_dir = repo / "docs" / "验证" / "开发" / session / "implementer" / "run1"
    d = run_dir
    d.mkdir(parents=True, exist_ok=True)
    cases: list = []
    png_a = _evi_make_png(8, 6, salt=1)
    png_b = _evi_make_png(8, 6, salt=1)      # duplicate content (honest mark)
    png_c = _evi_make_png(9, 5, salt=2)
    (d / "GEO-02-s1.window.png").write_bytes(png_a)
    (d / "GEO-02-s1.window-dup.png").write_bytes(png_b)
    (d / "SHD-05-a.window.png").write_bytes(png_c)

    def triplet(stem: str, log_lines: list | None = None) -> None:
        (d / f"{stem}.console.txt").write_bytes(
            f"[runner] {stem} start\n[runner] {stem} done\n".encode("utf-8"))
        log = "\n".join(log_lines or [f"[vo] {stem} generic frame"]) + "\n"
        (d / f"{stem}.mpv.log").write_bytes(log.encode("utf-8"))
        (d / f"{stem}.mpv.transcript.jsonl").write_bytes(
            '{"req":["get_property","scale-selector/state"]}\n'
            '{"res":"active"}\n'.encode("utf-8"))

    def sessions(cid: str, restarts: int = 1,
                 log_lines: list | None = None) -> list:
        stems = [f"{cid}-s1"] + [f"{cid}-s1-r{i}" for i in range(2, restarts + 1)]
        for stem in stems:
            triplet(stem, log_lines)
        return stems

    sm_rec = {"pixelformat": "yuv420p", "w": 1280, "h": 720, "dw": 2560,
              "dh": 1440, "osd_w": 2560, "osd_h": 1440,
              "vo_passes_frame_counts": {"fresh": 2, "redraw": 1},
              "same_window": True}

    def sm(fmt: str = "yuv420p") -> dict:
        rec = dict(sm_rec)
        rec["pixelformat"] = fmt
        return rec

    fresh = {"render_fresh": True, "method": "vo-passes-fresh-increase",
             "chain_epoch": 3, "fresh_before": 1, "fresh_after": 2}
    nis_line = _evi_desc_line(p3.NIS_DESC_KEYWORDS[0])
    for cid in P3_REQUIRED_IDS:
        case = {"id": cid, "status": "PASS", "files": [], "variants": []}
        if cid in gate.NO_MPV_CASES:
            if cid == "EVI-01":
                case["facts"] = {
                    "negatives_detected": {k: True for k in gate.EVI_NEGATIVE_KEYS},
                    "positive_control_clean": True}
            cases.append(case)
            continue
        if cid in ("SHD-05", "SHD-06", "SHD-07"):
            kw = {"SHD-05": p3.NIS_DESC_KEYWORDS[0],
                  "SHD-06": p3.XBR_DESC_KEYWORDS[0],
                  "SHD-07": p3.SHARP_AUTO_DESC_KEYWORDS[0]}[cid]
            line = _evi_desc_line(kw)
            case["sessions"] = sessions(cid, restarts=2, log_lines=[line])
            case["variants"] = [{
                "desc_evidence": {"count": 1, "sample_hits": {kw: [line]}},
                "chain_epoch": 3, "same_moment": [sm()], "freshness": fresh,
            }]
        elif cid in ("SHD-01", "SHD-02"):
            case["sessions"] = sessions(cid)
            case["variants"] = [{"desc_keyword_pass_hits": 3}]
        elif cid == "SHD-04":
            case["sessions"] = sessions(cid)
            case["variants"] = [{"required_desc_hits": {"anime4k": True}}]
        elif cid == "SHD-09":
            case["sessions"] = sessions(cid)
            case["variants"] = [
                {"bitdepth": 8, "same_moment": [sm()]},
                {"bitdepth": 10, "same_moment": [sm("yuv420p10le")]},
            ]
        elif cid == "PER-04-COMPUTE":
            case["sessions"] = sessions(cid)
            case["variants"] = [{"chain_epoch": 3, "same_moment": [sm()],
                                 "freshness": fresh}]
            case["facts"] = {"perf_samples_ns": [120000, 340000, 290000],
                             "samples_note": "raw ns samples; no gain claim"}
        elif cid in gate.SAME_MOMENT_CASES:
            case["sessions"] = sessions(cid)
            variant = {"chain_epoch": 3, "same_moment": [sm()],
                       "freshness": fresh}
            if cid in gate.INTEGER_NATIVE_BOOL_CASES:
                variant["native_unscaled"] = {"native_type": "bool",
                                              "value": False}
            case["variants"] = [variant]
        else:
            case["sessions"] = sessions(cid)
        cases.append(case)

    nis_line_b = _evi_desc_line(p3.NIS_DESC_KEYWORDS[0])
    results = {
        "stage": "P3", "session": session, "required_unmeasured": [],
        "live_configuration_written": False,
        "cases": cases,
        "png_captures": [
            {"path": f"docs/验证/开发/{session}/implementer/run1/GEO-02-s1.window.png",
             "w": 8, "h": 6, "sha256": lib.sha256_bytes(png_a)},
            {"path": f"docs/验证/开发/{session}/implementer/run1/GEO-02-s1.window-dup.png",
             "w": 8, "h": 6, "sha256": lib.sha256_bytes(png_b)},
            {"path": f"docs/验证/开发/{session}/implementer/run1/SHD-05-a.window.png",
             "w": 9, "h": 5, "sha256": lib.sha256_bytes(png_c)},
        ],
        "non_corroborative_png": [{
            "files": [
                f"docs/验证/开发/{session}/implementer/run1/GEO-02-s1.window.png",
                f"docs/验证/开发/{session}/implementer/run1/GEO-02-s1.window-dup.png",
            ],
            "reason": "同 SHA-256 重复内容（合成对照），诚实标注不具重复佐证力",
        }],
        "notes": ["EVI-01 sandbox positive control"],
    }
    _evi_write_json(d / "objective-results.json", results)
    (d / "runner.console.txt").write_bytes(
        "[runner] p3 sandbox positive control\n".encode("utf-8"))
    # bind every on-disk file except the closed exclusion class
    names = sorted(p.name for p in d.iterdir() if p.is_file())
    bound = [d / n for n in names
             if n not in gate.EXCLUDED_FROM_MANIFEST]
    manifest = lib.build_evidence_manifest(session, bound, repo_root=repo)
    _evi_write_json(d / "evidence-manifest.json", manifest)
    _evi_write_json(d / "manifest-verify.json", {
        "schema": gate.MANIFEST_VERIFY_SCHEMA, "session": session,
        "evidence_manifest_sha256": lib.sha256_file(d / "evidence-manifest.json"),
        "runner_console_sha256": lib.sha256_file(d / "runner.console.txt"),
    })
    return d


def _evi_clone(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def case_evi01(ev: lib.Evidence) -> dict:
    result = {"id": "EVI-01", "variants": [], "files": [], "facts": {},
              "sessions": []}
    sandbox_root = Path(tempfile.mkdtemp(prefix="p3-evi01-"))
    detected: dict = {}
    details: dict = {}
    positive_clean = False
    try:
        session = "p3-evi-sandbox"
        pos_repo = sandbox_root / "pos"
        pos_dir = _evi_build_positive_control(pos_repo, session)
        problems = gate.run_full_gate(
            pos_dir, session,
            pos_dir / "objective-results.json",
            pos_dir / "evidence-manifest.json",
            True, repo_root=pos_repo)
        positive_clean = not problems
        details["positive_control_problems"] = problems
        for cls in sorted(gate.EVI_NEGATIVE_KEYS):
            neg_repo = sandbox_root / f"neg-{cls}"
            neg_dir = _evi_build_positive_control(neg_repo, session)
            problems = _evi_plant_negative(cls, neg_dir)
            problems = problems or gate.run_full_gate(
                neg_dir, session,
                neg_dir / "objective-results.json",
                neg_dir / "evidence-manifest.json",
                True, repo_root=neg_repo)
            keywords = EVI_NEGATIVE_DETECTORS[cls]
            matched = [p for p in problems
                       if any(k in p for k in keywords)]
            detected[cls] = bool(matched)
            details[cls] = {"planted": True, "detected": bool(matched),
                            "matched_problems": matched[:3],
                            "all_problems": problems[:6]}
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)
    report = {
        "schema": "p3-evi01-sandbox-report/v1",
        "session": SESSION,
        "checker": "tools/p3_check_evidence.py run_full_gate (imported, real code)",
        "sandbox": "system-temp throwaway synthetic repo（证据目录外，零残留）",
        "positive_control_clean": positive_clean,
        "negatives": details,
        "note": "负例全部真实植入沙箱并对本 checker 实测；未在证据目录内植入越名文件",
    }
    p = ev.write_json("EVI-01.sandbox-report.json", report)
    result["files"].append(relp(p))
    result["facts"] = {
        "negatives_detected": detected,
        "positive_control_clean": positive_clean,
        "sandbox_outside_evidence_dir": True,
    }
    ok = positive_clean and all(detected.get(k) is True
                                for k in gate.EVI_NEGATIVE_KEYS)
    result["status"] = "PASS" if ok else "FAIL"
    return result


def _evi_plant_negative(cls: str, d: Path) -> list:
    """Mutate the sandbox control for one class; return problems found by a
    first gate pass where the mutation alone already triggers detection
    (mutation of results.json happens BEFORE the gate runs — the gate must
    catch it)."""
    results_path = d / "objective-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in results["cases"]}
    if cls == "path_traversal":
        cases["CTL-01"]["files"] = ["docs/验证/开发/p3-evi-sandbox/../../evil.txt"]
    elif cls == "manifest_omission":
        (d / "GEO-03-s1.unbound.txt").write_bytes(b"unbound\n")
    elif cls == "wrong_hash":
        p = d / "CTL-02-s1.mpv.log"
        p.write_bytes(p.read_bytes() + b"tampered\n")
    elif cls == "replaced_png":
        (d / "SHD-05-a.window.png").write_bytes(_evi_make_png(9, 5, salt=99))
    elif cls == "fake_desc_samples":
        v = cases["SHD-06"]["variants"][0]
        v["desc_evidence"]["sample_hits"] = {
            "xbr": ["[vo] fabricated line that exists nowhere in the logs"]}
        _evi_write_json(results_path, results)
        return []
    elif cls == "zero_zero_counting":
        cases["SHD-01"]["variants"][0]["desc_keyword_pass_hits"] = 0
    elif cls == "decoder_fake_freshness":
        for c in cases.values():
            for v in c.get("variants", []):
                if "freshness" in v:
                    v["freshness"]["method"] = "decoder-time-pos-advance"
    elif cls == "stale_epoch":
        for c in cases.values():
            for v in c.get("variants", []):
                if "freshness" in v:
                    v["freshness"]["chain_epoch"] = \
                        v["freshness"]["chain_epoch"] + 5
    elif cls == "native_bool_violation":
        for c in cases.values():
            for v in c.get("variants", []):
                if "native_unscaled" in v:
                    v["native_unscaled"] = {"native_type": "string",
                                            "value": "yes"}
    elif cls == "restart_missing":
        (d / "SHD-05-s1-r2.mpv.transcript.jsonl").unlink()
    else:
        raise AssertionError(f"unknown EVI negative class {cls}")
    _evi_write_json(results_path, results)
    return []


# ---------------------------------------------------------------------------
# probe — light backend capability preflight (own evidence dir)
# ---------------------------------------------------------------------------

def run_probe(ev: lib.Evidence, console: RunnerConsole) -> bool:
    console.log("probe: mpv/vulkan/compute preflight")
    ctx = P3Context(ev, "probe")
    ok = False
    try:
        s = ctx.start("idle", extra_args=["--idle=once"])
        s.wait_until(lambda: isinstance(s.get("mpv-version"), str), 15.0)
        facts = {
            "mpv_version": s.get("mpv-version"),
            "ffmpeg_version": s.get("ffmpeg-version"),
            "vo": s.get("vo"),
            "gpu_api": s.get("gpu-api"),
            "gpu_context": s.get("gpu-context"),
            "osd_dimensions": {"w": s.get("osd-width"), "h": s.get("osd-height")},
            "display_fps": s.get("display-fps"),
            "mpv_exe": lib.MPV_EXE,
        }
        s.quit()
        inputsha = ctx.save_inputsha()
        p = ev.write_json("probe.json", facts)
        files = [relp(p)] + ([inputsha] if inputsha else [])
        console.log("probe facts: " + json.dumps(facts, ensure_ascii=False)[:400])
        ok = bool(facts["mpv_version"] and facts["vo"] == "gpu-next")
    finally:
        if ctx.session is not None and ctx.session.proc is not None \
                and ctx.session.proc.poll() is None:
            ctx.session.kill()
        ctx.cleanup()
    return ok


# ---------------------------------------------------------------------------
# reused P2 cases + runner
# ---------------------------------------------------------------------------

CASES = {}


def _register_cases() -> None:
    for cid in REUSED_P2_IDS:
        CASES[cid] = p2v.CASES[cid]
    for cid, fn in {
        "SHD-05": case_shd05, "SHD-06": case_shd06, "SHD-07": case_shd07,
        "SHD-09": case_shd09, "SHD-10": case_shd10, "SHD-11": case_shd11,
        "GEO-02": case_geo02, "GEO-03": case_geo03, "GEO-04": case_geo04,
        "GEO-05": case_geo05, "GEO-06": case_geo06,
        "WINDOW-01": case_window01, "PER-04-COMPUTE": case_per04,
        "UNIT-P3-01": case_unit_p3_01, "EVI-01": case_evi01,
    }.items():
        CASES[cid] = fn


_register_cases()

# Session-correct reuse: the frozen p2/p1 harnesses parameterize their
# contexts from these module globals at CALL time.
p2v.SESSION = SESSION
p1v.SESSION = SESSION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=sorted(CASES),
                        help="run one required id (repeatable)")
    parser.add_argument("--only", action="append", default=None,
                        help="comma-separated subset of ids (repeatable)")
    parser.add_argument("--all", action="store_true",
                        help="run the full 35-id matrix")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--probe", action="store_true",
                        help="light mpv/vulkan/compute preflight only")
    parser.add_argument("--session", default=None,
                        help="session id; REQUIRED for any run (p3-001)")
    parser.add_argument("--evidence-dir", required=True,
                        help="evidence directory; REQUIRED, must be a FRESH "
                             "dir inside the repo session tree (no --force)")
    args = parser.parse_args()

    if args.list:
        for k in sorted(CASES):
            print(k)
        return 0

    global SESSION
    if not args.session or not re.fullmatch(r"p3-[a-z0-9][a-z0-9-]{0,62}",
                                            args.session):
        parser.error("--session is required (e.g. p3-001)")
    SESSION = args.session
    p2v.SESSION = SESSION
    p1v.SESSION = SESSION

    selected = sorted(CASES) if args.all else []
    if args.only:
        for chunk in args.only:
            for tok in chunk.split(","):
                tok = tok.strip()
                if not tok:
                    continue
                if tok not in CASES:
                    parser.error(f"--only: unknown id {tok!r}")
                if tok not in selected:
                    selected.append(tok)
    selected = selected or (args.case or [])
    if not selected and not args.probe:
        parser.error("choose --all, --probe, --only or at least one --case")

    ev_abs = Path(args.evidence_dir).resolve()
    try:
        ev_rel = ev_abs.relative_to(lib.REPO_ROOT).as_posix()
    except ValueError:
        parser.error(f"--evidence-dir must live inside the repo ({lib.REPO_ROOT})")
    lib.ensure_fresh_evidence_dir(ev_abs, force=False)  # refuse reuse BEFORE mpv
    ev_rel_dir = f"{lib.SESSIONS_ROOT}/{SESSION}"
    if ev_rel != ev_rel_dir and not ev_rel.startswith(ev_rel_dir + "/"):
        parser.error(f"--evidence-dir must be inside the session tree {ev_rel_dir}/")

    evidence = lib.Evidence(ev_abs)
    console = RunnerConsole(ev_abs)
    failures: list = []
    exit_code = 0
    try:
        console.log(f"p3_verify session={SESSION} evidence={ev_rel} "
                    f"create-only (reuse refused before any mpv start)")
        console.log(f"mpv={lib.MPV_EXE} vo=gpu-next gpu-api=vulkan "
                    f"isolated temp cfg (no live config writes)")
        source_pins = {rel: lib.sha256_file(lib.REPO_ROOT / rel)
                       for rel in SOURCE_PINS}
        pins_path = evidence.write_json("source-pins.json", {
            "note": "本轮 harness 实际引用的产品/工具源 SHA-256（只读留痕）",
            "pins": source_pins})
        probe_ok = True
        probe_bound: list = []
        if args.probe:
            probe_ok = run_probe(evidence, console)
            probe_bound = [relp(ev_abs / "probe.json")]
            if (ev_abs / f"probe.inputsha.json").exists():
                probe_bound.append(relp(ev_abs / "probe.inputsha.json"))
            console.log(f"probe: {'PASS' if probe_ok else 'FAIL'}")
        if selected:
            cases_out = []
            new_artifacts: set = set()
            for cid in selected:
                console.log(f"running {cid} ...")
                before = {p for p in ev_abs.rglob("*") if p.is_file()}
                started = time.time()
                try:
                    case_result = CASES[cid](evidence)
                except Exception as error:  # noqa: BLE001 — record, never hide
                    case_result = {"id": cid, "status": "FAIL",
                                   "error": repr(error)}
                elapsed = round(time.time() - started, 1)
                after = {p for p in ev_abs.rglob("*") if p.is_file()}
                new_files = after - before
                stems = sorted({
                    p.name[:-len(".console.txt")] for p in new_files
                    if p.name.endswith(".console.txt") and p.parent == ev_abs})
                bound_files = sorted({relp(p) for p in new_files})
                for f in case_result.get("files") or []:
                    if f not in bound_files:
                        bound_files.append(f)
                case_entry = {
                    "id": cid,
                    "status": case_result.get("status", "FAIL"),
                    "sessions": case_result.get("sessions") or stems,
                    "files": bound_files,
                    "variants": case_result.get("variants") or [],
                    "facts": case_result.get("facts") or {},
                    "elapsed_s": elapsed,
                    "repro_command": (
                        f"python -X utf8 tools/p3_verify.py --case {cid} "
                        f"--session {SESSION} --evidence-dir {ev_rel}"),
                }
                if case_result.get("error"):
                    case_entry["error"] = case_result["error"]
                cases_out.append(case_entry)
                swept = sweep_orphan_sessions()
                if swept:
                    console.log(f"{cid}: orphan sessions force-killed "
                                f"(own PIDs only): {swept}")
                    case_entry["orphan_sessions_swept"] = swept
                console.log(f"{cid}: {case_entry['status']} ({elapsed}s)")
                if case_entry["status"] != "PASS":
                    failures.append(cid)
            # png captures: every PNG on disk, true decoded dims + sha
            png_captures = []
            groups: dict = {}
            for p in sorted(ev_abs.rglob("*")):
                if not p.is_file() or p.suffix.lower() != ".png":
                    continue
                data = p.read_bytes()
                if not data:
                    continue
                try:
                    dec = p3.decode_png(data)
                    w, h = dec["w"], dec["h"]
                except ValueError:
                    w, h = (png_size_fast(data) or (None, None))
                cap = {"path": relp(p), "w": w, "h": h,
                       "sha256": lib.sha256_bytes(data)}
                png_captures.append(cap)
                groups.setdefault(cap["sha256"], []).append(cap["path"])
            non_corroborative = [
                {"files": rels,
                 "reason": "同 SHA-256 重复内容（同帧重采/相同黑帧）；重复图标"
                           "不具佐证力，证据仅计一次，不伪造重采成功"}
                for rels in sorted(groups.values()) if len(rels) > 1]
            covered = {c["id"] for c in cases_out}
            summary = {
                "stage": STAGE,
                "session": SESSION,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "evidence_dir": ev_rel,
                "create_only": True,
                "required_test_ids": P3_REQUIRED_IDS,
                "required_unmeasured": sorted(set(P3_REQUIRED_IDS) - covered),
                "live_configuration_written": False,
                "backend_pin": {"vo": "gpu-next", "gpu_api": "vulkan",
                                "mpv_exe": lib.MPV_EXE,
                                "note": "直呼 mpv.exe + list-argv；全屏经命令行"
                                        "末位 --fullscreen=yes 覆盖 start 内部 "
                                        "no，并逐 case 读回 osd 2560x1440"},
                "isolation": {
                    "temp_config_home_appdata": True,
                    "credential_free_child_env": True,
                    "own_pids_only": True,
                    "live_configuration_written": False,
                },
                "contract": ("docs/验证/开发/p3-001/verifier-build/"
                             "evidence-tools-contract.json"),
                "semantics_authority": (
                    "docs/P3/P3执行约束与验收brief.md + docs/P3实施计划.json "
                    "required_test_notes + docs/P3/P3核心限域修正brief-v2.json "
                    "+ docs/P3/P3验证器限域收敛brief-v3.json"
                    " (V3-E1 修正：全部为实际存在的权威路径，不再指向不存在的"
                    "扁平化 docs 路径)"),
                "source_pins": {"path": relp(pins_path),
                                "sha256": lib.sha256_file(pins_path)},
                "notes": [
                    "20 个 P2 冻结 ID 经只读导入 p2_verify/p1_verify 真实复跑；"
                    "121+ 旧单测行为不删不跳（UNIT-P2-01 全套实跑）。",
                    "P3 新增 ID 按 checker 契约产出结构化 same_moment/freshness/"
                    "desc_evidence/native_unscaled 记录；样本行逐字出自会话日志。",
                    "PNG 用 p3_lib stdlib 解码器取真实位深尺寸；同 SHA 重复组"
                    "诚实标注 non-corroborative。",
                    "真实 FAIL 如实保留（不删不洗白）；像素/几何 oracle 独立于"
                    "checker，产品 bug 走 REWORK 而非放宽。",
                ],
                "cases": cases_out,
                "png_captures": png_captures,
                "non_corroborative_png": non_corroborative,
            }
            obj_path = evidence.write_json("objective-results.json", summary)
            console.log(f"objective results: {len(cases_out)} cases, "
                        f"failures: {failures or 'none'} -> {relp(obj_path)}")
            # full-tree manifest (closed exclusion class unbound); the runner
            # console must be FINAL before manifest-verify.json pins its hash
            all_files = [p for p in sorted(ev_abs.rglob("*"))
                         if p.is_file()
                         and p.name not in gate.EXCLUDED_FROM_MANIFEST]
            manifest = lib.build_evidence_manifest(SESSION,
                                                   [relp(p) for p in all_files])
            man_path = evidence.write_json("evidence-manifest.json", manifest)
            manifest_sha = lib.sha256_file(man_path)
            console.log(f"evidence-manifest: {relp(man_path)} "
                        f"sha256={manifest_sha}")
            console.close()   # runner.console.txt bytes are now FINAL
            evidence.write_json("manifest-verify.json", {
                "schema": gate.MANIFEST_VERIFY_SCHEMA,
                "session": SESSION,
                "evidence_manifest_sha256": manifest_sha,
                "runner_console_sha256": lib.sha256_file(ev_abs /
                                                         "runner.console.txt"),
            })
            # post-chain notes go to stdout only (the console is already pinned)
            print(f"[{SESSION}] manifest-verify.json written (pins manifest + "
                  "runner console; closed exclusion class)", flush=True)
            print(f"[{SESSION}] next: python -X utf8 tools/p3_check_evidence.py "
                  f"--evidence-dir {ev_rel} --session {SESSION} "
                  "[--require-tests] [--write-gate]", flush=True)
            missing = [f for c in cases_out for f in c.get("files", [])
                       if not (lib.REPO_ROOT / f).exists()]
            if missing:
                print(f"[{SESSION}] MISSING EVIDENCE FILES: {missing}", flush=True)
                exit_code = 2
            elif failures:
                exit_code = 1
        elif args.probe:
            exit_code = 0 if probe_ok else 1
    finally:
        try:
            console.close()
        except Exception:  # noqa: BLE001
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
