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

    def test_restart_reload_and_watcher_wrappers_delegate_to_systemctl(self, mocker: Any) -> None:
        calls: list[tuple[str, str]] = []

        def _fake_systemctl(action: str, unit: str) -> ExecutionResult:
            calls.append((action, unit))
            return ExecutionResult(
                action_id=f"{action}:{unit}",
                action_type="systemctl",
                success=True,
                return_code=0,
            )

        mocker.patch("abhaile.apply.coredns.run_systemctl_command", side_effect=_fake_systemctl)

        CorednsExecutor.restart_coredns_service()
        CorednsExecutor.reload_coredns_service()
        CorednsExecutor.stop_zone_watcher()
        CorednsExecutor.start_zone_watcher()

        assert calls == [
            ("restart", "coredns.service"),
            ("reload", "coredns.service"),
            ("stop", "coredns-zones.path"),
            ("start", "coredns-zones.path"),
        ]

    def test_daemon_reload_and_start_unit_delegate_to_command_layers(self, mocker: Any) -> None:
        command_calls: list[list[str]] = []
        unit_calls: list[tuple[str, str]] = []

        def _fake_command(argv: list[str], **_kwargs: object) -> ExecutionResult:
            command_calls.append(argv)
            return ExecutionResult(
                action_id="ok",
                action_type="systemctl",
                success=True,
                return_code=0,
            )

        def _fake_systemctl(action: str, unit: str) -> ExecutionResult:
            unit_calls.append((action, unit))
            return ExecutionResult(
                action_id="ok",
                action_type="systemctl",
                success=True,
                return_code=0,
            )

        mocker.patch("abhaile.apply.coredns.run_command", side_effect=_fake_command)
        mocker.patch("abhaile.apply.coredns.run_systemctl_command", side_effect=_fake_systemctl)

        CorednsExecutor.daemon_reload()
        CorednsExecutor.start_unit("demo.service")

        assert command_calls == [["systemctl", "daemon-reload"]]
        assert unit_calls == [("start", "demo.service")]

    def test_verify_unit_loaded_raises_when_not_loaded(self, mocker: Any) -> None:
        mocker.patch(
            "abhaile.apply.coredns.run_command",
            return_value=ExecutionResult(
                action_id="show",
                action_type="systemctl",
                success=True,
                return_code=0,
                stdout="not-found\n",
            ),
        )

        with pytest.raises(ApplyError, match="Expected generated unit"):
            CorednsExecutor.verify_unit_loaded("coredns-omada-build.service")

    def test_wait_coredns_active_raises_on_timeout(self, mocker: Any) -> None:
        mocker.patch(
            "abhaile.apply.coredns.run_command",
            return_value=ExecutionResult(
                action_id="is-active",
                action_type="systemctl",
                success=False,
                return_code=3,
                stdout="inactive\n",
            ),
        )
        timeline = iter([0.0, 1.0, 2.0])
        mocker.patch("abhaile.apply.coredns.time.monotonic", side_effect=lambda: next(timeline))
        mocker.patch("abhaile.apply.coredns.time.sleep", side_effect=lambda _s: None)

        with pytest.raises(ApplyError, match="did not become active"):
            CorednsExecutor.wait_coredns_active(timeout_seconds=0.5)

    def test_verify_coredns_binary_checks_executable(self, tmp_path: Path) -> None:
        binary = tmp_path / "coredns"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o644)

        with pytest.raises(ApplyError, match="not executable"):
            CorednsExecutor.verify_coredns_binary(binary)

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

    def test_transaction_build_inputs_change_runs_build_install_then_restart(
        self, mocker: Any
    ) -> None:
        """Build input changes should run ordered build/install before CoreDNS restart."""
        calls: list[str] = []

        def result(name: str) -> ExecutionResult:
            calls.append(name)
            return ExecutionResult(
                action_id=name,
                action_type="test",
                success=True,
                return_code=0,
                stdout="active" if name.startswith("wait") else "loaded",
            )

        mocker.patch.object(
            CorednsExecutor, "stop_zone_watcher", side_effect=lambda: result("stop")
        )
        mocker.patch.object(CorednsExecutor, "daemon_reload", side_effect=lambda: result("reload"))
        mocker.patch.object(
            CorednsExecutor,
            "verify_unit_loaded",
            side_effect=lambda _unit: result("verify-generated"),
        )
        mocker.patch.object(
            CorednsExecutor,
            "start_unit",
            side_effect=lambda unit: result(f"start:{unit}"),
        )
        mocker.patch.object(CorednsExecutor, "verify_coredns_binary", side_effect=lambda _p: None)
        mocker.patch.object(
            CorednsExecutor, "restart_coredns_service", side_effect=lambda: result("restart")
        )
        mocker.patch.object(
            CorednsExecutor, "wait_coredns_active", side_effect=lambda: result("wait")
        )
        mocker.patch.object(
            CorednsExecutor, "start_zone_watcher", side_effect=lambda: result("start-watcher")
        )

        summary = CorednsExecutor.apply_transaction(
            config_changed=False,
            zone_writes=[],
            zone_removals=[],
            build_inputs_changed=True,
        )

        assert summary["kind"] == "coredns.transaction"
        assert calls == [
            "stop",
            "reload",
            "verify-generated",
            "start:coredns-omada-build.service",
            "start:coredns-omada-install.service",
            "restart",
            "wait",
            "start-watcher",
        ]

    def test_transaction_build_failure_prevents_restart(self, mocker: Any) -> None:
        """Build failure should stop transaction before install/restart."""
        calls: list[str] = []

        def result(name: str) -> ExecutionResult:
            calls.append(name)
            return ExecutionResult(
                action_id=name,
                action_type="test",
                success=True,
                return_code=0,
                stdout="loaded",
            )

        mocker.patch.object(
            CorednsExecutor, "stop_zone_watcher", side_effect=lambda: result("stop")
        )
        mocker.patch.object(CorednsExecutor, "daemon_reload", side_effect=lambda: result("reload"))
        mocker.patch.object(
            CorednsExecutor,
            "verify_unit_loaded",
            side_effect=lambda _unit: result("verify-generated"),
        )

        def _fail_start(unit: str) -> ExecutionResult:
            if unit == "coredns-omada-build.service":
                raise ApplyError("build failed")
            return result(f"start:{unit}")

        mocker.patch.object(CorednsExecutor, "start_unit", side_effect=_fail_start)
        mock_restart = mocker.patch.object(CorednsExecutor, "restart_coredns_service")
        mocker.patch.object(
            CorednsExecutor, "start_zone_watcher", side_effect=lambda: result("start-watcher")
        )

        with pytest.raises(ApplyError, match="build failed"):
            CorednsExecutor.apply_transaction(
                config_changed=False,
                zone_writes=[],
                zone_removals=[],
                build_inputs_changed=True,
            )

        assert calls == ["stop", "reload", "verify-generated", "start-watcher"]
        mock_restart.assert_not_called()

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
