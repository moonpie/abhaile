"""Generate INVENTORY.md from mapping.yaml and network.yaml only."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import sys

# Ensure tools package can be imported when running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.core import PathConfig, setup_logging, get_logger
from tools.inventory.collectors import (
    collect_mapping_config,
    collect_network_config,
    collect_dns_zones,
)
from tools.inventory.analyzers import analyze_dns_zones
from tools.inventory.formatters import format_inventory_markdown
from tools.inventory import MissingConfigError


logger = get_logger(__name__)


def resolve_paths(root: Path | None = None) -> PathConfig:
    """Resolve repository-aware paths for inventory tools.

    Mirrors render PathConfig usage: defaults to environment discovery,
    but allows overriding the repo root for tests or alternate checkouts.
    PathConfig will load paths.ini and derive all paths automatically.
    """

    if root:
        # Let PathConfig derive paths from paths.ini based on repo_root
        return PathConfig(repo_root=root)

    return PathConfig.from_env()


def build_deployments(mapping: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Build host->services mapping from mapping.yaml content.

    The renderer treats mapping.yaml as the single source of host/service placement
    (roles are optional). Here we normalize to {host: {"default": [services]}} for
    simplicity.
    """

    deployments: dict[str, dict[str, list[str]]] = {}
    abhaile = mapping.get("abhaile", []) or []

    for entry in abhaile:
        if not isinstance(entry, dict):
            continue
        for host, services in entry.items():
            if not isinstance(services, list):
                continue
            deployments.setdefault(host, {})["default"] = services

    return deployments


def extract_deployed_services(deployments: dict[str, dict[str, list]]) -> set[str]:
    """Extract all deployed service names from deployment structure."""
    services = set()
    for host_config in deployments.values():
        for services_list in host_config.values():
            services.update(services_list)
    return services


def generate_inventory(
    paths: PathConfig | None = None,
    verbose: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate INVENTORY.md from mapping.yaml and network.yaml.

    Args:
        paths: PathConfig configuration (defaults to workspace root)
        verbose: Enable debug logging
        output_dir: Optional output directory (defaults to repo root)

    Returns:
        Dict containing generated inventory data

    Raises:
        MissingConfigError: If required config files missing
    """
    setup_logging(verbose=verbose)

    if paths is None:
        paths = resolve_paths()

    logger.info(f"Generating inventory from {paths.repo_root}")

    # Collect configuration
    mapping = collect_mapping_config(paths)
    network = collect_network_config(paths)
    dns_zones = collect_dns_zones(paths)

    # Analyze data
    deployments = build_deployments(mapping)
    deployed_services = extract_deployed_services(deployments)
    dns_analysis = analyze_dns_zones(dns_zones)

    logger.info(f"Found {len(deployments)} hosts and {len(deployed_services)} services")
    logger.info(
        f"Found {dns_analysis['total_internal']} internal and "
        f"{dns_analysis['total_external']} external DNS zones"
    )

    # Format output
    inventory_md = format_inventory_markdown(network, deployments, dns_analysis)

    inventory_dir = Path(output_dir) if output_dir else paths.repo_root
    inventory_dir.mkdir(parents=True, exist_ok=True)

    md_file = inventory_dir / "INVENTORY.md"
    md_file.write_text(inventory_md)
    logger.info(f"Wrote {md_file}")

    logger.info("\n" + "=" * 60)
    logger.info("INVENTORY GENERATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Output: {md_file.parent}")
    logger.info(f"- {len(deployments)} hosts")
    logger.info(f"- {len(deployed_services)} deployed services")

    return {"deployments": deployments, "network": network}


def main() -> int:
    """Generate inventory CLI.

    Returns:
        int: Exit code (0 success; 2 validation error; 1 unexpected error).
    """
    from tools.common.core.cli import create_parser

    parser = create_parser(
        description="Generate infrastructure inventory from rendered output"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Custom output directory for inventory files",
    )
    parser.add_argument(
        "--root", type=Path, help="Project root directory (defaults to workspace root)"
    )

    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    paths = resolve_paths(root=args.root)

    try:
        generate_inventory(
            paths=paths, verbose=args.verbose, output_dir=args.output_dir
        )
        return 0
    except MissingConfigError as e:
        logger.error(f"Inventory generation failed: {e}")
        return 2
    except Exception:
        logger.exception("Unexpected error during inventory generation")
        return 1


if __name__ == "__main__":
    sys.exit(main())
