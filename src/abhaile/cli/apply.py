"""CLI entrypoint for abhaile-apply."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from abhaile.apply.actions import (
    check_destructive_gate,
    remove_target_file,
)
from abhaile.apply.build import ManagedBuildExecutor
from abhaile.apply.quadlet import QuadletExecutor
from abhaile.apply.staging import _copy_artifact_for_apply
from abhaile.apply.dispatch import (
    _collect_owner_escalations,
    _run_caddy_owner_actions,
    _run_coredns_owner_actions,
    _run_dry_run_validations,
    _run_networkd_owner_actions,
    _run_quadlet_owner_actions,
    _run_service_owner_actions,
    _run_systemd_owner_actions,
    _run_user_owner_actions,
    _run_vault_owner_actions,
)
from abhaile.plan.diff import PlanResult, plan_manifest_drift
from abhaile.state.history import update_state_manifests
from abhaile.cli.common import configure_logging, print_diff_summary, resolve_cli_paths
from abhaile.utils.errors import ApplyError, PipelineError

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ApplyPaths:
    """Resolved filesystem paths used by apply."""

    rendered_dir: Path
    state_dir: Path
    desired_path: Path
    applied_path: Path


@dataclass(frozen=True)
class _RollbackRecord:
    """Previous live file content captured before apply staging."""

    target_path: Path
    existed: bool
    content: bytes | None
    mode: int | None


@dataclass(frozen=True)
class _ApplyFileSync:
    """File synchronization counts and removals selected for owner actions."""

    writes: list[dict[str, object]]
    removals_to_apply: list[dict[str, object]]
    write_count: int
    remove_count: int
    rollback_records: list[_RollbackRecord]


def _is_managed_networkd_dropin_removal(removal: dict[str, object]) -> bool:
    """Return True for managed networkd drop-in file removals eligible for safe auto-prune."""
    kind = removal.get("kind")
    target_path = removal.get("target_path")
    if kind != "networkd.dropin" or not isinstance(target_path, str):
        return False
    path = Path(target_path)
    parent_name = path.parent.name
    return parent_name.endswith(".network.d") and path.suffix == ".conf"


def _default_safe_removals(removals_safe: list[dict[str, object]]) -> list[dict[str, object]]:
    """Select prune-safe removals that should be applied without explicit prune flags."""
    return [
        removal
        for removal in removals_safe
        if _is_managed_networkd_dropin_removal(removal) or removal.get("kind") == "quadlet.image"
    ]


def _local_hostname() -> str:
    """Return short local hostname for safety checks."""
    return socket.gethostname().split(".")[0]


def _check_host_safety(
    plan: dict[str, object] | PlanResult,
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
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: info, -vv: debug)",
    )
    return parser.parse_args(argv)


def _validate_apply_args(args: argparse.Namespace) -> None:
    """Validate CLI argument combinations."""
    if args.prune and args.force_prune:
        raise ApplyError("Use either --prune or --force-prune, not both")
    if args.dry_run_validations and not args.dry_run:
        raise ApplyError("--dry-run-validations requires --dry-run")


def _preflight_apply(args: argparse.Namespace) -> tuple[_ApplyPaths, PlanResult]:
    """Resolve paths, compute drift, and run host safety checks."""
    rendered_dir, state_dir, desired_path, applied_path = resolve_cli_paths(
        args.output,
        args.desired_manifest,
        args.applied_manifest,
    )
    paths = _ApplyPaths(rendered_dir, state_dir, desired_path, applied_path)
    plan = plan_manifest_drift(desired_path, applied_path)
    _check_host_safety(plan, args.host, args.allow_host_mismatch)
    return paths, plan


def _desired_entries_from_plan(plan: PlanResult) -> list[dict[str, object]] | None:
    """Extract desired manifest entries for dry-run validation staging."""
    desired_manifest = plan.get("desired_manifest")
    if not isinstance(desired_manifest, dict):
        return None
    entries_obj = desired_manifest.get("entries")
    if not isinstance(entries_obj, list):
        return None
    return [entry for entry in entries_obj if isinstance(entry, dict)]


def _run_dry_run(
    args: argparse.Namespace,
    paths: _ApplyPaths,
    plan: PlanResult,
    owner_escalations: list[str],
) -> int:
    """Handle dry-run output and optional read-only validations."""
    LOG.info("apply.dry_run writes_planned=%d", len(plan["sync"]["writes"]))
    validation_results: list[dict[str, object]] = []
    if args.dry_run_validations:
        validation_results = _run_dry_run_validations(
            paths.rendered_dir,
            writes=plan["sync"]["writes"],
            desired_entries=_desired_entries_from_plan(plan),
        )
        if not args.json:
            print("mode=dry-run action=validations-only")
    elif not args.json:
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
                    "image_acquisitions": plan.get("image_acquisitions", []),
                    "build_transactions": plan.get("build_transactions", []),
                    "quadlet_convergence_plans": quadlet_convergence_plans,
                },
                indent=2,
            )
        )
    return 0


def _validated_sync_plan(
    plan: PlanResult,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Extract and validate sync plan lists."""
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
    return writes, removals_safe, removals_drifted


