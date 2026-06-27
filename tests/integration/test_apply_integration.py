"""Integration tests for apply workflow execution and state rotation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abhaile.cli.apply import main as main_apply

pytestmark = pytest.mark.integration


def _sha_of(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write_manifest(
    path: Path,
    host: str,
    entries: list[dict[str, object]],
    *,
    owners: dict[str, dict[str, object]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "version": "1",
        "host": host,
        "entries": entries,
    }
    if owners:
        payload["owners"] = owners
    path.write_text(json.dumps(payload, indent=2) + "\n")


class TestApplyIntegration:
    """Integration scenarios for apply with real drift planning and state writes."""

    def test_apply_mixed_owner_execution_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Apply should copy files, execute owner families, and persist state."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        systemd_source = (
            tmp_path / "rendered" / "system" / "etc" / "systemd" / "system" / "demo.service"
        )
        systemd_source.parent.mkdir(parents=True, exist_ok=True)
        systemd_source.write_text("[Unit]\nDescription=Demo\n")

        quadlet_source = (
            tmp_path
            / "rendered"
            / "services"
            / "demo"
            / "etc"
            / "containers"
            / "systemd"
            / "demo.container"
        )
        quadlet_source.parent.mkdir(parents=True, exist_ok=True)
        quadlet_source.write_text("[Container]\nImage=demo:latest\n")

        vault_source = (
            tmp_path
            / "rendered"
            / "services"
            / "vault-agent"
            / "srv"
            / "vault"
            / "agent"
            / "config"
            / "config.hcl"
        )
        vault_source.parent.mkdir(parents=True, exist_ok=True)
        vault_source.write_text('pid_file = "/tmp/vault-agent.pid"\n')

        systemd_target = tmp_path / "target" / "etc" / "systemd" / "system" / "demo.service"
        quadlet_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "demo.container"
        vault_target = tmp_path / "target" / "srv" / "vault" / "agent" / "config" / "config.hcl"

        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/etc/systemd/system/demo.service",
                    "target_path": systemd_target.as_posix(),
                    "kind": "systemd.unit",
                    "owner_ref": "unit:demo.service",
                    "sha256": _sha_of("[Unit]\nDescription=Demo\n"),
                    "size": len("[Unit]\nDescription=Demo\n"),
                },
                {
                    "render_path": "services/demo/etc/containers/systemd/demo.container",
                    "target_path": quadlet_target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:demo.service",
                    "apply_hints": {"rootless": False},
                    "sha256": _sha_of("[Container]\nImage=demo:latest\n"),
                    "size": len("[Container]\nImage=demo:latest\n"),
                },
                {
                    "render_path": "services/vault-agent/srv/vault/agent/config/config.hcl",
                    "target_path": vault_target.as_posix(),
                    "kind": "vault.config",
                    "owner_ref": "service:vault-agent",
                    "apply_hints": {"podman_user": "abhaile", "rootless": True},
                    "sha256": _sha_of('pid_file = "/tmp/vault-agent.pid"\n'),
                    "size": len('pid_file = "/tmp/vault-agent.pid"\n'),
                },
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.SystemdExecutor.apply_unit_write",
            lambda unit_name, entry, *, user, run_as_user: {
                "unit_name": unit_name,
                "kind": entry.get("kind", "systemd.unit"),
                "actions": [{"action": "daemon-reload", "success": True, "return_code": 0}],
            },
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_owner_change",
            lambda owner_ref, kinds, changed_phases, rootless, run_as_user, restart_mode: {
                "owner_ref": owner_ref,
                "unit": "demo.service",
                "kinds": kinds,
                "restart_mode": restart_mode,
                "actions": [{"action": "try-restart", "success": True, "return_code": 0}],
            },
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.VaultExecutor.apply_owner_change",
            lambda owner_ref, run_as_user: {
                "owner_ref": owner_ref,
                "run_as_user": run_as_user,
                "actions": [{"action": "restart", "success": True, "return_code": 0}],
            },
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert payload["writes"] == 3

        kinds = {item["kind"] for item in payload["owner_execution"]}
        assert "systemd.unit" in kinds
        assert "quadlet.owner" in kinds
        assert "vault.owner" in kinds

        assert systemd_target.read_text() == "[Unit]\nDescription=Demo\n"
        assert quadlet_target.read_text() == "[Container]\nImage=demo:latest\n"
        assert vault_target.read_text() == 'pid_file = "/tmp/vault-agent.pid"\n'
        assert applied.exists()

    def test_apply_prune_safe_removal_rotates_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Prune-safe removals should delete target and rotate state manifests."""
        desired_v1 = tmp_path / "rendered" / "manifest-v1.json"
        desired_v2 = tmp_path / "rendered" / "manifest-v2.json"
        applied = tmp_path / "state" / "manifest.json"

        source = tmp_path / "rendered" / "system" / "etc" / "demo.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("demo=1\n")

        target = tmp_path / "target" / "etc" / "demo.conf"

        v1_entries = [
            {
                "render_path": "system/etc/demo.conf",
                "target_path": target.as_posix(),
                "kind": "service.config",
                "owner_ref": "service:demo",
                "sha256": _sha_of("demo=1\n"),
                "size": len("demo=1\n"),
            }
        ]
        _write_manifest(desired_v1, "phobos", v1_entries)
        _write_manifest(desired_v2, "phobos", [])

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        rc1 = main_apply(
            [
                "--desired-manifest",
                desired_v1.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )
        assert rc1 == 0
        assert target.exists()

        # Keep target untouched so removal is prune-safe against applied hash
        rc2 = main_apply(
            [
                "--desired-manifest",
                desired_v2.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
                "--prune",
            ]
        )

        assert rc2 == 0
        assert not target.exists()

        previous = applied.parent / "manifest.previous.json"
        history_dir = applied.parent / "history"
        assert applied.exists()
        assert previous.exists()
        assert any(history_dir.glob("manifest-*.json"))

        current_payload = json.loads(applied.read_text())
        previous_payload = json.loads(previous.read_text())
        assert current_payload["entries"] == []
        assert len(previous_payload["entries"]) == 1
