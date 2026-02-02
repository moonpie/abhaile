"""Tests for scripts/lib/python/validation modules."""

import sys
from pathlib import Path

import pytest
import yaml

# Add lib/python to path
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "scripts" / "lib" / "python")
)

from utils.errors import RenderError
from validation.network import validate_network_sanity, validate_host_physical_device


class TestNetworkSanity:
    """Tests for network sanity validation."""

    def test_valid_network(self, tmp_repo_with_config):
        """Test validation passes for valid network config."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())

        # Should not raise
        validate_network_sanity(network)

    def test_unknown_vlan_host_interface(self, tmp_repo_with_config):
        """Test error when host interface references unknown VLAN."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        network["hosts"]["phobos"]["interfaces"]["eth0"]["vlan"] = "unknown-vlan"

        with pytest.raises(RenderError, match="references unknown vlan"):
            validate_network_sanity(network)

    def test_unknown_vlan_service(self, tmp_repo_with_config):
        """Test error when service references unknown VLAN."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        network["services"]["test-service"]["vlan"] = "unknown-vlan"

        with pytest.raises(RenderError, match="references unknown vlan"):
            validate_network_sanity(network)

    def test_ip_outside_vlan_subnet_host(self, tmp_repo_with_config):
        """Test error when host interface IP is outside VLAN subnet."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        network["hosts"]["phobos"]["interfaces"]["eth0"]["address"] = "192.168.1.1/24"

        with pytest.raises(RenderError, match="not in vlan"):
            validate_network_sanity(network)

    def test_ip_outside_vlan_subnet_service(self, tmp_repo_with_config):
        """Test error when service IP is outside VLAN subnet."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        network["services"]["test-service"]["address"] = "192.168.1.100/32"

        with pytest.raises(RenderError, match="not in vlan"):
            validate_network_sanity(network)

    def test_service_ip_outside_ipvlan_range(self, tmp_repo_with_config):
        """Test error when service /32 is outside ipvlanl2_range."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        # Range is 172.20.20.200-172.20.20.254
        network["services"]["test-service"]["address"] = "172.20.20.150/32"

        with pytest.raises(RenderError, match="not in ipvlanl2_range"):
            validate_network_sanity(network)

    def test_duplicate_ip_detection(self, tmp_repo_with_config):
        """Test error when same IP is used multiple times."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        # Add another host with same IP as phobos
        network["hosts"]["deimos"]["interfaces"]["eth0"]["address"] = "172.20.20.10/24"

        with pytest.raises(RenderError, match="Duplicate IP"):
            validate_network_sanity(network)

    def test_duplicate_ip_host_and_service(self, tmp_repo_with_config):
        """Test error when host and service share same IP."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())
        network["services"]["test-service"]["address"] = "172.20.20.10/32"

        with pytest.raises(RenderError, match="Duplicate IP"):
            validate_network_sanity(network)


class TestHostPhysicalDevice:
    """Tests for host physical_device validation."""

    def test_valid_physical_device(self, tmp_repo_with_config):
        """Test validation passes when physical_device exists in network.yaml."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())

        host_config = {"name": "phobos", "physical_device": "eth0"}

        # Should not raise
        validate_host_physical_device("phobos", host_config, network)

    def test_missing_physical_device_in_network(self, tmp_repo_with_config):
        """Test error when physical_device doesn't exist in network.yaml interfaces."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())

        host_config = {"name": "phobos", "physical_device": "nonexistent-device"}

        with pytest.raises(
            RenderError,
            match="physical_device 'nonexistent-device' not found in network.yaml interfaces",
        ):
            validate_host_physical_device("phobos", host_config, network)

    def test_optional_physical_device(self, tmp_repo_with_config):
        """Test validation passes when physical_device is not specified."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())

        host_config = {"name": "common"}  # No physical_device

        # Should not raise
        validate_host_physical_device("common", host_config, network)

    def test_host_not_in_network(self, tmp_repo_with_config):
        """Test error when host is not defined in network.yaml."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())

        host_config = {"name": "unknown-host", "physical_device": "eth0"}

        with pytest.raises(
            RenderError, match="Host 'unknown-host' not found in network.yaml"
        ):
            validate_host_physical_device("unknown-host", host_config, network)

    def test_error_message_includes_available_interfaces(self, tmp_repo_with_config):
        """Test error message lists available interfaces for debugging."""
        network_path = tmp_repo_with_config / "config" / "network.yaml"
        network = yaml.safe_load(network_path.read_text())

        host_config = {"name": "phobos", "physical_device": "eth99"}

        with pytest.raises(RenderError) as exc_info:
            validate_host_physical_device("phobos", host_config, network)

        error_msg = str(exc_info.value)
        assert "Available interfaces:" in error_msg
        assert "eth0" in error_msg
