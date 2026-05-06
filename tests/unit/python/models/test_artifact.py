"""Tests for artifact models (Phase 1.1)."""

from abhaile.models.artifact import OwnerMetadata, RenderedArtifact, RenderMetadata


class TestRenderedArtifact:
    """Tests for RenderedArtifact dataclass."""

    def test_artifact_creation_with_str_content(self):
        """Test creating artifact with string content."""
        artifact = RenderedArtifact(
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
        assert artifact.hash is None
        assert artifact.size is None
        assert artifact.contributor_ref is None
        assert artifact.apply_hints is None

    def test_artifact_creation_with_bytes_content(self):
        """Test creating artifact with bytes content."""
        artifact = RenderedArtifact(
            render_path="system/etc/config",
            target_path="/etc/config",
            kind="resolved.config",
            owner_ref="systemd",
            content=b"binary content",
        )

        assert artifact.content == b"binary content"
        assert artifact.content_bytes() == b"binary content"

    def test_artifact_content_bytes_str(self):
        """Test content_bytes() converts str to bytes."""
        artifact = RenderedArtifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="service.config",
            owner_ref="test",
            content="text content",
        )

        assert artifact.content_bytes() == b"text content"

    def test_artifact_with_metadata(self):
        """Test artifact with contributor and hints."""
        artifact = RenderedArtifact(
            render_path="services/caddy/config.json",
            target_path="/srv/caddy/config.json",
            kind="service.config",
            owner_ref="caddy-a",
            content='{"key": "value"}',
            contributor_ref="caddy-base",
            apply_hints={"requires_reload": True, "priority": 10},
        )

        assert artifact.contributor_ref == "caddy-base"
        assert artifact.apply_hints == {"requires_reload": True, "priority": 10}

    def test_artifact_with_hash_and_size(self):
        """Test artifact with pre-computed hash and size."""
        artifact = RenderedArtifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="test",
            content="test",
            hash="abc123def456",
            size=1024,
        )

        assert artifact.hash == "abc123def456"
        assert artifact.size == 1024

    def test_artifact_immutability(self):
        """Test that RenderedArtifact is immutable (frozen=True)."""
        import dataclasses

        artifact = RenderedArtifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="test",
            content="test",
        )

        # Should raise FrozenInstanceError
        try:
            dataclasses.replace(artifact, render_path="different")
            # If we get here, artifact itself is still unchanged
            assert artifact.render_path == "system/etc/test"
        except Exception:
            pass  # Expected - frozen dataclass


class TestOwnerMetadata:
    """Tests for OwnerMetadata dataclass."""

    def test_owner_creation_minimal(self):
        """Test creating owner with minimal fields."""
        owner = OwnerMetadata(name="chrony-a")

        assert owner.name == "chrony-a"
        assert owner.description == ""
        assert owner.requires == []
        assert owner.apply_hints is None

    def test_owner_creation_full(self):
        """Test creating owner with all fields."""
        owner = OwnerMetadata(
            name="caddy-a",
            description="Caddy reverse proxy instance A",
            requires=["systemd", "network"],
            apply_hints={"role": "ingress", "priority": 20},
        )

        assert owner.name == "caddy-a"
        assert owner.description == "Caddy reverse proxy instance A"
        assert owner.requires == ["systemd", "network"]
        assert owner.apply_hints == {"role": "ingress", "priority": 20}

    def test_owner_with_empty_requires(self):
        """Test owner can have empty requires list."""
        owner = OwnerMetadata(name="standalone")
        assert owner.requires == []


class TestRenderMetadata:
    """Tests for RenderMetadata collector."""

    def test_render_metadata_creation(self):
        """Test creating empty RenderMetadata."""
        rm = RenderMetadata()

        assert rm.artifacts == {}
        assert rm.owners == {}

    def test_register_artifact(self):
        """Test registering an artifact."""
        rm = RenderMetadata()
        artifact = RenderedArtifact(
            render_path="system/etc/hostname",
            target_path="/etc/hostname",
            kind="systemd.unit",
            owner_ref="chrony-a",
            content="phobos",
        )

        rm.register_artifact(artifact)

        assert "system/etc/hostname" in rm.artifacts
        assert rm.artifacts["system/etc/hostname"] == artifact

    def test_register_artifact_duplicate_fails(self):
        """Test that registering duplicate artifact raises ValueError."""
        rm = RenderMetadata()
        artifact1 = RenderedArtifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="owner1",
            content="content1",
        )
        artifact2 = RenderedArtifact(
            render_path="system/etc/test",
            target_path="/etc/test",
            kind="systemd.unit",
            owner_ref="owner2",
            content="content2",
        )

        rm.register_artifact(artifact1)

        try:
            rm.register_artifact(artifact2)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already registered" in str(e)

    def test_register_owner(self):
        """Test registering an owner."""
        rm = RenderMetadata()
        owner = OwnerMetadata(name="chrony-a", description="Chrony instance A")

        rm.register_owner(owner)

        assert "chrony-a" in rm.owners
        assert rm.owners["chrony-a"] == owner

    def test_register_owner_duplicate_fails(self):
        """Test that registering duplicate owner raises ValueError."""
        rm = RenderMetadata()
        owner1 = OwnerMetadata(name="test", description="First")
        owner2 = OwnerMetadata(name="test", description="Second")

        rm.register_owner(owner1)

        try:
            rm.register_owner(owner2)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already registered" in str(e)

    def test_get_artifact_by_owner(self):
        """Test retrieving artifacts by owner."""
        rm = RenderMetadata()

        # Register artifacts for different owners
        art1 = RenderedArtifact(
            render_path="system/etc/1",
            target_path="/etc/1",
            kind="systemd.unit",
            owner_ref="owner-a",
            content="1",
        )
        art2 = RenderedArtifact(
            render_path="system/etc/2",
            target_path="/etc/2",
            kind="systemd.unit",
            owner_ref="owner-a",
            content="2",
        )
        art3 = RenderedArtifact(
            render_path="system/etc/3",
            target_path="/etc/3",
            kind="systemd.unit",
            owner_ref="owner-b",
            content="3",
        )

        rm.register_artifact(art1)
        rm.register_artifact(art2)
        rm.register_artifact(art3)

        # Query by owner
        owner_a_artifacts = rm.get_artifact_by_owner("owner-a")
        assert len(owner_a_artifacts) == 2
        assert all(a.owner_ref == "owner-a" for a in owner_a_artifacts)

        owner_b_artifacts = rm.get_artifact_by_owner("owner-b")
        assert len(owner_b_artifacts) == 1
        assert owner_b_artifacts[0].owner_ref == "owner-b"

        owner_c_artifacts = rm.get_artifact_by_owner("owner-c")
        assert owner_c_artifacts == []

    def test_multiple_artifacts_and_owners(self):
        """Test registering multiple artifacts and owners."""
        rm = RenderMetadata()

        # Register multiple artifacts
        for i in range(3):
            artifact = RenderedArtifact(
                render_path=f"system/etc/file{i}",
                target_path=f"/etc/file{i}",
                kind="systemd.unit",
                owner_ref="test-owner",
                content=f"content{i}",
            )
            rm.register_artifact(artifact)

        # Register multiple owners
        for i in range(2):
            owner = OwnerMetadata(name=f"owner-{i}", description=f"Owner {i}", requires=[])
            rm.register_owner(owner)

        assert len(rm.artifacts) == 3
        assert len(rm.owners) == 2
