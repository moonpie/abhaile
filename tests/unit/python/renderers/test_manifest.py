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

        manifest = build_manifest(rendered_dir, target_root)

        assert "rendered_at" in manifest
        assert manifest["artifacts"] == []

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
        manifest = build_manifest(rendered_dir, target_root)

        assert len(manifest["artifacts"]) == 2
        # Check deterministic ordering by rel_path
        rel_paths = [a["rel_path"] for a in manifest["artifacts"]]
        assert rel_paths == sorted(rel_paths)

    def test_manifest_rel_and_target_paths(self, tmp_path):
        """Test that rel_path and target_path are correct."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        (rendered_dir / "etc").mkdir()
        (rendered_dir / "etc" / "config").write_text("test")

        target_root = Path("/")
        manifest = build_manifest(rendered_dir, target_root)

        artifact = manifest["artifacts"][0]
        assert artifact["rel_path"] == "etc/config"
        assert artifact["target_path"] == "/etc/config"

    def test_manifest_file_metadata(self, tmp_path):
        """Test that manifest includes correct file metadata."""
        rendered_dir = tmp_path / "rendered"
        rendered_dir.mkdir()
        test_file = rendered_dir / "test.txt"
        test_file.write_text("test content")

        target_root = Path("/")
        manifest = build_manifest(rendered_dir, target_root)

        artifact = manifest["artifacts"][0]
        assert artifact["size"] == len("test content")
        assert "sha256" in artifact
        assert len(artifact["sha256"]) == 64  # SHA256 hex is 64 chars
        assert artifact["mode"] is not None
        assert artifact["uid"] is not None
        assert artifact["gid"] is not None

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
        manifest1 = build_manifest(rendered_dir1, target_root)
        manifest2 = build_manifest(rendered_dir2, target_root)

        # Same files in different order should produce same artifact order
        assert len(manifest1["artifacts"]) == len(manifest2["artifacts"])
        for a1, a2 in zip(manifest1["artifacts"], manifest2["artifacts"]):
            assert a1["rel_path"] == a2["rel_path"]
            assert a1["sha256"] == a2["sha256"]


class TestWriteManifest:
    """Tests for writing manifest to file."""

    def test_write_manifest_success(self, tmp_path):
        """Test successful manifest write."""
        manifest = {
            "rendered_at": "2026-02-01T12:00:00Z",
            "artifacts": [
                {
                    "target_path": "/etc/config",
                    "rel_path": "etc/config",
                    "sha256": "abc123",
                    "size": 100,
                    "mode": "0644",
                    "uid": 0,
                    "gid": 0,
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
        manifest = {"rendered_at": "2026-02-01T12:00:00Z", "artifacts": []}
        manifest_path = tmp_path / "deep" / "nested" / "path" / "manifest.json"

        # Parent dirs don't exist yet
        assert not manifest_path.parent.exists()

        write_manifest(manifest, manifest_path)

        assert manifest_path.exists()
        assert manifest_path.parent.exists()

    def test_write_manifest_formatting(self, tmp_path):
        """Test that manifest JSON is properly formatted."""
        manifest = {
            "rendered_at": "2026-02-01T12:00:00Z",
            "artifacts": [
                {
                    "target_path": "/etc/config",
                    "rel_path": "etc/config",
                    "sha256": "abc123",
                    "size": 100,
                    "mode": "0644",
                    "uid": 0,
                    "gid": 0,
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
