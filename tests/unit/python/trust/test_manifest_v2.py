"""Tests for the closed convergence manifest v2 trust contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from abhaile.models.artifact import RenderedArtifact
from abhaile.renderers.convergence_manifest import _entry, _restart_authority
from abhaile.trust.errors import TrustError
from abhaile.trust.manifest import validate_manifest
from abhaile.utils.errors import RenderError


def test_renderer_rejects_circular_unmanaged_restart_authority() -> None:
    """Do not let an entry manufacture authority over an unrelated system unit."""
    with pytest.raises(RenderError, match="no reviewed authority"):
        _restart_authority("service:example", "system", "sshd.service", [])
    assert (
        _restart_authority("service:chrony-a", "system", "chrony.service", []) == "service:chrony-a"
    )
    with pytest.raises(RenderError, match="no reviewed authority"):
        _restart_authority("service:chrony-lookalike", "system", "chrony.service", [])


def test_renderer_rejects_cross_owner_managed_restart_authority() -> None:
    """Do not turn another service's managed unit into restart authority."""
    managed = RenderedArtifact(
        "services/vault/vault.service",
        "/etc/systemd/system/vault.service",
        "systemd.unit",
        "unit:vault.service",
        b"[Service]\n",
    )
    with pytest.raises(RenderError, match="unrelated owner"):
        _restart_authority("service:example", "system", "vault.service", [managed])
    assert (
        _restart_authority("service:vault", "system", "vault.service", [managed])
        == "unit:vault.service"
    )


def test_rootless_quadlet_uses_root_owned_per_uid_publication_authority() -> None:
    """Keep rootless unit publication outside user-writable ancestry."""
    content = b"[Container]\nImage=example.invalid/example@sha256:" + b"1" * 64 + b"\n"
    artifact = RenderedArtifact(
        "services/example/example.container",
        "/home/abhaile/.config/containers/systemd/example.container",
        "quadlet.container",
        "service:example",
        content,
        hash=hashlib.sha256(content).hexdigest(),
        size=len(content),
        apply_hints={"rootless": True, "podman_user": "abhaile", "mode": "0644"},
    )
    entry = _entry(
        artifact,
        [artifact],
        {
            "user:abhaile": {
                "uid": 1001,
                "gid": 1001,
                "home": "/home/abhaile",
                "runtime_dir": "/run/user/1001",
            }
        },
    )
    assert entry["target_path"] == "/etc/containers/systemd/users/1001/example.container"
    assert entry["metadata"] == {"owner": "root", "group": "root", "mode": "0644"}


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
            "max_bytes": 1048576,
            "redirect_origins": [],
            "max_redirects": 0,
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
            "lifecycle_metadata": {},
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
                "lifecycle_metadata": {},
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
        "execution_identities": {},
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
        "execution_identities": {},
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
                "lifecycle_metadata": {},
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
        (lambda value: value["entries"][0].pop("lifecycle_metadata"), "incomplete"),
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


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"service-restart": {"unit": "bad/name.service", "mode": "restart"}},
        {"service-restart": {"unit": "unit.service", "mode": "reload"}},
        {"service-restart": {"unit": "unit.service", "mode": "restart", "extra": True}},
    ],
)
def test_rejects_missing_or_malformed_restart_authority(
    tmp_path: Path, metadata: dict[str, object]
) -> None:
    """Require exact unit and bounded mode authority for every restart effect."""

    def mutate(value: dict[str, Any]) -> None:
        value["entries"][0]["lifecycle"] = ["manager-reload", "service-restart"]
        value["entries"][0]["lifecycle_metadata"] = metadata

    _write_v2(tmp_path, mutate)
    with pytest.raises(TrustError, match="lifecycle|restart"):
        validate_manifest(tmp_path, "deimos")


