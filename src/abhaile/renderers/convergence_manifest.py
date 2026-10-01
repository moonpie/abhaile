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
    identities = _execution_identities(metadata, artifacts)
    return {
        "schema_version": CONVERGENCE_MANIFEST_VERSION,
        "host": host,
        "rendered_root": ".",
        "execution_identities": identities,
        "entries": [_entry(artifact, artifacts, identities) for artifact in artifacts],
        "owners": {name: _owner(owners[name], artifacts) for name in sorted(owners)},
    }


def _execution_identities(
    metadata: RenderMetadata, artifacts: list[RenderedArtifact]
) -> dict[str, dict[str, object]]:
    required = {
        _context(artifact) for artifact in artifacts if _context(artifact).startswith("user:")
    }
    missing = required - set(metadata.execution_identities)
    if missing:
        raise RenderError(f"Named-user convergence lacks identity authority: {sorted(missing)}")
    return {name: metadata.execution_identities[name] for name in sorted(required)}


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
        "restart_authorities": _restart_authorities(owner.name, artifacts),
    }


def _entry(
    artifact: RenderedArtifact,
    artifacts: list[RenderedArtifact],
    identities: dict[str, dict[str, object]],
) -> dict[str, Any]:
    if artifact.hash is None or artifact.size is None:
        raise RenderError(f"Incomplete convergence artifact: {artifact.render_path}")
    hints = artifact.apply_hints or {}
    kind = "service.directory" if artifact.is_directory else artifact.kind
    entry: dict[str, Any] = {
        "render_path": artifact.render_path,
        "target_path": _target_path(artifact, kind, identities),
        "kind": kind,
        "action": _SOFTWARE_ACTIONS.get(kind, "create" if artifact.is_directory else "publish"),
        "owner_ref": artifact.owner_ref,
        "sha256": artifact.hash,
        "size": artifact.size,
        "execution_context": _context(artifact),
        "metadata": _metadata(
            artifact, hints, system_rootless_quadlet=_is_rootless_quadlet(artifact)
        ),
        "validation": _validation(kind),
        "lifecycle": _lifecycle(kind, hints),
        "lifecycle_metadata": _lifecycle_metadata(kind, hints, artifact, artifacts),
        "safe_prune": (
            "report-only"
            if artifact.kind.startswith("software.") or artifact.is_directory
            else "safe-if-unchanged"
        ),
    }
    return entry


def _metadata(
    artifact: RenderedArtifact, hints: dict[str, Any], *, system_rootless_quadlet: bool = False
) -> dict[str, Any]:
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
    if system_rootless_quadlet:
        return {"owner": "root", "group": "root", "mode": str(mode)}
    owner = hints.get("owner", hints.get("owner_user", hints.get("podman_user", "root")))
    group = hints.get("group", hints.get("owner_group", hints.get("podman_user", "root")))
    if not all(isinstance(value, (str, int)) for value in (mode, owner, group)):
        raise RenderError(f"Artifact has invalid file metadata: {artifact.render_path}")
    return {"owner": str(owner), "group": str(group), "mode": str(mode)}


def _is_rootless_quadlet(artifact: RenderedArtifact) -> bool:
    """Return whether v2 publishes this Quadlet from root-owned user authority."""
    return artifact.kind.startswith("quadlet.") and _context(artifact).startswith("user:")


def _target_path(
    artifact: RenderedArtifact,
    kind: str,
    identities: dict[str, dict[str, object]],
) -> str | None:
    """Select a race-safe v2 target without changing the legacy v1 target."""
    if kind.startswith("software."):
        return None
    if not _is_rootless_quadlet(artifact):
        return artifact.target_path
    context = _context(artifact)
    identity = identities.get(context)
    uid = None if identity is None else identity.get("uid")
    if type(uid) is not int or uid <= 0:
        raise RenderError("Rootless Quadlet lacks sealed numeric publication authority")
    return f"/etc/containers/systemd/users/{uid}/{Path(artifact.target_path).name}"


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
    if kind.startswith("systemd."):
        return "systemd"
    if kind.startswith("resolved."):
        return "resolved"
    if kind == "caddy.config":
        return "caddy"
    if kind == "coredns.config":
        return "coredns"
    if kind == "coredns.zone":
        return "coredns-zone"
    if kind.startswith("quadlet."):
        return "quadlet"
    if kind == "vault.config":
        return "vault-agent"
    if kind.startswith("software."):
        return "software-result"
    return "structural"


