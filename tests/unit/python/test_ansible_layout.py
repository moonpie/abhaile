"""Tests for the quarantined Ansible migration scaffold."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_ansible_enables_host_key_validation() -> None:
    """Do not weaken pinned Git host trust through Ansible configuration."""
    text = (REPO_ROOT / "ansible/ansible.cfg").read_text(encoding="utf-8")
    assert "host_key_checking = True" in text
    assert "host_key_checking = False" not in text


def test_sudo_policy_is_non_installed_constrained_candidate() -> None:
    """Keep the fixed launcher policy separate from the live-compatible policy."""
    candidate = REPO_ROOT / "ansible/sudoers/abhaile-converge.candidate"
    live_role = REPO_ROOT / "ansible/roles/sudoers/tasks/main.yml"
    text = candidate.read_text(encoding="utf-8")
    assert "/usr/local/sbin/abhaile-converge-launcher ^--runner" in text
    assert "[0-9a-f]{40}" in text
    assert text.count("*") == 0
    assert "NOPASSWD:ALL" not in text
    assert "--dry-run" in text
    assert "/opt/abhaile/.venv/bin/abhaile-apply" in live_role.read_text(encoding="utf-8")


def test_scaffold_uses_protected_runtime_and_suppresses_payload_channels() -> None:
    """Keep mutable checkout discovery and secret reporting out of defaults."""
    config = ConfigParser()
    config.read(REPO_ROOT / "ansible/ansible.cfg")
    defaults = config["defaults"]
    assert "/opt/abhaile" not in str(dict(defaults))
    assert defaults["stdout_callback"] == "default"
    assert "inventory" not in defaults
    assert "callbacks_enabled" not in defaults
    assert defaults["gathering"] == "explicit"
    assert defaults.getboolean("no_log")
    assert not defaults.getboolean("keep_remote_files")
    assert not defaults.getboolean("collections_scan_sys_path")
    assert not config["diff"].getboolean("always")
    assert defaults["interpreter_python"].startswith("/usr/lib/abhaile-ansible-runtime/")


def test_privileged_launcher_uses_isolated_protected_python() -> None:
    """Exclude caller-controlled import paths from privileged launcher execution."""
    launcher = (REPO_ROOT / "scripts/abhaile-converge-launcher").read_text(encoding="utf-8")
    assert (
        "exec /usr/lib/abhaile-trust-runtime/bin/python -I " '-m abhaile.trust.launcher "$@"'
    ) in launcher


def test_convergence_play_invokes_only_bounded_quarantined_role() -> None:
    """Keep bootstrap roles and mutation tasks out of protected convergence."""
    playbook = yaml.safe_load(
        (REPO_ROOT / "ansible/playbooks/converge.yml").read_text(encoding="utf-8")
    )
    assert playbook[0]["hosts"] == "localhost"
    assert playbook[0]["connection"] == "local"
    assert playbook[0]["gather_facts"] is False
    assert playbook[0]["become"] is False
    assert playbook[0]["roles"] == [{"role": "manifest_convergence"}]


def test_bounded_role_requires_gate_before_two_pass_dispatch() -> None:
    """Validate every operation before the production mutation pass begins."""
    tasks = yaml.safe_load(
        (REPO_ROOT / "ansible/roles/manifest_convergence/tasks/main.yml").read_text(
            encoding="utf-8"
        )
    )
    assert (
        "abhaile_execution_scope | default('disabled') == 'isolated-disposable-v1'"
        in tasks[0]["ansible.builtin.assert"]["that"]
    )
    assert tasks[1]["ansible.builtin.include_tasks"] == "validate_operation.yml"
    execute = next(
        task
        for task in tasks
        if task.get("ansible.builtin.include_tasks") == "execute_operation.yml"
    )
    assert execute["ansible.builtin.include_tasks"] == "execute_operation.yml"
