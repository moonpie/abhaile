"""Tests for commit-based DNS serial management."""

import tempfile
from pathlib import Path

import yaml

from tools.render.dns.dns_serial import (
    calculate_record_hash,
    calculate_serial,
    get_committed_network_config,
    validate_serial_metadata,
)


class TestRecordHash:
    """Tests for deterministic record hashing."""

    def test_hash_is_deterministic(self):
        """Same records should always produce same hash."""
        records = [
            {"type": "A", "name": "caddy", "rdata": "172.20.20.200", "ptr": True},
            {"type": "A", "name": "vault", "rdata": "172.20.20.204", "ptr": True},
        ]
        hash1 = calculate_record_hash(records)
        hash2 = calculate_record_hash(records)
        assert hash1 == hash2

    def test_hash_order_independent(self):
        """Different record orders should produce same hash (records are sorted)."""
        records1 = [
            {"type": "A", "name": "vault", "rdata": "172.20.20.204", "ptr": True},
            {"type": "A", "name": "caddy", "rdata": "172.20.20.200", "ptr": True},
        ]
        records2 = [
            {"type": "A", "name": "caddy", "rdata": "172.20.20.200", "ptr": True},
            {"type": "A", "name": "vault", "rdata": "172.20.20.204", "ptr": True},
        ]
        assert calculate_record_hash(records1) == calculate_record_hash(records2)

    def test_hash_changes_on_record_change(self):
        """Different records should produce different hashes."""
        records1 = [
            {"type": "A", "name": "caddy", "rdata": "172.20.20.200", "ptr": True},
        ]
        records2 = [
            {"type": "A", "name": "caddy", "rdata": "172.20.20.201", "ptr": True},
        ]
        assert calculate_record_hash(records1) != calculate_record_hash(records2)

    def test_hash_format_is_hex(self):
        """Hash should be hex string of reasonable length."""
        records = [
            {"type": "A", "name": "test", "rdata": "1.2.3.4", "ptr": False},
        ]
        hash_val = calculate_record_hash(records)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA256 hex
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_empty_records_hash(self):
        """Empty records list should produce consistent hash."""
        hash1 = calculate_record_hash([])
        hash2 = calculate_record_hash([])
        assert hash1 == hash2


class TestCalculateSerial:
    """Tests for serial calculation logic."""

    def test_new_zone_starts_at_00(self):
        """New zone (no committed serial) should start with counter 00."""
        records = [{"type": "A", "name": "test", "rdata": "1.2.3.4", "ptr": False}]
        serial, hash_val, needs_update = calculate_serial("test.zone", records, None)
        assert serial.endswith("00")
        assert len(serial) == 10  # YYYYMMDDXX format
        assert needs_update is False  # No change on first render
        assert needs_update is False  # New zones don't need updating yet

    def test_unchanged_content_reuses_serial(self, dns_test_dates):
        """If content hash matches, serial should be reused."""
        records = [{"type": "A", "name": "test", "rdata": "1.2.3.4", "ptr": False}]
        hash_val = calculate_record_hash(records)
        committed = {
            "date": dns_test_dates.TODAY,
            "counter": 3,
            "content_hash": hash_val,
        }

        serial, new_hash, needs_update = calculate_serial(
            "test.zone", records, committed, today=dns_test_dates.TODAY
        )
        # Same hash → reuse serial (format: YYYYMMDDXX where XX is zero-padded counter)
        assert serial == f"{dns_test_dates.TODAY}03"  # YYYYMMDD + 03
        assert new_hash == hash_val
        assert needs_update is False  # No update needed when content unchanged
        assert needs_update is False  # No change, no update needed

    def test_changed_content_increments_counter_same_day(self, dns_test_dates):
        """If content hash differs on same day, counter should increment."""
        old_records = [{"type": "A", "name": "test", "rdata": "1.2.3.4", "ptr": False}]
        new_records = [{"type": "A", "name": "test", "rdata": "1.2.3.5", "ptr": False}]

        old_hash = calculate_record_hash(old_records)
        committed = {
            "date": dns_test_dates.TODAY,
            "counter": 3,
            "content_hash": old_hash,
        }

        serial, new_hash, needs_update = calculate_serial(
            "test.zone", new_records, committed, today=dns_test_dates.TODAY
        )
        # Different hash + same day → increment counter
        assert (
            serial == f"{dns_test_dates.TODAY}04"
        )  # YYYYMMDD + 04 (incremented from 03)
        assert new_hash != old_hash
        assert needs_update is True  # Update needed when content changed
        assert needs_update is True  # Content changed, update required

    def test_counter_increments_up_to_99(self, dns_test_dates):
        """Counter should cap at 99."""
        records = [{"type": "A", "name": "test", "rdata": "1.2.3.4", "ptr": False}]
        committed = {
            "date": dns_test_dates.TODAY,
            "counter": 99,
            "content_hash": "different_hash",
        }

        serial, _, needs_update = calculate_serial(
            "test.zone", records, committed, today=dns_test_dates.TODAY
        )
        assert serial == f"{dns_test_dates.TODAY}99"  # Stays at 99
        assert needs_update is True  # Content changed (different hash)
        assert needs_update is True  # Content changed


