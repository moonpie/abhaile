"""Unit tests for service config error handling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.services import render_service_configs
from abhaile.utils.errors import RenderError


class TestRenderServiceConfigs:
    """Tests for render_service_configs()."""

    def test_missing_service_definition_raises_error(self, tmp_path: Path) -> None:
        """Missing service definition raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        network: dict[str, Any] = {}

        with pytest.raises(RenderError, match="Missing service definition"):
            render_service_configs(
                "phobos",
                ["nonexistent-service"],
                network,
                config_root,
                output_dir,
            )

    def test_missing_included_service_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Missing included service raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  include:
    - nonexistent-service
  config: []
""",
        )

        network: dict[str, Any] = {}

        with pytest.raises(RenderError, match="Missing service definition"):
            render_service_configs(
                "phobos",
                ["test-service"],
                network,
                config_root,
                output_dir,
            )

    def test_invalid_placeholder_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Invalid network placeholder raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
        variables:
          value: '%%network.invalid.path%%'
      destination: /etc/app/app.conf
""",
        )

        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "value={{ service.config.value }}\n",
        )

        network: dict[str, Any] = {"services": {}}

        with pytest.raises(RenderError, match="Placeholder path not found"):
            render_service_configs(
                "phobos",
                ["test-service"],
                network,
                config_root,
                output_dir,
            )

    def test_unknown_placeholder_filter_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Unknown placeholder filter raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
        variables:
          value: '%%network.services.test-service.address | unknown_filter%%'
      destination: /etc/app/app.conf
""",
        )

        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "value={{ service.config.value }}\n",
        )

        network: dict[str, Any] = {"services": {"test-service": {"address": "172.20.20.200/32"}}}

        with pytest.raises(RenderError, match="Unknown placeholder filter"):
            render_service_configs(
                "phobos",
                ["test-service"],
                network,
                config_root,
                output_dir,
            )
