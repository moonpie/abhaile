"""Exercise the owner-scoped CoreDNS configuration Ansible role."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(
    rendered_root: Path,
    *,
    kind: str,
    owner_ref: str,
    render_path: str,
    target_path: str,
    content: str,
    apply_hints: dict[str, object],
) -> dict[str, object]:
    """Write one candidate and return its CoreDNS manifest entry."""
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
        "apply_hints": apply_hints,
    }


def _entries(rendered_root: Path) -> list[dict[str, object]]:
    """Return one complete isolated CoreDNS selection."""
    return [
        _entry(
            rendered_root,
            kind="coredns.config",
            owner_ref="dns:coredns",
            render_path="services/coredns/etc/coredns/Corefile",
            target_path="/etc/coredns/Corefile",
            content="example.test:53 {\n    file /etc/coredns/zones/example.test.zone\n}\n",
            apply_hints={"restart_unit": None},
        ),
        _entry(
            rendered_root,
            kind="coredns.zone",
            owner_ref="dns-zone:example.test",
            render_path="services/coredns/etc/coredns/zones/example.test.zone",
            target_path="/etc/coredns/zones/example.test.zone",
            content="$ORIGIN example.test.\n@ 60 IN SOA ns hostmaster 1 60 60 60 60\n",
            apply_hints={"reload_mode": "zones-service"},
        ),
    ]


def _run_contract(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
    *,
    cleanup_entries: list[dict[str, object]] | None = None,
) -> tuple[int, str, str]:
    """Run only the non-mutating CoreDNS contract tasks."""
    playbook = tmp_path / "coredns.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test CoreDNS configuration contract",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_coredns_entries": entries,
                        "abhaile_coredns_cleanup_entries": cleanup_entries or [],
                    },
                    "roles": ["coredns_config"],
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
            "coredns_contract",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_coredns_contract_accepts_corefile_and_zone(tmp_path: Path) -> None:
    """Accept one exact Corefile and its source-bound zone selection."""
    rendered = tmp_path / "rendered"

    code, stdout, stderr = _run_contract(tmp_path, rendered, _entries(rendered))

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_coredns_contract_rejects_zone_owner_target_mismatch(tmp_path: Path) -> None:
    """Reject a zone whose owner does not bind its fixed live path."""
    rendered = tmp_path / "rendered"
    entries = _entries(rendered)
    entries[1]["target_path"] = "/etc/coredns/zones/different.test.zone"

    code, _stdout, _stderr = _run_contract(tmp_path, rendered, entries)

    assert code != 0


@pytest.mark.integration
def test_coredns_contract_accepts_matching_candidate_only_zone_cleanup(tmp_path: Path) -> None:
    """Accept only complete identity evidence for a closed managed zone path."""
    rendered = tmp_path / "rendered"
    digest = hashlib.sha256(b"obsolete zone\n").hexdigest()
    cleanup: dict[str, object] = {
        "kind": "coredns.zone",
        "owner_ref": "dns-zone:obsolete.test",
        "target_path": "/etc/coredns/zones/obsolete.test.zone",
        "candidate_sha256": digest,
        "live_sha256": digest,
        "apply_hints": {"reload_mode": "zones-service"},
    }

    code, stdout, stderr = _run_contract(
        tmp_path,
        rendered,
        _entries(rendered),
        cleanup_entries=[cleanup],
    )

    assert code == 0, stdout + stderr


@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "coredns.config"),
        ("target_path", "/etc/coredns/Corefile"),
        ("live_sha256", "0" * 64),
    ],
)
def test_coredns_contract_rejects_unsafe_candidate_cleanup(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Reject unsupported families, paths, and non-matching live evidence."""
    rendered = tmp_path / "rendered"
    digest = hashlib.sha256(b"obsolete zone\n").hexdigest()
    cleanup: dict[str, object] = {
        "kind": "coredns.zone",
        "owner_ref": "dns-zone:obsolete.test",
        "target_path": "/etc/coredns/zones/obsolete.test.zone",
        "candidate_sha256": digest,
        "live_sha256": digest,
        "apply_hints": {"reload_mode": "zones-service"},
    }
    cleanup[field] = value

    code, _stdout, _stderr = _run_contract(
        tmp_path,
        rendered,
        _entries(rendered),
        cleanup_entries=[cleanup],
    )

    assert code != 0


def test_coredns_runtime_validates_before_one_watcher_safe_batch() -> None:
    """Keep fixed zone validation before publication and restore the watcher."""
    role_path = Path(__file__).resolve().parents[2] / "ansible/roles/coredns_config/tasks/main.yml"
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task["name"] for task in tasks]

    validate_index = names.index("Validate candidate CoreDNS zones")
    inspect_index = names.index("Inspect live CoreDNS targets before watcher coordination")
    batch_index = names.index("Publish CoreDNS configuration as one watcher-safe batch")
    assert validate_index < inspect_index < batch_index
    assert tasks[validate_index]["ansible.builtin.command"]["argv"][:1] == [
        "/usr/bin/named-checkzone"
    ]

    batch = next(
        task
        for task in tasks
        if task.get("name") == "Publish CoreDNS configuration as one watcher-safe batch"
    )
    block_names = [task["name"] for task in batch["block"]]
    assert block_names == [
        "Stop the CoreDNS zone watcher",
        "Recheck candidate-only CoreDNS zones immediately before removal",
        "Refuse changed or redirected candidate-only CoreDNS zones",
        "Remove matching candidate-only CoreDNS zones",
        "Publish CoreDNS configuration and zones",
        "Record changed CoreDNS resource families",
        "Restart CoreDNS after Corefile publication",
        "Reload CoreDNS after zone-only publication",
        "Verify CoreDNS is active after changed publication",
    ]
    assert batch["always"][0]["name"] == "Restore the CoreDNS zone watcher"
    assert batch["always"][0]["ansible.builtin.systemd_service"]["state"] == "started"
    assert "abhaile_coredns_batch_changed" in batch["block"][0]["when"]
    assert "abhaile_coredns_batch_changed" in batch["always"][0]["when"]
