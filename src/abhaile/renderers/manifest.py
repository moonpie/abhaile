"""Manifest generation: deterministic serialization from collected metadata."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from abhaile.models.artifact import OwnerMetadata, RenderMetadata, RenderedArtifact
from abhaile.models.kinds import ALL_KINDS
from abhaile.utils.errors import RenderError

LOG = logging.getLogger(__name__)
MANIFEST_VERSION = "1"


def build_manifest(host: str, metadata: RenderMetadata) -> dict[str, Any]:
    """Build manifest dict from collected render metadata."""
    entries = _serialize_entries(metadata)
    owners = _serialize_owners(metadata)

    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "host": host,
        "rendered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }
    if owners:
        manifest["owners"] = owners
    return manifest


def _serialize_entries(metadata: RenderMetadata) -> list[dict[str, Any]]:
    """Serialize artifact entries in deterministic render_path order."""
    entries: list[dict[str, Any]] = []
    artifacts: list[RenderedArtifact] = sorted(
        metadata.artifacts.values(),
        key=lambda artifact: artifact.render_path,
    )

    for artifact in artifacts:
        if artifact.hash is None or artifact.size is None:
            raise RenderError(
                "Artifact metadata missing hash/size before manifest serialization: "
                f"{artifact.render_path}"
            )
        if artifact.kind not in ALL_KINDS:
            raise RenderError(f"Unknown artifact kind '{artifact.kind}': {artifact.render_path}")

        entry: dict[str, Any] = {
            "render_path": artifact.render_path,
            "target_path": artifact.target_path,
            "kind": artifact.kind,
            "owner_ref": artifact.owner_ref,
            "sha256": artifact.hash,
            "size": artifact.size,
        }

        if artifact.contributor_ref:
            entry["contributor_ref"] = artifact.contributor_ref
        if artifact.apply_hints:
            entry["apply_hints"] = artifact.apply_hints

        entries.append(entry)

    return entries


def _serialize_owners(metadata: RenderMetadata) -> dict[str, dict[str, Any]]:
    """Serialize owners in deterministic key order, omitting empty optional fields."""
    serialized: dict[str, dict[str, Any]] = {}
    owners: list[OwnerMetadata] = sorted(
        metadata.owners.values(),
        key=lambda owner: owner.name,
    )

    for owner in owners:
        owner_entry: dict[str, Any] = {
            "name": owner.name,
        }
        if owner.description:
            owner_entry["description"] = owner.description
        if owner.requires:
            owner_entry["requires"] = sorted(set(owner.requires))
        if owner.apply_hints:
            owner_entry["apply_hints"] = owner.apply_hints

        serialized[owner.name] = owner_entry

    return serialized


def write_manifest(manifest: dict[str, Any], manifest_path: Path) -> None:
    """Write manifest JSON to disk."""
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        LOG.debug(
            "render.manifest entries=%d path=%s",
            len(manifest.get("entries", [])),
            manifest_path,
        )
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception as exc:
        raise RenderError(f"Failed to write manifest: {manifest_path} ({exc})") from exc
