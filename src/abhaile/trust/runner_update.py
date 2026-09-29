"""Plan deferred runner replacement without publishing or operating units."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from abhaile.trust.errors import TrustError
from abhaile.trust.transaction import TransactionPlan, TransactionStage


class RunnerUpdateStage(str, Enum):
    """Describe ordered evidence gates for the future publication executor."""

    PLANNED = "planned"
    VALIDATED = "validated"
    STAGED = "staged"
    COMMITTED = "committed"
    PUBLISHED = "published"
    RELOADED = "reloaded"
    READY = "ready-for-next-invocation"


@dataclass(frozen=True)
class RunnerUpdatePlan:
    """Track a planning simulation; these values never authorize live execution."""

    lock_device: int
    lock_inode: int
    service_changed: bool
    timer_changed: bool
    transaction_id: str
    candidate_revision: str
    candidate_capsule_sha256: str
    candidate_manifest_sha256: str
    service_sha256: str
    timer_sha256: str
    recovery_record_sha256: str
    stage: RunnerUpdateStage = RunnerUpdateStage.PLANNED

    @property
    def next_action(self) -> str:
        """Return the next planning action under the unchanged existing lock."""
        return {
            RunnerUpdateStage.PLANNED: "validate-both-units",
            RunnerUpdateStage.VALIDATED: "stage-both-units-and-recovery-record",
            RunnerUpdateStage.STAGED: "await-transaction-commit-evidence",
            RunnerUpdateStage.COMMITTED: "publish-staged-unit-pair",
            RunnerUpdateStage.PUBLISHED: "reload-system-manager",
            RunnerUpdateStage.RELOADED: (
                "rearm-timer-after-commit" if self.timer_changed else "retain-timer"
            ),
            RunnerUpdateStage.READY: "release-existing-lock-on-exit",
        }[self.stage]

    @property
    def recovery(self) -> str:
        """Define recovery without pretending publication is atomic as a pair."""
        if self.stage in {
            RunnerUpdateStage.PLANNED,
            RunnerUpdateStage.VALIDATED,
            RunnerUpdateStage.STAGED,
        }:
            return "preserve-current-units; retain-or-discard-unpublished-stage-under-lock"
        if self.stage is RunnerUpdateStage.COMMITTED:
            return "recover-pair-from-protected-record-before-reload; keep-lock"
        if self.stage in {RunnerUpdateStage.PUBLISHED, RunnerUpdateStage.RELOADED}:
            return "retry-post-commit-effects-from-protected-record; keep-lock"
        return "next-invocation-uses-published-units; never-restart-active-runner"


def plan_runner_update(
    *,
    lock_device: int,
    lock_inode: int,
    service_changed: bool,
    timer_changed: bool,
    transaction_id: str,
    candidate_revision: str,
    candidate_capsule_sha256: str,
    candidate_manifest_sha256: str,
    service_sha256: str,
    timer_sha256: str,
    recovery_record_sha256: str,
) -> RunnerUpdatePlan:
    """Bind a pure plan to the held lock inode rather than a replacement lock."""
    if (
        type(lock_device) is not int
        or type(lock_inode) is not int
        or lock_device < 0
        or lock_inode <= 0
        or type(service_changed) is not bool
        or type(timer_changed) is not bool
        or not transaction_id
        or not _digest(candidate_revision, 40)
        or any(
            not _digest(value, 64)
            for value in (
                candidate_capsule_sha256,
                candidate_manifest_sha256,
                service_sha256,
                timer_sha256,
                recovery_record_sha256,
            )
        )
    ):
        raise TrustError("Runner update planning inputs are invalid")
    return RunnerUpdatePlan(
        lock_device,
        lock_inode,
        service_changed,
        timer_changed,
        transaction_id,
        candidate_revision,
        candidate_capsule_sha256,
        candidate_manifest_sha256,
        service_sha256,
        timer_sha256,
        recovery_record_sha256,
        RunnerUpdateStage.PLANNED if service_changed or timer_changed else RunnerUpdateStage.READY,
    )


def advance_runner_update(
    plan: RunnerUpdatePlan,
    *,
    completed_action: str,
    lock_device: int,
    lock_inode: int,
    lock_held: bool,
) -> RunnerUpdatePlan:
    """Simulate one gate; reject reordered effects or changed locks."""
    if (
        lock_held is not True
        or (lock_device, lock_inode) != (plan.lock_device, plan.lock_inode)
        or completed_action != plan.next_action
        or plan.stage in {RunnerUpdateStage.STAGED, RunnerUpdateStage.READY}
    ):
        raise TrustError("Runner update gate or existing lock is invalid")
    stages = list(RunnerUpdateStage)
    return replace(plan, stage=stages[stages.index(plan.stage) + 1])


@dataclass(frozen=True)
class RunnerPublicationEvidence:
    """Bind staged runner artifacts and both ledger commits to one transaction."""

    transaction_id: str
    candidate_revision: str
    candidate_capsule_sha256: str
    candidate_manifest_sha256: str
    service_sha256: str
    timer_sha256: str
    recovery_record_sha256: str
    apply_commit_evidence: str
    runner_lkg_commit_evidence: str


def bind_runner_publication_evidence(
    transaction: TransactionPlan, plan: RunnerUpdatePlan
) -> RunnerPublicationEvidence:
    """Create pure publication evidence only after exact transaction commits."""
    if (
        transaction.dry_run
        or transaction.stage is not TransactionStage.RUNNER_COMMITTED
        or plan.stage is not RunnerUpdateStage.STAGED
        or transaction.apply_commit_evidence is None
        or transaction.runner_lkg_commit_evidence is None
        or _transaction_identity(transaction) != _runner_identity(plan)
    ):
        raise TrustError("Runner publication evidence cannot be bound")
    return RunnerPublicationEvidence(
        *(_runner_identity(plan)),
        plan.service_sha256,
        plan.timer_sha256,
        plan.recovery_record_sha256,
        transaction.apply_commit_evidence,
        transaction.runner_lkg_commit_evidence,
    )


def authorize_runner_publication(
    transaction: TransactionPlan,
    plan: RunnerUpdatePlan,
    evidence: RunnerPublicationEvidence,
) -> RunnerUpdatePlan:
    """Authorize only the exact staged pair once both matching ledgers commit."""
    expected = bind_runner_publication_evidence(transaction, plan)
    if evidence != expected:
        raise TrustError("Runner publication evidence is stale, replayed, or mismatched")
    return replace(plan, stage=RunnerUpdateStage.COMMITTED)


def _transaction_identity(plan: TransactionPlan) -> tuple[str, str, str, str]:
    return (
        plan.transaction_id,
        plan.candidate_revision,
        plan.candidate_capsule_sha256,
        plan.candidate_manifest_sha256,
    )


def _runner_identity(plan: RunnerUpdatePlan) -> tuple[str, str, str, str]:
    return (
        plan.transaction_id,
        plan.candidate_revision,
        plan.candidate_capsule_sha256,
        plan.candidate_manifest_sha256,
    )


def _digest(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )
