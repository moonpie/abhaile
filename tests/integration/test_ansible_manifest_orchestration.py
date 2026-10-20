"""Exercise fixed manifest-v1 selection and direct-role orchestration."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path

import pytest
import yaml

from abhaile.cli.render import load_and_validate, render_host
from abhaile.utils.config import clear_config_cache
from abhaile.utils.paths import load_paths
from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(kind: str, owner: str, *, rootless: bool | None = None) -> dict[str, object]:
    """Return the minimum selection-time manifest entry."""
    entry: dict[str, object] = {"kind": kind, "owner_ref": owner}
    if rootless is not None:
        entry["apply_hints"] = {"rootless": rootless}
    return entry


def _run_selection(
    tmp_path: Path,
    entries: list[dict[str, object]],
    *,
    manifest_host: str = "test-host",
    expected_host: str = "test-host",
    include_owners: bool = True,
    cleanup_entries: list[dict[str, object]] | None = None,
) -> tuple[int, str, str]:
    """Run only the production orchestration selection contract."""
    rendered = tmp_path / "rendered"
    rendered.mkdir(parents=True)
    manifest: dict[str, object] = {
        "version": "1",
        "host": manifest_host,
        "entries": entries,
    }
    if include_owners:
        manifest["owners"] = {}
    (rendered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return _run_existing_selection(
        tmp_path,
        rendered,
        expected_host,
        cleanup_entries=cleanup_entries,
    )


def _run_existing_selection(
    tmp_path: Path,
    rendered: Path,
    expected_host: str,
    *,
    cleanup_entries: list[dict[str, object]] | None = None,
) -> tuple[int, str, str]:
    """Run selection against an existing rendered manifest."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    playbook = tmp_path / "selection.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test manifest orchestration selection",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered),
                        "abhaile_expected_host": expected_host,
                        "abhaile_candidate_cleanup_entries": cleanup_entries or [],
                    },
                    "roles": ["manifest_orchestration"],
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
            "--tags",
            "manifest_selection",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_manifest_selection_covers_every_direct_family(tmp_path: Path) -> None:
    """Partition every supported kind exactly once without invoking mutation roles."""
    entries: list[dict[str, object]] = [
        _entry("service.directory", "service:example"),
        {
            **_entry("host.sysusers", "host-users:test-host"),
            "target_path": "/etc/sysusers.d/abhaile.conf",
        },
        _entry("systemd.unit", "unit:example.service"),
        _entry("service.config", "service:example"),
        _entry("service.env", "service:example"),
        _entry("vault.config", "service:vault-agent"),
        _entry("quadlet.container", "unit:vault-agent.service", rootless=True),
        _entry("quadlet.container", "unit:example.service", rootless=False),
        _entry("caddy.config", "service:caddy-internal"),
        _entry("coredns.config", "dns:coredns"),
        _entry("networkd.network", "iface:eth0"),
    ]

    code, stdout, stderr = _run_selection(tmp_path, entries)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_rejects_unknown_kind(tmp_path: Path) -> None:
    """Refuse incomplete family coverage before invoking any mutation role."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [_entry("unknown.resource", "unknown:example")],
    )

    assert code != 0


@pytest.mark.integration
def test_manifest_selection_rejects_wrong_host(tmp_path: Path) -> None:
    """Bind orchestration to the caller-selected host manifest."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [],
        manifest_host="other-host",
    )

    assert code != 0


@pytest.mark.integration
def test_manifest_selection_accepts_omitted_empty_owners(tmp_path: Path) -> None:
    """Honor the canonical renderer's optional empty owners field."""
    code, stdout, stderr = _run_selection(tmp_path, [], include_owners=False)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_accepts_supported_service_cleanup(tmp_path: Path) -> None:
    """Route service cleanup through the existing owner-scoped role boundary."""
    code, stdout, stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("service.config", "service:obsolete")],
    )

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_accepts_supported_coredns_zone_cleanup(tmp_path: Path) -> None:
    """Route candidate-only zones through the existing CoreDNS role boundary."""
    code, stdout, stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("coredns.zone", "dns-zone:obsolete.test")],
    )

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_accepts_supported_rootful_unit_cleanup(tmp_path: Path) -> None:
    """Route ordinary rootful unit cleanup through its existing family role."""
    code, stdout, stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("systemd.unit", "unit:obsolete.service")],
    )

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_reserves_runner_units_from_ordinary_convergence(
    tmp_path: Path,
) -> None:
    """Count the fixed runner inventory without passing it to a mutation role."""
    entries: list[dict[str, object]] = [
        {
            "kind": "systemd.unit",
            "owner_ref": f"unit:{unit_name}",
            "target_path": f"/etc/systemd/system/{unit_name}",
        }
        for unit_name in (
            "abhaile-network-restore.service",
            "abhaile-runner.service",
            "abhaile-runner.timer",
        )
    ]

    code, stdout, stderr = _run_selection(tmp_path, entries)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_rejects_spoofed_reserved_runner_unit(tmp_path: Path) -> None:
    """Require a reserved owner to use its one fixed system unit target."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [
            {
                "kind": "systemd.unit",
                "owner_ref": "unit:abhaile-runner.service",
                "target_path": "/tmp/abhaile-runner.service",
            }
        ],
    )

    assert code != 0


@pytest.mark.integration
def test_manifest_selection_rejects_rootful_dropin_cleanup(tmp_path: Path) -> None:
    """Keep parent-aware drop-in removal fail-closed."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("systemd.dropin", "unit:example.service")],
    )

    assert code != 0


@pytest.mark.integration
def test_manifest_selection_rejects_coredns_corefile_cleanup(tmp_path: Path) -> None:
    """Keep removal of the required CoreDNS runtime configuration fail-closed."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("coredns.config", "dns:coredns")],
    )

    assert code != 0


@pytest.mark.integration
def test_manifest_selection_accepts_rootful_quadlet_cleanup(tmp_path: Path) -> None:
    """Route rootful Quadlet cleanup through its existing family role."""
    code, stdout, stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("quadlet.container", "unit:obsolete.service", rootless=False)],
    )

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_manifest_selection_rejects_rootless_quadlet_cleanup(tmp_path: Path) -> None:
    """Keep rootless candidate removal outside the supported cleanup boundary."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [],
        cleanup_entries=[_entry("quadlet.container", "unit:obsolete.service", rootless=True)],
    )

    assert code != 0


@pytest.mark.integration
def test_manifest_selection_rejects_spoofed_reserved_host_access_target(tmp_path: Path) -> None:
    """Treat host identity and access artifacts as fixed bootstrap-owned inventory."""
    code, _stdout, _stderr = _run_selection(
        tmp_path,
        [
            {
                **_entry("host.sudoers", "host-sudoers:test-host"),
                "target_path": "/tmp/abhaile",
            }
        ],
    )

    assert code != 0


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("host", ["deimos", "phobos"])
def test_manifest_selection_covers_current_host_render(
    host: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partition every entry emitted by each current real host render."""
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr("abhaile.cli.render.validate_dns_serials", lambda *a, **kw: None)
    clear_config_cache()
    paths = load_paths(repo_root)
    validated = load_and_validate(repo_root, paths)
    manifest_path = render_host(
        host,
        output_override=tmp_path / "output",
        paths=paths,
        all_mode=False,
        repo_root=repo_root,
        mapping=validated.mapping,
        network=validated.network,
        host_services=validated.host_services,
    )

    code, stdout, stderr = _run_existing_selection(
        tmp_path / "ansible",
        manifest_path.parent,
        host,
    )

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_reconcile_check_mode_supports_new_managed_parent_and_file(tmp_path: Path) -> None:
    """Validate a new managed directory and child file without creating either."""
    rendered = tmp_path / "rendered"
    source = rendered / "services/example/config.yml"
    source.parent.mkdir(parents=True)
    content = b"value=true\n"
    source.write_bytes(content)
    target_root = tmp_path / "managed-service"
    target = target_root / "config.yml"
    manifest = {
        "version": "1",
        "host": "test-host",
        "entries": [
            {
                "render_path": "services/example/data",
                "target_path": str(target_root),
                "kind": "service.directory",
                "owner_ref": "service:example",
                "sha256": "0" * 64,
                "size": 0,
                "is_directory": True,
                "apply_hints": {
                    "owner": os.getuid(),
                    "group": os.getgid(),
                    "mode": "0750",
                },
            },
            {
                "render_path": "services/example/config.yml",
                "target_path": str(target),
                "kind": "service.config",
                "owner_ref": "service:example",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "apply_hints": None,
            },
        ],
    }
    (rendered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    repo_root = Path(__file__).resolve().parents[2]
    result = _ansible(
        "ansible.cli.playbook",
        [
            "-i",
            "localhost,",
            "--connection=local",
            "--check",
            "-e",
            json.dumps(
                {
                    "abhaile_rendered_root": str(rendered),
                    "abhaile_config_root": str(repo_root / "config"),
                    "abhaile_expected_host": "test-host",
                    "abhaile_candidate_cleanup_entries": [],
                }
            ),
            str(repo_root / "ansible/playbooks/reconcile.yml"),
        ],
        _closed_environment(environment_root),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=2" in result.stdout
    assert not target_root.exists()


def test_manifest_orchestration_uses_fixed_dependency_order() -> None:
    """Keep direct family calls explicit and production convergence quarantined."""
    role_path = Path("ansible/roles/manifest_orchestration/tasks/main.yml")
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    selection = next(
        task for task in tasks if task["name"] == "Select fixed manifest resource families"
    )
    assert selection["ansible.builtin.set_fact"]["abhaile_rootful_quadlet_owners"] == (
        "{{ abhaile_manifest.owners | default({}) }}"
    )
    calls = [
        task.get("ansible.builtin.include_role", {}).get("name")
        or task.get("ansible.builtin.include_tasks")
        for task in tasks
        if "ansible.builtin.include_role" in task or "ansible.builtin.include_tasks" in task
    ]

    assert calls == [
        "managed_directories",
        "rootful_unit_preflight",
        "rootful_systemd",
        "service_owner.yml",
        "vault_agent_config",
        "rootful_quadlet_files",
        "caddy_owner.yml",
        "coredns_config",
        "networkd_config",
        "local_acceptance",
    ]
