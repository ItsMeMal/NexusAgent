"""Workspace checkpoints with bounded snapshots and safe restore semantics."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple


class CheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be safely created, inspected, or restored."""


class CheckpointManager:
    """Create portable workspace snapshots outside the workspace itself.

    Default restore is overlay-only: it restores files recorded in the snapshot but
    never deletes files created afterwards. Exact restore additionally removes
    eligible new files and therefore requires an explicit confirmation flag.
    """

    EXCLUDED_DIRS = {
        ".git", ".nexus", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "node_modules",
        "bower_components", ".next", ".nuxt", ".output", ".turbo", "coverage",
        "dist", "build", "target", ".gradle", ".cache", "vendor",
        ".ssh", ".aws", ".azure", ".gnupg", ".terraform",
    }
    EXCLUDED_FILE_NAMES = {
        ".netrc", ".npmrc", ".pypirc", "credentials.json", "secrets.json",
        "id_rsa", "id_ed25519", "authorized_keys", "known_hosts",
    }
    EXCLUDED_SUFFIXES = {
        ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdb", ".sqlite-wal",
        ".sqlite-shm",
    }
    MAX_FILES = 10000
    MAX_FILE_BYTES = 5 * 1024 * 1024
    MAX_TOTAL_BYTES = 100 * 1024 * 1024
    CHECKPOINT_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")

    def __init__(self, workspace: Path, storage_root: Optional[Path] = None):
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise CheckpointError(f"Workspace directory does not exist: {self.workspace}")

        if storage_root is None:
            digest = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:16]
            storage_root = Path.home() / ".nexus" / "checkpoints" / digest
        self.storage_root = Path(storage_root).expanduser().resolve()
        if self.storage_root == self.workspace or self.workspace in self.storage_root.parents:
            raise CheckpointError("Checkpoint storage must be outside the workspace.")
        self.storage_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.storage_root, stat.S_IRWXU)
        except OSError:
            pass
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _safe_relative_path(value: str) -> PurePosixPath:
        if not value or "\\" in value:
            raise CheckpointError(f"Invalid checkpoint path: {value!r}")
        relative = PurePosixPath(value)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise CheckpointError(f"Unsafe checkpoint path: {value!r}")
        if relative.parts and re.match(r"^[A-Za-z]:", relative.parts[0]):
            raise CheckpointError(f"Absolute checkpoint path is not allowed: {value!r}")
        return relative

    @classmethod
    def _is_excluded_dir(cls, name: str) -> bool:
        low = name.casefold()
        return low in cls.EXCLUDED_DIRS or low.startswith(".venv-")

    @classmethod
    def _is_sensitive_file(cls, relative: PurePosixPath) -> bool:
        name = relative.name.casefold()
        if name.startswith(".env") and name not in {".env.example", ".env.sample", ".env.template", ".env.dist"}:
            return True
        if name in cls.EXCLUDED_FILE_NAMES:
            return True
        if Path(name).suffix.casefold() in cls.EXCLUDED_SUFFIXES:
            return True
        return False

    def _iter_workspace_files(self):
        for current, dirs, files in os.walk(self.workspace, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(
                name for name in dirs
                if not self._is_excluded_dir(name)
                and not (current_path / name).is_symlink()
            )
            for name in sorted(files):
                path = current_path / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    relative = PurePosixPath(path.relative_to(self.workspace).as_posix())
                    if self._is_sensitive_file(relative):
                        continue
                    size = path.stat().st_size
                    if size > self.MAX_FILE_BYTES:
                        continue
                    yield path, relative
                except (OSError, ValueError):
                    continue

    def _checkpoint_path(self, checkpoint_id: str) -> Path:
        if not self.CHECKPOINT_ID_RE.fullmatch(str(checkpoint_id or "")):
            raise CheckpointError("Invalid checkpoint ID.")
        path = self.storage_root / f"{checkpoint_id}.zip"
        if path.is_symlink() or not path.is_file() or path.resolve().parent != self.storage_root:
            raise CheckpointError(f"Checkpoint '{checkpoint_id}' was not found or is not a regular archive.")
        return path

    def create_checkpoint(self, label: str = "") -> Dict[str, Any]:
        clean_label = re.sub(r"\s+", " ", str(label or "").strip())[:120]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        checkpoint_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        destination = self.storage_root / f"{checkpoint_id}.zip"

        entries: List[Dict[str, Any]] = []
        preserved_paths: List[str] = []
        total_bytes = 0
        skipped_limit = 0

        with self._lock:
            fd, temp_name = tempfile.mkstemp(prefix=".checkpoint-", suffix=".zip", dir=str(self.storage_root))
            os.close(fd)
            try:
                with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for path, relative in self._iter_workspace_files():
                        if len(entries) >= self.MAX_FILES:
                            skipped_limit += 1
                            preserved_paths.append(relative.as_posix())
                            continue
                        try:
                            before = path.stat()
                            if total_bytes + before.st_size > self.MAX_TOTAL_BYTES:
                                skipped_limit += 1
                                preserved_paths.append(relative.as_posix())
                                continue
                            data = path.read_bytes()
                            after = path.stat()
                            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                                skipped_limit += 1
                                preserved_paths.append(relative.as_posix())
                                continue
                            digest = hashlib.sha256(data).hexdigest()
                            archive.writestr(relative.as_posix(), data)
                            entries.append({
                                "path": relative.as_posix(),
                                "size": len(data),
                                "sha256": digest,
                                "mode": stat.S_IMODE(after.st_mode),
                                "mtime_ns": after.st_mtime_ns,
                            })
                            total_bytes += len(data)
                        except (OSError, PermissionError):
                            skipped_limit += 1
                            preserved_paths.append(relative.as_posix())
                    manifest = {
                        "format_version": 1,
                        "id": checkpoint_id,
                        "label": clean_label,
                        "workspace": str(self.workspace),
                        "created_at": self._now(),
                        "file_count": len(entries),
                        "total_bytes": total_bytes,
                        "skipped_count": skipped_limit,
                        "preserved_paths": preserved_paths,
                        "files": entries,
                    }
                    archive.writestr(
                        "checkpoint-manifest.json",
                        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                    )
                os.replace(temp_name, destination)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise

        return {
            "id": checkpoint_id,
            "label": clean_label,
            "created_at": manifest["created_at"],
            "file_count": len(entries),
            "total_bytes": total_bytes,
            "skipped_count": skipped_limit,
            "archive": str(destination),
        }

    def _read_manifest(self, checkpoint_id: str) -> Tuple[Path, Dict[str, Any]]:
        archive_path = self._checkpoint_path(checkpoint_id)
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                bad_member = archive.testzip()
                if bad_member:
                    raise CheckpointError(f"Checkpoint archive integrity failed at '{bad_member}'.")
                raw = archive.read("checkpoint-manifest.json")
            manifest = json.loads(raw.decode("utf-8"))
        except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CheckpointError(f"Cannot read checkpoint '{checkpoint_id}': {error}") from error

        if manifest.get("format_version") != 1 or manifest.get("id") != checkpoint_id:
            raise CheckpointError("Unsupported or mismatched checkpoint manifest.")
        if Path(str(manifest.get("workspace", ""))).resolve() != self.workspace:
            raise CheckpointError("Checkpoint belongs to a different workspace.")
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) > self.MAX_FILES:
            raise CheckpointError("Checkpoint manifest contains an invalid file list.")
        preserved = manifest.get("preserved_paths", [])
        if not isinstance(preserved, list) or len(preserved) > self.MAX_FILES:
            raise CheckpointError("Checkpoint manifest contains an invalid preserved-path list.")
        for preserved_path in preserved:
            self._safe_relative_path(str(preserved_path))
        return archive_path, manifest

    def list_checkpoints(self, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        records: List[Dict[str, Any]] = []
        for path in sorted(self.storage_root.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
            if len(records) >= safe_limit:
                break
            checkpoint_id = path.stem
            try:
                _, manifest = self._read_manifest(checkpoint_id)
                records.append({
                    "id": checkpoint_id,
                    "label": manifest.get("label", ""),
                    "created_at": manifest.get("created_at", ""),
                    "file_count": manifest.get("file_count", 0),
                    "total_bytes": manifest.get("total_bytes", 0),
                    "skipped_count": manifest.get("skipped_count", 0),
                })
            except (CheckpointError, OSError):
                continue
        return records

    def inspect_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        _, manifest = self._read_manifest(checkpoint_id)
        return {
            key: manifest.get(key)
            for key in ("id", "label", "workspace", "created_at", "file_count", "total_bytes", "skipped_count")
        }

    def _prepare_restore(self, archive_path: Path, manifest: Dict[str, Any]):
        restore_items = []
        total_bytes = 0
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = set(archive.namelist())
            for item in manifest["files"]:
                if not isinstance(item, dict):
                    raise CheckpointError("Checkpoint contains an invalid file entry.")
                relative = self._safe_relative_path(str(item.get("path", "")))
                name = relative.as_posix()
                if name not in names or name == "checkpoint-manifest.json":
                    raise CheckpointError(f"Checkpoint file '{name}' is missing from its archive.")
                expected_size = int(item.get("size", -1))
                if expected_size < 0 or expected_size > self.MAX_FILE_BYTES:
                    raise CheckpointError(f"Checkpoint file '{name}' exceeds the restore size limit.")
                data = archive.read(name)
                if len(data) != expected_size or hashlib.sha256(data).hexdigest() != item.get("sha256"):
                    raise CheckpointError(f"Checkpoint file '{name}' failed integrity verification.")
                total_bytes += len(data)
                if total_bytes > self.MAX_TOTAL_BYTES:
                    raise CheckpointError("Checkpoint exceeds the total restore size limit.")
                target = self.workspace.joinpath(*relative.parts)
                current_parent = self.workspace
                for part in relative.parts[:-1]:
                    current_parent = current_parent / part
                    if current_parent.is_symlink():
                        raise CheckpointError(f"Refusing to restore through a symlink directory: '{name}'.")
                resolved_parent = target.parent.resolve()
                if not resolved_parent.is_relative_to(self.workspace):
                    raise CheckpointError(f"Restore path escapes the workspace: '{name}'.")
                if target.is_symlink():
                    raise CheckpointError(f"Refusing to overwrite symlink: '{name}'.")
                restore_items.append((target, data, int(item.get("mode", 0o644))))
        return restore_items

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        mode: str = "overlay",
        confirm_exact: bool = False,
    ) -> Dict[str, Any]:
        restore_mode = str(mode or "overlay").strip().lower()
        if restore_mode not in {"overlay", "exact"}:
            raise CheckpointError("Restore mode must be 'overlay' or 'exact'.")
        if restore_mode == "exact" and confirm_exact is not True:
            raise CheckpointError("Exact restore deletes eligible files absent from the checkpoint; set confirm_exact=true only after explicit user confirmation.")

        archive_path, manifest = self._read_manifest(checkpoint_id)
        if restore_mode == "exact" and int(manifest.get("skipped_count", 0) or 0) > 0:
            raise CheckpointError(
                "Exact restore is unavailable because this snapshot skipped one or more files. "
                "Use overlay restore or create a complete checkpoint before making destructive changes."
            )
        restore_items = self._prepare_restore(archive_path, manifest)
        snapshot_paths = {str(target.relative_to(self.workspace).as_posix()) for target, _, _ in restore_items}
        preserved_paths = set(manifest.get("preserved_paths", []))

        with self._lock:
            safety_checkpoint = self.create_checkpoint(label=f"pre-restore-{checkpoint_id}")
            _, safety_manifest = self._read_manifest(safety_checkpoint["id"])
            safety_captured = {
                str(item.get("path", ""))
                for item in safety_manifest.get("files", [])
                if isinstance(item, dict)
            }
            unprotected_targets = sorted(
                str(target.relative_to(self.workspace).as_posix())
                for target, _, _ in restore_items
                if target.exists()
                and str(target.relative_to(self.workspace).as_posix()) not in safety_captured
            )
            if unprotected_targets:
                raise CheckpointError(
                    "Restore cancelled because the safety checkpoint could not capture files that would be overwritten: "
                    + ", ".join(unprotected_targets[:5])
                )
            if restore_mode == "exact" and int(safety_manifest.get("skipped_count", 0) or 0) > 0:
                raise CheckpointError(
                    f"Exact restore cancelled because the pre-restore safety checkpoint {safety_checkpoint['id']} "
                    "is incomplete; no workspace files were changed."
                )
            staged: List[Tuple[Path, str, int]] = []
            try:
                for target, data, mode_bits in restore_items:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    current_parent = self.workspace
                    relative = target.relative_to(self.workspace)
                    for part in relative.parts[:-1]:
                        current_parent = current_parent / part
                        if current_parent.is_symlink():
                            raise CheckpointError(f"Restore destination changed through a symlink: '{target}'.")
                    resolved_parent = target.parent.resolve()
                    if not resolved_parent.is_relative_to(self.workspace) or target.is_symlink():
                        raise CheckpointError(f"Restore destination changed during operation: '{target}'.")
                    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.restore-", dir=str(target.parent))
                    try:
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(data)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.chmod(temp_name, mode_bits & 0o777)
                        staged.append((target, temp_name, mode_bits))
                    except Exception:
                        try:
                            os.unlink(temp_name)
                        except OSError:
                            pass
                        raise

                restored = 0
                for target, temp_name, _ in staged:
                    os.replace(temp_name, target)
                    restored += 1

                deleted = 0
                if restore_mode == "exact":
                    for path, relative in list(self._iter_workspace_files()):
                        if relative.as_posix() in snapshot_paths or relative.as_posix() in preserved_paths:
                            continue
                        try:
                            path.unlink()
                            deleted += 1
                        except OSError:
                            continue

                return {
                    "id": checkpoint_id,
                    "mode": restore_mode,
                    "restored_files": restored,
                    "deleted_new_files": deleted,
                    "safety_checkpoint_id": safety_checkpoint["id"],
                    "created_at": manifest.get("created_at"),
                }
            finally:
                for _, temp_name, _ in staged:
                    try:
                        os.unlink(temp_name)
                    except OSError:
                        pass
