"""Tests for abhaile-diff CLI exit code semantics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from abhaile.cli.diff import main as main_diff


def _sha_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write_manifest(
    path: Path,
    host: str,
    entries: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized: list[dict[str, object]] = []
    for entry in entries:
        normalized_entry = dict(entry)
        normalized_entry.setdefault("kind", "service.config")
        normalized_entry.setdefault("owner_ref", "service:test")
        normalized.append(normalized_entry)
    payload = {"version": "1", "host": host, "entries": normalized}
    path.write_text(json.dumps(payload, indent=2) + "\n")


class TestDiffExitCodes:
    """Tests for diff exit code semantics."""

    def test_exit_0_when_manifests_identical(self, tmp_path: Path) -> None:
        """Exit 0 when desired and applied manifests have no differences."""
        target = tmp_path / "target" / "etc" / "app.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("a=1\n")

        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"
        entries: list[dict[str, object]] = [
            {
                "render_path": "system/etc/app.conf",
                "target_path": target.as_posix(),
                "sha256": _sha_of("a=1\n"),
                "size": 4,
            }
        ]
        _write_manifest(desired, "phobos", entries)
        _write_manifest(applied, "phobos", entries)

        rc = main_diff(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )
        assert rc == 0

    def test_exit_1_when_differences_exist(self, tmp_path: Path) -> None:
        """Exit 1 when content differences (added/changed/removed) are found."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        target = tmp_path / "target" / "etc" / "app.conf"
        _write_manifest(
            desired,
            "deimos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("new\n"),
                    "size": 4,
                }
            ],
        )
        _write_manifest(applied, "deimos", [])

        rc = main_diff(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )
        assert rc == 1

    def test_exit_1_when_removed_entries_present(self, tmp_path: Path) -> None:
        """Exit 1 when entries are removed (present in applied but not desired)."""
        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        target = tmp_path / "target" / "etc" / "old.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old\n")

        _write_manifest(desired, "phobos", [])
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/old.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("old\n"),
                    "size": 4,
                }
            ],
        )

        rc = main_diff(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )
        assert rc == 1

    def test_exit_0_when_metadata_only_change(self, tmp_path: Path) -> None:
        """Exit 0 when only metadata differs (same sha256 but different kind)."""
        target = tmp_path / "target" / "etc" / "app.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("a=1\n")

        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("a=1\n"),
                    "size": 4,
                    "kind": "service.config",
                    "owner_ref": "service:new-owner",
                }
            ],
        )
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("a=1\n"),
                    "size": 4,
                    "kind": "service.config",
                    "owner_ref": "service:old-owner",
                }
            ],
        )

        rc = main_diff(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )
        assert rc == 0

    def test_raises_on_invalid_manifest(self, tmp_path: Path) -> None:
        """DiffError raised on malformed manifest (exit 2 in entrypoint)."""
        from abhaile.utils.errors import DiffError

        desired = tmp_path / "rendered" / "manifest.json"
        desired.parent.mkdir(parents=True, exist_ok=True)
        desired.write_text("not valid json {{{")

        applied = tmp_path / "state" / "manifest.json"

        with pytest.raises(DiffError):
            main_diff(
                [
                    "--desired-manifest",
                    desired.as_posix(),
                    "--applied-manifest",
                    applied.as_posix(),
                ]
            )

    def test_metadata_changes_reported_in_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Metadata-only changes are reported distinctly in human-readable output."""
        target = tmp_path / "target" / "etc" / "app.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("a=1\n")

        desired = tmp_path / "rendered" / "manifest.json"
        applied = tmp_path / "state" / "manifest.json"

        _write_manifest(
            desired,
            "phobos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("a=1\n"),
                    "size": 4,
                    "kind": "service.config",
                    "owner_ref": "service:new-owner",
                }
            ],
        )
        _write_manifest(
            applied,
            "phobos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("a=1\n"),
                    "size": 4,
                    "kind": "service.config",
                    "owner_ref": "service:old-owner",
                }
            ],
        )

        rc = main_diff(
            [
                "--desired-manifest",
                desired.as_posix(),
                "--applied-manifest",
                applied.as_posix(),
            ]
        )
        output = capsys.readouterr().out
        assert rc == 0
        assert "metadata_changes=1" in output
