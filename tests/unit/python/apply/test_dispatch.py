"""Tests for dispatch removal branches and helper functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from abhaile.apply.dispatch import (
    _entry_user_context,
    _resolve_parent_unit_name,
    _run_caddy_owner_actions,
    _run_coredns_owner_actions,
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

    @patch("abhaile.apply.dispatch.CorednsExecutor.apply_zone_remove")
    def test_zone_removal_dispatches(self, mock_remove: Any) -> None:
        mock_remove.return_value = {
            "kind": "coredns.zone",
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
        assert results[0]["phase"] == "remove"
        mock_remove.assert_called_once()

    @patch("abhaile.apply.dispatch.CorednsExecutor.apply_config_write")
    def test_config_removal_dispatches(self, mock_write: Any) -> None:
        mock_write.return_value = {
            "kind": "coredns.config",
            "actions": [{"action": "reload", "success": True, "return_code": 0}],
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
        assert results[0]["phase"] == "remove"
        mock_write.assert_called_once()


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
