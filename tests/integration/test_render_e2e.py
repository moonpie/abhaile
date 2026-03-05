"""End-to-end integration tests for render pipeline."""

import json
from pathlib import Path

import pytest

from abhaile.renderers.manifest import build_manifest, write_manifest

pytestmark = pytest.mark.integration


class TestRenderE2E:
    """End-to-end render pipeline tests."""

    def test_render_single_host_with_manifest(self, tmp_repo_with_config, tmp_output):
        """Test rendering a single host produces valid manifest."""
        # repo_root = tmp_repo_with_config
        output_dir = tmp_output

        # Simulate rendering: create some dummy files in rendered dir
        rendered_dir = output_dir / "rendered"
        rendered_dir.mkdir(parents=True)

        # Create sample rendered files
        (rendered_dir / "systemd-networkd.conf").write_text("# Network config\n")
        (rendered_dir / "quadlet.container").write_text("[Container]\n")

        # Build and write manifest
        manifest = build_manifest(rendered_dir, target_root=Path("/"))
        state_dir = output_dir / "state"
        state_dir.mkdir(parents=True)
        manifest_path = state_dir / "manifest.json"
        write_manifest(manifest, manifest_path)

        # Verify manifest exists and is valid JSON
        assert manifest_path.exists()
        with open(manifest_path) as f:
            loaded = json.load(f)

        assert "rendered_at" in loaded
        assert "artifacts" in loaded
        assert len(loaded["artifacts"]) == 2

        # Verify artifacts are sorted by rel_path
        rel_paths = [a["rel_path"] for a in loaded["artifacts"]]
        assert rel_paths == sorted(rel_paths)

    def test_render_all_hosts_separate_manifests(self, tmp_repo_with_config, tmp_output):
        """Test rendering all hosts produces separate manifests per host."""
        # repo_root = tmp_repo_with_config
        output_dir = tmp_output

        # Simulate rendering phobos and deimos separately
        for host in ["phobos", "deimos"]:
            rendered_dir = output_dir / host / "rendered"
            rendered_dir.mkdir(parents=True)

            # Create sample host-specific files
            (rendered_dir / f"{host}-network.conf").write_text("# Config\n")

            state_dir = output_dir / host / "state"
            state_dir.mkdir(parents=True)

            manifest = build_manifest(rendered_dir, target_root=Path("/"))
            manifest_path = state_dir / "manifest.json"
            write_manifest(manifest, manifest_path)

            assert manifest_path.exists()

        # Verify both manifests exist and are independent
        phobos_manifest = json.loads(
            (output_dir / "phobos" / "state" / "manifest.json").read_text()
        )
        deimos_manifest = json.loads(
            (output_dir / "deimos" / "state" / "manifest.json").read_text()
        )

        assert phobos_manifest["artifacts"][0]["rel_path"] == "phobos-network.conf"
        assert deimos_manifest["artifacts"][0]["rel_path"] == "deimos-network.conf"

    def test_render_empty_dir_produces_empty_manifest(self, tmp_output):
        """Test that rendering an empty directory produces valid empty manifest."""
        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        state_dir = tmp_output / "state"
        state_dir.mkdir(parents=True)

        manifest = build_manifest(rendered_dir, target_root=Path("/"))
        manifest_path = state_dir / "manifest.json"
        write_manifest(manifest, manifest_path)

        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text())
        assert loaded["artifacts"] == []

    def test_manifest_preserves_file_permissions(self, tmp_output):
        """Test that manifest records file permissions correctly."""
        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        # Create a file with specific permissions
        test_file = rendered_dir / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello\n")
        test_file.chmod(0o755)

        # Build manifest
        manifest = build_manifest(rendered_dir, target_root=Path("/"))

        # Verify mode is recorded (as octal string)
        artifact = manifest["artifacts"][0]
        assert "mode" in artifact
        # Mode should be recorded as octal string (e.g., "0755")
        assert artifact["mode"] == "0755"

    def test_manifest_contains_valid_sha256_hashes(self, tmp_output):
        """Test that manifest contains valid SHA256 hashes."""
        import hashlib

        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        # Create test file with known content
        test_file = rendered_dir / "config.yaml"
        content = "test: value\n"
        test_file.write_text(content)

        # Build manifest
        manifest = build_manifest(rendered_dir, target_root=Path("/"))

        # Verify hash matches
        artifact = manifest["artifacts"][0]
        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        assert artifact["sha256"] == expected_hash

    def test_render_with_nested_directories(self, tmp_output):
        """Test rendering nested directory structures preserves paths."""
        rendered_dir = tmp_output / "rendered"

        # Create nested structure
        (rendered_dir / "systemd" / "system").mkdir(parents=True)
        (rendered_dir / "systemd-networkd" / "networks").mkdir(parents=True)
        (rendered_dir / "systemd" / "system" / "service.service").write_text("[Unit]\n")
        (rendered_dir / "systemd-networkd" / "networks" / "eth0.network").write_text("[Match]\n")

        state_dir = tmp_output / "state"
        state_dir.mkdir(parents=True)

        # Build and write manifest
        manifest = build_manifest(rendered_dir, target_root=Path("/"))
        manifest_path = state_dir / "manifest.json"
        write_manifest(manifest, manifest_path)

        # Verify nested paths are preserved in manifest
        loaded = json.loads(manifest_path.read_text())
        rel_paths = {a["rel_path"] for a in loaded["artifacts"]}

        assert "systemd/system/service.service" in rel_paths
        assert "systemd-networkd/networks/eth0.network" in rel_paths

    def test_manifest_determinism_multiple_runs(self, tmp_output):
        """Test that rendering same content multiple times produces identical manifest."""
        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        # Create test files
        (rendered_dir / "config1.yaml").write_text("config: 1\n")
        (rendered_dir / "config2.yaml").write_text("config: 2\n")

        state_dir = tmp_output / "state"
        state_dir.mkdir(parents=True)

        # Generate manifest twice
        manifest1 = build_manifest(rendered_dir, target_root=Path("/"))
        write_manifest(manifest1, state_dir / "manifest1.json")

        manifest2 = build_manifest(rendered_dir, target_root=Path("/"))
        write_manifest(manifest2, state_dir / "manifest2.json")

        # Load both manifests and verify they're identical
        m1_content = (state_dir / "manifest1.json").read_text()
        m2_content = (state_dir / "manifest2.json").read_text()

        # Parse to compare (timestamps will be close but might differ slightly)
        m1 = json.loads(m1_content)
        m2 = json.loads(m2_content)

        # Artifacts should be identical
        assert m1["artifacts"] == m2["artifacts"]

    def test_render_services_configs(self, tmp_repo_with_config, tmp_output):
        """Test that service configs are rendered correctly for mapped services."""
        repo_root = tmp_repo_with_config
        output_dir = tmp_output

        # Add a service with static and templated configs
        services_root = repo_root / "config" / "services"
        test_service_dir = services_root / "test-service"
        test_service_dir.mkdir(parents=True, exist_ok=True)

        # Create service.yaml
        (test_service_dir / "service.yaml").write_text("""name: test-service
composition:
  config:
    - source: test-service/config/static.conf
      destination: /etc/test/static.conf
    - source:
        template: test-service/config/app.conf.j2
        variables:
          service_ip: '%%network.services.test-service.address | strip_cidr%%'
      destination: /etc/test/app.conf
""")

        # Create static config
        config_dir = test_service_dir / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "static.conf").write_text("# Static config\nenabled=true\n")

        # Create template
        (config_dir / "app.conf.j2").write_text(
            "# App config\nhost={{ host_name }}\nservice={{ service_name }}\nbind={{ service.config.service_ip }}\n"
        )

        # Import and use the full render pipeline
        from abhaile.renderers.services import render_service_configs
        from abhaile.utils.config import read_yaml

        network = read_yaml(repo_root / "config" / "network.yaml")
        rendered_dir = output_dir / "rendered"
        services_output_dir = rendered_dir / "services"

        render_service_configs(
            "phobos",
            ["test-service"],
            network,
            repo_root / "config",
            services_output_dir,
        )

        # Verify static config was copied
        static_output = services_output_dir / "test-service" / "etc/test/static.conf"
        assert static_output.exists()
        assert static_output.read_text() == "# Static config\nenabled=true\n"

        # Verify templated config was rendered with correct substitutions
        template_output = services_output_dir / "test-service" / "etc/test/app.conf"
        assert template_output.exists()
        content = template_output.read_text()
        assert "host=phobos" in content
        assert "service=test-service" in content
        assert "bind=172.20.20.200" in content
