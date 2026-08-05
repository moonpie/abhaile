"""Shared helper utilities for quadlet rendering."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
from typing import Any

from abhaile.models.kinds import KIND_FAMILIES
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.config import read_yaml_mapping
from abhaile.utils.errors import RenderError

# Derived from KIND_FAMILIES["quadlet"] — maps file suffix to artifact kind
_QUADLET_KIND_BY_SUFFIX: dict[str, str] = {
    f".{kind.split('.', 1)[1]}": kind for kind in KIND_FAMILIES["quadlet"]
}
_SUPPORTED_PULL_POLICIES = {"always", "missing", "never", "newer"}


def _quadlet_kind_from_filename(filename: str) -> str:
    """Return the quadlet artifact kind for a given output filename (e.g., ``blocky.container`` → ``quadlet.container``)."""
    suffix = Path(filename).suffix
    return _QUADLET_KIND_BY_SUFFIX.get(suffix, "quadlet.unknown")


def _quadlet_unit_name(filename: str) -> str:
    """Return the derived systemd unit name for a quadlet file.

    Containers map ``{stem}.container`` → ``{stem}.service``. Pods and other
    quadlet types append the extension type as a suffix to distinguish them
    from container units.
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    if suffix == ".container":
        return f"{stem}.service"
    if suffix == ".pod":
        return f"{stem}-pod.service"
    ext_word = suffix.lstrip(".")
    return f"{stem}-{ext_word}.service"


def _register_quadlet_artifact(
    *,
    collector: ArtifactCollector,
    rendered_root: Path,
    output_path: Path,
    target_path: str,
    kind: str,
    owner_ref: str,
    content: str,
    apply_hints: dict[str, Any] | None = None,
    owner_apply_hints: dict[str, Any] | None = None,
    owner_requires: list[str] | None = None,
    replace: bool = False,
) -> None:
    """Register a single quadlet artifact with the collector.

    Creates the owner if it has not yet been registered for this render.
    """
    render_path = output_path.relative_to(rendered_root).as_posix()
    if owner_ref not in collector.get_all_owners():
        collector.register_owner(
            name=owner_ref,
            description=f"Quadlet unit {owner_ref}",
            apply_hints=owner_apply_hints,
            requires=owner_requires or [],
        )
    collector.register_artifact(
        render_path=render_path,
        target_path=target_path,
        kind=kind,
        owner_ref=owner_ref,
        content=content,
        apply_hints=apply_hints,
        replace=replace,
    )


def _validate_trailing_newline(path: Path, *, context: str) -> None:
    """Validate text source file has a trailing newline.

    Raises:
        RenderError: If file is non-empty and does not end with a newline.
    """
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        raise RenderError(f"{context} must end with a trailing newline: {path}")


def _discover_build_image_files(
    quadlets_dir: Path,
    service: str,
    container_name: str | None = None,
    services_root: Path | None = None,
) -> tuple[Path | None, Path | None, str | None, str | None]:
    """Discover build/image files and compute target filenames."""
    name_base = f"{service}-app-{container_name}" if container_name else service

    if services_root is not None and container_name is None:
        build_path = _resolve_quadlet_source_file(service, services_root, "build.build")
        image_path = _resolve_quadlet_source_file(service, services_root, "image.image")
    else:
        build_path = quadlets_dir / "build.build"
        image_path = quadlets_dir / "image.image"

    build_path = build_path if build_path and build_path.exists() else None
    image_path = image_path if image_path and image_path.exists() else None

    build_filename = f"{name_base}.build" if build_path else None
    image_filename = f"{name_base}.image" if image_path else None

    return build_path, image_path, build_filename, image_filename


def _validate_registry_image(image: object, *, service: str) -> str:
    """Validate and return a registry image reference."""
    if not isinstance(image, str) or not image.strip():
        raise RenderError(f"Podman image must be a non-empty string for service '{service}'")
    return image.strip()


def _validate_pull_policy(policy: object, *, service: str) -> str:
    """Validate and return a Quadlet pull policy."""
    if policy is None:
        return "missing"
    if not isinstance(policy, str) or policy not in _SUPPORTED_PULL_POLICIES:
        supported = ", ".join(sorted(_SUPPORTED_PULL_POLICIES))
        raise RenderError(
            f"Unsupported Podman pull_policy for service '{service}': {policy!r} "
            f"(supported: {supported})"
        )
    return policy


def _service_podman_config(service: str, services_root: Path) -> dict[str, Any]:
    """Read one service's podman config, returning an empty mapping when absent."""
    service_path = services_root / service / "service.yaml"
    data = read_yaml_mapping(service_path)
    podman = data.get("podman", {}) or {}
    return podman if isinstance(podman, dict) else {}


