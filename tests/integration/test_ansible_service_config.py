"""Exercise the owner-scoped service configuration Ansible role."""

from __future__ import annotations

import hashlib
import os
import pwd
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(
    rendered_root: Path,
    target: Path,
    *,
    owner_ref: str = "service:example",
    kind: str = "service.config",
    content: str = "value=true\n",
    hints: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write a source and return its selected manifest entry."""
    render_path = f"services/example/{target.name}"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": str(target),
        "kind": kind,
        "owner_ref": owner_ref,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": hints,
    }


def _cleanup_entry(entry: dict[str, object]) -> dict[str, object]:
    """Convert a canonical candidate entry into matching cleanup evidence."""
    cleanup = dict(entry)
    cleanup["candidate_sha256"] = cleanup.pop("sha256")
    cleanup["live_sha256"] = cleanup["candidate_sha256"]
    return cleanup


def _write_playbook(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
    *,
    cleanup_entries: list[dict[str, object]] | None = None,
    managed_directory_targets: list[Path] | None = None,
) -> Path:
    """Write an isolated localhost play invoking the production role."""
    playbook = tmp_path / "service-config.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test service configuration",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_service_config_entries": entries,
                        "abhaile_service_config_cleanup_entries": cleanup_entries or [],
                        "abhaile_service_config_managed_directory_targets": [
                            str(path) for path in managed_directory_targets or []
                        ],
                    },
                    "roles": ["service_config"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return playbook


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
def test_service_config_rootless_first_run_and_unchanged_rerun(tmp_path: Path) -> None:
    """Publish rootless configuration once and remain unchanged on rerun."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "config.yml"
    target.parent.mkdir()
    current_user = pwd.getpwuid(os.getuid()).pw_name
    entry = _entry(
        rendered,
        target,
        hints={
            "restart_unit": None,
            "rootless": True,
            "podman_user": current_user,
            "mode": "0600",
        },
    )
    playbook = _write_playbook(tmp_path, rendered, [entry])

    first_code, first_stdout, first_stderr = _run_playbook(tmp_path / "first", playbook)
    assert first_code == 0, first_stdout + first_stderr
    assert target.read_text(encoding="utf-8") == "value=true\n"
    assert target.stat().st_mode & 0o777 == 0o600

    second_code, second_stdout, second_stderr = _run_playbook(tmp_path / "second", playbook)
    assert second_code == 0, second_stdout + second_stderr
    assert "changed=0" in second_stdout


@pytest.mark.integration
def test_service_config_publishes_config_and_environment_for_one_owner(tmp_path: Path) -> None:
    """Publish structurally identical config and environment files in one owner batch."""
    rendered = tmp_path / "rendered"
    target_root = tmp_path / "service"
    target_root.mkdir()
    current_user = pwd.getpwuid(os.getuid()).pw_name
    hints: dict[str, object] = {
        "restart_unit": None,
        "rootless": True,
        "podman_user": current_user,
    }
    entries = [
        _entry(rendered, target_root / "config.hcl", hints=hints),
        _entry(rendered, target_root / "vault.env", kind="service.env", hints=hints),
    ]
    playbook = _write_playbook(tmp_path, rendered, entries)

    code, stdout, stderr = _run_playbook(tmp_path / "combined", playbook)

    assert code == 0, stdout + stderr
    assert (target_root / "config.hcl").read_text(encoding="utf-8") == "value=true\n"
    assert (target_root / "vault.env").read_text(encoding="utf-8") == "value=true\n"


@pytest.mark.integration
def test_service_config_check_mode_does_not_publish_or_restart(tmp_path: Path) -> None:
    """Report a restart-bearing change without publishing or touching systemd."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "config.yml"
    target.parent.mkdir()
    entry = _entry(rendered, target, hints={"restart_unit": "example.service"})
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, stdout, stderr = _run_playbook(tmp_path / "check", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert not target.exists()


@pytest.mark.integration
def test_service_config_check_mode_accepts_absent_declared_parent(tmp_path: Path) -> None:
    """Validate a new file whose managed parent will be created during live apply."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "new-service" / "config.yml"
    entry = _entry(rendered, target, hints={"restart_unit": None})
    playbook = _write_playbook(
        tmp_path,
        rendered,
        [entry],
        managed_directory_targets=[target.parent],
    )

    code, stdout, stderr = _run_playbook(tmp_path / "absent-parent", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert not target.parent.exists()


@pytest.mark.integration
def test_service_config_check_mode_rejects_absent_undeclared_parent(tmp_path: Path) -> None:
    """Refuse to assume that an absent parent will be created without manifest authority."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "undeclared-service" / "config.yml"
    entry = _entry(rendered, target, hints={"restart_unit": None})
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "undeclared-parent", playbook, check=True)

    assert code != 0
    assert not target.parent.exists()


@pytest.mark.integration
def test_service_config_rejects_mixed_owners_before_publication(tmp_path: Path) -> None:
    """Require the caller to provide one coherent owner selection."""
    rendered = tmp_path / "rendered"
    first_target = tmp_path / "service" / "first.yml"
    second_target = tmp_path / "service" / "second.yml"
    first_target.parent.mkdir()
    entries = [
        _entry(rendered, first_target, owner_ref="service:first", hints={}),
        _entry(rendered, second_target, owner_ref="service:second", hints={}),
    ]
    playbook = _write_playbook(tmp_path, rendered, entries)

    code, _stdout, _stderr = _run_playbook(tmp_path / "mixed", playbook)

    assert code != 0
    assert not first_target.exists()
    assert not second_target.exists()


@pytest.mark.integration
def test_service_config_rejects_coerced_rootless_hint(tmp_path: Path) -> None:
    """Require an exact boolean rootless hint."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "config.yml"
    target.parent.mkdir()
    entry = _entry(rendered, target, hints={"rootless": "false"})
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "coerced", playbook)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
def test_service_config_removes_matching_candidate_only_file(tmp_path: Path) -> None:
    """Remove one identity-matched candidate addition through the owner role."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "candidate.yml"
    target.parent.mkdir()
    candidate = _entry(rendered, target, content="candidate=true\n", hints={})
    target.write_text("candidate=true\n")
    playbook = _write_playbook(
        tmp_path,
        rendered,
        [],
        cleanup_entries=[_cleanup_entry(candidate)],
    )

    code, stdout, stderr = _run_playbook(tmp_path / "cleanup", playbook)

    assert code == 0, stdout + stderr
    assert not target.exists()


@pytest.mark.integration
def test_service_config_cleanup_refuses_live_drift(tmp_path: Path) -> None:
    """Keep a candidate-only file whose bytes changed after classification."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "candidate.yml"
    target.parent.mkdir()
    candidate = _entry(rendered, target, content="candidate=true\n", hints={})
    target.write_text("operator-change=true\n")
    playbook = _write_playbook(
        tmp_path,
        rendered,
        [],
        cleanup_entries=[_cleanup_entry(candidate)],
    )

    code, _stdout, _stderr = _run_playbook(tmp_path / "drift", playbook)

    assert code != 0
    assert target.read_text() == "operator-change=true\n"


@pytest.mark.integration
def test_service_config_cleanup_check_mode_preserves_matching_file(tmp_path: Path) -> None:
    """Report candidate-only removal without deleting in check mode."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "candidate.env"
    target.parent.mkdir()
    candidate = _entry(
        rendered,
        target,
        kind="service.env",
        content="CANDIDATE=true\n",
        hints={},
    )
    target.write_text("CANDIDATE=true\n")
    playbook = _write_playbook(
        tmp_path,
        rendered,
        [],
        cleanup_entries=[_cleanup_entry(candidate)],
    )

    code, stdout, stderr = _run_playbook(tmp_path / "check-cleanup", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert target.read_text() == "CANDIDATE=true\n"


@pytest.mark.integration
def test_service_config_cleanup_rejects_desired_overlap(tmp_path: Path) -> None:
    """Never delete a target also selected by last-successful desired state."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "shared.yml"
    target.parent.mkdir()
    desired = _entry(rendered, target, content="accepted=true\n", hints={})
    target.write_text("accepted=true\n")
    playbook = _write_playbook(
        tmp_path,
        rendered,
        [desired],
        cleanup_entries=[_cleanup_entry(desired)],
    )

    code, _stdout, _stderr = _run_playbook(tmp_path / "overlap", playbook)

    assert code != 0
    assert target.read_text() == "accepted=true\n"


@pytest.mark.integration
def test_service_config_cleanup_rejects_traversal_target(tmp_path: Path) -> None:
    """Reject a cleanup path containing parent traversal before live inspection."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "service" / "candidate.yml"
    target.parent.mkdir()
    candidate = _entry(rendered, target, content="candidate=true\n", hints={})
    cleanup = _cleanup_entry(candidate)
    cleanup["target_path"] = f"{tmp_path}/service/../candidate.yml"
    playbook = _write_playbook(tmp_path, rendered, [], cleanup_entries=[cleanup])

    code, _stdout, _stderr = _run_playbook(tmp_path / "traversal", playbook)

    assert code != 0
    assert not target.exists()
