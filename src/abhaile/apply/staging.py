"""Artifact staging helpers for the apply pipeline."""

from __future__ import annotations

import grp
import logging
import os
import pwd
from pathlib import Path

from abhaile.apply.actions import (
    atomic_copy_file_with_perms,
    resolve_rendered_source,
)
from abhaile.apply.users import UserManagementExecutor
from abhaile.models.kinds import KIND_FAMILIES
from abhaile.utils.errors import ApplyError

LOG = logging.getLogger(__name__)
_USER_KINDS = KIND_FAMILIES["user"]
_DEFAULT_FILE_MODE = 0o644


def _required_user_hints(entry: dict[str, object]) -> tuple[str, str, int, int | None]:
    """Extract required owner/group/mode hints for user-managed artifacts."""
    apply_hints = entry.get("apply_hints")
    if not isinstance(apply_hints, dict):
        raise ApplyError("Missing apply_hints for user-managed artifact")

    owner_user = apply_hints.get("owner_user")
    owner_group = apply_hints.get("owner_group")
    mode_raw = apply_hints.get("mode")
    ssh_dir_mode_raw = apply_hints.get("ssh_dir_mode")

    if not isinstance(owner_user, str) or not owner_user:
        raise ApplyError("Missing owner_user in apply_hints for user-managed artifact")
    if not isinstance(owner_group, str) or not owner_group:
        raise ApplyError("Missing owner_group in apply_hints for user-managed artifact")
    if not isinstance(mode_raw, str) or not mode_raw:
        raise ApplyError("Missing mode in apply_hints for user-managed artifact")

    try:
        mode = int(mode_raw, 8)
    except ValueError as exc:
        raise ApplyError(f"Invalid mode hint: {mode_raw}") from exc

    ssh_dir_mode: int | None = None
    if ssh_dir_mode_raw is not None:
        if not isinstance(ssh_dir_mode_raw, str) or not ssh_dir_mode_raw:
            raise ApplyError("Invalid ssh_dir_mode in apply_hints")
        try:
            ssh_dir_mode = int(ssh_dir_mode_raw, 8)
        except ValueError as exc:
            raise ApplyError(f"Invalid ssh_dir_mode hint: {ssh_dir_mode_raw}") from exc

    return owner_user, owner_group, mode, ssh_dir_mode


def _prepare_authorized_keys_parent(
    target: Path,
    *,
    owner_user: str,
    owner_group: str,
    ssh_dir_mode: int,
) -> None:
    """Prepare ~/.ssh parent directory with strict ownership and mode."""
    ssh_dir = target.parent
    ssh_dir.mkdir(parents=True, exist_ok=True)
    ssh_dir.chmod(ssh_dir_mode)
    try:
        uid = pwd.getpwnam(owner_user).pw_uid
        gid = grp.getgrnam(owner_group).gr_gid
    except KeyError as exc:
        raise ApplyError(
            f"Unable to resolve owner/group for authorized_keys: {owner_user}:{owner_group}"
        ) from exc

    try:
        os.chown(ssh_dir, uid, gid)
    except OSError as exc:
        raise ApplyError(f"Failed to set ownership on {ssh_dir}: {exc}") from exc


def _default_file_hints(entry: dict[str, object]) -> tuple[str, str, int]:
    """Return default owner/group/mode for apply-managed non-user artifacts."""
    apply_hints = entry.get("apply_hints")
    if isinstance(apply_hints, dict) and bool(apply_hints.get("rootless")):
        podman_user = apply_hints.get("podman_user")
        if not isinstance(podman_user, str) or not podman_user:
            raise ApplyError("Rootless artifact missing podman_user in apply_hints")
        return podman_user, podman_user, _DEFAULT_FILE_MODE
    return "root", "root", _DEFAULT_FILE_MODE


def _copy_artifact_for_apply(action: dict[str, object], rendered_dir: Path) -> None:
    """Copy artifact for apply, using strict policy for user-managed kinds."""
    render_path = action.get("render_path")
    target_path = action.get("target_path")
    kind = action.get("kind")
    if not isinstance(render_path, str) or not isinstance(target_path, str):
        raise ApplyError("Write action missing render_path/target_path")
    if not isinstance(kind, str):
        raise ApplyError("Write action missing kind")

    LOG.debug("staging.copy kind=%s target=%s", kind, target_path)

    if action.get("is_directory") is True or kind == "service.directory":
        return

    source = resolve_rendered_source(rendered_dir, render_path)
    target = Path(target_path)

    if kind in _USER_KINDS:
        owner_user, owner_group, mode, ssh_dir_mode = _required_user_hints(action)

        if kind == "host.sudoers":
            UserManagementExecutor.validate_sudoers(source)

        if kind == "host.authorized_keys":
            if ssh_dir_mode is None:
                raise ApplyError("Missing ssh_dir_mode in apply_hints for host.authorized_keys")
            _prepare_authorized_keys_parent(
                target,
                owner_user=owner_user,
                owner_group=owner_group,
                ssh_dir_mode=ssh_dir_mode,
            )

        atomic_copy_file_with_perms(
            source,
            target,
            mode=mode,
            owner_user=owner_user,
            owner_group=owner_group,
        )
        return

    owner_user, owner_group, mode = _default_file_hints(action)
    atomic_copy_file_with_perms(
        source,
        target,
        mode=mode,
        owner_user=owner_user,
        owner_group=owner_group,
    )
