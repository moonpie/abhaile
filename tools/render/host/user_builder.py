"""User configuration builder."""

from pathlib import Path
import yaml

from tools.common.core import load_yaml, get_logger

logger = get_logger(__name__)


def _merge_user_data(merged: dict, new_data: dict) -> None:
    """Merge user/group/sudoers definitions into the aggregate structure."""
    for user, attrs in (new_data.get("users", {}) or {}).items():
        current = merged.setdefault("users", {}).get(user, {})
        base = {k: v for k, v in current.items() if k != "additional_groups"}
        merged.setdefault("users", {})[user] = {
            **base,
            **{k: v for k, v in attrs.items() if k != "additional_groups"},
        }

        existing_groups = list(current.get("additional_groups", []))
        for grp in attrs.get("additional_groups", []) or []:
            if grp not in existing_groups:
                existing_groups.append(grp)
        if existing_groups:
            merged["users"][user]["additional_groups"] = existing_groups

    for group, attrs in (new_data.get("groups", {}) or {}).items():
        merged.setdefault("groups", {})[group] = attrs

    if new_data.get("sudoers"):
        merged.setdefault("sudoers", []).extend(new_data.get("sudoers", []))


def _write_users_yaml(output_dir: Path, data: dict) -> None:
    users_yaml = output_dir / "users.yaml"
    users_yaml.write_text(yaml.safe_dump(data, sort_keys=False))
    logger.info("Wrote users manifest: %s", users_yaml)


def _write_sudoers(output_dir: Path, sudoers: list[dict]) -> None:
    if not sudoers:
        return

    entry = sudoers[0]
    filename = output_dir / f"sudoers.d-{entry.get('name', 'abhaile')}"

    lines = [
        "# Generated sudoers configuration",
        "# This file is managed by the orchestrator - do not edit manually",
        f"# Place in /etc/sudoers.d/{entry.get('name', 'abhaile')} with mode 0440",
        "",
        "# Defaults for all users",
        "Defaults use_pty",
        "Defaults logfile=/var/log/sudo.log",
        "",
        f"# {entry.get('name', 'abhaile')}",
    ]

    for rule in entry.get("rules", []):
        lines.append(rule)

    lines.append("")
    filename.write_text("\n".join(lines))
    logger.info("Wrote sudoers config: %s", filename)


def _write_setup_script(output_dir: Path, data: dict) -> None:
    users = data.get("users", {}) or {}
    groups = data.get("groups", {}) or {}
    if not users:
        return

    lines = [
        "#!/bin/bash",
        "# Generated user configuration script",
        "# Creates groups and users, sets up sudoers",
        "set -euo pipefail",
        "",
    ]

    for group in sorted(groups):
        gid = groups[group].get("gid")
        gid_flag = f" -g {gid}" if gid is not None else ""
        lines.append(f"groupadd{gid_flag} {group} 2>/dev/null || true")

    lines.append("")

    for user in sorted(users):
        info = users[user]
        uid = info.get("uid")
        primary_group = info.get("primary_group")
        gid = groups.get(primary_group, {}).get("gid", primary_group)
        home = info.get("home", f"/home/{user}")
        shell = info.get("shell", "/bin/bash")
        desc = info.get("description", user)
        addl_groups = info.get("additional_groups", [])

        lines.append(
            " ".join(
                [
                    "useradd",
                    f"-u {uid}" if uid is not None else "",
                    f"-g {gid}" if gid is not None else "",
                    f"-d {home}",
                    f"-s {shell}",
                    f"-c '{desc}'",
                    user,
                    "2>/dev/null",
                    "||",
                    "true",
                ]
            ).strip()
        )

        if addl_groups:
            lines.append(f"usermod -aG {','.join(addl_groups)} {user}")

        lines.append(f"mkdir -p {home}")
        if uid is not None and gid is not None:
            lines.append(f"chown {uid}:{gid} {home}")
        lines.append("chmod 0750 {home}".replace("{home}", home))
        lines.append("")

    script_path = output_dir / "setup-users.sh"
    script_path.write_text("\n".join(lines).rstrip() + "\n")
    script_path.chmod(0o755)
    logger.info("Wrote user setup script: %s", script_path)


def build_user_configs(
    hostname: str,
    config_path: Path,
    output_path: Path,
) -> None:
    """Build user configuration files for the host.

    Merges common and host-specific users.yaml definitions and emits a
    combined manifest, sudoers snippet, and setup script.
    """
    merged: dict = {"users": {}, "groups": {}, "sudoers": []}

    common_users = config_path / "common" / "users.yaml"
    host_users = config_path / hostname / "users.yaml"

    if common_users.exists():
        _merge_user_data(merged, load_yaml(common_users) or {})
    if host_users.exists():
        _merge_user_data(merged, load_yaml(host_users) or {})

    if not merged["users"] and not merged["groups"]:
        return

    output_dir = output_path / hostname / "users"
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_users_yaml(output_dir, merged)
    _write_sudoers(output_dir, merged.get("sudoers", []))
    _write_setup_script(output_dir, merged)
