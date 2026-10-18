"""Exercise the closed Vault Agent configuration Ansible role."""

from __future__ import annotations

import hashlib
import os
import pwd
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(
    rendered_root: Path,
    target: Path,
    *,
    kind: str,
    content: str,
    user: str,
) -> dict[str, object]:
    """Write one Vault source and return its selected manifest entry."""
    render_path = f"services/vault-agent/{target.name}"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": str(target),
        "kind": kind,
        "owner_ref": "service:vault-agent",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {
            "podman_user": user,
            "restart_mode": "restart",
            "rootless": True,
            "write_order": "before-config" if kind == "vault.template" else "after-templates",
        },
    }


def _quadlet_entry(
    rendered_root: Path,
    target: Path,
    *,
    kind: str,
    owner_ref: str,
    content: str,
    user: str,
) -> dict[str, object]:
    """Write one Vault Agent rootless Quadlet source."""
    render_path = f"services/vault-agent/{target.name}"
    source = rendered_root / render_path
    source.write_text(content, encoding="utf-8")
    encoded = content.encode()
    return {
        "render_path": render_path,
        "target_path": str(target),
        "kind": kind,
        "owner_ref": owner_ref,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {"podman_user": user, "rootless": True, "shared": False},
    }


def _write_playbook(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
    quadlet_entries: list[dict[str, object]],
    runtime_home: Path,
    *,
    managed_directory_targets: list[Path] | None = None,
) -> Path:
    """Write an isolated localhost play invoking the production role."""
    playbook = tmp_path / "vault-agent-config.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test Vault Agent configuration",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_vault_agent_entries": entries,
                        "abhaile_vault_agent_quadlet_entries": quadlet_entries,
                        "abhaile_vault_agent_home": str(runtime_home),
                        "abhaile_vault_agent_managed_directory_targets": [
                            str(path) for path in managed_directory_targets or []
                        ],
                    },
                    "roles": ["vault_agent_config"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return playbook


def _run_playbook(tmp_path: Path, playbook: Path, *, check: bool = False) -> tuple[int, str, str]:
    """Run the isolated role play and return its result fields."""
    tmp_path.mkdir(parents=True)
    environment_root = tmp_path / "env"
    environment_root.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    arguments.append(str(playbook))
    result = _ansible(
        "ansible.cli.playbook",
        arguments,
        _closed_environment(environment_root),
        timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


def _entries(
    tmp_path: Path,
) -> tuple[Path, list[dict[str, object]], list[dict[str, object]], Path]:
    """Return one complete Vault Agent owner selection."""
    rendered = tmp_path / "rendered"
    target_root = tmp_path / "vault-agent"
    target_root.mkdir()
    user = pwd.getpwuid(os.getuid()).pw_name
    config_entries = [
        _entry(
            rendered,
            target_root / "ready.ctmpl",
            kind="vault.template",
            content='{{ with secret "secret/ready" }}ready{{ end }}\n',
            user=user,
        ),
        _entry(
            rendered,
            target_root / "config.hcl",
            kind="vault.config",
            content='vault { address = "http://vault.example" }\n',
            user=user,
        ),
    ]
    runtime_home = tmp_path / "home"
    quadlet_root = runtime_home / ".config" / "containers" / "systemd"
    quadlet_root.mkdir(parents=True)
    quadlet_root.chmod(0o700)
    volumes = [
        ("host-certs", "/etc/ssl/certs"),
        ("vault-agent-out", str(target_root / "out")),
        ("vault-agent-run", str(target_root / "run")),
        ("vault-agent-templates", str(target_root / "templates")),
    ]
    quadlets = [
        _quadlet_entry(
            rendered,
            quadlet_root / f"{name}.volume",
            kind="quadlet.volume",
            owner_ref=f"unit:{name}-volume.service",
            content=f"[Volume]\nDevice={device}\nOptions=bind\n",
            user=user,
        )
        for name, device in volumes
    ]
    quadlets.append(
        _quadlet_entry(
            rendered,
            quadlet_root / "vault-agent.container",
            kind="quadlet.container",
            owner_ref="unit:vault-agent.service",
            content=(
                "[Container]\n"
                "Image=docker.io/hashicorp/vault:1.21.4\n"
                "Volume=vault-agent-out.volume:/agent/out\n"
                "Volume=vault-agent-run.volume:/agent/run\n"
                "Volume=vault-agent-templates.volume:/agent/templates\n"
                "Volume=host-certs.volume:/etc/ssl/certs:ro\n"
                "Exec=version\n\n"
                "[Install]\nWantedBy=default.target\n"
            ),
            user=user,
        )
    )
    return rendered, config_entries, quadlets, runtime_home


@pytest.mark.integration
def test_vault_agent_unchanged_files_report_no_check_mode_drift(tmp_path: Path) -> None:
    """Report an exact owner selection unchanged while check mode skips runtime repair."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    for entry in entries:
        source = rendered / str(entry["render_path"])
        target = Path(str(entry["target_path"]))
        target.write_bytes(source.read_bytes())
        target.chmod(0o644)
    for entry in quadlets:
        source = rendered / str(entry["render_path"])
        target = Path(str(entry["target_path"]))
        target.write_bytes(source.read_bytes())
        target.chmod(0o644)
    playbook = _write_playbook(tmp_path, rendered, entries, quadlets, runtime_home)

    code, stdout, stderr = _run_playbook(tmp_path / "unchanged", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_vault_agent_check_mode_preserves_order_without_restart(tmp_path: Path) -> None:
    """Order template before config publication without writing or restarting."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    playbook = _write_playbook(tmp_path, rendered, entries, quadlets, runtime_home)

    code, stdout, stderr = _run_playbook(tmp_path / "check", playbook, check=True)

    assert code == 0, stdout + stderr
    assert stdout.index("Publish Vault Agent templates") < stdout.index(
        "Publish Vault Agent configuration after templates"
    )
    assert not any(Path(str(entry["target_path"])).exists() for entry in entries)


@pytest.mark.integration
def test_vault_agent_check_mode_accepts_parent_implied_by_managed_child(
    tmp_path: Path,
) -> None:
    """Model the ancestor that native directory creation will create in live mode."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    target_root = Path(str(entries[0]["target_path"])).parent
    for entry in entries:
        Path(str(entry["target_path"])).unlink(missing_ok=True)
    target_root.rmdir()
    quadlet_root = Path(str(quadlets[0]["target_path"])).parent
    for entry in quadlets:
        Path(str(entry["target_path"])).unlink(missing_ok=True)
    quadlet_root.rmdir()
    playbook = _write_playbook(
        tmp_path,
        rendered,
        entries,
        quadlets,
        runtime_home,
        managed_directory_targets=[target_root / "templates"],
    )

    code, stdout, stderr = _run_playbook(tmp_path / "absent-parents", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=0" not in stdout
    assert not target_root.exists()
    assert not quadlet_root.exists()


@pytest.mark.integration
def test_vault_agent_check_mode_rejects_absent_unmanaged_parent(tmp_path: Path) -> None:
    """Reject an absent parent unrelated to every exact managed directory."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    target_root = Path(str(entries[0]["target_path"])).parent
    for entry in entries:
        Path(str(entry["target_path"])).unlink(missing_ok=True)
    target_root.rmdir()
    playbook = _write_playbook(
        tmp_path,
        rendered,
        entries,
        quadlets,
        runtime_home,
        managed_directory_targets=[tmp_path / "unrelated" / "templates"],
    )

    code, _stdout, _stderr = _run_playbook(tmp_path / "unmanaged-parent", playbook, check=True)

    assert code != 0
    assert not target_root.exists()


@pytest.mark.integration
def test_vault_agent_rejects_wrong_order_before_publication(tmp_path: Path) -> None:
    """Reject a malformed ordering hint before publishing any file."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    entries[0]["apply_hints"]["write_order"] = "after-templates"  # type: ignore[index]
    playbook = _write_playbook(tmp_path, rendered, entries, quadlets, runtime_home)

    code, _stdout, _stderr = _run_playbook(tmp_path / "wrong-order", playbook)

    assert code != 0
    assert not any(Path(str(entry["target_path"])).exists() for entry in entries)


@pytest.mark.integration
def test_vault_agent_rejects_mixed_users_before_publication(tmp_path: Path) -> None:
    """Reject a selection spanning rootless identities before publication."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    entries[1]["apply_hints"]["podman_user"] = "different-user"  # type: ignore[index]
    playbook = _write_playbook(tmp_path, rendered, entries, quadlets, runtime_home)

    code, _stdout, _stderr = _run_playbook(tmp_path / "mixed-user", playbook)

    assert code != 0
    assert not any(Path(str(entry["target_path"])).exists() for entry in entries)


@pytest.mark.integration
def test_vault_agent_rejects_incomplete_quadlet_owner_before_publication(
    tmp_path: Path,
) -> None:
    """Require the exact five-file Vault Agent rootless runtime."""
    rendered, entries, quadlets, runtime_home = _entries(tmp_path)
    missing = quadlets[:-1]
    playbook = _write_playbook(tmp_path, rendered, entries, missing, runtime_home)

    code, _stdout, _stderr = _run_playbook(tmp_path / "incomplete-quadlets", playbook)

    assert code != 0
    assert not any(Path(str(entry["target_path"])).exists() for entry in entries)


def test_vault_agent_runtime_uses_one_user_manager_activation_boundary() -> None:
    """Keep rootless reload, restart, and readiness in one owner-specific role."""
    role_path = (
        Path(__file__).resolve().parents[2] / "ansible/roles/vault_agent_config/tasks/main.yml"
    )
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task.get("name") for task in tasks]

    assert "Reload the Vault Agent user manager after Quadlet publication" in names
    assert names.index("Publish Vault Agent rootless Quadlet files") < names.index(
        "Publish Vault Agent templates"
    )
    restart = next(
        task
        for task in tasks
        if task.get("name") == "Restart Vault Agent once after changed publication"
    )
    assert any("abhaile_vault_agent_quadlets_changed" in condition for condition in restart["when"])
    observe = next(
        task for task in tasks if task.get("name") == "Observe Vault Agent runtime state"
    )
    assert observe["failed_when"] is False
    start = next(task for task in tasks if task.get("name") == "Start inactive Vault Agent runtime")
    assert "abhaile_vault_agent_active.rc != 0" in start["when"]
    verify = next(task for task in tasks if task.get("name") == "Verify Vault Agent is active")
    assert verify["when"] == "not ansible_check_mode"
