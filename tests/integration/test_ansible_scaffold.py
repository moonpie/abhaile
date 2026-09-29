"""Validate the quarantined play through a real isolated Ansible loader."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _closed_environment(tmp_path: Path) -> dict[str, str]:
    """Build the fixed test analogue of the protected Ansible environment."""
    home = tmp_path / "home"
    temporary = tmp_path / "temporary"
    collections = tmp_path / "collections"
    plugins = tmp_path / "plugins"
    modules = tmp_path / "modules"
    module_utils = tmp_path / "module_utils"
    for path in (home, temporary, collections, plugins, modules, module_utils):
        path.mkdir()
    environment = {
        "PATH": str(Path(sys.executable).parent),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "ANSIBLE_CONFIG": str(REPO_ROOT / "ansible/ansible.cfg"),
        "ANSIBLE_ROLES_PATH": str(REPO_ROOT / "ansible/roles"),
        "ANSIBLE_COLLECTIONS_PATH": str(collections),
        "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "False",
        "ANSIBLE_INVENTORY_ENABLED": "host_list",
        "ANSIBLE_STDOUT_CALLBACK": "default",
        "ANSIBLE_LOAD_CALLBACK_PLUGINS": "False",
        "ANSIBLE_NOCOLOR": "True",
        "ANSIBLE_NO_LOG": "True",
        "ANSIBLE_DIFF_ALWAYS": "False",
        "ANSIBLE_KEEP_REMOTE_FILES": "False",
        "ANSIBLE_LOCAL_TEMP": str(temporary),
        "ANSIBLE_REMOTE_TEMP": str(temporary),
        "ANSIBLE_RETRY_FILES_ENABLED": "False",
        "ANSIBLE_CACHE_PLUGIN": "memory",
        "ANSIBLE_GATHERING": "explicit",
        "ANSIBLE_INTERPRETER_PYTHON": sys.executable,
        "ANSIBLE_LOG_PATH": os.devnull,
        "TMPDIR": str(temporary),
    }
    for plugin in (
        "ACTION",
        "BECOME",
        "CACHE",
        "CALLBACK",
        "CLICONF",
        "CONNECTION",
        "FILTER",
        "HTTPAPI",
        "INVENTORY",
        "LOOKUP",
        "NETCONF",
        "SHELL",
        "STRATEGY",
        "TERMINAL",
        "TEST",
        "VARS",
    ):
        environment[f"ANSIBLE_{plugin}_PLUGINS"] = str(plugins / plugin.lower())
    environment["ANSIBLE_LIBRARY"] = str(modules)
    environment["ANSIBLE_MODULE_UTILS"] = str(module_utils)
    return environment


def _ansible(
    module: str, arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one Ansible CLI module without caller Python or environment state."""
    return subprocess.run(
        (sys.executable, "-I", "-m", module, *arguments),
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.integration
def test_real_ansible_loader_and_syntax_are_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve builtin modules and syntax using only fixed admitted candidates."""
    specification = importlib.util.find_spec("ansible.cli.playbook")
    assert specification is not None and specification.loader is not None
    monkeypatch.setenv("ANSIBLE_INVENTORY", "/tmp/ambient-inventory")
    monkeypatch.setenv("ANSIBLE_CALLBACKS_ENABLED", "ambient.callback")
    environment = _closed_environment(tmp_path)

    configuration = _ansible("ansible.cli.config", ["dump", "--only-changed"], environment)
    assert configuration.returncode == 0, configuration.stderr
    assert f"CONFIG_FILE() = {REPO_ROOT / 'ansible/ansible.cfg'}" in configuration.stdout
    assert str(REPO_ROOT / "ansible/roles") in configuration.stdout
    assert str(tmp_path / "collections") in configuration.stdout
    assert "DEFAULT_HOST_LIST" not in configuration.stdout
    assert "CALLBACKS_ENABLED" not in configuration.stdout
    assert "/tmp/ambient-inventory" not in configuration.stdout + configuration.stderr
    assert "ambient.callback" not in configuration.stdout + configuration.stderr
    assert "/opt/abhaile" not in configuration.stdout + configuration.stderr

    inventory = _ansible("ansible.cli.inventory", ["-i", "localhost,", "--list"], environment)
    assert inventory.returncode == 0, inventory.stderr
    parsed_inventory = json.loads(inventory.stdout)
    assert parsed_inventory["all"]["children"] == ["ungrouped"]
    assert parsed_inventory["ungrouped"]["hosts"] == ["localhost"]
    assert parsed_inventory["_meta"]["hostvars"] == {}

    documentation = _ansible(
        "ansible.cli.doc",
        ["--json", "ansible.builtin.assert", "ansible.builtin.debug"],
        environment,
    )
    assert documentation.returncode == 0, documentation.stderr
    assert '"ansible.builtin.assert"' in documentation.stdout
    assert '"ansible.builtin.debug"' in documentation.stdout

    syntax = _ansible(
        "ansible.cli.playbook",
        [
            "--syntax-check",
            "-i",
            "localhost,",
            "--connection=local",
            str(REPO_ROOT / "ansible/playbooks/converge.yml"),
        ],
        environment,
    )
    assert syntax.returncode == 0, syntax.stderr
    assert "playbook:" in syntax.stdout
