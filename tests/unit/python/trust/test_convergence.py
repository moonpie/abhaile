"""Tests for deterministic manifest-only convergence planning."""

import pytest

from abhaile.trust.convergence import build_convergence_plan
from abhaile.trust.errors import TrustError


def test_orders_dependencies_phases_and_equal_peers_deterministically() -> None:
    """Order owner dependencies first and use stable phase/path tie breaks."""
    manifest = {
        "schema_version": 2,
        "host": "phobos",
        "owners": {
            "service:z": {"requires": ["software:packages"]},
            "software:packages": {"requires": []},
            "service:a": {"requires": ["software:packages"]},
        },
        "entries": [
            {
                "owner_ref": "service:z",
                "render_path": "z",
                "target_path": "/z",
                "kind": "service.config",
                "action": "publish",
                "execution_context": "system",
                "validation": "structural",
                "lifecycle": ["service-restart"],
            },
            {
                "owner_ref": "software:packages",
                "render_path": "p",
                "target_path": "/p",
                "kind": "software.packages",
                "action": "install",
                "execution_context": "system",
                "validation": "software-result",
                "lifecycle": [],
            },
            {
                "owner_ref": "service:a",
                "render_path": "a",
                "target_path": "/a",
                "kind": "service.directory",
                "action": "create",
                "execution_context": "system",
                "validation": "structural",
                "lifecycle": [],
            },
        ],
    }
    plan = build_convergence_plan(manifest)
    assert plan.owner_order == ("software:packages", "service:a", "service:z")
    assert [step.render_path for step in plan.steps] == ["p", "a", "z"]
    assert plan.steps[-1].lifecycle == ("service-restart",)


def test_rejects_unknown_version_and_owner_cycle() -> None:
    """Fail closed when compatibility or ordering cannot be proven."""
    with pytest.raises(TrustError, match="schema v2"):
        build_convergence_plan({"schema_version": 3})
    with pytest.raises(TrustError, match="cycle"):
        build_convergence_plan(
            {
                "schema_version": 2,
                "host": "phobos",
                "entries": [],
                "owners": {"a": {"requires": ["b"]}, "b": {"requires": ["a"]}},
            }
        )


def test_dependency_edge_overrides_phase_preference_and_keeps_owner_contiguous() -> None:
    """Never move a lower-phase dependent ahead of its higher-phase prerequisite."""
    manifest = {
        "schema_version": 2,
        "host": "deimos",
        "owners": {
            "iface:parent": {"requires": []},
            "iface:child": {"requires": ["iface:parent"]},
        },
        "entries": [
            {
                "owner_ref": "iface:child",
                "render_path": "child-dir",
                "target_path": "/etc/child",
                "kind": "service.directory",
                "action": "create",
                "execution_context": "system",
                "validation": "structural",
                "lifecycle": [],
            },
            {
                "owner_ref": "iface:parent",
                "render_path": "parent-file",
                "target_path": "/etc/parent",
                "kind": "service.config",
                "action": "publish",
                "execution_context": "system",
                "validation": "structural",
                "lifecycle": [],
            },
            {
                "owner_ref": "iface:parent",
                "render_path": "parent-dir",
                "target_path": "/etc/parent.d",
                "kind": "service.directory",
                "action": "create",
                "execution_context": "system",
                "validation": "structural",
                "lifecycle": [],
            },
        ],
    }
    plan = build_convergence_plan(manifest)
    assert plan.owner_order == ("iface:parent", "iface:child")
    assert [step.render_path for step in plan.steps] == ["parent-dir", "parent-file", "child-dir"]
