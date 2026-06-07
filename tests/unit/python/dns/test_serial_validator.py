"""Tests for serial validator edge cases."""

from datetime import datetime as _dt
from pathlib import Path
from typing import Any

import pytest

import abhaile.dns.serial_validator as serial_validator
from abhaile.dns.records import collect_zone_records
from abhaile.dns.serial_validator import compute_content_hash, validate_zone_serial
from abhaile.utils.errors import RenderError


class _FixedDatetime:
    @classmethod
    def now(cls) -> _dt:
        return _dt(2026, 3, 6)


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


def test_hash_mismatch_increments_counter(
    monkeypatch: pytest.MonkeyPatch,
    minimal_config_root: Path,
) -> None:
    """Hash mismatch should require a counter increment based on git HEAD."""
    monkeypatch.setattr(serial_validator, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        serial_validator,
        "_get_git_head_serial",
        lambda _zone_name: {"date": "20260306", "counter": "03", "content_hash": "dead"},
    )

    network: dict[str, Any] = {"hosts": {}, "services": {}}
    zone: dict[str, Any] = {
        "name": "example.com.",
        "provider": {"type": "internal", "name": "coredns-common"},
        "serial": {"date": "20260306", "counter": "00", "content_hash": "bad"},
    }

    expected_zone: dict[str, Any] = {
        "name": "example.com.",
        "provider": {"type": "internal", "name": "coredns-common"},
        "serial": {"date": "20260306", "counter": "04"},
    }
    from abhaile.dns.renderer import render_zone_template

    records = collect_zone_records(expected_zone, network, [])
    expected_content = render_zone_template(
        "coredns-common/config/zones/zone.zone.j2",
        expected_zone,
        records,
        minimal_config_root,
    )
    expected_hash = compute_content_hash(expected_content)

    with pytest.raises(RenderError) as exc_info:
        validate_zone_serial(zone, network, [], config_root=minimal_config_root)

    error_msg = str(exc_info.value)
    assert "content hash mismatch" in error_msg
    assert "serial.counter: 04" in error_msg
    assert f"serial.content_hash: {expected_hash}" in error_msg


def test_hash_match_no_increment(
    monkeypatch: pytest.MonkeyPatch,
    minimal_config_root: Path,
) -> None:
    """Hash match should not attempt a counter increment."""
    monkeypatch.setattr(serial_validator, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        serial_validator,
        "_get_git_head_serial",
        lambda _zone_name: {"date": "20260306", "counter": "99", "content_hash": "dead"},
    )

    network: dict[str, Any] = {"hosts": {}, "services": {}}
    zone: dict[str, Any] = {
        "name": "example.com.",
        "provider": {"type": "internal", "name": "coredns-common"},
        "serial": {"date": "20260306", "counter": "00", "content_hash": ""},
    }

    from abhaile.dns.renderer import render_zone_template

    records = collect_zone_records(zone, network, [])
    zone_content = render_zone_template(
        "coredns-common/config/zones/zone.zone.j2",
        zone,
        records,
        minimal_config_root,
    )
    zone["serial"]["content_hash"] = compute_content_hash(zone_content)

    validate_zone_serial(zone, network, [], config_root=minimal_config_root)


def test_hash_match_uses_renderer_template(tmp_path: Path) -> None:
    """Validation should accept hash derived from the renderer template output."""
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

    (template_dir / "zone.zone.j2").write_text(
        "$ORIGIN {{ zone.name }}\n"
        "$TTL 300\n"
        "@ IN SOA ns1.abhaile.home.arpa. hostmaster.abhaile.home.arpa. ({{ zone.serial }} 7200 3600 1209600 3600)\n"
        "@ IN NS ns1.abhaile.home.arpa.\n",
        encoding="utf-8",
    )

    network: dict[str, Any] = {"hosts": {}, "services": {}}
    zone: dict[str, Any] = {
        "name": "example.com.",
        "provider": {"type": "internal", "name": "coredns-common"},
        "serial": {"date": "20260306", "counter": "00", "content_hash": ""},
    }

    from abhaile.dns.renderer import render_zone_template

    records = collect_zone_records(zone, network, [])
    rendered_content = render_zone_template(
        "coredns-common/config/zones/zone.zone.j2",
        zone,
        records,
        config_root,
    )
    zone["serial"]["content_hash"] = compute_content_hash(rendered_content)

    validate_zone_serial(zone, network, [], config_root=config_root)
