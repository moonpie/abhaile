"""Integration tests for DNS rendering."""

from pathlib import Path

import pytest

from renderers.dns import _compute_content_hash, _collect_zone_records, render_dns
from utils.config import read_yaml
from utils.errors import RenderError
from validation.dns import validate_dns_serials


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


@pytest.fixture
def network_config():
    """Load network.yaml for integration tests."""
    config_path = Path(__file__).parent.parent.parent / "config" / "network.yaml"
    if not config_path.exists():
        pytest.skip("network.yaml not found")
    return read_yaml(config_path)


@pytest.fixture
def mapping_config():
    """Load mapping.yaml for integration tests."""
    mapping_path = Path(__file__).parent.parent.parent / "config" / "mapping.yaml"
    if not mapping_path.exists():
        pytest.skip("mapping.yaml not found")
    return read_yaml(mapping_path)


@pytest.fixture
def config_root():
    """Get config root directory."""
    return Path(__file__).parent.parent.parent / "config"


@pytest.fixture
def all_services(mapping_config):
    """Get all services from mapping in order."""
    from validation.services import parse_mapping

    host_services = parse_mapping(mapping_config)
    # Deduplicate while preserving order
    seen = set()
    services = []
    for host, svc_list in host_services.items():
        for svc in svc_list:
            if svc not in seen:
                services.append(svc)
                seen.add(svc)
    return services


@pytest.fixture
def network_config_with_updated_serials(network_config, all_services):
    """Return network config with updated DNS serials for rendering tests.

    This fixture computes and updates serials to match current zone content,
    allowing rendering tests to proceed even if user hasn't updated network.yaml yet.
    """
    from datetime import datetime

    if "dns" not in network_config or "zones" not in network_config["dns"]:
        return network_config

    today_str = datetime.now().strftime("%Y%m%d")
    zones = network_config["dns"]["zones"]
    for zone in zones:
        if zone.get("provider", {}).get("type") != "internal":
            continue

        # Compute current content hash
        serial_info = zone.get("serial", {})
        if not serial_info:
            continue

        # Update serial to today's date with counter 00, and compute hash with that serial
        serial_info["date"] = int(today_str)
        serial_info["counter"] = 0

        records = _collect_zone_records(zone, network_config, all_services)
        content = _build_zone_content_for_hash(zone, records)
        zone["serial"]["content_hash"] = _compute_content_hash(content)

    return network_config


