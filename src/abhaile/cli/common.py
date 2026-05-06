"""Shared CLI utilities for abhaile commands."""

from __future__ import annotations

import logging
from pathlib import Path

from abhaile.utils.errors import PipelineError
from abhaile.utils.paths import get_repo_root, load_paths

LOG = logging.getLogger(__name__)


def configure_logging(verbosity: int) -> None:
    """Configure CLI logging verbosity."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s event=%(message)s",
    )


def resolve_cli_paths(
    output: str | None,
    desired_manifest: str | None,
    applied_manifest: str | None,
    desired_manifest_positional: str | None = None,
    applied_manifest_positional: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Resolve output, desired manifest, and applied manifest paths.

    Returns (rendered_dir, state_dir, desired_path, applied_path).
    """
    repo_root = get_repo_root(Path(__file__))
    paths = load_paths(repo_root)
    output_root = Path(output).resolve() if output else Path(paths["output_root_default"])

    rendered_dir = output_root / paths["rendered_dir_name"]
    state_dir = output_root / paths["state_dir_name"]

    desired_arg = desired_manifest_positional or desired_manifest
    applied_arg = applied_manifest_positional or applied_manifest

    desired_path = Path(desired_arg).resolve() if desired_arg else rendered_dir / "manifest.json"
    if applied_arg:
        applied_path = Path(applied_arg).resolve()
    elif desired_arg:
        base_root = (
            desired_path.parent.parent
            if desired_path.parent.name == "rendered"
            else desired_path.parent
        )
        applied_path = base_root / "state" / "manifest.json"
    else:
        applied_path = state_dir / "manifest.json"

    # When explicit manifests are provided (common in tests/workstation flows),
    # derive roots from those paths instead of default output_root.
    rendered_dir = desired_path.parent
    state_dir = applied_path.parent

    return rendered_dir, state_dir, desired_path, applied_path


def print_diff_summary(plan: dict[str, object]) -> None:
    """Print human-readable drift summary."""
    summary = plan["summary"]
    if not isinstance(summary, dict):
        raise PipelineError("Invalid plan summary")

    print(f"host={plan['host']}")
    print(
        "diff "
        f"added={summary['added']} "
        f"changed={summary['changed']} "
        f"removed={summary['removed']}"
    )
    print(
        "sync "
        f"writes={summary['writes']} "
        f"removals_safe={summary['removals_safe']} "
        f"removals_drifted={summary['removals_drifted']} "
        f"removals_missing={summary['removals_missing']}"
    )
