"""Exercise native host prerequisite check mode without changing host accounts or packages."""

from __future__ import annotations

import hashlib
import grp
import os
import pwd
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment
from abhaile.utils.config import read_json
from abhaile.utils.errors import RenderError
from abhaile.validation.schema import validate_schema

pytestmark = pytest.mark.integration


def _run(
    tmp_path: Path,
    users: dict[str, Any],
    groups: dict[str, Any],
    packages: list[str] | None = None,
) -> tuple[int, str]:
    """Run the production role in check mode using only temporary desired source files."""
    rendered = tmp_path / "rendered"
    rendered.mkdir()
    source = rendered / "users.conf"
    source.write_text("# temporary desired account inventory\n")
    entry = {
        "kind": "host.sysusers",
        "render_path": "users.conf",
        "target_path": "/etc/sysusers.d/abhaile.conf",
        "owner_ref": "host-users:test",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "size": source.stat().st_size,
        "apply_hints": {
            "owner_user": "root",
            "owner_group": "root",
            "mode": "0644",
            "users": users,
            "groups": groups,
        },
    }
    entries = [entry]
    if packages is not None:
        package_source = rendered / "packages.txt"
        package_source.write_text("".join(package + "\n" for package in packages))
        entries.append(
            {
                "kind": "host.packages",
                "render_path": "packages.txt",
                "target_path": "/etc/abhaile/packages.txt",
                "owner_ref": "host-packages:test",
                "sha256": hashlib.sha256(package_source.read_bytes()).hexdigest(),
                "size": package_source.stat().st_size,
                "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "0644"},
            }
        )
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Check native host prerequisites",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered),
                        "abhaile_host_foundation_entries": entries,
                    },
                    "roles": ["host_foundations"],
                }
            ]
        )
    )
    environment = tmp_path / "environment"
    environment.mkdir()
    result = _ansible(
        "ansible.cli.playbook",
        ["-i", "localhost,", "--connection=local", "--check", str(playbook)],
        _closed_environment(environment),
    )
    return result.returncode, result.stdout + result.stderr


def test_declared_new_group_and_user_remain_pending_in_check_mode(tmp_path: Path) -> None:
    """Do not fail or create an account just because check mode has not created its group."""
    code, output = _run(
        tmp_path,
        {"abhaile-fixture": {"primary_group": "abhaile-fixture", "system": True}},
        {"abhaile-fixture": {}},
    )
    assert code == 0, output
    assert "Report account checks pending newly declared groups" in output


def test_gid_collision_is_refused_before_group_creation(tmp_path: Path) -> None:
    """Reject assigning the root GID to an unrelated declared group."""
    code, output = _run(tmp_path, {}, {"abhaile-fixture": {"gid": 0}})
    assert code != 0
    assert "GID conflicts" in output
    assert "Create declared groups" not in output


def test_uid_collision_is_refused_before_account_creation(tmp_path: Path) -> None:
    """Reject assigning the current UID to a different declared user."""
    code, output = _run(
        tmp_path,
        {"abhaile-fixture": {"uid": os.getuid(), "primary_group": "root"}},
        {},
    )
    assert code != 0
    assert "conflicts with existing identity" in output
    assert "Create declared groups" not in output


def test_existing_user_home_is_not_relocated(tmp_path: Path) -> None:
    """Refuse an authored home change instead of moving existing application data."""
    user = pwd.getpwuid(os.getuid())
    code, output = _run(tmp_path, {user.pw_name: {"home": "/nonexistent/abhaile-fixture"}}, {})
    assert code != 0
    assert "conflicts with existing identity" in output
    assert "Create declared groups" not in output


def test_existing_primary_group_is_not_changed(tmp_path: Path) -> None:
    """Refuse a primary GID change before invoking the native user module."""
    user = pwd.getpwuid(os.getuid())
    group = next(group for group in grp.getgrall() if group.gr_gid != user.pw_gid)
    code, output = _run(tmp_path, {user.pw_name: {"primary_group": group.gr_name}}, {})
    assert code != 0
    assert "conflicts with existing identity" in output
    assert "Create declared groups" not in output


