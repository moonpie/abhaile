"""Vault-agent templates renderer for aggregating vault_agent template configurations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.config import read_yaml
from utils.errors import RenderError


def render_vault_agent_configs(
    host: str,
    host_services: List[str],
    network: Dict[str, Any],
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render aggregated vault-agent configuration for the host.

    Finds the base vault-agent service (with vault_agent.base) on the current host,
    then aggregates vault_agent.templates from services ONLY on the same host
    (since vault-agent writes to local filesystem).

    Args:
        host: Host name (e.g., phobos, deimos).
        host_services: Services mapped to this specific host.
        network: Network configuration from network.yaml.
        config_root: Path to config/ directory.
        output_dir: Path to rendered services root (rendered/services).

    Raises:
        RenderError: If rendering fails or validation errors occur.
    """
    if not host_services:
        return

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find base vault-agent service
    base_service = _find_base_vault_agent_service(services_root, host_services)

    if not base_service:
        # No vault-agent on this host
        return

    # Load base service configuration
    service_yaml = services_root / base_service / "service.yaml"
    service_data = read_yaml(service_yaml) or {}

    vault_agent_def = service_data.get("composition", {}).get("vault_agent", {})
    base = vault_agent_def.get("base")

    if not base:
        raise RenderError(
            f"Service '{base_service}' missing vault_agent.base definition"
        )

    source = base.get("source")
    destination = base.get("destination")

    if not source or not destination:
        raise RenderError(
            f"Service '{base_service}' vault_agent.base missing source or destination"
        )

    templates_host_root, templates_mount_root, out_mount_root = (
        _resolve_vault_agent_volume_paths(base_service, service_data)
    )

    # Collect templates from services on this host
    templates = _collect_vault_agent_templates(
        host_services,
        services_root,
        output_dir,
        templates_host_root,
        templates_mount_root,
        out_mount_root,
    )

    # Render base config
    _render_base_config(
        base_service=base_service,
        source=source,
        destination=destination,
        templates=templates,
        network=network,
        services_root=services_root,
        output_dir=output_dir,
    )


def _find_base_vault_agent_service(
    services_root: Path,
    host_services: List[str],
) -> str | None:
    """Find the vault-agent service that defines base configuration.

    Args:
        services_root: Path to config/services directory.
        host_services: Services mapped to the current host.

    Returns:
        Service name with vault_agent.base, or None if not found.

    Raises:
        RenderError: If service.yaml is missing or invalid.
    """
    for service in host_services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        vault_agent_def = service_data.get("composition", {}).get("vault_agent", {})

        if "base" in vault_agent_def:
            return service

    return None


def _collect_vault_agent_templates(
    host_services: List[str],
    services_root: Path,
    output_dir: Path,
    templates_host_root: str,
    templates_mount_root: str,
    out_mount_root: str,
) -> List[Dict[str, str]]:
    """Collect vault-agent templates from services on this host.

    Copies template files to vault-agent output directory and returns
    template metadata for config rendering. Recursively follows composition.include.

    Args:
        host_services: Services mapped to the current host.
        services_root: Path to config/services directory.
        output_dir: Path to rendered services root.

    Returns:
        List of template dicts with source, dest, perms keys, in mapping order.

    Raises:
        RenderError: If a referenced template file doesn't exist.
    """
    templates: List[Dict[str, str]] = []
    visited: Set[str] = set()

    for service in host_services:
        templates.extend(
            _collect_service_vault_templates(
                service=service,
                services_root=services_root,
                output_dir=output_dir,
                templates_host_root=templates_host_root,
                templates_mount_root=templates_mount_root,
                out_mount_root=out_mount_root,
                visited=visited,
                stack=[],
            )
        )

    return templates


def _collect_service_vault_templates(
    service: str,
    services_root: Path,
    output_dir: Path,
    templates_host_root: str,
    templates_mount_root: str,
    out_mount_root: str,
    visited: Set[str],
    stack: List[str],
) -> List[Dict[str, str]]:
    """Recursively collect vault_agent templates from a service and its includes.

    Args:
        service: Service name.
        services_root: Path to config/services directory.
        output_dir: Path to rendered services root.
        visited: Set of already-visited services.
        stack: Current include stack for cycle detection.

    Returns:
        List of template dicts from this service and its includes.

    Raises:
        RenderError: If cycle detected or template not found.
    """
    if service in stack:
        cycle = " -> ".join(stack + [service])
        raise RenderError(f"Service include cycle detected: {cycle}")
    if service in visited:
        return []

    service_yaml = services_root / service / "service.yaml"
    if not service_yaml.exists():
        raise RenderError(f"Missing service definition: {service_yaml}")

    service_data = read_yaml(service_yaml) or {}
    composition = service_data.get("composition", {})

    stack.append(service)
    templates: List[Dict[str, str]] = []

    # First, recursively collect from includes
    includes = composition.get("include", []) or []
    for included in includes:
        templates.extend(
            _collect_service_vault_templates(
                service=included,
                services_root=services_root,
                output_dir=output_dir,
                templates_host_root=templates_host_root,
                templates_mount_root=templates_mount_root,
                out_mount_root=out_mount_root,
                visited=visited,
                stack=stack,
            )
        )

    # Then, collect from this service's vault_agent definition
    vault_agent_def = composition.get("vault_agent", {})
    template_defs = vault_agent_def.get("templates", []) or []

    for template_def in template_defs:
        source = template_def.get("source")
        out = template_def.get("out")
        perms = template_def.get("perms")

        if not source or not out:
            raise RenderError(
                f"Invalid vault_agent template entry in service '{service}': {template_def}"
            )

        # Resolve source path (may include service prefix)
        relative_source = source
        if source.startswith(f"{service}/"):
            relative_source = source[len(service) + 1 :]

        source_path = services_root / service / relative_source

        if not source_path.exists():
            raise RenderError(
                f"Vault-agent template not found: {source} in service '{service}'"
            )

        # Determine template relative path for vault-agent directories
        if relative_source.startswith("templates/"):
            template_rel = relative_source[len("templates/") :]
        else:
            template_rel = relative_source

        # Copy template file to vault-agent output
        dest_path = (
            output_dir / "vault-agent" / templates_host_root.lstrip("/") / template_rel
        )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(source_path.read_text())

        # Build template metadata for config
        templates.append(
            {
                "source": _join_mount_path(templates_mount_root, template_rel),
                "dest": _join_mount_path(out_mount_root, out),
                "perms": perms or "0640",
                "comment": f"{service}",
            }
        )

    stack.pop()
    visited.add(service)
    return templates


