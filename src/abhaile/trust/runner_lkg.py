"""Durably bind runner last-known-good advancement to one apply transaction."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Protocol, Sequence

from abhaile.trust.errors import TrustError
from abhaile.trust.state_store import (
    _atomic_write,
    _open_protected_directory,
    _read_regular,
    _unlink,
    recover_previous_state_record,
    recover_state_record,
)
from abhaile.trust.transaction import (
    TransactionPlan,
    TransactionStage,
    commit_runner_lkg,
    validate_transaction_commit_evidence,
)

RUNNER_LKG_JOURNAL_VERSION = 1
RUNNER_LKG_TRANSITIONS = ("planned", "ref-advanced", "receipt-written")
HEALTH_ACTIVE_VERSION = 1
HEALTH_TERMINAL_VERSION = 1
HEALTH_ACTIVE_STATES = ("challenged", "failed-awaiting-rollback")


class RunnerLkgLedger(Protocol):
    """Expose the protected mirror operations required by the coordinator."""

    def last_known_good(self) -> str:
        """Return the currently retained protected revision."""

    def advance_last_known_good(self, revision: str, *, expected: str | None) -> None:
        """Compare-and-swap the protected ref and verify its result."""


@dataclass(frozen=True)
class RunnerLkgReceipt:
    """Bind a verified mirror update to the exact transaction identities."""

    transaction_id: str
    candidate_revision: str
    capsule_sha256: str
    manifest_sha256: str
    apply_commit_evidence: str
    runner_lkg_commit_evidence: str
    prior_revision: str
    prior_manifest_sha256: str
    health_evidence_sha256: str


@dataclass(frozen=True)
class WiderHealthChallenge:
    """Bind a post-apply unpredictable health request to one transaction."""

    transaction_id: str
    candidate_revision: str
    capsule_sha256: str
    manifest_sha256: str
    apply_commit_evidence: str
    challenge: str


@dataclass(frozen=True)
class HealthTerminalRecord:
    """Bind one completed health lifecycle to its durable terminal evidence."""

    transaction_id: str
    candidate_revision: str
    capsule_sha256: str
    manifest_sha256: str
    apply_commit_evidence: str
    challenge: str
    outcome: str
    terminal_transaction_id: str
    terminal_commit_evidence: str


def prepare_wider_health_challenge(
    root: Path,
    transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
) -> WiderHealthChallenge:
    """Persist a post-apply health challenge and reject predated results."""
    validate_transaction_commit_evidence(transaction)
    if transaction.stage is not TransactionStage.APPLY_COMMITTED:
        raise TrustError("Wider-health challenge requires committed apply state")
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        active = _read_active_health(root_fd, expected_uid, expected_gid)
        existing_payload = _read_regular(
            root_fd,
            "wider-health.challenge.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        result_payload = _read_regular(
            root_fd,
            "wider-health.result.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if active is None:
            terminal = _read_health_terminal(
                root_fd, transaction.transaction_id, expected_uid, expected_gid
            )
            if terminal is not None and terminal.transaction_id == transaction.transaction_id:
                raise TrustError("Wider-health transaction is already finalized")
            if existing_payload is not None:
                raise TrustError("Unowned wider-health challenge is prohibited")
            if result_payload is not None:
                raise TrustError("Predated wider-health result is prohibited")
            challenge = WiderHealthChallenge(
                transaction.transaction_id,
                transaction.candidate_revision,
                transaction.candidate_capsule_sha256,
                transaction.candidate_manifest_sha256,
                str(transaction.apply_commit_evidence),
                secrets.token_hex(32),
            )
            _write_active_health(root_fd, challenge, "challenged")
            _atomic_write(
                root_fd,
                "wider-health.challenge.json",
                _encode_health_challenge(challenge),
            )
            return challenge
        challenge, _state = active
        if not _challenge_matches_transaction(challenge, transaction):
            raise TrustError("Interrupted wider-health challenge is transaction-mismatched")
        if existing_payload is None:
            _atomic_write(
                root_fd,
                "wider-health.challenge.json",
                _encode_health_challenge(challenge),
            )
            return challenge
        challenge = _decode_health_challenge(existing_payload)
        if not _challenge_matches_transaction(challenge, transaction):
            raise TrustError("Interrupted wider-health challenge is transaction-mismatched")
        return challenge
    finally:
        os.close(root_fd)


def write_protected_health_result(
    root: Path,
    transaction: TransactionPlan,
    observations: Sequence[tuple[str, bool]],
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    """Publish a trusted producer result for an existing protected challenge."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        active = _read_active_health(root_fd, expected_uid, expected_gid)
        if active is None or not _challenge_matches_transaction(active[0], transaction):
            raise TrustError("Wider-health producer lacks active transaction authority")
        challenge_payload = _read_regular(
            root_fd,
            "wider-health.challenge.json",
            required=True,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        assert challenge_payload is not None
        challenge = _decode_health_challenge(challenge_payload)
        if not _challenge_matches_transaction(challenge, transaction):
            raise TrustError("Wider-health producer challenge is transaction-mismatched")
        canonical = tuple(sorted(observations))
        if (
            not canonical
            or any(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", name) is None
                or type(succeeded) is not bool
                for name, succeeded in canonical
            )
            or len({name for name, _succeeded in canonical}) != len(canonical)
        ):
            raise TrustError("Protected wider-health observations are invalid")
        payload = {
            "version": 2,
            "transaction_id": challenge.transaction_id,
            "candidate_revision": challenge.candidate_revision,
            "capsule_sha256": challenge.capsule_sha256,
            "manifest_sha256": challenge.manifest_sha256,
            "apply_commit_evidence": challenge.apply_commit_evidence,
            "challenge": challenge.challenge,
            "observations": [
                {"name": name, "succeeded": succeeded} for name, succeeded in canonical
            ],
        }
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        existing = _read_regular(
            root_fd,
            "wider-health.result.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if existing is None:
            _atomic_write(root_fd, "wider-health.result.json", encoded)
        elif existing != encoded:
            raise TrustError("Protected wider-health result is immutable once published")
    finally:
        os.close(root_fd)


class ProtectedHealthEvidence:
    """Carry verifier-issued health evidence for one exact transaction."""

    transaction_id: str
    candidate_revision: str
    capsule_sha256: str
    manifest_sha256: str
    observations_sha256: str
    succeeded: bool
    _seal: object

    __slots__ = (
        "transaction_id",
        "candidate_revision",
        "capsule_sha256",
        "manifest_sha256",
        "observations_sha256",
        "succeeded",
        "_seal",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Health evidence is issued only by protected observation evaluation")

    @classmethod
    def _issue(
        cls,
        transaction: TransactionPlan,
        observations_sha256: str,
        succeeded: bool,
    ) -> ProtectedHealthEvidence:
        evidence = object.__new__(cls)
        evidence.transaction_id = transaction.transaction_id
        evidence.candidate_revision = transaction.candidate_revision
        evidence.capsule_sha256 = transaction.candidate_capsule_sha256
        evidence.manifest_sha256 = transaction.candidate_manifest_sha256
        evidence.observations_sha256 = observations_sha256
        evidence.succeeded = succeeded
        evidence._seal = _HEALTH_EVIDENCE_SEAL
        return evidence


_AUTHORITY_SEAL = object()
_HEALTH_EVIDENCE_SEAL = object()


def read_protected_health_evidence(
    root: Path,
    transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
) -> ProtectedHealthEvidence:
    """Read and verify one persisted transaction-bound wider-health result."""
    validate_transaction_commit_evidence(transaction)
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        payload = _read_regular(
            root_fd,
            "wider-health.result.json",
            required=True,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    finally:
        os.close(root_fd)
    assert payload is not None
    try:
        value: Any = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {
            "version",
            "transaction_id",
            "candidate_revision",
            "capsule_sha256",
            "manifest_sha256",
            "apply_commit_evidence",
            "challenge",
            "observations",
        }:
            raise ValueError
        if value["version"] != 2 or not isinstance(value["observations"], list):
            raise ValueError
        observations = tuple(
            (item["name"], item["succeeded"])
            for item in value["observations"]
            if isinstance(item, dict) and set(item) == {"name", "succeeded"}
        )
        if len(observations) != len(value["observations"]):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected wider-health result is malformed") from exc
    challenge = _read_health_challenge(root, expected_uid, expected_gid)
    if (
        (
            value["transaction_id"],
            value["candidate_revision"],
            value["capsule_sha256"],
            value["manifest_sha256"],
            value["apply_commit_evidence"],
        )
        != (
            transaction.transaction_id,
            transaction.candidate_revision,
            transaction.candidate_capsule_sha256,
            transaction.candidate_manifest_sha256,
            transaction.apply_commit_evidence,
        )
        or not _challenge_matches_transaction(challenge, transaction)
        or value["challenge"] != challenge.challenge
        or not observations
        or any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", name) is None
            or type(succeeded) is not bool
            for name, succeeded in observations
        )
        or len({name for name, _succeeded in observations}) != len(observations)
    ):
        raise TrustError("Protected wider-health result is mismatched or invalid")
    canonical = tuple(sorted(observations))
    payload = (json.dumps(canonical, separators=(",", ":")) + "\n").encode()
    return ProtectedHealthEvidence._issue(
        transaction,
        hashlib.sha256(payload).hexdigest(),
        all(succeeded for _name, succeeded in canonical),
    )


def await_protected_health_evidence(
    root: Path,
    transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
    timeout_seconds: float,
    poll_seconds: float = 0.01,
) -> ProtectedHealthEvidence:
    """Boundedly await the protected producer's challenge-bound result."""
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise TrustError("Wider-health wait bounds are invalid")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return read_protected_health_evidence(
                root,
                transaction,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
        except TrustError as exc:
            if "is missing: wider-health.result.json" not in str(exc):
                raise
            if time.monotonic() >= deadline:
                raise TrustError("Timed out awaiting protected wider-health result") from exc
            time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))


class VerifiedRunnerLkgAuthority:
    """Carry verifier-issued publication authority within one locked transaction."""

    transaction_id: str
    candidate_revision: str
    capsule_sha256: str
    manifest_sha256: str
    apply_commit_evidence: str
    runner_lkg_commit_evidence: str
    health_evidence_sha256: str
    receipt_sha256: str
    _seal: object

    __slots__ = (
        "transaction_id",
        "candidate_revision",
        "capsule_sha256",
        "manifest_sha256",
        "apply_commit_evidence",
        "runner_lkg_commit_evidence",
        "health_evidence_sha256",
        "receipt_sha256",
        "_seal",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Runner-LKG authority is issued only by protected verification")

    @classmethod
    def _issue(cls, receipt: RunnerLkgReceipt, receipt_sha256: str) -> VerifiedRunnerLkgAuthority:
        authority = object.__new__(cls)
        authority.transaction_id = receipt.transaction_id
        authority.candidate_revision = receipt.candidate_revision
        authority.capsule_sha256 = receipt.capsule_sha256
        authority.manifest_sha256 = receipt.manifest_sha256
        authority.apply_commit_evidence = receipt.apply_commit_evidence
        authority.runner_lkg_commit_evidence = receipt.runner_lkg_commit_evidence
        authority.health_evidence_sha256 = receipt.health_evidence_sha256
        authority.receipt_sha256 = receipt_sha256
        authority._seal = _AUTHORITY_SEAL
        return authority


def _commit_runner_lkg_durably(
    root: Path,
    state_root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    health: ProtectedHealthEvidence,
    *,
    expected_uid: int,
    expected_gid: int,
    failure_hook: Callable[[str], None] | None = None,
) -> TransactionPlan:
    """Advance, verify, journal, and receipt one protected runner-LKG commit."""
    verify_committed_apply_state(state_root, transaction, expected_uid, expected_gid)
    if transaction.stage is not TransactionStage.HEALTHY:
        raise TrustError("Durable runner-LKG commit requires successful wider health")
    committed = commit_runner_lkg(transaction)
    validate_protected_health_evidence(transaction, health)
    if health.succeeded is not True:
        raise TrustError("Failed wider-health evidence cannot commit runner LKG")
    receipt = _receipt_from_transaction(committed, health)
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        existing = _read_receipt(root_fd, expected_uid, expected_gid)
        journal_payload = _read_regular(
            root_fd,
            "runner-lkg.journal.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if journal_payload is None and existing == receipt:
            _verify_ledger(ledger, receipt.candidate_revision)
            return committed
        if (
            journal_payload is None
            and existing is not None
            and existing.transaction_id == receipt.transaction_id
        ):
            raise TrustError("Runner-LKG transaction identity is stale or replayed")
        if journal_payload is None:
            journal: dict[str, object] = {
                "version": RUNNER_LKG_JOURNAL_VERSION,
                "stage": "planned",
                "receipt": asdict(receipt),
            }
            _write_journal(root_fd, journal)
            _inject(failure_hook, "planned")
        else:
            journal = _decode_journal(journal_payload)
            if _decode_receipt_value(journal["receipt"]) != receipt:
                raise TrustError("Interrupted runner-LKG transaction requires exact recovery")

        current = ledger.last_known_good()
        if receipt.prior_revision == receipt.candidate_revision:
            if current != receipt.candidate_revision:
                raise TrustError("Protected runner-LKG ref is inconsistent with recovery authority")
        elif current == receipt.prior_revision:
            _inject(failure_hook, "before-ref-update")
            ledger.advance_last_known_good(
                receipt.candidate_revision, expected=receipt.prior_revision
            )
            _inject(failure_hook, "after-ref-update")
        elif current != receipt.candidate_revision:
            raise TrustError("Protected runner-LKG ref is inconsistent with recovery authority")
        _verify_ledger(ledger, receipt.candidate_revision)
        if journal["stage"] == "planned":
            _advance_journal(root_fd, journal, "ref-advanced")
        _inject(failure_hook, "ref-advanced")

        existing = _read_receipt(root_fd, expected_uid, expected_gid)
        if existing is not None and existing != receipt:
            # Replacing the prior successful receipt is normal only after its ref was the
            # exact retained revision for this transaction.
            if existing.candidate_revision != receipt.prior_revision:
                raise TrustError("Protected runner-LKG receipt does not match prior authority")
        _inject(failure_hook, "before-receipt-write")
        _atomic_write(root_fd, "runner-lkg.current.json", _encode_receipt(receipt))
        _inject(failure_hook, "after-receipt-write")
        if journal["stage"] == "ref-advanced":
            _advance_journal(root_fd, journal, "receipt-written")
        _inject(failure_hook, "receipt-written")
        _inject(failure_hook, "before-journal-unlink")
        _unlink(root_fd, "runner-lkg.journal.json")
        os.fsync(root_fd)
        _inject(failure_hook, "after-journal-unlink")
        return committed
    finally:
        os.close(root_fd)


def verify_runner_lkg_commit(
    root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
) -> RunnerLkgReceipt:
    """Verify the durable receipt and mirror ref before runner publication."""
    validate_transaction_commit_evidence(transaction)
    if transaction.stage is not TransactionStage.RUNNER_COMMITTED:
        raise TrustError("Runner publication requires a committed runner-LKG transaction")
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        if (
            _read_regular(
                root_fd,
                "runner-lkg.journal.json",
                required=False,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            is not None
        ):
            raise TrustError("Runner-LKG recovery must complete before publication")
        receipt = _read_receipt(root_fd, expected_uid, expected_gid)
        if receipt is None or not _receipt_matches_transaction(receipt, transaction):
            raise TrustError("Runner-LKG durable receipt is stale, missing, or mismatched")
        _verify_ledger(ledger, receipt.candidate_revision)
        return receipt
    finally:
        os.close(root_fd)


def runner_lkg_receipt_digest(receipt: RunnerLkgReceipt) -> str:
    """Return the deterministic digest of one verified durable receipt."""
    return hashlib.sha256(_encode_receipt(receipt)).hexdigest()


def _issue_runner_lkg_authority(
    root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
) -> VerifiedRunnerLkgAuthority:
    """Issue an in-process capability only after durable receipt/ref verification."""
    receipt = verify_runner_lkg_commit(
        root,
        transaction,
        ledger,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return VerifiedRunnerLkgAuthority._issue(receipt, runner_lkg_receipt_digest(receipt))


def validate_runner_lkg_authority(
    authority: VerifiedRunnerLkgAuthority, transaction: TransactionPlan
) -> str:
    """Validate that publication authority was issued by the durable verifier."""
    if (
        not isinstance(authority, VerifiedRunnerLkgAuthority)
        or getattr(authority, "_seal", None) is not _AUTHORITY_SEAL
        or getattr(authority, "transaction_id", None) != transaction.transaction_id
        or getattr(authority, "candidate_revision", None) != transaction.candidate_revision
        or getattr(authority, "capsule_sha256", None) != transaction.candidate_capsule_sha256
        or getattr(authority, "manifest_sha256", None) != transaction.candidate_manifest_sha256
        or getattr(authority, "apply_commit_evidence", None) != transaction.apply_commit_evidence
        or getattr(authority, "runner_lkg_commit_evidence", None)
        != transaction.runner_lkg_commit_evidence
        or re.fullmatch(r"[0-9a-f]{64}", getattr(authority, "health_evidence_sha256", "")) is None
        or re.fullmatch(r"[0-9a-f]{64}", getattr(authority, "receipt_sha256", "")) is None
    ):
        raise TrustError("Runner publication lacks verified durable LKG authority")
    return str(authority.receipt_sha256)


@contextmanager
def protected_coordinator_lock(
    root: Path, *, expected_uid: int, expected_gid: int
) -> Iterator[None]:
    """Serialize apply verification, health, LKG commit, and publication authority."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        try:
            descriptor = os.open(
                ".coordinator.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=root_fd,
            )
        except OSError as exc:
            raise TrustError("Protected coordinator lock cannot be opened safely") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                metadata.st_uid != expected_uid
                or metadata.st_gid != expected_gid
                or metadata.st_mode & 0o077
            ):
                raise TrustError("Protected coordinator lock ownership or mode is unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)
    finally:
        os.close(root_fd)


def verify_committed_apply_state(
    root: Path, transaction: TransactionPlan, expected_uid: int, expected_gid: int
) -> None:
    validate_transaction_commit_evidence(transaction)
    if transaction.stage not in {
        TransactionStage.APPLY_COMMITTED,
        TransactionStage.HEALTHY,
        TransactionStage.RUNNER_COMMITTED,
    }:
        raise TrustError("Wider health requires durably committed local apply state")
    record = recover_state_record(root, expected_uid=expected_uid, expected_gid=expected_gid)
    if record is None or (
        record.transaction_id,
        record.candidate_revision,
        record.capsule_sha256,
        record.manifest_sha256,
        record.apply_commit_evidence,
    ) != (
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
    ):
        raise TrustError("Protected apply state does not authorize wider-health promotion")


def verify_retained_lkg_authority(
    root: Path,
    lkg_root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    expected_uid: int,
    expected_gid: int,
) -> None:
    """Bind rollback and promotion authority to protected state plus mirror LKG."""
    ledger_revision = ledger.last_known_good()
    if ledger_revision != transaction.retained_lkg_revision:
        if (
            ledger_revision != transaction.candidate_revision
            or not _durable_state_authorizes_recovery(
                lkg_root, transaction, expected_uid, expected_gid
            )
        ):
            raise TrustError("Protected runner-LKG ref does not match retained authority")
    current = recover_state_record(root, expected_uid=expected_uid, expected_gid=expected_gid)
    if current is None:
        raise TrustError("Protected retained apply-state authority is missing")
    retained = current
    if (
        transaction.candidate_revision == transaction.retained_lkg_revision
        and transaction.candidate_manifest_sha256 == transaction.retained_lkg_manifest_sha256
    ):
        pass
    else:
        previous = recover_previous_state_record(
            root, expected_uid=expected_uid, expected_gid=expected_gid
        )
        if previous is None:
            raise TrustError("Protected applied state does not match retained LKG authority")
        retained = previous
    if (
        retained.candidate_revision,
        retained.manifest_sha256,
    ) != (
        transaction.retained_lkg_revision,
        transaction.retained_lkg_manifest_sha256,
    ):
        raise TrustError("Protected applied state does not match retained LKG authority")


def _durable_state_authorizes_recovery(
    root: Path,
    transaction: TransactionPlan,
    expected_uid: int,
    expected_gid: int,
) -> bool:
    """Return whether an exact journal or receipt explains an advanced ref."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        journal_payload = _read_regular(
            root_fd,
            "runner-lkg.journal.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        receipt_payload = _read_regular(
            root_fd,
            "runner-lkg.current.json",
            required=False,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    finally:
        os.close(root_fd)
    if journal_payload is not None:
        receipt = _decode_receipt_value(_decode_journal(journal_payload)["receipt"])
    elif receipt_payload is not None:
        receipt = _decode_receipt(receipt_payload)
    else:
        return False
    return (
        receipt.transaction_id,
        receipt.candidate_revision,
        receipt.capsule_sha256,
        receipt.manifest_sha256,
        receipt.apply_commit_evidence,
        receipt.prior_revision,
        receipt.prior_manifest_sha256,
    ) == (
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
        transaction.retained_lkg_revision,
        transaction.retained_lkg_manifest_sha256,
    )


def _receipt_from_transaction(
    transaction: TransactionPlan, health: ProtectedHealthEvidence
) -> RunnerLkgReceipt:
    """Create the exact durable receipt represented by a committed transaction."""
    if transaction.apply_commit_evidence is None or transaction.runner_lkg_commit_evidence is None:
        raise TrustError("Runner-LKG transaction evidence is incomplete")
    return RunnerLkgReceipt(
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
        transaction.runner_lkg_commit_evidence,
        transaction.retained_lkg_revision,
        transaction.retained_lkg_manifest_sha256,
        health_evidence_digest(health),
    )


def _receipt_matches_transaction(receipt: RunnerLkgReceipt, transaction: TransactionPlan) -> bool:
    return (
        receipt.transaction_id,
        receipt.candidate_revision,
        receipt.capsule_sha256,
        receipt.manifest_sha256,
        receipt.apply_commit_evidence,
        receipt.runner_lkg_commit_evidence,
        receipt.prior_revision,
        receipt.prior_manifest_sha256,
    ) == (
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
        transaction.runner_lkg_commit_evidence,
        transaction.retained_lkg_revision,
        transaction.retained_lkg_manifest_sha256,
    )


def health_evidence_digest(health: ProtectedHealthEvidence) -> str:
    """Hash the closed protected health result included in durable authority."""
    payload = (
        json.dumps(
            {
                "transaction_id": health.transaction_id,
                "candidate_revision": health.candidate_revision,
                "capsule_sha256": health.capsule_sha256,
                "manifest_sha256": health.manifest_sha256,
                "observations_sha256": health.observations_sha256,
                "succeeded": health.succeeded,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_protected_health_evidence(
    transaction: TransactionPlan, health: ProtectedHealthEvidence
) -> None:
    if (
        not isinstance(health, ProtectedHealthEvidence)
        or getattr(health, "_seal", None) is not _HEALTH_EVIDENCE_SEAL
        or type(health.succeeded) is not bool
        or (
            health.transaction_id,
            health.candidate_revision,
            health.capsule_sha256,
            health.manifest_sha256,
        )
        != (
            transaction.transaction_id,
            transaction.candidate_revision,
            transaction.candidate_capsule_sha256,
            transaction.candidate_manifest_sha256,
        )
        or re.fullmatch(r"[0-9a-f]{64}", health.observations_sha256) is None
    ):
        raise TrustError("Protected wider-health evidence is malformed or mismatched")


def _verify_ledger(ledger: RunnerLkgLedger, expected: str) -> None:
    """Require the protected mirror ledger to expose the expected revision."""
    if ledger.last_known_good() != expected:
        raise TrustError("Protected runner-LKG ledger verification failed")


def _read_receipt(root_fd: int, expected_uid: int, expected_gid: int) -> RunnerLkgReceipt | None:
    """Read and validate the optional current runner-LKG receipt."""
    payload = _read_regular(
        root_fd,
        "runner-lkg.current.json",
        required=False,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return None if payload is None else _decode_receipt(payload)


def _encode_health_challenge(challenge: WiderHealthChallenge) -> bytes:
    """Encode one protected wider-health challenge deterministically."""
    payload = {"version": 1, **asdict(challenge)}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _decode_health_challenge(payload: bytes) -> WiderHealthChallenge:
    """Decode the closed wider-health challenge shape."""
    try:
        value: Any = json.loads(payload)
        fields = set(WiderHealthChallenge.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) != fields | {"version"}:
            raise ValueError
        if value.pop("version") != 1:
            raise ValueError
        challenge = WiderHealthChallenge(**value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected wider-health challenge is malformed") from exc
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", challenge.transaction_id) is None
        or re.fullmatch(r"[0-9a-f]{40}", challenge.candidate_revision) is None
        or any(
            re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in (
                challenge.capsule_sha256,
                challenge.manifest_sha256,
                challenge.apply_commit_evidence,
                challenge.challenge,
            )
        )
    ):
        raise TrustError("Protected wider-health challenge is malformed")
    return challenge


def _read_health_challenge(
    root: Path, expected_uid: int, expected_gid: int
) -> WiderHealthChallenge:
    """Read a protected challenge without following caller-controlled links."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        payload = _read_regular(
            root_fd,
            "wider-health.challenge.json",
            required=True,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        assert payload is not None
        return _decode_health_challenge(payload)
    finally:
        os.close(root_fd)


def _read_active_health(
    root_fd: int, expected_uid: int, expected_gid: int
) -> tuple[WiderHealthChallenge, str] | None:
    """Read the exact active health lifecycle journal."""
    payload = _read_regular(
        root_fd,
        "wider-health.active.json",
        required=False,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if payload is None:
        return None
    try:
        value: Any = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {"version", "state", "challenge"}:
            raise ValueError
        if value["version"] != HEALTH_ACTIVE_VERSION or value["state"] not in HEALTH_ACTIVE_STATES:
            raise ValueError
        challenge_value = value["challenge"]
        if not isinstance(challenge_value, dict):
            raise ValueError
        challenge = _decode_health_challenge(
            (json.dumps(challenge_value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected wider-health active journal is malformed") from exc
    return challenge, str(value["state"])


def _write_active_health(root_fd: int, challenge: WiderHealthChallenge, state: str) -> None:
    """Persist one monotonic active health lifecycle state."""
    if state not in HEALTH_ACTIVE_STATES:
        raise TrustError("Protected wider-health active state is invalid")
    payload = {
        "version": HEALTH_ACTIVE_VERSION,
        "state": state,
        "challenge": json.loads(_encode_health_challenge(challenge)),
    }
    _atomic_write(
        root_fd,
        "wider-health.active.json",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def mark_health_failure_pending_rollback(
    root: Path,
    transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    """Durably retain failed health authority until rollback is committed."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        active = _read_active_health(root_fd, expected_uid, expected_gid)
        if active is None or not _challenge_matches_transaction(active[0], transaction):
            raise TrustError("Failed wider-health state lacks exact active authority")
        if active[1] == "challenged":
            _write_active_health(root_fd, active[0], "failed-awaiting-rollback")
    finally:
        os.close(root_fd)


def finalize_successful_health(
    root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
    failure_hook: Callable[[str], None] | None = None,
) -> None:
    """Finalize health only after the durable runner-LKG receipt exists."""
    if transaction.stage is not TransactionStage.RUNNER_COMMITTED:
        raise TrustError("Successful health finalization requires runner-LKG commit")
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        receipt = _read_receipt(root_fd, expected_uid, expected_gid)
        if receipt is None or not _receipt_matches_transaction(receipt, transaction):
            raise TrustError("Successful health finalization lacks durable LKG receipt")
        _verify_ledger(ledger, transaction.candidate_revision)
        _finalize_health(
            root_fd,
            transaction,
            outcome="promoted",
            terminal_transaction_id=transaction.transaction_id,
            terminal_commit_evidence=receipt.runner_lkg_commit_evidence,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            failure_hook=failure_hook,
        )
    finally:
        os.close(root_fd)


def finalize_failed_health_after_rollback(
    root: Path,
    failed_transaction: TransactionPlan,
    rollback_transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
    failure_hook: Callable[[str], None] | None = None,
) -> None:
    """Finalize failed health only after exact rollback apply state is durable."""
    validate_transaction_commit_evidence(rollback_transaction)
    if rollback_transaction.stage is not TransactionStage.APPLY_COMMITTED:
        raise TrustError("Failed health finalization requires committed rollback state")
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        active = _read_active_health(root_fd, expected_uid, expected_gid)
        if active is None:
            terminal = _read_health_terminal(
                root_fd, failed_transaction.transaction_id, expected_uid, expected_gid
            )
            if (
                terminal is not None
                and _terminal_matches_transaction(terminal, failed_transaction)
                and terminal.outcome == "rollback-completed"
                and terminal.terminal_transaction_id == rollback_transaction.transaction_id
                and terminal.terminal_commit_evidence == rollback_transaction.apply_commit_evidence
            ):
                return
            raise TrustError("Failed health is not awaiting rollback resolution")
        if active[1] != "failed-awaiting-rollback":
            raise TrustError("Failed health is not awaiting rollback resolution")
        _finalize_health(
            root_fd,
            failed_transaction,
            outcome="rollback-completed",
            terminal_transaction_id=rollback_transaction.transaction_id,
            terminal_commit_evidence=str(rollback_transaction.apply_commit_evidence),
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            failure_hook=failure_hook,
        )
    finally:
        os.close(root_fd)


def recover_health_terminal(
    root: Path,
    transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
) -> HealthTerminalRecord | None:
    """Recover interrupted finalization and return this transaction's terminal record."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        terminal = _read_health_terminal(
            root_fd, transaction.transaction_id, expected_uid, expected_gid
        )
        if terminal is None or terminal.transaction_id != transaction.transaction_id:
            return None
        if not _terminal_matches_transaction(terminal, transaction):
            raise TrustError("Protected wider-health terminal record is transaction-mismatched")
        return terminal
    finally:
        os.close(root_fd)


def _finalize_health(
    root_fd: int,
    transaction: TransactionPlan,
    *,
    outcome: str,
    terminal_transaction_id: str,
    terminal_commit_evidence: str,
    expected_uid: int,
    expected_gid: int,
    failure_hook: Callable[[str], None] | None,
) -> None:
    active = _read_active_health(root_fd, expected_uid, expected_gid)
    if active is None or not _challenge_matches_transaction(active[0], transaction):
        terminal = _read_health_terminal(
            root_fd, transaction.transaction_id, expected_uid, expected_gid
        )
        if terminal is not None and _terminal_matches_transaction(terminal, transaction):
            return
        raise TrustError("Health finalization lacks exact active authority")
    terminal = HealthTerminalRecord(
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        str(transaction.apply_commit_evidence),
        active[0].challenge,
        outcome,
        terminal_transaction_id,
        terminal_commit_evidence,
    )
    existing = _read_health_terminal(
        root_fd, transaction.transaction_id, expected_uid, expected_gid
    )
    if existing is None:
        _inject(failure_hook, "before-health-terminal-write")
        _atomic_write(
            root_fd,
            _health_terminal_name(transaction.transaction_id),
            _encode_health_terminal(terminal),
        )
    elif existing != terminal:
        raise TrustError("Protected wider-health terminal record conflicts with active state")
    _inject(failure_hook, "health-terminal-written")
    _finish_health_finalization(root_fd, failure_hook=failure_hook)
    _inject(failure_hook, "health-finalized")


def recover_interrupted_health_finalization(
    root: Path,
    state_root: Path,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    """Finish cleanup only after independently reverifying terminal durability."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        active = _read_active_health(root_fd, expected_uid, expected_gid)
        if active is None:
            return
        terminal = _read_health_terminal(
            root_fd, active[0].transaction_id, expected_uid, expected_gid
        )
        if terminal is None:
            return
        if not _terminal_matches_challenge(terminal, active[0]):
            raise TrustError("Protected wider-health terminal record conflicts with active state")
        if terminal.outcome == "promoted":
            receipt = _read_receipt(root_fd, expected_uid, expected_gid)
            if (
                receipt is None
                or receipt.transaction_id != terminal.transaction_id
                or receipt.candidate_revision != terminal.candidate_revision
                or receipt.capsule_sha256 != terminal.capsule_sha256
                or receipt.manifest_sha256 != terminal.manifest_sha256
                or receipt.apply_commit_evidence != terminal.apply_commit_evidence
                or receipt.runner_lkg_commit_evidence != terminal.terminal_commit_evidence
            ):
                raise TrustError("Health finalization lacks durable runner-LKG authority")
            _verify_ledger(ledger, terminal.candidate_revision)
        else:
            record = recover_state_record(
                state_root, expected_uid=expected_uid, expected_gid=expected_gid
            )
            if (
                record is None
                or record.transaction_id != terminal.terminal_transaction_id
                or record.apply_commit_evidence != terminal.terminal_commit_evidence
            ):
                raise TrustError("Health finalization lacks durable rollback authority")
        _finish_health_finalization(root_fd)
    finally:
        os.close(root_fd)


def require_health_transaction_admission(
    root: Path,
    transaction: TransactionPlan,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    """Reject a new transaction while unrelated health work remains active."""
    root_fd = _open_protected_directory(root, expected_uid, expected_gid)
    try:
        active = _read_active_health(root_fd, expected_uid, expected_gid)
        if active is not None and not _challenge_matches_transaction(active[0], transaction):
            raise TrustError("Unrelated wider-health transaction remains unresolved")
    finally:
        os.close(root_fd)


def _finish_health_finalization(
    root_fd: int, *, failure_hook: Callable[[str], None] | None = None
) -> None:
    for label, name in (
        ("result", "wider-health.result.json"),
        ("challenge", "wider-health.challenge.json"),
        ("active", "wider-health.active.json"),
    ):
        _inject(failure_hook, f"before-health-{label}-unlink")
        try:
            _unlink(root_fd, name)
        except FileNotFoundError:
            pass
        _inject(failure_hook, f"after-health-{label}-unlink")
    os.fsync(root_fd)


def _read_health_terminal(
    root_fd: int, transaction_id: str, expected_uid: int, expected_gid: int
) -> HealthTerminalRecord | None:
    payload = _read_regular(
        root_fd,
        _health_terminal_name(transaction_id),
        required=False,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if payload is None:
        return None
    try:
        value: Any = json.loads(payload)
        fields = set(HealthTerminalRecord.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) != fields | {"version"}:
            raise ValueError
        if value.pop("version") != HEALTH_TERMINAL_VERSION:
            raise ValueError
        terminal = HealthTerminalRecord(**value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected wider-health terminal record is malformed") from exc
    if (
        terminal.outcome not in {"promoted", "rollback-completed"}
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", terminal.transaction_id) is None
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", terminal.terminal_transaction_id) is None
        or re.fullmatch(r"[0-9a-f]{40}", terminal.candidate_revision) is None
        or any(
            re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in (
                terminal.capsule_sha256,
                terminal.manifest_sha256,
                terminal.apply_commit_evidence,
                terminal.challenge,
                terminal.terminal_commit_evidence,
            )
        )
    ):
        raise TrustError("Protected wider-health terminal record is malformed")
    return terminal


def _health_terminal_name(transaction_id: str) -> str:
    """Return a transaction-scoped protected terminal record name."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", transaction_id) is None:
        raise TrustError("Protected wider-health transaction identity is invalid")
    return f"wider-health.terminal.{transaction_id}.json"


def _encode_health_terminal(terminal: HealthTerminalRecord) -> bytes:
    return (
        json.dumps(
            {"version": HEALTH_TERMINAL_VERSION, **asdict(terminal)},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _terminal_matches_challenge(
    terminal: HealthTerminalRecord, challenge: WiderHealthChallenge
) -> bool:
    return (
        terminal.transaction_id,
        terminal.candidate_revision,
        terminal.capsule_sha256,
        terminal.manifest_sha256,
        terminal.apply_commit_evidence,
        terminal.challenge,
    ) == (
        challenge.transaction_id,
        challenge.candidate_revision,
        challenge.capsule_sha256,
        challenge.manifest_sha256,
        challenge.apply_commit_evidence,
        challenge.challenge,
    )


def _terminal_matches_transaction(
    terminal: HealthTerminalRecord, transaction: TransactionPlan
) -> bool:
    return (
        terminal.transaction_id,
        terminal.candidate_revision,
        terminal.capsule_sha256,
        terminal.manifest_sha256,
        terminal.apply_commit_evidence,
    ) == (
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
    )


def _challenge_matches_transaction(
    challenge: WiderHealthChallenge, transaction: TransactionPlan
) -> bool:
    """Return whether a challenge binds the exact committed apply identity."""
    return (
        challenge.transaction_id,
        challenge.candidate_revision,
        challenge.capsule_sha256,
        challenge.manifest_sha256,
        challenge.apply_commit_evidence,
    ) == (
        transaction.transaction_id,
        transaction.candidate_revision,
        transaction.candidate_capsule_sha256,
        transaction.candidate_manifest_sha256,
        transaction.apply_commit_evidence,
    )


def _write_journal(root_fd: int, journal: dict[str, object]) -> None:
    """Atomically persist and sync the closed promotion journal."""
    _atomic_write(
        root_fd,
        "runner-lkg.journal.json",
        (json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def _advance_journal(root_fd: int, journal: dict[str, object], stage: str) -> None:
    """Advance the durable journal by exactly one transition."""
    current = str(journal["stage"])
    if RUNNER_LKG_TRANSITIONS.index(stage) != RUNNER_LKG_TRANSITIONS.index(current) + 1:
        raise TrustError("Runner-LKG journal transition is not monotonic")
    journal["stage"] = stage
    _write_journal(root_fd, journal)


def _decode_journal(payload: bytes) -> dict[str, Any]:
    """Decode and validate the closed runner-LKG journal shape."""
    try:
        value: Any = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {"version", "stage", "receipt"}:
            raise ValueError
        if value["version"] != RUNNER_LKG_JOURNAL_VERSION:
            raise ValueError
        if value["stage"] not in RUNNER_LKG_TRANSITIONS:
            raise ValueError
        _decode_receipt_value(value["receipt"])
        return value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustError("Protected runner-LKG journal is malformed") from exc


def _encode_receipt(receipt: RunnerLkgReceipt) -> bytes:
    """Encode a durable receipt deterministically."""
    return (json.dumps(asdict(receipt), sort_keys=True, separators=(",", ":")) + "\n").encode()


def _decode_receipt(payload: bytes) -> RunnerLkgReceipt:
    """Decode a protected receipt payload."""
    try:
        return _decode_receipt_value(json.loads(payload))
    except json.JSONDecodeError as exc:
        raise TrustError("Protected runner-LKG receipt is malformed") from exc


def _decode_receipt_value(value: object) -> RunnerLkgReceipt:
    """Validate and construct a runner-LKG receipt value."""
    try:
        if not isinstance(value, dict) or set(value) != set(RunnerLkgReceipt.__dataclass_fields__):
            raise ValueError
        receipt = RunnerLkgReceipt(**value)
    except (TypeError, ValueError) as exc:
        raise TrustError("Protected runner-LKG receipt is malformed") from exc
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", receipt.transaction_id) is None
        or re.fullmatch(r"[0-9a-f]{40}", receipt.candidate_revision) is None
        or re.fullmatch(r"[0-9a-f]{40}", receipt.prior_revision) is None
        or any(
            re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in (
                receipt.capsule_sha256,
                receipt.manifest_sha256,
                receipt.apply_commit_evidence,
                receipt.runner_lkg_commit_evidence,
                receipt.prior_manifest_sha256,
                receipt.health_evidence_sha256,
            )
        )
    ):
        raise TrustError("Protected runner-LKG receipt identity is invalid")
    return receipt


def _inject(hook: Callable[[str], None] | None, boundary: str) -> None:
    """Invoke an optional deterministic interruption hook."""
    if hook is not None:
        hook(boundary)
