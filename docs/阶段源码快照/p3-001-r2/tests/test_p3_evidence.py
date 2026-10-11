# -*- coding: utf-8 -*-
"""Synthetic (mpv-free, GPU-free) unit tests for tools/p3_check_evidence.py.

The EVI-01 machine gate is exercised against REAL fixture trees built in a
temporary synthetic repo (never the real evidence trees, never any mpv/GPU,
never any candidate): every common vulnerability is actually PLANTED on disk
and the checker must reject it, plus one full positive control that must
pass cleanly with --require-tests over all 35 P3 REQUIRED ids.

Covered attacks (each a real mutation of the positive control):
  * path traversal           — case refs / png_captures escaping the session;
  * 漏项 (manifest omission)  — on-disk file not bound in the manifest;
  * 错 hash                  — bound file mutated after sealing;
  * 替换 PNG                 — bytes swapped with stale captures sha / lying
                                dimensions (true decode via p3_lib.decode_png);
  * 不真实 samples           — desc_evidence excerpts absent from session logs;
  * 0==0 counting            — desc_keyword_pass_hits==0, count==0,
                                fresh_before==fresh_after;
  * decoder fake freshness   — render_fresh won by a decoder-only method;
  * 旧 epoch                 — freshness.chain_epoch ≠ variant.chain_epoch;
  * native-bool violation    — video-unscaled readback recorded as "yes"/"no";
  * restart missing          — declared restart session triplet incomplete /
                                orphan console stems without a case;
  * closed-class violations  — excluded files in the manifest / broken
                                runner-console / manifest-verify / gate chain.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import p1_lib as lib  # noqa: E402
import p3_check_evidence as gate  # noqa: E402
import p3_lib  # noqa: E402

SESSION = "p3-evi-test"
RUN = "full-r1"
EXCLUDED = set(gate.EXCLUDED_FROM_MANIFEST)

DESC_LINE_1 = "[vo/gpu] pass 'p3-NIS' processed 1 frames (NIS compute)"
DESC_LINE_2 = "[vo/gpu] pass 'p3-NIS-usm' processed 1 frames"


# ---------------------------------------------------------------------------
# fixture bytes helpers
# ---------------------------------------------------------------------------

def make_png(w: int, h: int, salt: int = 0) -> bytes:
    """A real (valid) RGB PNG of w×h with salt-dependent pixels."""
    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + ctype + data
                + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter: none
        for x in range(w):
            raw += bytes(((x * 7 + salt) % 256, (y * 11 + salt) % 256,
                          (x * y + salt) % 256))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def sm(fmt: str = "yuv420p") -> dict:
    """One same-moment record matching the p3_lib.same_moment_sample shape."""
    return {"pixelformat": fmt, "w": 1280, "h": 720, "dw": 2560, "dh": 1440,
            "osd_w": 2560, "osd_h": 1440,
            "vo_passes_frame_counts": {"fresh": 2, "redraw": 1},
            "same_window": True}


def fresh_ok(epoch: int = 3) -> dict:
    return {"render_fresh": True, "method": "vo-passes-fresh-increase",
            "chain_epoch": epoch, "fresh_before": 1, "fresh_after": 2}


def desc_ok() -> dict:
    return {"count": 2, "sample_hits": {"NIS": [DESC_LINE_1, DESC_LINE_2]}}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# positive-control builder
# ---------------------------------------------------------------------------

class PositiveControl:
    """Builds a complete, honest P3 evidence run in a synthetic repo."""

    def __init__(self, repo: Path, session: str = SESSION, run: str = RUN):
        self.repo = repo
        self.session = session
        self.run = run
        self.run_dir = repo / "docs" / "验证" / "开发" / session / "implementer" / run
        self.cases: list = []
        self._build()

    # -- artifact helpers -------------------------------------------------
    def _triplet(self, stem: str, log_lines: list | None = None) -> None:
        d = self.run_dir
        (d / f"{stem}.console.txt").write_bytes(
            f"[runner] {stem} start\n[runner] {stem} done\n".encode("utf-8"))
        log = "\n".join(log_lines or [f"[vo] {stem} generic frame"]) + "\n"
        (d / f"{stem}.mpv.log").write_bytes(log.encode("utf-8"))
        (d / f"{stem}.mpv.transcript.jsonl").write_bytes(
            '{"req":["get_property","scale-selector/state"]}\n'
            '{"res":"active"}\n'.encode("utf-8"))

    def _sessions(self, cid: str, restarts: int = 1,
                  log_lines: list | None = None) -> list:
        stems = [f"{cid}-s1"] + [f"{cid}-s1-r{i}" for i in range(2, restarts + 1)]
        for stem in stems:
            self._triplet(stem, log_lines)
        return stems

    # -- the 35 stub cases -----------------------------------------------
    def _build(self):
        d = self.run_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / "runner.console.txt").write_bytes(
            "[runner] p3 evidence run start\n[runner] all cases done\n".encode("utf-8"))
        nis_log = [DESC_LINE_1, DESC_LINE_2, "[vo] gamma=SDR"]

        for cid in gate.P3_REQUIRED_IDS:
            case: dict = {"id": cid, "status": "PASS", "files": [], "variants": []}
            if cid in gate.NO_MPV_CASES:
                if cid == "EVI-01":
                    case["facts"] = {
                        "negatives_detected": {k: True for k in gate.EVI_NEGATIVE_KEYS},
                        "positive_control_clean": True,
                    }
                self.cases.append(case)
                continue
            if cid in ("SHD-05", "SHD-06", "SHD-07"):
                if cid == "SHD-05":
                    case_log = nis_log
                else:
                    case_log = [f"[vo/gpu] pass '{cid}' processed 1 frames"]
                case["sessions"] = self._sessions(cid, restarts=2,
                                                  log_lines=case_log)
                case["variants"] = [{
                    "desc_evidence": desc_ok() if cid == "SHD-05" else {
                        "count": 1,
                        "sample_hits": {"gear": case_log[0]},
                    },
                    "chain_epoch": 3,
                    "same_moment": [sm("yuv420p")],
                    "freshness": fresh_ok(3),
                }]
            elif cid == "SHD-01" or cid == "SHD-02":
                case["sessions"] = self._sessions(cid)
                case["variants"] = [{"desc_keyword_pass_hits": 3}]
            elif cid == "SHD-04":
                case["sessions"] = self._sessions(cid)
                case["variants"] = [{"required_desc_hits": {"anime4k": True}}]
            elif cid == "SHD-09":
                case["sessions"] = self._sessions(cid)
                case["variants"] = [
                    {"bitdepth": 8, "same_moment": [sm("yuv420p")]},
                    {"bitdepth": 10, "same_moment": [sm("yuv420p10le")]},
                ]
            elif cid == "PER-04-COMPUTE":
                case["sessions"] = self._sessions(cid)
                case["variants"] = [{
                    "chain_epoch": 3,
                    "same_moment": [sm("yuv420p")],
                    "freshness": fresh_ok(3),
                }]
                case["facts"] = {"perf_samples_ns": [120000, 340000, 290000],
                                 "samples_note": "3 raw fresh-redraw ns samples; "
                                                 "no performance-gain claim"}
            elif cid in gate.SAME_MOMENT_CASES:
                case["sessions"] = self._sessions(cid)
                variant: dict = {"chain_epoch": 3,
                                 "same_moment": [sm("yuv420p")],
                                 "freshness": fresh_ok(3)}
                if cid in gate.INTEGER_NATIVE_BOOL_CASES:
                    variant["native_unscaled"] = {"native_type": "bool",
                                                  "value": False}
                case["variants"] = [variant]
            else:  # plain mpv cases
                case["sessions"] = self._sessions(cid)
            self.cases.append(case)

        # real PNG captures (one duplicate pair, honestly marked)
        png_a = make_png(8, 6, salt=1)
        (d / "shot-a.png").write_bytes(png_a)
        (d / "shot-b.png").write_bytes(png_a)  # identical bytes → same SHA
        (d / "shot-c.png").write_bytes(make_png(4, 4, salt=2))
        rel_base = self.run_dir.relative_to(self.repo).as_posix()
        rel = lambda name: f"{rel_base}/{name}"
        by_id = {c["id"]: c for c in self.cases}
        by_id["GEO-02"]["files"] += [rel("shot-a.png"), rel("shot-b.png"),
                                     rel("shot-c.png")]

        self.results = {
            "stage": "P3",
            "session": self.session,
            "required_unmeasured": [],
            "live_configuration_written": False,
            "cases": self.cases,
            "png_captures": [
                {"path": rel("shot-a.png"), "w": 8, "h": 6,
                 "sha256": lib.sha256_file(d / "shot-a.png")},
                {"path": rel("shot-b.png"), "w": 8, "h": 6,
                 "sha256": lib.sha256_file(d / "shot-b.png")},
                {"path": rel("shot-c.png"), "w": 4, "h": 4,
                 "sha256": lib.sha256_file(d / "shot-c.png")},
            ],
            "non_corroborative_png": [
                {"files": [rel("shot-a.png"), rel("shot-b.png")],
                 "reason": "重复内容截图（同 SHA-256）不具独立佐证力，诚实标注"},
            ],
        }
        write_json(d / "objective-results.json", self.results)
        self.seal()

    # -- honest producer sealing (manifest AFTER all artifacts) ------------
    def seal(self) -> None:
        files = sorted(p for p in self.run_dir.rglob("*")
                       if p.is_file() and p.name not in EXCLUDED)
        manifest = lib.build_evidence_manifest(self.session, files, self.repo)
        write_json(self.run_dir / "evidence-manifest.json", manifest)
        write_json(self.run_dir / "manifest-verify.json", {
            "schema": gate.MANIFEST_VERIFY_SCHEMA,
            "session": self.session,
            "evidence_manifest_sha256":
                lib.sha256_file(self.run_dir / "evidence-manifest.json"),
            "runner_console_sha256":
                lib.sha256_file(self.run_dir / "runner.console.txt"),
        })

    # -- gate invocation ----------------------------------------------------
    def problems(self, require_tests: bool = True, required_ids=None,
                 session: str | None = None) -> list:
        return gate.run_full_gate(
            self.run_dir, session or self.session,
            self.run_dir / "objective-results.json",
            self.run_dir / "evidence-manifest.json",
            require_tests, self.repo, required_ids)


class GateFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pc = PositiveControl(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def assert_problem(self, problems, needle):
        self.assertTrue(problems, "expected problems, got none")
        self.assertTrue(any(needle in p for p in problems),
                         f"expected {needle!r} in:\n" + "\n".join(problems))


# ---------------------------------------------------------------------------
# positive control
# ---------------------------------------------------------------------------

class TestPositiveControl(GateFixture):
    def test_full_gate_passes_all_35_required_ids(self):
        self.assertEqual(self.pc.problems(require_tests=True), [])

    def test_repo_relative_manifest_projection_is_the_real_shape(self):
        """Regression pin: lib manifest keys are REPO-relative; the coverage
        projection must accept exactly that shape (the evidence-relative
        misreading would flag every file as 漏项)."""
        manifest = json.loads(
            (self.pc.run_dir / "evidence-manifest.json").read_text(encoding="utf-8"))
        key = next(iter(manifest["files"]))
        self.assertTrue(key.startswith(f"docs/验证/开发/{SESSION}/implementer/{RUN}/"),
                        key)
        self.assertEqual(gate.check_full_directory_coverage(
            manifest, self.pc.run_dir, self.pc.repo), [])

    def test_case_without_required_ids_override_still_clean(self):
        self.assertEqual(self.pc.problems(require_tests=False), [])

    def test_pngs_decode_with_true_dimensions(self):
        decoded = p3_lib.decode_png(make_png(5, 3, salt=9))
        self.assertEqual((decoded["w"], decoded["h"]), (5, 3))


# ---------------------------------------------------------------------------
# planted negatives — every class must be REALLY detected
# ---------------------------------------------------------------------------

class TestPlantedNegatives(GateFixture):
    def _resealed_problems(self):
        self.pc.seal()
        return self.pc.problems()

    def test_path_traversal_in_case_files(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-05"]["files"].append(
            f"docs/验证/开发/{SESSION}/implementer/{RUN}/../../{SESSION}-steal.bin")
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "非法证据引用")

    def test_path_traversal_in_png_captures(self):
        self.pc.results["png_captures"].append(
            {"path": f"docs/验证/开发/{SESSION}/implementer/{RUN}/../outside.png",
             "w": 1, "h": 1, "sha256": "0" * 64})
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "png_captures 路径非法")

    def test_manifest_omission_detected(self):
        (self.pc.run_dir / "unbound-artifact.bin").write_bytes(b"sneaky")
        self.assert_problem(self.pc.problems(), "全目录覆盖漏项")

    def test_manifest_key_outside_evidence_dir_detected(self):
        mp = self.pc.run_dir / "evidence-manifest.json"
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        manifest["files"][f"docs/验证/开发/{SESSION}/elsewhere/x.bin"] = "0" * 64
        write_json(mp, manifest)
        self.assert_problem(self.pc.problems(), "证据目录之外的路径")

    def test_wrong_hash_detected(self):
        (self.pc.run_dir / "GEO-02-s1.mpv.log").write_bytes(b"TAMPERED\n")
        self.assert_problem(self.pc.problems(), "被改动（SHA-256 不符）")

    def test_replaced_png_with_stale_captures_sha(self):
        (self.pc.run_dir / "shot-c.png").write_bytes(make_png(4, 4, salt=99))
        self.pc.seal()  # manifest rebound, png_captures intentionally stale
        self.assert_problem(self.pc.problems(), "哈希与磁盘不符（疑似替换 PNG）")

    def test_png_dimensions_lie_detected_by_true_decode(self):
        self.pc.results["png_captures"][2]["w"] = 99
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "声明尺寸与真实解码不符")

    def test_manifest_png_not_registered_in_captures(self):
        (self.pc.run_dir / "shot-hidden.png").write_bytes(make_png(2, 2, salt=3))
        self.pc.seal()  # bound in manifest but absent from png_captures
        self.assert_problem(self.pc.problems(), "未登记 png_captures")

    def test_unmarked_duplicate_png_detected(self):
        self.pc.results["non_corroborative_png"] = []
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "未诚实标注")

    def test_fabricated_desc_samples_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-05"]["variants"][0]["desc_evidence"] = {
            "count": 1, "sample_hits": {"NIS": ["[fake] totally absent line"]}}
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "伪造样本")

    def test_zero_zero_desc_counting_rejected_p3_shape(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-05"]["variants"][0]["desc_evidence"] = {
            "count": 0, "sample_hits": {"NIS": []}}
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "0==0")

    def test_zero_zero_desc_counting_rejected_legacy_shape(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-01"]["variants"][0]["desc_keyword_pass_hits"] = 0
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "缺少 DESC 结构化命中证据")

    def test_missing_desc_evidence_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-06"]["variants"][0].pop("desc_evidence")
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "缺少结构化 desc_evidence")

    def test_decoder_fake_freshness_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-02"]["variants"][0]["freshness"]["method"] = "decoder-liveness"
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "解码活性不能兜底")

    def test_zero_zero_freshness_counter_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        v = by_id["GEO-02"]["variants"][0]
        v["freshness"]["fresh_before"] = v["freshness"]["fresh_after"] = 2
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "0==0 拒绝")

    def test_missing_freshness_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-03"]["variants"][0].pop("freshness")
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "缺少 freshness 结构化证据")

    def test_stale_epoch_pairing_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-02"]["variants"][0]["freshness"]["chain_epoch"] = 2
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "陈旧 epoch 配对")

    def test_native_bool_violation_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-04"]["variants"][0]["native_unscaled"] = {
            "native_type": "str", "value": "yes"}
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "非原生 bool")

    def test_missing_native_bool_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-05"]["variants"][0].pop("native_unscaled")
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "原生 bool 读回记录")

    def test_restart_session_triplet_missing_rejected(self):
        (self.pc.run_dir / "SHD-05-s1-r2.mpv.log").unlink()
        self.assert_problem(self._resealed_problems(), "缺少 .mpv.log 产物")

    def test_orphan_console_stem_rejected(self):
        (self.pc.run_dir / "ROGUE-s9.console.txt").write_bytes(b"ghost session")
        self.assert_problem(self._resealed_problems(), "无 case 声明")

    def test_empty_session_artifact_rejected(self):
        (self.pc.run_dir / "CTL-01-s1.console.txt").write_bytes(b"")
        self.assert_problem(self.pc.problems(), "为空文件")

    def test_mpv_case_without_sessions_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["CTL-02"]["sessions"] = []
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self.pc.problems(), "sessions 为空")

    def test_duplicate_case_id_rejected(self):
        self.pc.results["cases"].append(dict(self.pc.results["cases"][0]))
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "case id 重复")

    def test_excluded_class_file_inside_manifest_rejected(self):
        mp = self.pc.run_dir / "evidence-manifest.json"
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        manifest["files"][f"docs/验证/开发/{SESSION}/implementer/{RUN}/"
                          "runner.console.txt"] = \
            lib.sha256_file(self.pc.run_dir / "runner.console.txt")
        write_json(mp, manifest)
        self.assert_problem(self.pc.problems(), "排除类文件不得进入清单")

    def test_missing_manifest_verify_rejected(self):
        (self.pc.run_dir / "manifest-verify.json").unlink()
        self.assert_problem(self.pc.problems(), "缺 manifest-verify.json")

    def test_tampered_runner_console_breaks_chain(self):
        (self.pc.run_dir / "runner.console.txt").write_bytes(b"rewritten history\n")
        self.assert_problem(self.pc.problems(), "runner_console_sha256")

    def test_empty_runner_console_rejected(self):
        (self.pc.run_dir / "runner.console.txt").write_bytes(b"")
        self.assert_problem(self.pc.problems(), "runner.console.txt 为空")

    def test_missing_runner_console_rejected(self):
        (self.pc.run_dir / "runner.console.txt").unlink()
        self.assert_problem(self.pc.problems(), "缺 runner.console.txt")

    def test_tampered_gate_pin_rejected(self):
        gate.write_gate_file(self.pc.run_dir, SESSION,
                             self.pc.run_dir / "evidence-manifest.json", [],
                             repo_root=self.pc.repo)
        mv_path = self.pc.run_dir / "manifest-verify.json"
        mv = json.loads(mv_path.read_text(encoding="utf-8"))
        mv["tampered"] = True  # manifest-verify bytes change after the gate pin
        write_json(mv_path, mv)
        self.assert_problem(self.pc.problems(),
                            "evidence-gate 钉扎的 manifest-verify 哈希")

    def test_wrong_session_rejected(self):
        self.assert_problem(self.pc.problems(session="p3-other"), "session 不符")

    def test_required_id_missing_rejected(self):
        self.pc.results["cases"] = [c for c in self.pc.results["cases"]
                                    if c["id"] != "EVI-01"]
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "必需测试缺少报告条目: EVI-01")

    def test_required_case_not_pass_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-02"]["status"] = "FAIL"
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        # require_tests=False keeps FAIL cases free of claim-checks; the real
        # gate (--require-tests) must reject the FAIL as a coverage hole:
        problems = self.pc.problems(require_tests=True)
        self.assertTrue(any("必需测试非 PASS" in p for p in problems), problems)

    def test_required_unmeasured_nonempty_rejected(self):
        self.pc.results["required_unmeasured"] = ["SHD-13"]
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "required_unmeasured 非空")

    def test_live_configuration_written_rejected(self):
        self.pc.results["live_configuration_written"] = True
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "必须为 false")

    def test_evi01_negative_class_missing_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        del by_id["EVI-01"]["facts"]["negatives_detected"]["stale_epoch"]
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "规定负例类别未覆盖")

    def test_evi01_negative_not_fired_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["EVI-01"]["facts"]["negatives_detected"]["wrong_hash"] = False
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "合成负例未被检出")

    def test_evi01_positive_control_dirty_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["EVI-01"]["facts"]["positive_control_clean"] = False
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "阳性对照")

    def test_shd09_fake_10bit_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-09"]["variants"][1]["same_moment"] = [sm("yuv420p")]
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "解码身份不符")

    def test_shd09_missing_10bit_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-09"]["variants"] = [by_id["SHD-09"]["variants"][0]]
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "缺少 10bit 实测证据")

    def test_shd09_honest_refusal_accepted(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["SHD-09"]["variants"][1] = {
            "bitdepth": 10, "refused": True,
            "reason": "档位明确拒用 10bit（支持理由记录）"}
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        problems = self._resealed_problems()
        self.assertFalse(any("SHD-09" in p for p in problems), problems)

    def test_per04_missing_samples_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["PER-04-COMPUTE"]["facts"] = {}
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "perf_samples_ns")

    def test_same_moment_prose_only_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["WINDOW-01"]["variants"][0].pop("same_moment")
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "缺少结构化 same_moment")

    def test_same_moment_missing_same_window_flag_rejected(self):
        by_id = {c["id"]: c for c in self.pc.results["cases"]}
        by_id["GEO-06"]["variants"][0]["same_moment"][0]["same_window"] = False
        write_json(self.pc.run_dir / "objective-results.json", self.pc.results)
        self.assert_problem(self._resealed_problems(), "same_window")

    def test_symlink_inside_evidence_dir_rejected(self):
        if os.name == "nt":  # symlink creation needs privileges on Windows
            self.skipTest("symlink creation not available on this platform")
        target = self.pc.run_dir / "shot-c.png"
        link = self.pc.run_dir / "shot-link.png"
        os.symlink(target, link)
        self.pc.seal()
        self.assert_problem(self.pc.problems(), "链接/reparse点")


# ---------------------------------------------------------------------------
# gate artifact create-only semantics
# ---------------------------------------------------------------------------

class TestGateArtifact(GateFixture):
    def test_write_gate_is_create_only_and_chained(self):
        self.assertEqual(self.pc.problems(), [])
        written = gate.write_gate_file(self.pc.run_dir, SESSION,
                                       self.pc.run_dir / "evidence-manifest.json",
                                       [], repo_root=self.pc.repo)
        self.assertEqual(written.name, "evidence-gate.json")
        with self.assertRaises(FileExistsError):
            gate.write_gate_file(self.pc.run_dir, SESSION,
                                 self.pc.run_dir / "evidence-manifest.json",
                                 ["late problem"], repo_root=self.pc.repo)
        # a sealed PASS gate keeps the full gate green
        self.assertEqual(self.pc.problems(), [])
        obj = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(obj["status"], "PASS")
        self.assertEqual(obj["manifest_verify_sha256"],
                         lib.sha256_file(self.pc.run_dir / "manifest-verify.json"))

    def test_fail_gate_preserved_verbatim(self):
        problems = ["EVI-01: 合成负例未被检出: ['wrong_hash']"]
        written = gate.write_gate_file(self.pc.run_dir, SESSION,
                                       self.pc.run_dir / "evidence-manifest.json",
                                       problems, repo_root=self.pc.repo)
        obj = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(obj["status"], "FAIL")
        self.assertEqual(obj["problems"], problems)  # FAIL 保留，不清洗


# ---------------------------------------------------------------------------
# focused helper tests
# ---------------------------------------------------------------------------

class TestHelperUnits(unittest.TestCase):
    def test_desc_sample_crosscheck_against_logs(self):
        case = {"id": "SHD-05", "status": "PASS",
                "sessions": ["SHD-05-s1"],
                "variants": [{"desc_evidence": desc_ok()}]}
        logs = [DESC_LINE_1.encode("utf-8"), DESC_LINE_2.encode("utf-8")]
        self.assertEqual(gate.check_desc_honesty(case, "SHD-05", logs), [])
        self.assertTrue(gate.check_desc_honesty(case, "SHD-05", [b"other log"]))

    def test_desc_count_must_cover_samples(self):
        de = {"count": 1, "sample_hits": {"NIS": [DESC_LINE_1, DESC_LINE_2]}}
        problems = gate._check_p3_desc_evidence(de, None)
        self.assertTrue(any("小于样本行数" in p for p in problems), problems)

    def test_freshness_epoch_helpers(self):
        self.assertEqual(gate._freshness_defects(fresh_ok(3), {"chain_epoch": 3}), [])
        self.assertTrue(gate._freshness_defects(fresh_ok(2), {"chain_epoch": 3}))

    def test_same_moment_record_validation(self):
        self.assertEqual(gate._same_moment_record_ok(sm()), [])
        bad = sm()
        bad["osd_h"] = -1
        self.assertTrue(gate._same_moment_record_ok(bad))

    def test_required_ids_match_p3_guard(self):
        sys.path.insert(0, str(REPO_ROOT / "taskflows"))
        import p3_guard  # noqa: E402
        self.assertEqual(sorted(gate.P3_REQUIRED_IDS), sorted(p3_guard.REQUIRED))


if __name__ == "__main__":
    unittest.main()
