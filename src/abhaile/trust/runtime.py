"""Define rootless prerequisites without inspecting or changing host state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from abhaile.trust.errors import TrustError


@dataclass(frozen=True)
class AccountIdentity:
    """Carry canonical composed account intent, never inferred host defaults."""

    uid: int
    gid: int
    home: str
    shell: str
    name: str = "abhaile"

    def __post_init__(self) -> None:
        """Reject unsupported service identities before building any command."""
        if (
            type(self.uid) is not int
            or type(self.gid) is not int
            or not 0 < self.uid < 2**32 - 1
            or not 0 < self.gid < 2**32 - 1
            or self.home != f"/home/{self.name}"
            or not self.name.replace("_", "a").replace("-", "a").isalnum()
            or self.shell not in {"/bin/bash", "/usr/sbin/nologin", "/bin/false"}
        ):
            raise TrustError("Rootless account intent is invalid")


class RuntimeKind(str, Enum):
    """Enumerate prerequisite inode types without reading contents."""

    DIRECTORY = "directory"
    SOCKET = "socket"


@dataclass(frozen=True)
class RuntimeMetadata:
    """Hold injected no-follow metadata bound to the fixed runtime or bus path."""

    present: bool
    kind: RuntimeKind | None
    uid: int | None
    mode: int | None
    valid: bool = True


@dataclass(frozen=True)
class RootlessPrerequisites:
    """Separate observed account and runtime facts from desired account intent."""

    identity_matches: bool
    linger: bool
    manager_active: bool
    runtime: RuntimeMetadata
    bus: RuntimeMetadata


def rootless_environment(
    account: AccountIdentity, prerequisites: RootlessPrerequisites
) -> dict[str, str]:
    """Build a closed environment only for an already-existing rootless runtime."""
    runtime, bus = prerequisites.runtime, prerequisites.bus
    if not (
        prerequisites.identity_matches is True
        and prerequisites.linger is True
        and prerequisites.manager_active is True
        and runtime.valid is True
        and runtime.present is True
        and runtime.kind is RuntimeKind.DIRECTORY
        and runtime.uid == account.uid
        and runtime.mode == 0o700
        and bus.valid is True
        and bus.present is True
        and bus.kind is RuntimeKind.SOCKET
        and bus.uid == account.uid
        and bus.mode is not None
        and 0 <= bus.mode <= 0o777
    ):
        raise TrustError("Rootless observation prerequisites are unavailable or conflicting")
    runtime_path = f"/run/user/{account.uid}"
    return {
        "HOME": account.home,
        "USER": account.name,
        "LOGNAME": account.name,
        "XDG_RUNTIME_DIR": runtime_path,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_path}/bus",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def rootless_transport(account: AccountIdentity) -> tuple[str, ...]:
    """Describe a PAM-free identity drop, with no shell or manager initialization."""
    return (
        "/usr/bin/setpriv",
        f"--reuid={account.uid}",
        f"--regid={account.gid}",
        "--clear-groups",
        "--no-new-privs",
        "--",
    )
