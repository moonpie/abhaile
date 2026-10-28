"""Test canonical container image resolution and existing composition selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.quadlets.helpers import (
    _resolve_composition_definition,
    _resolve_container_image_config,
)
from abhaile.utils.errors import RenderError
from abhaile.renderers.quadlets.renderer import render_service_quadlets


def _write_service(root: Path, name: str, composition: dict[str, Any]) -> None:
    """Write an isolated service definition."""
    path = root / name / "service.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "composition": composition}))


@pytest.mark.parametrize(
    ("container", "expected"),
    [
        ({}, (None, "missing")),
        ({"image": "app:1"}, ("app:1", "missing")),
        ({"image": "app:1", "pull_policy": "never"}, ("app:1", "never")),
        ({"image": "app:1", "pull_policy": "newer"}, ("app:1", "newer")),
        ({"pull_policy": "always"}, (None, "always")),
    ],
)
def test_selected_container_settings(
    container: dict[str, Any], expected: tuple[str | None, str]
) -> None:
    """Resolve only the supplied container object, applying the existing policy default."""
    assert (
        _resolve_container_image_config(
            service="leaf", container_name="app", container_def=container
        )
        == expected
    )


@pytest.mark.parametrize(
    "container",
    [
        {"image": ""},
        {"image": "  "},
        {"image": 42},
        {"image": "app:1", "pull_policy": "sometimes"},
    ],
)
def test_invalid_registry_values_have_container_context(container: dict[str, Any]) -> None:
    """Report the pod member in malformed image or policy diagnostics."""
    with pytest.raises(RenderError, match="leaf/app"):
        _resolve_container_image_config(
            service="leaf", container_name="app", container_def=container
        )


@pytest.mark.parametrize("local", [False, True])
def test_existing_include_selection_and_local_replacement(tmp_path: Path, local: bool) -> None:
    """Select the first resolvable include, unless a nonempty local container replaces it."""
    root = tmp_path / "services"
    _write_service(root, "base", {"container": {"image": "base:1", "pull_policy": "never"}})
    _write_service(root, "first", {"include": ["base"]})
    _write_service(root, "second", {"container": {"image": "second:2", "pull_policy": "always"}})
    composition: dict[str, Any] = {"include": ["first", "second"]}
    if local:
        # A local mount cannot silently recover the image from the inherited container.
        composition["container"] = {"mounted_files": []}
    _write_service(root, "leaf", composition)
    definition, source = _resolve_composition_definition("container", "leaf", composition, root)
    assert definition is not None
    assert source == ("leaf" if local else "first")
    assert _resolve_container_image_config(
        service="leaf", container_name=None, container_def=definition
    ) == ((None, "missing") if local else ("base:1", "never"))


def test_deep_merge_within_selected_include_is_preserved(tmp_path: Path) -> None:
    """Keep deep merging inside the selected included composition graph."""
    root = tmp_path / "services"
    _write_service(root, "base", {"container": {"image": "base:1", "pull_policy": "never"}})
    _write_service(root, "shared", {"include": ["base"], "container": {"image": "override:2"}})
    composition = {"include": ["shared"]}
    _write_service(root, "leaf", composition)
    definition, _source = _resolve_composition_definition("container", "leaf", composition, root)
    assert definition is not None
    assert _resolve_container_image_config(
        service="leaf", container_name=None, container_def=definition
    ) == ("override:2", "never")


@pytest.mark.parametrize("source", ["standalone-service", "pod-service", "pod-wrapper"])
def test_removed_image_locations_cannot_supply_rendered_image(tmp_path: Path, source: str) -> None:
    """Even direct renderer calls cannot obtain images from removed authoring locations."""
    root = tmp_path / "config" / "services"
    podman: dict[str, Any] = {"user": "root", "network": "host"}
    member: dict[str, Any] = {"name": "app", "container": {}}
    if source == "pod-wrapper":
        member.update(image="ignored:1", pull_policy="always")
    else:
        podman.update(image="ignored:1", pull_policy="always")
    in_pod = source != "standalone-service"
    composition = (
        {"pod": {"containers": [member]}} if in_pod else {"container": {"mounted_files": []}}
    )
    path = root / "leaf" / "service.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"name": "leaf", "podman": podman, "composition": composition}))
    quadlets = path.parent / "quadlets"
    quadlets.mkdir()
    if in_pod:
        (quadlets / "pod.pod.j2").write_text("[Pod]\n")
        quadlets = quadlets / "app"
        quadlets.mkdir()
    (quadlets / "container.container.j2").write_text("[Container]\nImage={{ image }}\n")
    with pytest.raises(RenderError, match="Template requires image variable"):
        render_service_quadlets("phobos", ["leaf"], {}, tmp_path / "config", tmp_path / "output")


def test_direct_pod_renderer_requires_nested_container(tmp_path: Path) -> None:
    """Give callers outside schema validation an actionable missing-object diagnostic."""
    root = tmp_path / "config" / "services"
    _write_service(root, "leaf", {"pod": {"containers": [{"name": "app"}]}})
    path = root / "leaf" / "service.yaml"
    data = json.loads(path.read_text())
    data["podman"] = {"user": "root", "network": "host"}
    path.write_text(json.dumps(data))
    quadlets = path.parent / "quadlets"
    quadlets.mkdir()
    (quadlets / "pod.pod.j2").write_text("[Pod]\n")
    with pytest.raises(RenderError, match="leaf/app.*must define a container object"):
        render_service_quadlets("phobos", ["leaf"], {}, tmp_path / "config", tmp_path / "output")
