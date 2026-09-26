"""Unit tests for protected trust-path policy."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.model import validate_protected_chain


def test_validates_every_component_from_injected_anchor(tmp_path: Path) -> None:
    """Accept a root-owned, non-writable directory chain and regular leaf."""
    anchor = tmp_path / "protected"
    leaf = anchor / "policy" / "known_hosts"
    leaf.parent.mkdir(parents=True, mode=0o700)
    leaf.write_text("pin\n", encoding="utf-8")
    leaf.chmod(0o600)
    validate_protected_chain(leaf, anchor=anchor, owner_uid=os.geteuid(), regular_file=True)


def test_rejects_writable_or_linked_intermediate_component(tmp_path: Path) -> None:
    """Fail closed before resolving through a writable directory or symlink."""
    anchor = tmp_path / "protected"
    writable = anchor / "writable"
    writable.mkdir(parents=True, mode=0o700)
    leaf = writable / "policy"
    leaf.write_text("policy", encoding="utf-8")
    leaf.chmod(0o600)
    writable.chmod(0o777)
    with pytest.raises(TrustError, match="writable"):
        validate_protected_chain(leaf, anchor=anchor, owner_uid=os.geteuid(), regular_file=True)
    writable.chmod(0o700)
    link = anchor / "link"
    link.symlink_to(writable, target_is_directory=True)
    with pytest.raises(TrustError, match="symlink"):
        validate_protected_chain(
            link / "policy", anchor=anchor, owner_uid=os.geteuid(), regular_file=True
        )


def test_rejects_path_outside_anchor(tmp_path: Path) -> None:
    """Do not validate a protected leaf through an unrelated trust root."""
    anchor = tmp_path / "protected"
    anchor.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_text("content", encoding="utf-8")
    with pytest.raises(TrustError, match="outside its trust anchor"):
        validate_protected_chain(outside, anchor=anchor, owner_uid=os.geteuid(), regular_file=True)
