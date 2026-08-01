"""Tests for dispatch removal branches and helper functions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from abhaile.apply.dispatch import (
    _entry_user_context,
    _resolve_parent_unit_name,
    _run_caddy_owner_actions,
    _run_coredns_owner_actions,
    _run_dry_run_validations,
    _run_quadlet_owner_actions,
    _run_systemd_owner_actions,
    _run_vault_owner_actions,
)
from abhaile.utils.errors import ApplyError


class TestEntryUserContext:
    """Tests for _entry_user_context."""

    def test_no_apply_hints_returns_rootful(self) -> None:
        assert _entry_user_context({}) == (False, None)

    def test_non_dict_apply_hints_returns_rootful(self) -> None:
        assert _entry_user_context({"apply_hints": "invalid"}) == (False, None)

    def test_rootless_with_podman_user(self) -> None:
        entry: dict[str, object] = {"apply_hints": {"rootless": True, "podman_user": "abhaile"}}
        assert _entry_user_context(entry) == (True, "abhaile")

    def test_rootless_without_podman_user(self) -> None:
        entry: dict[str, object] = {"apply_hints": {"rootless": True}}
        assert _entry_user_context(entry) == (True, None)

    def test_rootful_explicit(self) -> None:
        entry: dict[str, object] = {"apply_hints": {"rootless": False}}
        assert _entry_user_context(entry) == (False, None)


class TestResolveParentUnitName:
    """Tests for _resolve_parent_unit_name."""

    def test_owner_ref_with_unit_prefix(self) -> None:
        assert (
            _resolve_parent_unit_name(
                "/etc/systemd/system/caddy.service.d/override.conf", "unit:caddy.service"
            )
            == "caddy.service"
        )

    def test_resolves_from_target_path_dotd(self) -> None:
        assert (
            _resolve_parent_unit_name(
                "/etc/systemd/system/caddy.service.d/override.conf", "host:phobos"
            )
            == "caddy.service"
        )

    def test_raises_when_cannot_determine(self) -> None:
        with pytest.raises(ApplyError, match="Unable to determine parent unit"):
            _resolve_parent_unit_name("/etc/systemd/system/caddy.service", "host:phobos")


class TestDryRunValidations:
    """Tests for apply dry-run validation dispatch."""

    def test_resolved_config_does_not_use_systemd_analyze_verify(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolved.conf is not systemd unit syntax and should not be verified as a unit."""
        calls: list[list[str]] = []

        def _fake_validation(argv: list[str], **_: object) -> object:
            calls.append(argv)
            return object()

        monkeypatch.setattr("abhaile.apply.dispatch.run_validation", _fake_validation)

        results = _run_dry_run_validations(
            tmp_path,
            [
                {
                    "kind": "resolved.config",
                    "render_path": "system/etc/systemd/resolved.conf",
                    "target_path": "/etc/systemd/resolved.conf",
                }
            ],
        )

        assert results == []
        assert calls == []


class TestSystemdOwnerActionsRemovals:
    """Tests for systemd removal branch in _run_systemd_owner_actions."""

    @patch("abhaile.apply.dispatch.SystemdExecutor.apply_unit_remove")
    def test_removal_dispatches_to_apply_unit_remove(self, mock_remove: Any) -> None:
        mock_remove.return_value = {
            "unit_name": "caddy.service",
            "kind": "systemd.unit",
            "actions": [{"action": "stop", "success": True, "return_code": 0}],
        }

        removals: list[dict[str, object]] = [
            {
                "kind": "systemd.unit",
                "target_path": "/etc/systemd/system/caddy.service",
                "owner_ref": "unit:caddy.service",
            }
        ]

        results = _run_systemd_owner_actions([], removals)

        assert len(results) == 1
        assert results[0]["phase"] == "remove"
        assert results[0]["kind"] == "systemd.unit"
        mock_remove.assert_called_once()

    def test_removal_skips_non_unit_kinds(self) -> None:
        removals: list[dict[str, object]] = [
            {
                "kind": "resolved.config",
                "target_path": "/etc/systemd/resolved.conf",
                "owner_ref": "host:phobos",
            }
        ]
        results = _run_systemd_owner_actions([], removals)
        assert results == []


