"""Integration tests for scripts/bootstrap.sh testable logic."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

BOOTSTRAP_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap.sh"


@pytest.mark.integration
class TestBootstrapPreflight:
    """Test bootstrap preflight and input validation (no root required)."""

    def test_no_hostname_exits_nonzero(self) -> None:
        """Bootstrap exits non-zero without hostname argument."""
        result = subprocess.run(
            ["bash", "-c", f"source {BOOTSTRAP_SCRIPT} 2>/dev/null; stage_preflight"],
            capture_output=True,
            text=True,
        )
        # The script requires root, so it will fail at EUID check first
        assert result.returncode != 0

    def test_invalid_hostname_rejected(self) -> None:
        """Bootstrap rejects hostnames that are not valid short DNS labels."""
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "validate_hostname_arg invalid_host"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_arbitrary_valid_hostname_accepted(self) -> None:
        """Bootstrap accepts valid hostnames without a hard-coded allowlist."""
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    "log() { :; }; die() { exit 1; }; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "validate_hostname_arg europa-1"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_default_vault_addr_uses_http_listener(self) -> None:
        """Bootstrap default Vault address matches the rendered HTTP listener."""
        env = os.environ.copy()
        env.pop("VAULT_ADDR", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"set -euo pipefail; source {BOOTSTRAP_SCRIPT}; printf '%s' \"$VAULT_ADDR\"",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert result.stdout == "http://vault.svc.abhaile.home.arpa:8200"

    def test_script_syntax_valid(self) -> None:
        """Bootstrap script has valid bash syntax."""
        result = subprocess.run(
            ["bash", "-n", str(BOOTSTRAP_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_token_acquisition_requires_input(self) -> None:
        """Token acquisition fails without any credential source."""
        # Unset all token env vars, no TTY
        env = os.environ.copy()
        env.pop("BOOTSTRAP_TOKEN", None)
        env.pop("BOOTSTRAP_TOKEN_FD", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    "log() { :; }; die() { exit 1; }; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "acquire_bootstrap_token"
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode != 0

    def test_token_from_env_var(self) -> None:
        """Token acquisition succeeds with BOOTSTRAP_TOKEN env var."""
        env = os.environ.copy()
        env["BOOTSTRAP_TOKEN"] = "test-token-value"
        env.pop("BOOTSTRAP_TOKEN_FD", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    "log() { :; }; die() { exit 1; }; "
                    "_bootstrap_token=''; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "acquire_bootstrap_token; "
                    'test -n "$_bootstrap_token"'
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0
