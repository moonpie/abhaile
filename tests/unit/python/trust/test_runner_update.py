"""Test runner-update ordering as a pure simulation with no unit publication."""

from typing import Any

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.runner_update import (
    RunnerUpdateStage,
    advance_runner_update,
    plan_runner_update,
)


def step(plan, **overrides):
    options = dict(completed_action=plan.next_action, lock_device=2, lock_inode=3, lock_held=True)
    options.update(overrides)
    return advance_runner_update(plan, **options)


@pytest.mark.parametrize("timer_changed", [True, False])
def test_staging_and_commit_precede_publication_reload_and_timer_effects(timer_changed):
    plan = plan_runner_update(
        lock_device=2, lock_inode=3, service_changed=True, timer_changed=timer_changed
    )
    actions = []
    recoveries = []
    while plan.stage is not RunnerUpdateStage.READY:
        actions.append(plan.next_action)
        recoveries.append(plan.recovery)
        plan = step(plan)
    assert actions[:5] == [
        "validate-both-units",
        "stage-both-units-and-recovery-record",
        "await-apply-and-health-commit",
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
    plan = plan_runner_update(lock_device=2, lock_inode=3, service_changed=True, timer_changed=True)
    with pytest.raises(TrustError):
        step(plan, **overrides)
    assert plan.stage is RunnerUpdateStage.PLANNED


@pytest.mark.parametrize(
    "changes", [{"lock_inode": 0}, {"lock_device": -1}, {"service_changed": 1}]
)
def test_invalid_planning_inputs_fail_closed(changes):
    values: dict[str, Any] = dict(
        lock_device=2, lock_inode=3, service_changed=True, timer_changed=False
    )
    values.update(changes)
    with pytest.raises(TrustError):
        plan_runner_update(**values)


def test_unchanged_units_need_no_reload_or_publication():
    plan = plan_runner_update(
        lock_device=2, lock_inode=3, service_changed=False, timer_changed=False
    )
    assert plan.stage is RunnerUpdateStage.READY
    assert plan.next_action == "release-existing-lock-on-exit"
