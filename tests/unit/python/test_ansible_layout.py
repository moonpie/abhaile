"""Tests for the quarantined Ansible migration scaffold."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_convergence_play_is_preflight_only_and_fail_closed() -> None:
    """Allow only read-only reporting and assertion modules in the quarantine play."""
    playbook_path = REPO_ROOT / "ansible/playbooks/converge.yml"
    plays = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))
    assert isinstance(plays, list) and len(plays) == 1
    play = plays[0]
    assert play["connection"] == "local"
    assert play["gather_facts"] is False
    assert play["become"] is False
    tasks = play["tasks"]
    modules = {key for task in tasks for key in task if key.startswith("ansible.builtin.")}
    assert modules <= {"ansible.builtin.assert", "ansible.builtin.debug", "ansible.builtin.stat"}
    assertions = [
        task["ansible.builtin.assert"] for task in tasks if "ansible.builtin.assert" in task
    ]
    assert assertions and any(assertion.get("that") is False for assertion in assertions)


def test_convergence_play_cannot_invoke_git_or_roles() -> None:
    """Keep fetch, checkout, role inclusion, and mutation out of convergence."""
    text = (REPO_ROOT / "ansible/playbooks/converge.yml").read_text(encoding="utf-8")
    forbidden = ("git", "checkout", "fetch", "include_role", "command:", "shell:", "file:")
    assert all(value not in text for value in forbidden)


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
    from configparser import ConfigParser

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
