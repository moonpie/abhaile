"""Users renderer for host user/group/sudo artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError

USER_SCALAR_FIELDS = ("uid", "system", "primary_group", "home", "shell", "gecos")
USER_LIST_FIELDS = ("additional_groups", "ssh_authorized_keys")


def render_users_artifacts(host: str, config_root: Path, output_dir: Path) -> None:
    """Render sysusers and sudoers artifacts for a host."""
    output_dir.mkdir(parents=True, exist_ok=True)

    merged = _merge_user_management(host, config_root)
    users = merged["users"]
    groups = merged["groups"]
    sudoers = merged["sudoers"]

    _validate_user_group_references(users, groups)

    sysusers_path = output_dir / "etc" / "sysusers.d" / "abhaile.conf"
    sudoers_path = output_dir / "etc" / "sudoers.d" / "abhaile"

    _write_sysusers_file(users, groups, sysusers_path)
    _write_sudoers_file(sudoers, sudoers_path)
    _write_authorized_keys(users, output_dir)


def _merge_user_management(host: str, config_root: Path) -> Dict[str, Any]:
    """Merge user management config across host include chain."""
    ordered_hosts = _walk_host_includes(host, config_root)

    merged_users: Dict[str, Dict[str, Any]] = {}
    merged_groups: Dict[str, Dict[str, Any]] = {}
    merged_sudoers: Dict[str, List[str]] = {}

    for host_name in ordered_hosts:
        host_path = config_root / "hosts" / host_name / "host.yaml"
        host_data = read_yaml_mapping(host_path)
        composition = host_data.get("composition", {}) or {}
        user_management = composition.get("user_management", {}) or {}
        users = user_management.get("users", {}) or {}
        groups = user_management.get("groups", {}) or {}
        sudoers = user_management.get("sudoers", []) or []

        for user_name, user_data in users.items():
            if not isinstance(user_data, dict):
                raise RenderError(f"User '{user_name}' must be a mapping: {host_path}")
            merged_users[user_name] = _merge_user_definition(
                user_name, merged_users.get(user_name), user_data, host_path
            )

        for group_name, group_data in groups.items():
            if not isinstance(group_data, dict):
                raise RenderError(f"Group '{group_name}' must be a mapping: {host_path}")
            merged_groups[group_name] = _merge_group_definition(
                group_name, merged_groups.get(group_name), group_data, host_path
            )

        for sudoer in sudoers:
            if not isinstance(sudoer, dict):
                raise RenderError(f"Sudoer entries must be mappings: {host_path}")
            name = sudoer.get("name")
            rules = sudoer.get("rules", [])
            if not isinstance(name, str) or not name:
                raise RenderError(f"Sudoer entry missing name: {host_path}")
            if not isinstance(rules, list) or any(not isinstance(item, str) for item in rules):
                raise RenderError(f"Sudoer rules must be a list of strings: {host_path}")
            merged_sudoers.setdefault(name, [])
            for rule in rules:
                if rule not in merged_sudoers[name]:
                    merged_sudoers[name].append(rule)

    return {
        "users": merged_users,
        "groups": merged_groups,
        "sudoers": merged_sudoers,
    }


def _merge_user_definition(
    user_name: str,
    existing: Dict[str, Any] | None,
    incoming: Dict[str, Any],
    host_path: Path,
) -> Dict[str, Any]:
    """Merge a user definition, enforcing scalar equality and list unions."""
    merged: Dict[str, Any] = dict(existing or {})

    for field in USER_SCALAR_FIELDS:
        if field in incoming and incoming[field] is not None:
            if field in merged and merged[field] is not None and merged[field] != incoming[field]:
                raise RenderError(
                    f"User '{user_name}' field '{field}' conflict in {host_path}: "
                    f"{merged[field]} vs {incoming[field]}"
                )
            merged[field] = incoming[field]

    for field in USER_LIST_FIELDS:
        values = incoming.get(field)
        if values is None:
            continue
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise RenderError(
                f"User '{user_name}' field '{field}' must be a list of strings: {host_path}"
            )
        merged.setdefault(field, [])
        for value in values:
            if value not in merged[field]:
                merged[field].append(value)

    return merged


def _merge_group_definition(
    group_name: str,
    existing: Dict[str, Any] | None,
    incoming: Dict[str, Any],
    host_path: Path,
) -> Dict[str, Any]:
    """Merge a group definition, enforcing gid equality if redefined."""
    merged: Dict[str, Any] = dict(existing or {})
    if "gid" in incoming and incoming["gid"] is not None:
        if "gid" in merged and merged["gid"] is not None and merged["gid"] != incoming["gid"]:
            raise RenderError(
                f"Group '{group_name}' gid conflict in {host_path}: {merged['gid']} vs {incoming['gid']}"
            )
        merged["gid"] = incoming["gid"]
    return merged


def _validate_user_group_references(
    users: Dict[str, Dict[str, Any]],
    groups: Dict[str, Dict[str, Any]],
) -> None:
    """Validate that user group references exist."""
    group_names = set(groups.keys())
    errors: List[str] = []
    for user_name, user_data in users.items():
        primary_group = user_data.get("primary_group") or user_name
        if primary_group not in group_names:
            errors.append(f"User '{user_name}' primary_group '{primary_group}' is not defined")
        for grp in user_data.get("additional_groups", []) or []:
            if grp not in group_names:
                errors.append(f"User '{user_name}' additional_group '{grp}' is not defined")
    if errors:
        formatted = "\n".join(f"- {err}" for err in errors)
        raise RenderError(f"User/group reference validation failed:\n{formatted}")


def _write_sysusers_file(
    users: Dict[str, Dict[str, Any]],
    groups: Dict[str, Dict[str, Any]],
    destination: Path,
) -> None:
    """Write sysusers configuration file with deterministic ordering."""
    lines: List[str] = ["# Managed by Abhaile. Do not edit.\n"]

    for group_name in sorted(groups.keys()):
        gid = groups[group_name].get("gid")
        gid_str = str(gid) if gid is not None else "-"
        lines.append(f"g {group_name} {gid_str}\n")

    for user_name in sorted(users.keys()):
        user = users[user_name]
        uid = user.get("uid")
        uid_str = str(uid) if uid is not None else "-"
        primary_group = user.get("primary_group") or user_name
        gecos = _quote_sysusers_field(user.get("gecos") or "-")
        home = _quote_sysusers_field(user.get("home") or "-")
        shell = _quote_sysusers_field(user.get("shell") or "-")
        lines.append(f"u {user_name} {uid_str} {primary_group} {gecos} {home} {shell}\n")

        additional_groups = sorted(set(user.get("additional_groups", []) or []))
        for group_name in additional_groups:
            lines.append(f"m {user_name} {group_name}\n")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8", newline="\n")


def _quote_sysusers_field(value: str) -> str:
    """Quote sysusers fields that contain whitespace."""
    if value in {"-", ""}:
        return "-"
    if any(ch.isspace() for ch in value):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _write_sudoers_file(sudoers: Dict[str, List[str]], destination: Path) -> None:
    """Write sudoers configuration file with deterministic ordering."""
    lines: List[str] = ["# Managed by Abhaile. Do not edit.\n"]
    for name in sorted(sudoers.keys()):
        rules = sorted(set(sudoers[name]))
        for rule in rules:
            lines.append(f"{rule}\n")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8", newline="\n")


def _write_authorized_keys(users: Dict[str, Dict[str, Any]], output_dir: Path) -> None:
    """Write authorized_keys files for users with SSH keys."""
    for user_name in sorted(users.keys()):
        user = users[user_name]
        keys = sorted(set(user.get("ssh_authorized_keys", []) or []))
        if not keys:
            continue
        home = user.get("home") or f"/home/{user_name}"
        if home == "-":
            continue
        authorized_keys_path = output_dir / home.lstrip("/") / ".ssh" / "authorized_keys"
        authorized_keys_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Managed by Abhaile. Do not edit.\n"]
        lines.extend(f"{key}\n" for key in keys)
        authorized_keys_path.write_text("".join(lines), encoding="utf-8", newline="\n")


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
