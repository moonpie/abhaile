"""Validate a rendered manifest inside an isolated capsule."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from abhaile.models.kinds import ALL_KINDS
from abhaile.models.software import PACKAGE, SoftwareEffect, parse_software_operation
from abhaile.trust.errors import TrustError
from abhaile.trust.securefs import SecureEntry, snapshot_tree
from abhaile.utils.errors import RenderError

SHA256 = re.compile(r"^[0-9a-f]{64}$")
ENTRY_KEYS = frozenset(
    {
        "render_path",
        "target_path",
        "kind",
        "owner_ref",
        "sha256",
        "size",
        "contributor_ref",
        "apply_hints",
        "is_directory",
    }
)
OWNER_KEYS = frozenset({"name", "description", "requires", "apply_hints"})
MANIFEST_KEYS = frozenset({"version", "host", "rendered_at", "entries", "owners"})
CONVERGENCE_MANIFEST = "convergence-manifest.json"
V2_KEYS = frozenset({"schema_version", "host", "rendered_root", "entries", "owners"})
V2_ENTRY_KEYS = frozenset(
    {
        "render_path",
        "target_path",
        "kind",
        "action",
        "owner_ref",
        "sha256",
        "size",
        "execution_context",
        "metadata",
        "validation",
        "lifecycle",
        "safe_prune",
    }
)
V2_OWNER_KEYS = frozenset({"name", "owner_kind", "execution_context", "requires"})
V2_ACTIONS = frozenset({"publish", "create", "install", "fetch", "build", "ensure"})
V2_VALIDATIONS = frozenset(
    {"structural", "sudoers", "sysusers", "systemd", "coredns-zone", "software-result"}
)
V2_LIFECYCLE = frozenset({"manager-reload", "service-restart", "network-reconfigure"})
V2_PRUNE = frozenset({"safe-if-unchanged", "report-only"})
V2_SOFTWARE_OPERATIONS = {
    "software.packages": frozenset({"packages"}),
    "software.download": frozenset({"binary-download", "archive-download"}),
    "software.build": frozenset({"container-build"}),
    "software.prerequisite": frozenset(
        {
            "kernel-modules",
            "systemd-units",
            "network-backend",
            "resolver",
            "unattended-upgrades",
            "udev-rule",
        }
    ),
}


def validate_manifest(rendered: Path, host: str) -> dict[str, Any]:
    """Validate manifest structure, artifact completeness, paths, hashes, and sizes."""
    return validate_manifest_snapshot(snapshot_tree(rendered), host)


def validate_manifest_snapshot(snapshot: dict[str, SecureEntry], host: str) -> dict[str, Any]:
    """Validate the v1 structural contract against one stable tree snapshot."""
    if CONVERGENCE_MANIFEST in snapshot:
        return validate_convergence_manifest_snapshot(snapshot, host)
    manifest_entry = snapshot.get("manifest.json")
    if manifest_entry is None or manifest_entry.kind != "file" or manifest_entry.content is None:
        raise TrustError("Required capsule file is unavailable: manifest.json")
    try:
        manifest = json.loads(manifest_entry.content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrustError("Rendered manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != "1":
        raise TrustError("Unsupported rendered manifest schema")
    if not set(manifest).issubset(MANIFEST_KEYS):
        raise TrustError("Rendered manifest contains unsupported top-level fields")
    rendered_at = manifest.get("rendered_at")
    if rendered_at is not None and (not isinstance(rendered_at, str) or not rendered_at):
        raise TrustError("Rendered manifest timestamp is invalid")
    if manifest.get("host") != host:
        raise TrustError("Rendered manifest host does not match requested host")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise TrustError("Rendered manifest entries must be a list")
    owners = _validate_owners(manifest.get("owners", {}))
    expected_files = {"manifest.json"}
    expected_directories: set[str] = set()
    seen_render: set[str] = set()
    seen_target: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise TrustError("Rendered manifest entry must be an object")
        if not set(entry).issubset(ENTRY_KEYS):
            raise TrustError("Manifest entry contains unsupported fields")
        render_path = entry.get("render_path")
        target_path = entry.get("target_path")
        digest = entry.get("sha256")
        size = entry.get("size")
        kind = entry.get("kind")
        owner_ref = entry.get("owner_ref")
        contributor_ref = entry.get("contributor_ref")
        apply_hints = entry.get("apply_hints")
        is_directory = entry.get("is_directory", False)
        if not isinstance(render_path, str) or not _safe_relative(render_path):
            raise TrustError("Manifest contains an unsafe render path")
        if not isinstance(target_path, str) or not _safe_absolute(target_path):
            raise TrustError("Manifest contains an unsafe target path")
        if render_path in seen_render:
            raise TrustError("Manifest contains a duplicate render path")
        if target_path in seen_target:
            raise TrustError("Manifest contains a duplicate target path")
        seen_render.add(render_path)
        seen_target.add(target_path)
        if kind not in ALL_KINDS:
            raise TrustError("Manifest contains an unsupported artifact kind")
        if not isinstance(owner_ref, str) or not _valid_owner_ref(owner_ref, owners):
            raise TrustError("Manifest contains an unknown owner reference")
        if contributor_ref is not None and (
            not isinstance(contributor_ref, str) or not contributor_ref
        ):
            raise TrustError("Manifest contains an invalid contributor reference")
        if apply_hints is not None and not isinstance(apply_hints, dict):
            raise TrustError("Manifest contains invalid apply hints")
        if not isinstance(is_directory, bool):
            raise TrustError("Manifest contains an invalid directory marker")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise TrustError("Manifest contains an invalid artifact size")
        if is_directory != (kind == "service.directory"):
            raise TrustError("Manifest directory marker and artifact kind disagree")
        artifact = snapshot.get(render_path)
        if is_directory:
            if digest != hashlib.sha256(b"").hexdigest() or size != 0:
                raise TrustError(
                    "Manifest directory must have the empty-content hash and zero size"
                )
            if artifact is None or artifact.kind != "directory":
                raise TrustError(f"Capsule directory must be a real directory: {render_path}")
            expected_directories.add(render_path)
        else:
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise TrustError("Manifest contains an invalid artifact hash")
            if artifact is None or artifact.kind != "file" or artifact.content is None:
                raise TrustError(f"Capsule file must be a regular unlinked file: {render_path}")
            if len(artifact.content) != size or _sha256(artifact) != digest:
                raise TrustError(f"Rendered artifact does not match manifest: {render_path}")
            expected_files.add(render_path)
    actual_files = {path for path, entry in snapshot.items() if entry.kind == "file"}
    actual_directories = {path for path, entry in snapshot.items() if entry.kind == "directory"}
    required_directories = set(expected_directories)
    for render_path in expected_files | expected_directories:
        parent = PurePosixPath(render_path).parent
        while parent != PurePosixPath("."):
            required_directories.add(parent.as_posix())
            parent = parent.parent
    if actual_files != expected_files or actual_directories != required_directories:
        raise TrustError("Rendered output completeness check failed")
    return manifest


def validate_convergence_manifest_snapshot(
    snapshot: dict[str, SecureEntry], host: str
) -> dict[str, Any]:
    """Validate the closed v2 contract and complete rendered tree."""
    manifest_entry = snapshot.get(CONVERGENCE_MANIFEST)
    if manifest_entry is None or manifest_entry.kind != "file" or manifest_entry.content is None:
        raise TrustError("Required convergence manifest is unavailable")
    try:
        manifest = json.loads(manifest_entry.content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrustError("Convergence manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != V2_KEYS:
        raise TrustError("Convergence manifest root contract is incomplete")
    if manifest.get("schema_version") != 2:
        raise TrustError("Unsupported convergence manifest schema")
    if manifest.get("host") != host or manifest.get("rendered_root") != ".":
        raise TrustError("Convergence manifest identity is invalid")
    owners = _validate_v2_owners(manifest.get("owners"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise TrustError("Convergence manifest entries must be a list")
    seen_render: set[str] = set()
    seen_target: set[str] = set()
    expected_files = {"manifest.json", CONVERGENCE_MANIFEST}
    expected_directories: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict) or set(raw) != V2_ENTRY_KEYS:
            raise TrustError("Convergence manifest entry is incomplete")
        render_path = raw["render_path"]
        target_path = raw["target_path"]
        if not isinstance(render_path, str) or not _safe_relative(render_path):
            raise TrustError("Convergence manifest contains an unsafe render path")
        software = isinstance(kind := raw["kind"], str) and kind.startswith("software.")
        if software:
            if target_path is not None:
                raise TrustError("Convergence software entries must use explicit effects")
        elif not isinstance(target_path, str) or not _safe_absolute(target_path):
            raise TrustError("Convergence manifest contains an unsafe target path")
        if not render_path.startswith(("system/", "services/", "software/")):
            raise TrustError("Convergence manifest render path is outside a known family")
        if not software and not target_path.startswith(
            ("/etc/", "/home/", "/srv/", "/usr/local/", "/var/lib/abhaile/")
        ):
            raise TrustError("Convergence manifest target path is outside an allowed root")
        authority = None if software else f"path:{target_path}"
        if render_path in seen_render or (authority is not None and authority in seen_target):
            raise TrustError("Convergence manifest contains a duplicate path")
        seen_render.add(render_path)
        if authority is not None:
            seen_target.add(authority)
        action = raw["action"]
        if kind not in ALL_KINDS or action not in V2_ACTIONS:
            raise TrustError("Convergence manifest kind or action is unsupported")
        if action != _v2_action(kind):
            raise TrustError("Convergence manifest kind and action disagree")
        if kind.startswith("software.") and not render_path.startswith("software/"):
            raise TrustError("Convergence software source path is invalid")
        owner_ref = raw["owner_ref"]
        context = raw["execution_context"]
        if owner_ref not in owners or owners[owner_ref]["execution_context"] not in {
            context,
            "orchestrator",
        }:
            raise TrustError("Convergence manifest owner or context is invalid")
        if not _valid_context(context):
            raise TrustError("Convergence manifest execution context is invalid")
        if raw["validation"] not in V2_VALIDATIONS:
            raise TrustError("Convergence manifest validation is unsupported")
        if raw["validation"] != _v2_validation(kind):
            raise TrustError("Convergence manifest kind and validation disagree")
        lifecycle = raw["lifecycle"]
        if (
            not isinstance(lifecycle, list)
            or lifecycle != sorted(set(lifecycle))
            or any(effect not in V2_LIFECYCLE for effect in lifecycle)
        ):
            raise TrustError("Convergence manifest lifecycle is invalid")
        if raw["safe_prune"] not in V2_PRUNE:
            raise TrustError("Convergence manifest prune class is invalid")
        if not _valid_lifecycle(kind, lifecycle):
            raise TrustError("Convergence manifest kind and lifecycle disagree")
        _validate_v2_metadata(kind, raw["metadata"])
        size, digest = raw["size"], raw["sha256"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise TrustError("Convergence manifest artifact size is invalid")
        artifact = snapshot.get(render_path)
        if kind == "service.directory":
            if artifact is None or artifact.kind != "directory" or size != 0:
                raise TrustError("Convergence directory artifact is invalid")
            if digest != hashlib.sha256(b"").hexdigest():
                raise TrustError("Convergence directory digest is invalid")
            expected_directories.add(render_path)
        else:
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise TrustError("Convergence manifest artifact digest is invalid")
            if artifact is None or artifact.kind != "file" or artifact.content is None:
                raise TrustError("Convergence manifest artifact is unavailable")
            if len(artifact.content) != size or _sha256(artifact) != digest:
                raise TrustError("Convergence manifest artifact integrity failed")
            if kind.startswith("software."):
                effects = _validate_software_payload(kind, raw["metadata"], artifact.content)
                for effect in effects:
                    if effect.collision_key in seen_target:
                        raise TrustError(
                            "Convergence manifest contains conflicting mutation authority"
                        )
                    seen_target.add(effect.collision_key)
            expected_files.add(render_path)
    actual_files = {path for path, entry in snapshot.items() if entry.kind == "file"}
    actual_directories = {path for path, entry in snapshot.items() if entry.kind == "directory"}
    required_directories = set(expected_directories)
    # The software renderer creates these fixed organizational buckets even when empty.
    required_directories.update(
        path
        for path in ("software/builds", "software/commands", "software/downloads")
        if path in actual_directories
    )
    for render_path in expected_files | expected_directories:
        parent = PurePosixPath(render_path).parent
        while parent != PurePosixPath("."):
            required_directories.add(parent.as_posix())
            parent = parent.parent
    if actual_files != expected_files or actual_directories != required_directories:
        raise TrustError("Convergence manifest completeness check failed")
    return manifest


def _validate_v2_owners(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise TrustError("Convergence manifest owners must be an object")
    owners: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, list[str]] = {}
    for name, payload in value.items():
        if not isinstance(name, str) or not name or not isinstance(payload, dict):
            raise TrustError("Convergence manifest owner is invalid")
        if re.fullmatch(r"[A-Za-z0-9_.@/-]+:[A-Za-z0-9_.@/-]+", name) is None:
            raise TrustError("Convergence manifest owner reference is invalid")
        if set(payload) != V2_OWNER_KEYS or payload.get("name") != name:
            raise TrustError("Convergence manifest owner is incomplete")
        requires = payload.get("requires")
        if (
            not isinstance(requires, list)
            or requires != sorted(set(requires))
            or any(not isinstance(item, str) or not item for item in requires)
        ):
            raise TrustError("Convergence manifest owner dependencies are invalid")
        context = payload.get("execution_context")
        owner_kind = payload.get("owner_kind")
        if not _valid_context(context) or owner_kind not in {
            "unit",
            "service",
            "iface",
            "user",
            "group",
            "software",
            "dns",
            "caddy",
        }:
            raise TrustError("Convergence manifest owner vocabulary is invalid")
        if owner_kind != _v2_owner_kind(name):
            raise TrustError("Convergence manifest owner kind disagrees with its reference")
        owners[name] = payload
        dependencies[name] = requires
    for name, requires in dependencies.items():
        if any(required not in owners for required in requires):
            raise TrustError(f"Convergence manifest owner dependency is unknown: {name}")
    _validate_owner_graph(dependencies)
    return owners


def _validate_v2_metadata(kind: object, metadata: object) -> None:
    if not isinstance(metadata, dict):
        raise TrustError("Convergence manifest metadata is invalid")
    if isinstance(kind, str) and kind.startswith("software."):
        if set(metadata) != {"operation_id", "operation_type", "execution_policy", "effects"}:
            raise TrustError("Convergence software metadata is incomplete")
        if not all(
            isinstance(metadata[key], str) and metadata[key]
            for key in ("operation_id", "operation_type", "execution_policy")
        ) or not isinstance(metadata["effects"], list):
            raise TrustError("Convergence software metadata is invalid")
        if metadata["operation_type"] not in V2_SOFTWARE_OPERATIONS.get(kind, frozenset()):
            raise TrustError("Convergence software operation is unsupported for its kind")
        return
    if set(metadata) != {"owner", "group", "mode"} or not all(
        isinstance(metadata[key], str) and metadata[key] for key in metadata
    ):
        raise TrustError("Convergence file metadata is incomplete")
    if re.fullmatch(r"0[0-7]{3}", metadata["mode"]) is None:
        raise TrustError("Convergence file mode is invalid")


def _valid_context(value: object) -> bool:
    return value in {"system", "orchestrator"} or (
        isinstance(value, str) and re.fullmatch(r"user:[A-Za-z_][A-Za-z0-9_-]*", value) is not None
    )


def _v2_action(kind: str) -> str:
    if kind == "software.packages":
        return "install"
    if kind == "software.download":
        return "fetch"
    if kind == "software.build":
        return "build"
    if kind == "software.prerequisite":
        return "ensure"
    return "create" if kind == "service.directory" else "publish"


def _v2_validation(kind: str) -> str:
    if kind == "host.sudoers":
        return "sudoers"
    if kind == "host.sysusers":
        return "sysusers"
    if kind.startswith(("systemd.", "resolved.")):
        return "systemd"
    if kind == "coredns.zone":
        return "coredns-zone"
    if kind.startswith("software."):
        return "software-result"
    return "structural"


def _valid_lifecycle(kind: str, lifecycle: list[object]) -> bool:
    for effect in lifecycle:
        if effect == "manager-reload" and not kind.startswith(("systemd.", "quadlet.")):
            return False
        if effect == "network-reconfigure" and not kind.startswith("networkd."):
            return False
        if effect == "service-restart" and kind.startswith("software."):
            return False
    return True


def _v2_owner_kind(name: str) -> str:
    prefix = name.partition(":")[0]
    return (
        prefix
        if prefix in {"unit", "service", "iface", "user", "group", "software", "dns", "caddy"}
        else "service"
    )


def _validate_software_payload(
    kind: str, metadata: dict[str, Any], content: bytes
) -> tuple[SoftwareEffect, ...]:
    """Parse and validate the complete typed software artifact under root authority."""
    if kind == "software.packages":
        try:
            packages = content.decode("utf-8").splitlines()
        except UnicodeError as exc:
            raise TrustError("Software package plan is not UTF-8") from exc
        if (
            not packages
            or packages != list(dict.fromkeys(packages))
            or any(PACKAGE.fullmatch(package) is None for package in packages)
        ):
            raise TrustError("Software package plan is invalid")
        effects = tuple(SoftwareEffect("package", package, "requirement") for package in packages)
        if metadata != {
            "operation_id": "packages",
            "operation_type": "packages",
            "execution_policy": "admitted",
            "effects": [effect.manifest_value() for effect in effects],
        }:
            raise TrustError("Software package effects disagree with manifest metadata")
        return effects
    try:
        payload = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise TrustError("Software operation plan is not valid YAML") from exc
    try:
        operation = parse_software_operation(payload)
    except RenderError as exc:
        raise TrustError(str(exc)) from exc
    if operation.operation_type != metadata["operation_type"]:
        raise TrustError("Software operation plan disagrees with manifest metadata")
    if operation.operation_id != metadata["operation_id"]:
        raise TrustError("Software operation identity disagrees with manifest metadata")
    if operation.execution_policy != metadata["execution_policy"]:
        raise TrustError("Software execution policy disagrees with manifest metadata")
    metadata_effects = [effect.manifest_value() for effect in operation.effects]
    if metadata_effects != metadata["effects"]:
        raise TrustError("Software effects disagree with manifest metadata")
    return operation.effects


def tree_digest(root: Path) -> str:
    """Bind relative paths, modes, and bytes into a deterministic tree digest."""
    digest = hashlib.sha256()
    for relative, entry in sorted(snapshot_tree(root).items()):
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(oct(entry.mode & 0o777).encode("ascii") + b"\0")
        if entry.content is not None:
            digest.update(entry.content)
    return digest.hexdigest()


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\0" not in value
        and not path.is_absolute()
        and "." not in path.parts
        and ".." not in path.parts
        and path.as_posix() == value
    )


def _safe_absolute(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\0" not in value
        and path.is_absolute()
        and value != "/"
        and not value.startswith("//")
        and "." not in path.parts
        and ".." not in path.parts
        and path.as_posix() == value
    )


def _validate_owners(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise TrustError("Manifest owners must be an object")
    owners: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, list[str]] = {}
    for name, payload in value.items():
        if not isinstance(name, str) or not name or not isinstance(payload, dict):
            raise TrustError("Manifest owner definition is invalid")
        if not set(payload).issubset(OWNER_KEYS):
            raise TrustError("Manifest owner contains unsupported fields")
        if payload.get("name") != name:
            raise TrustError("Manifest owner name does not match its key")
        description = payload.get("description")
        requires = payload.get("requires", [])
        apply_hints = payload.get("apply_hints")
        if description is not None and not isinstance(description, str):
            raise TrustError("Manifest owner description is invalid")
        if not isinstance(requires, list) or not all(
            isinstance(item, str) and item for item in requires
        ):
            raise TrustError("Manifest owner dependencies are invalid")
        if len(set(requires)) != len(requires) or name in requires:
            raise TrustError("Manifest owner dependencies contain a duplicate or self-reference")
        if apply_hints is not None and not isinstance(apply_hints, dict):
            raise TrustError("Manifest owner apply hints are invalid")
        owners[name] = payload
        dependencies[name] = requires
    for name, requires in dependencies.items():
        if any(required not in owners for required in requires):
            raise TrustError(f"Manifest owner dependency is unknown: {name}")
    _validate_owner_graph(dependencies)
    return owners


def _validate_owner_graph(dependencies: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise TrustError("Manifest owner dependency graph contains a cycle")
        if name in visited:
            return
        visiting.add(name)
        for dependency in dependencies[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in dependencies:
        visit(name)


def _valid_owner_ref(owner_ref: str, owners: dict[str, dict[str, Any]]) -> bool:
    if owner_ref in owners:
        return True
    return re.fullmatch(r"(?:service|unit):[A-Za-z0-9_.@-]+", owner_ref) is not None


def _sha256(entry: SecureEntry) -> str:
    if entry.content is None:
        raise TrustError(f"Capsule entry is not a file: {entry.path}")
    return hashlib.sha256(entry.content).hexdigest()
