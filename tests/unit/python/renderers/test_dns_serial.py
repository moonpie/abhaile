"""Unit tests for DNS serial validation."""

from pathlib import Path
from typing import Any

import pytest

from abhaile.dns.records import collect_zone_records as _collect_zone_records
from abhaile.dns.serial_validator import (
    compute_content_hash as _compute_content_hash,
    validate_zone_serial as _validate_zone_serial,
    validate_zone_serial_collect as _validate_zone_serial_collect,
)
from abhaile.utils.errors import RenderError


@pytest.fixture
def minimal_config_root(tmp_path: Path) -> Path:
    """Create minimal config_root with coredns-common service and zone template."""
    config_root = tmp_path / "config"
    template_dir = config_root / "services" / "coredns-common" / "config" / "zones"
    template_dir.mkdir(parents=True)

    (config_root / "services" / "coredns-common" / "service.yaml").write_text(
        """
name: coredns-common
composition:
  dns:
    zone_files:
      - zone: '*'
        file:
          source:
            template: coredns-common/config/zones/zone.zone.j2
          destination: /etc/coredns/zones/zone.zone
""".strip() + "\n",
        encoding="utf-8",
    )

    # Match the legacy formatter's single-line SOA and simpler structure
    (template_dir / "zone.zone.j2").write_text(
        "$ORIGIN {{ zone.name }}\n"
        "\n"
        "{% set zone_name_stripped = zone.name.rstrip('.') %}"
        "{{ zone_name_stripped }}. 3600 IN SOA ns1.{{ zone_name_stripped }}. "
        "hostmaster.{{ zone_name_stripped }}. {{ zone.serial }} 3600 1800 604800 86400\n"
        "{{ zone_name_stripped }}. 3600 IN NS ns1.{{ zone_name_stripped }}.\n"
        "\n"
        "{% for record in zone.records %}"
        "{{ record.name.rstrip('.') }} {{ record.ttl }} IN {{ record.type.upper() }} {{ record.rdata }}\n"
        "{% endfor %}"
        "\n",
        encoding="utf-8",
    )

    return config_root


class TestValidateZoneSerial:
    """Tests for _validate_zone_serial."""

    def test_serial_valid_no_content_change(self, minimal_config_root: Path) -> None:
        """Test that validation passes when content hash matches."""
        network: dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zone: dict[str, Any] = {
            "name": "example.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,  # Will be computed
            },
        }

        # First compute what the hash should be using renderer
        from abhaile.dns.renderer import render_zone_template

        records = _collect_zone_records(zone, network, [])
        zone_content = render_zone_template(
            "coredns-common/config/zones/zone.zone.j2",
            zone,
            records,
            minimal_config_root,
        )
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        # This should not raise
        _validate_zone_serial(zone, network, [], config_root=minimal_config_root)

    def test_serial_invalid_content_changed(self, minimal_config_root: Path) -> None:
        """Test that validation fails when content hash mismatches."""
        network: dict[str, Any] = {
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
        zone: dict[str, Any] = {
            "name": "example.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260101",
                "counter": "00",
                "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            },
        }

        with pytest.raises(RenderError) as exc_info:
            _validate_zone_serial(zone, network, [], config_root=minimal_config_root)

        error_msg = str(exc_info.value)
        assert "content hash mismatch" in error_msg
        # Should show at least the content_hash field that differs
        assert "serial.content_hash" in error_msg or "serial.counter" in error_msg

    def test_serial_missing_content_hash_fails(self, minimal_config_root: Path) -> None:
        """Test that validation fails if content_hash is missing."""
        network: dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zone: dict[str, Any] = {
            "name": "example.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260208",
                "counter": "00",
            },
        }

        with pytest.raises(RenderError) as exc_info:
            _validate_zone_serial(zone, network, [], config_root=minimal_config_root)

        error_msg = str(exc_info.value)
        assert "missing content_hash" in error_msg


class TestValidateZoneSerialCollect:
    """Tests for _validate_zone_serial_collect."""

    def test_collect_single_valid_zone(self, minimal_config_root: Path) -> None:
        """Test that valid zones don't generate errors."""
        network: dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zone: dict[str, Any] = {
            "name": "example.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,
            },
        }

        # Pre-compute the expected hash using renderer
        from abhaile.dns.renderer import render_zone_template

        records = _collect_zone_records(zone, network, [])
        zone_content = render_zone_template(
            "coredns-common/config/zones/zone.zone.j2",
            zone,
            records,
            minimal_config_root,
        )
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        zones = [zone]
        errors = _validate_zone_serial_collect(zones, network, [], config_root=minimal_config_root)
        assert errors == []

    def test_collect_multiple_mismatched_zones(self, minimal_config_root: Path) -> None:
        """Test that all mismatched zones are collected."""
        network: dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zones = [
            {
                "name": "zone1.com.",
                "provider": {"type": "internal", "name": "coredns-common"},
                "serial": {
                    "date": "20260101",
                    "counter": "00",
                    "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
                },
            },
            {
                "name": "zone2.com.",
                "provider": {"type": "internal", "name": "coredns-common"},
                "serial": {
                    "date": "20260101",
                    "counter": "05",
                    "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
                },
            },
        ]

        errors = _validate_zone_serial_collect(zones, network, [], config_root=minimal_config_root)

        # Should have errors for both zones
        assert len(errors) == 2
        assert "zone1.com." in errors[0]
        assert "zone2.com." in errors[1]
        assert "content hash mismatch" in errors[0]
        assert "content hash mismatch" in errors[1]

    def test_collect_mixed_valid_and_invalid(self, minimal_config_root: Path) -> None:
        """Test collecting from mix of valid and invalid zones."""
        network: dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        # Valid zone
        zone1: dict[str, Any] = {
            "name": "valid.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,
            },
        }

        from abhaile.dns.renderer import render_zone_template

        records = _collect_zone_records(zone1, network, [])
        zone_content = render_zone_template(
            "coredns-common/config/zones/zone.zone.j2",
            zone1,
            records,
            minimal_config_root,
        )
        zone1["serial"]["content_hash"] = _compute_content_hash(zone_content)

        # Invalid zone
        zone2: dict[str, Any] = {
            "name": "invalid.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            },
        }

        zones = [zone1, zone2]
        errors = _validate_zone_serial_collect(zones, network, [], config_root=minimal_config_root)

        # Should have error only for zone2
        assert len(errors) == 1
        assert "invalid.com." in errors[0]

    def test_collect_skips_external_zones(self, minimal_config_root: Path) -> None:
        """Test that external zones are skipped."""
        network: dict[str, Any] = {
            "hosts": {},
            "services": {},
        }
        zones = [
            {
                "name": "example.com.",
                "provider": {"type": "external", "name": "desec.io"},
            }
        ]

        errors = _validate_zone_serial_collect(zones, network, [], config_root=minimal_config_root)
        assert errors == []

    def test_serial_includes_service_records_in_mapping_order(
        self, minimal_config_root: Path
    ) -> None:
        """Test that service records are hashed in mapping order."""
        network: dict[str, Any] = {
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
        zone: dict[str, Any] = {
            "name": "example.com.",
            "provider": {"type": "internal", "name": "coredns-common"},
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,
            },
        }

        from abhaile.dns.renderer import render_zone_template

        deployed_services = ["svc-b", "svc-a"]
        records = _collect_zone_records(zone, network, deployed_services)
        zone_content = render_zone_template(
            "coredns-common/config/zones/zone.zone.j2",
            zone,
            records,
            minimal_config_root,
        )
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        _validate_zone_serial(zone, network, deployed_services, config_root=minimal_config_root)
