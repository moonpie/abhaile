"""Unit tests for apply manifest drift planning."""

from __future__ import annotations

import json
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


class TestPlanManifestDrift:
    """Tests for plan_manifest_drift()."""

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
