"""Unit tests for service config rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.services import render_service_configs


class TestRenderServiceConfigs:
    """Tests for render_service_configs()."""

    def test_render_static_config_files(self, tmp_path: Path, write_file: Any) -> None:
        """Static config files are copied to service output directory."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition
        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source: test-service/config/app.conf
      destination: /etc/app/app.conf
""",
        )

        # Create source file
        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf",
            "# App config\nport=8080\n",
        )

        network: dict[str, Any] = {"example": "data"}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.exists()
        assert output_file.read_text() == "# App config\nport=8080\n"

    def test_render_templated_config_files(self, tmp_path: Path, write_file: Any) -> None:
        """Templated config files are rendered with service context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition with template
        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
        variables:
          port: 8080
          host: localhost
      destination: /etc/app/app.conf
""",
        )

        # Create template
        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "# App config\nhost={{ service.config.host }}\nport={{ service.config.port }}\n",
        )

        network: dict[str, Any] = {"example": "data"}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.exists()
        assert output_file.read_text() == "# App config\nhost=localhost\nport=8080\n"

    def test_resolve_network_placeholders(self, tmp_path: Path, write_file: Any) -> None:
        """%%network...%% placeholders are resolved from network.yaml."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition with network placeholders
        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
        variables:
          bind_ip: '%%network.services.test-service.address | strip_cidr%%'
      destination: /etc/app/app.conf
""",
        )

        # Create template
        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "bind={{ service.config.bind_ip }}\n",
        )

        network: dict[str, Any] = {
            "services": {
                "test-service": {
                    "address": "172.20.20.200/32",
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
        assert output_file.exists()
        assert output_file.read_text() == "bind=172.20.20.200\n"

    def test_resolve_network_placeholders_without_strip_cidr(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """%%network...%% placeholders without | strip_cidr preserve CIDR."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition
        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
        variables:
          bind_ip: '%%network.services.test-service.address%%'
      destination: /etc/app/app.conf
""",
        )

        # Create template
        write_file(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "bind={{ service.config.bind_ip }}\n",
        )

        network: dict[str, Any] = {
            "services": {
                "test-service": {
                    "address": "172.20.20.200/32",
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
        assert output_file.exists()
        assert output_file.read_text() == "bind=172.20.20.200/32\n"

    def test_empty_services_list_creates_no_output(self, tmp_path: Path) -> None:
        """Empty services list creates no output."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            [],
            network,
            config_root,
            output_dir,
        )

        # No services means nothing is rendered (directory may not exist)
        assert not output_dir.exists() or list(output_dir.iterdir()) == []

    def test_service_with_no_config_entries(self, tmp_path: Path, write_file: Any) -> None:
        """Service with no config entries creates no output."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
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

        # Service directory not created if no configs
        assert not (output_dir / "test-service").exists()

    def test_multiple_services_render_independently(self, tmp_path: Path, write_file: Any) -> None:
        """Multiple services render to separate directories."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create two services
        for service in ["service-a", "service-b"]:
            write_file(
                config_root / "services" / service / "service.yaml",
                f"""name: {service}
composition:
  config:
    - source: {service}/config/app.conf
      destination: /etc/app/app.conf
""",
            )
            write_file(
                config_root / "services" / service / "config" / "app.conf",
                f"{service}=true\n",
            )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            ["service-a", "service-b"],
            network,
            config_root,
            output_dir,
        )

        # Both services should have independent output
        assert (output_dir / "service-a" / "etc/app/app.conf").read_text() == "service-a=true\n"
        assert (output_dir / "service-b" / "etc/app/app.conf").read_text() == "service-b=true\n"
