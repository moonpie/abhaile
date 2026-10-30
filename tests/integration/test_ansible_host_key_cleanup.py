"""Exercise bounded candidate-only principal key cleanup without changing host accounts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment

pytestmark = pytest.mark.integration


def _run(
    tmp_path: Path, home: Path, *, check: bool = False, principal: str = "fixture"
) -> tuple[int, str]:
    """Invoke the actual host role with no desired accounts and one temporary cleanup leaf."""
    digest = hashlib.sha256(b"approved public key fixture\n").hexdigest()
    entry = {
        "kind": "host.authorized_keys",
        "owner_ref": f"principal:{principal}",
        "target_path": str(home / ".ssh/authorized_keys"),
        "candidate_sha256": digest,
        "live_sha256": digest,
        "apply_hints": {"owner_user": principal, "home": str(home)},
    }
    playbook = tmp_path / "cleanup.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Clean candidate-only ordinary principal key",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "abhaile_rendered_root": str(tmp_path),
                        "abhaile_host_foundation_entries": [],
                        "abhaile_host_foundation_cleanup_entries": [entry],
                    },
                    "roles": ["host_foundations"],
                }
            ]
        )
    )
    environment = tmp_path / "environment"
    environment.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    result = _ansible(
        "ansible.cli.playbook", [*arguments, str(playbook)], _closed_environment(environment)
    )
    return result.returncode, result.stdout + result.stderr


@pytest.mark.parametrize("check", [False, True])
def test_matching_key_cleanup_preserves_home_and_application_data(
    tmp_path: Path, check: bool
) -> None:
    """Only the proven key leaf is removed; check mode preserves even that leaf."""
    home = tmp_path / "home/fixture"
    ssh = home / ".ssh"
    ssh.mkdir(parents=True)
    key = ssh / "authorized_keys"
    key.write_bytes(b"approved public key fixture\n")
    database = home / "application.db"
    database.write_bytes(b"keep application state\n")
    code, output = _run(tmp_path, home, check=check)
    assert code == 0, output
    assert key.exists() is check
    assert database.read_bytes() == b"keep application state\n"
    assert ssh.is_dir() and home.is_dir()


@pytest.mark.parametrize("state", ["changed", "dangling", "redirected_parent"])
def test_changed_or_redirected_key_cleanup_is_refused(tmp_path: Path, state: str) -> None:
    """Refuse changed bytes and redirected parents/leaves before removing anything."""
    home = tmp_path / "home/fixture"
    home.mkdir(parents=True)
    ssh = home / ".ssh"
    outside = tmp_path / "outside"
    if state == "redirected_parent":
        outside.mkdir()
        ssh.symlink_to(outside, target_is_directory=True)
    else:
        ssh.mkdir()
    key = ssh / "authorized_keys"
    if state == "dangling":
        key.symlink_to(outside)
    else:
        key.write_bytes(
            b"changed key fixture\n" if state == "changed" else b"approved public key fixture\n"
        )
    code, _output = _run(tmp_path, home)
    assert code != 0
    assert key.is_symlink() if state == "dangling" else key.is_file()
    if state == "dangling":
        assert not outside.exists()
    else:
        assert key.read_bytes() == (
            b"changed key fixture\n" if state == "changed" else b"approved public key fixture\n"
        )
    if state == "redirected_parent":
        assert ssh.is_symlink()


@pytest.mark.parametrize("principal", ["root", "abhaile"])
def test_protected_principal_cleanup_is_refused(tmp_path: Path, principal: str) -> None:
    """A matching digest never authorizes recovery to remove protected administrative keys."""
    home = tmp_path / "home" / principal
    key = home / ".ssh/authorized_keys"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"approved public key fixture\n")
    code, _output = _run(tmp_path, home, principal=principal)
    assert code != 0
    assert key.read_bytes() == b"approved public key fixture\n"


def test_absent_candidate_key_cleanup_is_a_noop(tmp_path: Path) -> None:
    """Keep a repeated cleanup safe without removing the remaining account data."""
    home = tmp_path / "home/fixture"
    home.mkdir(parents=True)
    database = home / "application.db"
    database.write_bytes(b"keep\n")
    code, output = _run(tmp_path, home)
    assert code == 0, output
    assert database.read_bytes() == b"keep\n"
    assert not (home / ".ssh").exists()
