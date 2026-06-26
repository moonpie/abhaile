"""Unit tests for service validation module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from abhaile.utils.errors import RenderError
from abhaile.validation.services import (
    ensure_service_definitions,
    get_all_services_in_order,
    parse_mapping,
    validate_config_change_restart_units,
    validate_service_names,
)


class TestParseMapping:
    """Tests for parse_mapping()."""

    def test_valid_mapping(self) -> None:
        """Parse a valid mapping with string service entries."""
        mapping = {"abhaile": [{"phobos": ["svc-a", "svc-b"]}, {"deimos": ["svc-c"]}]}
        result = parse_mapping(mapping)
        assert result == {"phobos": ["svc-a", "svc-b"], "deimos": ["svc-c"]}

    def test_missing_abhaile_key(self) -> None:
        """Raise RenderError when top-level key is missing."""
        with pytest.raises(RenderError, match="missing top-level 'abhaile'"):
            parse_mapping({"hosts": []})

    def test_non_dict_input(self) -> None:
        """Raise RenderError for non-dict input."""
        with pytest.raises(RenderError, match="missing top-level 'abhaile'"):
            parse_mapping(["not", "a", "dict"])

    def test_host_entry_not_single_key(self) -> None:
        """Raise RenderError when host entry has multiple keys."""
        mapping = {"abhaile": [{"phobos": ["a"], "deimos": ["b"]}]}
        with pytest.raises(RenderError, match="single-key objects"):
            parse_mapping(mapping)

    def test_services_not_list(self) -> None:
        """Raise RenderError when services value is not a list."""
        mapping = {"abhaile": [{"phobos": "not-a-list"}]}
        with pytest.raises(RenderError, match="must be a list"):
            parse_mapping(mapping)

    def test_dict_service_entry_with_name(self) -> None:
        """Parse dict service entries using 'name' key."""
        mapping = {"abhaile": [{"phobos": [{"name": "svc-a"}]}]}
        result = parse_mapping(mapping)
        assert result == {"phobos": ["svc-a"]}

    def test_dict_service_entry_single_key(self) -> None:
        """Parse single-key dict service entries."""
        mapping = {"abhaile": [{"phobos": [{"svc-a": {"extra": "data"}}]}]}
        result = parse_mapping(mapping)
        assert result == {"phobos": ["svc-a"]}

    def test_invalid_service_entry_type(self) -> None:
        """Raise RenderError for non-string/non-dict service entries."""
        mapping = {"abhaile": [{"phobos": [123]}]}
        with pytest.raises(RenderError, match="must be string or object"):
            parse_mapping(mapping)


class TestGetAllServicesInOrder:
    """Tests for get_all_services_in_order()."""

    def test_deduplicates_across_hosts(self) -> None:
        """Return unique services in declaration order."""
        mapping = {"abhaile": [{"phobos": ["a", "b"]}, {"deimos": ["b", "c"]}]}
        result = get_all_services_in_order(mapping)
        assert result == ["a", "b", "c"]

    def test_preserves_declaration_order(self) -> None:
        """First occurrence wins for ordering."""
        mapping = {"abhaile": [{"deimos": ["z", "a"]}, {"phobos": ["m", "z"]}]}
        result = get_all_services_in_order(mapping)
        assert result == ["z", "a", "m"]

    def test_empty_mapping(self) -> None:
        """Return empty list for empty host list."""
        mapping: dict[str, list[Any]] = {"abhaile": []}
        result = get_all_services_in_order(mapping)
        assert result == []

    def test_missing_abhaile_key(self) -> None:
        """Raise RenderError for invalid structure."""
        with pytest.raises(RenderError, match="missing top-level 'abhaile'"):
            get_all_services_in_order({})


class TestEnsureServiceDefinitions:
    """Tests for ensure_service_definitions()."""

    def test_all_services_exist(self, tmp_path: Path, write_file: Any) -> None:
        """Return paths when all service.yaml files exist."""
        config_root = tmp_path / "config"
        write_file(config_root / "services" / "svc-a" / "service.yaml", "name: svc-a\n")
        write_file(config_root / "services" / "svc-b" / "service.yaml", "name: svc-b\n")

        result = ensure_service_definitions(config_root, ["svc-a", "svc-b"])
        assert len(result) == 2
        assert all(p.exists() for p in result)

    def test_missing_service_raises(self, tmp_path: Path) -> None:
        """Raise RenderError for missing service definition."""
        config_root = tmp_path / "config"
        (config_root / "services").mkdir(parents=True)

        with pytest.raises(RenderError, match="Missing service definition"):
            ensure_service_definitions(config_root, ["nonexistent"])

    def test_empty_services_list(self, tmp_path: Path) -> None:
        """Return empty list for no services."""
        config_root = tmp_path / "config"
        (config_root / "services").mkdir(parents=True)

        result = ensure_service_definitions(config_root, [])
        assert result == []


class TestValidateServiceNames:
    """Tests for validate_service_names()."""

    def test_matching_names_pass(self, tmp_path: Path, write_file: Any) -> None:
        """No error when service name matches directory."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "my-svc" / "service.yaml",
            yaml.dump({"name": "my-svc"}),
        )
        validate_service_names(config_root)

    def test_mismatched_name_raises(self, tmp_path: Path, write_file: Any) -> None:
        """Raise RenderError when name field disagrees with directory."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "my-svc" / "service.yaml",
            yaml.dump({"name": "wrong-name"}),
        )
        with pytest.raises(RenderError, match="Service name mismatch"):
            validate_service_names(config_root)

    def test_no_name_field_passes(self, tmp_path: Path, write_file: Any) -> None:
        """No error when service.yaml has no name field."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "my-svc" / "service.yaml",
            yaml.dump({"type": "container"}),
        )
        validate_service_names(config_root)


