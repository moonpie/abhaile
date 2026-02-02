"""Manifest generation: file hashing, deterministic inventory."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Import errors from utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.errors import RenderError


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


def build_manifest(rendered_dir: Path, target_root: Path) -> Dict[str, Any]:
    """Build manifest from rendered artifacts.

    Manifest includes SHA256, size, mode, uid, gid for each file.
    Artifacts are sorted deterministically by rel_path.

    Args:
        rendered_dir: Path to rendered output directory.
        target_root: Live target root (typically /).

    Returns:
        Manifest dictionary with rendered_at timestamp and artifacts list.
    """

    artifacts: List[Dict[str, Any]] = []
    if rendered_dir.exists():
        for root, _, files in os.walk(rendered_dir):
            for name in files:
                file_path = Path(root) / name
                if file_path.is_symlink():
                    continue
                rel_path = file_path.relative_to(rendered_dir).as_posix()
                stat = file_path.stat()
                artifacts.append(
                    {
                        "target_path": (target_root / rel_path).as_posix(),
                        "rel_path": rel_path,
                        "sha256": sha256_file(file_path),
                        "size": stat.st_size,
                        "mode": f"{stat.st_mode & 0o7777:04o}",
                        "uid": stat.st_uid,
                        "gid": stat.st_gid,
                    }
                )
    artifacts.sort(key=lambda item: item["rel_path"])
    return {
        "rendered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifacts": artifacts,
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
