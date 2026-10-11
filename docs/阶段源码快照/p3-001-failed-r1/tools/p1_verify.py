"""p1_verify.py — P1 isolated objective verification runner (real mpv + IPC).

Drives the real mpv binary (vo=gpu-next, gpu-api=vulkan) in throwaway temp
configs over JSON IPC and records evidence under an explicit evidence
directory (default session tree docs/验证/开发/<session>/, but --evidence-dir
is REQUIRED so a rerun can never silently fall back to an old session path).
Every p1-test-* gear/shader in a test config is a runtime-generated test
stub, not a product gear (测试桩非产品档位).

Usage (session p1-002 rework example):
    python -X utf8 tools/p1_verify.py --case CTL-01 \
        --session p1-002 --evidence-dir docs/验证/开发/p1-002/implementer
    python -X utf8 tools/p1_verify.py --all --session p1-002 \
        --evidence-dir docs/验证/开发/p1-002/implementer
    python -X utf8 tools/p1_verify.py --list

Rules honored:
  * live configuration written = false (only temp dirs + this evidence dir);
  * failures are recorded as FAIL, never silently retried into PASS;
  * only PIDs spawned here are terminated;
  * evidence is create-only (限域修正 C): an already-used evidence dir is
    refused before mpv starts; per-case artifacts refuse existing targets;
  * screenshots enter the evidence file list only when the command succeeded
    AND the file exists non-empty (限域修正 B / F-01); failures are recorded
    with an explicit not_generated marker instead of a phantom path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1_lib as lib  # noqa: E402

SESSION = "p1-001"  # default only; the runner requires --session explicitly
STAGE = "P1"
REQUIRED_TEST_IDS = ["CTL-01", "CTL-02", "CTL-03", "CTL-04", "CTL-05", "CTL-06",
                     "CTL-07", "CTL-08", "GEO-01", "GEO-07", "SHD-12", "PIC-05"]

# ---------------------------------------------------------------------------
# shared case scaffolding
# ---------------------------------------------------------------------------

STUB_GEARS = [
    {"id": "p1-test-shader",
     "label": "p1-test-shader" + lib.STUB_LABEL_SUFFIX,
     "set": ["scale=bilinear", "glsl-shaders+=~~/p1-test-stub.glsl"]},
    {"id": "p1-test-b",
     "label": "p1-test-b" + lib.STUB_LABEL_SUFFIX,
     "set": ["glsl-shaders+=~~/p1-test-stub-b.glsl"]},
    {"id": "p1-test-scale",
     "label": "p1-test-scale" + lib.STUB_LABEL_SUFFIX,
     "set": ["scale=spline36"]},
    {"id": "p1-test-geo",
     "label": "p1-test-geo" + lib.STUB_LABEL_SUFFIX,
     "set": ["video-zoom=0.25"]},
    {"id": "p1-test-missing",
     "label": "p1-test-missing" + lib.STUB_LABEL_SUFFIX,
     "set": ["glsl-shaders+=~~/p1-test-nonexistent.glsl"]},
    {"id": "p1-test-badvalue",
     "label": "p1-test-badvalue" + lib.STUB_LABEL_SUFFIX,
     "set": ["scale=p1-test-invalid"]},
]

MANAGED_PROPS = ["glsl-shaders", "scale", "cscale", "dscale", "video-zoom"]


class CaseContext:
    def __init__(self, evidence: lib.Evidence, label: str, stubs: bool = True,
                 playing: bool = True, session: str = SESSION):
        self.evidence = evidence
        self.label = label
        self.session = session
        self.env = lib.make_env(label, session=session)
        self.env.write_mpv_conf(
            scale_baseline="bicubic",
            baseline_shaders=["~~/p1-test-baseline.glsl"],
        )
        self.env.write_input_conf()
        self.env.install_plugin(lib.PLUGIN_LUA)
        self.env.write_scalar_opts()
        self.env.write_gears_conf(lib.GEARS_CONF.read_text(encoding="utf-8"),
                                  stub_gears=STUB_GEARS if stubs else None)
        self.env.write_stub_shaders()
        self.media = None
        self.media_sha = None
        if playing:
            self.media = self.env.root / "media.y4m"
            self.media_sha = lib.generate_y4m(self.media)
        self.session = None
        # P3 harness root-cause fix (P2R-F2/P2S-02): full registry of every
        # session spawned by this case (restarts included).
        self.all_sessions = []

    def start_playing(self, variant: str):
        name = f"{self.label}-{variant}"
        self.session = lib.MpvSession(self.env, name, self.evidence.dir,
                                      session=self.session)
        # P3 harness root-cause fix (P2R-F2/P2S-02): every spawned session is
        # registered so save_session_artifacts can collect its console/mpv.log
        # too — restart sessions (CTL-05/WINDOW-01/GEO-04) no longer leak from
        # the automatic evidence manifest.
        self.all_sessions.append(self.session)
        self.session.start(media=self.media, extra_args=["--loop-file=inf"])
        return self.session

    def start_idle(self, variant: str):
        name = f"{self.label}-{variant}"
        self.session = lib.MpvSession(self.env, name, self.evidence.dir,
                                      session=self.session)
        self.all_sessions.append(self.session)
        self.session.start(media=None, extra_args=["--idle=once"])
        return self.session

    def cleanup(self):
        if self.session is not None and self.session.proc is not None \
                and self.session.proc.poll() is None:
            self.session.kill()
        self.env.cleanup()


def backend_facts(s) -> dict:
    gpu_api = s.get("gpu-api")
    return {
        "mpv_version": s.get("mpv-version"),
        "current_vo": s.get("current-vo"),
        "gpu_api": gpu_api,
        "vulkan_enabled": any(isinstance(x, dict) and x.get("name") == "vulkan"
                              and x.get("enabled") for x in (gpu_api or []))
        if isinstance(gpu_api, list) else None,
    }


def run_selftest(s) -> dict:
    s.cmd("script-message", "scale-selector-selftest")
    ok = s.wait_until(lambda: isinstance(s.ud("selftest"), dict)
                      and s.ud("selftest").get("status") in ("pass", "fail"), 10.0)
    if not ok:
        return {"status": "fail", "error": "selftest result not exported"}
    return s.ud("selftest")


def user_shader_pass_count(s, keywords=None) -> int:
    """P3 harness root-cause fix (P2S-01, brief: “对照计数按实际 DESC 命中 +
    samples 而非 'user shader' 子串”）:

    * with ``keywords``: count the vo-passes entries whose desc actually hits
      one of the given //!DESC keywords AND carries non-empty GPU samples —
      the honest algorithm-presence count. Product gears are ALWAYS counted
      this way (p3_verify never calls this without keywords for them).
    * without ``keywords``: count only the build's label for DESC-LESS user
      shader passes — which is what the DESC-less p1-test-* stubs produce.
      This legacy branch exists solely for the stub-compat P1 cases; it must
      never be used as algorithm-presence proof for a product gear.
    Returns -1 when vo-passes is unavailable (never silently 0).
    """
    vp = s.get("vo-passes")
    if not isinstance(vp, dict):
        return -1
    n = 0
    for frame in ("fresh", "redraw"):
        for item in (vp.get(frame) or []):
            if not isinstance(item, dict):
                continue
            desc = str(item.get("desc", ""))
            samples = item.get("samples") or []
            if keywords:
                if any(kw in desc for kw in keywords) and samples:
                    n += 1
            else:
                if "user shader" in desc:
                    n += 1
    return n


def desc_sample_hits(s, keywords) -> dict:
    """Per-keyword honest hit map: keyword present in a pass desc AND that
    pass carries non-empty GPU samples (P2S-01 fix companion)."""
    out = {}
    vp = s.get("vo-passes")
    joined = []
    if isinstance(vp, dict):
        for frame in ("fresh", "redraw"):
            for item in (vp.get(frame) or []):
                if isinstance(item, dict) and (item.get("samples") or []):
                    joined.append(str(item.get("desc", "")))
    text = "\n".join(joined)
    for kw in keywords or []:
        out[kw] = kw in text
    return out


def relp(p) -> str:
    """Canonical repo-relative POSIX path (evidence lives inside the repo)."""
    return Path(p).resolve().relative_to(lib.REPO_ROOT).as_posix()


def take_screenshot(s, ev: lib.Evidence, filename: str, variant: dict,
                    key: str = "screenshot", mode: str = "subtitles",
                    seen_hashes: dict | None = None):
    """限域修正 B (F-01/R2) + P3 harness root-cause fix (P2R-F1): screenshot
    honesty gate with state/frame binding and duplicate-hash honesty.

    Only a capture whose command succeeded AND whose file exists non-empty is
    returned for the evidence file list; anything else is recorded on the
    variant with an explicit not_generated marker (never a phantom path), and
    the case verdict is unchanged — menu facts are carried by the user-data
    machine-readable export, not by pixels.

    P2R-F1 closure (in-harness, cross-variant):
      * every capture binds the OBSERVATION STATE: player state, chain_epoch,
        and the vo-passes frame counters captured immediately before and after
        the screenshot command (same observation window);
      * PNG dimensions/bit depth are parsed with the TRUE-bitdepth stdlib
        decoder and recorded (an 8-bit parser must never masquerade as
        universal — p3_lib.decode_png handles 8/16-bit);
      * when ``seen_hashes`` (a filename -> sha256 registry shared across the
        case) is given and the new capture byte-matches an earlier one, the
        capture is RETAKEN ONCE after waiting for the frame counters to
        advance; if it is still identical it is honestly marked
        ``non_corroborative`` (identical bytes never count as independent
        evidence; the fact is recorded, not hidden).
    Returns the repo-relative path on success, else None.
    """
    path = ev.dir / filename
    entry = {"file": filename, "mode": mode, "captured": False, "exists": False,
             "not_generated": True}
    result_path = None
    try:
        def _obs():
            vp = s.get("vo-passes") or {}
            counts = {}
            for frame in ("fresh", "redraw"):
                counts[frame] = sum(int(i.get("count") or 0)
                                    for i in (vp.get(frame) or [])
                                    if isinstance(i, dict))
            return {"state": s.ud("state"), "chain_epoch": s.ud("chain_epoch"),
                    "frame_counts": counts}

        s.ensure_screenshot_target(path)  # create-only precheck (raises)
        entry["before"] = _obs()
        ok = s.screenshot(path, mode=mode)
        entry["after"] = _obs()
        entry["command_ok"] = bool(ok)
        entry["exists"] = bool(path.exists() and path.stat().st_size > 0)
        if ok and entry["exists"]:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import p3_lib as _p3  # noqa: E402 — late bind to avoid cycles
            try:
                dec = _p3.decode_png(path.read_bytes())
                entry["png"] = {"w": dec["w"], "h": dec["h"],
                                "bitdepth": dec["bitdepth"],
                                "color_type": dec["color_type"],
                                "true_bitdepth_parser": True}
            except ValueError as png_err:
                entry["png"] = {"error": repr(png_err)}
            entry["sha256"] = lib.sha256_file(path)
            if seen_hashes is not None:
                dup_of = next((fn for fn, h in seen_hashes.items()
                               if h == entry["sha256"]), None)
                if dup_of is not None:
                    # retake ONCE after frames advanced; honest marking if still equal
                    deadline = time.time() + 6.0
                    while time.time() < deadline:
                        cur = _obs()["frame_counts"]
                        if cur != entry["before"]["frame_counts"]:
                            break
                        time.sleep(0.4)
                    retake = ev.dir / (path.stem + "-retake" + path.suffix)
                    if not retake.exists():
                        ok2 = s.screenshot(retake, mode=mode)
                        if ok2 and retake.exists() and retake.stat().st_size > 0:
                            sha2 = lib.sha256_file(retake)
                            entry["retake"] = {"file": retake.name, "sha256": sha2}
                            if sha2 != entry["sha256"]:
                                entry["duplicate_of"] = dup_of
                                entry["resolved_by_retake"] = True
                                path = retake
                                entry["sha256"] = sha2
                            else:
                                entry["duplicate_of"] = dup_of
                                entry["non_corroborative"] = True
                        else:
                            entry["duplicate_of"] = dup_of
                            entry["non_corroborative"] = True
                    else:
                        entry["duplicate_of"] = dup_of
                        entry["non_corroborative"] = True
                seen_hashes[filename] = entry["sha256"]
            entry["captured"] = True
            entry["not_generated"] = False
            result_path = relp(path)
        else:
            entry["reason"] = ("screenshot-to-file 失败或产物缺失/为空"
                               "（如实记录，不列入证据文件）")
    except (lib.IPCError, OSError, ValueError) as error:
        entry["reason"] = f"截图未生成: {error!r}"
    variant[key] = entry
    return result_path


def osd_visibility_probe(s, ctx: CaseContext) -> dict:
    """限域修正 B: empirically probe whether screenshot captures contain the
    OSD menu (subtitles & window modes), instead of claiming it. Probe files
    stay in the throwaway temp shots dir; facts + hashes are recorded.
    menu_visible_in_capture is None when the probe itself could not run."""
    out = {}
    for mode in ("subtitles", "window"):
        open_p = ctx.env.shots / f"osd-probe-{mode}-open.png"
        closed_p = ctx.env.shots / f"osd-probe-{mode}-closed.png"
        fact = {"mode": mode, "probe_ok": False, "menu_visible_in_capture": None}
        try:
            opened = s.open_menu()
            time.sleep(0.4)
            ok1 = s.screenshot(open_p, mode=mode) if opened else False
            closed = s.close_menu()
            time.sleep(0.4)
            ok2 = s.screenshot(closed_p, mode=mode) if closed else False
            fact["probe_ok"] = bool(ok1 and ok2 and open_p.exists() and closed_p.exists())
            if fact["probe_ok"]:
                sha_open = lib.sha256_file(open_p)
                sha_closed = lib.sha256_file(closed_p)
                fact["sha_menu_open"] = sha_open
                fact["sha_menu_closed"] = sha_closed
                fact["menu_visible_in_capture"] = sha_open != sha_closed
        except (lib.IPCError, OSError, ValueError) as error:
            fact["error"] = repr(error)
        out[mode] = fact
    return out


def save_session_artifacts(ctx: CaseContext, evidence_names: list) -> list:
    files = []
    # P3 harness root-cause fix (P2R-F2/P2S-02): collect artifacts from EVERY
    # session this case spawned (restart sessions included), not just the
    # last one; per-session transcripts keep unique names.
    sessions = list(getattr(ctx, "all_sessions", []) or [])
    if ctx.session is not None and ctx.session not in sessions:
        sessions.append(ctx.session)
    seen_tnames = set()
    for s in sessions:
        if s is None:
            continue
        if s.log_path.exists():
            files.append(relp(s.log_path))
        if getattr(s, "console_path", None) and s.console_path.exists():
            files.append(relp(s.console_path))
        if s.ipc is not None and s.ipc.transcript:
            base = s.log_path.stem
            tname = base + ".transcript.jsonl"
            i = 1
            while tname in seen_tnames:
                i += 1
                tname = f"{base}.transcript-{i}.jsonl"
            seen_tnames.add(tname)
            p = ctx.evidence.save_transcript(tname, s.ipc.transcript)
            files.append(relp(p))
    # record runtime-generated inputs (test stubs + synthetic media) with
    # hashes; name keeps the FIRST session's case_name for uniqueness (a case
    # may spawn several contexts with the same label but distinct variants).
    first = next((s for s in sessions if s is not None), None)
    base_name = first.case_name if first is not None else ctx.label
    inputs_path = ctx.evidence.write_json(base_name + ".inputs.json", {
        "note": "运行时生成的测试桩与合成输入；测试桩非产品档位",
        "config_dir_files_sha256": ctx.env.inputs,
        "media_sha256": ctx.media_sha,
    })
    files.append(relp(inputs_path))
    return files


# ---------------------------------------------------------------------------
# CTL-01 — F8 binding, menu open/close, state display vs glsl-shaders/vo-passes
# ---------------------------------------------------------------------------

def case_ctl01(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-01", "variants": [], "files": [], "facts": {}}
    static = lib.audit_plugin_source()
    conf_audit = lib.audit_gears_conf()
    result["facts"]["plugin_source_audit"] = static
    result["facts"]["gears_conf_audit"] = conf_audit
    if not static["binds_only_menu_key"]:
        result["status"] = "FAIL"
        result["error"] = "plugin source binding audit failed"
        return result

    # variant a: idle, product gears only
    ctx = CaseContext(ev, "CTL-01", stubs=False, playing=False, session=SESSION)
    try:
        s = ctx.start_idle("a-idle")
        st = run_selftest(s)
        ok = st.get("status") == "pass"
        opened = s.open_menu()
        entries_idle = s.menu_entries()
        off_entry = next((e for e in entries_idle if e.get("id") == "off"), None)
        variant = {
            "name": "idle-product-gears",
            "selftest": st.get("status"),
            "selftest_cases": len(st.get("cases", [])),
            "menu_open_ok": opened,
            "menu_close_ok": None,
            "entry_count": len(entries_idle),
            "off_first_enabled": bool(off_entry and off_entry.get("enabled")),
            "disabled_count": sum(1 for e in entries_idle if not e.get("enabled")),
            "reserved_entries_all_disabled": all(
                not e.get("enabled") for e in entries_idle
                if e.get("id") != "off"),
            "backend": backend_facts(s),
        }
        # 限域修正 B: idle (no video) captures genuinely fail here; the failure
        # is recorded on the variant, never as a phantom evidence path.
        shot_idle = take_screenshot(s, ev, "CTL-01-menu-idle.png", variant)
        closed = s.close_menu()
        variant["menu_close_ok"] = closed
        # F8 toggle stability: 4 rapid toggles
        toggles = []
        for _ in range(4):
            s.key("F8", delay=0.15)
            toggles.append(bool(s.ud("menu_open")))
        s.close_menu()
        variant["rapid_toggles"] = toggles
        ok = ok and opened and closed and len(entries_idle) == 11 \
            and off_entry and off_entry.get("enabled") \
            and variant["disabled_count"] == 10 \
            and variant["reserved_entries_all_disabled"] \
            and toggles == [True, False, True, False]
        result["variants"].append(variant)
        if shot_idle:
            result["files"].append(shot_idle)
        result["files"] += save_session_artifacts(ctx, [])
    finally:
        ctx.cleanup()
    if not ok:
        result["status"] = "FAIL"
        return result

    # variant b: playing with stub gears; display must match glsl-shaders/vo-passes
    ctx = CaseContext(ev, "CTL-01", stubs=True, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("b-playing")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict)
                          and (s.get("vo-passes").get("fresh") or []), 15.0)
        count_off = user_shader_pass_count(s)
        glsl_off = s.get("glsl-shaders")
        nav = s.navigate_and_activate("p1-test-shader")
        ok = ok and nav and s.wait_state("active", 6.0)
        count_active = user_shader_pass_count(s)
        glsl_active = s.get("glsl-shaders")
        scale_active = s.get("scale")
        opened = s.open_menu()
        entries = s.menu_entries()
        consistent = (
            isinstance(glsl_active, list)
            and "~~/p1-test-stub.glsl" in glsl_active
            and "~~/p1-test-baseline.glsl" in glsl_active
            and scale_active == "bilinear"
            and count_active == count_off + 1
            and any(e.get("id") == "p1-test-shader" and e.get("enabled") for e in entries)
        )
        variant = {
            "name": "playing-stub-active",
            "menu_nav_ok": nav,
            "state": s.ud("state"),
            "gear": s.ud("gear"),
            "glsl_off": glsl_off,
            "glsl_active": glsl_active,
            "scale_active": scale_active,
            "user_shader_passes_off": count_off,
            "user_shader_passes_active": count_active,
            "menu_display_consistent_with_facts": consistent,
            "backend": backend_facts(s),
        }
        shot_menu = take_screenshot(s, ev, "CTL-01-menu-playing-active.png", variant)
        s.close_menu()
        # 限域修正 B: empirical OSD-visibility probe — do screenshots contain
        # the menu? Measured, not claimed (probe files stay in the temp env).
        variant["osd_probe"] = osd_visibility_probe(s, ctx)
        ok = ok and consistent
        result["variants"].append(variant)
        if shot_menu:
            result["files"].append(shot_menu)
        result["files"] += save_session_artifacts(ctx, [])
    finally:
        ctx.cleanup()

    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-02 — Off restores only managed & unmodified properties; no glsl-shaders-clr
# ---------------------------------------------------------------------------

def case_ctl02(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-02", "variants": [], "files": [], "facts": {}}
    result["facts"]["plugin_source_audit"] = lib.audit_plugin_source()
    ok = True
    ctx = CaseContext(ev, "CTL-02", stubs=True, playing=True)
    try:
        s = ctx.start_playing("main")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        pre = {p: s.get(p) for p in ["glsl-shaders", "scale", "cscale", "dscale"]}
        nav = s.navigate_and_activate("p1-test-shader")
        ok = ok and nav and s.wait_state("active", 6.0)
        mid = {p: s.get(p) for p in ["glsl-shaders", "scale", "cscale", "dscale"]}
        baseline = s.ud("baseline")
        last = s.ud("last_written")
        wrote = s.ud("wrote")
        current = {p: s.get(p) for p in MANAGED_PROPS}
        exp_restores, exp_kept = lib.expected_off_actions(baseline, last, wrote,
                                                          s.ud("owned_shaders"), current)
        # 关 via the real menu
        nav = s.navigate_and_activate("off")
        ok = ok and nav and s.wait_state("off", 6.0)
        post = {p: s.get(p) for p in ["glsl-shaders", "scale", "cscale", "dscale"]}
        report = s.ud("off_report") or {}
        matches = (
            lib.close_enough(post["glsl-shaders"], pre["glsl-shaders"])
            and post["scale"] == pre["scale"]
            and post["cscale"] == pre["cscale"]
            and post["dscale"] == pre["dscale"]
            and exp_kept == {}
            and all(lib.close_enough(post[p], v) for p, v in exp_restores.items())
        )
        passes_back = user_shader_pass_count(s) >= 1  # baseline shader still active
        variant = {
            "name": "off-restores-baseline",
            "pre": pre, "mid": mid, "post": post,
            "expected_restores": exp_restores,
            "expected_kept": exp_kept,
            "off_report": report,
            "restores_match_oracle": matches,
            "baseline_shader_still_listed": passes_back,
            "ud_cleared": (s.ud_empty(s.ud("baseline")) and s.ud_empty(s.ud("wrote"))
                           and s.ud_empty(s.ud("owned_shaders"))),
            "backend": backend_facts(s),
        }
        ok = ok and matches and variant["ud_cleared"] and passes_back \
            and result["facts"]["plugin_source_audit"]["no_glsl_shaders_clr"]
        result["variants"].append(variant)
        result["files"] += save_session_artifacts(ctx, [])
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-03 — external chain change → external state, plugin yields, never overwrites
# ---------------------------------------------------------------------------

def case_ctl03(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-03", "variants": [], "files": [], "facts": {}}
    variants = [
        ("a-ctrl1-append", "key_CTRL+1"),
        ("b-f6-scale", "key_F6"),
        ("c-ipc-setproperty", "ipc_set_property"),
        ("d-ctrl0-clr", "key_CTRL+0"),
    ]
    ok = True
    for variant_name, method in variants:
        ctx = CaseContext(ev, "CTL-03", stubs=True, playing=True, session=SESSION)
        try:
            s = ctx.start_playing(variant_name)
            vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
            nav = s.navigate_and_activate("p1-test-shader")
            vok = vok and nav and s.wait_state("active", 6.0)
            glsl_before = s.get("glsl-shaders")
            scale_before = s.get("scale")
            if method == "key_CTRL+1":
                s.key("CTRL+1", delay=0.5)
                exp_glsl = (glsl_before or []) + ["~~/p1-test-ext-a.glsl"]
            elif method == "key_F6":
                s.key("F6", delay=0.5)
                exp_glsl = glsl_before
            elif method == "ipc_setproperty":
                new_list = list(glsl_before or []) + ["~~/p1-test-ext-b.glsl"]
                r = s.set("glsl-shaders", new_list)
                vok = vok and r.get("error") == "success"
                exp_glsl = new_list
            else:
                s.key("CTRL+0", delay=0.5)
                exp_glsl = []
            vok = vok and s.wait_state("external", 6.0)
            reason = s.ud("reason") or ""
            # yield check: sample three times over ~2s; plugin must not rewrite
            samples = []
            for _ in range(3):
                time.sleep(0.7)
                samples.append((s.get("glsl-shaders"), s.get("scale")))
            scale_expected = "spline36" if method == "key_F6" else scale_before
            stable = all(
                lib.close_enough(g, exp_glsl) and sc == scale_expected
                for g, sc in samples
            )
            menu_ok = s.open_menu()
            entries = s.menu_entries()
            # 关 from external only happens in CTL-08; here verify no auto-off
            not_off = s.ud("state") == "external"
            variant = {
                "name": variant_name,
                "method": method,
                "external_state": not_off,
                "reason": reason,
                "glsl_expected": exp_glsl,
                "glsl_samples": [g for g, _ in samples],
                "yielded_stable": stable,
                "menu_open_ok": menu_ok,
                "menu_entry_count": len(entries),
                "backend": backend_facts(s),
            }
            shot = take_screenshot(s, ev, f"CTL-03-{variant_name}-menu.png", variant)
            s.close_menu()
            vok = vok and not_off and stable and menu_ok
            if method in ("key_CTRL+1", "ipc_setproperty", "key_CTRL+0"):
                vok = vok and "glsl-shaders" in reason
            if method == "key_F6":
                vok = vok and "scale" in reason
            result["variants"].append(variant)
            if shot:
                result["files"].append(shot)
            result["files"] += save_session_artifacts(ctx, [])
            ok = ok and vok
        finally:
            ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-04 — rapid switching: no residue, unique final state, no crash
# ---------------------------------------------------------------------------

def case_ctl04(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-04", "variants": [], "files": [], "facts": {}}
    ok = True
    ctx = CaseContext(ev, "CTL-04", stubs=True, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("rapid")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        pre = {p: s.get(p) for p in ["glsl-shaders", "scale"]}
        t0 = time.time()
        # 3 fast cycles: shader → b → scale → off, plus rapid menu toggles
        for cycle in range(3):
            for gear in ("p1-test-shader", "p1-test-b", "p1-test-scale", "off"):
                if not s.navigate_and_activate(gear):
                    ok = False
            for _ in range(2):
                s.key("F8", delay=0.05)
        elapsed = time.time() - t0
        final_off_ok = s.wait_state("off", 6.0)
        time.sleep(1.5)
        post = {p: s.get(p) for p in ["glsl-shaders", "scale"]}
        alive = s.proc.poll() is None
        passes_final = user_shader_pass_count(s)
        log_clean = True
        if s.log_path.exists():
            txt = s.log_path.read_text(encoding="utf-8", errors="replace")
            log_clean = ("panicked" not in txt) and ("lua error" not in txt.lower())
        end_expected = lib.close_enough(post["glsl-shaders"], pre["glsl-shaders"]) \
            and post["scale"] == pre["scale"]
        v1 = {
            "name": "12 rapid switches ending off",
            "elapsed_s": round(elapsed, 2),
            "final_state_off": bool(final_off_ok),
            "pre": pre, "post": post,
            "final_matches_off": end_expected,
            "mpv_alive": alive,
            "user_shader_passes_final": passes_final,
            "log_clean": log_clean,
            "backend": backend_facts(s),
        }
        result["variants"].append(v1)
        ok = ok and final_off_ok and end_expected and alive and log_clean

        # variant 2: rapid, ending on a stub gear
        for gear in ("p1-test-scale", "p1-test-shader", "p1-test-b"):
            if not s.navigate_and_activate(gear):
                ok = False
        active_ok = s.wait_state("active", 6.0)
        gear = s.ud("gear")
        time.sleep(1.5)
        post2 = {p: s.get(p) for p in ["glsl-shaders", "scale"]}
        exp_list = lib.expected_gear_list(pre["glsl-shaders"], [], adds=["~~/p1-test-stub-b.glsl"])
        match2 = lib.close_enough(post2["glsl-shaders"], exp_list) and post2["scale"] == pre["scale"]
        v2 = {
            "name": "rapid switch ending on p1-test-b",
            "final_state_active": bool(active_ok),
            "gear": gear,
            "post": post2,
            "expected_list": exp_list,
            "final_matches": match2,
            "backend": backend_facts(s),
        }
        result["variants"].append(v2)
        result["files"] += save_session_artifacts(ctx, [])
        ok = ok and active_ok and gear == "p1-test-b" and match2
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-05 — quit/restart in each state: no cross-session residue (no persistence)
# ---------------------------------------------------------------------------

def case_ctl05(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-05", "variants": [], "files": [], "facts": {}}
    ok = True
    setups = ["off", "active", "external", "fallback"]
    for state in setups:
        ctx = CaseContext(ev, "CTL-05", stubs=True, playing=True, session=SESSION)
        try:
            s = ctx.start_playing(state)
            sok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
            if state != "off":
                sok = sok and s.navigate_and_activate("p1-test-shader") \
                    and s.wait_state("active", 6.0)
            if state == "external":
                s.key("CTRL+1", delay=0.5)
                sok = sok and s.wait_state("external", 6.0)
            if state == "fallback":
                sok = sok and s.navigate_and_activate("p1-test-missing") \
                    and s.wait_state("fallback", 6.0)
            state_before = s.ud("state")
            manifest_before = ctx.env.snapshot_manifest()
            watch_later_before = sorted(p.name for p in ctx.env.watch_later.rglob("*"))
            quit_ok = s.quit()
            exit_code = s.wait_exit(20.0)
            manifest_after = ctx.env.snapshot_manifest()
            watch_later_after = sorted(p.name for p in ctx.env.watch_later.rglob("*"))
            no_persist = manifest_before == manifest_after \
                and watch_later_before == watch_later_after
            # relaunch with the same config dir; P1 must come back in off
            s2 = lib.MpvSession(ctx.env, f"CTL-05-{state}-restart", ev.dir,
                                 session=SESSION)
            s2.start(media=ctx.media, extra_args=["--loop-file=inf"])
            try:
                restarted_off = s2.wait_state("off", 8.0)
                glsl = s2.get("glsl-shaders")
                scale = s2.get("scale")
                clean = lib.close_enough(glsl, ["~~/p1-test-baseline.glsl"]) \
                    and scale == "bicubic"
                variant = {
                    "name": f"quit-restart-from-{state}",
                    "state_before": state_before,
                    "quit_ok": quit_ok,
                    "exit_code": exit_code,
                    "config_dir_unchanged": no_persist,
                    "restarted_state_off": bool(restarted_off),
                    "restarted_glsl": glsl,
                    "restarted_scale": scale,
                    "restarted_clean": clean,
                    "backend": backend_facts(s2),
                }
                sok = sok and quit_ok and exit_code == 0 and no_persist \
                    and restarted_off and clean
            finally:
                if s2.proc is not None and s2.proc.poll() is None:
                    s2.kill()
            result["variants"].append(variant)
            result["files"] += save_session_artifacts(ctx, [])
            if s2.log_path.exists():
                result["files"].append(relp(s2.log_path))
            if s2.ipc is not None and s2.ipc.transcript:
                p = ev.save_transcript(s2.log_path.stem + ".transcript.jsonl",
                                       s2.ipc.transcript)
                result["files"].append(relp(p))
            ok = ok and sok
        finally:
            ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-06 — corrupt/invalid plugin config: degrade with reasons, never crash
# ---------------------------------------------------------------------------

def case_ctl06(ev: lib.Evidence) -> dict:
    """限域修正 A：损坏/恶意配置邻近变体全簇——
      a 缺 gears 键（回退内建默认）      b 非法 id
      c 坏 _set                          d 重复键/未知键（原 R1 冻结证据变体）
      e 保留 id 显式 active+_set+_label  （LS1 冒名攻击，必须 disabled+固定身份）
      f 自定义 active 档位用保留名 label （BCAS 冒名，必须拒绝）
      g 重复 id + off 不在首位           （必须合并且 off 提到首项）
      h gears 缺 off                     （必须自动补在首位且可用）
    任意变体下：off 恒在首项且可用；保留 id 恒 disabled；菜单可用；mpv 存活。"""
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
        # e: 保留 id 冒名攻击（R1/F-03 主案例的入口邻近变体）
        "e-reserved-id-active-set": "gears=off,ls1\noff_label=关\n"
                                    "ls1_label=超级LS1\n"
                                    "ls1_mode=active\n"
                                    "ls1_set=scale=bilinear;glsl-shaders+=~~/p1-test-stub.glsl\n"
                                    "ls1_reason=已被替代，可用\n",
        # f: 自定义 active 档位借保留算法名冒名
        "f-impersonating-label": "gears=off,p1-test-fake\n"
                                 "p1_test_fake_mode=active\n"
                                 "p1_test_fake_label=BCAS\n"
                                 "p1_test_fake_set=scale=bilinear\n",
        # g: 重复 id + off 不在首位
        "g-duplicate-and-late-off": "gears=ls1,ls1,off,off\n",
        # h: gears 缺 off
        "h-missing-off": "gears=ls1,p1-test-shader\n" + stub_shader,
    }
    for name, conf_text in variants.items():
        ctx = CaseContext(ev, "CTL-06", stubs=True, playing=False, session=SESSION)
        # overwrite the generated conf with the raw variant
        ctx.env.write_raw_gears_conf(conf_text)
        try:
            s = ctx.start_idle(name)
            st = run_selftest(s)
            opened = s.open_menu()
            entries = s.menu_entries()
            off_entry = next((e for e in entries if e.get("id") == "off"), None)
            broken_entry = next((e for e in entries if e.get("id") == "p1-test-broken"), None)
            # mpv must remain usable
            alive = s.proc.poll() is None
            by_id = {e.get("id"): e for e in entries}
            variant = {
                "name": name,
                "selftest": st.get("status"),
                "menu_open_ok": opened,
                "entry_ids": [e.get("id") for e in entries],
                "entry_count": len(entries),
                "off_first_enabled": bool(entries and entries[0].get("id") == "off"
                                          and entries[0].get("enabled")),
                "off_enabled": bool(off_entry and off_entry.get("enabled")),
                "reserved_ids_all_disabled": all(
                    (e.get("enabled") is False) for gid, e in by_id.items()
                    if gid in ("ls1", "fsr1", "nis", "sgsr1", "bcas", "anime4k",
                               "xbr", "sharpbilinear", "integer", "nearest")),
                "broken_entry": broken_entry,
                "mpv_alive": alive,
                "backend": backend_facts(s),
            }
            shot = take_screenshot(s, ev, f"CTL-06-{name}.png", variant)
            s.close_menu()
            if name == "c-broken-set":
                # broken gear disabled with reason; sibling stub still selectable
                nav = s.navigate_and_activate("p1-test-shader")
                worked = nav and s.wait_state("active", 6.0)
                vok = opened and off_entry and broken_entry \
                    and broken_entry.get("enabled") is False \
                    and "配置错误" in (broken_entry.get("reason") or "") and worked
                variant["sibling_stub_still_selectable"] = bool(worked)
            elif name == "e-reserved-id-active-set":
                ls1 = by_id.get("ls1") or {}
                nav = s.navigate_and_activate("ls1")
                refused = (not nav) and s.ud("state") != "active" \
                    and s.ud("gear") != "ls1"
                variant["ls1_entry"] = ls1
                variant["activation_refused"] = bool(refused)
                vok = (opened and variant["off_first_enabled"]
                       and variant["reserved_ids_all_disabled"]
                       and ls1.get("label") == "LS1"
                       and "无公开源码" in (ls1.get("reason") or "")
                       and bool(refused))
            elif name == "f-impersonating-label":
                fake = by_id.get("p1-test-fake") or {}
                nav = s.navigate_and_activate("p1-test-fake")
                refused = (not nav) and s.ud("state") != "active"
                variant["fake_entry"] = fake
                variant["impersonation_refused"] = bool(refused)
                vok = (opened and variant["off_first_enabled"]
                       and fake.get("enabled") is False
                       and fake.get("label") == "p1-test-fake"
                       and "配置错误" in (fake.get("reason") or "")
                       and bool(refused))
            elif name == "g-duplicate-and-late-off":
                vok = (opened and variant["off_first_enabled"]
                       and variant["reserved_ids_all_disabled"]
                       and variant["entry_ids"] == ["off", "ls1"])
            elif name == "h-missing-off":
                nav = s.navigate_and_activate("p1-test-shader")
                worked = nav and s.wait_state("active", 6.0)
                variant["stub_still_selectable"] = bool(worked)
                vok = opened and variant["off_first_enabled"] and bool(worked)
            elif name == "d-duplicate-unknown-keys":
                ls1 = by_id.get("ls1") or {}
                vok = (opened and variant["off_first_enabled"]
                       and variant["reserved_ids_all_disabled"]
                       and ls1.get("label") == "LS1")
            else:
                vok = opened and variant["off_first_enabled"] \
                    and variant["reserved_ids_all_disabled"]
            result["variants"].append(variant)
            if shot:
                result["files"].append(shot)
            result["files"] += save_session_artifacts(ctx, [])
            ok = ok and vok and alive and st.get("status") == "pass"
        finally:
            ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-07 — missing resource / invalid value → fallback with true reason, no residue
# ---------------------------------------------------------------------------

def case_ctl07(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-07", "variants": [], "files": [], "facts": {}}
    ok = True
    ctx = CaseContext(ev, "CTL-07", stubs=True, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("fallback")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        pre = {p: s.get(p) for p in ["glsl-shaders", "scale"]}

        # 1. missing shader file (first activation → release to fallback/off-stable)
        nav = s.navigate_and_activate("p1-test-missing")
        ok = ok and nav and s.wait_state("fallback", 6.0)
        reason_missing = s.ud("reason") or ""
        after_missing = {p: s.get(p) for p in ["glsl-shaders", "scale"]}
        released = s.ud_empty(s.ud("baseline")) and s.ud("stable_gear") == "off"

        # 2. good gear still works after fallback
        nav = s.navigate_and_activate("p1-test-shader")
        ok = ok and nav and s.wait_state("active", 6.0)
        mid = {p: s.get(p) for p in ["glsl-shaders", "scale"]}

        # 3. invalid property value (mpv rejects) → rollback, no half chain
        nav = s.navigate_and_activate("p1-test-badvalue")
        ok = ok and nav and s.wait_state("fallback", 8.0)
        reason_bad = s.ud("reason") or ""
        after_bad = {p: s.get(p) for p in ["glsl-shaders", "scale"]}
        stable_kept = s.ud("stable_gear") == "p1-test-shader"

        # 4. off restores baseline
        nav = s.navigate_and_activate("off")
        ok = ok and nav and s.wait_state("off", 6.0)
        post = {p: s.get(p) for p in ["glsl-shaders", "scale"]}

        residue_free = (
            lib.close_enough(after_missing["glsl-shaders"], pre["glsl-shaders"])
            and after_missing["scale"] == pre["scale"]
            and lib.close_enough(after_bad["glsl-shaders"], mid["glsl-shaders"])
            and after_bad["scale"] == mid["scale"]
            and lib.close_enough(post["glsl-shaders"], pre["glsl-shaders"])
            and post["scale"] == pre["scale"]
        )
        reasons_real = ("shader 文件缺失" in reason_missing
                        and "p1-test-nonexistent.glsl" in reason_missing
                        and reason_bad != "")
        variant = {
            "name": "missing-shader-and-invalid-value",
            "reason_missing_shader": reason_missing,
            "reason_invalid_value": reason_bad,
            "pre": pre, "after_missing": after_missing, "mid": mid,
            "after_bad": after_bad, "post": post,
            "released_after_first_failure": released,
            "stable_kept_after_switch_failure": stable_kept,
            "residue_free": residue_free,
            "reasons_real": reasons_real,
            "backend": backend_facts(s),
        }
        s.open_menu()
        shot = take_screenshot(s, ev, "CTL-07-fallback-menu.png", variant)
        s.close_menu()
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += save_session_artifacts(ctx, [])
        ok = ok and residue_free and reasons_real and released and stable_kept
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# CTL-08 — external then Off: diff-based restore, no stale overwrite
# ---------------------------------------------------------------------------

def case_ctl08(ev: lib.Evidence) -> dict:
    result = {"id": "CTL-08", "variants": [], "files": [], "facts": {}}
    ok = True
    for variant_name, also_touch_scale in (("a-shader-external", False),
                                           ("b-shader-and-scale-external", True)):
        ctx = CaseContext(ev, "CTL-08", stubs=True, playing=True, session=SESSION)
        try:
            s = ctx.start_playing(variant_name)
            vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
            vok = vok and s.navigate_and_activate("p1-test-shader") \
                and s.wait_state("active", 6.0)
            baseline = s.ud("baseline")
            last = s.ud("last_written")
            wrote = s.ud("wrote")
            owned = s.ud("owned_shaders")
            # external: user appends a shader (keystroke path)
            s.key("CTRL+1", delay=0.5)
            vok = vok and s.wait_state("external", 6.0)
            if also_touch_scale:
                s.key("F6", delay=0.5)
                vok = vok and s.wait_state("external", 6.0)
            current = {p: s.get(p) for p in MANAGED_PROPS}
            exp_restores, exp_kept = lib.expected_off_actions(
                baseline, last, wrote, owned, current)
            vok = vok and s.navigate_and_activate("off") and s.wait_state("off", 6.0)
            post = {p: s.get(p) for p in MANAGED_PROPS}
            report = s.ud("off_report") or {}
            # oracle: post must equal expected restores for restored props and
            # equal external values for kept props
            match = True
            for p, v in exp_restores.items():
                match = match and lib.close_enough(post.get(p), v)
            for p in exp_kept:
                if p in exp_restores:
                    # element-level list restore already checked above
                    continue
                match = match and lib.close_enough(post.get(p), current.get(p))
            glsl_kept_external_entry = "~~/p1-test-ext-a.glsl" in (post["glsl-shaders"] or [])
            no_stub_left = "~~/p1-test-stub.glsl" not in (post["glsl-shaders"] or [])
            scale_ok = (post["scale"] == ("spline36" if also_touch_scale else "bicubic"))
            variant = {
                "name": variant_name,
                "baseline": baseline, "last_written": last, "wrote": wrote,
                "current_at_off": current,
                "expected_restores": exp_restores,
                "expected_kept": sorted(exp_kept.keys()),
                "post": post,
                "off_report": report,
                "matches_oracle": match,
                "glsl_kept_external_entry": glsl_kept_external_entry,
                "no_plugin_stub_left": no_stub_left,
                "scale_ok": scale_ok,
                "backend": backend_facts(s),
            }
            vok = vok and match and glsl_kept_external_entry and no_stub_left and scale_ok
            result["variants"].append(variant)
            result["files"] += save_session_artifacts(ctx, [])
            ok = ok and vok
        finally:
            ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# GEO-01 — geometry target-size source audit (no feedback path)
# ---------------------------------------------------------------------------

def case_geo01(ev: lib.Evidence) -> dict:
    result = {"id": "GEO-01", "variants": [], "files": [], "facts": {}}
    static = lib.audit_plugin_source()
    result["facts"]["plugin_source_audit"] = static
    ok = static["geometry_reads_vop_only"]
    ctx = CaseContext(ev, "GEO-01", stubs=True, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("main")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        st = run_selftest(s)
        geo_case = next((c for c in st.get("cases", [])
                         if c.get("name", "").startswith("geo01")), {})
        # exercise a geometry-touching stub gear
        nav = s.navigate_and_activate("p1-test-geo")
        ok = ok and nav and s.wait_state("active", 6.0)
        zoom_active = s.get("video-zoom")
        nav = s.navigate_and_activate("p1-test-shader")
        ok = ok and nav and s.wait_state("active", 6.0)
        zoom_restored = s.get("video-zoom")
        nav = s.navigate_and_activate("off")
        ok = ok and nav and s.wait_state("off", 6.0)
        journal = s.ud("read_journal") or []
        allow = set(lib.ALLOWED_JOURNAL_PROPS) | {"video-zoom"}
        offending = sorted({p for p in journal if p not in allow})
        journal_clean = (offending == [])
        variant = {
            "name": "journal-audit",
            "selftest_geo_case": geo_case,
            "video_zoom_active": zoom_active,
            "video_zoom_restored": zoom_restored,
            "journal_len": len(journal),
            "journal_props_seen": sorted(set(journal)),
            "offending_reads": offending,
            "journal_clean": journal_clean,
            "backend": backend_facts(s),
        }
        result["variants"].append(variant)
        result["files"] += save_session_artifacts(ctx, [])
        ok = ok and journal_clean and st.get("status") == "pass" \
            and lib.close_enough(zoom_active, 0.25) and lib.close_enough(zoom_restored, 0)
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# GEO-07 — fullscreen/minimize with an active gear: state and geometry hold
# ---------------------------------------------------------------------------

def case_geo07(ev: lib.Evidence) -> dict:
    result = {"id": "GEO-07", "variants": [], "files": [], "facts": {}}
    ok = True
    ctx = CaseContext(ev, "GEO-07", stubs=True, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("main")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        ok = ok and s.navigate_and_activate("p1-test-shader") and s.wait_state("active", 6.0)
        pre = {"glsl": s.get("glsl-shaders"), "scale": s.get("scale"),
               "zoom": s.get("video-zoom"), "state": s.ud("state")}
        # fullscreen on
        s.cmd("cycle", "fullscreen")
        time.sleep(1.2)
        fs_on = s.get("fullscreen")
        hold_fs = (s.ud("state") == "active"
                   and lib.close_enough(s.get("glsl-shaders"), pre["glsl"]))
        # fullscreen capture while mpv is alive (honesty-gated, subtitles mode)
        variant_capture = {}
        shot_fs = take_screenshot(s, ev, "GEO-07-fullscreen.png", variant_capture)
        # minimize and restore
        s.set("window-minimized", True)
        time.sleep(1.2)
        minimized = s.get("window-minimized")
        s.set("window-minimized", False)
        time.sleep(1.0)
        hold_min = (s.ud("state") == "active"
                    and lib.close_enough(s.get("glsl-shaders"), pre["glsl"]))
        # fullscreen off
        s.cmd("cycle", "fullscreen")
        time.sleep(1.2)
        fs_off = s.get("fullscreen")
        post = {"glsl": s.get("glsl-shaders"), "scale": s.get("scale"),
                "zoom": s.get("video-zoom"), "state": s.ud("state")}
        backend = backend_facts(s)
        stable = all(lib.close_enough(pre[k], post[k]) for k in ("glsl", "scale", "zoom")) \
            and post["state"] == "active"
        alive = s.proc.poll() is None
        quit_ok = s.quit()
        variant = {
            "name": "fullscreen-and-minimize-with-active-gear",
            "fullscreen_on": fs_on, "minimized_flag_during": minimized,
            "fullscreen_off_after": fs_off,
            "state_held_fullscreen": hold_fs,
            "state_held_minimize": hold_min,
            "pre": pre, "post": post,
            "state_and_geometry_stable": stable,
            "mpv_alive_after_interactions": alive,
            "quit_ok": quit_ok,
            "backend": backend,
        }
        variant.update(variant_capture)  # merges fullscreen_capture fact
        result["variants"].append(variant)
        if shot_fs:
            result["files"].append(shot_fs)
        result["files"] += save_session_artifacts(ctx, [])
        ok = ok and fs_on is True and fs_off is False and hold_fs and hold_min \
            and stable and alive and quit_ok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# SHD-12 — LS1/BCAS disabled entries with true reasons; never selectable
# ---------------------------------------------------------------------------

def case_shd12(ev: lib.Evidence) -> dict:
    """限域修正 A：产品 conf 下 LS1/BCAS 禁用+真实原因+不可选（变体 main），
    以及本地 conf 攻击变体（conf-attack）：显式 active+_set+_label/_reason
    覆盖也必须保持 disabled、固定标签/原因、激活被拒。"""
    result = {"id": "SHD-12", "variants": [], "files": [], "facts": {}}
    conf_audit = lib.audit_gears_conf()
    result["facts"]["gears_conf_audit"] = conf_audit
    ok = all(conf_audit.values())

    def probe_disabled_entries(s, entries):
        ls1 = next((e for e in entries if e.get("id") == "ls1"), None)
        bcas = next((e for e in entries if e.get("id") == "bcas"), None)
        # cursor must never land on disabled entries while traversing the menu
        visited = []
        for _ in range(len(entries) + 2):
            sel = [e.get("id") for e in s.menu_entries() if e.get("selected")]
            visited += sel
            s.key("DOWN", delay=0.08)
        visited_clean = "ls1" not in visited and "bcas" not in visited
        policy_ok = bool(
            ls1 and bcas
            and ls1.get("enabled") is False and bcas.get("enabled") is False
            and all(k in (ls1.get("reason") or "") for k in ("无公开源码", "权重", "移植许可"))
            and "身份未核实" in (bcas.get("reason") or "")
            and "不以CAS/Bicubic+CAS冒名" in (bcas.get("reason") or "")
        )
        labels_ok = bool(ls1 and bcas and ls1.get("label") == "LS1" and bcas.get("label") == "BCAS")
        return ls1, bcas, visited, visited_clean, policy_ok, labels_ok

    # variant main: shipped product gear table
    ctx = CaseContext(ev, "SHD-12", stubs=False, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("main")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        opened = s.open_menu()
        entries = s.menu_entries()
        ls1, bcas, visited, visited_clean, policy_ok, labels_ok = \
            probe_disabled_entries(s, entries)
        variant = {
            "name": "ls1-bcas-disabled",
            "menu_open_ok": opened,
            "ls1_entry": ls1, "bcas_entry": bcas,
            "cursor_path": visited,
            "cursor_never_on_disabled": visited_clean,
            "policy_reasons_ok": policy_ok,
            "labels_not_substituted": labels_ok,
            "backend": backend_facts(s),
        }
        shot = take_screenshot(s, ev, "SHD-12-menu.png", variant)
        s.close_menu()
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += save_session_artifacts(ctx, [])
        ok = ok and opened and policy_ok and visited_clean and labels_ok
    finally:
        ctx.cleanup()

    # variant conf-attack: local conf tries to activate LS1/BCAS and rename them
    attack_conf = (
        "gears=off,ls1,bcas\n"
        "off_label=关\n"
        "ls1_label=超级LS1\n"
        "ls1_mode=active\n"
        "ls1_set=scale=bilinear;glsl-shaders+=~~/p1-test-stub.glsl\n"
        "ls1_reason=已被替代，可用\n"
        "bcas_label=Bicubic+CAS\n"
        "bcas_mode=active\n"
        "bcas_set=glsl-shaders+=~~/p1-test-stub.glsl\n"
    )
    ctx = CaseContext(ev, "SHD-12", stubs=False, playing=True, session=SESSION)
    ctx.env.write_raw_gears_conf(attack_conf)
    try:
        s = ctx.start_playing("conf-attack")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        opened = s.open_menu()
        entries = s.menu_entries()
        ls1, bcas, visited, visited_clean, policy_ok, labels_ok = \
            probe_disabled_entries(s, entries)
        nav_ls1 = s.navigate_and_activate("ls1")
        nav_bcas = s.navigate_and_activate("bcas")
        refused = ((not nav_ls1) and (not nav_bcas)
                   and s.ud("state") != "active" and s.ud("gear") == "")
        variant = {
            "name": "conf-attack-ls1-bcas-active-set-label",
            "menu_open_ok": opened,
            "ls1_entry": ls1, "bcas_entry": bcas,
            "cursor_path": visited,
            "cursor_never_on_disabled": visited_clean,
            "policy_reasons_ok": policy_ok,
            "labels_not_substituted": labels_ok,
            "activation_refused": bool(refused),
            "state_after_attempts": s.ud("state"),
            "backend": backend_facts(s),
        }
        shot = take_screenshot(s, ev, "SHD-12-menu-conf-attack.png", variant)
        s.close_menu()
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += save_session_artifacts(ctx, [])
        vok = vok and opened and policy_ok and visited_clean and labels_ok and refused
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


# ---------------------------------------------------------------------------
# PIC-05 — disabled-item wording accuracy (objective part; wording acceptance
# stays with user check P1-UC-2)
# ---------------------------------------------------------------------------

def case_pic05(ev: lib.Evidence) -> dict:
    """限域修正 A+B：禁用文案客观核对（主观部分留 P1-UC-2）。
    变体 main：随附产品档位表；变体 no-mode：全部产品 id 仅列于 gears、
    省略一切 *_mode/_label/_reason——缺字段不得使任何产品算法变为可选，
    且必须回退到注册表固定标签/原因。"""
    result = {"id": "PIC-05", "variants": [], "files": [], "facts": {}}
    conf_audit = lib.audit_gears_conf()
    result["facts"]["gears_conf_audit"] = conf_audit
    ok = conf_audit["no_stub_gears_in_product"] and conf_audit["no_placeholder_set"]
    placeholder_ids = ("fsr1", "nis", "sgsr1", "anime4k", "xbr", "sharpbilinear",
                       "integer", "nearest")

    def check_menu(entries):
        by_id = {e.get("id"): e for e in entries}
        placeholders_ok = all(
            e.get("enabled") is False and "未实现/后续阶段" in (e.get("reason") or "")
            for gid, e in by_id.items()
            if gid in placeholder_ids
        )
        off_ok = (entries and entries[0].get("id") == "off"
                  and by_id.get("off", {}).get("enabled") is True)
        # nothing in the menu may present LS1/BCAS as available or renamed
        # (the exact label "BCAS" itself is fine; anything else containing
        #  CAS — e.g. a "CAS"/"Bicubic+CAS" stand-in — is not)
        no_substitute = all(
            not ("CAS" in (e.get("label") or "") and e.get("label") != "BCAS")
            for e in entries
        )
        disabled_labeled = all(
            e.get("enabled") is False and (e.get("reason") or "") != ""
            for e in entries if e.get("id") != "off"
        )
        all_reserved_disabled = all(
            e.get("enabled") is False
            for gid, e in by_id.items() if gid != "off"
        )
        return placeholders_ok, off_ok, no_substitute, disabled_labeled, all_reserved_disabled

    # variant main: shipped product gear table
    ctx = CaseContext(ev, "PIC-05", stubs=False, playing=True, session=SESSION)
    try:
        s = ctx.start_playing("main")
        ok = ok and s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        opened = s.open_menu()
        entries = s.menu_entries()
        placeholders_ok, off_ok, no_substitute, disabled_labeled, all_reserved_disabled = \
            check_menu(entries)
        variant = {
            "name": "menu-wording",
            "menu_open_ok": opened,
            "placeholders_ok": placeholders_ok,
            "off_enabled": off_ok,
            "no_substitute_labels": no_substitute,
            "all_disabled_have_reason": disabled_labeled,
            "reserved_all_disabled": all_reserved_disabled,
            "entries": entries,
            "subjective_pending": "P1-UC-2（文案可接受性留用户确认；本条仅客观核对）",
            "backend": backend_facts(s),
        }
        shot = take_screenshot(s, ev, "PIC-05-menu.png", variant)
        s.close_menu()
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += save_session_artifacts(ctx, [])
        ok = ok and opened and placeholders_ok and off_ok and no_substitute \
            and disabled_labeled
    finally:
        ctx.cleanup()

    # variant no-mode: every product id listed, all _mode/_label/_reason omitted
    ctx = CaseContext(ev, "PIC-05", stubs=False, playing=True, session=SESSION)
    ctx.env.write_raw_gears_conf(
        "gears=off,ls1,fsr1,nis,sgsr1,bcas,anime4k,xbr,sharpbilinear,integer,nearest\n")
    try:
        s = ctx.start_playing("no-mode")
        vok = s.wait_until(lambda: isinstance(s.get("vo-passes"), dict), 15.0)
        opened = s.open_menu()
        entries = s.menu_entries()
        placeholders_ok, off_ok, no_substitute, disabled_labeled, all_reserved_disabled = \
            check_menu(entries)
        nav_ls1 = s.navigate_and_activate("ls1")
        nav_nearest = s.navigate_and_activate("nearest")
        refused = (not nav_ls1) and (not nav_nearest) and s.ud("state") != "active"
        variant = {
            "name": "all-product-ids-missing-mode",
            "menu_open_ok": opened,
            "entry_count": len(entries),
            "placeholders_ok": placeholders_ok,
            "off_enabled": off_ok,
            "no_substitute_labels": no_substitute,
            "all_disabled_have_reason": disabled_labeled,
            "reserved_all_disabled": all_reserved_disabled,
            "activation_refused": bool(refused),
            "entries": entries,
            "backend": backend_facts(s),
        }
        shot = take_screenshot(s, ev, "PIC-05-menu-no-mode.png", variant)
        s.close_menu()
        result["variants"].append(variant)
        if shot:
            result["files"].append(shot)
        result["files"] += save_session_artifacts(ctx, [])
        vok = vok and opened and placeholders_ok and off_ok and no_substitute \
            and disabled_labeled and all_reserved_disabled and refused \
            and len(entries) == 11
        ok = ok and vok
    finally:
        ctx.cleanup()
    result["status"] = "PASS" if ok else "FAIL"
    return result


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
    "GEO-01": case_geo01,
    "GEO-07": case_geo07,
    "SHD-12": case_shd12,
    "PIC-05": case_pic05,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=sorted(CASES),
                        help="run a single required test id (repeatable)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--session", default=None,
                        help="session id (e.g. p1-002); REQUIRED for any run — "
                             "names temp roots, IPC pipes and the evidence tree")
    parser.add_argument("--evidence-dir", required=True,
                        help="evidence directory; REQUIRED, must be a fresh "
                             "dir inside the repo session tree (never an old "
                             "session path)")
    parser.add_argument("--force", action="store_true",
                        help="acknowledge reuse of a non-empty, non-frozen "
                             "evidence dir; file writes remain create-only, "
                             "reviewed dirs (candidate.json/tests.json) are "
                             "always refused")
    args = parser.parse_args()
    if args.list:
        for k in sorted(CASES):
            print(k)
        return 0
    global SESSION
    if not args.session or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.session):
        parser.error("--session is required (lowercase letters/digits/hyphens, "
                     "e.g. p1-002)")
    SESSION = args.session
    selected = sorted(CASES) if args.all else (args.case or [])
    if not selected:
        parser.error("choose --all or at least one --case")

    # 限域修正 C: resolve the evidence dir inside the repo session tree and
    # refuse already-used targets BEFORE any mpv starts or any log opens.
    ev_abs = Path(args.evidence_dir).resolve()
    try:
        ev_rel = ev_abs.relative_to(lib.REPO_ROOT).as_posix()
    except ValueError:
        parser.error(f"--evidence-dir must live inside the repo ({lib.REPO_ROOT}); got {ev_abs}")
    lib.ensure_fresh_evidence_dir(ev_abs, force=args.force)
    ev_rel_dir = f"{lib.SESSIONS_ROOT}/{SESSION}"
    if ev_rel != ev_rel_dir and not ev_rel.startswith(ev_rel_dir + "/"):
        parser.error(f"--evidence-dir must be inside the session tree {ev_rel_dir}/; got {ev_rel}")

    evidence = lib.Evidence(ev_abs)
    repro_tail = (f"--session {SESSION} --evidence-dir {ev_rel}")
    summary = {
        "stage": STAGE,
        "session": SESSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "evidence_dir": ev_rel,
        "create_only": True,
        "backend_pin": {"vo": "gpu-next", "gpu_api": "vulkan",
                        "mpv_exe": lib.MPV_EXE,
                        "note": "mpv.com 的包装器会改写含反斜杠的命令行参数（探针证据），"
                                "程序化 IPC 测试直接调用 mpv.exe"},
        "live_configuration_written": False,
        "notes": [
            "截图真实性（限域修正 B）：仅命令成功且文件存在非空的截图才列入 files；"
            "失败变体在各 case variants[].screenshot 显式记录 not_generated 与原因，"
            "绝不引用不存在的 PNG。",
            "菜单渲染事实以 user-data/scale-selector/menu_entries 机读导出为准；"
            "截图是否包含 OSD 菜单以本次运行的 OSD 可见性探针实测为准"
            "（见 CTL-01 variants[].osd_probe），不把 user-data 导出等同视觉验证；"
            "菜单观感/交互属 P1-UC-1 用户确认。",
            "所有 p1-test-* 档位/shader 为运行时生成的测试桩非产品档位，仅存在于临时配置目录；"
            "保留档位（LS1/BCAS 等）由解析器强制 disabled+固定身份（限域修正 A）。",
            "证据为 create-only（限域修正 C）：目标已存在即 fail-closed；"
            "本目录另产出 evidence-manifest.json（全部产物 SHA-256，含 .gitignore 忽略的 .log），"
            "可用 tools/p1_check_evidence.py 校验；非 OS 沙箱/非事务。",
            "IPC 自动化只证功能与状态真实性，不替代真人交互感受。",
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
            f"python -X utf8 tools/p1_verify.py --case {cid} {repro_tail}")
        summary["cases"].append(case_result)
        status = case_result.get("status")
        print(f"[{SESSION}] {cid}: {status} ({case_result['elapsed_s']}s)", flush=True)
        if status != "PASS":
            failures.append(cid)

    # 限域修正 B: every path referenced in files must exist non-empty —
    # the summary may not reference phantoms (belt & suspenders over the
    # take_screenshot gate; a missing file flips the run to FAIL).
    missing = []
    for case in summary["cases"]:
        for f in list(case.get("files", [])):
            p = lib.REPO_ROOT / f
            if not p.exists() or p.stat().st_size == 0:
                missing.append(f)
    summary["evidence_files_all_exist"] = not missing
    summary["missing_evidence_files"] = missing

    obj_path = evidence.write_json("objective-results.json", summary)
    print(f"[{SESSION}] objective results: {len(summary['cases'])} cases, "
          f"failures: {failures or 'none'}", flush=True)

    # 限域修正 C: bind every artifact (incl. .gitignore'd logs) into a
    # SHA-256 manifest so tampering/omission is machine-detectable.
    bound = sorted({f for case in summary["cases"] for f in case.get("files", [])}
                   | {relp(obj_path)})
    manifest = lib.build_evidence_manifest(SESSION, bound)
    man_path = evidence.write_json("evidence-manifest.json", manifest)
    manifest_rel = relp(man_path)
    manifest_sha = lib.sha256_file(man_path)
    print(f"[{SESSION}] evidence manifest: {manifest_rel}", flush=True)
    print(f"[{SESSION}] evidence-manifest sha256: {manifest_sha}", flush=True)
    print(f"[{SESSION}] 集成负责人请在 tests.json 中记录: "
          f'"evidence_manifest": {{"path": "{manifest_rel}", "sha256": "{manifest_sha}"}} '
          f"（candidate tests_sha256 钉住 tests.json，进而钉住清单）", flush=True)
    if missing:
        print(f"[{SESSION}] MISSING EVIDENCE FILES: {missing}", flush=True)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
