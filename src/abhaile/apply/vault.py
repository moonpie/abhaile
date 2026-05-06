"""Execution helpers for vault-agent artifact family (phase 7.6)."""

from __future__ import annotations

from typing import Any

from abhaile.apply.actions import ExecutionResult, run_systemctl_command


class VaultExecutor:
    """Executor for vault.config and vault.template artifacts."""

    DEFAULT_USER = "abhaile"
    UNIT_NAME = "vault-agent.service"

    @staticmethod
    def user_from_entry(entry: dict[str, Any]) -> str:
        """Resolve rootless runtime user from apply hints, with safe default."""
        apply_hints = entry.get("apply_hints")
        if isinstance(apply_hints, dict):
            user = apply_hints.get("podman_user")
            if isinstance(user, str) and user:
                return user
        return VaultExecutor.DEFAULT_USER

    @staticmethod
    def restart_vault_agent(*, run_as_user: str) -> ExecutionResult:
        """Restart vault-agent via user systemd manager."""
        return run_systemctl_command(
            "restart",
            VaultExecutor.UNIT_NAME,
            user=True,
            run_as_user=run_as_user,
        )

    @staticmethod
    def apply_owner_change(owner_ref: str, *, run_as_user: str) -> dict[str, Any]:
        """Converge vault-agent runtime after any vault config/template change."""
        restart = VaultExecutor.restart_vault_agent(run_as_user=run_as_user)
        return {
            "owner_ref": owner_ref,
            "run_as_user": run_as_user,
            "actions": [
                {
                    "action": "restart",
                    "service": VaultExecutor.UNIT_NAME,
                    "scope": "user",
                    "success": restart.success,
                    "return_code": restart.return_code,
                }
            ],
        }
