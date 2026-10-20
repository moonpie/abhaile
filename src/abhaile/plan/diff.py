"""Preserve the removal-classifier import across last-successful revisions."""

from abhaile.state.removals import (
    ManifestRemovalClassification,
    classify_candidate_only_files,
    classify_manifest_removals,
)

__all__ = [
    "ManifestRemovalClassification",
    "classify_candidate_only_files",
    "classify_manifest_removals",
]
