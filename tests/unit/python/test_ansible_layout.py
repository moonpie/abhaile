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


def test_scaffold_uses_existing_runtime_and_suppresses_payload_channels() -> None:
    """Use the retained GitOps runtime without enabling ambient reporting channels."""
    config = ConfigParser()
    config.read(REPO_ROOT / "ansible/ansible.cfg")
    defaults = config["defaults"]
    assert defaults["roles_path"] == "/opt/abhaile/ansible/roles"
    assert defaults["stdout_callback"] == "default"
    assert "inventory" not in defaults
    assert "callbacks_enabled" not in defaults
    assert defaults["gathering"] == "explicit"
    assert "no_log" not in defaults
    assert not defaults.getboolean("keep_remote_files")
    assert not defaults.getboolean("collections_scan_sys_path")
    assert not config["diff"].getboolean("always")
    assert defaults["interpreter_python"] == "/opt/abhaile/.venv/bin/python"


def test_convergence_play_is_preflight_only_and_fail_closed() -> None:
    """Allow only read-only reporting and a terminal quarantine assertion."""
    playbook = yaml.safe_load(
        (REPO_ROOT / "ansible/playbooks/converge.yml").read_text(encoding="utf-8")
    )
    assert playbook[0]["hosts"] == "localhost"
    assert playbook[0]["connection"] == "local"
    assert playbook[0]["gather_facts"] is False
    assert playbook[0]["become"] is False
    tasks = playbook[0]["tasks"]
    modules = {key for task in tasks for key in task if key.startswith("ansible.builtin.")}
    assert modules <= {"ansible.builtin.assert", "ansible.builtin.debug"}
    assertions = [
        task["ansible.builtin.assert"] for task in tasks if "ansible.builtin.assert" in task
    ]
    assert assertions and any(assertion.get("that") is False for assertion in assertions)


def test_convergence_play_cannot_invoke_roles_or_mutation() -> None:
    """Keep role dispatch, commands, and mutation out of convergence."""
    text = (REPO_ROOT / "ansible/playbooks/converge.yml").read_text(encoding="utf-8")
    forbidden = ("roles:", "include_role", "command:", "shell:", "file:")
    assert all(value not in text for value in forbidden)
