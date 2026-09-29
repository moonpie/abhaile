"""Unit tests for protected render launcher construction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from abhaile.trust.containment import CgroupBoundary
from abhaile.trust.errors import TrustError
from abhaile.trust.git import CommandResult
from abhaile.trust.launcher import load_policy, main, protected_render
from abhaile.trust.model import TrustPaths, TrustPolicy


def test_load_policy_maps_fixed_split_namespaces_through_test_root(tmp_path: Path) -> None:
    """Keep production anchors fixed while allowing an isolated filesystem fixture."""
    etc = tmp_path / "etc/abhaile"
    etc.mkdir(parents=True)
    for name in ("known_hosts", "git-fetch-identity"):
        path = etc / name
        path.write_text("fixture", encoding="utf-8")
        path.chmod(0o600)
    policy_path = etc / "trust-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "paths": {
                    "mirror": "/var/lib/abhaile/mirror.git",
                    "staging": "/var/lib/abhaile/staging",
                    "quarantine": "/var/lib/abhaile/quarantine",
                    "capsules": "/var/lib/abhaile/capsules",
                    "active": "/var/lib/abhaile/active",
                    "known_hosts": "/etc/abhaile/known_hosts",
                    "fetch_identity": "/etc/abhaile/git-fetch-identity",
                },
                "remote_url": "ssh://git@example.invalid/repository",
                "branch": "main",
                "host": "deimos",
                "render_uid": os.geteuid() + 1,
                "render_gid": os.getegid() + 1,
                "known_host_pins": ["example.invalid ssh-ed25519 fixture"],
                "remote_host": "example.invalid",
            }
        ),
        encoding="utf-8",
    )
    policy_path.chmod(0o600)

    paths, policy = load_policy(policy_path, root_uid=os.geteuid(), filesystem_root=tmp_path)

    assert paths.mirror == tmp_path / "var/lib/abhaile/mirror.git"
    assert paths.known_hosts == etc / "known_hosts"
    assert policy.fetch_identity == etc / "git-fetch-identity"
    assert policy.render_runtime_root == tmp_path / "usr/lib/abhaile-render-runtime"


def test_load_policy_rejects_nonfixed_policy_path(tmp_path: Path) -> None:
    """Do not turn a caller-selected JSON file into privileged anchor policy."""
    path = tmp_path / "policy.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(TrustError, match="not fixed"):
        load_policy(path, root_uid=os.geteuid(), filesystem_root=tmp_path)


@pytest.mark.parametrize("uid,gid", [(0, 1), (1, 0), (-1, 1), (True, 1), (1, "2"), (2**32, 1)])
def test_load_policy_rejects_invalid_render_identity(
    tmp_path: Path, uid: object, gid: object
) -> None:
    """Reject malformed or privileged identities at the policy boundary."""
    etc = tmp_path / "etc/abhaile"
    etc.mkdir(parents=True)
    for name in ("known_hosts", "git-fetch-identity"):
        candidate = etc / name
        candidate.write_text("fixture", encoding="utf-8")
        candidate.chmod(0o600)
    policy_path = etc / "trust-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "paths": {
                    "mirror": "/var/lib/abhaile/mirror.git",
                    "staging": "/var/lib/abhaile/staging",
                    "quarantine": "/var/lib/abhaile/quarantine",
                    "capsules": "/var/lib/abhaile/capsules",
                    "active": "/var/lib/abhaile/active",
                    "known_hosts": "/etc/abhaile/known_hosts",
                    "fetch_identity": "/etc/abhaile/git-fetch-identity",
                },
                "remote_url": "ssh://git@example.invalid/repository",
                "branch": "main",
                "host": "deimos",
                "render_uid": uid,
                "render_gid": gid,
                "known_host_pins": ["example.invalid ssh-ed25519 fixture"],
                "remote_host": "example.invalid",
            }
        ),
        encoding="utf-8",
    )
    policy_path.chmod(0o600)
    with pytest.raises(TrustError, match="dedicated non-root"):
        load_policy(policy_path, root_uid=os.geteuid(), filesystem_root=tmp_path)


def test_protected_render_imports_selected_source_with_fixed_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bind renderer imports to sealed source without accepting a repository-root option."""
    source = tmp_path / "capsule" / "source"
    output = tmp_path / "capsule" / "rendered"
    source.joinpath("src").mkdir(parents=True)
    output.mkdir()
    runtime = tmp_path / "protected-runtime" / "python"
    runtime.parent.mkdir()
    runtime.write_text("test runtime placeholder", encoding="utf-8")
    runtime.chmod(0o555)
    commands: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def run(
        command: tuple[str, ...], *, cwd: Path, env: dict[str, str], check: bool
    ) -> CommandResult:
        assert check is False
        commands.append((command, cwd, env))
        return CommandResult(0)

    boundary = CgroupBoundary()
    monkeypatch.setattr(
        boundary, "run", lambda command, **kwargs: run(command, check=False, **kwargs)
    )
    policy = TrustPolicy(
        "remote",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid(),
        render_gid=os.getegid(),
        render_python=runtime,
        render_runtime_root=runtime.parent,
    )
    protected_render(source, output, "deimos", policy, boundary=boundary)

    command, cwd, env = commands[0]
    assert command[:6] == (
        "/usr/bin/setpriv",
        f"--reuid={os.geteuid()}",
        f"--regid={os.getegid()}",
        "--clear-groups",
        "--no-new-privs",
        "--",
    )
    assert command[6] == str(runtime)
    assert command[7:9] == ("-I", "-c")
    assert str(source / "src") in command
    assert "--repo-root" not in command
    assert command[-2:] == ("--output", str(output.parent))
    assert cwd == source
    assert env == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def test_protected_render_requires_runtime_executable_by_distinct_identity(
    tmp_path: Path,
) -> None:
    """Reject a root-only interpreter that the configured render identity cannot execute."""
    source = tmp_path / "capsule/source"
    output = tmp_path / "capsule/rendered"
    source.joinpath("src").mkdir(parents=True)
    output.mkdir()
    runtime_root = tmp_path / "runtime"
    runtime = runtime_root / "bin/python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("placeholder", encoding="utf-8")
    runtime.chmod(0o500)
    policy = TrustPolicy(
        "remote",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid() + 1000,
        render_gid=os.getegid() + 1000,
        render_python=runtime,
        render_runtime_root=runtime_root,
    )
    with pytest.raises(TrustError, match="not executable"):
        protected_render(source, output, "deimos", policy)


