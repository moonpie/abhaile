"""Coordinate protected Phase 4 transaction mechanics in their required order."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from abhaile.trust.errors import TrustError
from abhaile.trust.network_recovery import (
    NetworkRecovery,
    PersistedNetworkRecovery,
    persist_network_snapshot,
)
from abhaile.trust.prune import ObjectIdentity, PruneDecision, execute_authorized_prune
from abhaile.trust.runner_publication import (
    _publish_runner_candidates,
    _recover_runner_publication,
)
from abhaile.trust.runner_lkg import (
    RunnerLkgLedger,
    _commit_runner_lkg_durably,
    _issue_runner_lkg_authority,
    await_protected_health_evidence,
    finalize_failed_health_after_rollback,
    finalize_successful_health,
    mark_health_failure_pending_rollback,
    prepare_wider_health_challenge,
    protected_coordinator_lock,
    recover_health_terminal,
    recover_interrupted_health_finalization,
    require_health_transaction_admission,
    validate_protected_health_evidence,
    verify_committed_apply_state,
    verify_runner_lkg_commit,
    verify_retained_lkg_authority,
)
from abhaile.trust.runner_update import (
    RunnerPublicationEvidence,
    RunnerUpdatePlan,
    bind_runner_publication_evidence,
)
from abhaile.trust.state_store import (
    commit_local_apply_result,
    recover_previous_state_record,
    recover_state_record,
)
from abhaile.trust.transaction import (
    RollbackPlan,
    TransactionPlan,
    commit_runner_lkg,
    commit_rollback_apply_state,
    commit_apply_state,
    plan_rollback,
    record_local_convergence,
    record_wider_health,
)


@dataclass(frozen=True)
class LocalConvergenceResult:
    """Carry complete local convergence evidence into the apply-state gate."""

    convergence_succeeded: bool
    validations_succeeded: bool
    handlers_succeeded: bool
    changed: bool


@dataclass(frozen=True)
class AuthorizedPrune:
    """Bind one removal to its inspected identities and approval decision."""

    root: Path
    relative_path: str
    prior: ObjectIdentity
    authorized_live: ObjectIdentity
    decision: PruneDecision
    expected_uid: int
    expected_gid: int


@dataclass(frozen=True)
class HealthResult:
    """Return either a promoted transaction or its exact rollback plan."""

    transaction: TransactionPlan
    rollback: RollbackPlan | None


@dataclass(frozen=True)
class RollbackResult:
    """Return the failed transaction marker and newly committed retained state."""

    failed_transaction: TransactionPlan
    applied_transaction: TransactionPlan


@dataclass(frozen=True)
class NetworkRecoveryRequest:
    """Carry optional network recovery inputs into the ordered coordinator."""

    root: Path
    snapshot: bytes
    candidate: bytes
    recovery: NetworkRecovery


@dataclass(frozen=True)
class RunnerPublicationRequest:
    """Carry optional staged runner publication inputs into the ordered coordinator."""

    stage_root: Path
    unit_root: Path
    plan: RunnerUpdatePlan
    lock_device: int
    lock_inode: int
    reload_manager: Callable[[], None]
    rearm_timer: Callable[[], None]


@dataclass(frozen=True)
class OrderedTransactionResult:
    """Return every durable result produced by one ordered coordinator run."""

    health: HealthResult
    network: PersistedNetworkRecovery | None
    runner_evidence: RunnerPublicationEvidence | None


class ProtectedTransactionCoordinator:
    """Enforce the complete Phase 4 transaction order under one protected lock."""

    def __init__(
        self,
        state_root: Path,
        lkg_root: Path,
        ledger: RunnerLkgLedger,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> None:
        self.state_root = state_root
        self.lkg_root = lkg_root
        self.ledger = ledger
        self.expected_uid = expected_uid
        self.expected_gid = expected_gid

    def run(
        self,
        transaction: TransactionPlan,
        converge: Callable[[], LocalConvergenceResult],
        *,
        network: NetworkRecoveryRequest | None = None,
        runner: RunnerPublicationRequest | None = None,
        prunes: Sequence[AuthorizedPrune] = (),
        failure_hook: Callable[[str], None] | None = None,
        health_timeout_seconds: float = 30.0,
    ) -> OrderedTransactionResult:
        """Prepare recovery, converge, commit, assess health, promote, then publish."""
        with protected_coordinator_lock(
            self.lkg_root,
            expected_uid=self.expected_uid,
            expected_gid=self.expected_gid,
        ):
            recover_interrupted_health_finalization(
                self.lkg_root,
                self.state_root,
                self.ledger,
                expected_uid=self.expected_uid,
                expected_gid=self.expected_gid,
            )
            require_health_transaction_admission(
                self.lkg_root,
                transaction,
                expected_uid=self.expected_uid,
                expected_gid=self.expected_gid,
            )
            persisted = None
            if network is not None:
                persisted = prepare_network_recovery(
                    network.root,
                    transaction,
                    network.snapshot,
                    network.candidate,
                    network.recovery,
                    failure_hook=failure_hook,
                )
            local_result = converge()
            applied = _commit_local_transaction(
                self.state_root,
                transaction,
                local_result,
                prunes=prunes,
                expected_uid=self.expected_uid,
                expected_gid=self.expected_gid,
                failure_hook=failure_hook,
            )
            health = _evaluate_wider_health_locked(
                self.state_root,
                self.lkg_root,
                applied,
                self.ledger,
                expected_uid=self.expected_uid,
                expected_gid=self.expected_gid,
                failure_hook=failure_hook,
                health_timeout_seconds=health_timeout_seconds,
            )
            runner_evidence = None
            if runner is not None:
                if health.rollback is not None:
                    raise TrustError("Runner publication is prohibited while rollback is required")
                runner_evidence = _publish_committed_runner_locked(
                    self.state_root,
                    runner.stage_root,
                    runner.unit_root,
                    self.lkg_root,
                    health.transaction,
                    runner.plan,
                    self.ledger,
                    expected_uid=self.expected_uid,
                    expected_gid=self.expected_gid,
                    lock_device=runner.lock_device,
                    lock_inode=runner.lock_inode,
                    reload_manager=runner.reload_manager,
                    rearm_timer=runner.rearm_timer,
                    failure_hook=failure_hook,
                )
            return OrderedTransactionResult(health, persisted, runner_evidence)


def prepare_network_recovery(
    root: Path,
    transaction: TransactionPlan,
    snapshot: bytes,
    candidate: bytes,
    recovery: NetworkRecovery,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> PersistedNetworkRecovery:
    """Persist recovery authority before any separately authorized network executor runs."""
    if transaction.dry_run:
        raise TrustError("Dry-run cannot persist network recovery state")
    return persist_network_snapshot(
        root,
        transaction,
        snapshot,
        candidate,
        recovery,
        failure_hook=failure_hook,
    )


def _commit_local_transaction(
    state_root: Path,
    transaction: TransactionPlan,
    result: LocalConvergenceResult,
    *,
    prunes: Sequence[AuthorizedPrune] = (),
    expected_uid: int,
    expected_gid: int,
    keep_history: int = 10,
    failure_hook: Callable[[str], None] | None = None,
) -> TransactionPlan:
    """Execute authorized prunes last, then commit truthful local apply state."""
    if transaction.dry_run:
        raise TrustError("Dry-run cannot execute prunes or commit apply state")
    if not all(
        (
            result.convergence_succeeded,
            result.validations_succeeded,
            result.handlers_succeeded,
        )
    ):
        raise TrustError("Incomplete local convergence cannot enter the commit boundary")
    changed = result.changed
    for prune in prunes:
        changed = (
            execute_authorized_prune(
                prune.root,
                prune.relative_path,
                prior=prune.prior,
                authorized_live=prune.authorized_live,
                decision=prune.decision,
                expected_uid=prune.expected_uid,
                expected_gid=prune.expected_gid,
                dry_run=False,
            )
            or changed
        )
    return commit_local_apply_result(
        state_root,
        transaction,
        convergence_succeeded=True,
        validations_succeeded=True,
        handlers_succeeded=True,
        prune_succeeded=True,
        changed=changed,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        keep_history=keep_history,
        failure_hook=failure_hook,
    )


def evaluate_wider_health(
    state_root: Path,
    lkg_root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
    failure_hook: Callable[[str], None] | None = None,
    health_timeout_seconds: float = 30.0,
) -> HealthResult:
    """Evaluate protected health and durably promote under one coordinator lock."""
    with protected_coordinator_lock(lkg_root, expected_uid=expected_uid, expected_gid=expected_gid):
        return _evaluate_wider_health_locked(
            state_root,
            lkg_root,
            transaction,
            ledger,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            failure_hook=failure_hook,
            health_timeout_seconds=health_timeout_seconds,
        )


def _evaluate_wider_health_locked(
    state_root: Path,
    lkg_root: Path,
    transaction: TransactionPlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
    failure_hook: Callable[[str], None] | None,
    health_timeout_seconds: float,
) -> HealthResult:
    """Perform the health/LKG sequence while the protected coordinator lock is held."""
    verify_committed_apply_state(state_root, transaction, expected_uid, expected_gid)
    recover_interrupted_health_finalization(
        lkg_root,
        state_root,
        ledger,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    verify_retained_lkg_authority(
        state_root, lkg_root, transaction, ledger, expected_uid, expected_gid
    )
    terminal = recover_health_terminal(
        lkg_root,
        transaction,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if terminal is not None:
        if terminal.outcome != "promoted":
            raise TrustError("Wider-health transaction was already resolved by rollback")
        assessed = record_wider_health(transaction, succeeded=True)
        committed = commit_runner_lkg(assessed)
        verify_runner_lkg_commit(
            lkg_root,
            committed,
            ledger,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        return HealthResult(committed, None)
    prepare_wider_health_challenge(
        lkg_root,
        transaction,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    health = await_protected_health_evidence(
        lkg_root,
        transaction,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        timeout_seconds=health_timeout_seconds,
    )
    validate_protected_health_evidence(transaction, health)
    # The health gate may be long-running. Re-read both candidate and retained
    # authority under the coordinator lock immediately before either outcome.
    verify_committed_apply_state(state_root, transaction, expected_uid, expected_gid)
    verify_retained_lkg_authority(
        state_root, lkg_root, transaction, ledger, expected_uid, expected_gid
    )
    succeeded = health.succeeded is True
    assessed = record_wider_health(transaction, succeeded=succeeded)
    if not succeeded:
        mark_health_failure_pending_rollback(
            lkg_root,
            assessed,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        return HealthResult(assessed, plan_rollback(assessed))
    committed = _commit_runner_lkg_durably(
        lkg_root,
        state_root,
        assessed,
        ledger,
        health,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        failure_hook=failure_hook,
    )
    finalize_successful_health(
        lkg_root,
        committed,
        ledger,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        failure_hook=failure_hook,
    )
    return HealthResult(committed, None)


def commit_rollback_transaction(
    state_root: Path,
    lkg_root: Path,
    failed_transaction: TransactionPlan,
    rollback_transaction: TransactionPlan,
    result: LocalConvergenceResult,
    *,
    expected_uid: int,
    expected_gid: int,
    keep_history: int = 10,
    failure_hook: Callable[[str], None] | None = None,
) -> RollbackResult:
    """Commit retained LKG state only after its rollback convergence validates."""
    with protected_coordinator_lock(lkg_root, expected_uid=expected_uid, expected_gid=expected_gid):
        return _commit_rollback_transaction_locked(
            state_root,
            lkg_root,
            failed_transaction,
            rollback_transaction,
            result,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            keep_history=keep_history,
            failure_hook=failure_hook,
        )


def _commit_rollback_transaction_locked(
    state_root: Path,
    lkg_root: Path,
    failed_transaction: TransactionPlan,
    rollback_transaction: TransactionPlan,
    result: LocalConvergenceResult,
    *,
    expected_uid: int,
    expected_gid: int,
    keep_history: int,
    failure_hook: Callable[[str], None] | None,
) -> RollbackResult:
    """Commit rollback state while the protected coordinator lock is held."""
    if not all(
        (
            result.convergence_succeeded,
            result.validations_succeeded,
            result.handlers_succeeded,
        )
    ):
        raise TrustError("Incomplete rollback convergence cannot enter the commit boundary")
    expected_applied = commit_apply_state(
        record_local_convergence(
            rollback_transaction,
            validations_succeeded=True,
            changed=result.changed,
        )
    )
    current = recover_state_record(state_root, expected_uid=expected_uid, expected_gid=expected_gid)
    if current is not None and (
        current.transaction_id,
        current.candidate_revision,
        current.capsule_sha256,
        current.manifest_sha256,
        current.apply_commit_evidence,
        current.convergence_outcome,
    ) == (
        expected_applied.transaction_id,
        expected_applied.candidate_revision,
        expected_applied.candidate_capsule_sha256,
        expected_applied.candidate_manifest_sha256,
        expected_applied.apply_commit_evidence,
        "changed" if expected_applied.local_changes else "no-op",
    ):
        marker = commit_rollback_apply_state(
            failed_transaction,
            convergence_succeeded=True,
            validations_succeeded=True,
        )
        finalize_failed_health_after_rollback(
            lkg_root,
            marker,
            expected_applied,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            failure_hook=failure_hook,
        )
        return RollbackResult(marker, expected_applied)
    rollback = plan_rollback(failed_transaction)
    prior = recover_previous_state_record(
        state_root, expected_uid=expected_uid, expected_gid=expected_gid
    )
    if prior is None:
        raise TrustError("Rollback lacks protected retained apply-state authority")
    if (
        prior.candidate_revision != rollback.to_revision
        or prior.manifest_sha256 != rollback.to_manifest_sha256
        or rollback_transaction.candidate_revision != prior.candidate_revision
        or rollback_transaction.candidate_capsule_sha256 != prior.capsule_sha256
        or rollback_transaction.candidate_manifest_sha256 != prior.manifest_sha256
        or rollback_transaction.transaction_id == failed_transaction.transaction_id
    ):
        raise TrustError("Rollback transaction is not bound to retained apply state")
    applied = _commit_local_transaction(
        state_root,
        rollback_transaction,
        result,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        keep_history=keep_history,
        failure_hook=failure_hook,
    )
    marker = commit_rollback_apply_state(
        failed_transaction,
        convergence_succeeded=True,
        validations_succeeded=True,
    )
    finalize_failed_health_after_rollback(
        lkg_root,
        marker,
        applied,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        failure_hook=failure_hook,
    )
    return RollbackResult(marker, applied)


def publish_committed_runner(
    state_root: Path,
    stage_root: Path,
    unit_root: Path,
    lkg_root: Path,
    transaction: TransactionPlan,
    runner: RunnerUpdatePlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
    lock_device: int,
    lock_inode: int,
    reload_manager: Callable[[], None],
    rearm_timer: Callable[[], None],
    failure_hook: Callable[[str], None] | None = None,
) -> RunnerPublicationEvidence:
    """Publish only a staged pair bound to both exact transaction commits."""
    with protected_coordinator_lock(lkg_root, expected_uid=expected_uid, expected_gid=expected_gid):
        return _publish_committed_runner_locked(
            state_root,
            stage_root,
            unit_root,
            lkg_root,
            transaction,
            runner,
            ledger,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            lock_device=lock_device,
            lock_inode=lock_inode,
            reload_manager=reload_manager,
            rearm_timer=rearm_timer,
            failure_hook=failure_hook,
        )


def _publish_committed_runner_locked(
    state_root: Path,
    stage_root: Path,
    unit_root: Path,
    lkg_root: Path,
    transaction: TransactionPlan,
    runner: RunnerUpdatePlan,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
    lock_device: int,
    lock_inode: int,
    reload_manager: Callable[[], None],
    rearm_timer: Callable[[], None],
    failure_hook: Callable[[str], None] | None,
) -> RunnerPublicationEvidence:
    """Publish while the caller holds the protected coordinator lock."""
    verify_committed_apply_state(state_root, transaction, expected_uid, expected_gid)
    authority = _issue_runner_lkg_authority(
        lkg_root,
        transaction,
        ledger,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    evidence = bind_runner_publication_evidence(
        transaction,
        runner,
        durable_runner_lkg_receipt_sha256=authority.receipt_sha256,
    )
    _publish_runner_candidates(
        stage_root,
        unit_root,
        transaction,
        runner,
        evidence,
        authority,
        lock_device=lock_device,
        lock_inode=lock_inode,
        dry_run=False,
        reload_manager=reload_manager,
        rearm_timer=rearm_timer,
        failure_hook=failure_hook,
    )
    return evidence


def recover_committed_runner(
    state_root: Path,
    stage_root: Path,
    unit_root: Path,
    lkg_root: Path,
    transaction: TransactionPlan,
    runner: RunnerUpdatePlan,
    evidence: RunnerPublicationEvidence,
    ledger: RunnerLkgLedger,
    *,
    expected_uid: int,
    expected_gid: int,
    lock_device: int,
    lock_inode: int,
    reload_manager: Callable[[], None],
    rearm_timer: Callable[[], None],
    rearm_idempotent: bool,
) -> str:
    """Recover runner publication only under reverified durable transaction authority."""
    with protected_coordinator_lock(lkg_root, expected_uid=expected_uid, expected_gid=expected_gid):
        verify_committed_apply_state(state_root, transaction, expected_uid, expected_gid)
        authority = _issue_runner_lkg_authority(
            lkg_root,
            transaction,
            ledger,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        return _recover_runner_publication(
            stage_root,
            unit_root,
            transaction,
            runner,
            evidence,
            authority,
            lock_device=lock_device,
            lock_inode=lock_inode,
            reload_manager=reload_manager,
            rearm_timer=rearm_timer,
            rearm_idempotent=rearm_idempotent,
        )
