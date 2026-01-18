#!/usr/bin/env python3
"""Rendering engine for Abhaile GitOps.

This script reads:
- config/mapping.yaml (hosts -> services placement)
- config/network.yaml (vlans, hosts, services definitions)
- config/services/<service>/service.yaml (service metadata)
- config/hosts/<host>/systemd-networkd/*.j2 (host-specific templates)
- config/hosts/templates/*.j2 (shared templates for drop-ins)

It renders Jinja2 templates into `out/rendered/` and validates configuration.

Usage:
    tools/render/cli.py [--output-dir DIR] [--skip-desec] [--strict-desec] [--validate-only]

Always renders all hosts from mapping.yaml (required for Caddy, DNS, deSEC context).
"""
from __future__ import annotations
from typing import Any
import os

import sys
from pathlib import Path

# Ensure tools package can be imported when running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.core import (
    PathConfig,
    get_jinja_env,
    get_logger,
    load_yaml,
    setup_logging,
)

__all__ = ["main"]
from tools.common.core.context_utils import last_octet
from tools.render.validate import validate_last_octet_uniqueness
from tools.render.services.service_builder import build_service_configs
from tools.render.services.service_meta import load_service_meta_with_includes
from tools.render.quadlet.quadlet_builder import build_quadlet_outputs
from tools.render.dns.dns_builder import (
    build_dns_context,
    build_desec_context,
)
from tools.render.dns.desec_plan import build_desec_plan, summarize_desec_drift
from tools.render.host.networkd_builder import build_networkd_outputs
from tools.render.services.caddy_builder import build_caddy_configs
from tools.render.services.vault_template_builder import (
    collect_vault_agent_templates,
    stage_vault_agent_templates,
)
from tools.render.host.user_builder import build_user_configs
from tools.render.host.software_builder import build_software_configs
from tools.render.host.resolved_builder import build_resolved_configs
from tools.common.core import ValidationError, RenderError


logger = get_logger(__name__)