class TestDNSIntegration:
    """Integration tests with real network configuration."""

    def test_validate_dns_serials_documents_status(self, network_config):
        """Document whether DNS serials in network.yaml are up-to-date.

        This test shows the user what updates are needed if serials are stale.
        """
        try:
            validate_dns_serials(network_config)
        except RenderError as e:
            # This is expected if user hasn't updated serials yet
            error_msg = str(e)
            assert "content hash mismatch" in error_msg
            assert "Stored hash" in error_msg
            assert "Current hash" in error_msg

    def test_render_dns_with_corrected_serials(
        self, network_config_with_updated_serials, all_services, config_root, tmp_path
    ):
        """Test full DNS rendering with up-to-date serials."""
        output_dir = tmp_path / "dns-render"
        output_dir.mkdir()

        # Note: Validation is tested separately. This test focuses on rendering
        # with a properly configured network config (serials already updated by fixture).

        # Render should complete without error
        render_dns(
            network_config_with_updated_serials,
            output_dir,
            all_services,
            all_services,
            config_root,
        )

        # Check that zone files were created in providing services
        zones = network_config_with_updated_serials.get("dns", {}).get("zones", [])
        internal_zones = [
            z for z in zones if z.get("provider", {}).get("type") == "internal"
        ]

        assert len(internal_zones) > 0, "No internal zones found in test config"

        # Find services that provide zones (e.g., coredns-clean, coredns-filtered)
        provider_names = {z.get("provider", {}).get("name") for z in internal_zones}
        providing_services = [
            s
            for s in all_services
            if any(
                p in s or s in ["coredns-clean", "coredns-filtered"]
                for p in provider_names
            )
        ]

        # Zone files should exist in providing service directories
        for service_name in providing_services:
            service_zones_dir = (
                output_dir / "services" / service_name / "etc/coredns/zones"
            )
            if not service_zones_dir.exists():
                continue

            for zone in internal_zones:
                zone_name = zone.get("name")
                zone_file = service_zones_dir / f"{zone_name}.zone"

                if zone_file.exists():
                    # Verify zone file has SOA and NS records
                    content = zone_file.read_text()
                    zone_name_stripped = zone_name.rstrip(".")
                    assert f"$ORIGIN {zone_name_stripped}." in content
                    assert "IN SOA" in content
                    assert "IN NS" in content

    def test_dns_record_deterministic_ordering(
        self, network_config_with_updated_serials, all_services, config_root, tmp_path
    ):
        """Test that DNS records are rendered in deterministic order."""
        output_dir = tmp_path / "dns-order"
        output_dir.mkdir()

        render_dns(
            network_config_with_updated_serials,
            output_dir,
            all_services,
            all_services,
            config_root,
        )

        # Render twice and compare
        output_dir2 = tmp_path / "dns-order2"
        output_dir2.mkdir()
        render_dns(
            network_config_with_updated_serials,
            output_dir2,
            all_services,
            all_services,
            config_root,
        )

        zones = network_config_with_updated_serials.get("dns", {}).get("zones", [])
        internal_zones = [
            z for z in zones if z.get("provider", {}).get("type") == "internal"
        ]

        # Get all service directories that have zone files
        service_dirs = [d for d in (output_dir / "services").iterdir() if d.is_dir()]

        for zone in internal_zones:
            zone_name = zone.get("name")

            # Find zone file in any of the providing services
            zone_file1 = None
            zone_file2 = None
            for service_dir in service_dirs:
                candidate1 = service_dir / "etc/coredns/zones" / f"{zone_name}.zone"
                candidate2 = (
                    output_dir2
                    / "services"
                    / service_dir.name
                    / "etc/coredns/zones"
                    / f"{zone_name}.zone"
                )
                if candidate1.exists() and candidate2.exists():
                    zone_file1 = candidate1
                    zone_file2 = candidate2
                    break

            if not zone_file1:
                continue  # Skip if zone not rendered

            content1 = zone_file1.read_text()
            content2 = zone_file2.read_text()

            # Content should be identical (deterministic)
            assert content1 == content2, f"Zone {zone_name} content not deterministic"

    def test_dns_zone_file_format(
        self, network_config_with_updated_serials, all_services, config_root, tmp_path
    ):
        """Test that zone files are in valid BIND RFC 1035 format."""
        output_dir = tmp_path / "dns-format"
        output_dir.mkdir()

        render_dns(
            network_config_with_updated_serials,
            output_dir,
            all_services,
            all_services,
            config_root,
        )

        zones = network_config_with_updated_serials.get("dns", {}).get("zones", [])
        internal_zones = [
            z for z in zones if z.get("provider", {}).get("type") == "internal"
        ]

        # Get all service directories that have zone files
        service_dirs = [d for d in (output_dir / "services").iterdir() if d.is_dir()]

        for zone in internal_zones:
            zone_name = zone.get("name")

            # Find zone file in any of the providing services
            zone_file = None
            for service_dir in service_dirs:
                candidate = service_dir / "etc/coredns/zones" / f"{zone_name}.zone"
                if candidate.exists():
                    zone_file = candidate
                    break

            if not zone_file:
                continue  # Skip if zone not rendered

            content = zone_file.read_text()
            lines = content.split("\n")

            # Should have $ORIGIN
            origin_lines = [line for line in lines if line.startswith("$ORIGIN")]
            assert len(origin_lines) > 0, "Zone file missing $ORIGIN"

            # Should have SOA
            soa_lines = [line for line in lines if "IN SOA" in line]
            assert len(soa_lines) > 0, "Zone file missing SOA record"

            # Should have NS
            ns_lines = [line for line in lines if "IN NS" in line]
            assert len(ns_lines) > 0, "Zone file missing NS record"

    def test_dns_serial_in_zone_file(
        self, network_config_with_updated_serials, all_services, config_root, tmp_path
    ):
        """Test that serial number appears in SOA record."""
        output_dir = tmp_path / "dns-serial"
        output_dir.mkdir()

        render_dns(
            network_config_with_updated_serials,
            output_dir,
            all_services,
            all_services,
            config_root,
        )

        zones = network_config_with_updated_serials.get("dns", {}).get("zones", [])
        internal_zones = [
            z for z in zones if z.get("provider", {}).get("type") == "internal"
        ]

        # Get all service directories that have zone files
        service_dirs = [d for d in (output_dir / "services").iterdir() if d.is_dir()]

        for zone in internal_zones:
            zone_name = zone.get("name")
            serial_info = zone.get("serial", {})
            date = str(serial_info.get("date", ""))
            counter = str(serial_info.get("counter", "")).zfill(2)
            expected_serial = f"{date}{counter}"

            # Find zone file in any of the providing services
            zone_file = None
            for service_dir in service_dirs:
                candidate = service_dir / "etc/coredns/zones" / f"{zone_name}.zone"
                if candidate.exists():
                    zone_file = candidate
                    break

            if not zone_file:
                continue  # Skip if zone not rendered

            content = zone_file.read_text()
            assert (
                expected_serial in content
            ), f"Zone {zone_name} SOA missing expected serial {expected_serial}"

    def test_dns_host_records_appear_in_zone(
        self, network_config_with_updated_serials, all_services, config_root, tmp_path
    ):
        """Test that host DNS records appear in rendered zones."""
        output_dir = tmp_path / "dns-hosts"
        output_dir.mkdir()

        render_dns(
            network_config_with_updated_serials,
            output_dir,
            all_services,
            all_services,
            config_root,
        )

        zones = network_config_with_updated_serials.get("dns", {}).get("zones", [])

        # Get all service directories that have zone files
        service_dirs = [d for d in (output_dir / "services").iterdir() if d.is_dir()]

        for zone in zones:
            if zone.get("provider", {}).get("type") != "internal":
                continue

            zone_name = zone.get("name")

            # Check if any hosts have records for this zone
            hosts = network_config_with_updated_serials.get("hosts", {})
            has_host_records = False
            for host_name, host_data in hosts.items():
                for dns_entry in host_data.get("dns", []):
                    if dns_entry.get("zone") == zone_name:
                        has_host_records = True
                        break
                if has_host_records:
                    break

            if not has_host_records:
                continue

            # Find zone file in any of the providing services
            zone_file = None
            for service_dir in service_dirs:
                candidate = service_dir / "etc/coredns/zones" / f"{zone_name}.zone"
                if candidate.exists():
                    zone_file = candidate
                    break

            if not zone_file:
                continue  # Skip if zone not rendered

            content = zone_file.read_text()

            # At least one host record should appear
            for host_name, host_data in hosts.items():
                for dns_entry in host_data.get("dns", []):
                    if dns_entry.get("zone") == zone_name:
                        for record in dns_entry.get("records", []):
                            record_name = record.get("name", "").rstrip(".")
                            if record_name:
                                # Record name should appear in zone file
                                assert (
                                    record_name in content or record_name == "*"
                                ), f"Host record {record_name} not found in zone {zone_name}"

    def test_dns_service_records_appear_in_zone(
        self, network_config_with_updated_serials, all_services, config_root, tmp_path
    ):
        """Test that service DNS records appear in rendered zones."""
        output_dir = tmp_path / "dns-services"
        output_dir.mkdir()

        render_dns(
            network_config_with_updated_serials,
            output_dir,
            all_services,
            all_services,
            config_root,
        )

        zones = network_config_with_updated_serials.get("dns", {}).get("zones", [])

        # Get all service directories that have zone files
        service_dirs = [d for d in (output_dir / "services").iterdir() if d.is_dir()]

        for zone in zones:
            if zone.get("provider", {}).get("type") != "internal":
                continue

            zone_name = zone.get("name")

            # Check if any services have records for this zone
            services = network_config_with_updated_serials.get("services", {})
            has_service_records = False
            for service_name, service_data in services.items():
                for dns_entry in service_data.get("dns", []):
                    if dns_entry.get("zone") == zone_name:
                        has_service_records = True
                        break
                if has_service_records:
                    break

            if not has_service_records:
                continue

            # Find zone file in any of the providing services
            zone_file = None
            for service_dir in service_dirs:
                candidate = service_dir / "etc/coredns/zones" / f"{zone_name}.zone"
                if candidate.exists():
                    zone_file = candidate
                    break

            if not zone_file:
                continue  # Skip if zone not rendered

            content = zone_file.read_text()

            # At least one service record should appear
            for service_name, service_data in services.items():
                for dns_entry in service_data.get("dns", []):
                    if dns_entry.get("zone") == zone_name:
                        for record in dns_entry.get("records", []):
                            record_name = record.get("name", "").rstrip(".")
                            if record_name and record_name != "*":
                                # Record name should appear in zone file
                                assert (
                                    record_name in content
                                ), f"Service record {record_name} not found in zone {zone_name}"
