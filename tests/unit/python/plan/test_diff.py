"""Unit tests for apply manifest drift planning."""

from __future__ import annotations

import json
import os
import grp
import pwd
from pathlib import Path

import pytest

from abhaile.plan.diff import plan_manifest_drift
from abhaile.utils.errors import DiffError


def _write_manifest(
    path: Path,
    host: str,
    entries: list[dict[str, object]],
    *,
    owners: dict[str, dict[str, object]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_entries: list[dict[str, object]] = []
    for entry in entries:
        normalized = dict(entry)
        normalized.setdefault("kind", "service.config")
        normalized.setdefault("owner_ref", "service:test")
        normalized_entries.append(normalized)

    payload: dict[str, object] = {
        "version": "1",
        "host": host,
        "entries": normalized_entries,
    }
    if owners:
        payload["owners"] = owners
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _sha_of(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _directory_manifest_entry(
    target_path: Path,
    *,
    render_path: str,
    owner_ref: str,
    owner: str,
    group: str,
    mode: str,
    kind: str = "service.directory",
) -> dict[str, object]:
    return {
        "render_path": render_path,
        "target_path": target_path.as_posix(),
        "kind": kind,
        "owner_ref": owner_ref,
        "sha256": _sha_of(""),
        "size": 0,
        "is_directory": True,
        "apply_hints": {
            "owner": owner,
            "group": group,
            "mode": mode,
        },
    }


def _quadlet_container_entry(
    target_path: Path,
    *,
    image: str,
    owner_ref: str = "unit:blocky.service",
    render_path: str = "services/blocky/etc/containers/systemd/blocky.container",
    rootless: bool = False,
    podman_user: str | None = None,
) -> dict[str, object]:
    hints: dict[str, object] = {
        "rootless": rootless,
        "podman_image": image,
        "pull_policy": "missing",
    }
    if podman_user:
        hints["podman_user"] = podman_user
    return {
        "render_path": render_path,
        "target_path": target_path.as_posix(),
        "kind": "quadlet.container",
        "owner_ref": owner_ref,
        "sha256": _sha_of(f"[Container]\nImage={image}\nPull=missing\n"),
        "size": len(f"[Container]\nImage={image}\nPull=missing\n"),
        "apply_hints": hints,
    }


def _quadlet_build_entry(
    target_path: Path,
    *,
    fingerprint: str,
    output_image: str = "localhost/coredns-omada:latest",
    owner_ref: str = "unit:coredns-omada-build.service",
    consumers: list[str] | None = None,
) -> dict[str, object]:
    content = "[Build]\nImageTag=localhost/coredns-omada:latest\nPull=missing\n"
    return {
        "render_path": "services/coredns/etc/containers/systemd/coredns-omada.build",
        "target_path": target_path.as_posix(),
        "kind": "quadlet.build",
        "owner_ref": owner_ref,
        "sha256": _sha_of(content),
        "size": len(content),
        "apply_hints": {
            "rootless": False,
            "managed_build": {
                "service": "coredns-omada",
                "output_image": output_image,
                "pull_policy": "missing",
                "input_fingerprint": fingerprint,
                "inputs": [
                    "coredns-omada/quadlets/build.build",
                    "coredns-omada/build/Containerfile",
                ],
                "post_build": {
                    "install_unit": "coredns-omada-install.service",
                    "verify_binary": "/usr/local/bin/coredns",
                },
                "consumers": consumers or ["coredns.service"],
            },
        },
    }


class TestPlanManifestDrift:
    """Tests for plan_manifest_drift()."""

    def test_directory_entry_is_converged_when_metadata_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Matching directory metadata should not schedule a write."""
        target = tmp_path / "target" / "srv" / "vault" / "agent" / "out"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        _write_manifest(
            desired_manifest,
            "deimos",
            [
                _directory_manifest_entry(
                    target,
                    render_path="services/vault/srv/vault/agent/out",
                    owner_ref="service:vault",
                    owner="abhaile",
                    group="abhaile",
                    mode="0750",
                )
            ],
        )
        _write_manifest(
            applied_manifest,
            "deimos",
            [
                _directory_manifest_entry(
                    target,
                    render_path="services/vault/srv/vault/agent/out",
                    owner_ref="service:vault",
                    owner="abhaile",
                    group="abhaile",
                    mode="0750",
                )
            ],
        )

        monkeypatch.setattr(
            "abhaile.plan.diff._live_directory_state",
            lambda path: {
                "state": "directory",
                "live_metadata": {"owner": "abhaile", "group": "abhaile", "mode": "0750"},
            },
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["writes"] == 0
        assert plan["summary"]["changed"] == 0
        assert plan["sync"]["writes"] == []

    def test_directory_entry_missing_reports_missing_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing directory targets should schedule a write with missing reason."""
        target = tmp_path / "target" / "srv" / "vault" / "agent" / "run"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        entry = _directory_manifest_entry(
            target,
            render_path="services/vault/srv/vault/agent/run",
            owner_ref="service:vault",
            owner="abhaile",
            group="abhaile",
            mode="0750",
        )
        _write_manifest(desired_manifest, "deimos", [entry])
        _write_manifest(applied_manifest, "deimos", [entry])

        monkeypatch.setattr(
            "abhaile.plan.diff._live_directory_state",
            lambda path: {"state": "missing"},
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["writes"] == 1
        assert plan["sync"]["writes"][0]["reason"] == "missing"
        assert plan["sync"]["writes"][0]["desired_metadata"] == {
            "owner": "abhaile",
            "group": "abhaile",
            "mode": "0750",
        }

    @pytest.mark.parametrize("field", ["owner", "group", "mode"])
    def test_directory_entry_metadata_drift_reports_change(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
    ) -> None:
        """Wrong directory metadata should be reported as metadata drift."""
        target = tmp_path / "target" / "srv" / "vault" / "agent" / "templates"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        entry = _directory_manifest_entry(
            target,
            render_path="services/vault/srv/vault/agent/templates",
            owner_ref="service:vault",
            owner="abhaile",
            group="abhaile",
            mode="0750",
        )
        _write_manifest(desired_manifest, "deimos", [entry])
        _write_manifest(applied_manifest, "deimos", [entry])

        live_metadata = {"owner": "abhaile", "group": "abhaile", "mode": "0750"}
        live_metadata[field] = "root" if field != "mode" else "0777"
        monkeypatch.setattr(
            "abhaile.plan.diff._live_directory_state",
            lambda path: {"state": "directory", "live_metadata": live_metadata},
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["writes"] == 1
        assert plan["sync"]["writes"][0]["reason"] == "metadata-drift"
        assert plan["sync"]["writes"][0]["desired_metadata"] == {
            "owner": "abhaile",
            "group": "abhaile",
            "mode": "0750",
        }
        assert plan["sync"]["writes"][0]["live_metadata"] == live_metadata

    @pytest.mark.parametrize("entry_type", ["file", "symlink"])
    def test_directory_entry_type_conflict_reports_change(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entry_type: str,
    ) -> None:
        """Non-directory live targets should be reported as type conflicts."""
        target = tmp_path / "target" / "etc" / "systemd" / "network" / "21-ipvlan-l2.network.d"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        entry = _directory_manifest_entry(
            target,
            render_path="hosts/phobos/etc/systemd/network/21-ipvlan-l2.network.d",
            owner_ref="host:phobos",
            owner="root",
            group="root",
            mode="0755",
            kind="networkd.dropin",
        )
        _write_manifest(desired_manifest, "phobos", [entry])
        _write_manifest(applied_manifest, "phobos", [entry])

        monkeypatch.setattr(
            "abhaile.plan.diff._live_directory_state",
            lambda path: {
                "state": "type-conflict",
                "live_metadata": {
                    "owner": "root",
                    "group": "root",
                    "mode": "0644",
                    "type": entry_type,
                },
            },
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["writes"] == 1
        assert plan["sync"]["writes"][0]["reason"] == "type-conflict"
        assert plan["sync"]["writes"][0]["live_metadata"]["type"] == entry_type

    def test_directory_contents_do_not_affect_convergence(self, tmp_path: Path) -> None:
        """Nested files inside a managed directory should not trigger drift."""
        target = tmp_path / "target" / "srv" / "vault" / "agent" / "templates"
        target.mkdir(parents=True, exist_ok=True)
        (target / "runtime.txt").write_text("runtime content\n")
        target.chmod(0o750)

        uid = os.getuid()
        gid = os.getgid()
        owner = pwd.getpwuid(uid).pw_name
        group = grp.getgrgid(gid).gr_name

        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"
        entry = _directory_manifest_entry(
            target,
            render_path="services/vault/srv/vault/agent/templates",
            owner_ref="service:vault",
            owner=owner,
            group=group,
            mode="0750",
        )
        _write_manifest(desired_manifest, "deimos", [entry])
        _write_manifest(applied_manifest, "deimos", [entry])

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["writes"] == 0
        assert plan["summary"]["changed"] == 0

    def test_missing_applied_manifest_treated_as_empty(self, tmp_path: Path) -> None:
        """Missing applied manifest should result in added+write actions."""
        target = tmp_path / "target" / "etc" / "app.conf"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        _write_manifest(
            desired_manifest,
            "deimos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target.as_posix(),
                    "sha256": _sha_of("value=1\n"),
                    "size": 8,
                }
            ],
        )

        plan = plan_manifest_drift(desired_manifest, tmp_path / "out" / "state" / "manifest.json")

        assert plan["summary"]["added"] == 1
        assert plan["summary"]["writes"] == 1
        assert plan["summary"]["removed"] == 0

    def test_changed_quadlet_image_creates_pre_pull_action(self, tmp_path: Path) -> None:
        """Changed container image metadata should create an explicit pre-pull plan."""
        target = tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        _write_manifest(
            desired_manifest,
            "deimos",
            [_quadlet_container_entry(target, image="ghcr.io/0xerr0r/blocky:v0.28.0")],
        )
        _write_manifest(
            applied_manifest,
            "deimos",
            [_quadlet_container_entry(target, image="ghcr.io/0xerr0r/blocky:v0.27.0")],
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["image_acquisitions"] == [
            {
                "service": "blocky",
                "owner_ref": "unit:blocky.service",
                "target_path": target.as_posix(),
                "scope": "rootful",
                "old_image": "ghcr.io/0xerr0r/blocky:v0.27.0",
                "desired_image": "ghcr.io/0xerr0r/blocky:v0.28.0",
                "pull_policy": "missing",
                "action": "pre-pull",
            }
        ]

    def test_unchanged_quadlet_image_creates_no_pre_pull_action(self, tmp_path: Path) -> None:
        """Unchanged image metadata should not acquire on unrelated container drift."""
        target = tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"
        entry = _quadlet_container_entry(target, image="ghcr.io/0xerr0r/blocky:v0.27.0")
        drifted_entry = dict(entry)
        drifted_entry["sha256"] = _sha_of("[Container]\nImage=ghcr.io/0xerr0r/blocky:v0.27.0\n")

        _write_manifest(desired_manifest, "deimos", [entry])
        _write_manifest(applied_manifest, "deimos", [drifted_entry])

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["image_acquisitions"] == []

    def test_new_quadlet_container_records_acquisition_candidate(self, tmp_path: Path) -> None:
        """New registry-backed containers should expose image acquisition intent."""
        target = tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"

        _write_manifest(
            desired_manifest,
            "deimos",
            [_quadlet_container_entry(target, image="ghcr.io/0xerr0r/blocky:v0.27.0")],
        )

        plan = plan_manifest_drift(desired_manifest, tmp_path / "out" / "state" / "manifest.json")

        assert plan["image_acquisitions"][0]["old_image"] is None
        assert plan["image_acquisitions"][0]["desired_image"] == "ghcr.io/0xerr0r/blocky:v0.27.0"

    def test_rootless_quadlet_image_acquisition_records_user(self, tmp_path: Path) -> None:
        """Rootless image changes should be planned under the configured Podman user."""
        target = (
            tmp_path
            / "target"
            / "home"
            / "abhaile"
            / ".config"
            / "containers"
            / "systemd"
            / "vault-agent.container"
        )
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        _write_manifest(
            desired_manifest,
            "deimos",
            [
                _quadlet_container_entry(
                    target,
                    image="docker.io/hashicorp/vault:1.21.4",
                    owner_ref="unit:vault-agent.service",
                    render_path="services/vault-agent/home/abhaile/.config/containers/systemd/vault-agent.container",
                    rootless=True,
                    podman_user="abhaile",
                )
            ],
        )
        _write_manifest(
            applied_manifest,
            "deimos",
            [
                _quadlet_container_entry(
                    target,
                    image="docker.io/hashicorp/vault:1.20.0",
                    owner_ref="unit:vault-agent.service",
                    render_path="services/vault-agent/home/abhaile/.config/containers/systemd/vault-agent.container",
                    rootless=True,
                    podman_user="abhaile",
                )
            ],
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["image_acquisitions"][0]["scope"] == "rootless"
        assert plan["image_acquisitions"][0]["run_as_user"] == "abhaile"

    def test_changed_build_fingerprint_creates_managed_build_transaction(
        self, tmp_path: Path
    ) -> None:
        """Changed managed build inputs should create one explicit build transaction."""
        target = tmp_path / "target" / "etc/containers/systemd/coredns-omada.build"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"
        _write_manifest(
            desired_manifest,
            "phobos",
            [_quadlet_build_entry(target, fingerprint="f" * 64)],
        )
        _write_manifest(
            applied_manifest,
            "phobos",
            [_quadlet_build_entry(target, fingerprint="e" * 64)],
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["build_transactions"] == [
            {
                "service": "coredns-omada",
                "owner_ref": "unit:coredns-omada-build.service",
                "target_path": target.as_posix(),
                "scope": "rootful",
                "old_fingerprint": "e" * 64,
                "desired_fingerprint": "f" * 64,
                "output_image": "localhost/coredns-omada:latest",
                "pull_policy": "missing",
                "build_unit": "coredns-omada-build.service",
                "inputs": [
                    "coredns-omada/quadlets/build.build",
                    "coredns-omada/build/Containerfile",
                ],
                "consumers": ["coredns.service"],
                "action": "build",
                "post_build": {
                    "install_unit": "coredns-omada-install.service",
                    "verify_binary": "/usr/local/bin/coredns",
                },
            }
        ]

    def test_unchanged_build_fingerprint_creates_no_build_transaction(self, tmp_path: Path) -> None:
        """Unchanged managed build inputs should not schedule a build."""
        target = tmp_path / "target" / "etc/containers/systemd/coredns-omada.build"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"
        entry = _quadlet_build_entry(target, fingerprint="f" * 64)
        _write_manifest(desired_manifest, "phobos", [entry])
        _write_manifest(applied_manifest, "phobos", [entry])

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["build_transactions"] == []

    def test_removed_file_is_prune_safe_when_live_matches_applied(self, tmp_path: Path) -> None:
        """Removed files are prune-safe only when live hash matches applied hash."""
        removed_target = tmp_path / "target" / "etc" / "old.conf"
        removed_target.parent.mkdir(parents=True, exist_ok=True)
        removed_target.write_text("old=yes\n")

        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        _write_manifest(desired_manifest, "deimos", [])
        _write_manifest(
            applied_manifest,
            "deimos",
            [
                {
                    "render_path": "system/etc/old.conf",
                    "target_path": removed_target.as_posix(),
                    "sha256": _sha_of("old=yes\n"),
                    "size": 8,
                }
            ],
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["removed"] == 1
        assert plan["summary"]["removals_safe"] == 1
        assert plan["summary"]["removals_drifted"] == 0

    def test_removed_file_is_drifted_when_live_hash_differs(self, tmp_path: Path) -> None:
        """Removed files with live drift are reported as drifted removals."""
        removed_target = tmp_path / "target" / "etc" / "old.conf"
        removed_target.parent.mkdir(parents=True, exist_ok=True)
        removed_target.write_text("locally-modified\n")

        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        _write_manifest(desired_manifest, "phobos", [])
        _write_manifest(
            applied_manifest,
            "phobos",
            [
                {
                    "render_path": "system/etc/old.conf",
                    "target_path": removed_target.as_posix(),
                    "sha256": _sha_of("old=yes\n"),
                    "size": 8,
                }
            ],
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["summary"]["removed"] == 1
        assert plan["summary"]["removals_safe"] == 0
        assert plan["summary"]["removals_drifted"] == 1

    def test_host_mismatch_between_desired_and_applied_raises(self, tmp_path: Path) -> None:
        """State host mismatch should fail closed."""
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        _write_manifest(desired_manifest, "deimos", [])
        _write_manifest(applied_manifest, "phobos", [])

        with pytest.raises(DiffError, match="State host mismatch"):
            plan_manifest_drift(desired_manifest, applied_manifest)

    def test_owner_plan_groups_writes_and_expands_dependencies(self, tmp_path: Path) -> None:
        """Changed owners should be grouped and ordered after dependency expansion."""
        target_cfg = tmp_path / "target" / "etc" / "app.conf"
        target_cfg.parent.mkdir(parents=True, exist_ok=True)

        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        _write_manifest(
            desired_manifest,
            "deimos",
            [
                {
                    "render_path": "system/etc/app.conf",
                    "target_path": target_cfg.as_posix(),
                    "sha256": _sha_of("new-value\n"),
                    "size": 10,
                    "owner_ref": "service:app",
                }
            ],
            owners={
                "unit:network-online.target": {
                    "name": "unit:network-online.target",
                },
                "service:app": {
                    "name": "service:app",
                    "requires": ["unit:network-online.target"],
                },
            },
        )

        plan = plan_manifest_drift(desired_manifest, tmp_path / "out" / "state" / "manifest.json")

        owner_plan = plan["owner_plan"]
        owners = owner_plan["owners"]
        assert [owner["owner_ref"] for owner in owners] == [
            "unit:network-online.target",
            "service:app",
        ]
        assert owners[0]["changed"] is False
        assert owners[1]["changed"] is True
        assert len(owners[1]["writes"]) == 1
        assert owners[1]["writes"][0]["target_path"] == target_cfg.as_posix()
        assert owner_plan["summary"]["expanded_owners"] == 2
        assert owner_plan["summary"]["changed_owners"] == 1

    def test_owner_plan_cycle_detection_raises(self, tmp_path: Path) -> None:
        """Owner dependency cycles should fail closed."""
        target_cfg = tmp_path / "target" / "etc" / "cyclic.conf"
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        _write_manifest(
            desired_manifest,
            "deimos",
            [
                {
                    "render_path": "system/etc/cyclic.conf",
                    "target_path": target_cfg.as_posix(),
                    "sha256": _sha_of("cyclic\n"),
                    "size": 7,
                    "owner_ref": "owner:a",
                }
            ],
            owners={
                "owner:a": {"name": "owner:a", "requires": ["owner:b"]},
                "owner:b": {"name": "owner:b", "requires": ["owner:a"]},
            },
        )

        with pytest.raises(DiffError, match="Owner dependency cycle"):
            plan_manifest_drift(desired_manifest, tmp_path / "out" / "state" / "manifest.json")

    def test_owner_plan_maps_removals_to_applied_owner(self, tmp_path: Path) -> None:
        """Removal ownership should come from applied entries."""
        removed_target = tmp_path / "target" / "etc" / "removed.conf"
        removed_target.parent.mkdir(parents=True, exist_ok=True)
        removed_target.write_text("stale=yes\n")

        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"
        _write_manifest(desired_manifest, "phobos", [])
        _write_manifest(
            applied_manifest,
            "phobos",
            [
                {
                    "render_path": "system/etc/removed.conf",
                    "target_path": removed_target.as_posix(),
                    "sha256": _sha_of("original\n"),
                    "size": 9,
                    "owner_ref": "service:legacy",
                }
            ],
            owners={
                "service:legacy": {"name": "service:legacy"},
            },
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)
        owner_bundle = next(
            owner
            for owner in plan["owner_plan"]["owners"]
            if owner["owner_ref"] == "service:legacy"
        )

        assert owner_bundle["changed"] is True
        assert owner_bundle["removals_drifted"]
        assert owner_bundle["removals_drifted"][0]["target_path"] == removed_target.as_posix()
        assert "prune-drifted" in owner_bundle["escalations"]

    def test_networkd_netdev_delete_order_is_child_first(self, tmp_path: Path) -> None:
        """Removed networkd.netdev owners should be ordered child-first for deletes."""
        parent_target = tmp_path / "target" / "etc" / "systemd" / "network" / "20-ipvlan-l2.netdev"
        child_target = (
            tmp_path / "target" / "etc" / "systemd" / "network" / "40-ipvlan-l2.100.netdev"
        )
        parent_target.parent.mkdir(parents=True, exist_ok=True)
        parent_target.write_text("[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n")
        child_target.write_text("[NetDev]\nName=ipvlan-l2.100\nKind=ipvlan\n")

        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"
        _write_manifest(desired_manifest, "phobos", [])
        _write_manifest(
            applied_manifest,
            "phobos",
            [
                {
                    "render_path": "system/etc/systemd/network/20-ipvlan-l2.netdev",
                    "target_path": parent_target.as_posix(),
                    "sha256": _sha_of("[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n"),
                    "size": len("[NetDev]\nName=ipvlan-l2\nKind=ipvlan\n"),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2",
                },
                {
                    "render_path": "system/etc/systemd/network/40-ipvlan-l2.100.netdev",
                    "target_path": child_target.as_posix(),
                    "sha256": _sha_of("[NetDev]\nName=ipvlan-l2.100\nKind=ipvlan\n"),
                    "size": len("[NetDev]\nName=ipvlan-l2.100\nKind=ipvlan\n"),
                    "kind": "networkd.netdev",
                    "owner_ref": "iface:ipvlan-l2.100",
                },
            ],
            owners={
                "iface:ipvlan-l2": {"name": "iface:ipvlan-l2"},
                "iface:ipvlan-l2.100": {
                    "name": "iface:ipvlan-l2.100",
                    "requires": ["iface:ipvlan-l2"],
                },
            },
        )

        plan = plan_manifest_drift(desired_manifest, applied_manifest)
        assert plan["networkd_netdev_delete_order"] == [
            "iface:ipvlan-l2.100",
            "iface:ipvlan-l2",
        ]

    def test_quadlet_convergence_plan_uses_reverse_owner_dependencies(self, tmp_path: Path) -> None:
        """Changed quadlet networks should emit stop/start plans for dependent containers."""
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        network_target = tmp_path / "target" / "etc" / "containers" / "systemd" / "services.network"
        container_target = (
            tmp_path / "target" / "etc" / "containers" / "systemd" / "blocky.container"
        )
        container_target.parent.mkdir(parents=True, exist_ok=True)
        container_target.write_text("[Container]\nImage=blocky:latest\n")

        _write_manifest(
            desired_manifest,
            "phobos",
            [
                {
                    "render_path": "services/_shared/etc/containers/systemd/services.network",
                    "target_path": network_target.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:services-network.service",
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n"),
                    "size": len("[Network]\nDriver=ipvlan\n"),
                },
                {
                    "render_path": "services/blocky/etc/containers/systemd/blocky.container",
                    "target_path": container_target.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:blocky.service",
                    "sha256": _sha_of("[Container]\nImage=blocky:latest\n"),
                    "size": len("[Container]\nImage=blocky:latest\n"),
                },
            ],
            owners={
                "unit:services-network.service": {"name": "unit:services-network.service"},
                "unit:blocky.service": {
                    "name": "unit:blocky.service",
                    "requires": ["unit:services-network.service"],
                },
            },
        )
        _write_manifest(applied_manifest, "phobos", [])

        plan = plan_manifest_drift(desired_manifest, applied_manifest)

        assert plan["quadlet_convergence_plans"] == {
            "unit:services-network.service": [
                {"owner_ref": "unit:blocky.service", "action": "stop"},
                {"owner_ref": "unit:blocky.service", "action": "start"},
            ]
        }

    def test_quadlet_convergence_plan_deduplicates_shared_dependents(self, tmp_path: Path) -> None:
        """Shared dependents should be stopped once and restarted once across multiple primaries."""
        desired_manifest = tmp_path / "out" / "rendered" / "manifest.json"
        applied_manifest = tmp_path / "out" / "state" / "manifest.json"

        alpha_network = tmp_path / "target" / "etc" / "containers" / "systemd" / "alpha.network"
        beta_network = tmp_path / "target" / "etc" / "containers" / "systemd" / "beta.network"
        dependent_container = (
            tmp_path / "target" / "etc" / "containers" / "systemd" / "app.container"
        )
        dependent_container.parent.mkdir(parents=True, exist_ok=True)
        dependent_container.write_text("[Container]\nImage=app:latest\n")

        _write_manifest(
            desired_manifest,
            "phobos",
            [
                {
                    "render_path": "services/_shared/etc/containers/systemd/alpha.network",
                    "target_path": alpha_network.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:alpha-network.service",
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n"),
                    "size": len("[Network]\nDriver=ipvlan\n"),
                },
                {
                    "render_path": "services/_shared/etc/containers/systemd/beta.network",
                    "target_path": beta_network.as_posix(),
                    "kind": "quadlet.network",
                    "owner_ref": "unit:beta-network.service",
                    "sha256": _sha_of("[Network]\nDriver=ipvlan\n#beta\n"),
                    "size": len("[Network]\nDriver=ipvlan\n#beta\n"),
                },
                {
                    "render_path": "services/app/etc/containers/systemd/app.container",
                    "target_path": dependent_container.as_posix(),
                    "kind": "quadlet.container",
                    "owner_ref": "unit:app.service",
                    "sha256": _sha_of("[Container]\nImage=app:latest\n"),
                    "size": len("[Container]\nImage=app:latest\n"),
                },
            ],
            owners={
                "unit:alpha-network.service": {"name": "unit:alpha-network.service"},
                "unit:beta-network.service": {"name": "unit:beta-network.service"},
                "unit:app.service": {
                    "name": "unit:app.service",
                    "requires": [
                        "unit:alpha-network.service",
                        "unit:beta-network.service",
                    ],
                },
            },
        )
        _write_manifest(applied_manifest, "phobos", [])

        plan = plan_manifest_drift(desired_manifest, applied_manifest)
        assert plan["quadlet_convergence_plans"] == {
            "unit:alpha-network.service": [
                {"owner_ref": "unit:app.service", "action": "stop"},
            ],
            "unit:beta-network.service": [
                {"owner_ref": "unit:app.service", "action": "start"},
            ],
        }
