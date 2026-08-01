"""Execution helpers for CoreDNS artifact family (phase 7.4)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from abhaile.apply.actions import ExecutionResult, run_command, run_systemctl_command
from abhaile.utils.errors import ApplyError


class CorednsExecutor:
    """Executor for coredns.config and coredns.zone artifacts."""

    @staticmethod
    def zone_name_from_target(target_path: str) -> str:
        """Derive DNS zone name from target path (typically /etc/coredns/zones/<zone>.zone)."""
        name = Path(target_path).name
        if name.endswith(".zone"):
            return name[: -len(".zone")]
        return Path(target_path).stem

    @staticmethod
    def validate_zone_file(
        zone_name: str,
        zone_file: Path,
        *,
        strict: bool,
    ) -> ExecutionResult:
        """Validate zone file with named-checkzone.

        Args:
            zone_name: DNS zone name.
            zone_file: Zone file path to validate.
            strict: If True, missing checker is fatal; if False, return a warning result.

        Raises:
            ApplyError: When strict and checker is missing or validation fails.
        """
        checker = shutil.which("named-checkzone")
        if checker is None:
            if strict:
                raise ApplyError(
                    "named-checkzone is required for CoreDNS apply validation "
                    "(install bind tools)"
                )
            return ExecutionResult(
                action_id=f"validate-zone:{zone_name}",
                action_type="validation",
                success=True,
                return_code=None,
                stdout="",
                stderr="",
                error_message="named-checkzone missing; validation skipped",
            )

        result = run_command(
            [checker, zone_name, zone_file.as_posix()],
            action_id=f"validate-zone:{zone_name}",
            action_type="validation",
            check=strict,
        )
        if strict and not result.success:
            raise ApplyError(f"Zone validation failed for {zone_name}: {result.error_message}")
        return result

    @staticmethod
    def restart_coredns_service() -> ExecutionResult:
        """Restart CoreDNS service after Corefile changes."""
        return run_systemctl_command("restart", "coredns.service")

    @staticmethod
    def reload_coredns_service() -> ExecutionResult:
        """Reload CoreDNS through systemd's serialized ExecReload path."""
        return run_systemctl_command("reload", "coredns.service")

    @staticmethod
    def stop_zone_watcher() -> ExecutionResult:
        """Stop the CoreDNS zone watcher while GitOps owns the transaction."""
        return run_systemctl_command("stop", "coredns-zones.path")

    @staticmethod
    def start_zone_watcher() -> ExecutionResult:
        """Start the CoreDNS zone watcher after a GitOps transaction."""
        return run_systemctl_command("start", "coredns-zones.path")

    @staticmethod
    def wait_coredns_active(*, timeout_seconds: float = 15.0) -> ExecutionResult:
        """Wait until coredns.service is active, bounded by timeout_seconds."""
        deadline = time.monotonic() + timeout_seconds
        last = ExecutionResult(
            action_id="systemctl is-active coredns.service",
            action_type="systemctl",
            success=False,
            return_code=None,
        )
        while time.monotonic() <= deadline:
            last = run_command(
                ["systemctl", "is-active", "coredns.service"],
                action_id="systemctl is-active coredns.service",
                action_type="systemctl",
                check=False,
            )
            if last.stdout.strip() == "active":
                return ExecutionResult(
                    action_id=last.action_id,
                    action_type=last.action_type,
                    success=True,
                    return_code=last.return_code,
                    stdout=last.stdout,
                    stderr=last.stderr,
                )
            time.sleep(0.25)

        raise ApplyError(
            "CoreDNS readiness check failed: "
            f"coredns.service did not become active within {timeout_seconds:.0f}s "
            f"(last={last.stdout.strip() or last.stderr.strip() or 'unknown'})"
        )

    @staticmethod
    def apply_transaction(
        *,
        config_changed: bool,
        zone_writes: list[dict[str, Any]],
        zone_removals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply one serialized CoreDNS runtime transaction after all file sync is complete."""
        actions: list[dict[str, Any]] = []
        zones: list[str] = []

        for entry in zone_writes:
            target_path = entry.get("target_path")
            if not isinstance(target_path, str):
                raise ApplyError("CoreDNS zone write missing target_path")
            zone_name = CorednsExecutor.zone_name_from_target(target_path)
            zones.append(zone_name)
            validate = CorednsExecutor.validate_zone_file(zone_name, Path(target_path), strict=True)
            actions.append(
                {
                    "action": "validate-zone",
                    "zone": zone_name,
                    "success": validate.success,
                    "return_code": validate.return_code,
                }
            )

        for entry in zone_removals:
            target_path = entry.get("target_path")
            if isinstance(target_path, str):
                zones.append(CorednsExecutor.zone_name_from_target(target_path))

        if not config_changed and not zone_writes and not zone_removals:
            return {
                "kind": "coredns.transaction",
                "zones": [],
                "actions": [],
            }

        stop_watcher = CorednsExecutor.stop_zone_watcher()
        actions.append(
            {
                "action": "stop",
                "service": "coredns-zones.path",
                "success": stop_watcher.success,
                "return_code": stop_watcher.return_code,
            }
        )

        try:
            if config_changed:
                restart = CorednsExecutor.restart_coredns_service()
                actions.append(
                    {
                        "action": "restart",
                        "service": "coredns.service",
                        "success": restart.success,
                        "return_code": restart.return_code,
                    }
                )
            else:
                ready_before = CorednsExecutor.wait_coredns_active()
                actions.append(
                    {
                        "action": "wait-active",
                        "service": "coredns.service",
                        "success": ready_before.success,
                        "return_code": ready_before.return_code,
                    }
                )
                reload_result = CorednsExecutor.reload_coredns_service()
                actions.append(
                    {
                        "action": "reload",
                        "service": "coredns.service",
                        "success": reload_result.success,
                        "return_code": reload_result.return_code,
                    }
                )

            ready_after = CorednsExecutor.wait_coredns_active()
            actions.append(
                {
                    "action": "wait-active",
                    "service": "coredns.service",
                    "success": ready_after.success,
                    "return_code": ready_after.return_code,
                }
            )
        finally:
            start_watcher = CorednsExecutor.start_zone_watcher()
            actions.append(
                {
                    "action": "start",
                    "service": "coredns-zones.path",
                    "success": start_watcher.success,
                    "return_code": start_watcher.return_code,
                }
            )

        return {
            "kind": "coredns.transaction",
            "zones": sorted(set(zones)),
            "config_changed": config_changed,
            "actions": actions,
        }
