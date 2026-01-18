"""Service metadata loader with include support (pure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.common.core import RenderError, load_yaml


def load_service_meta_with_includes(
    svc: str,
    services_dir: Path,
    cache: dict[str, dict[str, Any]],
    include_stack: list[str] | None = None,
) -> dict[str, Any]:
    """Load service metadata and merge included services.

    Resolves the ``include`` list recursively, merging config, ingress,
    and vault_agent.templates entries so included content renders under the
    parent service's output path.

    Args:
        svc: Service name to load
        services_dir: Base directory containing service definitions
        cache: Cache of already-loaded service metadata
        include_stack: Stack of services being included (for cycle detection)

    Raises:
        RenderError: If circular include detected or service file missing
    """
    # Initialize include stack on first call
    if include_stack is None:
        include_stack = []

    # Detect circular includes
    if svc in include_stack:
        cycle_path = " -> ".join(include_stack + [svc])
        raise RenderError(f"circular include detected: {cycle_path}")

    if svc in cache:
        return cache[svc]

    svc_file = services_dir / svc / "service.yaml"
    if not svc_file.exists():
        raise RenderError(f"missing service metadata for {svc}: {svc_file}")

    meta = load_yaml(svc_file) or {}

    merged_config: list[dict[str, Any]] = []
    merged_ingress: dict[str, list[Any]] = {}
    merged_va_templates: list[dict[str, Any]] = []

    # Add current service to include stack before processing includes
    new_stack = include_stack + [svc]

    for inc in meta.get("include", []) or []:
        inc_meta = load_service_meta_with_includes(inc, services_dir, cache, new_stack)
        merged_config.extend(inc_meta.get("config", []))

        for ingress_type, blocks in inc_meta.get("ingress", {}).items():
            merged_ingress.setdefault(ingress_type, []).extend(blocks)

        merged_va_templates.extend(inc_meta.get("vault_agent", {}).get("templates", []))

    merged_config.extend(meta.get("config", []))

    merged_meta = {**meta}
    merged_meta["config"] = merged_config

    if merged_ingress or meta.get("ingress"):
        ingress = {**merged_ingress}
        for ingress_type, blocks in (meta.get("ingress", {}) or {}).items():
            ingress.setdefault(ingress_type, []).extend(blocks)
        merged_meta["ingress"] = ingress

    va_meta = meta.get("vault_agent", {}) or {}
    if merged_va_templates or va_meta.get("templates"):
        merged_meta["vault_agent"] = {**va_meta}
        merged_meta["vault_agent"]["templates"] = merged_va_templates + va_meta.get(
            "templates", []
        )

    cache[svc] = merged_meta
    return merged_meta
