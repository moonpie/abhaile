"""Exercise the direct systemd-networkd configuration role."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _file_entry(
    rendered_root: Path,
    *,
    kind: str,
    owner_ref: str,
    render_path: str,
    target_path: str,
    content: str,
) -> dict[str, object]:
    """Write one networkd source and return its manifest entry."""
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": target_path,
        "kind": kind,
        "owner_ref": owner_ref,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": None,
    }


def _entries(rendered_root: Path) -> list[dict[str, object]]:
    """Return a small complete networkd owner selection."""
    return [
        _file_entry(
            rendered_root,
            kind="networkd.netdev",
            owner_ref="iface:ipvlan-l2",
            render_path="system/etc/systemd/network/20-ipvlan-l2.netdev",
            target_path="/etc/systemd/network/20-ipvlan-l2.netdev",
            content="[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n",
        ),
        _file_entry(
            rendered_root,
            kind="networkd.network",
            owner_ref="iface:ipvlan-l2",
            render_path="system/etc/systemd/network/21-ipvlan-l2.network",
            target_path="/etc/systemd/network/21-ipvlan-l2.network",
            content="[Match]\nName=ipvlan-l2\n[Network]\nDHCP=no\n",
        ),
        {
            "render_path": "system/etc/systemd/network/21-ipvlan-l2.network.d",
            "target_path": "/etc/systemd/network/21-ipvlan-l2.network.d/",
            "kind": "networkd.dropin",
            "owner_ref": "iface:ipvlan-l2",
            "is_directory": True,
            "sha256": hashlib.sha256(b"").hexdigest(),
            "size": 0,
            "apply_hints": {"owner": "root", "group": "root", "mode": "0755"},
        },
        _file_entry(
            rendered_root,
            kind="networkd.dropin",
            owner_ref="iface:ipvlan-l2",
            render_path="system/etc/systemd/network/21-ipvlan-l2.network.d/200-example.conf",
            target_path="/etc/systemd/network/21-ipvlan-l2.network.d/200-example.conf",
            content="[Network]\nAddress=192.0.2.10/32\n",
        ),
    ]


def _run_contract(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
    cleanup_entries: list[dict[str, object]] | None = None,
) -> tuple[int, str, str]:
    """Run only the non-mutating networkd contract tasks."""
    playbook = tmp_path / "networkd.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test networkd configuration contract",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_networkd_entries": entries,
                        "abhaile_networkd_cleanup_entries": cleanup_entries or [],
                    },
                    "roles": ["networkd_config"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    environment_root = tmp_path / "env"
    environment_root.mkdir()
    result = _ansible(
        "ansible.cli.playbook",
        [
            "-i",
            "localhost,",
            "--connection=local",
            "--check",
            "--tags",
            "networkd_contract",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_networkd_contract_accepts_files_and_dropin_directory(tmp_path: Path) -> None:
    """Accept source-bound networkd files and their managed directory."""
    rendered = tmp_path / "rendered"

    code, stdout, stderr = _run_contract(tmp_path, rendered, _entries(rendered))

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_networkd_contract_accepts_ordinary_file_without_apply_hints(tmp_path: Path) -> None:
    """Accept the exact optional-hints shape emitted for an ordinary network file."""
    rendered = tmp_path / "rendered"
    entries = _entries(rendered)
    entries[1].pop("apply_hints")

    code, stdout, stderr = _run_contract(tmp_path, rendered, entries)

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_networkd_contract_accepts_cleanup_without_desired_entries(tmp_path: Path) -> None:
    """Allow recovery to remove a verified candidate-only network file."""
    rendered = tmp_path / "rendered"
    digest = hashlib.sha256(b"candidate\n").hexdigest()
    cleanup: list[dict[str, object]] = [
        {
            "target_path": "/etc/systemd/network/10-test0.network",
            "kind": "networkd.network",
            "owner_ref": "iface:test0",
            "candidate_sha256": digest,
            "live_sha256": digest,
        }
    ]

    code, stdout, stderr = _run_contract(tmp_path, rendered, [], cleanup)

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_networkd_contract_rejects_owner_filename_mismatch(tmp_path: Path) -> None:
    """Reject a network file whose numbered filename names another interface."""
    rendered = tmp_path / "rendered"
    entries = _entries(rendered)
    entries[1]["owner_ref"] = "iface:different"

    code, _stdout, _stderr = _run_contract(tmp_path, rendered, entries)

    assert code != 0


def test_networkd_runtime_uses_one_reload_and_manifest_order() -> None:
    """Keep publication ordered and runtime effects bounded to changed owners."""
    role_path = Path(__file__).resolve().parents[2] / "ansible/roles/networkd_config/tasks/main.yml"
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task["name"] for task in tasks]

    assert "Refuse existing networkd netdev definition changes" in names
    publish_index = names.index("Publish networkd entries in manifest order")
    enable_index = names.index("Enable and start the adopted networkd backend")
    reload_index = names.index("Reload networkd configuration once after publication")
    reconfigure_index = names.index("Reconfigure changed networkd owners in manifest order")
    assert publish_index < enable_index < reload_index < reconfigure_index

    publication = tasks[publish_index]
    assert publication["loop"] == "{{ abhaile_networkd_entries }}"
    assert publication["loop_control"]["loop_var"] == "abhaile_networkd_entry"

    reload_task = tasks[reload_index]
    assert reload_task["ansible.builtin.command"]["argv"] == [
        "/usr/bin/networkctl",
        "reload",
    ]
    reconfigure = tasks[reconfigure_index]
    assert reconfigure["loop"] == "{{ abhaile_changed_networkd_owners | unique }}"
    assert reconfigure["ansible.builtin.command"]["argv"][:2] == [
        "/usr/bin/networkctl",
        "reconfigure",
    ]


def test_networkd_refuses_implicit_legacy_backend_adoption() -> None:
    """Keep one-time backend migration outside recurring reconciliation."""
    role_path = Path(__file__).resolve().parents[2] / "ansible/roles/networkd_config/tasks/main.yml"
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    by_name = {task["name"]: task for task in tasks}

    inspection = by_name["Inspect legacy networking backend enablement"]
    assert inspection["ansible.builtin.command"]["argv"] == [
        "/usr/bin/systemctl",
        "is-enabled",
        "networking.service",
    ]
    refusal = by_name["Refuse implicit network backend adoption"]
    assert "abhaile_networkd_adoption" in refusal["ansible.builtin.assert"]["that"][0]
    enablement = by_name["Enable and start the adopted networkd backend"]
    assert enablement["ansible.builtin.systemd_service"] == {
        "name": "systemd-networkd.service",
        "enabled": True,
        "state": "started",
    }
    assert enablement["register"] == "abhaile_networkd_backend_activation"
    assert "abhaile_networkd_early_restore" in enablement["when"]


def test_networkd_backend_repair_requires_local_acceptance() -> None:
    """Probe the management path when networkd activation repairs drift."""
    role_path = (
        Path(__file__).resolve().parents[2] / "ansible/roles/local_acceptance/tasks/main.yml"
    )
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    canonical_intent = next(
        task
        for task in tasks
        if task["name"] == "Require the canonical network intent for a changed network"
    )

    requirement = canonical_intent["vars"]["network_acceptance_required"]
    assert "abhaile_networkd_backend_activation.changed | default(false)" in requirement
    assert "abhaile_changed_networkd_owners" in requirement
