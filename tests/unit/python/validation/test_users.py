"""Unit tests for user management validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.utils.errors import RenderError
from abhaile.validation.users import validate_user_management_ids


def test_validate_users_detects_duplicate_uid(write_file: Any, tmp_path: Path) -> None:
    """Duplicate uid across different users fails validation."""
    config_root = tmp_path / "config"

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        """
name: common
composition:
  include: []
  user_management:
    users:
      alice:
        uid: 1001
    groups:
      alice:
        gid: 1001
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "host.yaml",
        """
name: phobos
composition:
  include:
    - common
  user_management:
    users:
      bob:
        uid: 1001
    groups:
      bob:
        gid: 1002
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="Duplicate uid 1001"):
        validate_user_management_ids("phobos", config_root)


def test_validate_users_detects_conflicting_scalar_fields(write_file: Any, tmp_path: Path) -> None:
    """Conflicting scalar fields for same user fail validation."""
    config_root = tmp_path / "config"

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        """
name: common
composition:
  include: []
  user_management:
    users:
      abhaile:
        uid: 1001
        shell: /bin/bash
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "host.yaml",
        """
name: phobos
composition:
  include:
    - common
  user_management:
    users:
      abhaile:
        shell: /bin/zsh
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="field 'shell' conflicts"):
        validate_user_management_ids("phobos", config_root)


def test_validate_users_detects_invalid_list_fields(write_file: Any, tmp_path: Path) -> None:
    """Non-list additional_groups fails validation."""
    config_root = tmp_path / "config"

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        """
name: common
composition:
  include: []
  user_management:
    users:
      abhaile:
        uid: 1001
        additional_groups: sudo
""".strip() + "\n",
    )
    write_file(
        config_root / "hosts" / "phobos" / "host.yaml",
        """
name: phobos
composition:
  include:
    - common
  user_management: {}
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="field 'additional_groups' must be a list of strings"):
        validate_user_management_ids("phobos", config_root)
