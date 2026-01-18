import pytest
import yaml
from pathlib import Path

# Core utils
from tools.common.core import strip_cidr, load_yaml, ValidationError
from tools.common.core.context_utils import last_octet
from tools.render.validate import (
    validate_last_octet_uniqueness,
    validate_network_config,
)
from tools.render.host.networkd_builder import build_network_file_map


# Removed duplicate tests - consolidated into class-based tests below
# - test_strip_cidr_none_and_empty → TestStripCIDR class
# - test_strip_cidr_malformed_raises → kept as standalone for error case
# - test_build_network_file_map_* → TestBuildNetworkFileMap class


def test_strip_cidr_malformed_raises():
    """Test that strip_cidr raises on malformed CIDR notation."""
    with pytest.raises(ValueError):
        strip_cidr("not.an.ip/24")


# Removed duplicate validate_network_config tests
# - Consolidated into TestValidateNetworkConfig class below


def test_last_octet_and_validate_uniqueness():
    assert last_octet("172.20.10.5/32") == 5
    network = {
        "services": {
            "a": {"address": "172.20.10.5/32", "vlan": "v1"},
            "b": {"address": "172.20.10.6/32", "vlan": "v1"},
        }
    }
    validate_last_octet_uniqueness(network)
    network_dup = {
        "services": {
            "a": {"address": "172.20.10.5/32", "vlan": "v1"},
            "b": {"address": "172.20.10.5/32", "vlan": "v1"},
        }
    }
    with pytest.raises(ValidationError):
        validate_last_octet_uniqueness(network_dup)


# ---- Test Classes ----
class TestBuildNetworkFileMap:
    """Unit tests for build_network_file_map function.

    Tests parsing of systemd-networkd configuration files to extract
    interface names and create drop-in directory paths.
    """

    def test_parses_match_name(self, tmp_path: Path):
        """Test that Match sections with Name= are parsed correctly."""
        nd = tmp_path / "net"
        nd.mkdir()
        f = nd / "10.network"
        f.write_text("[Match]\nName=enp0s31f6\n")
        m = build_network_file_map(nd)
        assert "enp0s31f6" in m
        assert m["enp0s31f6"].name.endswith("10.network.d")

    def test_no_match_returns_empty(self, tmp_path: Path):
        """Test that files without [Match] sections are ignored."""
        nd = tmp_path / "net2"
        nd.mkdir()
        (nd / "a.network").write_text("[Link]\nDescription=foo\n")
        m = build_network_file_map(nd)
        assert m == {}

    def test_comprehensive_parsing(self, tmp_path: Path):
        """Test parsing multiple network files with different configurations."""
        d = tmp_path / "net"
        d.mkdir()
        f = d / "10-enp0s31f6.network"
        f.write_text("[Match]\nName=enp0s31f6\n[Network]\nDHCP=yes\n")
        mapping = build_network_file_map(d)
        assert "enp0s31f6" in mapping
        assert mapping["enp0s31f6"].name.endswith("10-enp0s31f6.network.d")


class TestStripCIDR:
    """Unit tests for strip_cidr function.

    Tests CIDR notation stripping from IP addresses.
    """

    def test_strip_cidr_with_suffix(self):
        assert strip_cidr("192.168.1.1/24") == "192.168.1.1"

    def test_strip_cidr_without_suffix(self):
        assert strip_cidr("192.168.1.1") == "192.168.1.1"

    def test_strip_cidr_empty_string(self):
        assert strip_cidr("") == ""

    def test_strip_cidr_non_string(self):
        assert strip_cidr(None) is None

    def test_strip_cidr_valid_address(self):
        """Test stripping CIDR from valid IP addresses."""
        assert strip_cidr("192.168.1.5/24") == "192.168.1.5"
        assert strip_cidr("172.20.20.10/32") == "172.20.20.10"


class TestValidateNetworkConfig:
    """Unit tests for validate_network_config function.

    Tests validation of network.yaml structure, VLAN definitions,
    service address assignments, and duplicate IP detection.
    """

    def test_valid_network_config(self, tmp_path):
        """Test that valid network configuration passes validation."""
        network_data = {
            "vlans": {
                20: {"subnet": "172.20.20.0/24"},
                30: {"subnet": "172.20.30.0/24"},
            },
            "services": {
                "vault": {"address": "172.20.20.10/32", "vlan": 20},
                "caddy": {"address": "172.20.20.11/32", "vlan": 20},
                "coredns": {"address": "172.20.30.5/32", "vlan": 30},
            },
        }
        network_yaml = tmp_path / "network.yaml"
        with open(network_yaml, "w") as f:
            yaml.dump(network_data, f)
        validate_network_config(tmp_path)

    def test_duplicate_ip_detection(self, tmp_path):
        """Test that duplicate IP addresses are detected and rejected."""
        network_data = {
            "vlans": {20: {"subnet": "172.20.20.0/24"}},
            "services": {
                "vault": {"address": "172.20.20.10/32", "vlan": 20},
                "caddy": {"address": "172.20.20.10/32", "vlan": 20},
            },
        }
        network_yaml = tmp_path / "network.yaml"
        with open(network_yaml, "w") as f:
            yaml.dump(network_data, f)
        with pytest.raises(ValidationError, match="duplicate IP address"):
            validate_network_config(tmp_path)

    def test_vlan_consistency_mismatch(self, tmp_path):
        """Test that service addresses must be in their VLAN subnet."""
        network_data = {
            "vlans": {
                20: {"subnet": "172.20.20.0/24"},
                30: {"subnet": "172.20.30.0/24"},
            },
            "services": {
                "vault": {
                    "address": "172.20.30.10/32",
                    "vlan": 20,
                }  # Wrong subnet for VLAN 20
            },
        }
        network_yaml = tmp_path / "network.yaml"
        with open(network_yaml, "w") as f:
            yaml.dump(network_data, f)
        with pytest.raises(ValidationError, match="not in VLAN subnet"):
            validate_network_config(tmp_path)

    def test_missing_network_yaml(self, tmp_path):
        """Test that missing network.yaml file raises ValidationError."""
        with pytest.raises(ValidationError, match="network.yaml not found"):
            validate_network_config(tmp_path)


# ---- Merged from test_yaml_utils.py ----
class TestYamlUtils:
    """Unit tests for YAML loading utilities.

    Tests load_yaml function with various file states.
    """

    def test_load_yaml_valid_file(self, tmp_path):
        """Test loading valid YAML file with nested structures."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nlist:\n  - item1\n  - item2\n")
        data = load_yaml(yaml_file)
        assert data["key"] == "value"
        assert data["list"] == ["item1", "item2"]

    def test_load_yaml_empty_file(self, tmp_path):
        """Test that empty YAML files return None or empty dict."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        data = load_yaml(yaml_file)
        assert data is None or data == {}

    def test_load_yaml_missing_file(self, tmp_path):
        """Test that missing YAML files raise FileNotFoundError."""
        yaml_file = tmp_path / "missing.yaml"
        with pytest.raises((FileNotFoundError, IOError)):
            load_yaml(yaml_file)
