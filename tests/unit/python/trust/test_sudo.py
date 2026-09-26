"""Unit tests for constrained sudo cutover planning."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.sudo import SudoInstallPaths, constrained_sudo_install_plan


def _paths(tmp_path: Path) -> SudoInstallPaths:
    protected = tmp_path / "protected"
    protected.mkdir(mode=0o700)
    launcher = protected / "launcher"
    policy = protected / "sudoers"
    visudo = protected / "visudo"
    for path in (launcher, policy, visudo):
        path.write_text("fixture\n", encoding="utf-8")
        path.chmod(0o500)
    legacy = protected / "legacy-sudoers"
    legacy.write_text("fixture\n", encoding="utf-8")
    legacy.chmod(0o400)
    return SudoInstallPaths(
        launcher,
        policy,
        tmp_path / "usr/local/sbin/abhaile-converge-launcher",
        tmp_path / "etc/sudoers.d/abhaile-converge",
        legacy,
        visudo,
    )


def test_orders_launcher_proof_before_policy_activation(tmp_path: Path) -> None:
    """Install and self-test the launcher before enabling constrained sudo."""
    plan = constrained_sudo_install_plan(
        _paths(tmp_path), host="deimos", revision="a" * 40, root_uid=os.geteuid()
    )
    names = [step.name for step in plan]
    assert names.index("validate-policy") < names.index("activate-launcher")
    assert names.index("activate-launcher") < names.index("self-test-launcher-root")
    assert names.index("self-test-launcher-root") < names.index("activate-policy")
    assert names.index("activate-policy") < names.index("self-test-sudo")
    sudo_test = plan[names.index("self-test-sudo")].command
    assert sudo_test[:7] == (
        "/usr/sbin/runuser",
        "--user",
        "abhaile",
        "--",
        "/usr/bin/sudo",
        "-n",
        "--",
    )
    assert sudo_test[-1] == "--offline"


def test_never_replaces_legacy_policy(tmp_path: Path) -> None:
    """Reject a plan whose constrained destination aliases the live legacy rule."""
    paths = _paths(tmp_path)
    unsafe = SudoInstallPaths(
        paths.launcher_source,
        paths.policy_source,
        paths.launcher_destination,
        paths.legacy_policy,
        paths.legacy_policy,
        paths.visudo,
    )
    with pytest.raises(TrustError, match="must not replace"):
        constrained_sudo_install_plan(
            unsafe, host="deimos", revision="a" * 40, root_uid=os.geteuid()
        )


def test_rejects_mutable_or_linked_sources(tmp_path: Path) -> None:
    """Accept installation artifacts only from protected regular files."""
    paths = _paths(tmp_path)
    paths.policy_source.chmod(0o666)
    with pytest.raises(TrustError, match="writable"):
        constrained_sudo_install_plan(
            paths, host="deimos", revision="a" * 40, root_uid=os.geteuid()
        )
