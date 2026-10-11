"""p1_lib.py — P1 isolated verification support library (stage P1).

Scope: helpers to run real mpv (gpu-next/vulkan) against throwaway temp
configs over JSON IPC, plus pure "oracle" functions that mirror the plugin's
ownership semantics for cross-checking. No live configuration is touched.

Session note: the library defaults to session "p1-001" for compatibility,
but every entry point accepts an explicit ``session`` so a rework run (e.g.
p1-002) gets its own temp roots, IPC pipe names and evidence tree.

Isolation rules implemented here:
  * every mpv run gets --config-dir under an ASCII temp root;
  * HOME/USERPROFILE/APPDATA/LOCALAPPDATA point into the temp root;
  * the child env is a minimal allowlist (no user credentials/API tokens);
  * watch-later/cache/screenshot dirs are inside the temp root or evidence dir;
  * only the PIDs we spawn are terminated (never a global taskkill).

Evidence rules (限域修正 C / R3+F-02):
  * evidence targets are create-only: an existing objective-results.json /
    transcript / console / mpv.log / screenshot makes the run fail-closed;
  * manifest helpers bind every evidence artifact (including .gitignore'd
    .log files) to canonical repo-relative paths + SHA-256;
  * this is machine-checking discipline, NOT an OS sandbox or transaction.

Test stubs (shader files, gear table entries) are generated at runtime into
the temp config; their ids are prefixed "p1-test-" and every evidence record
labels them "测试桩非产品档位".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

MPV_EXE = os.environ.get("P1_MPV_EXE", r"D:/MPV/mpv.exe")
# NOTE: mpv.com is the documented console entry, but its wrapper re-parses and
# re-quotes the command line, which corrupted the IPC pipe argument in probes
# (log showed a halved `\\.\pipe\...` path and a fatal exit). We therefore
# launch mpv.exe directly with list-argv; same binary, deterministic args.

# Backslash constructed via chr(92) so the file survives any shell transport.
_BS = chr(92)
PIPE_NAMESPACE = (_BS + _BS + "." + _BS + "pipe" + _BS)  # \\.\pipe\

SAFE_ENV_KEYS = [
    "SystemRoot", "SystemDrive", "windir", "WINDIR", "COMSPEC", "PATH",
    "TEMP", "TMP", "PATHEXT", "COMMONPROGRAMFILES", "PROCESSOR_ARCHITECTURE",
]

# P2 (p2-001) additive migration (semantics widened, discipline not weakened):
#   * osd-width/osd-height — the real window pixels; the brief-mandated source
#     for the //!WHEN decision (video-out-params.dw/dh are aspect-only);
#   * video-crop / current-window-scale — P2 anti-stale GUARD observations
#     (read-only, never written, never in the baseline snapshot).
# P3 (p3-001) additive migration (same discipline): video-unscaled / video-zoom
#   — the Integer gear's managed geometry properties. They are plugin-OWNED
#   writes (take/restore via the ownership ledger), and the journal audit must
#   therefore accept reads of them; the geometry SOURCE remains
#   video-out-params + the raw window pixels (anti-feedback rule unchanged).
# 2026-10-12 additive migration (SHD-1): osd-dimensions — its margins give
#   the real video display rect, which is what a shader's //!WHEN OUTPUT
#   measures (letterboxed video ≠ window). Read-only, used ONLY for the WHEN
#   mirror; the Integer k still comes from the raw window pixels.
# The audit's core rule is unchanged: geometry comes only from
# video-out-params + window pixels; no decoded/intermediate size reads.
ALLOWED_JOURNAL_PROPS = {
    "glsl-shaders", "scale", "cscale", "dscale", "video-out-params",
    "osd-width", "osd-height", "video-crop", "current-window-scale",
    "video-unscaled", "video-zoom", "osd-dimensions",
}

IDENTITY_GLSL = (
    "//!HOOK MAIN\n"
    "//!BIND HOOKED\n"
    "//!SAVE HOOKED\n"
    "vec4 hook() { return HOOKED_tex(HOOKED_pos); }\n"
)

STUB_LABEL_SUFFIX = "（测试桩非产品档位）"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_text_lf(path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\r\n", "\n").encode("utf-8")
    path.write_bytes(data)


def close_enough(a, b) -> bool:
    """JSON-tolerant equality for mpv property values (floats may wobble)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close_enough(x, y) for x, y in zip(a, b))
    return a == b


# ---------------------------------------------------------------------------
# Isolated environment / temp config generation
# ---------------------------------------------------------------------------

