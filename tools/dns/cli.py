#!/usr/bin/env python3
"""Unified DNS management CLI for Abhaile.

Provides a single interface for DNS operations:
- Fetch current records from provider
- Plan changes (compare desired vs current)
- Apply changes to provider

Supports deSEC provider (extensible to other providers via DNSProvider interface).

Usage:
    # Fetch current records
    python3 tools/dns/cli.py fetch
    python3 tools/dns/cli.py fetch --format json

    # Plan changes (dry-run)
    python3 tools/dns/cli.py plan

    # Apply changes
    python3 tools/dns/cli.py apply

    # Apply from pre-computed plan file
    python3 tools/dns/cli.py apply --plan-file /path/to/desec.state

Examples:
    # Manual ops: plan and apply
    export DESEC_TOKEN=your_token_here
    python3 tools/dns/cli.py plan > plan.json
    python3 tools/dns/cli.py apply --plan-file plan.json

    # Quick fetch
    python3 tools/dns/cli.py fetch --token-file ~/.config/abhaile/desec.token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure tools package can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.core import PathConfig, get_logger, load_yaml, setup_logging
from tools.common.dns import DNSClient, DesecProvider

logger = get_logger(__name__)

__all__ = [
    "load_token",
    "collect_desired_records",
    "cmd_fetch",
    "cmd_plan",
    "cmd_apply",
    "main",
]


def load_token(args: argparse.Namespace) -> str:
    """Load deSEC token from args, file, or environment.

    Args:
        args: Parsed command-line arguments

    Returns:
        deSEC API token

    Raises:
        SystemExit: If token cannot be loaded
    """
    if args.token:
        return args.token

    if args.token_file:
        token_path = Path(args.token_file).expanduser()
        if not token_path.exists():
            raise SystemExit(f"Token file not found: {token_path}")
        return token_path.read_text().strip()

    env_token = os.getenv("DESEC_TOKEN")
    if env_token:
        return env_token.strip()

    raise SystemExit(
        "deSEC token not provided. Use --token, --token-file, or DESEC_TOKEN env var"
    )


def collect_desired_records(
    network: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collect desired DNS records from config files.

    Only includes records for services that are deployed (present in mapping.yaml).
    Filters to external DNS zone only.

    Args:
        network: Parsed network.yaml
        mapping: Parsed mapping.yaml

    Returns:
        List of desired DNS records
    """
    # Find deployed services
    deployed = set()
    for host_entry in mapping.get("abhaile", []):
        if isinstance(host_entry, dict):
            for _, services_list in host_entry.items():
                deployed.update(services_list)

    services = network.get("services", {})
    desired = []
    zone = "abhaile.dedyn.io"

    for svc_name, svc_def in services.items():
        if svc_name not in deployed:
            continue

        for dns_entry in svc_def.get("dns", []):
            entry_zone = dns_entry.get("zone", "").rstrip(".")
            if entry_zone != zone:
                continue

            for rec in dns_entry.get("records", []):
                rtype = rec.get("type", "").upper()
                name = rec.get("name", "@").rstrip(".")

                # Only handle public record types
                if rtype not in {"A", "AAAA", "CNAME", "TXT", "MX", "SRV"}:
                    continue

                rdata = rec.get("rdata", "")

                # Handle simple address placeholder
                if isinstance(rdata, str) and "strip_cidr" in rdata:
                    # expect format: %%services.<svc>.address | strip_cidr%%
                    from tools.common.core import strip_cidr

                    addr = svc_def.get("address")
                    if addr:
                        rdata = strip_cidr(addr)

                desired.append(
                    {
                        "type": rtype,
                        "name": name if name else "@",
                        "content": [rdata] if isinstance(rdata, str) else rdata,
                    }
                )

    return desired


def cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch current DNS records from provider.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 on success)
    """
    token = load_token(args)
    provider = DesecProvider(token)
    client = DNSClient(provider)

    logger.info("Fetching current DNS records...")
    records = client.fetch_current()

    if args.format == "json":
        print(json.dumps(records, indent=2))
    else:
        # Human-readable format
        for rec in records:
            name = rec.get("name", "@")
            rtype = rec.get("type", "")
            content = rec.get("content", [])
            ttl = rec.get("ttl", 0)
            print(f"{name:30} {ttl:6} {rtype:6} {', '.join(content)}")

    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Plan DNS changes (compare desired vs current).

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 on success, 1 if changes needed)
    """
    token = load_token(args)
    provider = DesecProvider(token)
    client = DNSClient(provider)

    # Load config
    paths = PathConfig.from_env()
    network = load_yaml(paths.config_root / "network.yaml")
    mapping = load_yaml(paths.config_root / "mapping.yaml")

    desired = collect_desired_records(network, mapping)

    logger.info("Planning DNS changes...")
    plan = client.sync(desired, dry_run=True)

    # Output plan as JSON
    print(json.dumps(plan, indent=2))

    # Exit code: 0 if no changes, 1 if changes needed
    return 1 if plan["summary"]["total"] > 0 else 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply DNS changes to provider.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 on success)
    """
    token = load_token(args)
    provider = DesecProvider(token)
    client = DNSClient(provider)

    if args.plan_file:
        # Apply from pre-computed plan file
        plan_path = Path(args.plan_file)
        if not plan_path.exists():
            raise SystemExit(f"Plan file not found: {plan_path}")

        logger.info("Loading plan from %s", plan_path)
        plan = json.loads(plan_path.read_text())

        # Check if plan was skipped (SKIP_DESEC mode)
        if plan.get("skipped"):
            logger.info("Plan was generated with --skip-desec; no changes to apply")
            return 0

        if plan["create"] or plan["update"] or plan["delete"]:
            logger.info("Applying pre-computed plan...")
            provider.apply_plan(plan)
            logger.info("DNS sync complete")
        else:
            logger.info("No changes in plan")
    else:
        # Plan and apply in one step
        paths = PathConfig.from_env()
        network = load_yaml(paths.config_root / "network.yaml")
        mapping = load_yaml(paths.config_root / "mapping.yaml")

        desired = collect_desired_records(network, mapping)

        logger.info("Planning and applying DNS changes...")
        plan = client.sync(desired, dry_run=False)

        if plan["summary"]["total"] == 0:
            logger.info("No changes needed")

    return 0


def main() -> int:
    """Main entry point.

    Args:
        None

    Returns:
        int: Process exit code (0 on success; non-zero on error).
    """
    from tools.common.core.cli import create_parser, add_verbose_flag

    parser = create_parser(
        description="Unified DNS management CLI for Abhaile",
    )
    parser.add_argument(
        "--token",
        help="deSEC API token (or use --token-file or DESEC_TOKEN env)",
    )
    parser.add_argument(
        "--token-file",
        help="Path to file containing deSEC token",
    )
    add_verbose_flag(parser)

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    subparsers.required = True

    # fetch command
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch current DNS records from provider",
    )
    fetch_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    # plan command
    plan_parser = subparsers.add_parser(
        "plan",
        help="Plan DNS changes (compare desired vs current)",
    )
    plan_parser.set_defaults(func=cmd_plan)

    # apply command
    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply DNS changes to provider",
    )
    apply_parser.add_argument(
        "--plan-file",
        help="Apply from pre-computed plan file (e.g., desec.state)",
    )
    apply_parser.set_defaults(func=cmd_apply)

    args = parser.parse_args()

    # Configure logging
    setup_logging(
        level="DEBUG" if args.verbose else "INFO",
    )

    try:
        return args.func(args)
    except KeyboardInterrupt:
        logger.error("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
