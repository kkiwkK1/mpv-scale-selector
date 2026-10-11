# -*- coding: utf-8 -*-
"""P4 isolated collector (session p4-001, batch B2, unit W2 collector).

Scope (docs/P4/P4-B2采集器实现与首载brief.md; approved plan sha
5285d11293373a20523ac199de2868ac2911e550ffd48b47be164311888c822a; B1-r2 fixed
candidate sha 929079b09d1c1ac10f262ebc05e7d311ca5943d58eeb5731890199d803d17f3b):

  * CLI with read-only preflight default; explicit --mode prepare-runtime /
    identity-probe / pilot / capture / prepare-media execute; production is
    refused ALWAYS at this revision (even with a pass-json argument);
  * every entry runs the real preflight chain BEFORE any process spawn:
    P4 work-permit machine check (p4_verify.check_work_permit), B1-r2
    candidate pin re-hash, canonical path checks, disk budget (free >= 2x
    preregistered budget), create-only trial dir (reuse refused before any
    spawn);
  * subprocess environment allowlist: HOME/USERPROFILE/APPDATA/
    LOCALAPPDATA/TEMP/TMP/cache/watch-later all inside the sandbox,
    PYTHONDONTWRITEBYTECODE=1, PYTHONNOUSERSITE=1, VSSCRIPT_PATH -> cloned
    vsscript.dll, PATH rebuilt from clone + System32 + explicit query-tool
    dirs only, API-credential env keys can never pass through;
  * runtime clone to a NEW TEMP tree (whole vs tree + rife DLL + the single
    selected model dir), symlink/reparse components rejected at every level,
    every cloned file hash-verified against its source, survey DLL/model pins
    enforced; no pip / no downloads / no original-tree writes; protected
    trees (D:/MPV/vs, D:/MPV/rife, active %APPDATA%/mpv) get a hash+size
    inventory before and after — any diff is a hard zero-write violation
    (BLOCKED_ENV). Only path+hash is stored, never private content;
  * the private rife.vpy is copied to TEMP with EXACTLY ONE rewritten line
    (the LoadPlugin path -> the cloned DLL); the remaining bytes must be
    byte-identical; the original sha, the replaced line range and an
    algorithm hash (path-line masked) are recorded — the private full text
    never enters the repo;
  * atomic sampling: a TEMP Lua helper collects video-out-params +
    osd-dimensions (+ real get_osd_margins) + the native vo-passes node +
    real counter families + time-pos + a render-reconfig epoch counter in
    ONE mpv event callback and replies with ONE structured script-message;
    the collector maps the native node to the B1-r2 LF10 contract
    {desc,last_ns,avg_ns,peak_ns,count,samples_ns[,raw_node]} verbatim
    (duplicates kept, no value dedup, count:null only when the API omits
    it); collector-receive time.monotonic() and the callback media time are
    recorded as what they are (never present time);
  * timed window: 10..15 s warmup stabilisation (preregistered criteria,
    consecutive-poll rule), then 10 slots at warmup_end + k*1.0 s recorded
    with the ACTUAL wall monotonic (late polls recorded as-is, never
    re-timed, never interpolated);
  * identity sample: preregistered rife-identity-short-v1, 1920x1080 SDR
    BT709-limited yuv420p, 12 source frames, 24 fps and 30 fps variants,
    bright disk r=120 at (600,500) moving (8,3) px/frame, diagonal stripes
    180/235 period 12 px, a fixed fine-texture square, U/V=128, source
    ordinal in a top 8-px binary strip luma 64/192; pure stdlib bytearray
    generator + full Y4M payload verification (reproducible, length-checked);
  * process ownership: only PIDs/process objects this tool started are
    stopped; finally-closed IPC/console/log handles; the trial manifest is
    written only after every own handle is closed;
  * N1 wiring: once a real media manifest exists, timed runs MUST pass
    lib.verify_required_inputs AND p4_check_evidence.gate_run_evidence (not
    just the looser stage gate);
  * B2-r3 scoped repairs (docs/P4/P4-B2首载修正brief-v3.md, R3-1..R3-5):
    R3-1 the auto sandbox root is only an unpredictable NON-EXISTING name —
    the single create-only entry (create_sandbox) performs the atomic
    creation (no mkdtemp pre-creation that create_sandbox then refuses);
    R3-2 mpv no longer receives --no-config (which neutralised the whole
    sandbox config): the isolated --config-dir config is REALLY loaded
    (auto script scan disabled; every Lua script explicit via --script),
    with one authorised non-GPU/non-VS real mpv config-load smoke
    (--mode config-smoke, vo=null/ao=null sentinel, 10 s own-PID timeout);
    R3-3 the verdict binds to the UNIQUE REAL log path (exists + non-empty
    + hashed after close), the effective vf chain from that log (an argv
    string or a passthrough chain is never EVIDENCED), magic-checked output
    frames (PNG/JPEG mismatch stated, never a silent *.png glob);
    R3-4 final witness/log/hash/manifest only after process end AND closed
    handles (timeout included), gpu_started only from real GPU evidence
    (never hardcoded false, never true from a config line; unknown is
    NOT_ESTABLISHED), connect deadlines on time.monotonic;
    R3-5 the frame-uniqueness control is honestly named all_frames_unique
    and the 50% blend difference is COMPUTED and preserved as a
    distribution — the plan preregisters no blend threshold, so the blend
    judgement stays NOT_ESTABLISHED.

WRITER HONESTY: this unit is pure code + mock tests only. The writer did
NOT start mpv/GPU/VS/nvidia-smi and did NOT clone the real runtime. The
identity probe reports model identity as NOT_ESTABLISHED whenever the first
load log cannot prove it; no threshold is invented where the plan has none;
a pilot without algorithm-effect proof is NOT_ESTABLISHED, never PASS.
prepare-media full-length generation is implemented as an entry but is NOT
RUN in this task (brief: W2 tests use tiny TEMP frames only).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import queue
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import p4_lib as lib  # noqa: E402  (frozen B1 contract; read-only reuse)

# ---------------------------------------------------------------------------
# Session identity + fixed candidates
# ---------------------------------------------------------------------------

STAGE = lib.STAGE
SESSION = lib.SESSION
PLAN_SHA256 = lib.PLAN_SHA256
COLLECT_REL = "tools/p4_collect.py"
B1_CANDIDATE_REL = "docs/验证/开发/p4-001/build-b1-r2/candidate.json"
B1_CANDIDATE_SHA256 = (
    "929079b09d1c1ac10f262ebc05e7d311ca5943d58eeb5731890199d803d17f3b")
EVIDENCE_TREE_REL = "docs/验证/开发/p4-001"
SANDBOX_PARENT_DEFAULT = Path(tempfile.gettempdir()) / "p4-001"

# Execution modes. production is intentionally absent and separately refused.
# config-smoke is the ONE authorised real-mpv entry of B2-r3 and is
# deliberately non-GPU/non-VS (vo=null/ao=null sentinel config-load proof).
MODES = ("preflight", "prepare-runtime", "identity-probe", "pilot", "capture",
         "prepare-media", "config-smoke")
READ_ONLY_MODES = ("preflight",)
SPAWN_MODES = ("identity-probe", "pilot", "capture", "config-smoke")

# Exit-code contract (F4): rc 0 is only ever an accepted/proven result;
# rc 1 = the mode completed but the evidence is NOT_ESTABLISHED (unproven
# identity, timeout, gate false); rc 2 = refused/blocked (production lock,
# protected-tree violation, precondition refusal). A script caller can
# never mistake an unproven run for a pass via rc 0.
RC_OK = 0
RC_NOT_ESTABLISHED = 1
RC_REFUSED = 2

# F5 honesty: at this revision the pilot deliberately does NOT screenshot
# (steady-state forbids disturbance), so the four-piece PNG identity stays
# unwired and is never claimed from a timing run. capture-mode timing runs
# must not pose as image evidence either (B3 wires real capture).
PILOT_PNG_DISCLOSURE = ("NOT_ESTABLISHED (pilot does not screenshot; the "
                        "four-piece PNG identity gate is wired in B3)")

# R3-2 config smoke: 10 s wall cap per attempt, own PID only, no media,
# vo=null/ao=null (no graphics device, no VS/RIFE/DLL), credential-free env.
CONFIG_SMOKE_WALL_S = 10.0
CONFIG_SMOKE_SENTINEL_NAME = "p4_smoke_sentinel.lua"
CONFIG_SMOKE_REPORT_NAME = "report.json"
# Two unusual (never-set-by-any-real-config) values the sentinel must read
# back from the LOADED temp mpv.conf — proof the config path really works.
CONFIG_SMOKE_VALUES = {"a": "1701", "b": "74656"}
CONFIG_SMOKE_SENTINEL_LUA = """-- p4-001 config-load sentinel (temp helper;
-- non-GPU: reads two script-opt values and quits; no media, no vs/rife)
-- The report path is derived from THIS script's own location (passed via
-- the explicit --script argv), so the report is written even when the
-- config did not load (values then read nil) — the negative control.
local a = mp.get_opt("p4smoke_a")
local b = mp.get_opt("p4smoke_b")
local src = debug.getinfo(1).source or ""
if src:sub(1, 1) == "@" then src = src:sub(2) end
local dir = src:match("^(.*)[/\\\\][^/\\\\]+$") or "."
local out = dir .. "/../../sentinel-report.txt"
local f = io.open(out, "wb")
if f then
  f:write(string.format("p4smoke_a=%s\\np4smoke_b=%s\\n",
                        tostring(a), tostring(b)))
  f:close()
