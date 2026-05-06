"""Tests for phase 7.2 systemd executor family."""

import pytest

from abhaile.apply.systemd import SystemdExecutor
from abhaile.utils.errors import ApplyError


class TestDaemonReload:
    """Tests for daemon-reload command."""

    def test_daemon_reload_success(self, mocker):
        """Verify daemon-reload returns successful result."""
        mock_run = mocker.patch(
            "abhaile.apply.systemd.run_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                    "error_message": None,
                },
            )(),
        )
        result = SystemdExecutor.daemon_reload()
        assert result.success
        assert result.return_code == 0
        mock_run.assert_called_once_with(
            ["systemctl", "daemon-reload"],
            action_id="systemctl-daemon-reload",
            action_type="systemctl",
        )

    def test_daemon_reload_failure_raises(self, mocker):
        """Verify daemon-reload raises ApplyError on failure."""
        mocker.patch(
            "abhaile.apply.systemd.run_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": False,
                    "return_code": 1,
                    "error_message": "Permission denied",
                },
            )(),
        )
        with pytest.raises(ApplyError, match="Daemon reload failed"):
            SystemdExecutor.daemon_reload()


class TestStartUnit:
    """Tests for start_unit command."""

    def test_start_rootful_unit(self, mocker):
        """Verify start unit for rootful service."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.start_unit("caddy.service", user=False)
        assert result.success
        mock_cmd.assert_called_once_with(
            "start",
            "caddy.service",
            user=False,
            run_as_user=None,
        )

    def test_start_rootless_unit(self, mocker):
        """Verify start unit for rootless user service."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.start_unit(
            "dbus.service",
            user=True,
            run_as_user="podman",
        )
        assert result.success
        mock_cmd.assert_called_once_with(
            "start",
            "dbus.service",
            user=True,
            run_as_user="podman",
        )

    def test_start_unit_failure_raises(self, mocker):
        """Verify start unit raises ApplyError on failure."""
        mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            side_effect=ApplyError("Unit not found"),
        )
        with pytest.raises(ApplyError):
            SystemdExecutor.start_unit("nonexistent.service")


class TestTryRestartUnit:
    """Tests for try-restart unit command."""

    def test_try_restart_unit(self, mocker):
        """Verify try-restart command formatting."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.try_restart_unit("caddy.service")
        assert result.success
        mock_cmd.assert_called_once_with(
            "try-restart",
            "caddy.service",
            user=False,
            run_as_user=None,
        )


class TestReloadUnit:
    """Tests for reload-or-restart command."""

    def test_reload_unit(self, mocker):
        """Verify reload-or-restart command formatting."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.reload_unit("caddy.service")
        assert result.success
        mock_cmd.assert_called_once_with(
            "reload-or-restart",
            "caddy.service",
            user=False,
            run_as_user=None,
        )


