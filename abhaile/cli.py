#!/usr/bin/env python3
"""CLI entry point for Abhaile rendering."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from abhaile.utils.errors import RenderError
from abhaile.utils.paths import get_repo_root, load_paths, resolve_output_root
from abhaile.utils.config import clear_config_cache, read_json, read_yaml_mapping
from abhaile.validation.schema import validate_schema
from abhaile.validation.network import validate_network_sanity, validate_host_physical_device
from abhaile.validation.dns import validate_dns_serials
from abhaile.validation.services import (
    parse_mapping,
    ensure_service_definitions,
    validate_service_names,
    get_all_services_in_order,
)
from abhaile.renderers.manifest import build_manifest, write_manifest
from abhaile.renderers.host import render_host_config
from abhaile.renderers.services import render_service_configs
from abhaile.renderers.quadlets import render_service_quadlets
from abhaile.renderers.ingress import render_ingress_configs
from abhaile.renderers.vault_templates import render_vault_agent_configs
from abhaile.dns import render_dns
from abhaile.renderers.networkd import (
    render_networkd_config,
    render_networkd_dropins,
)
from abhaile.types.config import MappingConfig, NetworkConfig, ServiceConfig

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidatedConfig:
    """Validated configuration for rendering."""

    host_services: dict[str, list[str]]
    mapping: MappingConfig
    network: NetworkConfig
    service_paths: list[Path]


@dataclass(frozen=True)
class ConfigRoots:
    """Resolved config roots."""

    config_root: Path
    schemas_root: Path
    hosts_root: Path
    mapping_path: Path
    network_path: Path


@dataclass(frozen=True)
class ConfigSchemas:
    """Loaded JSON schemas."""

    mapping: dict[str, Any]
    network: dict[str, Any]
    service: dict[str, Any]
    host: dict[str, Any]


def load_and_validate(repo_root: Path, paths: dict[str, str]) -> ValidatedConfig:
    """Load and validate all configuration files."""
    roots = _resolve_config_roots(repo_root, paths)
    schemas = _load_config_schemas(roots)
    mapping, network = _load_mapping_and_network(roots)
    _validate_mapping_and_network(mapping, network, roots, schemas)
    host_services = _validate_hosts(mapping, network, roots, schemas)
    service_paths = _validate_services(host_services, roots, schemas)
    return ValidatedConfig(
        host_services=host_services,
        mapping=mapping,
        network=network,
        service_paths=service_paths,
    )


def _resolve_config_roots(repo_root: Path, paths: dict[str, str]) -> ConfigRoots:
    """Resolve filesystem roots for config and schema assets."""
    config_root = repo_root / paths["config_root"]
    schemas_root = repo_root / paths["schemas_root"]
    hosts_root = config_root / paths["hosts_subdir"]
    return ConfigRoots(
        config_root=config_root,
        schemas_root=schemas_root,
        hosts_root=hosts_root,
        mapping_path=config_root / "mapping.yaml",
        network_path=config_root / "network.yaml",
    )


def _load_config_schemas(roots: ConfigRoots) -> ConfigSchemas:
    """Load JSON schemas for mapping, network, service, and host files."""
    return ConfigSchemas(
        mapping=read_json(roots.schemas_root / "mapping.schema.json"),
        network=read_json(roots.schemas_root / "network.schema.json"),
        service=read_json(roots.schemas_root / "service.schema.json"),
        host=read_json(roots.schemas_root / "host.schema.json"),
    )


def _load_mapping_and_network(roots: ConfigRoots) -> tuple[MappingConfig, NetworkConfig]:
    """Load mapping.yaml and network.yaml into dicts."""
    mapping = cast(
        MappingConfig,
        read_yaml_mapping(roots.mapping_path),
    )
    network = cast(
        NetworkConfig,
        read_yaml_mapping(roots.network_path),
    )
    return mapping, network


def _validate_mapping_and_network(
    mapping: MappingConfig,
    network: NetworkConfig,
    roots: ConfigRoots,
    schemas: ConfigSchemas,
) -> None:
    """Validate mapping and network configs plus basic network sanity."""
    validate_schema(
        mapping,
        schemas.mapping,
        str(roots.mapping_path),
        roots.schemas_root / "mapping.schema.json",
    )
    validate_schema(
        network,
        schemas.network,
        str(roots.network_path),
        roots.schemas_root / "network.schema.json",
    )
    validate_network_sanity(cast(dict[str, Any], network))
    validate_service_names(roots.config_root)


def _validate_hosts(
    mapping: MappingConfig,
    network: NetworkConfig,
    roots: ConfigRoots,
    schemas: ConfigSchemas,
) -> dict[str, list[str]]:
    """Validate host configs and return host-to-services mapping."""
    host_services = parse_mapping(cast(dict[str, Any], mapping))
    for host in host_services.keys():
        host_yaml_path = roots.hosts_root / host / "host.yaml"
        if host_yaml_path.exists():
            host_data = read_yaml_mapping(host_yaml_path)
            validate_schema(
                host_data,
                schemas.host,
                str(host_yaml_path),
                roots.schemas_root / "host.schema.json",
            )
            validate_host_physical_device(host, host_data, cast(dict[str, Any], network))
    return host_services


def _validate_services(
    host_services: dict[str, list[str]],
    roots: ConfigRoots,
    schemas: ConfigSchemas,
) -> list[Path]:
    """Validate service definitions and return their paths."""
    service_paths: list[Path] = []
    for service in sorted({svc for services in host_services.values() for svc in services}):
        service_paths.extend(ensure_service_definitions(roots.config_root, [service]))

    for service_path in service_paths:
        service_data = cast(
            ServiceConfig,
            read_yaml_mapping(service_path),
        )
        validate_schema(
            service_data,
            schemas.service,
            str(service_path),
            roots.schemas_root / "service.schema.json",
        )

    return service_paths


def render_host(
    host: str,
    output_override: Path | None,
    paths: dict[str, str],
    all_mode: bool,
    repo_root: Path,
    mapping: MappingConfig,
    network: NetworkConfig,
    host_services: dict[str, list[str]],
) -> Path:
    """Render a single host.

    Args:
        host: Host name.
        output_override: Optional output root override.
        paths: Path configuration.
        all_mode: True if rendering all hosts.
        repo_root: Repository root path.
        mapping: Mapping configuration.
        network: Network configuration from network.yaml.
        host_services: Mapping of host to services.

    Returns:
        Path to manifest.json.
    """
    output_root = resolve_output_root(host, output_override, paths, all_mode)
    rendered_dir, state_dir = _prepare_output_dirs(output_root, paths)
    config_root = repo_root / paths["config_root"]

    host_config, common_config = _load_host_configs(host, config_root, paths)
    system_dir, services_output_dir = _prepare_host_artifact_dirs(rendered_dir, paths)

    _render_host_system(
        host,
        host_config,
        common_config,
        network,
        config_root,
        system_dir,
        host_services.get(host, []),
    )

    all_services = get_all_services_in_order(cast(dict[str, Any], mapping))
    _render_host_services(
        host,
        host_services.get(host, []),
        all_services,
        network,
        config_root,
        services_output_dir,
        rendered_dir,
    )

    manifest_path = _write_manifest(rendered_dir, state_dir, paths)

    # Validate DNS serials after rendering so artifacts exist for troubleshooting
    validate_dns_serials(cast(dict[str, Any], network), all_services)

    return manifest_path


def _prepare_output_dirs(output_root: Path, paths: dict[str, str]) -> tuple[Path, Path]:
    """Create rendered and state output directories."""
    rendered_dir = output_root / paths["rendered_dir_name"]
    state_dir = output_root / paths["state_dir_name"]
    rendered_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    return rendered_dir, state_dir


def _load_host_configs(host: str, config_root: Path, paths: dict[str, str]) -> tuple[dict, dict]:
    """Load host and common host configuration files."""
    hosts_root = config_root / paths["hosts_subdir"]
    common_path = hosts_root / "common" / "host.yaml"
    host_path = hosts_root / host / "host.yaml"
    common_config = read_yaml_mapping(common_path)
    host_config = read_yaml_mapping(host_path)
    return host_config, common_config


def _prepare_host_artifact_dirs(rendered_dir: Path, paths: dict[str, str]) -> tuple[Path, Path]:
    """Create system and services output directories for a host."""
    system_dir = rendered_dir / paths["system_dir_name"]
    system_dir.mkdir(parents=True, exist_ok=True)

    software_dir = rendered_dir / paths["software_dir_name"]
    software_dir.mkdir(parents=True, exist_ok=True)

    users_dir = rendered_dir / paths["users_dir_name"]
    users_dir.mkdir(parents=True, exist_ok=True)

    services_output_dir = rendered_dir / paths["services_dir_name"]
    services_output_dir.mkdir(parents=True, exist_ok=True)

    return system_dir, services_output_dir


def _render_host_system(
    host: str,
    host_config: dict,
    common_config: dict,
    network: NetworkConfig,
    config_root: Path,
    system_dir: Path,
    services: list[str],
) -> None:
    """Render system configuration artifacts for a host."""
    render_host_config(
        host,
        host_config,
        common_config,
        cast(dict[str, Any], network),
        config_root,
        system_dir,
    )
    render_networkd_config(
        host,
        host_config,
        common_config,
        cast(dict[str, Any], network),
        config_root,
        system_dir,
    )
    render_networkd_dropins(
        host,
        services,
        cast(dict[str, Any], network),
        config_root,
        system_dir / "etc/systemd/network",
    )


def _render_host_services(
    host: str,
    services: list[str],
    all_services: list[str],
    network: NetworkConfig,
    config_root: Path,
    services_output_dir: Path,
    rendered_dir: Path,
) -> None:
    """Render service, ingress, vault, and DNS artifacts for a host."""
    render_service_configs(
        host,
        services,
        cast(dict[str, Any], network),
        config_root,
        services_output_dir,
    )
    render_service_quadlets(
        host,
        services,
        cast(dict[str, Any], network),
        config_root,
        services_output_dir,
    )
    render_ingress_configs(host, services, all_services, config_root, services_output_dir)
    render_vault_agent_configs(
        host,
        services,
        cast(dict[str, Any], network),
        config_root,
        services_output_dir,
    )
    render_dns(cast(dict[str, Any], network), rendered_dir, services, all_services, config_root)


def _write_manifest(rendered_dir: Path, state_dir: Path, paths: dict[str, str]) -> Path:
    """Build and write the render manifest to state."""
    target_root = Path(paths["target_root"])
    manifest = build_manifest(rendered_dir, target_root)
    manifest_path = state_dir / "manifest.json"
    write_manifest(manifest, manifest_path)
    return manifest_path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Render Abhaile desired state")
    parser.add_argument("--host", help="Host to render (e.g., phobos)")
    parser.add_argument("--all", action="store_true", help="Render all hosts")
    parser.add_argument("--output", help="Output root override (workstation/CI)")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: info, -vv: debug)",
    )
    return parser.parse_args()


def _configure_logging(verbosity: int) -> None:
    """Configure CLI logging verbosity."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s event=%(message)s",
    )


