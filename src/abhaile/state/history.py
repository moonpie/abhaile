"""Durable applied-state history and manifest rotation."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from abhaile.utils.errors import ApplyError

DEFAULT_HISTORY_KEEP = 10


def _timestamp_utc() -> str:
    """Create a compact UTC timestamp for history filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def update_state_manifests(
    desired_manifest_path: Path,
    state_dir: Path,
    *,
    keep_history: int = DEFAULT_HISTORY_KEEP,
) -> None:
    """Rotate and write durable state manifests after successful apply."""
    if keep_history < 1:
        raise ApplyError("keep_history must be >= 1")
    if not desired_manifest_path.exists():
        raise ApplyError(f"Desired manifest not found: {desired_manifest_path}")

    current_path = state_dir / "manifest.json"
    previous_path = state_dir / "manifest.previous.json"
    history_dir = state_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    if current_path.exists():
        try:
            shutil.copy2(current_path, previous_path)

            timestamp = _timestamp_utc()
            history_path = history_dir / f"manifest-{timestamp}.json"
            counter = 1
            while history_path.exists():
                history_path = history_dir / f"manifest-{timestamp}-{counter}.json"
                counter += 1
            shutil.copy2(current_path, history_path)
        except OSError as exc:
            raise ApplyError(f"Failed rotating state manifests in {state_dir} ({exc})") from exc

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(desired_manifest_path, current_path)
    except OSError as exc:
        raise ApplyError(f"Failed writing current state manifest in {state_dir} ({exc})") from exc

    history_files = sorted(history_dir.glob("manifest-*.json"))
    if len(history_files) > keep_history:
        for stale in history_files[: len(history_files) - keep_history]:
            stale.unlink(missing_ok=True)
