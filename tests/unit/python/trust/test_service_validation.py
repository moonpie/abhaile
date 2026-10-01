"""Test closed offline validation of renderer-produced service configurations."""

from pathlib import Path
from typing import Callable

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.service_validation import (
    validate_caddyfile,
    validate_coredns_corefile,
    validate_resolved_config,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "relative",
    [
        "config/services/caddy-internal/config/Caddyfile",
        "config/services/caddy-dmz/config/Caddyfile",
    ],
)
def test_accepts_renderer_caddy_vocabulary(relative: str) -> None:
    """Accept the complete checked-in Caddy template vocabulary without executing Caddy."""
    payload = (ROOT / relative).read_bytes()
    validate_caddyfile(payload)


def test_accepts_rendered_coredns_vocabulary() -> None:
    """Accept a representative complete renderer-produced CoreDNS configuration."""
    payload = b"example.test:53 {\n bind 192.0.2.1\n log\n errors\n}\n"
    validate_coredns_corefile(payload)


def test_accepts_renderer_resolved_grammar() -> None:
    """Accept the complete closed rendered resolved key vocabulary."""
    payload = (ROOT / "config/hosts/common/systemd-resolved/resolved.conf.j2").read_bytes()
    validate_resolved_config(payload)


@pytest.mark.parametrize(
    "validator,payload",
    [
        (validate_caddyfile, b"example.test {\n shell /bin/sh\n}\n"),
        (validate_caddyfile, b"example.test {\n respond\n}\n"),
        (validate_caddyfile, b"example.test {\n token value\n}\n"),
        (validate_caddyfile, b"example.test {\n import ../../unsafe\n}\n"),
        (validate_coredns_corefile, b".:53 {\n exec /bin/sh\n}\n"),
        (validate_coredns_corefile, b".:53 {\n bind\n}\n"),
        (validate_coredns_corefile, b".:53 {\n force_tcp\n}\n"),
        (validate_coredns_corefile, b".:53 {\n log\n"),
        (validate_resolved_config, b"[Resolve]\nExec=/bin/sh\n"),
    ],
)
def test_rejects_unsupported_or_incomplete_configuration(
    validator: Callable[[bytes], None], payload: bytes
) -> None:
    """Reject unknown directives, unsafe imports, and unbalanced blocks."""
    with pytest.raises(TrustError):
        validator(payload)
