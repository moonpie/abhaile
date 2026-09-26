"""Read protected trees through descriptor-anchored, no-follow traversal."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from abhaile.trust.errors import TrustError

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


@dataclass(frozen=True)
class SecureEntry:
    """Capture stable metadata and bytes from one protected tree entry."""

    path: str
    kind: str
    mode: int
    uid: int
    gid: int
    content: bytes | None


def snapshot_tree(root: Path) -> dict[str, SecureEntry]:
    """Snapshot a tree without following links or reopening validated pathnames."""
    try:
        descriptor = os.open(root, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise TrustError(f"Protected tree is unavailable: {root}") from exc
    try:
        before = os.fstat(descriptor)
        entries = _snapshot_directory(descriptor, PurePosixPath("."))
        _require_same(before, os.fstat(descriptor), PurePosixPath("."))
        return entries
    finally:
        os.close(descriptor)


def _snapshot_directory(descriptor: int, prefix: PurePosixPath) -> dict[str, SecureEntry]:
    entries: dict[str, SecureEntry] = {}
    try:
        names = sorted(os.listdir(descriptor))
    except OSError as exc:
        raise TrustError("Protected tree directory cannot be enumerated") from exc
    for name in names:
        if name in (".", "..") or "/" in name or "\0" in name:
            raise TrustError("Protected tree contains an unsafe entry name")
        relative = PurePosixPath(name) if prefix == PurePosixPath(".") else prefix / name
        try:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as exc:
            raise TrustError(f"Protected tree entry is unavailable: {relative}") from exc
        if stat.S_ISLNK(before.st_mode):
            raise TrustError(f"Protected tree contains a symlink: {relative}")
        if stat.S_ISDIR(before.st_mode):
            child = _open_at(descriptor, name, _DIRECTORY_FLAGS, relative)
            try:
                opened = os.fstat(child)
                _require_same(before, opened, relative)
                entries[relative.as_posix()] = _entry(relative, opened, "directory", None)
                entries.update(_snapshot_directory(child, relative))
                _require_same(opened, os.fstat(child), relative)
            finally:
                os.close(child)
            continue
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise TrustError(f"Protected tree contains an unsupported entry: {relative}")
        child = _open_at(descriptor, name, _FILE_FLAGS, relative)
        try:
            opened = os.fstat(child)
            _require_same(before, opened, relative)
            content = _read_all(child, relative)
            after = os.fstat(child)
            _require_same(opened, after, relative)
            if len(content) != after.st_size:
                raise TrustError(f"Protected tree file changed while reading: {relative}")
            entries[relative.as_posix()] = _entry(relative, after, "file", content)
        finally:
            os.close(child)
    try:
        if sorted(os.listdir(descriptor)) != names:
            raise TrustError(f"Protected tree directory changed during validation: {prefix}")
    except OSError as exc:
        raise TrustError("Protected tree directory cannot be re-enumerated") from exc
    return entries


def materialize_snapshot(snapshot: dict[str, SecureEntry], destination: Path) -> None:
    """Copy a validated snapshot into newly created root-only inodes."""
    try:
        destination.mkdir(mode=0o700, parents=False)
    except OSError as exc:
        raise TrustError(f"Sealed snapshot destination cannot be created: {destination}") from exc
    directories = sorted(
        (entry for entry in snapshot.values() if entry.kind == "directory"),
        key=lambda entry: (len(PurePosixPath(entry.path).parts), entry.path),
    )
    files = sorted(
        (entry for entry in snapshot.values() if entry.kind == "file"),
        key=lambda entry: entry.path,
    )
    try:
        for entry in directories:
            (destination / entry.path).mkdir(mode=0o700)
        for entry in files:
            if entry.content is None:
                raise TrustError(f"Snapshot file has no content: {entry.path}")
            target = destination / entry.path
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                view = memoryview(entry.content)
                while view:
                    written = os.write(descriptor, view)
                    if written == 0:
                        raise TrustError(f"Failed to materialize snapshot file: {entry.path}")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        for directory in reversed(directories):
            _sync_directory(destination / directory.path)
        _sync_directory(destination)
    except (OSError, TrustError):
        raise


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, _DIRECTORY_FLAGS)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_at(parent: int, name: str, flags: int, relative: PurePosixPath) -> int:
    try:
        return os.open(name, flags, dir_fd=parent)
    except OSError as exc:
        raise TrustError(f"Protected tree entry cannot be opened safely: {relative}") from exc


def _read_all(descriptor: int, relative: PurePosixPath) -> bytes:
    chunks: list[bytes] = []
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    except OSError as exc:
        raise TrustError(f"Protected tree file cannot be read: {relative}") from exc
    return b"".join(chunks)


def _require_same(before: os.stat_result, after: os.stat_result, path: PurePosixPath) -> None:
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    current = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity != current:
        raise TrustError(f"Protected tree entry changed during validation: {path}")


def _entry(
    path: PurePosixPath, metadata: os.stat_result, kind: str, content: bytes | None
) -> SecureEntry:
    return SecureEntry(
        path.as_posix(),
        kind,
        metadata.st_mode & 0o7777,
        metadata.st_uid,
        metadata.st_gid,
        content,
    )
