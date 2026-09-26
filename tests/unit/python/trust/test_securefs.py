"""Unit tests for descriptor-anchored protected tree reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.securefs import snapshot_tree


def test_snapshots_regular_tree_from_open_descriptors(tmp_path: Path) -> None:
    """Capture paths, metadata, and bytes from a regular tree."""
    root = tmp_path / "root"
    artifact = root / "directory" / "artifact"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"trusted")
    snapshot = snapshot_tree(root)
    assert snapshot["directory"].kind == "directory"
    assert snapshot["directory/artifact"].content == b"trusted"


def test_rejects_symlink_at_any_depth(tmp_path: Path) -> None:
    """Never follow a link encountered beneath an opened protected root."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "target").write_text("content", encoding="utf-8")
    (root / "link").symlink_to("target")
    with pytest.raises(TrustError, match="symlink"):
        snapshot_tree(root)


def test_rejects_hard_linked_files(tmp_path: Path) -> None:
    """Reject aliases that could mutate sealed content through another pathname."""
    root = tmp_path / "root"
    root.mkdir()
    original = root / "original"
    original.write_text("content", encoding="utf-8")
    os.link(original, root / "alias")
    with pytest.raises(TrustError, match="unsupported"):
        snapshot_tree(root)


def test_rejects_symlink_root(tmp_path: Path) -> None:
    """Open the protected root itself with no-follow semantics."""
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "root"
    root.symlink_to(target, target_is_directory=True)
    with pytest.raises(TrustError, match="unavailable"):
        snapshot_tree(root)
