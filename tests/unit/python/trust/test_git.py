"""Unit tests for protected Git revision admission."""

from __future__ import annotations

import os
import subprocess
import tarfile
import threading
from pathlib import Path
from typing import Sequence

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.git import ACTIVE_REF, CommandResult, TrustedMirror
from abhaile.trust.model import TrustPolicy


def _run(*command: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path, TrustedMirror]:
    """Create an injectable remote, worktree, and protected bare mirror."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    protected = tmp_path / "protected"
    protected.mkdir(mode=0o700)
    known_hosts = protected / "known_hosts"
    known_hosts.write_text("github.example ssh-ed25519 AAAATESTPIN\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    _run("git", "init", "--bare", str(remote))
    _run("git", "init", str(work))
    _run("git", "checkout", "-b", "main", cwd=work)
    _run("git", "config", "user.email", "test@example.invalid", cwd=work)
    _run("git", "config", "user.name", "Test", cwd=work)
    (work / "data").write_text("one", encoding="utf-8")
    _run("git", "add", "data", cwd=work)
    _run("git", "commit", "-m", "one", cwd=work)
    _run("git", "remote", "add", "origin", str(remote), cwd=work)
    _run("git", "push", "origin", "main", cwd=work)
    identity = protected / "fetch-identity"
    identity.write_text("test-only-placeholder\n", encoding="utf-8")
    identity.chmod(0o600)
    policy = TrustPolicy(
        str(remote),
        "main",
        "deimos",
        root_uid=os.geteuid(),
        known_host_pins=("github.example ssh-ed25519 AAAATESTPIN",),
        fetch_identity=identity,
    )
    mirror = TrustedMirror(protected / "mirror.git", policy, known_hosts, allow_local_remote=True)
    mirror.initialize()
    return remote, work, mirror


def test_admits_only_full_reachable_commit(repositories: tuple[Path, Path, TrustedMirror]) -> None:
    """Reject abbreviated and unrelated revisions while admitting trusted history."""
    _remote, work, mirror = repositories
    trusted = mirror.fetch()
    assert mirror.admit(trusted) == trusted
    with pytest.raises(TrustError, match="full lowercase"):
        mirror.admit(trusted[:12])
    (work / "data").write_text("untrusted", encoding="utf-8")
    _run("git", "commit", "-am", "untrusted", cwd=work)
    untrusted = _run("git", "rev-parse", "HEAD", cwd=work)
    with pytest.raises(TrustError, match="not a commit"):
        mirror.admit(untrusted)


def test_rejects_non_fast_forward_without_approval(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Require explicit approval before rewriting the protected trusted ref."""
    _remote, work, mirror = repositories
    original = mirror.fetch()
    _run("git", "checkout", "--orphan", "replacement", cwd=work)
    (work / "data").write_text("replacement", encoding="utf-8")
    _run("git", "add", "data", cwd=work)
    _run("git", "commit", "-m", "replacement", cwd=work)
    _run("git", "push", "--force", "origin", "HEAD:main", cwd=work)
    with pytest.raises(TrustError, match="not fast-forward"):
        mirror.fetch()
    assert mirror.admit(original) == original
    replacement = mirror.fetch(approve_non_fast_forward=True)
    assert replacement != original


