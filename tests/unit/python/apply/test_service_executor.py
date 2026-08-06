"""Unit tests for service config apply executor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.service import ServiceConfigExecutor  # pyright: ignore[reportMissingImports]
from abhaile.utils.errors import ApplyError


class TestServiceConfigExecutor:
    """Tests for service config/env owner convergence."""

    def test_apply_owner_change_try_restart_rootful(self, mocker: Any) -> None:
        """Rootful service hints should restart and validate active state."""
        mock_restart = mocker.patch(
            "abhaile.apply.service.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl try-restart chrony.service",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_show = mocker.patch(
            "abhaile.apply.service.run_command",
            return_value=ExecutionResult(
                action_id="systemctl show chrony.service",
                action_type="systemctl",
                success=True,
                return_code=0,
                stdout="active\n",
            ),
        )

        summary = ServiceConfigExecutor.apply_owner_change(
            "service:chrony-a",
            writes=[{"kind": "service.config"}],
            removals=[],
            apply_hints={"restart_unit": "chrony.service"},
        )

        assert summary["restart_unit"] == "chrony.service"
        assert [action["action"] for action in summary["actions"]] == [
            "try-restart",
            "validate-active",
        ]
        mock_restart.assert_called_once_with(
            "try-restart",
            "chrony.service",
            user=False,
            run_as_user=None,
        )
        mock_show.assert_called_once_with(
            ["systemctl", "show", "chrony.service", "-p", "ActiveState", "--value"],
            action_id="systemctl show chrony.service",
            action_type="systemctl",
            run_as_user=None,
        )

    def test_apply_owner_change_try_restart_rootless(self, mocker: Any) -> None:
        """Rootless service hints should use systemctl --user and podman user."""
        mock_restart = mocker.patch(
            "abhaile.apply.service.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl --user try-restart authelia-app.service",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mock_show = mocker.patch(
            "abhaile.apply.service.run_command",
            return_value=ExecutionResult(
                action_id="systemctl --user show authelia-app.service",
                action_type="systemctl",
                success=True,
                return_code=0,
                stdout="active\n",
            ),
        )

        summary = ServiceConfigExecutor.apply_owner_change(
            "service:authelia",
            writes=[{"kind": "service.env"}],
            removals=[],
            apply_hints={
                "restart_unit": "authelia-app.service",
                "rootless": True,
                "podman_user": "abhaile",
            },
        )

        assert summary["rootless"] is True
        assert summary["run_as_user"] == "abhaile"
        mock_restart.assert_called_once_with(
            "try-restart",
            "authelia-app.service",
            user=True,
            run_as_user="abhaile",
        )
        mock_show.assert_called_once_with(
            [
                "systemctl",
                "--user",
                "-M",
                "abhaile@",
                "show",
                "authelia-app.service",
                "-p",
                "ActiveState",
                "--value",
            ],
            action_id="systemctl show authelia-app.service",
            action_type="systemctl",
            run_as_user=None,
        )

    def test_apply_owner_change_no_restart_when_restart_unit_null(self, mocker: Any) -> None:
        """Null restart hints should no-op for static-data service entries."""
        mock_restart = mocker.patch("abhaile.apply.service.run_systemctl_command")
        mock_show = mocker.patch("abhaile.apply.service.run_command")

        summary = ServiceConfigExecutor.apply_owner_change(
            "service:static-certs",
            writes=[{"kind": "service.config"}],
            removals=[],
            apply_hints={"restart_unit": None},
        )

        assert summary["actions"] == []
        mock_restart.assert_not_called()
        mock_show.assert_not_called()

    def test_apply_owner_change_raises_when_unit_not_active(self, mocker: Any) -> None:
        """Post-restart validation should fail if the unit is not active."""
        mocker.patch(
            "abhaile.apply.service.run_systemctl_command",
            return_value=ExecutionResult(
                action_id="systemctl try-restart blocky.service",
                action_type="systemctl",
                success=True,
                return_code=0,
            ),
        )
        mocker.patch(
            "abhaile.apply.service.run_command",
            return_value=ExecutionResult(
                action_id="systemctl show blocky.service",
                action_type="systemctl",
                success=True,
                return_code=0,
                stdout="inactive\n",
            ),
        )

        with pytest.raises(ApplyError, match="not active"):
            ServiceConfigExecutor.apply_owner_change(
                "service:blocky",
                writes=[{"kind": "service.config"}],
                removals=[],
                apply_hints={"restart_unit": "blocky.service"},
            )

    def test_apply_directory_change_enforces_owner_group_mode(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Directory enforcement should mkdir, chown, and chmod target path."""
        mocker.patch("abhaile.apply.service.resolve_uid", return_value=1001)
        mocker.patch("abhaile.apply.service.resolve_gid", return_value=1001)
        mock_chown = mocker.patch("abhaile.apply.service.os.chown")

        target = tmp_path / "srv" / "authelia" / "config"
        summary = ServiceConfigExecutor.apply_directory_change(
            target.as_posix(),
            {"owner": "abhaile", "group": "abhaile", "mode": "0750"},
        )

        assert target.exists()
        assert summary["target_path"] == target.as_posix()
        assert summary["owner"] == "abhaile"
        assert summary["group"] == "abhaile"
        assert summary["mode"] == "0750"
        mock_chown.assert_called_once_with(target, 1001, 1001)
        assert target.stat().st_mode & 0o777 == 0o750

    def test_apply_directory_change_idempotent_existing_directory(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Existing directory ownership and mode should be safely re-enforced."""
        target = tmp_path / "srv" / "existing" / "config"
        target.mkdir(parents=True, exist_ok=True)

        mocker.patch("abhaile.apply.service.resolve_uid", return_value=0)
        mocker.patch("abhaile.apply.service.resolve_gid", return_value=0)
        mock_chown = mocker.patch("abhaile.apply.service.os.chown")

        summary = ServiceConfigExecutor.apply_directory_change(
            target.as_posix(),
            {"owner": "root", "group": "root", "mode": "0755"},
        )

        assert summary["actions"][0]["action"] == "ensure-directory"
        assert target.exists()
        mock_chown.assert_called_once_with(target, 0, 0)
        assert target.stat().st_mode & 0o777 == 0o755

    def test_apply_directory_change_accepts_numeric_owner_group(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        """Numeric UID/GID metadata should be accepted by service.directory apply."""
        target = tmp_path / "srv" / "mongodb" / "data"
        mock_chown = mocker.patch("abhaile.apply.service.os.chown")

        summary = ServiceConfigExecutor.apply_directory_change(
            target.as_posix(),
            {"owner": 999, "group": 999, "mode": "0750"},
        )

        assert summary["owner"] == 999
        assert summary["group"] == 999
        mock_chown.assert_called_once_with(target, 999, 999)
        assert target.stat().st_mode & 0o777 == 0o750

    def test_apply_directory_change_rejects_invalid_mode(self, tmp_path: Path) -> None:
        """Invalid mode hints should fail closed."""
        target = tmp_path / "srv" / "invalid" / "config"
        with pytest.raises(ApplyError, match="Invalid directory mode"):
            ServiceConfigExecutor.apply_directory_change(
                target.as_posix(),
                {"owner": "root", "group": "root", "mode": "not-octal"},
            )

    def test_apply_directory_change_uses_shared_resolver(self, mocker: Any, tmp_path: Path) -> None:
        """Service directory enforcement should respect the shared metadata resolver."""
        mocker.patch("abhaile.apply.service.resolve_uid", return_value=1001)
        mocker.patch("abhaile.apply.service.resolve_gid", return_value=1001)
        mock_chown = mocker.patch("abhaile.apply.service.os.chown")
        mocker.patch(
            "abhaile.apply.service.resolve_directory_metadata",
            return_value=SimpleNamespace(owner="abhaile", group="abhaile", mode="0711"),
        )

        target = tmp_path / "srv" / "example" / "config"
        summary = ServiceConfigExecutor.apply_directory_change(target.as_posix(), None)

        assert summary["owner"] == "abhaile"
        assert summary["group"] == "abhaile"
        assert summary["mode"] == "0711"
        mock_chown.assert_called_once_with(target, 1001, 1001)
        assert target.stat().st_mode & 0o777 == 0o711
