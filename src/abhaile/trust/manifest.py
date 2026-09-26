"""Validate a rendered manifest inside an isolated capsule."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from abhaile.models.kinds import ALL_KINDS
from abhaile.trust.errors import TrustError
from abhaile.trust.securefs import SecureEntry, snapshot_tree

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


def validate_manifest(rendered: Path, host: str) -> dict[str, Any]:
    """Validate manifest structure, artifact completeness, paths, hashes, and sizes."""
    return validate_manifest_snapshot(snapshot_tree(rendered), host)


def validate_manifest_snapshot(snapshot: dict[str, SecureEntry], host: str) -> dict[str, Any]:
    """Validate the v1 structural contract against one stable tree snapshot."""
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
