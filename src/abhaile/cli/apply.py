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
from abhaile.apply.coredns import CorednsExecutor
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
class _ApplyFileSync:
    """File synchronization counts and removals selected for owner actions."""

    writes: list[dict[str, object]]
    removals_to_apply: list[dict[str, object]]
    write_count: int
    remove_count: int


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
    return [removal for removal in removals_safe if _is_managed_networkd_dropin_removal(removal)]


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

    write_count = 0
    for action in writes:
        if not isinstance(action, dict):
            raise ApplyError("Invalid write action")
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
        remove_target_file(Path(target_path))
        remove_count += 1

    LOG.info("apply.staging.complete staged=%d removed=%d", write_count, remove_count)
    return _ApplyFileSync(writes, removals_to_apply, write_count, remove_count)


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

    excluded_quadlet_owners: set[str] | None = None
    if CorednsExecutor.build_inputs_changed(writes):
        excluded_quadlet_owners = {"unit:coredns-omada-build.service"}
    quadlet_owner_results = _run_quadlet_owner_actions(
        writes,
        removals_to_apply,
        convergence_plans=quadlet_convergence_plans,
        owner_apply_hints=_owner_apply_hints_from_plan(plan),
        excluded_owner_refs=excluded_quadlet_owners,
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
                    "owner_execution": owner_execution,
                },
                indent=2,
            )
        )
    else:
        print(
            f"mode=apply writes={sync.write_count} "
            f"removals={sync.remove_count} state_updated=true"
        )


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

    sync = _sync_files_for_apply(args, paths, plan, owner_escalations)
    owner_execution = _run_apply_owner_actions(plan, sync)
    LOG.info("apply.owners.complete")
    LOG.info("apply.state_update dir=%s", paths.state_dir)
    update_state_manifests(paths.desired_path, paths.state_dir)
    _print_apply_report(args, sync, owner_execution)

    LOG.info("apply.complete writes=%d removals=%d", sync.write_count, sync.remove_count)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        sys.exit(1)
