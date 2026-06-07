"""Integration test: render phobos → plan_manifest_drift (dry-run)."""

from __future__ import annotations

from pathlib import Path

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

        # Validate all kinds are in the canonical registry
        import json

        manifest = json.loads(manifest_path.read_text())
        entries = manifest["entries"]
        assert len(entries) > 0

        invalid_kinds = {e["kind"] for e in entries} - ALL_KINDS
        assert invalid_kinds == set(), f"Unknown kinds: {invalid_kinds}"
