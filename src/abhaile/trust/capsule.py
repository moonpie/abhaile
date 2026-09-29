"""Build, seal, verify, and activate immutable convergence capsules."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from abhaile.trust.errors import TrustError
from abhaile.trust.containment import BoundaryCreationError, RenderBoundary
from abhaile.trust.git import (
    ACTIVE_REF,
    LKG_REF,
    ROLLBACK_REF_PREFIX,
    TRANSACTION_REF_PREFIX,
    TRUSTED_REF,
    TrustedMirror,
)
from abhaile.trust.manifest import (
    tree_digest,
    validate_manifest,
    validate_manifest_snapshot,
)
from abhaile.trust.model import (
    TrustPaths,
    TrustPolicy,
    validate_production_path,
    validate_protected_path,
)
from abhaile.trust.securefs import materialize_snapshot, snapshot_tree
from abhaile.trust.orphans import cleanup_orphans, record_orphan

FailureHook = Callable[[str, Path], None]
Render = Callable[[Path, Path, str, RenderBoundary], None]
OwnerLookup = Callable[[Path], int]
ChangeOwner = Callable[[Path, int], None]


def _owner_uid(path: Path) -> int:
    """Return a path owner for production ownership validation."""
    return path.lstat().st_uid


def _change_owner(path: Path, uid: int) -> None:
    """Change ownership without following a link."""
    os.chown(path, uid, -1, follow_symlinks=False)


@dataclass(frozen=True)
class SealedCapsule:
    """Identify verified protected source and desired output."""

    revision: str
    host: str
    path: Path

    @property
    def source(self) -> Path:
        """Return the sealed source root."""
        return self.path / "source"

    @property
    def rendered(self) -> Path:
        """Return the sealed rendered root."""
        return self.path / "rendered"


class CapsuleStore:
    """Coordinate admission, isolated rendering, sealing, and cached rollback."""

    def __init__(
        self,
        paths: TrustPaths,
        policy: TrustPolicy,
        mirror: TrustedMirror,
        *,
        failure_hook: FailureHook | None = None,
        boundary: RenderBoundary | None = None,
        owner_lookup: OwnerLookup = _owner_uid,
        change_owner: ChangeOwner = _change_owner,
    ) -> None:
        self.boundary = boundary
        self.paths = paths
        self.policy = policy
        self.mirror = mirror
        self.failure_hook = failure_hook or (lambda _stage, _path: None)
        self.owner_lookup = owner_lookup
        self.change_owner = change_owner

    def prepare(
        self,
        revision: str,
        render: Render,
        *,
        mode: Literal["dry-run", "converge"] = "dry-run",
    ) -> SealedCapsule:
        """Create or return a sealed capsule without mutating managed host state."""
        with self.mirror.trust_lock():
            return self._prepare_locked(revision, render, mode=mode)

    def _prepare_locked(
        self,
        revision: str,
        render: Render,
        *,
        mode: Literal["dry-run", "converge"],
    ) -> SealedCapsule:
        """Prepare a capsule while holding the mirror transaction lock."""
        admitted = self.mirror.admit(revision)
        final = self.paths.capsules / self.policy.host / admitted
        if final.exists():
            return self.verify(final, admitted)
        self._validate_roots()
        if self.boundary is None:
            raise TrustError("Root-controlled renderer containment is required")
        transaction_name = uuid.uuid4().hex
        transaction_ref = f"refs/abhaile/transactions/{transaction_name}"
        self.mirror.retain_transaction(transaction_name, admitted)
        transaction = self.paths.quarantine / f"{admitted}.{transaction_name}"
        source = transaction / "source"
        render_scratch = transaction / "render-scratch"
        render_work = render_scratch / "rendered"
        rendered = transaction / "rendered"
        boundary_created = False
        try:
            transaction.mkdir(mode=0o711)
            self.failure_hook("before-export", transaction)
            self.mirror.export_archive(admitted, source)
            self._reject_unsupported_tree(source)
            self._make_read_only(source)
            render_work.mkdir(mode=0o700, parents=True)
            self._change_tree_owner(render_scratch, self.policy.root_uid, self._render_uid())
            try:
                self.boundary.create(transaction_name)
            except BoundaryCreationError as exc:
                if exc.recovered:
                    self.discard_quarantine(transaction)
                    self._sync_directory(self.paths.quarantine)
                raise
            boundary_created = True
            self.failure_hook("before-render", transaction)
            render(source, render_work, self.policy.host, self.boundary)
            self.boundary.verify_quiescent()
            self.failure_hook("after-render", transaction)
            self._validate_tree_owner(source, self.policy.root_uid)
            self._validate_tree_owner(render_work, self._render_uid())
            rendered_snapshot = snapshot_tree(render_work)
            validate_manifest_snapshot(rendered_snapshot, self.policy.host)
            self.failure_hook("after-validation", transaction)
            materialize_snapshot(rendered_snapshot, rendered)
            self.failure_hook("after-copy", transaction)
            self._make_read_only(rendered)
            validate_manifest(rendered, self.policy.host)
            seal = {
                "version": 1,
                "host": self.policy.host,
                "revision": admitted,
                "source_sha256": tree_digest(source),
                "rendered_sha256": tree_digest(rendered),
                "mode": mode,
            }
            seal_path = transaction / "seal.json"
            seal_path.write_text(json.dumps(seal, sort_keys=True) + "\n", encoding="utf-8")
            seal_path.chmod(0o400)
            self._sync_file(seal_path)
            self.failure_hook("before-seal", transaction)
            orphan = self.paths.quarantine / f".render-orphan.{admitted}.{transaction_name}"
            os.replace(render_scratch, orphan)
            record_orphan(self.paths.quarantine, orphan, self.boundary)
            self.verify(transaction, admitted)
            final.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.replace(transaction, final)
            final.chmod(0o500)
            self._sync_directory(final.parent)
            self.failure_hook("after-seal", final)
            return self.verify(final, admitted)
        finally:
            try:
                if boundary_created and render_scratch.exists():
                    # Failed renders keep a receipt only when kernel evidence proves safety.
                    # Ambiguity preserves the entire transaction for operator investigation.
                    try:
                        self.boundary.verify_quiescent()
                    except TrustError:
                        pass
                    else:
                        orphan = (
                            self.paths.quarantine / f".render-orphan.{admitted}.{transaction_name}"
                        )
                        os.replace(render_scratch, orphan)
                        record_orphan(self.paths.quarantine, orphan, self.boundary)
            finally:
                self.mirror.release_ref(transaction_ref)

    def verify(self, path: Path, revision: str) -> SealedCapsule:
        """Revalidate ownership, immutability, manifest, and seal before consumption."""
        validate_protected_path(path, owner_uid=self.policy.root_uid)
        for child in path.rglob("*"):
            stat = child.lstat()
            if child.is_symlink() or stat.st_uid != self.policy.root_uid or stat.st_mode & 0o222:
                raise TrustError(f"Capsule is mutable or has unsafe ownership: {child}")
        seal_path = path / "seal.json"
        try:
            seal = json.loads(seal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrustError("Capsule seal is unavailable or invalid") from exc
        if seal.get("host") != self.policy.host or seal.get("revision") != revision:
            raise TrustError("Capsule seal identity does not match the request")
        source = path / "source"
        rendered = path / "rendered"
        if seal.get("source_sha256") != tree_digest(source):
            raise TrustError("Sealed capsule source has changed")
        if seal.get("rendered_sha256") != tree_digest(rendered):
            raise TrustError("Sealed capsule rendered output has changed")
        validate_manifest(rendered, self.policy.host)
        return SealedCapsule(revision, self.policy.host, path)

    def activate(self, capsule: SealedCapsule) -> None:
        """Atomically record an active capsule using a root-owned regular file."""
        with self.mirror.trust_lock():
            self.verify(capsule.path, capsule.revision)
            previous = self.mirror.protected_revisions().get(ACTIVE_REF)
            previous_file = self._active_revision()
            if previous_file != previous:
                raise TrustError("Active capsule ref and pathname disagree before activation")
            self.mirror.retain_active_transaction(capsule.revision)
            try:
                self.paths.active.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                validate_protected_path(self.paths.active.parent, owner_uid=self.policy.root_uid)
                self.failure_hook("before-activation", capsule.path)
                temporary = self.paths.active.with_name(f".{self.paths.active.name}.new")
                temporary.write_text(capsule.revision + "\n", encoding="ascii")
                temporary.chmod(0o400)
                self._sync_file(temporary)
                os.replace(temporary, self.paths.active)
                self._sync_directory(self.paths.active.parent)
            except (OSError, TrustError):
                self._restore_active_file(previous_file)
                if previous is None:
                    self.mirror.release_ref(ACTIVE_REF)
                else:
                    self.mirror.restore_active_transaction(previous, expected=capsule.revision)
                raise

    def _active_revision(self) -> str | None:
        if not self.paths.active.exists():
            return None
        validate_protected_path(
            self.paths.active, owner_uid=self.policy.root_uid, regular_file=True
        )
        revision = self.paths.active.read_text(encoding="ascii").strip()
        if len(revision) != 40 or any(
            character not in "0123456789abcdef" for character in revision
        ):
            raise TrustError("Active capsule pathname contains an invalid revision")
        return revision

    def _restore_active_file(self, revision: str | None) -> None:
        if revision is None:
            self.paths.active.unlink(missing_ok=True)
            self._sync_directory(self.paths.active.parent)
            return
        temporary = self.paths.active.with_name(f".{self.paths.active.name}.rollback")
        temporary.write_text(revision + "\n", encoding="ascii")
        temporary.chmod(0o400)
        self._sync_file(temporary)
        os.replace(temporary, self.paths.active)
        self._sync_directory(self.paths.active.parent)

    def cached_last_known_good(self) -> SealedCapsule:
        """Resolve an already-admitted cached capsule without fetching a remote."""
        revision = self.mirror.admit(self.mirror.last_known_good())
        return self.verify(self.paths.capsules / self.policy.host / revision, revision)

    def garbage_collect(self) -> tuple[str, ...]:
        """Quarantine and remove capsules not retained by a protected Git ref."""
        with self.mirror.trust_lock():
            return self._garbage_collect_locked()

    def _garbage_collect_locked(self) -> tuple[str, ...]:
        """Collect capsules after validating the complete closed host namespace."""
        self._validate_roots()
        host_root = self.paths.capsules / self.policy.host
        if not host_root.exists():
            host_root.mkdir(mode=0o700)
            self._sync_directory(self.paths.capsules)
        validate_protected_path(host_root, owner_uid=self.policy.root_uid)
        namespaces = list(self.paths.capsules.iterdir())
        if any(path.name != self.policy.host for path in namespaces):
            raise TrustError("Capsule store contains an unexpected host namespace")
        protected = self.mirror.protected_revisions()
        allowed = {
            ref: revision
            for ref, revision in protected.items()
            if ref in {TRUSTED_REF, LKG_REF, ACTIVE_REF}
            or ref.startswith(TRANSACTION_REF_PREFIX)
            or ref.startswith(ROLLBACK_REF_PREFIX)
        }
        retained = set(allowed.values())
        capsules: dict[str, Path] = {}
        for path in host_root.iterdir():
            if not re.fullmatch(r"[0-9a-f]{40}", path.name):
                raise TrustError("Capsule store contains a non-canonical revision entry")
            capsules[path.name] = path
        for revision, path in capsules.items():
            self.verify(path, revision)
        pending: list[tuple[str, Path]] = []
        prefix = f".gc.{self.policy.host}."
        for path in self.paths.quarantine.iterdir():
            if not path.name.startswith(prefix):
                continue
            revision = path.name.removeprefix(prefix)
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise TrustError("Capsule GC quarantine contains a non-canonical revision")
            self.verify(path, revision)
            pending.append((revision, path))
        required = {
            revision
            for ref, revision in allowed.items()
            if ref in {LKG_REF, ACTIVE_REF} or ref.startswith(ROLLBACK_REF_PREFIX)
        }
        missing = required - capsules.keys()
        if missing:
            raise TrustError("A protected revision has no sealed capsule")
        collectible = sorted(capsules.keys() - retained)
        for _revision, path in pending:
            self.discard_quarantine(path)
            self._sync_directory(self.paths.quarantine)
        quarantined: list[tuple[str, Path]] = []
        for revision in collectible:
            source = capsules[revision]
            destination = self.paths.quarantine / f".gc.{self.policy.host}.{revision}"
            if destination.exists():
                raise TrustError("Capsule garbage-collection quarantine already exists")
            self.failure_hook("before-gc-quarantine", source)
            source.chmod(0o700)
            try:
                os.replace(source, destination)
            except OSError:
                source.chmod(0o500)
                raise
            self._sync_directory(host_root)
            self._sync_directory(self.paths.quarantine)
            quarantined.append((revision, destination))
            self.failure_hook("after-gc-quarantine", destination)
        for _revision, path in quarantined:
            self.discard_quarantine(path)
            self._sync_directory(self.paths.quarantine)
        return tuple(collectible)

    def cleanup_render_orphans(self, *, dry_run: bool = True) -> tuple[str, ...]:
        """Collect only quiescent associated scratch under the protected trust lock."""
        if dry_run:
            return ()
        if self.boundary is None:
            raise TrustError("Root-controlled renderer containment is required")
        with self.mirror.trust_lock():
            self._validate_roots()
            return cleanup_orphans(
                self.paths.quarantine,
                self.boundary,
                root_uid=self.policy.root_uid,
                render_uid=self._render_uid(),
                namespace=Path("/var/lib/abhaile"),
                filesystem_root=self.mirror.filesystem_root,
                dry_run=False,
            )

    def _validate_roots(self) -> None:
        for root in (self.paths.quarantine, self.paths.capsules):
            if self.mirror.allow_local_remote:
                validate_protected_path(root, owner_uid=self.policy.root_uid)
            else:
                validate_production_path(
                    root,
                    Path("/var/lib/abhaile"),
                    filesystem_root=self.mirror.filesystem_root,
                    owner_uid=self.policy.root_uid,
                )

    def _render_uid(self) -> int:
        if self.policy.render_uid is None:
            raise TrustError("Protected render identity UID is not configured")
        return self.policy.render_uid

    def _validate_tree_owner(self, root: Path, expected_uid: int) -> None:
        for path in (root, *root.rglob("*")):
            if self.owner_lookup(path) != expected_uid:
                raise TrustError(f"Protected render tree has unexpected ownership: {path}")

    def _change_tree_owner(self, root: Path, expected_uid: int, new_uid: int) -> None:
        self._validate_tree_owner(root, expected_uid)
        for path in (root, *root.rglob("*")):
            self.change_owner(path, new_uid)

    @staticmethod
    def _make_read_only(root: Path) -> None:
        for path in sorted(root.rglob("*"), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        root.chmod(0o555)

    @staticmethod
    def _reject_unsupported_tree(root: Path) -> None:
        seen: set[tuple[int, int]] = set()
        for path in root.rglob("*"):
            stat = path.lstat()
            identity = (stat.st_dev, stat.st_ino)
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise TrustError(f"Capsule contains an unsupported path: {path}")
            if path.is_file() and (stat.st_nlink != 1 or identity in seen):
                raise TrustError(f"Capsule contains a hard-linked file: {path}")
            seen.add(identity)

    @staticmethod
    def discard_quarantine(path: Path) -> None:
        """Remove only a named failed transaction after restoring owner write access."""
        if path.exists():
            for child in path.rglob("*"):
                if not child.is_symlink():
                    child.chmod(0o700 if child.is_dir() else 0o600)
            path.chmod(0o700)
            shutil.rmtree(path)

    @staticmethod
    def _sync_file(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
