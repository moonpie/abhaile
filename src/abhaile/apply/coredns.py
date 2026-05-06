"""Execution helpers for CoreDNS artifact family (phase 7.4)."""

from __future__ import annotations

import shutil
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
    def start_zone_reload_service() -> ExecutionResult:
        """Trigger coredns-zones.service to reload zones deterministically."""
        return run_systemctl_command("start", "coredns-zones.service")

    @staticmethod
    def restart_coredns_service() -> ExecutionResult:
        """Restart CoreDNS service after Corefile changes."""
        return run_systemctl_command("try-restart", "coredns.service")

    @staticmethod
    def apply_config_write(entry: dict[str, Any]) -> dict[str, Any]:
        """Apply runtime step for coredns.config writes."""
        restart = CorednsExecutor.restart_coredns_service()
        return {
            "kind": entry.get("kind", "coredns.config"),
            "actions": [
                {
                    "action": "try-restart",
                    "service": "coredns.service",
                    "success": restart.success,
                    "return_code": restart.return_code,
                }
            ],
        }

    @staticmethod
    def apply_zone_write(entry: dict[str, Any], target_path: str) -> dict[str, Any]:
        """Apply runtime step for coredns.zone writes (validate then reload zones)."""
        zone_name = CorednsExecutor.zone_name_from_target(target_path)
        validate = CorednsExecutor.validate_zone_file(zone_name, Path(target_path), strict=True)
        reload_result = CorednsExecutor.start_zone_reload_service()

        return {
            "kind": entry.get("kind", "coredns.zone"),
            "zone": zone_name,
            "actions": [
                {
                    "action": "validate-zone",
                    "success": validate.success,
                    "return_code": validate.return_code,
                },
                {
                    "action": "start",
                    "service": "coredns-zones.service",
                    "success": reload_result.success,
                    "return_code": reload_result.return_code,
                },
            ],
        }

    @staticmethod
    def apply_zone_remove(entry: dict[str, Any], target_path: str) -> dict[str, Any]:
        """Apply runtime step for coredns.zone removals (reload zones after deletion)."""
        zone_name = CorednsExecutor.zone_name_from_target(target_path)
        reload_result = CorednsExecutor.start_zone_reload_service()
        return {
            "kind": entry.get("kind", "coredns.zone"),
            "zone": zone_name,
            "actions": [
                {
                    "action": "start",
                    "service": "coredns-zones.service",
                    "success": reload_result.success,
                    "return_code": reload_result.return_code,
                }
            ],
        }
