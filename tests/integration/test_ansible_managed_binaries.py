"""Exercise native binary inspection and publication without host filesystem writes."""

import hashlib
import os
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _run(
    tmp_path: Path, entry: dict, *, check: bool = False, full: bool = False
) -> tuple[int, str]:
    """Invoke the production tasks against isolated payloads and targets."""
    tmp_path.mkdir()
    if full:
        descriptor = b"download declaration\n"
        (tmp_path / "binary.yaml").write_bytes(descriptor)
        entry = {
            **entry,
            "render_path": "binary.yaml",
            "size": len(descriptor),
            "sha256": hashlib.sha256(descriptor).hexdigest(),
        }
    tasks = [
        {
            "ansible.builtin.include_role": {
                "name": "managed_binaries",
                "tasks_from": "main.yml" if full else "binary.yml",
            }
        }
    ]
    playbook = tmp_path / "play.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_binary_entry": entry,
                        "abhaile_binary_entries": [entry],
                        "abhaile_rendered_root": str(tmp_path),
                    },
                    "tasks": tasks,
                }
            ]
        )
    )
    environment = tmp_path / "env"
    environment.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    result = _ansible(
        "ansible.cli.playbook",
        [*arguments, str(playbook)],
        _closed_environment(environment),
        timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


def _entry(target: Path, payload: Path) -> dict:
    """Use file transport only in isolated publication tests; main rejects it."""
    return {
        "kind": "host.binary",
        "target_path": str(target),
        "apply_hints": {
            "url": payload.as_uri(),
            "payload_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            "owner_user": str(os.getuid()),
            "owner_group": str(os.getgid()),
            "mode": "0755",
        },
    }


@pytest.mark.integration
def test_binary_install_offline_noop_metadata_repair_and_restore(tmp_path: Path) -> None:
    """Install once, remain offline when matching, and restore the previous payload."""
    target = tmp_path / "executable"
    payload = tmp_path / "payload"
    payload.write_bytes(b"first release")
    entry = _entry(target, payload)
    code, output = _run(tmp_path / "install", entry)
    assert code == 0, output
    assert target.read_bytes() == b"first release"
    assert target.stat().st_mode & 0o777 == 0o755
    original_inode = target.stat().st_ino
    payload.unlink()
    code, output = _run(tmp_path / "offline", entry)
    assert code == 0, output
    assert "changed=0" in output
    assert target.stat().st_ino == original_inode
    target.chmod(0o700)
    code, output = _run(tmp_path / "metadata", entry)
    assert code == 0, output
    assert target.stat().st_mode & 0o777 == 0o755
    assert target.stat().st_ino == original_inode
    payload.write_bytes(b"second release")
    candidate = _entry(target, payload)
    code, output = _run(tmp_path / "upgrade", candidate)
    assert code == 0, output
    assert target.read_bytes() == b"second release"
    assert target.stat().st_ino != original_inode
    payload.unlink()
    code, output = _run(tmp_path / "offline-restore", entry)
    assert code != 0, output
    assert target.read_bytes() == b"second release"
    assert not list(tmp_path.glob(".abhaile-binary-*"))
    payload.write_bytes(b"first release")
    code, output = _run(tmp_path / "restore", entry)
    assert code == 0, output
    assert target.read_bytes() == b"first release"
    assert not list(tmp_path.glob(".abhaile-binary-*"))


@pytest.mark.integration
def test_binary_check_mode_and_failed_checksum_preserve_target(tmp_path: Path) -> None:
    """Check missing/mismatched targets locally and refuse unverified replacement."""
    target = tmp_path / "executable"
    payload = tmp_path / "payload"
    payload.write_bytes(b"expected release")
    entry = _entry(target, payload)
    payload.unlink()
    code, output = _run(tmp_path / "check-missing", entry, check=True)
    assert code == 0, output
    assert "changed=1" in output
    assert not target.exists()
    target.write_bytes(b"installed release")
    code, output = _run(tmp_path / "check-mismatch", entry, check=True)
    assert code == 0, output
    assert target.read_bytes() == b"installed release"
    payload.write_bytes(b"incorrect upstream bytes")
    code, output = _run(tmp_path / "bad-checksum", entry)
    assert code != 0, output
    assert target.read_bytes() == b"installed release"
    assert not list(tmp_path.glob(".abhaile-binary-*"))


@pytest.mark.integration
def test_binary_role_rejects_unsafe_declaration_before_mutation(tmp_path: Path) -> None:
    """Exercise the real role boundary rather than relaxing production paths for tests."""
    payload = tmp_path / "payload"
    payload.write_bytes(b"payload")
    target = tmp_path / "must-not-exist"
    code, output = _run(tmp_path / "unsafe", _entry(target, payload), full=True)
    assert code != 0, output
    assert not target.exists()


@pytest.mark.integration
def test_complete_binary_role_accepts_valid_check_mode_declaration(tmp_path: Path) -> None:
    """Run production path, parent and source validation without modifying the host."""
    target = Path("/usr/local/bin") / ("abhaile-test-" + tmp_path.name)
    assert not target.exists()
    entry = {
        "kind": "host.binary",
        "target_path": str(target),
        "owner_ref": "host-binary:example",
        "apply_hints": {
            "url": "https://example.invalid/releases/example",
            "payload_sha256": "a" * 64,
            "owner_user": "root",
            "owner_group": "root",
            "mode": "0755",
        },
    }
    code, output = _run(tmp_path / "valid-check", entry, check=True, full=True)
    assert code == 0, output
    assert "changed=1" in output
    assert not target.exists()
