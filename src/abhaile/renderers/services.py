"""Service configuration renderer for service compositions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.config import render_config_entries
from abhaile.renderers.metadata import classify_service_artifact, classify_systemd_artifact
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.composition import walk_service_includes
from abhaile.utils.config import read_yaml
from abhaile.utils.errors import RenderError
from abhaile.utils.placeholders import resolve_placeholders


def render_service_configs(
    host: str,
    services: list[str],
    network: dict[str, Any],
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
    """Render per-service configuration files for a host."""
    if not services:
        return

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    for service in services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        apply_hints = _service_config_apply_hints(service, service_data)
        directory_apply_hints = _service_directory_apply_hints(service_data)

        config_entries = _collect_service_composition_entries(service, config_root, "config")
        systemd_entries = _collect_service_composition_entries(service, config_root, "systemd")

        if not config_entries and not systemd_entries:
            continue

        service_output_dir = output_dir / service
        context = {
            "network": network,
            "host_name": host,
            "service_name": service,
        }

        if config_entries:
            resolved_entries = _resolve_config_entry_variables(config_entries, network)
            annotated_entries = _annotate_config_entries_with_apply_hints(
                resolved_entries,
                apply_hints,
                directory_apply_hints,
            )

            render_config_entries(
                annotated_entries,
                services_root,
                services_root,
                service_output_dir,
                context,
                collector=collector,
                rendered_root=rendered_root,
                default_owner_ref=f"service:{service}",
                classify_artifact=lambda destination, owner_ref, is_directory: classify_service_artifact(
                    destination,
                    default_owner_ref=owner_ref,
                    is_directory=is_directory,
                ),
            )

        if systemd_entries:
            resolved_systemd_entries = _resolve_config_entry_variables(systemd_entries, network)
            annotated_systemd_entries = _annotate_systemd_entries_with_apply_hints(
                resolved_systemd_entries,
            )

            render_config_entries(
                annotated_systemd_entries,
                services_root,
                services_root,
                service_output_dir,
                context,
                collector=collector,
                rendered_root=rendered_root,
                default_owner_ref=f"service:{service}",
                classify_artifact=lambda destination, _owner_ref, _is_directory: classify_systemd_artifact(
                    destination,
                ),
            )


def _collect_service_composition_entries(
    service: str,
    config_root: Path,
    section: str,
) -> list[dict[str, Any]]:
    """Collect composition entries for a service and its includes.

    Includes are resolved depth-first; included entries are rendered before the
    service's own entries to allow later overrides.
    """
    entries: list[dict[str, Any]] = []
    ordered_services = walk_service_includes(service, config_root)

    for service_name in ordered_services:
        service_yaml = config_root / "services" / service_name / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        composition = service_data.get("composition", {})
        for entry in composition.get(section, []) or []:
            if not isinstance(entry, dict):
                entries.append(entry)
                continue
            copied = dict(entry)
            copied["_abhaile_contributor_ref"] = service_name
            entries.append(copied)

    return entries


def _resolve_config_entry_variables(
    entries: list[dict[str, Any]],
    network: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve %%...%% placeholders in template variables using network data."""
    resolved: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            resolved.append(entry)
            continue

        source = entry.get("source")
        if not isinstance(source, dict):
            resolved.append(entry)
            continue

        variables = source.get("variables", {})
        if not isinstance(variables, dict):
            resolved.append(entry)
            continue

        resolved_vars = resolve_placeholders(variables, network)

        updated = dict(entry)
        updated_source = dict(source)
        updated_source["variables"] = resolved_vars
        updated["source"] = updated_source
        resolved.append(updated)

    return resolved


def _service_config_apply_hints(service: str, service_data: dict[str, Any]) -> dict[str, Any]:
    """Build apply hints for service-owned config artifacts."""
    hints: dict[str, Any] = {}

    apply_block = service_data.get("apply")
    if isinstance(apply_block, dict):
        restart_unit = apply_block.get("restart_unit")
        if isinstance(restart_unit, str) and restart_unit:
            hints["restart_unit"] = restart_unit

    if "restart_unit" not in hints:
        composition = service_data.get("composition")
        if isinstance(composition, dict):
            if "pod" in composition:
                hints["restart_unit"] = f"{service}-app.service"
            elif "container" in composition:
                hints["restart_unit"] = f"{service}.service"

    podman = service_data.get("podman")
    if isinstance(podman, dict):
        podman_user = podman.get("user")
        if isinstance(podman_user, str) and podman_user:
            rootless_value = podman.get("rootless")
            if isinstance(rootless_value, bool):
                rootless = rootless_value
            else:
                rootless = podman_user != "root"
            hints["rootless"] = rootless
            if rootless:
                hints["podman_user"] = podman_user

    return hints


def _annotate_config_entries_with_apply_hints(
    entries: list[dict[str, Any]],
    apply_hints: dict[str, Any],
    directory_apply_hints: dict[str, Any],
) -> list[Any]:
    """Attach internal apply hints to service config/directory entries."""
    if not apply_hints and not directory_apply_hints:
        return entries

    annotated: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict):
            annotated.append(entry)
            continue

        merged = dict(entry)
        entry_hints: dict[str, Any] = dict(apply_hints)
        if "source" not in merged:
            entry_hints.update(directory_apply_hints)
            for key in ("owner", "group", "mode"):
                value = merged.get(key)
                if isinstance(value, str) and value:
                    entry_hints[key] = value

        if entry_hints:
            merged["_abhaile_apply_hints"] = entry_hints
        annotated.append(merged)

    return annotated


def _annotate_systemd_entries_with_apply_hints(entries: list[dict[str, Any]]) -> list[Any]:
    """Attach internal apply hints to composition.systemd entries."""
    annotated: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict):
            annotated.append(entry)
            continue

        merged = dict(entry)
        hints: dict[str, Any] = {}
        if merged.get("enable") is True:
            hints["enable_mode"] = "enable"
        if merged.get("start") is True:
            hints["activation_mode"] = "start"
        if hints:
            merged["_abhaile_apply_hints"] = hints
        annotated.append(merged)

    return annotated


def _service_directory_apply_hints(service_data: dict[str, Any]) -> dict[str, Any]:
    """Build apply hints for service.directory ownership/mode enforcement."""
    podman = service_data.get("podman")
    owner = "root"
    if isinstance(podman, dict):
        podman_user = podman.get("user")
        if isinstance(podman_user, str) and podman_user:
            owner = podman_user

    group = owner if owner != "root" else "root"

    return {
        "owner": owner,
        "group": group,
        "mode": "0750",
    }
