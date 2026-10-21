"""Tests for bounded live manifest-integrity auditing."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from abhaile import integrity
from abhaile.integrity import MAX_HASH_BYTES, audit_manifest


def _entry(path: Path, content: bytes, *, kind: str = "service.config") -> dict[str, object]:
    """Build one manifest-v1 regular-file entry."""
    return {
        "render_path": f"rendered/{path.name}",
        "target_path": path.as_posix(),
        "kind": kind,
        "owner_ref": "service:test",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def _manifest(path: Path, entries: list[dict[str, object]]) -> Path:
    """Write one minimum deterministic manifest."""
    kinds = {entry.get("kind") for entry in entries}
    for kind, target in (
        ("host.sysusers", "/etc/sysusers.d/abhaile.conf"),
        ("host.sudoers", "/etc/sudoers.d/abhaile"),
    ):
        if kind not in kinds:
            entries.append(
                {
                    "render_path": f"foundations/{kind}",
                    "target_path": target,
                    "kind": kind,
                    "owner_ref": (
                        "host-users:test" if kind == "host.sysusers" else "host-sudoers:test"
                    ),
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "size": 0,
                    "apply_hints": {
                        "owner_user": "root",
                        "owner_group": "root",
                        "mode": "0644" if kind == "host.sysusers" else "0440",
                    },
                }
            )
    path.write_text(
        json.dumps({"version": "1", "host": "test", "entries": entries}),
        encoding="utf-8",
    )
    return path


def test_audit_separates_ordinary_and_foundation_entries(tmp_path: Path, monkeypatch: Any) -> None:
    """Keep reserved access foundations outside ordinary repair admission."""
    ordinary = tmp_path / "ordinary"
    sysusers = tmp_path / "sysusers"
    foundation = tmp_path / "sudoers"
    ordinary.write_bytes(b"ordinary")
    sysusers.write_bytes(b"sysusers")
    foundation.write_bytes(b"foundation")
    monkeypatch.setattr(
        integrity,
        "_REQUIRED_FOUNDATIONS",
        {
            ("host.sysusers", sysusers.as_posix()),
            ("host.sudoers", foundation.as_posix()),
        },
    )
    entries = [
        _entry(ordinary, b"ordinary"),
        {
            **_entry(sysusers, b"sysusers", kind="host.sysusers"),
            "owner_ref": "host-users:test",
            "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "0644"},
        },
        {
            **_entry(foundation, b"foundation", kind="host.sudoers"),
            "owner_ref": "host-sudoers:test",
            "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "0440"},
        },
    ]
    manifest = _manifest(tmp_path / "manifest.json", entries)

    assert audit_manifest(manifest, "ordinary", expected_host="test").entries == 1
    assert audit_manifest(manifest, "ordinary", expected_host="test").success is True
    assert audit_manifest(manifest, "enrollment-foundations", expected_host="test").entries == 2
    assert audit_manifest(manifest, "enrollment-foundations", expected_host="test").success is True


def test_audit_reports_content_size_type_and_symlink_drift(tmp_path: Path) -> None:
    """Reject each known mismatch without following redirected leaves."""
    content_path = tmp_path / "content"
    size_path = tmp_path / "size"
    fifo_path = tmp_path / "fifo"
    symlink_path = tmp_path / "symlink"
    content_path.write_bytes(b"wrong")
    size_path.write_bytes(b"too-long")
    os.mkfifo(fifo_path)
    symlink_path.symlink_to(content_path)
    expected = b"right"
    manifest = _manifest(
        tmp_path / "manifest.json",
        [
            _entry(content_path, expected),
            _entry(size_path, expected),
            _entry(fifo_path, expected),
            _entry(symlink_path, expected),
        ],
    )

    result = audit_manifest(manifest, "ordinary", expected_host="test")

    assert result.drift == 4
    assert result.uncertainty == 0
    assert all(path.startswith(".../") for path in result.paths)


def test_audit_treats_oversize_entry_as_uncertain(tmp_path: Path) -> None:
    """Bound unsafe resource demands without hashing the target."""
    target = tmp_path / "large"
    target.write_bytes(b"")
    oversized = _entry(target, b"")
    oversized["size"] = MAX_HASH_BYTES + 1
    manifest = _manifest(tmp_path / "manifest.json", [oversized])

    result = audit_manifest(manifest, "ordinary", expected_host="test")

    assert result.uncertainty == 1
    assert result.success is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda entries: entries.clear(),
        lambda entries: entries.append(dict(entries[0])),
        lambda entries: entries[0].pop("owner_ref"),
        lambda entries: entries[0].__setitem__("is_directory", "false"),
        lambda entries: entries[0].__setitem__("sha256", "z" * 64),
        lambda entries: entries[0].__setitem__("target_path", "/wrong/sysusers"),
    ],
)
def test_audit_rejects_incomplete_or_malformed_manifest(tmp_path: Path, mutation: Any) -> None:
    """Prevent malformed or incomplete authority from becoming vacuously clean."""
    entries = [
        {
            "render_path": "foundations/sysusers",
            "target_path": "/etc/sysusers.d/abhaile.conf",
            "kind": "host.sysusers",
            "owner_ref": "host-users:test",
            "sha256": hashlib.sha256(b"").hexdigest(),
            "size": 0,
            "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "0644"},
        },
        {
            "render_path": "foundations/sudoers",
            "target_path": "/etc/sudoers.d/abhaile",
            "kind": "host.sudoers",
            "owner_ref": "host-sudoers:test",
            "sha256": hashlib.sha256(b"").hexdigest(),
            "size": 0,
            "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "0440"},
        },
    ]
    mutation(entries)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"version": "1", "host": "test", "entries": entries}), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        audit_manifest(manifest, "enrollment-foundations", expected_host="test")


def test_audit_rejects_wrong_host_and_manifest_symlink(tmp_path: Path) -> None:
    """Bind admission to the expected host and a stable regular manifest leaf."""
    manifest = _manifest(tmp_path / "manifest.json", [])
    with pytest.raises(ValueError):
        audit_manifest(manifest, "ordinary", expected_host="other-host")

    link = tmp_path / "linked.json"
    link.symlink_to(manifest)
    with pytest.raises(ValueError):
        audit_manifest(link, "ordinary", expected_host="test")


def test_audit_rejects_extra_fixed_foundation_target(tmp_path: Path) -> None:
    """Keep privileged fixed-kind auditing closed to the two canonical targets."""
    entries: list[dict[str, object]] = []
    _manifest(tmp_path / "initial.json", entries)
    entries.append(
        {
            "render_path": "foundations/extra-sudoers",
            "target_path": "/etc/sudoers.d/extra",
            "kind": "host.sudoers",
            "owner_ref": "host-sudoers:test",
            "sha256": hashlib.sha256(b"").hexdigest(),
            "size": 0,
            "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "0440"},
        }
    )
    manifest = _manifest(tmp_path / "manifest.json", entries)

    with pytest.raises(ValueError, match="fixed enrollment foundation"):
        audit_manifest(manifest, "enrollment-foundations", expected_host="test")


@pytest.mark.parametrize(
    ("target", "owner_ref", "owner_user"),
    [
        ("/home/alice/.ssh/authorized_keys", "principal:bob", "bob"),
        ("/home/alice/.ssh/authorized_keys", "principal:alice", "bob"),
        ("/etc/ssh/.ssh/authorized_keys", "principal:alice", "alice"),
    ],
)
def test_audit_rejects_mismatched_authorized_key_identity(
    tmp_path: Path, target: str, owner_ref: str, owner_user: str
) -> None:
    """Bind authorized-key paths and metadata to their declared principal."""
    entries: list[dict[str, object]] = []
    _manifest(tmp_path / "initial.json", entries)
    entries.append(
        {
            "render_path": "foundations/authorized_keys",
            "target_path": target,
            "kind": "host.authorized_keys",
            "owner_ref": owner_ref,
            "sha256": hashlib.sha256(b"").hexdigest(),
            "size": 0,
            "apply_hints": {
                "owner_user": owner_user,
                "owner_group": owner_user,
                "mode": "0600",
                "ssh_dir_mode": "0700",
            },
        }
    )
    manifest = _manifest(tmp_path / "manifest.json", entries)

    with pytest.raises(ValueError, match="authorized_keys foundation"):
        audit_manifest(manifest, "enrollment-foundations", expected_host="test")


def test_audit_bounds_reported_paths(tmp_path: Path) -> None:
    """Keep operator output finite when broad drift occurs."""
    entries = [_entry(tmp_path / f"missing-{index}", b"") for index in range(20)]
    result = audit_manifest(
        _manifest(tmp_path / "manifest.json", entries), "ordinary", expected_host="test"
    )

    assert result.drift == 20
    assert len(result.paths) == 10


def test_audit_1000_small_files_within_budget(tmp_path: Path) -> None:
    """Meet the standalone five-second compatibility-revision budget."""
    entries: list[dict[str, object]] = []
    for index in range(1000):
        target = tmp_path / f"file-{index}"
        content = f"value-{index}\n".encode()
        target.write_bytes(content)
        entries.append(_entry(target, content))
    manifest = _manifest(tmp_path / "manifest.json", entries)

    started = time.monotonic()
    result = audit_manifest(manifest, "ordinary", expected_host="test")

    assert result.success is True
    assert time.monotonic() - started < 5
