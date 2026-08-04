"""Shared validation scope helpers for systemd and Quadlet targets."""

from __future__ import annotations

from pathlib import Path

from abhaile.models.kinds import KIND_FAMILIES
from abhaile.utils.errors import ApplyError

_SYSTEMD_VERIFY_KINDS = {"systemd.unit", "systemd.dropin"}
_QUADLET_KINDS = KIND_FAMILIES["quadlet"]
_ROOTFUL_SYSTEMD_PREFIX = "/etc/systemd/system/"
_ROOTFUL_QUADLET_PREFIX = "/etc/containers/systemd/"


def rootless_user_from_target_path(target_path: str) -> str | None:
    """Extract the rootless user from a user-level target path."""
    if not target_path.startswith("/home/"):
        return None

    parts = Path(target_path).parts
    if len(parts) < 6:
        return None

    user = parts[2]

    if parts[:5] == ("/", "home", user, ".config", "containers") and len(parts) >= 7:
        if parts[5] == "systemd":
            return user

    if parts[:5] == ("/", "home", user, ".config", "systemd") and len(parts) >= 7:
        if parts[5] == "user":
            return user

    return None


def is_quadlet_target_path(target_path: str) -> bool:
    """Return True for rootful or rootless Quadlet target paths."""
    if target_path.startswith(_ROOTFUL_QUADLET_PREFIX):
        return True
    return "/.config/containers/systemd/" in target_path


def validation_context_for_entry(
    *, kind: str, target_path: str, apply_hints: object
) -> tuple[bool, str | None] | None:
    """Resolve validation context as ``(rootless, user)`` when applicable."""
    if kind in _SYSTEMD_VERIFY_KINDS:
        user_from_path = rootless_user_from_target_path(target_path)
        if user_from_path is not None:
            return (True, user_from_path)
        if target_path.startswith(_ROOTFUL_SYSTEMD_PREFIX) or "/etc/systemd/system/" in target_path:
            return (False, None)
        return None

    if kind in _QUADLET_KINDS or is_quadlet_target_path(target_path):
        user_from_path = rootless_user_from_target_path(target_path)
        if user_from_path is not None:
            return (True, user_from_path)
        if target_path.startswith(_ROOTFUL_QUADLET_PREFIX):
            return (False, None)
        if isinstance(apply_hints, dict) and bool(apply_hints.get("rootless")):
            podman_user = apply_hints.get("podman_user")
            if isinstance(podman_user, str) and podman_user:
                return (True, podman_user)
            return (True, None)
        return (False, None)

    return None


def canonical_validation_target_path(
    *,
    kind: str,
    target_path: str,
    context: tuple[bool, str | None],
) -> str:
    """Map a staged target path to its canonical validation-root location."""
    rootless, user = context

    if kind in _SYSTEMD_VERIFY_KINDS:
        if rootless:
            if not user:
                raise ApplyError(f"Missing rootless user for validation target: {target_path}")
            return _rebase_target(
                target_path,
                "/.config/systemd/user/",
                f"/home/{user}/.config/systemd/user/",
            )
        return _rebase_target(target_path, "/etc/systemd/system/", "/etc/systemd/system/")

    if kind in _QUADLET_KINDS or is_quadlet_target_path(target_path):
        if rootless:
            if not user:
                raise ApplyError(f"Missing rootless user for Quadlet target: {target_path}")
            return _rebase_target(
                target_path,
                "/.config/containers/systemd/",
                f"/home/{user}/.config/containers/systemd/",
            )
        return _rebase_target(target_path, "/etc/containers/systemd/", "/etc/containers/systemd/")

    raise ApplyError(f"Unsupported validation target path: {target_path}")


def _rebase_target(target_path: str, marker: str, prefix: str) -> str:
    if marker in target_path:
        return f"{prefix}{target_path.split(marker, 1)[1]}"
    return f"{prefix}{Path(target_path).name}"
