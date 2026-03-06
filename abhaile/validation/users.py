"""User management validation: uid/gid conflicts across host includes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError


def validate_user_management_ids(host: str, config_root: Path) -> None:
    """Validate user management config across host includes.

    Args:
        host: Host name (e.g., phobos, deimos).
        config_root: Root of config/ directory.

    Raises:
        RenderError: If duplicate uid/gid values are detected.
    """
    ordered_hosts = _walk_host_includes(host, config_root)

    uid_to_users: Dict[int, List[str]] = {}
    gid_to_groups: Dict[int, List[str]] = {}
    user_to_uid: Dict[str, int] = {}
    group_to_gid: Dict[str, int] = {}
    user_scalars: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for host_name in ordered_hosts:
        host_path = config_root / "hosts" / host_name / "host.yaml"
        host_data = read_yaml_mapping(host_path)
        composition = host_data.get("composition", {}) or {}
        user_management = composition.get("user_management", {}) or {}
        users = user_management.get("users", {}) or {}
        groups = user_management.get("groups", {}) or {}

        for user_name, user_data in users.items():
            if not isinstance(user_data, dict):
                continue
            existing = user_scalars.get(user_name, {})
            for field in ("uid", "system", "primary_group", "home", "shell", "gecos"):
                if field in user_data and user_data[field] is not None:
                    if field in existing and existing[field] is not None:
                        if existing[field] != user_data[field]:
                            errors.append(
                                f"User '{user_name}' field '{field}' conflicts: {existing[field]} vs {user_data[field]}"
                            )
                    existing[field] = user_data[field]
            for field in ("additional_groups", "ssh_authorized_keys"):
                value = user_data.get(field)
                if value is None:
                    continue
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    errors.append(f"User '{user_name}' field '{field}' must be a list of strings")
            user_scalars[user_name] = existing
            uid = user_data.get("uid")
            if uid is None:
                continue
            if user_name in user_to_uid and user_to_uid[user_name] != uid:
                errors.append(
                    f"User '{user_name}' has conflicting uid values: {user_to_uid[user_name]} vs {uid}"
                )
            user_to_uid[user_name] = uid
            uid_to_users.setdefault(uid, []).append(user_name)

        for group_name, group_data in groups.items():
            if not isinstance(group_data, dict):
                continue
            gid = group_data.get("gid")
            if gid is None:
                continue
            if group_name in group_to_gid and group_to_gid[group_name] != gid:
                errors.append(
                    f"Group '{group_name}' has conflicting gid values: {group_to_gid[group_name]} vs {gid}"
                )
            group_to_gid[group_name] = gid
            gid_to_groups.setdefault(gid, []).append(group_name)

    for uid, users in uid_to_users.items():
        unique_users = sorted(set(users))
        if len(unique_users) > 1:
            errors.append(f"Duplicate uid {uid} used by users: {', '.join(unique_users)}")

    for gid, groups in gid_to_groups.items():
        unique_groups = sorted(set(groups))
        if len(unique_groups) > 1:
            errors.append(f"Duplicate gid {gid} used by groups: {', '.join(unique_groups)}")

    if errors:
        formatted = "\n".join(f"- {err}" for err in errors)
        raise RenderError(f"User management id validation failed for host '{host}':\n{formatted}")


def _walk_host_includes(
    host: str,
    config_root: Path,
    *,
    visited: Set[str] | None = None,
    stack: List[str] | None = None,
) -> List[str]:
    """Return depth-first include order for host composition."""
    if visited is None:
        visited = set()
    if stack is None:
        stack = []

    if host in stack:
        cycle = " -> ".join(stack + [host])
        raise RenderError(f"Host include cycle detected: {cycle}")
    if host in visited:
        return []

    host_path = config_root / "hosts" / host / "host.yaml"
    if not host_path.exists():
        raise RenderError(f"Missing host definition: {host_path}")

    host_data = read_yaml_mapping(host_path)
    composition = host_data.get("composition", {}) or {}
    includes = composition.get("include", []) or []
    if not isinstance(includes, list) or any(not isinstance(item, str) for item in includes):
        raise RenderError(f"Host includes must be a list of strings: {host_path}")

    ordered: List[str] = []
    stack.append(host)
    for include_host in includes:
        ordered.extend(
            _walk_host_includes(
                include_host,
                config_root,
                visited=visited,
                stack=stack,
            )
        )
    stack.pop()

    visited.add(host)
    ordered.append(host)
    return ordered
