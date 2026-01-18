import pytest
from tools.common.core.context_utils import last_octet
from tools.render.validate import validate_last_octet_uniqueness
from tools.common.core import ValidationError

# --- Network builder tests ---


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


# --- Activity 5: Expanded network builder tests ---


def test_ipvlan_address_assignment_different_vlans():
    """Test that same last octet is allowed across different VLANs."""
    network = {
        "services": {
            "svc1": {"address": "172.20.20.100/32", "vlan": "services"},
            "svc2": {
                "address": "172.20.100.100/32",
                "vlan": "dmz",
            },  # Same octet, different VLAN
        }
    }
    # Should not raise
    validate_last_octet_uniqueness(network)


def test_service32_address_validation_no_address():
    """Test that services without addresses don't cause validation errors."""
    network = {
        "services": {
            "host_service": {"vlan": "services"},  # No address field
            "svc1": {"address": "172.20.20.100/32", "vlan": "services"},
        }
    }
    # Should not raise
    validate_last_octet_uniqueness(network)


def test_service32_address_validation_no_vlan():
    """Test that services without VLAN don't cause validation errors."""
    network = {
        "services": {
            "orphan_service": {"address": "172.20.20.100/32"},  # No vlan field
            "svc1": {"address": "172.20.20.101/32", "vlan": "services"},
        }
    }
    # Should not raise (services without VLAN are skipped)
    validate_last_octet_uniqueness(network)


def test_vlan_routing_duplicate_detection_detailed():
    """Test detailed duplicate detection with clear error messages."""
    network = {
        "services": {
            "svc1": {"address": "172.20.20.50/32", "vlan": "services"},
            "svc2": {"address": "172.20.20.51/32", "vlan": "services"},
            "svc3": {
                "address": "172.20.20.50/32",
                "vlan": "services",
            },  # Duplicate of svc1
        }
    }

    with pytest.raises(ValidationError, match="Duplicate last-octet"):
        validate_last_octet_uniqueness(network)


def test_last_octet_extraction_various_formats():
    """Test last octet extraction from various IP formats."""
    assert last_octet("172.20.20.5/32") == 5
    assert last_octet("10.0.0.1") == 1
    assert last_octet("192.168.1.255/24") == 255
    assert last_octet("172.20.20.100") == 100


def test_dropin_ordering_by_last_octet():
    """Test that drop-in file ordering is deterministic via last octet."""
    network = {
        "services": {
            "svc_high": {"address": "172.20.20.200/32", "vlan": "services"},
            "svc_low": {"address": "172.20.20.50/32", "vlan": "services"},
            "svc_mid": {"address": "172.20.20.100/32", "vlan": "services"},
        }
    }

    # Validate uniqueness passes
    validate_last_octet_uniqueness(network)

    # Extract and sort by last octet
    services = network["services"]
    sorted_services = sorted(
        services.items(), key=lambda x: last_octet(x[1].get("address", "0.0.0.0"))
    )

    # Should be ordered: svc_low (50), svc_mid (100), svc_high (200)
    assert sorted_services[0][0] == "svc_low"
    assert sorted_services[1][0] == "svc_mid"
    assert sorted_services[2][0] == "svc_high"


# --- End network builder tests ---
