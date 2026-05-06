"""Unit tests for phase 7.3 user-management executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.apply.users import UserManagementExecutor
from abhaile.utils.errors import ApplyError


class TestUserManagementExecutor:
    """Tests for host user-management apply executor."""

    def test_run_sysusers_reconcile_success(self, mocker: Any) -> None:
        """systemd-sysusers command should be returned on success."""
        mock_run = mocker.patch(
            "abhaile.apply.users.run_command",
            return_value=type(
                "Result",
                (),
                {"success": True, "return_code": 0, "error_message": ""},
            )(),
        )

        result = UserManagementExecutor.run_sysusers_reconcile()
        assert result.success
        mock_run.assert_called_once_with(
            ["systemd-sysusers"],
            action_id="systemd-sysusers",
            action_type="user-management",
        )

    def test_run_sysusers_reconcile_failure_raises(self, mocker: Any) -> None:
        """sysusers failure should abort apply (fail-fast)."""
        mocker.patch(
            "abhaile.apply.users.run_command",
            return_value=type(
                "Result",
                (),
                {"success": False, "return_code": 1, "error_message": "bad config"},
            )(),
        )

        with pytest.raises(ApplyError, match="systemd-sysusers failed"):
            UserManagementExecutor.run_sysusers_reconcile()

    def test_validate_sudoers(self, mocker: Any, tmp_path: Path) -> None:
        """visudo validation should run as blocker."""
        sudoers = tmp_path / "abhaile"
        sudoers.write_text("abhaile ALL=(ALL) NOPASSWD:ALL\n")

        mock_validate = mocker.patch(
            "abhaile.apply.users.run_validation",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )

        result = UserManagementExecutor.validate_sudoers(sudoers)
        assert result.success
        mock_validate.assert_called_once_with(
            ["visudo", "-cf", sudoers.as_posix()],
            action_id=f"validate:sudoers:{sudoers}",
            is_blocker=True,
        )

    def test_apply_sysusers_write_summary(self, mocker: Any) -> None:
        """host.sysusers summary should include reconciliation action."""
        mocker.patch.object(
            UserManagementExecutor,
            "run_sysusers_reconcile",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )

        result = UserManagementExecutor.apply_sysusers_write({"kind": "host.sysusers"})
        assert result["kind"] == "host.sysusers"
        assert result["actions"][0]["action"] == "systemd-sysusers"

    def test_apply_sudoers_write_summary(self, mocker: Any, tmp_path: Path) -> None:
        """host.sudoers summary should include validation action."""
        target = tmp_path / "abhaile"
        target.write_text("abhaile ALL=(ALL) NOPASSWD:ALL\n")

        mocker.patch.object(
            UserManagementExecutor,
            "validate_sudoers",
            return_value=type("Result", (), {"success": True, "return_code": 0})(),
        )

        result = UserManagementExecutor.apply_sudoers_write({"kind": "host.sudoers"}, target)
        assert result["kind"] == "host.sudoers"
        assert result["actions"][0]["action"] == "visudo-validate"

    def test_apply_authorized_keys_write_noop(self) -> None:
        """host.authorized_keys runtime action should be a no-op command-wise."""
        result = UserManagementExecutor.apply_authorized_keys_write(
            {"kind": "host.authorized_keys"}
        )
        assert result["kind"] == "host.authorized_keys"
        assert result["actions"] == []