class TestValidateConfigChangeRestartUnits:
    """Tests for explicit config-change restart policy validation."""

    def test_service_config_requires_explicit_restart_policy(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Raise when mapped service.config writes omit restart policy."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
composition:
  config:
    - source: blocky/config/config.yml
      destination: /srv/blocky/config.yml
""",
        )

        with pytest.raises(RenderError, match="apply.config_change_restart_unit"):
            validate_config_change_restart_units(config_root, {"phobos": ["blocky"]})

    def test_service_config_accepts_explicit_restart_unit(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Accept mapped service.config writes with an explicit restart unit."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
apply:
  config_change_restart_unit: blocky.service
composition:
  config:
    - source: blocky/config/config.yml
      destination: /srv/blocky/config.yml
""",
        )

        validate_config_change_restart_units(config_root, {"phobos": ["blocky"]})

    def test_service_config_accepts_explicit_null_restart_unit(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Accept mapped static service.config writes with explicit null."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "omada-controller" / "service.yaml",
            """name: omada-controller
apply:
  config_change_restart_unit: null
composition:
  config:
    - source: omada-controller/config/omada.js
      destination: /srv/omada-controller/mongodb/initdb/omada.js
""",
        )

        validate_config_change_restart_units(config_root, {"phobos": ["omada-controller"]})

    def test_special_coredns_config_does_not_require_restart_policy(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Ignore special coredns.config artifacts."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "coredns-clean" / "service.yaml",
            """name: coredns-clean
composition:
  config:
    - source: coredns-clean/config/Corefile
      destination: /etc/coredns/Corefile
""",
        )

        validate_config_change_restart_units(config_root, {"deimos": ["coredns-clean"]})

    def test_included_service_config_requires_including_service_policy(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Validate include-expanded service.config writes against mapped service."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "coredns-omada" / "service.yaml",
            """name: coredns-omada
composition:
  config:
    - source: coredns-omada/build/Containerfile
      destination: /srv/build/coredns-omada/Containerfile
""",
        )
        write_file(
            config_root / "services" / "coredns-clean" / "service.yaml",
            """name: coredns-clean
composition:
  include:
    - coredns-omada
  config:
    - source: coredns-clean/config/Corefile
      destination: /etc/coredns/Corefile
""",
        )

        with pytest.raises(RenderError, match="coredns-clean"):
            validate_config_change_restart_units(config_root, {"deimos": ["coredns-clean"]})

    def test_included_service_config_accepts_including_service_policy(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Accept include-expanded service.config writes with mapped service policy."""
        config_root = tmp_path / "config"
        write_file(
            config_root / "services" / "coredns-omada" / "service.yaml",
            """name: coredns-omada
composition:
  config:
    - source: coredns-omada/build/Containerfile
      destination: /srv/build/coredns-omada/Containerfile
""",
        )
        write_file(
            config_root / "services" / "coredns-clean" / "service.yaml",
            """name: coredns-clean
apply:
  config_change_restart_unit: null
composition:
  include:
    - coredns-omada
  config:
    - source: coredns-clean/config/Corefile
      destination: /etc/coredns/Corefile
""",
        )

        validate_config_change_restart_units(config_root, {"deimos": ["coredns-clean"]})