class TestStopUnit:
    """Tests for stop unit command."""

    def test_stop_unit(self, mocker):
        """Verify stop command formatting."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.stop_unit("caddy.service")
        assert result.success
        mock_cmd.assert_called_once_with(
            "stop",
            "caddy.service",
            user=False,
            run_as_user=None,
        )


class TestEnableUnit:
    """Tests for enable_unit command."""

    def test_enable_rootful_unit(self, mocker):
        """Verify enable command is issued for rootful unit."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.enable_unit("caddy.service")
        assert result.success
        mock_cmd.assert_called_once_with(
            "enable",
            "caddy.service",
            user=False,
            run_as_user=None,
        )

    def test_enable_rootless_unit(self, mocker):
        """Verify enable command is issued with --user scope for rootless unit."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.enable_unit("dbus.service", user=True, run_as_user="podman")
        assert result.success
        mock_cmd.assert_called_once_with(
            "enable",
            "dbus.service",
            user=True,
            run_as_user="podman",
        )


class TestDisableUnit:
    """Tests for disable_unit command."""

    def test_disable_rootful_unit(self, mocker):
        """Verify disable command is issued for rootful unit."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.disable_unit("caddy.service")
        assert result.success
        mock_cmd.assert_called_once_with(
            "disable",
            "caddy.service",
            user=False,
            run_as_user=None,
        )

    def test_disable_rootless_unit(self, mocker):
        """Verify disable command is issued with --user scope for rootless unit."""
        mock_cmd = mocker.patch(
            "abhaile.apply.systemd.run_systemctl_command",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.disable_unit("dbus.service", user=True, run_as_user="podman")
        assert result.success
        mock_cmd.assert_called_once_with(
            "disable",
            "dbus.service",
            user=True,
            run_as_user="podman",
        )


class TestApplyUnitWrite:
    """Tests for systemd.unit write entry application."""

    def test_unit_write_minimal_hints(self, mocker):
        """Verify unit write with no restart/activation hints."""
        mock_daemon_reload = mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "systemd.unit",
            "owner_ref": "host",
            "apply_hints": {},
        }
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        assert result["unit_name"] == "caddy.service"
        assert result["kind"] == "systemd.unit"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "daemon-reload"
        mock_daemon_reload.assert_called_once()

    def test_unit_write_with_try_restart_hint(self, mocker):
        """Verify unit write applies try-restart when hint set."""
        mock_daemon_reload = mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_try_restart = mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "systemd.unit",
            "apply_hints": {"restart_mode": "try-restart"},
        }
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        assert len(result["actions"]) == 2
        assert result["actions"][0]["action"] == "daemon-reload"
        assert result["actions"][1]["action"] == "try-restart"
        mock_daemon_reload.assert_called_once()
        mock_try_restart.assert_called_once()

    def test_unit_write_with_start_hint(self, mocker):
        """Verify unit write applies start when hint set."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_start = mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "systemd.unit",
            "apply_hints": {"activation_mode": "start"},
        }
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        assert len(result["actions"]) == 2
        assert result["actions"][1]["action"] == "start"
        mock_start.assert_called_once()

    def test_unit_write_with_both_hints(self, mocker):
        """Verify unit write applies both try-restart and start."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "systemd.unit",
            "apply_hints": {
                "restart_mode": "try-restart",
                "activation_mode": "start",
            },
        }
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        assert len(result["actions"]) == 3
        assert result["actions"][0]["action"] == "daemon-reload"
        assert result["actions"][1]["action"] == "try-restart"
        assert result["actions"][2]["action"] == "start"

    def test_unit_write_start_now_hint(self, mocker):
        """Verify start-now hint also triggers start action."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_start = mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "systemd.unit",
            "apply_hints": {"activation_mode": "start-now"},
        }
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        assert result["actions"][1]["action"] == "start"
        mock_start.assert_called_once()

    def test_unit_write_restart_failure_raises(self, mocker):
        """Verify restart failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            side_effect=ApplyError("Restart failed"),
        )
        entry = {
            "apply_hints": {"restart_mode": "try-restart"},
        }
        with pytest.raises(ApplyError, match="Unit restart failed"):
            SystemdExecutor.apply_unit_write("caddy.service", entry)

    def test_unit_write_start_failure_raises(self, mocker):
        """Verify start failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            side_effect=ApplyError("Start failed"),
        )
        entry = {
            "apply_hints": {"activation_mode": "start"},
        }
        with pytest.raises(ApplyError, match="Unit start failed"):
            SystemdExecutor.apply_unit_write("caddy.service", entry)

    def test_unit_write_with_enable_mode(self, mocker):
        """Verify unit write with enable_mode emits enable action after daemon-reload."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_enable = mocker.patch.object(
            SystemdExecutor,
            "enable_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {"apply_hints": {"enable_mode": "enable"}}
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        assert any(a["action"] == "enable" for a in result["actions"])
        mock_enable.assert_called_once_with(
            "caddy.service",
            user=False,
            run_as_user=None,
        )

    def test_unit_write_enable_mode_ordered_before_start(self, mocker):
        """Verify enable action appears before start in the actions list."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "enable_unit",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        entry = {"apply_hints": {"enable_mode": "enable", "activation_mode": "start"}}
        result = SystemdExecutor.apply_unit_write("caddy.service", entry)
        action_names = [a["action"] for a in result["actions"]]
        assert action_names.index("enable") < action_names.index("start")

    def test_unit_write_enable_failure_raises(self, mocker):
        """Verify enable failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "enable_unit",
            side_effect=ApplyError("Permission denied"),
        )
        entry = {"apply_hints": {"enable_mode": "enable"}}
        with pytest.raises(ApplyError, match="Unit enable failed"):
            SystemdExecutor.apply_unit_write("caddy.service", entry)

    def test_unit_write_no_enable_when_mode_absent(self, mocker):
        """Verify enable_unit is not called when enable_mode hint is absent."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mock_enable = mocker.patch.object(SystemdExecutor, "enable_unit")
        entry = {"apply_hints": {"activation_mode": "start"}}
        mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        SystemdExecutor.apply_unit_write("caddy.service", entry)
        mock_enable.assert_not_called()

    def test_unit_write_with_rootless_user(self, mocker):
        """Verify unit write passes user/run_as_user to systemctl commands."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_start = mocker.patch.object(
            SystemdExecutor,
            "start_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "apply_hints": {"activation_mode": "start"},
        }
        SystemdExecutor.apply_unit_write(
            "dbus.service",
            entry,
            user=True,
            run_as_user="podman",
        )
        mock_start.assert_called_once_with(
            "dbus.service",
            user=True,
            run_as_user="podman",
        )


