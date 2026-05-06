"""Unit tests for phase 7.5 Caddy executor."""

from __future__ import annotations

from typing import Any

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.caddy import CaddyExecutor  # pyright: ignore[reportMissingImports]
from abhaile.utils.errors import ApplyError


class TestCaddyExecutor:
    """Tests for Caddy apply executor."""

    def test_segment_from_owner_ref(self) -> None:
        """Segment should be parsed from owner_ref when present."""
        assert (
            CaddyExecutor.segment_from_owner_or_target("caddy:dmz", "/srv/caddy/dmz/Caddyfile")
            == "dmz"
        )

    def test_segment_from_target_path(self) -> None:
        """Segment should fall back to target path when owner_ref is generic."""
        assert (
            CaddyExecutor.segment_from_owner_or_target(
                "service:caddy",
                "/srv/caddy/internal/Caddyfile",
            )
            == "internal"
        )

    def test_validate_missing_podman_non_strict(self, mocker: Any) -> None:
        """Dry-run validation should warn when podman is unavailable."""
        mocker.patch("abhaile.apply.caddy.shutil.which", return_value=None)

        result = CaddyExecutor.validate_caddy_config("dmz", strict=False)
        assert result.success
        assert result.return_code is None
        assert "missing" in result.error_message

    def test_validate_missing_podman_strict_raises(self, mocker: Any) -> None:
        """Apply should fail-fast when podman is unavailable."""
        mocker.patch("abhaile.apply.caddy.shutil.which", return_value=None)

        with pytest.raises(ApplyError, match="podman is required"):
            CaddyExecutor.validate_caddy_config("dmz", strict=True)

    def test_apply_config_write_reloads_when_validation_passes(self, mocker: Any) -> None:
        """caddy.config write should validate then reload."""
        mock_validate = mocker.patch.object(
            CaddyExecutor,
            "validate_caddy_config",
            return_value=ExecutionResult(
                action_id="validate-caddy:dmz",
                action_type="validation",
                success=True,
                return_code=0,
            ),
        )
        mock_reload = mocker.patch.object(
            CaddyExecutor,
            "reload_caddy_config",
            return_value=ExecutionResult(
                action_id="reload-caddy:dmz",
                action_type="reload",
                success=True,
                return_code=0,
            ),
        )

        summary = CaddyExecutor.apply_config_write(
            {
                "kind": "caddy.config",
                "owner_ref": "caddy:dmz",
            },
            "/srv/caddy/dmz/Caddyfile",
        )

        assert summary["kind"] == "caddy.config"
        assert summary["segment"] == "dmz"
        assert summary["actions"][0]["action"] == "validate-caddy"
        assert summary["actions"][1]["action"] == "reload-caddy"
        mock_validate.assert_called_once_with("dmz", strict=True)
        mock_reload.assert_called_once_with("dmz", check=False)

    def test_apply_config_write_reload_failure_with_restart_fallback(self, mocker: Any) -> None:
        """When configured, reload failure should fall back to systemd try-restart."""
        mocker.patch.object(
            CaddyExecutor,
            "validate_caddy_config",
            return_value=ExecutionResult(
                action_id="validate-caddy:internal",
                action_type="validation",
                success=True,
                return_code=0,
            ),
        )
        mocker.patch.object(
            CaddyExecutor,
            "reload_caddy_config",
            return_value=ExecutionResult(
                action_id="reload-caddy:internal",
                action_type="reload",
                success=False,
                return_code=1,
                error_message="reload failed",
            ),
        )
        mock_restart = mocker.patch.object(
            CaddyExecutor,
            "restart_caddy_service",
            return_value=ExecutionResult(
                action_id="systemctl-try-restart-caddy-internal",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = CaddyExecutor.apply_config_write(
            {
                "kind": "caddy.config",
                "owner_ref": "caddy:internal",
                "apply_hints": {"restart_on_failure": True},
            },
            "/srv/caddy/internal/Caddyfile",
        )

        assert summary["actions"][2]["action"] == "try-restart"
        mock_restart.assert_called_once_with("internal")

    def test_apply_config_write_reload_failure_without_fallback_raises(self, mocker: Any) -> None:
        """Without restart_on_failure hint, reload failure should fail apply."""
        mocker.patch.object(
            CaddyExecutor,
            "validate_caddy_config",
            return_value=ExecutionResult(
                action_id="validate-caddy:dmz",
                action_type="validation",
                success=True,
                return_code=0,
            ),
        )
        mocker.patch.object(
            CaddyExecutor,
            "reload_caddy_config",
            return_value=ExecutionResult(
                action_id="reload-caddy:dmz",
                action_type="reload",
                success=False,
                return_code=1,
                error_message="reload failed",
            ),
        )

        with pytest.raises(ApplyError, match="Caddy reload failed"):
            CaddyExecutor.apply_config_write(
                {
                    "kind": "caddy.config",
                    "owner_ref": "caddy:dmz",
                },
                "/srv/caddy/dmz/Caddyfile",
            )
