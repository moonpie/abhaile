"""Tests for serial validator edge cases."""

from datetime import datetime as _dt
from typing import Any, Dict

import pytest

import abhaile.dns.serial_validator as serial_validator
from abhaile.dns.records import collect_zone_records
from abhaile.dns.serial_validator import compute_content_hash, validate_zone_serial
from abhaile.utils.errors import RenderError
from tests.unit.python.renderers.dns_helpers import build_zone_content_for_hash


class _FixedDatetime:
    @classmethod
    def now(cls) -> _dt:
        return _dt(2026, 3, 6)


def test_hash_mismatch_increments_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash mismatch should require a counter increment based on git HEAD."""
    monkeypatch.setattr(serial_validator, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        serial_validator,
        "_get_git_head_serial",
        lambda _zone_name: {"date": "20260306", "counter": "03", "content_hash": "dead"},
    )

    network: Dict[str, Any] = {"hosts": {}, "services": {}}
    zone: Dict[str, Any] = {
        "name": "example.com.",
        "serial": {"date": "20260306", "counter": "00", "content_hash": "bad"},
    }

    expected_zone: Dict[str, Any] = {
        "name": "example.com.",
        "serial": {"date": "20260306", "counter": "04"},
    }
    records = collect_zone_records(expected_zone, network, [])
    expected_content = build_zone_content_for_hash(expected_zone, records)
    expected_hash = compute_content_hash(expected_content)

    with pytest.raises(RenderError) as exc_info:
        validate_zone_serial(zone, network, [])

    error_msg = str(exc_info.value)
    assert "content hash mismatch" in error_msg
    assert "serial.counter: 04" in error_msg
    assert f"serial.content_hash: {expected_hash}" in error_msg


def test_hash_match_no_increment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash match should not attempt a counter increment."""
    monkeypatch.setattr(serial_validator, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        serial_validator,
        "_get_git_head_serial",
        lambda _zone_name: {"date": "20260306", "counter": "99", "content_hash": "dead"},
    )

    network: Dict[str, Any] = {"hosts": {}, "services": {}}
    zone: Dict[str, Any] = {
        "name": "example.com.",
        "serial": {"date": "20260306", "counter": "00", "content_hash": ""},
    }

    records = collect_zone_records(zone, network, [])
    zone_content = build_zone_content_for_hash(zone, records)
    zone["serial"]["content_hash"] = compute_content_hash(zone_content)

    validate_zone_serial(zone, network, [])
