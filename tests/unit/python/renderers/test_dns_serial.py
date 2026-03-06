"""Unit tests for DNS serial validation."""

from datetime import datetime
from typing import Any, Dict

import pytest

from abhaile.dns.records import collect_zone_records as _collect_zone_records
from abhaile.dns.serial_validator import (
    compute_content_hash as _compute_content_hash,
    validate_zone_serial as _validate_zone_serial,
    validate_zone_serial_collect as _validate_zone_serial_collect,
)
from abhaile.utils.errors import RenderError
from tests.unit.python.renderers.dns_helpers import build_zone_content_for_hash


class TestValidateZoneSerial:
    """Tests for _validate_zone_serial."""

    def test_serial_valid_no_content_change(self):
        """Test that validation passes when content hash matches."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zone: Dict[str, Any] = {
            "name": "example.com.",
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,  # Will be computed
            },
        }

        # First compute what the hash should be
        records = _collect_zone_records(zone, network, [])
        zone_content = build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        # This should not raise
        _validate_zone_serial(zone, network, [])

    def test_serial_invalid_content_changed(self):
        """Test that validation fails when content hash mismatches."""
        network: Dict[str, Any] = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "192.0.2.1",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {},
        }
        today = datetime.now().strftime("%Y%m%d")
        zone: Dict[str, Any] = {
            "name": "example.com.",
            "serial": {
                "date": today,
                "counter": "00",
                "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            },
        }

        with pytest.raises(RenderError) as exc_info:
            _validate_zone_serial(zone, network, [])

        error_msg = str(exc_info.value)
        assert "content hash mismatch" in error_msg
        # Should show at least the content_hash field that differs
        assert "serial.content_hash" in error_msg or "serial.counter" in error_msg

    def test_serial_missing_content_hash_fails(self):
        """Test that validation fails if content_hash is missing."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zone: Dict[str, Any] = {
            "name": "example.com.",
            "serial": {
                "date": "20260208",
                "counter": "00",
            },
        }

        with pytest.raises(RenderError) as exc_info:
            _validate_zone_serial(zone, network, [])

        error_msg = str(exc_info.value)
        assert "missing content_hash" in error_msg


class TestValidateZoneSerialCollect:
    """Tests for _validate_zone_serial_collect."""

    def test_collect_single_valid_zone(self):
        """Test that valid zones don't generate errors."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zone: Dict[str, Any] = {
            "name": "example.com.",
            "provider": {"type": "internal", "name": "coredns"},
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,
            },
        }

        # Pre-compute the expected hash
        records = _collect_zone_records(zone, network, [])
        zone_content = build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        zones = [zone]
        errors = _validate_zone_serial_collect(zones, network, [])
        assert errors == []

    def test_collect_multiple_mismatched_zones(self):
        """Test that all mismatched zones are collected."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        today = datetime.now().strftime("%Y%m%d")
        zones = [
            {
                "name": "zone1.com.",
                "provider": {"type": "internal", "name": "coredns"},
                "serial": {
                    "date": today,
                    "counter": "00",
                    "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
                },
            },
            {
                "name": "zone2.com.",
                "provider": {"type": "internal", "name": "coredns"},
                "serial": {
                    "date": today,
                    "counter": "05",
                    "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
                },
            },
        ]

        errors = _validate_zone_serial_collect(zones, network, [])

        # Should have errors for both zones
        assert len(errors) == 2
        assert "zone1.com." in errors[0]
        assert "zone2.com." in errors[1]
        assert "content hash mismatch" in errors[0]
        assert "content hash mismatch" in errors[1]

    def test_collect_mixed_valid_and_invalid(self):
        """Test collecting from mix of valid and invalid zones."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        today = datetime.now().strftime("%Y%m%d")

        # Valid zone
        zone1: Dict[str, Any] = {
            "name": "valid.com.",
            "provider": {"type": "internal", "name": "coredns"},
            "serial": {
                "date": today,
                "counter": "00",
                "content_hash": None,
            },
        }
        records = _collect_zone_records(zone1, network, [])
        zone_content = build_zone_content_for_hash(zone1, records)
        zone1["serial"]["content_hash"] = _compute_content_hash(zone_content)

        # Invalid zone
        zone2: Dict[str, Any] = {
            "name": "invalid.com.",
            "provider": {"type": "internal", "name": "coredns"},
            "serial": {
                "date": today,
                "counter": "00",
                "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            },
        }

        zones = [zone1, zone2]
        errors = _validate_zone_serial_collect(zones, network, [])

        # Should have error only for zone2
        assert len(errors) == 1
        assert "invalid.com." in errors[0]

    def test_collect_skips_external_zones(self):
        """Test that external zones are skipped."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zones = [
            {
                "name": "example.com.",
                "provider": {"type": "external", "name": "desec.io"},
            }
        ]

        errors = _validate_zone_serial_collect(zones, network, [])
        assert errors == []

    def test_serial_includes_service_records_in_mapping_order(self):
        """Test that service records are hashed in mapping order."""
        network: Dict[str, Any] = {
            "hosts": {},
            "services": {
                "svc-a": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "alpha",
                                    "type": "a",
                                    "rdata": "192.0.2.10",
                                    "ttl": 3600,
                                }
                            ],
                        }
                    ]
                },
                "svc-b": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "beta",
                                    "type": "a",
                                    "rdata": "192.0.2.11",
                                    "ttl": 3600,
                                }
                            ],
                        }
                    ]
                },
            },
        }
        zone: Dict[str, Any] = {
            "name": "example.com.",
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,
            },
        }

        deployed_services = ["svc-b", "svc-a"]
        records = _collect_zone_records(zone, network, deployed_services)
        zone_content = build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        _validate_zone_serial(zone, network, deployed_services)
