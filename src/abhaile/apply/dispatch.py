"""Owner dispatch helpers for the apply pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from abhaile.apply.actions import resolve_rendered_source, run_validation
from abhaile.apply.caddy import CaddyExecutor
from abhaile.apply.coredns import CorednsExecutor
from abhaile.apply.networkd import NetworkdExecutor
from abhaile.apply.quadlet import QuadletExecutor
from abhaile.apply.service import ServiceConfigExecutor
from abhaile.apply.systemd import SystemdExecutor
from abhaile.apply.users import UserManagementExecutor
from abhaile.apply.vault import VaultExecutor
from abhaile.models.kinds import KIND_FAMILIES
from abhaile.plan.diff import PlanResult
from abhaile.utils.errors import ApplyError

LOG = logging.getLogger(__name__)

_SYSTEMD_KINDS = KIND_FAMILIES["systemd"]
_USER_KINDS = KIND_FAMILIES["user"]
_COREDNS_KINDS = KIND_FAMILIES["coredns"]
_CADDY_KINDS = KIND_FAMILIES["caddy"]
_VAULT_KINDS = KIND_FAMILIES["vault"]
_NETWORKD_KINDS = KIND_FAMILIES["networkd"]
_QUADLET_KINDS = KIND_FAMILIES["quadlet"]
_SERVICE_KINDS = KIND_FAMILIES["service"]


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


def _resolve_parent_unit_name(target_path: str, owner_ref: str) -> str:
    """Resolve parent unit name for dropin entries."""
    if owner_ref.startswith("unit:"):
        return owner_ref.split(":", 1)[1]

    tail = Path(target_path).relative_to("/etc/systemd/system").as_posix()
    first = tail.split("/", 1)[0]
    if first.endswith(".d"):
        return first[:-2]
    raise ApplyError(f"Unable to determine parent unit for dropin target: {target_path}")


def _run_dry_run_validations(
    rendered_dir: Path, writes: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Execute read-only validations for changed systemd-family artifacts."""
    results: list[dict[str, object]] = []

    for action in writes:
        kind = action.get("kind")
        render_path = action.get("render_path")
        target_path = action.get("target_path")
        if not isinstance(kind, str) or kind not in _SYSTEMD_KINDS:
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
            elif isinstance(kind, str) and kind in _NETWORKD_KINDS:
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
            elif isinstance(kind, str) and kind in _QUADLET_KINDS:
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
        if not isinstance(kind, str) or kind not in _SYSTEMD_KINDS:
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

    LOG.debug("dispatch.systemd results=%d", len(owner_results))
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
        if not isinstance(kind, str) or kind not in _USER_KINDS:
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

    LOG.debug("dispatch.users results=%d", len(owner_results))
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
        if not isinstance(kind, str) or kind not in _COREDNS_KINDS:
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
        if not isinstance(kind, str) or kind not in _COREDNS_KINDS:
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

    LOG.debug("dispatch.coredns results=%d", len(owner_results))
    return owner_results


def _run_caddy_owner_actions(
    writes: list[dict[str, object]],
    removals_to_apply: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run phase 7.5 Caddy actions for changed entries."""
    owner_results: list[dict[str, object]] = []
    initial_deploy_segments = _caddy_segments_with_container_writes(writes)

    for action in writes:
        kind = action.get("kind")
        target_path = action.get("target_path")
        owner_ref = action.get("owner_ref")
        if not isinstance(kind, str) or kind not in _CADDY_KINDS:
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("Caddy write action missing target_path/owner_ref")

        entry: dict[str, object] = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": action.get("apply_hints"),
        }

        segment = CaddyExecutor.segment_from_owner_or_target(owner_ref, target_path)
        summary = CaddyExecutor.apply_config_write(
            entry,
            target_path,
            allow_missing_container=segment in initial_deploy_segments,
        )
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
        if not isinstance(kind, str) or kind not in _CADDY_KINDS:
            continue
        if not isinstance(target_path, str) or not isinstance(owner_ref, str):
            raise ApplyError("Caddy removal action missing target_path/owner_ref")

        entry = {
            "kind": kind,
            "owner_ref": owner_ref,
            "apply_hints": removal.get("apply_hints"),
        }
        segment = CaddyExecutor.segment_from_owner_or_target(owner_ref, target_path)
        summary = CaddyExecutor.apply_config_write(
            entry,
            target_path,
            allow_missing_container=segment in initial_deploy_segments,
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

    LOG.debug("dispatch.caddy results=%d", len(owner_results))
    return owner_results


def _caddy_segments_with_container_writes(writes: list[dict[str, object]]) -> set[str]:
    """Return Caddy segments whose container quadlet is being written."""
    segments: set[str] = set()
    for action in writes:
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        if kind != "quadlet.container" or not isinstance(owner_ref, str):
            continue
        if not owner_ref.startswith("unit:caddy-") or not owner_ref.endswith(".service"):
            continue
        unit_name = owner_ref.split(":", 1)[1]
        segments.add(unit_name.removeprefix("caddy-").removesuffix(".service"))
    return segments


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
        if not isinstance(kind, str) or kind not in _VAULT_KINDS:
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
        if not isinstance(kind, str) or kind not in _VAULT_KINDS:
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

    LOG.debug("dispatch.vault results=%d", len(owner_results))
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
        if not isinstance(kind, str) or kind not in _NETWORKD_KINDS:
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
        if not isinstance(kind, str) or kind not in _NETWORKD_KINDS:
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

    LOG.debug("dispatch.networkd results=%d", len(owner_results))
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
        if not isinstance(kind, str) or kind not in _QUADLET_KINDS:
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
        if not isinstance(kind, str) or kind not in _QUADLET_KINDS:
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

    def _restart_mode_for_owner(owner_ref: str, raw_entries: list[object]) -> str:
        if owner_apply_hints is not None:
            hints = owner_apply_hints.get(owner_ref)
            if isinstance(hints, dict):
                restart_mode = hints.get("restart_mode")
                if isinstance(restart_mode, str) and restart_mode:
                    return restart_mode

        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            hints = raw_entry.get("apply_hints")
            if not isinstance(hints, dict):
                continue
            restart_mode = hints.get("restart_mode")
            if isinstance(restart_mode, str) and restart_mode:
                return restart_mode

        return "try-restart"

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
            restart_mode=_restart_mode_for_owner(owner_ref, raw_entries),
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

    LOG.debug("dispatch.quadlet results=%d", len(owner_results))
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
        if not isinstance(kind, str) or kind not in _SERVICE_KINDS:
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
        if not isinstance(kind, str) or kind not in _SERVICE_KINDS:
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

    LOG.debug("dispatch.service results=%d", len(owner_results))
    return owner_results


def _collect_owner_escalations(plan: PlanResult | dict[str, Any]) -> list[str]:
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
