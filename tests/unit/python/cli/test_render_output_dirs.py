"""Tests for render output directory preparation."""

from __future__ import annotations

from pathlib import Path

from abhaile.cli.render import _prepare_output_dirs


def test_prepare_output_dirs_preserves_rendered_directory(tmp_path: Path) -> None:
    """Clear rendered contents without replacing the rendered directory."""
    output_root = tmp_path / "out"
    rendered_dir = output_root / "rendered"
    stale_dir = rendered_dir / "system"
    stale_dir.mkdir(parents=True)
    (stale_dir / "old.conf").write_text("old\n", encoding="utf-8")
    (rendered_dir / "manifest.json").write_text("{}\n", encoding="utf-8")

    before_inode = rendered_dir.stat().st_ino

    result = _prepare_output_dirs(output_root, {"rendered_dir_name": "rendered"})

    assert result == rendered_dir
    assert rendered_dir.stat().st_ino == before_inode
    assert list(rendered_dir.iterdir()) == []
