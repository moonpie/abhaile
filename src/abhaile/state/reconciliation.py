"""Manage the minimal durable reconciliation commit boundary under the runner's lock."""

from __future__ import annotations

import contextlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from abhaile.utils.errors import ApplyError

CURRENT_RUN = "current-run"
FAILED_TARGET = "failed-target"
LAST_SUCCESSFUL_COMMIT = "last-successful-commit"
LAST_FULL_RECONCILIATION = "last-full-reconciliation"
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

StartupAction = Literal[
    "normal",
    "verify-committed",
    "recover-last-successful",
    "enrollment-required",
    "recovery-blocked",
]
Postcheck = Literal["clean", "degraded"]

RUN_OUTCOMES = frozenset(
    {
        "success",
        "recovery-success",
        "offline-last-successful",
        "failure",
        "failure-recovered",
        "failure-before-mutation",
        "fast-forward-failure",
        "retry-suppressed",
        "last-successful-context-failure",
        "enrollment-required",
        "recovery-blocked",
        "dirty-worktree",
        "fast-clean",
        "fast-offline-clean",
        "full-new-commit",
        "full-integrity-drift",
        "full-actionable-health",
        "full-periodic",
        "full-periodic-offline",
        "full-forced",
        "degraded-post-full",
        "degraded-repair-deferred",
        "degraded-enrollment-foundation",
        "degraded-invalid-full-interval",
        "failed-target-suppressed",
    }
)


@dataclass(frozen=True)
class LastFullReconciliation:
    """Represent non-authoritative completed-full scheduling evidence."""

    commit_sha: str
    completed_at: datetime
    postcheck: Postcheck


def _validate_sha(value: str, *, record_name: str) -> str:
    """Return one normalized SHA or reject malformed authority."""
    normalized = value.strip()
    if not _SHA_PATTERN.fullmatch(normalized):
        raise ApplyError(f"Invalid {record_name} commit SHA")
    return normalized


