"""Unit tests for DNS serial hash helpers."""

from abhaile.dns.serial_validator import compute_content_hash as _compute_content_hash


class TestComputeContentHash:
    """Tests for _compute_content_hash."""

    def test_consistent_hash(self) -> None:
        """Test that same content produces same hash."""
        content = "example.com. 3600 IN SOA ns1.example.com. hostmaster.example.com. 2026020800 3600 1800 604800 86400\n"
        hash1 = _compute_content_hash(content)
        hash2 = _compute_content_hash(content)
        assert hash1 == hash2

    def test_different_content_different_hash(self) -> None:
        """Test that different content produces different hash."""
        content1 = "example.com. 3600 IN SOA ns1.example.com. hostmaster.example.com. 2026020800 3600 1800 604800 86400\n"
        content2 = "example.com. 3600 IN SOA ns1.example.com. hostmaster.example.com. 2026020801 3600 1800 604800 86400\n"
        hash1 = _compute_content_hash(content1)
        hash2 = _compute_content_hash(content2)
        assert hash1 != hash2

    def test_hash_format(self) -> None:
        """Test that hash is valid SHA-256 hex."""
        content = "test content"
        hash_val = _compute_content_hash(content)
        assert len(hash_val) == 64  # SHA-256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in hash_val)
