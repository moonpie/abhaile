"""Manifest generation: deterministic serialization from collected metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from abhaile.models.artifact import OwnerMetadata, RenderMetadata, RenderedArtifact
from abhaile.utils.errors import RenderError

MANIFEST_VERSION = "1"


def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of a file.

    Args:
        path: File path.

    Returns:
        Hex-encoded SHA256 hash.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(host: str, metadata: RenderMetadata) -> Dict[str, Any]:
    """Build enriched manifest from collector metadata.

    Args:
        host: Hostname for manifest safety checks.
        metadata: Collected render metadata with populated hashes/sizes.

    Returns:
        Manifest dictionary with version, host, rendered_at, entries, and owners.
    """
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


def _serialize_entries(metadata: RenderMetadata) -> List[Dict[str, Any]]:
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


def _serialize_owners(metadata: RenderMetadata) -> Dict[str, Dict[str, Any]]:
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


def write_manifest(manifest: Dict[str, Any], manifest_path: Path) -> None:
    """Write manifest to JSON file.

    Args:
        manifest: Manifest dictionary.
        manifest_path: Path to write manifest.

    Raises:
        RenderError: If write fails.
    """
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception as exc:
        raise RenderError(f"Failed to write manifest: {manifest_path} ({exc})") from exc