class TestCorednsOwnerActionsRemovals:
    """Tests for coredns removal branch."""

    @patch("abhaile.apply.dispatch.CorednsExecutor.apply_transaction")
    def test_zone_removal_dispatches_transaction(self, mock_transaction: Any) -> None:
        mock_transaction.return_value = {
            "kind": "coredns.transaction",
            "actions": [{"action": "reload", "success": True, "return_code": 0}],
        }

        removals: list[dict[str, object]] = [
            {
                "kind": "coredns.zone",
                "target_path": "/etc/coredns/zones/old.zone",
                "owner_ref": "dns-zone:old.example.com",
            }
        ]

        results = _run_coredns_owner_actions([], removals)

        assert len(results) == 1
        assert results[0]["phase"] == "transaction"
        mock_transaction.assert_called_once_with(
            config_changed=False,
            zone_writes=[],
            zone_removals=removals,
        )

    @patch("abhaile.apply.dispatch.CorednsExecutor.apply_transaction")
    def test_config_removal_dispatches_restart_transaction(self, mock_transaction: Any) -> None:
        mock_transaction.return_value = {
            "kind": "coredns.transaction",
            "actions": [{"action": "restart", "success": True, "return_code": 0}],
        }

        removals: list[dict[str, object]] = [
            {
                "kind": "coredns.config",
                "target_path": "/etc/coredns/Corefile",
                "owner_ref": "dns:coredns",
            }
        ]

        results = _run_coredns_owner_actions([], removals)

        assert len(results) == 1
        assert results[0]["phase"] == "transaction"
        mock_transaction.assert_called_once_with(
            config_changed=True,
            zone_writes=[],
            zone_removals=[],
        )

    @patch("abhaile.apply.dispatch.CorednsExecutor.apply_transaction")
    def test_multiple_zone_writes_are_one_transaction(self, mock_transaction: Any) -> None:
        """Multiple zone changes should produce one CoreDNS runtime action."""
        mock_transaction.return_value = {
            "kind": "coredns.transaction",
            "actions": [{"action": "reload", "success": True, "return_code": 0}],
        }

        writes: list[dict[str, object]] = [
            {
                "kind": "coredns.zone",
                "target_path": "/etc/coredns/zones/a.zone",
                "owner_ref": "dns-zone:a",
            },
            {
                "kind": "coredns.zone",
                "target_path": "/etc/coredns/zones/b.zone",
                "owner_ref": "dns-zone:b",
            },
        ]

        results = _run_coredns_owner_actions(writes, [])

        assert len(results) == 1
        mock_transaction.assert_called_once_with(
            config_changed=False,
            zone_writes=writes,
            zone_removals=[],
        )

    @patch("abhaile.apply.dispatch.CorednsExecutor.apply_transaction")
    def test_config_and_zone_writes_are_one_restart_transaction(
        self, mock_transaction: Any
    ) -> None:
        """Corefile changes subsume zone reloads into one restart."""
        mock_transaction.return_value = {
            "kind": "coredns.transaction",
            "actions": [{"action": "restart", "success": True, "return_code": 0}],
        }

        writes: list[dict[str, object]] = [
            {
                "kind": "coredns.config",
                "target_path": "/etc/coredns/Corefile",
                "owner_ref": "dns:coredns",
            },
            {
                "kind": "coredns.zone",
                "target_path": "/etc/coredns/zones/a.zone",
                "owner_ref": "dns-zone:a",
            },
        ]

        results = _run_coredns_owner_actions(writes, [])

        assert len(results) == 1
        mock_transaction.assert_called_once_with(
            config_changed=True,
            zone_writes=[writes[1]],
            zone_removals=[],
        )


class TestCaddyOwnerActionsRemovals:
    """Tests for caddy removal branch."""

    @patch("abhaile.apply.dispatch.CaddyExecutor.apply_config_write")
    def test_caddy_write_allows_missing_container_for_same_apply_container_write(
        self, mock_write: Any
    ) -> None:
        mock_write.return_value = {
            "kind": "caddy.config",
            "actions": [{"action": "reload", "success": True, "return_code": 0}],
        }

        writes: list[dict[str, object]] = [
            {
                "kind": "caddy.config",
                "target_path": "/srv/caddy/dmz/Caddyfile",
                "owner_ref": "caddy:dmz",
            },
            {
                "kind": "quadlet.container",
                "target_path": "/etc/containers/systemd/caddy-dmz.container",
                "owner_ref": "unit:caddy-dmz.service",
            },
        ]

        results = _run_caddy_owner_actions(writes, [])

        assert len(results) == 1
        assert mock_write.call_args.kwargs == {"allow_missing_container": True}

    @patch("abhaile.apply.dispatch.CaddyExecutor.apply_config_write")
    def test_caddy_write_does_not_allow_missing_container_without_container_write(
        self, mock_write: Any
    ) -> None:
        mock_write.return_value = {
            "kind": "caddy.config",
            "actions": [{"action": "reload", "success": True, "return_code": 0}],
        }

        writes: list[dict[str, object]] = [
            {
                "kind": "caddy.config",
                "target_path": "/srv/caddy/internal/Caddyfile",
                "owner_ref": "caddy:internal",
            }
        ]

        results = _run_caddy_owner_actions(writes, [])

        assert len(results) == 1
        assert mock_write.call_args.kwargs == {"allow_missing_container": False}

    @patch("abhaile.apply.dispatch.CaddyExecutor.apply_config_write")
    def test_caddy_removal_dispatches(self, mock_write: Any) -> None:
        mock_write.return_value = {
            "kind": "caddy.config",
            "actions": [{"action": "reload", "success": True, "return_code": 0}],
        }

        removals: list[dict[str, object]] = [
            {
                "kind": "caddy.config",
                "target_path": "/srv/caddy/dmz/Caddyfile",
                "owner_ref": "caddy:dmz",
            }
        ]

        results = _run_caddy_owner_actions([], removals)

        assert len(results) == 1
        assert results[0]["phase"] == "remove"
        mock_write.assert_called_once()


