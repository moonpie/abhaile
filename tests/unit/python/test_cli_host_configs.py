"""Unit tests for CLI host config loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.cli.render import _load_host_configs
from abhaile.utils.errors import RenderError


class TestLoadHostConfigs:
    """Tests for _load_host_configs() validation."""

    def test_empty_common_host_yaml_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Empty common/host.yaml raises RenderError."""
        config_root = tmp_path / "config"

        # Create empty common host.yaml
        write_file(
            config_root / "hosts" / "common" / "host.yaml",
            "",
        )

        # Create valid host-specific host.yaml
        write_file(
            config_root / "hosts" / "phobos" / "host.yaml",
            "physical_device: enp0s31f6\n",
        )

        paths = {"hosts_subdir": "hosts"}

        with pytest.raises(RenderError, match="Expected YAML mapping"):
            _load_host_configs("phobos", config_root, paths)

    def test_empty_host_yaml_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Empty host-specific host.yaml raises RenderError."""
        config_root = tmp_path / "config"

        # Create valid common host.yaml
        write_file(
            config_root / "hosts" / "common" / "host.yaml",
            "domain: example.com\n",
        )

        # Create empty host-specific host.yaml
        write_file(
            config_root / "hosts" / "phobos" / "host.yaml",
            "",
        )

        paths = {"hosts_subdir": "hosts"}

        with pytest.raises(RenderError, match="Expected YAML mapping"):
            _load_host_configs("phobos", config_root, paths)

    def test_list_common_host_yaml_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """YAML list in common/host.yaml raises RenderError."""
        config_root = tmp_path / "config"

        # Create list in common host.yaml
        write_file(
            config_root / "hosts" / "common" / "host.yaml",
            "- item1\n- item2\n",
        )

        # Create valid host-specific host.yaml
        write_file(
            config_root / "hosts" / "phobos" / "host.yaml",
            "physical_device: enp0s31f6\n",
        )

        paths = {"hosts_subdir": "hosts"}

        with pytest.raises(RenderError, match="Expected YAML mapping"):
            _load_host_configs("phobos", config_root, paths)

    def test_list_host_yaml_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """YAML list in host-specific host.yaml raises RenderError."""
        config_root = tmp_path / "config"

        # Create valid common host.yaml
        write_file(
            config_root / "hosts" / "common" / "host.yaml",
            "domain: example.com\n",
        )

        # Create list in host-specific host.yaml
        write_file(
            config_root / "hosts" / "phobos" / "host.yaml",
            "- device1\n- device2\n",
        )

        paths = {"hosts_subdir": "hosts"}

        with pytest.raises(RenderError, match="Expected YAML mapping"):
            _load_host_configs("phobos", config_root, paths)

    def test_scalar_host_yaml_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """YAML scalar in host.yaml raises RenderError."""
        config_root = tmp_path / "config"

        # Create valid common host.yaml
        write_file(
            config_root / "hosts" / "common" / "host.yaml",
            "domain: example.com\n",
        )

        # Create scalar in host-specific host.yaml
        write_file(
            config_root / "hosts" / "phobos" / "host.yaml",
            "just a string\n",
        )

        paths = {"hosts_subdir": "hosts"}

        with pytest.raises(RenderError, match="Expected YAML mapping"):
            _load_host_configs("phobos", config_root, paths)

    def test_valid_host_configs_load_successfully(self, tmp_path: Path, write_file: Any) -> None:
        """Valid host configs load without error."""
        config_root = tmp_path / "config"

        # Create valid common host.yaml
        write_file(
            config_root / "hosts" / "common" / "host.yaml",
            "domain: example.com\nsoftware:\n  packages: []\n",
        )

        # Create valid host-specific host.yaml
        write_file(
            config_root / "hosts" / "phobos" / "host.yaml",
            "physical_device: enp0s31f6\n",
        )

        paths = {"hosts_subdir": "hosts"}

        host_config, common_config = _load_host_configs("phobos", config_root, paths)

        assert isinstance(host_config, dict)
        assert isinstance(common_config, dict)
        assert host_config["physical_device"] == "enp0s31f6"
        assert common_config["domain"] == "example.com"