def _select_removals_to_apply(
    args: argparse.Namespace,
    removals_safe: list[dict[str, object]],
    removals_drifted: list[dict[str, object]],
    owner_escalations: list[str],
) -> list[dict[str, object]]:
    """Select and deduplicate removals allowed by prune flags and safety gates."""
    removals_to_apply: list[dict[str, object]] = _default_safe_removals(removals_safe)
    if args.force_prune:
        check_destructive_gate(
            gate_name="prune-drifted",
            allow_destructive=args.allow_destructive,
            escalations=owner_escalations,
        )
        removals_to_apply = [*removals_safe, *removals_drifted]
    elif args.prune:
        removals_to_apply = [*removals_safe]

    unique_removals: dict[str, dict[str, object]] = {}
    for removal in removals_to_apply:
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if isinstance(target_path, str):
            unique_removals[target_path] = removal
    return [unique_removals[path] for path in sorted(unique_removals)]


def _sync_files_for_apply(
    args: argparse.Namespace,
    paths: _ApplyPaths,
    plan: PlanResult,
    owner_escalations: list[str],
) -> _ApplyFileSync:
    """Copy desired artifacts and apply selected removals."""
    writes, removals_safe, removals_drifted = _validated_sync_plan(plan)
    LOG.info(
        "apply.plan host=%s writes=%d removals_safe=%d removals_drifted=%d",
        plan["host"],
        len(writes),
        len(removals_safe),
        len(removals_drifted),
    )

    rollback_records: list[_RollbackRecord] = []
    write_count = 0
    for action in writes:
        if not isinstance(action, dict):
            raise ApplyError("Invalid write action")
        target_path = action.get("target_path")
        if isinstance(target_path, str):
            rollback_records.append(_snapshot_target(Path(target_path)))
        _copy_artifact_for_apply(action, paths.rendered_dir)
        write_count += 1

    removals_to_apply = _select_removals_to_apply(
        args, removals_safe, removals_drifted, owner_escalations
    )
    remove_count = 0
    for removal in removals_to_apply:
        target_path = removal.get("target_path") if isinstance(removal, dict) else None
        if not isinstance(target_path, str):
            raise ApplyError("Removal action missing target_path")
        path = Path(target_path)
        rollback_records.append(_snapshot_target(path))
        remove_target_file(path)
        remove_count += 1

    LOG.info("apply.staging.complete staged=%d removed=%d", write_count, remove_count)
    return _ApplyFileSync(writes, removals_to_apply, write_count, remove_count, rollback_records)


def _snapshot_target(path: Path) -> _RollbackRecord:
    """Capture a live target before staging mutates it."""
    if not path.exists() or path.is_dir():
        return _RollbackRecord(path, False, None, None)
    try:
        stat = path.stat()
        return _RollbackRecord(path, True, path.read_bytes(), stat.st_mode & 0o7777)
    except OSError as exc:
        raise ApplyError(f"Failed to snapshot target for rollback: {path} ({exc})") from exc