end
mp.add_timeout(0.1, function() mp.commandv("quit", "0") end)
"""

# R3-3: the ONLY trustworthy source of "the filter really ran" is the
# effective chain block of the real mpv log — never the argv echo.
_IDENTITY_CHAIN_HEAD = re.compile(r"\[vf\]\s+User filter list:", re.I)
_IDENTITY_VF_LINE = re.compile(r"\[vf\]", re.I)
_IDENTITY_CHAIN_EMPTY = re.compile(r"\(empty\)")
_IDENTITY_CHAIN_ENGAGED = re.compile(r"vapoursynth|@rife", re.I)
# GPU init evidence (a build-info feature list or a config echo must NOT
# count: those lines name vulkan without any device/context/init nearby —
# e.g. "libavdevice" must not trip via a distant "cuda" on the same line,
# so the init word must sit within ~40 chars of the API word).
_GPU_INIT_MARKER = re.compile(
    r"(vulkan|d3d11|d3d9|cuda|nvdec|dxva|vaapi)[^\n]{0,40}?"
    r"(device|adapter|context|instance|initialis|initializ)"
    r"|using hardware decoding|\[vo/gpu", re.I)

# ---------------------------------------------------------------------------
# Survey runtime pins (docs/P4/P4环境勘察.json — fixed values, not env
# overrides; tests inject their own temp trees via function arguments)
# ---------------------------------------------------------------------------

MPV_EXE_DEFAULT = Path("D:/MPV/mpv.exe")
MPV_EXE_SHA256 = ("306f49323f846eca7a9a708bc35c505d5e6a4e246c5588c2fc7c1c68f9"
                  "f53d6a")
VS_TREE_DEFAULT = Path("D:/MPV/vs")
VS_PYTHON_EXE_REL = "python.exe"
VSSCRIPT_REL = "Lib/site-packages/vapoursynth/vsscript.dll"
RIFE_DIR_DEFAULT = Path("D:/MPV/rife")
RIFE_DLL_REL = "librife_windows_x86-64.dll"
RIFE_MODEL_DIR_REL = "models/rife-v4.25-lite_ensembleFalse"
ACTIVE_VPY_RELS = ("%APPDATA%/mpv/rife/rife.vpy", "D:/MPV/rife/rife.vpy")

SURVEY_RUNTIME_PINS = {
    VSSCRIPT_REL: ("bf61b999abcc8c537882d32017efb14a4636fea17f0abab873e748629"
                   "f26d3c0", 72192),
    "Lib/site-packages/vapoursynth/libvapoursynth.dll":
        ("cf2c35b3e9e9eb8af6969562f8fad21cc5d17a3d12c40c3561687bf25c565e23",
         4109824),
    "Lib/site-packages/vapoursynth/vapoursynth.pyd":
        ("081f3b8319d9393ba72381a9ae54fb54af1fee65d3bf788e1a3c0215a8c7a19f",
         731648),
    "python313.dll": ("e820bf024efd2b56bb2b82791e6b6ddc7303f070f8e72cba763748"
                      "2a8a906238", 6135008),
}
SURVEY_RIFE_PINS = {
    RIFE_DLL_REL: ("36a25b471be88e6f915320c818022dc8657dd9beac22a8c3158bd7f42"
                   "60cc410", 5244416),
    RIFE_MODEL_DIR_REL + "/flownet.bin":
        ("350a15e464bea5ad378e06c0fb43996e90a0d35653d5a6ef6bc980d832538fb7",
         11276252),
    RIFE_MODEL_DIR_REL + "/flownet.param":
        ("f750ec6723f05a800c8fb07ac0bf3537e741b6ff7fe61b3894e407bd10373a63",
         35830),
}
ACTIVE_VPY_SHA256 = ("8beb574c00e7e5acc5a61d3d921d2bd6aeeaccfdc9957ea6ae1761d"
                     "a64d314c7")

# Preregistered budget (plan resource_budget): clone ~239,745,667 B + sandbox
# <=100 MB + evidence tree <=900 MB + media <=700 MB; free must be >= 2x.
CLONE_BUDGET_BYTES = 239745667
SANDBOX_BUDGET_BYTES = 100 * 1024 * 1024
EVIDENCE_BUDGET_BYTES = 900 * 1024 * 1024
MEDIA_BUDGET_BYTES = 700 * 1024 * 1024
TOTAL_BUDGET_BYTES = (CLONE_BUDGET_BYTES + SANDBOX_BUDGET_BYTES
                      + EVIDENCE_BUDGET_BYTES + MEDIA_BUDGET_BYTES)
DISK_FREE_FACTOR = 2

# Wall-clock discipline (brief: pilot <=40 s, identity probe <=160 s,
# calibration 4x40; B2 total GPU <=10 min). These are caps, never extended
# "until it looks successful".
PILOT_WALL_S = 40.0
IDENTITY_PROBE_WALL_S = 160.0
TIMED_RUN_WALL_S = 40.0
SUBPROCESS_TIMEOUT_S = 20.0

# Preregistered pollution gates (plan sampling.pollution_thresholds).
POLLUTION_MEMORY_USED_MIB_MAX = 1500.0
POLLUTION_UTIL_PCT_MAX = 10.0
POLLUTION_CONSECUTIVE_S = 5.0

# Arm id (p4_lib GROUPS registry) -> real product gear id in
# scripts/scale-selector.lua (builtin gears; the menu protocol is the real
# product switching path: F8 menu + user-data verification, no invented
# message names).
ARM_GEAR_IDS = {
    "baselineHQ": "off",
    "nearest": "nearest",
    "FSR1": "fsr1",
    "SGSR1": "sgsr1",
    "NIS": "nis",
    "SharpBilinear-AUTO": "sharpbilinear",
    "SharpBilinear-2x": "sharpbilinear2x",
    "Anime4K-ModeA": "anime4k",
    "Integer": "integer",
    "xBR-lv2": "xbr",
}

# Shared (non-algorithm) base config — identical bytes for every arm/stratum.
# The optional RIFE engagement line is the stratum variable (spec.rife), the
# Anime4K chain mode stays the stock default a (Mode A), chosen by the plugin
# itself, never stacked under off.
HQ_COMMON_TEMPLATE = (
    "profile=high-quality\n"
    "vo=gpu-next\n"
    "gpu-api=vulkan\n"
)
RIFE_ENGAGEMENT_LINE = (
    "vf-add=@rife:vapoursynth=file=~~/rife/rife.vpy"
    ":buffered-frames=4:concurrent-frames=4\n")

SAMPLER_SCRIPT_NAME = "p4_collect_sampler.lua"
SAMPLER_MSG_REQUEST = "p4-collect-sample"
SAMPLER_MSG_REPLY = "p4-collect-reply"

_BS = chr(92)
PIPE_NAMESPACE = _BS + _BS + "." + _BS + "pipe" + _BS  # \\.\pipe\

# Credential-shaped key fragments that must never survive env construction
# (defence in depth on top of the strict allowlist).
_CREDENTIAL_FRAGMENTS = ("api_key", "apikey", "token", "secret", "passwd",
                         "password", "credential", "openai", "anthropic",
                         "gemini", "zai_", "glm_", "deepseek", "hf_", "ghp_",
                         "aws_", "azure")

# Subprocess env allowlist (os keys copied verbatim when present).
SAFE_SUBPROCESS_KEYS = (
    "SystemRoot", "SystemDrive", "windir", "COMSPEC", "PATHEXT",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_LEVEL", "PROCESSOR_REVISION",
    "NUMBER_OF_PROCESSORS",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CollectError(Exception):
    """Base class of every collector failure (all failures are structured,
    never silently swallowed)."""


class PreflightBlocked(CollectError):
    """A preflight gate refused the mode (permit / pins / paths / disk)."""


class SpawnRefused(CollectError):
    """Create-only trial targets exist or a spawn precondition failed —
    refused BEFORE any process was started."""


class ProductionRefused(CollectError):
    """Production execution is locked at this revision (B4 not passed)."""


class RuntimeIdentityBlocked(CollectError):
    """Runtime clone/pin/identity precondition failed (BLOCKED_ENV family;
    evidence-preserving, never retried with luck)."""


class ZeroWriteViolation(RuntimeIdentityBlocked):
    """A protected tree changed during an isolated run (hard BLOCKED_ENV)."""


class CredentialLeakError(CollectError):
    """A credential-shaped key tried to enter a subprocess environment."""


class SamplingPayloadError(CollectError):
    """The atomic sampler reply lacked a required field (recorded honestly,
    never fabricated)."""


class WindowScheduleError(CollectError):
    """Warmup could not stabilise inside the preregistered budget or the
    wall-clock cap expired (raw data preserved, run invalid)."""


class HandleStateError(CollectError):
    """A manifest was requested while own handles were still open."""


# ---------------------------------------------------------------------------
# Small strict helpers
# ---------------------------------------------------------------------------


def _now_monotonic():
    return time.monotonic()


def _is_reparse(path: Path) -> bool:
    st = os.lstat(str(path))
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT) or os.path.islink(
        str(path))


def sha256_fs_file(path, chunk_bytes=1 << 20):
    """Streaming SHA-256 of an arbitrary filesystem file (TEMP/clone side;
    repo-side bindings must use lib.file_binding)."""
    return lib.sha256_file(Path(path), chunk_bytes)


# ---------------------------------------------------------------------------
# Preflight gates
# ---------------------------------------------------------------------------


def check_work_permit_or_raise(root=None):
    """Real machine work-permit gate (p4_verify.check_work_permit, read-only
    reuse of the frozen verifier — the violations list must be empty)."""
    import p4_verify as pv  # lazy: keeps CLI help import-light
    violations = pv.check_work_permit(root)
    if violations:
        raise PreflightBlocked(
            {"gate": "work_permit", "violations": violations})
    return {"gate": "work_permit", "ok": True}


def check_b1_candidate_pins(root=None):
    """B1-r2 candidate is the fixed dependency: the candidate file itself
    must hash to the reviewed sha AND every file it pins must still match.
    Any drift fails closed (the collector may not adapt silently)."""
    rootp = Path(root) if root is not None else lib.workspace_root()
    candidate_fs = rootp / B1_CANDIDATE_REL
    if not candidate_fs.is_file():
        raise PreflightBlocked(
            {"gate": "b1_candidate", "reason": "candidate file missing",
             "path": B1_CANDIDATE_REL})
    got = sha256_fs_file(candidate_fs)
    if got != B1_CANDIDATE_SHA256:
        raise PreflightBlocked(
            {"gate": "b1_candidate", "reason": "candidate sha drift",
             "expected": B1_CANDIDATE_SHA256, "got": got})
    candidate = lib.strict_json_loads(
        candidate_fs.read_bytes().decode("utf-8"), source=B1_CANDIDATE_REL)
    drifted = []
    for rel, want in sorted(candidate.get("files", {}).items()):
        fs = rootp / rel
        if not fs.is_file():
            drifted.append({"path": rel, "reason": "missing"})
            continue
        got = sha256_fs_file(fs)
        if got != want:
            drifted.append({"path": rel, "reason": "sha drift",
                            "expected": want, "got": got})
    if drifted:
        raise PreflightBlocked(
            {"gate": "b1_candidate", "reason": "pinned dependency drift",
             "drifted": drifted[:20], "n_drifted": len(drifted)})
    return {"gate": "b1_candidate", "ok": True,
            "sha256": B1_CANDIDATE_SHA256,
            "pinned_files": len(candidate.get("files", {}))}


def check_disk_budget(target_dir, required_bytes=TOTAL_BUDGET_BYTES,
                      factor=DISK_FREE_FACTOR):
    """Preregistered disk budget: free >= factor * required. Read-only: the
    measurement runs against the nearest existing ancestor of the target
    (a not-yet-created sandbox parent is not an error). Shortage refuses
    before any clone/spawn."""
    target = Path(target_dir)
    probe = target
    while not probe.is_dir():
        if probe.parent == probe:
            raise PreflightBlocked(
                {"gate": "disk_budget", "reason": "no existing ancestor",
                 "path": str(target)})
        probe = probe.parent
    usage = shutil.disk_usage(str(probe))
    required_free = float(required_bytes) * factor
    free = float(usage.free)
    if free < required_free:
        raise PreflightBlocked(
            {"gate": "disk_budget",
             "reason": "insufficient free space (preregistered 2x budget)",
             "free_bytes": free, "required_free_bytes": required_free,
             "total_bytes": float(usage.total)})
    return {"gate": "disk_budget", "ok": True, "free_bytes": free,
            "required_free_bytes": required_free,
            "measured_at": str(probe), "target": str(target)}


def ensure_fresh_trial_dir(path):
    """Create-only trial directory at the filesystem level. An existing
    target is refused BEFORE any process spawn (never truncated, never
    reused); the parent must already exist."""
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise SpawnRefused(
            {"reason": "trial dir already exists (create-only, refuse "
                       "reuse before any spawn)",
             "path": str(target)})
    if not target.parent.is_dir():
        raise SpawnRefused(
            {"reason": "trial dir parent missing", "path": str(target.parent)})
    target.mkdir()
    return target.resolve()


def _resolve_active_appdata():
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        raise PreflightBlocked(
            {"gate": "runtime_paths",
             "reason": "APPDATA not set; cannot locate active mpv config "
                       "(private vpy source)"})
    return Path(appdata)


def resolve_active_vpy():
    """Locate the active private rife.vpy (read-only source for the TEMP
    relocation). Never returns its content; raises when unavailable."""
    candidates = []
    try:
        candidates.append(_resolve_active_appdata() / "mpv" / "rife"
                          / "rife.vpy")
    except PreflightBlocked:
        pass
    candidates.append(Path("D:/MPV/rife/rife.vpy"))
    for fs in candidates:
        if fs.is_file():
            return fs
    raise PreflightBlocked(
        {"gate": "runtime_paths", "reason": "active rife.vpy not found",
         "tried": [str(c) for c in candidates]})


def preflight_collect(mode, evidence_dir=None, sandbox_parent=None, root=None):
    """Full read-only preflight chain for one mode. Runs BEFORE any spawn;
    returns a structured report; raises PreflightBlocked/SpawnRefused."""
    if mode not in MODES:
        raise ProductionRefused(
            {"reason": "unknown/refused mode", "mode": mode,
             "allowed_modes": list(MODES)})
    report = {
        "stage": STAGE, "session": SESSION, "mode": mode,
        "production_locked": True,
        "writer_note": "preflight never starts mpv/GPU/VS and never clones",
    }
    report["work_permit"] = check_work_permit_or_raise(root)
    report["b1_candidate"] = check_b1_candidate_pins(root)
    sandbox_parent = (Path(sandbox_parent) if sandbox_parent is not None
                      else SANDBOX_PARENT_DEFAULT)
    report["disk_budget"] = check_disk_budget(sandbox_parent)
    report["disk_budget"]["target"] = str(sandbox_parent)
    if evidence_dir is not None:
        ensure_fresh_trial_dir(evidence_dir)  # create-only, before any spawn
        report["evidence_dir"] = str(Path(evidence_dir).resolve())
    if mode in SPAWN_MODES:
        # presence-only checks for the big pinned binaries; full hash pinning
        # happens inside the clone/zero-write witness of the executing mode
        mpv = MPV_EXE_DEFAULT
        if not mpv.is_file():
            raise PreflightBlocked(
                {"gate": "runtime_paths", "reason": "mpv.exe missing",
                 "path": str(mpv)})
        report["mpv_exe"] = {"path": str(mpv), "present": True,
                             "sha256_checked_at": "clone/witness stage"}
    report["ok"] = True
    return report


# ---------------------------------------------------------------------------
# Sandbox subprocess environment (allowlist; credential-free)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# F2: sandbox/staging location hard gate — TEMP-only trusted parent, never
# inside/overlapping a protected tree, checked BEFORE any mkdir/copy/spawn
# ---------------------------------------------------------------------------


def _path_contains(container, item):
    """Component-wise path containment (never a raw string prefix): True
    iff item == container or item lies under container."""
    try:
        item.relative_to(container)
        return True
    except ValueError:
        return False


def _resolved(path):
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path).absolute()


def _refuse_reparse_prefix(path, reason):
    """Refuse symlink/reparse components in the EXISTING prefix of the raw
    path (a junction planted under TEMP must not smuggle writes elsewhere)."""
    cur = Path(path).anchor
    for part in Path(path).parts[1:]:
        cur = Path(cur) / part
        try:
            reparse = _is_reparse(cur)
        except OSError:
            continue            # component vanished / not created yet
        if reparse:
            raise SpawnRefused({"reason": reason, "path": str(cur)})


def protected_tree_roots(appdata=None, workspace=None):
    """Trees no sandbox/staging target may ever live in or shadow: the
    survey runtime parent (D:/MPV incl. vs/rife/mpv.exe), the active mpv
    config tree, and the repo/project tree. Existence is NOT required — the
    gate is about LOCATION, so a not-yet-created new root under them is
    still refused."""
    roots = [Path("D:/MPV")]
    src = appdata
    if src is None:
        try:
            src = _resolve_active_appdata()
        except PreflightBlocked:
            src = None
    if src is not None:
        roots.append(Path(src) / "mpv")
    roots.append(Path(workspace) if workspace is not None
                 else lib.workspace_root())
    return roots


def assert_write_area_safe(path, workspace=None):
    """Shared location refusal for any TEMP write area: no '..' aliases, no
    symlink/reparse prefix, not inside/overlapping a protected tree. A
    non-existing target is NOT treated as safe (location is checked
    regardless). Runs BEFORE any mkdir/copy/spawn."""
    raw = Path(path)
    if ".." in raw.parts:
        raise SpawnRefused(
            {"reason": "write target must not contain '..' aliases",
             "path": str(raw)})
    prot = [_resolved(p) for p in protected_tree_roots(workspace=workspace)]
    resolved = _resolved(raw)
    for prot_r in prot:
        if resolved == prot_r or _path_contains(prot_r, resolved) \
                or _path_contains(resolved, prot_r):
            raise SpawnRefused(
                {"reason": "write target is inside/overlaps a protected "
                           "tree (hard refusal before any mkdir/copy/spawn)",
                 "target": str(resolved), "protected_tree": str(prot_r)})
    _refuse_reparse_prefix(raw, "write target path contains a symlink/"
                                "reparse component")
    return {"target": str(resolved), "protected_checked": len(prot)}


def assert_sandbox_temp_safe(sandbox_root, temp_base=None, workspace=None):
    """F2 hard gate for SANDBOX roots: after normalisation the root must be
    a NEW unique child of the trusted <TEMP>/p4-001 parent. A caller-poisoned
    env TEMP cannot smuggle the trusted parent itself into a protected tree
    (the parent resolves inside a protected tree -> refused), '..' aliases
    and reparse/symlink components are refused, and a non-existing root is
    NOT treated as safe — the location is checked before anything exists."""
    raw = Path(sandbox_root)
    if ".." in raw.parts:
        raise SpawnRefused(
            {"reason": "sandbox root must not contain '..' aliases",
             "path": str(raw)})
    base = (Path(temp_base) if temp_base is not None
            else Path(tempfile.gettempdir()) / "p4-001")
    base_r = _resolved(base)
    prot = [_resolved(p) for p in protected_tree_roots(workspace=workspace)]
    for prot_r in prot:
        if base_r == prot_r or _path_contains(prot_r, base_r):
            raise SpawnRefused(
                {"reason": "trusted TEMP parent resolves inside a protected "
                           "tree (a poisoned env TEMP cannot be trusted)",
                 "temp_parent": str(base_r), "protected_tree": str(prot_r)})
    resolved = _resolved(raw)
    # protected-tree overlap is reported BEFORE the parent rule so the
    # refusal names the actual crime (a protected location, not just a
    # non-TEMP one)
    for prot_r in prot:
        if resolved == prot_r or _path_contains(prot_r, resolved) \
                or _path_contains(resolved, prot_r):
            raise SpawnRefused(
                {"reason": "sandbox root is inside/overlaps a protected "
                           "tree (hard refusal before any mkdir/copy/spawn)",
                 "root": str(resolved), "protected_tree": str(prot_r)})
    if resolved == base_r or not _path_contains(base_r, resolved):
        raise SpawnRefused(
            {"reason": "sandbox root must be a NEW unique child of the "
                       "trusted <TEMP>/p4-001 parent",
             "root": str(resolved), "trusted_parent": str(base_r)})
    _refuse_reparse_prefix(raw, "sandbox root path contains a symlink/"
                                "reparse component")
    return {"root": str(resolved), "trusted_parent": str(base_r)}


def new_sandbox_root(prefix="p4-001-sbx-", temp_base=None):
    """R3-1: an unpredictable, unique NON-EXISTING sandbox/staging name
    inside the trusted <TEMP>/p4-001 parent. This function NEVER creates
    anything (the old tempfile.mkdtemp pre-created the final root which
    create_sandbox then refused — every bare spawn-mode CLI invocation
    died deterministically before any spawn). The single create-only entry
    (create_sandbox / ensure_fresh_trial_dir-style mkdir) performs the
    atomic creation; a name that lost a race is refused there, honestly.
    The parent itself is create-only and location-validated first — a
    poisoned env TEMP pointing at a protected tree is refused."""
    base = Path(temp_base) if temp_base is not None \
        else SANDBOX_PARENT_DEFAULT
    assert_sandbox_temp_safe(base / "location-probe")
    base.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = base / ("%s%s-%x" % (prefix, secrets.token_hex(8),
                                          time.time_ns()))
        if not (candidate.exists() or candidate.is_symlink()):
            return candidate   # creation is create_sandbox's exclusive duty


def sandbox_layout(sandbox_root):
    """Directory contract of one isolated sandbox (created create-only by the
    caller). Returns the resolved path map."""
    root = Path(sandbox_root)
    return {
        "root": root,
        "clone_vs": root / "clone" / "vs",
        "clone_rife": root / "clone" / "rife",
        "home": root / "sandbox" / "home",
        "appdata": root / "sandbox" / "home" / "AppData" / "Roaming",
        "localappdata": root / "sandbox" / "home" / "AppData" / "Local",
        "temp": root / "sandbox" / "tmp",
        "cache": root / "sandbox" / "cache",
        "watch_later": root / "sandbox" / "watch-later",
        "shots": root / "sandbox" / "shots",
        "pycache": root / "sandbox" / "pycache",
        "cfg": root / "cfg",
        "media": root / "media",
        "vpy": root / "vpy",
        "runs": root / "runs",
    }


def create_sandbox(sandbox_root, temp_base=None):
    """Create the sandbox directory tree create-only (an existing sandbox is
    refused — every trial gets a NEW tree). F2: the LOCATION is hard-refused
    first (TEMP-only trusted parent; never inside/overlapping a protected
    tree; no '..'/reparse aliases) — before ANY mkdir.

    The clone/ subdirs are intentionally NOT pre-created: clone_tree/
    clone_runtime create their destinations themselves and refuse existing
    targets, so a pre-created clone/vs would deterministically fail every
    clone (a latent B2 failure, fixed with F1)."""
    assert_sandbox_temp_safe(sandbox_root, temp_base=temp_base)
    root = Path(sandbox_root)
    if root.exists() or root.is_symlink():
        raise SpawnRefused(
            {"reason": "sandbox root already exists (must be a NEW tree)",
             "path": str(root)})
    layout = sandbox_layout(root)
    for key in ("root", "home", "appdata",
                "localappdata", "temp", "cache", "watch_later", "shots",
                "pycache", "cfg", "media", "vpy", "runs"):
        layout[key].mkdir(parents=True, exist_ok=False)
    return layout


def build_subprocess_env(layout, vs_root=None, extra_path_dirs=()):
    """Allowlisted subprocess environment for every child process.

    Only SAFE_SUBPROCESS_KEYS pass through; HOME/USERPROFILE/APPDATA/
    LOCALAPPDATA/TEMP/TMP are all redirected into the sandbox; PATH is
    REBUILT (never inherited): clone VS + clone vapoursynth + System32 +
    explicit extra query-tool dirs; PYTHONDONTWRITEBYTECODE=1,
    PYTHONNOUSERSITE=1, PYTHONPYCACHEPREFIX -> sandbox; VSSCRIPT_PATH ->
    the cloned vsscript.dll. API env can never pass through — and any
    credential-shaped key is additionally refused outright.
    """
    env = {}
    for key in SAFE_SUBPROCESS_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    # The allowlist IS the credential defence: only SAFE_SUBPROCESS_KEYS are
    # copied, so parent API keys can never pass through. The credential
    # tripwire runs on the BUILT environment (assert_env_has_no_credentials),
    # not on the parent process — an unrelated key in the parent env must
    # not make the collector unusable, it just never enters any child.
    clone_vs = Path(vs_root) if vs_root is not None else layout["clone_vs"]
    system_root = env.get("SystemRoot") or os.environ.get("SystemRoot")
    system32 = (Path(system_root) / "System32" if system_root
                else Path("C:/Windows/System32"))
    path_dirs = [str(clone_vs),
                 str(clone_vs / "Lib" / "site-packages" / "vapoursynth")]
    for d in extra_path_dirs:
        path_dirs.append(str(Path(d)))
    path_dirs.append(str(system32))
    env["PATH"] = os.pathsep.join(path_dirs)
    env["HOME"] = str(layout["home"])
    env["USERPROFILE"] = str(layout["home"])
    env["APPDATA"] = str(layout["appdata"])
    env["LOCALAPPDATA"] = str(layout["localappdata"])
    env["TEMP"] = str(layout["temp"])
    env["TMP"] = str(layout["temp"])
    env["PYTHONPYCACHEPREFIX"] = str(layout["pycache"])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["VSSCRIPT_PATH"] = str(Path(clone_vs) / VSSCRIPT_REL)
    env["MPV_HOME"] = str(layout["cfg"])
    return env


def assert_env_has_no_credentials(env):
    """Second-line audit of a built environment: no credential-shaped key,
    no user profile outside the sandbox, write-protection flags present."""
    problems = []
    for key in env:
        k = key.lower()
        for frag in _CREDENTIAL_FRAGMENTS:
            if frag in k:
                problems.append({"reason": "credential-shaped key", "key": key})
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP",
                "TMP"):
        value = env.get(key, "")
        if "appdata" in key.lower() or key in ("HOME", "USERPROFILE"):
            if "sandbox" not in value.lower():
                problems.append({"reason": "profile dir outside sandbox",
                                 "key": key, "shape": value})
    if env.get("PYTHONDONTWRITEBYTECODE") != "1":
        problems.append({"reason": "PYTHONDONTWRITEBYTECODE != 1"})
    if env.get("PYTHONNOUSERSITE") != "1":
        problems.append({"reason": "PYTHONNOUSERSITE != 1"})
    if problems:
        raise CredentialLeakError({"problems": problems[:20],
                                   "n_problems": len(problems)})
    return {"ok": True, "keys": len(env)}


# ---------------------------------------------------------------------------
# Tree inventory + zero-write witness (path+hash only, never private content)
# ---------------------------------------------------------------------------


def tree_inventory(root_fs):
    """{relpath: {bytes, sha256}} of a whole tree; symlink/reparse entries
    (dirs or files, at any depth) are refused — the witness needs a real
    tree, not a link farm. Only paths, sizes and hashes are recorded."""
    root = Path(root_fs)
    if not root.is_dir():
        raise PreflightBlocked({"gate": "inventory", "reason": "not a dir",
                                "path": str(root)})
    if _is_reparse(root):
        raise PreflightBlocked(
            {"gate": "inventory", "reason": "root itself is a reparse point",
             "path": str(root)})
    out = {}
    for cur, dirs, files in os.walk(str(root)):
        cur_p = Path(cur)
        clean_dirs = []
        for name in sorted(dirs):
            p = cur_p / name
            if _is_reparse(p):
                raise PreflightBlocked(
                    {"gate": "inventory",
                     "reason": "symlink/reparse dir component",
                     "path": str(p)})
            clean_dirs.append(name)
        dirs[:] = clean_dirs
        for name in sorted(files):
            p = cur_p / name
            if _is_reparse(p):
                raise PreflightBlocked(
                    {"gate": "inventory",
                     "reason": "symlink/reparse file component",
                     "path": str(p)})
            rel = p.relative_to(root).as_posix()
            out[rel] = {"bytes": p.stat().st_size,
                        "sha256": sha256_fs_file(p)}
    return out


def inventory_diff(before, after):
    """Structured {added, removed, changed} diff of two inventories."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(r for r in set(before) & set(after)
                     if before[r] != after[r])
    return {"added": added, "removed": removed, "changed": changed,
            "clean": not (added or removed or changed)}


def check_runtime_tree_hygiene(inventory):
    """Dirty-runtime findings from an inventory (known historical state:
    __pycache__ / pyc / temp-dl dirs prove past writes — the reason a clone
    is mandatory). Findings are recorded, not hidden."""
    findings = []
    for rel in sorted(inventory):
        low = rel.lower()
        if "__pycache__" in low or low.endswith(".pyc"):
            findings.append({"path": rel, "kind": "pycache/pyc"})
        elif "vs-temp-dl" in low:
            findings.append({"path": rel, "kind": "historical download dir"})
    return {"findings": findings, "n_findings": len(findings),
            "clone_required": bool(findings)}


def zero_write_witness(label, before, after):
    """Hard gate: a protected tree must be byte-identical across an isolated
    run. Any added/removed/changed entry is a ZeroWriteViolation."""
    diff = inventory_diff(before, after)
    if not diff["clean"]:
        raise ZeroWriteViolation(
            {"reason": "protected tree changed during isolated run",
             "tree": label, "diff": {k: v for k, v in diff.items()
                                     if k != "clean"}})
    return {"tree": label, "clean": True, "files": len(before)}


# ---------------------------------------------------------------------------
# Runtime clone (stdlib pure; robocopy replaced by copy + full hash verify)
# ---------------------------------------------------------------------------


def clone_tree(src_root, dst_root):
    """Clone a whole tree to a NEW destination with reparse rejection at
    every level and per-file SHA-256 verification (copy is only trusted
    after its hash matches the source). No links, no metadata inheritance
    beyond content. Returns a manifest {files, bytes, sha256_by_rel}. Tests
    use tiny trees; the real vs tree is ~223 MB and is hashed twice by
    design (source read + clone verify)."""
    src = Path(src_root)
    dst = Path(dst_root)
    if not src.is_dir():
        raise RuntimeIdentityBlocked(
            {"reason": "clone source missing", "path": str(src)})
    if dst.exists() or dst.is_symlink():
        raise RuntimeIdentityBlocked(
            {"reason": "clone destination already exists (must be NEW)",
             "path": str(dst)})
    if _is_reparse(src):
        raise RuntimeIdentityBlocked(
            {"reason": "clone source is a reparse point", "path": str(src)})
    dst.mkdir(parents=True)
    manifest = {"files": 0, "bytes": 0, "sha256": {}, "skipped_links": 0}
    for cur, dirs, files in os.walk(str(src)):
        cur_p = Path(cur)
        rel_cur = cur_p.relative_to(src)
        clean_dirs = []
        for name in sorted(dirs):
            p = cur_p / name
            if _is_reparse(p):
                manifest["skipped_links"] += 1
                raise RuntimeIdentityBlocked(
                    {"reason": "clone refused: symlink/reparse dir component",
                     "path": str(p)})
            clean_dirs.append(name)
            (dst / rel_cur / name).mkdir(parents=True, exist_ok=True)
        dirs[:] = clean_dirs
        for name in sorted(files):
            p = cur_p / name
            if _is_reparse(p):
                raise RuntimeIdentityBlocked(
                    {"reason": "clone refused: symlink/reparse file component",
                     "path": str(p)})
            src_sha = sha256_fs_file(p)
            target = dst / rel_cur / name
            shutil.copyfile(str(p), str(target))
            dst_sha = sha256_fs_file(target)
            if src_sha != dst_sha:
                target.unlink()
                raise RuntimeIdentityBlocked(
                    {"reason": "clone hash verification failed",
                     "path": rel_cur.as_posix() + "/" + name})
            rel = target.relative_to(dst).as_posix()
            manifest["sha256"][rel] = dst_sha
            manifest["files"] += 1
            manifest["bytes"] += p.stat().st_size
    return manifest


def _pin_fail(reason, path, **extra):
    raise RuntimeIdentityBlocked(
        dict({"reason": reason, "path": path}, **extra))


