"""Audit rendered manifest identities against the live host filesystem."""

from __future__ import annotations

import hashlib
import json
import os
import grp
import pwd
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from abhaile.models.kinds import ALL_KINDS

AuditScope = Literal["ordinary", "enrollment-foundations"]

FOUNDATION_KINDS = frozenset({"host.sysusers", "host.sudoers", "host.authorized_keys"})
MAX_HASH_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_REPORTED_PATHS = 10
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FOUNDATIONS = {
    ("host.sysusers", "/etc/sysusers.d/abhaile.conf"),
    ("host.sudoers", "/etc/sudoers.d/abhaile"),
}


@dataclass(frozen=True)
class IntegrityResult:
    """Summarize one bounded manifest-integrity audit."""

    scope: AuditScope
    entries: int
    drift: int
    uncertainty: int
    paths: tuple[str, ...]

    @property
    def success(self) -> bool:
        """Return whether every selected entry was proved clean."""
        return self.drift == 0 and self.uncertainty == 0


def audit_manifest(
    manifest_path: Path, scope: AuditScope, *, expected_host: str
) -> IntegrityResult:
    """Audit one closed manifest scope without mutating live state."""
    manifest = _load_manifest(manifest_path, expected_host=expected_host)
    selected = _selected_entries(manifest, scope)
    drift = 0
    uncertainty = 0
    paths: list[str] = []
    for entry in selected:
        outcome = _audit_entry(entry)
        if outcome == "drift":
            drift += 1
        elif outcome == "uncertainty":
            uncertainty += 1
        if outcome != "clean" and len(paths) < MAX_REPORTED_PATHS:
            paths.append(_redact_path(entry.get("target_path")))
    return IntegrityResult(scope, len(selected), drift, uncertainty, tuple(paths))


def result_to_json(result: IntegrityResult) -> str:
    """Serialize an integrity result deterministically."""
    return json.dumps(asdict(result), indent=2, sort_keys=True)


