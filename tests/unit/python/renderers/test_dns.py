"""Unit tests for DNS renderer."""

from datetime import datetime
from pathlib import Path

import pytest

from renderers.dns import (
    _collect_zone_records,
    _compute_content_hash,
    _render_zone_template,
    _validate_zone_serial,
    _validate_zone_serial_collect,
    render_dns,
)
from utils.errors import RenderError


def _build_zone_content_for_hash(zone: dict, records: list[dict]) -> str:
    zone_name = zone.get("name", "")
    zone_name_stripped = zone_name.rstrip(".")
    serial_info = zone.get("serial", {})
    serial_str = str(serial_info.get("date", "20260101")).strip() + str(
        serial_info.get("counter", "00")
    ).zfill(2)

    lines = []
    lines.append(f"$ORIGIN {zone_name}")
    lines.append("")
    lines.append(
        f"{zone_name_stripped}. 3600 IN SOA ns1.{zone_name_stripped}. "
        f"hostmaster.{zone_name_stripped}. {serial_str} 3600 1800 604800 86400"
    )
    lines.append(f"{zone_name_stripped}. 3600 IN NS ns1.{zone_name_stripped}.")
    lines.append("")

    for record in records:
        record_name = record.get("name", "").rstrip(".")
        record_type = record.get("type", "").upper()
        rdata = record.get("rdata", "").strip()
        ttl = record.get("ttl", 3600)

        if not record_type or not rdata:
            continue

        lines.append(f"{record_name} {ttl} IN {record_type} {rdata}")

    lines.append("")
    return "\n".join(lines)