def main() -> int:
    """Main entry point."""
    args = parse_args()
    _configure_logging(args.verbose)

    if args.all and args.host:
        raise RenderError("Use either --host or --all, not both")
    if not args.all and not args.host:
        raise RenderError("--host is required unless --all is specified")

    clear_config_cache()

    repo_root = get_repo_root(Path(__file__))
    paths = load_paths(repo_root)

    output_override = Path(args.output).resolve() if args.output else None

    LOG.info(
        "render.start mode=%s host=%s output_override=%s",
        "all" if args.all else "single",
        args.host if args.host else "*",
        output_override if output_override else "<default>",
    )

    validated = load_and_validate(repo_root, paths)

    if args.all:
        hosts = sorted(validated.host_services.keys())
    else:
        if args.host not in validated.host_services:
            raise RenderError(f"Unknown host '{args.host}' in mapping.yaml")
        hosts = [args.host]

    LOG.info("render.hosts_selected count=%d hosts=%s", len(hosts), ",".join(hosts))

    for host in hosts:
        LOG.info("render.host.begin host=%s", host)
        render_host(
            host,
            output_override,
            paths,
            all_mode=args.all,
            repo_root=repo_root,
            mapping=validated.mapping,
            network=validated.network,
            host_services=validated.host_services,
        )
        LOG.info("render.host.complete host=%s", host)

    LOG.info("render.complete hosts=%d", len(hosts))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RenderError as exc:
        print(f"render: {exc}", file=sys.stderr)
        sys.exit(1)
