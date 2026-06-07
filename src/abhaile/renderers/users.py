"""Users renderer for host user/group/sudo artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.composition import walk_host_includes
from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError

USER_SCALAR_FIELDS = ("uid", "system", "primary_group", "home", "shell", "gecos")
USER_LIST_FIELDS = ("additional_groups", "ssh_authorized_keys")


def render_users_artifacts(
    host: str,
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
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
    _register_users_artifact(
        collector=collector,
        rendered_root=rendered_root,
        output_path=sysusers_path,
        target_path="/etc/sysusers.d/abhaile.conf",
        kind="host.sysusers",
        owner_ref=f"host-users:{host}",
        content=sysusers_path.read_text(encoding="utf-8"),
        owner_description=f"host user database for {host}",
        apply_hints={
            "owner_user": "root",
            "owner_group": "root",
            "mode": "0644",
        },
    )

    _write_sudoers_file(sudoers, sudoers_path)
    _register_users_artifact(
        collector=collector,
        rendered_root=rendered_root,
        output_path=sudoers_path,
        target_path="/etc/sudoers.d/abhaile",
        kind="host.sudoers",
        owner_ref=f"host-sudoers:{host}",
        content=sudoers_path.read_text(encoding="utf-8"),
        owner_description=f"host sudo policy for {host}",
        owner_requires=[f"host-users:{host}"],
        apply_hints={
            "owner_user": "root",
            "owner_group": "root",
            "mode": "0440",
        },
    )

    _write_authorized_keys(
        users,
        output_dir,
        host=host,
        collector=collector,
        rendered_root=rendered_root,
    )


def _merge_user_management(host: str, config_root: Path) -> dict[str, Any]:
    """Merge user management config across host include chain."""
    ordered_hosts = walk_host_includes(host, config_root)

    merged_users: dict[str, dict[str, Any]] = {}
    merged_groups: dict[str, dict[str, Any]] = {}
    merged_sudoers: dict[str, list[str]] = {}

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
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    host_path: Path,
) -> dict[str, Any]:
    """Merge a user definition, enforcing scalar equality and list unions."""
    merged: dict[str, Any] = dict(existing or {})

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
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    host_path: Path,
) -> dict[str, Any]:
    """Merge a group definition, enforcing gid equality if redefined."""
    merged: dict[str, Any] = dict(existing or {})
    if "gid" in incoming and incoming["gid"] is not None:
        if "gid" in merged and merged["gid"] is not None and merged["gid"] != incoming["gid"]:
            raise RenderError(
                f"Group '{group_name}' gid conflict in {host_path}: {merged['gid']} vs {incoming['gid']}"
            )
        merged["gid"] = incoming["gid"]
    return merged


def _validate_user_group_references(
    users: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
) -> None:
    """Validate that user group references exist."""
    group_names = set(groups.keys())
    errors: list[str] = []
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
    users: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    destination: Path,
) -> None:
    """Write sysusers configuration file with deterministic ordering."""
    lines: list[str] = ["# Managed by Abhaile. Do not edit.\n"]

    for group_name in sorted(groups.keys()):
        gid = groups[group_name].get("gid")
        gid_str = str(gid) if gid is not None else "-"
        lines.append(f"g {group_name} {gid_str}\n")

    for user_name in sorted(users.keys()):
        user = users[user_name]
        uid = user.get("uid")
        uid_str = str(uid) if uid is not None else "-"
        primary_group = user.get("primary_group") or user_name
        id_field = f"{uid_str}:{primary_group}" if primary_group != user_name else uid_str
        gecos = _quote_sysusers_field(user.get("gecos") or "-")
        home = _quote_sysusers_field(user.get("home") or "-")
        shell = _quote_sysusers_field(user.get("shell") or "-")
        lines.append(f"u {user_name} {id_field} {gecos} {home} {shell}\n")

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


def _write_sudoers_file(sudoers: dict[str, list[str]], destination: Path) -> None:
    """Write sudoers configuration file with deterministic ordering."""
    lines: list[str] = ["# Managed by Abhaile. Do not edit.\n"]
    for name in sorted(sudoers.keys()):
        rules = sorted(set(sudoers[name]))
        for rule in rules:
            lines.append(f"{rule}\n")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8", newline="\n")


def _write_authorized_keys(
    users: dict[str, dict[str, Any]],
    output_dir: Path,
    *,
    host: str,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
) -> None:
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

        _register_users_artifact(
            collector=collector,
            rendered_root=rendered_root,
            output_path=authorized_keys_path,
            target_path=f"{home.rstrip('/')}/.ssh/authorized_keys",
            kind="host.authorized_keys",
            owner_ref=f"principal:{user_name}",
            content="".join(lines),
            owner_description=f"authorized_keys for {user_name}",
            owner_requires=[f"host-users:{host}"],
            apply_hints={
                "owner_user": user_name,
                "owner_group": user.get("primary_group") or user_name,
                "mode": "0600",
                "ssh_dir_mode": "0700",
            },
        )


def _register_users_artifact(
    *,
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
    output_path: Path,
    target_path: str,
    kind: str,
    owner_ref: str,
    content: str,
    owner_description: str,
    owner_requires: list[str] | None = None,
    apply_hints: dict[str, Any] | None = None,
) -> None:
    """Register user-management artifact and owner metadata when enabled."""
    if collector is None or rendered_root is None:
        return

    render_path = output_path.relative_to(rendered_root).as_posix()
    collector.register_artifact(
        render_path=render_path,
        target_path=target_path,
        kind=kind,
        owner_ref=owner_ref,
        content=content,
        replace=True,
        apply_hints=apply_hints,
    )

    if owner_ref not in collector.get_all_owners():
        collector.register_owner(
            name=owner_ref,
            description=owner_description,
            requires=owner_requires or [],
        )