class TestComputeContentHash:
    """Tests for _compute_content_hash."""

    def test_consistent_hash(self):
        """Test that same content produces same hash."""
        content = "example.com. 3600 IN SOA ns1.example.com. hostmaster.example.com. 2026020800 3600 1800 604800 86400\n"
        hash1 = _compute_content_hash(content)
        hash2 = _compute_content_hash(content)
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Test that different content produces different hash."""
        content1 = "example.com. 3600 IN SOA ns1.example.com. hostmaster.example.com. 2026020800 3600 1800 604800 86400\n"
        content2 = "example.com. 3600 IN SOA ns1.example.com. hostmaster.example.com. 2026020801 3600 1800 604800 86400\n"
        hash1 = _compute_content_hash(content1)
        hash2 = _compute_content_hash(content2)
        assert hash1 != hash2

    def test_hash_format(self):
        """Test that hash is valid SHA-256 hex."""
        content = "test content"
        hash_val = _compute_content_hash(content)
        assert len(hash_val) == 64  # SHA-256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in hash_val)


class TestRenderZoneTemplate:
    """Tests for _render_zone_template."""

    def _write_template(self, tmp_path, content: str) -> Path:
        config_root = tmp_path / "config"
        template_path = (
            config_root / "services" / "testsvc" / "templates" / "zone.zone.j2"
        )
        template_path.parent.mkdir(parents=True)
        template_path.write_text(content)
        return config_root

    def test_basic_zone_rendering(self, tmp_path):
        """Test basic zone file rendering from template."""
        config_root = self._write_template(
            tmp_path,
            "$ORIGIN {{ zone.name }}\n"
            "SERIAL {{ zone.serial }}\n"
            "{% for rec in zone.records %}"
            "{{ rec.name }} {{ rec.type }} {{ rec.rdata }}\n"
            "{% endfor %}",
        )

        zone = {
            "name": "example.com.",
            "serial": {"date": "20260208", "counter": "00", "content_hash": "abc123"},
        }
        records = [
            {"name": "www", "type": "A", "rdata": "192.0.2.1", "ttl": 3600},
        ]
        content = _render_zone_template(
            "testsvc/templates/zone.zone.j2",
            zone,
            records,
            config_root,
        )

        assert "$ORIGIN example.com." in content
        assert "SERIAL 2026020800" in content
        assert "www A 192.0.2.1" in content

    def test_zone_template_serial_uses_date_counter(self, tmp_path):
        """Test that serial is composed from date + counter."""
        config_root = self._write_template(
            tmp_path,
            "SERIAL {{ zone.serial }}\n",
        )

        zone = {
            "name": "example.com.",
            "serial": {"date": "20260208", "counter": "09", "content_hash": "abc123"},
        }
        content = _render_zone_template(
            "testsvc/templates/zone.zone.j2",
            zone,
            [],
            config_root,
        )

        assert "SERIAL 2026020809" in content


class TestCollectZoneRecords:
    """Tests for _collect_zone_records."""

    def test_collect_host_records_only(self):
        """Test collecting records from hosts only."""
        network = {
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
        zone = {"name": "example.com."}
        records = _collect_zone_records(zone, network, [])

        assert len(records) == 1
        assert records[0]["name"] == "host1"

    def test_collect_service_records_only(self):
        """Test collecting records from services only."""
        network = {
            "hosts": {},
            "services": {
                "service1": {
                    "dns": [
                        {
                            "zone": "svc.example.com.",
                            "records": [
                                {
                                    "name": "service1",
                                    "type": "a",
                                    "rdata": "172.20.20.1",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
        }
        zone = {"name": "svc.example.com."}
        records = _collect_zone_records(zone, network, ["service1"])

        assert len(records) == 1
        assert records[0]["name"] == "service1"

    def test_collect_host_and_service_records(self):
        """Test collecting records from both hosts and services."""
        network = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "svc.example.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "172.20.20.10",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {
                "service1": {
                    "dns": [
                        {
                            "zone": "svc.example.com.",
                            "records": [
                                {
                                    "name": "service1",
                                    "type": "a",
                                    "rdata": "172.20.20.1",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
        }
        zone = {"name": "svc.example.com."}
        records = _collect_zone_records(zone, network, ["service1"])

        assert len(records) == 2
        # Host records come first
        assert records[0]["name"] == "host1"
        assert records[1]["name"] == "service1"

    def test_collect_multiple_records_per_entity(self):
        """Test collecting multiple records from same host."""
        network = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "example.com.",
                            "records": [
                                {
                                    "name": "www",
                                    "type": "a",
                                    "rdata": "192.0.2.1",
                                    "ttl": 3600,
                                },
                                {
                                    "name": "mail",
                                    "type": "a",
                                    "rdata": "192.0.2.2",
                                    "ttl": 3600,
                                },
                            ],
                        }
                    ]
                }
            },
            "services": {},
        }
        zone = {"name": "example.com."}
        records = _collect_zone_records(zone, network, [])

        assert len(records) == 2
        assert records[0]["name"] == "www"
        assert records[1]["name"] == "mail"

    def test_collect_records_multiple_zones(self):
        """Test that only matching zone records are collected."""
        network = {
            "hosts": {
                "host1": {
                    "dns": [
                        {
                            "zone": "zone1.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "192.0.2.1",
                                    "ttl": 3600,
                                },
                            ],
                        },
                        {
                            "zone": "zone2.com.",
                            "records": [
                                {
                                    "name": "host1",
                                    "type": "a",
                                    "rdata": "192.0.2.2",
                                    "ttl": 3600,
                                },
                            ],
                        },
                    ]
                }
            },
            "services": {},
        }
        zone = {"name": "zone1.com."}
        records = _collect_zone_records(zone, network, [])

        assert len(records) == 1
        assert records[0]["rdata"] == "192.0.2.1"


class TestValidateZoneSerial:
    """Tests for _validate_zone_serial."""

    def test_serial_valid_no_content_change(self):
        """Test that validation passes when content hash matches."""
        network = {
            "hosts": {},
            "services": {},
        }
        zone = {
            "name": "example.com.",
            "serial": {
                "date": "20260208",
                "counter": "00",
                "content_hash": None,  # Will be computed
            },
        }

        # First compute what the hash should be
        records = _collect_zone_records(zone, network, [])
        zone_content = _build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        # This should not raise
        _validate_zone_serial(zone, network)

    def test_serial_invalid_content_changed(self):
        """Test that validation fails when content hash mismatches."""
        network = {
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
        zone = {
            "name": "example.com.",
            "serial": {
                "date": today,
                "counter": "00",
                "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            },
        }

        with pytest.raises(RenderError) as exc_info:
            _validate_zone_serial(zone, network)

        error_msg = str(exc_info.value)
        assert "content hash mismatch" in error_msg
        # Should show at least the content_hash field that differs
        assert "serial.content_hash" in error_msg or "serial.counter" in error_msg

    def test_serial_missing_content_hash_fails(self):
        """Test that validation fails if content_hash is missing."""
        network = {
            "hosts": {},
            "services": {},
        }
        zone = {
            "name": "example.com.",
            "serial": {
                "date": "20260208",
                "counter": "00",
            },
        }

        with pytest.raises(RenderError) as exc_info:
            _validate_zone_serial(zone, network)

        error_msg = str(exc_info.value)
        assert "missing content_hash" in error_msg


class TestValidateZoneSerialCollect:
    """Tests for _validate_zone_serial_collect."""

    def test_collect_single_valid_zone(self):
        """Test that valid zones don't generate errors."""
        network = {
            "hosts": {},
            "services": {},
        }
        zone = {
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
        zone_content = _build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        zones = [zone]
        errors = _validate_zone_serial_collect(zones, network)
        assert len(errors) == 0

    def test_collect_multiple_mismatched_zones(self):
        """Test that all mismatched zones are collected."""
        network = {
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

        errors = _validate_zone_serial_collect(zones, network)

        # Should have errors for both zones
        assert len(errors) == 2
        assert "zone1.com." in errors[0]
        assert "zone2.com." in errors[1]
        assert "content hash mismatch" in errors[0]
        assert "content hash mismatch" in errors[1]

    def test_collect_mixed_valid_and_invalid(self):
        """Test collecting from mix of valid and invalid zones."""
        network = {
            "hosts": {},
            "services": {},
        }
        today = datetime.now().strftime("%Y%m%d")

        # Valid zone
        zone1 = {
            "name": "valid.com.",
            "provider": {"type": "internal", "name": "coredns"},
            "serial": {
                "date": today,
                "counter": "00",
                "content_hash": None,
            },
        }
        records = _collect_zone_records(zone1, network, [])
        zone_content = _build_zone_content_for_hash(zone1, records)
        zone1["serial"]["content_hash"] = _compute_content_hash(zone_content)

        # Invalid zone
        zone2 = {
            "name": "invalid.com.",
            "provider": {"type": "internal", "name": "coredns"},
            "serial": {
                "date": today,
                "counter": "00",
                "content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            },
        }

        zones = [zone1, zone2]
        errors = _validate_zone_serial_collect(zones, network)

        # Should have error only for zone2
        assert len(errors) == 1
        assert "invalid.com." in errors[0]

    def test_collect_skips_external_zones(self):
        """Test that external zones are skipped."""
        network = {
            "hosts": {},
            "services": {},
        }
        zones = [
            {
                "name": "example.com.",
                "provider": {"type": "external", "name": "desec.io"},
            }
        ]

        errors = _validate_zone_serial_collect(zones, network)
        assert len(errors) == 0


class TestRenderDns:
    """Tests for render_dns."""

    def test_render_dns_skips_external_providers(self, tmp_path):
        """Test that external DNS providers are skipped."""
        network = {
            "dns": {
                "zones": [
                    {
                        "name": "example.com.",
                        "provider": {"type": "external", "name": "desec.io"},
                    }
                ]
            },
            "hosts": {},
            "services": {},
        }
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(network, output_dir, [], [], Path("/fake/config"))

        # No zone file should be created for external provider
        assert not (output_dir / "services" / "desec.io").exists()

    def test_render_dns_internal_zone(self, tmp_path):
        """Test rendering internal DNS zone to providing service."""
        # Create fake config structure
        config_root = tmp_path / "config"
        services_dir = config_root / "services"

        # Create coredns-common service
        common_dir = services_dir / "coredns-common"
        common_dir.mkdir(parents=True)
        (common_dir / "service.yaml").write_text("""
name: coredns-common
composition:
  dns:
    zone_files:
      - zone: '*'
        file:
          source:
            template: coredns-common/config/zones/zone.zone.j2
            variables: {}
          destination: /etc/coredns/zones/zone.zone
""")

        template_path = common_dir / "config" / "zones" / "zone.zone.j2"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(
            "$ORIGIN {{ zone.name }}\n"
            "SERIAL {{ zone.serial }}\n"
            "{% for rec in zone.records %}"
            "{{ rec.name }} IN {{ rec.type }} {{ rec.rdata }}\n"
            "{% endfor %}"
        )

        # Create coredns-clean service that includes coredns-common
        clean_dir = services_dir / "coredns-clean"
        clean_dir.mkdir(parents=True)
        (clean_dir / "service.yaml").write_text("""
name: coredns-clean
composition:
  include:
    - coredns-common
""")

        network = {
            "dns": {
                "zones": [
                    {
                        "name": "example.com.",
                        "provider": {"type": "internal", "name": "coredns-common"},
                        "serial": {
                            "date": "20260208",
                            "counter": "00",
                            "content_hash": None,
                        },
                    }
                ]
            },
            "hosts": {},
            "services": {},
        }

        # Pre-compute the expected hash
        zone = network["dns"]["zones"][0]
        records = _collect_zone_records(zone, network, ["coredns-clean"])
        zone_content = _build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(
            network, output_dir, ["coredns-clean"], ["coredns-clean"], config_root
        )

        # Zone file should be created in coredns-clean directory (not coredns-common)
        zone_file = (
            output_dir
            / "services"
            / "coredns-clean"
            / "etc/coredns/zones"
            / "example.com.zone"
        )
        assert zone_file.exists()
        content = zone_file.read_text()
        assert "$ORIGIN example.com." in content
        assert "SERIAL 2026020800" in content

    def test_render_dns_multiple_zones(self, tmp_path):
        """Test rendering multiple zones."""
        # Create fake config structure
        config_root = tmp_path / "config"
        services_dir = config_root / "services"

        # Create coredns-common service
        common_dir = services_dir / "coredns-common"
        common_dir.mkdir(parents=True)
        (common_dir / "service.yaml").write_text("""
name: coredns-common
composition:
  dns:
    zone_files:
      - zone: '*'
        file:
          source:
            template: coredns-common/config/zones/zone.zone.j2
            variables: {}
          destination: /etc/coredns/zones/zone.zone
""")

        template_path = common_dir / "config" / "zones" / "zone.zone.j2"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(
            "$ORIGIN {{ zone.name }}\n"
            "SERIAL {{ zone.serial }}\n"
            "{% for rec in zone.records %}"
            "{{ rec.name }} IN {{ rec.type }} {{ rec.rdata }}\n"
            "{% endfor %}"
        )

        # Create coredns-clean service
        clean_dir = services_dir / "coredns-clean"
        clean_dir.mkdir(parents=True)
        (clean_dir / "service.yaml").write_text("""
name: coredns-clean
composition:
  include:
    - coredns-common
""")

        network = {
            "dns": {
                "zones": [
                    {
                        "name": "zone1.com.",
                        "provider": {"type": "internal", "name": "coredns-common"},
                        "serial": {
                            "date": "20260208",
                            "counter": "00",
                            "content_hash": None,
                        },
                    },
                    {
                        "name": "zone2.com.",
                        "provider": {"type": "internal", "name": "coredns-common"},
                        "serial": {
                            "date": "20260208",
                            "counter": "00",
                            "content_hash": None,
                        },
                    },
                ]
            },
            "hosts": {},
            "services": {},
        }

        # Pre-compute hashes for both zones
        for zone in network["dns"]["zones"]:
            records = _collect_zone_records(zone, network, ["coredns-clean"])
            zone_content = _build_zone_content_for_hash(zone, records)
            zone["serial"]["content_hash"] = _compute_content_hash(zone_content)

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(
            network, output_dir, ["coredns-clean"], ["coredns-clean"], config_root
        )

        # Both zone files should be created in coredns-clean directory
        zone1_file = (
            output_dir
            / "services"
            / "coredns-clean"
            / "etc/coredns/zones"
            / "zone1.com.zone"
        )
        zone2_file = (
            output_dir
            / "services"
            / "coredns-clean"
            / "etc/coredns/zones"
            / "zone2.com.zone"
        )
        assert zone1_file.exists()
        assert zone2_file.exists()

    def test_render_dns_no_dns_config(self, tmp_path):
        """Test that render handles missing DNS config gracefully."""
        network = {"hosts": {}, "services": {}}
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        # Should not raise
        render_dns(network, output_dir, [], [], Path("/fake/config"))
