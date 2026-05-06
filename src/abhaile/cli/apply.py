"""CLI entrypoint for abhaile-apply."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import socket
import sys
from pathlib import Path

from abhaile.apply.actions import (
    atomic_copy_file,
    atomic_copy_file_with_perms,
    check_destructive_gate,
    remove_target_file,
    resolve_rendered_source,
    run_validation,
)
from abhaile.apply.caddy import CaddyExecutor
from abhaile.apply.coredns import CorednsExecutor
from abhaile.apply.networkd import NetworkdExecutor
from abhaile.apply.quadlet import QuadletExecutor
from abhaile.apply.service import ServiceConfigExecutor
from abhaile.apply.systemd import SystemdExecutor
from abhaile.apply.users import UserManagementExecutor
from abhaile.apply.vault import VaultExecutor
from abhaile.plan.diff import plan_manifest_drift
from abhaile.state.history import update_state_manifests
from abhaile.cli.common import print_diff_summary, resolve_cli_paths
from abhaile.utils.errors import ApplyError, PipelineError


def _local_hostname() -> str:
    """Return short local hostname for safety checks."""
    return socket.gethostname().split(".")[0]


def _check_host_safety(
    plan: dict[str, object],
    explicit_host: str | None,
    allow_host_mismatch: bool,
) -> None:
    """Validate host identity gate before apply mutations."""
    manifest_host = plan["host"]
    if not isinstance(manifest_host, str) or not manifest_host:
        raise ApplyError("Manifest host is missing from desired manifest")

    expected_host = explicit_host if explicit_host else manifest_host
    if expected_host != manifest_host and not allow_host_mismatch:
        raise ApplyError(
            "Host mismatch between CLI and manifest: "
            f"--host={expected_host} manifest.host={manifest_host}"
        )

    live_host = _local_hostname()
    if live_host != expected_host and not allow_host_mismatch:
        raise ApplyError(
            "Host safety gate failed: " f"live hostname={live_host} expected={expected_host}"
        )


def parse_apply_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for abhaile-apply."""
    parser = argparse.ArgumentParser(description="Apply desired state to local host")
    parser.add_argument("--output", help="Output root override")
    parser.add_argument("--desired-manifest", help="Path to desired rendered manifest")
    parser.add_argument("--applied-manifest", help="Path to last applied manifest")
    parser.add_argument("--host", help="Expected host name override")
    parser.add_argument(
        "--allow-host-mismatch",
        action="store_true",
        help="Bypass host safety gate (explicitly unsafe)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only; make no changes")
    parser.add_argument(
        "--dry-run-validations",
        action="store_true",
        help="In dry-run, also run read-only validation commands",
    )
    parser.add_argument("--prune", action="store_true", help="Delete only prune-safe removals")
    parser.add_argument(
        "--force-prune",
        action="store_true",
        help="Delete removals even when live content drifted",
    )
    parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Allow destructive operations (volume/network recreate/delete)",
    )
    parser.add_argument("--json", action="store_true", help="Output structured JSON report")
    return parser.parse_args(argv)


def _is_systemd_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.2 systemd family."""
    return kind in {
        "systemd.unit",
        "systemd.dropin",
        "resolved.config",
        "resolved.dropin",
    }


def _is_user_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.3 user-management family."""
    return kind in {
        "host.sysusers",
        "host.sudoers",
        "host.authorized_keys",
    }


def _is_coredns_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.4 CoreDNS family."""
    return kind in {
        "coredns.config",
        "coredns.zone",
    }


def _is_caddy_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.5 Caddy family."""
    return kind == "caddy.config"


def _is_vault_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.6 vault-agent family."""
    return kind in {
        "vault.config",
        "vault.template",
    }


def _is_networkd_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.7 systemd-networkd family."""
    return kind in {
        "networkd.netdev",
        "networkd.network",
        "networkd.dropin",
    }


