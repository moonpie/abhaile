"""Unit tests for quadlet validation improvements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.quadlets.container import _validate_template_variables
from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.errors import RenderError


class TestHostPathValidation:
    """Tests for per-user host_path reuse validation."""

    def test_duplicate_host_path_requires_shared_true(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Same host_path under same user must use shared=true."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "svc-a" / "service.yaml",
            """name: svc-a
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /shared/path
        mount_path: /config
    mounted_files: []
""",
        )
        write_file(
            config_root / "services" / "svc-a" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )
        write_file(
            config_root / "services" / "svc-a" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "services" / "svc-b" / "service.yaml",
            """name: svc-b
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /shared/path
        mount_path: /config
    mounted_files: []
""",
        )
        write_file(
            config_root / "services" / "svc-b" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )
        write_file(
            config_root / "services" / "svc-b" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )
        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"svc-a": {"vlan": "services"}, "svc-b": {"vlan": "services"}},
        }

        with pytest.raises(RenderError, match="must be declared with shared=true"):
            render_service_quadlets(
                "phobos",
                ["svc-a", "svc-b"],
                network,
                config_root,
                output_dir,
            )

    def test_duplicate_shared_host_path_requires_same_volume_name(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Same shared host_path must reuse the same shared volume name."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "svc-a" / "service.yaml",
            """name: svc-a
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: shared-config
        host_path: /shared/path
        mount_path: /config
        shared: true
    mounted_files: []
""",
        )
        write_file(
            config_root / "services" / "svc-a" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )
        write_file(
            config_root / "services" / "svc-a" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "services" / "svc-b" / "service.yaml",
            """name: svc-b
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: another-name
        host_path: /shared/path
        mount_path: /config
        shared: true
    mounted_files: []
""",
        )
        write_file(
            config_root / "services" / "svc-b" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )
        write_file(
            config_root / "services" / "svc-b" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nDevice={{ host_path }}\nOptions=bind\n",
        )
        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"svc-a": {"vlan": "services"}, "svc-b": {"vlan": "services"}},
        }

        with pytest.raises(RenderError, match="must reuse the same shared volume name"):
            render_service_quadlets(
                "phobos",
                ["svc-a", "svc-b"],
                network,
                config_root,
                output_dir,
            )


class TestTemplateVariableValidation:
    """Tests for template variable validation."""

    def test_validate_template_variables_success(self) -> None:
        """Template with valid variables passes validation."""
        template_text = """
[Container]
Image={{ image }}
Build={{ build }}
"""
        # Should not raise
        _validate_template_variables("container.container.j2", template_text)

    def test_validate_template_variables_partial(self) -> None:
        """Template with optional variables is valid."""
        template_text = """
[Container]
Image={{ image }}
"""
        # Should not raise - build is optional
        _validate_template_variables("container.container.j2", template_text)

    def test_validate_template_variables_no_vars(self) -> None:
        """Template with no variables is valid."""
        template_text = """
[Container]
Image=static:latest
"""
        # Should not raise
        _validate_template_variables("container.container.j2", template_text)

    def test_validate_template_variables_unknown_template(self) -> None:
        """Unknown template name is silently accepted."""
        template_text = """
[Service]
Type=notify
"""
        # Should not raise - unknown template types are not validated
        _validate_template_variables("unknown.template.j2", template_text)

    def test_template_missing_image_at_render_time(self, tmp_path: Path, write_file: Any) -> None:
        """Template expecting image but no image.image file raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "app" / "service.yaml",
            """name: app
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"app": {"vlan": "services"}},
        }

        with pytest.raises(RenderError, match="Template requires image variable"):
            render_service_quadlets(
                "phobos",
                ["app"],
                network,
                config_root,
                output_dir,
            )

    def test_template_missing_build_at_render_time(self, tmp_path: Path, write_file: Any) -> None:
        """Template expecting build but no build.build file raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "app" / "service.yaml",
            """name: app
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "container.container.j2",
            "[Container]\nBuild={{ build }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"app": {"vlan": "services"}},
        }

        with pytest.raises(RenderError, match="Template requires build variable"):
            render_service_quadlets(
                "phobos",
                ["app"],
                network,
                config_root,
                output_dir,
            )

    def test_template_with_image_and_build(self, tmp_path: Path, write_file: Any) -> None:
        """Template with both image and build variables works when both provided."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "app" / "service.yaml",
            """name: app
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "build.build",
            "[Build]\nBuildArgs=--tag=app:latest\n",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\nBuild={{ build }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"app": {"vlan": "services"}},
        }

        # Should succeed
        render_service_quadlets(
            "phobos",
            ["app"],
            network,
            config_root,
            output_dir,
        )

        # Verify all files were created
        output_root = output_dir / "app" / "etc" / "containers" / "systemd"
        assert (output_root / "app.container").exists()
        assert (output_root / "app.image").exists()
        assert (output_root / "app.build").exists()

    def test_missing_trailing_newline_in_quadlet_source_raises(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Source quadlet files must include trailing newline."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "app" / "service.yaml",
            """name: app
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "image.image",
            "[Image]\nImage=ghcr.io/example/app:latest",
        )
        write_file(
            config_root / "services" / "app" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"app": {"vlan": "services"}},
        }

        with pytest.raises(RenderError, match="must end with a trailing newline"):
            render_service_quadlets(
                "phobos",
                ["app"],
                network,
                config_root,
                output_dir,
            )


