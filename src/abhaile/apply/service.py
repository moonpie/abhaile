"""Execution helpers for service-owned config/env artifacts."""

from __future__ import annotations

import grp
import os
import pwd
from pathlib import Path
from typing import Any

from abhaile.apply.actions import run_command, run_systemctl_command
from abhaile.utils.errors import ApplyError


class ServiceConfigExecutor:
    """Executor for service.config and service.env post-write actions."""

    @staticmethod
    def apply_owner_change(
        owner_ref: str,
        writes: list[dict[str, object]],
        removals: list[dict[str, object]],
        apply_hints: dict[str, object] | None,
    ) -> dict[str, Any]:
        """Apply post-write convergence for a service owner group."""
        hints = apply_hints if isinstance(apply_hints, dict) else {}
        restart_unit = hints.get("restart_unit")

        if restart_unit is not None and not isinstance(restart_unit, str):
            raise ApplyError(f"Invalid restart_unit apply hint for {owner_ref}")

        rootless = bool(hints.get("rootless"))
        run_as_user: str | None = None
        if rootless:
            podman_user = hints.get("podman_user")
            if not isinstance(podman_user, str) or not podman_user:
                raise ApplyError(f"Missing podman_user for rootless service owner {owner_ref}")
            run_as_user = podman_user

        actions: list[dict[str, object]] = []

        if isinstance(restart_unit, str) and restart_unit and writes:
            restart_result = run_systemctl_command(
                "try-restart",
                restart_unit,
                user=rootless,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "try-restart",
                    "unit": restart_unit,
                    "success": restart_result.success,
                    "return_code": restart_result.return_code,
                }
            )

            active_state = ServiceConfigExecutor._active_state(
                restart_unit,
                rootless=rootless,
                run_as_user=run_as_user,
            )
            actions.append(
                {
                    "action": "validate-active",
                    "unit": restart_unit,
                    "active_state": active_state,
                    "success": active_state == "active",
                    "return_code": 0,
                }
            )
            if active_state != "active":
                raise ApplyError(
                    f"Service unit is not active after restart ({restart_unit}): state={active_state}"
                )

        return {
            "owner_ref": owner_ref,
            "restart_unit": restart_unit,
            "rootless": rootless,
            "run_as_user": run_as_user,
            "writes": len(writes),
            "removals": len(removals),
            "actions": actions,
        }

    @staticmethod
    def _active_state(
        unit_name: str,
        *,
        rootless: bool,
        run_as_user: str | None,
    ) -> str:
        """Query systemd ActiveState for a unit."""
        argv = ["systemctl"]
        if rootless:
            argv.append("--user")
        argv.extend(["show", unit_name, "-p", "ActiveState", "--value"])
        result = run_command(
            argv,
            action_id=f"systemctl show {unit_name}",
            action_type="systemctl",
            run_as_user=run_as_user,
        )
        return result.stdout.strip()

    @staticmethod
    def apply_directory_change(
        target_path: str,
        apply_hints: dict[str, object] | None,
    ) -> dict[str, Any]:
        """Ensure a service.directory target exists with expected owner/group/mode."""
        hints = apply_hints if isinstance(apply_hints, dict) else {}
        owner = hints.get("owner", "root")
        group = hints.get("group", "root")
        mode = hints.get("mode", "0750")

        if not isinstance(owner, str) or not owner:
            raise ApplyError(f"Invalid owner apply hint for service directory: {target_path}")
        if not isinstance(group, str) or not group:
            raise ApplyError(f"Invalid group apply hint for service directory: {target_path}")
        if not isinstance(mode, str) or not mode:
            raise ApplyError(f"Invalid mode apply hint for service directory: {target_path}")

        try:
            mode_value = int(mode, 8)
        except ValueError as exc:
            raise ApplyError(
                f"Invalid directory mode apply hint ({mode}) for {target_path}"
            ) from exc

        target = Path(target_path)
        target.mkdir(parents=True, exist_ok=True)

        try:
            uid = pwd.getpwnam(owner).pw_uid
            gid = grp.getgrnam(group).gr_gid
        except KeyError as exc:
            raise ApplyError(
                f"Unable to resolve service.directory owner/group for {target_path}: {owner}:{group}"
            ) from exc

        try:
            os.chown(target, uid, gid)
            target.chmod(mode_value)
        except OSError as exc:
            raise ApplyError(
                f"Failed to enforce service.directory ownership/mode for {target_path}: {exc}"
            ) from exc

        return {
            "target_path": target_path,
            "owner": owner,
            "group": group,
            "mode": mode,
            "actions": [
                {
                    "action": "ensure-directory",
                    "success": True,
                    "return_code": 0,
                }
            ],
        }
