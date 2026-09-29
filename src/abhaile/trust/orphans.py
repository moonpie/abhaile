"""Retain and explicitly collect render scratch using protected cgroup receipts."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from abhaile.trust.containment import RenderBoundary
from abhaile.trust.errors import TrustError
from abhaile.trust.model import validate_production_path, validate_protected_path

_NAME = re.compile(r"^\.render-orphan\.([0-9a-f]{40})\.([0-9a-f]{32})$")
_RECEIPT = re.compile(r"^(\.render-orphan\.[0-9a-f]{40}\.[0-9a-f]{32})\.receipt$")


def record_orphan(root: Path, scratch: Path, boundary: RenderBoundary) -> None:
    """Persist a root-owned receipt only after independent quiescence verification."""
    boundary.verify_quiescent()
    metadata = scratch.lstat()
    receipt = root / (scratch.name + ".receipt")
    content = json.dumps(
        {
            "version": 1,
            "scratch": [metadata.st_dev, metadata.st_ino],
            "cgroup": list(boundary.identity()),
        },
        sort_keys=True,
    ).encode("ascii")
    descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _sync(root)


def cleanup_orphans(
    root: Path,
    boundary: RenderBoundary,
    *,
    root_uid: int,
    render_uid: int,
    namespace: Path,
    filesystem_root: Path = Path("/"),
    dry_run: bool = True,
    limit: int = 32,
) -> tuple[str, ...]:
    """Remove bounded associated scratch; preserve legacy and ambiguous evidence."""
    if dry_run:
        return ()
    if not 1 <= limit <= 32:
        raise TrustError("Render orphan cleanup limit is invalid")
    validate_production_path(
        root,
        namespace,
        filesystem_root=filesystem_root,
        owner_uid=root_uid,
    )
    entries = {path.name: path for path in root.iterdir()}
    for name in entries:
        if not name.startswith(".render-orphan."):
            continue
        if _NAME.fullmatch(name) is None and _RECEIPT.fullmatch(name) is None:
            raise TrustError("Render orphan name is invalid")

    candidates: list[tuple[Path | None, Path, str, dict[str, object]]] = []
    receipt_names = sorted(name for name in entries if _RECEIPT.fullmatch(name))
    for receipt_name in receipt_names:
        receipt_match = _RECEIPT.fullmatch(receipt_name)
        assert receipt_match is not None
        scratch_name = receipt_match.group(1)
        scratch_match = _NAME.fullmatch(scratch_name)
        assert scratch_match is not None
        receipt = entries[receipt_name]
        path = entries.get(scratch_name)
        if len(candidates) >= limit:
            break
        validate_protected_path(receipt, owner_uid=root_uid, regular_file=True)
        try:
            if receipt.stat().st_size > 4096:
                raise ValueError
            evidence = json.loads(receipt.read_text(encoding="ascii"))
            if evidence.get("version") != 1:
                raise ValueError
            identity = evidence.get("cgroup")
            if not (
                isinstance(identity, list)
                and len(identity) == 3
                and _valid_inode_identity(identity[:2])
                and isinstance(identity[2], str)
            ):
                raise ValueError
            if evidence.get("retiring") is True:
                if path is not None:
                    raise ValueError
            else:
                boundary.resume(scratch_match.group(2))
                if identity != list(boundary.identity()):
                    raise ValueError
            if path is not None:
                metadata = path.lstat()
                if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
                    raise ValueError
                if evidence.get("scratch") != [metadata.st_dev, metadata.st_ino]:
                    raise ValueError
                _validate_tree(path, root_uid, render_uid)
            elif not _valid_inode_identity(evidence.get("scratch")):
                raise ValueError
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            raise TrustError("Render orphan evidence is invalid") from None
        candidates.append((path, receipt, scratch_match.group(2), evidence))

    # Canonically named Phase 1 orphans without receipts have no quiescence
    # evidence and remain retained. All receipt-backed work is bounded above.
    for name, path in entries.items():
        if _NAME.fullmatch(name) is None:
            continue
        if name + ".receipt" not in entries:
            metadata = path.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
                raise TrustError("Render orphan evidence is invalid")

    removed: list[str] = []
    for path, receipt, transaction, evidence in candidates:
        if evidence.get("retiring") is not True:
            boundary.resume(transaction)
            boundary.verify_quiescent()
            if evidence["cgroup"] != list(boundary.identity()):
                raise TrustError("Render orphan containment identity changed")
        if path is not None:
            # Quiescent renderers cannot race these operations. The parent is root-only.
            _validate_tree(path, root_uid, render_uid)
            if not shutil.rmtree.avoids_symlink_attacks:
                raise TrustError("Safe render orphan removal is unavailable")
            shutil.rmtree(path)
            _sync(root)
        if evidence.get("retiring") is not True:
            evidence["retiring"] = True
            _replace_receipt(root, receipt, evidence)
        identity = evidence["cgroup"]
        assert isinstance(identity, list)
        boundary.retire(transaction, (identity[0], identity[1], identity[2]))
        receipt.unlink()
        _sync(root)
        removed.append(receipt.name.removesuffix(".receipt"))
    return tuple(removed)


def _valid_inode_identity(value: object) -> bool:
    """Validate retained scratch identity after interrupted tree deletion."""
    return bool(
        isinstance(value, list)
        and len(value) == 2
        and all(type(part) is int and part >= 0 for part in value)
    )


def _validate_tree(root: Path, root_uid: int, render_uid: int) -> None:
    """Reject links, aliases, special entries, and excessive trees before removal."""
    pending = [root]
    count = 0
    while pending:
        path = pending.pop()
        count += 1
        if count > 10000:
            raise TrustError("Render orphan exceeds cleanup bound")
        metadata = path.lstat()
        if metadata.st_uid not in {root_uid, render_uid} or metadata.st_mode & 0o022:
            raise TrustError("Render orphan ownership or mode is invalid")
        if stat.S_ISDIR(metadata.st_mode):
            if path == root and any(child.name != "rendered" for child in path.iterdir()):
                raise TrustError("Render orphan contains unexpected entries")
            pending.extend(path.iterdir())
        elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise TrustError("Render orphan contains an unsupported entry")


def _sync(root: Path) -> None:
    """Persist receipt publication and interrupted deletion progress."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_receipt(root: Path, receipt: Path, evidence: dict[str, object]) -> None:
    """Publish retirement intent durably before removing its kernel evidence."""
    descriptor, name = tempfile.mkstemp(prefix=".orphan-receipt-update.", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            json.dump(evidence, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt)
        _sync(root)
    finally:
        temporary.unlink(missing_ok=True)
