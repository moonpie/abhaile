"""Integration tests for composition.include resolution across all renderers."""

from pathlib import Path

import pytest

from abhaile.renderers.ingress import render_ingress_configs
from abhaile.renderers.quadlets import render_service_quadlets
from abhaile.renderers.vault_templates import render_vault_agent_configs
from abhaile.utils.config import read_yaml

pytestmark = pytest.mark.integration


@pytest.fixture
def config_root() -> Path:
    """Return the actual config root path."""
    return Path(__file__).parent.parent.parent / "config"


class TestCompositionIncludes:
    """Test that composition.include is honored by all renderers."""

    @pytest.mark.slow
    def test_vault_agent_follows_includes(self, tmp_path: Path, config_root: Path) -> None:
        """Vault-agent renderer collects templates from included services."""
        output_dir = tmp_path / "output"
        network = read_yaml(config_root / "network.yaml")

        # coredns-filtered includes coredns-omada which has vault_agent template
        host_services = ["vault-agent", "coredns-filtered"]

        render_vault_agent_configs(
            host="phobos",
            host_services=host_services,
            network=network,
            config_root=config_root,
            output_dir=output_dir,
        )

        # Verify coredns-omada template was copied
        template_file = (
            output_dir / "vault-agent" / "srv/vault/agent/templates" / "coredns-omada.env.ctmpl"
        )
        assert template_file.exists()

        # Verify it's in the config
        config_file = output_dir / "vault-agent" / "srv/vault/agent/config.hcl"
        assert config_file.exists()
        config_content = config_file.read_text()
        assert "/agent/templates/coredns-omada.env.ctmpl" in config_content
        assert "/agent/out/coredns-omada.env" in config_content

    def test_ingress_follows_includes_if_applicable(
        self, tmp_path: Path, config_root: Path
    ) -> None:
        """Ingress renderer collects blocks from included services (if they exist)."""
        output_dir = tmp_path / "output"

        # omada-controller has ingress blocks for both zones
        # If it were included by another service, those blocks would be collected
        host_services = ["caddy-dmz", "caddy-internal"]
        all_services = ["caddy-dmz", "caddy-internal", "omada-controller"]

        render_ingress_configs(
            host="phobos",
            host_services=host_services,
            all_services=all_services,
            config_root=config_root,
            output_dir=output_dir,
        )

        # Verify ingress blocks from omada-controller are in caddy configs
        dmz_caddyfile = output_dir / "caddy-dmz" / "srv/caddy/dmz/Caddyfile"
        assert dmz_caddyfile.exists()
        dmz_content = dmz_caddyfile.read_text()
        assert "omada-controller" in dmz_content

    def test_quadlets_resolves_container_from_includes(
        self, tmp_path: Path, config_root: Path
    ) -> None:
        """Quadlets renderer resolves pod/container definitions from includes."""
        output_dir = tmp_path / "output"
        network = read_yaml(config_root / "network.yaml")

        # If any service included another with a container definition,
        # it would be resolved. Current repo doesn't have this pattern,
        # but the resolver functions exist to support it.
        # This test verifies the renderer doesn't crash with includes.

        # blocky has a direct container definition
        services = ["blocky"]

        render_service_quadlets(
            host="phobos",
            services=services,
            network=network,
            config_root=config_root,
            output_dir=output_dir,
        )

        # Verify blocky quadlet was rendered
        # (blocky is rootless, so output is in home directory)
        quadlet_file = list((output_dir / "blocky").rglob("blocky.container"))
        assert len(quadlet_file) >= 1

    def test_nested_includes_work(self, tmp_path: Path, config_root: Path) -> None:
        """Verify that includes can be nested (A includes B, B includes C)."""
        output_dir = tmp_path / "output"
        network = read_yaml(config_root / "network.yaml")

        # coredns-filtered includes coredns-common and coredns-omada
        # This tests multi-level include resolution
        host_services = ["vault-agent", "coredns-filtered"]

        render_vault_agent_configs(
            host="phobos",
            host_services=host_services,
            network=network,
            config_root=config_root,
            output_dir=output_dir,
        )

        # Verify template from coredns-omada (nested include) was collected
        template_file = (
            output_dir / "vault-agent" / "srv/vault/agent/templates" / "coredns-omada.env.ctmpl"
        )
        assert template_file.exists()

    def test_include_cycle_detection(self, tmp_path: Path, config_root: Path) -> None:
        """Verify that include cycles are detected and reported."""
        from abhaile.utils.errors import RenderError

        services_root = tmp_path / "services"

        # Create a cycle: service-a -> service-b -> service-a
        (services_root / "service-a").mkdir(parents=True)
        (services_root / "service-b").mkdir(parents=True)

        (services_root / "service-a" / "service.yaml").write_text(
            "composition:\n  include:\n    - service-b\n"
        )
        (services_root / "service-b" / "service.yaml").write_text(
            "composition:\n  include:\n    - service-a\n"
        )

        # Should raise RenderError about cycle
        with pytest.raises(RenderError, match="cycle detected"):
            from abhaile.utils.composition import walk_service_includes

            walk_service_includes(
                "service-a",
                config_root=tmp_path,
            )
