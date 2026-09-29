"""Test rootless planning without host observation or runtime initialization."""

from dataclasses import replace

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.runtime import (
    AccountIdentity,
    RootlessPrerequisites,
    RuntimeKind,
    RuntimeMetadata,
    rootless_environment,
    rootless_transport,
)


@pytest.fixture
def account():
    return AccountIdentity(1001, 1001, "/home/abhaile", "/bin/bash")


@pytest.fixture
def prerequisites():
    return RootlessPrerequisites(
        True,
        True,
        True,
        RuntimeMetadata(True, RuntimeKind.DIRECTORY, 1001, 0o700),
        RuntimeMetadata(True, RuntimeKind.SOCKET, 1001, 0o666),
    )


def test_environment_is_closed_and_identity_drop_is_pam_free(monkeypatch, account, prerequisites):
    monkeypatch.setenv("PYTHONPATH", "secret-marker")
    env = rootless_environment(account, prerequisites)
    assert env["HOME"] == "/home/abhaile"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1001"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1001/bus"
    assert "PYTHONPATH" not in env
    assert rootless_transport(account) == (
        "/usr/bin/setpriv",
        "--reuid=1001",
        "--regid=1001",
        "--clear-groups",
        "--no-new-privs",
        "--",
    )


@pytest.mark.parametrize("field", ["identity_matches", "linger", "manager_active"])
def test_missing_prerequisite_fails_closed(account, prerequisites, field):
    with pytest.raises(TrustError):
        rootless_environment(account, replace(prerequisites, **{field: False}))


@pytest.mark.parametrize(
    "changes",
    [
        {"present": False},
        {"valid": False},
        {"kind": None},
        {"uid": 0},
        {"mode": 0o777},
        {"mode": None},
    ],
)
def test_runtime_requires_declared_owner_private_mode(account, prerequisites, changes):
    with pytest.raises(TrustError):
        rootless_environment(
            account, replace(prerequisites, runtime=replace(prerequisites.runtime, **changes))
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"present": False},
        {"valid": False},
        {"uid": 0},
        {"kind": None},
        {"mode": None},
    ],
)
def test_missing_or_wrong_bus_fails_closed(account, prerequisites, changes):
    with pytest.raises(TrustError):
        rootless_environment(
            account, replace(prerequisites, bus=replace(prerequisites.bus, **changes))
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"uid": 0},
        {"gid": -1},
        {"uid": True},
        {"home": "/tmp"},
        {"shell": "secret-marker"},
    ],
)
def test_invalid_account_intent_is_sanitized(account, changes):
    with pytest.raises(TrustError) as error:
        replace(account, **changes)
    assert "secret-marker" not in str(error.value)


@pytest.mark.parametrize("field", ["identity_matches", "linger", "manager_active"])
def test_truthy_strings_are_not_observation_evidence(account, prerequisites, field):
    with pytest.raises(TrustError):
        rootless_environment(account, replace(prerequisites, **{field: "false"}))
