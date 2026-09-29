"""Exercise the cgroup kernel contract through isolated filesystem/process fixtures."""

from pathlib import Path
import os
import subprocess

import pytest

from abhaile.trust.containment import BoundaryCreationError, CgroupBoundary
from abhaile.trust.errors import TrustError


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    """Create synthetic kernel control files when a boundary directory is created."""
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.procs").write_text("")
    interpreter = tmp_path / "python"
    interpreter.write_text("protected interpreter fixture")
    interpreter.chmod(0o555)
    mkdir = Path.mkdir

    def kernel_mkdir(path, *args, **kwargs):
        mkdir(path, *args, **kwargs)
        if path.parent == root:
            for name, content in {
                "cgroup.events": "populated 0\nfrozen 0\n",
                "cgroup.procs": "",
                "cgroup.kill": "",
            }.items():
                (path / name).write_text(content)

    monkeypatch.setattr(Path, "mkdir", kernel_mkdir)
    result = CgroupBoundary(
        root=root,
        cgroup_mount=root,
        owner_uid=os.geteuid(),
        filesystem_root=tmp_path,
        interpreter=interpreter,
        sleep=lambda _duration: None,
        filesystem_check=lambda _root: None,
        boot_identity=lambda: "fixture-boot",
    )
    result.create("a" * 32)
    return result


def test_root_bootstrap_attaches_before_exec_and_suppresses_output(boundary, monkeypatch, tmp_path):
    """Keep root attachment outside repository code and inherited output channels."""

    def run(command, **kwargs):
        assert command[1:3] == ("-I", "-c")
        assert command[3].index("os.write") < command[3].index("os.execve")
        assert kwargs["pass_fds"] == (int(command[4]),)
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert "preexec_fn" not in kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    boundary.run(("/usr/sbin/runuser", "--user", "abhaile-render"), cwd=tmp_path, env={})
    boundary.verify_quiescent()
    assert (boundary.path / "cgroup.kill").read_text() == "1"


def test_descendants_block_sealing_even_after_callback_returns(boundary):
    """Use subtree population rather than direct process completion."""
    (boundary.path / "cgroup.events").write_text("populated 1\nfrozen 0\n")
    with pytest.raises(TrustError, match="descendants"):
        boundary.verify_quiescent()
    with pytest.raises(TrustError, match="descendants"):
        boundary.terminate()


def test_kill_waits_for_descendant_quiescence(boundary):
    """Wait for the kernel to observe exit after issuing subtree termination."""
    events = boundary.path / "cgroup.events"
    events.write_text("populated 1\n")
    boundary.sleep = lambda _duration: events.write_text("populated 0\n")
    boundary.terminate()


@pytest.mark.parametrize(
    "evidence",
    ["", "populated yes\n", "populated 0\npopulated 1\n", "populated 0 extra\n", "x" * 4097],
)
def test_malformed_kernel_evidence_fails_closed(boundary, evidence):
    """Never interpret malformed or truncated evidence as an empty process tree."""
    (boundary.path / "cgroup.events").write_text(evidence)
    with pytest.raises(TrustError, match="malformed"):
        boundary.verify_quiescent()


def test_failed_renderer_is_sanitized_and_terminated(boundary, monkeypatch, tmp_path):
    """Suppress subprocess exception payloads while still terminating descendants."""

    def fail(*args, **kwargs):
        raise subprocess.SubprocessError("PLACEHOLDER_SECRET_DO_NOT_EMIT")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(TrustError, match="execution failed") as error:
        boundary.run(("renderer",), cwd=tmp_path, env={})
    assert "PLACEHOLDER_SECRET" not in str(error.value)
    assert (boundary.path / "cgroup.kill").read_text() == "1"


def test_missing_or_replaced_control_is_not_quiescence(boundary, tmp_path):
    """Reject links before interpreting supposedly kernel-provided evidence."""
    events = boundary.path / "cgroup.events"
    events.unlink()
    target = tmp_path / "forged"
    target.write_text("populated 0\n")
    events.symlink_to(target)
    with pytest.raises(TrustError, match="symlink"):
        boundary.verify_quiescent()


