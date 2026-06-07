"""CLI entrypoint for abhaile-inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import PipelineError
from abhaile.utils.paths import get_repo_root, load_paths
from abhaile.validation.services import parse_mapping


def parse_inventory_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for abhaile-inventory."""
    parser = argparse.ArgumentParser(description="Print host-to-services inventory")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Check that each service has a service.yaml",
    )
    return parser.parse_args(argv)


def _load_host_services(config_root: Path) -> dict[str, list[str]]:
    """Load host-to-services mapping from mapping.yaml."""
    mapping_path = config_root / "mapping.yaml"
    mapping = read_yaml_mapping(mapping_path)
    return parse_mapping(mapping)


def _validate_service_definitions(
    host_services: dict[str, list[str]], config_root: Path
) -> list[str]:
    """Check that each mapped service has a service.yaml. Return missing paths."""
    missing: list[str] = []
    seen: set[str] = set()
    for services in host_services.values():
        for service in services:
            if service in seen:
                continue
            seen.add(service)
            service_path = config_root / "services" / service / "service.yaml"
            if not service_path.exists():
                missing.append(str(service_path))
    return sorted(missing)


def main(argv: list[str] | None = None) -> int:
    """Run abhaile-inventory."""
    args = parse_inventory_args(argv)

    repo_root = get_repo_root(Path(__file__))
    paths = load_paths(repo_root)
    config_root = repo_root / paths["config_root"]

    host_services = _load_host_services(config_root)

    if args.validate:
        missing = _validate_service_definitions(host_services, config_root)
        if missing:
            for path in missing:
                print(f"missing: {path}", file=sys.stderr)
            return 1

    if args.json:
        # Hosts sorted, services in mapping order
        output: dict[str, Any] = {
            host: host_services[host] for host in sorted(host_services.keys())
        }
        print(json.dumps(output, indent=2))
    else:
        for host in sorted(host_services.keys()):
            print(f"{host}:")
            for service in host_services[host]:
                print(f"  {service}")
            print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PipelineError as exc:
        print(f"inventory: {exc}", file=sys.stderr)
        sys.exit(1)