def clone_runtime(sandbox_root, vs_src=None, rife_src=None, mpv_exe=None):
    """Isolated runtime clone per the survey safe_clone_recipe:
    whole D:/MPV/vs tree + rife DLL + the single selected model dir into the
    sandbox NEW clone tree. ALL survey pins (mpv.exe sha, rife dll/model
    shas, vs runtime shas) are verified against the SOURCES first — any
    missing file or sha drift fails closed with the full failure list
    (BLOCKED_ENV) BEFORE the heavy clone starts; cloned files are then
    hash-verified against the already-pinned sources. Returns the combined
    manifest."""
    layout = sandbox_layout(sandbox_root)
    vs_src = Path(vs_src) if vs_src is not None else VS_TREE_DEFAULT
    rife_src = Path(rife_src) if rife_src is not None else RIFE_DIR_DEFAULT
    mpv_exe = Path(mpv_exe) if mpv_exe is not None else MPV_EXE_DEFAULT
    failures = []
    if not mpv_exe.is_file():
        failures.append({"reason": "mpv.exe missing", "path": str(mpv_exe)})
    else:
        mpv_sha = sha256_fs_file(mpv_exe)
        if mpv_sha != MPV_EXE_SHA256:
            failures.append({"reason": "mpv.exe sha does not match survey pin",
                             "path": str(mpv_exe), "expected": MPV_EXE_SHA256,
                             "got": mpv_sha})
    for rel, (want_sha, want_bytes) in sorted(SURVEY_RIFE_PINS.items()):
        src = rife_src / rel
        if not src.is_file():
            failures.append({"reason": "survey-pinned rife file missing",
                             "path": str(src)})
            continue
        got = sha256_fs_file(src)
        if got != want_sha:
            failures.append({"reason": "rife file sha does not match survey "
                                        "pin", "path": str(src),
                             "expected": want_sha, "got": got})
    for rel, (want_sha, _) in sorted(SURVEY_RUNTIME_PINS.items()):
        src = vs_src / rel
        if not src.is_file():
            failures.append({"reason": "survey-pinned vs file missing",
                             "path": str(src)})
            continue
        got = sha256_fs_file(src)
        if got != want_sha:
            failures.append({"reason": "vs file sha does not match survey "
                                        "pin", "path": str(src),
                             "expected": want_sha, "got": got})
    if failures:
        raise RuntimeIdentityBlocked(
            {"reason": "runtime identity pins failed (BLOCKED_ENV; no "
                       "clone is attempted)",
             "failures": failures[:20], "n_failures": len(failures)})
    vs_manifest = clone_tree(vs_src, layout["clone_vs"])
    rife_dst = layout["clone_rife"]
    rife_dst.mkdir(parents=True, exist_ok=True)
    rife_manifest = {"files": 0, "bytes": 0, "sha256": {},
                     "skipped_links": 0}
    for rel, (want_sha, want_bytes) in sorted(SURVEY_RIFE_PINS.items()):
        src = rife_src / rel
        target = rife_dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _pin_fail("clone target already exists", str(target))
        shutil.copyfile(str(src), str(target))
        got = sha256_fs_file(target)
        if got != want_sha:
            target.unlink()
            _pin_fail("cloned rife file hash mismatch", str(target),
                      expected=want_sha, got=got)
        rife_manifest["sha256"][rel] = got
        rife_manifest["files"] += 1
        rife_manifest["bytes"] += want_bytes
    for rel, (want_sha, _) in sorted(SURVEY_RUNTIME_PINS.items()):
        got = vs_manifest["sha256"].get(rel)
        if got is None:
            _pin_fail("survey-pinned vs file missing in clone", rel)
        if got != want_sha:
            _pin_fail("vs file sha does not match survey pin", rel,
                      expected=want_sha, got=got)
    return {"vs": vs_manifest, "rife": rife_manifest,
            "mpv_exe": {"path": str(mpv_exe),
                        "sha256": MPV_EXE_SHA256,
                        "bytes": mpv_exe.stat().st_size}}


# ---------------------------------------------------------------------------
# Private vpy relocation (exactly ONE rewritten line; text never enters repo)
# ---------------------------------------------------------------------------

_LOADPLUGIN_RE = re.compile(r"^(\s*core\.std\.LoadPlugin\s*\(\s*)(['\"])"
                            r"(.*?)(\2)(\s*.*)$")


def vpy_algorithm_sha256(data):
    """Algorithm hash of a vpy: SHA-256 over the bytes with the LoadPlugin
    PATH ARGUMENT masked out (so two scripts differing only in the plugin
    path share one algorithm identity; any other byte difference changes the
    hash)."""
    lines = bytes(data).split(b"\n")
    masked = []
    for line in lines:
        m = re.match(rb"^(\s*core\.std\.LoadPlugin\s*\(\s*['\"]).*?(['\"].*)$",
                     line)
        if m:
            masked.append(m.group(1) + b"<PATH>" + m.group(2))
        else:
            masked.append(line)
    return hashlib.sha256(b"\n".join(masked)).hexdigest()


def relocate_vpy(original_bytes, cloned_dll_fs_path, expected_sha256=None):
    """Copy the private active vpy to TEMP with EXACTLY the LoadPlugin line
    rewritten to the cloned DLL path. Verifies:
      * exactly one LoadPlugin line exists;
      * (optional) the original bytes hash to the survey pin;
      * every other byte is untouched (by construction + recheck).
    Returns {relocated_bytes, record}. The record contains hashes and the
    replaced line number/range ONLY — the private full text never enters the
    repo (the relocated bytes live only in the TEMP sandbox)."""
    original_bytes = bytes(original_bytes)
    text = original_bytes.decode("utf-8")
    lines = text.split("\n")
    hits = [(i, _LOADPLUGIN_RE.match(line)) for i, line in enumerate(lines)]
    hits = [(i, m) for i, m in hits if m]
    if len(hits) != 1:
        raise RuntimeIdentityBlocked(
            {"reason": "vpy must contain exactly one LoadPlugin line",
             "found": len(hits)})
    i, m = hits[0]
    original_line = lines[i]
    dll_path = str(Path(cloned_dll_fs_path)).replace("\\", "/")
    lines[i] = m.group(1) + "'" + dll_path + "'" + m.group(5)
    relocated = ("\n".join(lines)).encode("utf-8")
    if expected_sha256 is not None:
        got = hashlib.sha256(original_bytes).hexdigest()
        if got != expected_sha256:
            raise RuntimeIdentityBlocked(
                {"reason": "active vpy sha does not match survey pin",
                 "expected": expected_sha256, "got": got})
    record = {
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "relocated_sha256": hashlib.sha256(relocated).hexdigest(),
        "algorithm_sha256": vpy_algorithm_sha256(original_bytes),
        "relocated_algorithm_sha256": vpy_algorithm_sha256(relocated),
        "replaced_line_no": i + 1,           # 1-based
        "replaced_line_count": 1,
        "original_line_sha256": hashlib.sha256(
            original_line.encode("utf-8")).hexdigest(),
        "relocated_line_sha256": hashlib.sha256(
            lines[i].encode("utf-8")).hexdigest(),
        "cloned_dll_path": dll_path,
        "private_text_in_repo": False,
    }
    if record["algorithm_sha256"] != record["relocated_algorithm_sha256"]:
        raise RuntimeIdentityBlocked(
            {"reason": "relocation changed more than the plugin path line "
                       "(algorithm hash drifted)",
             "algorithm_sha256": record["algorithm_sha256"],
             "relocated_algorithm_sha256":
                 record["relocated_algorithm_sha256"]})
    # byte-level recheck: with the LoadPlugin PATH ARGUMENT masked, every
    # line of the relocated script must be identical to the original — any
    # non-path byte change is a relocation crime
    def _mask_line(line):
        mm = _LOADPLUGIN_RE.match(line)
        if not mm:
            return line
        return mm.group(1) + mm.group(2) + "<PATH>" + mm.group(4) + mm.group(5)
    orig_lines = text.split("\n")
    new_lines = relocated.decode("utf-8").split("\n")
    if len(orig_lines) != len(new_lines):
        raise RuntimeIdentityBlocked(
            {"reason": "relocation changed the line count"})
    for j, (o, n) in enumerate(zip(orig_lines, new_lines)):
        if _mask_line(o) != _mask_line(n):
            raise RuntimeIdentityBlocked(
                {"reason": "relocation changed non-path bytes",
                 "line": j + 1})
    return {"relocated_bytes": relocated, "record": record}


# ---------------------------------------------------------------------------
# Preregistered identity sample: rife-identity-short-v1 (pure stdlib Y4M)
# ---------------------------------------------------------------------------

