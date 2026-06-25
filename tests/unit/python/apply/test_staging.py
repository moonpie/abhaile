"""Tests for apply staging helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.staging import (
    _copy_artifact_for_apply,
    _default_file_hints,
    _prepare_authorized_keys_parent,
    _required_user_hints,
)
from abhaile.utils.errors import ApplyError


class TestRequiredUserHints:
    """Tests for _required_user_hints."""

    def test_valid_hints(self) -> None:
        entry: dict[str, object] = {
            "apply_hints": {
                "owner_user": "root",
                "owner_group": "root",
                "mode": "0644",
            }
        }
        user, group, mode, ssh_mode = _required_user_hints(entry)
        assert user == "root"
        assert group == "root"
        assert mode == 0o644
        assert ssh_mode is None

    def test_valid_hints_with_ssh_dir_mode(self) -> None:
        entry: dict[str, object] = {
            "apply_hints": {
                "owner_user": "abhaile",
                "owner_group": "abhaile",
                "mode": "0600",
                "ssh_dir_mode": "0700",
            }
        }
        user, group, mode, ssh_mode = _required_user_hints(entry)
        assert user == "abhaile"
        assert group == "abhaile"
        assert mode == 0o600
        assert ssh_mode == 0o700

    def test_missing_apply_hints_raises(self) -> None:
        with pytest.raises(ApplyError, match="Missing apply_hints"):
            _required_user_hints({})

    def test_missing_owner_user_raises(self) -> None:
        entry: dict[str, object] = {"apply_hints": {"owner_group": "root", "mode": "0644"}}
        with pytest.raises(ApplyError, match="Missing owner_user"):
            _required_user_hints(entry)

    def test_missing_owner_group_raises(self) -> None:
        entry: dict[str, object] = {"apply_hints": {"owner_user": "root", "mode": "0644"}}
        with pytest.raises(ApplyError, match="Missing owner_group"):
            _required_user_hints(entry)

    def test_missing_mode_raises(self) -> None:
        entry: dict[str, object] = {"apply_hints": {"owner_user": "root", "owner_group": "root"}}
        with pytest.raises(ApplyError, match="Missing mode"):
            _required_user_hints(entry)

    def test_invalid_mode_raises(self) -> None:
        entry: dict[str, object] = {
            "apply_hints": {"owner_user": "root", "owner_group": "root", "mode": "xyz"}
        }
        with pytest.raises(ApplyError, match="Invalid mode hint"):
            _required_user_hints(entry)

    def test_invalid_ssh_dir_mode_raises(self) -> None:
        entry: dict[str, object] = {
            "apply_hints": {
                "owner_user": "root",
                "owner_group": "root",
                "mode": "0644",
                "ssh_dir_mode": "bad",
            }
        }
        with pytest.raises(ApplyError, match="Invalid ssh_dir_mode"):
            _required_user_hints(entry)


class TestDefaultFileHints:
    """Tests for default apply metadata hints."""

    def test_rootful_file_defaults_to_root_metadata(self) -> None:
        user, group, mode = _default_file_hints({"kind": "service.config"})
        assert user == "root"
        assert group == "root"
        assert mode == 0o644

    def test_rootless_file_defaults_to_podman_user_metadata(self) -> None:
        entry: dict[str, object] = {
            "kind": "quadlet.container",
            "apply_hints": {
                "rootless": True,
                "podman_user": "abhaile",
            },
        }

        user, group, mode = _default_file_hints(entry)
        assert user == "abhaile"
        assert group == "abhaile"
        assert mode == 0o644

    def test_rootless_file_missing_podman_user_raises(self) -> None:
        entry: dict[str, object] = {
            "kind": "quadlet.container",
            "apply_hints": {
                "rootless": True,
            },
        }

        with pytest.raises(ApplyError, match="missing podman_user"):
            _default_file_hints(entry)


class TestCopyArtifactForApply:
    """Tests for _copy_artifact_for_apply."""

    def test_service_directory_is_noop(self, tmp_path: Path) -> None:
        action: dict[str, object] = {
            "render_path": "services/app/srv/app/data",
            "target_path": "/srv/app/data",
            "kind": "service.directory",
        }
        # Should not raise or do anything
        _copy_artifact_for_apply(action, tmp_path)

    def test_directory_marker_is_noop_for_non_service_kind(self, tmp_path: Path) -> None:
        action: dict[str, object] = {
            "render_path": "system/etc/systemd/network/21-ipvlan-l2.network.d",
            "target_path": "/etc/systemd/network/21-ipvlan-l2.network.d",
            "kind": "networkd.network",
            "is_directory": True,
        }
        _copy_artifact_for_apply(action, tmp_path)

    @patch("abhaile.apply.staging.atomic_copy_file_with_perms")
    def test_regular_artifact_copies_with_default_metadata(
        self, mock_copy: Any, tmp_path: Path
    ) -> None:
        rendered = tmp_path / "rendered"
        rendered.mkdir()
        source = rendered / "system" / "etc" / "app.conf"
        source.parent.mkdir(parents=True)
        source.write_text("content")

        target = tmp_path / "target" / "etc" / "app.conf"
        action: dict[str, object] = {
            "render_path": "system/etc/app.conf",
            "target_path": target.as_posix(),
            "kind": "service.config",
        }

        _copy_artifact_for_apply(action, rendered)
        mock_copy.assert_called_once_with(
            source,
            target,
            mode=0o644,
            owner_user="root",
            owner_group="root",
        )

    @patch("abhaile.apply.staging.atomic_copy_file_with_perms")
    def test_rootless_artifact_copies_with_podman_user_metadata(
        self, mock_copy: Any, tmp_path: Path
    ) -> None:
        rendered = tmp_path / "rendered"
        source = rendered / "services" / "vault-agent" / "vault-agent.container"
        source.parent.mkdir(parents=True)
        source.write_text("[Container]")

        action: dict[str, object] = {
            "render_path": "services/vault-agent/vault-agent.container",
            "target_path": "/home/abhaile/.config/containers/systemd/vault-agent.container",
            "kind": "quadlet.container",
            "apply_hints": {
                "rootless": True,
                "podman_user": "abhaile",
            },
        }

        _copy_artifact_for_apply(action, rendered)
        mock_copy.assert_called_once_with(
            source,
            Path("/home/abhaile/.config/containers/systemd/vault-agent.container"),
            mode=0o644,
            owner_user="abhaile",
            owner_group="abhaile",
        )

    @patch("abhaile.apply.staging.atomic_copy_file_with_perms")
    @patch("abhaile.apply.staging.UserManagementExecutor.validate_sudoers")
    def test_sudoers_validates_and_copies_with_perms(
        self, mock_validate: Any, mock_copy: Any, tmp_path: Path
    ) -> None:
        rendered = tmp_path / "rendered"
        source = rendered / "system" / "etc" / "sudoers.d" / "abhaile"
        source.parent.mkdir(parents=True)
        source.write_text("# sudoers")

        mock_validate.return_value = ExecutionResult(
            action_id="validate:sudoers",
            action_type="validation",
            success=True,
            return_code=0,
        )

        action: dict[str, object] = {
            "render_path": "system/etc/sudoers.d/abhaile",
            "target_path": "/etc/sudoers.d/abhaile",
            "kind": "host.sudoers",
            "apply_hints": {
                "owner_user": "root",
                "owner_group": "root",
                "mode": "0440",
            },
        }

        _copy_artifact_for_apply(action, rendered)
        mock_validate.assert_called_once_with(source)
        mock_copy.assert_called_once_with(
            source,
            Path("/etc/sudoers.d/abhaile"),
            mode=0o440,
            owner_user="root",
            owner_group="root",
        )

    @patch("abhaile.apply.staging.atomic_copy_file_with_perms")
    def test_sysusers_copies_with_perms(self, mock_copy: Any, tmp_path: Path) -> None:
        rendered = tmp_path / "rendered"
        source = rendered / "system" / "etc" / "sysusers.d" / "abhaile.conf"
        source.parent.mkdir(parents=True)
        source.write_text("u abhaile")

        action: dict[str, object] = {
            "render_path": "system/etc/sysusers.d/abhaile.conf",
            "target_path": "/etc/sysusers.d/abhaile.conf",
            "kind": "host.sysusers",
            "apply_hints": {
                "owner_user": "root",
                "owner_group": "root",
                "mode": "0644",
            },
        }

        _copy_artifact_for_apply(action, rendered)
        mock_copy.assert_called_once_with(
            source,
            Path("/etc/sysusers.d/abhaile.conf"),
            mode=0o644,
            owner_user="root",
            owner_group="root",
        )

    @patch("abhaile.apply.staging._prepare_authorized_keys_parent")
    @patch("abhaile.apply.staging.atomic_copy_file_with_perms")
    def test_authorized_keys_prepares_parent_and_copies(
        self, mock_copy: Any, mock_prepare: Any, tmp_path: Path
    ) -> None:
        rendered = tmp_path / "rendered"
        source = rendered / "system" / "home" / "user" / ".ssh" / "authorized_keys"
        source.parent.mkdir(parents=True)
        source.write_text("ssh-ed25519 AAAA")

        action: dict[str, object] = {
            "render_path": "system/home/user/.ssh/authorized_keys",
            "target_path": "/home/user/.ssh/authorized_keys",
            "kind": "host.authorized_keys",
            "apply_hints": {
                "owner_user": "user",
                "owner_group": "user",
                "mode": "0600",
                "ssh_dir_mode": "0700",
            },
        }

        _copy_artifact_for_apply(action, rendered)
        mock_prepare.assert_called_once_with(
            Path("/home/user/.ssh/authorized_keys"),
            owner_user="user",
            owner_group="user",
            ssh_dir_mode=0o700,
        )
        mock_copy.assert_called_once_with(
            source,
            Path("/home/user/.ssh/authorized_keys"),
            mode=0o600,
            owner_user="user",
            owner_group="user",
        )

    def test_authorized_keys_missing_ssh_dir_mode_raises(self, tmp_path: Path) -> None:
        rendered = tmp_path / "rendered"
        source = rendered / "system" / "home" / "user" / ".ssh" / "authorized_keys"
        source.parent.mkdir(parents=True)
        source.write_text("ssh-ed25519 AAAA")

        action: dict[str, object] = {
            "render_path": "system/home/user/.ssh/authorized_keys",
            "target_path": "/home/user/.ssh/authorized_keys",
            "kind": "host.authorized_keys",
            "apply_hints": {
                "owner_user": "user",
                "owner_group": "user",
                "mode": "0600",
            },
        }

        with pytest.raises(ApplyError, match="Missing ssh_dir_mode"):
            _copy_artifact_for_apply(action, rendered)

    def test_missing_render_path_raises(self, tmp_path: Path) -> None:
        action: dict[str, object] = {"target_path": "/etc/test", "kind": "service.config"}
        with pytest.raises(ApplyError, match="missing render_path"):
            _copy_artifact_for_apply(action, tmp_path)

    def test_missing_kind_raises(self, tmp_path: Path) -> None:
        action: dict[str, object] = {"render_path": "system/etc/test", "target_path": "/etc/test"}
        with pytest.raises(ApplyError, match="missing kind"):
            _copy_artifact_for_apply(action, tmp_path)


class TestPrepareAuthorizedKeysParent:
    """Tests for _prepare_authorized_keys_parent."""

    def test_creates_directory_with_mode(self, tmp_path: Path, monkeypatch: Any) -> None:

        target = tmp_path / ".ssh" / "authorized_keys"

        # Mock pwd/grp lookups to avoid needing real users
        monkeypatch.setattr(
            "abhaile.apply.staging.pwd.getpwnam",
            lambda name: type("pw", (), {"pw_uid": 1000})(),
        )
        monkeypatch.setattr(
            "abhaile.apply.staging.grp.getgrnam",
            lambda name: type("gr", (), {"gr_gid": 1000})(),
        )
        monkeypatch.setattr("abhaile.apply.staging.os.chown", lambda path, uid, gid: None)

        _prepare_authorized_keys_parent(
            target,
            owner_user="testuser",
            owner_group="testuser",
            ssh_dir_mode=0o700,
        )

        assert target.parent.exists()
        assert target.parent.stat().st_mode & 0o777 == 0o700

    def test_unknown_user_raises(self, tmp_path: Path, monkeypatch: Any) -> None:

        target = tmp_path / ".ssh" / "authorized_keys"
        target.parent.mkdir(parents=True)

        monkeypatch.setattr(
            "abhaile.apply.staging.pwd.getpwnam",
            lambda name: (_ for _ in ()).throw(KeyError(name)),
        )

        with pytest.raises(ApplyError, match="Unable to resolve owner/group"):
            _prepare_authorized_keys_parent(
                target,
                owner_user="nobody_xyz",
                owner_group="nobody_xyz",
                ssh_dir_mode=0o700,
            )
