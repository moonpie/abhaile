"""Persist transaction-bound state records beneath a protected directory."""

from __future__ import annotations

import json
import hashlib
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from abhaile.trust.errors import TrustError
from abhaile.trust.transaction import (
    TransactionPlan,
    TransactionStage,
    commit_apply_state,
    record_local_convergence,
    validate_transaction_commit_evidence,
)


@dataclass(frozen=True)
class StateRecord:
    """Bind one durable ledger record to an immutable transaction identity."""

    transaction_id: str
    candidate_revision: str
    capsule_sha256: str
    manifest_sha256: str
    apply_commit_evidence: str
    runner_lkg_commit_evidence: str | None
    convergence_outcome: str


STATE_JOURNAL_VERSION = 1
STATE_TRANSITIONS = (
    "planned",
    "previous-written",
    "history-written",
    "current-written",
    "committed",
)


def record_from_transaction(plan: TransactionPlan) -> StateRecord:
    """Create a state record only after the apply ledger has committed."""
    if not isinstance(plan, TransactionPlan):
        raise TrustError("Transaction has no durable apply-state evidence")
    validate_transaction_commit_evidence(plan)
    if plan.stage is not TransactionStage.APPLY_COMMITTED or plan.apply_commit_evidence is None:
        raise TrustError("Transaction has no durable apply-state evidence")
    return StateRecord(
        plan.transaction_id,
        plan.candidate_revision,
        plan.candidate_capsule_sha256,
        plan.candidate_manifest_sha256,
        plan.apply_commit_evidence,
        None,
        "changed" if plan.local_changes else "no-op",
    )


def commit_local_apply_result(
    root: Path,
    plan: TransactionPlan,
    *,
    convergence_succeeded: bool,
    validations_succeeded: bool,
    handlers_succeeded: bool,
    prune_succeeded: bool,
    changed: bool,
    expected_uid: int,
    expected_gid: int,
    keep_history: int = 10,
    failure_hook: Callable[[str], None] | None = None,
) -> TransactionPlan:
    """Commit apply state only after every local convergence boundary succeeds."""
    if not all(
        (
            convergence_succeeded,
            validations_succeeded,
            handlers_succeeded,
            prune_succeeded,
        )
    ):
        raise TrustError("Local convergence result cannot authorize apply-state commit")
    if type(changed) is not bool:
        raise TrustError("Local convergence change evidence is invalid")
    converged = record_local_convergence(plan, validations_succeeded=True, changed=changed)
    committed = commit_apply_state(converged)
    commit_state_record(
        root,
        committed,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        keep_history=keep_history,
        failure_hook=failure_hook,
    )
    return committed