def _resolve_vault_agent_volume_paths(
    base_service: str,
    service_data: Dict[str, Any],
) -> Tuple[str, str, str]:
    """Resolve vault-agent templates/out paths from named volumes.

    Uses the base service's container.named_volumes entries for
    `templates` and `out` to determine host and mount roots.

    Returns:
        (templates_host_root, templates_mount_root, out_mount_root)
    """
    container_def = service_data.get("composition", {}).get("container", {})
    named_volumes = container_def.get("named_volumes", []) or []

    templates_host_root = None
    templates_mount_root = None
    out_mount_root = None

    for volume in named_volumes:
        if not isinstance(volume, dict):
            continue
        name = volume.get("name")
        host_path = volume.get("host_path")
        mount_path = volume.get("mount_path")

        if name == "templates":
            templates_host_root = host_path
            templates_mount_root = mount_path
        elif name == "out":
            out_mount_root = mount_path

    if not templates_host_root or not templates_mount_root or not out_mount_root:
        raise RenderError(
            f"Service '{base_service}' must define container.named_volumes for "
            "'templates' (host_path + mount_path) and 'out' (mount_path)"
        )

    return templates_host_root, templates_mount_root, out_mount_root


def _join_mount_path(root: str, path: str) -> str:
    """Join a root mount path with a relative path."""
    root_clean = root.rstrip("/")
    path_clean = path.lstrip("/")
    return f"{root_clean}/{path_clean}"


def _render_base_config(
    base_service: str,
    source: Dict[str, Any],
    destination: str,
    templates: List[Dict[str, str]],
    network: Dict[str, Any],
    services_root: Path,
    output_dir: Path,
) -> None:
    """Render the base vault-agent configuration file.

    Args:
        base_service: Name of the vault-agent service.
        source: Source configuration (template and variables).
        destination: Destination path for rendered config.
        templates: List of template metadata dicts.
        network: Network configuration.
        services_root: Path to config/services directory.
        output_dir: Path to rendered services root.

    Raises:
        RenderError: If template rendering fails.
    """
    template_path = source.get("template")
    variables = source.get("variables", {})

    if not template_path:
        raise RenderError(
            f"Service '{base_service}' vault_agent.base.source missing template"
        )

    # Resolve template path (may include service prefix)
    full_template_path = services_root / base_service / template_path
    if not full_template_path.exists():
        # Try without service prefix
        if template_path.startswith(f"{base_service}/"):
            relative_path = template_path[len(base_service) + 1 :]
            full_template_path = services_root / base_service / relative_path

    if not full_template_path.exists():
        raise RenderError(
            f"Vault-agent base template not found: {template_path} in service '{base_service}'"
        )

    # Set up Jinja2 environment
    jinja_env = Environment(
        loader=FileSystemLoader(full_template_path.parent),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_env.filters["strip_cidr"] = _strip_cidr

    # Build template context
    context = {
        "vault_agent_templates": templates,
        "service": {"config": {}},
    }

    # Process variables (may contain network placeholders)
    for key, value in variables.items():
        if isinstance(value, str) and value.startswith("%%") and value.endswith("%%"):
            # Resolve network placeholder
            placeholder = value[2:-2].strip()
            resolved = _resolve_network_placeholder(placeholder, network)
            context["service"]["config"][key] = resolved
        else:
            context["service"]["config"][key] = value

    # Render template
    template = jinja_env.get_template(full_template_path.name)
    rendered = template.render(**context)

    # Write output
    output_path = output_dir / base_service / destination.lstrip("/")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)


def _resolve_network_placeholder(placeholder: str, network: Dict[str, Any]) -> Any:
    """Resolve a network.yaml placeholder like 'network.services.vault.address'.

    Handles filter syntax like 'network.services.vault.address | strip_cidr'.

    Args:
        placeholder: Placeholder string (e.g., 'network.services.vault.address | strip_cidr').
        network: Network configuration dict.

    Returns:
        Resolved value from network config.

    Raises:
        RenderError: If placeholder cannot be resolved.
    """
    # Split on | to handle Jinja2 filter syntax
    path_part = placeholder.split("|")[0].strip()
    filter_part = placeholder.split("|")[1].strip() if "|" in placeholder else None

    parts = path_part.split(".")
    if parts[0] != "network":
        raise RenderError(
            f"Invalid placeholder: {placeholder} (must start with 'network')"
        )

    value = network
    for part in parts[1:]:
        if isinstance(value, dict):
            value = value.get(part)
            if value is None:
                raise RenderError(f"Placeholder not found: {path_part}")
        else:
            raise RenderError(f"Cannot resolve placeholder: {placeholder}")

    # Apply filter if specified
    if filter_part == "strip_cidr":
        value = _strip_cidr(value)

    return value


def _strip_cidr(address: str) -> str:
    """Strip CIDR suffix from IP address."""
    return address.split("/")[0] if "/" in address else address
