"""Define bootstrap-owned prerequisites and convergence ordering contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from abhaile.trust.errors import TrustError


class FoundationOwner(str, Enum):
    """Identify the lifecycle authority for a host foundation."""

    BOOTSTRAP = "bootstrap"
    CONVERGENCE = "convergence"
    TRANSACTION = "transaction"
    ADOPTION = "adoption"


@dataclass(frozen=True)
class FoundationStep:
    """Describe one ordered prerequisite without authorizing host mutation."""

    name: str
    owner: FoundationOwner
    requires: tuple[str, ...]
    preserve_existing: bool = False
    live_proof_phase: int | None = None


FOUNDATION_STEPS = (
    FoundationStep("repository-prerequisites", FoundationOwner.BOOTSTRAP, ()),
    FoundationStep("deploy-key", FoundationOwner.BOOTSTRAP, ("repository-prerequisites",), True, 6),
    FoundationStep(
        "pinned-known-hosts", FoundationOwner.BOOTSTRAP, ("repository-prerequisites",), True, 6
    ),
    FoundationStep(
        "protected-launcher", FoundationOwner.BOOTSTRAP, ("pinned-known-hosts",), True, 6
    ),
    FoundationStep(
        "protected-python-runtime",
        FoundationOwner.BOOTSTRAP,
        ("protected-launcher",),
        True,
        6,
    ),
    FoundationStep(
        "protected-ansible-runtime",
        FoundationOwner.BOOTSTRAP,
        ("protected-python-runtime",),
        True,
        6,
    ),
    FoundationStep(
        "renderer-identity", FoundationOwner.BOOTSTRAP, ("protected-python-runtime",), True, 6
    ),
    FoundationStep(
        "cgroup-and-temporary-namespaces",
        FoundationOwner.BOOTSTRAP,
        ("renderer-identity",),
        True,
        6,
    ),
    FoundationStep(
        "runner-environment", FoundationOwner.BOOTSTRAP, ("protected-launcher",), True, 6
    ),
    FoundationStep(
        "apply-and-runner-state-directories",
        FoundationOwner.BOOTSTRAP,
        ("runner-environment",),
        True,
        6,
    ),
    FoundationStep(
        "rootless-identity-and-linger",
        FoundationOwner.ADOPTION,
        ("repository-prerequisites",),
        True,
        6,
    ),
    FoundationStep(
        "rootless-runtime-and-bus",
        FoundationOwner.ADOPTION,
        ("rootless-identity-and-linger",),
        True,
        6,
    ),
    FoundationStep(
        "rootless-vault-agent-prerequisites",
        FoundationOwner.ADOPTION,
        ("rootless-runtime-and-bus",),
        True,
        6,
    ),
    FoundationStep(
        "sudo-candidate-validation",
        FoundationOwner.ADOPTION,
        ("protected-launcher", "protected-ansible-runtime"),
        True,
        6,
    ),
    FoundationStep(
        "runner-service-and-timer-candidates",
        FoundationOwner.TRANSACTION,
        ("apply-and-runner-state-directories",),
        True,
    ),
)


def foundation_order(steps: tuple[FoundationStep, ...] = FOUNDATION_STEPS) -> tuple[str, ...]:
    """Return a deterministic prerequisite order and reject incomplete graphs."""
    by_name = {step.name: step for step in steps}
    if len(by_name) != len(steps) or any(
        requirement not in by_name for step in steps for requirement in step.requires
    ):
        raise TrustError("Foundation prerequisite graph is incomplete")
    remaining = {name: set(step.requires) for name, step in by_name.items()}
    ordered: list[str] = []
    while remaining:
        ready = sorted(name for name, requirements in remaining.items() if not requirements)
        if not ready:
            raise TrustError("Foundation prerequisite graph contains a cycle")
        ordered.extend(ready)
        for name in ready:
            remaining.pop(name)
        for requirements in remaining.values():
            requirements.difference_update(ready)
    return tuple(ordered)


def convergence_may_manage(step: FoundationStep, *, fresh_enrollment: bool) -> bool:
    """Keep bootstrap credentials and trust foundations outside normal convergence."""
    if step.owner is FoundationOwner.CONVERGENCE:
        return True
    if fresh_enrollment and step.owner is FoundationOwner.BOOTSTRAP:
        return True
    return False