def render_host(hostname: str, out_dir: Path, paths: PathConfig) -> None:
    """Render systemd-networkd configuration for a single host.

    Args:
        hostname: Name of host to render.
        out_dir: Output directory for rendered files.
        paths: PathConfig with config/output directories.

    Raises:
        ValidationError: If host not found in mapping or service validation fails.
        RenderError: If template rendering fails or required files missing.
    """

    # Load configuration files
    mapping = load_yaml(paths.config_root / "mapping.yaml")
    network = load_yaml(paths.config_root / "network.yaml")
    services_dir = paths.config_root / "services"

    # Validate last-octet uniqueness
    validate_last_octet_uniqueness(network)

    # Validate host mapping and get services assigned
    from tools.render.validate import validate_host_mapping

    host_services = validate_host_mapping(mapping, hostname)

    # Build list of all deployed services across all hosts for global context
    # (DNS zones, Caddy ingress blocks need to reference all services)
    all_deployed_services = []
    for host_entry in mapping.get("abhaile", []):
        if isinstance(host_entry, dict):
            for services_list in host_entry.values():
                all_deployed_services.extend(services_list)

    # Load service metadata for ALL deployed services (not just this host)
    # Needed for Caddy ingress blocks, DNS zones, and TLS issuer extraction
    services_meta: dict[str, Any] = {}
    meta_cache: dict[str, Any] = {}
    for svc in all_deployed_services:
        services_meta[svc] = load_service_meta_with_includes(
            svc, services_dir, meta_cache
        )

    # Prepare Jinja2 environment with host-specific and shared templates
    host_templates = paths.config_root / "hosts" / hostname / "systemd-networkd"
    shared_templates = paths.config_root / "_templates" / "hosts"

    env = get_jinja_env([host_templates, shared_templates])

    out_dir.mkdir(parents=True, exist_ok=True)

    # Prepare template context
    ctx = {
        "hosts": network.get("hosts", {}),
        "vlans": network.get("vlans", {}),
        "services": network.get("services", {}),
        "host_name": hostname,
    }

    # Build DNS context for zone templates using all deployed services
    dns_ctx = build_dns_context(
        deployed_services=all_deployed_services,
        network=network,
        hosts=network.get("hosts", {}),
        services_meta=services_meta,
        repo_root=paths.repo_root,
    )

    # Add DNS context to template context
    ctx["dns"] = dns_ctx

    # Collect and stage Vault-Agent templates from services and includes
    va_templates, va_templates_copy = collect_vault_agent_templates(
        host_services=host_services,
        services_meta=services_meta,
        services_dir=services_dir,
        output_root=paths.output_root,
        hostname=hostname,
    )
    ctx["vault_agent_templates"] = va_templates
    stage_vault_agent_templates(va_templates_copy)

    # Build networkd outputs (pure) and write them
    network_outputs, network_files_map = build_networkd_outputs(
        hostname=hostname,
        ctx=ctx,
        host_templates=host_templates,
        shared_templates=shared_templates,
    )
    for rel_path, content in network_outputs:
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
        logger.info("Wrote %s", dest)

    # Convert network_files_map to absolute drop-in paths
    network_files = {
        iface: out_dir / dropin for iface, dropin in network_files_map.items()
    }

    # Note: Network requirements are pre-validated in validate_all() before rendering
    # Skip redundant validation here to avoid signature mismatch

    # Generate per-service drop-in .conf files
    for svc in host_services:
        svc_meta = services_meta.get(svc, {})
        svc_network = svc_meta.get("network")

        # Skip services with network: host (they use host network stack)
        if svc_network == "host":
            continue

        # Get service definition from network.yaml
        svc_def = network.get("services", {}).get(svc)
        svc_address = svc_def.get("address") if svc_def else None
        svc_vlan = svc_def.get("vlan") if svc_def else None

        # Determine which template to use based on network mode
        if svc_network == "service-32":
            template_name = "service-addr.conf.j2"
        elif svc_network == "ipvlan-l2":
            template_name = "service-route.conf.j2"
        else:
            raise RenderError(
                f"Service '{svc}' has unsupported network mode '{svc_network}'"
            )

        # Determine the drop-in directory based on VLAN dynamically
        vlan_info = network.get("vlans", {}).get(svc_vlan, {})
        vlan_id = vlan_info.get("id")
        # Prefer ipvlan shim matching VLAN id, else plain ipvlan-l2
        preferred_iface = f"ipvlan-l2.{vlan_id}"
        if preferred_iface in network_files:
            dropin_dir = network_files[preferred_iface]
            interface_name = preferred_iface
        elif "ipvlan-l2" in network_files:
            dropin_dir = network_files["ipvlan-l2"]
            interface_name = "ipvlan-l2"
        else:
            raise RenderError(
                f"No matching ipvlan network found for VLAN id {vlan_id} on host {hostname}"
            )

        dropin_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename using last octet
        oct = last_octet(svc_address)
        fname = f"{oct:03d}-{svc}.conf"

        # Render template with service-specific context
        svc_ctx = {
            **ctx,
            "service_name": svc,
            "interface_name": interface_name,
        }

        tpl = env.get_template(template_name)
        rendered = tpl.render(**svc_ctx)

        out_path = dropin_dir / fname
        if not rendered.endswith("\n"):
            rendered += "\n"
        out_path.write_text(rendered)
        logger.info("Wrote %s", out_path)

    # Build service-specific configuration files (pure) and write
    svc_rendered, svc_copied = build_service_configs(
        hostname=hostname,
        host_services=host_services,
        services_meta=services_meta,
        ctx=ctx,
        services_dir=services_dir,
    )
    for rel_path, content in svc_rendered:
        dest = paths.output_root / hostname / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
        logger.info("Wrote service config: %s", dest)
    for rel_path, data in svc_copied:
        dest = paths.output_root / hostname / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("Copied service config: %s", dest)

    # Render host-level container network quadlets using unified template
    shared_services_tpl = paths.config_root / "_templates" / "services" / "quadlets"
    if shared_services_tpl.exists():
        containers_env = get_jinja_env([shared_services_tpl])
        containers_out_dir = (
            paths.output_root
            / hostname
            / "services"
            / "podman-networks"
            / "etc"
            / "containers"
            / "systemd"
        )
        containers_out_dir.mkdir(parents=True, exist_ok=True)

        # Determine which VLANs are required by containers on this host
        required_vlans = set()
        for svc in host_services:
            svc_meta = services_meta.get(svc, {})
            if (
                svc_meta.get("type") == "container"
                and svc_meta.get("network") == "ipvlan-l2"
            ):
                svc_def = network.get("services", {}).get(svc)
                if svc_def:
                    vlan_name = svc_def.get("vlan")
                    if vlan_name:
                        required_vlans.add(vlan_name)

        # Note: Container VLAN requirements are pre-validated in validate_all()
        # Use computed required_vlans set for network quadlet rendering
        for vlan_name in required_vlans:
            tpl = containers_env.get_template("network.network.j2")
            rendered = tpl.render(**ctx, vlan_name=vlan_name)
            out_path = containers_out_dir / f"{vlan_name}.network"
            if not rendered.endswith("\n"):
                rendered += "\n"
            out_path.write_text(rendered)
            logger.info("Wrote %s", out_path)

    # Build quadlet outputs for container and pod services and write them
    quadlet_outputs = build_quadlet_outputs(
        hostname=hostname,
        host_services=host_services,
        network=network,
        services_meta=services_meta,
        out_dir=paths.output_root / hostname,
        root=paths.config_root.parent,
    )
    for dest, content in quadlet_outputs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
        logger.info("Wrote quadlet: %s", dest)

    # Render Caddyfiles for caddy-internal and caddy-dmz (if deployed on this host)
    # Use all_deployed_services so Caddy gets ingress blocks from all hosts,
    # but only render Caddy configs if this host has Caddy services
    caddy_services_on_host = [svc for svc in host_services if svc.startswith("caddy-")]
    if caddy_services_on_host:
        # Create a filtered deployed_services list that only includes caddy-* services on this host
        # but keeps all other services for ingress block collection
        filtered_services = [
            svc
            for svc in all_deployed_services
            if not svc.startswith("caddy-") or svc in caddy_services_on_host
        ]
        caddy_outputs = build_caddy_configs(
            hostname=hostname,
            deployed_services=filtered_services,
            services_meta=services_meta,
            services_dir=services_dir,
        )
        for rel_path, content in caddy_outputs:
            dest = paths.output_root / hostname / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            logger.info("Wrote Caddyfile: %s", dest)

    # Build user configuration
    build_user_configs(
        hostname,
        config_path=paths.config_root / "hosts",
        output_path=paths.output_root,
    )

    # Build software configuration (apt packages + post-install actions)
    build_software_configs(
        hostname,
        hosts_path=paths.config_root / "hosts",
        output_path=paths.output_root,
    )

    # Build systemd-resolved configuration
    build_resolved_configs(
        hostname,
        hosts_path=paths.config_root / "hosts",
        output_path=paths.output_root,
    )


