"""Unit tests for ingress renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.ingress import render_ingress_configs
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError


class TestRenderIngressConfigs:
    """Tests for render_ingress_configs()."""

    def test_no_services_does_nothing(self, tmp_path: Path) -> None:
        """Empty services list does nothing."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        render_ingress_configs(
            "phobos",
            [],
            [],
            config_root,
            output_dir,
        )

        # No output should be generated
        assert not output_dir.exists()

    def test_no_base_services_does_nothing(self, tmp_path: Path, write_file: Any) -> None:
        """Services without ingress base definitions are skipped."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "blocky" / "service.yaml",
            """name: blocky
composition:
  container:
    named_volumes: []
""",
        )

        render_ingress_configs(
            "phobos",
            ["blocky"],
            ["blocky"],
            config_root,
            output_dir,
        )

        # No ingress output
        assert not (output_dir / "blocky").exists()

    def test_render_single_base_no_blocks(self, tmp_path: Path, write_file: Any) -> None:
        """Base service without blocks renders only base content."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            """{
\tadmin off
}

:80 {
\tredir https://{host}{uri}
}
""",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-dmz"],
            ["caddy-dmz"],
            config_root,
            output_dir,
        )

        output_file = output_dir / "caddy-dmz" / "srv/caddy/dmz/Caddyfile"
        assert output_file.exists()

        content = output_file.read_text()
        assert "admin off" in content
        assert ":80" in content
        # No blocks appended
        assert "Aggregated Ingress Blocks" not in content

    def test_render_base_with_blocks(self, tmp_path: Path, write_file: Any) -> None:
        """Base service aggregates blocks from other services."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Base service
        write_file(
            config_root / "services" / "caddy-internal" / "service.yaml",
            """name: caddy-internal
composition:
  ingress:
    internal:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/internal/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-internal" / "config" / "Caddyfile",
            """{
\tadmin off
}
""",
        )

        # Service with block
        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  ingress:
    internal:
      blocks:
        - caddy/internal-ingress.txt
""",
        )

        write_file(
            config_root / "services" / "authelia" / "caddy" / "internal-ingress.txt",
            """authelia.abhaile.home.arpa {
\treverse_proxy http://authelia.svc:9091
}
""",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-internal"],
            ["caddy-internal", "authelia"],
            config_root,
            output_dir,
        )

        output_file = output_dir / "caddy-internal" / "srv/caddy/internal/Caddyfile"
        assert output_file.exists()

        content = output_file.read_text()
        assert "admin off" in content
        assert "Aggregated Ingress Blocks" in content
        assert "# --- authelia ---" in content
        assert "authelia.abhaile.home.arpa" in content
        assert "reverse_proxy" in content

    def test_multiple_blocks_deterministic_order(self, tmp_path: Path, write_file: Any) -> None:
        """Multiple blocks are aggregated in alphabetical order by service."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            "{ admin off }\n",
        )

        # Service vault (alphabetically last)
        write_file(
            config_root / "services" / "vault" / "service.yaml",
            """name: vault
composition:
  ingress:
    dmz:
      blocks:
        - caddy/dmz-ingress.txt
""",
        )

        write_file(
            config_root / "services" / "vault" / "caddy" / "dmz-ingress.txt",
            "vault.example.com { reverse_proxy :8200 }\n",
        )

        # Service authelia (alphabetically first)
        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  ingress:
    dmz:
      blocks:
        - caddy/dmz-ingress.txt
""",
        )

        write_file(
            config_root / "services" / "authelia" / "caddy" / "dmz-ingress.txt",
            "auth.example.com { reverse_proxy :9091 }\n",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-dmz"],
            ["caddy-dmz", "authelia", "vault"],
            config_root,
            output_dir,
        )

        output_file = output_dir / "caddy-dmz" / "srv/caddy/dmz/Caddyfile"
        content = output_file.read_text()

        # Check order: caddy-dmz base, then blocks in mapping order
        authelia_pos = content.find("# --- authelia ---")
        vault_pos = content.find("# --- vault ---")
        assert authelia_pos < vault_pos

    def test_multiple_blocks_from_same_service(self, tmp_path: Path, write_file: Any) -> None:
        """Service with multiple block files includes all."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy-internal" / "service.yaml",
            """name: caddy-internal