def _resolve_service_image_config(
    service: str,
    services_root: Path,
) -> tuple[str | None, str]:
    """Resolve inherited service-level registry image and pull policy."""
    from abhaile.utils.composition import walk_service_includes

    image: str | None = None
    pull_policy: str | None = None
    for service_name in walk_service_includes(service, services_root.parent):
        podman = _service_podman_config(service_name, services_root)
        if "image" in podman:
            image = _validate_registry_image(podman.get("image"), service=service_name)
        if "pull_policy" in podman:
            pull_policy = _validate_pull_policy(podman.get("pull_policy"), service=service_name)
    return image, _validate_pull_policy(pull_policy, service=service)


def _resolve_container_image_config(
    *,
    service: str,
    container_name: str | None,
    container_def: dict[str, Any],
    podman: dict[str, Any],
    services_root: Path,
) -> tuple[str | None, str]:
    """Resolve effective image reference and pull policy for a container."""
    service_image, service_pull_policy = _resolve_service_image_config(service, services_root)
    image = service_image
    pull_policy = service_pull_policy

    if "image" in podman:
        image = _validate_registry_image(podman.get("image"), service=service)
    if "pull_policy" in podman:
        pull_policy = _validate_pull_policy(podman.get("pull_policy"), service=service)
    if "image" in container_def:
        image = _validate_registry_image(
            container_def.get("image"),
            service=f"{service}/{container_name}" if container_name else service,
        )
    if "pull_policy" in container_def:
        pull_policy = _validate_pull_policy(
            container_def.get("pull_policy"),
            service=f"{service}/{container_name}" if container_name else service,
        )

    return image, pull_policy


def _resolve_managed_build_hints(service: str, services_root: Path) -> dict[str, Any] | None:
    """Resolve managed build metadata for a service's .build Quadlet."""
    service_path = services_root / service / "service.yaml"
    data = read_yaml_mapping(service_path)
    build = data.get("build")
    if not isinstance(build, dict):
        return None
    output_image = build.get("output_image")
    if not isinstance(output_image, str) or not output_image:
        raise RenderError(f"build.output_image must be a non-empty string for {service}")
    pull_policy = build.get("pull_policy", "missing")
    if pull_policy != "missing":
        raise RenderError(f"Only build.pull_policy=missing is supported for {service}")
    inputs = build.get("inputs", [])
    if not isinstance(inputs, list) or not all(isinstance(item, str) and item for item in inputs):
        raise RenderError(f"build.inputs must be a list of source paths for {service}")
    consumers = build.get("consumers", [])
    if not isinstance(consumers, list) or not all(
        isinstance(item, str) and item for item in consumers
    ):
        raise RenderError(f"build.consumers must be a list of unit names for {service}")

    payload: dict[str, Any] = {
        "service": service,
        "output_image": output_image,
        "pull_policy": pull_policy,
        "input_fingerprint": _managed_build_fingerprint(
            services_root,
            input_paths=inputs,
            build=build,
        ),
        "inputs": inputs,
        "consumers": consumers,
    }
    post_build = build.get("post_build")
    if isinstance(post_build, dict):
        payload["post_build"] = post_build
    return {"managed_build": payload}


def _managed_build_fingerprint(
    services_root: Path,
    *,
    input_paths: list[str],
    build: dict[str, Any],
) -> str:
    """Return a deterministic fingerprint for declared managed build inputs."""
    payload: dict[str, Any] = {
        "build": {key: value for key, value in sorted(build.items())},
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


def _read_legacy_image_reference(image_path: Path, *, service: str) -> str:
    """Read an image reference from a legacy image.image source file."""
    _validate_trailing_newline(image_path, context="quadlet image source file")
    for line in image_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Image="):
            return _validate_registry_image(line.split("=", 1)[1], service=service)
    raise RenderError(f"Legacy image.image file missing Image= line: {image_path}")


def _resolve_quadlet_source_file(service: str, services_root: Path, filename: str) -> Path | None:
    """Resolve a service quadlet source file, allowing direct files to override includes."""
    from abhaile.utils.composition import walk_service_includes

    ordered_services = walk_service_includes(service, services_root.parent)
    for service_name in ordered_services:
        candidate = services_root / service_name / "quadlets" / filename
        if candidate.exists():
            return candidate
    return None


def _resolve_composition_definition(
    key: str,
    service: str,
    composition: dict[str, Any],
    services_root: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a composition definition by key, walking includes if needed."""
    from abhaile.utils.composition import resolve_composition

    definition = composition.get(key)
    if definition:
        return definition, service

    config_root = services_root.parent
    includes = composition.get("include", []) or []
    for included in includes:
        included_composition = resolve_composition(
            service_name=included,
            config_root=config_root,
            merge_strategy="deep",
        )
        definition = included_composition.get(key)
        if definition:
            return definition, included

    return None, None
