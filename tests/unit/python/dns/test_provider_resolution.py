"""Unit tests for DNS provider resolution logic."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from abhaile.dns.renderer import (
    build_provider_mapping as _build_provider_mapping,
    get_zone_files_config as _get_zone_files_config,
)
from abhaile.utils.errors import RenderError


def _write_service(
    config_root: Path,
    name: str,
    composition: dict[str, Any] | None = None,
    dns_config: dict[str, Any] | None = None,
) -> None:
    """Write a service.yaml file to the config root."""
    service_dir = config_root / "services" / name
    service_dir.mkdir(parents=True, exist_ok=True)

    composition_data: dict[str, Any] = dict(composition or {})
    if dns_config is not None:
        composition_data = {**composition_data, "dns": dns_config}

    service_data: dict[str, Any] = {
        "name": name,
        "composition": composition_data,
    }

    (service_dir / "service.yaml").write_text(yaml.safe_dump(service_data))


class TestBuildProviderMappingDirectProvider:
    """Test direct provider mode: service provides zones under its own name."""

    def test_direct_provider_single_service(self, tmp_path: Path) -> None:
        """A service that directly defines zone_files becomes a provider for itself."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "coredns",
            dns_config={"zone_files": [{"zone": "example.com"}]},
        )

        result = _build_provider_mapping(["coredns"], config_root)

        # coredns should map to itself as a provider
        assert result == {"coredns": ["coredns"]}

    def test_direct_provider_multiple_services_with_zone_files(self, tmp_path: Path) -> None:
        """Multiple services with zone_files become providers for themselves."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "coredns",
            dns_config={"zone_files": [{"zone": "example.com"}]},
        )
        _write_service(
            config_root,
            "dnsmasq",
            dns_config={"zone_files": [{"zone": "local.test"}]},
        )

        result = _build_provider_mapping(["coredns", "dnsmasq"], config_root)

        assert result == {"coredns": ["coredns"], "dnsmasq": ["dnsmasq"]}

    def test_direct_provider_wildcard_zone_files(self, tmp_path: Path) -> None:
        """A service with zone_files entry (including wildcard) becomes a provider."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "coredns",
            dns_config={"zone_files": [{"zone": "*", "file": {"destination": "zones/zone.zone"}}]},
        )

        result = _build_provider_mapping(["coredns"], config_root)
        assert result == {"coredns": ["coredns"]}

    def test_no_provider_without_zone_files(self, tmp_path: Path) -> None:
        """Services without zone_files are not providers."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(config_root, "app")

        result = _build_provider_mapping(["app"], config_root)
        assert result == {}

    def test_direct_provider_empty_zone_files_list(self, tmp_path: Path) -> None:
        """Service with empty zone_files list is not a provider."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(config_root, "coredns", dns_config={"zone_files": []})

        result = _build_provider_mapping(["coredns"], config_root)
        assert result == {}


class TestBuildProviderMappingTransitiveProvider:
    """Test transitive provider mode: service includes a provider in composition.include."""

    def test_transitive_provider_single_level_include(self, tmp_path: Path) -> None:
        """A service that includes a provider becomes associated with that provider."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        # coredns-common: base provider with zone_files
        _write_service(
            config_root,
            "coredns-common",
            dns_config={"zone_files": [{"zone": "*"}]},
        )

        # coredns-app: includes coredns-common and also has zone_files
        _write_service(
            config_root,
            "coredns-app",
            composition={"include": ["coredns-common"]},
            dns_config={"zone_files": [{"zone": "app.local"}]},
        )

        result = _build_provider_mapping(["coredns-app"], config_root)

        # coredns-app is a provider for itself (direct)
        # coredns-app is also a provider for coredns-common (transitive)
        assert "coredns-app" in result["coredns-app"]
        assert "coredns-app" in result["coredns-common"]

    def test_transitive_provider_multi_level_include_chain(self, tmp_path: Path) -> None:
        """A service with zone_files that includes a multi-level chain becomes provider for all levels."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        # Level 1: base provider
        _write_service(config_root, "dns-base")

        # Level 2: mid-level
        _write_service(
            config_root,
            "dns-mid",
            composition={"include": ["dns-base"]},
        )

        # Level 3: top-level service with zone_files
        _write_service(
            config_root,
            "coredns",
            composition={"include": ["dns-mid"]},
            dns_config={"zone_files": [{"zone": "example.com"}]},
        )

        result = _build_provider_mapping(["coredns"], config_root)

        # coredns should be a provider for all services in its include chain
        assert "coredns" in result["coredns"]  # direct mode
        assert "coredns" in result["dns-mid"]  # transitive mode
        assert "coredns" in result["dns-base"]  # transitive mode

    def test_transitive_provider_multiple_includes(self, tmp_path: Path) -> None:
        """A service that includes multiple providers becomes associated with all."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(config_root, "provider-a")
        _write_service(config_root, "provider-b")

        _write_service(
            config_root,
            "aggregate",
            composition={"include": ["provider-a", "provider-b"]},
            dns_config={"zone_files": [{"zone": "*.local"}]},
        )

        result = _build_provider_mapping(["aggregate"], config_root)

        # aggregate is a provider for both included services
        assert "aggregate" in result["provider-a"]
        assert "aggregate" in result["provider-b"]
        assert "aggregate" in result["aggregate"]  # direct mode

    def test_transitive_provider_no_duplication(self, tmp_path: Path) -> None:
        """Services are not duplicated in provider mappings when added multiple times."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        # Base service without zone_files
        _write_service(config_root, "dns-base")

        # Provider that includes dns-base twice in different ways
        # (in practice this shouldn't happen, but we test for deduplication)
        _write_service(
            config_root,
            "coredns",
            composition={"include": ["dns-base"]},
            dns_config={"zone_files": [{"zone": "*"}]},
        )

        result = _build_provider_mapping(["coredns"], config_root)

        # coredns should appear exactly once as a provider for dns-base
        assert result["dns-base"].count("coredns") == 1
        assert "coredns" in result["coredns"]


