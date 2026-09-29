"""Test explicit bounded cleanup using synthetic protected cgroup receipts."""

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from abhaile.trust.errors import TrustError
from abhaile.trust.orphans import cleanup_orphans, record_orphan


class Boundary:
    """Model independently observed kernel population and boot-bound identity."""

    populated = False
    boot = "first-boot"

    def create(self, transaction):
        pass

    def run(self, command: Any, *, cwd: Path, env: dict[str, str]) -> None:
        raise AssertionError("Orphan cleanup never launches a renderer")

    def resume(self, transaction):
        self.verify_quiescent()

    def verify_quiescent(self):
        if self.populated:
            raise TrustError("Render descendants remain active")

    def identity(self):
        return 1, 2, self.boot

    def retire(self, transaction, identity):
        if identity != self.identity():
            raise TrustError("Containment retirement identity changed")
        self.verify_quiescent()
        self.retired = True


@pytest.fixture
def orphan(tmp_path):
    """Create renderer scratch and a root-only recovery receipt under a fixture root."""
    root = tmp_path / "quarantine"
    root.mkdir(mode=0o700)
    scratch = root / (".render-orphan." + "a" * 40 + "." + "b" * 32)
    rendered = scratch / "rendered"
    rendered.mkdir(parents=True)
    (rendered / "artifact").write_text("fixture")
    boundary = Boundary()
    record_orphan(root, scratch, boundary)
    return root, scratch, boundary


def clean(root, boundary, **kwargs):
    """Invoke explicit local fixture cleanup with the fixture owner's identity."""
    return cleanup_orphans(
        root,
        boundary,
        root_uid=os.geteuid(),
        render_uid=os.geteuid(),
        namespace=Path("/quarantine"),
        filesystem_root=root.parent,
        **kwargs,
    )


def test_dry_run_retains_receipts_and_scratch(orphan):
    """Never garbage collect as a side effect of preview."""
    root, scratch, boundary = orphan
    assert clean(root, boundary) == ()
    assert scratch.is_dir()
    assert len(list(root.iterdir())) == 2


def test_cleanup_removes_only_associated_scratch_and_is_retry_safe(orphan):
    """Remove proven scratch while retaining legacy unassociated orphan content."""
    root, scratch, boundary = orphan
    legacy = root / (".render-orphan." + "c" * 40 + "." + "d" * 32)
    legacy.mkdir()
    assert clean(root, boundary, dry_run=False) == (scratch.name,)
    assert boundary.retired
    assert clean(root, boundary, dry_run=False) == ()
    assert legacy.exists()


def test_live_descendants_preserve_scratch(orphan):
    """Retain the entire candidate when complete tree quiescence is not established."""
    root, scratch, boundary = orphan
    boundary.populated = True
    with pytest.raises(TrustError, match="descendants"):
        clean(root, boundary, dry_run=False)
    assert (scratch / "rendered/artifact").exists()


def test_reboot_invalidates_receipt(orphan):
    """Do not confuse inode reuse in a later boot with the original empty cgroup."""
    root, scratch, boundary = orphan
    boundary.boot = "second-boot"
    with pytest.raises(TrustError, match="evidence"):
        clean(root, boundary, dry_run=False)
    assert scratch.exists()


@pytest.mark.parametrize(
    "attack", ["symlink", "hardlink", "unexpected", "writable", "malformed-name", "receipt-link"]
)
def test_unsafe_orphans_fail_before_deletion(orphan, tmp_path, attack):
    """Reject malformed namespace entries, links, writable paths and aliases."""
    root, scratch, boundary = orphan
    artifact = scratch / "rendered/artifact"
    if attack == "symlink":
        artifact.unlink()
        artifact.symlink_to(tmp_path / "outside")
    elif attack == "hardlink":
        os.link(artifact, tmp_path / "alias")
    elif attack == "unexpected":
        (scratch / "unexpected").mkdir()
    elif attack == "writable":
        artifact.chmod(0o666)
    elif attack == "malformed-name":
        (root / ".render-orphan.bad").mkdir()
    else:
        receipt = root / (scratch.name + ".receipt")
        receipt.unlink()
        receipt.symlink_to(tmp_path / "outside")
    with pytest.raises(TrustError):
        clean(root, boundary, dry_run=False)
    assert scratch.exists()


