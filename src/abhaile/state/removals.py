"""Classify manifest removals against live file identity."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any, TypedDict

from abhaile.utils.errors import DiffError
from abhaile.utils.hashing import sha256_file


class ManifestRemovalClassification(TypedDict):
    """Group manifest-only files by live identity evidence."""

    host: str
    identity_matches: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    blocked: list[dict[str, Any]]


def _load_entries(path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    """Load the host and uniquely indexed entries from one manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiffError(f"Failed to read manifest: {path} ({exc})") from exc
    if not isinstance(payload, dict) or payload.get("version") != "1":
        raise DiffError(f"Manifest has unsupported or missing version: {path}")
    host = payload.get("host")
    entries = payload.get("entries")
    if not isinstance(host, str) or not host or not isinstance(entries, list):
        raise DiffError(f"Manifest has an invalid host or entries collection: {path}")

    indexed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise DiffError(f"Manifest entry must be an object: {path}")
        target = entry.get("target_path")
        if not isinstance(target, str) or not Path(target).is_absolute():
            raise DiffError(f"Manifest entry has invalid target_path: {path}")
        if target in indexed:
            raise DiffError(f"Duplicate target_path in manifest: {target}")
        for field in ("render_path", "kind", "owner_ref"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise DiffError(f"Manifest entry has invalid {field}: {path} target={target}")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise DiffError(f"Manifest entry has invalid sha256: {path} target={target}")
        size = entry.get("size")
        if not isinstance(size, int) or size < 0:
            raise DiffError(f"Manifest entry has invalid size: {path} target={target}")
        if "apply_hints" in entry and not isinstance(entry["apply_hints"], dict):
            raise DiffError(f"Manifest entry has invalid apply_hints: {path} target={target}")
        if "is_directory" in entry and not isinstance(entry["is_directory"], bool):
            raise DiffError(f"Manifest entry has invalid is_directory: {path} target={target}")
        indexed[target] = entry
    return host, indexed


def _live_digest(target: str) -> str | None:
    """Return a regular file digest, None when absent, or a type sentinel."""
    path = Path(target)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DiffError(f"Failed to inspect live file: {target} ({exc})") from exc
    if not stat.S_ISREG(metadata.st_mode):
        return "__NON_REGULAR__"
    try:
        return sha256_file(path)
    except OSError as exc:
        raise DiffError(f"Failed to hash live file: {target} ({exc})") from exc


def classify_manifest_removals(
    desired_manifest_path: Path,
    removal_source_manifest_path: Path,
    *,
    included_kinds: set[str] | None = None,
    directory_residue_kinds: set[str] | None = None,
    file_residue_kinds: set[str] | None = None,
) -> ManifestRemovalClassification:
    """Classify files absent from desired state without authorizing removal."""
    desired_host, desired = _load_entries(desired_manifest_path)
    source_host, source = _load_entries(removal_source_manifest_path)
    if source_host != desired_host:
        raise DiffError(
            "Manifest removal host mismatch: "
            f"desired host={desired_host} removal-source host={source_host}"
        )

    result: ManifestRemovalClassification = {
        "host": desired_host,
        "identity_matches": [],
        "missing": [],
        "blocked": [],
    }
    for target in sorted(set(source) - set(desired)):
        entry = source[target]
        kind = entry["kind"]
        if included_kinds is not None and kind not in included_kinds:
            continue
        classification = {
            "target_path": target,
            "render_path": entry["render_path"],
            "kind": kind,
            "owner_ref": entry["owner_ref"],
            "candidate_sha256": entry["sha256"],
            "apply_hints": entry.get("apply_hints"),
        }
        if entry.get("is_directory") is True:
            if directory_residue_kinds is None or kind not in directory_residue_kinds:
                result["blocked"].append(
                    {**classification, "reason": "directory-identity-incomplete"}
                )
            continue
        if file_residue_kinds is not None and kind in file_residue_kinds:
            continue

        live_digest = _live_digest(target)
        evidence = {**classification, "live_sha256": live_digest}
        if live_digest is None:
            result["missing"].append(evidence)
        elif live_digest == entry["sha256"]:
            result["identity_matches"].append(evidence)
        else:
            reason = (
                "non-regular-live-path"
                if live_digest == "__NON_REGULAR__"
                else "live-content-mismatch"
            )
            result["blocked"].append({**evidence, "reason": reason})
    return result


def classify_candidate_only_files(
    last_successful_manifest_path: Path,
    candidate_manifest_path: Path,
    *,
    included_kinds: set[str] | None = None,
    directory_residue_kinds: set[str] | None = None,
    file_residue_kinds: set[str] | None = None,
) -> ManifestRemovalClassification:
    """Classify interrupted-candidate additions without authorizing removal."""
    return classify_manifest_removals(
        last_successful_manifest_path,
        candidate_manifest_path,
        included_kinds=included_kinds,
        directory_residue_kinds=directory_residue_kinds,
        file_residue_kinds=file_residue_kinds,
    )
