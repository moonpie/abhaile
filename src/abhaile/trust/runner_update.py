"""Plan deferred runner replacement without publishing or operating units."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from abhaile.trust.errors import TrustError


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
    stage: RunnerUpdateStage = RunnerUpdateStage.PLANNED

    @property
    def next_action(self) -> str:
        """Return the next planning action under the unchanged existing lock."""
        return {
            RunnerUpdateStage.PLANNED: "validate-both-units",
            RunnerUpdateStage.VALIDATED: "stage-both-units-and-recovery-record",
            RunnerUpdateStage.STAGED: "await-apply-and-health-commit",
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
    *, lock_device: int, lock_inode: int, service_changed: bool, timer_changed: bool
) -> RunnerUpdatePlan:
    """Bind a pure plan to the held lock inode rather than a replacement lock."""
    if (
        type(lock_device) is not int
        or type(lock_inode) is not int
        or lock_device < 0
        or lock_inode <= 0
        or type(service_changed) is not bool
        or type(timer_changed) is not bool
    ):
        raise TrustError("Runner update planning inputs are invalid")
    return RunnerUpdatePlan(
        lock_device,
        lock_inode,
        service_changed,
        timer_changed,
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
        or plan.stage is RunnerUpdateStage.READY
    ):
        raise TrustError("Runner update gate or existing lock is invalid")
    stages = list(RunnerUpdateStage)
    return replace(plan, stage=stages[stages.index(plan.stage) + 1])
