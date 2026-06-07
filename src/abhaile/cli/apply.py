"""CLI entrypoint for abhaile-apply."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from pathlib import Path

from abhaile.apply.actions import (
    check_destructive_gate,
    remove_target_file,
)
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


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-apply."""
    args = parse_apply_args(argv)
    configure_logging(args.verbose)

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
        LOG.info("apply.dry_run writes_planned=%d", len(plan["sync"]["writes"]))
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

    LOG.info(
        "apply.plan host=%s writes=%d removals_safe=%d removals_drifted=%d",
        plan["host"],
        len(writes),
        len(removals_safe),
        len(removals_drifted),
    )
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

    LOG.info("apply.staging.complete staged=%d removed=%d", write_count, remove_count)
    # Phase ordering: systemd before vault (daemon-reload before user services),
    # service before networkd (configs before network changes),
    # networkd before quadlet (network interfaces before containers).
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

    LOG.info("apply.owners.complete")
    LOG.info("apply.state_update dir=%s", state_dir)
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

    LOG.info("apply.complete writes=%d removals=%d", write_count, remove_count)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        sys.exit(1)
