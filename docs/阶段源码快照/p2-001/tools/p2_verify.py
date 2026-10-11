"""p2_verify.py — P2 (p2-001) isolated objective verification runner.

Real-mpv (vo=gpu-next, gpu-api=vulkan, direct mpv.exe + list-argv) regression
over throwaway temp configs, driving the four registered P2 gears
(fsr1 / sgsr1 / anime4k / nearest) and the P1 compat stub semantics.

Covers ALL 24 required test IDs (docs/P2实施计划.json):
  CTL-01..09, SHD-01..04, SHD-08..13, GEO-01, GEO-07, WINDOW-01, PIC-05,
  UNIT-P2-01.

Authoritative semantics under test (docs/P2中断接续brief-v1.json 纠正):
  * single main chain with FIRST takeover included: with a pre-existing
    Anime4K baseline in glsl-shaders, explicitly selecting a registered gear
    snapshots the baseline and replaces the ENTIRE property with the new
    recipe (nearest = empty shader list) — never an append;
  * Off restores the complete baseline only while glsl-shaders still equals
    last_written and is still owned; after an external whole-property
    modification the user's COMPLETE list is kept (no path-string removal of
    re-added same-name entries);
  * P1 stub element-level semantics remain a labelled compat mode
    (p1-test-* only);
  * WHEN/ratio use real window pixels (osd-width/height), never
    video-out-params.dw/dh (aspect-only); unknown/idle never reported as an
    active-effect algorithm;
  * RGB/HDR LUMA guard (HDR evidence = vf format metadata override on a
    synthetic SDR source, explicitly annotated metadata-override-synthetic);
  * every SHD case binds three-way evidence: glsl-shaders list + vo-passes
    (DESC keywords / user-shader pass count) + user-data export.

Usage:
    python -X utf8 tools/p2_verify.py --probe --session p2-001 \
        --evidence-dir docs/验证/开发/p2-001/implementer
    python -X utf8 tools/p2_verify.py --case SHD-01 --session p2-001 \
        --evidence-dir docs/验证/开发/p2-001/implementer
    python -X utf8 tools/p2_verify.py --all --session p2-001 \
        --evidence-dir docs/验证/开发/p2-001/implementer

Rules honored (same discipline as p1_verify.py):
  * live configuration written = false; only temp dirs + the evidence tree;
  * failures are recorded as FAIL, never silently retried into PASS; a case
    without a real executed result is never PASS;
  * only PIDs spawned here are terminated;
  * evidence is create-only; per-case artifacts refuse existing targets;
  * screenshots only enter the file list when captured non-empty.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1_lib as lib          # noqa: E402
import p2_lib as p2           # noqa: E402
import p1_verify as p1v       # noqa: E402  (read-only reuse of case scaffolding)

SESSION = "p2-001"
STAGE = "P2"
REQUIRED_TEST_IDS = ["CTL-01", "CTL-02", "CTL-03", "CTL-04", "CTL-05", "CTL-06",
                     "CTL-07", "CTL-08", "CTL-09",
                     "SHD-01", "SHD-02", "SHD-03", "SHD-04", "SHD-08",
                     "SHD-09", "SHD-10", "SHD-11", "SHD-12", "SHD-13",
                     "GEO-01", "GEO-07", "WINDOW-01", "PIC-05", "UNIT-P2-01"]

BUILTIN_IDS = ("fsr1", "sgsr1", "anime4k", "nearest")
PLACEHOLDER_IDS = ("ls1", "bcas", "nis", "xbr", "sharpbilinear", "integer")
METADATA_OVERRIDE_NOTE = ("metadata-override-synthetic：SDR 合成源经 vf=format "
                          "色彩元数据覆盖标为 HDR；非 HDR 编码片源，仅验证识别/"
                          "禁用/回退与文案，不做 HDR 画质评价")


# ---------------------------------------------------------------------------
# Session-correct case context
# ---------------------------------------------------------------------------

class CaseContext(p1v.CaseContext):
    """p1_verify's context with the session fixed to p2-001.

    The parent class resets ``self.session`` to None after env setup (a P1
    quirk that produced ``None``-prefixed IPC pipes); P2 restores the session
    name so pipes/roots are honestly p2-001-bound. Reused P1 case functions
    are pointed at this class via the module-global patch below.
    """

    def __init__(self, evidence, label, stubs=True, playing=True, session=None):
        super().__init__(evidence, label, stubs=stubs, playing=playing,
                         session=SESSION)
        self.session = SESSION  # undo the parent's reset-to-None quirk


# Reused p1 cases must construct the session-correct context and read the
# p2 session at call time (CTL-05 restart MpvSession reads the global).
p1v.CaseContext = CaseContext
p1v.SESSION = SESSION


class P2Context:
    """Isolated env with real P2 resources, stock CTRL+1..6 block, synthetic
    media and (optionally) broken fixtures in the ISOLATED copy only."""

    def __init__(self, ev: lib.Evidence, label: str, anime4k_mode: str = "a",
                 media: str = "y4m8", width: int = 320, height: int = 240,
                 frames: int = 48, broken: dict | None = None,
                 drop_resources: tuple = (), extra_args: list | None = None):
        self.evidence = ev
        self.label = label
        self.env = lib.make_env(label, session=SESSION)
        env = self.env
        env.write_mpv_conf(scale_baseline="bicubic")
        env.add_generated_input("input.conf", p2.p2_input_conf_text())
        env.install_plugin(lib.PLUGIN_LUA)
        env.add_generated_input(
            "script-opts/scale-selector.conf",
            f"key_menu=F8\nmenu_font_size=22\nanime4k_chain={anime4k_mode}\n")
        env.write_gears_conf(lib.GEARS_CONF.read_text(encoding="utf-8"))
        # full P1 stub set (baseline/stub/stub-b/ext-a/ext-b): reused CTL-06
        # compat configs reference ~~p1-test-stub.glsl; missing stub files
        # would turn legal activation into a missing-resource fallback and
        # fake a negative result
        env.write_stub_shaders()
        p2.install_p2_resources(env, broken=broken)
        for rel in drop_resources:
            target = env.cfg / rel
            if target.exists():
                target.unlink()
        self.media = None
        self.media_sha = None
        if media is None:
            pass  # idle/backend runs — no synthetic file
        elif media == "y4m8":
            self.media = env.root / "media.y4m"
            self.media_sha = p2.generate_y4m(self.media, w=width, h=height,
                                             frames=frames)
        elif media == "y4m10":
            self.media = env.root / "media10.y4m"
            self.media_sha = p2.generate_y4m(self.media, w=width, h=height,
                                             frames=frames, ten_bit=True)
        elif media == "ppm":
            self.media = env.root / "media.ppm"
            self.media_sha = p2.generate_ppm(self.media, w=width, h=height)
        else:
            raise ValueError(f"unknown media kind {media!r}")
        self.session = None
        self.extra_args = list(extra_args or [])

    def start(self, variant: str, extra_args: list | None = None):
        name = f"{self.label}-{variant}"
        self.session = lib.MpvSession(self.env, name, self.evidence.dir,
                                      session=SESSION)
        args = self.extra_args + (extra_args or []) + ["--loop-file=inf"]
        self.session.start(media=self.media, extra_args=args)
        return self.session

    def start_playing(self, variant: str, extra_args: list | None = None):
        return self.start(variant, extra_args)

    def start_idle(self, variant: str, extra_args: list | None = None):
        name = f"{self.label}-{variant}"
        self.session = lib.MpvSession(self.env, name, self.evidence.dir,
                                      session=SESSION)
        args = self.extra_args + (extra_args or []) + ["--idle=once"]
        self.session.start(media=None, extra_args=args)
        return self.session

    def cleanup(self):
        if self.session is not None and self.session.proc is not None \
                and self.session.proc.poll() is None:
            self.session.kill()
        self.env.cleanup()


# ---------------------------------------------------------------------------
# shared probes
# ---------------------------------------------------------------------------

def vop_facts(s) -> dict:
    vop = s.get("video-out-params") or {}
    osd = s.get("osd-dimensions") or {}
    out = {
        "w": vop.get("w"), "h": vop.get("h"),
        "dw": vop.get("dw"), "dh": vop.get("dh"),
        "pixelformat": vop.get("pixelformat"), "gamma": vop.get("gamma"),
        "osd_w": osd.get("w"), "osd_h": osd.get("h"),
    }
    out["upscale_ratio_window_pixels"] = p2.upscale_ratio(
        {"w": out["w"], "h": out["h"], "osd_w": out["osd_w"], "osd_h": out["osd_h"]})
    out["ratio_from_dw_dh_IS_aspect_only_not_window"] = (
        (out["dw"] * out["dh"]) / float(out["w"] * out["h"])
        if out.get("w") and out.get("h") and out.get("dw") and out.get("dh") else None)
    return out


def desc_passes(s) -> dict:
    vp = s.get("vo-passes")
    out = {"fresh": [], "redraw": []}
    if isinstance(vp, dict):
        for frame in ("fresh", "redraw"):
            for item in (vp.get(frame) or []):
                if isinstance(item, dict) and isinstance(item.get("desc"), str):
                    out[frame].append(item["desc"])
    return out


def desc_hits(s, keywords) -> dict:
    descs = desc_passes(s)
    joined = "\n".join(descs["fresh"] + descs["redraw"])
    return {kw: (kw in joined) for kw in keywords}, descs


def wait_chain_state(s, want, timeout_s=12.0) -> bool:
    return s.wait_until(lambda: s.ud("chain_verified") == want, timeout_s)


def stable_user_pass_count(s, samples=2, gap=0.8, timeout_s=14.0) -> int | None:
    """Poll until the user-shader pass count stops changing (stale-proof)."""
    deadline = time.time() + timeout_s
    last, same = None, 0
    while time.time() < deadline:
        n = p1v.user_shader_pass_count(s)
        if n == last:
            same += 1
            if same >= samples - 1:
                return n
        else:
            same = 0
        last = n
        time.sleep(gap)
    return last


def desc_hit_count(s, keywords) -> int:
    """Number of the given //!DESC keywords present in fresh/redraw passes.

    On this build a user shader WITH //!DESC appears in vo-passes with the
    DESC text as the pass description (probe evidence); the P1 "user shader"
    substring only matches DESC-less stubs, so keyword hits are the honest
    pass-presence evidence for the real P2 gears.
    """
    hits, _ = desc_hits(s, keywords)
    return sum(1 for v in hits.values() if v)


def fresh_pass_proof(s, keywords, gap_s: float = 0.8,
                     timeout_s: float = 15.0) -> dict:
    """Frame-freshness proof that the CURRENT frames really carry the gear's
    user-shader pass (数据互斥：陈旧帧不得报 active）.

    Two vo-passes samples ≥gap_s apart must show:
      * the //!DESC keyword hit in the LATER sample (pass present now),
      * strictly increasing total render-pass frame counts across the two
        samples (frames actually flowed between the samples — the hit cannot
        come from a pre-activation frozen frame),
      * non-empty per-pass samples on the hit pass (real GPU timing recorded),
      * an unchanged chain_epoch across the proof window (no chain rebuild in
        between — the evidence belongs to the current epoch).
    """
    deadline = time.time() + timeout_s
    epoch0 = s.ud("chain_epoch")
    proof = {"desc_hit_now": False, "frames_advanced": False,
             "hit_pass_has_samples": False, "epoch_stable": False,
             "frame_count_first": None, "frame_count_second": None,
             "epoch_first": epoch0, "epoch_second": None,
             "hit_pass_desc": None}

    def snapshot() -> tuple:
        vp = s.get("vo-passes")
        total = 0
        descs = []
        if isinstance(vp, dict):
            for frame in ("fresh", "redraw"):
                for item in (vp.get(frame) or []):
                    if isinstance(item, dict):
                        total += int(item.get("count") or 0)
                        if isinstance(item.get("desc"), str):
                            descs.append(item)
        return total, descs

    last = None
    while time.time() < deadline:
        total, descs = snapshot()
        hit = next((d for d in descs
                    if any(kw in d["desc"] for kw in keywords)), None)
        if last is not None and hit is not None and total > last[0]:
            proof.update({"desc_hit_now": True,
                          "frames_advanced": True,
                          "hit_pass_has_samples": bool(hit.get("samples")),
                          "frame_count_first": last[0],
                          "frame_count_second": total,
                          "hit_pass_desc": hit["desc"]})
            proof["epoch_second"] = s.ud("chain_epoch")
            proof["epoch_stable"] = proof["epoch_second"] == epoch0
            return proof
        last = (total, descs)
        time.sleep(gap_s)
    proof["epoch_second"] = s.ud("chain_epoch")
    proof["epoch_stable"] = proof["epoch_second"] == epoch0
    return proof


def enter_fullscreen_1440p(s, timeout_s: float = 12.0) -> dict:
    """Engage real fullscreen and wait for the true 2560x1440 output rectangle.

    The pinned main scenario is 1080p→1440p: the OUTPUT/texture target is the
    fullscreen render rect (2560x1440 on the pinned 2560x1440 display), NOT
    dw/dh (aspect-only display params) and NOT the screenshot size (a capture
    of the window). Returns osd-dimensions evidence; raises AssertionError on
    timeout so the case fails honestly instead of recording a wrong target.
    """
    r = s.set("fullscreen", True)
    ok = s.wait_until(
        lambda: (s.get("osd-dimensions") or {}).get("w") == 2560
        and (s.get("osd-dimensions") or {}).get("h") == 1440, timeout_s)
    osd = s.get("osd-dimensions") or {}
    return {"fullscreen_set_ok": r.get("error") == "success",
            "fullscreen_reached": bool(ok),
            "osd_dimensions": osd,
            "true_output_target": "2560x1440",
            "note": "osd-dimensions=真实窗口输出矩形（纹理目标）；"
                    "dw/dh 仅为显示比例参数；screenshot 只是窗口捕获"}


def state_facts(s) -> dict:
    return {
        "state": s.ud("state"),
        "gear": s.ud("gear"),
        "stable_gear": s.ud("stable_gear"),
        "chain_verified": s.ud("chain_verified"),
        "chain_epoch": s.ud("chain_epoch"),
        "chain_kind": s.ud("chain_kind"),
        "skip_note": s.ud("skip_note"),
        "optional_missing": s.ud("optional_missing"),
        "reason": s.ud("reason"),
        "vo_params": s.ud("vo_params"),
        "owned_shaders": s.ud("owned_shaders"),
        "chain_keywords": s.ud("chain_keywords"),
    }


def activate_via_menu(s, gear_id) -> bool:
    return s.navigate_and_activate(gear_id)


def scale_triple(s) -> dict:
    return {p: s.get(p) for p in ("scale", "cscale", "dscale")}


def set_window_scale(s, value: float) -> dict:
    r = s.set("current-window-scale", value)
    time.sleep(1.0)
    return {"set_ok": r.get("error") == "success", "value": value,
            "osd": s.get("osd-dimensions")}


# ---------------------------------------------------------------------------
# shared P1 regression cases (read-only reuse; session-correct context)
# ---------------------------------------------------------------------------

case_ctl01_p1 = p1v.case_ctl01      # NOT used directly: P2 menu expectations
case_ctl02 = p1v.case_ctl02         # stub compat off-restore
case_ctl03 = p1v.case_ctl03         # external yield ×4
case_ctl04 = p1v.case_ctl04         # rapid switching (stub compat)
case_ctl05 = p1v.case_ctl05         # quit/restart ×4 states (REV-01/V2-02)
case_ctl06_p1 = p1v.case_ctl06      # NOT used directly: P2 menu expectations
case_ctl07 = p1v.case_ctl07         # stub fallback reasons
case_ctl08 = p1v.case_ctl08         # external → off (stub compat semantics)
case_geo01 = p1v.case_geo01         # journal audit (P2-widened allow set)
case_geo07 = p1v.case_geo07         # fullscreen/minimize hold
case_shd12 = p1v.case_shd12         # LS1/BCAS disabled identity


# ---------------------------------------------------------------------------
# CTL-01 — P2 menu facts: builtins selectable, placeholders disabled
# ---------------------------------------------------------------------------

def case_ctl01(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-01", "variants": [], "files": [], "facts": {}}
    static = lib.audit_plugin_source()
    result["facts"]["plugin_source_audit"] = static
    result["facts"]["gears_conf_audit_p2"] = p2.audit_gears_conf_p2()
    ok = static["binds_only_menu_key"]
    if not ok:
        result["status"] = "FAIL"
        result["error"] = "plugin source binding audit failed"
        return result

    # variant a: idle, product conf only — P2 builtin/placeholder policy
    ctx = P2Context(ev, "CTL-01", media=None)
    try:
        s = ctx.start_idle("a-idle")
        st = p1v.run_selftest(s)
        ok = ok and st.get("status") == "pass"
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        builtins_enabled = all(by_id.get(g, {}).get("enabled") for g in BUILTIN_IDS)
        placeholders_disabled = all(
            not by_id.get(g, {}).get("enabled") for g in PLACEHOLDER_IDS)
        variant = {
            "name": "idle-p2-product-gears",
            "selftest": st.get("status"),
            "selftest_cases": len(st.get("cases", [])),
            "menu_open_ok": opened,
            "entry_ids": [e.get("id") for e in entries],
            "entry_count": len(entries),
            "off_first_enabled": bool(entries and entries[0].get("id") == "off"
                                      and entries[0].get("enabled")),
            "builtin_ids_enabled": builtins_enabled,
            "placeholder_ids_disabled": placeholders_disabled,
            "builtin_labels": {g: by_id.get(g, {}).get("label") for g in BUILTIN_IDS},
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "CTL-01-menu-idle-p2.png", variant)
        closed = s.close_menu()
        variant["menu_close_ok"] = closed
        toggles = []
        for _ in range(4):
            s.key("F8", delay=0.15)
            toggles.append(bool(s.ud("menu_open")))
        s.close_menu()
        variant["rapid_toggles"] = toggles
        ok = ok and opened and closed and len(entries) == 11 \
            and variant["off_first_enabled"] and builtins_enabled \
            and placeholders_disabled and toggles == [True, False, True, False]
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
    finally:
        ctx.cleanup()

    # variant b: playing with a compat stub gear (P1 element-level semantics)
    ctx = CaseContext(ev, "CTL-01", stubs=True, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("b-playing")
        ok = ok and s.wait_until(
            lambda: isinstance(s.get("vo-passes"), dict)
            and (s.get("vo-passes").get("fresh") or []), 15.0)
        count_off = p1v.user_shader_pass_count(s)
        nav = s.navigate_and_activate("p1-test-shader")
        ok = ok and nav and s.wait_state("active", 6.0)
        count_active = p1v.user_shader_pass_count(s)
        glsl_active = s.get("glsl-shaders")
        # compat stub: element-level append (baseline shader stays listed)
        compat_append = isinstance(glsl_active, list) \
            and "~~/p1-test-stub.glsl" in glsl_active \
            and "~~/p1-test-baseline.glsl" in glsl_active
        variant = {
            "name": "playing-compat-stub-active",
            "menu_nav_ok": nav,
            "glsl_active": glsl_active,
            "user_shader_passes_off": count_off,
            "user_shader_passes_active": count_active,
            "compat_stub_element_level_append": compat_append,
            "backend": p1v.backend_facts(s),
        }
        ok = ok and compat_append and count_active == count_off + 1
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-06 — corrupt/invalid config under the P2 registry
# ---------------------------------------------------------------------------

def case_ctl06(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-06", "variants": [], "files": [], "facts": {}}
    ok = True
    stub_shader = ("p1_test_shader_label=p1-test-shader（测试桩非产品档位）\n"
                   "p1_test_shader_mode=active\n"
                   "p1_test_shader_set=scale=bilinear;glsl-shaders+=~~/p1-test-stub.glsl\n")
    variants = {
        "a-missing-gears-key": "off_label=关\nls1_mode=disabled\nls1_reason=x\n",
        "b-bad-ids": "gears=off,BAD_ID!!,p1-test-shader\n" + stub_shader,
        "c-broken-set": "gears=off,p1-test-broken,p1-test-shader\n"
                        "p1_test_broken_label=p1-test-broken（测试桩非产品档位）\n"
                        "p1_test_broken_set=scale\n" + stub_shader,
        "d-duplicate-unknown-keys": "gears=off,ls1\noff_label=关\noff_label=关\nspelling_err_x=1\n",
        "e-reserved-id-active-set": "gears=off,ls1\noff_label=关\n"
                                    "ls1_label=超级LS1\n"
                                    "ls1_mode=active\n"
                                    "ls1_set=scale=bilinear;glsl-shaders+=~~/p1-test-stub.glsl\n"
                                    "ls1_reason=已被替代，可用\n",
        "f-impersonating-label": "gears=off,p1-test-fake\n"
                                 "p1_test_fake_mode=active\n"
                                 "p1_test_fake_label=BCAS\n"
                                 "p1_test_fake_set=scale=bilinear\n",
        "g-duplicate-and-late-off": "gears=ls1,ls1,off,off\n",
        "h-missing-off": "gears=ls1,p1-test-shader\n" + stub_shader,
    }
    for name, conf_text in variants.items():
        ctx = P2Context(ev, "CTL-06", media=None)
        ctx.env.write_raw_gears_conf(conf_text)
        try:
            s = ctx.start_idle(name)
            st = p1v.run_selftest(s)
            opened = s.open_menu()
            entries = s.menu_entries()
            by_id = {e.get("id"): e for e in entries}
            broken_entry = by_id.get("p1-test-broken")
            placeholders_disabled = all(
                not by_id.get(g, {}).get("enabled") for g in PLACEHOLDER_IDS
                if g in by_id)
            builtins_enabled = all(
                by_id.get(g, {}).get("enabled") for g in BUILTIN_IDS if g in by_id)
            variant = {
                "name": name,
                "selftest": st.get("status"),
                "menu_open_ok": opened,
                "entry_ids": [e.get("id") for e in entries],
                "entry_count": len(entries),
                "off_first_enabled": bool(entries and entries[0].get("id") == "off"
                                          and entries[0].get("enabled")),
                "placeholder_ids_all_disabled": placeholders_disabled,
                "builtin_ids_enabled_when_listed": builtins_enabled,
                "mpv_alive": s.proc.poll() is None,
                "backend": p1v.backend_facts(s),
            }
            vok = opened and variant["off_first_enabled"] \
                and placeholders_disabled and builtins_enabled
            if name == "a-missing-gears-key":
                vok = vok and len(entries) == 11  # full built-in default table
            if name == "c-broken-set":
                nav = s.navigate_and_activate("p1-test-shader")
                worked = bool(nav and s.wait_state("active", 6.0))
                variant["sibling_stub_still_selectable"] = worked
                vok = vok and broken_entry and broken_entry.get("enabled") is False \
                    and "配置错误" in (broken_entry.get("reason") or "") and worked
            elif name == "e-reserved-id-active-set":
                ls1 = by_id.get("ls1") or {}
                nav = s.navigate_and_activate("ls1")
                refused = (not nav) and s.ud("state") != "active"
                variant["ls1_label"] = ls1.get("label")
                variant["activation_refused"] = bool(refused)
                vok = vok and ls1.get("label") == "LS1" \
                    and "无公开源码" in (ls1.get("reason") or "") and refused
            elif name == "f-impersonating-label":
                fake = by_id.get("p1-test-fake") or {}
                nav = s.navigate_and_activate("p1-test-fake")
                refused = (not nav) and s.ud("state") != "active"
                variant["fake_label"] = fake.get("label")
                variant["impersonation_refused"] = bool(refused)
                vok = vok and fake.get("enabled") is False \
                    and fake.get("label") == "p1-test-fake" and refused
            elif name == "g-duplicate-and-late-off":
                vok = vok and variant["entry_ids"] == ["off", "ls1"]
            elif name == "h-missing-off":
                nav = s.navigate_and_activate("p1-test-shader")
                worked = bool(nav and s.wait_state("active", 6.0))
                variant["stub_still_selectable"] = worked
                vok = vok and worked
            shot = p1v.take_screenshot(s, ev, f"CTL-06-{name}.png", variant)
            s.close_menu()
            result["variants"].append(variant)
            if shot:
                result["files"].append(shot)
            result["files"] += p1v.save_session_artifacts(ctx, [])
            ok = ok and vok and variant["mpv_alive"] and st.get("status") == "pass"
        finally:
            ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-09 — RGB/HDR LUMA guard at activation, at runtime, and unknown/idle
# ---------------------------------------------------------------------------

def case_ctl09(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-09", "variants": [], "files": [], "facts": {}}
    ok = True

    # variant a: RGB (PPM) — LUMA gears refused at activation, nearest works
    ctx = P2Context(ev, "CTL-09", media="ppm", width=320, height=240)
    try:
        s = ctx.start_playing("a-rgb-ppm")
        vok = s.wait_until(lambda: (s.get("video-out-params") or {}).get("pixelformat"),
                           15.0)
        geo = vop_facts(s)
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        luma_blocked = {g: by_id.get(g, {}).get("guard_blocked", False)
                        for g in ("fsr1", "sgsr1", "anime4k")}
        luma_reason_rgb = all("RGB" in (by_id.get(g, {}).get("reason") or "")
                              for g in ("fsr1", "sgsr1", "anime4k"))
        nav_fsr = s.navigate_and_activate("fsr1")
        not_activated = (not nav_fsr) and s.ud("state") != "active" \
            and s.ud("gear") != "fsr1"
        glsl = s.get("glsl-shaders")
        nav_near = s.navigate_and_activate("nearest")
        near_ok = nav_near and s.wait_state("active", 6.0) \
            and scale_triple(s) == {"scale": "nearest", "cscale": "nearest",
                                    "dscale": "nearest"}
        variant = {
            "name": "rgb-ppm-guard",
            "pixelformat": geo["pixelformat"],
            "geometry": geo,
            "menu_open_ok": opened,
            "luma_gears_guard_blocked": luma_blocked,
            "luma_reason_mentions_RGB": luma_reason_rgb,
            "fsr1_activation_refused": bool(not_activated),
            "glsl_after_refusal": glsl,
            "nearest_active_on_rgb": bool(near_ok),
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "CTL-09-rgb-guard-menu.png", variant)
        s.close_menu()
        vok = vok and opened and luma_blocked["fsr1"] and luma_blocked["sgsr1"] \
            and luma_blocked["anime4k"] and luma_reason_rgb and not_activated \
            and near_ok and p2.is_rgb_pixfmt(geo["pixelformat"] or "")
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant b: HDR via vf metadata override (synthetic, annotated)
    ctx = P2Context(ev, "CTL-09", media="y4m8", width=320, height=240,
                    extra_args=["--vf=format:gamma=pq:primaries=bt.2020"])
    try:
        s = ctx.start_playing("b-hdr-metadata-override")
        vok = s.wait_until(lambda: (s.get("video-out-params") or {}).get("gamma"),
                           15.0)
        geo = vop_facts(s)
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        hdr_reasons = {g: by_id.get(g, {}).get("reason") or ""
                       for g in ("fsr1", "sgsr1", "anime4k")}
        blocked = all(by_id.get(g, {}).get("guard_blocked", False)
                      for g in ("fsr1", "sgsr1", "anime4k"))
        reasons_hdr = all("HDR" in r for r in hdr_reasons.values())
        nav = s.navigate_and_activate("fsr1")
        refused = (not nav) and s.ud("state") != "active"
        variant = {
            "name": "hdr-metadata-override-guard",
            "metadata_override_note": METADATA_OVERRIDE_NOTE,
            "gamma": geo["gamma"],
            "pixelformat": geo["pixelformat"],
            "menu_open_ok": opened,
            "luma_gears_guard_blocked": blocked,
            "luma_reasons_mentions_HDR": reasons_hdr,
            "fsr1_activation_refused": bool(refused),
            "nearest_not_guarded": by_id.get("nearest", {}).get("enabled"),
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "CTL-09-hdr-guard-menu.png", variant)
        s.close_menu()
        vok = vok and opened and blocked and reasons_hdr and refused \
            and geo["gamma"] in ("pq", "hlg")
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant c: runtime switch to HDR while fsr1 active → guard release
    ctx = P2Context(ev, "CTL-09", media="y4m8", width=320, height=240)
    try:
        s = ctx.start_playing("c-runtime-guard-release")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 6.0)
        vok = vok and wait_chain_state(s, True)
        glsl_active = s.get("glsl-shaders")
        # flip the same SDR source to HDR metadata at runtime (override)
        r = s.set("vf", [{"name": "format",
                          "params": {"gamma": "pq", "primaries": "bt.2020"}}])
        vok = vok and r.get("error") == "success"
        released = s.wait_state("fallback", 10.0)
        time.sleep(1.0)
        reason = s.ud("reason") or ""
        geo = vop_facts(s)
        glsl_after = s.get("glsl-shaders")
        no_residue = isinstance(glsl_after, list) \
            and all("p2-FSR1" not in x for x in glsl_after)
        variant = {
            "name": "runtime-hdr-guard-release",
            "glsl_active_before": glsl_active,
            "vf_set_ok": r.get("error") == "success",
            "state_fallback": bool(released),
            "reason": reason,
            "gamma_after": geo["gamma"],
            "glsl_after": glsl_after,
            "no_fsr_residue": no_residue,
            "baseline_shader_only": glsl_after == [],
            "backend": p1v.backend_facts(s),
        }
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok and released and "HDR" in reason and no_residue
    finally:
        ctx.cleanup()

    # variant d: idle/unknown vo — honest "no-video", never pseudo-active effect
    ctx = P2Context(ev, "CTL-09", media=None)
    try:
        s = ctx.start_idle("d-idle-honesty")
        vok = s.get("video-out-params") is None
        nav = activate_via_menu(s, "fsr1")
        state_active = s.wait_state("active", 6.0)
        time.sleep(1.5)
        facts = state_facts(s)
        honest = (facts["chain_verified"] == "no-video"
                  and facts["vo_params"] is None)
        opened = s.open_menu()
        variant = {
            "name": "idle-unknown-vo-honesty",
            "vo_none": vok,
            "activation_accepted": bool(nav and state_active),
            "chain_verified": facts["chain_verified"],
            "never_reported_verified": facts["chain_verified"] != True,
            "honest_no_video": honest,
            "menu_open_ok": opened,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "CTL-09-idle-honesty-menu.png", variant)
        s.close_menu()
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok and nav and state_active and honest
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-01 — FSR1: real passes, WHEN via window pixels, ≤2× clamp
# ---------------------------------------------------------------------------

def case_shd01(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-01", "variants": [], "files": [], "facts": {}}
    result["facts"]["desc_keywords"] = p2.FSR_DESC_KEYWORDS
    ok = True

    # variant a: real upscale — 1080p→1440p main scenario at the TRUE output
    # target: fullscreen render rect 2560x1440 (not dw/dh, not a clamped
    # window; the old 1.5× window was WM-clamped to 2496x1404 and is hereby
    # replaced). Passes verified with a frame-freshness proof.
    ctx = P2Context(ev, "SHD-01", media="y4m8", width=1920, height=1080, frames=16)
    try:
        s = ctx.start_playing("a-upscale")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 20.0)
        fs = enter_fullscreen_1440p(s)
        vok = vok and fs["fullscreen_reached"]
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        time.sleep(1.0)
        geo = vop_facts(s)
        glsl = s.get("glsl-shaders")
        proof = fresh_pass_proof(s, p2.FSR_DESC_KEYWORDS)
        hits, descs = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        pass_hits = desc_hit_count(s, p2.FSR_DESC_KEYWORDS)
        ud = state_facts(s)
        whole_chain = glsl == ["~~/shaders/p2-FSR1.glsl"]
        ratio = geo["upscale_ratio_window_pixels"]
        variant = {
            "name": "upscale-passes-verified",
            "window_scale_set": None,
            "fullscreen": fs,
            "geometry": geo,
            "WHEN_source": "osd-width/osd-height（窗口像素）；dw/dh 仅显示比例",
            "true_output_texture_target": "2560x1440",
            "dw_dh_are_aspect_only": geo["ratio_from_dw_dh_IS_aspect_only_not_window"] == 1.0,
            "screenshot_is_capture_not_texture": True,
            "upscale_ratio_window_pixels": ratio,
            "glsl_whole_chain": glsl,
            "whole_property_is_exactly_recipe": whole_chain,
            "desc_hits": hits,
            "desc_keyword_pass_hits": pass_hits,
            "vo_passes_fresh_n": len(descs["fresh"]),
            "fresh_pass_proof": proof,
            "chain_verified": ud["chain_verified"],
            "skip_note": ud["skip_note"],
            "state": ud["state"],
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-01-fsr1-upscale.png", variant)
        s.close_menu()
        vok = vok and whole_chain and all(hits.values()) and pass_hits == 2 \
            and ratio is not None and ratio > 1.0 \
            and ud["chain_verified"] is True and ud["skip_note"] == "" \
            and geo["osd_w"] == 2560 and geo["osd_h"] == 1440 \
            and proof["desc_hit_now"] and proof["frames_advanced"] \
            and proof["hit_pass_has_samples"] and proof["epoch_stable"]
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant b: 1× — honest //!WHEN skip, zero FSR passes, no pseudo-active
    ctx = P2Context(ev, "SHD-01", media="y4m8", width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("b-same-size-when-skip")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        set_window_scale(s, 1.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, "skipped-when")
        time.sleep(1.0)
        geo = vop_facts(s)
        hits, descs = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        ud = state_facts(s)
        variant = {
            "name": "same-size-when-skip",
            "geometry": geo,
            "upscale_ratio_window_pixels": geo["upscale_ratio_window_pixels"],
            "desc_hits": hits,
            "descs_fresh_sample": descs["fresh"][:6],
            "chain_verified": ud["chain_verified"],
            "skip_note": ud["skip_note"],
            "honest_skip": ("跳过" in (ud["skip_note"] or ""))
                           and ud["chain_verified"] == "skipped-when",
            "state": ud["state"],
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-01-fsr1-skip-when.png", variant)
        s.close_menu()
        vok = vok and not any(hits.values()) \
            and ud["chain_verified"] == "skipped-when" \
            and "跳过" in (ud["skip_note"] or "") \
            and geo["upscale_ratio_window_pixels"] is not None \
            and geo["upscale_ratio_window_pixels"] <= 1.0 + 1e-6
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant c: per-axis >2× — clamp note, passes still run, mpv takes over
    ctx = P2Context(ev, "SHD-01", media="y4m8", width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("c-over-2x-clamp")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        ws = set_window_scale(s, 2.5)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        time.sleep(1.0)
        geo = vop_facts(s)
        hits, _ = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        ud = state_facts(s)
        axes = p2.axis_scales({"w": geo["w"], "h": geo["h"],
                               "osd_w": geo["osd_w"], "osd_h": geo["osd_h"]})
        over2 = bool(axes and (axes[0] > 2.0 or axes[1] > 2.0))
        clamp_note = "2×" in (ud["skip_note"] or "")
        variant = {
            "name": "over-2x-per-axis-clamp",
            "window_scale_set": ws,
            "geometry": geo,
            "axis_scales": axes,
            "axis_over_2x": over2,
            "desc_hits": hits,
            "chain_verified": ud["chain_verified"],
            "skip_note": ud["skip_note"],
            "clamp_note_shown": clamp_note,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-01-fsr1-over-2x.png", variant)
        s.close_menu()
        vok = vok and all(hits.values()) and ud["chain_verified"] is True
        if over2:
            vok = vok and clamp_note
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-02 — SGSR1: single LUMA pass, WHEN honesty
# ---------------------------------------------------------------------------

def case_shd02(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-02", "variants": [], "files": [], "facts": {}}
    result["facts"]["desc_keywords"] = p2.SGSR_DESC_KEYWORDS
    ok = True
    # variant a: real upscale — 1080p→1440p main scenario at the TRUE output
    # target 2560x1440 fullscreen (the old 1.5× window was WM-clamped to
    # 2496x1404). Single SGSR1 LUMA pass verified with a frame-freshness proof.
    ctx = P2Context(ev, "SHD-02", media="y4m8", width=1920, height=1080, frames=16)
    try:
        s = ctx.start_playing("a-upscale")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 20.0)
        fs = enter_fullscreen_1440p(s)
        vok = vok and fs["fullscreen_reached"]
        vok = vok and activate_via_menu(s, "sgsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        time.sleep(1.0)
        geo = vop_facts(s)
        glsl = s.get("glsl-shaders")
        proof = fresh_pass_proof(s, p2.SGSR_DESC_KEYWORDS)
        hits, descs = desc_hits(s, p2.SGSR_DESC_KEYWORDS)
        pass_hits = desc_hit_count(s, p2.SGSR_DESC_KEYWORDS)
        ud = state_facts(s)
        variant = {
            "name": "upscale-single-pass-verified",
            "window_scale_set": None,
            "fullscreen": fs,
            "geometry": geo,
            "true_output_texture_target": "2560x1440",
            "dw_dh_are_aspect_only": geo["ratio_from_dw_dh_IS_aspect_only_not_window"] == 1.0,
            "screenshot_is_capture_not_texture": True,
            "glsl_whole_chain": glsl,
            "whole_property_is_exactly_recipe":
                glsl == ["~~/shaders/p2-SGSR1.glsl"],
            "desc_hits": hits,
            "desc_keyword_pass_hits": pass_hits,
            "vo_passes_fresh_n": len(descs["fresh"]),
            "fresh_pass_proof": proof,
            "chain_verified": ud["chain_verified"],
            "skip_note": ud["skip_note"],
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-02-sgsr1-upscale.png", variant)
        s.close_menu()
        vok = vok and variant["whole_property_is_exactly_recipe"] \
            and all(hits.values()) and pass_hits == 1 \
            and ud["chain_verified"] is True \
            and geo["osd_w"] == 2560 and geo["osd_h"] == 1440 \
            and proof["desc_hit_now"] and proof["frames_advanced"] \
            and proof["hit_pass_has_samples"] and proof["epoch_stable"]
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    ctx = P2Context(ev, "SHD-02", media="y4m8", width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("b-same-size-when-skip")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        set_window_scale(s, 1.0)
        vok = vok and activate_via_menu(s, "sgsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, "skipped-when")
        time.sleep(1.0)
        geo = vop_facts(s)
        hits, _ = desc_hits(s, p2.SGSR_DESC_KEYWORDS)
        ud = state_facts(s)
        variant = {
            "name": "same-size-when-skip",
            "geometry": geo,
            "desc_hits": hits,
            "chain_verified": ud["chain_verified"],
            "skip_note": ud["skip_note"],
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and not any(hits.values()) \
            and ud["chain_verified"] == "skipped-when"
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-03 — nearest: explicit scale/cscale/dscale triple, no shaders, no guard
# ---------------------------------------------------------------------------

def case_shd03(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-03", "variants": [], "files": [], "facts": {}}
    ok = True
    ctx = P2Context(ev, "SHD-03", media="y4m8", width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("a-yuv-nearest")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        glsl_before = s.get("glsl-shaders")
        descs_before = desc_passes(s)
        vok = vok and activate_via_menu(s, "nearest") and s.wait_state("active", 6.0)
        time.sleep(0.8)
        triple = scale_triple(s)
        glsl_after = s.get("glsl-shaders")
        ud = state_facts(s)
        variant = {
            "name": "yuv-explicit-triple",
            "glsl_before": glsl_before,
            "scale_cscale_dscale": triple,
            "explicit_all_nearest": triple == {"scale": "nearest",
                                               "cscale": "nearest",
                                               "dscale": "nearest"},
            "glsl_after": glsl_after,
            "empty_shader_list_recipe": glsl_after == [],
            "vo_passes_desc_n_after": len(desc_passes(s)["fresh"])
                                      + len(desc_passes(s)["redraw"]),
            "vo_passes_desc_n_before": len(descs_before["fresh"])
                                       + len(descs_before["redraw"]),
            "chain_verified": ud["chain_verified"],
            "chain_kind": ud["chain_kind"],
            "backend": p1v.backend_facts(s),
        }
        # off restores the pre-takeover scalers (actual captured baseline,
        # not assumed defaults — mpv 0.40's default cscale is "hermite")
        baseline_snapshot = s.ud("baseline") or {}
        nav = s.navigate_and_activate("off")
        ok_off = nav and s.wait_state("off", 6.0)
        post = scale_triple(s)
        expected_post = {
            "scale": baseline_snapshot.get("scale"),
            "cscale": baseline_snapshot.get("cscale")
                      or baseline_snapshot.get("scale") or "bilinear",
            "dscale": baseline_snapshot.get("dscale"),
        }
        variant["off_scale_restored"] = post
        variant["baseline_scalers"] = {k: baseline_snapshot.get(k)
                                       for k in ("scale", "cscale", "dscale")}
        variant["off_restores_baseline_scalers"] = post == expected_post
        shot = p1v.take_screenshot(s, ev, "SHD-03-nearest.png", variant)
        s.close_menu()
        vok = vok and variant["explicit_all_nearest"] \
            and variant["empty_shader_list_recipe"] \
            and ud["chain_verified"] is True and ok_off \
            and variant["off_restores_baseline_scalers"]
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant b: RGB input — nearest has NO LUMA guard and works
    ctx = P2Context(ev, "SHD-03", media="ppm", width=320, height=240)
    try:
        s = ctx.start_playing("b-rgb-no-guard")
        vok = s.wait_until(lambda: (s.get("video-out-params") or {}).get("pixelformat"),
                           15.0)
        geo = vop_facts(s)
        vok = vok and activate_via_menu(s, "nearest") and s.wait_state("active", 6.0)
        time.sleep(0.6)
        ud = state_facts(s)
        variant = {
            "name": "rgb-no-luma-guard",
            "pixelformat": geo["pixelformat"],
            "scale_cscale_dscale": scale_triple(s),
            "chain_verified": ud["chain_verified"],
            "state": ud["state"],
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and p2.is_rgb_pixfmt(geo["pixelformat"] or "") \
            and ud["state"] == "active" and ud["chain_verified"] is True
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-04 — stock six modes equivalence + single-main-chain ownership (real)
# ---------------------------------------------------------------------------

def case_shd04(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-04", "variants": [], "files": [], "facts": {}}
    result["facts"]["note"] = ("对照仅比对 glsl-shaders 列表、pass 数与 //!DESC "
                               "在场；不比画质。stock 链为隔离环境内零改动副本。")
    ok = True

    # six modes: direct CTRL+n stock chain vs registered anime4k gear
    for idx, mode in enumerate(("a", "b", "c", "d", "e", "f"), start=1):
        ctx = P2Context(ev, "SHD-04", anime4k_mode=mode, media="y4m8",
                        width=640, height=360, frames=24)
        try:
            s = ctx.start_playing(f"mode-{mode}")
            vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                               and (s.get("vo-passes").get("fresh") or []), 15.0)
            # 1) direct stock binding (plugin off, not takeover)
            s.key(f"CTRL+{idx}", delay=0.8)
            stock_list = None
            stock_stable = s.wait_until(
                lambda: (gl := s.get("glsl-shaders")) == p2.anime4k_chain_paths(mode),
                6.0)
            stock_list = s.get("glsl-shaders")
            stock_passes = stable_user_pass_count(s)
            # 2) registered gear via the real menu (whole-property replace)
            nav = activate_via_menu(s, "anime4k")
            gear_ok = nav and s.wait_state("active", 8.0)
            gear_list = s.get("glsl-shaders")
            gear_passes = stable_user_pass_count(s)
            ud = state_facts(s)
            hits, _ = desc_hits(s, p2.ANIME4K_MODE_KEYWORDS[mode]["required"])
            list_equal = stock_list == gear_list == p2.anime4k_chain_paths(mode)
            variant = {
                "name": f"mode-{mode}-ctrl{idx}-equivalence",
                "stock_key": f"CTRL+{idx}",
                "stock_list": stock_list,
                "gear_list": gear_list,
                "registered_recipe": p2.anime4k_chain_paths(mode),
                "lists_identical": list_equal,
                "stock_user_passes": stock_passes,
                "gear_user_passes": gear_passes,
                "pass_counts_equal": stock_passes == gear_passes,
                "required_desc_hits": hits,
                "optional_missing": ud["optional_missing"],
                "chain_verified": ud["chain_verified"],
                "backend": p1v.backend_facts(s),
            }
            shot = p1v.take_screenshot(s, ev, f"SHD-04-mode-{mode}.png", variant)
            s.close_menu()
            vok = vok and stock_stable and gear_ok and list_equal \
                and stock_passes == gear_passes and all(hits.values()) \
                and ud["chain_verified"] is True
            result["variants"].append(variant)
            if shot:
                result["files"].append(shot)
            result["files"] += p1v.save_session_artifacts(ctx, [])
            ok = ok and vok
        finally:
            ctx.cleanup()

    # first takeover over an existing Anime4K baseline → whole-property
    # replacement, then Off restores the COMPLETE baseline chain
    ctx = P2Context(ev, "SHD-04", anime4k_mode="a", media="y4m8",
                    width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("first-takeover-anime-baseline")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        s.key("CTRL+1", delay=0.8)
        baseline_chain = p2.anime4k_chain_paths("a")
        vok = vok and s.wait_until(
            lambda: s.get("glsl-shaders") == baseline_chain, 6.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        glsl_active = s.get("glsl-shaders")
        replaced = glsl_active == ["~~/shaders/p2-FSR1.glsl"]
        baseline_snapshot = s.ud("baseline") or {}
        snapshot_kept = baseline_snapshot.get("glsl-shaders") == baseline_chain
        # Off → complete baseline restored
        off_ok = s.navigate_and_activate("off") and s.wait_state("off", 6.0)
        glsl_off = s.get("glsl-shaders")
        report = s.ud("off_report") or {}
        restored_complete = glsl_off == baseline_chain
        variant = {
            "name": "first-takeover-anime-baseline-whole-replace-and-off",
            "baseline_chain": baseline_chain,
            "glsl_active_after_selecting_fsr1": glsl_active,
            "whole_property_replaced_no_append": replaced,
            "baseline_snapshot_kept_chain": snapshot_kept,
            "off_restored_complete_baseline": restored_complete,
            "glsl_after_off": glsl_off,
            "off_report_restored": report.get("restored"),
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-04-first-takeover-fsr1.png", variant)
        s.close_menu()
        vok = vok and replaced and snapshot_kept and restored_complete and off_ok
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # nearest on an Anime4K baseline: recipe = EMPTY shader list; Off restores
    ctx = P2Context(ev, "SHD-04", anime4k_mode="a", media="y4m8",
                    width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("nearest-on-baseline")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        s.key("CTRL+1", delay=0.8)
        baseline_chain = p2.anime4k_chain_paths("a")
        vok = vok and s.wait_until(
            lambda: s.get("glsl-shaders") == baseline_chain, 6.0)
        vok = vok and activate_via_menu(s, "nearest") and s.wait_state("active", 6.0)
        glsl_active = s.get("glsl-shaders")
        empty_ok = glsl_active == []
        triple_ok = scale_triple(s) == {"scale": "nearest", "cscale": "nearest",
                                        "dscale": "nearest"}
        off_ok = s.navigate_and_activate("off") and s.wait_state("off", 6.0)
        glsl_off = s.get("glsl-shaders")
        variant = {
            "name": "nearest-on-anime-baseline-empty-list-and-off",
            "glsl_after_nearest": glsl_active,
            "empty_shader_list_recipe": empty_ok,
            "scale_triple": triple_ok,
            "off_restored_complete_baseline": glsl_off == baseline_chain,
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and empty_ok and triple_ok and off_ok \
            and glsl_off == baseline_chain
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # external whole-property modification after activation → Off keeps the
    # user's COMPLETE external list (same-name entry survives)
    ctx = P2Context(ev, "SHD-04", anime4k_mode="a", media="y4m8",
                    width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("external-preserve-complete-list")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        # external: user presses CTRL+2 (stock chain b set = whole-property ext)
        s.key("CTRL+2", delay=0.8)
        ext_chain = p2.anime4k_chain_paths("b")
        vok = vok and s.wait_state("external", 8.0)
        vok = vok and s.wait_until(lambda: s.get("glsl-shaders") == ext_chain, 6.0)
        off_ok = s.navigate_and_activate("off") and s.wait_state("off", 6.0)
        glsl_off = s.get("glsl-shaders")
        report = s.ud("off_report") or {}
        kept = report.get("kept_external") or {}
        complete_kept = glsl_off == ext_chain
        variant = {
            "name": "external-keeps-complete-user-list",
            "external_chain_ctrl2": ext_chain,
            "glsl_after_off": glsl_off,
            "complete_external_list_kept": complete_kept,
            "off_report_kept_external": sorted(kept.keys()),
            "off_report_notes": report.get("notes"),
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and complete_kept and off_ok and "glsl-shaders" in kept
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # 1-second real-gear fast switching: fsr1 → sgsr1 → anime4k → nearest →
    # off with ~1s between activations. Each step must own the WHOLE
    # glsl-shaders property with exactly its own recipe (no append mixing,
    # no half-replaced chains), epochs non-decreasing, ends clean off.
    ctx = P2Context(ev, "SHD-04", anime4k_mode="a", media="y4m8",
                    width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("fast-switch-1s")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        set_window_scale(s, 1.5)
        a4k_chain = p2.anime4k_chain_paths("a")
        recipes = {
            "fsr1": ["~~/shaders/p2-FSR1.glsl"],
            "sgsr1": ["~~/shaders/p2-SGSR1.glsl"],
            "anime4k": a4k_chain,
            "nearest": [],
        }
        steps = []
        epochs = []
        t0 = time.time()
        switch_ok = True
        for gear_id, want in recipes.items():
            nav = activate_via_menu(s, gear_id)
            step_ok = bool(nav and s.wait_state("active", 6.0))
            got = None
            if gear_id != "nearest":
                step_ok = step_ok and wait_chain_state(s, True, 10.0)
                got = s.get("glsl-shaders")
                step_ok = step_ok and got == want
            else:
                time.sleep(0.8)
                got = s.get("glsl-shaders")
                step_ok = step_ok and got == want \
                    and scale_triple(s)["scale"] == "nearest"
            epochs.append(s.ud("chain_epoch"))
            steps.append({"gear": gear_id, "glsl": got,
                          "matches_recipe": got == want,
                          "chain_epoch": epochs[-1]})
            switch_ok = switch_ok and step_ok
            time.sleep(1.0)  # ~1s per real switch (brief: 快速切换1秒)
        elapsed = round(time.time() - t0, 1)
        off_ok = s.navigate_and_activate("off") and s.wait_state("off", 6.0)
        time.sleep(1.0)
        glsl_off = s.get("glsl-shaders")
        epochs_nondec = all(b >= a for a, b in zip(epochs, epochs[1:]))
        alive = s.proc.poll() is None
        log_clean = True
        if s.log_path.exists():
            txt = s.log_path.read_text(encoding="utf-8", errors="replace")
            log_clean = ("panicked" not in txt) and ("lua error" not in txt.lower())
        variant = {
            "name": "fast-switch-real-gears-1s",
            "elapsed_s": elapsed,
            "switch_interval_s": 1.0,
            "steps": steps,
            "epochs": epochs,
            "epochs_non_decreasing": epochs_nondec,
            "off_clean": bool(off_ok) and glsl_off == [],
            "glsl_after_off": glsl_off,
            "mpv_alive": alive,
            "log_clean": log_clean,
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and switch_ok and epochs_nondec and variant["off_clean"] \
            and alive and log_clean
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-08 — honest display: WHEN skip, no-video, resize re-verification
# ---------------------------------------------------------------------------

def case_shd08(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-08", "variants": [], "files": [], "facts": {}}
    ok = True
    # variant a: skip-when honesty in state export + menu
    ctx = P2Context(ev, "SHD-08", media="y4m8", width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("a-skip-when-note")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        set_window_scale(s, 1.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, "skipped-when")
        ud = state_facts(s)
        opened = s.open_menu()
        entries = s.menu_entries()
        fsr_entry = next((e for e in entries if e.get("id") == "fsr1"), None)
        variant = {
            "name": "skip-when-honest-display",
            "chain_verified": ud["chain_verified"],
            "skip_note": ud["skip_note"],
            "state": ud["state"],
            "menu_open_ok": opened,
            "fsr1_entry_still_selectable": bool(fsr_entry and fsr_entry.get("enabled")),
            "no_pseudo_verified": ud["chain_verified"] != True,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-08-skip-when-menu.png", variant)
        s.close_menu()
        vok = vok and opened and ud["chain_verified"] == "skipped-when" \
            and "跳过" in (ud["skip_note"] or "")
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant b: resize out of the skip band → re-verification (no stale state)
    ctx = P2Context(ev, "SHD-08", media="y4m8", width=640, height=360, frames=24)
    try:
        s = ctx.start_playing("b-resize-reverify")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        set_window_scale(s, 1.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, "skipped-when")
        epoch1 = s.ud("chain_epoch")
        ws = set_window_scale(s, 2.0)
        verified_again = wait_chain_state(s, True)
        epoch2 = s.ud("chain_epoch")
        hits, _ = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        ud = state_facts(s)
        variant = {
            "name": "resize-reverify-no-stale",
            "window_scale_set": ws,
            "epoch_before": epoch1,
            "epoch_after": epoch2,
            "epoch_increased": isinstance(epoch2, int) and isinstance(epoch1, int)
                               and epoch2 > epoch1,
            "re_verified": bool(verified_again),
            "desc_hits": hits,
            "chain_verified": ud["chain_verified"],
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and variant["epoch_increased"] and verified_again \
            and all(hits.values())
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-09 — 10-bit source: real pixelformat recorded by mpv + fsr1 runs
# ---------------------------------------------------------------------------

def case_shd09(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-09", "variants": [], "files": [], "facts": {}}
    ok = True
    ctx = P2Context(ev, "SHD-09", media="y4m10", width=1280, height=720, frames=16)
    try:
        s = ctx.start_playing("a-10bit-fsr1")
        vok = s.wait_until(lambda: (s.get("video-out-params") or {}).get("pixelformat"),
                           20.0)
        geo = vop_facts(s)
        pixfmt = geo["pixelformat"] or ""
        vok = vok and "10" in pixfmt and "420" in pixfmt
        set_window_scale(s, 1.5)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        time.sleep(1.0)
        hits, _ = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        pass_hits = desc_hit_count(s, p2.FSR_DESC_KEYWORDS)
        ud = state_facts(s)
        variant = {
            "name": "yuv420p10-fsr1",
            "media": "C420p10 stdlib-synthetic y4m (10-bit little-endian planar)",
            "media_sha256": ctx.media_sha,
            "actual_pixelformat_recorded_by_mpv": pixfmt,
            "geometry": geo,
            "desc_hits": hits,
            "desc_keyword_pass_hits": pass_hits,
            "chain_verified": ud["chain_verified"],
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-09-10bit-fsr1.png", variant)
        s.close_menu()
        vok = vok and all(hits.values()) and pass_hits == 2 \
            and ud["chain_verified"] is True
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-10 — RGB input: LUMA gears disabled with reasons; nearest unaffected
# ---------------------------------------------------------------------------

def case_shd10(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-10", "variants": [], "files": [], "facts": {}}
    ok = True
    ctx = P2Context(ev, "SHD-10", media="ppm", width=640, height=360)
    try:
        s = ctx.start_playing("a-rgb-guard")
        vok = s.wait_until(lambda: (s.get("video-out-params") or {}).get("pixelformat"),
                           15.0)
        geo = vop_facts(s)
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        blocked_map = {g: {"blocked": by_id.get(g, {}).get("guard_blocked", False),
                           "reason": by_id.get(g, {}).get("reason") or ""}
                       for g in ("fsr1", "sgsr1", "anime4k")}
        all_blocked = all(v["blocked"] and "RGB" in v["reason"]
                          for v in blocked_map.values())
        refused = True
        for g in ("fsr1", "sgsr1", "anime4k"):
            nav = s.navigate_and_activate(g)
            refused = refused and (not nav) and s.ud("state") != "active"
        glsl = s.get("glsl-shaders")
        near_ok = s.navigate_and_activate("nearest") \
            and s.wait_state("active", 6.0)
        variant = {
            "name": "rgb-source-luma-guard",
            "pixelformat": geo["pixelformat"],
            "geometry": geo,
            "luma_gears": blocked_map,
            "all_luma_blocked_with_rgb_reason": all_blocked,
            "all_luma_activations_refused": refused,
            "glsl_unchanged": glsl,
            "nearest_active_on_rgb": bool(near_ok),
            "menu_open_ok": opened,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-10-rgb-guard-menu.png", variant)
        s.close_menu()
        vok = vok and opened and all_blocked and refused and near_ok \
            and p2.is_rgb_pixfmt(geo["pixelformat"] or "")
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-11 — HDR guard via vf metadata override (synthetic; annotated)
# ---------------------------------------------------------------------------

def case_shd11(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-11", "variants": [], "files": [], "facts": {}}
    result["facts"]["metadata_override_note"] = METADATA_OVERRIDE_NOTE
    ok = True
    ctx = P2Context(ev, "SHD-11", media="y4m8", width=640, height=360, frames=24,
                    extra_args=["--vf=format:gamma=pq:primaries=bt.2020"])
    try:
        s = ctx.start_playing("a-hdr-metadata-override")
        vok = s.wait_until(lambda: (s.get("video-out-params") or {}).get("gamma"),
                           15.0)
        geo = vop_facts(s)
        opened = s.open_menu()
        entries = s.menu_entries()
        by_id = {e.get("id"): e for e in entries}
        blocked_map = {g: {"blocked": by_id.get(g, {}).get("guard_blocked", False),
                           "reason": by_id.get(g, {}).get("reason") or ""}
                       for g in ("fsr1", "sgsr1", "anime4k")}
        all_blocked = all(v["blocked"] and "HDR" in v["reason"]
                          for v in blocked_map.values())
        refused = True
        for g in ("fsr1", "sgsr1", "anime4k"):
            nav = s.navigate_and_activate(g)
            refused = refused and (not nav) and s.ud("state") != "active"
        near_ok = s.navigate_and_activate("nearest") \
            and s.wait_state("active", 6.0)
        variant = {
            "name": "hdr-metadata-override-synthetic-guard",
            "metadata_override_note": METADATA_OVERRIDE_NOTE,
            "gamma": geo["gamma"],
            "pixelformat": geo["pixelformat"],
            "luma_gears": blocked_map,
            "all_luma_blocked_with_hdr_reason": all_blocked,
            "all_luma_activations_refused": refused,
            "nearest_active_no_guard": bool(near_ok),
            "no_hdr_quality_claim": "仅守卫不评画质（PIC-06 另行立项）",
            "menu_open_ok": opened,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-11-hdr-guard-menu.png", variant)
        s.close_menu()
        vok = vok and opened and all_blocked and refused and near_ok \
            and geo["gamma"] in ("pq", "hlg")
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-13 — resource missing / compile failure / bad PARAM → honest fallback
# ---------------------------------------------------------------------------

def _fixture(name: str) -> str:
    p = lib.REPO_ROOT / "tests" / "fixtures" / "p2" / name
    return p.read_text(encoding="utf-8")


def case_shd13(ev: lib.Evidence) -> dict:
    result = {"id": "SHD-13", "variants": [], "files": [], "facts": {}}
    ok = True

    # variant a: broken syntax (fsr1) after a stable nearest → verify failure
    # releases the whole takeover to fallback/off with ZERO residue.
    # Semantics note (recorded, not silently assumed): the P1-inherited state
    # machine sets stable=active gear on activation, so the FIRST verify
    # failure takes the release_all_to_fallback branch (stable=off, scalers
    # back to the pre-takeover baseline). The "replay previous stable gear"
    # branch is retained code but unreachable on a first failure; changing the
    # state machine to force the draft's "rollback-to-nearest" expectation
    # would deviate from 沿用 P1 状态机 and is NOT done to pass a test.
    # (window >1× first: at ≤1× the //!WHEN legitimately skips the pass and the
    # broken shader would never reach its failure — the negative case must
    # create the real failure conditions, not a legal skip)
    ctx = P2Context(ev, "SHD-13", media="y4m8", width=640, height=360, frames=24,
                    broken={"fsr1": _fixture("broken-syntax.glsl")})
    try:
        s = ctx.start_playing("a-broken-syntax-rollback")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        set_window_scale(s, 1.5)
        vok = vok and activate_via_menu(s, "nearest") and s.wait_state("active", 6.0)
        stable_scale = scale_triple(s)
        baseline_snapshot = s.ud("baseline") or {}
        vok = vok and activate_via_menu(s, "fsr1")
        fell_back = s.wait_state("fallback", 25.0)
        time.sleep(1.0)
        reason = s.ud("reason") or ""
        stable_now = s.ud("stable_gear")
        scale_after = scale_triple(s)
        glsl_after = s.get("glsl-shaders")
        hits, _ = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        expected_baseline = {
            "scale": baseline_snapshot.get("scale"),
            "cscale": baseline_snapshot.get("cscale")
                      or baseline_snapshot.get("scale") or "bilinear",
            "dscale": baseline_snapshot.get("dscale"),
        }
        variant = {
            "name": "broken-syntax-verify-fail-release-fallback",
            "stable_scale_before": stable_scale,
            "state_fallback": bool(fell_back),
            "reason": reason,
            "stable_gear_after": stable_now,
            "scale_after_rollback": scale_after,
            "baseline_scalers": expected_baseline,
            "scalers_back_to_baseline": scale_after == expected_baseline,
            "glsl_after": glsl_after,
            "no_broken_residue": isinstance(glsl_after, list)
                                 and all("p2-FSR1" not in x for x in glsl_after),
            "fsr_desc_absent": not any(hits.values()),
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "SHD-13-broken-syntax-fallback.png", variant)
        s.close_menu()
        vok = vok and fell_back and "链验证失败" in reason \
            and stable_now == "off" \
            and variant["scalers_back_to_baseline"] \
            and glsl_after == [] \
            and variant["no_broken_residue"] and not any(hits.values())
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant b: bad PARAM (sgsr1) as first gear → release to fallback
    # (same >1× precondition so the broken shader is really exercised)
    ctx = P2Context(ev, "SHD-13", media="y4m8", width=640, height=360, frames=24,
                    broken={"sgsr1": _fixture("bad-param.glsl")})
    try:
        s = ctx.start_playing("b-bad-param-release")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        set_window_scale(s, 1.5)
        vok = vok and activate_via_menu(s, "sgsr1")
        fell_back = s.wait_state("fallback", 25.0)
        time.sleep(1.0)
        reason = s.ud("reason") or ""
        glsl_after = s.get("glsl-shaders")
        ud = state_facts(s)
        hits, _ = desc_hits(s, p2.SGSR_DESC_KEYWORDS)
        variant = {
            "name": "bad-param-release-to-fallback",
            "state_fallback": bool(fell_back),
            "reason": reason,
            "stable_gear_after": ud["stable_gear"],
            "glsl_after": glsl_after,
            "no_sgsr_residue": isinstance(glsl_after, list)
                               and all("p2-SGSR1" not in x for x in glsl_after),
            "sgsr_desc_absent": not any(hits.values()),
            "chain_verified": ud["chain_verified"],
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and fell_back and "链验证失败" in reason \
            and variant["no_sgsr_residue"] and not any(hits.values())
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()

    # variant c: resource file missing → immediate fallback with precise reason
    ctx = P2Context(ev, "SHD-13", media="y4m8", width=640, height=360, frames=24,
                    drop_resources=("shaders/p2-SGSR1.glsl",))
    try:
        s = ctx.start_playing("c-missing-resource")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        vok = vok and activate_via_menu(s, "sgsr1")
        fell_back = s.wait_state("fallback", 10.0)
        reason = s.ud("reason") or ""
        ud = state_facts(s)
        variant = {
            "name": "missing-resource-fallback-reason",
            "state_fallback": bool(fell_back),
            "reason": reason,
            "released_to_off_stable": ud["stable_gear"] == "off",
            "baseline_empty": s.ud_empty(s.ud("baseline")),
            "reason_names_missing_file": ("shader 文件缺失" in reason
                                          and "p2-SGSR1.glsl" in reason),
            "backend": p1v.backend_facts(s),
        }
        s.close_menu()
        vok = vok and fell_back and variant["reason_names_missing_file"] \
            and variant["released_to_off_stable"]
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# WINDOW-01 — resize/pause/aspect/clip-change: re-evaluation, no stale passes
# ---------------------------------------------------------------------------

def case_window01(ev: lib.Evidence) -> dict:
    result = {"id": "WINDOW-01", "variants": [], "files": [], "facts": {}}
    ok = True
    media2_src = None
    ctx = P2Context(ev, "WINDOW-01", media="y4m8", width=640, height=360, frames=24)
    try:
        # second synthetic clip for the loadfile step
        media2_src = ctx.env.root / "media2.y4m"
        p2.generate_y4m(media2_src, w=320, h=240, frames=12)
        ctx.env.inputs["media2.y4m"] = lib.sha256_file(media2_src)
        s = ctx.start_playing("resize-pause-clip")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                           and (s.get("vo-passes").get("fresh") or []), 15.0)
        set_window_scale(s, 1.5)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        vok = vok and wait_chain_state(s, True)
        steps = []
        epoch0 = s.ud("chain_epoch")

        # 1) pause + resize (clip-resize-paused staleness probe)
        s.set("pause", True)
        time.sleep(0.4)
        ws = set_window_scale(s, 2.0)
        time.sleep(1.2)
        paused_state = state_facts(s)
        hits_paused, descs_paused = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        consistent_paused = (paused_state["state"] == "active"
                             and paused_state["chain_keywords"] is not None)
        steps.append({
            "step": "pause+resize",
            "window_scale": ws,
            "chain_verified": paused_state["chain_verified"],
            "chain_epoch": paused_state["chain_epoch"],
            "chain_keywords_present": paused_state["chain_keywords"] is not None,
            "desc_hits": hits_paused,
            "descs_present_via_fresh_or_redraw": any(hits_paused.values()),
            "state": paused_state["state"],
            "consistent_paused": consistent_paused,
        })
        s.set("pause", False)
        time.sleep(0.6)

        # 2) aspect override change (letterbox) — geometry re-evaluation
        s.set("video-aspect-override", "4:3")
        time.sleep(1.2)
        aspect_state = state_facts(s)
        geo_aspect = vop_facts(s)
        steps.append({
            "step": "aspect-override-4:3",
            "chain_epoch": aspect_state["chain_epoch"],
            "chain_verified": aspect_state["chain_verified"],
            "state": aspect_state["state"],
            "osd": {"w": geo_aspect["osd_w"], "h": geo_aspect["osd_h"]},
        })

        # 3) clip change (different source size) — reconfig, no stale passes
        s.cmd("loadfile", str(media2_src), "replace")
        vok = vok and s.wait_until(
            lambda: (s.get("video-out-params") or {}).get("w") == 320, 12.0)
        time.sleep(1.5)
        clip_state = state_facts(s)
        geo_clip = vop_facts(s)
        hits_clip, _ = desc_hits(s, p2.FSR_DESC_KEYWORDS)
        glsl_still = s.get("glsl-shaders")
        steps.append({
            "step": "loadfile-320x240",
            "video_w_now": geo_clip["w"],
            "chain_epoch": clip_state["chain_epoch"],
            "chain_verified": clip_state["chain_verified"],
            "desc_hits": hits_clip,
            "glsl_unchanged": glsl_still == ["~~/shaders/p2-FSR1.glsl"],
            "state": clip_state["state"],
        })

        epochs = [x.get("chain_epoch") for x in steps if x.get("chain_epoch") is not None]
        epochs_nondec = all(b >= a for a, b in zip(epochs, epochs[1:])) if epochs else False
        alive = s.proc.poll() is None
        log_clean = True
        if s.log_path.exists():
            txt = s.log_path.read_text(encoding="utf-8", errors="replace")
            log_clean = ("panicked" not in txt) and ("lua error" not in txt.lower())
        variant = {
            "name": "resize-pause-aspect-clipchange",
            "steps": steps,
            "epochs_recorded": epochs,
            "epochs_non_decreasing": epochs_nondec,
            "mpv_alive": alive,
            "log_clean": log_clean,
            "backend": p1v.backend_facts(s),
        }
        shot = p1v.take_screenshot(s, ev, "WINDOW-01-after-steps.png", variant)
        s.close_menu()
        ok_steps = (all(x.get("state") == "active" for x in steps)
                    and steps[0]["descs_present_via_fresh_or_redraw"]
                    and steps[0]["consistent_paused"]
                    and steps[2]["glsl_unchanged"]
                    and epochs_nondec and alive and log_clean)
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        ok = ok and vok and ok_steps
    finally:
        ctx.cleanup()

    # variant b: quit after the run → next launch starts clean off (no residue)
    ctx = P2Context(ev, "WINDOW-01", media="y4m8", width=320, height=240, frames=12)
    try:
        s = ctx.start_playing("quit-restart-clean")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        vok = vok and activate_via_menu(s, "fsr1") and s.wait_state("active", 8.0)
        quit_ok = s.quit()
        exit_code = s.wait_exit(20.0)
        s2 = lib.MpvSession(ctx.env, "WINDOW-01-restart", ev.dir, session=SESSION)
        s2.start(media=ctx.media, extra_args=["--loop-file=inf"])
        try:
            restarted_off = s2.wait_state("off", 8.0)
            clean = s2.get("glsl-shaders") == [] \
                and s2.get("scale") == "bicubic"
            variant = {
                "name": "quit-restart-no-residue",
                "quit_ok": quit_ok,
                "exit_code": exit_code,
                "restarted_state_off": bool(restarted_off),
                "restarted_clean": clean,
                "backend": p1v.backend_facts(s2),
            }
            ok = ok and vok and quit_ok and exit_code == 0 \
                and restarted_off and clean
        finally:
            if s2.proc is not None and s2.proc.poll() is None:
                s2.kill()
        result["variants"].append(variant)
        result["files"] += p1v.save_session_artifacts(ctx, [])
        if s2.log_path.exists():
            result["files"].append(p1v.relp(s2.log_path))
        if s2.ipc is not None and s2.ipc.transcript:
            p = ev.save_transcript(s2.log_path.stem + ".transcript.jsonl",
                                   s2.ipc.transcript)
            result["files"].append(p1v.relp(p))
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# PIC-05 — P2 menu wording (objective part; subjective stays user-check)
# ---------------------------------------------------------------------------

def case_pic05(ev: lib.Evidence) -> dict:
    result = {"id": "PIC-05", "variants": [], "files": [], "facts": {}}
    conf_audit = lib.audit_gears_conf()
    conf_audit_p2 = p2.audit_gears_conf_p2()
    result["facts"]["gears_conf_audit"] = conf_audit
    result["facts"]["gears_conf_audit_p2"] = conf_audit_p2
    ok = conf_audit["no_stub_gears_in_product"] and conf_audit["no_placeholder_set"] \
        and all(conf_audit_p2.values())

    def check_menu(entries):
        by_id = {e.get("id"): e for e in entries}
        builtin_ok = all(by_id.get(g, {}).get("enabled") for g in BUILTIN_IDS)
        placeholder_ok = all(
            not e.get("enabled") and (e.get("reason") or "") != ""
            for gid, e in by_id.items() if gid in PLACEHOLDER_IDS)
        off_ok = (entries and entries[0].get("id") == "off"
                  and by_id.get("off", {}).get("enabled") is True)
        no_substitute = all(
            not ("CAS" in (e.get("label") or "") and e.get("label") != "BCAS")
            for e in entries)
        ls1_reason_ok = "无公开源码" in (by_id.get("ls1", {}).get("reason") or "")
        bcas_reason_ok = "身份未核实" in (by_id.get("bcas", {}).get("reason") or "")
        builtin_labels_ok = (by_id.get("fsr1", {}).get("label") == "FSR1"
                             and by_id.get("sgsr1", {}).get("label") == "SGSR1"
                             and by_id.get("nearest", {}).get("label") == "Nearest Neighbor"
                             and "Anime4K" in (by_id.get("anime4k", {}).get("label") or ""))
        return (builtin_ok, placeholder_ok, off_ok, no_substitute,
                ls1_reason_ok, bcas_reason_ok, builtin_labels_ok)

    for name, stubs in (("main-product-conf", False),):
        ctx = P2Context(ev, "PIC-05", media="y4m8", width=320, height=240) \
            if not stubs else CaseContext(ev, "PIC-05", stubs=True, playing=True,
                                          session=SESSION)
        try:
            s = ctx.start_playing(name)
            vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
            opened = s.open_menu()
            entries = s.menu_entries()
            (builtin_ok, placeholder_ok, off_ok, no_substitute,
             ls1_ok, bcas_ok, labels_ok) = check_menu(entries)
            variant = {
                "name": name,
                "menu_open_ok": opened,
                "builtin_entries_enabled": builtin_ok,
                "placeholder_entries_disabled_with_reason": placeholder_ok,
                "off_first_enabled": off_ok,
                "no_cas_substitute_labels": no_substitute,
                "ls1_true_reason": ls1_ok,
                "bcas_true_reason": bcas_ok,
                "builtin_fixed_labels": labels_ok,
                "entries": entries,
                "subjective_pending": "P2-UC-1（菜单观感/文案偏好留用户确认；本条仅客观核对）",
                "backend": p1v.backend_facts(s),
            }
            shot = p1v.take_screenshot(s, ev, "PIC-05-p2-menu.png", variant)
            s.close_menu()
            vok = vok and opened and builtin_ok and placeholder_ok and off_ok \
                and no_substitute and ls1_ok and bcas_ok and labels_ok
            result["variants"].append(variant)
            if shot:
                result["files"].append(shot)
            result["files"] += p1v.save_session_artifacts(ctx, [])
            ok = ok and vok
        finally:
            ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# UNIT-P2-01 — full unit suite (real subprocess run, recorded)
# ---------------------------------------------------------------------------

def case_unit_p2_01(ev: lib.Evidence) -> dict:
    result = {"id": "UNIT-P2-01", "variants": [], "files": [], "facts": {}}
    cmd = [sys.executable, "-B", "-X", "utf8", "-m", "unittest", "discover",
           "-s", "tests"]
    proc = subprocess.run(cmd, cwd=str(lib.REPO_ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env={**{k: v for k, v in os.environ.items()
                                  if k in lib.SAFE_ENV_KEYS},
                               "SYSTEMROOT": os.environ.get("SystemRoot", ""),
                               "PATH": os.environ.get("PATH", "")})
    tail = (proc.stdout or "") + "\n" + (proc.stderr or "")
    m = re.search(r"Ran (\d+) tests? in", tail)
    total = int(m.group(1)) if m else None
    mfail = re.search(r"FAILED \(failures=(\d+), errors=(\d+)\)", tail)
    mok = re.search(r"^OK\b", tail, re.M)
    variant = {
        "name": "unittest-discover-tests",
        "command": "python -B -X utf8 -m unittest discover -s tests",
        "returncode": proc.returncode,
        "total_tests": total,
        "ok_marker": bool(mok),
        "failures_errors": mfail.groups() if mfail else None,
        "tail": tail[-2000:],
        "original_91_still_included": total is not None and total >= 121,
    }
    result["variants"].append(variant)
    ok = proc.returncode == 0 and bool(mok) and total is not None and total >= 121
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# --probe — media/backend capability probe (plan step 2 evidence)
# ---------------------------------------------------------------------------

def run_probe(ev: lib.Evidence, write_canonical: bool = True) -> dict:
    """Empirical capability probe; results go to media-probe.json (session
    tree) with raw console/log/transcripts bound in <evidence>/probe/."""
    probe = {"schema": "mpv-scaler-p2-media-probe/v1", "session": SESSION,
             "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "mpv_exe": lib.MPV_EXE, "results": {}}
    files = []
    probe_dir = ev.dir / "probe"
    probe_dir.mkdir(parents=True, exist_ok=False)

    def one_run(tag, media_builder, extra=None, with_fsr=False, stock_key=None):
        sub = probe_dir / tag
        sub.mkdir(parents=True, exist_ok=False)
        ctx = P2Context(ev, f"probe-{tag}", media=None)
        try:
            media = ctx.env.root / f"{tag}.media"
            sha = media_builder(media)
            ctx.media, ctx.media_sha = media, sha
            name = f"probe-{tag}"
            s = lib.MpvSession(ctx.env, name, sub, session=SESSION)
            args = list(extra or []) + ["--loop-file=inf"]
            s.start(media=media, extra_args=args)
            rec = {"media_sha256": sha}
            try:
                if media_builder is not None:
                    s.wait_until(lambda: (s.get("video-out-params") or {})
                                 .get("pixelformat") or
                                 (s.get("video-out-params") or {}).get("gamma"),
                                 20.0)
                rec["selftest"] = None
                if with_fsr:
                    st = p1v.run_selftest(s)
                    rec["selftest"] = st.get("status")
                    s.set("current-window-scale", 1.5)
                    time.sleep(0.8)
                    s.open_menu()
                    s.navigate_and_activate("fsr1")
                    s.wait_state("active", 8.0)
                    wait_chain_state(s, True) or wait_chain_state(s, "skipped-when")
                    time.sleep(1.0)
                if stock_key:
                    st = p1v.run_selftest(s)
                    rec["selftest"] = st.get("status")
                    s.key(stock_key, delay=1.0)
                    time.sleep(2.0)
                rec["video_out_params"] = {k: (s.get("video-out-params") or {}).get(k)
                                           for k in ("w", "h", "pixelformat", "gamma")}
                rec["osd_dimensions"] = s.get("osd-dimensions")
                rec["glsl_shaders"] = s.get("glsl-shaders")
                rec["user_shader_passes"] = p1v.user_shader_pass_count(s)
                descs = desc_passes(s)
                rec["vo_passes_desc_sample"] = {
                    "fresh_n": len(descs["fresh"]),
                    "fresh_head": descs["fresh"][:8],
                    "user_shader_desc_head": [d for d in descs["fresh"]
                                              if "user shader" in d][:8],
                }
                if with_fsr:
                    hits, _ = desc_hits(s, p2.FSR_DESC_KEYWORDS)
                    rec["fsr_desc_hits"] = hits
                if stock_key:
                    joined = "\n".join(descs["fresh"] + descs["redraw"])
                    rec["anime4k_desc_hits"] = {
                        kw: (kw in joined)
                        for kw in ("Anime4K-v4.0-De-Ring",
                                   "Anime4K-v4.0-Restore-CNN-(VL)",
                                   "Anime4K-v3.2-Upscale-CNN-x2-(VL)")}
            finally:
                if s.proc is not None and s.proc.poll() is None:
                    s.quit()
                if s.log_path.exists():
                    files.append(p1v.relp(s.log_path))
                if getattr(s, "console_path", None) and s.console_path.exists():
                    files.append(p1v.relp(s.console_path))
                if s.ipc is not None and s.ipc.transcript:
                    pth = sub / f"{name}.transcript.jsonl"
                    data = "\n".join(json.dumps(x, ensure_ascii=False)
                                     for x in s.ipc.transcript) + "\n"
                    p = ev._write_create_only(pth, data.encode("utf-8"))
                    files.append(p1v.relp(p))
            rec["exit_code"] = s.exit_code
            probe["results"][tag] = rec
        finally:
            ctx.cleanup()

    backend = {"mpv_version": None}
    ctx0 = P2Context(ev, "probe-backend", media=None)
    try:
        s = lib.MpvSession(ctx0.env, "probe-backend-idle", probe_dir,
                           session=SESSION)
        s.start(media=None, extra_args=["--idle=once"])
        backend["mpv_version"] = s.get("mpv-version")
        backend["current_vo"] = s.get("current-vo")
        backend["mpv_platform"] = s.get("mpv-platform")
        gpu = s.get("gpu-api")
        backend["gpu_api_vulkan_enabled"] = any(
            isinstance(x, dict) and x.get("name") == "vulkan" and x.get("enabled")
            for x in (gpu or [])) if isinstance(gpu, list) else None
        st = p1v.run_selftest(s)
        backend["selftest"] = st.get("status")
        backend["selftest_cases"] = len(st.get("cases", []))
        backend["selftest_failed_cases"] = [
            c for c in (st.get("cases") or []) if not c.get("pass")]
        if s.log_path.exists():
            files.append(p1v.relp(s.log_path))
        if s.console_path.exists():
            files.append(p1v.relp(s.console_path))
        if s.ipc is not None and s.ipc.transcript:
            pth = probe_dir / "probe-backend-idle.transcript.jsonl"
            data = "\n".join(json.dumps(x, ensure_ascii=False)
                             for x in s.ipc.transcript) + "\n"
            p = ev._write_create_only(pth, data.encode("utf-8"))
            files.append(p1v.relp(p))
        s.quit()
    finally:
        ctx0.cleanup()
    probe["backend"] = backend

    one_run("y4m8", lambda p: p2.generate_y4m(p, w=320, h=240, frames=12))
    one_run("y4m10", lambda p: p2.generate_y4m(p, w=320, h=240, frames=12,
                                               ten_bit=True))
    one_run("ppm", lambda p: p2.generate_ppm(p, w=320, h=240))
    one_run("hdr-override", lambda p: p2.generate_y4m(p, w=320, h=240, frames=12),
            extra=["--vf=format:gamma=pq:primaries=bt.2020"])
    one_run("fsr1-desc-shape",
            lambda p: p2.generate_y4m(p, w=640, h=360, frames=12), with_fsr=True)
    one_run("stock-desc-shape",
            lambda p: p2.generate_y4m(p, w=640, h=360, frames=12), stock_key="CTRL+1")

    probe["decisions"] = {
        "y4m8_usable": probe["results"].get("y4m8", {}).get("video_out_params", {})
        .get("pixelformat", "").startswith("yuv420p"),
        "y4m10_usable": "10" in probe["results"].get("y4m10", {})
        .get("video_out_params", {}).get("pixelformat", ""),
        "ppm_rgb_usable": p2.is_rgb_pixfmt(probe["results"].get("ppm", {})
                                           .get("video_out_params", {})
                                           .get("pixelformat", "") or ""),
        "hdr_override_gamma": probe["results"].get("hdr-override", {})
        .get("video_out_params", {}).get("gamma"),
        "fsr_desc_verified": probe["results"].get("fsr1-desc-shape", {})
        .get("fsr_desc_hits"),
        "anime4k_desc_verified": probe["results"].get("stock-desc-shape", {})
        .get("anime4k_desc_hits"),
        "lua_selftest": backend.get("selftest"),
    }
    obj = ev.write_json("media-probe.json", probe)
    files.append(p1v.relp(obj))
    # also the canonical session-tree copy required by the plan (create-only);
    # skipped when a canonical already exists (stale input recorded instead —
    # the fresh evidence lives in this evidence dir's media-probe.json)
    canonical = lib.REPO_ROOT / lib.SESSIONS_ROOT / SESSION / "media-probe.json"
    if write_canonical:
        if canonical.exists():
            raise FileExistsError(f"create-only 目标已存在: {canonical}")
        canonical.write_bytes((json.dumps(probe, ensure_ascii=False, indent=2)
                               + "\n").encode("utf-8"))
        files.append(p1v.relp(canonical))
    manifest = lib.build_evidence_manifest(SESSION, sorted(set(files)))
    ev.write_json("probe-evidence-manifest.json", manifest)
    print(json.dumps(probe["decisions"], ensure_ascii=False, indent=2))
    return probe


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

CASES = {
    "CTL-01": case_ctl01,
    "CTL-02": case_ctl02,
    "CTL-03": case_ctl03,
    "CTL-04": case_ctl04,
    "CTL-05": case_ctl05,
    "CTL-06": case_ctl06,
    "CTL-07": case_ctl07,
    "CTL-08": case_ctl08,
    "CTL-09": case_ctl09,
    "SHD-01": case_shd01,
    "SHD-02": case_shd02,
    "SHD-03": case_shd03,
    "SHD-04": case_shd04,
    "SHD-08": case_shd08,
    "SHD-09": case_shd09,
    "SHD-10": case_shd10,
    "SHD-11": case_shd11,
    "SHD-12": case_shd12,
    "SHD-13": case_shd13,
    "GEO-01": case_geo01,
    "GEO-07": case_geo07,
    "WINDOW-01": case_window01,
    "PIC-05": case_pic05,
    "UNIT-P2-01": case_unit_p2_01,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=sorted(CASES),
                        help="run a single required test id (repeatable)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--probe", action="store_true",
                        help="run the media/backend capability probe only")
    parser.add_argument("--session", default=None,
                        help="session id; REQUIRED for any run (p2-001)")
    parser.add_argument("--evidence-dir", required=True,
                        help="evidence directory; REQUIRED, must be a fresh "
                             "dir inside the repo session tree")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.list:
        for k in sorted(CASES):
            print(k)
        return 0
    global SESSION
    if not args.session or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.session):
        parser.error("--session is required (e.g. p2-001)")
    SESSION = args.session
    p1v.SESSION = SESSION
    selected = sorted(CASES) if args.all else (args.case or [])
    if not selected and not args.probe:
        parser.error("choose --all, --probe or at least one --case")

    ev_abs = Path(args.evidence_dir).resolve()
    try:
        ev_rel = ev_abs.relative_to(lib.REPO_ROOT).as_posix()
    except ValueError:
        parser.error(f"--evidence-dir must live inside the repo ({lib.REPO_ROOT})")
    lib.ensure_fresh_evidence_dir(ev_abs, force=args.force)
    ev_rel_dir = f"{lib.SESSIONS_ROOT}/{SESSION}"
    if ev_rel != ev_rel_dir and not ev_rel.startswith(ev_rel_dir + "/"):
        parser.error(f"--evidence-dir must be inside the session tree {ev_rel_dir}/")

    evidence = lib.Evidence(ev_abs)
    if args.probe:
        probe = run_probe(evidence)
        ok = (probe["decisions"]["lua_selftest"] == "pass"
              and probe["decisions"]["y4m8_usable"]
              and probe["decisions"]["y4m10_usable"]
              and probe["decisions"]["ppm_rgb_usable"]
              and probe["decisions"]["hdr_override_gamma"] in ("pq", "hlg")
              and all((probe["decisions"].get("fsr_desc_verified") or {}).values())
              and (probe["decisions"].get("anime4k_desc_verified") or {})
              .get("Anime4K-v4.0-De-Ring", False))
        print("[probe] result:", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    # plan step 2: media capability probe precedes the case matrix (create-only;
    # an existing canonical media-probe.json is reused as read-only input ONLY
    # when its decisions still describe the current source bytes — the 15:44
    # canonical predates the 2026-10-03 shader parse fix and recorded
    # fsr_desc_verified=false / lua_selftest=fail against superseded bytes;
    # reusing those as current facts would be dishonest). If stale, a fresh
    # probe is run bound to THIS evidence dir; the canonical file stays
    # untouched (create-only) and its sha is recorded as a stale input.
    canonical_probe = lib.REPO_ROOT / lib.SESSIONS_ROOT / SESSION / "media-probe.json"
    probe_bound: list = []
    canonical_note = None
    media_probe = None
    if canonical_probe.exists():
        canon = json.loads(canonical_probe.read_text(encoding="utf-8"))
        canon_dec = canon.get("decisions", {})
        fsr_ok = isinstance(canon_dec.get("fsr_desc_verified"), dict) \
            and all(canon_dec.get("fsr_desc_verified", {}).values())
        canon_green = fsr_ok and canon_dec.get("lua_selftest") == "pass" \
            and canon_dec.get("y4m8_usable") and canon_dec.get("y4m10_usable") \
            and canon_dec.get("ppm_rgb_usable") \
            and canon_dec.get("hdr_override_gamma") in ("pq", "hlg")
        if canon_green:
            media_probe = {"decisions": canon_dec,
                           "note": "已有 media-probe.json（create-only）作为只读输入复用"}
            probe_bound = [p1v.relp(canonical_probe)]
        else:
            canonical_note = {
                "path": p1v.relp(canonical_probe),
                "sha256": lib.sha256_file(canonical_probe),
                "stale_decisions": canon_dec,
                "reason": "canonical probe 的决定产生于 2026-10-03 shader 解析"
                          "修复之前的源字节（fsr_desc_verified=false / "
                          "lua_selftest=fail 与当前源码实测矛盾），不作为当前"
                          "事实复用；本目录另跑全新 probe，canonical 保持"
                          " create-only 不改。"}
    if media_probe is None:
        full_probe = run_probe(evidence, write_canonical=canonical_note is None)
        media_probe = {"decisions": full_probe["decisions"],
                       "backend": full_probe["backend"],
                       "results": full_probe["results"]}
        if canonical_note is not None:
            media_probe["canonical_stale_input"] = canonical_note
        probe_bound = [p1v.relp(evidence.dir / "media-probe.json"),
                       p1v.relp(evidence.dir / "probe-evidence-manifest.json")]
        if canonical_note is not None:
            probe_bound.append(canonical_note["path"])

    repro_tail = f"--session {SESSION} --evidence-dir {ev_rel}"
    summary = {
        "stage": STAGE,
        "session": SESSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "evidence_dir": ev_rel,
        "create_only": True,
        "required_test_ids": REQUIRED_TEST_IDS,
        "backend_pin": {"vo": "gpu-next", "gpu_api": "vulkan",
                        "mpv_exe": lib.MPV_EXE,
                        "note": "直呼 mpv.exe + list-argv（mpv.com 包装器会改写"
                                "含反斜杠的参数，P1 探针证据）"},
        "live_configuration_written": False,
        "media_probe": media_probe,
        "semantics_authority": "docs/P2中断接续brief-v1.json（单主链整property替换"
                               "含首次接管；Off 恢复条件；external 保留完整列表；"
                               "WHEN 用窗口像素）",
        "notes": [
            "每个 SHD 用例三路证据：glsl-shaders 列表 + vo-passes（DESC/pass 数）"
            "+ user-data 导出。",
            "RGB 源为 stdlib PPM(P6)；10bit 为 stdlib C420p10 y4m；HDR 守卫证据"
            "为 vf=format 元数据覆盖合成（metadata-override-synthetic 明示），"
            "非 HDR 编码片源，不做画质评价。",
            "P1 兼容回归（CTL-02..05/07/08、GEO-01/07、SHD-12）经只读导入复用 "
            "p1_verify 用例，上下文会话修正为 p2-001；桩档位元素级语义为明确兼容模式。",
            "证据 create-only；清单含全部产物 SHA-256（含 .gitignore 的 .log）。",
            "IPC 自动化只证功能与状态真实性，不替代真人交互感受；不做画质/性能收益宣称。",
        ],
        "cases": [],
    }
    failures = []
    for cid in selected:
        print(f"[{SESSION}] running {cid} ...", flush=True)
        started = time.time()
        try:
            case_result = CASES[cid](evidence)
        except Exception as error:  # noqa: BLE001 — record, never hide
            case_result = {"id": cid, "status": "FAIL", "error": repr(error)}
        case_result["elapsed_s"] = round(time.time() - started, 1)
        case_result["repro_command"] = (
            f"python -X utf8 tools/p2_verify.py --case {cid} {repro_tail}")
        summary["cases"].append(case_result)
        status = case_result.get("status")
        print(f"[{SESSION}] {cid}: {status} ({case_result['elapsed_s']}s)",
              flush=True)
        if status != "PASS":
            failures.append(cid)

    missing = []
    for case in summary["cases"]:
        for f in list(case.get("files", [])):
            p = lib.REPO_ROOT / f
            if not p.exists() or p.stat().st_size == 0:
                missing.append(f)
    summary["evidence_files_all_exist"] = not missing
    summary["missing_evidence_files"] = missing
    summary["required_ids_covered"] = sorted(
        {c.get("id") for c in summary["cases"]}) == sorted(set(REQUIRED_TEST_IDS)) \
        if len(summary["cases"]) == len(REQUIRED_TEST_IDS) else False

    obj_path = evidence.write_json("objective-results.json", summary)
    print(f"[{SESSION}] objective results: {len(summary['cases'])} cases, "
          f"failures: {failures or 'none'}", flush=True)

    bound = sorted({f for case in summary["cases"] for f in case.get("files", [])}
                   | {p1v.relp(obj_path)} | set(probe_bound))
    manifest = lib.build_evidence_manifest(SESSION, bound)
    man_path = evidence.write_json("evidence-manifest.json", manifest)
    print(f"[{SESSION}] evidence manifest: {p1v.relp(man_path)}", flush=True)
    print(f"[{SESSION}] evidence-manifest sha256: {lib.sha256_file(man_path)}",
          flush=True)
    print(f"[{SESSION}] 集成负责人冻结时请在 tests.json 中记录: "
          f'"evidence_manifest": {{"path": "{p1v.relp(man_path)}", '
          f'"sha256": "{lib.sha256_file(man_path)}"}}', flush=True)
    if missing:
        print(f"[{SESSION}] MISSING EVIDENCE FILES: {missing}", flush=True)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