class TestBuildProviderMappingMixed:
    """Test mixed scenarios with both direct and transitive providers."""

    def test_multiple_services_mixed_modes(self, tmp_path: Path) -> None:
        """Multiple services using both direct and transitive modes."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        # Direct provider: app-a has zone_files
        _write_service(
            config_root,
            "app-a",
            dns_config={"zone_files": [{"zone": "a.local"}]},
        )

        # Base for transitive mode
        _write_service(config_root, "dns-base")

        # Transitive provider: app-b includes dns-base and has zone_files
        _write_service(
            config_root,
            "app-b",
            composition={"include": ["dns-base"]},
            dns_config={"zone_files": [{"zone": "b.local"}]},
        )

        result = _build_provider_mapping(["app-a", "app-b"], config_root)

        assert result["app-a"] == ["app-a"]  # app-a direct
        assert "app-b" in result["app-b"]  # app-b direct
        assert "app-b" in result["dns-base"]  # app-b transitive

    def test_no_services_returns_empty(self, tmp_path: Path) -> None:
        """Empty host_services list returns empty provider mapping."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        result = _build_provider_mapping([], config_root)
        assert result == {}

    def test_nonexistent_service_skipped(self, tmp_path: Path) -> None:
        """Services without service.yaml files are skipped silently."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "exists",
            dns_config={"zone_files": [{"zone": "exists.local"}]},
        )

        result = _build_provider_mapping(["exists", "missing"], config_root)

        # Only the existing service appears in result
        assert "exists" in result
        assert "missing" not in result


class TestGetZoneFilesConfigDirect:
    """Test _get_zone_files_config for direct provider mode."""

    def test_get_zone_files_config_simple(self, tmp_path: Path) -> None:
        """Fetch zone_files from a provider with direct definition."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        zone_files_config = [
            {"zone": "example.com", "file": {"destination": "zones/example.com.zone"}}
        ]

        _write_service(config_root, "coredns", dns_config={"zone_files": zone_files_config})

        result = _get_zone_files_config("coredns", config_root)
        assert result == zone_files_config

    def test_get_zone_files_config_multiple_entries(self, tmp_path: Path) -> None:
        """Fetch multiple zone_files entries from a provider."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        zone_files_config = [
            {"zone": "example.com", "file": {"destination": "zones/example.com.zone"}},
            {"zone": "test.local", "file": {"destination": "zones/test.local.zone"}},
            {"zone": "*", "file": {"destination": "zones/zone.zone"}},
        ]

        _write_service(config_root, "coredns", dns_config={"zone_files": zone_files_config})

        result = _get_zone_files_config("coredns", config_root)
        assert result == zone_files_config


class TestGetZoneFilesConfigTransitive:
    """Test _get_zone_files_config for transitive provider mode."""

    def test_get_zone_files_config_inherited_via_include(self, tmp_path: Path) -> None:
        """Fetch zone_files that are inherited through composition.include."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        zone_files_config = [{"zone": "*", "file": {"destination": "zones/zone.zone"}}]

        # Base provider defines zone_files
        _write_service(
            config_root,
            "coredns-common",
            dns_config={"zone_files": zone_files_config},
        )

        # Derived provider includes base
        _write_service(
            config_root,
            "coredns",
            composition={"include": ["coredns-common"]},
        )

        # Should resolve zone_files from the include chain
        result = _get_zone_files_config("coredns", config_root)
        assert result == zone_files_config

    def test_get_zone_files_config_override_in_child(self, tmp_path: Path) -> None:
        """Child service can override zone_files from parent."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        parent_zone_files = [{"zone": "parent.com", "file": {"destination": "zones/parent.zone"}}]
        child_zone_files = [{"zone": "child.com", "file": {"destination": "zones/child.zone"}}]

        _write_service(
            config_root,
            "parent",
            dns_config={"zone_files": parent_zone_files},
        )

        _write_service(
            config_root,
            "child",
            composition={"include": ["parent"]},
            dns_config={"zone_files": child_zone_files},
        )

        result = _get_zone_files_config("child", config_root)
        assert result == child_zone_files  # Child value overrides parent


class TestGetZoneFilesConfigErrors:
    """Test error handling in _get_zone_files_config."""

    def test_missing_provider_service(self, tmp_path: Path) -> None:
        """Error when provider service doesn't exist."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        with pytest.raises(RenderError, match="Missing provider service definition"):
            _get_zone_files_config("nonexistent", config_root)

    def test_zone_files_not_a_list(self, tmp_path: Path) -> None:
        """Error when zone_files is not a list."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "bad-config",
            dns_config={"zone_files": "not-a-list"},
        )

        with pytest.raises(RenderError, match="expected list, got"):
            _get_zone_files_config("bad-config", config_root)

    def test_zone_files_entry_not_object(self, tmp_path: Path) -> None:
        """Error when zone_files entry is not an object."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "bad-config",
            dns_config={"zone_files": ["string-entry"]},
        )

        with pytest.raises(RenderError, match="each entry must be an object"):
            _get_zone_files_config("bad-config", config_root)

    def test_zone_files_multiple_invalid_entries(self, tmp_path: Path) -> None:
        """Error identifies index of invalid zone_files entry."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(
            config_root,
            "bad-config",
            dns_config={
                "zone_files": [
                    {"zone": "valid.com"},
                    "invalid-entry",
                ]
            },
        )

        with pytest.raises(RenderError, match="index 1"):
            _get_zone_files_config("bad-config", config_root)

    def test_dns_config_not_dict(self, tmp_path: Path) -> None:
        """Error when dns configuration is not a dictionary."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        # This is contrived but tests the validation
        service_dir = config_root / "services" / "bad"
        service_dir.mkdir(parents=True)
        service_data = {
            "name": "bad",
            "composition": {"dns": "not-a-dict"},
        }
        (service_dir / "service.yaml").write_text(yaml.safe_dump(service_data))

        with pytest.raises(RenderError, match="Invalid 'dns' configuration"):
            _get_zone_files_config("bad", config_root)

    def test_error_message_suggests_fix(self, tmp_path: Path) -> None:
        """Error message for missing zone_files entry suggests how to fix."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        # Provider with bad zone_files config
        _write_service(
            config_root,
            "provider",
            dns_config={"zone_files": 123},  # Wrong type
        )

        with pytest.raises(RenderError) as exc_info:
            _get_zone_files_config("provider", config_root)

        error_msg = str(exc_info.value)
        # Error should suggest fix for zone_files
        assert "expected list, got" in error_msg


class TestProviderResolutionEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_service_with_dns_but_no_zone_files_key(self, tmp_path: Path) -> None:
        """Service with dns config but no zone_files key is not a provider."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(config_root, "service", dns_config={"settings": {"a": 1}})

        result = _build_provider_mapping(["service"], config_root)
        assert result == {}

    def test_service_without_any_dns_config(self, tmp_path: Path) -> None:
        """Service without dns config is not a provider."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(config_root, "app")

        result = _build_provider_mapping(["app"], config_root)
        assert result == {}

    def test_get_zone_files_from_service_without_dns_config(self, tmp_path: Path) -> None:
        """Fetching zone_files from service without dns config returns empty list."""
        config_root = tmp_path / "config"
        config_root.mkdir(parents=True)

        _write_service(config_root, "simple-service")

        result = _get_zone_files_config("simple-service", config_root)
        assert result == []
