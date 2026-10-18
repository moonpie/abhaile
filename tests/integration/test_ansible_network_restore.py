"""Exercise the network-only boot restoration playbook boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.integration.test_ansible_scaffold import REPO_ROOT, _ansible, _closed_environment

PLAYBOOK = REPO_ROOT / "ansible/playbooks/restore-network.yml"


def _run_unauthorized_restore(tmp_path: Path) -> tuple[int, str, str]:
    """Run normal mode without its required live authorization."""
    rendered_root = tmp_path / "rendered"
    source = rendered_root / "system/etc/systemd/network/10-test0.network"
    source.parent.mkdir(parents=True)
    content = "[Match]\nName=test0\n"
    source.write_text(content, encoding="utf-8")
    manifest = {
        "version": "1",
        "host": "test-host",
        "entries": [
            {
                "render_path": "system/etc/systemd/network/10-test0.network",
                "target_path": "/etc/systemd/network/10-test0.network",
                "kind": "networkd.network",
                "owner_ref": "iface:test0",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "size": len(content.encode()),
                "apply_hints": None,
            }
        ],
    }
    (rendered_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    extra_vars = {
        "abhaile_rendered_root": str(rendered_root),
        "abhaile_expected_host": "test-host",
        "abhaile_candidate_cleanup_entries": [],
        "abhaile_live_apply": False,
    }
    result = _ansible(
        "ansible.cli.playbook",
        [
            "-i",
            "localhost,",
            "--connection=local",
            "-e",
            json.dumps(extra_vars),
            str(PLAYBOOK),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_network_restore_passes_syntax_check(tmp_path: Path) -> None:
    """Load the dedicated playbook through the closed Ansible environment."""
    environment_root = tmp_path / "environment"
    environment_root.mkdir()

    result = _ansible(
        "ansible.cli.playbook",
        ["--syntax-check", "-i", "localhost,", "--connection=local", str(PLAYBOOK)],
        _closed_environment(environment_root),
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.integration
def test_network_restore_normal_mode_requires_live_authorization(tmp_path: Path) -> None:
    """Fail before role execution when mutation is not explicitly authorized."""
    code, stdout, stderr = _run_unauthorized_restore(tmp_path)

    assert code != 0
    assert "explicit live authorization" in stdout + stderr


def test_network_restore_role_skips_runtime_networkctl_effects() -> None:
    """Keep early restoration limited to files before networkd starts."""
    tasks_path = REPO_ROOT / "ansible/roles/networkd_config/tasks/main.yml"
    tasks = tasks_path.read_text(encoding="utf-8")

    assert "not abhaile_networkd_early_restore | default(false)" in tasks
    assert "Remove matching candidate-only networkd files" in tasks
