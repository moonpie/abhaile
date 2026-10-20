"""Tests for the last-successful removal-classifier import path."""

from abhaile.plan.diff import classify_manifest_removals as compatibility_classifier
from abhaile.state.removals import classify_manifest_removals


def test_compatibility_path_exports_current_classifier() -> None:
    """Keep the historical runner import bound to the current implementation."""
    assert compatibility_classifier is classify_manifest_removals
