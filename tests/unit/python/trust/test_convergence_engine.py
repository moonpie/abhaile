"""Tests for bounded manifest-to-Ansible operation compilation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from abhaile.trust.convergence import build_convergence_plan
from abhaile.trust.convergence_engine import AnsibleOperation, compile_ansible_operations
from abhaile.trust.errors import TrustError


def _entry(kind: str, render_path: str, target: str | None) -> dict[str, object]:
    action = {
        "service.directory": "create",
        "software.packages": "install",
        "software.download": "fetch",
        "software.build": "build",
        "software.prerequisite": "ensure",
    }.get(kind, "publish")
    return {
        "owner_ref": "service:test",
        "render_path": render_path,
        "sha256": "a" * 64,
        "target_path": target,
        "kind": kind,
        "action": action,
        "execution_context": "system",
        "metadata": (
            {"owner": "root", "group": "root", "mode": "0644"}
            if not kind.startswith("software.")
            else {}
        ),
        "validation": "software-result" if kind.startswith("software.") else "structural",
        "lifecycle": [],
        "lifecycle_metadata": {},
    }


def _compile(
    root: Path,
    entries: list[dict[str, object]],
    identities: dict[str, dict[str, object]] | None = None,
) -> tuple[AnsibleOperation, ...]:
    manifest = {
        "schema_version": 2,
        "host": "phobos",
        "execution_identities": identities or {},
        "owners": {"service:test": {"requires": []}},
        "entries": entries,
    }
    return compile_ansible_operations(build_convergence_plan(manifest), manifest, root)


def test_compiles_ordered_system_files_and_directories(tmp_path: Path) -> None:
    """Preserve dependency order and exact file metadata."""
    directory = _entry("service.directory", "services/test/data", "/srv/test")
    directory["metadata"] = {"owner": "svc", "group": "svc", "mode": "0750"}
    regular = _entry("service.config", "services/test/config", "/etc/test.conf")
    (tmp_path / "services/test/data").mkdir(parents=True)
    (tmp_path / "services/test/config").write_text("value\n", encoding="utf-8")

    identity = {
        "name": "svc",
        "uid": 1001,
        "gid": 1001,
        "home": "/home/svc",
        "shell": "/bin/bash",
    }
    operations = _compile(tmp_path, [regular, directory], {"user:svc": identity})

    assert [operation.operation for operation in operations] == ["directory", "publish"]
    assert operations[0].owner == "1001"
    assert operations[1].target == "/etc/test.conf"
    assert operations[1].no_log and not operations[1].diff


def test_binds_named_user_to_sealed_identity_authority(tmp_path: Path) -> None:
    """Bind named-user operations without inferring UID, GID, HOME, or runtime paths."""
    directory = _entry("service.directory", "services/test/data", "/srv/test")
    directory["execution_context"] = "user:svc"
    (tmp_path / "services/test/data").mkdir(parents=True)
    identity = {
        "name": "svc",
        "uid": 1001,
        "gid": 1001,
        "home": "/home/svc",
        "shell": "/bin/bash",
    }
    operation = _compile(tmp_path, [directory], {"user:svc": identity})[0]
    assert dict(operation.execution_identity or ()) == identity
    assert set(operation.ansible_value()) == {
        "action",
        "context",
        "diff",
        "effects",
        "execution_identity",
        "group",
        "kind",
        "lifecycle",
        "lifecycle_metadata",
        "mode",
        "no_log",
        "operation",
        "owner",
        "owner_ref",
        "parameters",
        "source",
        "source_sha256",
        "target",
        "validation",
    }

    with pytest.raises(TrustError, match="identity"):
        _compile(tmp_path, [directory])


@pytest.mark.parametrize(
    "replacement",
    [
        {"name": "svc", "uid": 1001, "gid": 1001, "home": "/wrong", "shell": "/bin/bash"},
        {"name": "other", "uid": 1001, "gid": 1001, "home": "/home/other", "shell": "/bin/bash"},
        {"name": "svc", "uid": True, "gid": 1001, "home": "/home/svc", "shell": "/bin/bash"},
        {
            "name": "svc",
            "uid": 1001,
            "gid": 1001,
            "home": "/home/svc",
            "shell": "/bin/bash",
            "runtime_identity_required": True,
        },
    ],
)
def test_rejects_incomplete_or_contradictory_named_user_identity(
    tmp_path: Path, replacement: dict[str, object]
) -> None:
    """Reject identity authority not matching the closed manifest contract."""
    directory = _entry("service.directory", "services/test/data", "/srv/test")
    directory["execution_context"] = "user:svc"
    (tmp_path / "services/test/data").mkdir(parents=True)

    with pytest.raises(TrustError, match="identity"):
        _compile(tmp_path, [directory], {"user:svc": replacement})


def test_compiles_admitted_packages_and_bounded_download(tmp_path: Path) -> None:
    """Compile admitted software only from payload-bound parameters and effects."""
    packages = _entry("software.packages", "software/packages.txt", None)
    packages["metadata"] = {
        "operation_id": "packages",
        "operation_type": "packages",
        "execution_policy": "admitted",
        "effects": [
            {"kind": "package", "target": "curl", "role": "requirement"},
            {"kind": "package", "target": "python3", "role": "requirement"},
        ],
    }
    download = _entry("software.download", "software/downloads/tool.yaml", None)
    payload = {
        "id": "tool",
        "name": "tool",
        "description": "immutable tool",
        "operation": "binary-download",
        "parameters": {
            "url": "https://example.invalid/tool",
            "sha256": "a" * 64,
            "destination": "/usr/local/bin/tool",
            "mode": "0755",
            "max_bytes": 1048576,
            "redirect_origins": [],
            "max_redirects": 0,
        },
        "effects": [{"kind": "path", "target": "/usr/local/bin/tool", "role": "primary"}],
        "validation": "binary-version",
        "expected_results": ["tool installed"],
        "execution_policy": "admitted",
    }
    download["metadata"] = {
        "operation_id": "tool",
        "operation_type": "binary-download",
        "execution_policy": "admitted",
        "effects": payload["effects"],
    }
    (tmp_path / "software/downloads").mkdir(parents=True)
    (tmp_path / "software/packages.txt").write_text("curl\npython3\n", encoding="utf-8")
    (tmp_path / "software/downloads/tool.yaml").write_text(
        yaml.safe_dump(payload), encoding="utf-8"
    )

    operations = _compile(tmp_path, [download, packages])
    assert [operation.operation for operation in operations] == ["packages", "binary-download"]
    assert dict(operations[0].parameters)["packages"] == ["curl", "python3"]
    assert dict(operations[1].parameters)["max_bytes"] == 1048576


def test_aggregates_lifecycle_once_after_owner_boundary(tmp_path: Path) -> None:
    """Coalesce lifecycle effects after all publications for an owner."""
    first = _entry("systemd.unit", "system/a.service", "/etc/systemd/system/a.service")
    second = _entry("systemd.dropin", "system/a.conf", "/etc/systemd/system/a.service.d/a.conf")
    first["validation"] = second["validation"] = "systemd"
    first["lifecycle"] = second["lifecycle"] = ["manager-reload"]
    for entry in (first, second):
        source = tmp_path / str(entry["render_path"])
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("[Unit]\n", encoding="utf-8")

    operations = _compile(tmp_path, [second, first])

    assert [operation.operation for operation in operations] == ["publish", "publish", "lifecycle"]
    assert operations[-1].owner_ref == "service:test"
    assert operations[-1].lifecycle == ("manager-reload",)


def test_aggregates_lifecycle_separately_per_owner_context(tmp_path: Path) -> None:
    """Never collapse system and named-user effects into one execution context."""
    system = _entry("systemd.unit", "system/a.service", "/etc/systemd/system/a.service")
    user = _entry("systemd.unit", "system/b.service", "/home/svc/.config/systemd/user/b.service")
    for entry in (system, user):
        entry["validation"] = "systemd"
        entry["lifecycle"] = ["manager-reload"]
        source = tmp_path / str(entry["render_path"])
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("[Unit]\n", encoding="utf-8")
    user["execution_context"] = "user:svc"
    identity = {"name": "svc", "uid": 1001, "gid": 1001, "home": "/home/svc", "shell": "/bin/bash"}

    operations = _compile(tmp_path, [system, user], {"user:svc": identity})

    lifecycle = [operation for operation in operations if operation.operation == "lifecycle"]
    assert [operation.context for operation in lifecycle] == ["system", "user:svc"]
    assert lifecycle[0].execution_identity is None
    assert dict(lifecycle[1].execution_identity or ()) == identity


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("software.build", "Container build"),
        ("networkd.network", "Network convergence"),
    ],
)
def test_rejects_integrity_blocked_and_network_families(
    tmp_path: Path, kind: str, expected: str
) -> None:
    """Reject blocked families during complete pre-mutation compilation."""
    relative = f"software/{kind}.yaml" if kind.startswith("software.") else "system/test.network"
    target = None if kind.startswith("software.") else "/etc/systemd/network/test.network"
    entry = _entry(kind, relative, target)
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("fixture\n", encoding="utf-8")
    with pytest.raises(TrustError, match=expected):
        _compile(tmp_path, [entry])


def test_rejects_plan_manifest_disagreement_before_operations(tmp_path: Path) -> None:
    """Do not compile caller-substituted manifest entries against a verified plan."""
    entry = _entry("service.config", "services/test/config", "/etc/test.conf")
    source = tmp_path / "services/test/config"
    source.parent.mkdir(parents=True)
    source.write_text("value\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "host": "phobos",
        "execution_identities": {},
        "owners": {"service:test": {"requires": []}},
        "entries": [entry],
    }
    plan = build_convergence_plan(manifest)
    entry["target_path"] = "/etc/substituted"
    with pytest.raises(TrustError, match="disagrees"):
        compile_ansible_operations(plan, manifest, tmp_path)