def test_missing_old_cgroup_is_preserved_not_recreated(boundary):
    """A reboot or missing group invalidates cleanup proof."""
    with pytest.raises(TrustError, match="unavailable"):
        boundary.resume("b" * 32)
    assert not (boundary.root / ("b" * 32)).exists()


def test_ordinary_directory_cannot_impersonate_kernel_cgroup(tmp_path):
    """Require kernel filesystem type independently of control-file contents."""
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.procs").write_text("")
    boundary = CgroupBoundary(
        root=root, cgroup_mount=root, filesystem_root=tmp_path, owner_uid=os.geteuid()
    )
    with pytest.raises(TrustError, match="cgroup v2"):
        boundary.create("c" * 32)


def test_writable_ancestor_migration_control_is_rejected(tmp_path):
    """Reject a delegated ancestor that could accept renderer migration."""
    mount = tmp_path / "cgroup"
    root = mount / "abhaile-render"
    root.mkdir(parents=True)
    (mount / "cgroup.procs").write_text("")
    (root / "cgroup.procs").write_text("")
    (mount / "cgroup.procs").chmod(0o666)
    boundary = CgroupBoundary(
        root=root,
        cgroup_mount=mount,
        filesystem_root=tmp_path,
        owner_uid=os.geteuid(),
        filesystem_check=lambda _root: None,
    )
    with pytest.raises(TrustError, match="group/other writable"):
        boundary.create("d" * 32)


def test_control_validation_failure_removes_exact_new_child(boundary, monkeypatch):
    """Rollback a child that fails validation before any process can attach."""
    transaction = "b" * 32
    original_control = boundary._control
    original_rmdir = Path.rmdir

    def fail_control(name):
        if name == "cgroup.kill":
            raise TrustError("injected control failure")
        return original_control(name)

    def kernel_rmdir(path):
        for control in path.iterdir():
            control.unlink()
        original_rmdir(path)

    monkeypatch.setattr(boundary, "_control", fail_control)
    monkeypatch.setattr(Path, "rmdir", kernel_rmdir)
    with pytest.raises(BoundaryCreationError) as error:
        boundary.create(transaction)
    assert error.value.recovered is True
    assert boundary.path is None
    assert not (boundary.root / transaction).exists()
    monkeypatch.setattr(boundary, "_control", original_control)
    boundary.create(transaction)
    assert {path.name for path in boundary.root.iterdir() if path.is_dir()} == {
        "a" * 32,
        transaction,
    }


def test_control_validation_failure_preserves_replaced_child(boundary, monkeypatch):
    """Never remove a child whose inode no longer proves creation identity."""
    transaction = "c" * 32
    original_control = boundary._control

    def replace_then_fail(name):
        if name == "cgroup.kill":
            child = boundary.root / transaction
            for control in child.iterdir():
                control.unlink()
            child.rmdir()
            child.mkdir()
            raise TrustError("injected control failure")
        return original_control(name)

    monkeypatch.setattr(boundary, "_control", replace_then_fail)
    with pytest.raises(BoundaryCreationError) as error:
        boundary.create(transaction)
    assert error.value.recovered is False
    assert (boundary.root / transaction).exists()


def test_retirement_removes_only_empty_matching_cgroup(boundary, monkeypatch):
    """Model kernel rmdir control removal and permit interrupted same-boot retry."""
    identity = boundary.identity()
    original = Path.rmdir

    def kernel_rmdir(path):
        for control in path.iterdir():
            control.unlink()
        original(path)

    monkeypatch.setattr(Path, "rmdir", kernel_rmdir)
    boundary.retire("a" * 32, identity)
    assert not boundary.path.exists()
    boundary.retire("a" * 32, identity)


@pytest.mark.parametrize("mismatch", ["boot", "inode", "populated"])
def test_retirement_preserves_ambiguous_cgroup(boundary, mismatch):
    """Reject population or identity changes before retiring a retained group."""
    identity = boundary.identity()
    if mismatch == "boot":
        identity = (identity[0], identity[1], "another-boot")
    elif mismatch == "inode":
        identity = (identity[0], identity[1] + 1, identity[2])
    else:
        (boundary.path / "cgroup.events").write_text("populated 1\n")
    with pytest.raises(TrustError):
        boundary.retire("a" * 32, identity)
    assert boundary.path.exists()