class IsolatedEnv:
    """Throwaway mpv world: config dir, fake HOME/APPDATA, media, stubs."""

    def __init__(self, root: Path, label: str = "case"):
        self.root = Path(root)
        self.label = label
        self.cfg = self.root / "cfg"
        self.home = self.root / "home"
        self.appdata = self.home / "AppData" / "Roaming"
        self.cache = self.root / "cache"
        self.watch_later = self.root / "watch-later"
        self.shots = self.root / "shots"
        for d in (self.cfg / "scripts", self.cfg / "script-opts",
                  self.home, self.appdata, self.cache, self.watch_later, self.shots):
            d.mkdir(parents=True, exist_ok=True)
        self.manifest: dict = {}
        self.inputs: dict = {}   # relpath -> sha256 (generated stubs/media)

    # -- file writers -------------------------------------------------------

    def add_generated_input(self, relpath: str, text: str) -> Path:
        p = self.cfg / relpath
        write_text_lf(p, text)
        self.inputs[relpath.replace("\\", "/")] = sha256_file(p)
        return p

    # -- config generation --------------------------------------------------

    def write_mpv_conf(self, scale_baseline: str = "bicubic",
                       baseline_shaders: list | None = None,
                       extra_lines: list | None = None) -> None:
        lines = [
            "vo=gpu-next",
            "gpu-api=vulkan",
            "fullscreen=no",
            f"scale={scale_baseline}",
        ]
        if baseline_shaders:
            joined = ",".join(baseline_shaders)
            lines.append(f"glsl-shaders={joined}")
        lines += extra_lines or []
        self.add_generated_input("mpv.conf", "\n".join(lines) + "\n")

    def write_input_conf(self) -> None:
        """External-change bindings mirroring the active config's command
        shapes (append/clr/toggle/set). These are test-local equivalents and
        never touch the real Anime4K chains. F8 must stay free."""
        tpl = [
            'CTRL+1 no-osd change-list glsl-shaders append "~~/p1-test-ext-a.glsl"; show-text "p1-test: 外部追加A"',
            'CTRL+2 no-osd change-list glsl-shaders append "~~/p1-test-ext-b.glsl"; show-text "p1-test: 外部追加B"',
            'CTRL+0 no-osd change-list glsl-shaders clr ""; show-text "p1-test: 外部清链"',
            'F5 no-osd change-list glsl-shaders toggle "~~/p1-test-ext-a.glsl"; show-text "p1-test: 外部toggle"',
            'F6 set scale spline36; show-text "p1-test: 外部改scale"',
        ]
        text = "\n".join(tpl) + "\n"
        assert "F8" not in text, "F8 must not be bound by the test input.conf"
        self.add_generated_input("input.conf", text)

    def install_plugin(self, plugin_source: Path) -> None:
        dst = self.cfg / "scripts" / "scale-selector.lua"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(plugin_source, dst)
        self.inputs["scripts/scale-selector.lua"] = sha256_file(dst)

    def write_scalar_opts(self) -> None:
        self.add_generated_input(
            "script-opts/scale-selector.conf",
            "key_menu=F8\nmenu_font_size=22\n",
        )

    def write_gears_conf(self, product_text: str, stub_gears: list | None = None) -> None:
        """product_text: repo's script-opts/scale-selector-gears.conf content.
        stub_gears: list of dicts {id,label,mode,reason,set:[strings]}."""
        text = "# 测试用档位表（产品默认 + p1-test-* 测试桩；桩档位非产品档位）\n" + product_text
        if stub_gears:
            ids = [g["id"] for g in stub_gears]
            for g in stub_gears:
                assert g["id"].startswith("p1-test-"), "stub gears must be named p1-test-*"
            existing = text.splitlines()
            for line in existing:
                if line.startswith("gears="):
                    old = line[len("gears="):].strip()
                    text = text.replace(line, "gears=" + old + "," + ",".join(ids), 1)
            for g in stub_gears:
                prefix = g["id"].replace("-", "_")
                text += f"\n{prefix}_label={g['label']}\n"
                text += f"{prefix}_mode={g.get('mode', 'active')}\n"
                if g.get("reason"):
                    text += f"{prefix}_reason={g['reason']}\n"
                if g.get("set"):
                    text += f"{prefix}_set=" + ";".join(g["set"]) + "\n"
        self.add_generated_input("script-opts/scale-selector-gears.conf", text)

    def write_stub_shaders(self, names: list | None = None) -> None:
        for name in (names or ["p1-test-baseline", "p1-test-stub", "p1-test-stub-b",
                               "p1-test-ext-a", "p1-test-ext-b"]):
            self.add_generated_input(name + ".glsl", IDENTITY_GLSL)

    def write_raw_gears_conf(self, text: str) -> None:
        """Raw (possibly corrupted) gears conf for CTL-06 variants."""
        self.add_generated_input("script-opts/scale-selector-gears.conf", text)

    # -- manifest -----------------------------------------------------------

    def snapshot_manifest(self) -> dict:
        out = {}
        for p in sorted(self.cfg.rglob("*")):
            if p.is_file():
                out[p.relative_to(self.cfg).as_posix()] = sha256_file(p)
        return out

    def env(self) -> dict:
        e = {k: os.environ.get(k, "") for k in SAFE_ENV_KEYS}
        if not e.get("SystemRoot"):
            e["SystemRoot"] = os.environ.get("SystemRoot", "")
        e.update({
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "APPDATA": str(self.appdata),
            "LOCALAPPDATA": str(self.appdata),
        })
        return e

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def make_env(label: str, session: str = "p1-001") -> IsolatedEnv:
    base = Path(tempfile.gettempdir()) / f"{session}-{label}-{os.getpid()}-{int(time.time())}"
    return IsolatedEnv(base, label)


