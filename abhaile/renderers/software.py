"""Software renderer for host software artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml

from abhaile.utils.config import read_json, read_yaml_mapping
from abhaile.utils.errors import RenderError
from abhaile.validation.schema import validate_schema

SOFTWARE_KEYS = ("packages", "downloads", "builds", "commands")
ENTRY_KEYS = ("downloads", "builds", "commands")


def render_software_artifacts(
    host: str,
    config_root: Path,
    output_dir: Path,
) -> None:
    """Render software package/install artifacts for a host.

    Output contract:
    - software/packages.txt: merged package ids in deterministic order
    - software/downloads/<id>.yaml: resolved download specs
    - software/builds/<id>.yaml: resolved build specs
    - software/commands/<id>.yaml: resolved command specs

    Duplicate ids across include chain are treated as configuration errors.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    ordered_hosts = _walk_host_includes(host, config_root)
    refs, sources = _collect_software_refs(ordered_hosts, config_root)

    _write_packages_file(refs["packages"], output_dir / "packages.txt")

    schema_path = config_root.parent / "schemas" / "software-action.schema.json"
    schema = read_json(schema_path)

    for key in ENTRY_KEYS:
        category_output_dir = output_dir / key
        category_output_dir.mkdir(parents=True, exist_ok=True)

        for ref in refs[key]:
            source_host = sources[(key, ref)]
            source_path = config_root / "hosts" / source_host / "software" / key / f"{ref}.yaml"
            if not source_path.exists():
                raise RenderError(f"Missing software {key} spec: {source_path}")

            spec = read_yaml_mapping(source_path)
            validate_schema(spec, schema, str(source_path), schema_path)

            spec_id = spec.get("id")
            if spec_id != ref:
                raise RenderError(
                    f"Software {key} spec id mismatch in {source_path}: "
                    f"expected id '{ref}', got '{spec_id}'"
                )

            rendered_path = category_output_dir / f"{ref}.yaml"
            rendered_path.write_text(
                yaml.safe_dump(spec, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )


def _walk_host_includes(
    host: str,
    config_root: Path,
    *,
    visited: Set[str] | None = None,
    stack: List[str] | None = None,
) -> List[str]:
    """Return depth-first include order for host composition."""
    if visited is None:
        visited = set()
    if stack is None:
        stack = []

    if host in stack:
        cycle = " -> ".join(stack + [host])
        raise RenderError(f"Host include cycle detected: {cycle}")
    if host in visited:
        return []

    host_path = config_root / "hosts" / host / "host.yaml"
    if not host_path.exists():
        raise RenderError(f"Missing host definition: {host_path}")

    host_data = read_yaml_mapping(host_path)
    composition = host_data.get("composition", {}) or {}
    includes = composition.get("include", []) or []
    if not isinstance(includes, list) or any(not isinstance(item, str) for item in includes):
        raise RenderError(f"Host includes must be a list of strings: {host_path}")

    ordered: List[str] = []
    stack.append(host)
    for include_host in includes:
        ordered.extend(
            _walk_host_includes(
                include_host,
                config_root,
                visited=visited,
                stack=stack,
            )
        )
    stack.pop()

    visited.add(host)
    ordered.append(host)
    return ordered


def _collect_software_refs(
    ordered_hosts: List[str],
    config_root: Path,
) -> Tuple[Dict[str, List[str]], Dict[Tuple[str, str], str]]:
    """Collect merged software references with duplicate detection."""
    refs: Dict[str, List[str]] = {key: [] for key in SOFTWARE_KEYS}
    seen: Dict[str, Set[str]] = {key: set() for key in SOFTWARE_KEYS}
    sources: Dict[Tuple[str, str], str] = {}

    for host_name in ordered_hosts:
        host_path = config_root / "hosts" / host_name / "host.yaml"
        host_data = read_yaml_mapping(host_path)
        composition = host_data.get("composition", {}) or {}
        software = composition.get("software", {}) or {}

        for key in SOFTWARE_KEYS:
            items = software.get(key, []) or []
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise RenderError(
                    f"composition.software.{key} must be a list of strings: {host_path}"
                )

            for item in items:
                if item in seen[key]:
                    raise RenderError(
                        f"Duplicate software {key} entry '{item}' while resolving host '{ordered_hosts[-1]}'"
                    )
                seen[key].add(item)
                refs[key].append(item)
                if key in ENTRY_KEYS:
                    sources[(key, item)] = host_name

    return refs, sources


def _write_packages_file(packages: List[str], destination: Path) -> None:
    """Write merged package list as a deterministic newline-delimited file."""
    lines = [f"{pkg}\n" for pkg in packages]
    destination.write_text("".join(lines), encoding="utf-8")
