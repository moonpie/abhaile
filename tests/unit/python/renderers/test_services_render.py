"""Unit tests for service config rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abhaile.renderers.services import render_service_configs
from abhaile.renderers.collector import ArtifactCollector


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
        """Service with no config or systemd entries creates no output."""
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

    def test_service_with_only_systemd_entries_renders_output(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Service with only composition.systemd entries still renders artifacts."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "test-service" / "service.yaml",
            """name: test-service
composition:
  systemd:
    - source: test-service/systemd/example.service
      destination: /etc/systemd/system/example.service
      enable: true
""",
        )
        write_file(
            config_root / "services" / "test-service" / "systemd" / "example.service",
            "[Unit]\nDescription=Example\n",
        )

        render_service_configs(
            "phobos",
            ["test-service"],
            {},
            config_root,
            output_dir,
        )

        assert (output_dir / "test-service" / "etc/systemd/system/example.service").exists()

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

    def test_container_service_config_emits_restart_hints(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Container-backed service config entries should emit derived restart hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
podman:
  user: root
  network: ipvlan-l2
apply:
  config_change_restart_unit: blocky.service
composition:
  container: {}
  config:
    - source: blocky/config/app.conf
      destination: /srv/blocky/config.yml
""",
        )
        write_file(
            config_root / "services" / "blocky" / "config" / "app.conf",
            "upstream: 1.1.1.1\n",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["blocky"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.config"]
        assert len(artifacts) == 1
        assert artifacts[0].apply_hints == {
            "restart_unit": "blocky.service",
            "rootless": False,
        }

    def test_host_daemon_service_config_emits_explicit_restart_hint(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Host-daemon services should use explicit config-change restart hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "chrony-a" / "service.yaml",
            """name: chrony-a
systemd:
  network: service-32
apply:
  config_change_restart_unit: chrony.service
composition:
  config:
    - source: chrony-a/config/chrony.conf
      destination: /etc/chrony/chrony.conf
""",
        )
        write_file(
            config_root / "services" / "chrony-a" / "config" / "chrony.conf",
            "pool pool.ntp.org iburst\n",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["chrony-a"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.config"]
        assert len(artifacts) == 1
        assert artifacts[0].apply_hints == {"restart_unit": "chrony.service"}

    def test_pod_service_config_without_explicit_restart_hint_does_not_restart(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Pod-backed service config entries should not derive restart hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
podman:
  user: abhaile
  network: ipvlan-l2
  rootless: true
composition:
  pod: {}
  config:
    - source: authelia/config/config.yml
      destination: /srv/authelia/config.yml
""",
        )
        write_file(
            config_root / "services" / "authelia" / "config" / "config.yml",
            "default_2fa_method: totp\n",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["authelia"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.config"]
        assert len(artifacts) == 1
        hints = artifacts[0].apply_hints
        assert hints is not None
        assert "restart_unit" not in hints
        assert hints.get("rootless") is True

    def test_static_data_service_config_emits_null_restart_unit(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Static-data-only service config entries should emit null restart_unit."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "static-certs" / "service.yaml",
            """name: static-certs
composition:
  config:
    - source: static-certs/config/cert.pem
      destination: /etc/ssl/cert.pem
""",
        )
        write_file(
            config_root / "services" / "static-certs" / "config" / "cert.pem",
            "-----BEGIN CERTIFICATE-----\n",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["static-certs"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.config"]
        assert len(artifacts) == 1
        hints = artifacts[0].apply_hints
        assert hints is None or hints.get("restart_unit") is None

    def test_explicit_null_config_change_restart_unit_is_preserved(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Services may explicitly mark static config writes as no direct restart."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "static-pod" / "service.yaml",
            """name: static-pod
podman:
  user: root
  network: ipvlan-l2
apply:
  config_change_restart_unit: null
composition:
  config:
    - source: static-pod/config/init.txt
      destination: /srv/static-pod/init.txt
  pod:
    containers:
      - name: app
""",
        )
        write_file(
            config_root / "services" / "static-pod" / "config" / "init.txt",
            "static input\n",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["static-pod"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.config"]
        assert len(artifacts) == 1
        assert artifacts[0].apply_hints == {"restart_unit": None, "rootless": False}

    def test_service_directory_emits_owner_group_mode_hints(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Directory-only config entries should emit owner/group/mode apply hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
podman:
  user: abhaile
  network: ipvlan-l2
composition:
  config:
    - destination: /srv/authelia/config
""",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["authelia"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.directory"]
        assert len(artifacts) == 1
        hints = artifacts[0].apply_hints
        assert hints is not None
        assert hints.get("owner") == "abhaile"
        assert hints.get("group") == "abhaile"
        assert hints.get("mode") == "0750"

    def test_service_directory_authored_metadata_overrides_defaults(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Directory metadata authored on config entries overrides service defaults."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
podman:
  user: abhaile
  network: ipvlan-l2
composition:
  config:
    - destination: /srv/authelia/config
      owner: root
      group: root
      mode: '0700'
""",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["authelia"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = [a for a in collector.get_all_artifacts() if a.kind == "service.directory"]
        assert len(artifacts) == 1
        hints = artifacts[0].apply_hints
        assert hints is not None
        assert hints.get("owner") == "root"
        assert hints.get("group") == "root"
        assert hints.get("mode") == "0700"

    def test_systemd_entries_emit_systemd_kinds_and_apply_hints(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """composition.systemd entries emit systemd artifact kinds and mapped hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "rendered" / "phobos"
        output_dir = rendered_root / "services"

        write_file(
            config_root / "services" / "demo" / "service.yaml",
            """name: demo
composition:
  systemd:
    - source: demo/systemd/demo.path
      destination: /etc/systemd/system/demo.path
      enable: true
      start: true
    - source: demo/systemd/demo.service
      destination: /etc/systemd/system/demo.service
""",
        )
        write_file(
            config_root / "services" / "demo" / "systemd" / "demo.path",
            "[Path]\nPathExists=/tmp/demo\n",
        )
        write_file(
            config_root / "services" / "demo" / "systemd" / "demo.service",
            "[Service]\nType=oneshot\n",
        )

        collector = ArtifactCollector()
        render_service_configs(
            "phobos",
            ["demo"],
            {},
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = sorted(
            [a for a in collector.get_all_artifacts() if a.kind == "systemd.unit"],
            key=lambda artifact: artifact.target_path,
        )
        assert len(artifacts) == 2
        assert artifacts[0].owner_ref == "unit:demo.path"
        assert artifacts[0].apply_hints == {
            "enable_mode": "enable",
            "activation_mode": "start",
        }
        assert artifacts[1].owner_ref == "unit:demo.service"
        assert artifacts[1].apply_hints is None
