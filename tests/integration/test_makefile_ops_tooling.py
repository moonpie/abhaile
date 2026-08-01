"""Tests for operator Makefile target wiring."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def run_make_dry_run(tmp_path: Path, *args: str) -> list[str]:
    """Run a Make target in dry-run mode and return printed recipe lines."""
    venv = tmp_path / "venv"
    venv.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "--dry-run",
            *args,
            f"VENV={venv}",
            "VENV_PYTHON=python",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def python_commands(lines: list[str]) -> list[str]:
    """Return only Abhaile Python entrypoint commands from Make output."""
    return [line for line in lines if line.startswith("python -m abhaile.cli.")]


class TestOpsToolingMakeTargets:
    """Tests for SPEC-2026-027 Makefile behaviour."""

    def test_render_is_render_only_for_all_hosts(self, tmp_path: Path) -> None:
        lines = run_make_dry_run(tmp_path, "render")

        assert python_commands(lines) == [
            "python -m abhaile.cli.render --all --output ./out",
        ]

    @pytest.mark.parametrize("host", ["phobos", "deimos"])
    def test_render_host_is_render_only_for_one_host(self, tmp_path: Path, host: str) -> None:
        lines = run_make_dry_run(tmp_path, "render-host", f"HOST={host}")

        assert python_commands(lines) == [
            f"python -m abhaile.cli.render --host {host} --output ./out",
        ]

    def test_validate_renders_all_hosts_then_dry_run_applies_supported_hosts(
        self, tmp_path: Path
    ) -> None:
        lines = run_make_dry_run(tmp_path, "validate")

        assert python_commands(lines) == [
            "python -m abhaile.cli.render --all --output ./out",
            "python -m abhaile.cli.apply --host phobos --output ./out/phobos --dry-run",
            "python -m abhaile.cli.apply --host deimos --output ./out/deimos --dry-run",
        ]
        assert "--allow-host-mismatch" not in "\n".join(lines)

    @pytest.mark.parametrize("host", ["phobos", "deimos"])
    def test_validate_host_renders_one_host_then_dry_run_applies_it(
        self, tmp_path: Path, host: str
    ) -> None:
        lines = run_make_dry_run(tmp_path, "validate-host", f"HOST={host}")

        assert python_commands(lines) == [
            f"python -m abhaile.cli.render --host {host} --output ./out",
            f"python -m abhaile.cli.apply --host {host} --output ./out --dry-run",
        ]

    def test_validate_host_without_host_fails_with_usage(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv"
        venv.mkdir()

        result = subprocess.run(
            ["make", "validate-host", f"VENV={venv}", "VENV_PYTHON=python"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "Usage: make validate-host HOST=phobos" in result.stderr
        assert "abhaile.cli.render" not in result.stdout
        assert "abhaile.cli.apply" not in result.stdout

    def test_host_mismatch_override_adds_only_flag_to_validate_dry_run_apply(
        self, tmp_path: Path
    ) -> None:
        lines = run_make_dry_run(tmp_path, "validate", "ALLOW_HOST_MISMATCH=1")

        assert lines == [
            "python -m abhaile.cli.render --all --output ./out",
            'echo "Host mismatch allowed for dry-run validation only."',
            "python -m abhaile.cli.apply --host phobos --output ./out/phobos --dry-run --allow-host-mismatch",
            "python -m abhaile.cli.apply --host deimos --output ./out/deimos --dry-run --allow-host-mismatch",
        ]

    def test_host_mismatch_override_adds_only_flag_to_validate_host_dry_run_apply(
        self, tmp_path: Path
    ) -> None:
        lines = run_make_dry_run(
            tmp_path,
            "validate-host",
            "HOST=phobos",
            "ALLOW_HOST_MISMATCH=1",
        )

        assert python_commands(lines) == [
            "python -m abhaile.cli.render --host phobos --output ./out",
            "python -m abhaile.cli.apply --host phobos --output ./out --dry-run --allow-host-mismatch",
        ]
        assert 'echo "Host mismatch allowed for dry-run validation only."' in lines

    @pytest.mark.parametrize("value", ["0", "true", "yes"])
    def test_host_mismatch_override_ignores_values_other_than_one(
        self, tmp_path: Path, value: str
    ) -> None:
        lines = run_make_dry_run(tmp_path, "validate", f"ALLOW_HOST_MISMATCH={value}")

        assert python_commands(lines) == [
            "python -m abhaile.cli.render --all --output ./out",
            "python -m abhaile.cli.apply --host phobos --output ./out/phobos --dry-run",
            "python -m abhaile.cli.apply --host deimos --output ./out/deimos --dry-run",
        ]
        assert "Host mismatch allowed" not in "\n".join(lines)

    def test_apply_remains_host_scoped_render_plus_dry_run_apply(self, tmp_path: Path) -> None:
        lines = run_make_dry_run(tmp_path, "apply", "HOST=phobos")

        assert python_commands(lines) == [
            "python -m abhaile.cli.render --host phobos --output ./out",
            "python -m abhaile.cli.apply --host phobos --output ./out --dry-run",
        ]

    def test_legacy_read_only_targets_remain_unchanged(self, tmp_path: Path) -> None:
        diff_lines = run_make_dry_run(tmp_path, "diff")
        docs_lines = run_make_dry_run(tmp_path, "docs")

        assert python_commands(diff_lines) == [
            "python -m abhaile.cli.diff --output ./out",
        ]
        assert python_commands(docs_lines) == [
            "python -m abhaile.cli.inventory --format markdown --output docs/INVENTORY.md",
        ]

    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("bootstrap-create", "scripts/sops-bootstrap create phobos vault-bootstrap"),
            ("bootstrap-edit", "scripts/sops-bootstrap edit phobos vault-bootstrap"),
            ("bootstrap-rotate", "scripts/sops-bootstrap rotate phobos vault-bootstrap"),
            ("bootstrap-validate", "scripts/sops-bootstrap validate"),
        ],
    )
    def test_bootstrap_targets_remain_unchanged(
        self, tmp_path: Path, target: str, expected: str
    ) -> None:
        args = [target]
        if target != "bootstrap-validate":
            args.extend(["HOST=phobos", "NAME=vault-bootstrap"])

        lines = run_make_dry_run(tmp_path, *args)

        assert expected in lines
