"""Check lifecycle health for completed jobs and named-user workloads."""

import subprocess
from typing import Any

import pytest

from abhaile import health


@pytest.mark.parametrize(
    "kind,started,result,expected",
    [
        ("oneshot", "100", "success", True),
        ("oneshot", "0", "success", False),
        ("oneshot", "100", "exit-code", False),
        ("simple", "100", "success", False),
    ],
)
def test_inactive_unit_requires_a_successfully_executed_oneshot(
    monkeypatch: Any, kind: str, started: str, result: str, expected: bool
) -> None:
    def command(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[1] == "is-active":
            return subprocess.CompletedProcess(argv, 3, "inactive", "")
        return subprocess.CompletedProcess(
            argv,
            0,
            f"Type={kind}\nActiveState=inactive\nResult={result}\nExecMainStatus=0\nExecMainStartTimestampMonotonic={started}\n",
            "",
        )

    monkeypatch.setattr(health, "_command", command)
    manifest = {
        "entries": [
            {
                "kind": "systemd.unit",
                "owner_ref": "unit:setup.service",
                "apply_hints": {"activation_mode": "start"},
            }
        ]
    }
    assert (
        health._check_system_units(manifest, timeout_seconds=1, actionable=True)[0].success
        is expected
    )


def test_generic_rootless_health_selects_the_owning_manager(monkeypatch: Any) -> None:
    seen: list[list[str]] = []

    def command(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(health, "_command", command)
    manifest = {
        "entries": [
            {
                "kind": "quadlet.pod",
                "owner_ref": "unit:app-pod.service",
                "apply_hints": {"rootless": True, "podman_user": "runtime"},
            }
        ]
    }
    assert health._check_rootless_units(manifest, timeout_seconds=1)[0].success
    assert seen == [
        ["systemctl", "--user", "-M", "runtime@", "is-active", "--quiet", "app-pod.service"]
    ]