def test_interrupted_tree_deletion_can_resume(orphan, monkeypatch):
    """Retain the inode receipt across partial recursive deletion for a safe retry."""
    import abhaile.trust.orphans as module

    root, scratch, boundary = orphan
    original = module.shutil.rmtree

    def interrupted(path):
        (path / "rendered/artifact").unlink()
        raise OSError("injected interruption")

    setattr(interrupted, "avoids_symlink_attacks", True)
    monkeypatch.setattr(module.shutil, "rmtree", interrupted)
    with pytest.raises(OSError, match="interruption"):
        clean(root, boundary, dry_run=False)
    assert (root / (scratch.name + ".receipt")).exists()
    monkeypatch.setattr(module.shutil, "rmtree", original)
    assert clean(root, boundary, dry_run=False) == (scratch.name,)


def test_receipt_only_interrupted_cleanup_can_resume(orphan):
    """Remove a durable receipt after an earlier cleanup removed the full tree."""
    root, scratch, boundary = orphan
    receipt = root / (scratch.name + ".receipt")
    original = receipt.read_bytes()
    shutil.rmtree(scratch)
    assert receipt.read_bytes() == original
    assert clean(root, boundary, dry_run=False) == (scratch.name,)
    assert not receipt.exists()


def test_wrong_owner_is_rejected_before_cleanup(orphan, monkeypatch):
    """Fail closed when receipt ownership no longer belongs to the protected identity."""
    root, scratch, boundary = orphan
    with pytest.raises(TrustError, match="owner"):
        cleanup_orphans(
            root,
            boundary,
            root_uid=os.geteuid() + 1,
            render_uid=os.geteuid(),
            namespace=Path("/quarantine"),
            filesystem_root=root.parent,
            dry_run=False,
        )
    assert scratch.exists()


def test_interrupted_retirement_retains_durable_intent(orphan, monkeypatch):
    """Retry cgroup retirement after scratch deletion without losing its receipt."""
    import json

    root, scratch, boundary = orphan
    original = boundary.retire

    def fail(*args):
        raise TrustError("injected retirement interruption")

    monkeypatch.setattr(boundary, "retire", fail)
    with pytest.raises(TrustError, match="interruption"):
        clean(root, boundary, dry_run=False)
    receipt = root / (scratch.name + ".receipt")
    assert json.loads(receipt.read_text())["retiring"] is True
    assert not scratch.exists()
    monkeypatch.setattr(boundary, "retire", original)
    assert clean(root, boundary, dry_run=False) == (scratch.name,)


def test_dry_run_does_not_retire_cgroup(orphan, monkeypatch):
    """Leave kernel containment untouched during previews."""
    root, _, boundary = orphan

    def forbidden(*args):
        raise AssertionError("dry-run retirement")

    monkeypatch.setattr(boundary, "retire", forbidden)
    assert clean(root, boundary, dry_run=True) == ()


def test_interruption_after_retirement_retries_without_resuming_removed_group(orphan, monkeypatch):
    """Use durable retirement intent when the cgroup is already gone on retry."""
    root, scratch, boundary = orphan
    receipt = root / (scratch.name + ".receipt")
    unlink = Path.unlink

    def interrupted(path, *args, **kwargs):
        if path == receipt:
            raise OSError("injected receipt removal interruption")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(OSError, match="interruption"):
        clean(root, boundary, dry_run=False)
    assert boundary.retired and receipt.exists()
    monkeypatch.setattr(Path, "unlink", unlink)

    def removed_group(transaction):
        raise AssertionError("Retired group must not be resumed")

    monkeypatch.setattr(boundary, "resume", removed_group)
    assert clean(root, boundary, dry_run=False) == (scratch.name,)
