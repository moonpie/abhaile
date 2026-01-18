#!/usr/bin/env python3
"""Unit tests for state file validation logic in drift.sh and desec.sh."""

import subprocess
from pathlib import Path

import pytest


def run_bash_function(func_name: str, *args, script_path: Path) -> tuple[int, str, str]:
    """Run a bash function from a script and return (returncode, stdout, stderr)."""
    # Need to mock log_error for validation functions
    logging_mock = 'log_error() { echo "ERROR: $*" >&2; }'

    # Source the script and call the function
    cmd = f"{logging_mock} && source {script_path} && {func_name}"
    if args:
        cmd += " " + " ".join(f'"{arg}"' for arg in args)

    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class TestStateFileValidation:
    """Test state file format validation functions."""

    @pytest.fixture
    def drift_sh(self) -> Path:
        """Return path to drift.sh."""
        return (
            Path(__file__).parent.parent.parent.parent
            / "tools"
            / "apply"
            / "lib"
            / "drift.sh"
        )

    @pytest.fixture
    def desec_sh(self) -> Path:
        """Return path to desec.sh."""
        return (
            Path(__file__).parent.parent.parent.parent
            / "tools"
            / "apply"
            / "lib"
            / "desec.sh"
        )

    def test_validate_simple_state_file_valid(self, drift_sh: Path, tmp_path: Path):
        """Test validation of valid simple state file."""
        state_file = tmp_path / "test.state"
        state_file.write_text(
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2  phobos/file1.conf\n"
            "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef  deimos/file2.network\n"
        )

        rc, stdout, stderr = run_bash_function(
            "validate_simple_state_file",
            str(state_file),
            "test",
            script_path=drift_sh,
        )

        assert rc == 0, f"Expected success but got rc={rc}, stderr={stderr}"

    def test_validate_simple_state_file_invalid_hash(
        self, drift_sh: Path, tmp_path: Path
    ):
        """Test validation rejects invalid hash format."""
        state_file = tmp_path / "test.state"
        state_file.write_text("invalid_hash  phobos/file1.conf\n")

        rc, stdout, stderr = run_bash_function(
            "validate_simple_state_file",
            str(state_file),
            "test",
            script_path=drift_sh,
        )

        assert rc == 1, f"Expected failure but got rc={rc}"
        assert "Invalid" in stderr or "Invalid" in stdout

    def test_validate_simple_state_file_missing_path(
        self, drift_sh: Path, tmp_path: Path
    ):
        """Test validation rejects entry without path."""
        state_file = tmp_path / "test.state"
        state_file.write_text(
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2\n"
        )

        rc, stdout, stderr = run_bash_function(
            "validate_simple_state_file",
            str(state_file),
            "test",
            script_path=drift_sh,
        )

        assert rc == 1, f"Expected failure but got rc={rc}"

    def test_validate_simple_state_file_missing_ok(
        self, drift_sh: Path, tmp_path: Path
    ):
        """Test validation allows missing state file."""
        state_file = tmp_path / "nonexistent.state"

        rc, stdout, stderr = run_bash_function(
            "validate_simple_state_file",
            str(state_file),
            "test",
            script_path=drift_sh,
        )

        assert rc == 0, f"Expected success for missing file but got rc={rc}"

    def test_validate_services_state_file_valid(self, drift_sh: Path, tmp_path: Path):
        """Test validation of valid services.state file."""
        state_file = tmp_path / "services.state"
        state_file.write_text(
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2  phobos/services/caddy/Caddyfile  /opt/caddy/Caddyfile\n"
            "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef  deimos/services/vault/config.hcl  /home/vault/.config/vault/config.hcl\n"
        )

        rc, stdout, stderr = run_bash_function(
            "validate_services_state_file",
            str(state_file),
            script_path=drift_sh,
        )

        assert rc == 0, f"Expected success but got rc={rc}, stderr={stderr}"

    def test_validate_services_state_file_invalid_target(
        self, drift_sh: Path, tmp_path: Path
    ):
        """Test validation rejects services.state without absolute target path."""
        state_file = tmp_path / "services.state"
        state_file.write_text(
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2  phobos/services/caddy/Caddyfile  opt/caddy/Caddyfile\n"
        )

        rc, stdout, stderr = run_bash_function(
            "validate_services_state_file",
            str(state_file),
            script_path=drift_sh,
        )

        assert rc == 1, f"Expected failure but got rc={rc}"

    def test_validate_services_state_file_missing_target(
        self, drift_sh: Path, tmp_path: Path
    ):
        """Test validation rejects services.state without target path column."""
        state_file = tmp_path / "services.state"
        state_file.write_text(
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2  phobos/services/caddy/Caddyfile\n"
        )

        rc, stdout, stderr = run_bash_function(
            "validate_services_state_file",
            str(state_file),
            script_path=drift_sh,
        )

        assert rc == 1, f"Expected failure but got rc={rc}"

    def test_validate_desec_plan_valid(self, desec_sh: Path, tmp_path: Path):
        """Test validation of valid desec_plan.json."""
        plan_file = tmp_path / "desec_plan.json"
        plan_file.write_text(
            """{
                "create": [],
                "update": [],
                "delete": [],
                "desired_records": [
                    {"type": "A", "name": "test", "rdata": "192.168.1.1"}
                ]
            }"""
        )

        rc, stdout, stderr = run_bash_function(
            "validate_desec_plan",
            str(plan_file),
            script_path=desec_sh,
        )

        assert rc == 0, f"Expected success but got rc={rc}, stderr={stderr}"

    def test_validate_desec_plan_invalid_json(self, desec_sh: Path, tmp_path: Path):
        """Test validation rejects invalid JSON."""
        plan_file = tmp_path / "desec_plan.json"
        plan_file.write_text("{ invalid json }")

        rc, stdout, stderr = run_bash_function(
            "validate_desec_plan",
            str(plan_file),
            script_path=desec_sh,
        )

        assert rc == 1, f"Expected failure but got rc={rc}"

    def test_validate_desec_plan_missing_fields(self, desec_sh: Path, tmp_path: Path):
        """Test validation rejects plan missing required fields."""
        plan_file = tmp_path / "desec_plan.json"
        plan_file.write_text(
            """{
                "create": [],
                "update": []
            }"""
        )

        rc, stdout, stderr = run_bash_function(
            "validate_desec_plan",
            str(plan_file),
            script_path=desec_sh,
        )

        assert rc == 1, f"Expected failure but got rc={rc}"

    def test_validate_desec_plan_missing_file_ok(self, desec_sh: Path, tmp_path: Path):
        """Test validation allows missing plan file."""
        plan_file = tmp_path / "nonexistent.json"

        rc, stdout, stderr = run_bash_function(
            "validate_desec_plan",
            str(plan_file),
            script_path=desec_sh,
        )

        assert rc == 0, f"Expected success for missing file but got rc={rc}"
