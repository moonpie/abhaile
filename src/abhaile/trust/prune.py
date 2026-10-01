"""Classify and authorize bounded removal of previously managed objects."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Callable

from abhaile.trust.errors import TrustError


class PruneClass(str, Enum):
    """Describe authority over one possible removal."""

    DESIRED = "desired"
    ALREADY_ABSENT = "already-absent"
    EXACT_PRIOR = "exact-prior"
    DRIFTED = "drifted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PruneDecision:
    """Report classification and the separate approval gate used."""

    classification: PruneClass
    remove: bool
    gate: str | None


@dataclass(frozen=True)
class ObjectIdentity:
    """Describe the no-follow type, content, ownership, and mode of an object."""

    kind: str
    sha256: str | None
    uid: int
    gid: int
    mode: int


def inspect_identity(root: Path, relative_path: str) -> ObjectIdentity | None:
    """Inspect an object beneath a trusted directory without following links."""
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise TrustError("Prune target path is not a safe relative path")
    try:
        parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TrustError("Prune trust root cannot be opened safely") from exc
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            os.close(parent_fd)
            parent_fd = next_fd
        leaf = relative.parts[-1]
        try:
            initial = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(initial.st_mode):
            _require_same_entry(parent_fd, leaf, initial)
            return ObjectIdentity(
                "symlink", None, initial.st_uid, initial.st_gid, initial.st_mode & 0o7777
            )
        if stat.S_ISDIR(initial.st_mode):
            _require_same_entry(parent_fd, leaf, initial)
            return ObjectIdentity(
                "directory", None, initial.st_uid, initial.st_gid, initial.st_mode & 0o7777
            )
        if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
            _require_same_entry(parent_fd, leaf, initial)
            return ObjectIdentity(
                "unsupported", None, initial.st_uid, initial.st_gid, initial.st_mode & 0o7777
            )
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            opened = os.fstat(descriptor)
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                raise TrustError("Prune target changed before inspection")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 65536):
                digest.update(chunk)
            after = os.fstat(descriptor)
            if _stat_identity(opened) != _stat_identity(after):
                raise TrustError("Prune target changed during inspection")
            _require_same_entry(parent_fd, leaf, after)
            return ObjectIdentity(
                "file", digest.hexdigest(), opened.st_uid, opened.st_gid, opened.st_mode & 0o7777
            )
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise TrustError("Prune target ancestry or type is unsafe") from exc
    finally:
        os.close(parent_fd)


def _stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Return every identity field relevant to exact prune classification."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _require_same_entry(parent_fd: int, leaf: str, expected: os.stat_result) -> None:
    """Revalidate the directory entry against the observed object identity."""
    try:
        current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise TrustError("Prune target changed during inspection") from exc
    if _stat_identity(current) != _stat_identity(expected):
        raise TrustError("Prune target changed during inspection")


def classify_prune(
    *, desired: bool, prior: ObjectIdentity | None, live: ObjectIdentity | None
) -> PruneClass:
    """Classify live state without silently adopting unmanaged objects."""
    if desired:
        return PruneClass.DESIRED
    if live is None:
        return PruneClass.ALREADY_ABSENT
    if prior is None:
        return PruneClass.UNKNOWN
    if live == prior:
        return PruneClass.EXACT_PRIOR
    return PruneClass.DRIFTED


def authorize_prune(
    classification: PruneClass,
    *,
    prune: bool,
    destructive: bool,
    network: bool = False,
    volume: bool = False,
    network_approved: bool = False,
    volume_approved: bool = False,
) -> PruneDecision:
    """Apply distinct prune, destructive, network, and volume gates."""
    if classification in {PruneClass.DESIRED, PruneClass.ALREADY_ABSENT}:
        return PruneDecision(classification, False, None)
    if classification is PruneClass.UNKNOWN:
        raise TrustError("Unmanaged state cannot be pruned")
    if not prune:
        return PruneDecision(classification, False, "prune")
    if classification is PruneClass.DRIFTED and not destructive:
        return PruneDecision(classification, False, "destructive")
    if network and not network_approved:
        return PruneDecision(classification, False, "network")
    if volume and not volume_approved:
        return PruneDecision(classification, False, "volume")
    return PruneDecision(classification, True, "authorized")


def execute_authorized_prune(
    root: Path,
    relative_path: str,
    *,
    prior: ObjectIdentity,
    authorized_live: ObjectIdentity,
    decision: PruneDecision,
    expected_uid: int,
    expected_gid: int,
    dry_run: bool,
    failure_hook: Callable[[str], None] | None = None,
) -> bool:
    """Remove one revalidated managed object through its protected parent descriptor."""
    if not decision.remove or decision.gate != "authorized":
        raise TrustError("Prune execution lacks complete approval authority")
    expected_class = classify_prune(desired=False, prior=prior, live=authorized_live)
    if decision.classification is not expected_class:
        raise TrustError("Prune decision is not bound to the authorized live identity")
    if authorized_live.kind not in {"file", "directory"}:
        raise TrustError("Prune execution rejects linked or unsupported object types")
    live = inspect_identity(root, relative_path)
    if live is None:
        return False
    if live != authorized_live:
        raise TrustError("Prune target changed after authorization")
    if dry_run:
        return True
    parent_fd, leaf = _open_protected_parent(
        root, relative_path, expected_uid=expected_uid, expected_gid=expected_gid
    )
    try:
        before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        current = inspect_identity(root, relative_path)
        if current != authorized_live:
            raise TrustError("Prune target changed immediately before removal")
        after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if _stat_identity(before) != _stat_identity(after):
            raise TrustError("Prune target changed immediately before removal")
        if authorized_live.kind == "directory":
            os.rmdir(leaf, dir_fd=parent_fd)
        else:
            os.unlink(leaf, dir_fd=parent_fd)
        os.fsync(parent_fd)
        if failure_hook is not None:
            failure_hook("removed")
        return True
    except OSError as exc:
        raise TrustError("Authorized prune could not remove the exact target") from exc
    finally:
        os.close(parent_fd)


def _open_protected_parent(
    root: Path, relative_path: str, *, expected_uid: int, expected_gid: int
) -> tuple[int, str]:
    """Open verified no-follow ancestry and return the leaf's parent descriptor."""
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise TrustError("Prune target path is not a safe relative path")
    try:
        parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        _verify_protected_directory(parent_fd, expected_uid, expected_gid)
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            try:
                _verify_protected_directory(next_fd, expected_uid, expected_gid)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(parent_fd)
            parent_fd = next_fd
    except OSError as exc:
        raise TrustError("Prune target ancestry is unavailable or unsafe") from exc
    return parent_fd, relative.parts[-1]


def _verify_protected_directory(descriptor: int, uid: int, gid: int) -> None:
    """Reject foreign-owned or group/world-writable prune ancestry."""
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != uid
        or metadata.st_gid != gid
        or metadata.st_mode & 0o022
    ):
        raise TrustError("Prune target ancestry ownership or mode is unsafe")
