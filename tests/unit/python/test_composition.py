"""Tests for service composition resolver."""

from pathlib import Path

import pytest
import yaml

from abhaile.utils.composition import resolve_composition
from abhaile.utils.errors import RenderError


def _write_service(config_root: Path, name: str, composition: dict) -> None:
    service_dir = config_root / "services" / name
    service_dir.mkdir(parents=True, exist_ok=True)
    service_data = {
        "name": name,
        "composition": composition,
    }
    (service_dir / "service.yaml").write_text(yaml.safe_dump(service_data))


def test_resolve_composition_simple(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True)

    composition = {"dns": {"zone_files": [{"zone": "*"}]}}
    _write_service(config_root, "simple", composition)

    resolved = resolve_composition("simple", config_root)
    assert resolved == composition


def test_resolve_composition_multi_level_includes(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True)

    _write_service(
        config_root,
        "base",
        {"dns": {"zone_files": [{"zone": "*"}], "settings": {"a": 1}}},
    )
    _write_service(
        config_root,
        "mid",
        {"include": ["base"], "dns": {"settings": {"b": 2}}},
    )
    _write_service(
        config_root,
        "top",
        {"include": ["mid"], "container": {"image": "example"}},
    )

    resolved = resolve_composition("top", config_root)

    assert resolved["container"]["image"] == "example"
    assert resolved["dns"]["zone_files"] == [{"zone": "*"}]
    assert resolved["dns"]["settings"] == {"a": 1, "b": 2}


def test_resolve_composition_cycle_detection(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True)

    _write_service(config_root, "alpha", {"include": ["beta"]})
    _write_service(config_root, "beta", {"include": ["alpha"]})

    with pytest.raises(RenderError, match="Circular dependency"):
        resolve_composition("alpha", config_root)


def test_resolve_composition_deep_vs_shallow(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True)

    _write_service(
        config_root,
        "base",
        {"dns": {"zone_files": [{"zone": "*"}], "settings": {"a": 1}}},
    )
    _write_service(
        config_root,
        "child",
        {"include": ["base"], "dns": {"settings": {"b": 2}}},
    )

    deep = resolve_composition("child", config_root, merge_strategy="deep")
    shallow = resolve_composition("child", config_root, merge_strategy="shallow")

    assert deep["dns"]["settings"] == {"a": 1, "b": 2}
    assert deep["dns"]["zone_files"] == [{"zone": "*"}]

    assert shallow["dns"] == {"settings": {"b": 2}}
