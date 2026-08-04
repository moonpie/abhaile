"""Execution helpers for CoreDNS artifact family (phase 7.4)."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from abhaile.apply.actions import ExecutionResult, run_command, run_systemctl_command
from abhaile.utils.errors import ApplyError

_COREDNS_BUILD_CONTAINERFILE = "/srv/build/coredns-omada/Containerfile"
_COREDNS_BUILD_QUADLET = "/etc/containers/systemd/coredns-omada.build"


class CorednsExecutor:
    """Executor for coredns.config and coredns.zone artifacts."""

    COREDNS_BUILD_UNIT = "coredns-omada-build.service"
    COREDNS_INSTALL_UNIT = "coredns-omada-install.service"
    COREDNS_BINARY_PATH = Path("/usr/local/bin/coredns")

    @staticmethod
    def build_inputs_changed(writes: list[dict[str, object]]) -> bool:
        """Return True when CoreDNS build inputs changed."""
        for action in writes:
            target_path = action.get("target_path")
            if not isinstance(target_path, str):
                continue
            if target_path in {_COREDNS_BUILD_CONTAINERFILE, _COREDNS_BUILD_QUADLET}:
                return True
        return False

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
    def daemon_reload() -> ExecutionResult:
        """Reload systemd units so Quadlet-generated units become available."""
        return run_command(
            ["systemctl", "daemon-reload"],
            action_id="systemctl daemon-reload",
            action_type="systemctl",
            check=True,
        )

    @staticmethod
    def verify_unit_loaded(unit_name: str) -> ExecutionResult:
        """Verify a unit is loaded in systemd after daemon-reload."""
        result = run_command(
            ["systemctl", "show", unit_name, "--property=LoadState", "--value"],
            action_id=f"systemctl show {unit_name} LoadState",
            action_type="systemctl",
            check=True,
        )
        if result.stdout.strip() != "loaded":
            raise ApplyError(
                f"Expected generated unit {unit_name} to be loaded, got "
                f"{result.stdout.strip() or 'unknown'}"
            )
        return result

    @staticmethod
    def start_unit(unit_name: str) -> ExecutionResult:
        """Start a unit and require successful completion."""
        return run_systemctl_command("start", unit_name)

    @staticmethod
    def verify_coredns_binary(path: Path) -> None:
        """Ensure installed coredns binary exists and is executable."""
        if not path.exists() or not path.is_file():
            raise ApplyError(f"CoreDNS build transaction failed: missing binary at {path}")
        if not os.access(path, os.X_OK):
            raise ApplyError(
                f"CoreDNS build transaction failed: binary is not executable at {path}"
            )

    @staticmethod
    def _append_result_action(
        actions: list[dict[str, Any]],
        *,
        action: str,
        result: ExecutionResult,
        service: str | None = None,
        unit: str | None = None,
        zone: str | None = None,
        path: str | None = None,
    ) -> None:
        """Append a normalized transaction action entry."""
        payload: dict[str, Any] = {
            "action": action,
            "success": result.success,
            "return_code": result.return_code,
        }
        if service is not None:
            payload["service"] = service
        if unit is not None:
            payload["unit"] = unit
        if zone is not None:
            payload["zone"] = zone
        if path is not None:
            payload["path"] = path
        actions.append(payload)

    @staticmethod
    def _collect_zone_changes(
        actions: list[dict[str, Any]],
        zone_writes: list[dict[str, Any]],
        zone_removals: list[dict[str, Any]],
    ) -> list[str]:
        """Validate changed zones and return all affected zone names."""
        zones: list[str] = []
        for entry in zone_writes:
            target_path = entry.get("target_path")
            if not isinstance(target_path, str):
                raise ApplyError("CoreDNS zone write missing target_path")
            zone_name = CorednsExecutor.zone_name_from_target(target_path)
            zones.append(zone_name)
            validate = CorednsExecutor.validate_zone_file(zone_name, Path(target_path), strict=True)
            CorednsExecutor._append_result_action(
                actions,
                action="validate-zone",
                zone=zone_name,
                result=validate,
            )

        for entry in zone_removals:
            target_path = entry.get("target_path")
            if isinstance(target_path, str):
                zones.append(CorednsExecutor.zone_name_from_target(target_path))
        return zones

    @staticmethod
    def _run_build_install_transaction(actions: list[dict[str, Any]]) -> None:
        """Run ordered CoreDNS build/install units and verify the installed binary."""
        reload_result = CorednsExecutor.daemon_reload()
        CorednsExecutor._append_result_action(
            actions,
            action="daemon-reload",
            service="systemd",
            result=reload_result,
        )

        generated = CorednsExecutor.verify_unit_loaded(CorednsExecutor.COREDNS_BUILD_UNIT)
        CorednsExecutor._append_result_action(
            actions,
            action="verify-generated-unit",
            unit=CorednsExecutor.COREDNS_BUILD_UNIT,
            result=generated,
        )

        build = CorednsExecutor.start_unit(CorednsExecutor.COREDNS_BUILD_UNIT)
        CorednsExecutor._append_result_action(
            actions,
            action="start",
            service=CorednsExecutor.COREDNS_BUILD_UNIT,
            result=build,
        )

        install = CorednsExecutor.start_unit(CorednsExecutor.COREDNS_INSTALL_UNIT)
        CorednsExecutor._append_result_action(
            actions,
            action="start",
            service=CorednsExecutor.COREDNS_INSTALL_UNIT,
            result=install,
        )

        CorednsExecutor.verify_coredns_binary(CorednsExecutor.COREDNS_BINARY_PATH)
        actions.append(
            {
                "action": "verify-binary",
                "path": CorednsExecutor.COREDNS_BINARY_PATH.as_posix(),
                "success": True,
                "return_code": 0,
            }
        )

    @staticmethod
    def _run_runtime_service_action(
        actions: list[dict[str, Any]],
        *,
        config_changed: bool,
        build_inputs_changed: bool,
    ) -> None:
        """Choose and run the CoreDNS runtime action after files are synchronized."""
        if build_inputs_changed:
            CorednsExecutor._run_build_install_transaction(actions)
            restart = CorednsExecutor.restart_coredns_service()
            CorednsExecutor._append_result_action(
                actions,
                action="restart",
                service="coredns.service",
                result=restart,
            )
            return

        if config_changed:
            restart = CorednsExecutor.restart_coredns_service()
            CorednsExecutor._append_result_action(
                actions,
                action="restart",
                service="coredns.service",
                result=restart,
            )
            return

        ready_before = CorednsExecutor.wait_coredns_active()
        CorednsExecutor._append_result_action(
            actions,
            action="wait-active",
            service="coredns.service",
            result=ready_before,
        )
        reload_result = CorednsExecutor.reload_coredns_service()
        CorednsExecutor._append_result_action(
            actions,
            action="reload",
            service="coredns.service",
            result=reload_result,
        )

    @staticmethod
    def apply_transaction(
        *,
        config_changed: bool,
        zone_writes: list[dict[str, Any]],
        zone_removals: list[dict[str, Any]],
        build_inputs_changed: bool = False,
    ) -> dict[str, Any]:
        """Apply one serialized CoreDNS runtime transaction after all file sync is complete."""
        actions: list[dict[str, Any]] = []
        zones = CorednsExecutor._collect_zone_changes(actions, zone_writes, zone_removals)

        if (
            not build_inputs_changed
            and not config_changed
            and not zone_writes
            and not zone_removals
        ):
            return {
                "kind": "coredns.transaction",
                "zones": [],
                "actions": [],
            }

        stop_watcher = CorednsExecutor.stop_zone_watcher()
        CorednsExecutor._append_result_action(
            actions,
            action="stop",
            service="coredns-zones.path",
            result=stop_watcher,
        )

        try:
            CorednsExecutor._run_runtime_service_action(
                actions,
                config_changed=config_changed,
                build_inputs_changed=build_inputs_changed,
            )

            ready_after = CorednsExecutor.wait_coredns_active()
            CorednsExecutor._append_result_action(
                actions,
                action="wait-active",
                service="coredns.service",
                result=ready_after,
            )
        finally:
            start_watcher = CorednsExecutor.start_zone_watcher()
            CorednsExecutor._append_result_action(
                actions,
                action="start",
                service="coredns-zones.path",
                result=start_watcher,
            )

        return {
            "kind": "coredns.transaction",
            "zones": sorted(set(zones)),
            "config_changed": config_changed,
            "actions": actions,
        }
