"""Integration tests for scripts/install-abhaile-entrypoints."""

from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess
from pathlib import Path

import pytest

INSTALLER_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install-abhaile-entrypoints"
BOOTSTRAP_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap.sh"
RUNNER_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "abhaile-runner"

ENTRYPOINTS: dict[str, str] = {
    "abhaile-render": "abhaile.cli.render",
    "abhaile-apply": "abhaile.cli.apply",
    "abhaile-diff": "abhaile.cli.diff",
    "abhaile-inventory": "abhaile.cli.inventory",
    "abhaile-health": "abhaile.cli.health",
}


@pytest.fixture
def installer_repo(tmp_path: Path) -> Path:
    """Create a minimal repository layout for entrypoint installer tests."""
    repo = tmp_path / "repo"
    venv_bin = repo / ".venv" / "bin"
    cli_dir = repo / "src" / "abhaile" / "cli"

    cli_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)

    for module in ENTRYPOINTS.values():
        leaf = module.rsplit(".", 1)[-1]
        (cli_dir / f"{leaf}.py").write_text("def main() -> int:\n    return 0\n")

    python_path = venv_bin / "python"
    python_path.write_text("#!/usr/bin/env bash\nexit 0\n")
    python_path.chmod(0o755)

    return repo


def _installer_env(repo: Path) -> dict[str, str]:
    """Build environment overrides for running the installer in tests."""
    user = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name
    env = os.environ.copy()
    env.update(
        {
            "ABHAILE_REPO_DIR": str(repo),
            "ABHAILE_VENV_BIN": str(repo / ".venv" / "bin"),
            "ABHAILE_PYTHON": str(repo / ".venv" / "bin" / "python"),
            "ABHAILE_SRC": str(repo / "src"),
            "ABHAILE_OWNER": user,
            "ABHAILE_GROUP": group,
        }
    )
    return env


def _run_installer(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the installer with test-local layout overrides."""
    return subprocess.run(
        ["bash", str(INSTALLER_SCRIPT)],
        cwd=repo,
        env=_installer_env(repo),
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.integration
class TestInstallEntrypoints:
    """Validate managed entrypoint synchronization behavior."""

    def test_fresh_install_creates_all_wrappers(self, installer_repo: Path) -> None:
        """Fresh installer run writes each expected wrapper."""
        result = _run_installer(installer_repo)
        assert result.returncode == 0, result.stdout + result.stderr

        venv_bin = installer_repo / ".venv" / "bin"
        for name, module in ENTRYPOINTS.items():
            wrapper = venv_bin / name
            assert wrapper.exists()
            text = wrapper.read_text()
            assert "set -euo pipefail" in text
            assert f"from {module} import main" in text

    def test_rerun_is_idempotent(self, installer_repo: Path) -> None:
        """Re-running installer preserves managed wrapper content."""
        first = _run_installer(installer_repo)
        assert first.returncode == 0, first.stdout + first.stderr

        venv_bin = installer_repo / ".venv" / "bin"
        before = {name: (venv_bin / name).read_text() for name in ENTRYPOINTS}

        second = _run_installer(installer_repo)
        assert second.returncode == 0, second.stdout + second.stderr

        after = {name: (venv_bin / name).read_text() for name in ENTRYPOINTS}
        assert before == after

    def test_existing_wrappers_are_updated(self, installer_repo: Path) -> None:
        """Installer replaces stale managed wrapper content."""
        venv_bin = installer_repo / ".venv" / "bin"
        stale = venv_bin / "abhaile-render"
        stale.write_text("#!/usr/bin/env bash\nexit 99\n")
        stale.chmod(0o755)

        result = _run_installer(installer_repo)
        assert result.returncode == 0, result.stdout + result.stderr

        text = stale.read_text()
        assert "managed-by: abhaile-entrypoints-v1" in text
        assert "from abhaile.cli.render import main" in text

    def test_newly_added_wrapper_is_created_on_existing_host(self, installer_repo: Path) -> None:
        """Installer adds missing wrappers while keeping existing ones."""
        venv_bin = installer_repo / ".venv" / "bin"
        for name in ("abhaile-render", "abhaile-apply"):
            path = venv_bin / name
            path.write_text("#!/usr/bin/env bash\nexit 0\n")
            path.chmod(0o755)

        result = _run_installer(installer_repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (venv_bin / "abhaile-health").exists()
        assert (venv_bin / "abhaile-inventory").exists()
        assert (venv_bin / "abhaile-diff").exists()

    def test_obsolete_managed_wrappers_are_removed(self, installer_repo: Path) -> None:
        """Installer removes obsolete wrappers listed in prior managed manifest."""
        venv_bin = installer_repo / ".venv" / "bin"
        obsolete = venv_bin / "abhaile-obsolete"
        obsolete.write_text(
            "#!/usr/bin/env bash\n# managed-by: abhaile-entrypoints-v1\nset -euo pipefail\nexit 0\n"
        )
        obsolete.chmod(0o755)
        (venv_bin / ".abhaile-managed-entrypoints").write_text("abhaile-obsolete\nabhaile-render\n")

        result = _run_installer(installer_repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not obsolete.exists()

    def test_unrelated_files_are_preserved(self, installer_repo: Path) -> None:
        """Installer does not delete unrelated executables in .venv/bin."""
        venv_bin = installer_repo / ".venv" / "bin"
        unrelated = venv_bin / "custom-tool"
        unrelated.write_text("#!/usr/bin/env bash\nexit 0\n")
        unrelated.chmod(0o755)

        result = _run_installer(installer_repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert unrelated.exists()

    def test_wrappers_have_expected_mode_and_content(self, installer_repo: Path) -> None:
        """Installer writes wrappers with mode 0755 and expected runtime content."""
        result = _run_installer(installer_repo)
        assert result.returncode == 0, result.stdout + result.stderr

        health_wrapper = installer_repo / ".venv" / "bin" / "abhaile-health"
        wrapper_mode = stat.S_IMODE(health_wrapper.stat().st_mode)
        assert wrapper_mode == 0o755

        text = health_wrapper.read_text()
        assert 'export PYTHONPATH="' in text
        assert "${PYTHONPATH:+:$PYTHONPATH}" in text
        assert 'exec "' in text
        assert "from abhaile.cli.health import main" in text

    def test_missing_python_fails_clearly(self, installer_repo: Path) -> None:
        """Installer fails with a clear message when virtualenv python is unavailable."""
        (installer_repo / ".venv" / "bin" / "python").unlink()

        result = _run_installer(installer_repo)
        assert result.returncode != 0
        assert "Missing virtualenv python executable" in result.stdout

    def test_missing_module_fails_clearly(self, installer_repo: Path) -> None:
        """Installer fails with a clear message when a mapped source module is missing."""
        (installer_repo / "src" / "abhaile" / "cli" / "health.py").unlink()

        result = _run_installer(installer_repo)
        assert result.returncode != 0
        assert "Required module file missing" in result.stdout

    def test_no_editable_or_package_install_dependency(self) -> None:
        """Entrypoint sync path does not rely on editable/package installation commands."""
        installer_text = INSTALLER_SCRIPT.read_text(encoding="utf-8")
        bootstrap_text = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        runner_text = RUNNER_SCRIPT.read_text(encoding="utf-8")

        assert "pip install -e" not in installer_text
        assert "pip install -e" not in runner_text
        assert "setuptools" not in installer_text
        assert "wheel" not in installer_text
        assert "install-abhaile-entrypoints" in bootstrap_text
