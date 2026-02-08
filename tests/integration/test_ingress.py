"""Integration tests for ingress rendering with actual config."""

import sys
from pathlib import Path

import pytest

# Add lib/python to path for imports during tests
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent / "scripts" / "lib" / "python")
)

from renderers.ingress import render_ingress_configs
from utils.config import read_yaml


class TestIngressIntegration:
    """Integration tests using actual repository configuration."""

    def test_render_actual_phobos_ingress(self, tmp_path: Path) -> None:
        """Test rendering ingress for phobos with actual config."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        if not mapping_yaml.exists():
            pytest.skip(f"Test requires mapping.yaml at {mapping_yaml}")

        # Load mapping to get all services in mapping order
        mapping = read_yaml(mapping_yaml)
        all_services = []
        seen = set()
        for entries in mapping.get("abhaile", []):
            for _, services in entries.items():
                for svc in services:
                    name = svc
                    if isinstance(svc, dict):
                        if "name" in svc:
                            name = svc["name"]
                        elif len(svc) == 1:
                            name = next(iter(svc.keys()))
                    if isinstance(name, str) and name not in seen:
                        all_services.append(name)
                        seen.add(name)

        output_dir = tmp_path / "services"

        phobos_services = []
        for entries in mapping.get("abhaile", []):
            if "phobos" in entries:
                phobos_services = entries["phobos"]
                break

        render_ingress_configs(
            "phobos",
            phobos_services,
            all_services,
            config_root,
            output_dir,
        )

        # Verify caddy-dmz output
        caddy_dmz_file = output_dir / "caddy-dmz" / "srv/caddy/dmz/Caddyfile"
        if caddy_dmz_file.exists():
            content = caddy_dmz_file.read_text()

            # Should have base content
            assert "admin off" in content or "{" in content

            # Should have aggregated blocks marker if there are blocks
            services_with_dmz_blocks = []
            for service in all_services:
                service_yaml = config_root / "services" / service / "service.yaml"
                if service_yaml.exists():
                    data = read_yaml(service_yaml) or {}
                    ingress = data.get("composition", {}).get("ingress", {})
                    if "blocks" in ingress.get("dmz", {}):
                        services_with_dmz_blocks.append(service)

            if services_with_dmz_blocks:
                assert "Aggregated Ingress Blocks" in content

        # Verify caddy-internal output
        caddy_internal_file = (
            output_dir / "caddy-internal" / "srv/caddy/internal/Caddyfile"
        )
        if caddy_internal_file.exists():
            content = caddy_internal_file.read_text()

            # Should have base content
            assert "admin off" in content or "{" in content

            # Check for expected blocks
            services_with_internal_blocks = []
            for service in all_services:
                service_yaml = config_root / "services" / service / "service.yaml"
                if service_yaml.exists():
                    data = read_yaml(service_yaml) or {}
                    ingress = data.get("composition", {}).get("ingress", {})
                    if "blocks" in ingress.get("internal", {}):
                        services_with_internal_blocks.append(service)

            if services_with_internal_blocks:
                assert "Aggregated Ingress Blocks" in content

            # Authelia should be in internal ingress
            if "authelia" in all_services:
                authelia_yaml = config_root / "services" / "authelia" / "service.yaml"
                if authelia_yaml.exists():
                    data = read_yaml(authelia_yaml)
                    if "blocks" in data.get("composition", {}).get("ingress", {}).get(
                        "internal", {}
                    ):
                        assert "# --- authelia ---" in content
                        assert "authelia" in content.lower()

    def test_ingress_blocks_deterministic(self, tmp_path: Path) -> None:
        """Verify ingress rendering is deterministic across runs."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        if not mapping_yaml.exists():
            pytest.skip(f"Test requires mapping.yaml at {mapping_yaml}")

        mapping = read_yaml(mapping_yaml)
        all_services = []
        seen = set()
        for entries in mapping.get("abhaile", []):
            for _, services in entries.items():
                for svc in services:
                    name = svc
                    if isinstance(svc, dict):
                        if "name" in svc:
                            name = svc["name"]
                        elif len(svc) == 1:
                            name = next(iter(svc.keys()))
                    if isinstance(name, str) and name not in seen:
                        all_services.append(name)
                        seen.add(name)

        # Render twice
        output_dir1 = tmp_path / "run1" / "services"
        output_dir2 = tmp_path / "run2" / "services"

        phobos_services = []
        for entries in mapping.get("abhaile", []):
            if "phobos" in entries:
                phobos_services = entries["phobos"]
                break

        render_ingress_configs(
            "phobos", phobos_services, all_services, config_root, output_dir1
        )
        render_ingress_configs(
            "phobos", phobos_services, all_services, config_root, output_dir2
        )

        # Compare outputs
        for caddy_service in ["caddy-dmz", "caddy-internal"]:
            file1 = (
                output_dir1
                / caddy_service
                / "srv/caddy"
                / caddy_service.split("-")[1]
                / "Caddyfile"
            )
            file2 = (
                output_dir2
                / caddy_service
                / "srv/caddy"
                / caddy_service.split("-")[1]
                / "Caddyfile"
            )

            if file1.exists() and file2.exists():
                assert (
                    file1.read_text() == file2.read_text()
                ), f"Ingress output for {caddy_service} should be deterministic"

    def test_omada_multi_zone_blocks(self, tmp_path: Path) -> None:
        """Test that omada-controller blocks appear in both zones."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        omada_yaml = config_root / "services" / "omada-controller" / "service.yaml"
        if not omada_yaml.exists():
            pytest.skip(f"Test requires omada-controller service at {omada_yaml}")

        omada_data = read_yaml(omada_yaml)
        ingress = omada_data.get("composition", {}).get("ingress", {})

        has_dmz = "blocks" in ingress.get("dmz", {})
        has_internal = "blocks" in ingress.get("internal", {})

        if not (has_dmz or has_internal):
            pytest.skip("omada-controller doesn't define ingress blocks")

        mapping_yaml = config_root / "mapping.yaml"
        mapping = read_yaml(mapping_yaml)
        all_services = []
        seen = set()
        for entries in mapping.get("abhaile", []):
            for _, services in entries.items():
                for svc in services:
                    name = svc
                    if isinstance(svc, dict):
                        if "name" in svc:
                            name = svc["name"]
                        elif len(svc) == 1:
                            name = next(iter(svc.keys()))
                    if isinstance(name, str) and name not in seen:
                        all_services.append(name)
                        seen.add(name)

        output_dir = tmp_path / "services"

        render_ingress_configs(
            "phobos",
            ["caddy-dmz", "caddy-internal"],
            all_services,
            config_root,
            output_dir,
        )

        if has_dmz:
            dmz_file = output_dir / "caddy-dmz" / "srv/caddy/dmz/Caddyfile"
            if dmz_file.exists():
                content = dmz_file.read_text()
                assert "# --- omada-controller ---" in content

        if has_internal:
            internal_file = (
                output_dir / "caddy-internal" / "srv/caddy/internal/Caddyfile"
            )
            if internal_file.exists():
                content = internal_file.read_text()
                assert "# --- omada-controller ---" in content
