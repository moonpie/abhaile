"""Generic managed Quadlet build transaction executor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from abhaile.apply.actions import ExecutionResult, run_systemctl_command
from abhaile.apply.quadlet import QuadletExecutor
from abhaile.utils.errors import ApplyError


class ManagedBuildExecutor:
    """Execute manifest-declared managed build transactions."""

    @staticmethod
    def _append(
        actions: list[dict[str, Any]],
        action: str,
        result: ExecutionResult,
        *,
        unit: str | None = None,
        image: str | None = None,
        path: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "action": action,
            "success": result.success,
            "return_code": result.return_code,
        }
        if unit is not None:
            payload["unit"] = unit
        if image is not None:
            payload["image"] = image
        if path is not None:
            payload["path"] = path
        actions.append(payload)

    @staticmethod
    def verify_file_executable(path: str) -> None:
        """Verify a post-build installed artifact exists and is executable."""
        artifact = Path(path)
        if not artifact.exists() or not artifact.is_file():
            raise ApplyError(f"Managed build post-build verification failed: missing {path}")
        if not os.access(artifact, os.X_OK):
            raise ApplyError(f"Managed build post-build verification failed: not executable {path}")

    @staticmethod
    def run_transaction(action: dict[str, Any]) -> dict[str, Any]:
        """Run one build, output verification, optional post-build, and consumer restart."""
        output_image = action.get("output_image")
        build_unit = action.get("build_unit")
        scope = action.get("scope")
        rootless = scope == "rootless"
        run_as_user_obj = action.get("run_as_user")
        run_as_user = run_as_user_obj if rootless and isinstance(run_as_user_obj, str) else None
        if not isinstance(output_image, str) or not output_image:
            raise ApplyError("Managed build transaction missing output_image")
        if not isinstance(build_unit, str) or not build_unit:
            raise ApplyError("Managed build transaction missing build_unit")

        actions: list[dict[str, Any]] = []
        reload_result = QuadletExecutor.daemon_reload(rootless=rootless, run_as_user=run_as_user)
        ManagedBuildExecutor._append(actions, "daemon-reload", reload_result)

        generated = QuadletExecutor.verify_generated_unit(
            build_unit,
            rootless=rootless,
            run_as_user=run_as_user,
        )
        ManagedBuildExecutor._append(actions, "verify-generated-unit", generated, unit=build_unit)

        build = run_systemctl_command("start", build_unit, user=rootless, run_as_user=run_as_user)
        ManagedBuildExecutor._append(actions, "start-build", build, unit=build_unit)

        if not QuadletExecutor.image_exists(
            output_image,
            rootless=rootless,
            run_as_user=run_as_user,
        ):
            raise ApplyError(f"Managed build output image is not visible locally: {output_image}")
        inspect = QuadletExecutor.inspect_image(
            output_image,
            rootless=rootless,
            run_as_user=run_as_user,
        )
        actions.append(
            {
                "action": "verify-output-image",
                "image": output_image,
                "success": True,
                "return_code": 0,
                **inspect,
            }
        )

        post_build = action.get("post_build")
        if isinstance(post_build, dict):
            install_unit = post_build.get("install_unit")
            if isinstance(install_unit, str) and install_unit:
                install = run_systemctl_command(
                    "start",
                    install_unit,
                    user=rootless,
                    run_as_user=run_as_user,
                )
                ManagedBuildExecutor._append(actions, "post-build", install, unit=install_unit)
            verify_binary = post_build.get("verify_binary")
            if isinstance(verify_binary, str) and verify_binary:
                ManagedBuildExecutor.verify_file_executable(verify_binary)
                actions.append(
                    {
                        "action": "verify-installed-artifact",
                        "path": verify_binary,
                        "success": True,
                        "return_code": 0,
                    }
                )

        consumers_obj = action.get("consumers", [])
        consumers = (
            [unit for unit in consumers_obj if isinstance(unit, str)]
            if isinstance(consumers_obj, list)
            else []
        )
        for unit in consumers:
            restart = run_systemctl_command("restart", unit, user=rootless, run_as_user=run_as_user)
            ManagedBuildExecutor._append(actions, "restart-consumer", restart, unit=unit)

        return {
            **action,
            "result": "built",
            "output_image": output_image,
            "live_service_unchanged": False,
            "actions": actions,
        }