class TestValidateSerialMetadata:
    """Tests for serial metadata validation."""

    def test_valid_metadata_no_errors(self, dns_test_dates):
        """Valid zones should pass validation."""
        network = {
            "dns": {
                "zones": [
                    {
                        "name": "test.zone",
                        "provider": "coredns-common",
                        "serial": {
                            "date": dns_test_dates.SERIAL_META,
                            "counter": 0,
                            "content_hash": "abc123",
                        },
                    }
                ]
            }
        }
        errors = validate_serial_metadata(["test.zone"], network)
        assert errors == []

    def test_missing_zone_entry_error(self):
        """Zone not in dns.zones should be reported."""
        network = {"dns": {"zones": []}}
        errors = validate_serial_metadata(["test.zone"], network)
        assert len(errors) == 1
        assert "test.zone" in errors[0]
        assert "missing from dns.zones" in errors[0]

    def test_missing_serial_metadata_error(self):
        """Zone without serial metadata should be reported."""
        network = {
            "dns": {
                "zones": [
                    {
                        "name": "test.zone",
                        "provider": "coredns-common",
                    }
                ]
            }
        }
        errors = validate_serial_metadata(["test.zone"], network)
        assert len(errors) == 1
        assert "missing 'serial' metadata" in errors[0]

    def test_incomplete_serial_metadata_error(self, dns_test_dates):
        """Serial missing required fields should be reported."""
        network = {
            "dns": {
                "zones": [
                    {
                        "name": "test.zone",
                        "provider": "coredns-common",
                        "serial": {
                            "date": dns_test_dates.SERIAL_META
                        },  # Missing counter and content_hash
                    }
                ]
            }
        }
        errors = validate_serial_metadata(["test.zone"], network)
        assert len(errors) == 1
        assert "serial metadata incomplete" in errors[0]

    def test_multiple_zone_validation(self, dns_test_dates):
        """Multiple zones should all be validated."""
        network = {
            "dns": {
                "zones": [
                    {
                        "name": "zone1.test",
                        "provider": "coredns-common",
                        "serial": {
                            "date": dns_test_dates.SERIAL_META,
                            "counter": 0,
                            "content_hash": "abc",
                        },
                    }
                    # zone2 is missing
                ]
            }
        }
        errors = validate_serial_metadata(["zone1.test", "zone2.test"], network)
        assert len(errors) == 1
        assert "zone2.test" in errors[0]


class TestGetCommittedNetworkConfig:
    """Tests for reading committed config from git."""

    def test_returns_none_when_not_in_git(self):
        """Should return None if not in a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_committed_network_config(Path(tmpdir))
            assert result is None

    def test_handles_missing_file_in_head(self):
        """Should return None if file doesn't exist in HEAD."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            # Initialize git repo but don't add network.yaml
            import subprocess

            subprocess.run(["git", "init"], cwd=repo_root, capture_output=True)
            result = get_committed_network_config(repo_root)
            assert result is None

    def test_reads_committed_network_yaml(self, dns_test_dates):
        """Should read and parse network.yaml from git."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            import subprocess

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_root, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_root,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_root,
                capture_output=True,
            )

            # Create and commit network.yaml
            network_file = repo_root / "config" / "network.yaml"
            network_file.parent.mkdir(parents=True)
            test_data = {
                "dns": {
                    "zones": [
                        {
                            "name": "test.zone",
                            "serial": {
                                "date": dns_test_dates.SERIAL_META,
                                "counter": 0,
                                "content_hash": "abc",
                            },
                        }
                    ]
                }
            }
            network_file.write_text(yaml.dump(test_data))

            subprocess.run(
                ["git", "add", "config/network.yaml"],
                cwd=repo_root,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=repo_root,
                capture_output=True,
            )

            # Read it back
            result = get_committed_network_config(repo_root)
            assert result is not None
            assert result["dns"]["zones"][0]["name"] == "test.zone"
