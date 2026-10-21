"""Integration tests for the reserved runner-unit installer."""

from __future__ import annotations

import fcntl
import grp
import os
import pwd
import stat
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "scripts" / "install-abhaile-runner-units"
UNIT_NAMES = (
    "abhaile-network-restore.service",
    "abhaile-runner.service",
    "abhaile-runner.timer",
)


@pytest.fixture
def runner_unit_layout(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """Create an accepted repository and isolated installation paths."""
    repo = tmp_path / "repo"
    sources = repo / "config" / "hosts" / "common" / "systemd"
    state = tmp_path / "runner"
    systemd = tmp_path / "systemd"
    sources.mkdir(parents=True)
    state.mkdir()
    systemd.mkdir()
    for name in UNIT_NAMES:
        (sources / name).write_text(f"[Unit]\nDescription={name}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (state / "last-successful-commit").write_text(f"{commit}\n", encoding="utf-8")
    (state / "lock").touch()
    return repo, state, systemd, commit


def _helpers(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create deterministic systemctl and systemd-analyze test doubles."""
    systemctl_log = tmp_path / "systemctl.log"
    analyze_log = tmp_path / "analyze.log"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "$*" >> "${TEST_SYSTEMCTL_LOG}"\n'
        'if [[ "$1" == "is-active" ]]; then\n'
        '  [[ "$2" == "abhaile-runner.timer" ]] '
        "&& printf '%s\\n' \"${TEST_TIMER_STATE:-inactive}\" "
        "|| printf '%s\\n' \"${TEST_SERVICE_STATE:-inactive}\"\n"
        "  exit 3\n"
        "fi\n"
        '[[ "$1" == "list-jobs" ]] && exit "${TEST_LIST_JOBS_STATUS:-0}"\n'
        '[[ "$1" == "daemon-reload" ]] && exit 0\n'
        "exit 2\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    analyze = tmp_path / "systemd-analyze"
    analyze.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" > "${TEST_ANALYZE_LOG}"\n',
        encoding="utf-8",
    )
    analyze.chmod(0o755)
    return systemctl, systemctl_log, analyze_log


def _run_installer(
    layout: tuple[Path, Path, Path, str],
    tmp_path: Path,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    """Run the installer against isolated paths."""
    repo, state, systemd, commit = layout
    user = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name
    systemctl, systemctl_log, analyze_log = _helpers(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "ABHAILE_REPO_DIR": str(repo),
            "ABHAILE_RUNNER_STATE_DIR": str(state),
            "ABHAILE_SYSTEMD_DIR": str(systemd),
            "ABHAILE_OWNER": user,
            "ABHAILE_TARGET_OWNER": user,
            "ABHAILE_TARGET_GROUP": group,
            "ABHAILE_SYSTEMCTL": str(systemctl),
            "ABHAILE_SYSTEMD_ANALYZE": str(tmp_path / "systemd-analyze"),
            "TEST_SYSTEMCTL_LOG": str(systemctl_log),
            "TEST_ANALYZE_LOG": str(analyze_log),
        }
    )
    env.update(overrides)
    return subprocess.run(
        ["bash", str(INSTALLER), commit],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.integration
class TestInstallRunnerUnits:
    """Validate explicit reserved-unit publication boundaries."""

    def test_installs_closed_unit_set_without_activation(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Publish only fixed runner units and reload the manager."""
        result = _run_installer(runner_unit_layout, tmp_path)
        _, _, systemd, _ = runner_unit_layout

        assert result.returncode == 0, result.stdout + result.stderr
        for name in UNIT_NAMES:
            target = systemd / name
            assert target.read_text(encoding="utf-8") == f"[Unit]\nDescription={name}\n"
            assert stat.S_IMODE(target.stat().st_mode) == 0o644
        systemctl_calls = (tmp_path / "systemctl.log").read_text(encoding="utf-8")
        assert "daemon-reload" in systemctl_calls
        assert "enable" not in systemctl_calls
        assert "start" not in systemctl_calls
        assert "verify" in (tmp_path / "analyze.log").read_text(encoding="utf-8")

    def test_rerun_is_idempotent(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Allow an exact accepted revision to be republished safely."""
        first = _run_installer(runner_unit_layout, tmp_path)
        second = _run_installer(runner_unit_layout, tmp_path)

        assert first.returncode == 0, first.stdout + first.stderr
        assert second.returncode == 0, second.stdout + second.stderr

    def test_rejects_active_timer(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Require scheduling to remain quiescent during publication."""
        result = _run_installer(runner_unit_layout, tmp_path, TEST_TIMER_STATE="active")

        assert result.returncode == 1
        assert "Runner timer must be inactive" in result.stdout

    def test_rejects_deactivating_service(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Reject a runner whose stop operation has not completed."""
        result = _run_installer(runner_unit_layout, tmp_path, TEST_SERVICE_STATE="deactivating")

        assert result.returncode == 1
        assert "Runner service must be inactive or failed" in result.stdout

    def test_rejects_mismatched_last_successful(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Bind publication to the accepted repository revision."""
        _, state, _, _ = runner_unit_layout
        (state / "last-successful-commit").write_text(f"{'0' * 40}\n", encoding="utf-8")

        result = _run_installer(runner_unit_layout, tmp_path)

        assert result.returncode == 1
        assert "Last-successful commit does not match" in result.stdout

    def test_rejects_dirty_repository(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Do not publish locally modified content under an accepted HEAD."""
        repo, _, _, _ = runner_unit_layout
        source = repo / "config" / "hosts" / "common" / "systemd" / UNIT_NAMES[0]
        source.write_text("[Unit]\nDescription=locally modified\n", encoding="utf-8")

        result = _run_installer(runner_unit_layout, tmp_path)

        assert result.returncode == 1
        assert "Repository worktree is dirty" in result.stdout

    def test_rejects_symlink_target(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Refuse to publish through a redirected unit target."""
        _, _, systemd, _ = runner_unit_layout
        destination = tmp_path / "redirected"
        destination.write_text("unmanaged\n", encoding="utf-8")
        (systemd / UNIT_NAMES[0]).symlink_to(destination)

        result = _run_installer(runner_unit_layout, tmp_path)

        assert result.returncode == 1
        assert "Unit target is not a regular file" in result.stdout
        assert destination.read_text(encoding="utf-8") == "unmanaged\n"

    def test_rejects_symlink_lock_without_changing_destination(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Never follow an automation-owned lock while running with privilege."""
        _, state, _, _ = runner_unit_layout
        destination = tmp_path / "lock-destination"
        destination.write_text("preserve\n", encoding="utf-8")
        (state / "lock").unlink()
        (state / "lock").symlink_to(destination)

        result = _run_installer(runner_unit_layout, tmp_path)

        assert result.returncode == 1
        assert "Runner lock is not a regular file" in result.stdout
        assert destination.read_text(encoding="utf-8") == "preserve\n"

    def test_rejects_held_runner_lock(
        self, runner_unit_layout: tuple[Path, Path, Path, str], tmp_path: Path
    ) -> None:
        """Share the runner's nonblocking serialization boundary."""
        _, state, _, _ = runner_unit_layout
        with (state / "lock").open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = _run_installer(runner_unit_layout, tmp_path)

        assert result.returncode == 1
        assert "Runner lock is held" in result.stdout
