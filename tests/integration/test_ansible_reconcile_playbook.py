"""Exercise the quarantined direct-role reconciliation playbook boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration.test_ansible_scaffold import REPO_ROOT, _ansible, _closed_environment

PLAYBOOK = REPO_ROOT / "ansible/playbooks/reconcile.yml"


def _write_empty_render(rendered_root: Path, host: str = "test-host") -> None:
    """Write the smallest valid host-bound manifest."""
    rendered_root.mkdir(parents=True)
    manifest = {"version": "1", "host": host, "entries": []}
    (rendered_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _run_reconcile(
    tmp_path: Path,
    *,
    check: bool,
    authorize: bool = False,
    manifest_host: str = "test-host",
    expected_host: str = "test-host",
) -> tuple[int, str, str]:
    """Run the production playbook boundary against an empty manifest."""
    rendered_root = tmp_path / "rendered"
    config_root = tmp_path / "config"
    config_root.mkdir()
    _write_empty_render(rendered_root, manifest_host)
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    extra_vars = {
        "abhaile_rendered_root": str(rendered_root),
        "abhaile_config_root": str(config_root),
        "abhaile_expected_host": expected_host,
        "abhaile_live_apply": authorize,
    }
    arguments = [
        "-i",
        "localhost,",
        "--connection=local",
        "-e",
        json.dumps(extra_vars),
    ]
    if check:
        arguments.append("--check")
    arguments.append(str(PLAYBOOK))
    result = _ansible(
        "ansible.cli.playbook",
        arguments,
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_reconcile_playbook_passes_syntax_check(tmp_path: Path) -> None:
    """Load the direct-role playbook through the closed Ansible environment."""
    environment_root = tmp_path / "environment"
    environment_root.mkdir()

    result = _ansible(
        "ansible.cli.playbook",
        ["--syntax-check", "-i", "localhost,", "--connection=local", str(PLAYBOOK)],
        _closed_environment(environment_root),
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.integration
def test_reconcile_check_mode_needs_no_live_authorization(tmp_path: Path) -> None:
    """Allow the runner's pre-mutation check-mode pass through the same roles."""
    code, stdout, stderr = _run_reconcile(tmp_path, check=True)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_reconcile_normal_mode_requires_live_authorization(tmp_path: Path) -> None:
    """Fail closed when normal mode lacks its explicit mutation gate."""
    code, stdout, stderr = _run_reconcile(tmp_path, check=False)

    assert code != 0
    assert "explicit live authorization" in stdout + stderr


@pytest.mark.integration
def test_reconcile_authorized_normal_mode_enters_orchestrator(tmp_path: Path) -> None:
    """Permit an explicitly authorized empty reconciliation without mutation."""
    code, stdout, stderr = _run_reconcile(tmp_path, check=False, authorize=True)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_reconcile_rejects_wrong_host_in_check_mode(tmp_path: Path) -> None:
    """Bind preflight to the rendered manifest's expected local host."""
    code, _stdout, _stderr = _run_reconcile(
        tmp_path,
        check=True,
        manifest_host="other-host",
    )

    assert code != 0
