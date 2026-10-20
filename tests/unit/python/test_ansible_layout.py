"""Tests for the quarantined Ansible migration scaffold."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

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
