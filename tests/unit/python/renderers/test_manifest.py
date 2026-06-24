"""Tests for metadata-driven manifest generation and writing."""

import json
from pathlib import Path

import pytest

from abhaile.renderers.manifest import MANIFEST_VERSION, build_manifest, write_manifest
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError


class TestBuildManifest:
    """Tests for manifest generation."""

    def test_empty_metadata(self) -> None:
        """Manifest for empty metadata contains no entries/owners."""
        collector = ArtifactCollector()

        manifest = build_manifest("testhost", collector.get_metadata())

        assert manifest["version"] == MANIFEST_VERSION
        assert manifest["host"] == "testhost"
        assert "rendered_at" in manifest
        assert manifest["entries"] == []
        assert "owners" not in manifest

    def test_manifest_with_entries_and_owners(self, tmp_path: Path) -> None:
        """Manifest includes enriched entry fields and top-level owners."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir(parents=True)

        source_a = rendered_dir / "system" / "etc" / "a.conf"
        source_a.parent.mkdir(parents=True, exist_ok=True)
        source_a.write_text("a=1\n")

        source_b = rendered_dir / "services" / "demo" / "etc" / "b.conf"
        source_b.parent.mkdir(parents=True, exist_ok=True)
        source_b.write_text("b=2\n")

        collector = ArtifactCollector()
        collector.register_artifact(
            render_path="services/demo/etc/b.conf",
            target_path="/etc/demo/b.conf",
            kind="service.config",
            owner_ref="service:demo",
            content=source_b.read_bytes(),
            contributor_ref="service:base",
            apply_hints={"restart_mode": "try-restart"},
        )
        collector.register_artifact(
            render_path="system/etc/a.conf",
            target_path="/etc/a.conf",
            kind="systemd.unit",
            owner_ref="unit:a.service",
            content=source_a.read_bytes(),
        )
        collector.register_owner(
            name="service:demo",
            description="Demo service owner",
            requires=["unit:network-online.target", "unit:network-online.target"],
            apply_hints={"restart_mode": "try-restart"},
        )
        collector.compute_hashes_and_sizes(rendered_dir)

        manifest = build_manifest("testhost", collector.get_metadata())

        assert manifest["version"] == MANIFEST_VERSION
        assert [entry["render_path"] for entry in manifest["entries"]] == [
            "services/demo/etc/b.conf",
            "system/etc/a.conf",
        ]

        first = manifest["entries"][0]
        assert first["kind"] == "service.config"
        assert first["owner_ref"] == "service:demo"
        assert first["contributor_ref"] == "service:base"
        assert first["apply_hints"] == {"restart_mode": "try-restart"}
        assert len(first["sha256"]) == 64

        owners = manifest["owners"]
        assert owners["service:demo"]["name"] == "service:demo"
        assert owners["service:demo"]["description"] == "Demo service owner"
        assert owners["service:demo"]["requires"] == ["unit:network-online.target"]
        assert owners["service:demo"]["apply_hints"] == {"restart_mode": "try-restart"}

    def test_manifest_omits_optional_empty_fields(self, tmp_path: Path) -> None:
        """Optional fields are omitted when unset or empty."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir(parents=True)
        source = rendered_dir / "system" / "etc" / "noop.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("noop=1\n")

        collector = ArtifactCollector()
        collector.register_artifact(
            render_path="system/etc/noop.conf",
            target_path="/etc/noop.conf",
            kind="service.config",
            owner_ref="service:noop",
            content=source.read_bytes(),
        )
        collector.compute_hashes_and_sizes(rendered_dir)

        manifest = build_manifest("testhost", collector.get_metadata())

        entry = manifest["entries"][0]
        assert "contributor_ref" not in entry
        assert "apply_hints" not in entry
        assert "owners" not in manifest

    def test_manifest_serializes_directory_marker(self, tmp_path: Path) -> None:
        """Directory artifacts include an explicit marker for apply staging."""
        rendered_dir = tmp_path / "rendered"
        directory = rendered_dir / "system" / "etc" / "systemd" / "network" / "iface.network.d"
        directory.mkdir(parents=True)

        collector = ArtifactCollector()
        collector.register_artifact(
            render_path="system/etc/systemd/network/iface.network.d",
            target_path="/etc/systemd/network/iface.network.d",
            kind="networkd.network",
            owner_ref="iface:iface",
            content=b"",
            is_directory=True,
        )
        collector.compute_hashes_and_sizes(rendered_dir)

        manifest = build_manifest("testhost", collector.get_metadata())

        assert manifest["entries"][0]["is_directory"] is True

    def test_manifest_requires_hashes_computed(self, tmp_path: Path) -> None:
        """Manifest serialization fails closed when hashes are not computed."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir(parents=True)
        source = rendered_dir / "system" / "etc" / "app.conf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("a=1\n")

        collector = ArtifactCollector()
        collector.register_artifact(
            render_path="system/etc/app.conf",
            target_path="/etc/app.conf",
            kind="service.config",
            owner_ref="service:app",
            content=source.read_bytes(),
        )

        with pytest.raises(RenderError):
            build_manifest("testhost", collector.get_metadata())


class TestWriteManifest:
    """Tests for writing manifest to file."""

    def test_write_manifest_success(self, tmp_path):
        """Test successful manifest write."""
        manifest = {
            "version": "1",
            "host": "testhost",
            "rendered_at": "2026-03-11T00:00:00Z",
            "entries": [
                {
                    "render_path": "etc/config",
                    "target_path": "/etc/config",
                    "kind": "service.config",
                    "owner_ref": "service:test",
                    "sha256": "abc123",
                    "size": 100,
                }
            ],
        }

        manifest_path = tmp_path / "manifest.json"
        write_manifest(manifest, manifest_path)

        assert manifest_path.exists()

        # Verify JSON is valid and matches
        written = json.loads(manifest_path.read_text())
        assert written == manifest

    def test_write_manifest_parent_creation(self, tmp_path):
        """Test that parent directories are created if needed."""
        manifest = {
            "version": "1",
            "host": "testhost",
            "rendered_at": "2026-03-11T00:00:00Z",
            "entries": [],
        }
        manifest_path = tmp_path / "deep" / "nested" / "path" / "manifest.json"

        # Parent dirs don't exist yet
        assert not manifest_path.parent.exists()

        write_manifest(manifest, manifest_path)

        assert manifest_path.exists()
        assert manifest_path.parent.exists()

    def test_write_manifest_formatting(self, tmp_path):
        """Test that manifest JSON is properly formatted."""
        manifest = {
            "version": "1",
            "host": "testhost",
            "rendered_at": "2026-03-11T00:00:00Z",
            "entries": [
                {
                    "render_path": "etc/config",
                    "target_path": "/etc/config",
                    "kind": "service.config",
                    "owner_ref": "service:test",
                    "sha256": "abc123",
                    "size": 100,
                }
            ],
        }

        manifest_path = tmp_path / "manifest.json"
        write_manifest(manifest, manifest_path)

        content = manifest_path.read_text()
        # Should be indented (pretty-printed)
        assert "\n  " in content
        # Should end with newline
        assert content.endswith("\n")
