"""Tests for scripts/lib/python/utils modules."""

import sys
from pathlib import Path

import pytest

# Add lib/python to path
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent / "scripts" / "lib" / "python")
)

from utils.errors import RenderError
from utils.paths import load_paths, resolve_output_root


class TestLoadPaths:
    """Tests for load_paths function."""

    def test_load_paths_success(self, tmp_repo_with_config):
        """Test loading valid paths.ini."""
        paths = load_paths(tmp_repo_with_config)
        assert paths["output_root_default"] == "/var/lib/abhaile"
        assert paths["target_root"] == "/"
        assert paths["config_root"] == "config"
        assert paths["schemas_root"] == "schemas"

    def test_load_paths_missing_file(self, tmp_path):
        """Test error when paths.ini is missing."""
        with pytest.raises(RenderError, match="Missing required paths file"):
            load_paths(tmp_path)

    def test_load_paths_missing_section(self, tmp_path):
        """Test error when [paths] section is missing."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "paths.ini").write_text("")

        with pytest.raises(RenderError, match="Missing \\[paths\\] section"):
            load_paths(tmp_path)

    def test_load_paths_missing_keys(self, tmp_path):
        """Test error when required keys are missing."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "paths.ini").write_text("[paths]\noutput_root_default = /tmp\n")

        with pytest.raises(RenderError, match="missing required keys"):
            load_paths(tmp_path)


class TestResolveOutputRoot:
    """Tests for resolve_output_root function."""

    def test_resolve_single_host_default(self, tmp_repo_with_config):
        """Test single-host render with default output root."""
        paths = load_paths(tmp_repo_with_config)
        root = resolve_output_root("phobos", None, paths, all_mode=False)
        assert root == Path("/var/lib/abhaile")

    def test_resolve_single_host_override(self, tmp_repo_with_config, tmp_output):
        """Test single-host render with output override."""
        paths = load_paths(tmp_repo_with_config)
        root = resolve_output_root("phobos", tmp_output, paths, all_mode=False)
        assert root == tmp_output

    def test_resolve_all_mode_requires_output(self, tmp_repo_with_config):
        """Test that --all requires --output."""
        paths = load_paths(tmp_repo_with_config)
        with pytest.raises(RenderError, match="--all requires --output"):
            resolve_output_root("phobos", None, paths, all_mode=True)

    def test_resolve_all_mode_with_output(self, tmp_repo_with_config, tmp_output):
        """Test --all mode with output override."""
        paths = load_paths(tmp_repo_with_config)
        root = resolve_output_root("phobos", tmp_output, paths, all_mode=True)
        assert root == tmp_output / "phobos"

        root = resolve_output_root("deimos", tmp_output, paths, all_mode=True)
        assert root == tmp_output / "deimos"

    def test_resolve_output_structure(self, tmp_repo_with_config, tmp_output):
        """Test that output structure matches ADR 0001."""
        paths = load_paths(tmp_repo_with_config)

        # Single-host: <output>/rendered and <output>/state
        root = resolve_output_root("phobos", tmp_output, paths, all_mode=False)
        assert root == tmp_output
        rendered = root / paths["rendered_dir_name"]
        state = root / paths["state_dir_name"]
        assert rendered == tmp_output / "rendered"
        assert state == tmp_output / "state"

        # All-mode: <output>/<host>/rendered and <output>/<host>/state
        root_all = resolve_output_root("phobos", tmp_output, paths, all_mode=True)
        assert root_all == tmp_output / "phobos"
        rendered_all = root_all / paths["rendered_dir_name"]
        state_all = root_all / paths["state_dir_name"]
        assert rendered_all == tmp_output / "phobos" / "rendered"
        assert state_all == tmp_output / "phobos" / "state"
