"""Execution helpers for Caddy ingress artifact family (phase 7.5)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from abhaile.apply.actions import ExecutionResult, run_command, run_systemctl_command
from abhaile.utils.errors import ApplyError


class CaddyExecutor:
    """Executor for caddy.config artifacts."""

    @staticmethod
    def segment_from_owner_or_target(owner_ref: str, target_path: str) -> str:
        """Derive Caddy segment from owner_ref (preferred) or target path."""
        if owner_ref.startswith("caddy:"):
            segment = owner_ref.split(":", 1)[1]
            if segment:
                return segment

        target = Path(target_path)
        parts = target.parts
        try:
            caddy_idx = parts.index("caddy")
            segment = parts[caddy_idx + 1]
            if segment:
                return segment
        except (ValueError, IndexError):
            pass

        raise ApplyError(
            "Unable to determine caddy segment from owner/target: "
            f"owner_ref={owner_ref} target_path={target_path}"
        )

    @staticmethod
    def _validate_argv(segment: str) -> list[str]:
        podman = shutil.which("podman")
        if podman is None:
            raise ApplyError("podman is required for caddy config validation")
        return [
            podman,
            "exec",
            f"systemd-caddy-{segment}",
            "/usr/bin/caddy",
            "validate",
            "-c",
            "/etc/caddy/Caddyfile",
        ]

    @staticmethod
    def _reload_argv(segment: str) -> list[str]:
        podman = shutil.which("podman")
        if podman is None:
            raise ApplyError("podman is required for caddy config reload")
        return [
            podman,
            "exec",
            f"systemd-caddy-{segment}",
            "/usr/bin/caddy",
            "reload",
            "-c",
            "/etc/caddy/Caddyfile",
        ]

    @staticmethod
    def _container_exists_argv(segment: str) -> list[str]:
        podman = shutil.which("podman")
        if podman is None:
            raise ApplyError("podman is required for caddy config validation")
        return [podman, "container", "exists", f"systemd-caddy-{segment}"]

    @staticmethod
    def caddy_container_exists(segment: str) -> ExecutionResult:
        """Check whether the segment container exists."""
        return run_command(
            CaddyExecutor._container_exists_argv(segment),
            action_id=f"container-exists-caddy:{segment}",
            action_type="validation",
            check=False,
        )

    @staticmethod
    def validate_caddy_config(
        segment: str,
        *,
        strict: bool,
    ) -> ExecutionResult:
        """Validate active Caddyfile inside the segment container."""
        if shutil.which("podman") is None:
            if strict:
                raise ApplyError("podman is required for caddy config validation")
            return ExecutionResult(
                action_id=f"validate-caddy:{segment}",
                action_type="validation",
                success=True,
                return_code=None,
                error_message="podman missing; validation skipped",
            )

        return run_command(
            CaddyExecutor._validate_argv(segment),
            action_id=f"validate-caddy:{segment}",
            action_type="validation",
            check=strict,
        )

    @staticmethod
    def reload_caddy_config(segment: str, *, check: bool = True) -> ExecutionResult:
        """Reload Caddy config inside the segment container."""
        return run_command(
            CaddyExecutor._reload_argv(segment),
            action_id=f"reload-caddy:{segment}",
            action_type="reload",
            check=check,
        )

    @staticmethod
    def restart_caddy_service(segment: str) -> ExecutionResult:
        """Fallback restart for the caddy segment systemd unit."""
        return run_systemctl_command("try-restart", f"caddy-{segment}.service")

    @staticmethod
    def apply_config_write(
        entry: dict[str, Any],
        target_path: str,
        *,
        allow_missing_container: bool = False,
    ) -> dict[str, Any]:
        """Apply runtime step for caddy.config writes/removals."""
        owner_ref = str(entry.get("owner_ref", ""))
        segment = CaddyExecutor.segment_from_owner_or_target(owner_ref, target_path)

        apply_hints = entry.get("apply_hints")
        if not isinstance(apply_hints, dict):
            apply_hints = {}
        restart_on_failure = bool(apply_hints.get("restart_on_failure"))

        container_exists = CaddyExecutor.caddy_container_exists(segment)
        if not container_exists.success:
            if not allow_missing_container:
                raise ApplyError(
                    f"Caddy container 'systemd-caddy-{segment}' is required for validation"
                )
            return {
                "kind": entry.get("kind", "caddy.config"),
                "segment": segment,
                "actions": [
                    {
                        "action": "validate-caddy",
                        "success": True,
                        "return_code": None,
                        "skipped": True,
                        "reason": "container missing during initial deployment",
                    },
                    {
                        "action": "reload-caddy",
                        "success": True,
                        "return_code": None,
                        "skipped": True,
                        "reason": "container missing during initial deployment",
                    },
                ],
            }

        validate = CaddyExecutor.validate_caddy_config(segment, strict=True)
        reload_result = CaddyExecutor.reload_caddy_config(segment, check=False)

        actions: list[dict[str, Any]] = [
            {
                "action": "validate-caddy",
                "success": validate.success,
                "return_code": validate.return_code,
            },
            {
                "action": "reload-caddy",
                "success": reload_result.success,
                "return_code": reload_result.return_code,
            },
        ]

        if not reload_result.success:
            if not restart_on_failure:
                raise ApplyError(
                    f"Caddy reload failed for segment '{segment}': "
                    f"{reload_result.error_message or reload_result.stderr.strip()}"
                )
            restart_result = CaddyExecutor.restart_caddy_service(segment)
            actions.append(
                {
                    "action": "try-restart",
                    "service": f"caddy-{segment}.service",
                    "success": restart_result.success,
                    "return_code": restart_result.return_code,
                }
            )

        return {
            "kind": entry.get("kind", "caddy.config"),
            "segment": segment,
            "actions": actions,
        }
