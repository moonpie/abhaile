"""Test deterministic native account and package enrollment intent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.software import render_software_artifacts
from abhaile.renderers.users import render_users_artifacts
from abhaile.utils.errors import RenderError


def _write_host(root: Path, users: dict[str, Any], groups: dict[str, Any]) -> None:
    """Write a temporary host with explicit user intent."""
    path = root / "config/hosts/test/host.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "name": "test",
                "composition": {"user_management": {"users": users, "groups": groups}},
            }
        )
    )


def _rootless(start: int = 100000) -> dict[str, Any]:
    """Declare one rootless user's namespace without allocating in render."""
    return {"subuid_start": start, "subgid_start": start, "count": 65536, "linger": True}


def test_accounts_preserve_optional_ids_and_explicit_rootless_intent(tmp_path: Path) -> None:
    """Keep native ID allocation in apply and carry complete authored account metadata."""
    users = {
        "app": {
            "system": False,
            "home": "/home/app",
            "primary_group": "app",
            "rootless": _rootless(),
        }
    }
    _write_host(tmp_path, users, {"app": {}})
    collector = ArtifactCollector()
    destination = tmp_path / "rendered/system"
    render_users_artifacts(
        "test",
        tmp_path / "config",
        destination,
        collector=collector,
        rendered_root=tmp_path / "rendered",
    )
    artifact = next(a for a in collector.get_all_artifacts() if a.kind == "host.sysusers")
    assert artifact.apply_hints is not None
    assert artifact.apply_hints["users"] == users
    assert artifact.apply_hints["groups"] == {"app": {}}
    assert "g app -\n" in artifact.content
    assert "u app - - /home/app -\n" in artifact.content


@pytest.mark.parametrize("field", ["subuid_start", "subgid_start"])
def test_overlapping_declared_namespaces_fail(tmp_path: Path, field: str) -> None:
    """Reject overlapping ranges before any host account lookup or mutation."""
    first, second = _rootless(), _rootless(300000)
    second[field] = first[field] + 1
    users = {
        "first": {"home": "/home/first", "rootless": first},
        "second": {"home": "/home/second", "rootless": second},
    }
    _write_host(tmp_path, users, {"first": {}, "second": {}})
    with pytest.raises(RenderError, match=f"{field} ranges overlap"):
        render_users_artifacts("test", tmp_path / "config", tmp_path / "output")


@pytest.mark.parametrize("field,value", [("subuid_start", 2**32), ("count", 1), ("count", True)])
def test_invalid_rootless_ranges_fail(tmp_path: Path, field: str, value: Any) -> None:
    """Reject overflowing, undersized and boolean namespace declarations."""
    namespace = _rootless()
    namespace[field] = value
    _write_host(tmp_path, {"app": {"home": "/home/app", "rootless": namespace}}, {"app": {}})
    with pytest.raises(RenderError, match="Invalid rootless"):
        render_users_artifacts("test", tmp_path / "config", tmp_path / "output")


def test_rootless_home_matches_quadlet_output_contract(tmp_path: Path) -> None:
    """Do not prepare a different home from the renderer's named-user unit paths."""
    _write_host(tmp_path, {"app": {"home": "/srv/app", "rootless": _rootless()}}, {"app": {}})
    with pytest.raises(RenderError, match="must declare home /home/app"):
        render_users_artifacts("test", tmp_path / "config", tmp_path / "output")


@pytest.mark.parametrize("field", ["uid", "gid"])
def test_colliding_planned_ids_fail_before_rendering(tmp_path: Path, field: str) -> None:
    """Catch collisions between two new declarations absent from the live account database."""
    users: dict[str, Any] = {"first": {}, "second": {}}
    groups: dict[str, Any] = {"first": {}, "second": {}}
    identities = users if field == "uid" else groups
    for definition in identities.values():
        definition[field] = 12345
    _write_host(tmp_path, users, groups)
    with pytest.raises(RenderError, match=f"Duplicate {field}"):
        render_users_artifacts("test", tmp_path / "config", tmp_path / "output")


@pytest.mark.parametrize("field", ["uid", "gid"])
def test_rootless_ranges_do_not_include_declared_host_ids(tmp_path: Path, field: str) -> None:
    """Prevent a namespace mapping from granting access as another declared host identity."""
    users: dict[str, Any] = {"app": {"home": "/home/app", "rootless": _rootless()}}
    groups: dict[str, Any] = {"app": {}}
    (users if field == "uid" else groups)["other"] = {field: 100001}
    if field == "uid":
        groups["other"] = {}
    _write_host(tmp_path, users, groups)
    with pytest.raises(RenderError, match=f"overlaps {field}"):
        render_users_artifacts("test", tmp_path / "config", tmp_path / "output")


def test_packages_join_manifest_without_command_execution(tmp_path: Path) -> None:
    """Register the package inventory while leaving command-oriented actions inert."""
    host = tmp_path / "config/hosts/test/host.yaml"
    host.parent.mkdir(parents=True)
    host.write_text(
        json.dumps({"name": "test", "composition": {"software": {"packages": ["curl", "podman"]}}})
    )
    schema = tmp_path / "schemas/software-action.schema.json"
    schema.parent.mkdir()
    schema.write_text(json.dumps({"$schema": "http://json-schema.org/draft-07/schema#"}))
    collector = ArtifactCollector()
    rendered = tmp_path / "rendered"
    render_software_artifacts(
        "test",
        tmp_path / "config",
        rendered / "software",
        collector=collector,
        rendered_root=rendered,
    )
    artifact = collector.get_all_artifacts()[0]
    assert artifact.kind == "host.packages"
    assert artifact.target_path == "/etc/abhaile/packages.txt"
    assert artifact.content == "curl\npodman\n"
    assert artifact.owner_ref == "host-packages:test"
    assert len(collector.get_all_artifacts()) == 1
