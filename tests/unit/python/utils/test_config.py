"""Unit tests for YAML cache in utils/config.py."""

from __future__ import annotations

from pathlib import Path

from abhaile.utils.config import clear_config_cache, read_yaml


def test_read_yaml_caches_by_resolved_path(tmp_path: Path) -> None:
    """Second read_yaml call for same path returns cached result without disk I/O."""
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("key: value\n")

    clear_config_cache()

    result1 = read_yaml(yaml_file)
    assert result1 == {"key": "value"}

    # Delete file — cached result should still be returned
    yaml_file.unlink()
    result2 = read_yaml(yaml_file)
    assert result2 == {"key": "value"}
    assert result1 is result2  # Same object from cache


def test_clear_config_cache_invalidates(tmp_path: Path) -> None:
    """After clear_config_cache, read_yaml re-reads from disk."""
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("version: 1\n")

    clear_config_cache()
    read_yaml(yaml_file)

    yaml_file.write_text("version: 2\n")
    clear_config_cache()

    result = read_yaml(yaml_file)
    assert result == {"version": 2}
