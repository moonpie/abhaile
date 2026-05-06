"""Unit tests for phase 7.4 CoreDNS executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.coredns import CorednsExecutor
from abhaile.utils.errors import ApplyError


class TestCorednsExecutor:
    """Tests for CoreDNS apply executor."""

    def test_zone_name_from_target(self) -> None:
        """Zone names should be derived from .zone filenames."""
        assert (
            CorednsExecutor.zone_name_from_target("/etc/coredns/zones/abhaile.home.arpa.zone")
            == "abhaile.home.arpa"
        )

    def test_validate_zone_missing_checker_non_strict(self, mocker: Any, tmp_path: Path) -> None:
        """Dry-run validation should warn when named-checkzone is unavailable."""
        zone_file = tmp_path / "abhaile.home.arpa.zone"
        zone_file.write_text("$ORIGIN abhaile.home.arpa.\n")
        mocker.patch("abhaile.apply.coredns.shutil.which", return_value=None)

        result = CorednsExecutor.validate_zone_file("abhaile.home.arpa", zone_file, strict=False)
        assert result.success
        assert result.return_code is None
        assert "missing" in result.error_message

    def test_validate_zone_missing_checker_strict_raises(self, mocker: Any, tmp_path: Path) -> None:
        """Apply should fail-fast when checker is missing."""
        zone_file = tmp_path / "abhaile.home.arpa.zone"
        zone_file.write_text("$ORIGIN abhaile.home.arpa.\n")
        mocker.patch("abhaile.apply.coredns.shutil.which", return_value=None)

        with pytest.raises(ApplyError, match="named-checkzone is required"):
            CorednsExecutor.validate_zone_file("abhaile.home.arpa", zone_file, strict=True)

    def test_apply_zone_write_runs_validation_then_reload(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """coredns.zone write should validate then start coredns-zones.service."""
        mock_validate = mocker.patch.object(
            CorednsExecutor,
            "validate_zone_file",
            return_value=ExecutionResult(
                action_id="validate-zone:abhaile.home.arpa",
                action_type="validation",
                success=True,
                return_code=0,
            ),
        )
        mock_reload = mocker.patch.object(
            CorednsExecutor,
            "start_zone_reload_service",
            return_value=ExecutionResult(
                action_id="systemctl-start-coredns-zones",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        target = tmp_path / "abhaile.home.arpa.zone"
        target.write_text("$ORIGIN abhaile.home.arpa.\n")
        summary = CorednsExecutor.apply_zone_write({"kind": "coredns.zone"}, target.as_posix())

        assert summary["kind"] == "coredns.zone"
        assert summary["zone"] == "abhaile.home.arpa"
        assert summary["actions"][0]["action"] == "validate-zone"
        assert summary["actions"][1]["action"] == "start"
        mock_validate.assert_called_once()
        mock_reload.assert_called_once()

    def test_apply_config_write_restarts_coredns(self, mocker: Any) -> None:
        """coredns.config write should restart coredns.service."""
        mock_restart = mocker.patch.object(
            CorednsExecutor,
            "restart_coredns_service",
            return_value=ExecutionResult(
                action_id="systemctl-try-restart-coredns",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = CorednsExecutor.apply_config_write({"kind": "coredns.config"})
        assert summary["kind"] == "coredns.config"
        assert summary["actions"][0]["action"] == "try-restart"
        mock_restart.assert_called_once()

    def test_apply_zone_remove_reloads_zones(self, mocker: Any) -> None:
        """coredns.zone removal should trigger zone reload service."""
        mock_reload = mocker.patch.object(
            CorednsExecutor,
            "start_zone_reload_service",
            return_value=ExecutionResult(
                action_id="systemctl-start-coredns-zones",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = CorednsExecutor.apply_zone_remove(
            {"kind": "coredns.zone"},
            "/etc/coredns/zones/svc.abhaile.home.arpa.zone",
        )
        assert summary["zone"] == "svc.abhaile.home.arpa"
        assert summary["actions"][0]["action"] == "start"
        mock_reload.assert_called_once()