def _restore_file_sync(rollback_records: list[_RollbackRecord]) -> list[dict[str, object]]:
    """Restore staged files from rollback records in reverse mutation order."""
    errors: list[dict[str, object]] = []
    for record in reversed(rollback_records):
        try:
            if not record.existed:
                if record.target_path.exists() and not record.target_path.is_dir():
                    record.target_path.unlink()
                continue
            if record.content is None:
                continue
            record.target_path.parent.mkdir(parents=True, exist_ok=True)
            record.target_path.write_bytes(record.content)
            if record.mode is not None:
                record.target_path.chmod(record.mode)
        except OSError as exc:
            errors.append(
                {
                    "action": "restore-file",
                    "target_path": record.target_path.as_posix(),
                    "success": False,
                    "error": str(exc),
                }
            )
    return errors


def _restore_quadlet_runtime(sync: _ApplyFileSync) -> list[dict[str, object]]:
    """Reload and restart restored Quadlet container or pod units."""
    owner_kinds: dict[str, set[str]] = {}
    owner_contexts: dict[str, tuple[bool, str | None]] = {}
    for action in [*sync.writes, *sync.removals_to_apply]:
        kind = action.get("kind") if isinstance(action, dict) else None
        if kind not in {"quadlet.container", "quadlet.pod"}:
            continue
        owner_ref = action.get("owner_ref")
        if not isinstance(owner_ref, str) or not owner_ref:
            continue
        hints = action.get("apply_hints")
        rootless = isinstance(hints, dict) and bool(hints.get("rootless"))
        podman_user = hints.get("podman_user") if isinstance(hints, dict) else None
        owner_kinds.setdefault(owner_ref, set()).add(kind)
        owner_contexts.setdefault(
            owner_ref,
            (rootless, podman_user if isinstance(podman_user, str) else None),
        )

    restored: list[dict[str, object]] = []
    for owner_ref in sorted(owner_kinds):
        rootless, run_as_user = owner_contexts[owner_ref]
        try:
            restored.append(
                QuadletExecutor.apply_owner_change(
                    owner_ref,
                    kinds=sorted(owner_kinds[owner_ref]),
                    changed_phases={"write"},
                    rootless=rootless,
                    run_as_user=run_as_user,
                )
            )
        except ApplyError as exc:
            restored.append(
                {
                    "owner_ref": owner_ref,
                    "kinds": sorted(owner_kinds[owner_ref]),
                    "rootless": rootless,
                    "run_as_user": run_as_user if rootless else None,
                    "actions": [
                        {
                            "action": "restore-runtime",
                            "success": False,
                            "error": str(exc),
                        }
                    ],
                }
            )
    return restored


def _rootless_context_from_hints(
    apply_hints: object,
    owner_hints: dict[str, object] | None = None,
) -> tuple[bool, str | None]:
    """Resolve rootless unit context from entry hints with owner hints as fallback."""
    hints = apply_hints if isinstance(apply_hints, dict) else {}
    owner_hints = owner_hints or {}
    rootless = bool(hints.get("rootless", owner_hints.get("rootless", False)))
    podman_user_obj = hints.get("podman_user", owner_hints.get("podman_user"))
    podman_user = podman_user_obj if isinstance(podman_user_obj, str) and podman_user_obj else None
    return (rootless, podman_user)


def _append_unique_verification(
    checks: list[dict[str, object]],
    seen: set[tuple[str, bool, str | None]],
    *,
    unit: str,
    rootless: bool,
    run_as_user: str | None,
    reason: str,
) -> None:
    """Append one unit active check if it has not already been scheduled."""
    key = (unit, rootless, run_as_user if rootless else None)
    if key in seen:
        return
    seen.add(key)
    checks.append(
        {
            "unit": unit,
            "rootless": rootless,
            "run_as_user": run_as_user if rootless else None,
            "reason": reason,
        }
    )


