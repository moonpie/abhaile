"""Test runner-update ordering as a pure simulation with no unit publication."""

from typing import Any

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.runner_update import (
    RunnerPublicationEvidence,
    RunnerUpdateStage,
    advance_runner_update,
    authorize_runner_publication,
    bind_runner_publication_evidence,
    plan_runner_update,
)
from abhaile.trust.transaction import (
    TransactionPlan,
    commit_apply_state,
    commit_runner_lkg,
    record_local_convergence,
    record_wider_health,
)

IDENTITY = {
    "transaction_id": "tx-1",
    "candidate_revision": "a" * 40,
    "candidate_capsule_sha256": "b" * 64,
    "candidate_manifest_sha256": "c" * 64,
    "service_sha256": "d" * 64,
    "timer_sha256": "e" * 64,
    "recovery_record_sha256": "f" * 64,
}


def runner_plan(**overrides):
    values: dict[str, Any] = dict(
        lock_device=2, lock_inode=3, service_changed=True, timer_changed=True, **IDENTITY
    )
    values.update(overrides)
    return plan_runner_update(**values)


def committed_transaction(**overrides):
    values: dict[str, Any] = dict(
        transaction_id="tx-1",
        candidate_revision="a" * 40,
        candidate_capsule_sha256="b" * 64,
        candidate_manifest_sha256="c" * 64,
        retained_lkg_revision="1" * 40,
        retained_lkg_manifest_sha256="2" * 64,
    )
    values.update(overrides)
    transaction = TransactionPlan(**values)
    transaction = record_local_convergence(transaction, validations_succeeded=True)
    transaction = commit_apply_state(transaction)
    transaction = record_wider_health(transaction, succeeded=True)
    return commit_runner_lkg(transaction)


def step(plan, **overrides):
    options = dict(completed_action=plan.next_action, lock_device=2, lock_inode=3, lock_held=True)
    options.update(overrides)
    return advance_runner_update(plan, **options)


@pytest.mark.parametrize("timer_changed", [True, False])
def test_staging_and_commit_precede_publication_reload_and_timer_effects(timer_changed):
    plan = runner_plan(timer_changed=timer_changed)
    actions = []
    recoveries = []
    while plan.stage is not RunnerUpdateStage.READY:
        actions.append(plan.next_action)
        recoveries.append(plan.recovery)
        if plan.stage is RunnerUpdateStage.STAGED:
            evidence = bind_runner_publication_evidence(committed_transaction(), plan)
            plan = authorize_runner_publication(committed_transaction(), plan, evidence)
        else:
            plan = step(plan)
    assert actions[:5] == [
        "validate-both-units",
        "stage-both-units-and-recovery-record",
        "await-transaction-commit-evidence",
        "publish-staged-unit-pair",
        "reload-system-manager",
    ]
    assert actions[5] == ("rearm-timer-after-commit" if timer_changed else "retain-timer")
    assert not any("restart" in action or "stop" in action for action in actions)
    assert "preserve-current-units" in recoveries[2]
    assert "recover-pair" in recoveries[3]
    assert "retry-post-commit" in recoveries[4]
    assert "next-invocation" in plan.recovery
    assert plan.next_action == "release-existing-lock-on-exit"
    with pytest.raises(TrustError):
        step(plan)


@pytest.mark.parametrize(
    "overrides",
    [
        {"completed_action": "publish-staged-unit-pair"},
        {"lock_held": False},
        {"lock_inode": 4},
        {"lock_device": 1},
    ],
)
def test_failure_or_replaced_lock_never_advances_plan(overrides):
    plan = runner_plan()
    with pytest.raises(TrustError):
        step(plan, **overrides)
    assert plan.stage is RunnerUpdateStage.PLANNED


@pytest.mark.parametrize(
    "changes", [{"lock_inode": 0}, {"lock_device": -1}, {"service_changed": 1}]
)
def test_invalid_planning_inputs_fail_closed(changes):
    values: dict[str, Any] = dict(
        lock_device=2, lock_inode=3, service_changed=True, timer_changed=False, **IDENTITY
    )
    values.update(changes)
    with pytest.raises(TrustError):
        plan_runner_update(**values)


def test_unchanged_units_need_no_reload_or_publication():
    plan = runner_plan(service_changed=False, timer_changed=False)
    assert plan.stage is RunnerUpdateStage.READY
    assert plan.next_action == "release-existing-lock-on-exit"


@pytest.mark.parametrize(
    "transaction_change,evidence_change",
    [
        ({"transaction_id": "tx-2"}, {}),
        ({"candidate_revision": "9" * 40}, {}),
        ({"candidate_manifest_sha256": "9" * 64}, {}),
        ({}, {"service_sha256": "9" * 64}),
        ({}, {"recovery_record_sha256": "9" * 64}),
    ],
)
def test_unrelated_or_tampered_evidence_cannot_authorize_publication(
    transaction_change, evidence_change
):
    plan = step(step(runner_plan()))
    transaction = committed_transaction(**transaction_change)
    if transaction_change:
        with pytest.raises(TrustError):
            bind_runner_publication_evidence(transaction, plan)
        return
    evidence = bind_runner_publication_evidence(transaction, plan)
    tampered = RunnerPublicationEvidence(**{**evidence.__dict__, **evidence_change})
    with pytest.raises(TrustError):
        authorize_runner_publication(transaction, plan, tampered)
    committed = authorize_runner_publication(transaction, plan, evidence)
    with pytest.raises(TrustError):
        authorize_runner_publication(transaction, committed, evidence)
