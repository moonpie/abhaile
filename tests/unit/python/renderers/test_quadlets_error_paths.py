"""Placeholder tests for quadlet rendering error paths.

These tests are stubs for future implementation.
Actual quadlet rendering is tested in other test_quadlets_*.py files.
"""

import pytest


def test_missing_template_raises(tmp_path):
    """Test that missing quadlet network template raises RenderError."""
    from abhaile.renderers.quadlets.network import _render_network_quadlets
    from abhaile.utils.errors import RenderError

    config_root = tmp_path / "config"
    output_dir = tmp_path / "output"

    # Don't create the template directory/file

    network = {
        "vlans": {
            "vlan10": {"id": 10, "parent": "eth0"},
        },
    }

    with pytest.raises(RenderError) as exc_info:
        _render_network_quadlets(
            host="phobos",
            network=network,
            vlans=["vlan10"],
            output_dir=output_dir,
            config_root=config_root,
        )

    error = str(exc_info.value)
    assert "Missing network template" in error


def test_invalid_volume_definition(tmp_path):
    """Test that invalid volume definition raises RenderError."""
    from abhaile.renderers.quadlets.volumes import _render_named_volumes
    from abhaile.utils.errors import RenderError

    config_root = tmp_path / "config"
    output_dir = tmp_path / "output"
    shared_output_dir = output_dir / "shared"

    # Create the template so we can reach validation logic
    template_dir = config_root / "_templates" / "services" / "quadlets"
    template_dir.mkdir(parents=True)
    template_path = template_dir / "volume.volume.j2"
    template_path.write_text(
        """[Volume]\n""",
        encoding="utf-8",
    )

    # Invalid volume entry (missing required fields)
    container_def = {"named_volumes": [{"name": "vol1"}]}  # Missing host_path and mount_path

    with pytest.raises(RenderError) as exc_info:
        _render_named_volumes(
            service="test-service",
            container_def=container_def,
            user="root",
            output_root_relative="etc/containers/systemd",
            output_dir=output_dir,
            shared_output_dir=shared_output_dir,
            host_paths_by_user={},
            config_root=config_root,
            shared_volume_is_global=False,
        )

    error = str(exc_info.value)
    assert "Invalid named volume" in error