def test_last_known_good_remains_admitted_offline(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Retain the last-known-good revision without another fetch."""
    _remote, work, mirror = repositories
    old = mirror.fetch()
    mirror.mark_last_known_good(old)
    (work / "data").write_text("two", encoding="utf-8")
    _run("git", "commit", "-am", "two", cwd=work)
    _run("git", "push", "origin", "main", cwd=work)
    mirror.fetch()
    assert mirror.admit(old) == old
    assert mirror.last_known_good() == old


def test_fetch_requires_non_writable_pinned_hosts(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Reject an unprotected host-key policy before invoking fetch."""
    _remote, _work, mirror = repositories
    mirror.known_hosts.chmod(0o666)
    with pytest.raises(TrustError, match="writable"):
        mirror.fetch()


def test_fetch_rejects_host_key_content_not_in_policy(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Reject substituted host keys even when the file permissions are protected."""
    _remote, _work, mirror = repositories
    mirror.known_hosts.write_text("github.example ssh-ed25519 DIFFERENT\n", encoding="utf-8")
    with pytest.raises(TrustError, match="does not match protected policy"):
        mirror.fetch()


def test_fetch_rejects_trust_files_outside_mirror_anchor(
    repositories: tuple[Path, Path, TrustedMirror], tmp_path: Path
) -> None:
    """Keep SSH trust files beneath the same protected root as the mirror."""
    _remote, _work, mirror = repositories
    outside = tmp_path / "outside-known-hosts"
    outside.write_text("github.example ssh-ed25519 AAAATESTPIN\n", encoding="utf-8")
    outside.chmod(0o600)
    attacked = TrustedMirror(
        mirror.path,
        mirror.policy,
        outside,
        allow_local_remote=True,
    )
    with pytest.raises(TrustError, match="outside its trust anchor"):
        attacked.fetch()


def test_fetch_rejects_remote_outside_pinned_ssh_policy(tmp_path: Path) -> None:
    """Reject non-SSH and mismatched SSH endpoints before invoking Git."""
    protected = tmp_path / "var/lib/abhaile"
    protected.mkdir(parents=True, mode=0o700)
    trust = tmp_path / "etc/abhaile"
    trust.mkdir(parents=True)
    known_hosts = trust / "known_hosts"
    known_hosts.write_text("git.example ssh-ed25519 PIN\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    identity = trust / "identity"
    identity.write_text("placeholder\n", encoding="utf-8")
    identity.chmod(0o600)
    calls: list[tuple[str, ...]] = []

    def runner(
        command: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        del env
        del input_text
        calls.append(tuple(command))
        return CommandResult(0)

    policy = TrustPolicy(
        "https://git.example/owner/repo.git",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        known_host_pins=("git.example ssh-ed25519 PIN",),
        fetch_identity=identity,
        remote_host="git.example",
        remote_user="git",
    )
    mirror = TrustedMirror(
        protected / "mirror.git", policy, known_hosts, runner=runner, filesystem_root=tmp_path
    )
    (protected / "mirror.git").mkdir(mode=0o700)
    with pytest.raises(TrustError, match="pinned SSH transport"):
        mirror.fetch()
    assert calls == []


def test_fetch_binds_valid_remote_to_strict_pinned_ssh_command(tmp_path: Path) -> None:
    """Pass the protected key and host-key database to an exact SSH endpoint."""
    protected = tmp_path / "var/lib/abhaile"
    mirror_path = protected / "mirror.git"
    mirror_path.mkdir(parents=True, mode=0o700)
    trust = tmp_path / "etc/abhaile"
    trust.mkdir(parents=True)
    known_hosts = trust / "known_hosts"
    known_hosts.write_text("[git.example]:2222 ssh-ed25519 PIN\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    identity = trust / "identity"
    identity.write_text("placeholder\n", encoding="utf-8")
    identity.chmod(0o600)
    revision = "a" * 40
    calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def runner(
        command: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        del input_text
        calls.append((tuple(command), env))
        if "fetch" in command:
            return CommandResult(0)
        if "refs/abhaile/incoming^{commit}" in command:
            return CommandResult(0, revision + "\n")
        if "refs/abhaile/trusted^{commit}" in command:
            return CommandResult(1)
        if "update-ref" in command:
            return CommandResult(0)
        return CommandResult(1)

    policy = TrustPolicy(
        "ssh://git@git.example:2222/owner/repo.git",
        "main",
        "deimos",
        root_uid=os.geteuid(),
        known_host_pins=("[git.example]:2222 ssh-ed25519 PIN",),
        fetch_identity=identity,
        remote_host="git.example",
        remote_user="git",
        remote_port=2222,
    )
    mirror = TrustedMirror(
        mirror_path, policy, known_hosts, runner=runner, filesystem_root=tmp_path
    )
    assert mirror.fetch() == revision
    fetch = next(call for call in calls if "fetch" in call[0])
    assert fetch[1] is not None
    ssh_command = fetch[1]["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=yes" in ssh_command
    assert f"IdentityFile={identity}" in ssh_command
    assert f"UserKnownHostsFile={known_hosts}" in ssh_command
    assert "accept-new" not in ssh_command


def test_retention_refs_survive_gc(repositories: tuple[Path, Path, TrustedMirror]) -> None:
    """Preserve trusted, LKG, active, transaction, and rollback objects through GC."""
    _remote, _work, mirror = repositories
    revision = mirror.fetch()
    mirror.mark_last_known_good(revision)
    mirror.retain_active_transaction(revision)
    mirror.retain_transaction("render-1", revision)
    mirror.retain_rollback(0, revision)
    mirror.garbage_collect()
    protected = mirror.protected_revisions()
    assert protected[ACTIVE_REF] == revision
    assert mirror.admit(revision) == revision


def test_retention_rejects_unbounded_or_unsafe_names(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Keep retention refs within configured policy and namespace."""
    _remote, _work, mirror = repositories
    revision = mirror.fetch()
    with pytest.raises(TrustError, match="outside protected policy"):
        mirror.retain_rollback(mirror.policy.rollback_history, revision)
    with pytest.raises(TrustError, match="name is invalid"):
        mirror.retain_transaction("../escape", revision)
    with pytest.raises(TrustError, match="Only active"):
        mirror.release_ref("refs/heads/main")


def test_last_known_good_rotation_is_atomic_bounded_and_distinct(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Retain only the configured number of displaced unrelated LKG revisions."""
    _remote, work, mirror = repositories
    revisions: list[str] = []
    first = mirror.fetch()
    mirror.mark_last_known_good(first)
    revisions.append(first)
    for number in range(1, 4):
        _run("git", "checkout", "--orphan", f"replacement-{number}", cwd=work)
        (work / "data").write_text(str(number), encoding="utf-8")
        _run("git", "add", "data", cwd=work)
        _run("git", "commit", "-m", f"replacement {number}", cwd=work)
        _run("git", "push", "--force", "origin", "HEAD:main", cwd=work)
        revision = mirror.fetch(approve_non_fast_forward=True)
        mirror.mark_last_known_good(revision)
        revisions.append(revision)
    protected = mirror.protected_revisions()
    assert protected["refs/abhaile/last-known-good"] == revisions[3]
    assert protected["refs/abhaile/rollback/0000"] == revisions[2]
    assert protected["refs/abhaile/rollback/0001"] == revisions[1]
    assert revisions[0] not in protected.values()
    mirror.garbage_collect()


def test_trust_lock_serializes_concurrent_transactions(
    repositories: tuple[Path, Path, TrustedMirror],
) -> None:
    """Prevent fetch, capsule preparation, and GC from overlapping."""
    _remote, _work, mirror = repositories
    attempted = threading.Event()
    acquired = threading.Event()

    def contender() -> None:
        attempted.set()
        with mirror.trust_lock():
            acquired.set()

    with mirror.trust_lock():
        thread = threading.Thread(target=contender)
        thread.start()
        assert attempted.wait(1)
        assert not acquired.wait(0.1)
    thread.join(timeout=1)
    assert acquired.is_set()


def test_archive_validation_rejects_file_path_collision() -> None:
    """Reject a file that would become the parent of another archive member."""
    parent = tarfile.TarInfo("path")
    parent.type = tarfile.REGTYPE
    child = tarfile.TarInfo("path/child")
    child.type = tarfile.REGTYPE
    with pytest.raises(TrustError, match="file/path collision"):
        TrustedMirror._validate_archive_members([parent, child])
