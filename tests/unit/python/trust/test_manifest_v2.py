"""Tests for the closed convergence manifest v2 trust contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from abhaile.trust.errors import TrustError
from abhaile.trust.manifest import validate_manifest


def _software_payload() -> dict[str, Any]:
    return {
        "id": "example",
        "name": "Example download",
        "description": "Install a verified example binary.",
        "operation": "binary-download",
        "execution_policy": "admitted",
        "parameters": {
            "url": "https://example.invalid/example",
            "sha256": "a" * 64,
            "destination": "/usr/local/bin/example",
            "mode": "0755",
        },
        "effects": [{"kind": "path", "target": "/usr/local/bin/example", "role": "primary"}],
        "validation": "binary-version",
        "expected_results": ["The verified binary is installed"],
    }


def _write_software_v2(root: Path, payload: dict[str, Any], *, extra_entry: bool = False) -> None:
    content = yaml.safe_dump(payload, sort_keys=False).encode()
    artifact = root / "software/downloads/example.yaml"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    (root / "manifest.json").write_text(
        json.dumps({"version": "1", "host": "deimos", "entries": []}), encoding="utf-8"
    )
    effects = payload.get("effects", [])
    operation = payload.get("operation")
    kind, action = (
        ("software.build", "build")
        if operation == "container-build"
        else (
            ("software.prerequisite", "ensure")
            if operation not in {"binary-download", "archive-download"}
            else ("software.download", "fetch")
        )
    )
    entries: list[dict[str, Any]] = [
        {
            "render_path": "software/downloads/example.yaml",
            "target_path": None,
            "kind": kind,
            "action": action,
            "owner_ref": "software:example",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "execution_context": "system",
            "metadata": {
                "operation_id": "example",
                "operation_type": payload.get("operation"),
                "execution_policy": payload.get("execution_policy"),
                "effects": effects,
            },
            "validation": "software-result",
            "lifecycle": [],
            "safe_prune": "report-only",
        }
    ]
    owners = {
        "software:example": {
            "name": "software:example",
            "owner_kind": "software",
            "execution_context": "system",
            "requires": [],
        }
    }
    if extra_entry:
        ordinary = root / "system/example"
        ordinary.parent.mkdir()
        ordinary.write_bytes(b"ordinary\n")
        entries.append(
            {
                "render_path": "system/example",
                "target_path": "/usr/local/bin/example",
                "kind": "service.config",
                "action": "publish",
                "owner_ref": "service:example",
                "sha256": hashlib.sha256(b"ordinary\n").hexdigest(),
                "size": 9,
                "execution_context": "system",
                "metadata": {"owner": "root", "group": "root", "mode": "0644"},
                "validation": "structural",
                "lifecycle": [],
                "safe_prune": "safe-if-unchanged",
            }
        )
        owners["service:example"] = {
            "name": "service:example",
            "owner_kind": "service",
            "execution_context": "system",
            "requires": [],
        }
    manifest = {
        "schema_version": 2,
        "host": "deimos",
        "rendered_root": ".",
        "entries": entries,
        "owners": owners,
    }
    (root / "convergence-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_v2(root: Path, mutate: Any = None) -> None:
    artifact = root / "system" / "unit.service"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"unit\n")
    (root / "manifest.json").write_text(
        json.dumps({"version": "1", "host": "deimos", "entries": []}), encoding="utf-8"
    )
    payload = {
        "schema_version": 2,
        "host": "deimos",
        "rendered_root": ".",
        "entries": [
            {
                "render_path": "system/unit.service",
                "target_path": "/etc/systemd/system/unit.service",
                "kind": "systemd.unit",
                "action": "publish",
                "owner_ref": "unit:unit.service",
                "sha256": hashlib.sha256(b"unit\n").hexdigest(),
                "size": 5,
                "execution_context": "system",
                "metadata": {"owner": "root", "group": "root", "mode": "0644"},
                "validation": "systemd",
                "lifecycle": ["manager-reload"],
                "safe_prune": "safe-if-unchanged",
            }
        ],
        "owners": {
            "unit:unit.service": {
                "name": "unit:unit.service",
                "owner_kind": "unit",
                "execution_context": "system",
                "requires": [],
            }
        },
    }
    if mutate is not None:
        mutate(payload)
    (root / "convergence-manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_accepts_complete_v2_and_rejects_unmanifested_output(tmp_path: Path) -> None:
    """Accept exactly covered trees and reject every extra artifact."""
    _write_v2(tmp_path)
    assert validate_manifest(tmp_path, "deimos")["schema_version"] == 2
    (tmp_path / "extra").write_text("unexpected", encoding="utf-8")
    with pytest.raises(TrustError, match="completeness"):
        validate_manifest(tmp_path, "deimos")


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda value: value.update(schema_version=3), "Unsupported"),
        (lambda value: value["entries"][0].update(kind="unknown"), "unsupported"),
        (lambda value: value["entries"][0].update(action="run"), "unsupported"),
        (lambda value: value["entries"][0].pop("metadata"), "incomplete"),
        (lambda value: value["entries"][0].update(target_path="../escape"), "unsafe target"),
        (
            lambda value: value["entries"][0].update(target_path="/root/escape"),
            "allowed root",
        ),
        (lambda value: value["entries"][0].update(owner_ref="missing"), "owner"),
    ],
)
def test_rejects_unknown_or_incomplete_authority(tmp_path: Path, mutate: Any, match: str) -> None:
    """Reject unsupported versions, vocabulary, paths, and references."""
    _write_v2(tmp_path, mutate)
    with pytest.raises(TrustError, match=match):
        validate_manifest(tmp_path, "deimos")


def test_rejects_duplicate_target_and_owner_cycle(tmp_path: Path) -> None:
    """Reject conflicting live authority and cyclic dependency graphs."""

    def duplicate(value: dict[str, Any]) -> None:
        second = dict(value["entries"][0])
        second["render_path"] = "system/other.service"
        value["entries"].append(second)

    _write_v2(tmp_path, duplicate)
    (tmp_path / "system/other.service").write_bytes(b"unit\n")
    with pytest.raises(TrustError, match="duplicate"):
        validate_manifest(tmp_path, "deimos")

    def cycle(value: dict[str, Any]) -> None:
        value["owners"]["unit:unit.service"]["requires"] = ["unit:other.service"]
        value["owners"]["unit:other.service"] = {
            "name": "unit:other.service",
            "owner_kind": "unit",
            "execution_context": "system",
            "requires": ["unit:unit.service"],
        }

    _write_v2(tmp_path, cycle)
    with pytest.raises(TrustError, match="cycle"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_tampering_symlink_and_hardlink(tmp_path: Path) -> None:
    """Reject content mutation and non-regular artifact aliases."""
    _write_v2(tmp_path)
    (tmp_path / "system/unit.service").write_text("tampered", encoding="utf-8")
    with pytest.raises(TrustError, match="integrity"):
        validate_manifest(tmp_path, "deimos")
    (tmp_path / "system/unit.service").unlink()
    (tmp_path / "system/unit.service").symlink_to("/etc/passwd")
    with pytest.raises(TrustError):
        validate_manifest(tmp_path, "deimos")


def test_rejects_unknown_typed_software_operation(tmp_path: Path) -> None:
    """Do not let a renderer smuggle an arbitrary software operation through metadata."""

    def software(value: dict[str, Any]) -> None:
        entry = value["entries"][0]
        entry.update(
            render_path="software/commands/example.yaml",
            target_path=None,
            kind="software.prerequisite",
            action="ensure",
            owner_ref="software:example",
            metadata={
                "operation_id": "example",
                "operation_type": "shell",
                "execution_policy": "admitted",
                "effects": [],
            },
            validation="software-result",
            lifecycle=[],
            safe_prune="report-only",
        )
        value["owners"] = {
            "software:example": {
                "name": "software:example",
                "owner_kind": "software",
                "execution_context": "system",
                "requires": [],
            }
        }

    _write_v2(tmp_path, software)
    target = tmp_path / "software/commands/example.yaml"
    target.parent.mkdir(parents=True)
    (tmp_path / "system/unit.service").replace(target)
    with pytest.raises(TrustError, match="software operation"):
        validate_manifest(tmp_path, "deimos")


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda value: value["parameters"].update(url="http://example.invalid/x"), "HTTPS"),
        (lambda value: value["parameters"].update(sha256="bad"), "digest"),
        (lambda value: value["parameters"].update(destination="/usr/local/../bin/x"), "canonical"),
        (lambda value: value["parameters"].update(mode="0999"), "mode"),
        (lambda value: value.update(validation="units-active"), "pairing"),
        (lambda value: value["parameters"].update(extra=True), "parameters"),
    ],
)
def test_rejects_unsafe_or_incompatible_software_values(
    tmp_path: Path, change: Any, match: str
) -> None:
    payload = _software_payload()
    change(payload)
    _write_software_v2(tmp_path, payload)
    with pytest.raises(TrustError, match=match):
        validate_manifest(tmp_path, "deimos")


def test_rejects_secondary_and_cross_family_target_collisions(tmp_path: Path) -> None:
    payload = _software_payload()
    payload["effects"].append(
        {"kind": "path", "target": "/usr/local/bin/example", "role": "backup"}
    )
    _write_software_v2(tmp_path, payload)
    with pytest.raises(TrustError, match="duplicate mutation"):
        validate_manifest(tmp_path, "deimos")

    other = tmp_path / "cross"
    _write_software_v2(other, _software_payload(), extra_entry=True)
    with pytest.raises(TrustError, match="duplicate path|conflicting mutation"):
        validate_manifest(other, "deimos")


def test_rejects_cross_operation_target_collision(tmp_path: Path) -> None:
    payload = _software_payload()
    _write_software_v2(tmp_path, payload)
    manifest_path = tmp_path / "convergence-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    second_payload = {**payload, "id": "other", "name": "Other download"}
    content = yaml.safe_dump(second_payload, sort_keys=False).encode()
    artifact = tmp_path / "software/downloads/other.yaml"
    artifact.write_bytes(content)
    second = dict(manifest["entries"][0])
    second.update(
        render_path="software/downloads/other.yaml",
        owner_ref="software:other",
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
        metadata={**second["metadata"], "operation_id": "other"},
    )
    manifest["entries"].append(second)
    manifest["owners"]["software:other"] = {
        "name": "software:other",
        "owner_kind": "software",
        "execution_context": "system",
        "requires": [],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TrustError, match="conflicting mutation"):
        validate_manifest(tmp_path, "deimos")


def test_rejects_malformed_nested_units_and_unsafe_output_glob(tmp_path: Path) -> None:
    units = {
        "id": "example",
        "name": "Units",
        "description": "Manage units.",
        "operation": "systemd-units",
        "execution_policy": "admitted",
        "parameters": {"units": [{"name": "bad/name.service", "enabled": 1, "state": "start"}]},
        "effects": [{"kind": "unit", "target": "bad/name.service", "role": "activation"}],
        "validation": "units-active",
        "expected_results": ["Units are ready"],
    }
    _write_software_v2(tmp_path, units)
    with pytest.raises(TrustError, match="unit"):
        validate_manifest(tmp_path, "deimos")

    build_root = tmp_path / "build"
    build = {
        "id": "example",
        "name": "Build",
        "description": "Build a package.",
        "operation": "container-build",
        "execution_policy": "phase4-integrity-blocked",
        "parameters": {
            "url": "https://example.invalid/source.git",
            "source_ref": "v1",
            "containerfile_base": "example.invalid/base:test",
            "output_glob": "../*.deb",
        },
        "effects": [
            {
                "kind": "artifact-set",
                "target": "/var/lib/abhaile/builds/example",
                "role": "output",
                "pattern": "../*.deb",
                "cardinality": 2,
            }
        ],
        "validation": "package-artifact",
        "expected_results": ["One package is built"],
    }
    _write_software_v2(build_root, build)
    with pytest.raises(TrustError, match="glob|artifact-set"):
        validate_manifest(build_root, "deimos")
