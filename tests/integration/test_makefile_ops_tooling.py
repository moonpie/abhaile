"""Tests for operator Makefile target wiring."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def _dry_run(tmp_path: Path, *args: str) -> str:
    """Return the output from one dry-run Make invocation."""
    venv = tmp_path / "venv"
    venv.mkdir(exist_ok=True)
    result = subprocess.run(
        ["make", "--no-print-directory", "--dry-run", *args, f"VENV={venv}", "VENV_PYTHON=python"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_render_remains_render_only(tmp_path: Path) -> None:
    """Render all hosts without invoking reconciliation."""
    output = _dry_run(tmp_path, "render")
    assert "python -m abhaile.cli.render --all --output ./out" in output
    assert "ansible-playbook" not in output


@pytest.mark.parametrize("target", ["check", "validate-host"])
def test_host_check_renders_then_runs_ansible_check(tmp_path: Path, target: str) -> None:
    """Use Ansible check mode as the host-local read-only plan."""
    output = _dry_run(tmp_path, target, "HOST=phobos")
    assert "python -m abhaile.cli.render --host phobos --output ./out" in output
    assert "/usr/bin/ansible-playbook" in output
    assert "--check" in output
    assert '"abhaile_expected_host":"phobos"' in output
    assert "abhaile.cli.apply" not in output


def test_validate_renders_all_hosts_and_syntax_checks_playbook(tmp_path: Path) -> None:
    """Validate portable repository inputs without impersonating either host."""
    output = _dry_run(tmp_path, "validate")
    assert "python -m abhaile.cli.render --all --output ./out" in output
    assert output.count("/usr/bin/ansible-playbook") == 1
    assert "--syntax-check" in output
    assert "abhaile_expected_host" not in output
    assert "abhaile.cli.apply" not in output


def test_host_check_requires_host(tmp_path: Path) -> None:
    """Reject a host-scoped check without an explicit host."""
    venv = tmp_path / "venv"
    venv.mkdir()
    result = subprocess.run(
        ["make", "check", f"VENV={venv}", "VENV_PYTHON=python"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Usage: make check HOST=phobos" in result.stderr


def test_legacy_apply_and_diff_targets_are_absent(tmp_path: Path) -> None:
    """Do not retain obsolete Python mutation or applied-state commands."""
    for target in ("apply", "diff"):
        result = subprocess.run(
            ["make", "--dry-run", target, f"VENV={tmp_path / 'venv'}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


def test_docs_target_remains_inventory_only(tmp_path: Path) -> None:
    """Keep generated inventory documentation independent from reconciliation."""
    output = _dry_run(tmp_path, "docs")
    assert "python -m abhaile.cli.inventory --format markdown --output docs/INVENTORY.md" in output
