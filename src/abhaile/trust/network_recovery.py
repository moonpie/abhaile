"""Model network candidate recovery without performing network operations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from abhaile.trust.errors import TrustError
from abhaile.trust.transaction import TransactionPlan, TransactionStage


class NetworkStage(str, Enum):
    """Describe the independently recoverable network transition."""

    PLANNED = "planned"
    SNAPSHOTTED = "snapshotted"
    REVERT_ARMED = "revert-armed"
    CANDIDATE_APPLIED = "candidate-applied"
    REACHABLE = "reachable"
    CONFIRMED = "confirmed"
    REVERTED = "reverted"


@dataclass(frozen=True)
class NetworkRecovery:
    """Bind snapshot, candidate, timer, and deletion approval state."""

    snapshot_sha256: str
    candidate_sha256: str
    revert_token: str
    deletions: bool
    deletion_approved: bool
    stage: NetworkStage = NetworkStage.PLANNED


NETWORK_JOURNAL_VERSION = 1


@dataclass(frozen=True)
class PersistedNetworkRecovery:
    """Bind a repository-only recovery plan to persisted validation evidence."""

    version: int
    transaction_id: str
    candidate_revision: str
    candidate_capsule_sha256: str
    candidate_manifest_sha256: str
    apply_commit_evidence: str | None
    plan: NetworkRecovery
    reachability_sha256: str | None = None
    confirmation_sha256: str | None = None


def advance_network(plan: NetworkRecovery, action: str) -> NetworkRecovery:
    """Advance only the declared safe network transition."""
    expected = {
        NetworkStage.PLANNED: "record-protected-snapshot",
        NetworkStage.SNAPSHOTTED: "arm-independent-revert",
        NetworkStage.REVERT_ARMED: "apply-candidate",
        NetworkStage.CANDIDATE_APPLIED: "verify-reachability",
        NetworkStage.REACHABLE: "confirm-and-cancel-revert",
    }
    if plan.deletions and not plan.deletion_approved and action == "apply-candidate":
        raise TrustError("Network deletion requires separate approval")
    if expected.get(plan.stage) != action:
        raise TrustError("Network recovery transition is out of order")
    stages = list(NetworkStage)
    return replace(plan, stage=stages[stages.index(plan.stage) + 1])


def recover_network(plan: NetworkRecovery, *, token: str) -> NetworkRecovery:
    """Revert an armed or applied candidate using the exact retained token."""
    if token != plan.revert_token or plan.stage not in {
        NetworkStage.REVERT_ARMED,
        NetworkStage.CANDIDATE_APPLIED,
        NetworkStage.REACHABLE,
    }:
        raise TrustError("Network recovery evidence is stale or invalid")
    return replace(plan, stage=NetworkStage.REVERTED)


def persist_network_snapshot(
    root: Path,
    transaction: TransactionPlan,
    snapshot: bytes,
    candidate: bytes,
    plan: NetworkRecovery,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> PersistedNetworkRecovery:
    """Atomically publish a protected snapshot bundle without changing networking."""
    _validate_transaction(transaction)
    if hashlib.sha256(snapshot).hexdigest() != plan.snapshot_sha256:
        raise TrustError("Network snapshot digest does not match the recovery plan")
    if hashlib.sha256(candidate).hexdigest() != plan.candidate_sha256:
        raise TrustError("Network candidate digest does not match the recovery plan")
    persisted = PersistedNetworkRecovery(
        NETWORK_JOURNAL_VERSION,
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
        advance_network(plan, "record-protected-snapshot"),
    )
    _persist_initial_bundle(root, persisted, snapshot, candidate, failure_hook)
    return persisted


def _persist_initial_bundle(
    root: Path,
    persisted: PersistedNetworkRecovery,
    snapshot: bytes,
    candidate: bytes,
    failure_hook: Callable[[str], None] | None,
) -> None:
    """Finish or resume one transaction-bound private-directory publication."""
    if not root.is_absolute() or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", root.name) is None:
        raise TrustError("Network recovery directory name is invalid")
    parent = root.parent
    _verify_root(parent)
    transaction_id = persisted.transaction_id
    staging_name = f".{root.name}.{transaction_id}.pending"
    init_name = f".{root.name}.initialization.json"
    expected_init = _encode_initialization(root.name, staging_name, persisted)

    if root.exists() or root.is_symlink():
        existing = load_network_recovery(root)
        if existing != persisted:
            raise TrustError("Existing network recovery state is transaction-mismatched")
        _finish_initialization_cleanup(parent, init_name, expected_init)
        return

    init_path = parent / init_name
    initialization_preexisting = init_path.exists() or init_path.is_symlink()
    staging = parent / staging_name
    if (staging.exists() or staging.is_symlink()) and not initialization_preexisting:
        raise TrustError("Network recovery staging predates initialization authority")
    if initialization_preexisting:
        if _read_regular(init_path) != expected_init:
            raise TrustError("Network recovery initialization is transaction-mismatched")
    else:
        _inject_failure(failure_hook, "before-initialization-journal")
        _write_new(init_path, expected_init)
        _sync_directory(parent)
        _inject_failure(failure_hook, "after-initialization-journal")

    if staging.exists() or staging.is_symlink():
        _verify_root(staging)
    else:
        _inject_failure(failure_hook, "before-directory-creation")
        staging.mkdir(mode=0o700)
        _sync_directory(parent)
        _inject_failure(failure_hook, "after-directory-creation")

    _ensure_initial_file(staging / "snapshot.bin", snapshot, failure_hook, "snapshot-write")
    _ensure_initial_file(staging / "candidate.bin", candidate, failure_hook, "candidate-write")
    journal = _encode_network_journal(persisted)
    _ensure_initial_file(
        staging / "network.journal.json", journal, failure_hook, "initial-journal-write"
    )
    _inject_failure(failure_hook, "before-directory-fsync-publication")
    _sync_directory(staging)
    parent_fd = _directory_fd(parent)
    try:
        os.rename(staging.name, root.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    _sync_directory(parent)
    _inject_failure(failure_hook, "after-directory-fsync-publication")
    _finish_initialization_cleanup(parent, init_name, expected_init)


def _directory_fd(path: Path) -> int:
    """Open a directory for one short descriptor-relative operation."""
    # os.rename consumes the descriptors synchronously; callers close them immediately below.
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _ensure_initial_file(
    path: Path,
    payload: bytes,
    failure_hook: Callable[[str], None] | None,
    stage: str,
) -> None:
    """Create one initial file or verify the exact durable retry artifact."""
    if path.exists() or path.is_symlink():
        if _read_regular(path) != payload:
            raise TrustError(f"Network recovery {stage} artifact is mismatched")
        return
    _inject_failure(failure_hook, f"before-{stage}")
    _write_new(path, payload)
    _inject_failure(failure_hook, f"after-{stage}")


def _finish_initialization_cleanup(parent: Path, name: str, expected: bytes) -> None:
    """Remove only the exact protected initialization authority after publication."""
    path = parent / name
    if not path.exists() and not path.is_symlink():
        return
    if _read_regular(path) != expected:
        raise TrustError("Network recovery initialization is transaction-mismatched")
    path.unlink()
    _sync_directory(parent)


def _inject_failure(hook: Callable[[str], None] | None, stage: str) -> None:
    """Invoke one isolated-test interruption point."""
    if hook is not None:
        hook(stage)


def _encode_initialization(
    final_name: str, staging_name: str, persisted: PersistedNetworkRecovery
) -> bytes:
    """Encode closed initialization authority before any private bundle exists."""
    value = {
        "version": NETWORK_JOURNAL_VERSION,
        "final_name": final_name,
        "staging_name": staging_name,
        "journal_sha256": hashlib.sha256(_encode_network_journal(persisted)).hexdigest(),
        "transaction_id": persisted.transaction_id,
        "snapshot_sha256": persisted.plan.snapshot_sha256,
        "candidate_sha256": persisted.plan.candidate_sha256,
        "revert_token_sha256": hashlib.sha256(persisted.plan.revert_token.encode()).hexdigest(),
        "deletions": persisted.plan.deletions,
        "deletion_approved": persisted.plan.deletion_approved,
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def persist_network_transition(
    root: Path,
    persisted: PersistedNetworkRecovery,
    action: str,
    *,
    transaction: TransactionPlan,
    evidence: bytes | None = None,
) -> PersistedNetworkRecovery:
    """Persist one pure recovery transition and its bounded evidence digest."""
    _verify_root(root)
    current = load_network_recovery(root)
    if current != persisted or not _matches_transaction(persisted, transaction):
        raise TrustError("Network recovery journal is stale or mismatched")
    next_plan = advance_network(persisted.plan, action)
    reachability = persisted.reachability_sha256
    confirmation = persisted.confirmation_sha256
    if action == "verify-reachability":
        if not evidence:
            raise TrustError("Reachability transition requires explicit evidence")
        reachability = hashlib.sha256(evidence).hexdigest()
    elif action == "confirm-and-cancel-revert":
        if not evidence or reachability is None:
            raise TrustError("Network confirmation requires reachability evidence")
        confirmation = hashlib.sha256(evidence).hexdigest()
    elif evidence is not None:
        raise TrustError("Network transition does not accept extra evidence")
    updated = PersistedNetworkRecovery(
        NETWORK_JOURNAL_VERSION,
        persisted.transaction_id,
        persisted.candidate_revision,
        persisted.candidate_capsule_sha256,
        persisted.candidate_manifest_sha256,
        persisted.apply_commit_evidence,
        next_plan,
        reachability,
        confirmation,
    )
    _write_network_journal(root, updated)
    return updated


def load_network_recovery(root: Path) -> PersistedNetworkRecovery:
    """Load a closed persisted recovery journal and verify its snapshot binding."""
    _verify_root(root)
    try:
        value: Any = json.loads(_read_regular(root / "network.journal.json"))
        required = {
            "version",
            "transaction_id",
            "candidate_revision",
            "candidate_capsule_sha256",
            "candidate_manifest_sha256",
            "apply_commit_evidence",
            "plan",
            "reachability_sha256",
            "confirmation_sha256",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError
        plan_value = value["plan"]
        if not isinstance(plan_value, dict) or set(plan_value) != {
            "snapshot_sha256",
            "candidate_sha256",
            "revert_token",
            "deletions",
            "deletion_approved",
            "stage",
        }:
            raise ValueError
        plan_value["stage"] = NetworkStage(plan_value["stage"])
        persisted = PersistedNetworkRecovery(
            value["version"],
            value["transaction_id"],
            value["candidate_revision"],
            value["candidate_capsule_sha256"],
            value["candidate_manifest_sha256"],
            value["apply_commit_evidence"],
            NetworkRecovery(**plan_value),
            value["reachability_sha256"],
            value["confirmation_sha256"],
        )
        if persisted.version != NETWORK_JOURNAL_VERSION:
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise TrustError("Network recovery journal is malformed") from exc
    snapshot_digest = hashlib.sha256(_read_regular(root / "snapshot.bin")).hexdigest()
    if snapshot_digest != persisted.plan.snapshot_sha256:
        raise TrustError("Persisted network snapshot identity is mismatched")
    candidate_digest = hashlib.sha256(_read_regular(root / "candidate.bin")).hexdigest()
    if candidate_digest != persisted.plan.candidate_sha256:
        raise TrustError("Persisted network candidate identity is mismatched")
    return persisted


def _validate_transaction(transaction: TransactionPlan) -> None:
    """Accept only a non-dry-run transaction before network convergence begins."""
    if transaction.dry_run or transaction.stage is not TransactionStage.PLANNED:
        raise TrustError("Network recovery requires a planned mutating transaction")


def _matches_transaction(persisted: PersistedNetworkRecovery, transaction: TransactionPlan) -> bool:
    """Bind every transition to the exact immutable transaction identity."""
    _validate_transaction(transaction)
    return (
        persisted.transaction_id == transaction.transaction_id
        and persisted.candidate_revision == transaction.candidate_revision
        and persisted.candidate_capsule_sha256 == transaction.candidate_capsule_sha256
        and persisted.candidate_manifest_sha256 == transaction.candidate_manifest_sha256
        and persisted.apply_commit_evidence == transaction.apply_commit_evidence
    )


def _write_network_journal(root: Path, persisted: PersistedNetworkRecovery) -> None:
    """Atomically write and sync the versioned network journal."""
    payload = _encode_network_journal(persisted)
    temporary = root / ".network.journal.pending"
    if temporary.exists() or temporary.is_symlink():
        metadata = temporary.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise TrustError("Network pending journal has an unsafe type")
        temporary.unlink()
    _write_new(temporary, payload)
    os.replace(temporary, root / "network.journal.json")
    _sync_directory(root)


def _encode_network_journal(persisted: PersistedNetworkRecovery) -> bytes:
    """Encode the closed network journal deterministically."""
    value = asdict(persisted)
    value["plan"]["stage"] = persisted.plan.stage.value
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_new(path: Path, payload: bytes) -> None:
    """Create and fsync one no-follow repository-only evidence file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise TrustError("Network recovery evidence write stalled")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular(path: Path) -> bytes:
    """Read one regular single-link evidence file without following links."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TrustError("Network recovery evidence cannot be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise TrustError("Network recovery evidence has an unsafe type")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _verify_root(root: Path) -> None:
    """Require a private executor-owned no-follow evidence directory."""
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TrustError("Network recovery directory cannot be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise TrustError("Network recovery directory ownership or mode is unsafe")
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    """Fsync a no-follow recovery directory."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
