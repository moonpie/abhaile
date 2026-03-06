"""Tests for ingress rendering error paths."""

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.ingress import render_ingress_configs
from abhaile.utils.errors import RenderError


def test_missing_ingress_file(tmp_path: Path, write_file: Any) -> None:
    """Missing ingress block file raises RenderError."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "output" / "services"

    write_file(
        config_root / "services" / "caddy-dmz" / "service.yaml",
        """name: caddy-dmz
composition:
    ingress:
        dmz:
            base:
                source: config/Caddyfile
                destination: /srv/caddy/dmz/Caddyfile
""",
    )

    write_file(
        config_root / "services" / "caddy-dmz" / "config" / "Caddyfile",
        "{ admin off }\n",
    )

    write_file(
        config_root / "services" / "authelia" / "service.yaml",
        """name: authelia
composition:
    ingress:
        dmz:
            blocks:
                - caddy/dmz-ingress.txt
""",
    )

    with pytest.raises(RenderError, match="Ingress block not found"):
        render_ingress_configs(
            "phobos",
            ["caddy-dmz"],
            ["caddy-dmz", "authelia"],
            config_root,
            output_dir,
        )
