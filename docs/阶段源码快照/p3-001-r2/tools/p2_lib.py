# -*- coding: utf-8 -*-
"""p2_lib.py — P2 (p2-001) shared support library, thin layer over p1_lib.

P2 scope (docs/P2实施计划.json): four real gears on the P1 state machine —
  * anime4k : stock Anime4K v4 CTRL+1..6 chains, byte-identical copies of the
              files referenced by the live config (zero modification);
  * fsr1    : AMD FidelityFX FSR v1.0.2 (EASU+RCAS, LUMA, MIT), adapted port,
              per-axis <=2x clamp kept, mpv takes over beyond;
  * sgsr1   : Qualcomm SGSR1 (single LUMA pass, BSD-3-Clause), adapted port;
  * nearest : scale=nearest + cscale=nearest + dscale=nearest (explicit).

This module adds to p1_lib (which stays the isolation/IPC/evidence base):
  * stock-chain inventory + hash audit (backup payload = frozen source,
    live APPDATA shaders = read-only cross reference);
  * the P2 resource manifest loader/auditor (shaders/resource-manifest.json);
  * stdlib synthetic media: 8-bit / 10-bit y4m and RGB PPM (no ffmpeg CLI);
  * pure guard oracles mirroring the plugin's RGB/HDR LUMA-guard logic
    (field names identical to the Lua side: ``pixelformat``, ``osd_w/osd_h``);
  * the isolated input.conf stock CTRL+1..6 block (pointing at the isolated
    copies) used for the SHD-04 equivalence comparison;
  * P2 registered whole-chain ownership oracles (brief 纠正): a registered
    P2 gear activation replaces the ENTIRE glsl-shaders property with its
    recipe (first takeover included — a pre-existing Anime4K baseline is
    snapshotted, never appended to); "关" restores the complete baseline
    only while the property still equals last_written and is still owned;
    after an external whole-property modification the user's COMPLETE list
    is kept (entries are never removed by path string). The P1 element-level
    helpers in p1_lib remain only as the labelled compat mode for p1-test-*
    stubs and must not be applied to P2 registered main chains.

Boundaries honored here (same discipline as p1_lib):
  * never writes APPDATA/mpv, D:/MPV, or the backup payload (read-only);
  * test gears remain prefixed p1-test-* / p2-test-* and are labeled
    测试桩非产品档位;
  * this is machine-checking support, not an OS sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

import p1_lib as lib  # noqa: E402  (same tools/ directory)

REPO_ROOT = lib.REPO_ROOT

# ---------------------------------------------------------------------------
# Stock Anime4K inventory (frozen backup payload = copy source; live APPDATA
# shaders directory = read-only cross reference; never written by P2).
# ---------------------------------------------------------------------------

BACKUP_MPV_CONFIG = Path(
    "D:/workspace/小项目/mpv插件/_备份/缩放插件/"
    "mpv-config-20261002-233943/payload/mpv-config")
BACKUP_SHADER_DIR = BACKUP_MPV_CONFIG / "shaders"
BACKUP_INPUT_CONF = BACKUP_MPV_CONFIG / "input.conf"
LIVE_SHADER_DIR = Path(os.environ.get("APPDATA", "")) / "mpv" / "shaders"
LIVE_INPUT_CONF = Path(os.environ.get("APPDATA", "")) / "mpv" / "input.conf"

REPO_ANIME4K_DIR = REPO_ROOT / "shaders" / "anime4k"
REPO_SHADER_DIR = REPO_ROOT / "shaders"
RESOURCE_MANIFEST_PATH = REPO_SHADER_DIR / "resource-manifest.json"

ANIME4K_LICENSE_EVIDENCE = "docs/证据/anime4k-readme.md"
FSR_BASE_EVIDENCE = "docs/证据/port-FSR.glsl"
SGSR_BASE_EVIDENCE = "docs/证据/port-SGSR.glsl"
FSR_BASE_SHA256 = "56d8597fc6b7bf6d13f8c3b2bdf1cdc43b06175d51746aab44cf1dca16929b9e"
SGSR_BASE_SHA256 = "10a3d1ada2c439607caac32de2a5adceab1cd1580261511aaf67bafd415065fe"

REPO_FSR_PATH = "shaders/p2-FSR1.glsl"
REPO_SGSR_PATH = "shaders/p2-SGSR1.glsl"

# The ten distinct stock files referenced by the live CTRL+1..6 chains.
ANIME4K_CHAIN_FILES = [
    "Anime4K_Clamp_Highlights.glsl",
    "Anime4K_Restore_CNN_VL.glsl",
    "Anime4K_Restore_CNN_Soft_VL.glsl",
    "Anime4K_Restore_CNN_M.glsl",
    "Anime4K_Restore_CNN_Soft_M.glsl",
    "Anime4K_Upscale_CNN_x2_VL.glsl",
    "Anime4K_Upscale_CNN_x2_M.glsl",
    "Anime4K_Upscale_Denoise_CNN_x2_VL.glsl",
    "Anime4K_AutoDownscalePre_x2.glsl",
    "Anime4K_AutoDownscalePre_x4.glsl",
]

# Exact stock chains (order preserved) as bound in the live/backup input.conf
# CTRL+1..6 (Anime4K v4.1 "Mode A (HQ)" .. "Mode C+A (HQ)").
ANIME4K_CHAINS = {
    "a": ["Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_AutoDownscalePre_x2.glsl",
          "Anime4K_AutoDownscalePre_x4.glsl", "Anime4K_Upscale_CNN_x2_M.glsl"],
    "b": ["Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_Soft_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_AutoDownscalePre_x2.glsl",
          "Anime4K_AutoDownscalePre_x4.glsl", "Anime4K_Upscale_CNN_x2_M.glsl"],
    "c": ["Anime4K_Clamp_Highlights.glsl", "Anime4K_Upscale_Denoise_CNN_x2_VL.glsl",
          "Anime4K_AutoDownscalePre_x2.glsl", "Anime4K_AutoDownscalePre_x4.glsl",
          "Anime4K_Upscale_CNN_x2_M.glsl"],
    "d": ["Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_Restore_CNN_M.glsl",
          "Anime4K_AutoDownscalePre_x2.glsl", "Anime4K_AutoDownscalePre_x4.glsl",
          "Anime4K_Upscale_CNN_x2_M.glsl"],
    "e": ["Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_Soft_VL.glsl",
          "Anime4K_Upscale_CNN_x2_VL.glsl", "Anime4K_AutoDownscalePre_x2.glsl",
          "Anime4K_AutoDownscalePre_x4.glsl", "Anime4K_Restore_CNN_Soft_M.glsl",
          "Anime4K_Upscale_CNN_x2_M.glsl"],
    "f": ["Anime4K_Clamp_Highlights.glsl", "Anime4K_Upscale_Denoise_CNN_x2_VL.glsl",
          "Anime4K_AutoDownscalePre_x2.glsl", "Anime4K_AutoDownscalePre_x4.glsl",
          "Anime4K_Restore_CNN_M.glsl", "Anime4K_Upscale_CNN_x2_M.glsl"],
}
ANIME4K_MODE_LABELS = {
    "a": "Mode A (HQ)", "b": "Mode B (HQ)", "c": "Mode C (HQ)",
    "d": "Mode A+A (HQ)", "e": "Mode B+B (HQ)", "f": "Mode C+A (HQ)",
}

# Gear id sets (mirror of the Lua registry; unit tests pin the two copies).
P2_BUILTIN_IDS = ("fsr1", "sgsr1", "anime4k", "nearest")
# P3 (p3-001) registry migration (P3A-01; docs/P3实施计划.json write_path_notes
# c-②): the still-placeholder set narrows to ls1/bcas — nis/xbr/sharpbilinear/
# integer are now real built-ins (plus the new sharpbilinear2x). The P2 four
# built-ins and this mirror's audit semantics are unchanged; the P3 increment
# lives in p3_lib (audit_gears_conf_p3), NOT here (minimal-migration rule).
STILL_DISABLED_IDS = ("ls1", "bcas")
P3_BUILTIN_IDS = ("nis", "xbr", "sharpbilinear", "sharpbilinear2x", "integer")
LUMA_GEAR_IDS = ("fsr1", "sgsr1", "anime4k")   # LUMA-hook chains (RGB/HDR guarded)
# nearest is a pure scale/cscale/dscale gear: NO LUMA guard by design.
# P3: nis is a LUMA compute chain (RGB/HDR guarded); xbr/sharpbilinear/
# sharpbilinear2x are MAIN RGB chains with an INDEPENDENT HDR guard; integer
# is scaler/geometry-only (no guard), mirroring nearest.

# vo-passes //!DESC keyword mirror of the Lua ANIME4K_MODE_KEYWORDS table.
# required = unconditionally-running stock files (missing ⇒ compile failure);
# optional = //!WHEN-gated stock files (legitimately skipped outside their
# window-size band; honest note only, never a failure).
ANIME4K_MODE_KEYWORDS = {
    "a": {"required": ["Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-(VL)"],
          "optional": ["Anime4K-v3.2-Upscale-CNN-x2-(VL)",
                       "Anime4K-v3.2-Upscale-CNN-x2-(M)"]},
    "b": {"required": ["Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-Soft-(VL)"],
          "optional": ["Anime4K-v3.2-Upscale-CNN-x2-(VL)",
                       "Anime4K-v3.2-Upscale-CNN-x2-(M)"]},
    "c": {"required": ["Anime4K-v4.0-De-Ring"],
          "optional": ["Anime4K-v3.2-Upscale-Denoise-CNN-x2-(VL)",
                       "Anime4K-v3.2-Upscale-CNN-x2-(M)"]},
    "d": {"required": ["Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-(VL)",
                       "Anime4K-v4.0-Restore-CNN-(M)"],
          "optional": ["Anime4K-v3.2-Upscale-CNN-x2-(VL)",
                       "Anime4K-v3.2-Upscale-CNN-x2-(M)"]},
    "e": {"required": ["Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-Soft-(VL)",
                       "Anime4K-v4.0-Restore-CNN-Soft-(M)"],
          "optional": ["Anime4K-v3.2-Upscale-CNN-x2-(VL)",
                       "Anime4K-v3.2-Upscale-CNN-x2-(M)"]},
    "f": {"required": ["Anime4K-v4.0-De-Ring", "Anime4K-v4.0-Restore-CNN-(M)"],
          "optional": ["Anime4K-v3.2-Upscale-Denoise-CNN-x2-(VL)",
                       "Anime4K-v3.2-Upscale-CNN-x2-(M)"]},
}

FSR_DESC_KEYWORDS = ["FidelityFX Super Resolution v1.0.2 (EASU)",
                     "FidelityFX Super Resolution v1.0.2 (RCAS)"]
SGSR_DESC_KEYWORDS = ["Snapdragon Game Super Resolution"]


def anime4k_chain_paths(mode: str) -> list:
    """Repo-relative glsl-shaders entries (mpv ~~/ form) for chain mode a..f."""
    if mode not in ANIME4K_CHAINS:
        raise ValueError(f"未知 Anime4K 链模式: {mode!r}（允许 a..f）")
    return ["~~/shaders/anime4k/" + name for name in ANIME4K_CHAINS[mode]]


def expected_builtin_chains(anime4k_mode: str = "a") -> dict:
    """gear id -> list of glsl-shaders appends (the plugin's built-in chains)."""
    return {
        "fsr1": ["~~/shaders/p2-FSR1.glsl"],
        "sgsr1": ["~~/shaders/p2-SGSR1.glsl"],
        "anime4k": anime4k_chain_paths(anime4k_mode),
        # nearest writes scale/cscale/dscale only; no shader chain.
        "nearest": [],
    }


# ---------------------------------------------------------------------------
# Stock-copy / resource-manifest audits
# ---------------------------------------------------------------------------

def stock_file_sha256(name: str, where: str) -> str:
    base = {"backup": BACKUP_SHADER_DIR, "live": LIVE_SHADER_DIR,
            "repo": REPO_ANIME4K_DIR}[where]
    return lib.sha256_file(base / name)


def verify_stock_copy(cross_check_live: bool = True) -> dict:
    """Byte-level audit: repo shaders/anime4k copies must be byte-identical to
    the frozen backup payload; when present, also cross-checked against the
    live APPDATA shaders (read-only reference). Raises on any mismatch."""
    problems = []
    per_file = {}
    for name in ANIME4K_CHAIN_FILES:
        entry = {}
        repo_p = REPO_ANIME4K_DIR / name
        backup_p = BACKUP_SHADER_DIR / name
        if not repo_p.is_file():
            problems.append(f"仓库缺 stock 副本: shaders/anime4k/{name}")
            per_file[name] = entry
            continue
        if not backup_p.is_file():
            problems.append(f"备份 payload 缺源文件（冻结源不完整?）: {name}")
            per_file[name] = entry
            continue
        repo_sha = lib.sha256_file(repo_p)
        backup_sha = lib.sha256_file(backup_p)
        entry["repo_sha256"] = repo_sha
        entry["backup_sha256"] = backup_sha
        if repo_sha != backup_sha:
            problems.append(f"stock 副本与冻结源不一致（零改动被破坏）: {name}")
        if cross_check_live and LIVE_SHADER_DIR.is_dir():
            live_p = LIVE_SHADER_DIR / name
            if live_p.is_file():
                live_sha = lib.sha256_file(live_p)
                entry["live_sha256"] = live_sha
                if live_sha != repo_sha:
                    problems.append(f"stock 副本与活动配置只读副本不一致: {name}")
            else:
                problems.append(f"活动配置缺对应文件（只读交叉核对不完整）: {name}")
        per_file[name] = entry
    return {"problems": problems, "files": per_file,
            "ok": not problems}


RESOURCE_MANIFEST_SCHEMA = "mpv-scaler-p2-resource-manifest/v1"


def verify_resource_manifest(path: Path = RESOURCE_MANIFEST_PATH) -> dict:
    """Audit shaders/resource-manifest.json against the bytes on disk.

    Checks, per resource: repo file exists and matches recorded sha256;
    for stock copies the source (backup payload) hash matches; for adapted
    ports the recorded base evidence hash matches docs/证据 (FSR/SGSR).
    """
    problems = []
    data = json.loads(Path(path).read_bytes().decode("utf-8"))
    if data.get("schema") != RESOURCE_MANIFEST_SCHEMA:
        problems.append(f"resource manifest schema 不符: {data.get('schema')!r}")
    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        return {"problems": problems + ["resources 缺失或为空"], "ok": False}
    for res in resources:
        rel = res.get("path", "")
        p = REPO_ROOT / rel
        recorded = res.get("sha256")
        if not p.is_file():
            problems.append(f"资源缺失: {rel}")
            continue
        actual = lib.sha256_file(p)
        if recorded != actual:
            problems.append(f"资源哈希不符（清单或文件被改）: {rel}")
        if res.get("kind") == "stock-copy":
            src_sha = stock_file_sha256(Path(rel).name, "backup")
            if res.get("source_sha256") != src_sha:
                problems.append(f"stock 来源哈希不符: {rel}")
            if recorded != src_sha:
                problems.append(f"stock 副本与冻结源不一致: {rel}")
        if res.get("kind") == "adapted-port":
            base_rel = res.get("base_evidence")
            base_recorded = res.get("base_sha256")
            if base_rel == FSR_BASE_EVIDENCE and base_recorded != FSR_BASE_SHA256:
                problems.append(f"FSR 基文件哈希记录不符: {rel}")
            if base_rel == SGSR_BASE_EVIDENCE and base_recorded != SGSR_BASE_SHA256:
                problems.append(f"SGSR 基文件哈希记录不符: {rel}")
            base_p = REPO_ROOT / base_rel
            if not base_p.is_file() or lib.sha256_file(base_p) != (base_recorded or ""):
                problems.append(f"适配基文件缺失或被改: {base_rel}")
    return {"problems": problems, "ok": not problems, "resources": resources}


# ---------------------------------------------------------------------------
# Gear registry consistency (mirror of the Lua PRODUCT_GEARS policy)
# ---------------------------------------------------------------------------

GEARS_CONF = lib.GEARS_CONF


def audit_gears_conf_p2() -> dict:
    """P2 policy audit of the shipped gear table (P2 superset of P1 rules).

    P3 (p3-001) registry migration (P3A-01; write_path_notes c-②): the
    still_disabled check narrows to ls1/bcas (the only remaining
    placeholders); the P2 four built-ins' semantics are UNCHANGED (their conf
    entries stay); the P3 increment (p3_builtins_active etc.) lives in
    p3_lib.audit_gears_conf_p3 — this mirror stays minimal by design.
    """
    text = GEARS_CONF.read_text(encoding="utf-8")
    checks = {
        "off_first": "gears=off," in text,
        "off_label_is_const_guan": "off_label=关" in text,
        "still_disabled": all(f"{gid}_mode=disabled" in text
                              for gid in STILL_DISABLED_IDS),
        "p2_builtins_active": all(f"{gid}_mode=active" in text
                                  for gid in P2_BUILTIN_IDS),
        "ls1_reason_policy": all(k in text for k in ("无公开源码", "权重", "移植许可")),
        "bcas_reason_policy": ("身份未核实" in text and "不以CAS/Bicubic+CAS冒名" in text),
        # Built-in chains live in Lua (hash-audited resources), never in conf.
        "no_builtin_set_in_conf": all(
            not line.startswith(f"{gid}_set=")
            for gid in P2_BUILTIN_IDS + STILL_DISABLED_IDS + P3_BUILTIN_IDS
            for line in text.splitlines()),
        "no_stub_gears_in_product": "p1-test-" not in text and "p2-test-" not in text,
    }
    return checks


# ---------------------------------------------------------------------------
# Pure guard oracles (mirror the plugin's LUMA-guard logic; unit-tested)
# ---------------------------------------------------------------------------

def is_rgb_pixfmt(pixfmt) -> bool:
    if not isinstance(pixfmt, str):
        return False
    p = pixfmt.lower()
    return ("rgb" in p) or ("bgr" in p) or ("gbr" in p) or p == "pal8"


def is_hdr_gamma(gamma) -> bool:
    return gamma in ("pq", "hlg")


def luma_guard_reason(is_luma_gear: bool, vo: dict) -> str | None:
    """Return a refusal reason when a LUMA gear must not be used, else None.

    vo: video-out-params subset with Lua-identical field names
    {pixelformat, gamma, w, h, dw, dh, osd_w, osd_h} — or None (unknown/no
    video → the hook simply never fires; not guarded, and never reported as
    verified/active-effect either).
    """
    if not is_luma_gear or vo is None:
        return None
    if is_rgb_pixfmt(vo.get("pixelformat")):
        return (f"RGB 输入（pixelformat={vo.get('pixelformat')}）：LUMA 档不可用"
                "（RGB 源无 LUMA hook，链不会生效）")
    if is_hdr_gamma(vo.get("gamma")):
        return (f"HDR 输入（gamma={vo.get('gamma')}）：P2 按计划禁用 LUMA 档"
                "（仅守卫不评画质，HDR 画质属 PIC-06 另行立项）")
    return None


def upscale_ratio(vo: dict) -> float | None:
    """(osd_w*osd_h)/(w*h): real window pixels vs source pixels.

    video-out-params.dw/dh are display ASPECT parameters, NOT the window
    output size — they must never be used for the //!WHEN decision (brief
    纠正). osd-width/osd-height are the window pixels. None = unknown
    (unknown must never be reported as the algorithm being active).
    """
    try:
        w, h = vo["w"], vo["h"]
        ow, oh = vo["osd_w"], vo["osd_h"]
        if not w or not h or not ow or not oh:
            return None
        return (ow * oh) / float(w * h)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def axis_scales(vo: dict) -> tuple | None:
    """(osd_w/w, osd_h/h) per-axis window scale; None when unknown."""
    try:
        w, h = vo["w"], vo["h"]
        ow, oh = vo["osd_w"], vo["osd_h"]
        if not w or not h or not ow or not oh:
            return None
        return (ow / float(w), oh / float(h))
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def fsr_when_applies(vo: dict) -> bool | None:
    """True = FSR/SGSR //!WHEN (upscale ratio > 1) passes will run.
    False = passes legitimately skipped (≤1×). None = unknown."""
    r = upscale_ratio(vo)
    if r is None:
        return None
    return r > 1.0


def chain_skip_note(gear_id: str, vo: dict) -> str:
    """Honest per-gear skip/clamp note for the current output geometry.
    Empty string = chain expected to be fully effective."""
    applies = fsr_when_applies(vo)
    if gear_id in ("fsr1", "sgsr1") and applies is False:
        return ("非放大（≤1×）：LUMA hook 按 //!WHEN 跳过，本链当前无实际 pass，"
                "缩放由 mpv scaler 完成")
    if gear_id == "fsr1" and applies:
        axes = axis_scales(vo)
        if axes and (axes[0] > 2.0 or axes[1] > 2.0):
            return ("单轴放大 >2×：FSR 按 ≤2× 钳制运行，超出部分由 mpv scaler 接管")
    return ""


# ---------------------------------------------------------------------------
# P2 registered whole-chain ownership oracles (brief 纠正 — the authoritative
# single-main-chain semantics; the P1 element-level helpers in p1_lib remain
# only as the labelled compat mode for p1-test-* stubs).
# ---------------------------------------------------------------------------

def expected_builtin_chain_write(gear_id: str, anime4k_mode: str = "a") -> list:
    """The exact glsl-shaders property a registered P2 gear activation writes.

    Whole-property replacement (first takeover included): the written list is
    EXACTLY the registered recipe — a pre-existing Anime4K/user chain in the
    property is snapshotted into the baseline, never appended to. nearest's
    recipe is the empty list by design.
    """
    return list(expected_builtin_chains(anime4k_mode)[gear_id])


def expected_off_actions_whole(baseline: dict, last: dict, wrote: dict,
                               current: dict) -> tuple:
    """"关" oracle for a takeover whose main chain was a registered P2 gear.

    Returns (restores, kept, notes):
      * glsl-shaders still equal to last_written (still owned) → restore the
        COMPLETE baseline (e.g. the user's original Anime4K chain);
      * externally modified whole property → keep the user's COMPLETE
        external list untouched (no element-level removal by path string —
        a re-added same-name entry must survive);
      * scalar props follow the same equal-to-last_written rule.
    """
    restores, kept, notes = {}, {}, []
    for prop, was_written in (wrote or {}).items():
        if not was_written:
            continue
        cur = (current or {}).get(prop)
        if prop == "glsl-shaders":
            cur_list = list(cur) if isinstance(cur, list) else []
            if lib.close_enough(cur_list, (last or {}).get(prop)):
                restores[prop] = list(baseline.get(prop) or [])
            else:
                kept[prop] = cur_list
                notes.append("glsl-shaders：外部改动后保留用户完整列表"
                             "（整链所有权，不按路径字符串删除条目）")
        else:
            if lib.close_enough(cur, (last or {}).get(prop)):
                restores[prop] = baseline.get(prop)
            else:
                kept[prop] = cur
    return restores, kept, notes


# ---------------------------------------------------------------------------
# Isolated input.conf: stock CTRL+1..6 block (isolated copies) + external
# bindings used by P1-style CTL cases. F8 stays free (plugin menu key).
# ---------------------------------------------------------------------------

def stock_anime4k_input_block() -> list:
    """The live config's CTRL+1..6 stock bindings, byte-equivalent semantics,
    retargeted to the isolated copies under ~~/.shaders/anime4k/."""
    lines = []
    for idx, mode in enumerate(("a", "b", "c", "d", "e", "f"), start=1):
        chain = ";".join(anime4k_chain_paths(mode))
        label = ANIME4K_MODE_LABELS[mode]
        lines.append(
            f'CTRL+{idx} no-osd change-list glsl-shaders set "{chain}"; '
            f'show-text "Anime4K: {label}"')
    return lines


def p2_input_conf_text(include_stock_block: bool = True,
                       external_block: bool = True) -> str:
    lines = []
    if include_stock_block:
        lines += stock_anime4k_input_block()
    if external_block:
        lines += [
            'CTRL+9 no-osd change-list glsl-shaders append "~~/p1-test-ext-a.glsl"; show-text "p2-test: 外部追加A"',
            'CTRL+8 no-osd change-list glsl-shaders append "~~/p1-test-ext-b.glsl"; show-text "p2-test: 外部追加B"',
            'CTRL+0 no-osd change-list glsl-shaders clr ""; show-text "p2-test: 外部清链"',
            'F5 no-osd change-list glsl-shaders toggle "~~/p1-test-ext-a.glsl"; show-text "p2-test: 外部toggle"',
            'F6 set scale spline36; show-text "p2-test: 外部改scale"',
        ]
    text = "\n".join(lines) + "\n"
    assert "F8" not in text, "F8 must stay free for the plugin menu"
    return text


# ---------------------------------------------------------------------------
# Stdlib synthetic media (no ffmpeg CLI on this machine)
# ---------------------------------------------------------------------------

def _row_pattern_y8(width: int, row: int, phase: int) -> bytes:
    """Deterministic 16-px checker band row (P1-compatible look, vectorized)."""
    band = (row // 16 + phase) & 1
    base = 30 + (200 if band else 0)
    chunk = bytes([base]) * 8 + bytes([base ^ 0x50]) * 8
    reps = width // 16 + (1 if width % 16 else 0)
    return (chunk * reps)[:width]


def _row_pattern_y10(width: int, row: int, phase: int) -> bytes:
    # chunk = 8 little-endian 16-bit pixel elements = 16 bytes = 8 pixels
    # (NOT 16 pixels — the pre-fix draft halved every row; brief 根因修复)
    band = (row // 16 + phase) & 1
    base = 120 + (800 if band else 0)
    chunk = struct.pack("<HHHHHHHH", base, base, base, base,
                        base ^ 0x140, base ^ 0x140, base ^ 0x140, base ^ 0x140)
    reps = width // 8 + (1 if width % 8 else 0)
    return (chunk * reps)[:width * 2]


def generate_y4m(path, w=320, h=240, frames=48, fps_num=24, fps_den=1,
                 ten_bit: bool = False) -> str:
    """Deterministic moving-band clip.

    ten_bit=False → C420jpeg 8-bit (P1-compatible layout).
    ten_bit=True  → C420p10 10-bit little-endian planar (mpv maps to
                    yuv420p10le; actual pixfmt recorded by the media probe).
    Returns sha256 of the file.
    """
    chroma_w, chroma_h = w // 2, h // 2
    ctag = "C420p10" if ten_bit else "C420jpeg"
    with open(path, "wb") as f:
        header = f"YUV4MPEG2 W{w} H{h} F{fps_num}:{fps_den} Ip A1:1 {ctag}\n"
        f.write(header.encode("ascii"))
        if ten_bit:
            # near-neutral chroma in 16-bit LE (u≈513, v≈608)
            u_frame = bytes([0x01, 0x02] * chroma_w * chroma_h)   # ~513 LE
            v_frame = bytes([0x60, 0x02] * chroma_w * chroma_h)   # ~608 LE
            rows = [_row_pattern_y10(w, yy, ph) for ph in (0, 1)
                    for yy in range(h)]
        else:
            u_frame = bytes([80] * (chroma_w * chroma_h))
            v_frame = bytes([140] * (chroma_w * chroma_h))
            rows = [_row_pattern_y8(w, yy, ph) for ph in (0, 1)
                    for yy in range(h)]
        # rows layout: rows[phase*h + yy]
        y_frames = [
            b"".join(rows[ph * h + yy] for yy in range(h))
            for ph in (0, 1)
        ]
        for i in range(frames):
            f.write(b"FRAME\n")
            f.write(y_frames[i % 2])
            f.write(u_frame)
            f.write(v_frame)
    return lib.sha256_file(path)


def generate_ppm(path, w=320, h=240) -> str:
    """Deterministic RGB PPM (P6) test image. Returns sha256."""
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    band = bytearray()
    for yy in range(h):
        base = 40 + (190 if (yy // 16) & 1 else 0)
        chunk = bytes([base, 255 - base, (base * 3) % 256]) * 8 \
            + bytes([255 - base, base, 77]) * 8
        reps = w // 16 + (1 if w % 16 else 0)
        band += (chunk * reps)[:w * 3]
    with open(path, "wb") as f:
        f.write(header)
        f.write(bytes(band))
    return lib.sha256_file(path)


# ---------------------------------------------------------------------------
# P2 CaseContext: isolated env with real P2 resources + stock input block
# ---------------------------------------------------------------------------

BROKEN_SYNTAX_GLSL = (
    "// p2-test broken shader（测试桩：故意语法错误，仅存在于测试隔离配置目录）\n"
    "//!HOOK LUMA\n"
    "//!BIND HOOKED\n"
    "//!DESC p2-test broken (syntax error)\n"
    "vec4 hook() { return HOOKED_tex(HOOKED_pos) ;;;; }\n"
)

BAD_PARAM_GLSL = (
    "// p2-test incompatible-PARAM shader（测试桩：PARAM 超出声明范围，仅测试隔离目录）\n"
    "//!PARAM TESTLEVEL\n"
    "//!DESC p2-test bad param\n"
    "//!TYPE CONSTANT float\n"
    "//!MINIMUM 0.0\n"
    "//!MAXIMUM 1.0\n"
    "42.0\n"
    "//!HOOK LUMA\n"
    "//!BIND HOOKED\n"
    "vec4 hook() { return HOOKED_tex(HOOKED_pos); }\n"
)


def install_p2_resources(env, broken: dict | None = None) -> None:
    """Copy the hash-audited repo shaders into the isolated config dir.

    broken: optional {"fsr1": text, "sgsr1": text} — replaces the isolated
    copy of that shader with a broken fixture (SHD-13). Fixtures NEVER touch
    the repo shaders/ directory.
    """
    broken = broken or {}
    (env.cfg / "shaders" / "anime4k").mkdir(parents=True, exist_ok=True)
    for name in ANIME4K_CHAIN_FILES:
        src = REPO_ANIME4K_DIR / name
        dst = env.cfg / "shaders" / "anime4k" / name
        dst.write_bytes(src.read_bytes())
        env.inputs[f"shaders/anime4k/{name}"] = lib.sha256_file(dst)
    for rel, replace_key in ((REPO_FSR_PATH, "fsr1"), (REPO_SGSR_PATH, "sgsr1")):
        dst = env.cfg / rel
        if replace_key in broken:
            lib.write_text_lf(dst, broken[replace_key])
            env.inputs[rel + ".broken-fixture"] = lib.sha256_file(dst)
        else:
            dst.write_bytes((REPO_ROOT / rel).read_bytes())
            env.inputs[rel] = lib.sha256_file(dst)
