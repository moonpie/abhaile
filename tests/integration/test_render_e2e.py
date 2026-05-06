"""End-to-end integration tests for render pipeline."""

import json
from pathlib import Path

import pytest

from abhaile.renderers.manifest import build_manifest, write_manifest
from abhaile.utils.artifact_collector import ArtifactCollector

pytestmark = pytest.mark.integration


def _collect_metadata_from_rendered(rendered_dir: Path) -> ArtifactCollector:
    """Collect rendered files as generic artifacts for integration tests."""
    collector = ArtifactCollector()

    for file_path in sorted(rendered_dir.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue

        render_path = file_path.relative_to(rendered_dir).as_posix()
        collector.register_artifact(
            render_path=render_path,
            target_path=f"/{render_path}",
            kind="service.config",
            owner_ref="service:test",
            content=file_path.read_bytes(),
        )

    collector.compute_hashes_and_sizes(rendered_dir)
    return collector


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
        collector = _collect_metadata_from_rendered(rendered_dir)
        manifest = build_manifest("testhost", collector.get_metadata())
        manifest_path = rendered_dir / "manifest.json"
        write_manifest(manifest, manifest_path)

        # Verify manifest exists and is valid JSON
        assert manifest_path.exists()
        with open(manifest_path) as f:
            loaded = json.load(f)

        assert loaded["host"] == "testhost"
        assert loaded["version"] == "1"
        assert "rendered_at" in loaded
        assert "entries" in loaded
        assert len(loaded["entries"]) == 2

        # Verify entries are sorted by render_path
        render_paths = [e["render_path"] for e in loaded["entries"]]
        assert render_paths == sorted(render_paths)

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

            collector = _collect_metadata_from_rendered(rendered_dir)
            manifest = build_manifest(host, collector.get_metadata())
            manifest_path = rendered_dir / "manifest.json"
            write_manifest(manifest, manifest_path)

            assert manifest_path.exists()

        # Verify both manifests exist and are independent
        phobos_manifest = json.loads(
            (output_dir / "phobos" / "rendered" / "manifest.json").read_text()
        )
        deimos_manifest = json.loads(
            (output_dir / "deimos" / "rendered" / "manifest.json").read_text()
        )

        assert phobos_manifest["host"] == "phobos"
        assert deimos_manifest["host"] == "deimos"
        assert "rendered_at" in phobos_manifest
        assert "rendered_at" in deimos_manifest
        # Verify host-specific files are in correct manifests
        phobos_paths = [e["target_path"] for e in phobos_manifest["entries"]]
        deimos_paths = [e["target_path"] for e in deimos_manifest["entries"]]
        assert any("phobos-network.conf" in p for p in phobos_paths)
        assert any("deimos-network.conf" in p for p in deimos_paths)

    def test_render_empty_dir_produces_empty_manifest(self, tmp_output):
        """Test that rendering an empty directory produces valid empty manifest."""
        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        collector = _collect_metadata_from_rendered(rendered_dir)
        manifest = build_manifest("testhost", collector.get_metadata())
        manifest_path = rendered_dir / "manifest.json"
        write_manifest(manifest, manifest_path)

        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text())
        assert loaded["entries"] == []

    def test_manifest_contains_hashes(self, tmp_output):
        """Test that manifest records file hashes correctly."""
        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        # Create a file
        test_file = rendered_dir / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello\n")
        test_file.chmod(0o755)

        # Build manifest
        collector = _collect_metadata_from_rendered(rendered_dir)
        manifest = build_manifest("testhost", collector.get_metadata())

        # Verify hash is recorded
        entry = manifest["entries"][0]
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64  # SHA256 is 64 hex chars

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
        collector = _collect_metadata_from_rendered(rendered_dir)
        manifest = build_manifest("testhost", collector.get_metadata())

        # Verify hash matches
        entry = manifest["entries"][0]
        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        assert entry["sha256"] == expected_hash

    def test_render_with_nested_directories(self, tmp_output):
        """Test rendering nested directory structures preserves paths."""
        rendered_dir = tmp_output / "rendered"

        # Create nested structure
        (rendered_dir / "systemd" / "system").mkdir(parents=True)
        (rendered_dir / "systemd-networkd" / "networks").mkdir(parents=True)
        (rendered_dir / "systemd" / "system" / "service.service").write_text("[Unit]\n")
        (rendered_dir / "systemd-networkd" / "networks" / "eth0.network").write_text("[Match]\n")

        # Build and write manifest
        collector = _collect_metadata_from_rendered(rendered_dir)
        manifest = build_manifest("testhost", collector.get_metadata())
        manifest_path = rendered_dir / "manifest.json"
        write_manifest(manifest, manifest_path)

        # Verify nested paths are preserved in manifest
        loaded = json.loads(manifest_path.read_text())
        target_paths = {e["target_path"] for e in loaded["entries"]}

        assert "/systemd/system/service.service" in target_paths
        assert "/systemd-networkd/networks/eth0.network" in target_paths

    def test_manifest_determinism_multiple_runs(self, tmp_output):
        """Test that rendering same content multiple times produces identical manifest."""
        rendered_dir = tmp_output / "rendered"
        rendered_dir.mkdir(parents=True)

        # Create test files
        (rendered_dir / "config1.yaml").write_text("config: 1\n")
        (rendered_dir / "config2.yaml").write_text("config: 2\n")

        # Generate manifest twice; write outside rendered_dir to avoid polluting entries
        collector1 = _collect_metadata_from_rendered(rendered_dir)
        manifest1 = build_manifest("testhost", collector1.get_metadata())
        write_manifest(manifest1, tmp_output / "manifest1.json")

        collector2 = _collect_metadata_from_rendered(rendered_dir)
        manifest2 = build_manifest("testhost", collector2.get_metadata())
        write_manifest(manifest2, tmp_output / "manifest2.json")

        # Load both manifests and verify they're identical
        m1_content = (tmp_output / "manifest1.json").read_text()
        m2_content = (tmp_output / "manifest2.json").read_text()

        # Parse to compare
        m1 = json.loads(m1_content)
        m2 = json.loads(m2_content)

        # Entries should be identical
        assert m1["entries"] == m2["entries"]

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
