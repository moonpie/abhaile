"""Tests for distinct apply-state and runner-LKG commit gates."""

from dataclasses import replace

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.transaction import (
    TransactionPlan,
    TransactionStage,
    commit_rollback_apply_state,
    commit_apply_state,
    commit_runner_lkg,
    plan_rollback,
    record_local_convergence,
    record_rollback_failure,
    record_wider_health,
    validate_transaction_commit_evidence,
)


def _plan(*, dry_run: bool = False) -> TransactionPlan:
    return TransactionPlan(
        "tx-1",
        "a" * 40,
        "3" * 64,
        "1" * 64,
        "b" * 40,
        "2" * 64,
        dry_run=dry_run,
    )


def test_separates_apply_runner_and_publication_gates() -> None:
    """Require local evidence, then wider health, before publishing runner changes."""
    converged = record_local_convergence(_plan(), validations_succeeded=True, changed=True)
    assert converged.apply_state_eligible and not converged.runner_lkg_eligible
    applied = commit_apply_state(converged)
    assert applied.stage is TransactionStage.APPLY_COMMITTED
    healthy = record_wider_health(applied, succeeded=True)
    assert healthy.runner_lkg_eligible and not healthy.runner_publication_eligible
    committed = commit_runner_lkg(healthy)
    assert committed.apply_commit_evidence is not None
    assert committed.runner_lkg_commit_evidence is not None
    assert not committed.runner_publication_eligible


def test_health_failure_plans_from_actual_applied_manifest_and_preserves_lkg() -> None:
    """Use the candidate apply manifest as rollback source after apply commit."""
    applied = commit_apply_state(
        record_local_convergence(_plan(), validations_succeeded=True, changed=True)
    )
    failed = record_wider_health(applied, succeeded=False)
    rollback = plan_rollback(failed)
    assert rollback.from_manifest_sha256 == "1" * 64
    assert rollback.to_manifest_sha256 == "2" * 64
    assert record_rollback_failure(failed).stage is TransactionStage.ROLLBACK_FAILED
    recovered = commit_rollback_apply_state(
        failed, convergence_succeeded=True, validations_succeeded=True
    )
    assert recovered.stage is TransactionStage.ROLLBACK_COMMITTED
    assert not recovered.runner_lkg_eligible
    assert not recovered.runner_publication_eligible
    with pytest.raises(TrustError):
        commit_runner_lkg(failed)


def test_same_desired_state_health_failure_has_explicit_recovery_semantics() -> None:
    """Represent same-desired-state recovery without pretending the revision changed."""
    same = replace(
        _plan(),
        candidate_revision="b" * 40,
        candidate_manifest_sha256="2" * 64,
    )
    applied = commit_apply_state(
        record_local_convergence(same, validations_succeeded=True, changed=False)
    )
    recovery = plan_rollback(record_wider_health(applied, succeeded=False))
    assert recovery.from_revision == recovery.to_revision
    assert recovery.from_manifest_sha256 == recovery.to_manifest_sha256
    assert recovery.reason == "wider-health-failed-same-desired-state-recovery"


def test_commit_failure_injection_never_skips_a_gate() -> None:
    """Reject apply, runner, publication, and rollback commits out of order."""
    plan = _plan()
    with pytest.raises(TrustError):
        commit_apply_state(plan)
    with pytest.raises(TrustError):
        commit_runner_lkg(plan)
    with pytest.raises(TrustError):
        commit_rollback_apply_state(plan, convergence_succeeded=True, validations_succeeded=True)
    assert plan.stage is TransactionStage.PLANNED


def test_dry_run_and_failed_local_validation_advance_nothing() -> None:
    """Keep both ledgers and publication unchanged for previews and failures."""
    for plan, succeeded in ((_plan(dry_run=True), True), (_plan(), False)):
        with pytest.raises(TrustError):
            record_local_convergence(plan, validations_succeeded=succeeded, changed=False)
        assert plan.stage is TransactionStage.PLANNED
        assert not plan.apply_state_eligible
        assert not plan.runner_lkg_eligible
        assert not plan.runner_publication_eligible


def test_apply_commit_evidence_rejects_outcome_tampering() -> None:
    """Bind changed/no-op truth to the exact apply commit evidence."""
    applied = commit_apply_state(
        record_local_convergence(_plan(), validations_succeeded=True, changed=False)
    )
    with pytest.raises(TrustError, match="fabricated or mismatched"):
        validate_transaction_commit_evidence(replace(applied, local_changes=True))