def _is_quadlet_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to phase 7.8 quadlet family."""
    return kind in {
        "quadlet.network",
        "quadlet.volume",
        "quadlet.image",
        "quadlet.build",
        "quadlet.pod",
        "quadlet.container",
    }


def _is_service_entry_kind(kind: str) -> bool:
    """Return True when kind belongs to service-owned config/env family."""
    return kind in {
        "service.config",
        "service.env",
        "service.directory",
    }


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


def _copy_artifact_for_apply(action: dict[str, object], rendered_dir: Path) -> None:
    """Copy artifact for apply, using strict policy for user-managed kinds."""
    render_path = action.get("render_path")
    target_path = action.get("target_path")
    kind = action.get("kind")
    if not isinstance(render_path, str) or not isinstance(target_path, str):
        raise ApplyError("Write action missing render_path/target_path")
    if not isinstance(kind, str):
        raise ApplyError("Write action missing kind")

    if kind == "service.directory":
        return

    source = resolve_rendered_source(rendered_dir, render_path)
    target = Path(target_path)

    if _is_user_entry_kind(kind):
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

    atomic_copy_file(source, target)


def _resolve_parent_unit_name(target_path: str, owner_ref: str) -> str:
    """Resolve parent unit name for dropin entries."""
    if owner_ref.startswith("unit:"):
        return owner_ref.split(":", 1)[1]

    tail = Path(target_path).relative_to("/etc/systemd/system").as_posix()
    first = tail.split("/", 1)[0]
    if first.endswith(".d"):
        return first[:-2]
    raise ApplyError(f"Unable to determine parent unit for dropin target: {target_path}")


def _entry_user_context(entry: dict[str, object]) -> tuple[bool, str | None]:
    """Derive rootless execution context from apply hints."""
    apply_hints = entry.get("apply_hints")
    if not isinstance(apply_hints, dict):
        return (False, None)

    rootless = bool(apply_hints.get("rootless"))
    podman_user = apply_hints.get("podman_user")
    if rootless and isinstance(podman_user, str) and podman_user:
        return (True, podman_user)
    if rootless:
        return (True, None)
    return (False, None)


def _run_dry_run_validations(
    rendered_dir: Path, writes: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Execute read-only validations for changed systemd-family artifacts."""
    results: list[dict[str, object]] = []

    for action in writes:
        kind = action.get("kind")
        render_path = action.get("render_path")
        target_path = action.get("target_path")
        if not isinstance(kind, str) or not _is_systemd_entry_kind(kind):
            if kind == "host.sudoers":
                render_path = action.get("render_path")
                target_path = action.get("target_path")
                if not isinstance(render_path, str) or not isinstance(target_path, str):
                    raise ApplyError("Validation action missing render_path/target_path")
                source = resolve_rendered_source(rendered_dir, render_path)
                validation = UserManagementExecutor.validate_sudoers(source)
                results.append(
                    {
                        "target_path": target_path,
                        "kind": kind,
                        "success": validation.success,
                        "return_code": validation.return_code,
                    }
                )
            elif kind == "host.sysusers":
                target_path = action.get("target_path")
                if not isinstance(target_path, str):
                    raise ApplyError("Validation action missing target_path")
                validation = UserManagementExecutor.validate_sysusers_dry_run()
                results.append(
                    {
                        "target_path": target_path,
                        "kind": kind,
                        "success": validation.success,
                        "return_code": validation.return_code,
                    }
                )
            elif kind == "coredns.zone":
                if not isinstance(render_path, str) or not isinstance(target_path, str):
                    raise ApplyError("Validation action missing render_path/target_path")
                source = resolve_rendered_source(rendered_dir, render_path)
                zone_name = CorednsExecutor.zone_name_from_target(target_path)
                validation = CorednsExecutor.validate_zone_file(
                    zone_name,
                    source,
                    strict=False,
                )
                payload: dict[str, object] = {
                    "target_path": target_path,
                    "kind": kind,
                    "success": validation.success,
                    "return_code": validation.return_code,
                }
                if validation.error_message:
                    payload["warning"] = validation.error_message
                results.append(payload)
            elif kind == "caddy.config":
                owner_ref = action.get("owner_ref")
                if not isinstance(target_path, str) or not isinstance(owner_ref, str):
                    raise ApplyError("Validation action missing target_path/owner_ref")
                segment = CaddyExecutor.segment_from_owner_or_target(owner_ref, target_path)
                validation = CaddyExecutor.validate_caddy_config(segment, strict=False)
                payload = {
                    "target_path": target_path,
                    "kind": kind,
                    "success": validation.success,
                    "return_code": validation.return_code,
                }
                if validation.error_message:
                    payload["warning"] = validation.error_message
                results.append(payload)
            elif isinstance(kind, str) and _is_networkd_entry_kind(kind):
                if not isinstance(target_path, str):
                    raise ApplyError("Validation action missing target_path")
                validation = NetworkdExecutor.validate_networkctl(strict=False)
                payload = {
                    "target_path": target_path,
                    "kind": kind,
                    "success": validation.success,
                    "return_code": validation.return_code,
                }
                if validation.error_message:
                    payload["warning"] = validation.error_message
                results.append(payload)
            elif isinstance(kind, str) and _is_quadlet_entry_kind(kind):
                if not isinstance(target_path, str):
                    raise ApplyError("Validation action missing target_path")
                entry = {
                    "kind": kind,
                    "owner_ref": action.get("owner_ref"),
                    "apply_hints": action.get("apply_hints"),
                }
                rootless, run_as_user = QuadletExecutor.user_context_from_entries([entry])
                validation = QuadletExecutor.validate_systemctl(
                    rootless=rootless,
                    run_as_user=run_as_user,
                    strict=False,
                )
                payload = {
                    "target_path": target_path,
                    "kind": kind,
                    "success": validation.success,
                    "return_code": validation.return_code,
                }
                if validation.error_message:
                    payload["warning"] = validation.error_message
                results.append(payload)
            continue
        if not isinstance(render_path, str) or not isinstance(target_path, str):
            raise ApplyError("Validation action missing render_path/target_path")

        source = resolve_rendered_source(rendered_dir, render_path)
        validation = run_validation(
            ["systemd-analyze", "verify", source.as_posix()],
            action_id=f"validate:{target_path}",
            is_blocker=True,
        )
        results.append(
            {
                "target_path": target_path,
                "kind": kind,
                "success": validation.success,
                "return_code": validation.return_code,
            }
        )

    return results


