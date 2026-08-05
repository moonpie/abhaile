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

    def test_apply_owner_change_restarts_active_container_kind(self, mocker: Any) -> None:
        """Active container/pod quadlet kinds should run restart after daemon-reload."""
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
        mock_active = mocker.patch.object(QuadletExecutor, "unit_is_active", return_value=True)
        mock_systemctl = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl-restart",
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

        assert summary["actions"][1]["action"] == "restart"
        assert summary["actions"][1]["was_active"] is True
        mock_active.assert_called_once_with(
            "blocky.service",
            rootless=False,
            run_as_user=None,
        )
        mock_systemctl.assert_called_once_with(
            "restart",
            "blocky.service",
            user=False,
            run_as_user=None,
        )

    def test_apply_owner_change_starts_inactive_container_kind(self, mocker: Any) -> None:
        """Inactive desired container/pod quadlet kinds should be started after reload."""
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
        mock_active = mocker.patch.object(QuadletExecutor, "unit_is_active", return_value=False)
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
            "unit:blocky.service",
            kinds=["quadlet.container"],
            changed_phases={"write"},
            rootless=False,
            run_as_user=None,
        )

        assert summary["actions"][1]["action"] == "start"
        assert summary["actions"][1]["was_active"] is False
        mock_active.assert_called_once_with(
            "blocky.service",
            run_as_user=None,
            rootless=False,
        )
        mock_systemctl.assert_called_once_with(
            "start",
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

    def test_apply_owner_change_image_remove_resets_after_reload(self, mocker: Any) -> None:
        """Removed image quadlets should clear stale generated image unit state narrowly."""
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
        mock_stop = mocker.patch.object(
            QuadletExecutor,
            "stop_obsolete_image_unit",
            return_value=ExecutionResult(
                action_id="systemctl stop blocky-image.service",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_reset = mocker.patch.object(
            QuadletExecutor,
            "reset_failed_unit",
            return_value=ExecutionResult(
                action_id="systemctl reset-failed blocky-image.service",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_unloaded = mocker.patch.object(
            QuadletExecutor,
            "verify_unit_unloaded",
            return_value=ExecutionResult(
                action_id="verify-obsolete-unit-unloaded:blocky-image.service",
                action_type="validation",
                success=True,
                return_code=0,
            ),
        )

        summary = QuadletExecutor.apply_owner_change(
            "unit:blocky-image.service",
            kinds=["quadlet.image"],
            changed_phases={"remove"},
            rootless=False,
            run_as_user=None,
        )

        assert [action["action"] for action in summary["actions"]] == [
            "stop",
            "daemon-reload",
            "reset-failed",
            "verify-unloaded",
        ]
        assert summary["actions"][0]["idempotent_noop"] is False
        mock_stop.assert_called_once_with(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )
        mock_reload.assert_called_once_with(rootless=False, run_as_user=None)
        mock_reset.assert_called_once_with(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )
        mock_unloaded.assert_called_once_with(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )

    def test_stop_obsolete_image_unit_accepts_not_loaded_result(self, mocker: Any) -> None:
        """Obsolete image unit stop should be idempotent when systemd already unloaded it."""
        mock_run = mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="systemctl stop blocky-image.service",
                action_type="systemctl",
                success=False,
                return_code=5,
                stderr="Unit blocky-image.service not loaded.",
                error_message="Unit blocky-image.service not loaded.",
            ),
        )

        result = QuadletExecutor.stop_obsolete_image_unit(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )

        assert result.success is True
        assert result.return_code == 5
        mock_run.assert_called_once_with(
            ["systemctl", "stop", "blocky-image.service"],
            action_id="systemctl stop blocky-image.service",
            action_type="systemctl",
            run_as_user=None,
            check=False,
        )

    def test_stop_obsolete_image_unit_raises_for_real_stop_failure(self, mocker: Any) -> None:
        """Unexpected stop failures should still block obsolete image unit migration."""
        mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="systemctl stop blocky-image.service",
                action_type="systemctl",
                success=False,
                return_code=1,
                stderr="permission denied",
                error_message="permission denied",
            ),
        )

        with pytest.raises(ApplyError, match="permission denied"):
            QuadletExecutor.stop_obsolete_image_unit(
                "blocky-image.service",
                rootless=False,
                run_as_user=None,
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

    def test_pre_pull_image_pulls_and_verifies_in_rootless_context(self, mocker: Any) -> None:
        """Image pre-pull should use the service user's Podman storage."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        results = [
            ExecutionResult(
                action_id="podman-pull",
                action_type="podman",
                success=True,
                return_code=0,
            ),
            ExecutionResult(
                action_id="podman-image-exists",
                action_type="podman",
                success=True,
                return_code=0,
            ),
            ExecutionResult(
                action_id="podman-image-inspect",
                action_type="podman",
                success=True,
                return_code=0,
                stdout="sha256:abc repo@example\n",
            ),
        ]
        mock_run = mocker.patch("abhaile.apply.quadlet.run_command", side_effect=results)

        result = QuadletExecutor.pre_pull_image(
            "docker.io/hashicorp/vault:1.21.4",
            rootless=True,
            run_as_user="abhaile",
        )

        assert result["scope"] == "rootless"
        assert result["run_as_user"] == "abhaile"
        assert result["image_id"] == "sha256:abc"
        assert result["digest"] == "repo@example"
        assert mock_run.call_args_list[0].args[0] == [
            "/usr/bin/podman",
            "pull",
            "docker.io/hashicorp/vault:1.21.4",
        ]
        assert [call.kwargs["run_as_user"] for call in mock_run.call_args_list] == [
            "abhaile",
            "abhaile",
            "abhaile",
        ]

    def test_pre_pull_image_failure_reports_non_destructive_context(self, mocker: Any) -> None:
        """Pull command failure should raise before image verification."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        mock_run = mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="podman-pull",
                action_type="podman",
                success=False,
                return_code=125,
                stderr="lookup registry failed",
            ),
        )

        with pytest.raises(ApplyError, match="image pre-pull failed"):
            QuadletExecutor.pre_pull_image(
                "ghcr.io/0xerr0r/blocky:v0.28.0",
                rootless=False,
                run_as_user=None,
            )

        mock_run.assert_called_once()

    def test_image_exists_false_when_podman_reports_absent(self, mocker: Any) -> None:
        """Image existence should be checked in the requested Podman storage."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        mock_run = mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="podman-image-exists",
                action_type="podman",
                success=False,
                return_code=1,
                stderr="image not known",
            ),
        )

        exists = QuadletExecutor.image_exists(
            "ghcr.io/0xerr0r/blocky:v0.28.0",
            rootless=False,
            run_as_user=None,
        )

        assert exists is False
        mock_run.assert_called_once_with(
            ["/usr/bin/podman", "image", "exists", "ghcr.io/0xerr0r/blocky:v0.28.0"],
            action_id="podman-image-exists:ghcr.io/0xerr0r/blocky:v0.28.0",
            action_type="podman",
            run_as_user=None,
            check=False,
        )

    def test_inspect_image_omits_nil_digest(self, mocker: Any) -> None:
        """Podman inspect payload should not expose a fake digest for local-only images."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="podman-image-inspect",
                action_type="podman",
                success=True,
                return_code=0,
                stdout="sha256:abc <nil>\n",
            ),
        )

        payload = QuadletExecutor.inspect_image(
            "localhost/coredns:latest",
            rootless=False,
            run_as_user=None,
        )

        assert payload == {"image": "localhost/coredns:latest", "image_id": "sha256:abc"}

    def test_pre_pull_image_requires_verified_local_image(self, mocker: Any) -> None:
        """A successful pull command is not enough unless the reference is visible locally."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        mocker.patch(
            "abhaile.apply.quadlet.run_command",
            side_effect=[
                ExecutionResult(
                    action_id="podman-pull",
                    action_type="podman",
                    success=True,
                    return_code=0,
                ),
                ExecutionResult(
                    action_id="podman-image-exists",
                    action_type="podman",
                    success=False,
                    return_code=1,
                ),
            ],
        )

        with pytest.raises(ApplyError, match="not visible locally"):
            QuadletExecutor.pre_pull_image(
                "ghcr.io/0xerr0r/blocky:v0.28.0",
                rootless=False,
                run_as_user=None,
            )

    def test_verify_unit_unloaded_raises_when_unit_remains_loaded(self, mocker: Any) -> None:
        """Obsolete generated image units must be gone after their Quadlet file is removed."""
        mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="show-load-state:blocky-image.service",
                action_type="validation",
                success=True,
                return_code=0,
                stdout="loaded\n",
            ),
        )

        with pytest.raises(ApplyError, match="remains loaded"):
            QuadletExecutor.verify_unit_unloaded(
                "blocky-image.service",
                rootless=False,
                run_as_user=None,
            )

    def test_verify_unit_unloaded_rootless_uses_user_manager(self, mocker: Any) -> None:
        """Rootless obsolete unit checks should target the configured user's manager."""
        mock_run = mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="show-load-state:vault-agent-image.service",
                action_type="validation",
                success=True,
                return_code=0,
                stdout="not-found\n",
            ),
        )

        result = QuadletExecutor.verify_unit_unloaded(
            "vault-agent-image.service",
            rootless=True,
            run_as_user="abhaile",
        )

        assert result.success is True
        mock_run.assert_called_once_with(
            [
                "systemctl",
                "--user",
                "-M",
                "abhaile@",
                "show",
                "vault-agent-image.service",
                "--property=LoadState",
                "--value",
            ],
            action_id="show-load-state:vault-agent-image.service",
            action_type="validation",
            run_as_user=None,
            check=False,
        )

    def test_reset_failed_unit_accepts_already_unloaded_unit(self, mocker: Any) -> None:
        """reset-failed may fail after removal if the generated unit is already unloaded."""
        mock_reset = mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl reset-failed blocky-image.service",
                action_type="systemctl",
                success=False,
                return_code=1,
                stderr="Unit blocky-image.service not loaded.",
            ),
        )
        mock_load_state = mocker.patch.object(
            QuadletExecutor,
            "get_unit_load_state",
            side_effect=pytest.fail,
        )

        result = QuadletExecutor.reset_failed_unit(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )

        assert result.success is True
        assert result.return_code == 1
        mock_reset.assert_called_once_with(
            "reset-failed",
            "blocky-image.service",
            user=False,
            run_as_user=None,
            check=False,
        )
        mock_load_state.assert_not_called()

    def test_reset_failed_unit_accepts_unloaded_load_state(self, mocker: Any) -> None:
        """reset-failed failure is converged if systemd no longer has a loaded unit."""
        mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl reset-failed blocky-image.service",
                action_type="systemctl",
                success=False,
                return_code=1,
                stderr="systemd transient failure",
            ),
        )
        mock_load_state = mocker.patch.object(
            QuadletExecutor,
            "get_unit_load_state",
            return_value="not-found",
        )

        result = QuadletExecutor.reset_failed_unit(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )

        assert result.success is True
        mock_load_state.assert_called_once_with(
            "blocky-image.service",
            rootless=False,
            run_as_user=None,
        )

    def test_reset_failed_unit_raises_when_loaded_unit_reset_fails(self, mocker: Any) -> None:
        """A reset-failed error remains fatal while the obsolete unit is still loaded."""
        mocker.patch(
            "abhaile.apply.quadlet.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl reset-failed blocky-image.service",
                action_type="systemctl",
                success=False,
                return_code=1,
                stderr="systemd refused reset",
            ),
        )
        mocker.patch.object(QuadletExecutor, "get_unit_load_state", return_value="loaded")

        with pytest.raises(ApplyError, match="Failed to reset failed state"):
            QuadletExecutor.reset_failed_unit(
                "blocky-image.service",
                rootless=False,
                run_as_user=None,
            )

    def test_remove_podman_object_treats_absent_object_as_converged(self, mocker: Any) -> None:
        """Missing generated Podman objects should not make removals fail."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="podman-network-rm:systemd-services",
                action_type="podman",
                success=False,
                return_code=1,
                stderr="Error: no such network",
            ),
        )

        result = QuadletExecutor.remove_podman_object(
            "unit:services-network.service",
            kinds={"quadlet.network"},
            rootless=False,
            run_as_user=None,
        )

        assert result.success is True
        assert result.return_code == 1

    def test_remove_podman_object_failure_raises(self, mocker: Any) -> None:
        """Unexpected Podman object removal failures should block the transaction."""
        mocker.patch("abhaile.apply.quadlet.shutil.which", return_value="/usr/bin/podman")
        mocker.patch(
            "abhaile.apply.quadlet.run_command",
            return_value=ExecutionResult(
                action_id="podman-volume-rm:systemd-config",
                action_type="podman",
                success=False,
                return_code=125,
                stderr="permission denied",
            ),
        )

        with pytest.raises(ApplyError, match="permission denied"):
            QuadletExecutor.remove_podman_object(
                "unit:config-volume.service",
                kinds={"quadlet.volume"},
                rootless=False,
                run_as_user=None,
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
