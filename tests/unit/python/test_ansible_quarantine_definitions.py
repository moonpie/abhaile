"""Audit production Ansible task definitions."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / "ansible/roles/manifest_convergence/tasks"


def test_compiler_vocabulary_has_definition_or_explicit_rejection() -> None:
    """Keep the production dispatcher exhaustive and bounded."""
    expected = {
        "binary-download": "abhaile_download",
        "archive-download": "abhaile_download",
        "directory": "abhaile_publish",
        "packages": "ansible.builtin.apt",
        "publish": "abhaile_publish",
        "lifecycle": "ansible.builtin.systemd_service",
        "sudo-candidate": "abhaile_publish",
        "kernel-modules": "ansible.builtin.include_tasks",
        "systemd-units": "ansible.builtin.systemd_service",
        "unattended-upgrades": "ansible.builtin.debconf",
        "udev-rule": "abhaile_publish",
    }
    for operation, module in expected.items():
        task_path = TASKS / "operations" / f"{operation}.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        assert any(module in task for task in tasks)
        text = task_path.read_text(encoding="utf-8")
        assert "ansible.builtin.shell" not in text
        assert all(task.get("no_log") is True for task in tasks)
        assert (TASKS / "validate" / f"{operation}.yml").is_file()


def test_production_role_discovery_excludes_test_support() -> None:
    """Use one production implementation rather than a test-only mutation copy."""
    production = (ROOT / "ansible/ansible.cfg").read_text(encoding="utf-8")
    playbook = (ROOT / "ansible/playbooks/converge.yml").read_text(encoding="utf-8")
    assert "tests/support" not in production
    assert "isolated_manifest_convergence" not in playbook
    assert not (ROOT / "tests/support/ansible_quarantine").exists()