def test_accepts_same_owner_system_and_named_user_restart_authority(tmp_path: Path) -> None:
    """Bind automatic restarts to the exact managed owner and execution identity."""

    def system_restart(value: dict[str, Any]) -> None:
        owner = value["owners"]["unit:unit.service"]
        owner["restart_authorities"] = [
            {
                "unit": "unit.service",
                "execution_context": "system",
                "authority_owner": "unit:unit.service",
            }
        ]
        entry = value["entries"][0]
        entry["lifecycle"] = ["manager-reload", "service-restart"]
        entry["lifecycle_metadata"] = {
            "service-restart": {
                "unit": "unit.service",
                "mode": "restart",
                "authority_owner": "unit:unit.service",
            }
        }

    _write_v2(tmp_path, system_restart)
    assert validate_manifest(tmp_path, "deimos")["schema_version"] == 2

    user_root = tmp_path / "user"

    def user_restart(value: dict[str, Any]) -> None:
        identity = {
            "name": "svc",
            "uid": 1200,
            "gid": 1200,
            "home": "/home/svc",
            "shell": "/bin/bash",
        }
        value["execution_identities"] = {"user:svc": identity}
        owner = value["owners"]["unit:unit.service"]
        owner["execution_context"] = "user:svc"
        owner["restart_authorities"] = [
            {
                "unit": "unit.service",
                "execution_context": "user:svc",
                "authority_owner": "unit:unit.service",
            }
        ]
        entry = value["entries"][0]
        entry["execution_context"] = "user:svc"
        entry["lifecycle"] = ["manager-reload", "service-restart"]
        entry["lifecycle_metadata"] = {
            "service-restart": {
                "unit": "unit.service",
                "mode": "try-restart",
                "authority_owner": "unit:unit.service",
            }
        }

    _write_v2(user_root, user_restart)
    assert validate_manifest(user_root, "deimos")["schema_version"] == 2


@pytest.mark.parametrize("case", ["missing", "unrelated", "cross-owner", "cross-context", "runner"])
def test_rejects_unowned_or_cross_context_restart_authority(tmp_path: Path, case: str) -> None:
    """Reject restart authority that is absent, unrelated, or crosses trust context."""

    def mutate(value: dict[str, Any]) -> None:
        owner = value["owners"]["unit:unit.service"]
        authority_owner = "unit:unit.service"
        unit = "unit.service"
        context = "system"
        if case == "unrelated":
            unit = "sshd.service"
        elif case == "cross-owner":
            authority_owner = "unit:other.service"
        elif case == "cross-context":
            context = "user:svc"
            value["execution_identities"] = {
                "user:svc": {
                    "name": "svc",
                    "uid": 1200,
                    "gid": 1200,
                    "home": "/home/svc",
                    "shell": "/bin/bash",
                }
            }
        elif case == "runner":
            unit = "abhaile-runner.service"
        declared_unit = "unit.service" if case == "unrelated" else unit
        if case != "missing":
            owner["restart_authorities"] = [
                {
                    "unit": declared_unit,
                    "execution_context": context,
                    "authority_owner": authority_owner,
                }
            ]
        entry = value["entries"][0]
        entry["lifecycle"] = ["manager-reload", "service-restart"]
        entry["lifecycle_metadata"] = {
            "service-restart": {
                "unit": unit,
                "mode": "restart",
                "authority_owner": authority_owner,
            }
        }

    _write_v2(tmp_path, mutate)
    with pytest.raises(TrustError, match="restart|context|runner|identity"):
        validate_manifest(tmp_path, "deimos")


def test_manual_restart_policy_emits_no_automatic_authority(tmp_path: Path) -> None:
    """Keep manual policy represented by the absence of automatic lifecycle authority."""
    _write_v2(tmp_path)
    manifest = validate_manifest(tmp_path, "deimos")
    assert manifest["entries"][0]["lifecycle"] == ["manager-reload"]
    assert manifest["entries"][0]["lifecycle_metadata"] == {}


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
