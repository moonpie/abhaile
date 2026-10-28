"""Test private named-volume directory intent and coherent duplicate registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.quadlets.volumes import _render_named_volume_host_directory
from abhaile.utils.errors import RenderError


def _volume(**overrides: Any) -> dict[str, Any]:
    """Build a private read-only rootful volume with explicit metadata."""
    return {
        "name": "config",
        "host_path": "/srv/example/config",
        "mount_path": "/config",
        "mode": "ro",
        "host_owner": 0,
        "host_group": 0,
        "host_mode": "0750",
        **overrides,
    }


def _render(
    root: Path,
    collector: ArtifactCollector | None,
    volume: dict[str, Any],
    *,
    user: str = "root",
    shared: bool = False,
) -> None:
    """Render one isolated host directory without applying ownership to the test tree."""
    _render_named_volume_host_directory(
        service="example",
        user=user,
        volume=volume,
        shared=shared,
        output_dir=root / "services",
        collector=collector,
        rendered_root=root,
    )


def test_incidental_output_directory_still_registers_intent(tmp_path: Path) -> None:
    """An earlier config write must not suppress the manifest directory entry."""
    parent = tmp_path / "services/example/srv/example/config"
    parent.mkdir(parents=True)
    config = parent / "app.conf"
    config.write_text("application configuration\n")
    collector = ArtifactCollector()
    _render(tmp_path, collector, _volume())
    artifact = collector.get_all_artifacts()[0]
    assert artifact.target_path == "/srv/example/config"
    assert artifact.kind == "service.directory" and artifact.is_directory
    assert artifact.apply_hints == {"owner": 0, "group": 0, "mode": "0750"}
    assert config.read_text() == "application configuration\n"


def test_matching_registration_retains_provenance_and_extra_hints(tmp_path: Path) -> None:
    """Reuse the original object instead of discarding its contributor and service hints."""
    collector = ArtifactCollector()
    existing = collector.register_artifact(
        render_path="services/example/srv/example/config",
        target_path="/srv/example/config",
        kind="service.directory",
        owner_ref="service:example",
        content="",
        is_directory=True,
        contributor_ref="shared-config",
        apply_hints={"owner": 0, "group": 0, "mode": "0750", "restart_unit": "example.service"},
    )
    _render(tmp_path, collector, _volume())
    assert collector.get_all_artifacts() == [existing]
    assert collector.get_all_artifacts()[0] is existing


@pytest.mark.parametrize(
    "override",
    [
        {"target_path": "/srv/another/config"},
        {"kind": "service.config"},
        {"owner_ref": "service:another"},
        {"is_directory": False},
        {"apply_hints": {"owner": "root", "group": 0, "mode": "0750"}},
        {"apply_hints": {"owner": 0, "group": 999, "mode": "0750"}},
        {"apply_hints": {"owner": 0, "group": 0, "mode": "0755"}},
    ],
)
def test_conflicting_registration_fails_without_replacing_existing(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    """Reject differing identity or metadata, including unresolved name versus numeric ID."""
    collector = ArtifactCollector()
    values = {
        "render_path": "services/example/srv/example/config",
        "target_path": "/srv/example/config",
        "kind": "service.directory",
        "owner_ref": "service:example",
        "content": "",
        "is_directory": True,
        "apply_hints": {"owner": 0, "group": 0, "mode": "0750"},
        **override,
    }
    existing = collector.register_artifact(**values)
    with pytest.raises(
        RenderError, match="Conflicting managed directory declaration.*srv/example/config"
    ):
        _render(tmp_path, collector, _volume())
    assert collector.get_all_artifacts()[0] is existing


def test_distinct_render_paths_keep_duplicate_target_detection(tmp_path: Path) -> None:
    """Do not turn two rendered artifacts for one live path into last-wins registration."""
    collector = ArtifactCollector()
    collector.register_artifact(
        render_path="services/other/directory",
        target_path="/srv/example/config",
        kind="service.directory",
        owner_ref="service:other",
        content="",
        is_directory=True,
        apply_hints={"owner": 0, "group": 0, "mode": "0750"},
    )
    _render(tmp_path, collector, _volume())
    with pytest.raises(ValueError, match="Duplicate target_path"):
        collector.compute_hashes_and_sizes(tmp_path)


@pytest.mark.parametrize("target_type", ["file", "symlink", "dangling"])
def test_non_directory_output_is_rejected(tmp_path: Path, target_type: str) -> None:
    """Refuse output files and links instead of registering redirected directory intent."""
    target = tmp_path / "services/example/srv/example/config"
    target.parent.mkdir(parents=True)
    if target_type == "file":
        target.write_text("keep\n")
    else:
        other = tmp_path / "outside"
        if target_type == "symlink":
            other.mkdir()
        target.symlink_to(other, target_is_directory=True)
    with pytest.raises(RenderError, match="not a regular directory"):
        _render(tmp_path, ArtifactCollector(), _volume())


def test_rootless_defaults_and_shared_exclusion_remain(tmp_path: Path) -> None:
    """Retain runtime-user defaults while shared host paths remain unmanaged."""
    collector = ArtifactCollector()
    volume = {"name": "data", "host_path": "/srv/example/data", "mount_path": "/data"}
    _render(tmp_path, collector, volume, user="abhaile")
    assert collector.get_all_artifacts()[0].apply_hints == {
        "owner": "abhaile",
        "group": "abhaile",
        "mode": "0750",
    }
    _render(tmp_path, collector, {"host_path": "/etc/ssl/certs"}, shared=True)
    assert len(collector.get_all_artifacts()) == 1
    assert not (tmp_path / "services/example/etc/ssl/certs").exists()


def test_render_without_collector_still_creates_directory(tmp_path: Path) -> None:
    """Keep renderer use without manifest collection supported."""
    _render(tmp_path, None, _volume())
    assert (tmp_path / "services/example/srv/example/config").is_dir()
