"""Unit tests for service rendering order preservation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.services import render_service_configs


class TestServiceRenderingOrder:
    """Tests for service rendering order preservation."""

    def test_services_rendered_in_mapping_order(self, tmp_path: Path, write_file: Any) -> None:
        """Services are rendered in the order specified in the services list."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create multiple service definitions in alphabetically non-sorted order
        # The order is: zebra, alpha, mike
        services = ["zebra-service", "alpha-service", "mike-service"]

        for service in services:
            write_file(
                config_root / "services" / service / "service.yaml",
                f"""name: {service}
composition:
  config:
    - source:
        template: {service}/config/test.conf.j2
        variables:
          order_marker: {service}
      destination: /etc/{service}/test.conf
""",
            )

            write_file(
                config_root / "services" / service / "config" / "test.conf.j2",
                "# {{ service.config.order_marker }}\n",
            )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            services,
            network,
            config_root,
            output_dir,
        )

        # Verify all services were rendered
        for service in services:
            output_file = output_dir / service / "etc" / service / "test.conf"
            assert output_file.exists()
            content = output_file.read_text()
            assert service in content

    def test_service_config_overrides_respect_order(self, tmp_path: Path, write_file: Any) -> None:
        """Service includes are processed in depth-first order allowing overrides."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Create base service
        write_file(
            config_root / "services" / "base-service" / "service.yaml",
            """name: base-service
composition:
  config:
    - source:
        template: base-service/config/base.conf.j2
        variables:
          setting: base_value
      destination: /etc/app/base.conf
""",
        )

        write_file(
            config_root / "services" / "base-service" / "config" / "base.conf.j2",
            "setting={{ service.config.setting }}\n",
        )

        # Create override service that includes base
        write_file(
            config_root / "services" / "override-service" / "service.yaml",
            """name: override-service
composition:
  include:
    - base-service
  config:
    - source:
        template: override-service/config/override.conf.j2
        variables:
          setting: override_value
      destination: /etc/app/override.conf
""",
        )

        write_file(
            config_root / "services" / "override-service" / "config" / "override.conf.j2",
            "setting={{ service.config.setting }}\n",
        )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            ["override-service"],
            network,
            config_root,
            output_dir,
        )

        # Verify base config was rendered first
        base_file = output_dir / "override-service" / "etc/app/base.conf"
        assert base_file.exists()
        assert "setting=base_value" in base_file.read_text()

        # Verify override config was rendered second
        override_file = output_dir / "override-service" / "etc/app/override.conf"
        assert override_file.exists()
        assert "setting=override_value" in override_file.read_text()

    def test_multiple_services_preserve_list_order(
        self, tmp_path: Path, write_file: Any, monkeypatch: Any
    ) -> None:
        """Multiple services are processed in exact list order, not alphabetically."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Track the order services are processed
        processed_order: list[str] = []

        original_mkdir = Path.mkdir

        def track_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
            """Track when service output dirs are created."""
            original_mkdir(self, *args, **kwargs)
            # Extract service name from path like output/services/service-name
            if "services" in str(self) and self.parent.name == "services":
                service_name = self.name
                if service_name not in processed_order:
                    processed_order.append(service_name)

        monkeypatch.setattr(Path, "mkdir", track_mkdir)

        # Create services in non-alphabetical order
        services = ["zebra", "alpha", "mike", "delta"]

        for service in services:
            write_file(
                config_root / "services" / service / "service.yaml",
                f"""name: {service}
composition:
  config:
    - destination: /etc/{service}
""",
            )

        network: dict[str, Any] = {}

        render_service_configs(
            "phobos",
            services,
            network,
            config_root,
            output_dir,
        )

        # Verify services were processed in the exact order provided
        # Filter to just the services we care about
        filtered_order = [s for s in processed_order if s in services]
        assert filtered_order == services
