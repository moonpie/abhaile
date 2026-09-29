"""Unit tests for immutable trusted convergence capsules."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from abhaile.trust.capsule import CapsuleStore
from abhaile.trust.containment import BoundaryCreationError
from abhaile.trust.errors import TrustError
from abhaile.trust.git import TrustedMirror
from abhaile.trust.launcher import protected_render
from abhaile.trust.model import TrustPaths, TrustPolicy


class FixtureBoundary:
    """Model a synchronous fixture renderer without launching host processes."""

    def create(self, transaction: str) -> None:
        pass

    def run(self, command: object, *, cwd: Path, env: dict[str, str]) -> None:
        raise AssertionError("Fixture process execution was not configured")

    def verify_quiescent(self) -> None:
        pass

    def resume(self, transaction: str) -> None:
        pass

    def identity(self) -> tuple[int, int, str]:
        return (1, 1, "fixture-boot")

    def retire(self, transaction: str, identity: tuple[int, int, str]) -> None:
        assert identity == self.identity()


class RecoveredCreationFailureBoundary(FixtureBoundary):
    """Model a failed child cgroup whose exact inode was already removed."""

    def create(self, transaction: str) -> None:
        raise BoundaryCreationError("injected cgroup creation failure", recovered=True)


def _render(source: Path, output: Path, host: str, _boundary: object) -> None:
    assert (source / "trusted.txt").read_text(encoding="utf-8") == "trusted"
    artifact = output / "system" / "unit.service"
    artifact.parent.mkdir()
    artifact.write_text("trusted artifact\n", encoding="utf-8")
    payload = artifact.read_bytes()
    manifest = {
        "version": "1",
        "host": host,
        "rendered_at": "ignored-by-trust-boundary",
        "entries": [
            {
                "render_path": "system/unit.service",
                "target_path": "/etc/systemd/system/unit.service",
                "kind": "systemd.unit",
                "owner_ref": "unit",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        ],
        "owners": {"unit": {"name": "unit"}},
    }
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _add_collectible_capsule(capsule_store: CapsuleStore, source: Path) -> tuple[str, Path]:
    """Copy a valid fixture capsule under an unretained canonical revision."""
    revision = "f" * 40
    destination = source.parent / revision
    shutil.copytree(source, destination)
    seal_path = destination / "seal.json"
    seal_path.chmod(0o600)
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["revision"] = revision
    seal_path.write_text(json.dumps(seal, sort_keys=True) + "\n", encoding="utf-8")
    capsule_store._make_read_only(destination)
    return revision, destination


@pytest.fixture
def store(tmp_path: Path) -> tuple[CapsuleStore, str]:
    """Create protected roots and an admitted source revision."""
    work = tmp_path / "work"
    remote = tmp_path / "remote.git"
    root = tmp_path / "root"
    work.mkdir()
    root.mkdir(mode=0o700)
    for name in ("quarantine", "capsules"):
        (root / name).mkdir(mode=0o700)
    known_hosts = root / "known_hosts"
    known_hosts.write_text("example ssh-ed25519 PIN\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=work, check=True)
    (work / "trusted.txt").write_text("trusted", encoding="utf-8")
    (work / "src").mkdir()
    (work / "src/placeholder").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work, check=True)
    subprocess.run(["git", "commit", "-m", "trusted"], cwd=work, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=work, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=work, check=True)
    identity = root / "fetch-identity"
    identity.write_text("test-only-placeholder\n", encoding="utf-8")
    identity.chmod(0o600)
    policy = TrustPolicy(
        str(remote),
        "main",
        "deimos",
        root_uid=os.geteuid(),
        render_uid=os.geteuid(),
        render_gid=os.getegid(),
        known_host_pins=("example ssh-ed25519 PIN",),
        fetch_identity=identity,
    )
    paths = TrustPaths(
        root / "mirror.git",
        root / "staging",
        root / "quarantine",
        root / "capsules",
        root / "active",
        known_hosts,
        identity,
    )
    mirror = TrustedMirror(paths.mirror, policy, known_hosts, allow_local_remote=True)
    mirror.initialize()
    revision = mirror.fetch()
    return CapsuleStore(paths, policy, mirror, boundary=FixtureBoundary()), revision


def test_seals_source_manifest_and_artifacts(store: tuple[CapsuleStore, str]) -> None:
    """Seal only mirror-exported source and verified output as non-writable content."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    assert capsule.revision == revision
    assert capsule.source.joinpath("trusted.txt").read_text(encoding="utf-8") == "trusted"
    assert not capsule.path.stat().st_mode & 0o222
    assert capsule_store.verify(capsule.path, revision) == capsule