def commit_state_record(
    root: Path,
    plan: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
    keep_history: int = 10,
    failure_hook: Callable[[str], None] | None = None,
) -> None:
    """Atomically rotate current, previous, and bounded history records."""
    if keep_history < 1:
        raise TrustError("State history retention must be positive")
    record = record_from_transaction(plan)
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        interrupted = _read_regular(
            root_fd,
            "transaction.journal.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if interrupted is not None:
            interrupted_journal = _decode_journal(interrupted)
            if StateRecord(**interrupted_journal["candidate"]) != record:
                raise TrustError("Interrupted state transaction requires recovery")
            _recover_state_journal(root_fd, expected_uid, expected_gid)
            return
        current = _read_regular(
            root_fd,
            "current.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        _reject_replayed_record(root_fd, record, expected_uid, expected_gid)
        history_name = _next_history_name(root_fd, expected_uid, expected_gid)
        journal: dict[str, object] = {
            "version": STATE_JOURNAL_VERSION,
            "transaction_id": record.transaction_id,
            "candidate": asdict(record),
            "prior": None if current is None else json.loads(current),
            "history_name": history_name,
            "keep_history": keep_history,
            "stage": "planned",
        }
        _write_state_journal(root_fd, journal)
        _inject_failure(failure_hook, "planned")
        if current is not None:
            _inject_failure(failure_hook, "before-previous-write")
            _atomic_write(root_fd, "previous.json", current)
            _inject_failure(failure_hook, "after-previous-write")
            _advance_state_journal(root_fd, journal, "previous-written")
            _inject_failure(failure_hook, "previous-written")
            _inject_failure(failure_hook, "before-history-write")
            _atomic_write(
                root_fd,
                f"history/{history_name}",
                current,
            )
            _inject_failure(failure_hook, "after-history-write")
            _advance_state_journal(root_fd, journal, "history-written")
            _inject_failure(failure_hook, "history-written")
        else:
            _advance_state_journal(root_fd, journal, "previous-written")
            _advance_state_journal(root_fd, journal, "history-written")
        _inject_failure(failure_hook, "before-current-write")
        _atomic_write(root_fd, "current.json", _encode(record))
        _inject_failure(failure_hook, "after-current-write")
        _advance_state_journal(root_fd, journal, "current-written")
        _inject_failure(failure_hook, "current-written")
        _record_replay_authority(root_fd, record, expected_uid, expected_gid)
        _inject_failure(failure_hook, "before-history-prune")
        _prune_history(root_fd, keep_history, expected_uid, expected_gid)
        _inject_failure(failure_hook, "after-history-prune")
        _inject_failure(failure_hook, "before-commit-journal")
        _advance_state_journal(root_fd, journal, "committed")
        _inject_failure(failure_hook, "after-commit-journal")
        _inject_failure(failure_hook, "before-journal-unlink")
        _unlink(root_fd, "transaction.journal.json")
        _inject_failure(failure_hook, "after-journal-unlink")
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def recover_state_record(root: Path, *, expected_uid: int, expected_gid: int) -> StateRecord | None:
    """Read the last fully published current record after interruption."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        _recover_state_journal(root_fd, expected_uid, expected_gid)
        payload = _read_regular(
            root_fd,
            "current.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        return None if payload is None else _decode(payload)
    finally:
        os.close(root_fd)


def recover_previous_state_record(
    root: Path, *, expected_uid: int, expected_gid: int
) -> StateRecord | None:
    """Read the protected prior applied-state identity for rollback binding."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        _recover_state_journal(root_fd, expected_uid, expected_gid)
        payload = _read_regular(
            root_fd,
            "previous.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        return None if payload is None else _decode(payload)
    finally:
        os.close(root_fd)


def _recover_state_journal(root_fd: int, expected_uid: int, expected_gid: int) -> None:
    """Resolve an interrupted rotation to either its prior or published current record."""
    payload = _read_regular(
        root_fd,
        "transaction.journal.json",
        required=False,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if payload is None:
        return
    journal = _decode_journal(payload)
    candidate = StateRecord(**journal["candidate"])
    current = _read_regular(
        root_fd,
        "current.json",
        required=False,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    prior_value = journal["prior"]
    prior = None if prior_value is None else StateRecord(**prior_value)
    if current is not None and _decode(current) not in {prior, candidate}:
        raise TrustError("Interrupted state transaction current record is inconsistent")
    history_name = str(journal["history_name"])
    if prior is not None:
        prior_payload = _encode(prior)
        for name in ("previous.json", f"history/{history_name}"):
            existing = _read_regular(
                root_fd,
                name,
                required=False,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            if existing is not None and _decode(existing) != prior:
                raise TrustError("Interrupted state transaction ancillary record is inconsistent")
            if existing is None:
                _atomic_write(root_fd, name, prior_payload)
    _atomic_write(root_fd, "current.json", _encode(candidate))
    _record_replay_authority(root_fd, candidate, expected_uid, expected_gid)
    _prune_history(root_fd, int(journal["keep_history"]), expected_uid, expected_gid)
    journal["stage"] = "committed"
    _write_state_journal(root_fd, journal)
    _unlink(root_fd, "transaction.journal.json")
    os.fsync(root_fd)


def _write_state_journal(root_fd: int, journal: dict[str, object]) -> None:
    """Durably replace the closed state-rotation journal."""
    payload = (json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _atomic_write(root_fd, "transaction.journal.json", payload)


def _advance_state_journal(root_fd: int, journal: dict[str, object], stage: str) -> None:
    """Advance a journal by exactly one monotonic transition."""
    current = str(journal["stage"])
    if STATE_TRANSITIONS.index(stage) != STATE_TRANSITIONS.index(current) + 1:
        raise TrustError("State transaction journal transition is not monotonic")
    journal["stage"] = stage
    _write_state_journal(root_fd, journal)


def _decode_journal(payload: bytes) -> dict[str, Any]:
    """Decode the versioned closed state-rotation journal."""
    try:
        value = json.loads(payload)
        required = {
            "version",
            "transaction_id",
            "candidate",
            "prior",
            "history_name",
            "keep_history",
            "stage",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError
        if value["version"] != STATE_JOURNAL_VERSION or value["stage"] not in STATE_TRANSITIONS:
            raise ValueError
        if not isinstance(value["candidate"], dict):
            raise ValueError
        if not isinstance(value["keep_history"], int) or value["keep_history"] < 1:
            raise ValueError
        if re.fullmatch(r"[0-9]{20}\.json", value["history_name"]) is None:
            raise ValueError
        candidate = StateRecord(**value["candidate"])
        _validate_record(candidate)
        if value["transaction_id"] != candidate.transaction_id:
            raise ValueError
        if value["prior"] is not None:
            prior = StateRecord(**value["prior"])
            _validate_record(prior)
    except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise TrustError("Protected state transaction journal is malformed") from exc
    return value


def _inject_failure(hook: Callable[[str], None] | None, stage: str) -> None:
    """Invoke an isolated-test failure point after durable transition."""
    if hook is not None:
        hook(stage)


def _unlink(root_fd: int, name: str) -> None:
    """Remove one descriptor-relative journal and sync its directory."""
    os.unlink(name, dir_fd=root_fd)
    os.fsync(root_fd)


def _open_protected_directory(root: Path, uid: int, gid: int) -> int:
    """Open and verify one protected directory without following links."""
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise TrustError(f"Protected state directory is unavailable: {root}") from exc
    if metadata.st_uid != uid or metadata.st_gid != gid or metadata.st_mode & 0o022:
        os.close(descriptor)
        raise TrustError("Protected state directory ownership or mode is unsafe")
    return descriptor


def _read_regular(
    root_fd: int, name: str, *, required: bool, expected_uid: int, expected_gid: int
) -> bytes | None:
    """Read a regular single-link file relative to a trusted descriptor."""
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    except FileNotFoundError:
        if not required:
            return None
        raise TrustError(f"Protected state record is missing: {name}") from None
    except OSError as exc:
        raise TrustError(f"Protected state record cannot be opened: {name}") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise TrustError(f"Protected state record has an unsafe type: {name}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_write(root_fd: int, name: str, payload: bytes) -> None:
    """Replace one descriptor-relative record and fsync its directory."""
    parent, leaf = name.rsplit("/", 1) if "/" in name else ("", name)
    parent_fd = root_fd
    close_parent = False
    if parent:
        try:
            os.mkdir(parent, 0o700, dir_fd=root_fd)
            os.fsync(root_fd)
        except FileExistsError:
            pass
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        close_parent = True
        root_metadata = os.fstat(root_fd)
        parent_metadata = os.fstat(parent_fd)
        if (
            parent_metadata.st_uid != root_metadata.st_uid
            or parent_metadata.st_gid != root_metadata.st_gid
            or parent_metadata.st_mode & 0o022
        ):
            raise TrustError(f"Protected state subdirectory is unsafe: {parent}")
    temporary = f".{leaf}.pending"
    try:
        try:
            pending = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(pending.st_mode) or pending.st_nlink != 1:
                raise TrustError(f"Interrupted state record has an unsafe type: {name}")
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise TrustError(f"Protected state record write stalled: {name}")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except OSError:
            pass
        raise TrustError(f"Protected state record cannot be committed: {name}") from exc
    finally:
        if close_parent:
            os.close(parent_fd)


def _prune_history(root_fd: int, keep: int, expected_uid: int, expected_gid: int) -> None:
    """Remove the oldest excess history records from a protected directory."""
    try:
        history_fd = os.open(
            "history", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
    except FileNotFoundError:
        return
    try:
        metadata = os.fstat(history_fd)
        if (
            metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or metadata.st_mode & 0o022
        ):
            raise TrustError("Protected state history ownership or mode is unsafe")
        names = sorted(name for name in os.listdir(history_fd) if name.endswith(".json"))
        for name in names[:-keep]:
            os.unlink(name, dir_fd=history_fd)
        os.fsync(history_fd)
    finally:
        os.close(history_fd)


def _reject_replayed_record(
    root_fd: int, candidate: StateRecord, expected_uid: int, expected_gid: int
) -> None:
    """Reject transaction/evidence replay using durable and diagnostic authority."""
    replay_fd = _open_replay_directory(root_fd, expected_uid, expected_gid, create=False)
    if replay_fd is not None:
        try:
            for name in _replay_names(candidate):
                marker = _read_regular(
                    replay_fd,
                    name,
                    required=False,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                )
                if marker is not None:
                    raise TrustError("Applied-state transaction evidence is stale or replayed")
        finally:
            os.close(replay_fd)
    payloads: list[bytes] = []
    for name in ("current.json", "previous.json"):
        payload = _read_regular(
            root_fd,
            name,
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if payload is not None:
            payloads.append(payload)
    try:
        history_fd = os.open(
            "history", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
    except FileNotFoundError:
        history_fd = None
    if history_fd is not None:
        try:
            metadata = os.fstat(history_fd)
            if (
                metadata.st_uid != expected_uid
                or metadata.st_gid != expected_gid
                or metadata.st_mode & 0o022
            ):
                raise TrustError("Protected state history ownership or mode is unsafe")
            for name in os.listdir(history_fd):
                if re.fullmatch(r"[0-9]{20}\.json", name) is None:
                    raise TrustError("Protected state history contains an unknown record")
                payload = _read_regular(
                    history_fd,
                    name,
                    required=True,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                )
                assert payload is not None
                payloads.append(payload)
        finally:
            os.close(history_fd)
    for payload in payloads:
        existing = _decode(payload)
        if (
            existing.transaction_id == candidate.transaction_id
            or existing.apply_commit_evidence == candidate.apply_commit_evidence
        ):
            raise TrustError("Applied-state transaction evidence is stale or replayed")


def _record_replay_authority(
    root_fd: int, record: StateRecord, expected_uid: int, expected_gid: int
) -> None:
    """Persist non-expiring replay markers independently of bounded diagnostics."""
    payload = _encode(record)
    replay_fd = _open_replay_directory(root_fd, expected_uid, expected_gid, create=True)
    assert replay_fd is not None
    try:
        for name in _replay_names(record):
            existing = _read_regular(
                replay_fd,
                name,
                required=False,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            if existing is None:
                _atomic_write(replay_fd, name, payload)
            elif existing != payload:
                raise TrustError("Protected replay authority is inconsistent")
    finally:
        os.close(replay_fd)


def _replay_names(record: StateRecord) -> tuple[str, str]:
    """Derive opaque marker names without exposing transaction identifiers as paths."""
    transaction = hashlib.sha256(record.transaction_id.encode()).hexdigest()
    evidence = hashlib.sha256(record.apply_commit_evidence.encode()).hexdigest()
    return (f"transaction-{transaction}", f"evidence-{evidence}")


def _open_replay_directory(
    root_fd: int, expected_uid: int, expected_gid: int, *, create: bool
) -> int | None:
    """Open the protected replay directory without trusting intermediate paths."""
    try:
        descriptor = os.open("replay", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except FileNotFoundError:
        if not create:
            return None
        try:
            os.mkdir("replay", 0o700, dir_fd=root_fd)
            os.fsync(root_fd)
            descriptor = os.open(
                "replay", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
            )
        except OSError as exc:
            raise TrustError("Protected replay directory cannot be created") from exc
    except OSError as exc:
        raise TrustError("Protected replay directory cannot be opened safely") from exc
    metadata = os.fstat(descriptor)
    if (
        metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise TrustError("Protected replay directory ownership or mode is unsafe")
    return descriptor


def _next_history_name(root_fd: int, expected_uid: int, expected_gid: int) -> str:
    """Allocate a monotonic descriptor-relative history sequence name."""
    try:
        history_fd = os.open(
            "history", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
    except FileNotFoundError:
        return "00000000000000000001.json"
    try:
        metadata = os.fstat(history_fd)
        if (
            metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or metadata.st_mode & 0o022
        ):
            raise TrustError("Protected state history ownership or mode is unsafe")
        numbers = [
            int(name.removesuffix(".json"))
            for name in os.listdir(history_fd)
            if re.fullmatch(r"[0-9]{20}\.json", name)
        ]
        return f"{max(numbers, default=0) + 1:020d}.json"
    finally:
        os.close(history_fd)


def _encode(record: StateRecord) -> bytes:
    """Encode a record in deterministic JSON form."""
    return (json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n").encode()


def _decode(payload: bytes) -> StateRecord:
    """Decode and validate one closed state-record object."""
    try:
        value: Any = json.loads(payload)
        if not isinstance(value, dict) or set(value) != set(StateRecord.__dataclass_fields__):
            raise ValueError
        record = StateRecord(**value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected state record is malformed") from exc
    _validate_record(record)
    return record


def _validate_record(record: StateRecord) -> None:
    """Reject identities unsuitable for evidence binding or safe filenames."""
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", record.transaction_id) is None
        or re.fullmatch(r"[0-9a-f]{40}", record.candidate_revision) is None
        or any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (
                record.capsule_sha256,
                record.manifest_sha256,
                record.apply_commit_evidence,
            )
        )
        or (
            record.runner_lkg_commit_evidence is not None
            and re.fullmatch(r"[0-9a-f]{64}", record.runner_lkg_commit_evidence) is None
        )
        or record.convergence_outcome not in {"changed", "no-op"}
    ):
        raise TrustError("Protected state record identity is invalid")
