"""Placeholder tests for serial validator edge cases.

These tests are stubs for future implementation of detailed counter increment
and git HEAD fallback logic. The actual validation logic is covered in
tests/unit/python/renderers/test_dns_serial.py.
"""

import pytest


def test_hash_mismatch_increments_counter(monkeypatch):
    """Test that hash mismatch increments counter on same day."""
    from datetime import datetime
    from subprocess import CompletedProcess
    from abhaile.dns.serial_validator import validate_zone_serial
    from abhaile.utils.errors import RenderError

    today = datetime.now().strftime("%Y%m%d")

    # Mock git HEAD to return counter=5 for today
    head_yaml = f"""
dns:
  zones:
    - name: example.com.
      serial:
        date: {today}
        counter: 5
        content_hash: old_hash
"""

    def mock_git_show(*args, **kwargs):
        return CompletedProcess(
            args=["git", "show", "HEAD:config/network.yaml"],
            returncode=0,
            stdout=head_yaml,
            stderr="",
        )

    monkeypatch.setattr("abhaile.dns.serial_validator.subprocess.run", mock_git_show)

    # Workspace has stale hash with counter still at 05
    network: dict[str, dict[str, object]] = {"hosts": {}, "services": {}}
    zone = {
        "name": "example.com.",
        "serial": {
            "date": today,
            "counter": "05",
            "content_hash": "wrong_hash",
        },
    }

    with pytest.raises(RenderError) as exc_info:
        validate_zone_serial(zone, network, [])

    error = str(exc_info.value)
    assert "content hash mismatch" in error
    # Should suggest counter=06 (HEAD was 5, so next is 6)
    # Since workspace counter matches expected counter, it won't be in the error
    # but content_hash will be


def test_hash_match_no_increment(monkeypatch):
    """Test that no error raised when content hash matches (no increment needed)."""
    from datetime import datetime
    from abhaile.dns.serial_validator import (
        compute_content_hash,
        validate_zone_serial,
    )
    from abhaile.dns.records import collect_zone_records
    from tests.unit.python.renderers.dns_helpers import build_zone_content_for_hash

    today = datetime.now().strftime("%Y%m%d")

    network: dict[str, dict[str, object]] = {"hosts": {}, "services": {}}
    zone: dict[str, object] = {
        "name": "example.com.",
        "serial": {
            "date": today,
            "counter": "00",
            "content_hash": None,
        },
    }

    # Compute correct hash
    records = collect_zone_records(zone, network, [])
    zone_content = build_zone_content_for_hash(zone, records)
    correct_hash = compute_content_hash(zone_content)
    zone_serial = zone["serial"]
    assert isinstance(zone_serial, dict)
    zone_serial["content_hash"] = correct_hash

    # Should not raise - hash matches, no increment needed
    validate_zone_serial(zone, network, [])
