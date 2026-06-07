"""Unit tests for users renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.users import render_users_artifacts
from abhaile.renderers.collector import ArtifactCollector
from abhaile.utils.errors import RenderError


def test_render_users_merges_and_renders_sysusers_and_sudoers(
    write_file: Any, tmp_path: Path
) -> None:
    """Merged user management renders deterministic sysusers and sudoers."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "system"

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
        system: false
        primary_group: abhaile
        home: /home/abhaile
        shell: /bin/bash
        gecos: "Abhaile service account"
        ssh_authorized_keys:
          - "ssh-ed25519 AAAATESTKEY1 moonpie@laptop"
          - "ssh-ed25519 AAAATESTKEY2 moonpie@desktop"
    groups:
      abhaile:
        gid: 1001
      apex:
        gid: 1002
      sudo:
        gid: 27
    sudoers:
      - name: abhaile
        rules:
          - "abhaile ALL=(ALL) NOPASSWD:ALL"
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
        additional_groups:
          - sudo
          - apex
""".strip() + "\n",
    )

    render_users_artifacts("phobos", config_root, output_dir)

    sysusers_text = (output_dir / "etc" / "sysusers.d" / "abhaile.conf").read_text(encoding="utf-8")
    sudoers_text = (output_dir / "etc" / "sudoers.d" / "abhaile").read_text(encoding="utf-8")
    authorized_keys_text = (output_dir / "home" / "abhaile" / ".ssh" / "authorized_keys").read_text(
        encoding="utf-8"
    )

    assert sysusers_text == (
        "# Managed by Abhaile. Do not edit.\n"
        "g abhaile 1001\n"
        "g apex 1002\n"
        "g sudo 27\n"
        'u abhaile 1001 "Abhaile service account" /home/abhaile /bin/bash\n'
        "m abhaile apex\n"
        "m abhaile sudo\n"
    )
    assert sudoers_text == (
        "# Managed by Abhaile. Do not edit.\n" "abhaile ALL=(ALL) NOPASSWD:ALL\n"
    )
    assert authorized_keys_text == (
        "# Managed by Abhaile. Do not edit.\n"
        "ssh-ed25519 AAAATESTKEY1 moonpie@laptop\n"
        "ssh-ed25519 AAAATESTKEY2 moonpie@desktop\n"
    )


def test_render_users_errors_on_conflicting_user_fields(write_file: Any, tmp_path: Path) -> None:
    """Conflicting scalar fields for same user fail render."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "system"

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
        primary_group: abhaile
    groups:
      abhaile:
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
      abhaile:
        uid: 2001
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="field 'uid' conflict"):
        render_users_artifacts("phobos", config_root, output_dir)


def test_render_users_errors_on_missing_group_reference(write_file: Any, tmp_path: Path) -> None:
    """Missing referenced group fails render."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "system"

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
        primary_group: abhaile
        additional_groups:
          - sudo
    groups:
      abhaile:
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
  user_management: {}
""".strip() + "\n",
    )

    with pytest.raises(RenderError, match="additional_group 'sudo' is not defined"):
        render_users_artifacts("phobos", config_root, output_dir)


def test_render_users_registers_metadata(write_file: Any, tmp_path: Path) -> None:
    """Users renderer registers host/user metadata kinds and owners."""
    config_root = tmp_path / "config"
    rendered_root = tmp_path / "out" / "rendered"
    output_dir = rendered_root / "system"
    collector = ArtifactCollector()

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
        primary_group: abhaile
        home: /home/abhaile
        ssh_authorized_keys:
          - "ssh-ed25519 AAAATESTKEY1 moonpie@laptop"
    groups:
      abhaile:
        gid: 1001
    sudoers:
      - name: abhaile
        rules:
          - "abhaile ALL=(ALL) NOPASSWD:ALL"
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

    render_users_artifacts(
        "phobos",
        config_root,
        output_dir,
        collector=collector,
        rendered_root=rendered_root,
    )

    sysusers = collector.get_artifacts_by_owner("host-users:phobos")
    assert any(artifact.kind == "host.sysusers" for artifact in sysusers)

    sudoers = collector.get_artifacts_by_owner("host-sudoers:phobos")
    assert any(artifact.kind == "host.sudoers" for artifact in sudoers)

    keys = collector.get_artifacts_by_owner("principal:abhaile")
    assert any(artifact.kind == "host.authorized_keys" for artifact in keys)

    owners = collector.get_all_owners()
    assert owners["host-sudoers:phobos"].requires == ["host-users:phobos"]
    assert owners["principal:abhaile"].requires == ["host-users:phobos"]


def test_sysusers_uid_group_syntax_when_group_differs(write_file: Any, tmp_path: Path) -> None:
    """When primary_group differs from username, sysusers emits uid:group syntax."""
    config_root = tmp_path / "config"
    output_dir = tmp_path / "out" / "rendered" / "system"

    write_file(
        config_root / "hosts" / "common" / "host.yaml",
        "name: common\ncomposition:\n  include: []\n  user_management: {}\n",
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
      deploy:
        uid: 2001
        primary_group: www-data
        home: /home/deploy
        shell: /bin/bash
    groups:
      www-data:
        gid: 33
""".strip() + "\n",
    )

    render_users_artifacts("phobos", config_root, output_dir)

    sysusers_text = (output_dir / "etc" / "sysusers.d" / "abhaile.conf").read_text(encoding="utf-8")
    assert "u deploy 2001:www-data - /home/deploy /bin/bash\n" in sysusers_text
