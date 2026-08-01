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

    def test_transaction_zone_only_reloads_once(self, mocker: Any, tmp_path: Path) -> None:
        """Multiple zone writes should validate all zones and reload CoreDNS once."""
        calls: list[str] = []

        def result(name: str) -> ExecutionResult:
            calls.append(name)
            return ExecutionResult(
                action_id=name,
                action_type="test",
                success=True,
                return_code=0,
                stdout="active" if name.startswith("wait") else "",
            )

        mock_validate = mocker.patch.object(
            CorednsExecutor,
            "validate_zone_file",
            side_effect=lambda *_args, **_kwargs: result("validate"),
        )
        mocker.patch.object(
            CorednsExecutor, "stop_zone_watcher", side_effect=lambda: result("stop")
        )
        mocker.patch.object(
            CorednsExecutor, "wait_coredns_active", side_effect=lambda: result("wait")
        )
        mocker.patch.object(
            CorednsExecutor, "reload_coredns_service", side_effect=lambda: result("reload")
        )
        mocker.patch.object(
            CorednsExecutor, "start_zone_watcher", side_effect=lambda: result("start")
        )

        zone_a = tmp_path / "abhaile.home.arpa.zone"
        zone_b = tmp_path / "svc.abhaile.home.arpa.zone"
        zone_a.write_text("$ORIGIN abhaile.home.arpa.\n", encoding="utf-8")
        zone_b.write_text("$ORIGIN svc.abhaile.home.arpa.\n", encoding="utf-8")

        summary = CorednsExecutor.apply_transaction(
            config_changed=False,
            zone_writes=[
                {"target_path": zone_a.as_posix()},
                {"target_path": zone_b.as_posix()},
            ],
            zone_removals=[],
        )

        assert summary["kind"] == "coredns.transaction"
        assert summary["zones"] == ["abhaile.home.arpa", "svc.abhaile.home.arpa"]
        assert calls == ["validate", "validate", "stop", "wait", "reload", "wait", "start"]
        assert mock_validate.call_count == 2

    def test_transaction_config_change_restarts_without_reload(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Corefile changes should restart once and skip zone reload in the same transaction."""
        calls: list[str] = []

        def result(name: str) -> ExecutionResult:
            calls.append(name)
            return ExecutionResult(
                action_id=name,
                action_type="test",
                success=True,
                return_code=0,
                stdout="active" if name.startswith("wait") else "",
            )

        mocker.patch.object(
            CorednsExecutor,
            "validate_zone_file",
            side_effect=lambda *_args, **_kwargs: result("validate"),
        )
        mocker.patch.object(
            CorednsExecutor, "stop_zone_watcher", side_effect=lambda: result("stop")
        )
        mocker.patch.object(
            CorednsExecutor, "restart_coredns_service", side_effect=lambda: result("restart")
        )
        mock_reload = mocker.patch.object(
            CorednsExecutor, "reload_coredns_service", side_effect=lambda: result("reload")
        )
        mocker.patch.object(
            CorednsExecutor, "wait_coredns_active", side_effect=lambda: result("wait")
        )
        mocker.patch.object(
            CorednsExecutor, "start_zone_watcher", side_effect=lambda: result("start")
        )

        zone = tmp_path / "abhaile.home.arpa.zone"
        zone.write_text("$ORIGIN abhaile.home.arpa.\n", encoding="utf-8")

        summary = CorednsExecutor.apply_transaction(
            config_changed=True,
            zone_writes=[{"target_path": zone.as_posix()}],
            zone_removals=[],
        )

        assert summary["config_changed"] is True
        assert calls == ["validate", "stop", "restart", "wait", "start"]
        mock_reload.assert_not_called()

    def test_transaction_noop_runs_no_systemd_actions(self, mocker: Any) -> None:
        """No effective CoreDNS changes should not touch systemd."""
        mock_stop = mocker.patch.object(CorednsExecutor, "stop_zone_watcher")

        summary = CorednsExecutor.apply_transaction(
            config_changed=False,
            zone_writes=[],
            zone_removals=[],
        )

        assert summary == {"kind": "coredns.transaction", "zones": [], "actions": []}
        mock_stop.assert_not_called()

    def test_transaction_restarts_watcher_when_reload_fails(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """The zone watcher should be restored even when the serialized reload fails."""
        calls: list[str] = []

        def result(name: str) -> ExecutionResult:
            calls.append(name)
            return ExecutionResult(
                action_id=name,
                action_type="test",
                success=True,
                return_code=0,
                stdout="active" if name.startswith("wait") else "",
            )

        mocker.patch.object(
            CorednsExecutor,
            "validate_zone_file",
            side_effect=lambda *_args, **_kwargs: result("validate"),
        )
        mocker.patch.object(
            CorednsExecutor, "stop_zone_watcher", side_effect=lambda: result("stop")
        )
        mocker.patch.object(
            CorednsExecutor, "wait_coredns_active", side_effect=lambda: result("wait")
        )
        mocker.patch.object(
            CorednsExecutor,
            "reload_coredns_service",
            side_effect=ApplyError("reload failed"),
        )
        mocker.patch.object(
            CorednsExecutor, "start_zone_watcher", side_effect=lambda: result("start")
        )

        zone = tmp_path / "abhaile.home.arpa.zone"
        zone.write_text("$ORIGIN abhaile.home.arpa.\n", encoding="utf-8")

        with pytest.raises(ApplyError, match="reload failed"):
            CorednsExecutor.apply_transaction(
                config_changed=False,
                zone_writes=[{"target_path": zone.as_posix()}],
                zone_removals=[],
            )

        assert calls == ["validate", "stop", "wait", "start"]
