"""Verify a configuration snapshot; rehearse/restore its mpv-config root safely.

No command restores the live configuration by default. Restore requires an explicit
mpv target, --apply and --confirm RESTORE-MPV-CONFIG. Existing target is retained
as a sibling directory. Binary runtimes and the optional launcher are not restored.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

CONFIRM = "RESTORE-MPV-CONFIG"
SCHEMA = "mpv-config-backup/v1"
PROJECT = Path(__file__).resolve().parents[1]


class BackupError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def no_links(path: Path) -> None:
    """Reject symlinks and Windows junction/reparse paths, including parents."""
    for item in [path, *path.parents]:
        if item.exists() or item.is_symlink():
            stat = item.lstat()
            if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise BackupError(f"Link/reparse point is not allowed: {item}")


def relative_name(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BackupError(f"Invalid relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise BackupError(f"Unsafe relative path: {value!r}")
    return value


def inventory(path: Path) -> tuple[list[str], dict[str, tuple[int, str]]]:
    no_links(path)
    if not path.exists():
        raise BackupError(f"Missing directory: {path}")
    if path.is_file():
        return [], {path.name: (path.stat().st_size, sha256(path))}
    directories: list[str] = []
    files: dict[str, tuple[int, str]] = {}
    for item in sorted(path.rglob("*")):
        no_links(item)
        name = item.relative_to(path).as_posix()
        if item.is_dir():
            directories.append(name)
        elif item.is_file():
            files[name] = (item.stat().st_size, sha256(item))
        else:
            raise BackupError(f"Unsupported file type: {item}")
    return directories, files


def validate_root(root: dict) -> dict[str, tuple[int, str]]:
    if root.get("source_kind") not in ("directory", "file"):
        raise BackupError("Unsupported source kind")
    identifier = root.get("id", "")
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9-]+", identifier):
        raise BackupError("Invalid root identifier")
    if root.get("payload") != f"payload/{identifier}":
        raise BackupError("Unexpected payload root")
    names: set[str] = set()
    expected: dict[str, tuple[int, str]] = {}
    for directory in root.get("directories", []):
        name = relative_name(directory)
        if name.casefold() in names:
            raise BackupError("Duplicate directory/path")
        names.add(name.casefold())
    for entry in root.get("files", []):
        name = relative_name(entry["path"])
        if name.casefold() in names:
            raise BackupError("Duplicate or colliding file path")
        names.add(name.casefold())
        size, digest = entry.get("bytes"), entry.get("sha256", "")
        if type(size) is not int or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError("Invalid file size/hash")
        expected[name] = (size, digest)
    return expected


def check_tree(path: Path, root: dict) -> None:
    directories, files = inventory(path)
    if sorted(directories) != sorted(root["directories"]) or files != validate_root(root):
        raise BackupError(f"Tree differs from manifest: {path}")


def verify_backup(backup: Path, compare_source: bool = False) -> tuple[dict, dict]:
    backup = backup.absolute()
    no_links(backup)
    manifest_path = backup / "manifest.json"
    receipt_path = backup / "verification.json"
    archive_path = backup / "mpv-config.zip"
    for path in [manifest_path, receipt_path, archive_path]:
        no_links(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or receipt.get("status") != "PASS":
        raise BackupError("Incomplete or unsupported backup")
    if sha256(manifest_path) != receipt.get("manifest_sha256"):
        raise BackupError("Manifest hash mismatch")
    if sha256(archive_path) != receipt.get("archive_sha256"):
        raise BackupError("Archive hash mismatch")
    roots = manifest.get("roots", [])
    if not roots or len({root["id"] for root in roots}) != len(roots):
        raise BackupError("Missing/duplicate roots")
    expected_members = {"manifest.json"}
    for root in roots:
        validate_root(root)
        check_tree(backup / root["payload"], root)
        expected_members.update(f'{root["payload"]}/{name}/' for name in root["directories"])
        expected_members.update(f'{root["payload"]}/{entry["path"]}' for entry in root["files"])
        if compare_source:
            check_tree(Path(root["source"]), root)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_members:
            raise BackupError("Archive member list mismatch")
        if archive.read("manifest.json") != manifest_path.read_bytes():
            raise BackupError("Archive manifest mismatch")
        for root in roots:
            for entry in root["files"]:
                name = f'{root["payload"]}/{entry["path"]}'
                if archive.getinfo(name).file_size != entry["bytes"]:
                    raise BackupError("Archive file size mismatch")
                with archive.open(name) as stream:
                    data = stream.read(entry["bytes"] + 1)
                if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise BackupError("Archive file hash mismatch")
    total = sum(len(root["files"]) for root in roots)
    size = sum(entry["bytes"] for root in roots for entry in root["files"])
    if total != receipt.get("files") or size != receipt.get("payload_bytes"):
        raise BackupError("Receipt file count/size mismatch")
    return manifest, {"status": "PASS", "files": total, "bytes": size,
                      "manifest_sha256": sha256(manifest_path),
                      "archive_sha256": sha256(archive_path),
                      "source_unchanged": True if compare_source else "not_checked"}


def check_target(backup: Path, target: Path) -> Path:
    no_links(target)
    target = target.absolute().resolve()
    backup = backup.absolute().resolve()
    if target.name.casefold() != "mpv" or not target.parent.is_dir():
        raise BackupError("Target must be an explicit mpv directory with an existing parent")
    for protected in [backup, PROJECT]:
        if target == protected or target in protected.parents or protected in target.parents:
            raise BackupError("Target overlaps backup or project")
    if target.exists() and not target.is_dir():
        raise BackupError("Target is not a directory")
    if any((target / name).exists() for name in ["mpv.exe", "mpv.com", "portable_config"]):
        raise BackupError("Target is a player installation, not a configuration directory")
    if target.exists():
        inventory(target)  # Reject nested junctions before any rename.
    return target


def require_live_player_closed(target: Path) -> bool:
    appdata = os.environ.get("APPDATA")
    if os.name != "nt" or not appdata or target != (Path(appdata) / "mpv").resolve():
        return False
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mpv.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, timeout=10, check=True)
    if any(row and row[0].casefold() == "mpv.exe" for row in csv.reader(result.stdout.splitlines())):
        raise BackupError("Close mpv before restoring its active configuration")
    return True


def restore_config(backup: Path, target: Path, apply: bool = False, confirm: str = "") -> dict:
    manifest, verification = verify_backup(backup)
    root = next((root for root in manifest["roots"] if root["id"] == "mpv-config"), None)
    if root is None or root["source_kind"] != "directory":
        raise BackupError("No directory-type mpv-config root")
    target = check_target(backup, target)
    if not apply:
        return {**verification, "action": "DRY_RUN", "target": str(target),
                "restore_files": len(root["files"]), "launcher_restored": False}
    if confirm != CONFIRM:
        raise BackupError("Applying restore requires --confirm RESTORE-MPV-CONFIG")
    player_checked = require_live_player_closed(target)
    warnings = [] if player_checked else ["Non-APPDATA target: player state was not checked. Close relevant players manually."]
    stage = Path(tempfile.mkdtemp(prefix=".mpv-restore-stage-", dir=target.parent))
    old: Path | None = None
    installed = False
    try:
        for directory in root["directories"]:
            (stage / directory).mkdir(parents=True, exist_ok=True)
        for entry in root["files"]:
            destination = stage / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / root["payload"] / entry["path"], destination)
        check_tree(stage, root)
        if target.exists():
            suffix = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            old = target.with_name(f"mpv.before-restore-{suffix}")
            if old.exists():
                raise BackupError("Quarantine already exists")
            target.rename(old)
        stage.rename(target)
        installed = True
        check_tree(target, root)
        return {**verification, "action": "RESTORED", "target": str(target),
                "previous_config_preserved": str(old) if old else None,
                "restore_files": len(root["files"]), "launcher_restored": False,
                "player_closed_check": "APPDATA_CHECK_PASSED" if player_checked else "NOT_CHECKED_NON_APPDATA",
                "warnings": warnings}
    except Exception as original_error:
        rollback_errors = []
        failed = None
        if installed and target.exists():
            failed = target.with_name(f"mpv.failed-restore-{dt.datetime.now():%Y%m%d-%H%M%S-%f}")
            try:
                target.rename(failed)
            except OSError as error:
                rollback_errors.append(f"Preserving failed installation failed: {error}")
        if old is not None and old.exists():
            if target.exists():
                rollback_errors.append("Target still exists; refusing to overwrite it during rollback")
            else:
                try:
                    old.rename(target)
                except OSError as error:
                    rollback_errors.append(f"Restoring previous directory failed: {error}")
        if rollback_errors:
            raise BackupError(f"Restore error: {original_error}; rollback errors: {rollback_errors}; "
                              f"previous preserved at {old}; target {target}; failed candidate {failed}") from original_error
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)  # Only our newly-created staging directory.


def rehearse(backup: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="mpv-backup-rehearsal-") as temporary:
        target = Path(temporary) / "mpv"
        target.mkdir()
        (target / "pre-restore-marker.txt").write_text("preserve this old config", encoding="utf-8")
        result = restore_config(backup, target, apply=True, confirm=CONFIRM)
        preserved = Path(result["previous_config_preserved"])
        if not (preserved / "pre-restore-marker.txt").is_file():
            raise BackupError("Previous simulated configuration was not preserved")
        return {"status": "PASS", "action": "REHEARSAL_ONLY", "restore_files": result["restore_files"],
                "old_simulated_config_preserved": True, "live_config_restored": False,
                "launcher_restored": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ["verify", "rehearse", "restore"]:
        sub = subparsers.add_parser(command)
        sub.add_argument("--backup", type=Path, required=True)
        if command == "verify":
            sub.add_argument("--compare-source", action="store_true")
        if command == "restore":
            sub.add_argument("--target", type=Path, required=True)
            sub.add_argument("--apply", action="store_true")
            sub.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify_backup(args.backup, args.compare_source)[1]
        elif args.command == "rehearse":
            result = rehearse(args.backup)
        else:
            result = restore_config(args.backup, args.target, args.apply, args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
