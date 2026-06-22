"""Integration tests for scripts/sops-bootstrap."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SOPS_BOOTSTRAP_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sops-bootstrap"


@pytest.mark.integration
class TestSopsBootstrap:
    """Test sealed secret artifact helper behavior."""

    def test_script_syntax_valid(self) -> None:
        """sops-bootstrap has valid bash syntax."""
        result = subprocess.run(
            ["bash", "-n", str(SOPS_BOOTSTRAP_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_validate_ignores_gitkeep_placeholders(self) -> None:
        """Validation ignores .gitkeep files used to preserve sealed directories."""
        if shutil.which("sops") is None:
            pytest.skip("sops is not installed")

        result = subprocess.run(
            [str(SOPS_BOOTSTRAP_SCRIPT), "validate"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_helper_operates_on_secrets_tree(self) -> None:
        """sops-bootstrap manages the generic secrets tree."""
        script = SOPS_BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'SECRETS_DIR="$REPO_ROOT/secrets"' in script
        assert "config/bootstrap/sealed" not in script
