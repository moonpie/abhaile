"""Unit tests for protected render launcher construction."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.git import CommandResult
from abhaile.trust.launcher import main, protected_render
from abhaile.trust.model import TrustPaths, TrustPolicy


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

    monkeypatch.setattr("abhaile.trust.launcher.subprocess.run", run)
    policy = TrustPolicy(
        "remote",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid(),
        render_python=runtime,
        render_runtime_root=runtime.parent,
    )
    protected_render(source, output, "deimos", policy)

    command, cwd, env = commands[0]
    assert command[4] == str(runtime)
    assert command[5:7] == ("-I", "-c")
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
        render_python=runtime,
        render_runtime_root=runtime_root,
    )
    with pytest.raises(TrustError, match="root is not traversable"):
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
