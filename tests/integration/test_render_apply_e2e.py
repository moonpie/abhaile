"""Integration tests for real-config render output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from abhaile.cli.render import load_and_validate, render_host
from abhaile.models.kinds import ALL_KINDS
from abhaile.plan.diff import plan_manifest_drift
from abhaile.utils.config import clear_config_cache
from abhaile.utils.paths import load_paths

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestRenderApplyE2E:
    """Render phobos with real config, then plan drift against empty state."""

    def test_render_phobos_plan_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Render phobos, feed manifest to plan_manifest_drift, validate kinds."""
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "config" / "mapping.yaml").exists():
            pytest.skip("Real config not available")

        monkeypatch.setattr("abhaile.cli.render.validate_dns_serials", lambda *a, **kw: None)
        clear_config_cache()

        paths = load_paths(repo_root)
        validated = load_and_validate(repo_root, paths)

        manifest_path = render_host(
            "phobos",
            output_override=tmp_path,
            paths=paths,
            all_mode=False,
            repo_root=repo_root,
            mapping=validated.mapping,
            network=validated.network,
            host_services=validated.host_services,
        )

        assert manifest_path.exists()

        # Plan drift against empty applied state (all entries become writes)
        applied_path = tmp_path / "state" / "manifest.json"
        plan = plan_manifest_drift(manifest_path, applied_path)

        assert plan["summary"]["added"] > 0
        assert plan["summary"]["writes"] > 0

        manifest = json.loads(manifest_path.read_text())
        entries = manifest["entries"]
        assert len(entries) > 0

        invalid_kinds = {e["kind"] for e in entries} - ALL_KINDS
        assert invalid_kinds == set(), f"Unknown kinds: {invalid_kinds}"

    def test_render_migrated_host_systemd_units_for_phobos_and_deimos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Render migrated host-owned units for phobos and deimos."""
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "config" / "mapping.yaml").exists():
            pytest.skip("Real config not available")

        monkeypatch.setattr("abhaile.cli.render.validate_dns_serials", lambda *a, **kw: None)
        clear_config_cache()

        paths = load_paths(repo_root)
        validated = load_and_validate(repo_root, paths)

        manifests = {}
        for host in ("phobos", "deimos"):
            manifests[host] = render_host(
                host,
                output_override=tmp_path / host,
                paths=paths,
                all_mode=False,
                repo_root=repo_root,
                mapping=validated.mapping,
                network=validated.network,
                host_services=validated.host_services,
            )

        phobos_root = manifests["phobos"].parent
        deimos_root = manifests["deimos"].parent

        phobos_unseal = (
            phobos_root / "system/etc/systemd/system/abhaile-vault-unseal.service"
        ).read_text(encoding="utf-8")
        deimos_unseal = (
            deimos_root / "system/etc/systemd/system/abhaile-vault-unseal.service"
        ).read_text(encoding="utf-8")

        assert "After=vault.service network-online.target" in phobos_unseal
        assert "After=network-online.target" in deimos_unseal
        assert "After=vault.service network-online.target" not in deimos_unseal

        for rendered_root in (phobos_root, deimos_root):
            assert (rendered_root / "system/etc/systemd/system/abhaile-runner.service").exists()
            assert (rendered_root / "system/etc/systemd/system/abhaile-runner.timer").exists()
            assert (
                rendered_root / "system/etc/systemd/system/abhaile-vault-unseal.service"
            ).exists()
            assert (rendered_root / "system/opt/abhaile/tools/bash/vault-unseal.sh").exists()

        phobos_entries = _entries_by_target(json.loads(manifests["phobos"].read_text()))
        deimos_entries = _entries_by_target(json.loads(manifests["deimos"].read_text()))

        for entries in (phobos_entries, deimos_entries):
            assert entries["/etc/systemd/system/abhaile-runner.service"]["kind"] == "systemd.unit"
            assert entries["/etc/systemd/system/abhaile-runner.timer"]["apply_hints"] == {
                "activation_mode": "start",
                "enable_mode": "enable",
            }
            assert entries["/etc/systemd/system/abhaile-vault-unseal.service"]["apply_hints"] == {
                "activation_mode": "start",
                "enable_mode": "enable",
            }
            assert entries["/opt/abhaile/tools/bash/vault-unseal.sh"]["owner_ref"].startswith(
                "host:"
            )


def _entries_by_target(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index manifest entries by target path."""
    return {entry["target_path"]: entry for entry in manifest["entries"]}
