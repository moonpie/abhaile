"""Exercise the bounded local acceptance Ansible role."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _run_role(
    tmp_path: Path,
    *,
    changed_owners: object,
    acceptance_required: bool = False,
    backend_changed: bool | None = None,
    network: dict[str, object] | None = None,
    host: dict[str, object] | None = None,
    check: bool = False,
) -> tuple[int, str, str]:
    """Run the production acceptance role in an isolated play."""
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True)
    if network is not None:
        (config_root / "network.yaml").write_text(
            yaml.safe_dump(network, sort_keys=False),
            encoding="utf-8",
        )
    if host is not None:
        host_root = config_root / "hosts/deimos"
        host_root.mkdir(parents=True)
        (host_root / "host.yaml").write_text(
            yaml.safe_dump(host, sort_keys=False),
            encoding="utf-8",
        )
    playbook = tmp_path / "acceptance.yml"
    role_vars: dict[str, object] = {
        "abhaile_changed_networkd_owners": changed_owners,
        "abhaile_network_acceptance_required": acceptance_required,
        "abhaile_config_root": str(config_root),
        "abhaile_expected_host": "deimos",
    }
    if backend_changed is not None:
        role_vars["abhaile_networkd_backend_activation"] = {"changed": backend_changed}
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test local acceptance",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": role_vars,
                    "roles": ["local_acceptance"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    environment_root = tmp_path / "env"
    environment_root.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    arguments.append(str(playbook))
    result = _ansible("ansible.cli.playbook", arguments, _closed_environment(environment_root))
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_local_acceptance_skips_network_probe_without_network_change(tmp_path: Path) -> None:
    """Require no extra health framework when family roles report no network change."""
    code, stdout, stderr = _run_role(tmp_path, changed_owners=[])

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_local_acceptance_validates_unchanged_network_when_required(tmp_path: Path) -> None:
    """Validate adoption intent even when rendered network files are unchanged."""
    network: dict[str, object] = {
        "vlans": {"services": {"gateway": "192.0.2.1"}},
        "hosts": {
            "deimos": {
                "interfaces": {"eth0": {"address": "192.0.2.10/24"}},
            }
        },
    }
    code, stdout, stderr = _run_role(
        tmp_path,
        changed_owners=[],
        acceptance_required=True,
        network=network,
        host={"name": "deimos", "physical_device": "eth0"},
        check=True,
    )

    assert code == 0, stdout + stderr
    assert "Require the canonical management interface online" in stdout


@pytest.mark.integration
def test_local_acceptance_validates_networkd_backend_repair(tmp_path: Path) -> None:
    """Validate the management path when service repair is the only change."""
    network: dict[str, object] = {
        "vlans": {"services": {"gateway": "192.0.2.1"}},
        "hosts": {
            "deimos": {
                "interfaces": {"eth0": {"address": "192.0.2.10/24"}},
            }
        },
    }
    code, stdout, stderr = _run_role(
        tmp_path,
        changed_owners=[],
        backend_changed=True,
        network=network,
        host={"name": "deimos", "physical_device": "eth0"},
        check=True,
    )

    assert code == 0, stdout + stderr
    assert "Require the canonical management interface online" in stdout
    assert "Resolve the canonical management route" in stdout


@pytest.mark.integration
def test_local_acceptance_validates_gateway_in_check_mode(tmp_path: Path) -> None:
    """Validate canonical gateway intent without probing before mutation."""
    network: dict[str, object] = {
        "vlans": {"services": {"gateway": "192.0.2.1"}},
        "hosts": {
            "deimos": {
                "interfaces": {"eth0": {"address": "192.0.2.10/24"}},
            }
        },
    }
    code, stdout, stderr = _run_role(
        tmp_path,
        changed_owners=["iface:eth0"],
        network=network,
        host={"name": "deimos", "physical_device": "eth0"},
        check=True,
    )

    assert code == 0, stdout + stderr
    assert "Require the canonical management interface online" in stdout
    assert "Resolve the canonical management route" in stdout
    assert stdout.count("skipping") >= 2


@pytest.mark.integration
def test_local_acceptance_rejects_missing_gateway(tmp_path: Path) -> None:
    """Treat unavailable required network evidence as failure before probing."""
    code, _stdout, _stderr = _run_role(
        tmp_path,
        changed_owners=["iface:eth0"],
        network={"vlans": {"services": {}}, "hosts": {}},
        host={"name": "deimos", "physical_device": "eth0"},
        check=True,
    )

    assert code != 0


def test_local_acceptance_uses_fixed_local_management_path_checks() -> None:
    """Keep the commit gate to networkd state and structured route selection."""
    tasks = yaml.safe_load(
        Path("ansible/roles/local_acceptance/tasks/main.yml").read_text(encoding="utf-8")
    )
    command_tasks = [task for task in tasks if "ansible.builtin.command" in task]

    assert len(command_tasks) == 2
    assert command_tasks[0]["ansible.builtin.command"]["argv"] == [
        "/usr/lib/systemd/systemd-networkd-wait-online",
        "--interface={{ abhaile_acceptance_host.physical_device }}",
        "--timeout=3s",
    ]
    assert command_tasks[1]["ansible.builtin.command"]["argv"] == [
        "/usr/sbin/ip",
        "-json",
        "route",
        "get",
        "{{ abhaile_acceptance_network.vlans.services.gateway }}",
        "from",
        "{{ abhaile_management_address }}",
    ]
    assert all("not ansible_check_mode" in task["when"] for task in command_tasks)


@pytest.mark.integration
def test_local_acceptance_rejects_missing_physical_interface(tmp_path: Path) -> None:
    """Fail closed when host and network intent do not identify one management path."""
    code, _stdout, _stderr = _run_role(
        tmp_path,
        changed_owners=["iface:eth0"],
        network={
            "vlans": {"services": {"gateway": "192.0.2.1"}},
            "hosts": {"deimos": {"interfaces": {}}},
        },
        host={"name": "deimos", "physical_device": "eth0"},
        check=True,
    )

    assert code != 0
