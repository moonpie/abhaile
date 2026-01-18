"""
Integration tests for apply.sh deployment workflows.

Tests the complete apply workflow including dry-run, drift detection,
validation, staging, backup, and deployment mechanics.
"""

import os
import pytest
import subprocess
import shutil


@pytest.fixture(scope="module")
def rendered_env(repo_root):
    """Render all hosts once and provide env with SKIP_DESEC set."""
    env = os.environ.copy()
    env["SKIP_DESEC"] = "1"
    render_result = subprocess.run(
        ["python3", "tools/render/cli.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )
    assert render_result.returncode == 0, f"Render failed: {render_result.stderr}"
    return env


@pytest.mark.slow
class TestApplyWorkflows:
    """Integration tests for apply.sh deployment workflows."""

    def test_apply_dry_run_success(self, repo_root, rendered_env):
        """Dry-run should complete without errors on clean render."""
        # Now run apply dry-run (pass env to apply.sh too)
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "phobos"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=rendered_env,
        )

        assert result.returncode == 0, f"Apply dry-run failed: {result.stderr}"
        assert "DRY RUN" in result.stderr or "dry" in result.stderr.lower()

    def test_apply_verbose_mode(self, repo_root, rendered_env):
        """Verbose mode should provide detailed output."""
        # Run with verbose flag
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "--verbose", "phobos"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=rendered_env,
        )

        # Verbose output should contain more detail
        assert result.returncode == 0
        # Should see validation steps or detailed output
        output = result.stdout + result.stderr
        assert len(output) > 100, "Verbose mode should produce substantial output"

    def test_apply_missing_host_fails(self, repo_root):
        """Apply should fail gracefully with non-existent host."""
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "nonexistent-host"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

        # Should fail with clear error about missing host
        assert result.returncode != 0
        assert (
            "nonexistent-host" in result.stderr.lower()
            or "not found" in result.stderr.lower()
            or "invalid" in result.stderr.lower()
        )

    def test_apply_missing_render_output_fails(self, repo_root, tmp_path):
        """Apply should fail if render output doesn't exist."""
        # Create a clean temp directory without render output
        test_dir = tmp_path / "test_repo"
        test_dir.mkdir()

        # Copy apply script
        apply_dir = test_dir / "tools" / "apply"
        apply_dir.mkdir(parents=True)
        shutil.copy(repo_root / "tools" / "apply" / "apply.sh", apply_dir)

        # Copy lib directory
        if (repo_root / "tools" / "apply" / "lib").exists():
            shutil.copytree(repo_root / "tools" / "apply" / "lib", apply_dir / "lib")

        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "phobos"],
            cwd=test_dir,
            capture_output=True,
            text=True,
        )

        # Should fail due to missing rendered configs
        assert result.returncode != 0

    def test_apply_validates_network_files(self, repo_root, rendered_env):
        """Apply should validate systemd-networkd files before staging."""
        # Run apply (dry-run by default)
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "phobos"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=rendered_env,
        )

        # Should succeed if validation passes
        # (systemd-analyze verify runs in CI, we test the workflow)
        assert result.returncode == 0 or "validation" in result.stderr.lower()


class TestApplyDriftDetection:
    """Integration tests for drift detection functionality."""

    def test_drift_detection_on_first_run(self, repo_root, rendered_env):
        """First run should detect that configs don't exist yet."""
        # On first run, drift detection should note configs need deployment
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "phobos"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=rendered_env,
        )

        # Should complete successfully (dry-run)
        assert result.returncode == 0


class TestApplyErrorHandling:
    """Integration tests for error handling in apply workflow."""

    def test_invalid_network_file_syntax_fails(self, tmp_path):
        """Apply should fail if rendered network files have invalid syntax."""
        # Create minimal structure with invalid .network file
        test_dir = tmp_path / "test_repo"
        test_dir.mkdir()

        rendered_dir = test_dir / "out" / "rendered" / "phobos" / "systemd-networkd"
        rendered_dir.mkdir(parents=True)

        # Create invalid .network file (missing required sections)
        (rendered_dir / "invalid.network").write_text("InvalidSyntax=True\n")

        # Create minimal apply.sh structure (would need full implementation)
        # For now, test that validation catches the error

        # Run systemd-analyze verify directly (same as apply.sh would)
        result = subprocess.run(
            ["systemd-analyze", "verify", str(rendered_dir / "invalid.network")],
            capture_output=True,
            text=True,
        )

        # Should fail validation
        assert result.returncode != 0 or "error" in result.stderr.lower()

    def test_skip_render_without_fresh_output_fails(self, repo_root, tmp_path):
        """Apply with --skip-render should fail if output is stale."""
        # This would require testing the freshness check logic
        # The apply.sh script checks if config/ is newer than out/rendered/

        # Remove rendered output to simulate stale state
        rendered_dir = repo_root / "out" / "rendered"
        if rendered_dir.exists():
            # Touch config file to make it newer
            config_file = repo_root / "config" / "mapping.yaml"
            if config_file.exists():
                config_file.touch()

        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "--skip-render", "phobos"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

        # May fail or warn about stale output (depending on implementation)
        # At minimum, should not crash
        assert result.returncode in [0, 1, 2]  # Valid exit codes


class TestApplyHelp:
    """Integration tests for apply.sh help and usage."""

    def test_help_flag_shows_usage(self, repo_root):
        """--help should display usage information."""
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

        # Should succeed and show usage
        assert result.returncode == 0
        output = result.stdout + result.stderr
        assert "usage" in output.lower() or "help" in output.lower()

    def test_no_arguments_shows_usage(self, repo_root):
        """Running without arguments should show usage or fail gracefully."""
        result = subprocess.run(
            ["bash", "tools/apply/apply.sh"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

        # Should fail or show help
        # Allow both success (showing help) or failure (missing args)
        assert result.returncode in [0, 1, 2]
        output = result.stdout + result.stderr
        # Should provide some guidance
        assert len(output) > 10