def _run_systemd_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run phase 7.2 systemd family actions for changed entries."""
    owner_results: list[dict[str, object]] = []

    for action in writes:
        kind = action.get("kind")
        target_path = action.get("target_path")
        owner_ref = action.get("owner_ref")
        if not isinstance(kind, str) or not _is_systemd_entry_kind(kind):
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("Systemd write action missing target_path/owner_ref")

        unit_name = Path(target_path).name
        entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": action.get("apply_hints"),
        }
        user_mode, run_as_user = _entry_user_context(entry)

        if kind == "systemd.unit":
            summary = SystemdExecutor.apply_unit_write(
                unit_name,
                entry,
                user=user_mode,
                run_as_user=run_as_user,
            )
        elif kind == "systemd.dropin":
            parent_unit = _resolve_parent_unit_name(target_path, owner_ref)
            summary = SystemdExecutor.apply_dropin_write(
                parent_unit,
                entry,
                user=user_mode,
                run_as_user=run_as_user,
            )
        else:
            summary = SystemdExecutor.apply_resolved_config_write(entry)

        owner_results.append(
            {
                "phase": "write",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or kind != "systemd.unit":
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("Systemd removal action missing target_path/owner_ref")

        unit_name = Path(target_path).name
        removal_entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": removal.get("apply_hints"),
        }
        user_mode, run_as_user = _entry_user_context(removal_entry)
        summary = SystemdExecutor.apply_unit_remove(
            unit_name,
            removal_entry,
            user=user_mode,
            run_as_user=run_as_user,
        )
        owner_results.append(
            {
                "phase": "remove",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    return owner_results


def _run_user_owner_actions(
    writes: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run phase 7.3 user-management actions for changed entries."""
    owner_results: list[dict[str, object]] = []

    for action in writes:
        kind = action.get("kind")
        target_path = action.get("target_path")
        owner_ref = action.get("owner_ref")
        if not isinstance(kind, str) or not _is_user_entry_kind(kind):
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("User-management write action missing target_path/owner_ref")

        entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": action.get("apply_hints"),
        }

        if kind == "host.sysusers":
            summary = UserManagementExecutor.apply_sysusers_write(entry)
        elif kind == "host.sudoers":
            summary = UserManagementExecutor.apply_sudoers_write(entry, Path(target_path))
        else:
            summary = UserManagementExecutor.apply_authorized_keys_write(entry)

        owner_results.append(
            {
                "phase": "write",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    return owner_results


def _run_coredns_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run phase 7.4 CoreDNS actions for changed entries."""
    owner_results: list[dict[str, object]] = []

    for action in writes:
        kind = action.get("kind")
        target_path = action.get("target_path")
        owner_ref = action.get("owner_ref")
        if not isinstance(kind, str) or not _is_coredns_entry_kind(kind):
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("CoreDNS write action missing target_path/owner_ref")

        entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": action.get("apply_hints"),
        }

        if kind == "coredns.config":
            summary = CorednsExecutor.apply_config_write(entry)
        else:
            summary = CorednsExecutor.apply_zone_write(entry, target_path)

        owner_results.append(
            {
                "phase": "write",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or not _is_coredns_entry_kind(kind):
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("CoreDNS removal action missing target_path/owner_ref")

        removal_entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": removal.get("apply_hints"),
        }

        if kind == "coredns.config":
            summary = CorednsExecutor.apply_config_write(removal_entry)
        else:
            summary = CorednsExecutor.apply_zone_remove(removal_entry, target_path)

        owner_results.append(
            {
                "phase": "remove",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    return owner_results


def _run_caddy_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run phase 7.5 Caddy actions for changed entries."""
    owner_results: list[dict[str, object]] = []

    for action in writes:
        kind = action.get("kind")
        target_path = action.get("target_path")
        owner_ref = action.get("owner_ref")
        if not isinstance(kind, str) or not _is_caddy_entry_kind(kind):
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("Caddy write action missing target_path/owner_ref")

        entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": action.get("apply_hints"),
        }

        summary = CaddyExecutor.apply_config_write(entry, target_path)
        owner_results.append(
            {
                "phase": "write",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or not _is_caddy_entry_kind(kind):
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("Caddy removal action missing target_path/owner_ref")

        entry = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": removal.get("apply_hints"),
        }
        summary = CaddyExecutor.apply_config_write(entry, target_path)
        owner_results.append(
            {
                "phase": "remove",
                "target_path": target_path,
                "kind": kind,
                "owner_ref": owner_ref,
                "summary": summary,
            }
        )

    return owner_results


def _run_vault_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run phase 7.6 vault-agent actions for changed entries."""
    owner_changes: dict[str, dict[str, object]] = {}

    def _record_change(
        *,
        source: str,
        kind: str,
        owner_ref: str,
        target_path: str,
        apply_hints: object,
    ) -> None:
        if owner_ref not in owner_changes:
            owner_changes[owner_ref] = {
                "run_as_user": VaultExecutor.DEFAULT_USER,
                "entries": [],
            }

        entry = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": apply_hints,
        }
        owner_state = owner_changes[owner_ref]
        current_user = owner_state.get("run_as_user")
        if (
            isinstance(current_user, str)
            and current_user == VaultExecutor.DEFAULT_USER
            and isinstance(apply_hints, dict)
            and isinstance(apply_hints.get("podman_user"), str)
        ):
            owner_state["run_as_user"] = VaultExecutor.user_from_entry(entry)

        entries = owner_state.get("entries")
        if isinstance(entries, list):
            entries.append(
                {
                    "phase": source,
                    "target_path": target_path,
                    "kind": kind,
                }
            )

    for action in writes:
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        target_path = action.get("target_path")
        if not isinstance(kind, str) or not _is_vault_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Vault write action missing owner_ref/target_path")
        _record_change(
            source="write",
            kind=kind,
            owner_ref=owner_ref,
            target_path=target_path,
            apply_hints=action.get("apply_hints"),
        )

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or not _is_vault_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Vault removal action missing owner_ref/target_path")
        _record_change(
            source="remove",
            kind=kind,
            owner_ref=owner_ref,
            target_path=target_path,
            apply_hints=removal.get("apply_hints"),
        )

    owner_results: list[dict[str, object]] = []
    for owner_ref in sorted(owner_changes.keys()):
        owner_state = owner_changes[owner_ref]
        run_as_user_obj = owner_state.get("run_as_user")
        run_as_user = (
            run_as_user_obj
            if isinstance(run_as_user_obj, str) and run_as_user_obj
            else VaultExecutor.DEFAULT_USER
        )

        summary = VaultExecutor.apply_owner_change(owner_ref, run_as_user=run_as_user)
        owner_results.append(
            {
                "phase": "converge",
                "kind": "vault.owner",
                "owner_ref": owner_ref,
                "summary": summary,
                "entries": owner_state.get("entries"),
            }
        )

    return owner_results


def _run_networkd_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
    *,
    netdev_delete_order: list[str] | None = None,
) -> list[dict[str, object]]:
    """Run phase 7.7 systemd-networkd actions for changed entries."""
    owner_changes: dict[str, dict[str, object]] = {}

    def _record_change(*, phase: str, kind: str, owner_ref: str, target_path: str) -> None:
        if owner_ref not in owner_changes:
            owner_changes[owner_ref] = {
                "phases": set(),
                "kinds": set(),
                "entries": [],
            }

        state = owner_changes[owner_ref]
        phases = state.get("phases")
        if isinstance(phases, set):
            phases.add(phase)
        kinds = state.get("kinds")
        if isinstance(kinds, set):
            kinds.add(kind)
        entries = state.get("entries")
        if isinstance(entries, list):
            entries.append(
                {
                    "phase": phase,
                    "kind": kind,
                    "target_path": target_path,
                }
            )

    for action in writes:
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        target_path = action.get("target_path")
        if not isinstance(kind, str) or not _is_networkd_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Networkd write action missing owner_ref/target_path")
        _record_change(
            phase="write",
            kind=kind,
            owner_ref=owner_ref,
            target_path=target_path,
        )

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or not _is_networkd_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Networkd removal action missing owner_ref/target_path")
        _record_change(
            phase="remove",
            kind=kind,
            owner_ref=owner_ref,
            target_path=target_path,
        )

    remove_only_netdev_owners: set[str] = set()
    for owner_ref, state in owner_changes.items():
        phases = state.get("phases")
        kinds = state.get("kinds")
        if not isinstance(phases, set) or not isinstance(kinds, set):
            continue
        if phases == {"remove"} and kinds == {"networkd.netdev"}:
            remove_only_netdev_owners.add(owner_ref)

    ordered_owner_refs: list[str] = []
    seen: set[str] = set()

    if isinstance(netdev_delete_order, list):
        for owner_ref in netdev_delete_order:
            if (
                isinstance(owner_ref, str)
                and owner_ref in owner_changes
                and owner_ref in remove_only_netdev_owners
                and owner_ref not in seen
            ):
                ordered_owner_refs.append(owner_ref)
                seen.add(owner_ref)

    for owner_ref in sorted(owner_changes.keys()):
        if owner_ref in seen:
            continue
        ordered_owner_refs.append(owner_ref)
        seen.add(owner_ref)

    owner_results: list[dict[str, object]] = []

    remove_only_owner_summaries: list[tuple[str, dict[str, object], list[dict[str, object]]]] = []
    for owner_ref in ordered_owner_refs:
        state = owner_changes[owner_ref]
        entries = state.get("entries")
        if not isinstance(entries, list) or not entries:
            continue

        sample_target = entries[0].get("target_path")
        if not isinstance(sample_target, str):
            raise ApplyError("Networkd owner entry missing target_path")

        interface = NetworkdExecutor.interface_from_owner_or_target(owner_ref, sample_target)
        phases = state.get("phases")
        strict_reconfigure = not (isinstance(phases, set) and phases == {"remove"})
        kinds = state.get("kinds")
        delete_interface_first = owner_ref in remove_only_netdev_owners
        if delete_interface_first:
            delete_result = NetworkdExecutor.delete_interface(interface)
            summary: dict[str, object] = {
                "owner_ref": owner_ref,
                "interface": interface,
                "kinds": sorted(list(kinds)) if isinstance(kinds, set) else [],
                "actions": [
                    {
                        "action": "delete-interface",
                        "success": delete_result.success,
                        "return_code": delete_result.return_code,
                    }
                ],
            }
            remove_only_owner_summaries.append((owner_ref, summary, entries))
            continue

        summary = NetworkdExecutor.apply_owner_change(
            owner_ref,
            interface=interface,
            strict_reconfigure=strict_reconfigure,
            kinds=list(kinds) if isinstance(kinds, set) else None,
            delete_interface_first=False,
            run_reconfigure=True,
        )
        owner_results.append(
            {
                "phase": "converge",
                "kind": "networkd.owner",
                "owner_ref": owner_ref,
                "summary": summary,
                "entries": entries,
            }
        )

    if remove_only_owner_summaries:
        reload_result = NetworkdExecutor.reload_networkd()
        first_summary = remove_only_owner_summaries[0][1]
        first_actions = first_summary.get("actions")
        if isinstance(first_actions, list):
            first_actions.append(
                {
                    "action": "reload-batch",
                    "success": reload_result.success,
                    "return_code": reload_result.return_code,
                }
            )

        for owner_ref, summary, entries in remove_only_owner_summaries:
            owner_results.append(
                {
                    "phase": "converge",
                    "kind": "networkd.owner",
                    "owner_ref": owner_ref,
                    "summary": summary,
                    "entries": entries,
                }
            )

    return owner_results


def _run_quadlet_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
    *,
    convergence_plans: dict[str, list[dict[str, str]]] | None = None,
    owner_apply_hints: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Run phase 7.8 quadlet actions for changed entries."""
    owner_changes: dict[str, dict[str, object]] = {}

    def _record_change(
        *,
        phase: str,
        kind: str,
        owner_ref: str,
        target_path: str,
        apply_hints: object,
    ) -> None:
        if owner_ref not in owner_changes:
            owner_changes[owner_ref] = {
                "phases": set(),
                "kinds": set(),
                "entries": [],
                "raw_entries": [],
            }
        state = owner_changes[owner_ref]
        phases = state.get("phases")
        if isinstance(phases, set):
            phases.add(phase)
        kinds = state.get("kinds")
        if isinstance(kinds, set):
            kinds.add(kind)
        entries = state.get("entries")
        if isinstance(entries, list):
            entries.append(
                {
                    "phase": phase,
                    "kind": kind,
                    "target_path": target_path,
                }
            )
        raw_entries = state.get("raw_entries")
        if isinstance(raw_entries, list):
            raw_entries.append(
                {
                    "kind": kind,
                    "owner_ref": owner_ref,
                    "target_path": target_path,
                    "apply_hints": apply_hints,
                }
            )

    for action in writes:
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        target_path = action.get("target_path")
        if not isinstance(kind, str) or not _is_quadlet_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Quadlet write action missing owner_ref/target_path")
        _record_change(
            phase="write",
            kind=kind,
            owner_ref=owner_ref,
            target_path=target_path,
            apply_hints=action.get("apply_hints"),
        )

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or not _is_quadlet_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Quadlet removal action missing owner_ref/target_path")
        _record_change(
            phase="remove",
            kind=kind,
            owner_ref=owner_ref,
            target_path=target_path,
            apply_hints=removal.get("apply_hints"),
        )

    owner_results: list[dict[str, object]] = []

    def _user_context_for_owner(owner_ref: str) -> tuple[bool, str | None]:
        state = owner_changes.get(owner_ref)
        if isinstance(state, dict):
            raw_entries = state.get("raw_entries")
            if isinstance(raw_entries, list) and raw_entries:
                return QuadletExecutor.user_context_from_entries(raw_entries)

        if owner_apply_hints is not None:
            hints = owner_apply_hints.get(owner_ref)
            if isinstance(hints, dict):
                rootless = bool(hints.get("rootless"))
                run_as_user_obj = hints.get("podman_user")
                owner_run_as_user = (
                    run_as_user_obj
                    if isinstance(run_as_user_obj, str) and run_as_user_obj
                    else None
                )
                return (rootless, owner_run_as_user)

        return (False, None)

    for owner_ref in sorted(owner_changes.keys()):
        state = owner_changes[owner_ref]
        raw_entries = state.get("raw_entries")
        if not isinstance(raw_entries, list):
            continue

        rootless, owner_run_as_user = QuadletExecutor.user_context_from_entries(raw_entries)
        convergence_actions: list[dict[str, object]] = []
        if convergence_plans is not None:
            steps = convergence_plans.get(owner_ref, [])
            if isinstance(steps, list) and steps:
                pre_steps = [step for step in steps if step.get("action") == "stop"]
                post_steps = [step for step in steps if step.get("action") != "stop"]

                for step in pre_steps:
                    dependent_owner_ref = step.get("owner_ref")
                    step_action = step.get("action")
                    if not isinstance(dependent_owner_ref, str) or not isinstance(step_action, str):
                        raise ApplyError("Invalid quadlet convergence step")
                    dep_rootless, dependent_run_as_user = _user_context_for_owner(
                        dependent_owner_ref
                    )
                    convergence_actions.append(
                        QuadletExecutor.apply_convergence_action(
                            dependent_owner_ref,
                            action=step_action,
                            rootless=dep_rootless,
                            run_as_user=dependent_run_as_user,
                        )
                    )

        kinds = state.get("kinds")
        phases = state.get("phases")
        summary = QuadletExecutor.apply_owner_change(
            owner_ref,
            kinds=sorted(list(kinds)) if isinstance(kinds, set) else [],
            changed_phases=phases if isinstance(phases, set) else set(),
            rootless=rootless,
            run_as_user=owner_run_as_user,
        )

        if convergence_plans is not None:
            steps = convergence_plans.get(owner_ref, [])
            if isinstance(steps, list) and steps:
                post_steps = [step for step in steps if step.get("action") != "stop"]
                for step in post_steps:
                    dependent_owner_ref = step.get("owner_ref")
                    step_action = step.get("action")
                    if not isinstance(dependent_owner_ref, str) or not isinstance(step_action, str):
                        raise ApplyError("Invalid quadlet convergence step")
                    dep_rootless, dependent_run_as_user = _user_context_for_owner(
                        dependent_owner_ref
                    )
                    convergence_actions.append(
                        QuadletExecutor.apply_convergence_action(
                            dependent_owner_ref,
                            action=step_action,
                            rootless=dep_rootless,
                            run_as_user=dependent_run_as_user,
                        )
                    )

        if convergence_actions:
            summary["convergence_actions"] = convergence_actions
        owner_results.append(
            {
                "phase": "converge",
                "kind": "quadlet.owner",
                "owner_ref": owner_ref,
                "summary": summary,
                "entries": state.get("entries"),
            }
        )

    return owner_results


def _run_service_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run service-owned post-write actions for changed config/env/directory entries."""
    owner_changes: dict[str, dict[str, object]] = {}

    def _ensure_owner(owner_ref: str) -> dict[str, object]:
        if owner_ref not in owner_changes:
            owner_changes[owner_ref] = {
                "config_writes": [],
                "removals": [],
                "directory_writes": [],
                "entries": [],
                "config_apply_hints": None,
            }
        return owner_changes[owner_ref]

    for action in writes:
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        target_path = action.get("target_path")
        if not isinstance(kind, str) or not _is_service_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Service write action missing owner_ref/target_path")

        state = _ensure_owner(owner_ref)
        if kind == "service.directory":
            directory_writes = state.get("directory_writes")
            if isinstance(directory_writes, list):
                directory_writes.append(action)
        else:
            config_writes = state.get("config_writes")
            if isinstance(config_writes, list):
                config_writes.append(action)
        entries = state.get("entries")
        if isinstance(entries, list):
            entries.append(
                {
                    "phase": "write",
                    "kind": kind,
                    "target_path": target_path,
                }
            )
        hints = action.get("apply_hints")
        if kind != "service.directory" and isinstance(hints, dict):
            state["config_apply_hints"] = hints

    for removal in removals_to_apply:
        kind = removal.get("kind") if isinstance(removal, dict) else None
        owner_ref = removal.get("owner_ref") if isinstance(removal, dict) else None
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if not isinstance(kind, str) or not _is_service_entry_kind(kind):
            continue
        if not isinstance(owner_ref, str) or not isinstance(target_path, str):
            raise ApplyError("Service removal action missing owner_ref/target_path")

        state = _ensure_owner(owner_ref)
        state_removals = state.get("removals")
        if isinstance(state_removals, list):
            state_removals.append(removal)
        entries = state.get("entries")
        if isinstance(entries, list):
            entries.append(
                {
                    "phase": "remove",
                    "kind": kind,
                    "target_path": target_path,
                }
            )
        hints = removal.get("apply_hints")
        if (
            kind != "service.directory"
            and state.get("config_apply_hints") is None
            and isinstance(hints, dict)
        ):
            state["config_apply_hints"] = hints

    owner_results: list[dict[str, object]] = []
    for owner_ref in sorted(owner_changes.keys()):
        state = owner_changes[owner_ref]
        state_writes = state.get("config_writes")
        state_removals = state.get("removals")
        state_directories = state.get("directory_writes")
        writes_for_owner = state_writes if isinstance(state_writes, list) else []
        removals_for_owner = state_removals if isinstance(state_removals, list) else []
        directory_writes = state_directories if isinstance(state_directories, list) else []

        directory_actions: list[dict[str, object]] = []
        for directory in directory_writes:
            target_path = directory.get("target_path")
            if not isinstance(target_path, str):
                raise ApplyError("Service directory write action missing target_path")
            hints = directory.get("apply_hints")
            directory_actions.append(
                ServiceConfigExecutor.apply_directory_change(
                    target_path,
                    hints if isinstance(hints, dict) else None,
                )
            )

        config_apply_hints = state.get("config_apply_hints")
        summary = ServiceConfigExecutor.apply_owner_change(
            owner_ref,
            writes_for_owner,
            removals_for_owner,
            config_apply_hints if isinstance(config_apply_hints, dict) else None,
        )
        if directory_actions:
            summary["directory_actions"] = directory_actions
        owner_results.append(
            {
                "phase": "converge",
                "kind": "service.owner",
                "owner_ref": owner_ref,
                "summary": summary,
                "entries": state.get("entries"),
            }
        )

    return owner_results


def _collect_owner_escalations(plan: dict[str, object]) -> list[str]:
    """Collect deduplicated escalation labels from owner plan bundles."""
    owner_plan = plan.get("owner_plan")
    if not isinstance(owner_plan, dict):
        return []
    owners = owner_plan.get("owners")
    if not isinstance(owners, list):
        return []

    escalations: set[str] = set()
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        owner_escalations = owner.get("escalations")
        if not isinstance(owner_escalations, list):
            continue
        for item in owner_escalations:
            if isinstance(item, str) and item:
                escalations.add(item)
    return sorted(escalations)


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-apply."""
    args = parse_apply_args(argv)

    if args.prune and args.force_prune:
        raise ApplyError("Use either --prune or --force-prune, not both")

    if args.dry_run_validations and not args.dry_run:
        raise ApplyError("--dry-run-validations requires --dry-run")

    rendered_dir, state_dir, desired_path, applied_path = resolve_cli_paths(
        args.output,
        args.desired_manifest,
        args.applied_manifest,
    )

    plan = plan_manifest_drift(desired_path, applied_path)
    _check_host_safety(plan, args.host, args.allow_host_mismatch)
    owner_escalations = _collect_owner_escalations(plan)
    if not args.json:
        print_diff_summary(plan)

    if args.dry_run:
        validation_results: list[dict[str, object]] = []
        if args.dry_run_validations:
            validation_results = _run_dry_run_validations(
                rendered_dir, writes=plan["sync"]["writes"]
            )
            if not args.json:
                print("mode=dry-run action=validations-only")
        else:
            if not args.json:
                print("mode=dry-run action=none")
        if args.json:
            quadlet_convergence_plans = plan.get("quadlet_convergence_plans")
            if not isinstance(quadlet_convergence_plans, dict):
                quadlet_convergence_plans = {}
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "validations_run": len(validation_results),
                        "validation_results": validation_results,
                        "owner_escalations": owner_escalations,
                        "quadlet_convergence_plans": quadlet_convergence_plans,
                    },
                    indent=2,
                )
            )
        return 0

    sync = plan["sync"]
    if not isinstance(sync, dict):
        raise ApplyError("Invalid sync plan")
    writes = sync["writes"]
    removals_safe = sync["removals_safe"]
    removals_drifted = sync["removals_drifted"]

    if not isinstance(writes, list):
        raise ApplyError("Invalid writes plan")
    if not isinstance(removals_safe, list) or not isinstance(removals_drifted, list):
        raise ApplyError("Invalid removal plan")

    write_count = 0
    remove_count = 0

    for action in writes:
        if not isinstance(action, dict):
            raise ApplyError("Invalid write action")
        _copy_artifact_for_apply(action, rendered_dir)
        write_count += 1

    removals_to_apply: list[dict[str, object]] = []
    if args.force_prune:
        check_destructive_gate(
            gate_name="prune-drifted",
            allow_destructive=args.allow_destructive,
            escalations=owner_escalations,
        )
        removals_to_apply = [*removals_safe, *removals_drifted]
    elif args.prune:
        removals_to_apply = [*removals_safe]

    for removal in removals_to_apply:
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if not isinstance(target_path, str):
            raise ApplyError("Removal action missing target_path")
        remove_target_file(Path(target_path))
        remove_count += 1

    systemd_owner_results = _run_systemd_owner_actions(writes, removals_to_apply)
    user_owner_results = _run_user_owner_actions(writes)
    coredns_owner_results = _run_coredns_owner_actions(writes, removals_to_apply)
    caddy_owner_results = _run_caddy_owner_actions(writes, removals_to_apply)
    vault_owner_results = _run_vault_owner_actions(writes, removals_to_apply)
    service_owner_results = _run_service_owner_actions(writes, removals_to_apply)
    netdev_delete_order = plan.get("networkd_netdev_delete_order")
    if not isinstance(netdev_delete_order, list):
        netdev_delete_order = None
    networkd_owner_results = _run_networkd_owner_actions(
        writes,
        removals_to_apply,
        netdev_delete_order=netdev_delete_order,
    )
    quadlet_convergence_plans = plan.get("quadlet_convergence_plans")
    if not isinstance(quadlet_convergence_plans, dict):
        quadlet_convergence_plans = None
    desired_manifest = plan.get("desired_manifest")
    owner_apply_hints: dict[str, dict[str, object]] = {}
    if isinstance(desired_manifest, dict):
        desired_owners = desired_manifest.get("owners")
        if isinstance(desired_owners, dict):
            for owner_ref, payload in desired_owners.items():
                if not isinstance(owner_ref, str) or not isinstance(payload, dict):
                    continue
                apply_hints = payload.get("apply_hints")
                if isinstance(apply_hints, dict):
                    owner_apply_hints[owner_ref] = apply_hints
    quadlet_owner_results = _run_quadlet_owner_actions(
        writes,
        removals_to_apply,
        convergence_plans=quadlet_convergence_plans,
        owner_apply_hints=owner_apply_hints,
    )

    update_state_manifests(desired_path, state_dir)

    if args.json:
        report = {
            "mode": "apply",
            "writes": write_count,
            "removals": remove_count,
            "state_updated": True,
            "allow_destructive": args.allow_destructive,
            "owner_execution": [
                *systemd_owner_results,
                *user_owner_results,
                *coredns_owner_results,
                *caddy_owner_results,
                *vault_owner_results,
                *service_owner_results,
                *networkd_owner_results,
                *quadlet_owner_results,
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        print(f"mode=apply writes={write_count} removals={remove_count} state_updated=true")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        sys.exit(1)
