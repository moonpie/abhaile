"""Execution helpers for systemd unit family (phase 7.2)."""

from __future__ import annotations

from typing import Any

from abhaile.apply.actions import ExecutionResult, run_command, run_systemctl_command
from abhaile.utils.errors import ApplyError


class SystemdExecutor:
    """Executor for systemd.unit, systemd.dropin, resolved.config, resolved.dropin."""

    @staticmethod
    def daemon_reload() -> ExecutionResult:
        """Run systemctl daemon-reload."""
        result = run_command(
            ["systemctl", "daemon-reload"],
            action_id="systemctl-daemon-reload",
            action_type="systemctl",
        )
        if not result.success:
            raise ApplyError(f"Daemon reload failed: {result.error_message}")
        return result

    @staticmethod
    def start_unit(
        unit_name: str,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> ExecutionResult:
        """Start a systemd unit."""
        return run_systemctl_command(
            "start",
            unit_name,
            user=user,
            run_as_user=run_as_user,
        )

    @staticmethod
    def try_restart_unit(
        unit_name: str,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> ExecutionResult:
        """Try-restart a systemd unit (restart if active, no-op if inactive)."""
        return run_systemctl_command(
            "try-restart",
            unit_name,
            user=user,
            run_as_user=run_as_user,
        )

    @staticmethod
    def reload_unit(
        unit_name: str,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> ExecutionResult:
        """Reload a systemd unit (using reload if available, else restart)."""
        return run_systemctl_command(
            "reload-or-restart",
            unit_name,
            user=user,
            run_as_user=run_as_user,
        )

    @staticmethod
    def stop_unit(
        unit_name: str,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> ExecutionResult:
        """Stop a systemd unit."""
        return run_systemctl_command(
            "stop",
            unit_name,
            user=user,
            run_as_user=run_as_user,
        )

    @staticmethod
    def enable_unit(
        unit_name: str,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> ExecutionResult:
        """Enable a systemd unit (creates boot-persistence symlink)."""
        return run_systemctl_command(
            "enable",
            unit_name,
            user=user,
            run_as_user=run_as_user,
        )

    @staticmethod
    def disable_unit(
        unit_name: str,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> ExecutionResult:
        """Disable a systemd unit (removes boot-persistence symlink)."""
        return run_systemctl_command(
            "disable",
            unit_name,
            user=user,
            run_as_user=run_as_user,
        )

    @staticmethod
    def apply_unit_write(
        unit_name: str,
        entry: dict[str, Any],
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> dict[str, Any]:
        """Apply a systemd.unit write entry (create or update).

        Workflow: daemon-reload, then optionally enable, try-restart, and/or start
        based on apply_hints (enable_mode, restart_mode, activation_mode).
        """
        actions = []

        # 1. Daemon-reload (mandatory after unit file write)
        daemon_result = SystemdExecutor.daemon_reload()
        actions.append(
            {
                "action": "daemon-reload",
                "success": daemon_result.success,
                "return_code": daemon_result.return_code,
            }
        )

        # 2. Extract hints
        apply_hints = entry.get("apply_hints", {})
        if not isinstance(apply_hints, dict):
            apply_hints = {}

        restart_mode = apply_hints.get(
            "restart_mode", "none"
        )  # none, reload-or-restart, try-restart
        activation_mode = apply_hints.get("activation_mode", "none")  # none, start, start-now
        enable_mode = apply_hints.get("enable_mode", "none")  # none, enable

        # 3. Enable unit if hint requests it (creates boot-persistence symlink)
        if enable_mode == "enable":
            try:
                enable_result = SystemdExecutor.enable_unit(
                    unit_name,
                    user=user,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "enable",
                        "success": enable_result.success,
                        "return_code": enable_result.return_code,
                    }
                )
            except ApplyError as exc:
                raise ApplyError(f"Unit enable failed ({unit_name}): {exc}") from exc

        # 4. Try-restart if active and hint says restart
        if restart_mode == "try-restart":
            try:
                restart_result = SystemdExecutor.try_restart_unit(
                    unit_name,
                    user=user,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "try-restart",
                        "success": restart_result.success,
                        "return_code": restart_result.return_code,
                    }
                )
            except ApplyError as exc:
                raise ApplyError(f"Unit restart failed ({unit_name}): {exc}") from exc

        # 5. Start if activation_mode requests it
        if activation_mode in ("start", "start-now"):
            try:
                start_result = SystemdExecutor.start_unit(
                    unit_name,
                    user=user,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "start",
                        "success": start_result.success,
                        "return_code": start_result.return_code,
                    }
                )
            except ApplyError as exc:
                raise ApplyError(f"Unit start failed ({unit_name}): {exc}") from exc

        return {
            "unit_name": unit_name,
            "kind": entry.get("kind", "systemd.unit"),
            "actions": actions,
        }

    @staticmethod
    def apply_dropin_write(
        parent_unit_name: str,
        entry: dict[str, Any],
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> dict[str, Any]:
        """Apply a systemd.dropin write entry (daemon-reload + try-restart parent)."""
        actions = []

        # 1. Daemon-reload (mandatory after dropin file write)
        daemon_result = SystemdExecutor.daemon_reload()
        actions.append(
            {
                "action": "daemon-reload",
                "success": daemon_result.success,
                "return_code": daemon_result.return_code,
            }
        )

        # 2. Try-restart parent if active (dropin changes require restart)
        try:
            restart_result = SystemdExecutor.try_restart_unit(
                parent_unit_name,
                user=user,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "try-restart",
                    "unit": parent_unit_name,
                    "success": restart_result.success,
                    "return_code": restart_result.return_code,
                }
            )
        except ApplyError as exc:
            raise ApplyError(f"Parent unit restart failed ({parent_unit_name}): {exc}") from exc

        return {
            "parent_unit_name": parent_unit_name,
            "kind": entry.get("kind", "systemd.dropin"),
            "actions": actions,
        }

    @staticmethod
    def apply_resolved_config_write(
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a resolved.config write entry (reload systemd-resolved)."""
        actions = []

        # 1. Reload systemd-resolved (always reload for singleton)
        try:
            reload_result = SystemdExecutor.reload_unit("systemd-resolved.service")
            actions.append(
                {
                    "action": "reload",
                    "service": "systemd-resolved.service",
                    "success": reload_result.success,
                    "return_code": reload_result.return_code,
                }
            )
        except ApplyError as exc:
            raise ApplyError(f"systemd-resolved reload failed: {exc}") from exc

        return {
            "service": "systemd-resolved.service",
            "kind": entry.get("kind", "resolved.config"),
            "actions": actions,
        }

    @staticmethod
    def apply_unit_remove(
        unit_name: str,
        entry: dict[str, Any] | None = None,
        *,
        user: bool = False,
        run_as_user: str | None = None,
    ) -> dict[str, Any]:
        """Apply a systemd.unit removal entry.

        Workflow: disable (if enabled), stop, daemon-reload.
        """
        actions = []

        # 1. Disable if the unit was enabled
        apply_hints = (entry or {}).get("apply_hints") or {}
        if not isinstance(apply_hints, dict):
            apply_hints = {}
        if apply_hints.get("enable_mode") == "enable":
            try:
                disable_result = SystemdExecutor.disable_unit(
                    unit_name,
                    user=user,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "disable",
                        "success": disable_result.success,
                        "return_code": disable_result.return_code,
                    }
                )
            except ApplyError as exc:
                raise ApplyError(f"Unit disable failed ({unit_name}): {exc}") from exc

        # 2. Stop unit if active
        try:
            stop_result = SystemdExecutor.stop_unit(
                unit_name,
                user=user,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "stop",
                    "success": stop_result.success,
                    "return_code": stop_result.return_code,
                }
            )
        except ApplyError as exc:
            raise ApplyError(f"Unit stop failed ({unit_name}): {exc}") from exc

        # 3. Daemon-reload
        daemon_result = SystemdExecutor.daemon_reload()
        actions.append(
            {
                "action": "daemon-reload",
                "success": daemon_result.success,
                "return_code": daemon_result.return_code,
            }
        )

        return {
            "unit_name": unit_name,
            "kind": "systemd.unit",
            "actions": actions,
        }