def _append_owner_readiness_checks(
    checks: list[dict[str, object]],
    seen: set[tuple[str, bool, str | None]],
    *,
    owner_payload: object,
) -> None:
    """Schedule supported readiness gates required by an affected owner."""
    if not isinstance(owner_payload, dict):
        return
    requires = owner_payload.get("requires")
    if not isinstance(requires, list):
        return
    for dependency in requires:
        if dependency != "unit:abhaile-secrets-ready.service":
            continue
        _append_unique_verification(
            checks,
            seen,
            unit="abhaile-secrets-ready.service",
            rootless=False,
            run_as_user=None,
            reason="readiness-gate",
        )


def _planned_health_verifications(
    plan: PlanResult,
    sync: _ApplyFileSync,
) -> list[dict[str, object]]:
    """Return affected active units/readiness gates to verify before state update."""
    desired_manifest = plan.get("desired_manifest")
    owners = desired_manifest.get("owners", {}) if isinstance(desired_manifest, dict) else {}
    owner_hints = _owner_apply_hints_from_plan(plan)
    checks: list[dict[str, object]] = []
    seen: set[tuple[str, bool, str | None]] = set()

    for action in sync.writes:
        if not isinstance(action, dict):
            continue
        kind = action.get("kind")
        owner_ref = action.get("owner_ref")
        entry_hints = action.get("apply_hints")

        if isinstance(owner_ref, str) and kind in {"quadlet.container", "quadlet.pod"}:
            hints = owner_hints.get(owner_ref, {})
            if hints.get("restart_mode") != "manual":
                rootless, run_as_user = _rootless_context_from_hints(entry_hints, hints)
                unit = QuadletExecutor.unit_from_owner(owner_ref)
                _append_unique_verification(
                    checks,
                    seen,
                    unit=unit,
                    rootless=rootless,
                    run_as_user=run_as_user,
                    reason="quadlet-runtime",
                )
                if isinstance(owners, dict):
                    _append_owner_readiness_checks(
                        checks,
                        seen,
                        owner_payload=owners.get(owner_ref),
                    )
            continue

        if kind == "service.config" and isinstance(entry_hints, dict):
            restart_unit = entry_hints.get("restart_unit")
            if isinstance(restart_unit, str) and restart_unit:
                rootless, run_as_user = _rootless_context_from_hints(entry_hints)
                _append_unique_verification(
                    checks,
                    seen,
                    unit=restart_unit,
                    rootless=rootless,
                    run_as_user=run_as_user,
                    reason="service-config",
                )
            continue

        if kind == "systemd.unit" and isinstance(owner_ref, str):
            activation_mode = (
                entry_hints.get("activation_mode") if isinstance(entry_hints, dict) else None
            )
            if activation_mode in {"start", "start-now"}:
                rootless, run_as_user = _rootless_context_from_hints(entry_hints)
                unit = QuadletExecutor.unit_from_owner(owner_ref)
                _append_unique_verification(
                    checks,
                    seen,
                    unit=unit,
                    rootless=rootless,
                    run_as_user=run_as_user,
                    reason="systemd-unit",
                )

    build_transactions = plan.get("build_transactions", [])
    if isinstance(build_transactions, list):
        for build in build_transactions:
            if not isinstance(build, dict):
                continue
            scope = build.get("scope")
            rootless = scope == "rootless"
            user_obj = build.get("run_as_user")
            run_as_user = user_obj if rootless and isinstance(user_obj, str) else None
            consumers = build.get("consumers", [])
            if not isinstance(consumers, list):
                continue
            for unit in consumers:
                if isinstance(unit, str) and unit:
                    _append_unique_verification(
                        checks,
                        seen,
                        unit=unit,
                        rootless=rootless,
                        run_as_user=run_as_user,
                        reason="managed-build-consumer",
                    )
    return checks


def _run_apply_health_verifications(
    plan: PlanResult,
    sync: _ApplyFileSync,
) -> list[dict[str, object]]:
    """Verify affected runtime units and readiness gates before applied state is updated."""
    results: list[dict[str, object]] = []
    for check in _planned_health_verifications(plan, sync):
        unit = check["unit"]
        rootless = bool(check.get("rootless"))
        run_as_user_obj = check.get("run_as_user")
        run_as_user = run_as_user_obj if rootless and isinstance(run_as_user_obj, str) else None
        if not isinstance(unit, str):
            continue
        result = QuadletExecutor.verify_unit_active(
            unit,
            rootless=rootless,
            run_as_user=run_as_user,
        )
        results.append(
            {
                **check,
                "action": "verify-active",
                "success": result.success,
                "return_code": result.return_code,
            }
        )
    return results


