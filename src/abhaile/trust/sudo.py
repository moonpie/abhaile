"""Define the fail-closed constrained-sudo installation transaction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from abhaile.trust.errors import TrustError
from abhaile.trust.model import validate_protected_path


@dataclass(frozen=True)
class SudoInstallPaths:
    """Describe injectable protected sources and privileged destinations."""

    launcher_source: Path
    policy_source: Path
    launcher_destination: Path
    policy_destination: Path
    legacy_policy: Path
    visudo: Path = Path("/usr/sbin/visudo")


@dataclass(frozen=True)
class SudoInstallStep:
    """Describe one ordered command in the privileged installation transaction."""

    name: str
    command: tuple[str, ...]


def constrained_sudo_install_plan(
    paths: SudoInstallPaths,
    *,
    host: str,
    revision: str,
    root_uid: int = 0,
) -> tuple[SudoInstallStep, ...]:
    """Validate trusted inputs and return the required non-locking cutover sequence."""
    if host not in ("deimos", "phobos"):
        raise TrustError("Sudo installation host is invalid")
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise TrustError("Sudo launcher self-test revision must be a full commit object ID")
    validate_protected_path(paths.launcher_source, owner_uid=root_uid, regular_file=True)
    validate_protected_path(paths.policy_source, owner_uid=root_uid, regular_file=True)
    validate_protected_path(paths.visudo, owner_uid=root_uid, regular_file=True)
    if not paths.launcher_destination.is_absolute() or not paths.policy_destination.is_absolute():
        raise TrustError("Sudo installation destinations must be absolute")
    if paths.legacy_policy == paths.policy_destination:
        raise TrustError("Constrained policy must not replace the legacy policy")
    validate_protected_path(paths.legacy_policy, owner_uid=root_uid, regular_file=True)
    launcher_staged = paths.launcher_destination.with_name(
        f".{paths.launcher_destination.name}.new"
    )
    policy_staged = paths.policy_destination.with_name(f".{paths.policy_destination.name}.new")
    exact_launcher = (
        str(paths.launcher_destination),
        "--runner",
        "--host",
        host,
        "--revision",
        revision,
        "--dry-run",
        "--offline",
    )
    return (
        SudoInstallStep(
            "stage-launcher",
            (
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0755",
                str(paths.launcher_source),
                str(launcher_staged),
            ),
        ),
        SudoInstallStep(
            "stage-policy",
            (
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0440",
                str(paths.policy_source),
                str(policy_staged),
            ),
        ),
        SudoInstallStep("validate-policy", (str(paths.visudo), "-cf", str(policy_staged))),
        SudoInstallStep(
            "activate-launcher", ("mv", "-T", str(launcher_staged), str(paths.launcher_destination))
        ),
        SudoInstallStep("self-test-launcher-root", exact_launcher),
        SudoInstallStep(
            "activate-policy", ("mv", "-T", str(policy_staged), str(paths.policy_destination))
        ),
        SudoInstallStep(
            "validate-installed-policy", (str(paths.visudo), "-cf", str(paths.policy_destination))
        ),
        SudoInstallStep(
            "self-test-sudo",
            (
                "/usr/sbin/runuser",
                "--user",
                "abhaile",
                "--",
                "/usr/bin/sudo",
                "-n",
                "--",
                *exact_launcher,
            ),
        ),
    )
