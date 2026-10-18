"""Check the explicit one-time network-backend adoption playbook."""

from pathlib import Path

import yaml


def test_adoption_orders_validation_before_legacy_disablement() -> None:
    """Retire ifupdown only after networkd activation and local acceptance."""
    playbook_path = Path(__file__).resolve().parents[2] / "ansible/playbooks/adopt-networkd.yml"
    play = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))[0]
    tasks = play["tasks"]
    names = [task["name"] for task in tasks]

    assert names == [
        "Install recovery before network backend adoption",
        "Publish and activate the networkd backend",
        "Verify local management-path acceptance",
        "Disable the legacy backend for the next boot",
    ]
    assert tasks[0]["ansible.builtin.include_role"]["name"] == "network_restore_install"
    network_role = tasks[1]
    assert network_role["ansible.builtin.include_role"]["name"] == "networkd_config"
    assert network_role["vars"]["abhaile_networkd_adoption"] is True
    assert tasks[2]["ansible.builtin.include_role"]["name"] == "local_acceptance"
    assert tasks[2]["vars"]["abhaile_network_acceptance_required"] is True
    assert tasks[3]["ansible.builtin.systemd_service"] == {
        "name": "networking.service",
        "enabled": False,
    }
    assert tasks[3]["when"] == "not ansible_check_mode"


def test_adoption_requires_explicit_live_authorization() -> None:
    """Keep the one-time cutover dry-run by default."""
    playbook_path = Path(__file__).resolve().parents[2] / "ansible/playbooks/adopt-networkd.yml"
    play = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))[0]
    gate = play["pre_tasks"][0]["ansible.builtin.assert"]["that"]

    assert "abhaile_live_apply is boolean" in gate
    assert "ansible_check_mode or abhaile_live_apply" in gate


def test_adoption_selects_only_the_fixed_network_restore_unit() -> None:
    """Bind adoption recovery installation to the rendered fixed unit."""
    playbook_path = Path(__file__).resolve().parents[2] / "ansible/playbooks/adopt-networkd.yml"
    play = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))[0]
    selection = next(
        task for task in play["pre_tasks"] if task["name"] == "Select networkd entries for adoption"
    )["ansible.builtin.set_fact"]["abhaile_network_restore_entries"]

    assert "selectattr('target_path', 'equalto'" in selection
    assert "/etc/systemd/system/abhaile-network-restore.service" in selection


def test_restore_install_requires_baseline_before_publication_and_enablement() -> None:
    """Install recovery only after proving a valid last-successful baseline."""
    role_path = (
        Path(__file__).resolve().parents[2] / "ansible/roles/network_restore_install/tasks/main.yml"
    )
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task["name"] for task in tasks]

    assert names.index("Require a valid recovery baseline before installation") < names.index(
        "Publish the network restore unit"
    )
    assert names.index("Publish the network restore unit") < names.index(
        "Enable pre-networkd recovery without starting it"
    )
    enable = next(
        task for task in tasks if task["name"] == "Enable pre-networkd recovery without starting it"
    )
    assert enable["ansible.builtin.systemd_service"] == {
        "name": "abhaile-network-restore.service",
        "enabled": True,
    }
    assert "state" not in enable["ansible.builtin.systemd_service"]


def test_restore_install_verifies_effective_dependency_and_ordering() -> None:
    """Verify adoption inspects the installed dependency graph, not only source text."""
    role_path = (
        Path(__file__).resolve().parents[2] / "ansible/roles/network_restore_install/tasks/main.yml"
    )
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task["name"] for task in tasks]

    assert "Inspect the effective recovery dependency" in names
    assert "Read the effective networkd requirements" in names
    assert "Read the effective restore ordering" in names
    assert "Verify effective restore dependency and boot ordering" in names
