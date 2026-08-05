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
    def image_exists(
        image_ref: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> bool:
        """Return True when an image reference exists in the target Podman storage."""
        podman = QuadletExecutor._podman_binary()
        result = run_command(
            [podman, "image", "exists", image_ref],
            action_id=f"podman-image-exists:{image_ref}",
            action_type="podman",
            run_as_user=run_as_user if rootless else None,
            check=False,
        )
        return result.success

    @staticmethod
    def inspect_image(
        image_ref: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> dict[str, Any]:
        """Inspect a local image reference in the target Podman storage."""
        podman = QuadletExecutor._podman_binary()
        result = run_command(
            [podman, "image", "inspect", image_ref, "--format", "{{.Id}} {{.Digest}}"],
            action_id=f"podman-image-inspect:{image_ref}",
            action_type="podman",
            run_as_user=run_as_user if rootless else None,
            check=True,
        )
        parts = result.stdout.strip().split(maxsplit=1)
        payload: dict[str, Any] = {
            "image": image_ref,
            "image_id": parts[0] if parts else "",
        }
        if len(parts) > 1 and parts[1] != "<nil>":
            payload["digest"] = parts[1]
        return payload

    @staticmethod
    def pre_pull_image(
        image_ref: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> dict[str, Any]:
        """Pull and verify an image before a Quadlet container update is staged."""
        podman = QuadletExecutor._podman_binary()
        pull = run_command(
            [podman, "pull", image_ref],
            action_id=f"podman-pull:{image_ref}",
            action_type="podman",
            run_as_user=run_as_user if rootless else None,
            check=False,
        )
        if not pull.success:
            raise ApplyError(
                "image pre-pull failed "
                f"desired={image_ref} scope={'rootless' if rootless else 'rootful'} "
                f"exit={pull.return_code} error={pull.error_message}"
            )
        if not QuadletExecutor.image_exists(
            image_ref,
            rootless=rootless,
            run_as_user=run_as_user,
        ):
            raise ApplyError(f"Pulled image is not visible locally: {image_ref}")
        inspect = QuadletExecutor.inspect_image(
            image_ref,
            rootless=rootless,
            run_as_user=run_as_user,
        )
        return {
            "action": "pre-pull",
            "image": image_ref,
            "scope": "rootless" if rootless else "rootful",
            "run_as_user": run_as_user if rootless else None,
            "success": True,
            "return_code": pull.return_code,
            **inspect,
        }

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
    def verify_generated_unit(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> ExecutionResult:
        """Verify systemd loaded the unit generated from a Quadlet source file."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
            if run_as_user:
                argv.extend(["-M", f"{run_as_user}@"])
                run_as_user = None
        argv.extend(["show", unit_name, "--property=LoadState", "--value"])
        result = run_command(
            argv,
            action_id=f"verify-generated-unit:{unit_name}",
            action_type="validation",
            run_as_user=run_as_user if rootless else None,
            check=True,
        )
        if result.stdout.strip() != "loaded":
            raise ApplyError(
                f"Quadlet generation failed for {unit_name}: "
                f"systemd LoadState={result.stdout.strip() or 'unknown'} after daemon-reload"
            )
        return result

    @staticmethod
    def reset_failed_unit(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> ExecutionResult:
        """Reset failed state for one obsolete generated unit if systemd still knows it."""
        result = run_systemctl_command(
            "reset-failed",
            unit_name,
            user=rootless,
            run_as_user=run_as_user if rootless else None,
            check=False,
        )
        if result.success:
            return result
        not_loaded = "not loaded" in f"{result.error_message}\n{result.stderr}".lower()
        if not_loaded:
            return ExecutionResult(
                action_id=result.action_id,
                action_type=result.action_type,
                success=True,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error_message=result.error_message,
            )

        load_state = QuadletExecutor.get_unit_load_state(
            unit_name,
            rootless=rootless,
            run_as_user=run_as_user,
        )
        if load_state != "loaded":
            return ExecutionResult(
                action_id=result.action_id,
                action_type=result.action_type,
                success=True,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        raise ApplyError(
            f"Failed to reset failed state for loaded unit {unit_name}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'unknown systemd error'}"
        )

    @staticmethod
    def get_unit_load_state(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> str:
        """Return systemd LoadState for a unit in the target manager."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
            if run_as_user:
                argv.extend(["-M", f"{run_as_user}@"])
                run_as_user = None
        argv.extend(["show", unit_name, "--property=LoadState", "--value"])
        result = run_command(
            argv,
            action_id=f"show-load-state:{unit_name}",
            action_type="validation",
            run_as_user=run_as_user if rootless else None,
            check=False,
        )
        load_state = result.stdout.strip()
        if result.success or load_state:
            return load_state or "unknown"
        raise ApplyError(
            f"Failed to query LoadState for {unit_name}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'unknown systemd error'}"
        )

    @staticmethod
    def stop_obsolete_image_unit(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> ExecutionResult:
        """Stop an obsolete generated image unit, accepting an already-unloaded unit."""
        argv = ["systemctl"]
        command_user = run_as_user
        if rootless:
            argv.append("--user")
            if command_user:
                argv.extend(["-M", f"{command_user}@"])
                command_user = None
        argv.extend(["stop", unit_name])
        result = run_command(
            argv,
            action_id=f"systemctl stop {unit_name}",
            action_type="systemctl",
            run_as_user=command_user if rootless else None,
            check=False,
        )
        not_loaded = "not loaded" in f"{result.error_message}\n{result.stderr}".lower()
        if result.success or not_loaded:
            return ExecutionResult(
                action_id=result.action_id,
                action_type=result.action_type,
                success=True,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        raise ApplyError(
            f"Command failed ({result.action_id}): "
            f"exit={result.return_code} error={result.error_message}"
        )

    @staticmethod
    def verify_unit_unloaded(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> ExecutionResult:
        """Verify an obsolete generated unit is no longer loaded."""
        load_state = QuadletExecutor.get_unit_load_state(
            unit_name,
            rootless=rootless,
            run_as_user=run_as_user,
        )
        if load_state == "loaded":
            raise ApplyError(f"Obsolete generated image unit remains loaded: {unit_name}")
        return ExecutionResult(
            action_id=f"verify-obsolete-unit-unloaded:{unit_name}",
            action_type="validation",
            success=True,
            return_code=0,
            stdout=f"{load_state}\n",
        )

    @staticmethod
    def unit_is_active(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> bool:
        """Return True when systemd reports a unit active in the target manager."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
            if run_as_user:
                argv.extend(["-M", f"{run_as_user}@"])
                run_as_user = None
        argv.extend(["is-active", "--quiet", unit_name])
        result = run_command(
            argv,
            action_id=f"systemctl-is-active:{unit_name}",
            action_type="validation",
            run_as_user=run_as_user if rootless else None,
            check=False,
        )
        return result.success

    @staticmethod
    def verify_unit_active(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> ExecutionResult:
        """Require a unit to be active in the target systemd manager."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
            if run_as_user:
                argv.extend(["-M", f"{run_as_user}@"])
                run_as_user = None
        argv.extend(["is-active", "--quiet", unit_name])
        return run_command(
            argv,
            action_id=f"verify-unit-active:{unit_name}",
            action_type="validation",
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
        daemon_reloaded: bool = False,
        verify_unit: bool = False,
    ) -> dict[str, Any]:
        """Converge runtime state for a quadlet owner."""
        if restart_mode not in {"try-restart", "manual"}:
            raise ApplyError(f"Unsupported quadlet restart_mode: {restart_mode}")

        unit_name = QuadletExecutor.unit_from_owner(owner_ref)
        actions: list[dict[str, Any]] = []

        kinds_set = set(kinds)
        only_remove = changed_phases == {"remove"}
        obsolete_image_remove = only_remove and "quadlet.image" in kinds_set
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

        if obsolete_image_remove:
            stop = QuadletExecutor.stop_obsolete_image_unit(
                unit_name,
                rootless=rootless,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "stop",
                    "unit": unit_name,
                    "success": stop.success,
                    "return_code": stop.return_code,
                    "idempotent_noop": stop.return_code != 0,
                }
            )

        if not daemon_reloaded:
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
        else:
            actions.append(
                {
                    "action": "daemon-reload",
                    "success": True,
                    "return_code": 0,
                    "scope": "batch",
                }
            )

        if verify_unit and not only_remove:
            verify = QuadletExecutor.verify_generated_unit(
                unit_name,
                rootless=rootless,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "verify-generated-unit",
                    "unit": unit_name,
                    "success": verify.success,
                    "return_code": verify.return_code,
                }
            )

        if only_remove:
            if obsolete_image_remove:
                reset = QuadletExecutor.reset_failed_unit(
                    unit_name,
                    rootless=rootless,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "reset-failed",
                        "unit": unit_name,
                        "success": reset.success,
                        "return_code": reset.return_code,
                    }
                )
                unloaded = QuadletExecutor.verify_unit_unloaded(
                    unit_name,
                    rootless=rootless,
                    run_as_user=run_as_user,
                )
                actions.append(
                    {
                        "action": "verify-unloaded",
                        "unit": unit_name,
                        "success": unloaded.success,
                        "return_code": unloaded.return_code,
                    }
                )
            else:
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
            was_active = QuadletExecutor.unit_is_active(
                unit_name,
                rootless=rootless,
                run_as_user=run_as_user,
            )
            action = "restart" if was_active else "start"
            restart = run_systemctl_command(
                action,
                unit_name,
                user=rootless,
                run_as_user=run_as_user if rootless else None,
            )
            actions.append(
                {
                    "action": action,
                    "unit": unit_name,
                    "was_active": was_active,
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
