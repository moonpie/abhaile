"""Unit tests for durable apply state rotation."""

from __future__ import annotations

import json
from pathlib import Path

from abhaile.state.history import update_state_manifests


def _write_manifest(path: Path, host: str, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": host,
        "entries": [
            {
                "render_path": "system/etc/example.conf",
                "target_path": "/etc/example.conf",
                "sha256": marker * 64,
                "size": 1,
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


class TestUpdateStateManifests:
    """Tests for update_state_manifests()."""

    def test_first_write_creates_current_only(self, tmp_path: Path) -> None:
        """First apply creates state/manifest.json."""
        desired = tmp_path / "rendered" / "manifest.json"
        state_dir = tmp_path / "state"
        _write_manifest(desired, "deimos", "a")

        update_state_manifests(desired, state_dir)

        assert (state_dir / "manifest.json").exists()
        assert not (state_dir / "manifest.previous.json").exists()

    def test_second_write_rotates_previous_and_history(self, tmp_path: Path) -> None:
        """Second apply rotates prior current manifest."""
        state_dir = tmp_path / "state"
        desired_v1 = tmp_path / "rendered" / "manifest-v1.json"
        desired_v2 = tmp_path / "rendered" / "manifest-v2.json"
        _write_manifest(desired_v1, "deimos", "a")
        _write_manifest(desired_v2, "deimos", "b")

        update_state_manifests(desired_v1, state_dir)
        update_state_manifests(desired_v2, state_dir)

        current = json.loads((state_dir / "manifest.json").read_text())
        previous = json.loads((state_dir / "manifest.previous.json").read_text())
        history_files = sorted((state_dir / "history").glob("manifest-*.json"))

        assert current["entries"][0]["sha256"] == "b" * 64
        assert previous["entries"][0]["sha256"] == "a" * 64
        assert len(history_files) == 1

    def test_history_pruned_to_keep_limit(self, tmp_path: Path) -> None:
        """History should be bounded to keep_history entries."""
        state_dir = tmp_path / "state"
        for idx in range(6):
            desired = tmp_path / "rendered" / f"manifest-v{idx}.json"
            marker = chr(ord("a") + idx)
            _write_manifest(desired, "phobos", marker)
            update_state_manifests(desired, state_dir, keep_history=3)

        history_files = sorted((state_dir / "history").glob("manifest-*.json"))
        assert len(history_files) == 3
