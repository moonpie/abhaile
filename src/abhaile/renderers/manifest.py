"""Manifest generation: file hashing, deterministic inventory."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from abhaile.utils.errors import RenderError


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


def _map_target_path(rel_path: str, target_root: Path) -> str:
    """Map rendered relative path to live host target path."""
    parts = Path(rel_path).parts
    if not parts:
        return target_root.as_posix()

    if parts[0] == "system" and len(parts) > 1:
        mapped = Path(*parts[1:])
    elif parts[0] == "users" and len(parts) > 1:
        mapped = Path(*parts[1:])
    elif parts[0] == "services" and len(parts) > 2:
        mapped = Path(*parts[2:])
    else:
        mapped = Path(*parts)

    return (target_root / mapped).as_posix()


def build_manifest(host: str, rendered_dir: Path, target_root: Path) -> Dict[str, Any]:
    """Build manifest from rendered artifacts.

    Manifest includes host identity, render timestamp, and file entries.

    Args:
        host: Hostname for manifest safety checks.
        rendered_dir: Path to rendered output directory.
        target_root: Live target root (typically /).

    Returns:
        Manifest dictionary with host, rendered_at, and entries list.
    """

    entries: List[Dict[str, Any]] = []
    if rendered_dir.exists():
        for root, _, files in os.walk(rendered_dir):
            for name in files:
                file_path = Path(root) / name
                if file_path.is_symlink():
                    continue
                rel_path = file_path.relative_to(rendered_dir).as_posix()
                target_path = _map_target_path(rel_path, target_root)
                entries.append(
                    {
                        "rel_path": rel_path,
                        "target_path": target_path,
                        "sha256": sha256_file(file_path),
                        "size": file_path.stat().st_size,
                    }
                )
    entries.sort(key=lambda item: item["rel_path"])
    return {
        "host": host,
        "rendered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }


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