# ---------------------------------------------------------------------------
# Synthetic media (stdlib only)
# ---------------------------------------------------------------------------

def generate_y4m(path, w=320, h=240, frames=48, fps_num=24, fps_den=1) -> str:
    """Deterministic checkerboard-with-motion test clip. Returns sha256."""
    with open(path, "wb") as f:
        header = f"YUV4MPEG2 W{w} H{h} F{fps_num}:{fps_den} Ip A1:1 C420jpeg\n"
        f.write(header.encode("ascii"))
        half_w, half_h = w // 2, h // 2
        u_base = bytes([80] * (half_w * half_h))
        v_base = bytes([140] * (half_w * half_h))
        for i in range(frames):
            f.write(b"FRAME\n")
            y = bytearray(w * h)
            phase = i % 2
            for yy in range(h):
                row = yy * w
                band = (yy // 16 + phase) & 1
                base = 30 + (200 if band else 0)
                for xx in range(w // 16):
                    val = base if (xx + i) % 2 == 0 else base ^ 0x50
                    y[row + xx * 16: row + xx * 16 + 16] = bytes([val] * 16)
            f.write(bytes(y))
            f.write(u_base)
            f.write(v_base)
    return sha256_file(path)


# ---------------------------------------------------------------------------
# JSON IPC client
# ---------------------------------------------------------------------------

class IPCError(RuntimeError):
    pass


class IpcClient:
    def __init__(self, pipe_name: str, timeout_s: float = 30.0):
        self.target = PIPE_NAMESPACE + pipe_name
        deadline = time.time() + timeout_s
        last_err = None
        while time.time() < deadline:
            try:
                self.f = open(self.target, "r+b", buffering=1 << 20)
                break
            except OSError as e:
                last_err = e
                time.sleep(0.4)
        else:
            raise IPCError(f"pipe connect failed: {last_err}")
        self.request_id = 0
        self.transcript: list = []

    def cmd(self, *args, record=True) -> dict:
        try:
            return self._cmd_once(*args, record=record)
        except IPCError as error:
            # Transient pipe hiccup (Errno 22 observed under heavy vo load):
            # reconnect once and resend. Retries are recorded in the transcript
            # so evidence stays honest about them.
            self.transcript.append({"t": round(time.time(), 3),
                                    "retry": True, "after": str(error)})
            self.reconnect()
            return self._cmd_once(*args, record=record)

    def reconnect(self, timeout_s: float = 15.0):
        try:
            self.f.close()
        except OSError:
            pass
        deadline = time.time() + timeout_s
        last_err = None
        while time.time() < deadline:
            try:
                self.f = open(self.target, "r+b", buffering=1 << 20)
                return
            except OSError as e:
                last_err = e
                time.sleep(0.3)
        raise IPCError(f"pipe reconnect failed: {last_err}")

    def _cmd_once(self, *args, record=True) -> dict:
        self.request_id += 1
        rid = self.request_id
        payload = json.dumps({"command": list(args), "request_id": rid}).encode("utf-8") + b"\n"
        try:
            self.f.write(payload)
            self.f.flush()
        except OSError as e:
            raise IPCError(f"pipe write failed: {e}")
        while True:
            line = self.f.readline()
            if not line:
                raise IPCError("pipe closed")
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if obj.get("request_id") == rid:
                if record:
                    self.transcript.append({"t": round(time.time(), 3), "req": list(args)})
                    self.transcript.append({"t": round(time.time(), 3),
                                            "resp": {"error": obj.get("error"), "data": _jsonable(obj.get("data"))}})
                return obj
            # unsolicited event line — skip

    def get_property(self, name):
        r = self.cmd("get_property", name)
        if r.get("error") == "success":
            return r.get("data")
        return None

    def get_property_raw(self, name):
        return self.cmd("get_property", name)

    def set_property(self, name, value):
        return self.cmd("set_property", name, value)

    def keypress(self, key, delay=0.12):
        r = self.cmd("keypress", key)
        time.sleep(delay)
        return r

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass


def _jsonable(v):
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


# ---------------------------------------------------------------------------
# mpv session
# ---------------------------------------------------------------------------

class MpvSession:
    def __init__(self, env: IsolatedEnv, case_name: str, log_dir: Path,
                 pipe_suffix: str = "ipc", session: str = "p1-001"):
        self.env = env
        self.case_name = case_name
        self.session = session
        self.proc: subprocess.Popen | None = None
        self.ipc: IpcClient | None = None
        self.pipe_name = f"{session}-{case_name}-{pipe_suffix}"
        self.log_path = Path(log_dir) / f"{case_name}.mpv.log"
        self.console_path = Path(log_dir) / f"{case_name}.console.txt"
        self.exit_code = None
        self.killed_by_tool = False
        self._console = None

    def check_targets_unused(self) -> None:
        """限域修正 C (R3/F-02): per-case artifacts are create-only.
        Fail-closed BEFORE any process starts if a target already exists —
        a rerun must never silently truncate frozen evidence."""
        for p in (self.console_path, self.log_path):
            if p.exists():
                raise FileExistsError(
                    f"证据目标已存在（create-only，拒绝截断/覆写）: {p}; "
                    "请使用新的 --evidence-dir")

    def start(self, media: Path | None = None, extra_args: list | None = None):
        self.check_targets_unused()
        self._console = open(self.console_path, "xb")
        args = [
            MPV_EXE,
            f"--config-dir={self.env.cfg}",
            f"--input-ipc-server={self.pipe_name}",
            "--vo=gpu-next", "--gpu-api=vulkan",
            "--fullscreen=no",
            f"--log-file={self.log_path}",
            f"--screenshot-directory={self.env.shots}",
            f"--watch-later-dir={self.env.watch_later}",
        ]
        # NOTE: this build has no --cache-dir option (fatal parse error); disk
        # cache stays inside the throwaway config/env by default. Isolation is
        # provided by the throwaway --config-dir plus the sandboxed env.
        args += extra_args or []
        if media is not None:
            args.append(str(media))
        self.proc = subprocess.Popen(
            args, env=self.env.env(),
            stdout=self._console, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        self.ipc = IpcClient(self.pipe_name, timeout_s=40.0)
        return self

    def cmd(self, *args):
        return self.ipc.cmd(*args)

    def get(self, name):
        return self.ipc.get_property(name)

    def get_raw(self, name):
        return self.ipc.get_property_raw(name)

    def set(self, name, value):
        return self.ipc.set_property(name, value)

    def key(self, name, delay=0.12):
        return self.ipc.keypress(name, delay)

    def ud(self, subkey):
        return self.get("user-data/scale-selector/" + subkey)

    @staticmethod
    def ud_empty(value):
        """mpv exports empty Lua maps as [] over JSON IPC; treat []/{} as empty."""
        return value is None or value == [] or value == {}

    def wait_state(self, expected: str, timeout_s: float = 6.0) -> bool:
        return self.wait_until(lambda: self.ud("state") == expected, timeout_s)

    def wait_until(self, predicate, timeout_s: float, poll=0.15) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if predicate():
                    return True
            except (IPCError, OSError):
                return False
            time.sleep(poll)
        return False

    @staticmethod
    def ensure_screenshot_target(path) -> None:
        """Screenshots are create-only too: mpv's screenshot-to-file would
        silently overwrite an existing file."""
        if Path(path).exists():
            raise FileExistsError(f"截图目标已存在（create-only 拒绝覆盖）: {path}")

    def screenshot(self, path, mode: str = "subtitles") -> bool:
        self.ensure_screenshot_target(path)
        r = self.cmd("screenshot-to-file", str(path), mode)
        return r.get("error") == "success"

    def open_menu(self):
        """Open the menu; idempotent (F8 toggles, so only press when closed)."""
        if self.ud("menu_open") is True:
            return True
        self.key("F8", delay=0.25)
        return self.wait_until(lambda: self.ud("menu_open") is True, 4.0)

    def close_menu(self):
        self.key("ESC", delay=0.2)
        return self.wait_until(lambda: self.ud("menu_open") is False, 4.0)

    def menu_entries(self):
        return self.ud("menu_entries") or []

    def navigate_and_activate(self, gear_id: str) -> bool:
        """Drive the real keybindings: F8 → walk (UP/DOWN, skipping disabled)
        until the target is selected → Enter."""
        if not self.ud("menu_open"):
            if not self.open_menu():
                return False
        entries = self.menu_entries()
        target_entry = next((e for e in entries if e.get("id") == gear_id), None)
        if target_entry is None or not target_entry.get("enabled"):
            return False

        def selected_id():
            sel = [e.get("id") for e in self.menu_entries() if e.get("selected")]
            return sel[0] if sel else None

        if selected_id() == gear_id:
            self.key("ENTER", delay=0.3)
            return True
        # decide walking direction from current position
        cur_idx = next((i for i, e in enumerate(entries) if e.get("selected")), None)
        tgt_idx = next((i for i, e in enumerate(entries) if e.get("id") == gear_id), None)
        direction = "DOWN" if (tgt_idx or 0) > (cur_idx or 0) else "UP"
        for _ in range(len(entries) + 1):
            if selected_id() == gear_id:
                self.key("ENTER", delay=0.3)
                return True
            self.key(direction, delay=0.05)
        return False

    def quit(self, timeout_s: float = 15.0) -> bool:
        try:
            self.cmd("quit")
        except (IPCError, OSError):
            pass
        try:
            self.ipc.close()
        except OSError:
            pass
        self._close_console()
        if self.proc is not None:
            try:
                self.exit_code = self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self.kill()
                return False
        return True

    def _close_console(self):
        if self._console is not None:
            try:
                self._console.close()
            except OSError:
                pass
            self._console = None

    def kill(self):
        """Terminate only the process this session spawned."""
        self.killed_by_tool = True
        self._close_console()
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True)
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        try:
            self.ipc.close()
        except OSError:
            pass

    def wait_exit(self, timeout_s: float = 20.0):
        if self.proc is not None:
            try:
                self.exit_code = self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                return None
        return self.exit_code


# ---------------------------------------------------------------------------
# Oracles (mirror of the plugin's documented ownership semantics)
# ---------------------------------------------------------------------------

UNAVAIL_SENTINEL = "@@unavailable@@"


def expected_off_actions(baseline, last, wrote, owned, current):
    """Return (restores, kept): what "关" must do for each managed property.

    P2 (p2-001) compat-mode oracle — the historical P1 element-level
    semantics for p1-test-* stub gears (external glsl-shaders → owned entries
    removed element-wise). It must NOT be applied to P2 registered whole
    main chains (fsr1/sgsr1/anime4k/nearest): use
    p2_lib.expected_off_actions_whole for those (complete-list preservation,
    no removal by path string).

    restores: prop -> value to write back (baseline for owned & unmodified;
              element-level list for externally-modified glsl-shaders).
    kept:     prop -> current value left untouched (external wins).
    """
    restores, kept = {}, {}
    for prop, was_written in (wrote or {}).items():
        if not was_written:
            continue
        cur = (current or {}).get(prop)
        if prop == "glsl-shaders":
            cur_list = list(cur) if isinstance(cur, list) else []
            if close_enough(cur_list, (last or {}).get(prop)):
                restores[prop] = baseline.get(prop) or []
            else:
                restores[prop] = [s for s in cur_list if s not in (owned or [])]
                kept[prop] = cur_list
        else:
            if close_enough(cur, (last or {}).get(prop)):
                restores[prop] = baseline.get(prop)
            else:
                kept[prop] = cur
    return restores, kept


def expected_gear_list(current, owned, adds=(), removes=()):
    """P2 (p2-001) compat-mode element-level list oracle for p1-test-* stubs
    (kept for the labelled compatibility test mode; P2 registered gears use
    whole-property recipes — see p2_lib.expected_builtin_chain_write)."""
    out = [s for s in (current or []) if s not in (owned or []) and s not in set(removes)]
    out += list(adds)
    return out


# ---------------------------------------------------------------------------
# Evidence recording (create-only per file; UTF-8/LF)
# 限域修正 C (R3/F-02): a rerun must never overwrite frozen evidence.
# ---------------------------------------------------------------------------

class Evidence:
    def __init__(self, evidence_dir: Path):
        self.dir = Path(evidence_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_create_only(p: Path, data: bytes) -> Path:
        if p.exists():
            raise FileExistsError(
                f"证据文件已存在（create-only，拒绝覆写）: {p}; 请改用全新证据目录")
        tmp = p.with_name(p.name + ".tmp")
        if tmp.exists():
            raise FileExistsError(
                f"临时文件已残留（上次运行中断?），拒绝继续: {tmp}")
        tmp.write_bytes(data)
        try:
            # Windows os.rename fails when the destination exists → TOCTOU guard
            os.rename(tmp, p)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        return p

    def write_json(self, name: str, obj) -> Path:
        p = self.dir / name
        data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return self._write_create_only(p, data)

    def save_transcript(self, name: str, transcript: list) -> Path:
        p = self.dir / name
        data = ("\n".join(json.dumps(x, ensure_ascii=False)
                          for x in transcript) + "\n").encode("utf-8")
        return self._write_create_only(p, data)

    def copy_file(self, src: Path, name: str) -> Path:
        dst = self.dir / name
        return self._write_create_only(dst, Path(src).read_bytes())


# ---------------------------------------------------------------------------
# Evidence-directory freshness guard + SHA-256 manifest (限域修正 C)
# ---------------------------------------------------------------------------

EVIDENCE_MANIFEST_SCHEMA = "mpv-scaler-evidence-manifest/v1"
SESSIONS_ROOT = "docs/验证/开发"
FROZEN_MARKERS = ("candidate.json", "tests.json")
USED_MARKERS = ("objective-results.json", "evidence-manifest.json")


def ensure_fresh_evidence_dir(path, force: bool = False) -> None:
    """Fail-closed BEFORE any mpv starts or any log is opened.

    * a reviewed/frozen evidence dir (candidate.json/tests.json present) is
      never reusable, not even with --force;
    * an already-used dir (objective-results.json/evidence-manifest.json, or
      any leftover file) requires a NEW --evidence-dir, or an explicit --force
      acknowledgment — and even then every file write below stays create-only,
      so force cannot actually overwrite existing artifacts.
    """
    p = Path(path)
    if not p.exists():
        return
    if not p.is_dir():
        raise NotADirectoryError(f"证据路径不是目录: {p}")
    frozen = [m for m in FROZEN_MARKERS if (p / m).exists()]
    if frozen:
        raise FileExistsError(
            f"已审查/冻结的证据目录禁止任何复用或强制覆盖: {p} 含 {frozen}")
    used = [m for m in USED_MARKERS if (p / m).exists()]
    entries = sorted(x.name for x in p.iterdir())
    if used or entries:
        detail = f"含 {used}" if used else f"含其他文件 {entries[:5]}"
        if not force:
            raise FileExistsError(
                f"证据目录非空（{detail}）; 请改用全新 --evidence-dir，"
                "或显式 --force（已冻结目录永远拒绝）")


def safe_manifest_relpath(rel: str, session: str, repo_root: Path = None) -> Path:
    """Validate a canonical repo-relative POSIX evidence path inside the
    session tree; return the concrete Path. Rejects traversal, absolute /
    backslash / drive paths, links & reparse points, private top dirs and
    anything outside docs/验证/开发/<session>/ or outside the repo."""
    if repo_root is None:
        repo_root = REPO_ROOT
    repo_root = Path(repo_root)
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
        raise ValueError(f"非法证据路径（须为仓库相对 POSIX 路径）: {rel!r}")
    if rel != rel.strip() or rel.startswith("/") or rel.endswith("/"):
        raise ValueError(f"非法证据路径（前后缀/空格）: {rel!r}")
    parts = PurePosixPath(rel).parts
    if not parts or ".." in parts or "." in parts or PurePosixPath(rel).as_posix() != rel:
        raise ValueError(f"证据路径不允许穿越/空段: {rel!r}")
    prefix = f"{SESSIONS_ROOT}/{session}/"
    if not rel.startswith(prefix) or len(rel) <= len(prefix):
        raise ValueError(
            f"证据路径必须位于本会话目录 {prefix} 之内: {rel!r}")
    path = repo_root / rel
    for item in [path, *path.parents]:
        if item.exists() or item.is_symlink():
            if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError(f"证据路径包含链接/reparse点: {rel}")
    resolved = path.resolve()
    if repo_root.resolve() not in resolved.parents:
        raise ValueError(f"证据路径逃逸仓库: {rel}")
    if not resolved.is_file():
        raise ValueError(f"证据路径不是常规文件: {rel}")
    return path


def build_evidence_manifest(session: str, paths, repo_root: Path = None,
                            generated_at: str | None = None) -> dict:
    """Bind evidence artifacts (repo-relative POSIX path -> SHA-256).
    Includes .gitignore'd files such as mpv logs on purpose (限域修正 C)."""
    if repo_root is None:
        repo_root = REPO_ROOT
    repo_root = Path(repo_root)
    files: dict = {}
    for p in paths:
        p = Path(p)
        try:
            rel = p.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            raise ValueError(f"证据文件位于仓库外，无法绑定: {p}")
        safe_manifest_relpath(rel, session, repo_root)  # validates
        files[rel] = sha256_file(repo_root / rel)
    return {
        "schema": EVIDENCE_MANIFEST_SCHEMA,
        "session": session,
        "generated_at": generated_at or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": ("create-only 证据清单：绑定会话树内全部证据产物"
                 "（含被 .gitignore 忽略的 .log）；非 OS 沙箱/非事务"),
        "files": dict(sorted(files.items())),
    }


def verify_evidence_manifest(manifest, session: str,
                             repo_root: Path = None) -> list:
    """Return a list of problems (empty = manifest internally consistent:
    schema/session valid, every path canonical+in-session, every file present
    and unmodified per its SHA-256)."""
    problems: list = []
    if repo_root is None:
        repo_root = REPO_ROOT
    if not isinstance(manifest, dict):
        return ["manifest 不是 JSON 对象"]
    if manifest.get("schema") != EVIDENCE_MANIFEST_SCHEMA:
        problems.append(f"manifest schema 不符: {manifest.get('schema')!r}")
    if manifest.get("session") != session:
        problems.append(
            f"manifest session 不符: {manifest.get('session')!r} ≠ {session!r}")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("manifest files 缺失或为空")
        return problems
    if len({k.casefold() for k in files}) != len(files):
        problems.append("manifest 存在大小写冲突的路径")
    for rel, digest in files.items():
        if not isinstance(rel, str) or not rel:
            problems.append("manifest 存在非法路径条目")
            continue
        # REV-02 同域修复（P2 限域）：常规文件缺失先短路给出「清单文件缺失」
        # 文案；路径形状非法仍由 safe_manifest_relpath 拒绝。判定能力不变
        # （两种情况都计为 problem），仅文案与设计意图一致。
        if not (Path(repo_root) / rel).exists() and ".." not in PurePosixPath(rel).parts \
                and ":" not in rel and "\\" not in rel:
            if rel.startswith(f"{SESSIONS_ROOT}/{session}/"):
                problems.append(f"清单文件缺失: {rel}")
                continue
        try:
            path = safe_manifest_relpath(rel, session, repo_root)
        except ValueError as e:
            problems.append(str(e))
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            problems.append(f"伪造/非法 SHA-256: {rel}")
            continue
        if not path.exists():
            problems.append(f"清单文件缺失: {rel}")
            continue
        if sha256_file(path) != digest:
            problems.append(f"文件被改动（SHA-256 不符）: {rel}")
    return problems


# ---------------------------------------------------------------------------
# Static policy checks over repo files
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_LUA = REPO_ROOT / "scripts" / "scale-selector.lua"
GEARS_CONF = REPO_ROOT / "script-opts" / "scale-selector-gears.conf"
SCALAR_CONF = REPO_ROOT / "script-opts" / "scale-selector.conf"


def audit_plugin_source() -> dict:
    """Static source audits used by CTL-01/CTL-02/GEO-01 evidence."""
    src = PLUGIN_LUA.read_text(encoding="utf-8")
    # comments may legitimately *mention* forbidden commands; audit code only
    code_only = "\n".join(line for line in src.splitlines()
                          if not line.strip().startswith("--"))
    return {
        "no_glsl_shaders_clr": ("glsl-shaders-clr" not in code_only
                                and "change-list" not in code_only),
        "binds_only_menu_key": all(
            k in src for k in ['add_key_binding(o.key_menu', 'add_forced_key_binding("UP"',
                               'add_forced_key_binding("DOWN"', 'add_forced_key_binding("ENTER"',
                               'add_forced_key_binding("ESC"'])
            and src.count("add_key_binding(") == 1,
        "geometry_reads_vop_only": 'jget("video-out-params")' in src
            and 'jget("video-params")' not in src
            and 'jget("width")' not in src and 'jget("height")' not in src,
        # no file writes: every io.open must be read-only
        "no_persistence": all(
            '"r"' in part for part in
            [src[i:i + 40] for i in range(len(src)) if src.startswith("io.open", i)]
        ) and src.count("io.open") > 0,
    }


def audit_gears_conf() -> dict:
    """Policy audit of the shipped default gear table.

    P2 (p2-001) compatibility migration of two checks (semantics narrowed,
    discipline not weakened — old P1 assertion that ALL product gears are
    disabled no longer holds because fsr1/sgsr1/anime4k/nearest are now real
    built-in gears with in-script chains):
      * all_product_gears_disabled → now covers the still-placeholder product
        gears only (ls1/bcas/nis/xbr/sharpbilinear/integer);
      * p2_builtins_active → the four P2 gears are declared active in conf
        (their chains/labels/modes are enforced in-script regardless);
      * no_placeholder_set → widened: NO product id may carry a _set= line
        (built-in chains live in the hash-audited Lua/resources, not conf).

    P3 (p3-001) migration (docs/P3实施计划.json write_path_notes c-①, closing
    adversarial finding P3A-01; discipline not weakened):
      * still_disabled / all_product_gears_disabled narrowed AGAIN to the
        still-placeholder pair (ls1/bcas) — nis/xbr/sharpbilinear/integer are
        now REAL built-ins (plus the new sharpbilinear2x);
      * NEW p3_builtins_active: the five P3 gears must be (a) registered
        mode="active" in the Lua BUILTIN_GEARS registry, (b) members of the
        conf gears= list, and (c) carry ZERO _mode/_label/_reason/_set
        override keys in conf. Deliberately does NOT check conf
        "_mode=active" for them: that key is silently ignored (with a parser
        warning) for built-in gears and must never be used to fake an audit
        identity — the honest active state is the Lua registration + conf
        membership + absence of override keys;
      * no_placeholder_set widened to cover the five new gear ids too.
    """
    text = GEARS_CONF.read_text(encoding="utf-8")
    still_disabled = ("ls1", "bcas")
    p2_builtins = ("fsr1", "sgsr1", "anime4k", "nearest")
    p3_builtins = ("nis", "xbr", "sharpbilinear", "sharpbilinear2x", "integer")
    product_ids = still_disabled + p2_builtins + p3_builtins
    lua_src = PLUGIN_LUA.read_text(encoding="utf-8")
    override_keys = ("_mode", "_label", "_reason", "_set")

    def _lua_builtin_block_span(src):
        start = src.index("local BUILTIN_GEARS = {")
        end = src.index("local BUILTIN_BY_ID", start)
        return start, end

    _bs, _be = _lua_builtin_block_span(lua_src)

    def _in_builtin_registry(gid):
        return re.search(r'\{ id = "%s",' % gid, lua_src[_bs:_be]) is not None

    def _not_placeholder(gid):
        ps = lua_src.index("local PLACEHOLDER_GEARS = {")
        pe = lua_src.index("}", ps)
        return re.search(r'\{ id = "%s",' % gid, lua_src[ps:pe]) is None

    checks = {
        "off_first": "gears=off," in text,
        "off_label_const": "off_label=关" in text,
        "ls1_disabled": "ls1_mode=disabled" in text,
        "bcas_disabled": "bcas_mode=disabled" in text,
        "all_product_gears_disabled": all(
            f"{gid}_mode=disabled" in text for gid in still_disabled),
        "p2_builtins_active": all(
            f"{gid}_mode=active" in text for gid in p2_builtins),
        "p3_builtins_active": all(
            # (a) registered in the Lua BUILTIN_GEARS registry (the parser
            #     forces mode=active for built-ins; placeholder registry must
            #     NOT contain them)
            _in_builtin_registry(gid)
            and _not_placeholder(gid)
            # (b) conf gears= membership
            and re.search(r"^gears=.*\b%s\b" % gid, text, re.M) is not None
            # (c) zero override keys in conf (never fake identity with
            #     the silently-ignored _mode=active)
            and not any(
                line.strip().startswith(gid.replace("-", "_") + suf + "=")
                for suf in override_keys
                for line in text.splitlines())
            for gid in p3_builtins),
        "ls1_reason_policy": all(k in text for k in ("无公开源码", "权重", "移植许可")),
        "bcas_reason_policy": ("身份未核实" in text and "不以CAS/Bicubic+CAS冒名" in text),
        "no_placeholder_set": all(
            (not line.startswith(f"{gid}_set="))
            for gid in product_ids
            for line in text.splitlines()
        ),
        "no_stub_gears_in_product": ("p1-test-" not in text
                                     and "p2-test-" not in text
                                     and "p3-test-" not in text),
    }
    return checks
