"""Unit tests for phase 7.6 vault-agent executor."""

from __future__ import annotations

from typing import Any

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.vault import VaultExecutor  # pyright: ignore[reportMissingImports]


class TestVaultExecutor:
    """Tests for Vault apply executor."""

    def test_user_from_entry_defaults_to_abhaile(self) -> None:
        """Missing hints should default to rootless service user."""
        assert VaultExecutor.user_from_entry({"kind": "vault.config"}) == "abhaile"

    def test_user_from_entry_uses_apply_hints_override(self) -> None:
        """podman_user hint should override default runtime user."""
        assert (
            VaultExecutor.user_from_entry(
                {
                    "kind": "vault.template",
                    "apply_hints": {"podman_user": "vaultsvc"},
                }
            )
            == "vaultsvc"
        )

    def test_apply_owner_change_restarts_user_service(self, mocker: Any) -> None:
        """Owner convergence should restart vault-agent via user systemd."""
        mock_restart = mocker.patch.object(
            VaultExecutor,
            "restart_vault_agent",
            return_value=ExecutionResult(
                action_id="systemctl-restart-vault-agent",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = VaultExecutor.apply_owner_change(
            "service:vault-agent",
            run_as_user="abhaile",
        )

        assert summary["owner_ref"] == "service:vault-agent"
        assert summary["run_as_user"] == "abhaile"
        assert summary["actions"][0]["action"] == "restart"
        mock_restart.assert_called_once_with(run_as_user="abhaile")