class TestApplyDropinWrite:
    """Tests for systemd.dropin write entry application."""

    def test_dropin_write_basic(self, mocker):
        """Verify dropin write always applies daemon-reload and try-restart."""
        mock_daemon_reload = mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_try_restart = mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "systemd.dropin",
            "owner_ref": "host",
        }
        result = SystemdExecutor.apply_dropin_write("caddy.service", entry)
        assert result["parent_unit_name"] == "caddy.service"
        assert result["kind"] == "systemd.dropin"
        assert len(result["actions"]) == 2
        assert result["actions"][0]["action"] == "daemon-reload"
        assert result["actions"][1]["action"] == "try-restart"
        mock_daemon_reload.assert_called_once()
        mock_try_restart.assert_called_once()

    def test_dropin_write_restarts_parent(self, mocker):
        """Verify dropin write restarts parent unit."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_try_restart = mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {"kind": "systemd.dropin"}
        SystemdExecutor.apply_dropin_write("caddy.service", entry)
        mock_try_restart.assert_called_once_with(
            "caddy.service",
            user=False,
            run_as_user=None,
        )

    def test_dropin_write_restart_failure_raises(self, mocker):
        """Verify restart failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            side_effect=ApplyError("Restart failed"),
        )
        entry = {"kind": "systemd.dropin"}
        with pytest.raises(ApplyError, match="Parent unit restart failed"):
            SystemdExecutor.apply_dropin_write("caddy.service", entry)

    def test_dropin_write_with_rootless_user(self, mocker):
        """Verify dropin write passes user/run_as_user correctly."""
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_try_restart = mocker.patch.object(
            SystemdExecutor,
            "try_restart_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {"kind": "systemd.dropin"}
        SystemdExecutor.apply_dropin_write(
            "dbus.service",
            entry,
            user=True,
            run_as_user="podman",
        )
        mock_try_restart.assert_called_once_with(
            "dbus.service",
            user=True,
            run_as_user="podman",
        )


class TestApplyResolvedConfigWrite:
    """Tests for resolved.config write entry application."""

    def test_resolved_config_write_basic(self, mocker):
        """Verify resolved config write applies reload."""
        mock_reload = mocker.patch.object(
            SystemdExecutor,
            "reload_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        entry = {
            "kind": "resolved.config",
            "owner_ref": "host",
        }
        result = SystemdExecutor.apply_resolved_config_write(entry)
        assert result["service"] == "systemd-resolved.service"
        assert result["kind"] == "resolved.config"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "reload"
        mock_reload.assert_called_once_with("systemd-resolved.service")

    def test_resolved_config_write_reload_failure_raises(self, mocker):
        """Verify reload failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "reload_unit",
            side_effect=ApplyError("Reload failed"),
        )
        entry = {"kind": "resolved.config"}
        with pytest.raises(ApplyError, match="systemd-resolved reload failed"):
            SystemdExecutor.apply_resolved_config_write(entry)


class TestApplyUnitRemove:
    """Tests for systemd.unit removal entry application."""

    def test_unit_remove_basic(self, mocker):
        """Verify unit removal stops unit and reloads daemon."""
        mock_stop = mocker.patch.object(
            SystemdExecutor,
            "stop_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mock_daemon_reload = mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        result = SystemdExecutor.apply_unit_remove("caddy.service")
        assert result["unit_name"] == "caddy.service"
        assert result["kind"] == "systemd.unit"
        assert len(result["actions"]) == 2
        assert result["actions"][0]["action"] == "stop"
        assert result["actions"][1]["action"] == "daemon-reload"
        mock_stop.assert_called_once()
        mock_daemon_reload.assert_called_once()

    def test_unit_remove_with_enable_mode_disables_before_stop(self, mocker):
        """Verify disable is called before stop when enable_mode=enable."""
        mock_disable = mocker.patch.object(
            SystemdExecutor,
            "disable_unit",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "stop_unit",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        entry = {"apply_hints": {"enable_mode": "enable"}}
        result = SystemdExecutor.apply_unit_remove("caddy.service", entry)
        action_names = [a["action"] for a in result["actions"]]
        assert action_names == ["disable", "stop", "daemon-reload"]
        mock_disable.assert_called_once_with("caddy.service", user=False, run_as_user=None)

    def test_unit_remove_no_disable_without_enable_mode(self, mocker):
        """Verify disable is not called when enable_mode hint is absent."""
        mock_disable = mocker.patch.object(SystemdExecutor, "disable_unit")
        mocker.patch.object(
            SystemdExecutor,
            "stop_unit",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )
        SystemdExecutor.apply_unit_remove("caddy.service", {"apply_hints": {}})
        mock_disable.assert_not_called()

    def test_unit_remove_disable_failure_raises(self, mocker):
        """Verify disable failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "disable_unit",
            side_effect=ApplyError("Permission denied"),
        )
        entry = {"apply_hints": {"enable_mode": "enable"}}
        with pytest.raises(ApplyError, match="Unit disable failed"):
            SystemdExecutor.apply_unit_remove("caddy.service", entry)

    def test_unit_remove_stop_failure_raises(self, mocker):
        """Verify stop failure raises ApplyError."""
        mocker.patch.object(
            SystemdExecutor,
            "stop_unit",
            side_effect=ApplyError("Stop failed"),
        )
        with pytest.raises(ApplyError, match="Unit stop failed"):
            SystemdExecutor.apply_unit_remove("caddy.service")

    def test_unit_remove_with_rootless_user(self, mocker):
        """Verify unit removal passes user/run_as_user correctly."""
        mock_stop = mocker.patch.object(
            SystemdExecutor,
            "stop_unit",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        mocker.patch.object(
            SystemdExecutor,
            "daemon_reload",
            return_value=type(
                "Result",
                (),
                {
                    "success": True,
                    "return_code": 0,
                },
            )(),
        )
        SystemdExecutor.apply_unit_remove(
            "dbus.service",
            user=True,
            run_as_user="podman",
        )
        mock_stop.assert_called_once_with(
            "dbus.service",
            user=True,
            run_as_user="podman",
        )
