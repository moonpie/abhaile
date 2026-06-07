"""JSON Schema validation for config files."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from referencing import Registry, Resource

from abhaile.utils.errors import RenderError
from abhaile.utils.config import read_json

_REGISTRY_CACHE: dict[str, Registry] = {}


def _to_json_pointer(path_parts: Iterable[Any]) -> str:
    """Convert an error path iterable into a JSON Pointer string."""
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path_parts]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _schema_source_label(schema: Any, schema_path: Path | None) -> str:
    """Return a readable schema source label for error messages."""
    if schema_path:
        return str(schema_path)
    if isinstance(schema, dict):
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id.strip():
            return schema_id
    return "<inline schema>"


def _get_registry(schema_dir: Path) -> Registry:
    """Get or build a schema registry for the given directory."""
    key = str(schema_dir.resolve())
    if key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[key]
    resources = []
    for schema_file in schema_dir.glob("*.json"):
        schema_data = read_json(schema_file)
        resources.append((schema_file.name, Resource.from_contents(schema_data)))
    registry = Registry().with_resources(resources)
    _REGISTRY_CACHE[key] = registry
    return registry


def validate_schema(data: Any, schema: Any, label: str, schema_path: Path | None = None) -> None:
    """Validate data against JSON Schema (draft-07)."""
    registry = _get_registry(schema_path.parent) if schema_path else None

    if registry is not None:
        validator = Draft7Validator(schema, registry=registry)
    else:
        validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        source_label = _schema_source_label(schema, schema_path)
        formatted_lines = []
        for err in errors:
            data_pointer = _to_json_pointer(err.absolute_path)
            schema_pointer = _to_json_pointer(err.absolute_schema_path)
            formatted_lines.append(
                f"- {label} at {data_pointer}: {err.message} "
                f"(schema: {source_label}#{schema_pointer})"
            )
        formatted = "\n".join(formatted_lines)
        raise RenderError(f"Schema validation failed:\n{formatted}")
