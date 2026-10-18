"""Exercise the owner-scoped Caddy configuration Ansible role."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(rendered_root: Path) -> dict[str, object]:
    """Write one Caddy candidate and return its manifest entry."""
    content = ':80 {\n    respond "ok"\n}\n'
    render_path = "services/caddy-internal/srv/caddy/internal/Caddyfile"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": "/srv/caddy/internal/Caddyfile",
        "kind": "caddy.config",
        "owner_ref": "caddy:internal",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {"contributors": ["service:example"]},
    }


def _run_contract(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
) -> tuple[int, str, str]:
    """Run only the non-mutating Caddy contract tasks."""
    playbook = tmp_path / "caddy.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test Caddy configuration contract",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_caddy_config_entries": entries,
                    },
                    "roles": ["caddy_config"],
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
            "caddy_contract",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_caddy_contract_accepts_exact_segment(tmp_path: Path) -> None:
    """Accept one source-bound Caddy segment without runtime mutation."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered)

    code, stdout, stderr = _run_contract(tmp_path, rendered, [entry])

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_caddy_contract_rejects_target_segment_mismatch(tmp_path: Path) -> None:
    """Reject an owner whose fixed live path names another segment."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered)
    entry["target_path"] = "/srv/caddy/dmz/Caddyfile"

    code, _stdout, _stderr = _run_contract(tmp_path, rendered, [entry])

    assert code != 0


def test_caddy_runtime_validates_before_publication_and_restart() -> None:
    """Validate first, then restart so a file bind mount observes the new inode."""
    role_path = Path(__file__).resolve().parents[2] / "ansible/roles/caddy_config/tasks/main.yml"
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task["name"] for task in tasks]

    validate_index = names.index("Validate candidate with the installed Caddy runtime")
    publish_index = names.index("Publish Caddy configuration")
    restart_index = names.index("Restart Caddy after changed configuration")
    assert validate_index < publish_index < restart_index

    validate = tasks[validate_index]["ansible.builtin.command"]
    assert validate["argv"] == [
        "/usr/bin/podman",
        "exec",
        "--interactive",
        "systemd-caddy-{{ caddy_segment }}",
        "/usr/bin/caddy",
        "validate",
        "--config",
        "-",
        "--adapter",
        "caddyfile",
    ]
    assert validate["stdin"] == "{{ abhaile_caddy_candidate.content | b64decode }}"
    assert validate["stdin_add_newline"] is False
    assert tasks[validate_index]["check_mode"] is False
    require_container = next(
        task
        for task in tasks
        if task.get("name") == "Require the existing Caddy container for candidate validation"
    )
    assert require_container["check_mode"] is False
    restart = tasks[restart_index]
    assert restart["ansible.builtin.systemd_service"] == {
        "name": "caddy-{{ caddy_segment }}.service",
        "state": "restarted",
    }
    assert "abhaile_caddy_publication.changed" in restart["when"]