def test_seals_complete_convergence_manifest_v2(store: tuple[CapsuleStore, str]) -> None:
    """Seal the validated v2 manifest and its referenced artifact as fresh inodes."""
    capsule_store, revision = store

    def render_v2(source: Path, output: Path, host: str, _boundary: object) -> None:
        assert source.joinpath("trusted.txt").is_file()
        artifact = output / "system/unit.service"
        artifact.parent.mkdir()
        artifact.write_bytes(b"unit\n")
        (output / "manifest.json").write_text(
            json.dumps({"version": "1", "host": host, "entries": []}), encoding="utf-8"
        )
        (output / "convergence-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "host": host,
                    "rendered_root": ".",
                    "entries": [
                        {
                            "render_path": "system/unit.service",
                            "target_path": "/etc/systemd/system/unit.service",
                            "kind": "systemd.unit",
                            "action": "publish",
                            "owner_ref": "unit:unit.service",
                            "sha256": hashlib.sha256(b"unit\n").hexdigest(),
                            "size": 5,
                            "execution_context": "system",
                            "metadata": {"owner": "root", "group": "root", "mode": "0644"},
                            "validation": "systemd",
                            "lifecycle": ["manager-reload"],
                            "safe_prune": "safe-if-unchanged",
                        }
                    ],
                    "owners": {
                        "unit:unit.service": {
                            "name": "unit:unit.service",
                            "owner_kind": "unit",
                            "execution_context": "system",
                            "requires": [],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    capsule = capsule_store.prepare(revision, render_v2)
    assert capsule.rendered.joinpath("convergence-manifest.json").is_file()
    assert capsule_store.verify(capsule.path, revision) == capsule


def test_rejects_manifest_artifact_tampering(store: tuple[CapsuleStore, str]) -> None:
    """Detect caller-style artifact changes before capsule consumption."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    artifact = capsule.rendered / "system" / "unit.service"
    artifact.chmod(0o600)
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(TrustError, match="mutable|changed"):
        capsule_store.verify(capsule.path, revision)


def test_copy_out_ignores_render_tree_changes_after_validation(
    store: tuple[CapsuleStore, str],
) -> None:
    """Seal copied inodes even when render-owned scratch changes after validation."""
    capsule_store, revision = store

    def tamper(stage: str, transaction: Path) -> None:
        if stage == "after-validation":
            (transaction / "render-scratch/rendered/system/unit.service").write_text(
                "changed", encoding="utf-8"
            )

    attacked = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        failure_hook=tamper,
    )
    capsule = attacked.prepare(revision, _render)
    assert capsule.rendered.joinpath("system/unit.service").read_text() == "trusted artifact\n"


def test_renderer_retained_writable_descriptor_cannot_change_capsule(
    store: tuple[CapsuleStore, str],
) -> None:
    """Ensure a renderer-held descriptor refers only to abandoned scratch inodes."""
    capsule_store, revision = store
    handles: list[Any] = []

    def render_with_retained_descriptor(
        source: Path, output: Path, host: str, boundary: object
    ) -> None:
        _render(source, output, host, boundary)
        handles.append((output / "system/unit.service").open("r+b"))

    capsule = capsule_store.prepare(revision, render_with_retained_descriptor)
    try:
        handles[0].seek(0)
        handles[0].write(b"attacker mutation")
        handles[0].flush()
        assert (
            capsule.rendered.joinpath("system/unit.service").read_text(encoding="utf-8")
            == "trusted artifact\n"
        )
        assert capsule_store.verify(capsule.path, revision) == capsule
    finally:
        handles[0].close()


def test_capsule_uses_real_protected_render_output_contract(
    store: tuple[CapsuleStore, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind CapsuleStore scratch layout to the real protected-render CLI invocation."""
    capsule_store, revision = store
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o755)
    runtime = runtime_root / "python"
    runtime.write_text("fixture", encoding="utf-8")
    runtime.chmod(0o555)
    policy = replace(
        capsule_store.policy,
        render_python=runtime,
        render_runtime_root=runtime_root,
    )
    real_run = subprocess.run

    def run(command: tuple[str, ...], **kwargs: Any) -> Any:
        if command[0] != "/usr/bin/setpriv":
            return real_run(command, **kwargs)
        output_root = Path(command[command.index("--output") + 1])
        _render(Path(kwargs["cwd"]), output_root / "rendered", "deimos", render_boundary)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("abhaile.trust.containment.subprocess.run", run)
    render_boundary = FixtureBoundary()
    monkeypatch.setattr(render_boundary, "run", lambda command, **kwargs: run(command, **kwargs))
    integrated = CapsuleStore(
        capsule_store.paths, policy, capsule_store.mirror, boundary=render_boundary
    )
    capsule = integrated.prepare(
        revision,
        lambda source, output, host, boundary: protected_render(
            source, output, host, policy, boundary=boundary
        ),
    )
    assert capsule.rendered.joinpath("system/unit.service").is_file()


def test_offline_cached_last_known_good_uses_no_fetch(store: tuple[CapsuleStore, str]) -> None:
    """Resolve the sealed rollback capsule using retained local objects only."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    capsule_store.mirror.mark_last_known_good(revision)
    assert capsule_store.cached_last_known_good() == capsule


def test_seals_manifest_directory_entries(store: tuple[CapsuleStore, str]) -> None:
    """Accept established directory artifacts while retaining strict completeness checks."""
    capsule_store, revision = store

    def render_directory(source: Path, output: Path, host: str, _boundary: object) -> None:
        assert source.joinpath("trusted.txt").is_file()
        directory = output / "services" / "data"
        directory.mkdir(parents=True)
        manifest = {
            "version": "1",
            "host": host,
            "entries": [
                {
                    "render_path": "services/data",
                    "target_path": "/srv/data",
                    "kind": "service.directory",
                    "owner_ref": "service:test",
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "size": 0,
                    "is_directory": True,
                }
            ],
            "owners": {"service:test": {"name": "service:test"}},
        }
        output.joinpath("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    capsule = capsule_store.prepare(revision, render_directory)
    assert capsule.rendered.joinpath("services/data").is_dir()


def test_rejects_directory_entry_with_file_payload(store: tuple[CapsuleStore, str]) -> None:
    """Reject a directory manifest entry whose rendered type is a regular file."""
    capsule_store, revision = store

    def render_wrong_type(_source: Path, output: Path, host: str, _boundary: object) -> None:
        artifact = output / "services" / "data"
        artifact.parent.mkdir()
        artifact.write_text("not a directory", encoding="utf-8")
        manifest = {
            "version": "1",
            "host": host,
            "entries": [
                {
                    "render_path": "services/data",
                    "target_path": "/srv/data",
                    "kind": "service.directory",
                    "owner_ref": "service:test",
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "size": 0,
                    "is_directory": True,
                }
            ],
            "owners": {"service:test": {"name": "service:test"}},
        }
        output.joinpath("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(TrustError, match="must be a real directory"):
        capsule_store.prepare(revision, render_wrong_type)


def test_render_ownership_handoff_is_injectable(
    store: tuple[CapsuleStore, str], tmp_path: Path
) -> None:
    """Model distinct root and render identities without requiring test root privileges."""
    capsule_store, _revision = store
    tree = tmp_path / "ownership"
    child = tree / "child"
    tree.mkdir()
    child.write_text("content", encoding="utf-8")
    owners = {tree: 1000, child: 1000}
    injected = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        owner_lookup=lambda path: owners[path],
        change_owner=lambda path, uid: owners.__setitem__(path, uid),
    )
    injected._change_tree_owner(tree, 1000, 2000)
    injected._validate_tree_owner(tree, 2000)
    assert owners == {tree: 2000, child: 2000}


def test_prepare_never_assigns_protected_source_to_render_identity(
    store: tuple[CapsuleStore, str],
) -> None:
    """Keep admitted source root-owned while handing off only isolated render output."""
    capsule_store, revision = store
    owners: dict[Path, int] = {}
    changes: list[tuple[Path, int]] = []
    render_uid = os.geteuid() + 1000

    def owner(path: Path) -> int:
        return owners.get(path, os.geteuid())

    def change(path: Path, uid: int) -> None:
        owners[path] = uid
        changes.append((path, uid))

    policy = TrustPolicy(
        capsule_store.policy.remote_url,
        capsule_store.policy.branch,
        capsule_store.policy.host,
        root_uid=os.geteuid(),
        render_uid=render_uid,
        known_host_pins=capsule_store.policy.known_host_pins,
        fetch_identity=capsule_store.policy.fetch_identity,
    )
    injected = CapsuleStore(
        capsule_store.paths,
        policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        owner_lookup=owner,
        change_owner=change,
    )

    def render_as_restricted(source: Path, output: Path, host: str, boundary: object) -> None:
        _render(source, output, host, boundary)
        for path in output.rglob("*"):
            owners[path] = render_uid

    injected.prepare(revision, render_as_restricted)
    assert changes
    assert all("source" not in path.parts for path, _uid in changes)


def test_rejects_unmanifested_directory(store: tuple[CapsuleStore, str]) -> None:
    """Reject an extra directory that is not required by any manifest artifact."""
    capsule_store, revision = store

    def render_extra_directory(source: Path, output: Path, host: str, boundary: object) -> None:
        _render(source, output, host, boundary)
        output.joinpath("unmanifested").mkdir()

    with pytest.raises(TrustError, match="completeness"):
        capsule_store.prepare(revision, render_extra_directory)


def test_activation_failure_before_commit_preserves_active_state(
    store: tuple[CapsuleStore, str],
) -> None:
    """Leave the active capsule unchanged when activation fails before atomic replace."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)

    def fail(stage: str, _path: Path) -> None:
        if stage == "before-activation":
            raise TrustError("injected activation failure")

    attacked = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        failure_hook=fail,
    )
    with pytest.raises(TrustError, match="injected activation"):
        attacked.activate(capsule)
    assert not capsule_store.paths.active.exists()
    assert "refs/abhaile/active-transaction" not in capsule_store.mirror.protected_revisions()


def test_activation_fsync_failure_restores_file_and_ref(
    store: tuple[CapsuleStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roll back both activation records when durability fails after publication."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    real_sync = capsule_store._sync_directory
    calls = 0

    def fail_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected directory fsync failure")
        real_sync(path)

    monkeypatch.setattr(capsule_store, "_sync_directory", fail_once)
    with pytest.raises(OSError, match="injected directory fsync"):
        capsule_store.activate(capsule)
    assert not capsule_store.paths.active.exists()
    assert "refs/abhaile/active-transaction" not in capsule_store.mirror.protected_revisions()


def test_prepare_releases_transaction_ref_after_success_or_failure(
    store: tuple[CapsuleStore, str],
) -> None:
    """Retain objects only while capsule preparation is actively using them."""
    capsule_store, revision = store
    capsule_store.prepare(revision, _render)
    assert not any(
        ref.startswith("refs/abhaile/transactions/")
        for ref in capsule_store.mirror.protected_revisions()
    )


def test_capsule_gc_preserves_every_ref_retained_revision(
    store: tuple[CapsuleStore, str],
) -> None:
    """Preserve every capsule named by any protected Abhaile ref."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    capsule_store.mirror.mark_last_known_good(revision)
    capsule_store.mirror.retain_active_transaction(revision)
    capsule_store.mirror.retain_rollback(0, revision)

    assert capsule_store.garbage_collect() == ()
    assert capsule.path.is_dir()


def test_capsule_gc_quarantines_then_deletes_unretained_capsule(
    store: tuple[CapsuleStore, str],
) -> None:
    """Move a verified unretained capsule aside before deleting it."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    collectible_revision, collectible = _add_collectible_capsule(capsule_store, capsule.path)
    observed: list[tuple[str, Path]] = []

    def observe(stage: str, path: Path) -> None:
        observed.append((stage, path))
        if stage == "after-gc-quarantine":
            assert path.is_dir()
            assert not collectible.exists()

    collector = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        failure_hook=observe,
    )
    assert collector.garbage_collect() == (collectible_revision,)
    assert capsule.path.exists()
    assert not collectible.exists()
    assert [stage for stage, _path in observed] == [
        "before-gc-quarantine",
        "after-gc-quarantine",
    ]


def test_capsule_gc_validates_all_capsules_before_deleting_any(
    store: tuple[CapsuleStore, str],
) -> None:
    """Fail closed before mutation when any capsule is invalid."""
    capsule_store, revision = store
    first = capsule_store.prepare(revision, _render)
    invalid_revision = "e" * 40
    invalid = first.path.parent / invalid_revision
    invalid.mkdir(mode=0o500)

    with pytest.raises(TrustError):
        capsule_store.garbage_collect()

    assert first.path.is_dir()
    assert invalid.is_dir()


def test_capsule_gc_rejects_open_namespace_before_mutation(
    store: tuple[CapsuleStore, str],
) -> None:
    """Reject unexpected hosts and non-canonical capsule names."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    _add_collectible_capsule(capsule_store, capsule.path)
    (capsule_store.paths.capsules / "phobos").mkdir(mode=0o700)

    with pytest.raises(TrustError, match="unexpected host"):
        capsule_store.garbage_collect()

    assert capsule.path.is_dir()


def test_capsule_gc_failure_after_quarantine_is_safely_retryable(
    store: tuple[CapsuleStore, str],
) -> None:
    """Leave a named quarantine after failure without risking retained capsules."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    collectible_revision, collectible = _add_collectible_capsule(capsule_store, capsule.path)

    def fail(stage: str, _path: Path) -> None:
        if stage == "after-gc-quarantine":
            raise TrustError("injected GC failure")

    collector = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        failure_hook=fail,
    )
    with pytest.raises(TrustError, match="injected GC failure"):
        collector.garbage_collect()

    quarantine = capsule_store.paths.quarantine / f".gc.deimos.{collectible_revision}"
    assert quarantine.is_dir()
    assert not collectible.exists()
    assert capsule_store.garbage_collect() == ()
    assert not quarantine.exists()


def test_capsule_gc_excludes_incoming_ref_from_retention(
    store: tuple[CapsuleStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not retain a capsule solely because an unadmitted incoming ref names it."""
    capsule_store, revision = store
    capsule = capsule_store.prepare(revision, _render)
    collectible_revision, collectible = _add_collectible_capsule(capsule_store, capsule.path)
    monkeypatch.setattr(
        capsule_store.mirror,
        "protected_revisions",
        lambda: {
            "refs/abhaile/trusted": revision,
            "refs/abhaile/incoming": collectible_revision,
        },
    )

    assert capsule_store.garbage_collect() == (collectible_revision,)
    assert not collectible.exists()


def test_capsule_gc_allows_trusted_revision_before_capsule_sealing(
    store: tuple[CapsuleStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allow trusted and in-flight refs to exist before their capsule is sealed."""
    capsule_store, revision = store
    missing = "e" * 40
    monkeypatch.setattr(
        capsule_store.mirror,
        "protected_revisions",
        lambda: {
            "refs/abhaile/trusted": missing,
            "refs/abhaile/transactions/render": revision,
        },
    )

    assert capsule_store.garbage_collect() == ()


def test_capsule_gc_handles_pending_and_recreated_same_revision(
    store: tuple[CapsuleStore, str],
) -> None:
    """Delete a validated pending quarantine before collecting its replacement."""
    capsule_store, revision = store
    retained = capsule_store.prepare(revision, _render)
    collectible_revision, collectible = _add_collectible_capsule(capsule_store, retained.path)
    pending = capsule_store.paths.quarantine / f".gc.deimos.{collectible_revision}"
    collectible.chmod(0o700)
    os.replace(collectible, pending)
    _add_collectible_capsule(capsule_store, retained.path)

    assert capsule_store.garbage_collect() == (collectible_revision,)
    assert not pending.exists()
    assert not collectible.exists()

    def fail(stage: str, _path: Path) -> None:
        if stage == "before-export":
            raise TrustError("injected transaction failure")

    attacked = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=FixtureBoundary(),
        failure_hook=fail,
    )
    other = capsule_store.paths.capsules / "deimos" / revision
    other.chmod(0o700)
    for child in other.rglob("*"):
        child.chmod(0o700 if child.is_dir() else 0o600)
    CapsuleStore.discard_quarantine(other)
    with pytest.raises(TrustError, match="transaction failure"):
        attacked.prepare(revision, _render)
    assert not any(
        ref.startswith("refs/abhaile/transactions/")
        for ref in capsule_store.mirror.protected_revisions()
    )


def test_failed_renderer_retains_receipt_for_explicit_retirement(store):
    """Keep safely quiescent failed scratch associated with its retained cgroup."""
    capsule_store, revision = store

    def fail(source, output, host, boundary):
        raise TrustError("injected renderer failure")

    with pytest.raises(TrustError, match="renderer failure"):
        capsule_store.prepare(revision, fail)
    receipts = list(capsule_store.paths.quarantine.glob(".render-orphan.*.receipt"))
    assert len(receipts) == 1
    assert receipts[0].with_suffix("").is_dir()
    assert capsule_store.cleanup_render_orphans(dry_run=True) == ()
    assert receipts[0].exists()


def test_recovered_boundary_creation_failure_removes_scratch_for_retry(store):
    """Do not accumulate untracked scratch after an atomic cgroup rollback."""
    capsule_store, revision = store
    attacked = CapsuleStore(
        capsule_store.paths,
        capsule_store.policy,
        capsule_store.mirror,
        boundary=RecoveredCreationFailureBoundary(),
    )
    for _attempt in range(2):
        with pytest.raises(BoundaryCreationError) as error:
            attacked.prepare(revision, _render)
        assert error.value.recovered is True
        assert list(capsule_store.paths.quarantine.iterdir()) == []
        assert not any(
            ref.startswith("refs/abhaile/transactions/")
            for ref in capsule_store.mirror.protected_revisions()
        )
