"""Model apply, health, publication, and rollback commit gates without I/O."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from enum import Enum

from abhaile.trust.errors import TrustError


class TransactionStage(str, Enum):
    """Describe truthful transaction progress across separate ledgers."""

    PLANNED = "planned"
    CONVERGED = "converged"
    APPLY_COMMITTED = "apply-committed"
    HEALTHY = "healthy"
    RUNNER_COMMITTED = "runner-committed"
    ROLLBACK_PLANNED = "rollback-planned"
    ROLLBACK_COMMITTED = "rollback-committed"
    ROLLBACK_FAILED = "rollback-failed"


@dataclass(frozen=True)
class TransactionPlan:
    """Bind ledger gates to immutable desired and retained manifests."""

    transaction_id: str
    candidate_revision: str
    candidate_capsule_sha256: str
    candidate_manifest_sha256: str
    retained_lkg_revision: str
    retained_lkg_manifest_sha256: str
    dry_run: bool = False
    stage: TransactionStage = TransactionStage.PLANNED
    apply_commit_evidence: str | None = None
    runner_lkg_commit_evidence: str | None = None

    def __post_init__(self) -> None:
        """Reject transaction identities that cannot be bound unambiguously."""
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.transaction_id) is None
            or re.fullmatch(r"[0-9a-f]{40}", self.candidate_revision) is None
            or re.fullmatch(r"[0-9a-f]{40}", self.retained_lkg_revision) is None
            or any(
                re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (
                    self.candidate_capsule_sha256,
                    self.candidate_manifest_sha256,
                    self.retained_lkg_manifest_sha256,
                )
            )
            or type(self.dry_run) is not bool
        ):
            raise TrustError("Transaction identity is invalid")

    @property
    def apply_state_eligible(self) -> bool:
        """Return whether local convergence evidence permits apply-state commit."""
        return not self.dry_run and self.stage is TransactionStage.CONVERGED

    @property
    def runner_lkg_eligible(self) -> bool:
        """Return whether wider health permits runner-LKG commit."""
        return not self.dry_run and self.stage is TransactionStage.HEALTHY

    @property
    def runner_publication_eligible(self) -> bool:
        """Require separate artifact-bound evidence before publication."""
        return False


@dataclass(frozen=True)
class RollbackPlan:
    """Compare actual applied desired state with retained LKG desired state."""

    transaction_id: str
    from_revision: str
    from_manifest_sha256: str
    to_revision: str
    to_manifest_sha256: str
    reason: str


def record_local_convergence(
    plan: TransactionPlan, *, validations_succeeded: bool
) -> TransactionPlan:
    """Record local convergence only when every local validation succeeds."""
    if plan.dry_run or plan.stage is not TransactionStage.PLANNED or not validations_succeeded:
        raise TrustError("Local convergence evidence does not satisfy the apply gate")
    return replace(plan, stage=TransactionStage.CONVERGED)


def commit_apply_state(plan: TransactionPlan) -> TransactionPlan:
    """Advance only the apply ledger after local success."""
    if not plan.apply_state_eligible:
        raise TrustError("Apply-state commit gate is not satisfied")
    return replace(
        plan,
        stage=TransactionStage.APPLY_COMMITTED,
        apply_commit_evidence=_commit_digest(plan, "apply-state", plan.candidate_manifest_sha256),
    )


def record_wider_health(plan: TransactionPlan, *, succeeded: bool) -> TransactionPlan:
    """Record wider health or expose the required rollback boundary."""
    if plan.stage is not TransactionStage.APPLY_COMMITTED:
        raise TrustError("Wider health requires committed apply state")
    return replace(
        plan,
        stage=TransactionStage.HEALTHY if succeeded else TransactionStage.ROLLBACK_PLANNED,
    )


def commit_runner_lkg(plan: TransactionPlan) -> TransactionPlan:
    """Advance runner LKG only after wider health success."""
    if not plan.runner_lkg_eligible:
        raise TrustError("Runner-LKG commit gate is not satisfied")
    if plan.apply_commit_evidence is None:
        raise TrustError("Runner-LKG commit requires apply-state commit evidence")
    return replace(
        plan,
        stage=TransactionStage.RUNNER_COMMITTED,
        runner_lkg_commit_evidence=_commit_digest(
            plan, "runner-lkg", plan.candidate_manifest_sha256
        ),
    )


def plan_rollback(plan: TransactionPlan) -> RollbackPlan:
    """Plan rollback from the actual applied manifest to retained LKG."""
    if plan.stage is not TransactionStage.ROLLBACK_PLANNED:
        raise TrustError("Rollback requires post-apply wider-health failure")
    if plan.candidate_manifest_sha256 == plan.retained_lkg_manifest_sha256:
        raise TrustError("Rollback manifests must identify distinct desired states")
    return RollbackPlan(
        plan.transaction_id,
        plan.candidate_revision,
        plan.candidate_manifest_sha256,
        plan.retained_lkg_revision,
        plan.retained_lkg_manifest_sha256,
        "wider-health-failed-after-apply-commit",
    )


def record_rollback_failure(plan: TransactionPlan) -> TransactionPlan:
    """Represent rollback failure without changing either ledger claim."""
    if plan.stage is not TransactionStage.ROLLBACK_PLANNED:
        raise TrustError("Rollback failure has no matching rollback plan")
    return replace(plan, stage=TransactionStage.ROLLBACK_FAILED)


def commit_rollback_apply_state(
    plan: TransactionPlan, *, convergence_succeeded: bool, validations_succeeded: bool
) -> TransactionPlan:
    """Record a validated rollback apply without promoting runner LKG."""
    if (
        plan.stage is not TransactionStage.ROLLBACK_PLANNED
        or not convergence_succeeded
        or not validations_succeeded
    ):
        raise TrustError("Rollback apply-state commit gate is not satisfied")
    return replace(plan, stage=TransactionStage.ROLLBACK_COMMITTED)


def _commit_digest(plan: TransactionPlan, ledger: str, manifest_sha256: str) -> str:
    """Bind injected commit evidence to one immutable transaction identity."""
    identity = "\0".join(
        (
            ledger,
            plan.transaction_id,
            plan.candidate_revision,
            plan.candidate_capsule_sha256,
            manifest_sha256,
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