composition:
  ingress:
    internal:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/internal/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-internal" / "config" / "Caddyfile",
            "{ admin off }\n",
        )

        write_file(
            config_root / "services" / "omada" / "service.yaml",
            """name: omada
composition:
  ingress:
    internal:
      blocks:
        - caddy/ingress.txt
        - caddy/cert.txt
""",
        )

        write_file(
            config_root / "services" / "omada" / "caddy" / "ingress.txt",
            "omada.home { reverse_proxy :8043 }\n",
        )

        write_file(
            config_root / "services" / "omada" / "caddy" / "cert.txt",
            "cert.home { file_server }\n",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-internal"],
            ["caddy-internal", "omada"],
            config_root,
            output_dir,
        )

        output_file = output_dir / "caddy-internal" / "srv/caddy/internal/Caddyfile"
        content = output_file.read_text()

        assert "omada.home" in content
        assert "cert.home" in content
        # Both under same service comment
        assert content.count("# --- omada ---") == 2

    def test_multiple_zones_separate_outputs(self, tmp_path: Path, write_file: Any) -> None:
        """Service defining multiple zones renders each independently."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        # Service with dmz base
        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            "# DMZ Base\n",
        )

        # Service with internal base
        write_file(
            config_root / "services" / "caddy-internal" / "service.yaml",
            """name: caddy-internal
composition:
  ingress:
    internal:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/internal/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-internal" / "config" / "Caddyfile",
            "# Internal Base\n",
        )
        # Service with blocks for both zones
        write_file(
            config_root / "services" / "omada" / "service.yaml",
            """name: omada
composition:
  ingress:
    dmz:
      blocks:
        - caddy/dmz-ingress.txt
    internal:
      blocks:
        - caddy/internal-ingress.txt
""",
        )

        write_file(
            config_root / "services" / "omada" / "caddy" / "dmz-ingress.txt",
            "omada-dmz.example.com { }\n",
        )

        write_file(
            config_root / "services" / "omada" / "caddy" / "internal-ingress.txt",
            "omada.home { }\n",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-dmz", "caddy-internal"],
            ["caddy-dmz", "caddy-internal", "omada"],
            config_root,
            output_dir,
        )

        dmz_file = output_dir / "caddy-dmz" / "srv/caddy/dmz/Caddyfile"
        internal_file = output_dir / "caddy-internal" / "srv/caddy/internal/Caddyfile"

        assert dmz_file.exists()
        assert internal_file.exists()

        dmz_content = dmz_file.read_text()
        internal_content = internal_file.read_text()

        # DMZ has dmz block, not internal
        assert "omada-dmz.example.com" in dmz_content
        assert "omada.home" not in dmz_content

        # Internal has internal block, not dmz
        assert "omada.home" in internal_content
        assert "omada-dmz.example.com" not in internal_content

    def test_registers_caddy_metadata(self, tmp_path: Path, write_file: Any) -> None:
        """Ingress render registers caddy.config artifact and segment owner metadata."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "out" / "rendered"
        output_dir = rendered_root / "services"
        collector = ArtifactCollector()

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            "# DMZ\n",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-dmz"],
            ["caddy-dmz"],
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = collector.get_artifacts_by_owner("caddy:dmz")
        assert len(artifacts) == 1
        assert artifacts[0].kind == "caddy.config"
        assert artifacts[0].target_path == "/srv/caddy/dmz/Caddyfile"

        owners = collector.get_all_owners()
        assert "caddy:dmz" in owners

    def test_registers_single_contributor_ref(self, tmp_path: Path, write_file: Any) -> None:
        """Single ingress block contributor is preserved on aggregated artifact."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "out" / "rendered"
        output_dir = rendered_root / "services"
        collector = ArtifactCollector()

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )
        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            "# DMZ\n",
        )
        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  ingress:
    dmz:
      blocks:
        - caddy/dmz-ingress.txt
