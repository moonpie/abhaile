"""Test bounded injected active-unit observation, never a live manager."""

from dataclasses import replace

import pytest

from abhaile.trust.active_discovery import ActiveDiscoveryBackend, ActiveProbe
from abhaile.trust.discovery import DiscoveryCommandResult
from abhaile.trust.runtime import (
    AccountIdentity,
    RootlessPrerequisites,
    RuntimeKind,
    RuntimeMetadata,
)


def setup_backend(output):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if isinstance(output, Exception):
            raise output
        return output

    account = AccountIdentity(1001, 1001, "/home/abhaile", "/bin/bash")
    facts = RootlessPrerequisites(
        True,
        True,
        True,
        RuntimeMetadata(True, RuntimeKind.DIRECTORY, 1001, 0o700),
        RuntimeMetadata(True, RuntimeKind.SOCKET, 1001, 0o666),
    )
    return ActiveDiscoveryBackend(runner, account, facts), calls


def vault_output():
    return (
        "Id=vault-agent.service\nLoadState=loaded\nActiveState=active\nSubState=running\n"
        "FragmentPath=/run/user/1001/systemd/generator/vault-agent.service\n"
        "SourcePath=/home/abhaile/.config/containers/systemd/vault-agent.container\n"
        "UnitFileState=generated\n"
    )


def test_user_quadlet_uses_existing_runtime_and_closed_privilege_drop():
    backend, calls = setup_backend(DiscoveryCommandResult(0, vault_output()))
    observation = backend.observe(ActiveProbe.USER_VAULT_AGENT)
    assert observation.present and observation.matches_expected
    command, kwargs = calls[0]
    assert command[0] == "/usr/bin/setpriv"
    assert "--user" in command and "show" in command
    assert kwargs["timeout"] == 5.0 and kwargs["max_output"] == 65536
    assert kwargs["env"]["HOME"] == "/home/abhaile"
    assert not any(word in command for word in ("start", "enable", "daemon-reload", "runuser"))


@pytest.mark.parametrize(
    "probe,unit,fragment",
    [
        (
            ActiveProbe.SYSTEM_RUNNER,
            "abhaile-runner.service",
            "/etc/systemd/system/abhaile-runner.service",
        ),
        (ActiveProbe.USER_MANAGER, "user@1001.service", "/usr/lib/systemd/system/user@.service"),
    ],
)
def test_system_queries_do_not_enter_user_manager(probe, unit, fragment):
    output = f"Id={unit}\nLoadState=loaded\nActiveState=active\nSubState=running\nFragmentPath={fragment}\nSourcePath=\nUnitFileState=static\n"
    backend, calls = setup_backend(DiscoveryCommandResult(0, output))
    assert backend.observe(probe).matches_expected
    assert calls[0][0][0] == "/usr/bin/systemctl"
    assert "--user" not in calls[0][0]
    assert "HOME" not in calls[0][1]["env"]


@pytest.mark.parametrize(
    "output",
    [
        DiscoveryCommandResult(1, "secret-marker", "secret-marker"),
        DiscoveryCommandResult(0, "secret-marker"),
        DiscoveryCommandResult(0, vault_output(), truncated=True),
        DiscoveryCommandResult(0, "x" * 65537),
        DiscoveryCommandResult(0, vault_output() + "Id=secret-marker\n"),
        DiscoveryCommandResult(0, vault_output().replace("Id=vault-agent", "Id=other")),
        DiscoveryCommandResult(0, vault_output().replace("LoadState=loaded", "LoadState=error")),
        DiscoveryCommandResult(0, vault_output().replace("SubState=running", "SubState=bad")),
        TimeoutError("secret-marker"),
    ],
)
def test_ambiguous_or_failed_unit_evidence_is_sanitized(output):
    backend, _ = setup_backend(output)
    observed = backend.observe(ActiveProbe.USER_VAULT_AGENT)
    assert not observed.valid
    assert "secret-marker" not in repr(observed)


@pytest.mark.parametrize(
    "old,new",
    [
        ("/run/user/1001", "/run/user/1002"),
        ("vault-agent.container", "other.container"),
        ("UnitFileState=generated", "UnitFileState=enabled"),
        ("ActiveState=active\nSubState=running", "ActiveState=inactive\nSubState=dead"),
    ],
)
def test_loaded_but_mismatched_unit_is_present_conflict(old, new):
    backend, _ = setup_backend(DiscoveryCommandResult(0, vault_output().replace(old, new)))
    observed = backend.observe(ActiveProbe.USER_VAULT_AGENT)
    assert observed.present and observed.matches_expected is False


