"""Unit tests for privileged manifest structural validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.manifest import validate_manifest


def _write_manifest(root: Path, mutate: Any = None) -> None:
    artifact = root / "system" / "unit.service"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"unit\n")
    payload: dict[str, Any] = {
        "version": "1",
        "host": "deimos",
        "entries": [
            {
                "render_path": "system/unit.service",
                "target_path": "/etc/systemd/system/unit.service",
                "kind": "systemd.unit",
                "owner_ref": "unit",
                "sha256": hashlib.sha256(b"unit\n").hexdigest(),
                "size": 5,
            }
        ],
        "owners": {"unit": {"name": "unit"}},
    }
    if mutate is not None:
        mutate(payload)
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_accepts_existing_v1_structural_contract(tmp_path: Path) -> None:
    """Accept known kinds, declared owners, canonical paths, and complete artifacts."""
    _write_manifest(tmp_path)
    assert validate_manifest(tmp_path, "deimos")["host"] == "deimos"


@pytest.mark.parametrize(
    "target",
    ("relative", "/", "//etc/unit", "/etc/../root/unit", "/etc/./unit", "/etc/unit\0x"),
)
def test_rejects_noncanonical_target_paths(tmp_path: Path, target: str) -> None:
    """Reject target paths whose normalized meaning differs from their text."""
    _write_manifest(tmp_path, lambda payload: payload["entries"][0].update(target_path=target))
    with pytest.raises(TrustError, match="unsafe target"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_unknown_kind_or_owner(tmp_path: Path) -> None:
    """Require every entry kind and owner reference to use the existing v1 vocabulary."""
    _write_manifest(tmp_path, lambda payload: payload["entries"][0].update(kind="unknown"))
    with pytest.raises(TrustError, match="unsupported artifact kind"):
        validate_manifest(tmp_path, "deimos")
    _write_manifest(tmp_path, lambda payload: payload["entries"][0].update(owner_ref="missing"))
    with pytest.raises(TrustError, match="unknown owner"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_duplicate_target_paths(tmp_path: Path) -> None:
    """Prevent two artifacts from authorizing changes to one live target."""

    def duplicate(payload: dict[str, Any]) -> None:
        entry = dict(payload["entries"][0])
        entry["render_path"] = "system/second.service"
        payload["entries"].append(entry)

    _write_manifest(tmp_path, duplicate)
    (tmp_path / "system/second.service").write_bytes(b"unit\n")
    with pytest.raises(TrustError, match="duplicate target"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_invalid_owner_dependency_graph(tmp_path: Path) -> None:
    """Require owner dependencies to resolve and remain acyclic."""

    def cyclic(payload: dict[str, Any]) -> None:
        payload["owners"] = {
            "unit": {"name": "unit", "requires": ["other"]},
            "other": {"name": "other", "requires": ["unit"]},
        }

    _write_manifest(tmp_path, cyclic)
    with pytest.raises(TrustError, match="cycle"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_boolean_size_and_unknown_schema_fields(tmp_path: Path) -> None:
    """Do not accept JSON booleans as sizes or silently ignore new authority fields."""
    _write_manifest(tmp_path, lambda payload: payload["entries"][0].update(size=True))
    with pytest.raises(TrustError, match="invalid artifact size"):
        validate_manifest(tmp_path, "deimos")
    _write_manifest(tmp_path, lambda payload: payload["entries"][0].update(authority="root"))
    with pytest.raises(TrustError, match="unsupported fields"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_directory_kind_marker_mismatch(tmp_path: Path) -> None:
    """Require directory entries to use the established service.directory kind."""
    _write_manifest(tmp_path, lambda payload: payload["entries"][0].update(is_directory=True))
    with pytest.raises(TrustError, match="marker and artifact kind"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_unknown_top_level_fields_and_invalid_timestamp(tmp_path: Path) -> None:
    """Keep the trusted v1 root schema closed and type its optional timestamp."""
    _write_manifest(tmp_path, lambda payload: payload.update(authority="caller"))
    with pytest.raises(TrustError, match="unsupported top-level"):
        validate_manifest(tmp_path, "deimos")
    _write_manifest(tmp_path, lambda payload: payload.update(rendered_at=False))
    with pytest.raises(TrustError, match="timestamp is invalid"):
        validate_manifest(tmp_path, "deimos")
