"""Define injectable paths and policies for trusted convergence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from abhaile.trust.errors import TrustError


@dataclass(frozen=True)
class TrustPaths:
    """Describe all privileged trust stores without hard-coding test roots."""

    mirror: Path
    staging: Path
    quarantine: Path
    capsules: Path
    active: Path
    known_hosts: Path
    fetch_identity: Path


@dataclass(frozen=True)
class TrustPolicy:
    """Constrain repository admission and capsule ownership."""

    remote_url: str
    branch: str
    host: str
    root_uid: int = 0
    render_uid: int | None = None
    rollback_history: int = 2
    known_host_pins: tuple[str, ...] = ()
    remote_host: str | None = None
    remote_user: str | None = None
    remote_port: int = 22
    fetch_identity: Path = Path("/etc/abhaile/git-fetch-identity")
    render_python: Path = Path("/usr/lib/abhaile-render-runtime/bin/python")
    render_runtime_root: Path = Path("/usr/lib/abhaile-render-runtime")


def validate_protected_path(path: Path, *, owner_uid: int, regular_file: bool = False) -> None:
    """Reject links, unexpected types, owners, and group/other writable paths."""
    try:
        stat = path.lstat()
    except OSError as exc:
        raise TrustError(f"Protected path is unavailable: {path} ({exc})") from exc
    if path.is_symlink():
        raise TrustError(f"Protected path must not be a symlink: {path}")
    if regular_file and not path.is_file():
        raise TrustError(f"Protected path must be a regular file: {path}")
    if not regular_file and not path.is_dir():
        raise TrustError(f"Protected path must be a directory: {path}")
    if stat.st_uid != owner_uid:
        raise TrustError(f"Protected path has unexpected owner: {path}")
    if stat.st_mode & 0o022:
        raise TrustError(f"Protected path is group/other writable: {path}")


def validate_protected_chain(
    path: Path,
    *,
    anchor: Path,
    owner_uid: int,
    regular_file: bool = False,
) -> None:
    """Validate every component from a protected anchor without accepting links."""
    if not path.is_absolute() or not anchor.is_absolute():
        raise TrustError("Protected path and anchor must be absolute")
    try:
        relative = path.relative_to(anchor)
    except ValueError as exc:
        raise TrustError(f"Protected path is outside its trust anchor: {path}") from exc
    validate_protected_path(anchor, owner_uid=owner_uid)
    current = anchor
    for index, component in enumerate(relative.parts):
        if component in ("", ".", ".."):
            raise TrustError(f"Protected path contains an unsafe component: {path}")
        current /= component
        validate_protected_path(
            current,
            owner_uid=owner_uid,
            regular_file=regular_file and index == len(relative.parts) - 1,
        )


def current_uid() -> int:
    """Return the effective identity for production policy construction."""
    return os.geteuid()
