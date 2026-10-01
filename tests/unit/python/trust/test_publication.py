"""Test descriptor-bound filesystem publication mechanics."""

import hashlib
import os
from pathlib import Path

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.publication import file_matches, publish_directory, publish_file


def test_file_publication_check_change_and_idempotence(tmp_path: Path) -> None:
    """Preview safely, publish atomically, and report unchanged reruns."""
    root = tmp_path / "root"
    parent = root / "etc"
    parent.mkdir(parents=True, mode=0o700)
    content = b"managed\n"
    digest = hashlib.sha256(content).hexdigest()
    target = str(parent / "config")
    preview = publish_file(
        root,
        target,
        content,
        sha256=digest,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
        check=True,
    )
    assert preview.changed and not Path(target).exists()
    first = publish_file(
        root,
        target,
        content,
        sha256=digest,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
        check=False,
    )
    second = publish_file(
        root,
        target,
        content,
        sha256=digest,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
        check=False,
    )
    assert first.changed and not second.changed
    assert Path(target).read_bytes() == content
    assert stat_mode(Path(target)) == 0o640
    assert file_matches(
        root,
        target,
        sha256=digest,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
    )
    assert not file_matches(
        root,
        target,
        sha256="0" * 64,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
    )


def test_disposable_root_maps_manifest_absolute_target(tmp_path: Path) -> None:
    """Map a production absolute target beneath an injected disposable root."""
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True, mode=0o700)
    content = b"mapped\n"
    result = publish_file(
        root,
        "/etc/example.conf",
        content,
        sha256=hashlib.sha256(content).hexdigest(),
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o600,
        check=False,
    )
    assert result.changed
    assert (root / "etc/example.conf").read_bytes() == content


def test_directory_publication_and_metadata_correction(tmp_path: Path) -> None:
    """Create and correct a directory through retained parent descriptors."""
    root = tmp_path / "root"
    (root / "srv").mkdir(parents=True, mode=0o700)
    target = str(root / "srv/service")
    assert publish_directory(
        root,
        target,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o750,
        check=False,
    ).changed
    assert not publish_directory(
        root,
        target,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o750,
        check=False,
    ).changed
    Path(target).chmod(0o700)
    assert publish_directory(
        root,
        target,
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o750,
        check=True,
    ).changed


@pytest.mark.parametrize("unsafe", ["linked-parent", "linked-target", "writable-parent"])
def test_publication_rejects_unsafe_paths(tmp_path: Path, unsafe: str) -> None:
    """Reject symlinked or writable ancestry and unexpected targets."""
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    parent = root / "etc"
    if unsafe == "linked-parent":
        parent.symlink_to(outside, target_is_directory=True)
        target = parent / "config"
    else:
        parent.mkdir(mode=0o700)
        target = parent / "config"
        if unsafe == "linked-target":
            target.symlink_to(outside / "config")
        else:
            parent.chmod(0o770)
    with pytest.raises(TrustError):
        publish_file(
            root,
            str(target),
            b"managed\n",
            sha256=hashlib.sha256(b"managed\n").hexdigest(),
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o600,
            check=False,
        )


def test_publication_rejects_source_digest_mismatch(tmp_path: Path) -> None:
    """Reject unsealed content before opening the target tree."""
    with pytest.raises(TrustError, match="source digest"):
        publish_file(
            tmp_path,
            str(tmp_path / "target"),
            b"content",
            sha256="0" * 64,
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o600,
            check=False,
        )


def stat_mode(path: Path) -> int:
    """Return permission bits for one test path."""
    return path.stat().st_mode & 0o7777
