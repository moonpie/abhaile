"""Unit tests for DNS rendering."""

from pathlib import Path
from typing import Any

from abhaile.dns.renderer import render_dns
from abhaile.dns.records import collect_zone_records as _collect_zone_records
from abhaile.dns.serial_validator import compute_content_hash as _compute_content_hash
from abhaile.renderers.collector import ArtifactCollector
from tests.unit.python.renderers.dns_helpers import build_zone_content_for_hash


class TestRenderDns:
    """Tests for render_dns."""

    def test_render_dns_skips_external_providers(self, tmp_path: Path) -> None:
        """Test that external DNS providers are skipped."""
        network: dict[str, Any] = {
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

    def test_render_dns_internal_zone(self, tmp_path: Path, write_file: Any) -> None:
        """Test rendering internal DNS zone to providing service."""
        # Create fake config structure
        config_root = tmp_path / "config"
        services_dir = config_root / "services"

        # Create coredns-common service
        common_dir = services_dir / "coredns-common"
        common_dir.mkdir(parents=True)
        write_file(
            common_dir / "service.yaml",
            """
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
""",
        )

        template_path = common_dir / "config" / "zones" / "zone.zone.j2"
        write_file(
            template_path,
            "$ORIGIN {{ zone.name }}\n"
            "SERIAL {{ zone.serial }}\n"
            "{% for rec in zone.records %}"
            "{{ rec.name }} IN {{ rec.type }} {{ rec.rdata }}\n"
            "{% endfor %}",
        )

        # Create coredns-clean service that includes coredns-common
        clean_dir = services_dir / "coredns-clean"
        clean_dir.mkdir(parents=True)
        write_file(
            clean_dir / "service.yaml",
            """
name: coredns-clean
composition:
  include:
    - coredns-common
""",
        )

        network: dict[str, Any] = {
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
        zone: dict[str, Any] = network["dns"]["zones"][0]
        records = _collect_zone_records(zone, network, ["coredns-clean"])
        zone_content = build_zone_content_for_hash(zone, records)
        expected_hash = _compute_content_hash(zone_content)
        zone["serial"]["content_hash"] = expected_hash

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(network, output_dir, ["coredns-clean"], ["coredns-clean"], config_root)

        # Zone file should be created in coredns-clean directory (not coredns-common)
        zone_file = (
            output_dir / "services" / "coredns-clean" / "etc/coredns/zones" / "example.com.zone"
        )
        assert zone_file.exists()
        content = zone_file.read_text()
        assert "$ORIGIN example.com." in content
        assert "SERIAL 2026020800" in content

    def test_render_dns_multiple_zones(self, tmp_path: Path, write_file: Any) -> None:
        """Test rendering multiple zones."""
        # Create fake config structure
        config_root = tmp_path / "config"
        services_dir = config_root / "services"

        # Create coredns-common service
        common_dir = services_dir / "coredns-common"
        common_dir.mkdir(parents=True)
        write_file(
            common_dir / "service.yaml",
            """
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
""",
        )

        template_path = common_dir / "config" / "zones" / "zone.zone.j2"
        write_file(
            template_path,
            "$ORIGIN {{ zone.name }}\n"
            "SERIAL {{ zone.serial }}\n"
            "{% for rec in zone.records %}"
            "{{ rec.name }} IN {{ rec.type }} {{ rec.rdata }}\n"
            "{% endfor %}",
        )

        # Create coredns-clean service
        clean_dir = services_dir / "coredns-clean"
        clean_dir.mkdir(parents=True)
        write_file(
            clean_dir / "service.yaml",
            """
name: coredns-clean
composition:
  include:
    - coredns-common
""",
        )

        network: dict[str, Any] = {
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
            zone_content = build_zone_content_for_hash(zone, records)
            zone["serial"]["content_hash"] = _compute_content_hash(zone_content)

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(network, output_dir, ["coredns-clean"], ["coredns-clean"], config_root)

        # Both zone files should be created in coredns-clean directory
        zone1_file = (
            output_dir / "services" / "coredns-clean" / "etc/coredns/zones" / "zone1.com.zone"
        )
        zone2_file = (
            output_dir / "services" / "coredns-clean" / "etc/coredns/zones" / "zone2.com.zone"
        )
        assert zone1_file.exists()
        assert zone2_file.exists()

    def test_render_dns_no_dns_config(self, tmp_path: Path) -> None:
        """Test that render handles missing DNS config gracefully."""
        network: dict[str, Any] = {"hosts": {}, "services": {}}
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        # Should not raise
        render_dns(network, output_dir, [], [], Path("/fake/config"))

    def test_render_dns_provider_is_service_itself(self, tmp_path: Path, write_file: Any) -> None:
        """Test provider resolution when provider is the service itself."""
        config_root = tmp_path / "config"
        services_dir = config_root / "services"

        provider_dir = services_dir / "coredns-self"
        provider_dir.mkdir(parents=True)
        write_file(
            provider_dir / "service.yaml",
            """
name: coredns-self
composition:
  dns:
    zone_files:
      - zone: '*'
        file:
          source:
            template: coredns-self/config/zones/zone.zone.j2
            variables: {}
          destination: /etc/coredns/zones/zone.zone
""",
        )

        template_path = provider_dir / "config" / "zones" / "zone.zone.j2"
        write_file(
            template_path,
            "$ORIGIN {{ zone.name }}\n" "SERIAL {{ zone.serial }}\n",
        )

        network: dict[str, Any] = {
            "dns": {
                "zones": [
                    {
                        "name": "example.com.",
                        "provider": {"type": "internal", "name": "coredns-self"},
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

        zone: dict[str, Any] = network["dns"]["zones"][0]
        records = _collect_zone_records(zone, network, ["coredns-self"])
        zone_content = build_zone_content_for_hash(zone, records)
        zone["serial"]["content_hash"] = _compute_content_hash(zone_content)

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(
            network,
            output_dir,
            ["coredns-self"],
            ["coredns-self"],
            config_root,
        )

        zone_file = (
            output_dir / "services" / "coredns-self" / "etc/coredns/zones" / "example.com.zone"
        )
        assert zone_file.exists()

    def test_render_dns_transitive_provider_include(self, tmp_path: Path, write_file: Any) -> None:
        """Test provider resolution through transitive includes."""
        config_root = tmp_path / "config"
        services_dir = config_root / "services"

        base_dir = services_dir / "coredns-base"
        base_dir.mkdir(parents=True)
        write_file(
            base_dir / "service.yaml",
            """
name: coredns-base
composition:
  dns:
    zone_files:
      - zone: '*'
        file:
          source:
            template: coredns-base/config/zones/zone.zone.j2
            variables: {}
          destination: /etc/coredns/zones/zone.zone
""",
        )

        template_path = base_dir / "config" / "zones" / "zone.zone.j2"
        write_file(
            template_path,
            "$ORIGIN {{ zone.name }}\n" "SERIAL {{ zone.serial }}\n",
        )

        mid_dir = services_dir / "coredns-mid"
        mid_dir.mkdir(parents=True)
        write_file(
            mid_dir / "service.yaml",
            """
name: coredns-mid
composition:
  include:
    - coredns-base
""",
        )

        top_dir = services_dir / "coredns-top"
        top_dir.mkdir(parents=True)
        write_file(
            top_dir / "service.yaml",
            """
name: coredns-top
composition:
  include:
    - coredns-mid
""",
        )

        network: dict[str, Any] = {
            "dns": {
                "zones": [
                    {
                        "name": "example.com.",
                        "provider": {"type": "internal", "name": "coredns-base"},
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

        zone: dict[str, Any] = network["dns"]["zones"][0]
        records = _collect_zone_records(zone, network, ["coredns-top"])
        zone_content = build_zone_content_for_hash(zone, records)
        zone["serial"]["content_hash"] = _compute_content_hash(zone_content)

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        render_dns(
            network,
            output_dir,
            ["coredns-top"],
            ["coredns-top"],
            config_root,
        )

        zone_file = (
            output_dir / "services" / "coredns-top" / "etc/coredns/zones" / "example.com.zone"
        )
        assert zone_file.exists()

    def test_registers_coredns_zone_metadata(self, tmp_path: Path, write_file: Any) -> None:
        """DNS renderer registers coredns.zone artifacts and owner dependencies."""
        config_root = tmp_path / "config"
        services_dir = config_root / "services"
        rendered_root = tmp_path / "out"
        collector = ArtifactCollector()

        provider_dir = services_dir / "coredns-common"
        provider_dir.mkdir(parents=True)
        write_file(
            provider_dir / "service.yaml",
            """
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
""",
        )
        write_file(
            provider_dir / "config" / "zones" / "zone.zone.j2",
            "$ORIGIN {{ zone.name }}\nSERIAL {{ zone.serial }}\n",
        )

        renderer_service = services_dir / "coredns"
        renderer_service.mkdir(parents=True)
        write_file(
            renderer_service / "service.yaml",
            """
name: coredns
composition:
  include:
    - coredns-common
""",
        )

        network: dict[str, Any] = {
            "dns": {
                "zones": [
                    {
                        "name": "abhaile.home.arpa.",
                        "provider": {"type": "internal", "name": "coredns-common"},
                        "serial": {
                            "date": "20260325",
                            "counter": "00",
                            "content_hash": None,
                        },
                    }
                ]
            },
            "hosts": {},
            "services": {},
        }

        zone = network["dns"]["zones"][0]
        records = _collect_zone_records(zone, network, ["coredns"])
        zone["serial"]["content_hash"] = _compute_content_hash(
            build_zone_content_for_hash(zone, records)
        )

        render_dns(
            network,
            rendered_root,
            ["coredns"],
            ["coredns"],
            config_root,
            collector=collector,
            rendered_root=rendered_root,
        )

        zone_artifacts = collector.get_artifacts_by_owner("dns-zone:abhaile.home.arpa")
        assert len(zone_artifacts) == 1
        assert zone_artifacts[0].kind == "coredns.zone"
        assert zone_artifacts[0].target_path == "/etc/coredns/zones/abhaile.home.arpa.zone"

        owners = collector.get_all_owners()
        assert owners["dns-zone:abhaile.home.arpa"].requires == ["dns:coredns"]