class TestFileEncoding:
    """Tests for UTF-8 encoding in generated files."""

    def test_quadlet_files_are_utf8_encoded(self, tmp_path: Path, write_file: Any) -> None:
        """Generated quadlet files use UTF-8 encoding."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Use unicode content with special characters
        unicode_content = """[Unit]
Description=Test Service ❤️ UTF-8
# Comment with unicode: 日本語

[Container]
Image=test:latest
"""

        write_file(
            config_root / "services" / "unicode-test" / "service.yaml",
            """name: unicode-test
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes: []
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "unicode-test" / "quadlets" / "image.image",
            "[Image]\nImage=test:latest\n",
        )

        # Template with unicode
        write_file(
            config_root / "services" / "unicode-test" / "quadlets" / "container.container.j2",
            unicode_content,
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"unicode-test": {"vlan": "services"}},
        }

        render_service_quadlets(
            "phobos",
            ["unicode-test"],
            network,
            config_root,
            output_dir,
        )

        # Verify file can be read with UTF-8 encoding
        container_file = (
            output_dir
            / "unicode-test"
            / "etc"
            / "containers"
            / "systemd"
            / "unicode-test.container"
        )
        content = container_file.read_text(encoding="utf-8")

        # Verify unicode content is preserved
        assert "❤️" in content
        assert "日本語" in content

    def test_pod_container_files_are_utf8_encoded(self, tmp_path: Path, write_file: Any) -> None:
        """Generated pod container files use UTF-8 encoding."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        unicode_content = "[Container]\n# Unicode: 中文\nImage=test:latest\n"

        write_file(
            config_root / "services" / "multi-container" / "service.yaml",
            """name: multi-container
podman:
  user: root
  network: ipvlan-l2
composition:
  pod:
    containers:
      - name: app
        named_volumes: []
        mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "multi-container" / "quadlets" / "pod.pod.j2",
            "[Pod]\n",
        )

        write_file(
            config_root / "services" / "multi-container" / "quadlets" / "app" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        write_file(
            config_root
            / "services"
            / "multi-container"
            / "quadlets"
            / "app"
            / "container.container.j2",
            unicode_content,
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"multi-container": {"vlan": "services"}},
        }

        render_service_quadlets(
            "phobos",
            ["multi-container"],
            network,
            config_root,
            output_dir,
        )

        container_file = (
            output_dir
            / "multi-container"
            / "etc"
            / "containers"
            / "systemd"
            / "multi-container-app-app.container"
        )
        content = container_file.read_text(encoding="utf-8")
        assert "中文" in content


class TestMultiplePlaceholdersInHostPath:
    """Tests for edge cases in volume rendering."""

    def test_multiple_volumes_per_container_per_service_scope(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Multiple volumes in same container allowed with PER_SERVICE scope."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "app" / "service.yaml",
            """name: app
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    named_volumes:
      - name: config
        host_path: /data/config
        mount_path: /config
      - name: data
        host_path: /data/store
        mount_path: /data
    mounted_files: []
""",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "image.image",
            "[Image]\nImage=app:latest\n",
        )

        write_file(
            config_root / "services" / "app" / "quadlets" / "container.container.j2",
            "[Container]\nImage={{ image }}\n{% for vol in volume_lines %}{{ vol }}\n{% endfor %}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "volume.volume.j2",
            "[Volume]\nPath={{ host_path }}\n",
        )

        write_file(
            config_root / "_templates" / "services" / "quadlets" / "network.network.j2",
            "[Network]\n",
        )

        network: dict[str, Any] = {
            "vlans": {"services": {"cidr": "172.20.20.0/24"}},
            "services": {"app": {"vlan": "services"}},
        }

        # Should succeed
        render_service_quadlets(
            "phobos",
            ["app"],
            network,
            config_root,
            output_dir,
        )

        # Verify volumes are created
        output_root = output_dir / "app" / "etc" / "containers" / "systemd"
        assert (output_root / "app-config.volume").exists()
        assert (output_root / "app-data.volume").exists()
