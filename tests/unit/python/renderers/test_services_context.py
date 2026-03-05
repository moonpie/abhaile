"""Unit tests for service template context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.services import render_service_configs


class TestRenderServiceConfigs:
    """Tests for render_service_configs()."""

    def test_network_context_available_in_templates(self, tmp_path: Path, write_file: Any) -> None:
        """Network data is available in template context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
      destination: /etc/app/app.conf
""",
        )

        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "gateway={{ network.vlans.services.gateway }}\n",
        )

        network: dict[str, Any] = {
            "vlans": {
                "services": {
                    "gateway": "172.20.20.1",
                }
            }
        }

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.read_text() == "gateway=172.20.20.1\n"

    def test_host_name_available_in_templates(self, tmp_path: Path, write_file: Any) -> None:
        """Host name is available in template context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
      destination: /etc/app/app.conf
""",
        )

        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "hostname={{ host_name }}\n",
        )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.read_text() == "hostname=phobos\n"

    def test_service_name_available_in_templates(self, tmp_path: Path, write_file: Any) -> None:
        """Service name is available in template context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
      destination: /etc/app/app.conf
""",
        )

        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "service={{ service_name }}\n",
        )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.read_text() == "service=test-service\n"
