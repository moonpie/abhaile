"""Shared helpers for resolving directory artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DirectoryMetadata:
    """Resolved owner/group/mode for a managed directory artifact."""

    owner: str
    group: str
    mode: str


def resolve_directory_metadata(
    kind: str, apply_hints: dict[str, Any] | None = None
) -> DirectoryMetadata:
    """Resolve effective directory metadata for a managed artifact kind."""
    hints = apply_hints if isinstance(apply_hints, dict) else {}

    owner = hints.get("owner")
    if owner is None or owner == "":
        if kind in {"service.directory", "networkd.dropin"}:
            podman_user = hints.get("podman_user")
            if kind == "service.directory" and isinstance(podman_user, str) and podman_user:
                owner = podman_user
            else:
                owner = "root"
        else:
            raise ValueError(f"Unsupported directory artifact kind: {kind}")

    group = hints.get("group")
    if group is None or group == "":
        if kind == "service.directory":
            group = owner if owner != "root" else "root"
        elif kind == "networkd.dropin":
            group = "root"
        else:
            raise ValueError(f"Unsupported directory artifact kind: {kind}")

    mode = hints.get("mode")
    if mode is None or mode == "":
        if kind == "service.directory":
            mode = "0750"
        elif kind == "networkd.dropin":
            mode = "0755"
        else:
            raise ValueError(f"Unsupported directory artifact kind: {kind}")

    if not isinstance(owner, str) or not owner:
        raise ValueError(f"Invalid owner apply hint for {kind}: {owner}")
    if not isinstance(group, str) or not group:
        raise ValueError(f"Invalid group apply hint for {kind}: {group}")
    if not isinstance(mode, str) or not mode:
        raise ValueError(f"Invalid mode apply hint for {kind}: {mode}")

    return DirectoryMetadata(owner=owner, group=group, mode=mode)


def directory_metadata_to_hints(metadata: DirectoryMetadata) -> dict[str, str]:
    """Convert resolved directory metadata to apply_hints payload."""
    return {"owner": metadata.owner, "group": metadata.group, "mode": metadata.mode}
