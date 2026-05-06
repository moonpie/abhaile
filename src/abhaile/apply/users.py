"""Execution helpers for host user-management artifact family (phase 7.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.apply.actions import ExecutionResult, run_command, run_validation
from abhaile.utils.errors import ApplyError


class UserManagementExecutor:
    """Executor for host.sysusers, host.sudoers, and host.authorized_keys artifacts."""

    @staticmethod
    def run_sysusers_reconcile() -> ExecutionResult:
        """Run systemd-sysusers to reconcile users/groups from sysusers fragments."""
        result = run_command(
            ["systemd-sysusers"],
            action_id="systemd-sysusers",
            action_type="user-management",
        )
        if not result.success:
            raise ApplyError(f"systemd-sysusers failed: {result.error_message}")
        return result

    @staticmethod
    def validate_sysusers_dry_run() -> ExecutionResult:
        """Run read-only sysusers validation (blocker)."""
        return run_validation(
            ["systemd-sysusers", "--dry-run"],
            action_id="validate:systemd-sysusers",
            is_blocker=True,
        )

    @staticmethod
    def validate_sudoers(path: Path) -> ExecutionResult:
        """Validate sudoers file syntax as a blocker."""
        return run_validation(
            ["visudo", "-cf", path.as_posix()],
            action_id=f"validate:sudoers:{path}",
            is_blocker=True,
        )

    @staticmethod
    def apply_sysusers_write(entry: dict[str, Any]) -> dict[str, Any]:
        """Apply runtime step for host.sysusers writes."""
        reconcile = UserManagementExecutor.run_sysusers_reconcile()
        return {
            "kind": entry.get("kind", "host.sysusers"),
            "actions": [
                {
                    "action": "systemd-sysusers",
                    "success": reconcile.success,
                    "return_code": reconcile.return_code,
                }
            ],
        }

    @staticmethod
    def apply_sudoers_write(entry: dict[str, Any], target_path: Path) -> dict[str, Any]:
        """Apply runtime step for host.sudoers writes."""
        validate = UserManagementExecutor.validate_sudoers(target_path)
        return {
            "kind": entry.get("kind", "host.sudoers"),
            "actions": [
                {
                    "action": "visudo-validate",
                    "success": validate.success,
                    "return_code": validate.return_code,
                }
            ],
        }

    @staticmethod
    def apply_authorized_keys_write(entry: dict[str, Any]) -> dict[str, Any]:
        """Apply runtime step for host.authorized_keys writes (no command)."""
        return {
            "kind": entry.get("kind", "host.authorized_keys"),
            "actions": [],
        }
