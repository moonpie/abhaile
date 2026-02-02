"""JSON Schema validation for config files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, RefResolver

# Import errors from utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.errors import RenderError
from utils.config import read_json


def validate_schema(
    data: Any, schema: Any, label: str, schema_path: Path | None = None
) -> None:
    """Validate data against JSON Schema (draft-07).

    Args:
        data: Data to validate.
        schema: JSON Schema (draft-07).
        label: Label for error messages (e.g., file path).
        schema_path: Path to schema file (for resolving $ref).

    Raises:
        RenderError: If validation fails.
    """
    # Create resolver for local $ref resolution
    resolver = None
    if schema_path:
        schema_dir = schema_path.parent
        store = {}

        # Pre-load all schemas in the same directory for $ref resolution
        for schema_file in schema_dir.glob("*.json"):
            schema_data = read_json(schema_file)
            store[schema_file.name] = schema_data

        resolver = RefResolver.from_schema(schema, store=store)

    validator = Draft7Validator(schema, resolver=resolver)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        formatted_lines = []
        for err in errors:
            path_str = "/".join(str(p) for p in err.path) or "<root>"
            formatted_lines.append(f"- {label}: {path_str}: {err.message}")
        formatted = "\n".join(formatted_lines)
        raise RenderError(f"Schema validation failed:\n{formatted}")