def test_protected_render_requires_traversable_runtime_root(tmp_path: Path) -> None:
    """Reject a protected runtime root inaccessible to the render identity."""
    source = tmp_path / "capsule/source"
    output = tmp_path / "capsule/rendered"
    source.joinpath("src").mkdir(parents=True)
    output.mkdir()
    runtime_root = tmp_path / "runtime"
    runtime = runtime_root / "bin/python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("placeholder", encoding="utf-8")
    runtime.chmod(0o555)
    runtime_root.chmod(0o700)
    policy = TrustPolicy(
        "remote",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid() + 1000,
        render_gid=os.getegid() + 1000,
        render_python=runtime,
        render_runtime_root=runtime_root,
    )
    with pytest.raises(TrustError, match="root is not traversable"):
        protected_render(source, output, "deimos", policy)


def test_protected_render_rejects_writable_runtime_dependency(tmp_path: Path) -> None:
    """Reject writable site hooks that could execute before cgroup attachment."""
    source = tmp_path / "capsule/source"
    output = tmp_path / "capsule/rendered"
    source.joinpath("src").mkdir(parents=True)
    output.mkdir()
    runtime_root = tmp_path / "runtime"
    runtime = runtime_root / "bin/python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("placeholder", encoding="utf-8")
    runtime.chmod(0o555)
    injection = runtime_root / "lib/python/site-packages/injection.pth"
    injection.parent.mkdir(parents=True)
    injection.write_text("import caller_controlled", encoding="utf-8")
    injection.chmod(0o666)
    policy = TrustPolicy(
        "remote",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid() + 1000,
        render_gid=os.getegid() + 1000,
        render_python=runtime,
        render_runtime_root=runtime_root,
    )
    with pytest.raises(TrustError, match="group/other writable"):
        protected_render(source, output, "deimos", policy)


def test_protected_render_rejects_lexical_runtime_escape(tmp_path: Path) -> None:
    """Reject an interpreter path containing traversal outside the protected runtime."""
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    policy = TrustPolicy(
        "remote",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid() + 1000,
        render_gid=os.getegid() + 1000,
        render_python=runtime_root / ".." / "elsewhere/python",
        render_runtime_root=runtime_root,
    )
    with pytest.raises(TrustError, match="escapes its runtime root"):
        protected_render(tmp_path / "source", tmp_path / "output", "deimos", policy)


def test_offline_launcher_never_fetches_and_prepares_selected_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the launcher boundary using only already-retained local trust state."""
    revision = "a" * 40
    paths = TrustPaths(
        tmp_path / "mirror.git",
        tmp_path / "staging",
        tmp_path / "quarantine",
        tmp_path / "capsules",
        tmp_path / "active",
        tmp_path / "known_hosts",
        tmp_path / "identity",
    )
    policy = TrustPolicy("remote", "main", "deimos", root_uid=os.geteuid())
    calls: list[tuple[str, object]] = []

    class Mirror:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def initialize(self) -> None:
            calls.append(("initialize", None))

        def fetch(self) -> None:
            raise AssertionError("offline launcher must not fetch")

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def prepare(self, selected: str, _render: object, *, mode: str) -> None:
            calls.append(("prepare", (selected, mode)))

    monkeypatch.setattr("abhaile.trust.launcher.os.geteuid", lambda: 0)
    monkeypatch.setattr("abhaile.trust.launcher.load_policy", lambda: (paths, policy))
    monkeypatch.setattr("abhaile.trust.launcher.TrustedMirror", Mirror)
    monkeypatch.setattr("abhaile.trust.launcher.CapsuleStore", Store)
    assert (
        main(
            [
                "--runner",
                "--host",
                "deimos",
                "--revision",
                revision,
                "--dry-run",
                "--offline",
            ]
        )
        == 0
    )
    assert calls == [("initialize", None), ("prepare", (revision, "dry-run"))]
