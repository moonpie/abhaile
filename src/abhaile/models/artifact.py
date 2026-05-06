"""Render-time artifact and owner models for metadata collection and planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RenderedArtifact:
    """Internal model for a rendered artifact before manifest serialization."""

    render_path: str
    target_path: str
    kind: str
    owner_ref: str
    content: bytes | str
    is_directory: bool = False
    hash: str | None = None
    size: int | None = None
    contributor_ref: str | None = None
    apply_hints: dict[str, Any] | None = None

    def content_bytes(self) -> bytes:
        """Return content as bytes, encoding if necessary."""
        if isinstance(self.content, bytes):
            return self.content
        return self.content.encode("utf-8")


@dataclass(frozen=True)
class OwnerMetadata:
    """Owner metadata for topological apply ordering."""

    name: str
    description: str = ""
    requires: list[str] = field(default_factory=list)
    apply_hints: dict[str, Any] | None = None


@dataclass
class RenderMetadata:
    """Collected metadata accumulated across all renderers during a single render pass."""

    artifacts: dict[str, RenderedArtifact] = field(default_factory=dict)
    owners: dict[str, OwnerMetadata] = field(default_factory=dict)

    def register_artifact(self, artifact: RenderedArtifact) -> None:
        """Register a single artifact.

        Args:
            artifact: The artifact to register.

        Raises:
            ValueError: If artifact already registered at render_path.
        """
        if artifact.render_path in self.artifacts:
            raise ValueError(f"Artifact already registered at {artifact.render_path}")
        self.artifacts[artifact.render_path] = artifact

    def register_owner(self, owner: OwnerMetadata) -> None:
        """Register owner metadata.

        Args:
            owner: The owner to register.

        Raises:
            ValueError: If owner already registered.
        """
        if owner.name in self.owners:
            raise ValueError(f"Owner already registered: {owner.name}")
        self.owners[owner.name] = owner

    def get_artifact_by_owner(self, owner_ref: str) -> list[RenderedArtifact]:
        """Get all artifacts owned by a specific owner.

        Args:
            owner_ref: The owner identifier.

        Returns:
            List of artifacts owned by this owner.
        """
        return [a for a in self.artifacts.values() if a.owner_ref == owner_ref]
