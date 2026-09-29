"""Supervise restricted renderers in nondelegated root-owned cgroup v2 boundaries."""

from __future__ import annotations

import os
import ctypes
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Callable, Protocol, Sequence

from abhaile.trust.errors import TrustError
from abhaile.trust.model import validate_protected_chain, validate_protected_path

CGROUP_ROOT = Path("/sys/fs/cgroup/abhaile-render")


class BoundaryCreationError(TrustError):
    """Report whether a failed child-cgroup creation was safely rolled back."""

    def __init__(self, message: str, *, recovered: bool) -> None:
        super().__init__(message)
        self.recovered = recovered


def _cgroup_filesystem(path: Path) -> None:
    """Require the Linux cgroup v2 superblock rather than lookalike control files."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        storage = ctypes.create_string_buffer(256)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.fstatfs(descriptor, ctypes.byref(storage)) != 0:
            raise TrustError("Render containment filesystem cannot be verified")
        if ctypes.c_long.from_buffer(storage).value != 0x63677270:
            raise TrustError("Render containment requires a cgroup v2 filesystem")
    finally:
        os.close(descriptor)


def _boot_identity() -> str:
    """Read the kernel boot identity only for privileged recovery evidence."""
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise TrustError("Render containment boot identity is unavailable") from None
    if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
        raise TrustError("Render containment boot identity is invalid")
    return value


class RenderBoundary(Protocol):
    """Keep renderer execution separate from root-observed quiescence."""

    def create(self, transaction: str) -> None: ...
    def run(self, command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> None: ...
    def verify_quiescent(self) -> None: ...
    def resume(self, transaction: str) -> None: ...
    def identity(self) -> tuple[int, int, str]: ...
    def retire(self, transaction: str, identity: tuple[int, int, str]) -> None: ...


class CgroupBoundary:
    """Retain a root-controlled cgroup until its renderer tree has exited."""

    def __init__(
        self,
        *,
        root: Path = CGROUP_ROOT,
        owner_uid: int = 0,
        sleep: Callable[[float], None] = time.sleep,
        interpreter: Path = Path("/usr/lib/abhaile-render-runtime/bin/python"),
        cgroup_mount: Path = Path("/sys/fs/cgroup"),
        filesystem_root: Path = Path("/"),
        filesystem_check: Callable[[Path], None] = _cgroup_filesystem,
        boot_identity: Callable[[], str] = _boot_identity,
    ) -> None:
        self.filesystem_check = filesystem_check
        self.boot_identity = boot_identity
        self.interpreter = interpreter
        self.cgroup_mount = cgroup_mount
        self.filesystem_root = filesystem_root
        self.root = root
        self.owner_uid = owner_uid
        self.sleep = sleep
        self.path: Path | None = None

    def create(self, transaction: str) -> None:
        """Create a unique nondelegated boundary before launching any renderer."""
        if len(transaction) != 32 or any(c not in "0123456789abcdef" for c in transaction):
            raise TrustError("Render containment transaction is invalid")
        self._validate_ancestor_controls()
        self.filesystem_check(self.root)
        path = self.root / transaction
        try:
            path.mkdir(mode=0o700)
        except OSError:
            raise TrustError("Render containment cannot be created") from None
        self.path = path
        identity: tuple[int, int] | None = None
        try:
            metadata = path.lstat()
            identity = (metadata.st_dev, metadata.st_ino)
            self._control("cgroup.events")
            self._control("cgroup.procs")
            self._control("cgroup.kill")
        except (OSError, TrustError):
            recovered = self._rollback_creation(path, identity) if identity is not None else False
            raise BoundaryCreationError(
                "Render containment controls cannot be validated", recovered=recovered
            ) from None

    def _rollback_creation(self, path: Path, identity: tuple[int, int]) -> bool:
        """Remove only the exact protected child created by this instance."""
        try:
            metadata = path.lstat()
            if (
                (metadata.st_dev, metadata.st_ino) != identity
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != self.owner_uid
                or metadata.st_mode & 0o022
            ):
                return False
            # No command can attach a process until create() returns successfully.
            path.rmdir()
        except OSError:
            return False
        self.path = None
        return True

    def _control(self, name: str) -> Path:
        """Validate every protected component before opening a kernel control."""
        if self.path is None:
            raise TrustError("Render containment is unavailable")
        path = self.path / name
        validate_protected_chain(
            path, anchor=self.root, owner_uid=self.owner_uid, regular_file=True
        )
        return path

    def resume(self, transaction: str) -> None:
        """Bind cleanup to a retained cgroup; never recreate missing evidence."""
        if len(transaction) != 32 or any(c not in "0123456789abcdef" for c in transaction):
            raise TrustError("Render containment transaction is invalid")
        self._validate_ancestor_controls()
        self.filesystem_check(self.root)
        self.path = self.root / transaction
        self.verify_quiescent()

    def _validate_ancestor_controls(self) -> None:
        """Reject delegation through writable ancestor migration controls."""
        validate_protected_chain(self.root, anchor=self.filesystem_root, owner_uid=self.owner_uid)
        try:
            relative = self.root.relative_to(self.cgroup_mount)
        except ValueError as exc:
            raise TrustError("Render cgroup is outside the fixed cgroup namespace") from exc
        current = self.cgroup_mount
        for component in (None, *relative.parts):
            if component is not None:
                current /= component
            validate_protected_path(
                current / "cgroup.procs",
                owner_uid=self.owner_uid,
                regular_file=True,
            )

    def run(self, command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> None:
        """Attach a root bootstrap child before executing the restricted renderer."""
        validate_protected_chain(
            self.interpreter,
            anchor=self.filesystem_root,
            owner_uid=self.owner_uid,
            regular_file=True,
        )
        descriptor = os.open(self._control("cgroup.procs"), os.O_WRONLY | os.O_NOFOLLOW)
        bootstrap = (
            "import os,sys; fd=int(sys.argv[1]); "
            "os.write(fd,str(os.getpid()).encode('ascii')); os.close(fd); "
            "os.execve(sys.argv[2],sys.argv[2:],dict(os.environ))"
        )
        try:
            result = subprocess.run(
                (str(self.interpreter), "-I", "-c", bootstrap, str(descriptor), *command),
                cwd=cwd,
                env=env,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=(descriptor,),
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError):
            raise TrustError("Protected renderer execution failed") from None
        finally:
            os.close(descriptor)
            self.terminate()
        if result.returncode:
            raise TrustError("Protected renderer execution failed")

    def terminate(self) -> None:
        """Kill surviving descendants and independently prove the cgroup is empty."""
        try:
            descriptor = os.open(self._control("cgroup.kill"), os.O_WRONLY | os.O_NOFOLLOW)
            try:
                os.write(descriptor, b"1")
            finally:
                os.close(descriptor)
            for _attempt in range(100):
                if self._populated() == 0:
                    return
                self.sleep(0.01)
        except OSError:
            raise TrustError("Render containment termination is ambiguous") from None
        raise TrustError("Render descendants remain active")

    def _populated(self) -> int:
        """Read the kernel's complete subtree population without trusting a PID."""
        descriptor = os.open(self._control("cgroup.events"), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(descriptor, 4097)
        finally:
            os.close(descriptor)
        try:
            if len(raw) > 4096:
                raise ValueError
            rows = [line.split() for line in raw.decode("ascii").splitlines()]
            if any(len(row) != 2 for row in rows):
                raise ValueError
            values = dict(rows)
            if len(values) != len(rows) or values.get("populated") not in {"0", "1"}:
                raise ValueError
            return int(values["populated"])
        except (UnicodeError, ValueError):
            raise TrustError("Render containment evidence is malformed") from None

    def verify_quiescent(self) -> None:
        """Refuse sealing or cleanup while any descendant remains in the boundary."""
        if self._populated() != 0:
            raise TrustError("Render descendants remain active")

    def identity(self) -> tuple[int, int, str]:
        """Bind persistent receipts to this exact retained cgroup inode."""
        self._control("cgroup.events")
        if self.path is None:
            raise TrustError("Render containment is unavailable")
        metadata = self.path.lstat()
        return metadata.st_dev, metadata.st_ino, self.boot_identity()

    def retire(self, transaction: str, identity: tuple[int, int, str]) -> None:
        """Retire an empty receipt-bound cgroup; retry absent groups only on the same boot."""
        if not re.fullmatch(r"[0-9a-f]{32}", transaction):
            raise TrustError("Render containment transaction is invalid")
        self._validate_ancestor_controls()
        self.filesystem_check(self.root)
        if identity[2] != self.boot_identity():
            raise TrustError("Render containment retirement boot identity changed")
        self.path = self.root / transaction
        try:
            self.path.lstat()
        except FileNotFoundError:
            return
        if self.identity() != identity:
            raise TrustError("Render containment retirement identity changed")
        self.verify_quiescent()
        try:
            # cgroupfs removes kernel controls itself; never recursively delete them.
            self.path.rmdir()
        except OSError:
            raise TrustError("Render containment retirement is incomplete") from None