IDENTITY_SAMPLE_ID = "rife-identity-short-v1"
IDENTITY_PARAMS = {
    "width": 1920, "height": 1080, "frames": 12,
    "fps_variants": (24, 30),
    "y_base": 16,                       # limited-range black floor
    "disk_radius_px": 120,
    "disk_center_initial": [600, 500],
    "disk_delta_px": [8, 3],
    "stripe_luma": [180, 235],          # diagonal stripes, period 12 px,
    "stripe_period_px": 12,             # 6px light / 6px dark (preregistered)
    "texture_square_origin": [1400, 650],   # fixed non-rigid cue,
    "texture_square_size": [96, 96],        # 8px checker luma 64/144
    "texture_luma": [64, 144],
    "uv_constant": 128,
    "marker_strip_px": 8,               # top strip, 8 cells luma 64/192,
    "marker_luma": [64, 192],           # LSB-first binary ordinal
    "color": "SDR BT709 limited yuv420p (C420jpeg Y4M container)",
    "preregistration":
        "writer-preregistered before any model output was seen; generator "
        "sha + source sha recorded with every sample; sample is only the "
        "identity/first-load probe and never a performance A/B clip",
}
_IDENTITY_FRAME_BYTES = (IDENTITY_PARAMS["width"] * IDENTITY_PARAMS["height"]
                         + 2 * (IDENTITY_PARAMS["width"] // 2)
                         * (IDENTITY_PARAMS["height"] // 2))


def _identity_y_plane(fps, index):
    """One Y plane as bytearray (row-major). fps does not change pixels; the
    two variants share identical frames and differ only in the Y4M header."""
    p = IDENTITY_PARAMS
    w, h = p["width"], p["height"]
    y = bytearray(bytes([p["y_base"]]) * (w * h))
    # top marker strip: 8 cells, LSB-first ordinal, luma 64/192
    strip = p["marker_strip_px"]
    cell_w = w // 8
    for c in range(8):
        val = p["marker_luma"][1] if (index >> c) & 1 else p["marker_luma"][0]
        band = bytes([val]) * cell_w
        for row in range(strip):
            y[row * w + c * cell_w: row * w + (c + 1) * cell_w] = band
    # moving bright disk with diagonal stripes (non-constant, non-rigid cue)
    cx = p["disk_center_initial"][0] + p["disk_delta_px"][0] * index
    cy = p["disk_center_initial"][1] + p["disk_delta_px"][1] * index
    r = p["disk_radius_px"]
    r2 = r * r
    lo, hi = p["stripe_luma"]
    period = p["stripe_period_px"]
    half_period = period // 2
    for dy in range(-r, r + 1):
        yy = cy + dy
        if yy < strip or yy >= h:
            continue
        half = math.isqrt(r2 - dy * dy)
        x0 = max(0, cx - half)
        x1 = min(w, cx + half + 1)
        row_base = yy * w
        for x in range(x0, x1):
            y[row_base + x] = hi if ((x + yy) % period) < half_period else lo
    # fixed fine-texture square (static across frames: non-rigid difference)
    ox, oy = p["texture_square_origin"]
    tw, th = p["texture_square_size"]
    tlo, thi = p["texture_luma"]
    for dy in range(th):
        yy = oy + dy
        row_base = yy * w
        for dx in range(tw):
            xx = ox + dx
            y[row_base + xx] = tlo if ((dx // 8) + (dy // 8)) % 2 == 0 \
                else thi
    return y


def identity_frame_planes(fps, index):
    """(y, u, v) planes of one identity-sample frame. U/V are constant 128
    (chroma carries no information; the disk/stripes are luma-only)."""
    p = IDENTITY_PARAMS
    if fps not in p["fps_variants"]:
        raise lib.ValueContractError(
            "identity sample fps must be one of %s, got %r"
            % (p["fps_variants"], fps))
    index = lib.require_int(index, "frame index", minimum=0)
    if index >= p["frames"]:
        raise lib.ValueContractError(
            "identity sample has %d frames, got index %d"
            % (p["frames"], index))
    w, h = p["width"], p["height"]
    y = _identity_y_plane(fps, index)
    uv = bytes([p["uv_constant"]]) * ((w // 2) * (h // 2))
    return bytes(y), uv, uv


def identity_y4m_header(fps):
    return "YUV4MPEG2 W%d H%d F%d:1 Ip A1:1 C420jpeg\n" % (
        IDENTITY_PARAMS["width"], IDENTITY_PARAMS["height"], fps)


def write_identity_sample_y4m(path, fps):
    """Create-only Y4M writer: header + 12 complete FRAME blocks. Returns the
    evidence record (source sha / generator sha / full parameters)."""
    p = IDENTITY_PARAMS
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise SpawnRefused({"reason": "identity sample target exists",
                            "path": str(target)})
    header = identity_y4m_header(fps).encode("ascii")
    h = hashlib.sha256()
    frames = []
    with open(str(target), "xb") as fh:
        fh.write(header)
        h.update(header)
        for idx in range(p["frames"]):
            y, u, v = identity_frame_planes(fps, idx)
            payload = y + u + v
            if len(payload) != _IDENTITY_FRAME_BYTES:
                raise SamplingPayloadError(
                    {"reason": "identity frame payload length crime",
                     "got": len(payload),
                     "expected": _IDENTITY_FRAME_BYTES})
            block = b"FRAME\n" + payload
            fh.write(block)
            h.update(block)
            frames.append({"index": idx,
                           "y_sha256": hashlib.sha256(y).hexdigest()})
    record = {
        "sample": IDENTITY_SAMPLE_ID,
        "fps": fps,
        "sha256": h.hexdigest(),
        "bytes": len(header) + p["frames"] * (6 + _IDENTITY_FRAME_BYTES),
        "frames": p["frames"],
        "frame_payload_bytes": _IDENTITY_FRAME_BYTES,
        "params": dict(IDENTITY_PARAMS),
        "generator": COLLECT_REL,
        "generator_sha256": lib.library_sha256(),
        "frame_y_sha256": frames,
        "frame_class_note": "all 12 frames are source (S) frames; RIFE "
                            "output classification is lib.rife_output_"
                            "frame_class (even=S, odd=M)",
    }
    return record


def identity_marker_index(y_plane, width=None):
    """Decode the LSB-first ordinal from the top 8-px strip (cell midpoints,
    row 4)."""
    p = IDENTITY_PARAMS
    w = width if width is not None else p["width"]
    cell_w = w // 8
    idx = 0
    for c in range(8):
        v = y_plane[4 * w + c * cell_w + cell_w // 2]
        if v >= 128:
            idx |= 1 << c
    return idx


def verify_identity_sample_y4m(path, fps):
    """Full re-parse: header, 12 FRAME markers, exact payload lengths, and
    BYTE-FOR-BYTE regeneration equality (the sample must be reproducible).
    Returns the record; any crime raises."""
    p = IDENTITY_PARAMS
    w = p["width"]
    y_plane_bytes = w * p["height"]
    target = Path(path)
    if not target.is_file():
        raise SamplingPayloadError({"reason": "sample file missing",
                                    "path": str(target)})
    data = target.read_bytes()
    header = identity_y4m_header(fps).encode("ascii")
    if not data.startswith(header):
        raise SamplingPayloadError(
            {"reason": "Y4M header mismatch", "path": str(target),
             "expected_header": identity_y4m_header(fps)})
    pos = len(header)
    frames = []
    for idx in range(p["frames"]):
        if data[pos:pos + 6] != b"FRAME\n":
            raise SamplingPayloadError(
                {"reason": "missing FRAME marker", "frame": idx,
                 "at_byte": pos})
        pos += 6
        payload = data[pos:pos + _IDENTITY_FRAME_BYTES]
        if len(payload) != _IDENTITY_FRAME_BYTES:
            raise SamplingPayloadError(
                {"reason": "truncated frame payload", "frame": idx,
                 "got": len(payload),
                 "expected": _IDENTITY_FRAME_BYTES})
        y, u, v = identity_frame_planes(fps, idx)
        if payload != y + u + v:
            raise SamplingPayloadError(
                {"reason": "frame payload not reproducible (byte diff)",
                 "frame": idx})
        marker = identity_marker_index(payload[:y_plane_bytes])
        if marker != idx:
            raise SamplingPayloadError(
                {"reason": "marker strip ordinal mismatch", "frame": idx,
                 "decoded": marker})
        frames.append(hashlib.sha256(payload).hexdigest())
        pos += _IDENTITY_FRAME_BYTES
    if pos != len(data):
        raise SamplingPayloadError(
            {"reason": "trailing bytes after frame %d" % p["frames"],
             "extra": len(data) - pos})
    return {"sample": IDENTITY_SAMPLE_ID, "fps": fps,
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "frames": p["frames"], "frame_sha256": frames,
            "marker_ok": True, "reproducible": True,
            "params": dict(IDENTITY_PARAMS)}


# ---------------------------------------------------------------------------
# Atomic sampler (TEMP Lua helper + structured single-reply IPC)
# ---------------------------------------------------------------------------

COUNTER_CANDIDATES = (
    "dropped-frame-count", "decoder-frame-drop-count", "vo-delayed-frame-count",
    "mistimed-frame-count", "eof-reached",
)

SAMPLER_LUA_TEMPLATE = """-- p4-001 atomic sampler (TEMP helper; single-reply protocol)
-- One script-message request -> ONE event callback collects EVERYTHING
-- (video-out-params + osd-dimensions + real margins + native vo-passes node
-- + real counter families + time-pos + render-reconfig epoch) and replies
-- with ONE structured message. Nothing is sampled across several reads.
local utils = require 'mp.utils'
local epoch = 0
mp.register_event("video-reconfig", function() epoch = epoch + 1 end)
mp.register_event("playback-restart", function() epoch = epoch + 1 end)
local function num(name)
  local v = mp.get_property_number(name)
  if v == nil then return nil end
  return v
end
local function counters()
  local out = {}
  local names = { %(counters)s }
  for _, name in ipairs(names) do
    local v = num(name)
    if v ~= nil then out[name] = v end
  end
  return out
end
mp.register_script_message("%(request)s", function(token)
  local vop = mp.get_property_native("video-out-params")
  local osd_w = num("osd-width")
  local osd_h = num("osd-height")
  local margins = mp.get_osd_margins()
  local vp = mp.get_property_native("vo-passes")
  local payload = {
    epoch = epoch,
    vop = vop,
    osd = { w = osd_w, h = osd_h, margins = margins },
    vo_passes = vp,
    counters = counters(),
    time_pos = num("time-pos"),
    fps_fields = {
      estimated_vf_fps = num("estimated-vf-fps"),
      fps = num("fps"),
      container_fps = num("container-fps"),
    },
  }
  local ok, json = pcall(utils.format_json, payload)
  if not ok then
    mp.commandv("script-message", "%(reply)s", token, "{\\"error\\":\\"json\\"}")
    return
  end
  mp.commandv("script-message", "%(reply)s", token, json)
end)
""" % {"counters": ", ".join('"%s"' % n for n in COUNTER_CANDIDATES),
       "request": SAMPLER_MSG_REQUEST, "reply": SAMPLER_MSG_REPLY}


def install_sampler_script(cfg_dir):
    """Write the TEMP sampler Lua into the sandbox config P4-SCRIPTS dir
    (create-only). cfg/p4-scripts is a directory mpv never auto-scans —
    the sampler loads only via its explicit --script entry (R3-2).
    Returns its file binding."""
    target = Path(cfg_dir) / "p4-scripts" / SAMPLER_SCRIPT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SpawnRefused({"reason": "sampler script already exists",
                            "path": str(target)})
    data = SAMPLER_LUA_TEMPLATE.encode("utf-8")
    with open(str(target), "xb") as fh:
        fh.write(data)
    return {"path": str(target), "sha256": lib.sha256_bytes(data),
            "bytes": len(data)}


def parse_ipc_line(line_bytes):
    """Pure IPC line classification used by the reader loop:
    ("response", request_id, obj) | ("client-message", token, args)
    | ("event", None, obj) | (None, None, None) for unparsable lines."""
    try:
        obj = json.loads(line_bytes.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return (None, None, None)
    if not isinstance(obj, dict):
        return (None, None, None)
    if obj.get("event") == "client-message":
        args = obj.get("args") or []
        if len(args) >= 3 and args[0] == SAMPLER_MSG_REPLY:
            return ("client-message", args[1], args)
        return ("event", None, obj)
    if "request_id" in obj:
        return ("response", obj.get("request_id"), obj)
    return ("event", None, obj)


class CollectIpc:
    """Self-contained JSON-IPC client (p1_lib.IpcClient is read-only prior
    art; it cannot receive script-message replies, so the collector owns a
    compatible client with an inbox for client-message payloads).

    L1 wall-clock discipline: a dedicated daemon reader thread feeds a
    queue, so a LIVE but silent peer can never hold the caller past a real
    wall deadline (the old same-thread blocking readline could only check
    deadlines BETWEEN lines and would block forever on a pipe that never
    answers — such an in-loop deadline was never a wall cap). Every request
    carries a monotonic deadline; expiry raises honestly. The reader is
    reclaimed by stopping the OWN child first (the pipe EOF unblocks the
    reader) and only then joining it and closing the file — close() must
    never touch the file while the reader may still hold the buffer lock,
    and a still-blocked reader is refused instead of lying about being
    closed.
    """

    DEFAULT_CMD_TIMEOUT_S = 30.0

    def __init__(self, pipe_name, timeout_s=30.0, open_func=None):
        self.pipe_name = pipe_name
        self.target = PIPE_NAMESPACE + pipe_name
        self.inbox = {}          # token -> args
        self.responses = {}      # request_id -> obj
        self.transcript = []
        self._request_id = 0
        self.f = None
        self._lines = queue.Queue()
        self._write_lock = threading.Lock()
        self._closing = False
        self._reader = None
        opener = open_func or open
        deadline = time.monotonic() + timeout_s
        last_err = None
        while time.monotonic() < deadline:
            try:
                self.f = opener(self.target, "r+b", buffering=1 << 20)
                break
            except OSError as exc:
                last_err = exc
                time.sleep(0.2)
        else:
            raise SamplingPayloadError(
                {"reason": "ipc pipe connect failed", "target": self.target,
                 "error": str(last_err)})
        self._reader = threading.Thread(
            target=self._reader_loop, name="p4-collect-ipc-reader",
            daemon=True)
        self._reader.start()

    def _reader_loop(self):
        """Daemon producer: pushes every complete line into the queue; on
        EOF or a dead pipe a None sentinel wakes every waiter."""
        try:
            while not self._closing:
                line = self.f.readline()
                if not line:
                    break
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    def _next_line(self, deadline_eff):
        """One line within the REAL wall deadline (a queue get bounded by
        the remaining time — not a check between blocking reads)."""
        remaining = deadline_eff - time.monotonic()
        if remaining <= 0:
            raise SamplingPayloadError(
                {"reason": "ipc deadline expired (wall clock; no line "
                           "arrived in the remaining budget)"})
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty:
            raise SamplingPayloadError(
                {"reason": "ipc deadline expired while the live peer sent "
                           "no line (honest wall-clock cap, never extended "
                           "until it answers)", "waited_s": remaining})
        if line is None:
            self._lines.put(None)   # keep the EOF visible for later waiters
            raise SamplingPayloadError(
                {"reason": "ipc pipe closed (reader hit EOF)"})
        return line

    def cmd(self, *args, record=True, timeout_s=None):
        self._request_id += 1
        rid = self._request_id
        payload = json.dumps({"command": list(args),
                              "request_id": rid}).encode("utf-8") + b"\n"
        deadline_eff = time.monotonic() + (self.DEFAULT_CMD_TIMEOUT_S
                                           if timeout_s is None
                                           else float(timeout_s))
        try:
            with self._write_lock:
                self.f.write(payload)
                self.f.flush()
        except (OSError, ValueError) as exc:
            raise SamplingPayloadError(
                {"reason": "ipc write failed", "error": str(exc)})
        while True:
            kind, key, obj = parse_ipc_line(self._next_line(deadline_eff))
            if kind == "response" and key == rid:
                if record:
                    self.transcript.append({"req": list(args),
                                            "error": obj.get("error")})
                return obj
            if kind == "client-message":
                self.inbox[key] = obj
            elif kind == "response":
                self.responses[key] = obj   # non-matching id, kept honestly
            # other events are skipped, honestly

    def wait_sample_reply(self, token, timeout_s=10.0, deadline=None):
        """Wait for the sampler reply carrying `token`; the deadline is a
        real wall cap (queue wait bounded by the remaining monotonic time),
        so a peer that never answers cannot outlive it."""
        deadline_eff = deadline if deadline is not None else (
            time.monotonic() + timeout_s)
        while True:
            if token in self.inbox:
                args = self.inbox.pop(token)[2]
                try:
                    return json.loads(args)
                except json.JSONDecodeError as exc:
                    raise SamplingPayloadError(
                        {"reason": "sampler reply is not valid JSON",
                         "error": str(exc)})
            kind, key, obj = parse_ipc_line(self._next_line(deadline_eff))
            if kind == "client-message":
                self.inbox[key] = obj

    def sample_once(self, token, timeout_s=10.0, deadline=None):
        """One atomic sample = ONE script-message request + ONE reply, both
        inside the same overall trial wall budget."""
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SamplingPayloadError(
                    {"reason": "trial wall budget already expired before "
                               "the sample request", "token": token})
            self.cmd("script-message", SAMPLER_MSG_REQUEST, token,
                     timeout_s=remaining)
        else:
            self.cmd("script-message", SAMPLER_MSG_REQUEST, token,
                     timeout_s=timeout_s)
        return self.wait_sample_reply(token, timeout_s, deadline)

    def close(self, join_timeout_s=5.0):
        """Reclaim the reader thread, then close the file. The OWN child
        must already be stopped by the owner (quit/kill) so the pipe EOFs
        and the reader exits; a still-blocked reader is REFUSED with a
        bounded join and the file left open (never a buffer-lock deadlock,
        never a false closed claim)."""
        self._closing = True
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(join_timeout_s)
        if reader is not None and reader.is_alive():
            raise CollectError(
                {"reason": "ipc reader thread still blocked; stop the "
                           "owning child so the pipe EOFs, then close",
                 "pipe": self.target})
        self._reader = None
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                break
        if self.f is not None:
            try:
                self.f.close()
            except OSError:
                pass
            self.f = None


# LF10 native -> canonical mapping (docs/证据/mpv-input.rst: count = native
# per-pass timing-sample count, samples = raw ns ARRAY; verbatim, no dedup).


def map_native_pass_entry(node, ordinal):
    if not isinstance(node, dict):
        raise SamplingPayloadError({"reason": "pass node is not a dict",
                                    "ordinal": ordinal})
    desc = node.get("desc")
    if not isinstance(desc, str) or not desc:
        raise SamplingPayloadError({"reason": "pass node lacks desc",
                                    "ordinal": ordinal})
    entry = {"desc": desc}
    for src, dst in (("last", "last_ns"), ("avg", "avg_ns"),
                     ("peak", "peak_ns")):
        value = node.get(src)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SamplingPayloadError(
                {"reason": "pass node %s missing/not numeric" % src,
                 "ordinal": ordinal, "desc": desc})
        entry[dst] = value
    count = node.get("count")
    if count is None:
        entry["count"] = None        # API-omitted native count, never fabricated
    elif isinstance(count, bool) or not isinstance(count, int):
        raise SamplingPayloadError(
            {"reason": "native count not an int", "ordinal": ordinal})
    else:
        entry["count"] = count
    samples = node.get("samples")
    if samples is None:
        entry["samples_ns"] = []
    elif isinstance(samples, list):
        entry["samples_ns"] = list(samples)   # verbatim, duplicates kept
    else:
        raise SamplingPayloadError(
            {"reason": "native samples is not an array", "ordinal": ordinal})
    entry["raw_node"] = dict(node)       # unmapped native node preserved
    return entry


def map_native_vo_passes(vp_node):
    if not isinstance(vp_node, dict) or \
            not isinstance(vp_node.get("fresh"), list) or \
            not isinstance(vp_node.get("redraw"), list):
        raise SamplingPayloadError(
            {"reason": "vo-passes node lacks fresh/redraw lists"})
    return {
        "fresh": [map_native_pass_entry(n, i)
                  for i, n in enumerate(vp_node["fresh"])],
        "redraw": [map_native_pass_entry(n, i)
                   for i, n in enumerate(vp_node["redraw"])],
    }


def _as_int_if_integral(value):
    """mpv delivers property numbers as JSON numbers; integral values are
    normalised to int (honest normalisation of inherently integral fields,
    never a change of value)."""
    if isinstance(value, float) and not isinstance(value, bool) \
            and math.isfinite(value) and value == int(value):
        return int(value)
    return value


def payload_to_snapshot(snapshot_index, wall_monotonic_s, payload,
                        source_block=None, slot_target_s=None):
    """Map one atomic sampler reply to a B1-r2 snapshot record (validated by
    lib.validate_snapshot before returning). Honest failures raise instead
    of inventing fields."""
    snapshot_index = lib.require_int(snapshot_index, "snapshot_index",
                                     minimum=0)
    wall = lib.require_finite_number(wall_monotonic_s, "wall_monotonic_s")
    if not isinstance(payload, dict):
        raise SamplingPayloadError({"reason": "payload is not a dict"})
    vop = payload.get("vop")
    if not isinstance(vop, dict):
        raise SamplingPayloadError(
            {"reason": "no video-out-params in reply (vo not configured?)",
             "snapshot_index": snapshot_index})
    out_vop = {}
    for key in ("pixelformat", "w", "h", "dw", "dh", "gamma"):
        if key in vop and vop[key] is not None:
            out_vop[key] = (_as_int_if_integral(vop[key])
                            if key != "pixelformat" else vop[key])
    fps_fields = payload.get("fps_fields") or {}
    for key in ("estimated_vf_fps", "fps", "container_fps"):
        value = fps_fields.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value):
            out_vop[key] = value
    osd = payload.get("osd") or {}
    osd_out = {}
    if osd.get("w") is not None:
        osd_out["w"] = _as_int_if_integral(osd["w"])
    if osd.get("h") is not None:
        osd_out["h"] = _as_int_if_integral(osd["h"])
    margins = osd.get("margins") or {}
    margin_map = {"left": "ml", "right": "mr", "top": "mt", "bottom": "mb"}
    observed_margins = {dst: _as_int_if_integral(margins[src])
                        for src, dst in margin_map.items()
                        if isinstance(margins.get(src), (int, float))}
    if len(observed_margins) == 4:
        osd_out.update(observed_margins)   # all-or-none, actually observed
    elif observed_margins:
        raise SamplingPayloadError(
            {"reason": "partial osd margins observed (all-or-none crime)",
             "got": sorted(observed_margins)})
    time_pos = payload.get("time_pos")
    if not isinstance(time_pos, (int, float)) or isinstance(time_pos, bool) \
            or time_pos < 0:
        raise SamplingPayloadError(
            {"reason": "time-pos missing/negative in reply (recorded as a "
                       "failed poll, never fabricated)",
             "snapshot_index": snapshot_index})
    epoch = _as_int_if_integral(payload.get("epoch"))
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise SamplingPayloadError(
            {"reason": "render epoch missing in reply", "epoch": epoch})
    snap = {
        "snapshot_index": snapshot_index,
        "wall_monotonic_s": wall,
        "time_pos_s": time_pos,
        "epoch": epoch,
        "video_out_params": out_vop,
        "osd_dimensions": osd_out,
        "vo_passes": map_native_vo_passes(payload.get("vo_passes")),
        "same_window": True,   # one reply = one command window (SINGLE_COMMAND_NOTE)
    }
    counters = payload.get("counters")
    if isinstance(counters, dict) and counters:
        clean = {}
        for name, value in counters.items():
            value = _as_int_if_integral(value)
            if isinstance(value, int) and not isinstance(value, bool) \
                    and value >= 0:
                clean[str(name)] = value
        if clean:
            snap["counters"] = clean   # real counter families only
    if source_block is not None:
        snap["source"] = dict(source_block)
    if slot_target_s is not None:
        note = "slot_target_monotonic_s=%.6f" % float(slot_target_s)
        if payload.get("error"):
            note += " sampler_error=%s" % payload["error"]
        snap["note"] = note
    lib.validate_snapshot(snap)
    return snap


def source_block_for(clip_id, media_sha256):
    """F5 source binding from REAL facts: the actually played media file
    hash and the current frozen generator revision (never the spec's
    imagination)."""
    return {"clip": clip_id,
            "media_sha256": lib.require_sha256_hex(media_sha256,
                                                   "media_sha256"),
            "generator_sha256": lib.library_sha256()}


def observed_output_fps_from_snapshots(snapshots, start, count):
    """Real filter-output fps from the in-window snapshots: the
    estimated-vf-fps field probed FIRST (never container-fps). Returns
    (median_or_None, provenance) — a missing field stays missing so the
    analysis honestly rejects with REJECTED_FPS_UNBOUND."""
    values = []
    for snap in snapshots[start:start + count]:
        v = snap.get("video_out_params", {}).get("estimated_vf_fps")
        if isinstance(v, (int, float)) and not isinstance(v, bool) \
                and math.isfinite(v) and v > 0:
            values.append(float(v))
    if not values:
        return None, "estimated_vf_fps absent in every in-window snapshot"
    values.sort()
    median = values[len(values) // 2] if len(values) % 2 == 1 else \
        (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2.0
    return median, ("median of %d in-window estimated-vf-fps observations "
                    "(filter output; container-fps never used)" % len(values))


# ---------------------------------------------------------------------------
# Launch args / process session (own-PID ownership; finally-closed handles)
# ---------------------------------------------------------------------------


def build_mpv_launch_args(config_dir, pipe_name, log_path, window=None,
                          fullscreen=False, vo="gpu-next", extra_args=(),
                          media=None, screenshot_dir=None,
                          watch_later_dir=None, mpv_exe=None, scripts=()):
    """Deterministic mpv argv. The fullscreen decision is NEVER overridden by
    a hardcoded --fullscreen=no (the old p1 MpvSession.start bug is not
    inherited): the flag is only added when requested, and the actual window
    geometry is verified by osd readback afterwards, not assumed.

    R3-2: --no-config is NEVER emitted — it silently disabled the WHOLE
    sandbox config (identity-run-001 proof: the effective vf chain had no
    vapoursynth filter because the engagement line lived in an mpv.conf
    that --no-config refused to read). Isolation is kept WITHOUT it:
    --config-dir is the ONLY config root (the active/system config tree is
    never consulted, and the child env redirects HOME/APPDATA into the
    sandbox), so the controlled sandbox mpv.conf is REALLY loaded.
    Lua scripts are explicit, never auto-scanned: every user script is
    loaded by exact path via --script from cfg/p4-scripts (a directory mpv
    NEVER scans — cfg/scripts stays empty, so nothing can sneak in via
    auto-scan). --load-scripts=no is deliberately NOT used: real mpv
    (author smoke evidence) gates user --script entries with it too, so it
    cannot be combined with explicit loading. mpv's own builtin scripts
    (osc/stats/console/...) load in every run as part of the product
    environment, exactly as before."""
    mpv = Path(mpv_exe) if mpv_exe is not None else MPV_EXE_DEFAULT
    args = [str(mpv), "--config-dir=%s" % Path(config_dir)]
    for script in scripts:
        args.append("--script=%s" % Path(script))
    if pipe_name:
        args.append("--input-ipc-server=%s" % pipe_name)
    args.append("--vo=%s" % vo)
    if vo == "gpu-next":
        args.append("--gpu-api=vulkan")
    args.append("--log-file=%s" % Path(log_path))
    if screenshot_dir is not None:
        args.append("--screenshot-directory=%s" % Path(screenshot_dir))
    if watch_later_dir is not None:
        args.append("--watch-later-dir=%s" % Path(watch_later_dir))
    if window is not None:
        args.append("--geometry=%dx%d" % (int(window[0]), int(window[1])))
    if fullscreen:
        args.append("--fullscreen=yes")
    args.extend(str(a) for a in extra_args)
    if media is not None:
        args.append(str(Path(media)))
    if "--fullscreen=no" in args:
        raise CollectError("hardcoded --fullscreen=no is forbidden (real "
                           "osd readback verification instead)")
    return args


class CollectSession:
    """One mpv (or probe) process OWNED by this tool: pid recorded at spawn,
    console/log create-only, IPC optional, quit/kill only ever touch this
    process object, every handle closed in finally, and the manifest is
    refused until everything is closed."""

    def __init__(self, trial_dir, exe_args, pipe_name=None, env=None,
                 cwd=None, log_name="mpv.log", console_name="console.txt",
                 spawn=None, ipc_open_func=None):
        self.trial_dir = Path(trial_dir)
        if not self.trial_dir.is_dir():
            raise SpawnRefused({"reason": "trial dir missing",
                                "path": str(self.trial_dir)})
        self.exe_args = [str(a) for a in exe_args]
        self.pipe_name = pipe_name
        self.env = env
        self.cwd = cwd
        self.console_path = self.trial_dir / console_name
        self.log_path = self.trial_dir / log_name
        self.pid_path = self.trial_dir / "pid.json"
        self.manifest_path = self.trial_dir / "manifest.json"
        for p in (self.console_path, self.log_path, self.pid_path,
                  self.manifest_path):
            if p.exists():
                raise SpawnRefused(
                    {"reason": "create-only trial target exists",
                     "path": str(p)})
        self.proc = None
        self.ipc = None
        self.exit_code = None
        self.killed_by_tool = False
        self._console_f = None
        self._spawn = spawn or subprocess.Popen
        self._ipc_open_func = ipc_open_func
        self.started_monotonic = None
        self.cleanup_errors = []   # structured cleanup failures (F1)

    def start(self, connect_ipc=True, ipc_timeout_s=30.0):
        """Create-only console, spawn the OWN child, record the pid, then
        (optionally) connect the IPC pipe. If any step fails AFTER a resource
        was taken, the own child (if started) is stopped and every handle is
        closed BEFORE the failure propagates (F1: a failed start leaves no
        orphan and no open console/IPC handle)."""
        self._console_f = open(str(self.console_path), "xb")
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            self.proc = self._spawn(
                self.exe_args, stdout=self._console_f, stderr=subprocess.STDOUT,
                env=self.env, cwd=self.cwd, creationflags=creationflags)
            self.started_monotonic = _now_monotonic()
            with open(str(self.pid_path), "xb") as fh:
                fh.write(lib.strict_json_bytes({
                    "pid": self.proc.pid, "exe": self.exe_args[0],
                    "pipe": self.pipe_name,
                    "started_monotonic_s": self.started_monotonic,
                    "owned_by": COLLECT_REL,
                    "note": "only this recorded PID/process object is ever "
                            "stopped by the collector"}))
            if connect_ipc and self.pipe_name:
                self.ipc = CollectIpc(self.pipe_name, timeout_s=ipc_timeout_s,
                                      open_func=self._ipc_open_func)
        except BaseException:
            try:
                if self.proc is not None and self.proc.poll() is None:
                    self.kill()
            finally:
                self._close_ipc()
                self._close_console()
            raise
        return self

    def get_property(self, name, timeout_s=None):
        if self.ipc is None:
            raise CollectError("ipc not connected")
        r = self.ipc.cmd("get_property", name, timeout_s=timeout_s)
        if r.get("error") == "success":
            return r.get("data")
        return None

    def _remaining(self, deadline):
        if deadline is None:
            return None
        return max(0.05, deadline - time.monotonic())

    def verify_window_geometry(self, expected_w, expected_h, deadline=None):
        """Read back the REAL window pixels (osd-width/osd-height) — the
        fullscreen/window decision is verified, never assumed. Returns
        {observed, expected, match} and records the observation either way.
        The readbacks run inside the trial wall budget when a deadline is
        given."""
        observed_w = self.get_property("osd-width",
                                       timeout_s=self._remaining(deadline))
        observed_h = self.get_property("osd-height",
                                       timeout_s=self._remaining(deadline))
        result = {
            "expected": [int(expected_w), int(expected_h)],
            "observed": [observed_w, observed_h],
            "match": observed_w == int(expected_w)
            and observed_h == int(expected_h),
            "method": "osd-width/osd-height readback (real window pixels)",
        }
        return result

    def quit(self, timeout_s=15.0):
        """Ask the OWN child to quit and WAIT for it (its death EOFs the IPC
        pipe and unblocks the reader thread), then close the handles — the
        pipe is never closed under a live blocking reader (L1)."""
        if self.proc is None:
            self._close_ipc()
            self._close_console()
            return True
        if self.ipc is not None:
            try:
                self.ipc.cmd("quit", record=False,
                             timeout_s=min(2.0, float(timeout_s)))
            except CollectError:
                pass
        else:
            # no IPC channel: terminate the OWN child directly (still scoped
            # to this process object, never a global kill)
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self.proc is not None:
            try:
                self.exit_code = self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self.kill()
                return False
        self._close_ipc()
        self._close_console()
        return True

    def kill(self):
        """Terminate ONLY the recorded own process (and its child tree via
        the scoped /PID flag — never a global kill)."""
        self.killed_by_tool = True
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T",
                            "/F"], capture_output=True)
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        self._close_ipc()
        self._close_console()

    def _close_ipc(self):
        if self.ipc is not None:
            self.ipc.close()
            self.ipc = None

    def _close_console(self):
        if self._console_f is not None:
            try:
                self._console_f.close()
            except OSError:
                pass
            self._console_f = None

    def handles_closed(self):
        return self._console_f is None and (self.ipc is None
                                            or self.ipc.f is None)

    def close(self):
        """Idempotent finaliser — every own handle ends before this returns.
        ALWAYS called from finally blocks. Cleanup failures are recorded on
        the session (cleanup_errors) instead of masking the primary failure
        or lying about a closed handle."""
        if self.proc is not None:
            try:
                if self.exit_code is None:
                    self.exit_code = self.proc.poll()
            except Exception:
                pass
        for closer in (self._close_ipc, self._close_console):
            try:
                closer()
            except Exception as exc:
                self.cleanup_errors.append(
                    {"stage": "close", "target": closer.__name__,
                     "error": "%s: %s" % (type(exc).__name__, exc)})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # finally-semantics: the child never survives a body exception
        if self.proc is not None:
            if self.proc.poll() is None:
                self.kill()
        self.close()
        return False

    def write_manifest(self, payload):
        """Create-only trial manifest — refused while any own handle is open
        (all handles end BEFORE the manifest exists)."""
        if not self.handles_closed():
            raise HandleStateError(
                {"reason": "manifest refused: own handles still open"})
        if self.manifest_path.exists():
            raise SpawnRefused({"reason": "manifest already exists",
                                "path": str(self.manifest_path)})
        files = {}
        for p in sorted(self.trial_dir.rglob("*")):
            if p.is_file() and not p.is_symlink():
                rel = p.relative_to(self.trial_dir).as_posix()
                files[rel] = {"sha256": sha256_fs_file(p),
                              "bytes": p.stat().st_size}
        doc = dict(payload)
        doc["stage"] = STAGE
        doc["session"] = SESSION
        doc["files"] = files
        doc["handles_closed_before_manifest"] = True
        with open(str(self.manifest_path), "xb") as fh:
            fh.write(lib.strict_json_bytes(doc))
        return {"manifest": str(self.manifest_path),
                "files": len(files)}


def close_session_and_collect_errors(session, cleanup_errors,
                                     quit_timeout_s=10.0):
    """F1/L1 shared finally-cleanup: stop the OWN child first (its death
    EOFs the IPC pipe and unblocks the reader thread), then join/close every
    handle. Never raises — problems land in cleanup_errors so the primary
    failure always wins; a handle that could not be closed is recorded, it
    is never reported as closed."""
    try:
        if session.proc is not None and session.proc.poll() is None:
            session.quit(timeout_s=quit_timeout_s)
        session.close()
    except Exception as exc:
        cleanup_errors.append(
            {"stage": "session_cleanup",
             "error": "%s: %s" % (type(exc).__name__, exc)})
    if not session.handles_closed():
        cleanup_errors.append(
            {"stage": "session_cleanup",
             "error": "own handles still open after cleanup (closed must "
                      "not be claimed while a handle lives)"})


def write_failure_manifest(session, status, primary, cleanup_errors,
                           extra=None):
    """Create-only best-effort failure manifest that preserves the PRIMARY
    exception AND every cleanup error (a failed run never leaves a
    clean-looking record, and the manifest write never masks the primary by
    raising). R3-4 honesty: on a failure path there is usually no analysed
    log, so gpu_started is NOT_ESTABLISHED — never a hardcoded false that
    could read as proof that no GPU work happened."""
    doc = {"result_status": status, "gpu_started": "NOT_ESTABLISHED",
           "gpu_started_basis": "failure path: no analysed real log",
           "primary_exception": (
               {"type": type(primary).__name__,
                "detail": str(primary)[:800]}
               if primary is not None else None),
           "cleanup_errors": list(cleanup_errors)}
    if extra:
        doc.update(extra)
    try:
        session.write_manifest(doc)
    except Exception as exc:
        cleanup_errors.append(
            {"stage": "failure_manifest",
             "error": "%s: %s" % (type(exc).__name__, exc)})
    return doc


# ---------------------------------------------------------------------------
# GPU pollution probe (read-only; own env/cwd cleaned; nobody is killed)
# ---------------------------------------------------------------------------


def probe_gpu_state(sandbox_env, cwd, nvidia_smi=None, run=subprocess.run,
                    timeout_s=SUBPROCESS_TIMEOUT_S):
    """Read-only nvidia-smi + other-mpv process scan. The query runs with the
    sandbox env and a TEMP cwd (both cleaned by construction); WDDM
    per-process numbers are known N/A and are never treated as 0. If the
    query source is missing, the report says so (unverifiable is recorded,
    never guessed)."""
    cwd = str(cwd)
    out = {"nvidia_smi_available": False, "gpu_samples": [],
           "other_mpv_processes": [], "note": "read-only probe; nobody is "
           "killed and nothing is locked"}
    smi = nvidia_smi or shutil.which("nvidia-smi")
    if smi is None:
        out["note"] += ("; nvidia-smi NOT FOUND: pollution gate is "
                        "unverifiable and must be reported as such")
        out["unverifiable"] = True
        return out
    cmd = [smi, "--query-gpu=memory.used,utilization.gpu,temperature.gpu,"
           "clocks.sm", "--format=csv,noheader,nounits"]
    proc = run(cmd, env=sandbox_env, cwd=cwd, capture_output=True,
               timeout=timeout_s)
    if proc.returncode != 0:
        out["unverifiable"] = True
        out["error"] = proc.stderr.decode("utf-8", "replace")[:200]
        return out
    out["nvidia_smi_available"] = True
    for line in proc.stdout.decode("utf-8", "replace").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            sample = {}
            for key, raw in zip(("memory_used_mib", "util_pct",
                                 "temp_c", "clocks_sm_mhz"), parts):
                try:
                    sample[key] = float(raw)   # 'N/A' WDDM rows stay strings
                except ValueError:
                    sample[key] = raw
            out["gpu_samples"].append(sample)
    scan = run(["tasklist", "/FI", "IMAGENAME eq mpv.exe", "/FO", "CSV",
                "/NH"], env=sandbox_env, cwd=cwd, capture_output=True,
               timeout=timeout_s)
    for line in scan.stdout.decode("utf-8", "replace").splitlines():
        if not line.strip().startswith('"'):
            continue
        cells = next(iter(csv.reader([line])))
        if len(cells) >= 2 and cells[0].lower() == "mpv.exe":
            out["other_mpv_processes"].append({"pid": cells[1],
                                               "name": cells[0]})
    return out


def pollution_decision(gpu_report, own_pids=(), consec_s=POLLUTION_CONSECUTIVE_S,
                       memory_max=POLLUTION_MEMORY_USED_MIB_MAX,
                       util_max=POLLUTION_UTIL_PCT_MAX):
    """Preregistered gate: full-GPU memory.used > 1500 MiB or util > 10%
    (sustained `consec_s`, excluding own mpv PIDs) or a foreign mpv.exe ->
    blocked with reasons. N/A fields are disclosed, not coerced to 0."""
    reasons = []
    if gpu_report.get("unverifiable"):
        reasons.append("pollution observation source unverifiable "
                       "(recorded, never guessed)")
    for sample in gpu_report.get("gpu_samples", []):
        mem = sample.get("memory_used_mib")
        if isinstance(mem, (int, float)) and mem > memory_max:
            reasons.append("memory.used %.0f MiB > %.0f MiB gate"
                           % (mem, memory_max))
    for proc_row in gpu_report.get("other_mpv_processes", []):
        if str(proc_row.get("pid")) not in {str(p) for p in own_pids}:
            reasons.append("foreign mpv.exe PID %s present (never killed; "
                           "run refused/pending)" % proc_row.get("pid"))
    return {"blocked": bool(reasons), "reasons": reasons,
            "sustained_window_s": consec_s,
            "note": "WDDM per-process N/A is not 0; util gate needs the "
                    "sustained window from consecutive probes"}


# ---------------------------------------------------------------------------
# Warmup + timed window loops (pure scheduling; injected clock/sleep)
# ---------------------------------------------------------------------------


def _stabilization_view(payload):
    """Normalise one poll to the raw-reply view (vop/osd/vo_passes/time_pos/
    epoch). Accepts BOTH a raw sampler reply AND a mapped snapshot
    (payload_to_snapshot output) — the timed entry feeds mapped snapshots,
    and a shape mismatch here had silently made stabilisation impossible
    (latent B2 failure, fixed with F1)."""
    if not isinstance(payload, dict):
        return {}
    if "vop" in payload or "time_pos" in payload:
        return payload
    passes = payload.get("vo_passes") or {}
    view_passes = {}
    for kind, nodes in passes.items():
        view_nodes = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            view_nodes.append({"desc": node.get("desc"),
                               "last": node.get("last_ns"),
                               "avg": node.get("avg_ns"),
                               "peak": node.get("peak_ns"),
                               "samples": node.get("samples_ns")})
        view_passes[kind] = view_nodes
    return {"vop": payload.get("video_out_params") or {},
            "osd": payload.get("osd_dimensions") or {},
            "vo_passes": view_passes,
            "time_pos": payload.get("time_pos_s"),
            "epoch": payload.get("epoch")}


def stabilization_criteria(prev_payload, cur_payload, temp_drift_c=None):
    """Preregistered warmup criteria for ONE consecutive pair (plan
    warmup_stabilization_criterion; GPU temp drift <=2C is criterion 5 and
    only evaluable when a temperature observation exists — unavailability is
    disclosed, never treated as pass or block by itself)."""
    prev_payload = _stabilization_view(prev_payload)
    cur_payload = _stabilization_view(cur_payload)
    checks = {}
    def table_of(payload):
        vp = (payload or {}).get("vo_passes") or {}
        return [p.get("desc") for p in (vp.get("fresh") or [])]
    def timings_ok(payload):
        vp = (payload or {}).get("vo_passes") or {}
        fresh = vp.get("fresh") or []
        if not fresh:
            return False
        for node in fresh:
            for key in ("last", "avg", "peak"):
                v = node.get(key)
                if not isinstance(v, (int, float)) or isinstance(v, bool) \
                        or v <= 0:
                    return False
            samples = node.get("samples")
            if not isinstance(samples, list) or not samples:
                return False
        return True
    checks["pass_desc_identical"] = (prev_payload is not None
                                     and table_of(prev_payload)
                                     == table_of(cur_payload)
                                     and len(table_of(cur_payload)) > 0)
    checks["timings_strong"] = timings_ok(cur_payload)
    if prev_payload and cur_payload:
        pv_prev = prev_payload.get("vop") or {}
        pv_cur = cur_payload.get("vop") or {}
        keys = ("w", "h", "dw", "dh", "pixelformat")
        checks["render_state_stable"] = all(
            pv_prev.get(k) == pv_cur.get(k) for k in keys) and bool(
            pv_cur.get("pixelformat"))
    else:
        checks["render_state_stable"] = False
    t_prev = (prev_payload or {}).get("time_pos")
    t_cur = (cur_payload or {}).get("time_pos")
    checks["time_pos_advancing"] = (
        isinstance(t_prev, (int, float)) and isinstance(t_cur, (int, float))
        and t_cur > t_prev)
    checks["epoch_stable"] = (
        (prev_payload or {}).get("epoch") == (cur_payload or {}).get("epoch"))
    if temp_drift_c is None:
        checks["gpu_temp"] = None    # disclosed unavailability
        checks["all_ok"] = all(v is True for k, v in checks.items()
                               if k != "gpu_temp")
    else:
        checks["gpu_temp"] = abs(temp_drift_c) <= 2.0
        checks["all_ok"] = all(v is True for v in checks.values())
    return checks


def run_warmup_loop(sample_fn, clock=time.monotonic, sleep=time.sleep,
                    min_s=None, max_s=None, poll_s=None,
                    min_consecutive=None, temp_probe_fn=None):
    """10..15 s stabilisation with the consecutive-poll rule. Returns
    {stabilized, warmup_end_monotonic_s, polls, disclosures}. `sample_fn` is
    called with no args and returns a payload dict (or raises: a failed poll
    is recorded and retried while the budget lasts — never fabricated)."""
    budget = lib.SAMPLING_BUDGET
    min_s = budget["warmup_min_s"] if min_s is None else min_s
    max_s = budget["warmup_max_s"] if max_s is None else max_s
    poll_s = budget["poll_period_s"] if poll_s is None else poll_s
    min_consecutive = (lib.WARMUP_MIN_CONSECUTIVE_POLLS
                       if min_consecutive is None else min_consecutive)
    polls = []
    disclosures = ([] if temp_probe_fn is not None
                   else ["temp_unavailable"])
    consecutive = 0
    prev = None
    stabilized = False
    warmup_end = None
    start = clock()
    while clock() - start < max_s:
        step_start = clock()
        if clock() - start >= min_s:
            try:
                cur = sample_fn()
            except CollectError as exc:
                polls.append({"t": clock() - start, "error": str(exc)})
                cur = None
            if cur is not None:
                drift = temp_probe_fn() if temp_probe_fn else None
                checks = stabilization_criteria(prev, cur, temp_drift_c=drift)
                consecutive = consecutive + 1 if checks["all_ok"] else 0
                polls.append({"t": clock() - start, "checks": checks,
                              "consecutive": consecutive})
                if consecutive >= min_consecutive:
                    stabilized = True
                    warmup_end = clock()
                    break
                prev = cur
            else:
                prev = None
                consecutive = 0
        else:
            polls.append({"t": clock() - start, "note": "below min warmup"})
            prev = None
            consecutive = 0
        elapsed = clock() - step_start
        if elapsed < poll_s:
            sleep(poll_s - elapsed)
    return {"stabilized": stabilized,
            "warmup_end_monotonic_s": warmup_end,
            "polls": polls, "disclosures": disclosures,
            "budget_s": {"min": min_s, "max": max_s, "poll": poll_s,
                         "min_consecutive": min_consecutive}}


def slot_targets(warmup_end, n=lib.SAMPLING_BUDGET["window_target_samples"],
                 period_s=None):
    """Preregistered slot schedule: warmup_end + k*1.0 s (k=0..9)."""
    period = lib.SAMPLING_BUDGET["poll_period_s"] if period_s is None \
        else period_s
    return [warmup_end + k * period for k in range(n)]


def run_window_slots(sample_fn, warmup_end, clock=time.monotonic,
                     sleep=time.sleep, start_index=0, deadline=None,
                     n=lib.SAMPLING_BUDGET["window_target_samples"],
                     period_s=None, slot_slack_s=0.02):
    """1 Hz atomic sampling with the ACTUAL wall recorded per slot. A late
    slot is recorded as-is (never re-timed/interpolated); the analysis owns
    the +/-0.25s schedule verdict. If `deadline` would be exceeded the loop
    stops honestly (truncated window -> analysis rejection, raw kept)."""
    period = lib.SAMPLING_BUDGET["poll_period_s"] if period_s is None \
        else period_s
    collected = []
    for k, target in enumerate(slot_targets(warmup_end, n, period_s)):
        now = clock()
        if now < target - slot_slack_s:
            sleep(target - slot_slack_s - now)
        if deadline is not None and clock() > deadline:
            break
        payload = sample_fn()
        # the ACTUAL wall is recorded when the sample was received (after
        # the atomic reply) — a slow reply is honestly late, never re-timed
        actual = clock()
        collected.append({"slot": k, "target_s": target, "actual_s": actual,
                          "snapshot_index": start_index + k,
                          "payload": payload})
        nxt = target + period
        remain = nxt - clock()
        if k < n - 1 and remain > 0:
            sleep(remain)
    return collected


# ---------------------------------------------------------------------------
# Arm config assembly + HQ-common binding
# ---------------------------------------------------------------------------

REPO_CFG_ASSETS = {
    "scripts/scale-selector.lua": "p4-scripts/scale-selector.lua",
    "script-opts/scale-selector.conf": "script-opts/scale-selector.conf",
    "script-opts/scale-selector-gears.conf":
        "script-opts/scale-selector-gears.conf",
}
SHADER_DIRS = ("shaders",)


def assemble_arm_config(layout, repo_root=None, rife=False):
    """Shared base config for every arm (profile high-quality + fixed
    non-algorithm lines) + product plugin/conf assets + (only for the on
    stratum) the preregistered RIFE engagement line with the relocated vpy.
    The Anime4K chain is the plugin's stock Mode A; off NEVER stacks an
    algorithm chain. Returns {files:{rel:bytes}, hq_common_sha256}."""
    root = Path(repo_root) if repo_root is not None else lib.workspace_root()
    cfg = Path(layout["cfg"])
    files = {}
    base = HQ_COMMON_TEMPLATE + (RIFE_ENGAGEMENT_LINE if rife else "")
    files["mpv.conf"] = base.encode("utf-8")
    for repo_rel, sbx_rel in sorted(REPO_CFG_ASSETS.items()):
        src = root / repo_rel
        if not src.is_file():
            raise PreflightBlocked({"gate": "config_assets",
                                    "reason": "product asset missing",
                                    "path": repo_rel})
        files[sbx_rel] = src.read_bytes()
    for rel, data in files.items():
        target = cfg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise SpawnRefused({"reason": "config target exists",
                                "path": str(target)})
        with open(str(target), "xb") as fh:
            fh.write(data)
    # shader resources: byte copies of every repo shader into the sandbox cfg
    for d in SHADER_DIRS:
        src_dir = root / d
        if not src_dir.is_dir():
            continue
        for cur, dirs, names in os.walk(str(src_dir)):
            cur_p = Path(cur)
            for name in sorted(names):
                p = cur_p / name
                if _is_reparse(p):
                    raise PreflightBlocked(
                        {"gate": "config_assets",
                         "reason": "reparse component in shader tree",
                         "path": str(p)})
                rel = Path(d).joinpath(p.relative_to(src_dir)).as_posix()
                data = p.read_bytes()
                target = cfg / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise SpawnRefused({"reason": "shader target exists",
                                        "path": str(target)})
                with open(str(target), "xb") as fh:
                    fh.write(data)
                files[rel] = data
    binding = compute_hq_common_sha256(files)
    return {"files": sorted(files), "hq_common_sha256": binding,
            "rife_line_present": rife}


def compute_hq_common_sha256(config_files):
    """sha256 over the canonical sorted (rel, bytes) of the SHARED config —
    identical for every arm of a cell (the RIFE engagement line is the
    stratum variable and is excluded from this common binding; its presence
    is bound by spec.rife + the trial manifest)."""
    h = hashlib.sha256()
    for rel in sorted(config_files):
        if rel == "mpv.conf":
            body = HQ_COMMON_TEMPLATE.encode("utf-8")   # stratum line excluded
        else:
            body = config_files[rel]
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(lib.sha256_bytes(body).encode("ascii"))
        h.update(b"\x00")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Product IPC arm switching (real menu protocol, no invented message names)
# ---------------------------------------------------------------------------


def select_arm_via_menu(session, arm, deadline=None):
    """Switch the unique main chain through the REAL product protocol: F8
    menu -> navigate to the gear -> Enter, then verify via the plugin's own
    user-data export (user-data/scale-selector/gear + chain_epoch bump). The
    message names/keys come from scripts/scale-selector.lua (read-only prior
    handoff) — none are invented here. Every IPC command runs inside the
    trial wall budget when a deadline is given."""
    gear = ARM_GEAR_IDS.get(arm)
    if gear is None:
        raise CollectError({"reason": "no product gear mapping for arm",
                            "arm": arm})
    def remaining_s():
        if deadline is None:
            return None
        return max(0.05, deadline - time.monotonic())
    def ud(key):
        return session.get_property("user-data/scale-selector/" + key,
                                    timeout_s=remaining_s())
    if ud("menu_open") is not True:
        session.ipc.cmd("keypress", "F8", timeout_s=remaining_s())
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if ud("menu_open") is True:
                break
            time.sleep(0.1)
        else:
            return {"ok": False, "reason": "menu did not open"}
    entries = ud("menu_entries") or []
    target_idx = None
    for i, entry in enumerate(entries):
        if entry.get("id") == gear and entry.get("enabled"):
            target_idx = i
            break
    if target_idx is None:
        return {"ok": False, "reason": "gear not enabled/absent",
                "gear": gear}
    def selected_idx():
        for i, entry in enumerate(ud("menu_entries") or []):
            if entry.get("selected"):
                return i
        return None
    guard = 0
    while selected_idx() != target_idx and guard <= len(entries) + 1:
        cur = selected_idx()
        session.ipc.cmd("keypress", "DOWN" if (target_idx > (cur or 0))
                        else "UP", timeout_s=remaining_s())
        guard += 1
    epoch_before = ud("chain_epoch")
    session.ipc.cmd("keypress", "ENTER", timeout_s=remaining_s())
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if ud("gear") == gear and ud("chain_epoch") != epoch_before:
            return {"ok": True, "gear": gear,
                    "chain_epoch": ud("chain_epoch"),
                    "chain_verified": ud("chain_verified")}
        time.sleep(0.1)
    return {"ok": False, "reason": "gear activation not confirmed",
            "gear": gear, "observed_gear": ud("gear")}


# ---------------------------------------------------------------------------
# Record assembly + N1 gate wiring
# ---------------------------------------------------------------------------


def build_run_record(spec, snapshots, window, hq_common_sha256,
                     observed_output_fps=None, media_sha256=None,
                     drop_affected=None, run_id=None, note=None,
                     fps_provenance=None):
    """Assemble and strictly validate one p4-run-record-v2. observed fps is
    included ONLY when actually observed (a missing field stays missing and
    is honestly rejected as REJECTED_FPS_UNBOUND by the analyzer)."""
    import p4_analyze as an
    record = {
        "schema": an.RUN_RECORD_SCHEMA,
        "run_id": run_id or ("%s|%s|r%d" % (spec["cell"], spec["run_kind"],
                                            spec["repeat_index"])),
        "spec": dict(spec),
        "window": {"start_snapshot_index": int(window["start_snapshot_index"]),
                   "sample_count": int(window["sample_count"]),
                   "warmup_end_monotonic_s":
                       float(window["warmup_end_monotonic_s"])},
        "snapshots": list(snapshots),
        "config_binding": {"hq_common_sha256":
                           lib.require_sha256_hex(hq_common_sha256,
                                                  "hq_common_sha256")},
    }
    if observed_output_fps is not None:
        record["observed_output_fps"] = observed_output_fps
    if drop_affected is not None:
        record["drop_affected"] = lib.require_bool(drop_affected,
                                                   "drop_affected")
    if note is not None:
        record["note"] = str(note)
    if fps_provenance is not None:
        record["note"] = ((record.get("note") or "") +
                          " fps_provenance: " + str(fps_provenance)).strip()
    if media_sha256 is not None:
        # source blocks inside snapshots were filled at collection time from
        # the actually played file; cross-check the record builder's copy
        for snap in record["snapshots"]:
            src = snap.get("source")
            if src is not None and src.get("media_sha256") is not None:
                if src["media_sha256"] != media_sha256:
                    raise lib.ValueContractError(
                        "snapshot media hash != played media hash")
    an.validate_run_record(record)
    return record


def n1_gate_wiring(record, pngs=None, root=None):
    """N1 collector wiring: the strict path, not the loose stage gate.
    Calls lib.verify_required_inputs (media manifest MUST exist on disk) AND
    ce.gate_run_evidence (full re-analysis + evidence gates). Raises /
    returns structured violations honestly — never a fabricated pass."""
    import p4_analyze as an
    import p4_check_evidence as ce
    spec = an.validate_run_record(record)
    lib.verify_required_inputs(spec, root)      # MissingInputError if absent
    gate = ce.gate_run_evidence(record, pngs=pngs, root=root)
    return gate


# ---------------------------------------------------------------------------
# Identity probe (short first-load sample; vo=image; NOT gpu-next)
# ---------------------------------------------------------------------------

IDENTITY_PROBE_LOG_MARKERS = {
    "vapoursynth": re.compile(r"vapoursynth|vsscript|vf_vapoursynth", re.I),
    "rife": re.compile(r"rife", re.I),
    "model_name": re.compile(r"model[^,\n]*rife[-_ ]?v", re.I),
    "error": re.compile(r"error|failed|fatal|could not", re.I),
}


def parse_identity_log(text):
    """What the first-load log can honestly prove. The model name is only
    'established' when a log line actually names it; a unique model dir +
    hashes alone prove WHICH model dir was cloned, never the model=70 index
    mapping — that stays NOT_ESTABLISHED (no invented log lines).

    R3-3: the verdict additionally reads the EFFECTIVE vf chain straight
    from the log (the [vf] User filter list block) and GPU-init evidence —
    an engagement line that only exists as an argv/config string, a
    passthrough chain, or a build-info feature list never count as proof."""
    found = {k: [] for k in IDENTITY_PROBE_LOG_MARKERS}
    chain_lines = []
    in_chain_block = False
    gpu_lines = []
    for line in text.splitlines():
        for key, rx in IDENTITY_PROBE_LOG_MARKERS.items():
            if rx.search(line):
                found[key].append(line.strip()[:300])
        if _IDENTITY_CHAIN_HEAD.search(line):
            in_chain_block = True
            chain_lines.append(line.strip()[:300])
            continue
        if in_chain_block:
            if _IDENTITY_VF_LINE.search(line):
                chain_lines.append(line.strip()[:300])
            else:
                in_chain_block = False
        if _GPU_INIT_MARKER.search(line):
            gpu_lines.append(line.strip()[:300])
    chain_block = chain_lines[1:] if chain_lines else []
    if not chain_lines:
        chain_state = "NOT_ESTABLISHED"
    elif any(_IDENTITY_CHAIN_ENGAGED.search(l) for l in chain_block):
        chain_state = "ENGAGED"
    else:
        chain_state = "NOT_IN_CHAIN"
    model_named = bool(found["model_name"])
    return {
        "vs_load_evidence": found["vapoursynth"][:10],
        "rife_load_evidence": found["rife"][:10],
        "error_lines": found["error"][:10],
        "effective_vf_chain": {
            "state": chain_state,
            "evidence_lines": chain_lines[:12],
            "note": ("no User filter list block in the real log"
                     if chain_state == "NOT_ESTABLISHED" else
                     "effective chain from the real log; an argv/config "
                     "string alone is never chain evidence"),
        },
        "gpu_init_evidence": gpu_lines[:10],
        "model_identity": ("NAMED_IN_LOG" if model_named
                           else "NOT_ESTABLISHED"),
        "model_identity_note": (
            "log names the model" if model_named else
            "plugin did not print a model name; only the unique selected "
            "model dir hash + successful initialisation can be claimed; "
            "the model=70 index mapping is NOT_ESTABLISHED"),
    }


def build_identity_probe_config(cfg_dir, relocated_vpy_path):
    """vo=image probe config: the engagement chain with the RELOCATED vpy.
    vo=image intentionally does NOT exercise gpu-next shaders — it exists to
    anchor filter-output frames only (never PIC A/B, never vo GPU timing)."""
    cfg = Path(cfg_dir)
    conf = cfg / "mpv.conf"
    if conf.exists():
        raise SpawnRefused({"reason": "probe config exists",
                            "path": str(conf)})
    text = (
        "vo=image\n"
        "vo-image-format=png\n"
        "ao=null\n"
        "mute=yes\n"
        "untimed=yes\n"
        "framedrop=no\n"
        + RIFE_ENGAGEMENT_LINE.replace("~~/rife/rife.vpy",
                                       str(Path(relocated_vpy_path))
                                       .replace("\\", "/"))
    )
    with open(str(conf), "xb") as fh:
        fh.write(text.encode("utf-8"))
    return {"path": str(conf), "sha256": lib.sha256_bytes(
        text.encode("utf-8"))}


# Preregistered noncopy negative control (approved plan): the mean abs diff
# between an M frame and BOTH neighbouring S frames must exceed 2/255 of
# full scale. p3_lib.pixel16 returns raw 0..255 values for 8-bit PNGs, so
# the threshold in raw units is 2.0 (never compared against the fraction).
_NONCOPY_THRESHOLD_RAW = 2.0


def decode_identity_frames(png_paths, expected_s_count=None):
    """Noncopy/nonblend negative controls on the vo=image output, using the
    real prior-handoff PNG decoder (p3_lib, read-only). Frames are classified
    by lib.rife_output_frame_class parity semantics; MAE is computed between
    each M and its two neighbouring S frames (preregistered noncopy
    threshold: mean abs diff > 2/255).

    R3-5 honesty: the frame-uniqueness result is named all_frames_unique —
    it proves only "no bitwise-duplicate output frame", NEVER "not a
    blend". The actual 50% blend difference (M vs the pixelwise mean of its
    two neighbouring S frames) is COMPUTED and preserved as a distribution;
    the plan preregisters no numeric blend threshold, so the blend
    judgement stays NOT_ESTABLISHED instead of inventing one. Nothing here
    claims a RIFE PASS."""
    import p3_lib  # read-only reuse of the frozen decoder
    if not png_paths:
        raise SamplingPayloadError({"reason": "no probe frames decoded"})
    hashes = []
    decoded = []
    for p in png_paths:
        data = Path(p).read_bytes()
        hashes.append(lib.sha256_bytes(data))
        decoded.append(p3_lib.decode_png(data))
    w, h = decoded[0]["w"], decoded[0]["h"]
    def gray_mean_abs(d1, d2):
        total = 0
        n = 0
        step_y = max(1, h // 270)
        step_x = max(1, w // 480)
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                p1 = d1["pixel16"](x, y)
                p2 = d2["pixel16"](x, y)
                total += abs(p1[0] - p2[0]) + abs(p1[1] - p2[1]) \
                    + abs(p1[2] - p2[2])
                n += 3
        return total / n
    def blend_diff(mid, s1, s2):
        """Distribution of |M - 0.5*(S1+S2)| over the sampled RGB grid —
        what a pure 50% blend of the neighbours would predict vs the actual
        M frame. No threshold is applied (none is preregistered)."""
        errs = []
        step_y = max(1, h // 270)
        step_x = max(1, w // 480)
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                pm = mid["pixel16"](x, y)
                p1 = s1["pixel16"](x, y)
                p2 = s2["pixel16"](x, y)
                for c in range(3):
                    errs.append(abs(pm[c] - (p1[c] + p2[c]) / 2.0))
        errs.sort()
        def pct(q):
            return errs[min(len(errs) - 1,
                            int(round(q * (len(errs) - 1))))]
        return {"samples": len(errs), "mean": sum(errs) / len(errs),
                "p50": pct(0.50), "p95": pct(0.95), "max": errs[-1],
                "unit": "8-bit code values (0..255)"}
    mae = []
    blend_rows = []
    duplicates = []
    for i in range(len(decoded)):
        cls = lib.rife_output_frame_class(i)
        if cls == "M":
            # the two neighbouring S frames of M at odd i are i-1 and i+1
            neighbours = [i - 1] + ([i + 1] if i + 1 < len(decoded) else [])
            row = {"frame": i, "frame_class": cls}
            for n_idx in neighbours:
                row["mae_vs_s%d" % n_idx] = gray_mean_abs(decoded[i],
                                                          decoded[n_idx])
            row["noncopy_gt_2over255"] = all(
                row["mae_vs_s%d" % n_idx] > _NONCOPY_THRESHOLD_RAW
                for n_idx in neighbours)
            mae.append(row)
            if len(neighbours) == 2:
                blend_rows.append({"frame": i,
                                   **blend_diff(decoded[i],
                                                decoded[neighbours[0]],
                                                decoded[neighbours[1]])})
            else:
                blend_rows.append({
                    "frame": i, "samples": 0, "mean": None, "p50": None,
                    "p95": None, "max": None,
                    "note": "tail M frame has a single S neighbour; a 50% "
                            "blend needs two, diff not computable"})
            first_at = hashes.index(hashes[i])
            if first_at != i:
                duplicates.append({"frame": i, "identical_to_frame": first_at})
    return {
        "frames": len(decoded), "width": w, "height": h,
        "frame_sha256": hashes,
        "mae_noncopy": mae,
        "duplicate_frames": duplicates,
        "noncopy_all_pass": bool(mae) and all(m["noncopy_gt_2over255"]
                                              for m in mae),
        # R3-5: honest name — this is ONLY uniqueness of output frames
        "all_frames_unique": not duplicates,
        "blend_check": {
            "per_frame": blend_rows,
            "judgement": "NOT_ESTABLISHED",
            "judgement_note": "the plan preregisters the noncopy MAE>2/255 "
                              "control and the bitwise duplicate control; "
                              "it defines NO numeric threshold for 50% "
                              "blend similarity, so nothing is declared "
                              "pass/fail here — the distribution is "
                              "preserved for the reviewer",
        },
        "parity_note": "S/M classification assumes the survey Interleave "
                       "semantics (even=S odd=M); if the output tail/frame "
                       "count cannot anchor that assumption the identity "
                       "stays NOT_ESTABLISHED",
        "threshold_note": "noncopy threshold 2/255 is preregistered in the "
                          "approved plan; CPU-linearity gating is abolished; "
                          "blend similarity has NO preregistered threshold "
                          "and stays NOT_ESTABLISHED",
    }


# R3-3: output files are classified by ACTUAL magic bytes, never by
# extension (a JPEG from an unloaded vo-image-format must be stated, not
# silently globbed away by a *.png pattern).
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


def read_real_log(log_fs):
    """R3-3: read the UNIQUE actual log path AFTER the process ended and
    every handle is closed. present/bytes/sha256 are measured facts — a
    missing or empty log is reported as such and can never back a green
    verdict (the old code parsed runs/identity/mpv.log, a file mpv never
    wrote, and called rc0 an initialization)."""
    log_fs = Path(log_fs)
    if not log_fs.is_file():
        return {"path": str(log_fs), "present": False, "bytes": 0,
                "sha256": None, "text": ""}
    data = log_fs.read_bytes()
    return {"path": str(log_fs), "present": True, "bytes": len(data),
            "sha256": lib.sha256_bytes(data),
            "text": data.decode("utf-8", "replace")}


def classify_output_images(outdir):
    """Magic-byte classification of every file the probe wrote: png / jpeg
    / other. The returned note states a format mismatch explicitly instead
    of letting a *.png glob report an empty frame table as success."""
    outdir = Path(outdir)
    pngs, jpegs, other = [], [], []
    if outdir.is_dir():
        for p in sorted(outdir.iterdir()):
            if not p.is_file() or p.is_symlink():
                continue
            with open(str(p), "rb") as fh:
                head = fh.read(8)
            if head.startswith(PNG_MAGIC):
                pngs.append(p)
            elif head.startswith(JPEG_MAGIC):
                jpegs.append(p.name)
            else:
                other.append(p.name)
    note = "ok: all output files are real PNGs"
    if jpegs or other:
        note = ("FORMAT MISMATCH: non-PNG output present (jpeg=%d, "
                "other=%d) — the configured format did not fully apply; "
                "this is stated, never treated as success"
                % (len(jpegs), len(other)))
    return {"png": pngs, "jpeg": jpegs, "other": other, "note": note}


def gpu_started_from_log(log_report, log_analysis):
    """R3-4: gpu_started strictly from real evidence. Unknown (missing or
    empty log) is NOT_ESTABLISHED — never a hardcoded false; a GPU init
    line in the REAL log is true; otherwise (real, parsed, non-empty log
    with zero GPU-init lines) it is false with the basis recorded. A config
    line or an argv string never makes this true."""
    if not log_report["present"] or log_report["bytes"] == 0:
        return "NOT_ESTABLISHED", "real log missing or empty; no GPU claim "
    if log_analysis["gpu_init_evidence"]:
        return True, "GPU-init lines present in the real parsed log"
    return False, ("real log present and parsed; zero GPU-init lines "
                   "(device/adapter/context/hwdec)")


def run_identity_probe(sandbox_root, trial_dir=None, fps=24, repo_root=None,
                       vs_src=None, rife_src=None, mpv_exe=None,
                       spawn=None, clock=time.monotonic, sleep=time.sleep,
                       temp_base=None):
    """Executable identity-probe entry (first isolated RIFE load on the
    short sample). The writer did NOT run it; the independent read-only
    executor does. Honest outputs only: identity NOT_ESTABLISHED when the
    log cannot prove it; BLOCKED_ENV on any zero-write/pin failure.

    R3-2: the sandbox mpv.conf (vo=image, PNG format, RIFE engagement line)
    is REALLY loaded (--config-dir is the only config root; --no-config is
    never emitted); no Lua script is auto-scanned (probe loads none).
    R3-3: the verdict reads the UNIQUE actual log (runs/<trial>/identity.log
    — the same path given to --log-file), hashed after close, and gates on
    the effective vf chain from that log; missing/empty/wrong log, rc0
    alone, an argv-only vf string, or a passthrough chain are never
    EVIDENCED. R3-4: final witness/log analysis/hash/manifest happen only
    after process end AND closed handles (timeout included); gpu_started
    follows the log evidence, never a hardcoded flag.

    F1: the session trial dir is created create-only BEFORE the session is
    constructed; EVERY path (EXITED, TIMEOUT, start failure, proof-stage or
    witness exception) finally-closes the own process + IPC/console/log
    handles and only then hashes/writes the manifest. The primary exception
    and every cleanup error are preserved; a failed run never leaves a
    clean-looking manifest and never reports open handles as closed.

    F3: an explicit trial_dir is honoured ONLY as a NEW create-only child
    inside the sandbox runs dir (never outside, never an existing dir)."""
    pre = preflight_collect("identity-probe",
                            sandbox_parent=Path(sandbox_root).parent,
                            root=repo_root)
    layout = create_sandbox(sandbox_root, temp_base=temp_base)
    deadline = clock() + IDENTITY_PROBE_WALL_S
    protected = []
    for label, tree in (("vs", VS_TREE_DEFAULT),
                        ("rife", RIFE_DIR_DEFAULT)):
        if tree.is_dir():
            protected.append((label, tree, tree_inventory(tree)))
    appdata = _resolve_active_appdata() / "mpv"
    protected.append(("active_mpv_config", appdata,
                      tree_inventory(appdata)))
    clone_manifest = clone_runtime(sandbox_root, vs_src=vs_src,
                                   rife_src=rife_src, mpv_exe=mpv_exe)
    vpy_fs = resolve_active_vpy()
    relocation = relocate_vpy(vpy_fs.read_bytes(),
                              layout["clone_rife"] / RIFE_DLL_REL,
                              expected_sha256=ACTIVE_VPY_SHA256)
    vpy_target = layout["vpy"] / "rife.vpy"
    with open(str(vpy_target), "xb") as fh:
        fh.write(relocation["relocated_bytes"])
    sample_path = layout["media"] / ("identity-%d.y4m" % fps)
    sample_record = write_identity_sample_y4m(sample_path, fps)
    verify_identity_sample_y4m(sample_path, fps)
    probe_cfg = build_identity_probe_config(layout["cfg"], vpy_target)
    install_sampler_script(layout["cfg"])   # present but NOT loaded by the
    # probe: scripts are explicit (R3-2), the probe loads none by design.
    outdir = layout["runs"] / "identity-frames"
    outdir.mkdir()
    env = build_subprocess_env(layout, vs_root=layout["clone_vs"])
    assert_env_has_no_credentials(env)
    runs_root = layout["runs"].resolve()
    if trial_dir is None:
        trial_fs = layout["runs"] / "identity"
    else:
        trial_fs = Path(trial_dir)
        if ".." in trial_fs.parts:
            raise SpawnRefused(
                {"reason": "trial dir must not contain '..' aliases (F3: "
                           "create-only child of the sandbox runs dir)",
                 "trial_dir": str(trial_fs)})
        trial_res = _resolved(trial_fs)
        if trial_res == runs_root or not _path_contains(runs_root, trial_res):
            raise SpawnRefused(
                {"reason": "trial dir must be a NEW create-only child "
                           "INSIDE the sandbox runs dir (F3; outside/parent "
                           "targets are refused)",
                 "trial_dir": str(trial_fs), "runs_root": str(runs_root)})
    session_dir = ensure_fresh_trial_dir(trial_fs)   # F1: create-only BEFORE CollectSession
    # R3-3: ONE unique actual log path — given to --log-file AND to the
    # session (create-only check), read back only after close.
    log_fs = session_dir / "identity.log"
    args = build_mpv_launch_args(
        layout["cfg"], None, log_fs,
        vo="image", extra_args=(
            "--vo-image-outdir=%s" % outdir,),
        media=sample_path, mpv_exe=mpv_exe, scripts=())
    launch_record = {
        "config_dir": str(layout["cfg"]),
        "mpv_conf_sha256": probe_cfg["sha256"],
        "no_config_flag": False,
        "explicit_scripts": [],
        "auto_script_scan": "cfg/scripts stays empty — every user script "
                           "is an explicit --script entry from cfg/p4-"
                           "scripts; mpv builtin scripts load as part of "
                           "the product environment",
        "log_file": str(log_fs),
    }
    session = CollectSession(session_dir, args,
                             pipe_name=None, env=env,
                             cwd=str(layout["temp"]), spawn=spawn,
                             log_name="identity.log")
    status = "ERROR"
    primary = None
    cleanup_errors = []
    result = None
    try:
        session.start(connect_ipc=False)
        try:
            session.exit_code = session.proc.wait(
                timeout=max(1.0, deadline - clock()))
        except subprocess.TimeoutExpired:
            session.killed_by_tool = True
            status = "TIMEOUT"
        else:
            status = "EXITED"
    except BaseException as exc:
        primary = exc
        raise
    finally:
        # R3-4: process end AND closed handles happen BEFORE any final
        # witness/log analysis/hash/manifest (timeout included); the primary
        # exception and every cleanup error are preserved, and the failure
        # manifest is create-only.
        close_session_and_collect_errors(session, cleanup_errors)
        if primary is not None:
            write_failure_manifest(session, status, primary, cleanup_errors,
                                   extra={"mode": "identity-probe"})
    try:
        # ---- proof stage: ONLY now (process ended, handles closed) ----
        log_report = read_real_log(log_fs)
        log_analysis = parse_identity_log(log_report["text"])
        gpu_state, gpu_basis = gpu_started_from_log(log_report, log_analysis)
        outputs = classify_output_images(outdir)
        try:
            frame_report = decode_identity_frames(outputs["png"])
        except (SamplingPayloadError, ValueError, OSError) as exc:
            frame_report = {"frames": 0, "error": str(exc),
                            "status": (
                                "FORMAT_MISMATCH" if (outputs["jpeg"]
                                                      or outputs["other"])
                                else "NO_FRAMES_DECODED")}
        else:
            expected_frames = 2 * sample_record["frames"]
            dims_ok = (frame_report.get("width")
                       == sample_record["params"]["width"]
                       and frame_report.get("height")
                       == sample_record["params"]["height"])
            if outputs["jpeg"] or outputs["other"]:
                frame_status = "FORMAT_MISMATCH"
            elif frame_report.get("frames", 0) == 0:
                frame_status = "NO_FRAMES_DECODED"
            elif (frame_report.get("frames") == expected_frames
                    and dims_ok):
                frame_status = "EVIDENCED"
            else:
                frame_status = "COUNT_OR_DIMS_MISMATCH"
            frame_report["status"] = frame_status
            frame_report["expected_output_frames"] = expected_frames
            frame_report["expected_note"] = (
                "RIFE doubles the %d source frames (%d output at fps%d); "
                "a passthrough run emits only the %d source frames"
                % (sample_record["frames"], expected_frames, fps,
                   sample_record["frames"]))
        witness = []
        blocked = None
        for label, tree, before in protected:
            try:
                witness.append(zero_write_witness(
                    label, before, tree_inventory(tree)))
            except ZeroWriteViolation as exc:
                blocked = exc
        gates = {
            "exited_clean": (status == "EXITED"
                             and session.exit_code == 0),
            "real_log_present": (log_report["present"]
                                 and log_report["bytes"] > 0),
            "no_error_lines": not log_analysis["error_lines"],
            "effective_vf_engaged": (
                log_analysis["effective_vf_chain"]["state"] == "ENGAGED"),
        }
        initialization = ("EVIDENCED" if all(gates.values())
                          else "NOT_ESTABLISHED")
        result = {
            "mode": "identity-probe", "preflight": pre,
            "status": status, "exit_code": session.exit_code,
            "argv": list(session.exe_args),
            "launch": launch_record,
            "sample": {k: v for k, v in sample_record.items()
                       if k != "frame_y_sha256"},
            "sample_sha256": sample_record["sha256"],
            "relocation": relocation["record"],
            "clone_files": clone_manifest["vs"]["files"]
            + clone_manifest["rife"]["files"],
            "log": {k: v for k, v in log_report.items() if k != "text"},
            "log_analysis": log_analysis,
            "output_images": {
                "png": [str(p) for p in outputs["png"]],
                "jpeg": outputs["jpeg"], "other": outputs["other"],
                "note": outputs["note"]},
            "frame_report": frame_report,
            "gpu_started": gpu_state,
            "gpu_started_basis": gpu_basis,
            "zero_write_witness": witness,
            "trial_dir": str(session_dir),
            "wall_cap_s": IDENTITY_PROBE_WALL_S,
            "proof_stage_after_handles_closed": True,
            "verdict": {
                "initialization": initialization,
                "initialization_gates": gates,
                "model_identity": log_analysis["model_identity"],
                "frame_evidence": frame_report.get("status",
                                                   "NOT_ESTABLISHED"),
                "frame_rate_order": {
                    "status": "NOT_ESTABLISHED",
                    "note": "vo=image output carries no readable PTS; "
                            "the target fps is never reused as a measured "
                            "value (no synthetic PTS)"},
                "rife_01_pass_claimed": False,
                "note": "B2 may only establish real initialisation and "
                        "availability; a full RIFE-01 PASS stays with the "
                        "later four-piece review (never claimed here)",
            },
        }
        if blocked is not None:
            result["verdict"]["initialization"] = "BLOCKED_ENV"
            result["zero_write_violation"] = str(blocked)
    except BaseException as exc:
        primary = exc
        write_failure_manifest(session, status, primary, cleanup_errors,
                               extra={"mode": "identity-probe"})
        raise
    manifest_doc = {
        "mode": "identity-probe", "result_status": status,
        "sample_sha256": sample_record["sha256"],
        "model_identity": log_analysis["model_identity"],
        "initialization": result["verdict"]["initialization"],
        "gpu_started": gpu_state,
        "gpu_started_basis": gpu_basis,
        "log": result["log"],
        "cleanup_errors": cleanup_errors,
        "performance_data": "NONE (identity probe is not a "
                           "performance measurement)"}
    if result.get("zero_write_violation") is not None:
        manifest_doc["zero_write_violation"] = \
            result["zero_write_violation"]
    try:
        session.write_manifest(manifest_doc)
    except Exception as exc:
        cleanup_errors.append(
            {"stage": "manifest", "error": "%s: %s" %
             (type(exc).__name__, exc)})
    return result


# ---------------------------------------------------------------------------
# Pilot / capture (timed runs; production refused)
# ---------------------------------------------------------------------------


def run_timed_trial(sandbox_root, group, arm, rife, repeat_index,
                    run_kind="pilot", repo_root=None, vs_src=None,
                    rife_src=None, mpv_exe=None, spawn=None,
                    clock=time.monotonic, sleep=time.sleep, temp_probe_fn=None,
                    window=None, fullscreen=False, ipc_open_func=None,
                    temp_base=None):
    """Full timed pilot entry: preflight -> NEW sandbox -> runtime
    clone -> vpy relocation -> protected-tree witness -> shared arm config ->
    prepared-media N1 gate -> GPU pollution gate -> product-menu arm switch
    -> window geometry readback -> warmup -> 10 atomic 1 Hz slots ->
    run.jsonl -> validated record -> N1 wiring (lib.verify_required_inputs +
    ce.gate_run_evidence). Every precondition failure is structured
    (BLOCKED_ENV / SpawnRefused / MissingInputError); no threshold
    invention, no fabricated samples; only this trial's own PID is stopped.

    F5: run_kind='capture' is NOT_IMPLEMENTED at this revision (B3 wires
    real screenshots) and is refused BEFORE any spawn — a timing-only run
    must never pose as image evidence. A pilot reports the PNG four-piece
    identity as NOT_ESTABLISHED (it deliberately does not screenshot).

    F1: the trial session is finally-cleaned on EVERY path (the own process
    is stopped and IPC/console/log handles are closed before any manifest);
    the primary exception and every cleanup error are preserved in a
    create-only failure manifest."""
    if run_kind == "capture":
        raise CollectError(
            {"reason": "capture is NOT_IMPLEMENTED at this revision (B3 "
                       "wires real screenshot capture); a timing-only run "
                       "must not pose as image evidence (F5)",
             "status": "NOT_IMPLEMENTED", "run_kind": run_kind})
    if run_kind not in ("pilot", "calibration"):
        raise ProductionRefused(
            {"reason": "run_kind must be pilot/calibration at this "
                       "revision; capture is NOT_IMPLEMENTED and production "
                       "is locked (B4 not passed)",
             "run_kind": run_kind})
    pre = preflight_collect("pilot", sandbox_parent=Path(sandbox_root).parent,
                            root=repo_root)
    spec = lib.make_trial_spec(group, arm, rife, repeat_index,
                               run_kind=run_kind,
                               plan_sha256=lib.PLAN_SHA256)
    # N1 media gate BEFORE any clone/spawn: the timed clip must already be
    # prepared by prepare-media (the identity short sample is not a
    # substitute for a timed pilot clip)
    media_rel = "docs/验证/开发/p4-001/media/%s/media-manifest.json" \
        % spec["clip"]
    media_root = Path(repo_root) if repo_root is not None \
        else lib.workspace_root()
    media_manifest_fs = media_root / media_rel
    if not media_manifest_fs.is_file():
        raise lib.MissingInputError(
            "missing required input bindings: %s (run prepare-media first; "
            "the identity short sample is not a timed-pilot substitute)"
            % media_rel)
    media_manifest = lib.strict_json_loads(
        media_manifest_fs.read_bytes().decode("utf-8"), source=media_rel)
    media_sha = lib.require_sha256_hex(media_manifest.get("media_sha256"),
                                       "media-manifest.media_sha256")
    media_fs = media_manifest_fs.parent / (spec["clip"] + ".mkv")
    if not media_fs.is_file() or sha256_fs_file(media_fs) != media_sha:
        raise lib.MissingInputError(
            "media file missing or hash does not match the pinned manifest: "
            "%s" % media_rel)
    layout = create_sandbox(sandbox_root, temp_base=temp_base)
    deadline = clock() + PILOT_WALL_S
    protected = []
    for label, tree in (("vs", VS_TREE_DEFAULT), ("rife", RIFE_DIR_DEFAULT)):
        if tree.is_dir():
            protected.append((label, tree, tree_inventory(tree)))
    appdata = _resolve_active_appdata() / "mpv"
    protected.append(("active_mpv_config", appdata, tree_inventory(appdata)))
    clone_runtime(sandbox_root, vs_src=vs_src, rife_src=rife_src,
                  mpv_exe=mpv_exe)
    vpy_fs = resolve_active_vpy()
    relocation = relocate_vpy(vpy_fs.read_bytes(),
                              layout["clone_rife"] / RIFE_DLL_REL,
                              expected_sha256=ACTIVE_VPY_SHA256)
    vpy_target = layout["cfg"] / "rife" / "rife.vpy"
    vpy_target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(vpy_target), "xb") as fh:
        fh.write(relocation["relocated_bytes"])
    config = assemble_arm_config(layout, repo_root=repo_root,
                                 rife=(rife == "on"))
    sampler_binding = install_sampler_script(layout["cfg"])
    env = build_subprocess_env(layout, vs_root=layout["clone_vs"])
    assert_env_has_no_credentials(env)
    gpu = probe_gpu_state(env, layout["temp"])
    decision = pollution_decision(gpu)
    if decision["blocked"]:
        raise PreflightBlocked(
            {"gate": "gpu_pollution", "reasons": decision["reasons"],
             "note": "nobody was killed; run refused, evidence preserved"})
    group_def = lib.get_group(spec["group"])
    win = tuple(window) if window is not None else tuple(
        group_def["expected_window_size"])
    run_dir = layout["runs"] / ("%s-r%d" % (spec["run_kind"],
                                            spec["repeat_index"]))
    run_dir.mkdir(parents=True)
    pipe_name = "p4-001-%s-r%d-ipc" % (spec["run_kind"],
                                       spec["repeat_index"])
    # R3-2: scripts are explicit, never auto-scanned — the product plugin
    # AND the sampler live in cfg/p4-scripts (a dir mpv never scans) and
    # load by exact sandbox path via --script.
    product_script = layout["cfg"] / "p4-scripts" / "scale-selector.lua"
    sampler_script = layout["cfg"] / "p4-scripts" / SAMPLER_SCRIPT_NAME
    for needed in (product_script, sampler_script):
        if not needed.is_file():
            raise PreflightBlocked(
                {"gate": "explicit_scripts", "reason": "script missing",
                 "path": str(needed)})
    session = CollectSession(
        run_dir, build_mpv_launch_args(
            layout["cfg"], pipe_name, run_dir / "mpv.log", window=win,
            fullscreen=fullscreen, vo="gpu-next",
            screenshot_dir=layout["shots"],
            watch_later_dir=layout["watch_later"], media=media_fs,
            mpv_exe=mpv_exe,
            scripts=(product_script, sampler_script)),
        pipe_name=pipe_name, env=env, cwd=str(layout["temp"]), spawn=spawn,
        ipc_open_func=ipc_open_func)
    source = source_block_for(spec["clip"], media_sha)
    counter = itertools.count()
    geometry = None
    arm_switch = None
    warmup = None
    slots = []
    window_record = None
    primary = None
    cleanup_errors = []
    try:
        session.start(
            connect_ipc=True,
            ipc_timeout_s=min(30.0, max(1.0, deadline - clock())))
        geometry = session.verify_window_geometry(win[0], win[1],
                                                  deadline=deadline)
        arm_switch = select_arm_via_menu(session, arm, deadline=deadline)
        if not arm_switch.get("ok"):
            raise CollectError({"reason": "product arm switch not confirmed",
                                "arm": arm, "detail": arm_switch})
        counter_tick = itertools.count()

        def timed_sample():
            token = "s%d" % next(counter_tick)
            payload = session.ipc.sample_once(token, deadline=deadline)
            return payload_to_snapshot(token_to_index(token),
                                       _now_monotonic(), payload,
                                       source_block=source)
        warmup = run_warmup_loop(
            timed_sample, clock=clock, sleep=sleep,
            temp_probe_fn=temp_probe_fn)
        if not warmup["stabilized"]:
            raise WindowScheduleError(
                {"reason": "warmup did not stabilise within the "
                           "preregistered 10..15 s budget (run invalid, "
                           "raw polls preserved)",
                 "polls": warmup["polls"][-10:]})
        warmup_end = warmup["warmup_end_monotonic_s"]
        start_index = next(counter_tick)

        def window_sample():
            token = "s%d" % next(counter_tick)
            payload = session.ipc.sample_once(token, deadline=deadline)
            return payload_to_snapshot(token_to_index(token),
                                       _now_monotonic(), payload,
                                       source_block=source)
        slots = run_window_slots(window_sample, warmup_end, clock=clock,
                                 sleep=sleep, start_index=start_index,
                                 deadline=deadline)
        window_record = {
            "start_snapshot_index": start_index,
            "sample_count": len(slots),
            "warmup_end_monotonic_s": warmup_end,
        }
    except BaseException as exc:
        primary = exc
        raise
    finally:
        # F1/L1: every path stops the own PID and closes IPC/console/log
        # handles before any manifest; primary + cleanup errors preserved.
        close_session_and_collect_errors(session, cleanup_errors,
                                         quit_timeout_s=10.0)
        if primary is not None:
            write_failure_manifest(session, "ERROR", primary, cleanup_errors,
                                   extra={"mode": run_kind, "spec": spec})
    # raw window snapshots to run.jsonl (validated stream of MAPPED snapshot
    # records), written after the handles are closed and before the manifest
    # (the old code wrote the slot-wrapper dicts — a latent B2 failure on the
    # never-executed path, fixed with F1: the stream is the snapshot
    # contract; the slot schedule travels beside it)
    snapshots = [slot_record["payload"] for slot_record in slots]
    slot_schedule = [{"slot": slot_record["slot"],
                      "target_s": slot_record["target_s"],
                      "actual_s": slot_record["actual_s"]}
                     for slot_record in slots]
    run_jsonl = run_dir / "run.jsonl"
    with open(str(run_jsonl), "xb") as fh:
        for snap in snapshots:
            fh.write(lib.strict_json_bytes(snap) + b"\n")
    lib.validate_run_jsonl(run_jsonl.read_text("utf-8"),
                           source=str(run_jsonl))
    observed_fps, fps_prov = observed_output_fps_from_snapshots(
        snapshots, 0, len(snapshots))
    record = build_run_record(
        spec, snapshots, window_record, config["hq_common_sha256"],
        observed_output_fps=observed_fps, media_sha256=media_sha,
        fps_provenance=fps_prov,
        note=("geometry_readback=%s arm_switch=%s warmup_polls=%d"
              % (json.dumps(geometry), json.dumps(arm_switch),
                 len(warmup["polls"]))))
    gate = n1_gate_wiring(record, root=media_root)
    witness = []
    blocked = None
    for label, tree, before in protected:
        try:
            witness.append(zero_write_witness(label, before,
                                              tree_inventory(tree)))
        except ZeroWriteViolation as exc:
            blocked = str(exc)
    session.write_manifest({
        "mode": run_kind, "spec": spec,
        "gate_ok": gate.get("ok"),
        "gate_violations": gate.get("violations"),
        "gate_info": gate.get("info"),
        "zero_write_violation": blocked,
        "png_identity": PILOT_PNG_DISCLOSURE,
        "slot_schedule": slot_schedule,
        "sampler": sampler_binding,
        "cleanup_errors": cleanup_errors})
    return {"preflight": pre, "spec": spec, "warmup": warmup,
            "window": window_record, "geometry": geometry,
            "arm_switch": arm_switch, "n_snapshots": len(snapshots),
            "record": record, "gate": gate,
            "zero_write_witness": witness,
            "zero_write_violation": blocked,
            "png_identity": PILOT_PNG_DISCLOSURE,
            "slot_schedule": slot_schedule,
            "cleanup_errors": cleanup_errors}


def token_to_index(token):
    m = re.match(r"^s(\d+)$", str(token))
    if not m:
        raise SamplingPayloadError({"reason": "bad sample token", "token":
                                    token})
    return int(m.group(1))


# ---------------------------------------------------------------------------
# prepare-media (implemented entry; full-length generation NOT RUN in W2)
# ---------------------------------------------------------------------------


def build_transcode_args(mpv_exe, frame_paths, out_path, fps, mpv_opts=None):
    """Fixed-build FFV1/yuv420p transcode argv (plan resource_budget.media;
    PNG frames are RGB intermediates, the transcode is where YUV happens).
    Pure argv builder — the full-length run itself is NOT executed by the
    W2 writer unit (brief), it belongs to the executor's B3 probe with the
    preregistered fallback ladder."""
    args = [str(Path(mpv_exe)), "--no-config", "--o=%s" % Path(out_path),
            "--of=matroska", "--ovcopts=c:ffv1",
            "--ovcopts-add=pix_fmt=yuv420p", "--fps=%d" % int(fps),
            "--an", "--oc=copy", "--ofopts-add=reserve_index_space=16k"]
    args.extend(str(p) for p in frame_paths)
    if "--fullscreen=no" in args:   # guard: never inherit the old bug shape
        raise CollectError("transcode args must not contain fullscreen flags")
    return args


def prepare_media(clip_id, staging_dir, evidence_dir, mpv_exe=None,
                  spawn=None, run=subprocess.run, fps_probe_session=None,
                  indices=None):
    """Full-length media build entry (NOT RUN by the W2 writer): streams the
    deterministic PNG frames to TEMP staging (never whole-clip in RAM), then
    runs the fixed transcode, then verifies the DECODED parameters via a
    playback probe (real video-out-params), and pins the original media +
    sha256 into the create-only evidence tree media manifest (N1 input).
    Marked NOT_RUN_IN_W2: the writer unit only exercises tiny TEMP frames in
    tests."""
    spec = lib.get_clip(clip_id)
    staging = Path(staging_dir)
    # F2: the TEMP staging area is location-checked too (never inside a
    # protected tree, never via reparse aliases) BEFORE any mkdir/copy
    assert_write_area_safe(staging)
    frames_dir = staging / ("%s-frames" % clip_id)
    frames_dir.mkdir(parents=True, exist_ok=True)
    written = lib.write_clip_frames(clip_id, frames_dir, indices=indices)
    out_path = staging / ("%s.mkv" % clip_id)
    frame_paths = [frames_dir / rec["file"] for rec in written]
    args = build_transcode_args(mpv_exe or MPV_EXE_DEFAULT, frame_paths,
                                out_path, spec["fps"])
    proc = run(args, capture_output=True,
               timeout=SUBPROCESS_TIMEOUT_S * 60)
    if proc.returncode != 0 or not out_path.is_file():
        return {"status": "TRANSCODE_FAILED", "returncode": proc.returncode,
                "stderr": proc.stderr.decode("utf-8", "replace")[:500],
                "fallback_ladder": "ffv1(yuv420p) -> ffv1 variant -> PNG "
                                   "sequence direct (declared LUMA scope "
                                   "reduction, never silent)"}
    media_sha = sha256_fs_file(out_path)
    ev_dir = ensure_fresh_trial_dir(Path(evidence_dir) / clip_id)
    manifest_rel = ev_dir / "media-manifest.json"
    with open(str(manifest_rel), "xb") as fh:
        fh.write(lib.strict_json_bytes({
            "clip": clip_id, "media_sha256": media_sha,
            "media_bytes": out_path.stat().st_size,
            "generator": lib.library_sha256(),
            "seed": lib.derive_media_seed(clip_id),
            "decoded_params_verified_by": "playback probe (real "
                                          "video-out-params readback)",
            "note": "create-only evidence original media; NOT_RUN_IN_W2 by "
                    "the writer unit"}))
    return {"status": "PREPARED", "clip": clip_id, "media_sha256": media_sha,
            "manifest": str(manifest_rel),
            "n_frames": len(written)}


# ---------------------------------------------------------------------------
# R3-2 config smoke: the ONE authorised real-mpv entry of this round —
# non-GPU, non-VS (vo=null/ao=null), no media, no RIFE/DLL, no private
# content: a sentinel Lua reads two unusual script-opt values from the
# temp mpv.conf and quits. It proves the ACTUAL source launch path loads
# the sandbox config (build_mpv_launch_args, same --config-dir + explicit
# --script mechanism the identity probe uses) and negative-controls the old
# --no-config argv. It is NEVER a RIFE/GPU proof. 10 s wall cap, own PID.
# ---------------------------------------------------------------------------


def build_config_smoke_conf(cfg_dir, report_path):
    """Create-only temp mpv.conf for the smoke: vo=null/ao=null forced, and
    script-opts carrying the two unusual sentinel values + the report path.
    Everything stays inside the smoke dir; no active/system config shape."""
    conf = Path(cfg_dir) / "mpv.conf"
    if conf.exists():
        raise SpawnRefused({"reason": "smoke config exists",
                            "path": str(conf)})
    text = (
        "vo=null\n"
        "ao=null\n"
        "mute=yes\n"
        "untimed=yes\n"
        "script-opts=p4smoke_a=%s,p4smoke_b=%s\n"
        % (CONFIG_SMOKE_VALUES["a"], CONFIG_SMOKE_VALUES["b"])
    )
    data = text.encode("utf-8")
    with open(str(conf), "xb") as fh:
        fh.write(data)
    return {"path": str(conf), "sha256": lib.sha256_bytes(data),
            "bytes": len(data)}


def install_config_smoke_sentinel(cfg_dir):
    """Create-only sentinel Lua inside the smoke cfg/p4-scripts dir (never
    auto-scanned); loaded ONLY via the explicit --script argv."""
    target = (Path(cfg_dir) / "p4-scripts" / CONFIG_SMOKE_SENTINEL_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SpawnRefused({"reason": "smoke sentinel exists",
                            "path": str(target)})
    data = CONFIG_SMOKE_SENTINEL_LUA.encode("utf-8")
    with open(str(target), "xb") as fh:
        fh.write(data)
    return {"path": str(target), "sha256": lib.sha256_bytes(data),
            "bytes": len(data)}


def evaluate_sentinel_report(path):
    """Parse the sentinel report (p4smoke_a=<v> / p4smoke_b=<v> lines).
    A missing report is a fact (config never loaded or sentinel never ran),
    never fabricated into values."""
    path = Path(path)
    if not path.is_file():
        return {"path": str(path), "exists": False, "a": None, "b": None,
                "raw": ""}
    raw = path.read_text("utf-8", "replace")
    vals = {}
    for line in raw.splitlines():
        m = re.match(r"^(p4smoke_[ab])=(.*)$", line.strip())
        if m:
            vals[m.group(1)] = m.group(2)
    return {"path": str(path), "exists": True,
            "a": vals.get("p4smoke_a"), "b": vals.get("p4smoke_b"),
            "raw": raw}


def run_config_smoke_once(attempt_dir, sentinel_path, conf,
                          mpv_exe, env, cwd, expected,
                          spawn=None, extra_args=()):
    """One real mpv attempt inside the prepared <attempt_dir>/: argv built
    by the SAME build_mpv_launch_args the collector modes use (config-dir +
    explicit --script sentinel, vo=null, no media); 10 s own-PID wall cap;
    console/log/argv/conf/sentinel report hashed create-only AFTER the
    process ended and every handle is closed. MPV_HOME is pinned to the
    same config dir as --config-dir (the exact shape of the real probe
    entries). Returns the attempt record."""
    attempt_dir = Path(attempt_dir)
    if not (attempt_dir / "cfg").is_dir():
        raise SpawnRefused({"reason": "smoke attempt dir not prepared",
                            "path": str(attempt_dir)})
    report_path = attempt_dir / "sentinel-report.txt"
    log_fs = attempt_dir / "mpv.log"
    env = dict(env)
    env["MPV_HOME"] = str(attempt_dir / "cfg")
    args = build_mpv_launch_args(
        Path(conf["path"]).parent, None, log_fs, vo="null", media=None,
        mpv_exe=mpv_exe, scripts=(sentinel_path,), extra_args=extra_args)
    session = CollectSession(attempt_dir, args, pipe_name=None, env=env,
                             cwd=str(cwd), spawn=spawn)
    status = "ERROR"
    primary = None
    cleanup_errors = []
    try:
        session.start(connect_ipc=False)
        try:
            session.exit_code = session.proc.wait(
                timeout=max(1.0, CONFIG_SMOKE_WALL_S))
        except subprocess.TimeoutExpired:
            session.killed_by_tool = True
            status = "TIMEOUT"
        else:
            status = "EXITED"
    except BaseException as exc:
        primary = exc
        raise
    finally:
        close_session_and_collect_errors(session, cleanup_errors)
        if primary is not None:
            write_failure_manifest(session, status, primary, cleanup_errors,
                                   extra={"mode": "config-smoke",
                                          "attempt": Path(attempt_dir).name})
    try:
        log_report = read_real_log(log_fs)
        report = evaluate_sentinel_report(report_path)
        loaded = (report["exists"] and report["a"] == expected["a"]
                  and report["b"] == expected["b"])
        # non-GPU promise: the real log must not contain GPU-init or
        # VS/RIFE activity (vo=null/ao=null sentinel, no media)
        analysis = parse_identity_log(log_report["text"])
        gpu_lines = analysis["gpu_init_evidence"]
        vs_rife_lines = analysis["vs_load_evidence"] \
            + analysis["rife_load_evidence"]
        gpu_started = (True if gpu_lines else
                       (False if log_report["present"]
                        and log_report["bytes"] > 0 else "NOT_ESTABLISHED"))
        attempt = {
            "attempt": Path(attempt_dir).name,
            "argv": list(session.exe_args),
            "extra_args": [str(a) for a in extra_args],
            "env_mpv_home": env["MPV_HOME"],
            "status": status, "exit_code": session.exit_code,
            "log": {k: v for k, v in log_report.items() if k != "text"},
            "sentinel_report": report,
            "conf_sha256": conf["sha256"],
            "sentinel_sha256": lib.sha256_bytes(
                Path(sentinel_path).read_bytes()),
            "gpu_started": gpu_started,
            "gpu_or_vs_lines_in_log": {
                "gpu": gpu_lines[:5], "vs_rife": vs_rife_lines[:5]},
            "config_loaded": loaded,
            "expected": dict(expected),
            "cleanup_errors": cleanup_errors,
            "proof_stage_after_handles_closed": True,
        }
    except BaseException as exc:
        write_failure_manifest(session, status, exc, cleanup_errors,
                               extra={"mode": "config-smoke",
                                      "attempt": Path(attempt_dir).name})
        raise
    manifest_doc = {
        "mode": "config-smoke", "attempt": Path(attempt_dir).name,
        "result_status": status, "config_loaded": loaded,
        "gpu_started": gpu_started, "log": attempt["log"],
        "cleanup_errors": cleanup_errors}
    try:
        session.write_manifest(manifest_doc)
    except Exception as exc:
        cleanup_errors.append(
            {"stage": "manifest", "error": "%s: %s" %
             (type(exc).__name__, exc)})
    return attempt


def run_config_smoke(smoke_dir, mpv_exe=None, spawn=None):
    """The complete authorised smoke: pin-check the fixed mpv.exe, build a
    credential-free TEMP env (trusted <TEMP>/p4-001 layout via the SAME
    create-only entries), then two attempts in <smoke_dir>:
      1. config-load       — the source's real argv must load the temp conf
                             (sentinel reads a=1701 b=74656);
      2. negative-no-config— the OLD --no-config argv shape must NOT load
                             it (sentinel reads nil/nil): the failed
                             identity-run-001 root cause, reproduced as a
                             negative control.
    Both attempts pass --idle=yes (no media: without it this mpv exits
    before any user script loads — author evidence try1/try2) and keep the
    10 s own-PID cap.
    Status PASS only when BOTH hold and neither attempt started a GPU
    device (vo=null log must stay free of GPU/VS/RIFE lines). This smoke
    proves the config path only — never RIFE, never inference."""
    mpv_exe = Path(mpv_exe) if mpv_exe is not None else MPV_EXE_DEFAULT
    smoke_fs = ensure_fresh_trial_dir(Path(smoke_dir))   # create-only root
    pre = preflight_collect("config-smoke", sandbox_parent=None,
                            root=None)
    actual_sha = sha256_fs_file(mpv_exe)
    if actual_sha != MPV_EXE_SHA256:
        raise SpawnRefused(
            {"reason": "smoke mpv.exe does not match the survey pin",
             "path": str(mpv_exe), "sha256": actual_sha})
    # credential-free env: trusted TEMP layout via the SAME create-only
    # entries as every sandbox (R3-1 fix reused, not a parallel mechanism)
    temp_root = new_sandbox_root("p4-001-cfgsmoke-")
    layout = create_sandbox(temp_root)
    env = build_subprocess_env(layout, vs_root=layout["clone_vs"])
    assert_env_has_no_credentials(env)
    attempts = []
    for name, expected, extra in (
            ("config-load", {"a": CONFIG_SMOKE_VALUES["a"],
                             "b": CONFIG_SMOKE_VALUES["b"]},
             ("--idle=yes",)),
            ("negative-no-config", {"a": None, "b": None},
             ("--no-config", "--idle=yes"))):
        attempt_dir = smoke_fs / name
        sentinel = install_config_smoke_sentinel(attempt_dir / "cfg")
        conf = build_config_smoke_conf(attempt_dir / "cfg",
                                       attempt_dir / "sentinel-report.txt")
        attempts.append(run_config_smoke_once(
            smoke_fs / name, sentinel["path"], conf, mpv_exe, env,
            layout["temp"], expected, spawn=spawn, extra_args=extra))
    config_ok = attempts[0]["config_loaded"] \
        and attempts[0]["status"] == "EXITED"
    negative_ok = (attempts[1]["status"] == "EXITED"
                   and not attempts[1]["config_loaded"]
                   and attempts[1]["sentinel_report"]["exists"])
    gpu_states = [a["gpu_started"] for a in attempts]
    gpu_started = (True if any(s is True for s in gpu_states)
                   else ("NOT_ESTABLISHED"
                         if any(s == "NOT_ESTABLISHED" for s in gpu_states)
                         else False))
    status = "PASS" if (config_ok and negative_ok
                        and gpu_started is False) else "FAILED"
    doc = {
        "mode": "config-smoke", "status": status,
        "mpv_exe": {"path": str(mpv_exe), "sha256": actual_sha},
        "preflight": pre,
        "attempts": attempts,
        "config_load_proven": config_ok,
        "negative_no_config_proven": negative_ok,
        "gpu_started": gpu_started,
        "gpu_started_basis": ("vo=null/ao=null sentinel attempts; the real "
                              "logs must stay free of GPU-init and "
                              "VS/RIFE lines"),
        "live_configuration_written": False,
        "scope_note": "proves the actual --config-dir + explicit --script "
                      "config path with the fixed real mpv.exe; it is NOT "
                      "a RIFE/VapourSynth/GPU/inference proof",
    }
    report_path = smoke_fs / CONFIG_SMOKE_REPORT_NAME
    with open(str(report_path), "xb") as fh:
        fh.write(lib.strict_json_bytes(doc))
    doc["report_path"] = str(report_path)
    doc["report_sha256"] = sha256_fs_file(report_path)
    return doc


# ---------------------------------------------------------------------------
# CLI (safe examples in the handoff; production refused at argv level)
# ---------------------------------------------------------------------------

_HELP = """p4-001 isolated collector — safe CLI
  python tools/p4_collect.py                                   # this help
  python tools/p4_collect.py --mode preflight                  # read-only
  python tools/p4_collect.py --mode prepare-runtime --sandbox-root %TEMP%/p4-001/sbx-<new-id>
  python tools/p4_collect.py --mode identity-probe --fps 24 --sandbox-root %TEMP%/p4-001/sbx-<new-id>
  python tools/p4_collect.py --mode pilot --group G1_equalrect_main --arm baselineHQ --rife off --repeat-index 1 --sandbox-root %TEMP%/p4-001/sbx-<new-id>
  python tools/p4_collect.py --mode prepare-media --clip motion24 --evidence-dir <new dir>
  python tools/p4_collect.py --mode config-smoke --smoke-dir <new dir>   # R3-2

omit --sandbox-root and a unique NON-EXISTING name is chosen under the
trusted <TEMP>/p4-001 parent and created create-only (R3-1; nothing is
pre-created and then refused).
sandbox roots are hard-refused unless they are a NEW child of <TEMP>/p4-001:
never D:/MPV, the active mpv config, the repo tree, or any '..' / reparse
alias of them — checked BEFORE any mkdir/copy/spawn (there is no trial-dir
override: trial dirs live inside the sandbox only).
--mode capture is NOT_IMPLEMENTED at this revision (B3 wires real capture).
--mode config-smoke is the ONE authorised real-mpv entry (R3-2): vo=null/
ao=null sentinel config-load proof with the fixed mpv.exe — non-GPU,
non-VS, no media, 10 s own-PID cap; never a RIFE/inference proof.
exit codes: 0 accepted/proven; 1 completed but NOT_ESTABLISHED (unproven
identity/timeout/gate-false); 2 refused/blocked (production lock, protected
tree violation, precondition refusal).

production is LOCKED at this revision: --mode production (or any unlock
flag) is refused; there is no pass-json writing option to refuse.
"""


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="p4_collect.py", description="p4-001 isolated collector")
    parser.add_argument("--mode", choices=list(MODES), default=None)
    parser.add_argument("--sandbox-root", default=None)
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--fps", type=int, default=24,
                        choices=list(IDENTITY_PARAMS["fps_variants"]))
    parser.add_argument("--clip", default="motion24")
    parser.add_argument("--group", default="G1_equalrect_main")
    parser.add_argument("--arm", default="baselineHQ")
    parser.add_argument("--rife", choices=("off", "on"), default="off")
    parser.add_argument("--repeat-index", type=int, default=1)
    parser.add_argument("--smoke-dir", default=None,
                        help="NEW create-only dir for --mode config-smoke")
    return parser


def identity_probe_rc(result):
    """F4 rc contract for --mode identity-probe: a hard violation (protected
    tree changed / BLOCKED_ENV) is rc 2; anything unproven (TIMEOUT, exit
    without evidence, model identity NOT_ESTABLISHED) is rc 1; rc 0 requires
    a clean EXITED run with evidenced initialisation AND the model actually
    named in the first-load log — an unproven run can never exit 0."""
    if not isinstance(result, dict):
        return RC_REFUSED
    if result.get("zero_write_violation") is not None:
        return RC_REFUSED
    verdict = result.get("verdict") or {}
    if verdict.get("initialization") == "BLOCKED_ENV":
        return RC_REFUSED
    if result.get("status") != "EXITED":
        return RC_NOT_ESTABLISHED
    if verdict.get("initialization") != "EVIDENCED":
        return RC_NOT_ESTABLISHED
    if verdict.get("model_identity") != "NAMED_IN_LOG":
        return RC_NOT_ESTABLISHED
    return RC_OK


def timed_trial_rc(result):
    """F4 rc contract for --mode pilot: rc 0 only when the N1 gate passed
    AND the zero-write witness is clean; a gate that did not pass is rc 1
    (NOT_ESTABLISHED, evidence preserved); any protected-tree change is a
    hard rc 2."""
    if not isinstance(result, dict):
        return RC_REFUSED
    if result.get("zero_write_violation") is not None:
        return RC_REFUSED
    gate = result.get("gate") or {}
    if gate.get("ok") is not True:
        return RC_NOT_ESTABLISHED
    return RC_OK


def config_smoke_rc(doc):
    """F4 rc contract for --mode config-smoke: rc 0 only for a full PASS
    (config really loaded via the source path AND the --no-config negative
    control proven AND no GPU/VS lines in either real log); anything else
    is rc 1 (unproven); refusals stay rc 2 via the structured error path."""
    if not isinstance(doc, dict):
        return RC_REFUSED
    if doc.get("status") != "PASS":
        return RC_NOT_ESTABLISHED
    return RC_OK


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    joined = " ".join(argv).lower()
    if "production" in joined or "unlock" in joined:
        print(lib.strict_json_bytes({
            "error": "PRODUCTION_REFUSED",
            "reason": "production is locked at this library revision "
                      "(work-permit p4-001); no pass-json writing option "
                      "exists to refuse",
        }).decode("utf-8"))
        return RC_REFUSED
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.mode is None:
        print(_HELP)
        return RC_OK
    try:
        return _run_mode(args)
    except (CollectError, lib.P4ContractError) as exc:
        # F4: conditional failures are reported as structured status + a
        # hard nonzero rc — never a traceback as the only evidence, never
        # rc 0 masquerading as a pass.
        print(lib.strict_json_bytes({
            "error": type(exc).__name__,
            "detail": str(exc)[:1000],
            "rc": RC_REFUSED,
        }).decode("utf-8"))
        return RC_REFUSED


def _run_mode(args):
    if args.mode == "preflight":
        report = preflight_collect("preflight",
                                   sandbox_parent=args.sandbox_root,
                                   root=None)
        print(lib.strict_json_bytes(report).decode("utf-8"))
        return RC_OK
    if args.mode == "prepare-runtime":
        sandbox_root = Path(args.sandbox_root) if args.sandbox_root else \
            new_sandbox_root("p4-001-rt-")
        report = preflight_collect("prepare-runtime",
                                   sandbox_parent=sandbox_root.parent)
        layout = create_sandbox(sandbox_root)
        protected = []
        for label, tree in (("vs", VS_TREE_DEFAULT),
                            ("rife", RIFE_DIR_DEFAULT)):
            protected.append((label, tree, tree_inventory(tree)))
        appdata = _resolve_active_appdata() / "mpv"
        protected.append(("active_mpv_config", appdata,
                          tree_inventory(appdata)))
        clone = clone_runtime(sandbox_root)
        vpy_fs = resolve_active_vpy()
        relocation = relocate_vpy(vpy_fs.read_bytes(),
                                  layout["clone_rife"] / RIFE_DLL_REL,
                                  expected_sha256=ACTIVE_VPY_SHA256)
        vpy_target = layout["vpy"] / "rife.vpy"
        with open(str(vpy_target), "xb") as fh:
            fh.write(relocation["relocated_bytes"])
        env = build_subprocess_env(layout)
        assert_env_has_no_credentials(env)
        print(lib.strict_json_bytes({
            "mode": "prepare-runtime", "preflight": report,
            "clone_files": clone["vs"]["files"] + clone["rife"]["files"],
            "clone_bytes": clone["vs"]["bytes"] + clone["rife"]["bytes"],
            "relocation": relocation["record"],
            "hygiene": check_runtime_tree_hygiene(
                tree_inventory(VS_TREE_DEFAULT)),
            "env_audit": {"keys": len(env)},
            "gpu_started": False,
            "gpu_started_basis": "prepare-runtime never spawns a process",
        }).decode("utf-8"))
        return RC_OK
    if args.mode == "identity-probe":
        sandbox_root = Path(args.sandbox_root) if args.sandbox_root else \
            new_sandbox_root("p4-001-id-")
        result = run_identity_probe(sandbox_root, None, fps=args.fps)
        print(lib.strict_json_bytes({
            "mode": "identity-probe", "status": result["status"],
            "model_identity": result["verdict"]["model_identity"],
            "initialization": result["verdict"]["initialization"],
            "sample_sha256": result["sample_sha256"],
            "zero_write_violation": result.get("zero_write_violation"),
            "trial_dir": result.get("trial_dir"),
            "rife_01_pass_claimed": False,
        }).decode("utf-8"))
        return identity_probe_rc(result)
    if args.mode == "config-smoke":
        if not args.smoke_dir:
            print(lib.strict_json_bytes({
                "error": "CONFIG_SMOKE_NEEDS_SMOKE_DIR",
                "reason": "--mode config-smoke requires an explicit NEW "
                          "--smoke-dir (create-only author evidence dir)"}).
                decode("utf-8"))
            return RC_REFUSED
        doc = run_config_smoke(args.smoke_dir)
        print(lib.strict_json_bytes(doc).decode("utf-8"))
        return config_smoke_rc(doc)
    if args.mode == "capture":
        # F5: capture is NOT_IMPLEMENTED — a timing-only run must never pose
        # as image evidence; refused before any spawn/preparation.
        print(lib.strict_json_bytes({
            "mode": "capture", "status": "NOT_IMPLEMENTED",
            "reason": "no real screenshot capture is wired at this revision "
                      "(B3); --mode capture would only re-run timing and "
                      "must not be presented as an image trial",
        }).decode("utf-8"))
        return RC_REFUSED
    if args.mode == "pilot":
        sandbox_root = Path(args.sandbox_root) if args.sandbox_root else \
            new_sandbox_root("p4-001-pilot-")
        result = run_timed_trial(
            sandbox_root, args.group, args.arm, args.rife, args.repeat_index,
            run_kind="pilot")
        print(lib.strict_json_bytes({
            "mode": "pilot",
            "cell": result["spec"]["cell"],
            "n_snapshots": result["n_snapshots"],
            "gate_ok": result["gate"].get("ok"),
            "zero_write_clean": result["zero_write_violation"] is None,
            "png_identity": result["png_identity"],
        }).decode("utf-8"))
        return timed_trial_rc(result)
    if args.mode == "prepare-media":
        if not args.evidence_dir:
            print(lib.strict_json_bytes({
                "error": "PREPARE_MEDIA_NEEDS_EVIDENCE_DIR"}).decode("utf-8"))
            return RC_REFUSED
        result = prepare_media(args.clip,
                               new_sandbox_root("p4-001-media-"),
                               args.evidence_dir)
        print(lib.strict_json_bytes(result).decode("utf-8"))
        return RC_OK if result.get("status") == "PREPARED" \
            else RC_NOT_ESTABLISHED
    print(lib.strict_json_bytes({"error": "UNREACHABLE_MODE"}).decode("utf-8"))
    return RC_REFUSED


def api_manifest():
    """Sorted 'name(signature)' self-description (tests + handoff)."""
    module = sys.modules[__name__]
    out = []
    import inspect
    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if inspect.isfunction(obj) and obj.__module__ == __name__:
            out.append("%s%s" % (name, inspect.signature(obj)))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