def _load_manifest(path: Path, *, expected_host: str) -> dict[str, Any]:
    """Load the minimum closed manifest structure used by the auditor."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MANIFEST_BYTES:
                raise ValueError("manifest is not a bounded regular file")
            payload_bytes = bytearray()
            while len(payload_bytes) <= before.st_size:
                chunk = os.read(
                    descriptor, min(1024 * 1024, before.st_size + 1 - len(payload_bytes))
                )
                if not chunk:
                    break
                payload_bytes.extend(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if len(payload_bytes) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ) != (after.st_dev, after.st_ino, after.st_size):
            raise ValueError("manifest changed during audit")
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("manifest is not a regular file")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Unable to load integrity manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != "1":
        raise ValueError("Unsupported integrity manifest")
    if payload.get("host") != expected_host or not isinstance(payload.get("entries"), list):
        raise ValueError("Malformed integrity manifest")
    _validate_entries(payload["entries"], expected_host=expected_host)
    return payload


def _validate_entries(entries: list[Any], *, expected_host: str) -> None:
    """Validate closed entry identities and required enrollment foundations."""
    render_paths: set[str] = set()
    target_paths: set[str] = set()
    foundations: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Malformed integrity manifest entry")
        render_path = entry.get("render_path")
        target_path = entry.get("target_path")
        owner_ref = entry.get("owner_ref")
        kind = entry.get("kind")
        is_directory = entry.get("is_directory", False)
        size = entry.get("size")
        digest = entry.get("sha256")
        if (
            not isinstance(render_path, str)
            or not render_path
            or Path(render_path).is_absolute()
            or ".." in Path(render_path).parts
            or not isinstance(target_path, str)
            or not target_path.startswith("/")
            or ".." in Path(target_path).parts
            or not isinstance(owner_ref, str)
            or not owner_ref
            or not isinstance(kind, str)
            or kind not in ALL_KINDS
            or not isinstance(is_directory, bool)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(digest, str)
            or not _SHA256_PATTERN.fullmatch(digest)
            or ("apply_hints" in entry and not isinstance(entry["apply_hints"], dict))
        ):
            raise ValueError("Malformed integrity manifest entry identity")
        if render_path in render_paths or target_path in target_paths:
            raise ValueError("Duplicate integrity manifest entry identity")
        render_paths.add(render_path)
        target_paths.add(target_path)
        if kind in FOUNDATION_KINDS:
            foundations.add((kind, target_path))
            hints = entry.get("apply_hints")
            if kind in {"host.sysusers", "host.sudoers"}:
                expected_target = dict(_REQUIRED_FOUNDATIONS).get(kind)
                expected_owner = (
                    f"host-users:{expected_host}"
                    if kind == "host.sysusers"
                    else f"host-sudoers:{expected_host}"
                )
                expected_mode = "0644" if kind == "host.sysusers" else "0440"
                if (
                    target_path != expected_target
                    or owner_ref != expected_owner
                    or not isinstance(hints, dict)
                    or hints.get("owner_user") != "root"
                    or hints.get("owner_group") != "root"
                    or hints.get("mode") != expected_mode
                ):
                    raise ValueError("Invalid fixed enrollment foundation identity")
            if kind == "host.authorized_keys":
                principal = owner_ref.removeprefix("principal:")
                expected_target = f"/home/{principal}/.ssh/authorized_keys"
                if principal == "root":
                    expected_target = "/root/.ssh/authorized_keys"
                if isinstance(hints, dict) and isinstance(hints.get("home"), str):
                    home = hints["home"]
                    if not home.startswith("/") or ".." in Path(home).parts:
                        raise ValueError("Invalid authorized_keys home")
                    expected_target = home.rstrip("/") + "/.ssh/authorized_keys"
                if (
                    not owner_ref.startswith("principal:")
                    or not principal
                    or target_path != expected_target
                    or not isinstance(hints, dict)
                    or hints.get("owner_user") != principal
                    or not isinstance(hints.get("owner_group"), str)
                    or not hints.get("owner_group")
                    or hints.get("mode") != "0600"
                    or hints.get("ssh_dir_mode") != "0700"
                ):
                    raise ValueError("Invalid authorized_keys foundation identity")
    if not _REQUIRED_FOUNDATIONS <= foundations:
        raise ValueError("Required enrollment foundations are incomplete")


def _selected_entries(manifest: dict[str, Any], scope: AuditScope) -> list[dict[str, Any]]:
    """Select only entries owned by the requested reconciliation boundary."""
    entries = manifest["entries"]
    selected: list[dict[str, Any]] = []
    for entry in entries:
        kind = entry.get("kind")
        is_foundation = kind in FOUNDATION_KINDS
        if (scope == "enrollment-foundations") == is_foundation:
            selected.append(entry)
    return selected


def _audit_entry(entry: dict[str, Any]) -> Literal["clean", "drift", "uncertainty"]:
    """Prove one declared leaf identity or classify the bounded failure."""
    target = entry.get("target_path")
    expected_size = entry.get("size")
    expected_hash = entry.get("sha256")
    is_directory = entry.get("is_directory") is True
    if (
        not isinstance(target, str)
        or not target.startswith("/")
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or not isinstance(expected_hash, str)
        or not _SHA256_PATTERN.fullmatch(expected_hash)
    ):
        return "uncertainty"
    path = Path(target)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return "drift"
    except OSError:
        return "uncertainty"
    if stat.S_ISLNK(before.st_mode):
        return "drift"
    if is_directory:
        if not stat.S_ISDIR(before.st_mode):
            return "drift"
        return _audit_directory_metadata(before, entry)
    if not stat.S_ISREG(before.st_mode):
        return "drift"
    if expected_size > MAX_HASH_BYTES:
        return "uncertainty"
    if before.st_size != expected_size:
        return "drift"
    return _audit_regular_file(path, before, expected_hash, expected_size)


def _audit_regular_file(
    path: Path,
    before: os.stat_result,
    expected_hash: str,
    expected_size: int,
) -> Literal["clean", "drift", "uncertainty"]:
    """Hash one non-symlink regular file and reject identity races."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                return "uncertainty"
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev,
                before.st_ino,
                expected_size,
            ):
                return "uncertainty"
            digest = hashlib.sha256()
            remaining = expected_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    return "uncertainty"
                digest.update(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                return "uncertainty"
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        return "uncertainty"
    if (after.st_dev, after.st_ino, after.st_size) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
    ):
        return "uncertainty"
    return "clean" if digest.hexdigest() == expected_hash else "drift"


def _audit_directory_metadata(
    metadata: os.stat_result, entry: dict[str, Any]
) -> Literal["clean", "drift", "uncertainty"]:
    """Check only directory metadata explicitly carried by the manifest."""
    hints = entry.get("apply_hints")
    if not isinstance(hints, dict):
        return "clean"
    mode = hints.get("mode")
    if mode is not None:
        if not isinstance(mode, str):
            return "uncertainty"
        try:
            expected_mode = int(mode, 8)
        except ValueError:
            return "uncertainty"
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            return "drift"
    for key, actual, resolver in (
        ("owner", metadata.st_uid, _resolve_user),
        ("group", metadata.st_gid, _resolve_group),
    ):
        expected = hints.get(key)
        if expected is None:
            continue
        resolved = resolver(expected)
        if resolved is None:
            return "uncertainty"
        if actual != resolved:
            return "drift"
    return "clean"


def _resolve_user(value: object) -> int | None:
    """Resolve a manifest user name or numeric ID."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value) if value.isdecimal() else pwd.getpwnam(value).pw_uid
    except (KeyError, ValueError):
        return None


def _resolve_group(value: object) -> int | None:
    """Resolve a manifest group name or numeric ID."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value) if value.isdecimal() else grp.getgrnam(value).gr_gid
    except (KeyError, ValueError):
        return None


def _redact_path(value: object) -> str:
    """Return a bounded path identifier without revealing parent components."""
    if not isinstance(value, str):
        return "<malformed>"
    return f".../{Path(value).name}"[:256]
