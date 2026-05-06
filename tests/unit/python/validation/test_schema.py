"""Tests for JSON schema validation error formatting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.utils.config import read_json
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


class TestServiceCompositionSchema:
    """Tests for service composition schema boundaries."""

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[4]

    def test_common_schema_config_entry_has_no_apply_block(self) -> None:
        """common configEntry no longer exposes authored entry-level apply blocks."""
        repo_root = self._repo_root()
        common_schema_path = repo_root / "schemas" / "common.schema.json"
        common_schema = read_json(common_schema_path)

        assert "configEntryApply" not in common_schema["definitions"]
        config_entry = common_schema["definitions"]["configEntry"]
        # configEntry is modeled as oneOf refs and does not include apply
        for variant in config_entry["oneOf"]:
            if isinstance(variant, dict) and "$ref" in variant:
                assert not variant["$ref"].endswith("configEntryApply")

    def test_common_schema_defines_reusable_file_source_destination_entry(self) -> None:
        """common schema provides reusable source/destination base for file-like entries."""
        repo_root = self._repo_root()
        common_schema_path = repo_root / "schemas" / "common.schema.json"
        common_schema = read_json(common_schema_path)

        assert "fileSourceDestinationEntry" in common_schema["definitions"]
        file_base = common_schema["definitions"]["fileSourceDestinationEntry"]
        assert file_base["required"] == ["source", "destination"]
        assert "source" in file_base["properties"]
        assert "destination" in file_base["properties"]

    def test_common_schema_defines_systemd_entry(self) -> None:
        """common schema defines explicit systemdEntry structure."""
        repo_root = self._repo_root()
        common_schema_path = repo_root / "schemas" / "common.schema.json"
        common_schema = read_json(common_schema_path)

        assert "systemdEntry" in common_schema["definitions"]
        systemd_entry = common_schema["definitions"]["systemdEntry"]
        assert "allOf" in systemd_entry
        composed_refs = [
            part.get("$ref") for part in systemd_entry["allOf"] if isinstance(part, dict)
        ]
        assert "#/definitions/fileSourceDestinationEntry" in composed_refs
        details = [
            part
            for part in systemd_entry["allOf"]
            if isinstance(part, dict) and "properties" in part
        ][0]
        assert details["properties"]["destination"]["pattern"] == "^/etc/systemd/system/.+"
        assert details["properties"]["enable"]["type"] == "boolean"
        assert details["properties"]["start"]["type"] == "boolean"

    def test_host_schema_accepts_config_entries_without_apply(self) -> None:
        """host schema continues to accept common config entries without apply blocks."""
        repo_root = self._repo_root()
        host_schema_path = repo_root / "schemas" / "host.schema.json"
        host_schema = read_json(host_schema_path)

        host_data: dict[str, Any] = {
            "name": "phobos",
            "composition": {
                "software": {},
                "user_management": {},
                "config": [
                    {
                        "source": "common/systemd/system/example.service",
                        "destination": "/etc/systemd/system/example.service",
                    }
                ],
            },
        }

        validate_schema(host_data, host_schema, "host.yaml", host_schema_path)

    def test_host_schema_rejects_apply_block_on_config_entries(self) -> None:
        """host config entries no longer accept authored entry-level apply blocks."""
        repo_root = self._repo_root()
        host_schema_path = repo_root / "schemas" / "host.schema.json"
        host_schema = read_json(host_schema_path)

        host_data: dict[str, Any] = {
            "name": "phobos",
            "composition": {
                "software": {},
                "user_management": {},
                "config": [
                    {
                        "source": "common/systemd/system/example.service",
                        "destination": "/etc/systemd/system/example.service",
                        "apply": {
                            "activation_mode": "enable",
                        },
                    }
                ],
            },
        }

        with pytest.raises(RenderError):
            validate_schema(host_data, host_schema, "host.yaml", host_schema_path)

    def test_service_schema_accepts_plain_config_entries(self) -> None:
        """service schema allows plain config entries without apply blocks."""
        repo_root = self._repo_root()
        service_schema_path = repo_root / "schemas" / "service.schema.json"
        service_schema = read_json(service_schema_path)

        service_data: dict[str, Any] = {
            "name": "example",
            "composition": {
                "config": [
                    {
                        "source": "example/config/example.conf",
                        "destination": "/etc/example/example.conf",
                    }
                ]
            },
        }

        validate_schema(service_data, service_schema, "service.yaml", service_schema_path)

    def test_service_schema_rejects_apply_block_on_config_entries(self) -> None:
        """service config entries no longer accept entry-level apply blocks."""
        repo_root = self._repo_root()
        service_schema_path = repo_root / "schemas" / "service.schema.json"
        service_schema = read_json(service_schema_path)

        service_data: dict[str, Any] = {
            "name": "example",
            "composition": {
                "config": [
                    {
                        "source": "example/config/example.conf",
                        "destination": "/etc/example/example.conf",
                        "apply": {
                            "activation_mode": "start",
                        },
                    }
                ]
            },
        }

        with pytest.raises(RenderError):
            validate_schema(service_data, service_schema, "service.yaml", service_schema_path)

    def test_service_schema_rejects_systemd_destinations_under_config(self) -> None:
        """service config entries cannot deploy files under /etc/systemd/system/."""
        repo_root = self._repo_root()
        service_schema_path = repo_root / "schemas" / "service.schema.json"
        service_schema = read_json(service_schema_path)

        service_data: dict[str, Any] = {
            "name": "example",
            "composition": {
                "config": [
                    {
                        "source": "example/systemd/example.service",
                        "destination": "/etc/systemd/system/example.service",
                    }
                ]
            },
        }

        with pytest.raises(RenderError):
            validate_schema(service_data, service_schema, "service.yaml", service_schema_path)

    def test_service_schema_accepts_explicit_systemd_entries(self) -> None:
        """service schema accepts composition.systemd entries with enable/start flags."""
        repo_root = self._repo_root()
        service_schema_path = repo_root / "schemas" / "service.schema.json"
        service_schema = read_json(service_schema_path)

        service_data: dict[str, Any] = {
            "name": "example",
            "composition": {
                "systemd": [
                    {
                        "source": "example/systemd/example.path",
                        "destination": "/etc/systemd/system/example.path",
                        "enable": True,
                        "start": True,
                    }
                ]
            },
        }

        validate_schema(service_data, service_schema, "service.yaml", service_schema_path)

    def test_service_schema_accepts_directory_metadata(self) -> None:
        """service config directory entries may declare owner/group/mode directly."""
        repo_root = self._repo_root()
        service_schema_path = repo_root / "schemas" / "service.schema.json"
        service_schema = read_json(service_schema_path)

        service_data: dict[str, Any] = {
            "name": "example",
            "composition": {
                "config": [
                    {
                        "destination": "/srv/example/data",
                        "owner": "example",
                        "group": "example",
                        "mode": "0750",
                    }
                ]
            },
        }

        validate_schema(service_data, service_schema, "service.yaml", service_schema_path)
