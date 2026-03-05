"""Unit tests for service include resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.services import render_service_configs
from abhaile.utils.errors import RenderError


class TestRenderServiceConfigs:
    """Tests for render_service_configs()."""

    def test_include_resolution_depth_first(self, tmp_path: Path, write_file: Any) -> None:
        """Includes are resolved depth-first with later entries overriding."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create shared service
        write_file(
            config_root / "services" / "shared" / "service.yaml",
            """name: shared
composition:
  config:
    - source: shared/config/shared.conf
      destination: /etc/shared/shared.conf
""",
        )
        write_file(
            config_root / "services" / "shared" / "config" / "shared.conf",
            "shared=true\n",
        )

        # Create service that includes shared
        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  include:
    - shared
  config:
    - source: test-service/config/app.conf
      destination: /etc/app/app.conf
""",
        )
        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf",
            "app=true\n",
        )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        # Both files should exist
        assert (output_dir / "test-service" / "etc/shared/shared.conf").exists()
        assert (output_dir / "test-service" / "etc/app/app.conf").exists()

    def test_include_deduplication(self, tmp_path: Path, write_file: Any) -> None:
        """Services included multiple times are only processed once."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create shared service with counter in template
        write_file(
            config_root / "services" / "shared" / "service.yaml",
            """name: shared
composition:
  config:
    - source:
        template: shared/config/shared.conf.j2
      destination: /etc/shared/shared.conf
""",
        )
        write_file(
            config_root / "services" / "shared" / "config" / "shared.conf.j2",
            "shared=true\n",
        )

        # Create service with duplicate include
        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  include:
    - shared
    - shared
  config: []
""",
        )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        # Should only render once
        output_file = output_dir / "test-service" / "etc/shared/shared.conf"
        assert output_file.exists()
        assert output_file.read_text() == "shared=true\n"

    def test_include_cycle_detection(self, tmp_path: Path, write_file: Any) -> None:
        """Circular includes raise RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create circular include: service-a -> service-b -> service-a
        write_file(
            config_root / "services" / "service-a" / "service.yaml",
            """name: service-a
composition:
  include:
    - service-b
  config: []
""",
        )
        write_file(
            config_root / "services" / "service-b" / "service.yaml",
            """name: service-b
composition:
  include:
    - service-a
  config: []
""",
        )

        network: dict[str, Any] = {}

        with pytest.raises(RenderError, match="cycle detected"):
            render_service_configs(
                "phobos",
                ["service-a"],
                network,
                config_root,
                output_dir,
            )
