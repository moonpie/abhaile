"""Tests for abhaile apply/diff CLI entrypoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abhaile.cli.apply import main as main_apply
from abhaile.cli.diff import main as main_diff
from abhaile.apply.actions import ExecutionResult
from abhaile.utils.errors import ApplyError


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
    normalized_entries: list[dict[str, object]] = []
    for entry in entries:
        normalized = dict(entry)
        normalized.setdefault("kind", "service.config")
        normalized.setdefault("owner_ref", "service:test")
        normalized_entries.append(normalized)

    payload: dict[str, object] = {
        "version": "1",
        "host": host,
        "entries": normalized_entries,
    }
    if owners:
        payload["owners"] = owners
    path.write_text(json.dumps(payload, indent=2) + "\n")


class TestApplyCli:
    """Tests for main_apply() and main_diff()."""

    def test_diff_runs_with_explicit_manifest_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """abhaile-diff should summarize drift for explicit manifests."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"
        target = tmp_path / "target" / "etc" / "app.conf"

        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("a=1\n"),
                    "size": 4,
                }
            ],
        )
        _write_manifest(applied, "deimos", [])

        rc = main_diff(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )

        output = capsys.readouterr().out
        assert rc == 1
        assert "diff added=1 changed=0 removed=0" in output

    def test_apply_dry_run_does_not_write_target_or_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--dry-run plans changes without writing files or state."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = tmp_path / "rendered" / "system" / "etc" / "app.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("a=1\n")

        target = tmp_path / "target" / "etc" / "app.conf"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("a=1\n"),
                    "size": 4,
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--dry-run"])
        assert rc == 0
        assert not target.exists()
        assert not (tmp_path / "state" / "manifest.json").exists()

    def test_apply_writes_target_and_updates_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-dry-run apply should copy desired file and update state."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = tmp_path / "rendered" / "system" / "etc" / "app.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("value=yes\n")

        target = tmp_path / "target" / "etc" / "app.conf"
        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("value=yes\n"),
                    "size": 10,
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        rc = main_apply(["--desired-manifest", desired.as_posix()])
        assert rc == 0
        assert target.read_text() == "value=yes\n"

        state_manifest = tmp_path / "state" / "manifest.json"
        assert state_manifest.exists()

    def test_apply_host_mismatch_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Host mismatch should raise ApplyError unless bypassed."""
        desired = tmp_path / "rendered" / "manifest.json"
        _write_manifest(desired, "deimos", [])
        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        with pytest.raises(ApplyError, match="Host safety gate failed"):
            main_apply(["--desired-manifest", desired.as_posix()])

    def test_apply_dry_run_validations_runs_read_only_checks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--dry-run-validations should execute validation commands and not mutate state."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = tmp_path / "rendered" / "system" / "etc" / "systemd" / "system" / "caddy.service"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("[Unit]\nDescription=Caddy\n")

        target = tmp_path / "target" / "etc" / "systemd" / "system" / "caddy.service"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/etc/systemd/system/caddy.service",
                    "target_path": target.as_posix(),
                    "kind": "systemd.unit",
                    "owner_ref": "unit:caddy.service",
                    "sha256": _sha_of("[Unit]\nDescription=Caddy\n"),
                    "size": len("[Unit]\nDescription=Caddy\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")

        calls: list[list[str]] = []

        class _ValidationResult:
            success = True
            return_code = 0

        def _fake_validation(
            argv: list[str], *, action_id: str, is_blocker: bool
        ) -> _ValidationResult:
            calls.append(argv)
            return _ValidationResult()

        monkeypatch.setattr("abhaile.apply.dispatch.run_validation", _fake_validation)

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--dry-run",
                "--dry-run-validations",
                "--json",
            ]
        )

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert rc == 0
        assert payload["mode"] == "dry-run"
        assert payload["validations_run"] == 1
        assert calls and calls[0][0] == "systemd-analyze"
        assert not target.exists()
        assert not (tmp_path / "state" / "manifest.json").exists()

    def test_apply_json_includes_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include structured owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = tmp_path / "rendered" / "system" / "etc" / "systemd" / "system" / "caddy.service"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("[Unit]\nDescription=Caddy\n")

        target = tmp_path / "target" / "etc" / "systemd" / "system" / "caddy.service"
        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/systemd/system/caddy.service",
                    "target_path": target.as_posix(),
                    "kind": "systemd.unit",
                    "owner_ref": "unit:caddy.service",
                    "sha256": _sha_of("[Unit]\nDescription=Caddy\n"),
                    "size": len("[Unit]\nDescription=Caddy\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        def _fake_apply_unit_write(
            unit_name: str,
            entry: dict[str, object],
            *,
            user: bool,
            run_as_user: str | None,
        ) -> dict[str, object]:
            return {
                "unit_name": unit_name,
                "kind": entry.get("kind", "systemd.unit"),
                "actions": [{"action": "daemon-reload", "success": True, "return_code": 0}],
            }

        monkeypatch.setattr(
            "abhaile.apply.dispatch.SystemdExecutor.apply_unit_write",
            _fake_apply_unit_write,
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert payload["writes"] == 1
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "systemd.unit"

    def test_apply_json_includes_user_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include user-management owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = tmp_path / "rendered" / "system" / "etc" / "sysusers.d" / "abhaile.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("u abhaile 1001 - /home/abhaile /bin/bash\n")

        target = tmp_path / "target" / "etc" / "sysusers.d" / "abhaile.conf"
        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/sysusers.d/abhaile.conf",
                    "target_path": target.as_posix(),
                    "kind": "host.sysusers",
                    "owner_ref": "host-users:phobos",
                    "apply_hints": {
                        "owner_user": "root",
                        "owner_group": "root",
                        "mode": "0644",
                    },
                    "sha256": _sha_of("u abhaile 1001 - /home/abhaile /bin/bash\n"),
                    "size": len("u abhaile 1001 - /home/abhaile /bin/bash\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")
        monkeypatch.setattr(
            "abhaile.apply.staging.atomic_copy_file_with_perms",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.UserManagementExecutor.apply_sysusers_write",
            lambda entry: {
                "kind": entry.get("kind", "host.sysusers"),
                "actions": [{"action": "systemd-sysusers", "success": True, "return_code": 0}],
            },
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "host.sysusers"

    def test_apply_authorized_keys_requires_apply_hints(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """host.authorized_keys apply should fail if owner metadata hints are missing."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = tmp_path / "rendered" / "system" / "home" / "abhaile" / ".ssh" / "authorized_keys"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("ssh-ed25519 AAAATEST\n")

        target = tmp_path / "target" / "home" / "abhaile" / ".ssh" / "authorized_keys"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/home/abhaile/.ssh/authorized_keys",
                    "target_path": target.as_posix(),
                    "kind": "host.authorized_keys",
                    "owner_ref": "principal:abhaile",
                    "sha256": _sha_of("ssh-ed25519 AAAATEST\n"),
                    "size": len("ssh-ed25519 AAAATEST\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")

        with pytest.raises(ApplyError, match="Missing apply_hints"):
            main_apply(["--desired-manifest", desired.as_posix()])

    def test_apply_dry_run_validations_coredns_zone_missing_checker_warns(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """CoreDNS zone dry-run validation should report warning when checker is unavailable."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
            tmp_path
            / "rendered"
            / "system"
            / "etc"
            / "coredns"
            / "zones"
            / "abhaile.home.arpa.zone"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("$ORIGIN abhaile.home.arpa.\n")

        target = tmp_path / "target" / "etc" / "coredns" / "zones" / "abhaile.home.arpa.zone"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/etc/coredns/zones/abhaile.home.arpa.zone",
                    "target_path": target.as_posix(),
                    "kind": "coredns.zone",
                    "owner_ref": "dns-zone:abhaile.home.arpa",
                    "sha256": _sha_of("$ORIGIN abhaile.home.arpa.\n"),
                    "size": len("$ORIGIN abhaile.home.arpa.\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.CorednsExecutor.validate_zone_file",
            lambda *args, **kwargs: ExecutionResult(
                action_id="validate-zone:abhaile.home.arpa",
                action_type="validation",
                success=True,
                return_code=None,
                error_message="named-checkzone missing; validation skipped",
            ),
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--dry-run",
                "--dry-run-validations",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["validations_run"] == 1
        assert payload["validation_results"][0]["kind"] == "coredns.zone"
        assert (
            payload["validation_results"][0]["warning"]
            == "named-checkzone missing; validation skipped"
        )

    def test_apply_json_includes_coredns_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include CoreDNS owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
            tmp_path
            / "rendered"
            / "system"
            / "etc"
            / "coredns"
            / "zones"
            / "abhaile.home.arpa.zone"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("$ORIGIN abhaile.home.arpa.\n")

        target = tmp_path / "target" / "etc" / "coredns" / "zones" / "abhaile.home.arpa.zone"
        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/coredns/zones/abhaile.home.arpa.zone",
                    "target_path": target.as_posix(),
                    "kind": "coredns.zone",
                    "owner_ref": "dns-zone:abhaile.home.arpa",
                    "sha256": _sha_of("$ORIGIN abhaile.home.arpa.\n"),
                    "size": len("$ORIGIN abhaile.home.arpa.\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.CorednsExecutor.apply_zone_write",
            lambda entry, target_path: {
                "kind": entry.get("kind", "coredns.zone"),
                "zone": "abhaile.home.arpa",
                "actions": [{"action": "validate-zone", "success": True, "return_code": 0}],
            },
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "coredns.zone"

    def test_apply_dry_run_validations_caddy_missing_podman_warns(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Caddy dry-run validation should report warning when podman is unavailable."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
            tmp_path / "rendered" / "services" / "caddy-dmz" / "srv" / "caddy" / "dmz" / "Caddyfile"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# caddy\n")

        target = tmp_path / "target" / "srv" / "caddy" / "dmz" / "Caddyfile"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "services/caddy-dmz/srv/caddy/dmz/Caddyfile",
                    "target_path": target.as_posix(),
                    "kind": "caddy.config",
                    "owner_ref": "caddy:dmz",
                    "sha256": _sha_of("# caddy\n"),
                    "size": len("# caddy\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.CaddyExecutor.validate_caddy_config",
            lambda *args, **kwargs: ExecutionResult(
                action_id="validate-caddy:dmz",
                action_type="validation",
                success=True,
                return_code=None,
                error_message="podman missing; validation skipped",
            ),
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--dry-run",
                "--dry-run-validations",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["validations_run"] == 1
        assert payload["validation_results"][0]["kind"] == "caddy.config"
        assert payload["validation_results"][0]["warning"] == "podman missing; validation skipped"

    def test_apply_json_includes_caddy_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include Caddy owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
            tmp_path / "rendered" / "services" / "caddy-dmz" / "srv" / "caddy" / "dmz" / "Caddyfile"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# caddy\n")

        target = tmp_path / "target" / "srv" / "caddy" / "dmz" / "Caddyfile"
        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/caddy-dmz/srv/caddy/dmz/Caddyfile",
                    "target_path": target.as_posix(),
                    "kind": "caddy.config",
                    "owner_ref": "caddy:dmz",
                    "sha256": _sha_of("# caddy\n"),
                    "size": len("# caddy\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.CaddyExecutor.apply_config_write",
            lambda entry, target_path, **_kwargs: {
                "kind": entry.get("kind", "caddy.config"),
                "segment": "dmz",
                "actions": [{"action": "reload-caddy", "success": True, "return_code": 0}],
            },
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "caddy.config"

    def test_apply_json_includes_vault_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include vault-agent owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
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
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('pid_file = "/tmp/vault-agent.pid"\n')

        target = tmp_path / "target" / "srv" / "vault" / "agent" / "config" / "config.hcl"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "services/vault-agent/srv/vault/agent/config/config.hcl",
                    "target_path": target.as_posix(),
                    "kind": "vault.config",
                    "owner_ref": "service:vault-agent",
                    "apply_hints": {
                        "podman_user": "abhaile",
                    },
                    "sha256": _sha_of('pid_file = "/tmp/vault-agent.pid"\n'),
                    "size": len('pid_file = "/tmp/vault-agent.pid"\n'),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.VaultExecutor.apply_owner_change",
            lambda owner_ref, run_as_user: {
                "owner_ref": owner_ref,
                "run_as_user": run_as_user,
                "actions": [
                    {
                        "action": "restart",
                        "service": "vault-agent.service",
                        "success": True,
                        "return_code": 0,
                    }
                ],
            },
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "vault.owner"
        assert payload["owner_execution"][0]["owner_ref"] == "service:vault-agent"

    def test_apply_json_includes_networkd_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include networkd owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
            tmp_path / "rendered" / "system" / "etc" / "systemd" / "network" / "10-vlan20.network"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("[Match]\nName=vlan20\n")

        target = tmp_path / "target" / "etc" / "systemd" / "network" / "10-vlan20.network"
        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/systemd/network/10-vlan20.network",
                    "target_path": target.as_posix(),
                    "kind": "networkd.network",
                    "owner_ref": "iface:vlan20",
                    "sha256": _sha_of("[Match]\nName=vlan20\n"),
                    "size": len("[Match]\nName=vlan20\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.apply_owner_change",
            lambda owner_ref, interface, strict_reconfigure, kinds, **kwargs: {
                "owner_ref": owner_ref,
                "interface": interface,
                "kinds": kinds,
                "actions": [
                    {"action": "reload", "success": True, "return_code": 0},
                    {"action": "reconfigure", "success": True, "return_code": 0},
                ],
            },
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "networkd.owner"
        assert payload["owner_execution"][0]["owner_ref"] == "iface:vlan20"

    def test_apply_networkd_netdev_remove_uses_ordered_delete_and_single_reload(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Remove-only netdev owners should delete in planner order and reload once."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        parent_target = tmp_path / "target" / "etc" / "systemd" / "network" / "20-ipvlan-l2.netdev"
        child_target = (
            tmp_path / "target" / "etc" / "systemd" / "network" / "40-ipvlan-l2.100.netdev"
        )
        parent_target.parent.mkdir(parents=True, exist_ok=True)
        parent_content = "[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n"
        child_content = "[NetDev]\nName=ipvlan-l2.100\nKind=ipvlan\n"
        parent_target.write_text(parent_content)
        child_target.write_text(child_content)

        _write_manifest(desired, "phobos", [])
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/systemd/network/20-ipvlan-l2.netdev",
                    "target_path": parent_target.as_posix(),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2",
                    "sha256": _sha_of(parent_content),
                    "size": len(parent_content),
                },
                {
                    "render_path": "system/etc/systemd/network/40-ipvlan-l2.100.netdev",
                    "target_path": child_target.as_posix(),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2.100",
                    "sha256": _sha_of(child_content),
                    "size": len(child_content),
                },
            ],
            owners={
                "iface:ipvlan-l2": {"name": "iface:ipvlan-l2"},
                "iface:ipvlan-l2.100": {
                    "name": "iface:ipvlan-l2.100",
                    "requires": ["iface:ipvlan-l2"],
                },
            },
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        deleted_ifaces: list[str] = []
        reload_calls = 0

        def _fake_delete_interface(interface: str) -> ExecutionResult:
            deleted_ifaces.append(interface)
            return ExecutionResult(
                action_id=f"ip-link-delete:{interface}",
                action_type="delete",
                success=True,
                return_code=0,
            )

        def _fake_reload_networkd() -> ExecutionResult:
            nonlocal reload_calls
            reload_calls += 1
            return ExecutionResult(
                action_id="networkctl-reload",
                action_type="reload",
                success=True,
                return_code=0,
            )

        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.delete_interface", _fake_delete_interface
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.reload_networkd", _fake_reload_networkd
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
                "--prune",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert deleted_ifaces == ["ipvlan-l2.100", "ipvlan-l2"]
        assert reload_calls == 1

        networkd_results = [
            entry for entry in payload["owner_execution"] if entry.get("kind") == "networkd.owner"
        ]
        assert len(networkd_results) == 2
        assert networkd_results[0]["owner_ref"] == "iface:ipvlan-l2.100"
        assert networkd_results[1]["owner_ref"] == "iface:ipvlan-l2"
        assert networkd_results[0]["summary"]["actions"][0]["action"] == "delete-interface"

    def test_apply_passes_netdev_delete_order_to_networkd_executor(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Apply should execute remove-only netdev owners in planner-provided order."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        parent_target = tmp_path / "target" / "etc" / "systemd" / "network" / "20-ipvlan-l2.netdev"
        child_target = (
            tmp_path / "target" / "etc" / "systemd" / "network" / "40-ipvlan-l2.100.netdev"
        )
        parent_target.parent.mkdir(parents=True, exist_ok=True)
        parent_target.write_text("parent\n")
        child_target.write_text("child\n")

        _write_manifest(desired, "phobos", [])
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/systemd/network/20-ipvlan-l2.netdev",
                    "target_path": parent_target.as_posix(),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2",
                    "sha256": _sha_of("parent\n"),
                    "size": len("parent\n"),
                },
                {
                    "render_path": "system/etc/systemd/network/40-ipvlan-l2.100.netdev",
                    "target_path": child_target.as_posix(),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2.100",
                    "sha256": _sha_of("child\n"),
                    "size": len("child\n"),
                },
            ],
            owners={
                "iface:ipvlan-l2": {"name": "iface:ipvlan-l2"},
                "iface:ipvlan-l2.100": {
                    "name": "iface:ipvlan-l2.100",
                    "requires": ["iface:ipvlan-l2"],
                },
            },
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        deleted_ifaces: list[str] = []
        reload_calls = 0

        def _fake_delete_interface(interface: str) -> ExecutionResult:
            deleted_ifaces.append(interface)
            return ExecutionResult(
                action_id=f"ip-link-delete:{interface}",
                action_type="delete",
                success=True,
                return_code=0,
            )

        def _fake_reload_networkd() -> ExecutionResult:
            nonlocal reload_calls
            reload_calls += 1
            return ExecutionResult(
                action_id="networkctl-reload",
                action_type="reload",
                success=True,
                return_code=0,
            )

        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.delete_interface", _fake_delete_interface
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.reload_networkd", _fake_reload_networkd
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
                "--prune",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert deleted_ifaces == ["ipvlan-l2.100", "ipvlan-l2"]
        assert reload_calls == 1

    def test_apply_json_includes_quadlet_owner_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json apply output should include quadlet owner execution entries."""
        desired = tmp_path / "rendered" / "manifest.json"
        source = (
            tmp_path
            / "rendered"
            / "services"
            / "blocky"
            / "etc"
            / "containers"
            / "systemd"
            / "blocky.container"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("[Container]\nImage=blocky:latest\n")

        target = tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "services/blocky/etc/containers/systemd/blocky.container",
                    "target_path": target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:blocky.service",
                    "apply_hints": {"rootless": False},
                    "sha256": _sha_of("[Container]\nImage=blocky:latest\n"),
                    "size": len("[Container]\nImage=blocky:latest\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_owner_change",
            lambda owner_ref, kinds, changed_phases, rootless, run_as_user: {
                "owner_ref": owner_ref,
                "unit": "blocky.service",
                "kinds": kinds,
                "rootless": rootless,
                "actions": [
                    {"action": "daemon-reload", "success": True, "return_code": 0},
                    {"action": "try-restart", "success": True, "return_code": 0},
                ],
            },
        )

        rc = main_apply(["--desired-manifest", desired.as_posix(), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "apply"
        assert len(payload["owner_execution"]) == 1
        assert payload["owner_execution"][0]["kind"] == "quadlet.owner"
        assert payload["owner_execution"][0]["owner_ref"] == "unit:blocky.service"

    def test_apply_quadlet_convergence_plan_stops_and_starts_dependents(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Changed shared quadlet network should stop/start dependent containers around primary convergence."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        network_source = (
            tmp_path
            / "rendered"
            / "services"
            / "_shared"
            / "etc"
            / "containers"
            / "systemd"
            / "services.network"
        )
        network_source.parent.mkdir(parents=True, exist_ok=True)
        network_source.write_text("[Network]\nDriver=ipvlan\n")

        network_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "services.network"
        container_target = (
            tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        )
        container_target.parent.mkdir(parents=True, exist_ok=True)
        container_content = "[Container]\nImage=blocky:latest\n"
        container_target.write_text(container_content)

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/_shared/etc/containers/systemd/services.network",
                    "target_path": network_target.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:services-network.service",
                    "apply_hints": {"rootless": False, "shared": True},
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n"),
                    "size": len("[Network]\nDriver=ipvlan\n"),
                },
                {
                    "render_path": "services/blocky/etc/containers/systemd/blocky.container",
                    "target_path": container_target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:blocky.service",
                    "apply_hints": {"rootless": False},
                    "sha256": _sha_of(container_content),
                    "size": len(container_content),
                },
            ],
            owners={
                "unit:services-network.service": {
                    "name": "unit:services-network.service",
                    "apply_hints": {"rootless": False, "shared": True},
                },
                "unit:blocky.service": {
                    "name": "unit:blocky.service",
                    "requires": ["unit:services-network.service"],
                    "apply_hints": {"rootless": False},
                },
            },
        )
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "services/blocky/etc/containers/systemd/blocky.container",
                    "target_path": container_target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:blocky.service",
                    "apply_hints": {"rootless": False},
                    "sha256": _sha_of(container_content),
                    "size": len(container_content),
                },
            ],
            owners={
                "unit:blocky.service": {
                    "name": "unit:blocky.service",
                    "requires": ["unit:services-network.service"],
                    "apply_hints": {"rootless": False},
                }
            },
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        convergence_calls: list[tuple[str, str]] = []
        primary_calls: list[str] = []

        def _fake_apply_convergence_action(
            owner_ref: str,
            action: str,
            rootless: bool,
            run_as_user: str | None,
        ) -> dict[str, object]:
            del rootless, run_as_user
            convergence_calls.append((action, owner_ref))
            return {
                "owner_ref": owner_ref,
                "unit": owner_ref.split(":", 1)[1],
                "action": action,
                "success": True,
                "return_code": 0,
            }

        def _fake_apply_owner_change(
            owner_ref: str,
            kinds: list[str],
            changed_phases: set[str],
            rootless: bool,
            run_as_user: str | None,
        ) -> dict[str, object]:
            del changed_phases, run_as_user
            primary_calls.append(owner_ref)
            return {
                "owner_ref": owner_ref,
                "unit": owner_ref.split(":", 1)[1],
                "kinds": kinds,
                "rootless": rootless,
                "actions": [
                    {"action": "daemon-reload", "success": True, "return_code": 0},
                    {"action": "start", "success": True, "return_code": 0},
                ],
            }

        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_convergence_action",
            _fake_apply_convergence_action,
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_owner_change",
            _fake_apply_owner_change,
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
        assert primary_calls == ["unit:services-network.service"]
        assert convergence_calls == [
            ("stop", "unit:blocky.service"),
            ("start", "unit:blocky.service"),
        ]
        quadlet_results = [
            entry for entry in payload["owner_execution"] if entry.get("kind") == "quadlet.owner"
        ]
        assert quadlet_results[0]["summary"]["convergence_actions"][0]["action"] == "stop"

    def test_apply_quadlet_convergence_plan_deduplicates_shared_dependent_actions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A dependent shared across multiple changed primaries should stop once and start once."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        alpha_source = (
            tmp_path
            / "rendered"
            / "services"
            / "_shared"
            / "etc"
            / "containers"
            / "systemd"
            / "alpha.network"
        )
        beta_source = (
            tmp_path
            / "rendered"
            / "services"
            / "_shared"
            / "etc"
            / "containers"
            / "systemd"
            / "beta.network"
        )
        alpha_source.parent.mkdir(parents=True, exist_ok=True)
        alpha_source.write_text("[Network]\nDriver=ipvlan\n")
        beta_source.write_text("[Network]\nDriver=ipvlan\n#beta\n")

        alpha_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "alpha.network"
        beta_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "beta.network"
        container_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "app.container"
        container_target.parent.mkdir(parents=True, exist_ok=True)
        container_content = "[Container]\nImage=app:latest\n"
        container_target.write_text(container_content)

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/_shared/etc/containers/systemd/alpha.network",
                    "target_path": alpha_target.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:alpha-network.service",
                    "apply_hints": {"rootless": False, "shared": True},
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n"),
                    "size": len("[Network]\nDriver=ipvlan\n"),
                },
                {
                    "render_path": "services/_shared/etc/containers/systemd/beta.network",
                    "target_path": beta_target.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:beta-network.service",
                    "apply_hints": {"rootless": False, "shared": True},
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n#beta\n"),
                    "size": len("[Network]\nDriver=ipvlan\n#beta\n"),
                },
                {
                    "render_path": "services/app/etc/containers/systemd/app.container",
                    "target_path": container_target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:app.service",
                    "apply_hints": {"rootless": False},
                    "sha256": _sha_of(container_content),
                    "size": len(container_content),
                },
            ],
            owners={
                "unit:alpha-network.service": {
                    "name": "unit:alpha-network.service",
                    "apply_hints": {"rootless": False, "shared": True},
                },
                "unit:beta-network.service": {
                    "name": "unit:beta-network.service",
                    "apply_hints": {"rootless": False, "shared": True},
                },
                "unit:app.service": {
                    "name": "unit:app.service",
                    "requires": ["unit:alpha-network.service", "unit:beta-network.service"],
                    "apply_hints": {"rootless": False},
                },
            },
        )
        _write_manifest(applied, "phobos", [])

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        convergence_calls: list[tuple[str, str]] = []
        primary_calls: list[str] = []

        def _fake_apply_convergence_action(
            owner_ref: str,
            action: str,
            rootless: bool,
            run_as_user: str | None,
        ) -> dict[str, object]:
            del rootless, run_as_user
            convergence_calls.append((action, owner_ref))
            return {
                "owner_ref": owner_ref,
                "unit": owner_ref.split(":", 1)[1],
                "action": action,
                "success": True,
                "return_code": 0,
            }

        def _fake_apply_owner_change(
            owner_ref: str,
            kinds: list[str],
            changed_phases: set[str],
            rootless: bool,
            run_as_user: str | None,
        ) -> dict[str, object]:
            del changed_phases, run_as_user
            primary_calls.append(owner_ref)
            return {
                "owner_ref": owner_ref,
                "unit": owner_ref.split(":", 1)[1],
                "kinds": kinds,
                "rootless": rootless,
                "actions": [
                    {"action": "daemon-reload", "success": True, "return_code": 0},
                    {"action": "start", "success": True, "return_code": 0},
                ],
            }

        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_convergence_action",
            _fake_apply_convergence_action,
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_owner_change",
            _fake_apply_owner_change,
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
        assert primary_calls == ["unit:alpha-network.service", "unit:beta-network.service"]
        assert convergence_calls == [
            ("stop", "unit:app.service"),
            ("start", "unit:app.service"),
        ]
        quadlet_results = [
            entry for entry in payload["owner_execution"] if entry.get("kind") == "quadlet.owner"
        ]
        assert len(quadlet_results) == 2

    def test_apply_dry_run_reports_owner_escalations(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Dry-run JSON should surface owner escalations from owner_plan."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"
        target = tmp_path / "target" / "etc" / "stale.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("live-modified\n")

        _write_manifest(desired, "deimos", [])
        _write_manifest(
            applied,
            "deimos",
            [
                {
                    "render_path": "system/etc/stale.conf",
                    "target_path": target.as_posix(),
                    "kind": "service.config",
                    "owner_ref": "service:legacy",
                    "sha256": _sha_of("original\n"),
                    "size": len("original\n"),
                }
            ],
            owners={
                "service:legacy": {
                    "name": "service:legacy",
                }
            },
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "deimos")

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
                "--dry-run",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert "prune-drifted" in payload["owner_escalations"]

    def test_apply_dry_run_surfaces_quadlet_convergence_plans(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Dry-run JSON should expose quadlet convergence plans without executing them."""
        desired = tmp_path / "rendered" / "manifest.json"
        network_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "services.network"
        container_target = (
            tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        )

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/_shared/etc/containers/systemd/services.network",
                    "target_path": network_target.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:services-network.service",
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n"),
                    "size": len("[Network]\nDriver=ipvlan\n"),
                },
                {
                    "render_path": "services/blocky/etc/containers/systemd/blocky.container",
                    "target_path": container_target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:blocky.service",
                    "sha256": _sha_of("[Container]\nImage=blocky:latest\n"),
                    "size": len("[Container]\nImage=blocky:latest\n"),
                },
            ],
            owners={
                "unit:services-network.service": {"name": "unit:services-network.service"},
                "unit:blocky.service": {
                    "name": "unit:blocky.service",
                    "requires": ["unit:services-network.service"],
                },
            },
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_convergence_action",
            lambda *args, **kwargs: pytest.fail("dry-run should not execute convergence actions"),
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.QuadletExecutor.apply_owner_change",
            lambda *args, **kwargs: pytest.fail("dry-run should not execute owner changes"),
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--dry-run",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "dry-run"
        assert payload["quadlet_convergence_plans"] == {
            "unit:services-network.service": [
                {"owner_ref": "unit:blocky.service", "action": "stop"},
                {"owner_ref": "unit:blocky.service", "action": "start"},
            ]
        }

    def test_apply_dry_run_does_not_execute_service_or_networkd_owner_actions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Dry-run should not dispatch service or networkd mutation executors."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        service_target = tmp_path / "target" / "etc" / "chrony" / "chrony.conf"
        directory_target = tmp_path / "target" / "srv" / "authelia" / "config"
        netdev_target = tmp_path / "target" / "etc" / "systemd" / "network" / "20-ipvlan-l2.netdev"

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/chrony-a/etc/chrony/chrony.conf",
                    "target_path": service_target.as_posix(),
                    "kind": "service.config",
                    "owner_ref": "service:chrony-a",
                    "sha256": _sha_of("pool pool.ntp.org iburst\n"),
                    "size": len("pool pool.ntp.org iburst\n"),
                    "apply_hints": {"restart_unit": "chrony.service"},
                },
                {
                    "render_path": "services/authelia/srv/authelia/config",
                    "target_path": directory_target.as_posix(),
                    "kind": "service.directory",
                    "owner_ref": "service:authelia",
                    "sha256": _sha_of(""),
                    "size": 0,
                    "apply_hints": {
                        "owner": "abhaile",
                        "group": "abhaile",
                        "mode": "0750",
                    },
                },
            ],
        )
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/systemd/network/20-ipvlan-l2.netdev",
                    "target_path": netdev_target.as_posix(),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2",
                    "sha256": _sha_of("[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n"),
                    "size": len("[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n"),
                }
            ],
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")
        monkeypatch.setattr(
            "abhaile.apply.dispatch.ServiceConfigExecutor.apply_owner_change",
            lambda *args, **kwargs: pytest.fail("dry-run should not execute service restarts"),
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.ServiceConfigExecutor.apply_directory_change",
            lambda *args, **kwargs: pytest.fail("dry-run should not execute directory enforcement"),
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.delete_interface",
            lambda *args, **kwargs: pytest.fail("dry-run should not delete interfaces"),
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.reload_networkd",
            lambda *args, **kwargs: pytest.fail("dry-run should not reload networkd"),
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.NetworkdExecutor.apply_owner_change",
            lambda *args, **kwargs: pytest.fail(
                "dry-run should not execute networkd owner changes"
            ),
        )

        rc = main_apply(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
                "--dry-run",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "dry-run"
        assert payload["validations_run"] == 0

    def test_apply_service_config_change_runs_service_owner_executor(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Service config writes should trigger service owner convergence actions."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"
        source = tmp_path / "rendered" / "services" / "chrony-a" / "etc" / "chrony" / "chrony.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("pool pool.ntp.org iburst\n")
        target = tmp_path / "target" / "etc" / "chrony" / "chrony.conf"

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/chrony-a/etc/chrony/chrony.conf",
                    "target_path": target.as_posix(),
                    "kind": "service.config",
                    "owner_ref": "service:chrony-a",
                    "sha256": _sha_of("pool pool.ntp.org iburst\n"),
                    "size": len("pool pool.ntp.org iburst\n"),
                    "apply_hints": {"restart_unit": "chrony.service"},
                }
            ],
        )
        _write_manifest(applied, "phobos", [])

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        service_calls: list[tuple[str, int, int, object]] = []

        def _fake_service_owner_change(
            owner_ref: str,
            writes: list[dict[str, object]],
            removals: list[dict[str, object]],
            apply_hints: dict[str, object] | None,
        ) -> dict[str, object]:
            service_calls.append((owner_ref, len(writes), len(removals), apply_hints))
            return {
                "owner_ref": owner_ref,
                "actions": [
                    {
                        "action": "try-restart",
                        "unit": "chrony.service",
                        "success": True,
                        "return_code": 0,
                    }
                ],
            }

        monkeypatch.setattr(
            "abhaile.apply.dispatch.ServiceConfigExecutor.apply_owner_change",
            _fake_service_owner_change,
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
        assert service_calls == [
            (
                "service:chrony-a",
                1,
                0,
                {"restart_unit": "chrony.service"},
            )
        ]
        service_results = [
            entry for entry in payload["owner_execution"] if entry.get("kind") == "service.owner"
        ]
        assert len(service_results) == 1
        assert service_results[0]["owner_ref"] == "service:chrony-a"

    def test_apply_service_directory_change_runs_directory_enforcement(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Service directory writes should dispatch to directory enforcement path."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"
        rendered_dir = (
            tmp_path / "rendered" / "services" / "authelia" / "srv" / "authelia" / "config"
        )
        rendered_dir.mkdir(parents=True, exist_ok=True)
        target_dir = tmp_path / "target" / "srv" / "authelia" / "config"

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "services/authelia/srv/authelia/config",
                    "target_path": target_dir.as_posix(),
                    "kind": "service.directory",
                    "owner_ref": "service:authelia",
                    "sha256": _sha_of(""),
                    "size": 0,
                    "apply_hints": {
                        "owner": "abhaile",
                        "group": "abhaile",
                        "mode": "0750",
                    },
                }
            ],
        )
        _write_manifest(applied, "phobos", [])

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        directory_calls: list[tuple[str, object]] = []
        restart_calls: list[tuple[str, int, int, object]] = []

        def _fake_apply_directory_change(
            target_path: str,
            apply_hints: dict[str, object] | None,
        ) -> dict[str, object]:
            directory_calls.append((target_path, apply_hints))
            return {
                "target_path": target_path,
                "actions": [{"action": "ensure-directory", "success": True, "return_code": 0}],
            }

        def _fake_apply_owner_change(
            owner_ref: str,
            writes: list[dict[str, object]],
            removals: list[dict[str, object]],
            apply_hints: dict[str, object] | None,
        ) -> dict[str, object]:
            restart_calls.append((owner_ref, len(writes), len(removals), apply_hints))
            return {
                "owner_ref": owner_ref,
                "actions": [],
            }

        monkeypatch.setattr(
            "abhaile.apply.dispatch.ServiceConfigExecutor.apply_directory_change",
            _fake_apply_directory_change,
        )
        monkeypatch.setattr(
            "abhaile.apply.dispatch.ServiceConfigExecutor.apply_owner_change",
            _fake_apply_owner_change,
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
        assert directory_calls == [
            (
                target_dir.as_posix(),
                {"owner": "abhaile", "group": "abhaile", "mode": "0750"},
            )
        ]
        assert restart_calls == [("service:authelia", 0, 0, None)]
        service_results = [
            entry for entry in payload["owner_execution"] if entry.get("kind") == "service.owner"
        ]
        assert len(service_results) == 1
        assert "directory_actions" in service_results[0]["summary"]

    def test_apply_force_prune_requires_allow_destructive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """force-prune on drifted removals should require --allow-destructive."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"
        target = tmp_path / "target" / "etc" / "legacy.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("locally-modified\n")

        _write_manifest(desired, "phobos", [])
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/legacy.conf",
                    "target_path": target.as_posix(),
                    "kind": "service.config",
                    "owner_ref": "service:legacy",
                    "sha256": _sha_of("managed\n"),
                    "size": len("managed\n"),
                }
            ],
            owners={
                "service:legacy": {
                    "name": "service:legacy",
                }
            },
        )

        monkeypatch.setattr("abhaile.cli.apply._local_hostname", lambda: "phobos")

        with pytest.raises(ApplyError, match="Destructive operation blocked"):
            main_apply(
                [
                    "--desired-manifest",
                    desired.as_posix(),
                    "--applied-manifest",
                    applied.as_posix(),
                    "--force-prune",
                ]
            )