""",
        )
        write_file(
            config_root / "services" / "authelia" / "caddy" / "dmz-ingress.txt",
            "auth.example.com { reverse_proxy :9091 }\n",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-dmz"],
            ["caddy-dmz", "authelia"],
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifact = collector.get_artifacts_by_owner("caddy:dmz")[0]
        assert artifact.contributor_ref == "service:authelia"
        assert artifact.apply_hints == {"contributors": ["service:authelia"]}

    def test_registers_multiple_contributors_in_hints(
        self, tmp_path: Path, write_file: Any
    ) -> None:
        """Multiple ingress block contributors are tracked in apply_hints."""
        config_root = tmp_path / "config"
        rendered_root = tmp_path / "out" / "rendered"
        output_dir = rendered_root / "services"
        collector = ArtifactCollector()

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )
        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            "# DMZ\n",
        )

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  ingress:
    dmz:
      blocks:
        - caddy/dmz-ingress.txt
""",
        )
        write_file(
            config_root / "services" / "authelia" / "caddy" / "dmz-ingress.txt",
            "auth.example.com { reverse_proxy :9091 }\n",
        )

        write_file(
            config_root / "services" / "vault" / "service.yaml",
            """name: vault
composition:
  ingress:
    dmz:
      blocks:
        - caddy/dmz-ingress.txt
""",
        )
        write_file(
            config_root / "services" / "vault" / "caddy" / "dmz-ingress.txt",
            "vault.example.com { reverse_proxy :8200 }\n",
        )

        render_ingress_configs(
            "phobos",
            ["caddy-dmz"],
            ["caddy-dmz", "authelia", "vault"],
            config_root,
            output_dir,
            collector=collector,
            rendered_root=rendered_root,
        )

        artifact = collector.get_artifacts_by_owner("caddy:dmz")[0]
        assert artifact.contributor_ref is None
        assert artifact.apply_hints == {
            "contributors": [
                "service:authelia",
                "service:vault",
            ]
        }

    def test_missing_base_source_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Missing base Caddyfile source raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/dmz/Caddyfile
""",
        )

        # Don't create the Caddyfile

        with pytest.raises(RenderError, match="Base Caddyfile not found"):
            render_ingress_configs(
                "phobos",
                ["caddy-dmz"],
                ["caddy-dmz"],
                config_root,
                output_dir,
            )

    def test_missing_block_file_raises_error(self, tmp_path: Path, write_file: Any) -> None:
        """Missing ingress block file raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy-internal" / "service.yaml",
            """name: caddy-internal
composition:
  ingress:
    internal:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/internal/Caddyfile
""",
        )

        write_file(
            config_root / "services" / "caddy-internal" / "config" / "Caddyfile",
            "{ admin off }\n",
        )

        write_file(
            config_root / "services" / "authelia" / "service.yaml",
            """name: authelia
composition:
  ingress:
    internal:
      blocks:
        - caddy/missing.txt
""",
        )

        # Don't create the block file

        with pytest.raises(RenderError, match="Ingress block not found"):
            render_ingress_configs(
                "phobos",
                ["caddy-internal"],
                ["caddy-internal", "authelia"],
                config_root,
                output_dir,
            )

    def test_base_missing_source_or_destination(self, tmp_path: Path, write_file: Any) -> None:
        """Base definition missing source or destination raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        write_file(
            config_root / "services" / "caddy-dmz" / "service.yaml",
            """name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        # Missing destination
""",
        )

        write_file(
            config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
            "{ }\n",
        )

        with pytest.raises(RenderError, match="missing source or destination"):
            render_ingress_configs(
                "phobos",
                ["caddy-dmz"],
                ["caddy-dmz"],
                config_root,
                output_dir,
            )

    def test_service_without_yaml_raises_error(self, tmp_path: Path) -> None:
        """Service without service.yaml raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output" / "services"

        with pytest.raises(RenderError, match="Missing service definition"):
            render_ingress_configs(
                "phobos",
                ["nonexistent"],
                ["nonexistent"],
                config_root,
                output_dir,
            )
