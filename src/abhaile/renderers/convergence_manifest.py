"""Build the strict manifest v2 convergence contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from abhaile.models.artifact import OwnerMetadata, RenderMetadata, RenderedArtifact
from abhaile.utils.errors import RenderError

CONVERGENCE_MANIFEST_VERSION = 2
CONVERGENCE_MANIFEST_NAME = "convergence-manifest.json"

_SOFTWARE_ACTIONS = {
    "software.packages": "install",
    "software.download": "fetch",
    "software.build": "build",
    "software.prerequisite": "ensure",
}


def build_convergence_manifest(host: str, metadata: RenderMetadata) -> dict[str, Any]:
    """Build a deterministic, complete manifest for future convergence."""
    artifacts = sorted(metadata.artifacts.values(), key=lambda artifact: artifact.render_path)
    owners = _complete_owners(metadata, artifacts)
    return {
        "schema_version": CONVERGENCE_MANIFEST_VERSION,
        "host": host,
        "rendered_root": ".",
        "entries": [_entry(artifact) for artifact in artifacts],
        "owners": {name: _owner(owners[name], artifacts) for name in sorted(owners)},
    }


def write_convergence_manifest(manifest: dict[str, Any], path: Path) -> None:
    """Write deterministic convergence manifest JSON."""
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        raise RenderError(f"Failed to write convergence manifest: {path} ({exc})") from exc


def _complete_owners(
    metadata: RenderMetadata, artifacts: list[RenderedArtifact]
) -> dict[str, OwnerMetadata]:
    owners = dict(metadata.owners)
    for artifact in artifacts:
        owners.setdefault(
            artifact.owner_ref,
            OwnerMetadata(
                name=artifact.owner_ref,
                description=f"Rendered owner {artifact.owner_ref}",
            ),
        )
    return owners


def _owner(owner: OwnerMetadata, artifacts: list[RenderedArtifact]) -> dict[str, Any]:
    owned = [artifact for artifact in artifacts if artifact.owner_ref == owner.name]
    contexts = {_context(artifact) for artifact in owned}
    return {
        "name": owner.name,
        "owner_kind": _owner_kind(owner.name),
        "execution_context": (
            "orchestrator" if len(contexts) > 1 else next(iter(contexts), "system")
        ),
        "requires": sorted(set(owner.requires)),
    }


def _entry(artifact: RenderedArtifact) -> dict[str, Any]:
    if artifact.hash is None or artifact.size is None:
        raise RenderError(f"Incomplete convergence artifact: {artifact.render_path}")
    hints = artifact.apply_hints or {}
    kind = "service.directory" if artifact.is_directory else artifact.kind
    entry: dict[str, Any] = {
        "render_path": artifact.render_path,
        "target_path": None if kind.startswith("software.") else artifact.target_path,
        "kind": kind,
        "action": _SOFTWARE_ACTIONS.get(kind, "create" if artifact.is_directory else "publish"),
        "owner_ref": artifact.owner_ref,
        "sha256": artifact.hash,
        "size": artifact.size,
        "execution_context": _context(artifact),
        "metadata": _metadata(artifact, hints),
        "validation": _validation(kind),
        "lifecycle": _lifecycle(kind, hints),
        "safe_prune": (
            "report-only"
            if artifact.kind.startswith("software.") or artifact.is_directory
            else "safe-if-unchanged"
        ),
    }
    return entry


def _metadata(artifact: RenderedArtifact, hints: dict[str, Any]) -> dict[str, Any]:
    if artifact.kind.startswith("software."):
        operation_type = hints.get("operation_type")
        operation_id = hints.get("operation_id")
        if not isinstance(operation_type, str) or not operation_type:
            raise RenderError(f"Software artifact lacks operation type: {artifact.render_path}")
        if not isinstance(operation_id, str) or not operation_id:
            raise RenderError(f"Software artifact lacks operation id: {artifact.render_path}")
        effects = hints.get("effects")
        policy = hints.get("execution_policy")
        if not isinstance(effects, list) or not isinstance(policy, str):
            raise RenderError(f"Software artifact lacks explicit effects: {artifact.render_path}")
        return {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "execution_policy": policy,
            "effects": effects,
        }
    mode = hints.get("mode", "0750" if artifact.is_directory else "0644")
    owner = hints.get("owner", hints.get("owner_user", hints.get("podman_user", "root")))
    group = hints.get("group", hints.get("owner_group", hints.get("podman_user", "root")))
    if not all(isinstance(value, (str, int)) for value in (mode, owner, group)):
        raise RenderError(f"Artifact has invalid file metadata: {artifact.render_path}")
    return {"owner": str(owner), "group": str(group), "mode": str(mode)}


def _context(artifact: RenderedArtifact) -> str:
    hints = artifact.apply_hints or {}
    if hints.get("rootless") is True:
        user = hints.get("podman_user")
        if not isinstance(user, str) or not user or user == "root":
            raise RenderError(f"Rootless artifact lacks an explicit user: {artifact.render_path}")
        return f"user:{user}"
    return "system"


def _validation(kind: str) -> str:
    if kind == "host.sudoers":
        return "sudoers"
    if kind == "host.sysusers":
        return "sysusers"
    if kind.startswith("systemd.") or kind.startswith("resolved."):
        return "systemd"
    if kind == "coredns.zone":
        return "coredns-zone"
    if kind.startswith("software."):
        return "software-result"
    return "structural"


def _lifecycle(kind: str, hints: dict[str, Any]) -> list[str]:
    effects: list[str] = []
    if kind.startswith(("systemd.", "quadlet.")):
        effects.append("manager-reload")
    if hints.get("restart_mode") or hints.get("restart_unit"):
        effects.append("service-restart")
    if kind.startswith("networkd."):
        effects.append("network-reconfigure")
    return sorted(effects)


def _owner_kind(name: str) -> str:
    prefix = name.partition(":")[0]
    if prefix in {"unit", "service", "iface", "user", "group", "software", "dns", "caddy"}:
        return prefix
    return "service"