def _run_image_acquisitions(plan: PlanResult) -> list[dict[str, object]]:
    """Run planned image acquisition actions before file staging."""
    actions = plan.get("image_acquisitions", [])
    if not isinstance(actions, list):
        return []

    results: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        desired_image = action.get("desired_image")
        if not isinstance(desired_image, str) or not desired_image:
            raise ApplyError("Image acquisition action missing desired_image")
        scope = action.get("scope")
        rootless = scope == "rootless"
        run_as_user_obj = action.get("run_as_user")
        run_as_user = (
            run_as_user_obj
            if rootless and isinstance(run_as_user_obj, str) and run_as_user_obj
            else None
        )

        if action.get("old_image") is None and QuadletExecutor.image_exists(
            desired_image,
            rootless=rootless,
            run_as_user=run_as_user,
        ):
            inspect = QuadletExecutor.inspect_image(
                desired_image,
                rootless=rootless,
                run_as_user=run_as_user,
            )
            results.append(
                {
                    **action,
                    "result": "already-local",
                    "live_service_unchanged": True,
                    **inspect,
                }
            )
            continue

        try:
            result = QuadletExecutor.pre_pull_image(
                desired_image,
                rootless=rootless,
                run_as_user=run_as_user,
            )
        except ApplyError as exc:
            service = action.get("service", "unknown")
            current = action.get("old_image") or "<none>"
            raise ApplyError(
                "deployment blocked during image acquisition "
                f"service={service} desired={desired_image} current={current} "
                "live_service_unchanged=true applied_state_unchanged=true "
                f"reason={exc}"
            ) from exc
        results.append({**action, "result": "pulled", "live_service_unchanged": True, **result})
    return results


def _owner_apply_hints_from_plan(plan: PlanResult) -> dict[str, dict[str, object]]:
    """Collect owner-level apply hints from the desired manifest."""
    desired_manifest = plan.get("desired_manifest")
    owner_apply_hints: dict[str, dict[str, object]] = {}
    if not isinstance(desired_manifest, dict):
        return owner_apply_hints
    desired_owners = desired_manifest.get("owners")
    if not isinstance(desired_owners, dict):
        return owner_apply_hints
    for owner_ref, payload in desired_owners.items():
        if not isinstance(owner_ref, str) or not isinstance(payload, dict):
            continue
        apply_hints = payload.get("apply_hints")
        if isinstance(apply_hints, dict):
            owner_apply_hints[owner_ref] = apply_hints
    return owner_apply_hints


def _run_apply_owner_actions(plan: PlanResult, sync: _ApplyFileSync) -> list[dict[str, object]]:
    """Run owner-specific apply actions and return report entries."""
    writes = sync.writes
    removals_to_apply = sync.removals_to_apply

    systemd_owner_results = _run_systemd_owner_actions(writes, removals_to_apply)
    user_owner_results = _run_user_owner_actions(writes)
    vault_owner_results = _run_vault_owner_actions(writes, removals_to_apply)
    netdev_delete_order = plan.get("networkd_netdev_delete_order")
    if not isinstance(netdev_delete_order, list):
        netdev_delete_order = None
    networkd_owner_results = _run_networkd_owner_actions(
        writes, removals_to_apply, netdev_delete_order=netdev_delete_order
    )
    quadlet_convergence_plans = plan.get("quadlet_convergence_plans")
    if not isinstance(quadlet_convergence_plans, dict):
        quadlet_convergence_plans = None

    build_transactions = plan.get("build_transactions", [])
    excluded_quadlet_owners = {
        action["owner_ref"]
        for action in build_transactions
        if isinstance(action, dict) and isinstance(action.get("owner_ref"), str)
    }
    quadlet_owner_results = _run_quadlet_owner_actions(
        writes,
        removals_to_apply,
        convergence_plans=quadlet_convergence_plans,
        owner_apply_hints=_owner_apply_hints_from_plan(plan),
        excluded_owner_refs=excluded_quadlet_owners or None,
    )
    service_owner_results = _run_service_owner_actions(writes, removals_to_apply)
    coredns_owner_results = _run_coredns_owner_actions(writes, removals_to_apply)
    caddy_owner_results = _run_caddy_owner_actions(writes, removals_to_apply)

    return [
        *systemd_owner_results,
        *user_owner_results,
        *coredns_owner_results,
        *caddy_owner_results,
        *vault_owner_results,
        *service_owner_results,
        *networkd_owner_results,
        *quadlet_owner_results,
    ]


