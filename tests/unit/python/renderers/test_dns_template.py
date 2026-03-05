"""Unit tests for DNS zone template rendering."""

from pathlib import Path
from typing import Any, Dict, List

from abhaile.dns.renderer import render_zone_template as _render_zone_template


class TestRenderZoneTemplate:
    """Tests for _render_zone_template."""

    def _write_template(self, tmp_path: Path, write_file: Any, content: str) -> Path:
        config_root = tmp_path / "config"
        template_path = config_root / "services" / "testsvc" / "templates" / "zone.zone.j2"
        write_file(template_path, content)
        return config_root

    def test_basic_zone_rendering(self, tmp_path: Path, write_file: Any) -> None:
        """Test basic zone file rendering from template."""
        config_root = self._write_template(
            tmp_path,
            write_file,
            "$ORIGIN {{ zone.name }}\n"
            "SERIAL {{ zone.serial }}\n"
            "{% for rec in zone.records %}"
            "{{ rec.name }} {{ rec.type }} {{ rec.rdata }}\n"
            "{% endfor %}",
        )

        zone: Dict[str, Any] = {
            "name": "example.com.",
            "serial": {"date": "20260208", "counter": "00", "content_hash": "abc123"},
        }
        records: List[Dict[str, Any]] = [
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

    def test_zone_template_serial_uses_date_counter(self, tmp_path: Path, write_file: Any) -> None:
        """Test that serial is composed from date + counter."""
        config_root = self._write_template(
            tmp_path,
            write_file,
            "SERIAL {{ zone.serial }}\n",
        )

        zone: Dict[str, Any] = {
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
