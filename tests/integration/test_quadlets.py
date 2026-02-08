"""Integration tests for quadlets rendering with actual config."""

import sys
from pathlib import Path

import pytest

# Add lib/python to path for imports during tests
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent / "scripts" / "lib" / "python")
)

from renderers.quadlets import render_service_quadlets
from utils.config import read_yaml


class TestQuadretsIntegration:
    """Integration tests using actual repository configuration."""

    def test_render_actual_blocky_service(self, tmp_path: Path) -> None:
        """Test rendering blocky service with actual config structure."""
        # Use __file__ to navigate from tests/ dir to repo root
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        blocky_yaml = config_root / "services" / "blocky" / "service.yaml"
        if not blocky_yaml.exists():
            pytest.skip(f"Test requires blocky service config at {blocky_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["blocky"],
            network,
            config_root,
            output_dir,
        )

        # Verify quadlet files exist
        service_dir = output_dir / "blocky" / "etc/containers/systemd"
        assert (service_dir / "blocky.container").exists()
        assert (service_dir / "blocky.image").exists()

        # Verify volume files for shared volumes
        shared_dir = output_dir / "_shared" / "etc/containers/systemd"
        assert (shared_dir / "host-certs.volume").exists()

    def test_render_actual_vault_service(self, tmp_path: Path) -> None:
        """Test rendering vault service with volumes."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        vault_yaml = config_root / "services" / "vault" / "service.yaml"
        if not vault_yaml.exists():
            pytest.skip(f"Test requires vault service config at {vault_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["vault"],
            network,
            config_root,
            output_dir,
        )

        service_dir = output_dir / "vault" / "etc/containers/systemd"
        assert (service_dir / "vault.container").exists()
        assert (service_dir / "vault.image").exists()
        assert (service_dir / "vault-config.volume").exists()
        assert (service_dir / "vault-data.volume").exists()

    def test_render_network_quadlets_for_vlans(self, tmp_path: Path) -> None:
        """Test that network quadlets are generated for used VLANs."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        blocky_yaml = config_root / "services" / "blocky" / "service.yaml"
        if not blocky_yaml.exists():
            pytest.skip(f"Test requires blocky service config at {blocky_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["blocky", "vault"],
            network,
            config_root,
            output_dir,
        )

        networks_dir = output_dir / "podman-networks" / "etc/containers/systemd"
        assert (networks_dir / "services.network").exists()

        # Verify network file is properly formatted
        network_content = (networks_dir / "services.network").read_text()
        assert "[Network]" in network_content
        assert "Driver=ipvlan" in network_content

    def test_deterministic_output(self, tmp_path: Path) -> None:
        """Test that rendering is deterministic (same input = same output)."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        blocky_yaml = config_root / "services" / "blocky" / "service.yaml"
        if not blocky_yaml.exists():
            pytest.skip(f"Test requires blocky service config at {blocky_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        network = read_yaml(network_yaml)

        # Render twice
        output_dir1 = tmp_path / "output1"
        output_dir2 = tmp_path / "output2"

        render_service_quadlets(
            "phobos", ["blocky"], network, config_root, output_dir1 / "services"
        )
        render_service_quadlets(
            "phobos", ["blocky"], network, config_root, output_dir2 / "services"
        )

        # Compare all rendered files
        container_file1 = (
            output_dir1
            / "services"
            / "blocky"
            / "etc/containers/systemd/blocky.container"
        )
        container_file2 = (
            output_dir2
            / "services"
            / "blocky"
            / "etc/containers/systemd/blocky.container"
        )

        assert container_file1.exists() and container_file2.exists()
        assert container_file1.read_text() == container_file2.read_text()

        image_file1 = (
            output_dir1 / "services" / "blocky" / "etc/containers/systemd/blocky.image"
        )
        image_file2 = (
            output_dir2 / "services" / "blocky" / "etc/containers/systemd/blocky.image"
        )

        assert image_file1.exists() and image_file2.exists()
        assert image_file1.read_text() == image_file2.read_text()

    def test_render_all_podman_services(self, tmp_path: Path) -> None:
        """Test rendering all podman services in mapping."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        mapping_yaml = config_root / "mapping.yaml"
        if not mapping_yaml.exists():
            pytest.skip(f"Test requires mapping.yaml at {mapping_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        mapping = read_yaml(mapping_yaml)
        network = read_yaml(network_yaml)

        # Extract services for phobos
        phobos_services = []
        for entry in mapping.get("abhaile", []):
            if isinstance(entry, dict) and "phobos" in entry:
                phobos_services = entry["phobos"]
                break

        if not phobos_services:
            pytest.skip("No services mapped to phobos")

        output_dir = tmp_path / "services"

        render_service_quadlets(
            "phobos",
            phobos_services,
            network,
            config_root,
            output_dir,
        )

        # Verify at least one quadlet was generated
        container_files = list(output_dir.glob("*/etc/containers/systemd/*.container"))
        assert len(container_files) > 0

    def test_render_actual_authelia_pod(self, tmp_path: Path) -> None:
        """Test rendering authelia pod service with actual config."""
        repo_root = Path(__file__).parent.parent.parent
        config_root = repo_root / "config"

        authelia_yaml = config_root / "services" / "authelia" / "service.yaml"
        if not authelia_yaml.exists():
            pytest.skip(f"Test requires authelia service config at {authelia_yaml}")

        network_yaml = config_root / "network.yaml"
        if not network_yaml.exists():
            pytest.skip(f"Test requires network.yaml at {network_yaml}")

        output_dir = tmp_path / "services"
        network = read_yaml(network_yaml)

        render_service_quadlets(
            "phobos",
            ["authelia"],
            network,
            config_root,
            output_dir,
        )

        # Verify pod quadlet exists with correct naming
        pod_file = (
            output_dir / "authelia" / "etc/containers/systemd" / "authelia-app.pod"
        )
        assert pod_file.exists(), "Pod quadlet should be named authelia-app.pod"

        pod_content = pod_file.read_text()
        assert "[Pod]" in pod_content
        assert "Network=" in pod_content

        # Verify authelia container exists with correct naming
        authelia_container = (
            output_dir
            / "authelia"
            / "etc/containers/systemd"
            / "authelia-app-authelia.container"
        )
        assert (
            authelia_container.exists()
        ), "Container should be named authelia-app-authelia.container"

        authelia_content = authelia_container.read_text()
        assert "Pod=authelia-app.pod" in authelia_content
        assert "[Container]" in authelia_content

        # Verify authelia image file
        authelia_image = (
            output_dir
            / "authelia"
            / "etc/containers/systemd"
            / "authelia-app-authelia.image"
        )
        assert (
            authelia_image.exists()
        ), "Image should be named authelia-app-authelia.image"

        # Verify redis container exists with correct naming
        redis_container = (
            output_dir
            / "authelia"
            / "etc/containers/systemd"
            / "authelia-app-redis.container"
        )
        assert (
            redis_container.exists()
        ), "Redis container should be named authelia-app-redis.container"

        redis_content = redis_container.read_text()
        assert "Pod=authelia-app.pod" in redis_content
        assert "[Container]" in redis_content

        # Verify redis image file
        redis_image = (
            output_dir
            / "authelia"
            / "etc/containers/systemd"
            / "authelia-app-redis.image"
        )
        assert (
            redis_image.exists()
        ), "Redis image should be named authelia-app-redis.image"

        # Verify volume files with correct naming pattern (service-app-container-volume)
        volume_files = list(
            (output_dir / "authelia" / "etc/containers/systemd").glob("*.volume")
        )
        assert len(volume_files) > 0, "Should have volume files for containers"

        # Check that volume names follow the pattern: authelia-app-{container}-{volume}.volume
        volume_names = [v.name for v in volume_files]
        assert any(
            "authelia-app-authelia-" in name for name in volume_names
        ), "Should have volume(s) for authelia container with authelia-app-authelia- prefix"
        assert any(
            "authelia-app-redis-" in name for name in volume_names
        ), "Should have volume(s) for redis container with authelia-app-redis- prefix"

        # Verify network quadlet
        network_file = (
            output_dir
            / "podman-networks"
            / "etc/containers/systemd"
            / "services.network"
        )
        assert (
            network_file.exists()
        ), "Network quadlet should be generated for pod's VLAN"
