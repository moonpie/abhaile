"""Unit tests for phase 7.7 systemd-networkd executor."""

from __future__ import annotations

from typing import Any

import pytest

from abhaile.apply.actions import ExecutionResult
from abhaile.apply.networkd import NetworkdExecutor  # pyright: ignore[reportMissingImports]
from abhaile.utils.errors import ApplyError


class TestNetworkdExecutor:
    """Tests for networkd apply executor."""

    def test_interface_from_owner_ref(self) -> None:
        """Interface should be parsed from owner_ref when present."""
        assert (
            NetworkdExecutor.interface_from_owner_or_target(
                "iface:enp0s31f6.100",
                "/etc/systemd/network/10-enp0s31f6.100.network",
            )
            == "enp0s31f6.100"
        )

    def test_interface_from_target_path_network(self) -> None:
        """Interface should fall back to .network filename parsing."""
        assert (
            NetworkdExecutor.interface_from_owner_or_target(
                "service:networkd",
                "/etc/systemd/network/10-vlan20.network",
            )
            == "vlan20"
        )

    def test_interface_from_target_path_dropin(self) -> None:
        """Interface should be derived from .network.d parent directory."""
        assert (
            NetworkdExecutor.interface_from_owner_or_target(
                "service:networkd",
                "/etc/systemd/network/21-ipvlan-l2.network.d/200-caddy.conf",
            )
            == "ipvlan-l2"
        )

    def test_validate_missing_networkctl_non_strict(self, mocker: Any) -> None:
        """Dry-run validation should warn when networkctl is unavailable."""
        mocker.patch("abhaile.apply.networkd.shutil.which", return_value=None)

        result = NetworkdExecutor.validate_networkctl(strict=False)
        assert result.success
        assert result.return_code is None
        assert "missing" in result.error_message

    def test_validate_missing_networkctl_strict_raises(self, mocker: Any) -> None:
        """Apply should fail-fast when networkctl is unavailable."""
        mocker.patch("abhaile.apply.networkd.shutil.which", return_value=None)

        with pytest.raises(ApplyError, match="networkctl is required"):
            NetworkdExecutor.validate_networkctl(strict=True)

    def test_apply_owner_change_runs_reload_then_reconfigure(self, mocker: Any) -> None:
        """networkd owner converge should run reload and reconfigure."""
        mock_reload = mocker.patch.object(
            NetworkdExecutor,
            "reload_networkd",
            return_value=ExecutionResult(
                action_id="networkctl-reload",
                action_type="reload",
                success=True,
                return_code=0,
            ),
        )
        mock_reconfigure = mocker.patch.object(
            NetworkdExecutor,
            "reconfigure_interface",
            return_value=ExecutionResult(
                action_id="networkctl-reconfigure:vlan20",
                action_type="reconfigure",
                success=True,
                return_code=0,
            ),
        )

        summary = NetworkdExecutor.apply_owner_change(
            "iface:vlan20",
            interface="vlan20",
            strict_reconfigure=True,
            kinds=["networkd.network"],
        )

        assert summary["owner_ref"] == "iface:vlan20"
        assert summary["interface"] == "vlan20"
        assert summary["actions"][0]["action"] == "reload"
        assert summary["actions"][1]["action"] == "reconfigure"
        mock_reload.assert_called_once()
        mock_reconfigure.assert_called_once_with("vlan20", strict=True)

    def test_apply_owner_change_remove_only_netdev_deletes_before_reload(self, mocker: Any) -> None:
        """remove-only netdev owner should delete interface and skip reconfigure."""
        mock_delete = mocker.patch.object(
            NetworkdExecutor,
            "delete_interface",
            return_value=ExecutionResult(
                action_id="ip-link-delete:ipvlan-l2",
                action_type="delete",
                success=True,
                return_code=0,
            ),
        )
        mock_reload = mocker.patch.object(
            NetworkdExecutor,
            "reload_networkd",
            return_value=ExecutionResult(
                action_id="networkctl-reload",
                action_type="reload",
                success=True,
                return_code=0,
            ),
        )
        mock_reconfigure = mocker.patch.object(NetworkdExecutor, "reconfigure_interface")

        summary = NetworkdExecutor.apply_owner_change(
            "iface:ipvlan-l2",
            interface="ipvlan-l2",
            strict_reconfigure=False,
            kinds=["networkd.netdev"],
            delete_interface_first=True,
            run_reconfigure=False,
        )

        assert [action["action"] for action in summary["actions"]] == [
            "delete-interface",
            "reload",
        ]
        mock_delete.assert_called_once_with("ipvlan-l2")
        mock_reload.assert_called_once()
        mock_reconfigure.assert_not_called()
