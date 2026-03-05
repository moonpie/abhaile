"""Apply manifest planning for drift detection.

This module will provide deterministic manifest generation and comparison for the
apply pipeline. Render writes a per-host manifest (paths + hashes); apply will
load the last-applied manifest from the target host and compute drift to decide
which artifacts are safe to update.

Planned responsibilities:
- Read rendered manifest from out/state or out/rendered.
- Read last-applied manifest from the host state directory.
- Compare hashes, permissions, and ownership metadata for each artifact.
- Produce a structured drift report used by --dry-run and safety gates.

Non-goals:
- Performing any on-host writes (apply execution lives elsewhere).
- Deciding service restarts (that stays in apply orchestration).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def plan_manifest_drift(
    rendered_manifest_path: Path, applied_manifest_path: Path
) -> Dict[str, Any]:
    """Plan manifest drift for apply by comparing rendered vs applied state.

    Expected usage: call during apply to produce a structured drift report
    for --dry-run output and safety gates.
    """
    raise NotImplementedError("Manifest drift planning is not implemented yet.")
