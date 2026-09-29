"""Manage the root-owned mirror and trusted revision refs."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tarfile
import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Protocol, Sequence
from urllib.parse import urlsplit

from abhaile.trust.errors import TrustError
from abhaile.trust.model import (
    TrustPolicy,
    validate_protected_chain,
    validate_protected_path,
    validate_production_path,
)

FULL_OID = re.compile(r"^[0-9a-f]{40}$")
TRUSTED_REF = "refs/abhaile/trusted"
INCOMING_REF = "refs/abhaile/incoming"
LKG_REF = "refs/abhaile/last-known-good"
ACTIVE_REF = "refs/abhaile/active-transaction"
TRANSACTION_REF_PREFIX = "refs/abhaile/transactions/"
ROLLBACK_REF_PREFIX = "refs/abhaile/rollback/"


@dataclass(frozen=True)
class CommandResult:
    """Capture command output without exposing a subprocess implementation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Run a command with an optional environment."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult: ...


def subprocess_runner(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> CommandResult:
    """Run a command without a shell or inherited interactive input."""
    result = subprocess.run(
        command,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(result.returncode, result.stdout, result.stderr)


class TrustedMirror:
    """Admit revisions using refs established only by the protected mirror."""

    def __init__(
        self,
        path: Path,
        policy: TrustPolicy,
        known_hosts: Path,
        runner: CommandRunner = subprocess_runner,
        allow_local_remote: bool = False,
        *,
        filesystem_root: Path = Path("/"),
    ) -> None:
        self.path = path
        self.policy = policy
        self.known_hosts = known_hosts
        self.runner = runner
        self.allow_local_remote = allow_local_remote
        self.filesystem_root = filesystem_root

    def initialize(self) -> None:
        """Create a bare mirror only inside its already-protected parent."""
        with self.trust_lock():
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        """Initialize or validate the mirror while holding the trust lock."""
        self._validate_mirror_parent()
        if self.path.exists():
            validate_protected_path(self.path, owner_uid=self.policy.root_uid)
            result = self._git("rev-parse", "--is-bare-repository")
            if result.stdout.strip() != "true":
                raise TrustError(f"Trusted mirror is not bare: {self.path}")
            return
        result = self.runner(("git", "init", "--bare", str(self.path)))
        self._require(result, "initialize trusted mirror")
        self.path.chmod(0o700)

    def fetch(self, *, approve_non_fast_forward: bool = False) -> str:
        """Fetch a candidate ref and atomically advance the trusted ref."""
        with self.trust_lock():
            return self._fetch_locked(approve_non_fast_forward=approve_non_fast_forward)

    def _fetch_locked(self, *, approve_non_fast_forward: bool) -> str:
        """Fetch while the caller holds the exclusive mirror transaction lock."""
        self._validate_fetch_trust()
        self._validate_remote_transport()
        result = self._git(
            "fetch",
            "--no-tags",
            self.policy.remote_url,
            f"+refs/heads/{self.policy.branch}:{INCOMING_REF}",
            env={"GIT_SSH_COMMAND": self._ssh_command()},
        )
        self._require(result, "fetch trusted revision")
        incoming = self._resolve(INCOMING_REF)
        current = self._optional_resolve(TRUSTED_REF)
        if current and not approve_non_fast_forward:
            relation = self._git("merge-base", "--is-ancestor", current, incoming)
            if relation.returncode != 0:
                raise TrustError("Trusted ref update is not fast-forward")
        expected = current or "0" * 40
        self._require(
            self._git("update-ref", TRUSTED_REF, incoming, expected),
            "advance trusted ref",
        )
        return incoming

    def admit(self, revision: str) -> str:
        """Accept only a full commit reachable from trusted or last-known-good refs."""
        if not FULL_OID.fullmatch(revision):
            raise TrustError("Revision must be a full lowercase commit object ID")
        kind = self._git("cat-file", "-t", revision)
        if kind.returncode != 0 or kind.stdout.strip() != "commit":
            raise TrustError("Requested revision is not a commit in the trusted mirror")
        for ref in (TRUSTED_REF, LKG_REF):
            if self._optional_resolve(ref) is None:
                continue
            if self._git("merge-base", "--is-ancestor", revision, ref).returncode == 0:
                return revision
        raise TrustError("Requested revision is not reachable from a retained trusted ref")

    def mark_last_known_good(self, revision: str) -> None:
        """Retain an admitted revision as last-known-good after an external health gate."""
        with self.trust_lock():
            self.admit(revision)
            current = self._optional_resolve(LKG_REF)
            rollback = self._rollback_refs()
            history = [item for item in (current, *rollback.values()) if item and item != revision]
            history = list(dict.fromkeys(history))[: self.policy.rollback_history]
            commands = ["start"]
            current_refs = {
                f"{ROLLBACK_REF_PREFIX}{slot:04d}": oid for slot, oid in rollback.items()
            }
            desired_refs = {
                f"{ROLLBACK_REF_PREFIX}{slot:04d}": oid for slot, oid in enumerate(history)
            }
            for ref in sorted(current_refs.keys() | desired_refs.keys()):
                old = current_refs.get(ref)
                new = desired_refs.get(ref)
                if new is None and old is not None:
                    commands.append(f"delete {ref} {old}")
                elif new is not None:
                    commands.append(f"update {ref} {new} {old or '0' * 40}")
            commands.append(f"update {LKG_REF} {revision} {current or '0' * 40}")
            commands.extend(("prepare", "commit"))
            self._require(
                self._git("update-ref", "--stdin", input_text="\n".join(commands) + "\n"),
                "rotate last-known-good refs",
            )

    def last_known_good(self) -> str:
        """Return the retained last-known-good commit without network access."""
        return self._resolve(LKG_REF)

    def retain_active_transaction(self, revision: str) -> None:
        """Protect the admitted revision used by the active transaction."""
        self.admit(revision)
        self._require(self._git("update-ref", ACTIVE_REF, revision), "retain active transaction")

    def retain_transaction(self, transaction: str, revision: str) -> None:
        """Protect an admitted revision while a named transaction is in flight."""
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", transaction):
            raise TrustError("Transaction name is invalid")
        self.admit(revision)
        self._require(
            self._git("update-ref", f"{TRANSACTION_REF_PREFIX}{transaction}", revision),
            "retain transaction",
        )

    def retain_rollback(self, slot: int, revision: str) -> None:
        """Protect an admitted revision in a configured rollback-history slot."""
        if slot < 0 or slot >= self.policy.rollback_history:
            raise TrustError("Rollback-history slot is outside protected policy")
        self.admit(revision)
        self._require(
            self._git("update-ref", f"{ROLLBACK_REF_PREFIX}{slot:04d}", revision),
            "retain rollback revision",
        )

    def release_ref(self, ref: str) -> None:
        """Release only a transaction retention ref after its transaction ends."""
        if ref != ACTIVE_REF and not ref.startswith(TRANSACTION_REF_PREFIX):
            raise TrustError("Only active transaction refs may be released")
        self._require(self._git("update-ref", "-d", ref), "release transaction ref")

    def restore_active_transaction(self, revision: str, *, expected: str) -> None:
        """Restore the prior active ref after a failed pathname publication."""
        self._require(
            self._git("update-ref", ACTIVE_REF, revision, expected),
            "restore active transaction ref",
        )

    def protected_revisions(self) -> dict[str, str]:
        """Return the trusted object-retention roots managed by this mirror."""
        result = self._git("for-each-ref", "--format=%(refname) %(objectname)", "refs/abhaile/")
        self._require(result, "enumerate protected refs")
        protected: dict[str, str] = {}
        for line in result.stdout.splitlines():
            ref, separator, revision = line.partition(" ")
            if separator and FULL_OID.fullmatch(revision):
                protected[ref] = revision
        return protected

    def _rollback_refs(self) -> dict[int, str]:
        rollback: dict[int, str] = {}
        for ref, revision in self.protected_revisions().items():
            if not ref.startswith(ROLLBACK_REF_PREFIX):
                continue
            slot = ref.removeprefix(ROLLBACK_REF_PREFIX)
            if slot.isdecimal():
                rollback[int(slot)] = revision
        return dict(sorted(rollback.items()))

    def garbage_collect(self) -> None:
        """Collect unreachable objects while Git refs preserve every protected root."""
        with self.trust_lock():
            required = {TRUSTED_REF, LKG_REF}
            protected = self.protected_revisions()
            if not required.issubset(protected):
                raise TrustError("Garbage collection requires trusted and last-known-good refs")
            for ref in protected:
                self._resolve(ref)
            self._require(self._git("fsck", "--no-dangling"), "validate trusted mirror objects")
            self._require(self._git("gc", "--prune=now"), "garbage collect trusted mirror")

    @contextmanager
    def trust_lock(self) -> Iterator[None]:
        """Serialize trust updates, capsule preparation, and garbage collection."""
        self._validate_mirror_parent()
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        try:
            descriptor = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            raise TrustError("Trusted mirror lock cannot be opened safely") from exc
        try:
            metadata = os.fstat(descriptor)
            if metadata.st_uid != self.policy.root_uid or metadata.st_mode & 0o077:
                raise TrustError("Trusted mirror lock has unsafe ownership or mode")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def export_archive(self, revision: str, destination: Path) -> None:
        """Export source from the protected mirror without using a checkout."""
        self.admit(revision)
        destination.mkdir(mode=0o700, parents=False)
        archive = destination.parent / f".{destination.name}.tar"
        self._require(
            self._git("archive", "--format=tar", "--output", str(archive), revision),
            "export trusted source",
        )
        try:
            with tarfile.open(archive, "r:") as bundle:
                members = bundle.getmembers()
                self._validate_archive_members(members)
                for member in members:
                    target = destination.joinpath(*PurePosixPath(member.name).parts)
                    if member.isdir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise TrustError(f"Trusted archive file is unavailable: {member.name}")
                    with source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        except (OSError, tarfile.TarError) as exc:
            raise TrustError("Failed to extract trusted source") from exc
        finally:
            archive.unlink(missing_ok=True)

    @staticmethod
    def _validate_archive_members(members: Sequence[tarfile.TarInfo]) -> None:
        seen: set[PurePosixPath] = set()
        file_paths: set[PurePosixPath] = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
                or path.is_absolute()
                or not path.parts
                or path == PurePosixPath(".")
                or ".." in path.parts
                or path in seen
            ):
                raise TrustError(f"Trusted archive contains unsafe member: {member.name}")
            seen.add(path)
            if member.isfile():
                file_paths.add(path)
        for path in seen:
            if any(parent in file_paths for parent in path.parents):
                raise TrustError(f"Trusted archive contains a file/path collision: {path}")

    def _validate_mirror_parent(self) -> None:
        """Anchor production state before opening the mirror or its lock."""
        if not self.allow_local_remote:
            validate_production_path(
                self.path.parent,
                Path("/var/lib/abhaile"),
                filesystem_root=self.filesystem_root,
                owner_uid=self.policy.root_uid,
            )
        else:
            validate_protected_path(self.path.parent, owner_uid=self.policy.root_uid)

    def _validate_fetch_trust(self) -> None:
        validate_protected_path(self.path, owner_uid=self.policy.root_uid)
        if not self.allow_local_remote:
            validate_production_path(
                self.path,
                Path("/var/lib/abhaile"),
                filesystem_root=self.filesystem_root,
                owner_uid=self.policy.root_uid,
            )
            validate_production_path(
                self.known_hosts,
                Path("/etc/abhaile"),
                regular_file=True,
                filesystem_root=self.filesystem_root,
                owner_uid=self.policy.root_uid,
            )
            validate_production_path(
                self.policy.fetch_identity,
                Path("/etc/abhaile"),
                regular_file=True,
                filesystem_root=self.filesystem_root,
                owner_uid=self.policy.root_uid,
            )
        trust_anchor = self.path.parent if self.allow_local_remote else self.filesystem_root
        validate_protected_chain(
            self.known_hosts,
            anchor=trust_anchor,
            owner_uid=self.policy.root_uid,
            regular_file=True,
        )
        validate_protected_chain(
            self.policy.fetch_identity,
            anchor=trust_anchor,
            owner_uid=self.policy.root_uid,
            regular_file=True,
        )
        actual_pins = tuple(
            line.strip()
            for line in self.known_hosts.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        if not self.policy.known_host_pins or actual_pins != self.policy.known_host_pins:
            raise TrustError("Pinned Git known_hosts content does not match protected policy")

    def _validate_remote_transport(self) -> None:
        if self.allow_local_remote:
            return
        parsed = urlsplit(self.policy.remote_url)
        if (
            parsed.scheme != "ssh"
            or not parsed.hostname
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.hostname != self.policy.remote_host
            or (parsed.username or None) != self.policy.remote_user
            or (parsed.port or 22) != self.policy.remote_port
        ):
            raise TrustError("Git remote does not match the pinned SSH transport policy")

    def _ssh_command(self) -> str:
        return (
            "ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
            f"-o {shlex.quote(f'IdentityFile={self.policy.fetch_identity}')} "
            f"-o {shlex.quote(f'UserKnownHostsFile={self.known_hosts}')} -o GlobalKnownHostsFile=/dev/null"
        )

    def _resolve(self, ref: str) -> str:
        result = self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        self._require(result, f"resolve {ref}")
        revision = result.stdout.strip()
        if not FULL_OID.fullmatch(revision):
            raise TrustError(f"Trusted ref did not resolve to a full commit: {ref}")
        return revision

    def _optional_resolve(self, ref: str) -> str | None:
        result = self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        return result.stdout.strip() if result.returncode == 0 else None

    def _git(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        return self.runner(
            ("git", f"--git-dir={self.path}", *arguments),
            env=env,
            input_text=input_text,
        )

    @staticmethod
    def _require(result: CommandResult, operation: str) -> None:
        if result.returncode != 0:
            raise TrustError(f"Failed to {operation}")
