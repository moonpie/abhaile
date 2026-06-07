"""Tests for ArtifactCollector (Phase 1.2)."""

import tempfile
from pathlib import Path

from abhaile.renderers.collector import ArtifactCollector


class TestArtifactCollector:
    """Tests for ArtifactCollector coordinator."""

    def test_collector_creation(self):
        """Test creating a new artifact collector."""
        collector = ArtifactCollector()

        assert collector.get_all_artifacts() == []
        assert collector.get_all_owners() == {}

    def test_register_artifact_str_content(self):
        """Test registering artifact with string content."""
        collector = ArtifactCollector()

        artifact = collector.register_artifact(
            render_path="system/etc/hostname",
            target_path="/etc/hostname",
            kind="systemd.unit",
            owner_ref="chrony-a",
            content="phobos",
        )

        assert artifact.render_path == "system/etc/hostname"
        assert artifact.target_path == "/etc/hostname"
        assert artifact.kind == "systemd.unit"
        assert artifact.owner_ref == "chrony-a"
        assert artifact.content == "phobos"
        assert artifact.hash is None  # Not computed yet
        assert artifact.size is None

    def test_register_artifact_bytes_content(self):
        """Test registering artifact with bytes content."""
        collector = ArtifactCollector()

        artifact = collector.register_artifact(
            render_path="system/etc/config",
            target_path="/etc/config",
            kind="resolved.config",
            owner_ref="systemd",
            content=b"binary",
        )

        assert artifact.content == b"binary"

    def test_register_artifact_with_contributor(self):
        """Test registering artifact with contributor attribution."""
        collector = ArtifactCollector()

        artifact = collector.register_artifact(
            render_path="services/caddy/config.json",
            target_path="/srv/caddy/config.json",
            kind="service.config",
            owner_ref="caddy-a",
            content='{"key": "value"}',
            contributor_ref="caddy-base",
        )

        assert artifact.contributor_ref == "caddy-base"

    def test_register_artifact_with_hints(self):
        """Test registering artifact with apply hints."""
        collector = ArtifactCollector()

        artifact = collector.register_artifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="test",
            content="test",
            apply_hints={"requires_reload": True},
        )

        assert artifact.apply_hints == {"requires_reload": True}

    def test_register_duplicate_artifact_fails(self):
        """Test that registering duplicate artifacts fails."""
        collector = ArtifactCollector()

        collector.register_artifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="owner1",
            content="content1",
        )

        try:
            collector.register_artifact(
                render_path="system/etc/test",
                target_path="/etc/test",
                kind="systemd.unit",
                owner_ref="owner2",
                content="content2",
            )
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already registered" in str(e)

    def test_register_owner(self):
        """Test registering owner metadata."""
        collector = ArtifactCollector()

        owner = collector.register_owner(
            name="chrony-a",
            description="Chrony instance A",
            requires=["systemd"],
        )

        assert owner.name == "chrony-a"
        assert owner.description == "Chrony instance A"
        assert owner.requires == ["systemd"]

    def test_register_owner_minimal(self):
        """Test registering owner with minimal fields."""
        collector = ArtifactCollector()

        owner = collector.register_owner(name="test")

        assert owner.name == "test"
        assert owner.description == ""
        assert owner.requires == []

    def test_register_duplicate_owner_fails(self):
        """Test that registering duplicate owners fails."""
        collector = ArtifactCollector()

        collector.register_owner(name="test")

        try:
            collector.register_owner(name="test")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already registered" in str(e)

    def test_get_all_artifacts_sorted(self):
        """Test that get_all_artifacts returns sorted list."""
        collector = ArtifactCollector()

        # Register artifacts in non-alphabetical order
        collector.register_artifact(
            render_path="system/etc/z",
            target_path="/etc/z",
            kind="systemd.unit",
            owner_ref="test",
            content="z",
        )
        collector.register_artifact(
            render_path="system/etc/a",
            target_path="/etc/a",
            kind="systemd.unit",
            owner_ref="test",
            content="a",
        )

        artifacts = collector.get_all_artifacts()

        assert len(artifacts) == 2
        assert artifacts[0].render_path == "system/etc/a"
        assert artifacts[1].render_path == "system/etc/z"

    def test_get_artifacts_by_owner(self):
        """Test filtering artifacts by owner."""
        collector = ArtifactCollector()

        collector.register_artifact(
            render_path="system/etc/1",
            target_path="/etc/1",
            kind="systemd.unit",
            owner_ref="owner-a",
            content="1",
        )
        collector.register_artifact(
            render_path="system/etc/2",
            target_path="/etc/2",
            kind="systemd.unit",
            owner_ref="owner-a",
            content="2",
        )
        collector.register_artifact(
            render_path="system/etc/3",
            target_path="/etc/3",
            kind="systemd.unit",
            owner_ref="owner-b",
            content="3",
        )

        owner_a = collector.get_artifacts_by_owner("owner-a")
        assert len(owner_a) == 2
        assert all(a.owner_ref == "owner-a" for a in owner_a)

    def test_get_all_owners(self):
        """Test retrieving all registered owners."""
        collector = ArtifactCollector()

        collector.register_owner(name="owner-1")
        collector.register_owner(name="owner-2")

        owners = collector.get_all_owners()

        assert len(owners) == 2
        assert "owner-1" in owners
        assert "owner-2" in owners

    def test_compute_hashes_and_sizes(self):
        """Test hash and size computation for artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered_dir = Path(tmpdir) / "rendered"
            rendered_dir.mkdir()

            # Create test files
            (rendered_dir / "system").mkdir()
            (rendered_dir / "system" / "test1").write_text("content1")
            (rendered_dir / "system" / "test2").write_bytes(b"content2")

            collector = ArtifactCollector()
            collector.register_artifact(
                render_path="system/test1",
                target_path="/etc/test1",
                kind="systemd.unit",
                owner_ref="test",
                content="content1",
            )
            collector.register_artifact(
                render_path="system/test2",
                target_path="/etc/test2",
                kind="systemd.unit",
                owner_ref="test",
                content=b"content2",
            )

            # Compute hashes
            collector.compute_hashes_and_sizes(rendered_dir)

            artifacts = collector.get_all_artifacts()
            assert all(a.hash is not None for a in artifacts)
            assert all(a.size is not None for a in artifacts)
            assert artifacts[0].size == 8  # "content1"
            assert artifacts[1].size == 8  # "content2"

    def test_compute_hashes_file_not_found(self):
        """Test that compute_hashes_and_sizes fails if file missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered_dir = Path(tmpdir) / "rendered"
            rendered_dir.mkdir()

            collector = ArtifactCollector()
            collector.register_artifact(
                render_path="system/missing",
                target_path="/etc/missing",
                kind="systemd.unit",
                owner_ref="test",
                content="content",
            )

            # File doesn't exist, should raise
            try:
                collector.compute_hashes_and_sizes(rendered_dir)
                assert False, "Should have raised FileNotFoundError"
            except FileNotFoundError as e:
                assert "not found" in str(e)

    def test_get_metadata(self):
        """Test getting raw metadata object."""
        collector = ArtifactCollector()

        collector.register_artifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="test",
            content="test",
        )
        collector.register_owner(name="test")

        metadata = collector.get_metadata()

        assert len(metadata.artifacts) == 1
        assert len(metadata.owners) == 1

    def test_full_workflow(self):
        """Test complete collector workflow: register, compute, retrieve."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered_dir = Path(tmpdir) / "rendered"
            rendered_dir.mkdir(parents=True)

            # Create files
            (rendered_dir / "system").mkdir()
            (rendered_dir / "system" / "hostname").write_text("host1")
            (rendered_dir / "system" / "resolv.conf").write_text("nameserver 8.8.8.8")

            collector = ArtifactCollector()

            # Register artifacts
            collector.register_artifact(
                render_path="system/hostname",
                target_path="/etc/hostname",
                kind="systemd.unit",
                owner_ref="chrony",
                content="host1",
            )
            collector.register_artifact(
                render_path="system/resolv.conf",
                target_path="/etc/resolv.conf",
                kind="resolved.config",
                owner_ref="systemd-resolved",
                content="nameserver 8.8.8.8",
            )

            # Register owners
            collector.register_owner(
                name="chrony", description="Chrony NTP service", requires=["systemd"]
            )
            collector.register_owner(name="systemd-resolved", description="DNS resolver")

            # Compute hashes
            collector.compute_hashes_and_sizes(rendered_dir)

            # Verify final state
            artifacts = collector.get_all_artifacts()
            assert len(artifacts) == 2
            assert all(a.hash is not None for a in artifacts)
            assert all(a.size is not None for a in artifacts)

            owners = collector.get_all_owners()
            assert len(owners) == 2
            assert owners["chrony"].requires == ["systemd"]
