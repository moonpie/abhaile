"""Inventory collectors - load raw data from config files.

Collectors are responsible for reading YAML files and returning structured data.
"""

from __future__ import annotations

from typing import Any

from tools.common.core import PathConfig, get_logger, load_yaml


logger = get_logger(__name__)


def collect_mapping_config(paths: PathConfig) -> dict[str, Any]:
    """Load mapping.yaml configuration.

    Returns:
        Parsed mapping.yaml as dict

    Raises:
        FileNotFoundError: If mapping.yaml doesn't exist
        yaml.YAMLError: If parsing fails
    """
    mapping_file = paths.config_root / "mapping.yaml"
    mapping = load_yaml(mapping_file)
    logger.info("Loaded mapping configuration")
    return mapping


def collect_network_config(paths: PathConfig) -> dict[str, Any]:
    """Load network.yaml configuration.

    Returns:
        Parsed network.yaml as dict

    Raises:
        FileNotFoundError: If network.yaml doesn't exist
        yaml.YAMLError: If parsing fails
    """
    network_file = paths.config_root / "network.yaml"
    network = load_yaml(network_file)
    logger.info("Loaded network configuration")
    return network


def collect_dns_zones(paths: PathConfig) -> list[dict[str, str]]:
    """Collect DNS zones from network.yaml.

    Returns:
        List of zone dicts with 'name' and 'provider' keys

    Raises:
        FileNotFoundError: If network.yaml doesn't exist
    """
    network = collect_network_config(paths)

    dns = network.get("dns", {}) or {}
    zones = dns.get("zones", []) or []

    logger.info(f"Collected {len(zones)} DNS zones")
    return zones
