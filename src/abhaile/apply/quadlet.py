"""Execution helpers for quadlet artifact family (phase 7.8)."""

from __future__ import annotations

import shutil
from typing import Any

from abhaile.apply.actions import ExecutionResult, run_command, run_systemctl_command
from abhaile.utils.errors import ApplyError


class QuadletExecutor:
    """Executor for quadlet.* artifacts."""

    ENSURE_START_KINDS = {
        "quadlet.network",
        "quadlet.volume",
        "quadlet.image",
        "quadlet.build",
    }
    ENSURE_RESTART_KINDS = {
        "quadlet.container",
        "quadlet.pod",
    }
    RECREATE_OBJECT_KINDS = {
        "quadlet.network",
        "quadlet.volume",
    }

    @staticmethod
    def unit_from_owner(owner_ref: str) -> str:
        """Extract unit name from owner ref."""
        if not owner_ref.startswith("unit:"):
            raise ApplyError(f"Invalid quadlet owner_ref: {owner_ref}")
        unit_name = owner_ref.split(":", 1)[1]
        if not unit_name:
            raise ApplyError(f"Invalid quadlet owner_ref: {owner_ref}")
        return unit_name

    @staticmethod
    def _podman_binary() -> str:
        """Resolve podman binary path."""
        podman = shutil.which("podman")
        if podman is None:
            raise ApplyError("podman is required for quadlet apply")
        return podman

    @staticmethod
    def _podman_object_spec(owner_ref: str, kinds: set[str]) -> tuple[str, str] | None:
        """Return (object_type, object_name) for quadlet network/volume owners."""
        unit_name = QuadletExecutor.unit_from_owner(owner_ref)
        if "quadlet.network" in kinds and unit_name.endswith("-network.service"):
            stem = unit_name[: -len("-network.service")]
            return ("network", f"systemd-{stem}")
        if "quadlet.volume" in kinds and unit_name.endswith("-volume.service"):
            stem = unit_name[: -len("-volume.service")]
            return ("volume", f"systemd-{stem}")
        return None

    @staticmethod
    def remove_podman_object(
        owner_ref: str,
        *,
        kinds: set[str],
        rootless: bool,
        run_as_user: str | None,
    ) -> ExecutionResult:
        """Remove a generated Podman network/volume object if present."""
        spec = QuadletExecutor._podman_object_spec(owner_ref, kinds)
        if spec is None:
            return ExecutionResult(
                action_id=f"podman-rm-skip:{owner_ref}",
                action_type="podman",
                success=True,
                return_code=0,
            )

        object_type, object_name = spec
        podman = QuadletExecutor._podman_binary()
        result = run_command(
            [podman, object_type, "rm", object_name],
            action_id=f"podman-{object_type}-rm:{object_name}",
            action_type="podman",
            run_as_user=run_as_user if rootless else None,
            check=False,
        )

        absent_markers = (
            "no such network",
            "no such volume",
            "not found",
            "no such object",
        )
        combined_output = f"{result.stderr}\n{result.stdout}".lower()
        if not result.success and any(marker in combined_output for marker in absent_markers):
            return ExecutionResult(
                action_id=result.action_id,
                action_type=result.action_type,
                success=True,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        if not result.success:
            raise ApplyError(
                f"Failed to remove Podman {object_type} object {object_name}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    @staticmethod
    def user_context_from_entries(entries: list[dict[str, Any]]) -> tuple[bool, str | None]:
        """Resolve rootless execution context from entry apply hints."""
        rootless = False
        run_as_user: str | None = None
        for entry in entries:
            hints = entry.get("apply_hints")
            if not isinstance(hints, dict):
                continue
            if bool(hints.get("rootless")):
                rootless = True
                podman_user = hints.get("podman_user")
                if isinstance(podman_user, str) and podman_user:
                    run_as_user = podman_user
        return (rootless, run_as_user)

    @staticmethod
    def validate_systemctl(
        *, rootless: bool, run_as_user: str | None, strict: bool
    ) -> ExecutionResult:
        """Run a read-only systemctl availability check."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
            if run_as_user:
                argv.extend(["-M", f"{run_as_user}@"])
                run_as_user = None
        argv.append("--version")
        return run_command(
            argv,
            action_id="validate-systemctl-user" if rootless else "validate-systemctl",
            action_type="validation",
            run_as_user=run_as_user if rootless else None,
            check=strict,
        )

    @staticmethod
    def daemon_reload(*, rootless: bool, run_as_user: str | None) -> ExecutionResult:
        """Run daemon-reload for rootful or rootless systemd scope."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
            if run_as_user:
                argv.extend(["-M", f"{run_as_user}@"])
                run_as_user = None
        argv.append("daemon-reload")
        return run_command(
            argv,
            action_id="systemctl-daemon-reload-user" if rootless else "systemctl-daemon-reload",
            action_type="systemctl",
            run_as_user=run_as_user if rootless else None,
            check=True,
        )

    @staticmethod
    def apply_convergence_action(
        owner_ref: str,
        *,
        action: str,
        rootless: bool,
        run_as_user: str | None,
    ) -> dict[str, Any]:
        """Apply a planner-emitted stop/start convergence action for a dependent owner."""
        if action not in {"stop", "start", "try-restart"}:
            raise ApplyError(f"Unsupported quadlet convergence action: {action}")

        unit_name = QuadletExecutor.unit_from_owner(owner_ref)
        result = run_systemctl_command(
            action,
            unit_name,
            user=rootless,
            run_as_user=run_as_user if rootless else None,
        )
        payload: dict[str, Any] = {
            "owner_ref": owner_ref,
            "unit": unit_name,
            "action": action,
            "success": result.success,
            "return_code": result.return_code,
        }
        if rootless and run_as_user:
            payload["run_as_user"] = run_as_user
        return payload

    @staticmethod
    def apply_owner_change(
        owner_ref: str,
        *,
        kinds: list[str],
        changed_phases: set[str],
        rootless: bool,
        run_as_user: str | None,
        restart_mode: str = "try-restart",
    ) -> dict[str, Any]:
        """Converge runtime state for a quadlet owner."""
        if restart_mode not in {"try-restart", "manual"}:
            raise ApplyError(f"Unsupported quadlet restart_mode: {restart_mode}")

        unit_name = QuadletExecutor.unit_from_owner(owner_ref)
        actions: list[dict[str, Any]] = []

        kinds_set = set(kinds)
        only_remove = changed_phases == {"remove"}
        recreate_object = bool(kinds_set & QuadletExecutor.RECREATE_OBJECT_KINDS)

        if recreate_object and not only_remove:
            remove_object = QuadletExecutor.remove_podman_object(
                owner_ref,
                kinds=kinds_set,
                rootless=rootless,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "remove-object",
                    "success": remove_object.success,
                    "return_code": remove_object.return_code,
                }
            )

        reload_result = QuadletExecutor.daemon_reload(
            rootless=rootless,
            run_as_user=run_as_user,
        )
        actions.append(
            {
                "action": "daemon-reload",
                "success": reload_result.success,
                "return_code": reload_result.return_code,
            }
        )

        if only_remove:
            stop = run_systemctl_command(
                "stop",
                unit_name,
                user=rootless,
                run_as_user=run_as_user if rootless else None,
            )
            actions.append(
                {
                    "action": "stop",
                    "unit": unit_name,
                    "success": stop.success,
                    "return_code": stop.return_code,
                }
            )
            if recreate_object:
                remove_object = QuadletExecutor.remove_podman_object(
                    owner_ref,
                    kinds=kinds_set,
                    rootless=rootless,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "remove-object",
                        "success": remove_object.success,
                        "return_code": remove_object.return_code,
                    }
                )
        elif kinds_set & QuadletExecutor.ENSURE_START_KINDS:
            start = run_systemctl_command(
                "start",
                unit_name,
                user=rootless,
                run_as_user=run_as_user if rootless else None,
            )
            actions.append(
                {
                    "action": "start",
                    "unit": unit_name,
                    "success": start.success,
                    "return_code": start.return_code,
                }
            )
        elif restart_mode == "manual":
            actions.append(
                {
                    "action": "skip-restart",
                    "unit": unit_name,
                    "reason": "manual-restart",
                    "success": True,
                    "return_code": 0,
                }
            )
        else:
            restart = run_systemctl_command(
                "try-restart",
                unit_name,
                user=rootless,
                run_as_user=run_as_user if rootless else None,
            )
            actions.append(
                {
                    "action": "try-restart",
                    "unit": unit_name,
                    "success": restart.success,
                    "return_code": restart.return_code,
                }
            )

        summary: dict[str, Any] = {
            "owner_ref": owner_ref,
            "unit": unit_name,
            "kinds": sorted(kinds_set),
            "rootless": rootless,
            "restart_mode": restart_mode,
            "actions": actions,
        }
        if rootless and run_as_user:
            summary["run_as_user"] = run_as_user
        return summary
