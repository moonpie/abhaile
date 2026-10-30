"""Tests for manifest removal identity classification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from abhaile.state.removals import (
    classify_candidate_only_files,
    classify_manifest_removals,
)
from abhaile.utils.errors import DiffError


def _digest(content: str) -> str:
    """Return the SHA-256 digest for text content."""
    return hashlib.sha256(content.encode()).hexdigest()


def _entry(target: Path, content: str, **overrides: object) -> dict[str, object]:
    """Build one manifest file entry."""
    entry: dict[str, object] = {
        "render_path": f"services/test/{target.name}",
        "target_path": target.as_posix(),
        "sha256": _digest(content),
        "size": len(content.encode()),
        "kind": "service.config",
        "owner_ref": "service:test",
    }
    entry.update(overrides)
    return entry


def _manifest(path: Path, host: str, entries: list[dict[str, object]]) -> None:
    """Write one minimal manifest."""
    path.write_text(json.dumps({"version": "1", "host": host, "entries": entries}))


def test_matching_previous_only_file_has_identity_evidence(tmp_path: Path) -> None:
    """Return exact live identity evidence without authorizing deletion."""
    target = tmp_path / "removed.conf"
    target.write_text("accepted=yes\n")
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [_entry(target, "accepted=yes\n")])

    result = classify_manifest_removals(desired, previous)

    assert [item["target_path"] for item in result["identity_matches"]] == [target.as_posix()]
    assert result["missing"] == []
    assert result["blocked"] == []


def test_shared_target_is_not_removal(tmp_path: Path) -> None:
    """Ignore targets still present in desired state."""
    target = tmp_path / "shared.conf"
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [_entry(target, "new\n")])
    _manifest(previous, "deimos", [_entry(target, "old\n")])

    result = classify_manifest_removals(desired, previous)

    assert result["identity_matches"] == []
    assert result["missing"] == []
    assert result["blocked"] == []


def test_missing_previous_only_file_is_classified(tmp_path: Path) -> None:
    """Separate an already absent target from matching live state."""
    target = tmp_path / "missing.conf"
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [_entry(target, "old\n")])

    result = classify_manifest_removals(desired, previous)

    assert [item["target_path"] for item in result["missing"]] == [target.as_posix()]


@pytest.mark.parametrize("path_type", ["directory", "symlink"])
def test_non_regular_previous_only_path_is_blocked(tmp_path: Path, path_type: str) -> None:
    """Block directories and dangling links where a regular file is expected."""
    target = tmp_path / "unsafe"
    if path_type == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "absent")
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [_entry(target, "old\n")])

    result = classify_manifest_removals(desired, previous)

    assert result["blocked"][0]["reason"] == "non-regular-live-path"


def test_drifted_previous_only_file_is_blocked(tmp_path: Path) -> None:
    """Block removal after live content diverges from retained intent."""
    target = tmp_path / "drifted.conf"
    target.write_text("operator=yes\n")
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [_entry(target, "old\n")])

    result = classify_manifest_removals(desired, previous)

    assert result["blocked"][0]["reason"] == "live-content-mismatch"


def test_manifest_directory_is_blocked_without_complete_identity(tmp_path: Path) -> None:
    """Do not infer directory-content identity from manifest metadata."""
    target = tmp_path / "managed.d"
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [_entry(target, "", is_directory=True)])

    result = classify_manifest_removals(desired, previous)

    assert result["blocked"][0]["reason"] == "directory-identity-incomplete"


def test_explicit_residue_and_kind_scope_are_ignored(tmp_path: Path) -> None:
    """Ignore only named inert residue and entries outside the selected family."""
    directory = tmp_path / "dropin.d"
    service = tmp_path / "service.conf"
    desired = tmp_path / "desired.json"
    candidate = tmp_path / "candidate.json"
    _manifest(desired, "deimos", [])
    _manifest(
        candidate,
        "deimos",
        [
            _entry(directory, "", kind="networkd.dropin", is_directory=True),
            _entry(service, "old\n", kind="service.config"),
        ],
    )

    result = classify_candidate_only_files(
        desired,
        candidate,
        included_kinds={"networkd.dropin"},
        directory_residue_kinds={"networkd.dropin"},
    )

    assert result["identity_matches"] == []
    assert result["blocked"] == []


def test_cross_host_context_is_rejected(tmp_path: Path) -> None:
    """Reject removal evidence from another host."""
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "phobos", [])

    with pytest.raises(DiffError, match="Manifest removal host mismatch"):
        classify_manifest_removals(desired, previous)


def test_duplicate_target_is_rejected(tmp_path: Path) -> None:
    """Reject ambiguous identity evidence for one live target."""
    target = tmp_path / "duplicate.conf"
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    duplicate = _entry(target, "old\n")
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [duplicate, duplicate])

    with pytest.raises(DiffError, match="Duplicate target_path"):
        classify_manifest_removals(desired, previous)


@pytest.mark.parametrize(
    ("field", "value"),
    [("sha256", "not-a-digest"), ("size", -1), ("apply_hints", []), ("is_directory", "yes")],
)
def test_invalid_identity_metadata_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    """Reject malformed metadata before it can be used as removal evidence."""
    target = tmp_path / "invalid.conf"
    desired = tmp_path / "desired.json"
    previous = tmp_path / "previous.json"
    _manifest(desired, "deimos", [])
    _manifest(previous, "deimos", [_entry(target, "old\n", **{field: value})])

    with pytest.raises(DiffError, match=f"invalid {field}"):
        classify_manifest_removals(desired, previous)


@pytest.mark.parametrize("host", ["phobos", "deimos"])
@pytest.mark.parametrize("drifted", [False, True])
def test_recovery_retains_candidate_package_inventory_without_cleanup(
    tmp_path: Path, host: str, drifted: bool
) -> None:
    """Retain additive package inventory while still classifying ordinary candidate files."""
    packages = tmp_path / "packages.txt"
    declared_packages = "podman\nuidmap\n"
    live_packages = "podman\nuidmap\nvim\n" if drifted else declared_packages
    packages.write_text(live_packages)
    ordinary = tmp_path / "candidate.conf"
    ordinary.write_text("candidate=yes\n")
    accepted = tmp_path / "accepted.json"
    candidate = tmp_path / "candidate.json"
    _manifest(accepted, host, [])
    _manifest(
        candidate,
        host,
        [
            _entry(
                packages,
                declared_packages,
                kind="host.packages",
                owner_ref=f"host-packages:{host}",
            ),
            _entry(ordinary, "candidate=yes\n"),
        ],
    )

    result = classify_candidate_only_files(
        accepted,
        candidate,
        directory_residue_kinds={"networkd.dropin", "service.directory"},
        file_residue_kinds={"caddy.config", "host.packages"},
    )

    assert result["blocked"] == []
    assert result["missing"] == []
    assert [entry["target_path"] for entry in result["identity_matches"]] == [str(ordinary)]
    assert packages.read_text() == live_packages
    assert ordinary.read_text() == "candidate=yes\n"
