"""Artifact collection coordinator for render pipeline.

Accumulates artifacts and owners from all renderers during a single render pass,
deferring hash computation until all files are written.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from abhaile.models.artifact import OwnerMetadata, RenderedArtifact, RenderMetadata


class ArtifactCollector:
    """Central coordinator for artifact collection during render.

    Attributes:
        _metadata: Internal RenderMetadata storage.
    """

    def __init__(self) -> None:
        """Initialize a new artifact collector."""
        self._metadata = RenderMetadata()

    def register_artifact(
        self,
        render_path: str,
        target_path: str,
        kind: str,
        owner_ref: str,
        content: bytes | str,
        *,
        is_directory: bool = False,
        replace: bool = False,
        contributor_ref: str | None = None,
        apply_hints: dict[str, Any] | None = None,
    ) -> RenderedArtifact:
        """Register a single artifact for collection.

        Args:
            replace: If True, overwrite existing artifact with same render_path.
        """
        artifact = RenderedArtifact(
            render_path=render_path,
            target_path=target_path,
            kind=kind,
            owner_ref=owner_ref,
            content=content,
            is_directory=is_directory,
            contributor_ref=contributor_ref,
            apply_hints=apply_hints,
        )
        if replace and render_path in self._metadata.artifacts:
            self._metadata.artifacts[render_path] = artifact
        else:
            self._metadata.register_artifact(artifact)

        return artifact

    def register_owner(
        self,
        name: str,
        description: str = "",
        requires: list[str] | None = None,
        apply_hints: dict[str, Any] | None = None,
    ) -> OwnerMetadata:
        """Register owner metadata for topological ordering."""
        owner = OwnerMetadata(
            name=name,
            description=description,
            requires=requires or [],
            apply_hints=apply_hints,
        )
        self._metadata.register_owner(owner)
        return owner

    def get_metadata(self) -> RenderMetadata:
        """Get the accumulated metadata."""
        return self._metadata

    def compute_hashes_and_sizes(self, rendered_dir: Path) -> None:
        """Compute hashes and sizes for all registered artifacts.

        Called after all artifacts are registered but before manifest serialization.
        """
        # Assert target_path uniqueness across all artifacts
        seen_targets: dict[str, str] = {}
        for artifact in self._metadata.artifacts.values():
            target = artifact.target_path
            if target in seen_targets:
                raise ValueError(
                    f"Duplicate target_path '{target}': "
                    f"render_path={artifact.render_path} conflicts with "
                    f"render_path={seen_targets[target]}"
                )
            seen_targets[target] = artifact.render_path

        for artifact in self._metadata.artifacts.values():
            artifact_path = rendered_dir / artifact.render_path

            if artifact.is_directory:
                if not artifact_path.exists() or not artifact_path.is_dir():
                    raise FileNotFoundError(
                        f"Artifact directory not found: {artifact_path} "
                        f"(render_path={artifact.render_path})"
                    )
                updated = RenderedArtifact(
                    render_path=artifact.render_path,
                    target_path=artifact.target_path,
                    kind=artifact.kind,
                    owner_ref=artifact.owner_ref,
                    content="",
                    is_directory=True,
                    hash=hashlib.sha256(b"").hexdigest(),
                    size=0,
                    contributor_ref=artifact.contributor_ref,
                    apply_hints=artifact.apply_hints,
                )
                self._metadata.artifacts[artifact.render_path] = updated
                continue

            if not artifact_path.exists():
                raise FileNotFoundError(
                    f"Artifact file not found: {artifact_path} "
                    f"(render_path={artifact.render_path})"
                )

            # Compute hash
            digest = hashlib.sha256()
            with artifact_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            file_hash = digest.hexdigest()

            # Get size
            file_size = artifact_path.stat().st_size

            # Update artifact with computed values
            # Since RenderedArtifact is frozen, we need to reconstruct it
            updated = RenderedArtifact(
                render_path=artifact.render_path,
                target_path=artifact.target_path,
                kind=artifact.kind,
                owner_ref=artifact.owner_ref,
                content=artifact.content,
                is_directory=False,
                hash=file_hash,
                size=file_size,
                contributor_ref=artifact.contributor_ref,
                apply_hints=artifact.apply_hints,
            )
            self._metadata.artifacts[artifact.render_path] = updated

    def get_artifacts_by_owner(self, owner_ref: str) -> list[RenderedArtifact]:
        """Get all artifacts owned by a specific owner."""
        return self._metadata.get_artifact_by_owner(owner_ref)

    def get_all_artifacts(self) -> list[RenderedArtifact]:
        """Get all registered artifacts sorted by render_path."""
        artifacts = list(self._metadata.artifacts.values())
        artifacts.sort(key=lambda a: a.render_path)
        return artifacts

    def get_all_owners(self) -> dict[str, OwnerMetadata]:
        """Get all registered owners."""
        return dict(self._metadata.owners)


class NullCollector:
    """No-op collector that discards all registrations."""

    def register_artifact(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Discard artifact registration."""

    def register_owner(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Discard owner registration."""

    def get_all_owners(self) -> dict[str, OwnerMetadata]:
        """Return empty owners dict."""
        return {}

    def get_all_artifacts(self) -> list[RenderedArtifact]:
        """Return empty artifacts list."""
        return []

    def get_artifacts_by_owner(self, owner_ref: str) -> list[RenderedArtifact]:  # noqa: ARG002
        """Return empty list for any owner."""
        return []