def test_unsupported_package_identifier_is_rejected(tmp_path: Path) -> None:
    """Reject shell-like or non-package input before invoking the package manager."""
    code, output = _run(tmp_path, {}, {}, ["bash;touch /tmp/unexpected"])
    assert code != 0
    assert "unsupported package identifier" in output


def test_native_package_check_is_non_mutating(tmp_path: Path) -> None:
    """Query an already installed baseline package without installing or starting anything."""
    code, output = _run(tmp_path, {}, {}, ["bash"])
    assert code == 0, output
    assert "Install declared packages through the native package manager" in output


def test_rootless_namespace_and_runtime_are_pending_in_check_mode(tmp_path: Path) -> None:
    """Validate explicit namespace intent without editing subordinate IDs or invoking logind."""
    occupied_end = 65536
    for path in (Path("/etc/subuid"), Path("/etc/subgid")):
        if path.exists():
            for line in path.read_text().splitlines():
                parts = line.split(":")
                if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                    occupied_end = max(occupied_end, int(parts[1]) + int(parts[2]))
    if occupied_end + 65536 > 2**32:
        pytest.skip("No free test namespace interval is available")
    code, output = _run(
        tmp_path,
        {
            "abhaile-fixture": {
                "home": "/home/abhaile-fixture",
                "system": False,
                "rootless": {
                    "subuid_start": occupied_end,
                    "subgid_start": occupied_end,
                    "count": 65536,
                },
            }
        },
        {"abhaile-fixture": {}},
    )
    assert code == 0, output
    assert "Report rootless runtime preparation pending live enrollment" in output


@pytest.mark.parametrize("invalid", [False, True])
def test_explicit_rootless_and_native_group_allocation_schema(invalid: bool) -> None:
    """Allow omitted native IDs and require complete explicit namespace ranges."""
    rootless = {"subuid_start": 100000, "subgid_start": 100000, "count": 65536}
    if invalid:
        rootless.pop("subgid_start")
    host = {
        "name": "test",
        "composition": {
            "software": {},
            "user_management": {
                "users": {"app": {"home": "/home/app", "rootless": rootless}},
                "groups": {"app": {}},
            },
        },
    }
    schema_path = Path(__file__).resolve().parents[2] / "schemas/host.schema.json"
    if invalid:
        with pytest.raises(RenderError, match="subgid_start"):
            validate_schema(host, read_json(schema_path), "host", schema_path)
    else:
        validate_schema(host, read_json(schema_path), "host", schema_path)


@pytest.mark.parametrize(
    "state,enrollment",
    [("matching", False), ("changed", False), ("missing", False), ("missing", True)],
)
def test_protected_access_requires_explicit_enrollment(
    tmp_path: Path, state: str, enrollment: bool
) -> None:
    """Exercise production no-follow target and access guards against disposable files."""
    role = Path(__file__).resolve().parents[2] / "ansible/roles/host_foundations/tasks/main.yml"
    task_names = {
        "Inspect host prerequisite publication targets",
        "Refuse redirected or non-file prerequisite targets",
        "Preserve protected automation access outside explicit enrollment",
    }
    tasks = [task for task in yaml.safe_load(role.read_text()) if task.get("name") in task_names]
    target = tmp_path / "protected-access"
    expected = b"# reviewed protected access\n"
    if state != "missing":
        target.write_bytes(expected if state == "matching" else b"# changed outside enrollment\n")
    entry = {
        "kind": "host.sudoers",
        "target_path": str(target),
        "sha256": hashlib.sha256(expected).hexdigest(),
    }
    playbook = tmp_path / "access.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Check protected access guards",
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "abhaile_host_foundation_entries": [entry],
                        "abhaile_bootstrap_enrollment": enrollment,
                    },
                    "tasks": tasks,
                }
            ]
        )
    )
    environment = tmp_path / "environment"
    environment.mkdir()
    before = target.read_bytes() if target.exists() else None
    result = _ansible(
        "ansible.cli.playbook",
        ["-i", "localhost,", "--connection=local", "--check", str(playbook)],
        _closed_environment(environment),
    )
    assert (result.returncode == 0) is (state == "matching" or enrollment), (
        result.stdout + result.stderr
    )
    assert (target.read_bytes() if target.exists() else None) == before