def _lifecycle(kind: str, hints: dict[str, Any]) -> list[str]:
    effects: list[str] = []
    if kind.startswith(("systemd.", "quadlet.")):
        effects.append("manager-reload")
    if _restart_metadata(hints):
        effects.append("service-restart")
    if kind.startswith("networkd."):
        effects.append("network-reconfigure")
    return sorted(effects)


def _lifecycle_metadata(
    kind: str,
    hints: dict[str, Any],
    artifact: RenderedArtifact,
    artifacts: list[RenderedArtifact],
) -> dict[str, Any]:
    restart = _restart_metadata(hints)
    if restart is None:
        return {}
    authority = _restart_authority(
        artifact.owner_ref, _context(artifact), restart["unit"], artifacts
    )
    return {"service-restart": {**restart, "authority_owner": authority}}


def _restart_metadata(hints: dict[str, Any]) -> dict[str, str] | None:
    unit = hints.get("restart_unit")
    mode = hints.get("restart_mode", "restart" if unit else None)
    if mode == "manual" or unit is None:
        return None
    if not isinstance(unit, str) or not unit or mode not in {"restart", "try-restart"}:
        raise RenderError("Service restart requires an explicit unit and bounded mode")
    return {"unit": unit, "mode": mode}


def _restart_authorities(owner: str, artifacts: list[RenderedArtifact]) -> list[dict[str, str]]:
    """Declare every exact restart authority used by one rendered owner."""
    values: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        if artifact.owner_ref != owner:
            continue
        restart = _restart_metadata(artifact.apply_hints or {})
        if restart is None:
            continue
        context = _context(artifact)
        authority_owner = _restart_authority(owner, context, restart["unit"], artifacts)
        value = {
            "unit": restart["unit"],
            "execution_context": context,
            "authority_owner": authority_owner,
        }
        if restart["unit"] in values and values[restart["unit"]] != value:
            raise RenderError(f"Restart authority is ambiguous: {restart['unit']}")
        values[restart["unit"]] = value
    return [values[name] for name in sorted(values)]


def _restart_authority(
    declaring_owner: str,
    context: str,
    unit: str,
    artifacts: list[RenderedArtifact],
) -> str:
    """Resolve a restart to one managed unit owner or explicit owner authority."""
    if unit in {"abhaile-runner.service", "abhaile-runner.timer"}:
        raise RenderError("The active runner cannot authorize its own restart")
    matches = [
        artifact
        for artifact in artifacts
        if _managed_unit_name(artifact) == unit and _context(artifact) == context
    ]
    if len(matches) > 1:
        raise RenderError(f"Restart unit authority is ambiguous: {unit}")
    if matches:
        authority_owner = matches[0].owner_ref
        service_name = declaring_owner.removeprefix("service:")
        if authority_owner == declaring_owner or (
            declaring_owner.startswith("service:")
            and authority_owner == f"unit:{service_name}.service"
        ):
            return authority_owner
        raise RenderError(f"Restart unit belongs to an unrelated owner: {unit}")
    if (
        declaring_owner in {"service:chrony-a", "service:chrony-b"}
        and context == "system"
        and unit == "chrony.service"
    ):
        return declaring_owner
    raise RenderError(f"Restart unit has no reviewed authority: {unit}")


def _managed_unit_name(artifact: RenderedArtifact) -> str | None:
    """Return the exact unit identity published by a unit or Quadlet artifact."""
    if artifact.kind == "systemd.unit":
        return Path(artifact.target_path).name
    if artifact.kind.startswith("quadlet.") and artifact.owner_ref.startswith("unit:"):
        return artifact.owner_ref.removeprefix("unit:")
    return None


def _owner_kind(name: str) -> str:
    prefix = name.partition(":")[0]
    if prefix in {"unit", "service", "iface", "user", "group", "software", "dns", "caddy"}:
        return prefix
    return "service"
