"""Exercise rootless enrollment preconditions and user-manager activation in isolation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(rendered: Path, user: str, *, kind: str = "quadlet.container") -> dict:
    """Write a candidate Quadlet and its canonical manifest identity."""
    suffix = kind.split(".")[1]
    source = rendered / f"services/example/example.{suffix}"
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b"[Container]\nImage=example.invalid/test:1\n"
    source.write_bytes(content)
    return {
        "render_path": str(source.relative_to(rendered)),
        "target_path": f"/home/{user}/.config/containers/systemd/example.{suffix}",
        "kind": kind,
        "owner_ref": "unit:example.service",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "apply_hints": {"rootless": True, "podman_user": user},
    }


def _run(
    tmp_path: Path,
    variables: dict,
    *,
    check: bool = False,
    activate: bool = False,
    cleanup: bool = False,
    build: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated production role entry point without host lifecycle actions."""
    tmp_path.mkdir()
    play = tmp_path / "play.yml"
    play.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": variables,
                    "tasks": [
                        {
                            "ansible.builtin.include_role": {
                                "name": "rootless_quadlets",
                                "tasks_from": (
                                    "cleanup_user"
                                    if cleanup
                                    else "build" if build else "activate" if activate else "main"
                                ),
                            }
                        }
                    ],
                }
            ],
            sort_keys=False,
        )
    )
    env = tmp_path / "env"
    env.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    arguments.append(str(play))
    environment = _closed_environment(env)
    environment["ANSIBLE_NO_LOG"] = "False"
    return _ansible("ansible.cli.playbook", arguments, environment, timeout=60)


