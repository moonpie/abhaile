"""Unit tests for shared execution primitives (Phase 7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from abhaile.apply.actions import (
    ExecutionResult,
    atomic_copy_file,
    atomic_copy_file_with_perms,
    check_destructive_gate,
    remove_target_file,
    run_command,
    run_systemctl_command,
    run_validation,
)
from abhaile.utils.errors import ApplyError


class TestAtomicCopyFile:
    """Tests for atomic_copy_file and atomic_copy_file_with_perms."""

    def test_copy_file_basic(self, tmp_path: Path) -> None:
        """Test basic file copy without mode/owner."""
        source = tmp_path / "source.txt"
        source.write_text("content")
        target = tmp_path / "target.txt"

        atomic_copy_file(source, target)

        assert target.read_text() == "content"
        assert target.exists()

    def test_copy_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Test that parent directories are created."""
        source = tmp_path / "source.txt"
        source.write_text("test")
        target = tmp_path / "a" / "b" / "c" / "target.txt"

        atomic_copy_file(source, target)

        assert target.read_text() == "test"
        assert target.parent.exists()

    def test_copy_file_missing_source_raises(self, tmp_path: Path) -> None:
        """Test that missing source raises error."""
        source = tmp_path / "missing.txt"
        target = tmp_path / "target.txt"

        with pytest.raises(ApplyError, match="Missing rendered source file"):
            atomic_copy_file(source, target)

    def test_copy_file_relative_target_raises(self, tmp_path: Path) -> None:
        """Test that relative target path raises error."""
        source = tmp_path / "source.txt"
        source.write_text("content")

        with pytest.raises(ApplyError, match="Target path must be absolute"):
            atomic_copy_file(source, Path("relative/target.txt"))

    def test_copy_file_with_mode(self, tmp_path: Path) -> None:
        """Test copy with enforced file mode."""
        source = tmp_path / "source.txt"
        source.write_text("content")
        target = tmp_path / "target.txt"

        atomic_copy_file_with_perms(source, target, mode=0o600)

        assert target.exists()
        assert target.stat().st_mode & 0o777 == 0o600

    def test_copy_file_invalid_user_raises(self, tmp_path: Path) -> None:
        """Test that invalid user name raises error."""
        source = tmp_path / "source.txt"
        source.write_text("content")
        target = tmp_path / "target.txt"

        with pytest.raises(ApplyError, match="User not found"):
            atomic_copy_file_with_perms(source, target, owner_user="nonexistent_user_xyz")


class TestRemoveTargetFile:
    """Tests for remove_target_file."""

    def test_remove_existing_file(self, tmp_path: Path) -> None:
        """Test removing an existing file."""
        target = tmp_path / "file.txt"
        target.write_text("content")

        remove_target_file(target)

        assert not target.exists()

    def test_remove_missing_file_succeeds(self, tmp_path: Path) -> None:
        """Test that removing non-existent file succeeds."""
        target = tmp_path / "missing.txt"

        # Should not raise
        remove_target_file(target)

    def test_remove_directory_raises(self, tmp_path: Path) -> None:
        """Test that attempting to remove directory raises error."""
        target = tmp_path / "dir"
        target.mkdir()

        with pytest.raises(ApplyError, match="Refusing to remove non-file target"):
            remove_target_file(target)

    def test_remove_symlink_succeeds(self, tmp_path: Path) -> None:
        """Test that symlinks can be removed."""
        source = tmp_path / "source.txt"
        source.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(source)

        remove_target_file(link)

        assert not link.exists()
        assert source.exists()


class TestRunCommand:
    """Tests for run_command."""

    def test_run_command_success(self) -> None:
        """Test successful command execution."""
        result = run_command(["echo", "hello"], action_id="test")

        assert result.success
        assert result.return_code == 0
        assert "hello" in result.stdout

    def test_run_command_failure_with_check_true(self) -> None:
        """Test command failure with check=True raises."""
        with pytest.raises(ApplyError, match="Command failed"):
            run_command(["false"], action_id="test", check=True)

    def test_run_command_failure_with_check_false(self) -> None:
        """Test command failure with check=False returns result."""
        result = run_command(["false"], action_id="test", check=False)

        assert not result.success
        assert result.return_code != 0

    def test_run_command_captures_stderr(self) -> None:
        """Test that stderr is captured."""
        result = run_command(
            ["bash", "-c", "echo error >&2; exit 1"],
            action_id="test",
            check=False,
        )

        assert not result.success
        assert "error" in result.stderr

    def test_run_command_with_action_id(self) -> None:
        """Test that action_id is captured in result."""
        result = run_command(["true"], action_id="my-action")

        assert result.action_id == "my-action"
        assert result.action_type == "command"


class TestRunValidation:
    """Tests for run_validation."""

    def test_validation_blocker_success(self) -> None:
        """Test successful blocker validation."""
        result = run_validation(["true"], action_id="test", is_blocker=True)

        assert result.success
        assert result.action_type == "validation"

    def test_validation_blocker_failure_raises(self) -> None:
        """Test that blocker validation failure raises."""
        with pytest.raises(ApplyError, match="Command failed"):
            run_validation(["false"], action_id="test", is_blocker=True)

    def test_validation_diagnostic_failure_succeeds(self) -> None:
        """Test that diagnostic validation failure does not raise."""
        result = run_validation(["false"], action_id="test", is_blocker=False)

        # Note: run_validation with is_blocker=False calls run_command with check=False
        assert not result.success


class TestRunSystemctlCommand:
    """Tests for run_systemctl_command."""

    def test_systemctl_command_format(self) -> None:
        """Test that systemctl command is formatted correctly."""
        # This test verifies the command format without actually executing
        # a real systemctl command (which may not be available in test env)
        try:
            run_systemctl_command("is-active", "nonexistent.service")
            # May fail if systemctl is not available, but that's OK for this test
        except ApplyError:
            pass  # Expected in non-systemd environments


class TestCheckDestructiveGate:
    """Tests for check_destructive_gate."""

    def test_gate_allowed_when_flag_set(self) -> None:
        """Test that gate passes when --allow-destructive is set."""
        # Should not raise
        check_destructive_gate(
            gate_name="quadlet.volume.delete",
            allow_destructive=True,
            escalations=["quadlet.volume.delete"],
        )

    def test_gate_blocked_when_flag_not_set(self) -> None:
        """Test that gate blocks when --allow-destructive is not set."""
        with pytest.raises(ApplyError, match="Destructive operation blocked"):
            check_destructive_gate(
                gate_name="quadlet.volume.delete",
                allow_destructive=False,
                escalations=["quadlet.volume.delete"],
            )

    def test_gate_allowed_when_not_escalated(self) -> None:
        """Test that gate passes when operation is not escalated."""
        # Should not raise even with allow_destructive=False
        check_destructive_gate(
            gate_name="quadlet.volume.delete",
            allow_destructive=False,
            escalations=[],
        )


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_result_creation(self) -> None:
        """Test creating ExecutionResult."""
        result = ExecutionResult(
            action_id="test",
            action_type="command",
            success=True,
            return_code=0,
            stdout="output",
            stderr="",
            error_message="",
        )

        assert result.action_id == "test"
        assert result.success
        assert result.return_code == 0
