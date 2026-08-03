"""Unit tests for shared directory metadata helpers."""

from __future__ import annotations

from abhaile.models.directory import directory_metadata_to_hints, resolve_directory_metadata


def test_networkd_dropin_defaults_to_root_root_0755() -> None:
    """Networkd drop-in directories should default to root:root 0755."""
    metadata = resolve_directory_metadata("networkd.dropin")

    assert metadata.owner == "root"
    assert metadata.group == "root"
    assert metadata.mode == "0755"


def test_service_directory_defaults_to_rootless_owner_contract() -> None:
    """Service directories should default to root:root 0750 when no owner is supplied."""
    metadata = resolve_directory_metadata("service.directory")

    assert metadata.owner == "root"
    assert metadata.group == "root"
    assert metadata.mode == "0750"


def test_service_directory_uses_explicit_owner_and_mode() -> None:
    """Service directory metadata should preserve authored overrides."""
    metadata = resolve_directory_metadata(
        "service.directory",
        {
            "owner": "abhaile",
            "mode": "0710",
        },
    )

    assert metadata.owner == "abhaile"
    assert metadata.group == "abhaile"
    assert metadata.mode == "0710"
    assert directory_metadata_to_hints(metadata) == {
        "owner": "abhaile",
        "group": "abhaile",
        "mode": "0710",
    }