class TestVaultOwnerActionsRemovals:
    """Tests for vault removal branch."""

    @patch("abhaile.apply.dispatch.VaultExecutor.apply_owner_change")
    def test_vault_removal_triggers_restart(self, mock_change: Any) -> None:
        mock_change.return_value = {
            "owner_ref": "service:vault-agent",
            "run_as_user": "abhaile",
            "actions": [{"action": "restart", "success": True, "return_code": 0}],
        }

        removals: list[dict[str, object]] = [
            {
                "kind": "vault.template",
                "target_path": "/srv/vault/agent/templates/old.ctmpl",
                "owner_ref": "service:vault-agent",
                "apply_hints": {"podman_user": "abhaile"},
            }
        ]

        results = _run_vault_owner_actions([], removals)

        assert len(results) == 1
        assert results[0]["phase"] == "converge"
        assert results[0]["kind"] == "vault.owner"
        mock_change.assert_called_once_with("service:vault-agent", run_as_user="abhaile")


class TestQuadletOwnerActions:
    """Tests for quadlet owner dispatch."""

    @patch("abhaile.apply.dispatch.QuadletExecutor.daemon_reload")
    @patch("abhaile.apply.dispatch.QuadletExecutor.apply_owner_change")
    def test_owner_apply_hints_control_restart_mode(
        self,
        mock_change: Any,
        mock_reload: Any,
    ) -> None:
        """Owner restart hints should be passed to the quadlet executor."""
        mock_reload.return_value = type(
            "Result",
            (),
            {"success": True, "return_code": 0},
        )()
        mock_change.return_value = {
            "owner_ref": "unit:omada-controller-app-mongodb.service",
            "unit": "omada-controller-app-mongodb.service",
            "restart_mode": "manual",
            "actions": [{"action": "skip-restart", "success": True, "return_code": 0}],
        }

        writes: list[dict[str, object]] = [
            {
                "kind": "quadlet.container",
                "target_path": "/etc/containers/systemd/omada-controller-app-mongodb.container",
                "owner_ref": "unit:omada-controller-app-mongodb.service",
                "apply_hints": {"rootless": False, "restart_mode": "manual"},
            }
        ]

        results = _run_quadlet_owner_actions(
            writes,
            [],
            owner_apply_hints={
                "unit:omada-controller-app-mongodb.service": {
                    "rootless": False,
                    "restart_mode": "manual",
                }
            },
        )

        assert len(results) == 2
        assert results[0]["kind"] == "quadlet.daemon-reload"
        assert results[1]["kind"] == "quadlet.owner"
        mock_reload.assert_called_once_with(rootless=False, run_as_user=None)
        mock_change.assert_called_once_with(
            "unit:omada-controller-app-mongodb.service",
            kinds=["quadlet.container"],
            changed_phases={"write"},
            rootless=False,
            run_as_user=None,
            restart_mode="manual",
            daemon_reloaded=True,
            verify_unit=True,
        )

    @patch("abhaile.apply.dispatch.QuadletExecutor.daemon_reload")
    @patch("abhaile.apply.dispatch.QuadletExecutor.apply_owner_change")
    def test_rootless_quadlet_creation_reloads_user_manager_before_owner_action(
        self,
        mock_change: Any,
        mock_reload: Any,
    ) -> None:
        """Rootless Quadlet changes should batch one user daemon-reload first."""
        mock_reload.return_value = type(
            "Result",
            (),
            {"success": True, "return_code": 0},
        )()
        mock_change.return_value = {
            "owner_ref": "unit:vault-agent.service",
            "unit": "vault-agent.service",
            "actions": [{"action": "start", "success": True, "return_code": 0}],
        }

        writes: list[dict[str, object]] = [
            {
                "kind": "quadlet.container",
                "target_path": "/home/abhaile/.config/containers/systemd/vault-agent.container",
                "owner_ref": "unit:vault-agent.service",
                "apply_hints": {"rootless": True, "podman_user": "abhaile"},
            }
        ]

        results = _run_quadlet_owner_actions(writes, [])

        assert [result["kind"] for result in results] == [
            "quadlet.daemon-reload",
            "quadlet.owner",
        ]
        mock_reload.assert_called_once_with(rootless=True, run_as_user="abhaile")
