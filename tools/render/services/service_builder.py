"""Service configuration file rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.core import (
    RenderError,
    get_jinja_env,
    resolve_placeholders,
    strip_cidr,
)

__all__ = [
    "substitute_variables",
    "build_service_configs",
]


def substitute_variables(
    variables: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """Substitute %%path.to.value%% placeholders in variables with actual context values.

    Supports filters like | strip_cidr and mixed placeholder+literal values.

    Args:
        variables: Dictionary of variables with potential placeholders
        ctx: Context dictionary to lookup values from

    Returns:
        Dictionary with placeholders replaced by actual values
    """
    result = {}
    for key, value in variables.items():
        if isinstance(value, str) and "%%" in value:
            try:
                result[key] = resolve_placeholders(value, ctx)
            except RenderError as exc:
                raise RenderError(
                    f"Failed to resolve placeholder in variable '{key}={value}': {exc}"
                ) from exc
        else:
            result[key] = value

    return result


def _resolve_source_path(
    source: str, svc_template_dir: Path, services_dir: Path
) -> Path | None:
    """Resolve a config source path.

    Supports absolute paths, service-local relative paths, or paths relative to the
    services root (useful when service.yaml already prefixes the service name).

    Args:
        source: Source path (absolute or relative).
        svc_template_dir: Service-specific template directory.
        services_dir: Root services directory.

    Returns:
        Path | None: Resolved path if found, else None.
    """
    candidate = Path(source)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    for base in (svc_template_dir, services_dir):
        candidate = base / source
        if candidate.exists():
            return candidate

    return None


def build_service_configs(
    hostname: str,
    host_services: list[str],
    services_meta: dict[str, Any],
    ctx: dict[str, Any],
    services_dir: Path,
) -> tuple[list[tuple[Path, str]], list[tuple[Path, bytes]]]:
    """Build service-specific configuration outputs (pure, no writes).

    Args:
        hostname: Name of host being rendered.
        host_services: List of service names to render for this host.
        services_meta: Service metadata dictionary.
        ctx: Rendering context (network, hosts, services).
        services_dir: Root directory for service templates.

    Returns:
        tuple: (rendered_text, copied_bytes) where:
            - rendered_text: list of (relative_path, content) for templated files
            - copied_bytes: list of (relative_path, bytes_content) for static files
    """
    rendered_outputs: list[tuple[Path, str]] = []
    copied_outputs: list[tuple[Path, bytes]] = []

    for svc in host_services:
        svc_meta = services_meta.get(svc, {})
        config_files = svc_meta.get("config", [])

        if not config_files:
            continue

        svc_template_dir = services_dir / svc
        if not svc_template_dir.exists():
            continue

        search_paths = [
            str(services_dir),
            str(svc_template_dir),
        ]

        env = get_jinja_env(search_paths, filters={"strip_cidr": strip_cidr})

        for config_entry in config_files:
            source = config_entry.get("source")
            if not source:
                continue

            if isinstance(source, dict):
                template_path = source.get("template")
                variables = source.get("variables", {})

                if not template_path:
                    continue

                resolved_vars = substitute_variables(variables, ctx)
                dest = config_entry.get("destination")
                if not dest:
                    continue

                if "DYNAMIC_ZONE_PLACEHOLDER" in dest:
                    tpl_is_coredns_common_zone = str(template_path).endswith(
                        "coredns-common/config/zones/zone.zone.j2"
                    )
                    if tpl_is_coredns_common_zone:
                        zones = (
                            ctx.get("dns", {}).get("zones_common", []) if ctx else []
                        )
                    else:
                        zones = ctx.get("dns", {}).get("zones", []) if ctx else []
                    seen_zones: set[str] = set()
                    for zone in zones:
                        zone_name = zone.get("name")
                        if not zone_name:
                            continue

                        normalized_zone = zone_name.rstrip(".")
                        if normalized_zone in seen_zones:
                            continue
                        seen_zones.add(normalized_zone)

                        zone_ctx = {
                            **ctx,
                            "config": resolved_vars,
                            "zone": zone,
                        }

                        tpl = env.get_template(template_path)
                        rendered = tpl.render(**zone_ctx)
                        rel_path = (
                            Path("services")
                            / svc
                            / dest.replace(
                                "DYNAMIC_ZONE_PLACEHOLDER", f"{normalized_zone}.zone"
                            ).lstrip("/")
                        )
                        rendered_outputs.append((rel_path, rendered))
                else:
                    config_ctx = {**ctx, "config": resolved_vars}
                    tpl = env.get_template(template_path)
                    rendered = tpl.render(**config_ctx)

                    rel_path = Path("services") / svc / dest.lstrip("/")
                    rendered_outputs.append((rel_path, rendered))
            else:
                src_path = _resolve_source_path(
                    str(source), svc_template_dir, services_dir
                )
                if not src_path:
                    raise RenderError(
                        f"Service '{svc}' config source file not found: '{source}'. "
                        f"Searched in {svc_template_dir} and {services_dir}"
                    )
                dest = config_entry.get("destination")
                if not dest:
                    raise RenderError(
                        f"Service '{svc}' config entry missing 'destination' for source '{source}'"
                    )
                rel_path = Path("services") / svc / dest.lstrip("/")
                copied_outputs.append((rel_path, src_path.read_bytes()))

    return rendered_outputs, copied_outputs


def render_service_configs(
    hostname: str,
    host_services: list[str],
    services_meta: dict[str, Any],
    ctx: dict[str, Any],
    out_dir: Path,
    services_dir: Path,
) -> None:
    """Compatibility wrapper that writes outputs from build_service_configs."""

    rendered_outputs, copied_outputs = build_service_configs(
        hostname=hostname,
        host_services=host_services,
        services_meta=services_meta,
        ctx=ctx,
        services_dir=services_dir,
    )
    for rel_path, content in rendered_outputs:
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        dest.write_text(content)
    for rel_path, data in copied_outputs:
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