def main() -> int:
    """Render CLI entry point.

    Returns:
        int: Exit code (0 on success; 1 render error; 2 validation error).
    """
    from tools.common.core.cli import create_parser

    parser = create_parser(
        description=(
            "Render all hosts from mapping.yaml (requires full context for Caddy, DNS, deSEC)"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory root (default: out/rendered/)",
    )
    parser.add_argument(
        "--skip-desec",
        action="store_true",
        help="Skip external DNS (deSEC) drift check and plan generation",
    )
    parser.add_argument(
        "--strict-desec",
        action="store_true",
        help="Fail render if deSEC drift check cannot complete",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation checks only, do not render (exit 0 if valid, 2 if errors)",
    )
    # Use parse_known_args to ignore unrelated argv (e.g. pytest flags) when imported
    args, _ = parser.parse_known_args()

    # Create PathConfig with custom output directory if specified
    output_root = Path(args.output_dir) if args.output_dir else None
    paths = PathConfig.from_env(output_root=output_root)

    skip_desec = args.skip_desec or bool(int(os.getenv("SKIP_DESEC", "0")))
    strict_desec = args.strict_desec or bool(int(os.getenv("STRICT_DESEC", "0")))

    # Configure logging for CLI execution so info messages are visible
    setup_logging(level="INFO")

    # Run pre-render validation
    from tools.render.validate import validate_all

    validation_errors = validate_all(paths)

    if validation_errors:
        logger.error("Pre-render validation failed:")
        for error in validation_errors:
            logger.error("  - %s", error)
        if args.validate_only:
            return 2
        logger.error("Aborting render due to validation errors")
        return 2

    if args.validate_only:
        logger.info("Validation passed: configuration is valid")
        return 0

    # Load mapping to get list of hosts
    mapping = load_yaml(paths.config_root / "mapping.yaml")
    network = load_yaml(paths.config_root / "network.yaml")

    # Extract all hostnames from mapping structure
    # Always render all hosts since Caddy, DNS, and deSEC require full context
    hosts_to_render = []
    for host_entry in mapping.get("abhaile", []):
        if isinstance(host_entry, dict):
            hosts_to_render.extend(host_entry.keys())

    try:
        if not mapping or not mapping.get("abhaile"):
            raise ValidationError("no hosts found in mapping.yaml")

        if not hosts_to_render:
            raise ValidationError("no hosts found in mapping.yaml")

        for hostname in hosts_to_render:
            out = paths.output_root / hostname / "systemd-networkd"
            logger.info("=== Rendering host %s -> %s ===", hostname, out)
            render_host(hostname, out, paths)
            logger.info("=== Completed %s ===", hostname)

        # Build deSEC context and report drift (always, not just when applying)
        logger.info("=== deSEC DNS Drift Report ===")
        all_deployed = []
        for host_entry in mapping.get("abhaile", []):
            if isinstance(host_entry, dict):
                for services_list in host_entry.values():
                    all_deployed.extend(services_list)

        desec_ctx = build_desec_context(
            deployed_services=all_deployed,
            network=network,
        )
        desired_recs = desec_ctx.get("desired_records", [])

        token = os.getenv("DESEC_TOKEN")
        plan, skipped = build_desec_plan(
            desired_records=desired_recs,
            token=token,
            strict=strict_desec,
            skip=skip_desec,
        )

        # Write deSEC plan file for apply phase
        import json

        state_dir = paths.state_root
        state_dir.mkdir(parents=True, exist_ok=True)
        plan_file = state_dir / "desec_plan.json"
        plan_file.write_text(json.dumps(plan, indent=2, default=str))
        logger.info("Wrote deSEC plan to %s", plan_file)

        creates, updates, deletes = summarize_desec_drift(plan)

        if skipped:
            logger.info("Skipping deSEC drift check (--skip-desec)")
        elif plan.get("error"):
            logger.warning(
                "deSEC drift check unavailable (recording desired state only): %s",
                plan.get("error"),
            )
        elif any([creates, updates, deletes]):
            logger.info("Detected deSEC drift:")
            for (name, rtype), contents in plan.get("create", []):
                logger.info("  [CREATE] %s %s -> %s", name or "@", rtype, contents)
            for (name, rtype), contents in plan.get("update", []):
                logger.info("  [UPDATE] %s %s -> %s", name or "@", rtype, contents)
            for name, rtype in plan.get("delete", []):
                logger.info("  [DELETE] %s %s", name or "@", rtype)
        else:
            logger.info("No deSEC drift detected")
    except ValidationError as ve:
        logger.error("VALIDATION ERROR: %s", ve)
        return 2
    except RenderError as re:
        logger.error("RENDER ERROR: %s", re)
        return 1
    except Exception as e:
        logger.exception("Unexpected error during render: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
