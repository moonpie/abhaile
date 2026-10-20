"""Targeted tests to cover low-coverage branches."""

from __future__ import annotations

import logging

from abhaile.cli.common import configure_logging


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


class TestDnsUtilsImport:
    """Cover dns/utils.py by importing it."""

    def test_import(self) -> None:
        import abhaile.dns.utils  # noqa: F401
