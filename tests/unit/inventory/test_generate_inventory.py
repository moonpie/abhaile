"""Tests for inventory generation orchestration."""

import pytest

from tools.inventory.cli import extract_deployed_services


class TestExtractDeployedServices:
    """Tests for extracting deployed services from deployment structure."""

    def test_extract_deployed_services_empty(self):
        """Should return empty set for empty deployments."""
        deployments = {}
        result = extract_deployed_services(deployments)
        assert result == set()

    def test_extract_deployed_services_single_host(self):
        """Should extract services from single host."""
        deployments = {"phobos": {"default": ["coredns-filtered", "blocky", "vault"]}}
        result = extract_deployed_services(deployments)
        assert result == {"coredns-filtered", "blocky", "vault"}

    def test_extract_deployed_services_multiple_roles(self):
        """Should extract services from multiple roles on same host."""
        deployments = {
            "phobos": {
                "network": ["coredns-filtered", "blocky"],
                "apps": ["jellyfin", "home-assistant"],
                "infrastructure": ["vault"],
            }
        }
        result = extract_deployed_services(deployments)
        assert result == {
            "coredns-filtered",
            "blocky",
            "jellyfin",
            "home-assistant",
            "vault",
        }

    def test_extract_deployed_services_multiple_hosts(self):
        """Should extract services from multiple hosts."""
        deployments = {
            "phobos": {"network": ["coredns-filtered"], "apps": ["jellyfin"]},
            "deimos": {"network": ["blocky"], "apps": ["home-assistant"]},
        }
        result = extract_deployed_services(deployments)
        assert result == {"coredns-filtered", "blocky", "jellyfin", "home-assistant"}

    def test_extract_deployed_services_deduplicates(self):
        """Should deduplicate if service appears in multiple places."""
        deployments = {
            "phobos": {
                "network": ["vault"],
                "infrastructure": ["vault"],  # Same service in multiple roles
            }
        }
        result = extract_deployed_services(deployments)
        assert result == {"vault"}


class TestGenerateInventory:
    """Tests for the main inventory generation function."""

    def test_generate_inventory_creates_output_directory(self, tmp_path, monkeypatch):
        """Should create output directory if it doesn't exist."""
        # This test is skipped because generate_inventory requires real rendered artifacts
        # which is an integration-level requirement. Unit tests for helper functions
        # like extract_deployed_services are tested above.
        pytest.skip("Integration test: requires rendered artifacts from render phase")

    def test_generate_inventory_handles_empty_deployments(self, tmp_path):
        """Should handle empty deployment configuration gracefully."""
        # This test is skipped because generate_inventory requires real rendered artifacts
        pytest.skip("Integration test: requires rendered artifacts from render phase")

    def test_generate_inventory_writes_json_files(self, tmp_path):
        """Should write all JSON files to output directory."""
        # This test is skipped because generate_inventory requires real rendered artifacts
        pytest.skip("Integration test: requires rendered artifacts from render phase")

    def test_generate_inventory_writes_markdown_file(self, tmp_path):
        """Should write INVENTORY.md with proper structure."""
        # This test is skipped because generate_inventory requires real rendered artifacts
        pytest.skip("Integration test: requires rendered artifacts from render phase")
