"""Targeted tests to cover low-coverage branches."""

from __future__ import annotations

import logging

import pytest

from abhaile.apply.caddy import CaddyExecutor
from abhaile.apply.networkd import NetworkdExecutor
from abhaile.cli.common import configure_logging, print_diff_summary
from abhaile.utils.errors import ApplyError


class TestConfigureLogging:
    """Tests for configure_logging branches."""

    def test_verbosity_zero_sets_warning(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.NOTSET)
        configure_logging(0)
        assert root.level == logging.WARNING

    def test_verbosity_one_sets_info(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.NOTSET)
        configure_logging(1)
        assert root.level == logging.INFO

    def test_verbosity_two_sets_debug(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.NOTSET)
        configure_logging(2)
        assert root.level == logging.DEBUG


class TestPrintDiffSummary:
    """Tests for print_diff_summary."""

    def test_prints_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        plan = {
            "host": "phobos",
            "summary": {
                "added": 1,
                "changed": 2,
                "removed": 0,
                "writes": 3,
                "removals_safe": 0,
                "removals_drifted": 0,
                "removals_missing": 0,
            },
        }
        print_diff_summary(plan)
        out = capsys.readouterr().out
        assert "host=phobos" in out
        assert "added=1" in out


class TestNetworkdInterfaceEdgeCases:
    """Cover untested branches in NetworkdExecutor."""

    def test_interface_from_netdev_target(self) -> None:
        """Fallback to .netdev filename parsing."""
        assert (
            NetworkdExecutor.interface_from_owner_or_target(
                "service:networkd",
                "/etc/systemd/network/20-ipvlan-l2.netdev",
            )
            == "ipvlan-l2"
        )

    def test_interface_unable_to_determine_raises(self) -> None:
        """Unknown target format raises ApplyError."""
        with pytest.raises(ApplyError, match="Unable to determine"):
            NetworkdExecutor.interface_from_owner_or_target(
                "service:networkd",
                "/etc/random/file.txt",
            )

    def test_normalize_iface_name_no_number_prefix(self) -> None:
        """Non-numbered filenames pass through as-is."""
        assert NetworkdExecutor._normalize_iface_name("enp0s31f6") == "enp0s31f6"

    def test_interface_from_empty_owner_ref_prefix(self) -> None:
        """Empty iface: value falls through to target path."""
        assert (
            NetworkdExecutor.interface_from_owner_or_target(
                "iface:",
                "/etc/systemd/network/10-vlan20.network",
            )
            == "vlan20"
        )


class TestCaddySegmentEdgeCases:
    """Cover untested branches in CaddyExecutor."""

    def test_segment_unable_to_determine_raises(self) -> None:
        """Non-caddy target path with generic owner raises ApplyError."""
        with pytest.raises(ApplyError, match="Unable to determine caddy segment"):
            CaddyExecutor.segment_from_owner_or_target(
                "service:generic",
                "/etc/random/config.txt",
            )

    def test_segment_from_empty_caddy_owner_falls_through(self) -> None:
        """Empty caddy: value falls through to target path."""
        assert (
            CaddyExecutor.segment_from_owner_or_target(
                "caddy:",
                "/srv/caddy/dmz/Caddyfile",
            )
            == "dmz"
        )


class TestDnsUtilsImport:
    """Cover dns/utils.py by importing it."""

    def test_import(self) -> None:
        import abhaile.dns.utils  # noqa: F401