def _require_state_dir(state_dir: Path) -> None:
    """Require an existing real state directory."""
    try:
        metadata = state_dir.lstat()
    except OSError as exc:
        raise ApplyError(f"Runner state directory is unavailable: {state_dir}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ApplyError(f"Runner state path is not a real directory: {state_dir}")


def _read_record(path: Path, *, allow_legacy_suffix: bool) -> str | None:
    """Read one regular record, optionally accepting legacy trailing metadata."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ApplyError(f"Unable to inspect runner state record: {path.name}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ApplyError(f"Runner state record is not a regular file: {path.name}")
    try:
        payload = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ApplyError(f"Unable to read runner state record: {path.name}") from exc
    if allow_legacy_suffix:
        fields = payload.split()
        payload = fields[0] if fields else ""
    return _validate_sha(payload, record_name=path.name)


def read_current_run(state_dir: Path) -> str | None:
    """Read the exact candidate mutation marker."""
    _require_state_dir(state_dir)
    return _read_record(state_dir / CURRENT_RUN, allow_legacy_suffix=False)


def read_last_successful(state_dir: Path) -> str | None:
    """Read last-successful, accepting the existing runner's metadata suffix."""
    _require_state_dir(state_dir)
    return _read_record(state_dir / LAST_SUCCESSFUL_COMMIT, allow_legacy_suffix=True)


def read_failed_target(state_dir: Path) -> str | None:
    """Read failed-target, accepting the existing runner's metadata suffix."""
    _require_state_dir(state_dir)
    return _read_record(state_dir / FAILED_TARGET, allow_legacy_suffix=True)


def read_last_full_reconciliation(state_dir: Path) -> LastFullReconciliation | None:
    """Read a closed last-full scheduling record without treating it as authority."""
    _require_state_dir(state_dir)
    path = state_dir / LAST_FULL_RECONCILIATION
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ApplyError("Unable to inspect last-full-reconciliation") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ApplyError("Runner state record is not a regular file: last-full-reconciliation")
    state_metadata = state_dir.lstat()
    if (
        stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != state_metadata.st_uid
        or metadata.st_gid != state_metadata.st_gid
    ):
        raise ApplyError("Invalid last-full-reconciliation ownership or mode")
    try:
        fields = path.read_text(encoding="utf-8").strip().split()
    except (OSError, UnicodeError) as exc:
        raise ApplyError("Unable to read runner state record: last-full-reconciliation") from exc
    if len(fields) != 3 or not fields[2].startswith("postcheck="):
        raise ApplyError("Invalid last-full-reconciliation record")
    commit_sha = _validate_sha(fields[0], record_name=LAST_FULL_RECONCILIATION)
    try:
        completed_at = datetime.fromisoformat(fields[1].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApplyError("Invalid last-full-reconciliation timestamp") from exc
    if completed_at.tzinfo is None:
        raise ApplyError("Invalid last-full-reconciliation timestamp")
    postcheck = fields[2].split("=", 1)[1]
    if postcheck not in {"clean", "degraded"}:
        raise ApplyError("Invalid last-full-reconciliation postcheck")
    return LastFullReconciliation(commit_sha, completed_at, cast(Postcheck, postcheck))


def _sync_directory(path: Path) -> None:
    """Persist a completed record rename or removal."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_record(path: Path, sha: str) -> None:
    """Atomically publish and sync one SHA-only record."""
    validated = _validate_sha(sha, record_name=path.name)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(f"{validated}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise ApplyError(f"Unable to publish runner state record: {path.name}") from exc
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def mark_current_run(state_dir: Path, candidate_sha: str) -> None:
    """Record the candidate immediately before its first mutation."""
    _require_state_dir(state_dir)
    _write_record(state_dir / CURRENT_RUN, candidate_sha)


def mark_failed_target(state_dir: Path, candidate_sha: str) -> None:
    """Record one candidate that automatic reconciliation must suppress."""
    _require_state_dir(state_dir)
    _write_record(state_dir / FAILED_TARGET, candidate_sha)


def establish_last_successful(state_dir: Path, commit_sha: str) -> None:
    """Record an explicitly completed enrollment as the recovery baseline."""
    _require_state_dir(state_dir)
    if read_current_run(state_dir) is not None:
        raise ApplyError("Cannot establish a baseline while a current run is recorded")
    commit = _validate_sha(commit_sha, record_name=LAST_SUCCESSFUL_COMMIT)
    _write_record(state_dir / LAST_SUCCESSFUL_COMMIT, commit)
    if read_last_successful(state_dir) != commit:
        raise ApplyError("Last-successful baseline verification failed")


def classify_startup(state_dir: Path) -> StartupAction:
    """Classify startup using only current-run and last-successful."""
    current = read_current_run(state_dir)
    last_successful = read_last_successful(state_dir)
    if last_successful is None:
        return "recovery-blocked" if current is not None else "enrollment-required"
    if current is None:
        return "normal"
    if current == last_successful:
        return "verify-committed"
    return "recover-last-successful"


def clear_matching_current_run(state_dir: Path, expected_sha: str) -> None:
    """Remove the marker only when it names the verified expected revision."""
    expected = _validate_sha(expected_sha, record_name=CURRENT_RUN)
    current = read_current_run(state_dir)
    if current != expected:
        raise ApplyError("Current-run marker does not match the verified commit")
    try:
        (state_dir / CURRENT_RUN).unlink()
        _sync_directory(state_dir)
    except OSError as exc:
        raise ApplyError("Unable to clear current-run marker") from exc


def clear_matching_failed_target(state_dir: Path, recorded_sha: str) -> None:
    """Remove failed-target only when it still names the previously read SHA."""
    expected = _validate_sha(recorded_sha, record_name=FAILED_TARGET)
    failed = read_failed_target(state_dir)
    if failed is None:
        return
    if failed != expected:
        raise ApplyError("Failed-target record changed before it could be cleared")
    try:
        (state_dir / FAILED_TARGET).unlink()
        _sync_directory(state_dir)
    except OSError as exc:
        raise ApplyError("Unable to clear failed-target record") from exc


def commit_last_successful(state_dir: Path, candidate_sha: str) -> None:
    """Advance last-successful and then clear its matching mutation marker."""
    candidate = _validate_sha(candidate_sha, record_name=LAST_SUCCESSFUL_COMMIT)
    current = read_current_run(state_dir)
    if current != candidate:
        raise ApplyError("Cannot commit a candidate without its current-run marker")
    _write_record(state_dir / LAST_SUCCESSFUL_COMMIT, candidate)
    if read_last_successful(state_dir) != candidate:
        raise ApplyError("Last-successful verification failed")
    clear_matching_current_run(state_dir, candidate)
