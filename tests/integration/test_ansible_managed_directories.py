"""Exercise the direct managed-directory Ansible role."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_playbook(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    """Write an isolated localhost play that invokes the production role."""
    playbook = tmp_path / "managed-directories.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test managed directories",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {"abhaile_directory_entries": entries},
                    "roles": ["managed_directories"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return playbook


def _entry(path: Path, *, mode: str = "0750") -> dict[str, object]:
    """Build one canonical selected manifest directory entry."""
    return {
        "render_path": "services/example/data",
        "target_path": str(path),
        "kind": "service.directory",
        "owner_ref": "service:example",
        "sha256": "0" * 64,
        "size": 0,
        "is_directory": True,
        "apply_hints": {"owner": os.getuid(), "group": os.getgid(), "mode": mode},
    }


def _run_playbook(tmp_path: Path, playbook: Path, *, check: bool = False) -> tuple[int, str, str]:
    """Run the isolated role play and return its result fields."""
    tmp_path.mkdir(parents=True)
    environment_root = tmp_path / "env"
    environment_root.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    arguments.append(str(playbook))
    result = _ansible("ansible.cli.playbook", arguments, _closed_environment(environment_root))
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_managed_directories_first_run_and_unchanged_rerun(tmp_path: Path) -> None:
    """Create exact directory metadata once and remain unchanged on rerun."""
    target = tmp_path / "managed" / "data"
    playbook = _write_playbook(tmp_path, [_entry(target)])

    first_code, first_stdout, first_stderr = _run_playbook(tmp_path / "first", playbook)
    assert first_code == 0, first_stdout + first_stderr
    assert "changed=1" in first_stdout
    assert target.is_dir()
    assert target.stat().st_mode & 0o777 == 0o750

    second_code, second_stdout, second_stderr = _run_playbook(tmp_path / "second", playbook)
    assert second_code == 0, second_stdout + second_stderr
    assert "changed=0" in second_stdout


@pytest.mark.integration
def test_managed_directories_check_mode_does_not_create(tmp_path: Path) -> None:
    """Report an absent directory without creating it in check mode."""
    target = tmp_path / "managed" / "check-only"
    playbook = _write_playbook(tmp_path, [_entry(target, mode="0755")])

    code, stdout, stderr = _run_playbook(tmp_path / "check", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert not target.exists()


@pytest.mark.integration
def test_managed_directories_validate_all_entries_before_mutation(tmp_path: Path) -> None:
    """Reject a malformed selection before creating any valid directory."""
    valid_target = tmp_path / "managed" / "must-not-exist"
    invalid_entry = _entry(tmp_path / "managed" / "invalid")
    invalid_entry["target_path"] = "relative/path"
    playbook = _write_playbook(tmp_path, [_entry(valid_target), invalid_entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "invalid", playbook)

    assert code != 0
    assert not valid_target.exists()


@pytest.mark.integration
def test_managed_directories_reject_coerced_marker_and_invalid_identity(tmp_path: Path) -> None:
    """Require canonical boolean and non-empty, non-negative identity values."""
    target = tmp_path / "managed" / "must-not-exist"
    invalid_entry = _entry(target)
    invalid_entry["is_directory"] = "true"
    invalid_entry["apply_hints"] = {"owner": "", "group": -1, "mode": "0750"}
    playbook = _write_playbook(tmp_path, [invalid_entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "invalid-types", playbook)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
@pytest.mark.parametrize("render_path", [".", "..", "./outside", "../outside"])
def test_managed_directories_reject_render_paths_outside_rendered_root(
    tmp_path: Path,
    render_path: str,
) -> None:
    """Reject leading traversal before any selected target is created."""
    target = tmp_path / "managed" / "must-not-exist"
    invalid_entry = _entry(target)
    invalid_entry["render_path"] = render_path
    playbook = _write_playbook(tmp_path, [invalid_entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "invalid-render-path", playbook)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
def test_managed_directories_repair_root_without_touching_descendants(tmp_path: Path) -> None:
    """Repair a root mode without changing nested application data or metadata."""
    target = tmp_path / "managed" / "data"
    child = target / "application"
    child.mkdir(parents=True)
    child.chmod(0o1777)
    database = child / "database"
    database.write_bytes(b"application state\n")
    database.chmod(0o600)
    target.chmod(0o700)
    paths = [child, database]
    before = {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid) for path in paths}
    playbook = _write_playbook(tmp_path, [_entry(target)])

    code, stdout, stderr = _run_playbook(tmp_path / "repair", playbook)
    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert target.stat().st_mode & 0o777 == 0o750
    assert database.read_bytes() == b"application state\n"
    assert before == {
        path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid) for path in paths
    }

    code, stdout, stderr = _run_playbook(tmp_path / "unchanged", playbook)
    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
@pytest.mark.parametrize("target_type", ["file", "symlink", "dangling"])
@pytest.mark.parametrize("check", [False, True])
def test_managed_directories_preflight_all_targets_before_changes(
    tmp_path: Path, target_type: str, check: bool
) -> None:
    """Reject unsafe targets in check and real mode before any selected directory changes."""
    existing = tmp_path / "existing"
    existing.mkdir(mode=0o700)
    missing = tmp_path / "must-not-create"
    invalid = tmp_path / "invalid"
    referent = tmp_path / "referent"
    if target_type == "file":
        invalid.write_bytes(b"keep file\n")
    else:
        if target_type == "symlink":
            referent.mkdir(mode=0o700)
        invalid.symlink_to(referent, target_is_directory=True)
    playbook = _write_playbook(tmp_path, [_entry(existing), _entry(missing), _entry(invalid)])

    code, stdout, stderr = _run_playbook(tmp_path / "unsafe", playbook, check=check)
    assert code != 0
    assert "existing file or symlink" in stdout + stderr
    assert existing.stat().st_mode & 0o777 == 0o700
    assert not missing.exists()
    if target_type == "file":
        assert invalid.read_bytes() == b"keep file\n"
    else:
        assert invalid.is_symlink()
        if target_type == "symlink":
            assert referent.stat().st_mode & 0o777 == 0o700


@pytest.mark.integration
def test_managed_directories_empty_recovery_selection_preserves_data(tmp_path: Path) -> None:
    """An older desired inventory without a new root must not delete its application data."""
    target = tmp_path / "data"
    target.mkdir(mode=0o750)
    database = target / "database"
    database.write_bytes(b"preserve across recovery\n")
    playbook = _write_playbook(tmp_path, [])
    code, stdout, stderr = _run_playbook(tmp_path / "recovery", playbook)
    assert code == 0, stdout + stderr
    assert "changed=0" in stdout
    assert target.is_dir()
    assert database.read_bytes() == b"preserve across recovery\n"
