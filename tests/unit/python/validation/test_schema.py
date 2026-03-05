"""Tests for JSON schema validation error formatting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.utils.errors import RenderError
from abhaile.validation.schema import validate_schema


class TestSchemaValidationFormatting:
    """Tests for improved schema validation error messages."""

    def test_error_includes_schema_file_and_pointers(self, tmp_path: Path) -> None:
        """Validation error includes data pointer and schema file pointer."""
        schema_path = tmp_path / "mapping.schema.json"
        schema = {
            "type": "object",
            "properties": {
                "abhaile": {
                    "type": "array",
                }
            },
            "required": ["abhaile"],
        }
        data: dict[str, Any] = {"abhaile": "not-a-list"}

        with pytest.raises(RenderError) as exc_info:
            validate_schema(data, schema, "config/mapping.yaml", schema_path)

        error_text = str(exc_info.value)
        assert "Schema validation failed:" in error_text
        assert "config/mapping.yaml at /abhaile" in error_text
        assert f"schema: {schema_path}#/properties/abhaile" in error_text

    def test_error_uses_schema_id_when_no_path(self) -> None:
        """Validation error falls back to schema $id when no schema_path is set."""
        schema: dict[str, Any] = {
            "$id": "abhaile://schemas/test",
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
            },
        }

        with pytest.raises(RenderError) as exc_info:
            validate_schema({}, schema, "inline-config")

        error_text = str(exc_info.value)
        assert "inline-config at /" in error_text
        assert "schema: abhaile://schemas/test#/required" in error_text
