"""Exercise the mutation task library only inside a fresh temporary root."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from abhaile.trust.convergence import build_convergence_plan
from abhaile.trust.convergence_engine import compile_ansible_operations

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "ansible/playbooks/converge.yml"


def _run(
    root: Path,
    operations: list[dict[str, object]],
    *,
    check: bool = False,
    authorized: bool = True,
    runtime_variables: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "ANSIBLE_ROLES_PATH": str(REPO_ROOT / "ansible/roles"),
        "ANSIBLE_LOCAL_TEMP": str(root / "tmp"),
        "ANSIBLE_REMOTE_TEMP": str(root / "tmp"),
        "ANSIBLE_NOCOLOR": "True",
        "ANSIBLE_NO_LOG": "True",
    }
    extra_variables: dict[str, object] = {
        "abhaile_capsule_verified": True,
        "abhaile_execution_scope": ("isolated-disposable-v1" if authorized else "disabled"),
        "abhaile_expected_host": "deimos",
        "abhaile_execution_root": str(root),
        "abhaile_rendered_root": str(root / "source"),
        "abhaile_manifest": str(root / "source/convergence-manifest.json"),
        "abhaile_operations": operations,
        "ansible_python_interpreter": sys.executable,
    }
    extra_variables.update(runtime_variables or {})
    arguments = [
        sys.executable,
        "-I",
        "-m",
        "ansible.cli.playbook",
        "-i",
        "localhost,",
        "--connection=local",
        "--extra-vars",
        json.dumps(extra_variables),
        str(PLAYBOOK),
    ]
    if check:
        arguments.append("--check")
    return subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _compiled_named_user_operations(
    root: Path,
    *,
    kind: str = "service.config",
    lifecycle: bool = False,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    """Compile a sealed named-user operation using the production compiler."""
    name = "isolateduser"
    context = f"user:{name}"
    identity: dict[str, object] = {
        "name": name,
        "uid": os.getuid(),
        "gid": os.getgid(),
        "home": f"/home/{name}",
        "shell": "/bin/bash",
    }
    if kind == "quadlet.container":
        render_path = "services/test/quadlets/test.container"
        target = f"/etc/containers/systemd/users/{os.getuid()}/test.container"
        validation = "quadlet"
        payload = b"[Container]\nImage=localhost/abhaile-isolated:test\n"
    else:
        render_path = "services/test/config"
        target = "/target/config"
        validation = "structural"
        payload = b"sealed-named-user-content\n"
    source = root / "source" / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)
    entry: dict[str, object] = {
        "owner_ref": "service:test",
        "render_path": render_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "target_path": target,
        "kind": kind,
        "action": "publish",
        "execution_context": context,
        "metadata": {"owner": str(os.getuid()), "group": str(os.getgid()), "mode": "0644"},
        "validation": validation,
        "lifecycle": ["manager-reload"] if lifecycle else [],
        "lifecycle_metadata": {"manager-reload": {}} if lifecycle else {},
    }
    manifest = {
        "schema_version": 2,
        "host": "deimos",
        "execution_identities": {context: identity},
        "owners": {"service:test": {"requires": []}},
        "entries": [entry],
    }
    operations = compile_ansible_operations(
        build_convergence_plan(manifest), manifest, root / "source"
    )
    observations: dict[str, dict[str, object]] = {
        context: {
            "identity": identity,
            "linger": True,
            "manager_active": True,
            "runtime_uid": os.getuid(),
            "runtime_mode": "0700",
            "bus_uid": os.getuid(),
        }
    }
    return [operation.ansible_value() for operation in operations], observations


@pytest.mark.integration
def test_compiler_named_user_quadlet_check_idempotence_and_lifecycle(tmp_path: Path) -> None:
    """Exercise compiler-produced rootless publication and lifecycle through the role."""
    root = tmp_path / "rootless"
    (root / "tmp").mkdir(parents=True)
    target = root / f"etc/containers/systemd/users/{os.getuid()}/test.container"
    target.parent.mkdir(parents=True)
    operations, observations = _compiled_named_user_operations(root, kind="quadlet.container")
    runtime = {
        "abhaile_rootless_observations_verified": True,
        "abhaile_rootless_observations": observations,
    }

    checked = _run(root, operations, check=True, runtime_variables=runtime)
    assert checked.returncode == 0, checked.stderr
    assert not target.exists()
    first = _run(root, operations, runtime_variables=runtime)
    assert first.returncode == 0, first.stderr
    assert target.read_text(encoding="utf-8").startswith("[Container]")
    second = _run(root, operations, runtime_variables=runtime)
    assert second.returncode == 0, second.stderr
    assert "changed=0" in second.stdout

    lifecycle_root = tmp_path / "rootless-lifecycle"
    (lifecycle_root / "tmp").mkdir(parents=True)
    lifecycle_target = lifecycle_root / f"etc/containers/systemd/users/{os.getuid()}/test.container"
    lifecycle_target.parent.mkdir(parents=True)
    lifecycle_operations, lifecycle_observations = _compiled_named_user_operations(
        lifecycle_root, kind="quadlet.container", lifecycle=True
    )
    assert [item["operation"] for item in lifecycle_operations] == ["publish", "lifecycle"]
    lifecycle_checked = _run(
        lifecycle_root,
        lifecycle_operations,
        check=True,
        runtime_variables={
            "abhaile_rootless_observations_verified": True,
            "abhaile_rootless_observations": lifecycle_observations,
        },
    )
    assert lifecycle_checked.returncode == 0, lifecycle_checked.stderr
    assert not lifecycle_target.exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    [
        "missing-observations",
        "unverified-observations",
        "malformed-observations",
        "contradictory-observations",
        "missing-identity",
        "false-identity",
        "unexpected-identity-authority",
        "cross-context-identity",
    ],
)
def test_compiler_named_user_authority_fails_before_mutation(tmp_path: Path, case: str) -> None:
    """Reject absent, malformed, contradictory, or unexpected identity authority."""
    root = tmp_path / case
    (root / "tmp").mkdir(parents=True)
    (root / "target").mkdir()
    operations, observations = _compiled_named_user_operations(root)
    runtime: dict[str, object] = {
        "abhaile_rootless_observations_verified": True,
        "abhaile_rootless_observations": observations,
    }
    if case == "missing-observations":
        runtime = {}
    elif case == "unverified-observations":
        runtime["abhaile_rootless_observations_verified"] = False
    elif case == "malformed-observations":
        runtime["abhaile_rootless_observations"] = {"user:isolateduser": False}
    elif case == "contradictory-observations":
        observations["user:isolateduser"]["runtime_uid"] = os.getuid() + 1
    elif case == "missing-identity":
        operations[0]["execution_identity"] = None
    elif case == "false-identity":
        operations[0]["execution_identity"] = False
    elif case == "unexpected-identity-authority":
        operations[0]["runtime_identity_required"] = True
    elif case == "cross-context-identity":
        operations[0]["context"] = "system"

    refused = _run(root, operations, runtime_variables=runtime)
    assert refused.returncode != 0
    assert not (root / "target/config").exists()
    assert "sealed-named-user-content" not in refused.stdout
    assert "sealed-named-user-content" not in refused.stderr


@pytest.mark.integration
def test_isolated_file_convergence_check_idempotence_and_escape(tmp_path: Path) -> None:
    """Prove check mode, unchanged rerun, and outside-root rejection."""
    root = tmp_path / "isolated"
    source = root / "source/config"
    target = root / "target/config"
    (root / "tmp").mkdir(parents=True)
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("safe\n", encoding="utf-8")
    operation: dict[str, object] = {
        "operation": "publish",
        "kind": "service.config",
        "action": "publish",
        "owner_ref": "system:test",
        "source": str(source),
        "source_sha256": hashlib.sha256(b"safe\n").hexdigest(),
        "target": "/target/config",
        "mode": "0644",
        "owner": str(os.getuid()),
        "group": str(os.getgid()),
        "context": "system",
        "validation": "structural",
        "lifecycle": [],
        "lifecycle_metadata": {},
        "execution_identity": None,
        "parameters": {},
        "effects": [],
        "no_log": True,
        "diff": False,
    }
    checked = _run(root, [operation], check=True)
    assert checked.returncode == 0, checked.stderr
    assert not target.exists()
    first = _run(root, [operation])
    assert first.returncode == 0, first.stderr
    assert target.read_text(encoding="utf-8") == "safe\n"
    second = _run(root, [operation])
    assert second.returncode == 0, second.stderr
    assert "changed=0" in second.stdout
    escaped = dict(operation, target="/../outside")
    refused = _run(root, [escaped])
    assert refused.returncode != 0
    assert not (tmp_path / "outside").exists()


@pytest.mark.integration
def test_isolated_harness_rejects_symlink_escape_and_root_target(tmp_path: Path) -> None:
    """Reject canonical-path escapes even when string prefixes appear confined."""
    root = tmp_path / "isolated"
    outside = tmp_path / "outside"
    (root / "tmp").mkdir(parents=True)
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    escaped: dict[str, object] = {
        "operation": "directory",
        "kind": "service.directory",
        "action": "create",
        "owner_ref": "system:test",
        "source": str(root / "source/directory"),
        "source_sha256": hashlib.sha256(b"").hexdigest(),
        "target": "/linked/managed",
        "mode": "0750",
        "owner": str(os.getuid()),
        "group": str(os.getgid()),
        "context": "system",
        "validation": "structural",
        "lifecycle": [],
        "lifecycle_metadata": {},
        "execution_identity": None,
        "parameters": {},
        "effects": [],
        "no_log": True,
        "diff": False,
    }
    (root / "source").mkdir()
    (root / "source/directory").mkdir()
    refused = _run(root, [escaped])
    assert refused.returncode != 0
    assert not (outside / "managed").exists()

    root_target = dict(escaped, target="/tmp/escaped", mode="0750")
    refused_root = _run(Path("/"), [root_target])
    assert refused_root.returncode != 0
    assert not Path("/tmp/escaped").exists()


@pytest.mark.integration
def test_production_role_rejects_missing_execution_gate(tmp_path: Path) -> None:
    """Keep the production role unreachable without its protected execution gate."""
    root = tmp_path / "isolated"
    source = root / "source/config"
    (root / "tmp").mkdir(parents=True)
    source.parent.mkdir(parents=True)
    source.write_text("safe\n", encoding="utf-8")
    operation: dict[str, object] = {
        "operation": "publish",
        "kind": "service.config",
        "action": "publish",
        "owner_ref": "system:test",
        "source": str(source),
        "source_sha256": hashlib.sha256(b"safe\n").hexdigest(),
        "target": "/target/config",
        "mode": "0644",
        "owner": str(os.getuid()),
        "group": str(os.getgid()),
        "context": "system",
        "validation": "structural",
        "lifecycle": [],
        "lifecycle_metadata": {},
        "execution_identity": None,
        "parameters": {},
        "effects": [],
        "no_log": True,
        "diff": False,
    }
    refused = _run(root, [operation], authorized=False)
    assert refused.returncode != 0
    assert not (root / "target/config").exists()


@pytest.mark.integration
def test_complete_preflight_prevents_earlier_mutation(tmp_path: Path) -> None:
    """Reject a malformed later operation before an earlier valid operation mutates."""
    root = tmp_path / "isolated"
    source = root / "source"
    (root / "tmp").mkdir(parents=True)
    source.mkdir()
    (source / "first").write_text("first\n", encoding="utf-8")
    (source / "second").write_text("second\n", encoding="utf-8")

    def operation(name: str, digest: str) -> dict[str, object]:
        return {
            "operation": "publish",
            "kind": "service.config",
            "action": "publish",
            "owner_ref": "system:test",
            "source": str(source / name),
            "source_sha256": digest,
            "target": f"/target/{name}",
            "mode": "0644",
            "owner": str(os.getuid()),
            "group": str(os.getgid()),
            "context": "system",
            "validation": "structural",
            "lifecycle": [],
            "lifecycle_metadata": {},
            "execution_identity": None,
            "parameters": {},
            "effects": [],
            "no_log": True,
            "diff": False,
        }

    first = operation("first", hashlib.sha256(b"first\n").hexdigest())
    invalid = operation("second", "0" * 64)
    refused = _run(root, [first, invalid])
    assert refused.returncode != 0
    assert not (root / "target/first").exists()


@pytest.mark.integration
def test_late_content_validator_failure_prevents_earlier_mutation(tmp_path: Path) -> None:
    """Run every sealed content validator before executing the first operation."""
    root = tmp_path / "isolated"
    source = root / "source"
    (root / "tmp").mkdir(parents=True)
    source.mkdir()
    (source / "first").write_text("first\n", encoding="utf-8")
    (source / "Caddyfile").write_text("example.test {\n shell /bin/sh\n}\n", encoding="utf-8")

    def operation(name: str, *, kind: str, validation: str) -> dict[str, object]:
        payload = (source / name).read_bytes()
        return {
            "operation": "publish",
            "kind": kind,
            "action": "publish",
            "owner_ref": "system:test",
            "source": str(source / name),
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "target": f"/target/{name}",
            "mode": "0644",
            "owner": str(os.getuid()),
            "group": str(os.getgid()),
            "context": "system",
            "validation": validation,
            "lifecycle": [],
            "lifecycle_metadata": {},
            "execution_identity": None,
            "parameters": {},
            "effects": [],
            "no_log": True,
            "diff": False,
        }

    refused = _run(
        root,
        [
            operation("first", kind="service.config", validation="structural"),
            operation("Caddyfile", kind="caddy.config", validation="caddy"),
        ],
    )
    assert refused.returncode != 0
    assert not (root / "target/first").exists()


@pytest.mark.integration
def test_unchanged_download_and_check_mode_do_not_acquire(tmp_path: Path) -> None:
    """Use protected local output identity before any unavailable network acquisition."""
    root = tmp_path / "isolated"
    source = root / "source/download.yaml"
    target = root / "usr/local/bin/tool"
    (root / "tmp").mkdir(parents=True)
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("sealed: true\n", encoding="utf-8")
    target.write_bytes(b"immutable tool")
    target.chmod(0o755)
    operation: dict[str, object] = {
        "operation": "binary-download",
        "kind": "software.download",
        "action": "fetch",
        "owner_ref": "software:tool",
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "target": None,
        "mode": "0755",
        "owner": str(os.getuid()),
        "group": str(os.getgid()),
        "context": "system",
        "validation": "software-result",
        "lifecycle": [],
        "lifecycle_metadata": {},
        "execution_identity": None,
        "parameters": {
            "url": "https://unavailable.invalid/tool",
            "sha256": hashlib.sha256(b"immutable tool").hexdigest(),
            "destination": "/usr/local/bin/tool",
            "mode": "0755",
            "max_bytes": 1024,
            "redirect_origins": [],
            "max_redirects": 0,
        },
        "effects": [{"kind": "path", "target": "/usr/local/bin/tool", "role": "primary"}],
        "no_log": True,
        "diff": False,
    }
    unchanged = _run(root, [operation])
    assert unchanged.returncode == 0, unchanged.stderr
    assert "changed=0" in unchanged.stdout
    target.unlink()
    preview = _run(root, [operation], check=True)
    assert preview.returncode == 0, preview.stderr
    assert not target.exists()
