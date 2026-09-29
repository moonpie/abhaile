"""Observe fixed active-unit metadata through fixture-only injected transport."""

from __future__ import annotations

from enum import Enum

from abhaile.trust.discovery import DiscoveryCommandRunner, Observation
from abhaile.trust.errors import TrustError
from abhaile.trust.runtime import (
    AccountIdentity,
    RootlessPrerequisites,
    rootless_environment,
    rootless_transport,
)


class ActiveProbe(str, Enum):
    """Identify closed active-runtime queries rather than caller-selected units."""

    USER_MANAGER = "user-manager"
    SYSTEM_RUNNER = "system-runner"
    USER_VAULT_AGENT = "user-vault-agent"
    ROOTLESS_PODMAN = "rootless-podman"


class ActiveObservationBlocker(str, Enum):
    """Expose closed capability failures separately from transient host evidence."""

    PODMAN_TRANSPORT_UNPROVEN = "non-initializing Podman transport is not established"


def active_probe_blocker(probe: ActiveProbe) -> ActiveObservationBlocker | None:
    """Report terminal transport limitations without inspecting any host resource.

    Existing storage, a user manager, or a listening API socket cannot prove that
    a Podman query avoids runtime refresh, storage changes, or socket activation.
    No local CLI, API connection, retry, or initialization fallback is permitted
    until a fixed transport has independent non-mutation evidence. This is a
    capability limitation, not evidence that containers or storage are absent.
    """
    if probe is ActiveProbe.ROOTLESS_PODMAN:
        return ActiveObservationBlocker.PODMAN_TRANSPORT_UNPROVEN
    return None


_PROPERTIES = "Id,LoadState,ActiveState,SubState,FragmentPath,SourcePath,UnitFileState"
_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


class ActiveDiscoveryBackend:
    """Accept only fixed injected queries; provide no production command runner."""

    def __init__(
        self,
        runner: DiscoveryCommandRunner,
        account: AccountIdentity,
        prerequisites: RootlessPrerequisites,
    ) -> None:
        self.runner = runner
        self.account = account
        self.prerequisites = prerequisites

    def observe(self, probe: ActiveProbe) -> Observation:
        """Return sanitized conformance, never raw unit properties or error output."""
        if not isinstance(probe, ActiveProbe):
            return _unavailable()
        blocker = active_probe_blocker(probe)
        if blocker is not None:
            return Observation(
                False,
                None,
                None,
                blocker.value,
                f"fixed-active-catalog:{blocker.name.lower()}",
                False,
            )
        user = probe is ActiveProbe.USER_VAULT_AGENT
        unit = {
            ActiveProbe.USER_MANAGER: f"user@{self.account.uid}.service",
            ActiveProbe.SYSTEM_RUNNER: "abhaile-runner.service",
            ActiveProbe.USER_VAULT_AGENT: "vault-agent.service",
        }[probe]
        command = (
            "/usr/bin/systemctl",
            *(("--user",) if user else ()),
            "--no-pager",
            "show",
            f"--property={_PROPERTIES}",
            "--",
            unit,
        )
        try:
            env = rootless_environment(self.account, self.prerequisites) if user else dict(_ENV)
            if user:
                command = rootless_transport(self.account) + command
            result = self.runner(command, env=env, timeout=5.0, max_output=65536)
            if (
                result.returncode != 0
                or result.stderr
                or result.truncated
                or len(result.stdout.encode("utf-8")) > 65536
            ):
                return _unavailable()
            return _parse_unit(result.stdout, unit, probe, self.account)
        except (OSError, ValueError, TimeoutError, TrustError):
            return _unavailable()


def _parse_unit(
    output: str, unit: str, probe: ActiveProbe, account: AccountIdentity
) -> Observation:
    """Require exact property names, identity, enum states, and generated provenance."""
    fields: dict[str, str] = {}
    for line in output.splitlines():
        name, sep, value = line.partition("=")
        if not sep or name in fields or name not in _PROPERTIES.split(","):
            return _unavailable()
        fields[name] = value
    if set(fields) != set(_PROPERTIES.split(",")) or fields["Id"] != unit:
        return _unavailable()
    if fields["LoadState"] == "not-found":
        if (
            fields["ActiveState"] != "inactive"
            or fields["SubState"] != "dead"
            or any(fields[key] for key in ("FragmentPath", "SourcePath", "UnitFileState"))
        ):
            return _unavailable()
        return Observation(True, False, True, "fixed unit absent", "fixed-active-catalog")
    if fields["LoadState"] != "loaded":
        return _unavailable()
    valid_states = {
        ("active", "running"),
        ("active", "exited"),
        ("inactive", "dead"),
        ("failed", "failed"),
    }
    if (fields["ActiveState"], fields["SubState"]) not in valid_states:
        return _unavailable()
    if probe is ActiveProbe.USER_VAULT_AGENT:
        matches = (
            fields["SourcePath"]
            == f"{account.home}/.config/containers/systemd/vault-agent.container"
            and fields["FragmentPath"]
            == f"/run/user/{account.uid}/systemd/generator/vault-agent.service"
            and fields["UnitFileState"] == "generated"
        )
    else:
        expected_fragment = (
            "/usr/lib/systemd/system/user@.service"
            if probe is ActiveProbe.USER_MANAGER
            else "/etc/systemd/system/abhaile-runner.service"
        )
        matches = (
            fields["FragmentPath"] == expected_fragment
            and not fields["SourcePath"]
            and fields["UnitFileState"] in {"static", "enabled", "disabled"}
        )
    allowed_states = {"active", "inactive"} if probe is ActiveProbe.SYSTEM_RUNNER else {"active"}
    matches = matches and fields["ActiveState"] in allowed_states
    return Observation(True, True, matches, "fixed unit observed", "fixed-active-catalog")


def _unavailable() -> Observation:
    """Suppress all raw transport failures and malformed property content."""
    return Observation(
        False, None, None, "active evidence unavailable", "fixed-active-catalog", False
    )