@pytest.mark.integration
@pytest.mark.parametrize("check", [False, True])
def test_missing_rootless_account_is_pending_only_in_check_mode(
    tmp_path: Path, check: bool
) -> None:
    """A missing declared account cannot be mistaken for live enrollment success."""
    user = "abhaile-test-user-not-created"
    with pytest.raises(KeyError):
        pwd.getpwnam(user)
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, user)
    result = _run(
        tmp_path / "run",
        {
            "abhaile_rootless_quadlet_entries": [entry],
            "abhaile_rendered_root": str(rendered),
            "abhaile_defer_activation": True,
        },
        check=check,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "pending declared account provisioning" in result.stdout
        assert "changed=0" in result.stdout
    else:
        assert result.returncode != 0
        assert "must be provisioned before live enrollment" in result.stdout


@pytest.mark.integration
def test_rootless_role_rejects_forged_source_before_identity_resolution(tmp_path: Path) -> None:
    """Reject a changed candidate rather than planning its publication."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, "abhaile-test-user-not-created")
    entry["sha256"] = "0" * 64
    result = _run(
        tmp_path / "run",
        {
            "abhaile_rootless_quadlet_entries": [entry],
            "abhaile_rendered_root": str(rendered),
        },
        check=True,
    )
    assert result.returncode != 0
    assert "Rendered source does not match manifest identity" in result.stdout


@pytest.mark.integration
def test_manual_rootless_members_require_a_pod_in_their_user_context(tmp_path: Path) -> None:
    """Reject manual members without an explicit selected parent even during check mode."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, "abhaile-test-user-not-created")
    entry["apply_hints"]["restart_mode"] = "manual"
    result = _run(
        tmp_path / "run",
        {
            "abhaile_rootless_quadlet_entries": [entry],
            "abhaile_rendered_root": str(rendered),
            "abhaile_rootful_quadlet_owners": {entry["owner_ref"]: {"requires": []}},
        },
        check=True,
    )
    assert result.returncode != 0
    assert "exactly one pod in the same user context" in result.stdout


def _systemctl_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Provide an isolated manager analogue recording per-user calls and activity."""
    binary = tmp_path / "systemctl-fixture"
    calls = tmp_path / "calls.jsonl"
    state = tmp_path / "state.json"
    binary.write_text(
        "#!/usr/bin/python3\n"
        "import json, pathlib, sys\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        f"state_path = pathlib.Path({str(state)!r})\n"
        "args = sys.argv[1:]\n"
        "with calls.open('a') as stream: stream.write(json.dumps(args) + '\\n')\n"
        "state = json.loads(state_path.read_text()) if state_path.exists() else {}\n"
        "user = args[args.index('-M') + 1]\n"
        "verb = args[args.index('-M') + 2]\n"
        "if verb == 'show': print('loaded')\n"
        "elif verb == 'is-active': sys.exit(0 if state.get(user + args[-1]) else 3)\n"
        "elif verb in ('start', 'restart'):\n"
        "    state[user + args[-1]] = True\n"
        "    state_path.write_text(json.dumps(state))\n"
    )
    binary.chmod(0o755)
    return binary, calls


@pytest.mark.integration
def test_rootless_activation_is_per_user_and_idempotent(tmp_path: Path) -> None:
    """Start absent workloads in the selected manager, then keep an unchanged workload running."""
    binary, calls = _systemctl_fixture(tmp_path)
    entry = {"owner_ref": "unit:example.service", "kind": "quadlet.container", "apply_hints": {}}
    variables = {
        "abhaile_systemctl_binary": str(binary),
        "abhaile_rootless_contexts": {"alice": {"entries": [entry]}},
        "abhaile_rootless_publications": {"alice": [{"item": entry, "changed": False}]},
    }
    first = _run(tmp_path / "first", variables, activate=True)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "changed=1" in first.stdout
    second = _run(tmp_path / "second", variables, activate=True)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "changed=0" in second.stdout
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert all(call[:3] == ["--user", "-M", "alice@"] for call in invocations)
    assert not any("restart" in call for call in invocations)


@pytest.mark.integration
def test_changed_manual_rootless_member_restarts_parent_pod(tmp_path: Path) -> None:
    """Refresh a pod once instead of starting its manual member independently."""
    binary, calls = _systemctl_fixture(tmp_path)
    pod = {"owner_ref": "unit:app-pod.service", "kind": "quadlet.pod", "apply_hints": {}}
    member = {
        "owner_ref": "unit:app-member.service",
        "kind": "quadlet.container",
        "apply_hints": {"restart_mode": "manual"},
    }
    variables = {
        "abhaile_systemctl_binary": str(binary),
        "abhaile_rootful_quadlet_owners": {member["owner_ref"]: {"requires": [pod["owner_ref"]]}},
        "abhaile_rootless_contexts": {"alice": {"entries": [pod, member]}},
        "abhaile_rootless_publications": {
            "alice": [
                {"item": pod, "changed": False},
                {"item": member, "changed": True},
            ]
        },
    }
    # The manager fixture treats a running pod's manual member as active too.
    (tmp_path / "state.json").write_text(json.dumps({"alice@app-member.service": True}))
    result = _run(tmp_path / "run", variables, activate=True)
    assert result.returncode == 0, result.stdout + result.stderr
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert ["--user", "-M", "alice@", "restart", "app-pod.service"] in invocations
    assert not any(call[-1] == "app-member.service" and "restart" in call for call in invocations)


@pytest.mark.integration
def test_rootless_config_only_change_refreshes_selected_user_workload(tmp_path: Path) -> None:
    """Refresh a queued rootless owner even when its Quadlet bytes did not change."""
    binary, calls = _systemctl_fixture(tmp_path)
    entry = {"owner_ref": "unit:example.service", "kind": "quadlet.container", "apply_hints": {}}
    variables = {
        "abhaile_systemctl_binary": str(binary),
        "abhaile_rootless_contexts": {"alice": {"entries": [entry]}},
        "abhaile_rootless_publications": {"alice": [{"item": entry, "changed": False}]},
        "abhaile_service_config_restarts": [
            {
                "rootless": True,
                "podman_user": "alice",
                "restart_unit": "example.service",
            }
        ],
    }
    result = _run(tmp_path / "run", variables, activate=True)
    assert result.returncode == 0, result.stdout + result.stderr
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert ["--user", "-M", "alice@", "restart", "example.service"] in invocations


@pytest.mark.integration
@pytest.mark.parametrize("matching", [True, False])
def test_rootless_cleanup_preserves_data_and_refuses_changed_unit_files(
    tmp_path: Path, matching: bool
) -> None:
    """Remove a matching candidate file only, or fail before stopping changed candidates."""
    binary, calls = _systemctl_fixture(tmp_path)
    target = tmp_path / "example.container"
    content = b"[Container]\nImage=example.invalid/test:1\n"
    target.write_bytes(content if matching else b"operator change\n")
    data = tmp_path / "data"
    data.mkdir()
    (data / "database").write_bytes(b"application state")
    entry = {
        "target_path": str(target),
        "owner_ref": "unit:example.service",
        "kind": "quadlet.container",
        "candidate_sha256": hashlib.sha256(content).hexdigest(),
    }
    result = _run(
        tmp_path / "run",
        {
            "abhaile_systemctl_binary": str(binary),
            "abhaile_rootless_user": "alice",
            "abhaile_rootless_context": {"cleanup": [entry]},
        },
        cleanup=True,
    )
    if matching:
        assert result.returncode == 0, result.stdout + result.stderr
        assert not target.exists()
        invocations = [json.loads(line) for line in calls.read_text().splitlines()]
        assert ["--user", "-M", "alice@", "stop", "example.service"] in invocations
    else:
        assert result.returncode != 0
        assert target.read_bytes() == b"operator change\n"
        assert not calls.exists()
    assert (data / "database").read_bytes() == b"application state"


@pytest.mark.integration
def test_rootless_cleanup_does_not_stop_volume_units(tmp_path: Path) -> None:
    """Leave native volume objects untouched when removing candidate-only definition files."""
    binary, calls = _systemctl_fixture(tmp_path)
    target = tmp_path / "example.volume"
    target.write_bytes(b"[Volume]\n")
    entry = {
        "target_path": str(target),
        "owner_ref": "unit:example-volume.service",
        "kind": "quadlet.volume",
        "candidate_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    result = _run(
        tmp_path / "run",
        {
            "abhaile_systemctl_binary": str(binary),
            "abhaile_rootless_user": "alice",
            "abhaile_rootless_context": {"cleanup": [entry]},
        },
        cleanup=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not target.exists()
    assert not calls.exists()


@pytest.mark.integration
def test_rootless_managed_build_creates_missing_image_before_consumers(tmp_path: Path) -> None:
    """Run a missing-image build in its user context and verify output before returning."""
    binary, calls = _systemctl_fixture(tmp_path)
    user = pwd.getpwuid(os.getuid()).pw_name
    podman = tmp_path / "podman-fixture"
    podman.write_text(
        "#!/usr/bin/python3\n"
        "import json, pathlib, sys\n"
        f"state_path = pathlib.Path({str(tmp_path / 'state.json')!r})\n"
        "state = json.loads(state_path.read_text()) if state_path.exists() else {}\n"
        f"sys.exit(0 if state.get({user + '@example-build.service'!r}) else 1)\n"
    )
    podman.chmod(0o755)
    entry = {
        "owner_ref": "unit:example-build.service",
        "apply_hints": {
            "managed_build": {
                "service": "example",
                "output_image": "localhost/example:1",
                "consumers": ["example.service"],
            }
        },
    }
    result = _run(
        tmp_path / "run",
        {
            "abhaile_systemctl_binary": str(binary),
            "abhaile_podman_binary": str(podman),
            "abhaile_rootless_user": user,
            "abhaile_rootless_context": {"home": str(tmp_path), "uid": str(os.getuid())},
            "abhaile_rootless_current_identity": {"stdout": str(os.getuid())},
            "abhaile_rootless_build": {"item": entry, "changed": False},
        },
        build=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert invocations == [["--user", "-M", user + "@", "restart", "example-build.service"]]
