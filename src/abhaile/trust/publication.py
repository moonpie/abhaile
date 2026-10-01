"""Publish managed filesystem objects through descriptor-bound trusted ancestry."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from abhaile.trust.errors import TrustError

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@dataclass(frozen=True)
class PublicationResult:
    """Describe whether one bounded publication changed managed state."""

    changed: bool
    action: str


def file_matches(root: Path, target: str, *, sha256: str, uid: int, gid: int, mode: int) -> bool:
    """Inspect one target through protected descriptors without changing it."""
    _validate_metadata(uid, gid, mode, directory=False)
    root_fd, parent_fd, leaf = _open_parent(root, target, allowed_uids={0, os.geteuid()})
    try:
        return _inspect_leaf(parent_fd, leaf) == (sha256, uid, gid, mode)
    except OSError as exc:
        raise TrustError("Publication target inspection failed") from exc
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def publish_file(
    root: Path,
    target: str,
    content: bytes,
    *,
    sha256: str,
    uid: int,
    gid: int,
    mode: int,
    check: bool,
) -> PublicationResult:
    """Atomically publish one regular file beneath trusted no-follow ancestry."""
    if hashlib.sha256(content).hexdigest() != sha256:
        raise TrustError("Publication source digest is mismatched")
    _validate_metadata(uid, gid, mode, directory=False)
    root_fd, parent_fd, leaf = _open_parent(root, target, allowed_uids={0, os.geteuid()})
    try:
        existing = _inspect_leaf(parent_fd, leaf)
        unchanged = existing == (sha256, uid, gid, mode)
        if unchanged:
            return PublicationResult(False, "unchanged")
        if check:
            return PublicationResult(True, "would-publish")
        pending = f".{leaf}.abhaile-pending"
        _remove_owned_pending(parent_fd, pending)
        descriptor = os.open(
            pending,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise TrustError("Atomic publication write stalled")
                view = view[written:]
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(pending, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
        return PublicationResult(True, "published")
    except OSError as exc:
        raise TrustError("Atomic file publication failed") from exc
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def publish_directory(
    root: Path,
    target: str,
    *,
    uid: int,
    gid: int,
    mode: int,
    check: bool,
) -> PublicationResult:
    """Create or correct one directory without following target links."""
    _validate_metadata(uid, gid, mode, directory=True)
    root_fd, parent_fd, leaf = _open_parent(root, target, allowed_uids={0, os.geteuid()})
    descriptor: int | None = None
    created = False
    try:
        try:
            descriptor = os.open(leaf, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            if check:
                return PublicationResult(True, "would-create-directory")
            os.mkdir(leaf, mode, dir_fd=parent_fd)
            created = True
            descriptor = os.open(leaf, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        metadata = os.fstat(descriptor)
        changed = created or (
            metadata.st_uid != uid
            or metadata.st_gid != gid
            or stat.S_IMODE(metadata.st_mode) != mode
        )
        if changed and not check:
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        if not check:
            os.fsync(parent_fd)
        return PublicationResult(changed, "would-update-directory" if check else "directory")
    except OSError as exc:
        raise TrustError("Directory publication failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)
        os.close(root_fd)


def _open_parent(root: Path, target: str, *, allowed_uids: set[int]) -> tuple[int, int, str]:
    """Open the target parent and retain every trusted descriptor until mutation ends."""
    relative = _relative_target(root, target)
    try:
        root_fd = os.open(root, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise TrustError("Publication root cannot be opened safely") from exc
    parent_fd = os.dup(root_fd)
    try:
        _verify_directory(parent_fd, allowed_uids)
        for component in relative.parts[:-1]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            try:
                _verify_directory(child, allowed_uids)
            except BaseException:
                os.close(child)
                raise
            os.close(parent_fd)
            parent_fd = child
        return root_fd, parent_fd, relative.parts[-1]
    except (OSError, TrustError) as exc:
        os.close(parent_fd)
        os.close(root_fd)
        if isinstance(exc, TrustError):
            raise
        raise TrustError("Publication target ancestry is unavailable or unsafe") from exc


def _relative_target(root: Path, target: str) -> PurePosixPath:
    value = PurePosixPath(target)
    if not value.is_absolute() or any(part in {"", ".", ".."} for part in value.parts):
        raise TrustError("Publication target is not canonical absolute")
    root_value = PurePosixPath(root.as_posix())
    if root_value == PurePosixPath("/"):
        relative = value.relative_to("/")
    else:
        try:
            relative = value.relative_to(root_value)
        except ValueError:
            # An injected disposable root maps the manifest's absolute target
            # namespace beneath that root; the production root remains `/`.
            relative = value.relative_to("/")
    if not relative.parts:
        raise TrustError("Publication target cannot replace the protected root")
    return relative


def _verify_directory(descriptor: int, allowed_uids: set[int]) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in allowed_uids
        or metadata.st_mode & 0o022
    ):
        raise TrustError("Publication ancestry ownership or mode is unsafe")


def _inspect_leaf(parent_fd: int, leaf: str) -> tuple[str, int, int, int] | None:
    try:
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise TrustError("Publication target has an unexpected type")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        if size != metadata.st_size:
            raise TrustError("Publication target changed during inspection")
        return (
            digest.hexdigest(),
            metadata.st_uid,
            metadata.st_gid,
            stat.S_IMODE(metadata.st_mode),
        )
    finally:
        os.close(descriptor)


def _remove_owned_pending(parent_fd: int, name: str) -> None:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise TrustError("Interrupted publication pending file is unsafe")
    os.unlink(name, dir_fd=parent_fd)
    os.fsync(parent_fd)


def _validate_metadata(uid: int, gid: int, mode: int, *, directory: bool) -> None:
    if (
        type(uid) is not int
        or type(gid) is not int
        or uid < 0
        or gid < 0
        or type(mode) is not int
        or not 0 <= mode <= 0o7777
        or (not directory and stat.S_ISDIR(mode))
    ):
        raise TrustError("Publication ownership or mode is invalid")
