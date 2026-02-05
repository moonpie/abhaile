"""Unit tests for service configs renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from renderers.services import render_service_configs
from utils.errors import RenderError


def _write(path: Path, content: str) -> None:
    """Helper to write file with parent directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestRenderServiceConfigs:
    """Tests for render_service_configs()."""

    def test_render_static_config_files(self, tmp_path: Path) -> None:
        """Static config files are copied to service output directory."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition
        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source: test-service/config/app.conf
      destination: /etc/app/app.conf
""",
        )

        # Create source file
        _write(
            config_root / "services" / "test-service" / "config" / "app.conf",
            "# App config\nport=8080\n",
        )

        network = {"example": "data"}

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

    def test_render_templated_config_files(self, tmp_path: Path) -> None:
        """Templated config files are rendered with service context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition with template
        _write(
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
        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "# App config\nhost={{ service.config.host }}\nport={{ service.config.port }}\n",
        )

        network = {"example": "data"}

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

    def test_resolve_network_placeholders(self, tmp_path: Path) -> None:
        """%%network...%% placeholders are resolved from network.yaml."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition with network placeholders
        _write(
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
        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "bind={{ service.config.bind_ip }}\n",
        )

        network = {
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
        self, tmp_path: Path
    ) -> None:
        """%%network...%% placeholders without | strip_cidr preserve CIDR."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create service definition
        _write(
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
        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "bind={{ service.config.bind_ip }}\n",
        )

        network = {
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

    def test_include_resolution_depth_first(self, tmp_path: Path) -> None:
        """Includes are resolved depth-first with later entries overriding."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create shared service
        _write(
            config_root / "services" / "shared" / "service.yaml",
            """name: shared
composition:
  config:
    - source: shared/config/shared.conf
      destination: /etc/shared/shared.conf
""",
        )
        _write(
            config_root / "services" / "shared" / "config" / "shared.conf",
            "shared=true\n",
        )

        # Create service that includes shared
        _write(
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
        _write(
            config_root / "services" / "test-service" / "config" / "app.conf",
            "app=true\n",
        )

        network = {}

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

    def test_include_deduplication(self, tmp_path: Path) -> None:
        """Services included multiple times are only processed once."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create shared service with counter in template
        _write(
            config_root / "services" / "shared" / "service.yaml",
            """name: shared
composition:
  config:
    - source:
        template: shared/config/shared.conf.j2
      destination: /etc/shared/shared.conf
""",
        )
        _write(
            config_root / "services" / "shared" / "config" / "shared.conf.j2",
            "shared=true\n",
        )

        # Create service with duplicate include
        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  include:
    - shared
    - shared
  config: []
""",
        )

        network = {}

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

    def test_include_cycle_detection(self, tmp_path: Path) -> None:
        """Circular includes raise RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create circular include: service-a -> service-b -> service-a
        _write(
            config_root / "services" / "service-a" / "service.yaml",
            """name: service-a
composition:
  include:
    - service-b
  config: []
""",
        )
        _write(
            config_root / "services" / "service-b" / "service.yaml",
            """name: service-b
composition:
  include:
    - service-a
  config: []
""",
        )

        network = {}

        with pytest.raises(RenderError, match="cycle detected"):
            render_service_configs(
                "phobos",
                ["service-a"],
                network,
                config_root,
                output_dir,
            )

    def test_missing_service_definition_raises_error(self, tmp_path: Path) -> None:
        """Missing service definition raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        network = {}

        with pytest.raises(RenderError, match="Missing service definition"):
            render_service_configs(
                "phobos",
                ["nonexistent-service"],
                network,
                config_root,
                output_dir,
            )

    def test_missing_included_service_raises_error(self, tmp_path: Path) -> None:
        """Missing included service raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  include:
    - nonexistent-service
  config: []
""",
        )

        network = {}

        with pytest.raises(RenderError, match="Missing service definition"):
            render_service_configs(
                "phobos",
                ["test-service"],
                network,
                config_root,
                output_dir,
            )

    def test_invalid_placeholder_raises_error(self, tmp_path: Path) -> None:
        """Invalid network placeholder raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "value={{ service.config.value }}\n",
        )

        network = {"services": {}}

        with pytest.raises(RenderError, match="Placeholder path not found"):
            render_service_configs(
                "phobos",
                ["test-service"],
                network,
                config_root,
                output_dir,
            )

    def test_unknown_placeholder_filter_raises_error(self, tmp_path: Path) -> None:
        """Unknown placeholder filter raises RenderError."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
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

        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "value={{ service.config.value }}\n",
        )

        network = {"services": {"test-service": {"address": "172.20.20.200/32"}}}

        with pytest.raises(RenderError, match="Unknown placeholder filter"):
            render_service_configs(
                "phobos",
                ["test-service"],
                network,
                config_root,
                output_dir,
            )

    def test_empty_services_list_creates_no_output(self, tmp_path: Path) -> None:
        """Empty services list creates no output."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        network = {}

        render_service_configs(
            "phobos",
            [],
            network,
            config_root,
            output_dir,
        )

        # No services means nothing is rendered (directory may not exist)
        assert not output_dir.exists() or list(output_dir.iterdir()) == []

    def test_service_with_no_config_entries(self, tmp_path: Path) -> None:
        """Service with no config entries creates no output."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config: []
""",
        )

        network = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        # Service directory not created if no configs
        assert not (output_dir / "test-service").exists()

    def test_multiple_services_render_independently(self, tmp_path: Path) -> None:
        """Multiple services render to separate directories."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create two services
        for service in ["service-a", "service-b"]:
            _write(
                config_root / "services" / service / "service.yaml",
                f"""name: {service}
composition:
  config:
    - source: {service}/config/app.conf
      destination: /etc/app/app.conf
""",
            )
            _write(
                config_root / "services" / service / "config" / "app.conf",
                f"{service}=true\n",
            )

        network = {}

        render_service_configs(
            "phobos",
            ["service-a", "service-b"],
            network,
            config_root,
            output_dir,
        )

        # Both services should have independent output
        assert (
            output_dir / "service-a" / "etc/app/app.conf"
        ).read_text() == "service-a=true\n"
        assert (
            output_dir / "service-b" / "etc/app/app.conf"
        ).read_text() == "service-b=true\n"

    def test_network_context_available_in_templates(self, tmp_path: Path) -> None:
        """Network data is available in template context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
      destination: /etc/app/app.conf
""",
        )

        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "gateway={{ network.vlans.services.gateway }}\n",
        )

        network = {
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

    def test_host_name_available_in_templates(self, tmp_path: Path) -> None:
        """Host name is available in template context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
      destination: /etc/app/app.conf
""",
        )

        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "hostname={{ host_name }}\n",
        )

        network = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.read_text() == "hostname=phobos\n"

    def test_service_name_available_in_templates(self, tmp_path: Path) -> None:
        """Service name is available in template context."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        _write(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  config:
    - source:
        template: test-service/config/app.conf.j2
      destination: /etc/app/app.conf
""",
        )

        _write(
            config_root / "services" / "test-service" / "config" / "app.conf.j2",
            "service={{ service_name }}\n",
        )

        network = {}

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            config_root,
            output_dir,
        )

        output_file = output_dir / "test-service" / "etc/app/app.conf"
        assert output_file.read_text() == "service=test-service\n"
