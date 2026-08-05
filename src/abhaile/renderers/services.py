"""Service configuration renderer for service compositions."""

from __future__ import annotations

import logging
import hashlib
import json
from pathlib import Path
from typing import Any

from abhaile.renderers.config import (
    annotate_systemd_entries_with_apply_hints,
    render_config_entries,
    resolve_config_entry_variables,
)
from abhaile.models.directory import directory_metadata_to_hints, resolve_directory_metadata
from abhaile.renderers.metadata import classify_service_artifact, classify_systemd_artifact
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.composition import walk_service_includes
from abhaile.utils.config import read_yaml
from abhaile.utils.errors import RenderError

LOG = logging.getLogger(__name__)


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

    LOG.debug("render.services host=%s count=%d", host, len(services))

    services_root = config_root / "services"
    output_dir.mkdir(parents=True, exist_ok=True)

    for service in services:
        service_yaml = services_root / service / "service.yaml"
        if not service_yaml.exists():
            raise RenderError(f"Missing service definition: {service_yaml}")

        service_data = read_yaml(service_yaml) or {}
        apply_hints = _service_config_apply_hints(service, service_data)
        directory_apply_hints = _service_directory_apply_hints(service_data)
        build_hints = _managed_build_hints_by_service(service, config_root)

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
            resolved_entries = resolve_config_entry_variables(config_entries, network)
            annotated_entries = _annotate_config_entries_with_apply_hints(
                resolved_entries,
                apply_hints,
                directory_apply_hints,
                build_hints,
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
            resolved_systemd_entries = resolve_config_entry_variables(systemd_entries, network)
            annotated_systemd_entries = annotate_systemd_entries_with_apply_hints(
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


def _service_config_apply_hints(_service: str, service_data: dict[str, Any]) -> dict[str, Any]:
    """Build apply hints for service-owned config artifacts."""
    _ = _service
    hints: dict[str, Any] = {}

    apply_block = service_data.get("apply")
    if isinstance(apply_block, dict):
        restart_unit = apply_block.get("config_change_restart_unit")
        if isinstance(restart_unit, str) and restart_unit:
            hints["restart_unit"] = restart_unit
        elif "config_change_restart_unit" in apply_block and restart_unit is None:
            hints["restart_unit"] = None

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
    build_hints_by_service: dict[str, dict[str, Any]],
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
        contributor = merged.get("_abhaile_contributor_ref")
        destination = merged.get("destination")
        if "source" not in merged:
            entry_hints.update(directory_apply_hints)
            for key in ("owner", "group", "mode"):
                value = merged.get(key)
                if isinstance(value, str) and value:
                    entry_hints[key] = value
        elif (
            isinstance(contributor, str)
            and isinstance(destination, str)
            and Path(destination).suffix == ".build"
            and contributor in build_hints_by_service
        ):
            entry_hints.update(build_hints_by_service[contributor])

        if entry_hints:
            merged["_abhaile_apply_hints"] = entry_hints
        annotated.append(merged)

    return annotated


def _managed_build_hints_by_service(service: str, config_root: Path) -> dict[str, dict[str, Any]]:
    """Build managed-build apply hints for a service and its includes."""
    hints: dict[str, dict[str, Any]] = {}
    for service_name in walk_service_includes(service, config_root):
        service_yaml = config_root / "services" / service_name / "service.yaml"
        service_data = read_yaml(service_yaml) or {}
        build = service_data.get("build")
        if not isinstance(build, dict):
            continue
        output_image = build.get("output_image")
        if not isinstance(output_image, str) or not output_image:
            raise RenderError(f"build.output_image must be a non-empty string for {service_name}")
        pull_policy = build.get("pull_policy", "missing")
        if pull_policy != "missing":
            raise RenderError(f"Only build.pull_policy=missing is supported for {service_name}")
        inputs = build.get("inputs", [])
        if not isinstance(inputs, list) or not all(
            isinstance(item, str) and item for item in inputs
        ):
            raise RenderError(f"build.inputs must be a list of source paths for {service_name}")
        post_build = build.get("post_build")
        consumers = build.get("consumers", [])
        if not isinstance(consumers, list) or not all(
            isinstance(item, str) and item for item in consumers
        ):
            raise RenderError(f"build.consumers must be a list of unit names for {service_name}")
        rootless, podman_user = _service_podman_context(service_data)
        hint: dict[str, Any] = {
            "rootless": rootless,
            "managed_build": {
                "service": service_name,
                "output_image": output_image,
                "pull_policy": pull_policy,
                "input_fingerprint": _managed_build_fingerprint(
                    config_root / "services",
                    input_paths=inputs,
                    build=build,
                ),
                "inputs": inputs,
                "consumers": consumers,
            },
        }
        if rootless and podman_user is not None:
            hint["podman_user"] = podman_user
        if isinstance(post_build, dict):
            hint["managed_build"]["post_build"] = post_build
        hints[service_name] = hint
    return hints


def _service_podman_context(service_data: dict[str, Any]) -> tuple[bool, str | None]:
    """Resolve service rootless context from podman config."""
    podman = service_data.get("podman")
    if not isinstance(podman, dict):
        return False, None
    user = podman.get("user")
    if not isinstance(user, str) or not user:
        return False, None
    rootless_value = podman.get("rootless")
    rootless = rootless_value if isinstance(rootless_value, bool) else user != "root"
    return rootless, user if rootless else None


def _managed_build_fingerprint(
    services_root: Path,
    *,
    input_paths: list[str],
    build: dict[str, Any],
) -> str:
    """Return a deterministic fingerprint for declared managed build inputs."""
    payload: dict[str, Any] = {
        "build": {
            key: value for key, value in sorted(build.items()) if key not in {"input_fingerprint"}
        },
        "inputs": [],
    }
    for input_path in sorted(input_paths):
        path = services_root / input_path
        if not path.exists() or not path.is_file():
            raise RenderError(f"Managed build input not found: {path}")
        payload["inputs"].append(
            {
                "path": input_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _service_directory_apply_hints(service_data: dict[str, Any]) -> dict[str, Any]:
    """Build apply hints for service.directory ownership/mode enforcement."""
    podman = service_data.get("podman")
    owner = "root"
    if isinstance(podman, dict):
        podman_user = podman.get("user")
        if isinstance(podman_user, str) and podman_user:
            owner = podman_user

    return directory_metadata_to_hints(
        resolve_directory_metadata("service.directory", {"owner": owner})
    )
