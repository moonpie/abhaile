"""Placeholder tests for ingress rendering error paths.

These tests are stubs for future implementation.
Actual ingress rendering is tested in test_ingress.py.
"""

import pytest


def test_missing_ingress_file(tmp_path):
    """Test that missing base Caddyfile raises RenderError."""
    from abhaile.renderers.ingress import render_ingress_configs
    from abhaile.utils.errors import RenderError

    config_root = tmp_path / "config"
    services_root = config_root / "services"
    output_dir = tmp_path / "output"

    # Create base service with ingress definition but missing source file
    base_service_dir = services_root / "caddy-dmz"
    base_service_dir.mkdir(parents=True)

    service_yaml = base_service_dir / "service.yaml"
    service_yaml.write_text(
        """
name: caddy-dmz
composition:
  ingress:
    dmz:
      base:
        source: config/Caddyfile
        destination: /srv/caddy/Caddyfile
""",
        encoding="utf-8",
    )

    # Don't create the actual Caddyfile

    with pytest.raises(RenderError) as exc_info:
        render_ingress_configs(
            host="phobos",
            host_services=["caddy-dmz"],
            all_services=["caddy-dmz"],
            config_root=config_root,
            output_dir=output_dir,
        )

    error = str(exc_info.value)
    assert "Base Caddyfile not found" in error
    assert "caddy-dmz" in error or "config/Caddyfile" in error
