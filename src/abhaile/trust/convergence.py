"""Build deterministic non-mutating convergence plans from manifest v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from abhaile.trust.errors import TrustError


@dataclass(frozen=True)
class ConvergenceStep:
    """Describe one future convergence operation without executing it."""

    owner_ref: str
    render_path: str
    target_path: str | None
    kind: str
    action: str
    execution_context: str
    validation: str
    lifecycle: tuple[str, ...]
    phase: int


@dataclass(frozen=True)
class ConvergencePlan:
    """Hold dependency-ordered entries and deferred effects."""

    host: str
    schema_version: int
    owner_order: tuple[str, ...]
    steps: tuple[ConvergenceStep, ...]


def build_convergence_plan(manifest: dict[str, Any]) -> ConvergencePlan:
    """Build a deterministic pure plan from an already validated manifest."""
    if manifest.get("schema_version") != 2:
        raise TrustError("Convergence planning requires manifest schema v2")
    host, owners, entries = manifest.get("host"), manifest.get("owners"), manifest.get("entries")
    if not isinstance(host, str) or not isinstance(owners, dict) or not isinstance(entries, list):
        raise TrustError("Convergence planning input is incomplete")
    unordered_steps = [
        ConvergenceStep(
            entry["owner_ref"],
            entry["render_path"],
            entry["target_path"],
            entry["kind"],
            entry["action"],
            entry["execution_context"],
            entry["validation"],
            tuple(entry["lifecycle"]),
            _phase(entry["kind"], entry["action"]),
        )
        for entry in entries
    ]
    owner_phases: dict[str, int] = {}
    for step in unordered_steps:
        owner_phases[step.owner_ref] = min(owner_phases.get(step.owner_ref, step.phase), step.phase)
    owner_order = _owner_order(owners, owner_phases)
    steps: list[ConvergenceStep] = []
    for owner in owner_order:
        owned = [step for step in unordered_steps if step.owner_ref == owner]
        owned.sort(key=lambda step: (step.phase, step.target_path or "", step.render_path))
        steps.extend(owned)
    return ConvergencePlan(host, 2, owner_order, tuple(steps))


def _owner_order(owners: dict[str, Any], owner_phases: dict[str, int]) -> tuple[str, ...]:
    remaining = {
        name: set(payload["requires"])
        for name, payload in owners.items()
        if isinstance(name, str) and isinstance(payload, dict)
    }
    if len(remaining) != len(owners):
        raise TrustError("Convergence owner graph is invalid")
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            (name for name, dependencies in remaining.items() if not dependencies),
            key=lambda name: (owner_phases.get(name, 50), name),
        )
        if not ready:
            raise TrustError("Convergence owner graph contains a cycle")
        for name in ready:
            ordered.append(name)
            remaining.pop(name)
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return tuple(ordered)


def _phase(kind: str, action: str) -> int:
    if kind == "software.packages":
        return 10
    if kind in {"host.sysusers", "service.directory"}:
        return 20
    if kind in {"software.download", "software.build", "software.prerequisite"}:
        return 30
    if action == "publish":
        return 40
    return 50
