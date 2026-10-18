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
