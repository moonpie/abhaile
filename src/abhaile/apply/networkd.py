"""Execution helpers for systemd-networkd artifact family (phase 7.7)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from abhaile.apply.actions import ExecutionResult, resolve_gid, resolve_uid, run_command
from abhaile.models.directory import resolve_directory_metadata
from abhaile.utils.errors import ApplyError


class NetworkdExecutor:
    """Executor for networkd.netdev, networkd.network, and networkd.dropin artifacts."""

    @staticmethod
    def interface_from_owner_or_target(owner_ref: str, target_path: str) -> str:
        """Derive network interface from owner_ref (preferred) or target path."""
        if owner_ref.startswith("iface:"):
            iface = owner_ref.split(":", 1)[1]
            if iface:
                return iface

        name = Path(target_path).name
        if name.endswith(".conf") and ".network.d" in target_path:
            parent = Path(target_path).parent.name
            if parent.endswith(".network.d"):
                base = parent[: -len(".network.d")]
                return NetworkdExecutor._normalize_iface_name(base)

        if name.endswith(".network"):
            return NetworkdExecutor._normalize_iface_name(name[: -len(".network")])

        if name.endswith(".netdev"):
            return NetworkdExecutor._normalize_iface_name(name[: -len(".netdev")])

        raise ApplyError(
            "Unable to determine networkd interface from owner/target: "
            f"owner_ref={owner_ref} target_path={target_path}"
        )

    @staticmethod
    def _normalize_iface_name(raw: str) -> str:
        """Normalize numbered networkd filenames into interface names."""
        parts = raw.split("-", 1)
        if len(parts) == 2 and parts[0].isdigit():
            return parts[1]
        return raw

    @staticmethod
    def _networkctl_binary(strict: bool) -> str | None:
        """Resolve networkctl binary path."""
        networkctl = shutil.which("networkctl")
        if networkctl is None and strict:
            raise ApplyError("networkctl is required for systemd-networkd apply")
        return networkctl

    @staticmethod
    def _ip_binary(strict: bool) -> str | None:
        """Resolve ip binary path."""
        ip_bin = shutil.which("ip")
        if ip_bin is None and strict:
            raise ApplyError("ip is required for systemd-networkd netdev deletes")
        return ip_bin

    @staticmethod
    def validate_networkctl(*, strict: bool) -> ExecutionResult:
        """Validate networkctl availability in dry-run/apply contexts."""
        networkctl = NetworkdExecutor._networkctl_binary(strict=strict)
        if networkctl is None:
            return ExecutionResult(
                action_id="validate-networkctl",
                action_type="validation",
                success=True,
                return_code=None,
                error_message="networkctl missing; validation skipped",
            )

        return run_command(
            [networkctl, "--version"],
            action_id="validate-networkctl",
            action_type="validation",
            check=strict,
        )

    @staticmethod
    def reload_networkd() -> ExecutionResult:
        """Reload networkd configuration with networkctl reload."""
        networkctl = NetworkdExecutor._networkctl_binary(strict=True)
        assert networkctl is not None
        return run_command(
            [networkctl, "reload"],
            action_id="networkctl-reload",
            action_type="reload",
            check=True,
        )

    @staticmethod
    def reconfigure_interface(interface: str, *, strict: bool) -> ExecutionResult:
        """Reconfigure an interface using networkctl reconfigure."""
        networkctl = NetworkdExecutor._networkctl_binary(strict=True)
        assert networkctl is not None
        return run_command(
            [networkctl, "reconfigure", interface],
            action_id=f"networkctl-reconfigure:{interface}",
            action_type="reconfigure",
            check=strict,
        )

    @staticmethod
    def delete_interface(interface: str) -> ExecutionResult:
        """Delete an interface via ip link delete.

        Missing interfaces are treated as an idempotent success.
        """
        ip_bin = NetworkdExecutor._ip_binary(strict=True)
        assert ip_bin is not None
        result = run_command(
            [ip_bin, "link", "delete", interface],
            action_id=f"ip-link-delete:{interface}",
            action_type="delete",
            check=False,
        )

        missing_markers = (
            "Cannot find device",
            "No such device",
            "does not exist",
        )
        output = "\n".join([result.stderr, result.stdout])
        if not result.success and any(marker in output for marker in missing_markers):
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
                f"Failed to delete interface {interface}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        return result

    @staticmethod
    def apply_owner_change(
        owner_ref: str,
        *,
        interface: str,
        strict_reconfigure: bool,
        kinds: list[str] | None = None,
        delete_interface_first: bool = False,
        run_reconfigure: bool = True,
    ) -> dict[str, Any]:
        """Converge a networkd interface owner after writes/removals."""
        actions: list[dict[str, Any]] = []

        if delete_interface_first:
            delete_result = NetworkdExecutor.delete_interface(interface)
            actions.append(
                {
                    "action": "delete-interface",
                    "success": delete_result.success,
                    "return_code": delete_result.return_code,
                }
            )

        reload_result = NetworkdExecutor.reload_networkd()
        actions.append(
            {
                "action": "reload",
                "success": reload_result.success,
                "return_code": reload_result.return_code,
            }
        )

        if run_reconfigure:
            reconfigure_result = NetworkdExecutor.reconfigure_interface(
                interface,
                strict=strict_reconfigure,
            )
            actions.append(
                {
                    "action": "reconfigure",
                    "success": reconfigure_result.success,
                    "return_code": reconfigure_result.return_code,
                }
            )

        return {
            "owner_ref": owner_ref,
            "interface": interface,
            "kinds": sorted(set(kinds or [])),
            "actions": actions,
        }

    @staticmethod
    def apply_directory_change(
        target_path: str,
        apply_hints: dict[str, object] | None,
    ) -> dict[str, Any]:
        """Ensure a networkd drop-in directory exists with expected owner/group/mode."""
        hints = apply_hints if isinstance(apply_hints, dict) else {}
        try:
            metadata = resolve_directory_metadata("networkd.dropin", hints)
        except ValueError as exc:
            raise ApplyError(
                f"Invalid networkd directory metadata apply hint for {target_path}: {exc}"
            ) from exc

        owner = metadata.owner
        group = metadata.group
        mode = metadata.mode

        if not isinstance(owner, (str, int)) or owner == "":
            raise ApplyError(f"Invalid owner apply hint for networkd directory: {target_path}")
        if not isinstance(group, (str, int)) or group == "":
            raise ApplyError(f"Invalid group apply hint for networkd directory: {target_path}")
        if not isinstance(mode, str) or not mode:
            raise ApplyError(f"Invalid mode apply hint for networkd directory: {target_path}")

        try:
            mode_value = int(mode, 8)
        except ValueError as exc:
            raise ApplyError(
                f"Invalid directory mode apply hint ({mode}) for {target_path}"
            ) from exc

        target = Path(target_path)
        target.mkdir(parents=True, exist_ok=True)

        uid = resolve_uid(owner)
        gid = resolve_gid(group)

        try:
            os.chown(target, uid, gid)
            target.chmod(mode_value)
        except OSError as exc:
            raise ApplyError(
                f"Failed to enforce networkd directory ownership/mode for {target_path}: {exc}"
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
