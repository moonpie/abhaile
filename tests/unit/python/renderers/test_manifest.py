"""Tests for scripts/lib/python/renderers modules."""

import json
from pathlib import Path

from abhaile.renderers.manifest import build_manifest, write_manifest


class TestBuildManifest:
    """Tests for manifest generation."""

    def test_empty_rendered_dir(self, tmp_path):
        """Test manifest for empty rendered directory."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        target_root = Path("/")

        manifest = build_manifest("testhost", rendered_dir, target_root)

        assert manifest["host"] == "testhost"
        assert "rendered_at" in manifest
        assert manifest["entries"] == []

    def test_manifest_with_files(self, tmp_path):
        """Test manifest generation with files."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()

        # Create some test files
        (rendered_dir / "etc").mkdir()
        (rendered_dir / "etc" / "config.txt").write_text("content1")
        (rendered_dir / "var").mkdir()
        (rendered_dir / "var" / "data.json").write_text("content2")

        target_root = Path("/")
        manifest = build_manifest("testhost", rendered_dir, target_root)

        assert len(manifest["entries"]) == 2
        # Check deterministic ordering by rel_path
        rel_paths = [e["rel_path"] for e in manifest["entries"]]
        assert rel_paths == sorted(rel_paths)

    def test_manifest_target_path(self, tmp_path):
        """Test that target_path is correct."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        (rendered_dir / "etc").mkdir()
        (rendered_dir / "etc" / "config").write_text("test")

        target_root = Path("/")
        manifest = build_manifest("testhost", rendered_dir, target_root)

        entry = manifest["entries"][0]
        assert entry["rel_path"] == "etc/config"
        assert entry["target_path"] == "/etc/config"

    def test_manifest_target_path_from_rendered_layout(self, tmp_path):
        """Test target path mapping from rendered layout prefixes."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()

        (rendered_dir / "system" / "etc").mkdir(parents=True)
        (rendered_dir / "system" / "etc" / "example.conf").write_text("a")

        (rendered_dir / "users" / "etc").mkdir(parents=True)
        (rendered_dir / "users" / "etc" / "sysusers.d").mkdir(parents=True)
        (rendered_dir / "users" / "etc" / "sysusers.d" / "abhaile.conf").write_text("b")

        (rendered_dir / "services" / "caddy-dmz" / "etc").mkdir(parents=True)
        (rendered_dir / "services" / "caddy-dmz" / "etc" / "Caddyfile").write_text("c")

        manifest = build_manifest("testhost", rendered_dir, Path("/"))
        by_rel = {entry["rel_path"]: entry["target_path"] for entry in manifest["entries"]}

        assert by_rel["system/etc/example.conf"] == "/etc/example.conf"
        assert by_rel["users/etc/sysusers.d/abhaile.conf"] == "/etc/sysusers.d/abhaile.conf"
        assert by_rel["services/caddy-dmz/etc/Caddyfile"] == "/etc/Caddyfile"

    def test_manifest_file_metadata(self, tmp_path):
        """Test that manifest includes correct file metadata."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        test_file = rendered_dir / "test.txt"
        test_file.write_text("test content")

        target_root = Path("/")
        manifest = build_manifest("testhost", rendered_dir, target_root)

        entry = manifest["entries"][0]
        assert "rel_path" in entry
        assert entry["size"] == len("test content")
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64  # SHA256 hex is 64 chars

    def test_manifest_determinism(self, tmp_path):
        """Test that same input produces same manifest."""
        rendered_dir1 = tmp_path / "rendered1"
        rendered_dir1.mkdir()
        (rendered_dir1 / "a.txt").write_text("content")
        (rendered_dir1 / "b.txt").write_text("content")

        rendered_dir2 = tmp_path / "rendered2"
        rendered_dir2.mkdir()
        (rendered_dir2 / "b.txt").write_text("content")
        (rendered_dir2 / "a.txt").write_text("content")

        target_root = Path("/")
        manifest1 = build_manifest("testhost", rendered_dir1, target_root)
        manifest2 = build_manifest("testhost", rendered_dir2, target_root)

        # Same files in different order should produce same entry order
        assert len(manifest1["entries"]) == len(manifest2["entries"])
        for e1, e2 in zip(manifest1["entries"], manifest2["entries"]):
            assert e1["rel_path"] == e2["rel_path"]
            assert e1["target_path"] == e2["target_path"]
            assert e1["sha256"] == e2["sha256"]


class TestWriteManifest:
    """Tests for writing manifest to file."""

    def test_write_manifest_success(self, tmp_path):
        """Test successful manifest write."""
        manifest = {
            "host": "testhost",
            "rendered_at": "2026-03-11T00:00:00Z",
            "entries": [
                {
                    "rel_path": "etc/config",
                    "target_path": "/etc/config",
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
        manifest = {"host": "testhost", "rendered_at": "2026-03-11T00:00:00Z", "entries": []}
        manifest_path = tmp_path / "deep" / "nested" / "path" / "manifest.json"

        # Parent dirs don't exist yet
        assert not manifest_path.parent.exists()

        write_manifest(manifest, manifest_path)

        assert manifest_path.exists()
        assert manifest_path.parent.exists()

    def test_write_manifest_formatting(self, tmp_path):
        """Test that manifest JSON is properly formatted."""
        manifest = {
            "host": "testhost",
            "rendered_at": "2026-03-11T00:00:00Z",
            "entries": [
                {
                    "rel_path": "etc/config",
                    "target_path": "/etc/config",
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