def _print_apply_report(
    args: argparse.Namespace,
    sync: _ApplyFileSync,
    owner_execution: list[dict[str, object]],
    image_acquisition_results: list[dict[str, object]],
    build_transaction_results: list[dict[str, object]],
    health_verifications: list[dict[str, object]],
) -> None:
    """Print apply report in text or JSON form."""
    if args.json:
        print(
            json.dumps(
                {
                    "mode": "apply",
                    "writes": sync.write_count,
                    "removals": sync.remove_count,
                    "state_updated": True,
                    "allow_destructive": args.allow_destructive,
                    "image_acquisitions": image_acquisition_results,
                    "build_transactions": build_transaction_results,
                    "owner_execution": owner_execution,
                    "health_verifications": health_verifications,
                },
                indent=2,
            )
        )
    else:
        print(
            f"mode=apply writes={sync.write_count} "
            f"removals={sync.remove_count} state_updated=true"
        )


def _run_managed_build_transactions(plan: PlanResult) -> list[dict[str, object]]:
    """Run planned managed build transactions before consumer owner actions."""
    actions = plan.get("build_transactions", [])
    if not isinstance(actions, list):
        return []
    results: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        service = action.get("service", "unknown")
        try:
            results.append(ManagedBuildExecutor.run_transaction(action))
        except ApplyError as exc:
            raise ApplyError(
                "deployment blocked during managed build "
                f"service={service} applied_state_unchanged=true reason={exc}"
            ) from exc
    return results


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-apply."""
    args = parse_apply_args(argv)
    configure_logging(args.verbose)
    _validate_apply_args(args)
    paths, plan = _preflight_apply(args)
    owner_escalations = _collect_owner_escalations(plan)
    if not args.json:
        print_diff_summary(plan)

    if args.dry_run:
        return _run_dry_run(args, paths, plan, owner_escalations)

    image_acquisition_results = _run_image_acquisitions(plan)
    sync = _sync_files_for_apply(args, paths, plan, owner_escalations)
    build_transaction_results: list[dict[str, object]] = []
    try:
        build_transaction_results = _run_managed_build_transactions(plan)
        owner_execution = _run_apply_owner_actions(plan, sync)
        health_verifications = _run_apply_health_verifications(plan, sync)
    except ApplyError as exc:
        file_restore_errors = _restore_file_sync(sync.rollback_records)
        runtime_restore_results = _restore_quadlet_runtime(sync)
        restore_errors: list[object] = [*file_restore_errors]
        for result in runtime_restore_results:
            actions = result.get("actions")
            if isinstance(actions, list) and any(
                isinstance(action, dict) and action.get("success") is False for action in actions
            ):
                restore_errors.append(result)
        rollback_suffix = (
            f" rollback_errors={json.dumps(restore_errors, sort_keys=True)}"
            if restore_errors
            else ""
        )
        raise ApplyError(
            "deployment failed before state update; previous artifacts restored "
            "applied_state_unchanged=true "
            f"reason={exc}"
            f"{rollback_suffix}"
        ) from exc
    LOG.info("apply.owners.complete")
    LOG.info("apply.state_update dir=%s", paths.state_dir)
    update_state_manifests(paths.desired_path, paths.state_dir)
    _print_apply_report(
        args,
        sync,
        owner_execution,
        image_acquisition_results,
        build_transaction_results,
        health_verifications,
    )

    LOG.info("apply.complete writes=%d removals=%d", sync.write_count, sync.remove_count)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        sys.exit(1)