def test_missing_runtime_prevents_command_execution():
    backend, calls = setup_backend(DiscoveryCommandResult(0, vault_output()))
    backend.prerequisites = replace(backend.prerequisites, manager_active=False)
    assert not backend.observe(ActiveProbe.USER_VAULT_AGENT).valid
    assert not calls


def test_podman_transport_remains_blocked_without_touching_storage_or_socket():
    backend, calls = setup_backend(DiscoveryCommandResult(0))
    observation = backend.observe(ActiveProbe.ROOTLESS_PODMAN)
    assert not observation.valid
    assert "transport is not established" in observation.reason
    assert not calls


def test_unknown_probe_cannot_choose_command():
    backend, calls = setup_backend(DiscoveryCommandResult(0))
    assert not backend.observe("caller-choice").valid
    assert not calls


@pytest.mark.parametrize("source,valid", [("", True), ("secret-marker", False)])
def test_missing_unit_requires_unambiguous_evidence(source, valid):
    output = (
        "Id=vault-agent.service\nLoadState=not-found\nActiveState=inactive\nSubState=dead\n"
        f"FragmentPath=\nSourcePath={source}\nUnitFileState=\n"
    )
    backend, _ = setup_backend(DiscoveryCommandResult(0, output))
    observation = backend.observe(ActiveProbe.USER_VAULT_AGENT)
    assert observation.valid is valid
    if valid:
        assert observation.present is False and observation.matches_expected


def test_idle_timer_driven_runner_is_not_incorrect_runtime_state():
    output = (
        "Id=abhaile-runner.service\nLoadState=loaded\nActiveState=inactive\nSubState=dead\n"
        "FragmentPath=/etc/systemd/system/abhaile-runner.service\nSourcePath=\nUnitFileState=static\n"
    )
    backend, _ = setup_backend(DiscoveryCommandResult(0, output))
    observation = backend.observe(ActiveProbe.SYSTEM_RUNNER)
    assert observation.present and observation.matches_expected


def test_podman_capability_is_explicit_and_other_unit_probes_remain_available():
    from abhaile.trust.active_discovery import ActiveObservationBlocker, active_probe_blocker

    assert active_probe_blocker(ActiveProbe.ROOTLESS_PODMAN) is (
        ActiveObservationBlocker.PODMAN_TRANSPORT_UNPROVEN
    )
    for probe in (
        ActiveProbe.USER_MANAGER,
        ActiveProbe.SYSTEM_RUNNER,
        ActiveProbe.USER_VAULT_AGENT,
    ):
        assert active_probe_blocker(probe) is None


@pytest.mark.parametrize("runtime_ready", [True, False])
def test_podman_terminal_blocker_has_no_io_or_initialization_fallback(monkeypatch, runtime_ready):
    import builtins
    import os
    from pathlib import Path
    import socket
    import subprocess

    from abhaile.trust.discovery import Classification, Probe, ProbeKind, discover_typed_host

    backend, calls = setup_backend(DiscoveryCommandResult(0, "PLACEHOLDER_SECRET_PODMAN"))
    if not runtime_ready:
        backend.prerequisites = replace(backend.prerequisites, manager_active=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Terminal Podman observation must not perform I/O")

    class Adapter:
        def observe(self, probe):
            assert probe.kind is ProbeKind.RUNTIME
            return backend.observe(ActiveProbe.ROOTLESS_PODMAN)

    # Fully ready metadata is deliberately insufficient to lift the blocker.
    # Patch possible I/O surfaces only around the request, never pytest internals.
    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, "open", forbidden)
        isolated.setattr(os, "open", forbidden)
        isolated.setattr(Path, "stat", forbidden)
        isolated.setattr(Path, "lstat", forbidden)
        isolated.setattr(socket, "socket", forbidden)
        isolated.setattr(subprocess, "run", forbidden)
        isolated.setattr(subprocess, "Popen", forbidden)
        first = backend.observe(ActiveProbe.ROOTLESS_PODMAN)
        second = backend.observe(ActiveProbe.ROOTLESS_PODMAN)
        record = discover_typed_host(
            [Probe("rootless Podman", ProbeKind.RUNTIME, "runtime:podman")], Adapter()
        )[0]

    assert first == second
    assert not first.available and not first.valid
    assert first.present is None and first.matches_expected is None
    assert first.provenance == "fixed-active-catalog:podman_transport_unproven"
    assert record.classification is Classification.CONFLICT
    assert "PLACEHOLDER_SECRET_PODMAN" not in repr(first) + repr(record)
    assert not calls
