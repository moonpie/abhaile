"""Unit tests for phase 7.8 quadlet executor."""

from __future__ import annotations

from typing import Any

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.quadlet import QuadletExecutor  # pyright: ignore[reportMissingImports]
from abhaile.utils.errors import ApplyError


class TestQuadletExecutor:
    """Tests for quadlet apply executor."""

    def test_unit_from_owner(self) -> None:
        """Owner refs should map to generated unit names."""
        assert QuadletExecutor.unit_from_owner("unit:blocky.service") == "blocky.service"

    def test_unit_from_owner_invalid_raises(self) -> None:
        """Non-unit owner refs should fail closed."""
        with pytest.raises(ApplyError, match="Invalid quadlet owner_ref"):
            QuadletExecutor.unit_from_owner("service:blocky")

    def test_user_context_from_entries_rootless(self) -> None:
        """Rootless context should be inferred from apply hints."""
        rootless, run_as_user = QuadletExecutor.user_context_from_entries(
            [
                {
                    "kind": "quadlet.container",
                    "apply_hints": {"rootless": True, "podman_user": "abhaile"},
                }
            ]
        )
        assert rootless is True
        assert run_as_user == "abhaile"

    def test_apply_owner_change_start_for_network_kind(self, mocker: Any) -> None:
        """Shared/create-like quadlet kinds should run start after daemon-reload."""
        mock_remove = mocker.patch.object(
            QuadletExecutor,
            "remove_podman_object",
            return_value=ExecutionResult(
                action_id="podman-network-rm:systemd-services",
                action_type="podman",
                success=True,
                return_code=0,
            ),
        )
        mock_reload = mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-start",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = QuadletExecutor.apply_owner_change(
            "unit:services-network.service",
            kinds=["quadlet.network"],
            changed_phases={"write"},
            rootless=False,
            run_as_user=None,
        )

        assert summary["unit"] == "services-network.service"
        assert summary["actions"][0]["action"] == "remove-object"
        assert summary["actions"][1]["action"] == "daemon-reload"
        assert summary["actions"][2]["action"] == "start"
        mock_remove.assert_called_once()
        mock_reload.assert_called_once_with(rootless=False, run_as_user=None)
        mock_systemctl.assert_called_once_with(
            "start",
            "services-network.service",
            user=False,
            run_as_user=None,
        )

    def test_apply_owner_change_try_restart_for_container_kind(self, mocker: Any) -> None:
        """Container/pod quadlet kinds should run try-restart after daemon-reload."""
        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-try-restart",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = QuadletExecutor.apply_owner_change(
            "unit:blocky.service",
            kinds=["quadlet.container"],
            changed_phases={"write"},
            rootless=False,
            run_as_user=None,
        )

        assert summary["actions"][1]["action"] == "try-restart"
        mock_systemctl.assert_called_once_with(
            "try-restart",
            "blocky.service",
            user=False,
            run_as_user=None,
        )

    def test_apply_owner_change_manual_restart_skips_systemctl_restart(self, mocker: Any) -> None:
        """Manual restart mode should reload unit files without restarting a pod member."""
        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_systemctl = mocker.patch("abhaile.apply.quadlet.run_systemctl_command")

        summary = QuadletExecutor.apply_owner_change(
            "unit:omada-controller-app-mongodb.service",
            kinds=["quadlet.container"],
            changed_phases={"write"},
            rootless=False,
            run_as_user=None,
            restart_mode="manual",
        )

        assert summary["restart_mode"] == "manual"
        assert summary["actions"][1] == {
            "action": "skip-restart",
            "unit": "omada-controller-app-mongodb.service",
            "reason": "manual-restart",
            "success": True,
            "return_code": 0,
        }
        mock_systemctl.assert_not_called()

    def test_apply_owner_change_stop_for_remove_only(self, mocker: Any) -> None:
        """Removal-only owner changes should stop the generated unit."""
        mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-stop",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = QuadletExecutor.apply_owner_change(
            "unit:blocky.service",
            kinds=["quadlet.container"],
            changed_phases={"remove"},
            rootless=True,
            run_as_user="abhaile",
        )

        assert summary["rootless"] is True
        assert summary["run_as_user"] == "abhaile"
        assert summary["actions"][1]["action"] == "stop"
        mock_systemctl.assert_called_once_with(
            "stop",
            "blocky.service",
            user=True,
            run_as_user="abhaile",
        )

    def test_apply_convergence_action_runs_systemctl(self, mocker: Any) -> None:
        """Planner-emitted convergence actions should dispatch to systemctl."""
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-stop",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        payload = QuadletExecutor.apply_convergence_action(
            "unit:blocky.service",
            action="stop",
            rootless=False,
            run_as_user=None,
        )

        assert payload["owner_ref"] == "unit:blocky.service"
        assert payload["unit"] == "blocky.service"
        assert payload["action"] == "stop"
        mock_systemctl.assert_called_once_with(
            "stop",
            "blocky.service",
            user=False,
            run_as_user=None,
        )

    def test_validate_systemctl_rootless_uses_machine_user_manager(self, mocker: Any) -> None:
        """Rootless systemctl validation should target the user's manager."""
        mock_run = mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="validate-systemctl-user",
                action_type="validation",
                success=True,
                return_code=0,
            ),
        )

        QuadletExecutor.validate_systemctl(rootless=True, run_as_user="abhaile", strict=True)

        mock_run.assert_called_once_with(
            ["systemctl", "--user", "-M", "abhaile@", "--version"],
            action_id="validate-systemctl-user",
            action_type="validation",
            run_as_user=None,
            check=True,
        )

    def test_daemon_reload_rootless_uses_machine_user_manager(self, mocker: Any) -> None:
        """Rootless daemon-reload should target the user's manager."""
        mock_run = mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload-user",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        QuadletExecutor.daemon_reload(rootless=True, run_as_user="abhaile")

        mock_run.assert_called_once_with(
            ["systemctl", "--user", "-M", "abhaile@", "daemon-reload"],
            action_id="systemctl-daemon-reload-user",
            action_type="systemctl",
            run_as_user=None,
            check=True,
        )

    def test_apply_owner_change_recreates_network_object_on_write(self, mocker: Any) -> None:
        """Changed quadlet networks should remove old object before reload/start."""
        mock_remove = mocker.patch.object(
            QuadletExecutor,
            "remove_podman_object",
            return_value=ExecutionResult(
                action_id="podman-network-rm:systemd-services",
                action_type="podman",
                success=True,
                return_code=0,
            ),
        )
        mock_reload = mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-start",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )

        summary = QuadletExecutor.apply_owner_change(
            "unit:services-network.service",
            kinds=["quadlet.network"],
            changed_phases={"write"},
            rootless=False,
            run_as_user=None,
        )

        assert [action["action"] for action in summary["actions"]] == [
            "remove-object",
            "daemon-reload",
            "start",
        ]
        mock_remove.assert_called_once()
        mock_reload.assert_called_once_with(rootless=False, run_as_user=None)
        mock_systemctl.assert_called_once_with(
            "start",
            "services-network.service",
            user=False,
            run_as_user=None,
        )

    def test_apply_owner_change_removes_volume_object_on_delete(self, mocker: Any) -> None:
        """Remove-only quadlet volumes should stop unit and remove backing Podman object."""
        mock_reload = mocker.patch.object(
            QuadletExecutor,
            "daemon_reload",
            return_value=ExecutionResult(
                action_id="systemctl-daemon-reload",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-stop",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_remove = mocker.patch.object(
            QuadletExecutor,
            "remove_podman_object",
            return_value=ExecutionResult(
                action_id="podman-volume-rm:systemd-config",
                action_type="podman",
                success=True,
                return_code=0,
            ),
        )

        summary = QuadletExecutor.apply_owner_change(
            "unit:config-volume.service",
            kinds=["quadlet.volume"],
            changed_phases={"remove"},
            rootless=False,
            run_as_user=None,
        )

        assert [action["action"] for action in summary["actions"]] == [
            "daemon-reload",
            "stop",
            "remove-object",
        ]
        mock_reload.assert_called_once_with(rootless=False, run_as_user=None)
        mock_systemctl.assert_called_once_with(
            "stop",
            "config-volume.service",
            user=False,
            run_as_user=None,
        )
        mock_remove.assert_called_once()
