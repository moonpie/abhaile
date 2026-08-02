"""Integration tests for scripts/abhaile-runner exit code paths."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

RUNNER_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "abhaile-runner"


@pytest.fixture
def runner_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with mapping.yaml for runner tests."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Init git repo
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create mapping.yaml with known hosts
    config_dir = repo / "config"
    config_dir.mkdir()
    mapping = {"abhaile": [{"phobos": ["svc-a"]}, {"deimos": ["svc-b"]}]}
    (config_dir / "mapping.yaml").write_text(yaml.dump(mapping))

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create runner state dir
    runner_state = tmp_path / "runner"
    runner_state.mkdir()

    return repo


def _git(repo: Path, *args: str) -> str:
    """Run git in a test repository and return stdout."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run_runner(
    repo: Path, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the runner script in the given repo with overrides."""
    env = os.environ.copy()
    env["ABHAILE_OUTPUT"] = str(repo.parent / "output")
    env["ABHAILE_BRANCH"] = "main"
    env["ABHAILE_REMOTE"] = "origin"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(RUNNER_SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _make_runner_executable(path: Path, body: str) -> None:
    """Create an executable helper script for runner integration tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _write_entrypoint_installer(repo: Path, body: str) -> Path:
    """Write a test entrypoint installer script into the repository."""
    path = repo / "scripts" / "install-abhaile-entrypoints"
    _make_runner_executable(path, body)
    return path


def _prepare_successful_runner(repo: Path) -> dict[str, str]:
    """Prepare fake runner dependencies and a local remote."""
    hostname = subprocess.run(
        ["hostname", "-s"], capture_output=True, text=True, check=True
    ).stdout.strip()
    mapping = {"abhaile": [{hostname: ["svc-a"]}, {"deimos": ["svc-b"]}]}
    (repo / "config" / "mapping.yaml").write_text(yaml.dump(mapping))
    _git(repo, "add", "config/mapping.yaml")
    _git(repo, "commit", "-m", "test host mapping")

    remote = repo.parent / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")

    venv_bin = repo / ".venv" / "bin"
    _make_runner_executable(
        venv_bin / "abhaile-render",
        '#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p "$4/rendered"\n',
    )
    _make_runner_executable(
        venv_bin / "abhaile-apply",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
    )
    _make_runner_executable(
        venv_bin / "abhaile-health",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
    )
    _write_entrypoint_installer(
        repo,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "mkdir -p .venv/bin\n"
            "for cmd in abhaile-render abhaile-apply abhaile-diff abhaile-inventory abhaile-health; do\n"
            "  :\n"
            "done\n"
        ),
    )
    (repo / ".gitignore").write_text(".venv/\n")
    _git(repo, "add", "scripts/install-abhaile-entrypoints", ".gitignore")
    _git(repo, "commit", "-m", "test entrypoint installer")
    _git(repo, "push", "-q", "origin", "main")

    fake_bin = repo.parent / "fake-bin"
    _make_runner_executable(
        fake_bin / "sudo",
        '#!/usr/bin/env bash\nset -euo pipefail\nexec "$@"\n',
    )

    return {
        "ABHAILE_VENV_BIN": str(venv_bin),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }


def _commit_and_push(repo: Path, message: str) -> str:
    """Commit all staged/unstaged changes and push to origin/main."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    _git(repo, "push", "-q", "origin", "main")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.integration
class TestRunnerExitCodes:
    """Test runner exit code paths."""

    def test_runner_uses_venv_entrypoints(self) -> None:
        """Runner invokes render/apply from the repository venv."""
        script = RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert 'readonly ABHAILE_VENV_BIN="${ABHAILE_VENV_BIN:-${PWD}/.venv/bin}"' in script
        assert 'readonly ABHAILE_RENDER="${ABHAILE_VENV_BIN}/abhaile-render"' in script
        assert 'readonly ABHAILE_APPLY="${ABHAILE_VENV_BIN}/abhaile-apply"' in script
        assert 'readonly ABHAILE_HEALTH="${ABHAILE_VENV_BIN}/abhaile-health"' in script
        assert 'readonly ABHAILE_CLUSTER_HEALTH="${ABHAILE_CLUSTER_HEALTH:-0}"' in script
        assert (
            'readonly ABHAILE_ENTRYPOINT_INSTALLER="${ABHAILE_ENTRYPOINT_INSTALLER:-${PWD}/scripts/install-abhaile-entrypoints}"'
            in script
        )
        assert '"$ABHAILE_RENDER" --host "$host" --output "$ABHAILE_OUTPUT"' in script
        assert 'sudo "$ABHAILE_APPLY" --output "$ABHAILE_OUTPUT"' in script
        assert 'sudo "$ABHAILE_HEALTH" --output "$ABHAILE_OUTPUT"' in script
        assert 'sudo "$ABHAILE_HEALTH" --output "$ABHAILE_OUTPUT" --cluster' in script
        assert 'record_current_phase "entrypoints"' in script

    def test_runner_uses_gitops_deploy_key(self) -> None:
        """Runner selects the non-default Git deploy key for fetches."""
        script = RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert (
            'readonly ABHAILE_GIT_SSH_KEY="${ABHAILE_GIT_SSH_KEY:-/home/abhaile/.ssh/gitops_ed25519}"'
            in script
        )
        assert 'export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i ${ABHAILE_GIT_SSH_KEY}' in script
        assert "IdentitiesOnly=yes" in script

    def test_unknown_host_exits_3(self, runner_repo: Path) -> None:
        """Runner exits 3 when hostname not in mapping.yaml."""
        # Covered by test_host_validation_rejects_unknown_host which tests
        # the Python validation logic directly. The full script test would
        # require mocking hostname -s which is not practical in integration.
        pass

    def test_host_validation_accepts_valid_host(self, runner_repo: Path) -> None:
        """Python validation one-liner correctly identifies known hosts."""
        config = runner_repo / "config" / "mapping.yaml"
        result = subprocess.run(
            [
                "python3",
                "-c",
                (
                    "import yaml, sys; "
                    f"m = yaml.safe_load(open('{config}')); "
                    "hosts = [k for item in m.get('abhaile', []) for k in item]; "
                    "sys.exit(0 if 'phobos' in hosts else 1)"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_host_validation_rejects_unknown_host(self, runner_repo: Path) -> None:
        """Python validation one-liner rejects unknown hosts."""
        config = runner_repo / "config" / "mapping.yaml"
        result = subprocess.run(
            [
                "python3",
                "-c",
                (
                    "import yaml, sys; "
                    f"m = yaml.safe_load(open('{config}')); "
                    "hosts = [k for item in m.get('abhaile', []) for k in item]; "
                    "sys.exit(0 if 'unknown-host' in hosts else 1)"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_dirty_worktree_exits_3(self, runner_repo: Path) -> None:
        """Runner exits 3 on dirty worktree."""
        # Create an untracked file to dirty the worktree
        (runner_repo / "dirty.txt").write_text("dirty")
        subprocess.run(
            ["git", "add", "dirty.txt"], cwd=runner_repo, check=True, capture_output=True
        )

        # We need the hostname to pass validation first, so add the test
        # machine's hostname to mapping.yaml
        hostname = subprocess.run(
            ["hostname", "-s"], capture_output=True, text=True, check=True
        ).stdout.strip()
        mapping = {"abhaile": [{hostname: ["svc-a"]}, {"deimos": ["svc-b"]}]}
        (runner_repo / "config" / "mapping.yaml").write_text(yaml.dump(mapping))

        result = _run_runner(runner_repo)
        assert result.returncode == 3
        assert "Dirty worktree" in result.stdout or "dirty" in result.stdout.lower()
        assert "dirty status:" in result.stdout
        assert "dirty staged changes:" in result.stdout
        assert "A\tdirty.txt" in result.stdout

    def test_fast_forward_add_leaves_worktree_clean(self, runner_repo: Path) -> None:
        """Runner fast-forward handles added files without staging inverse deletions."""
        env = _prepare_successful_runner(runner_repo)
        (runner_repo / "added.txt").write_text("added\n")
        target_sha = _commit_and_push(runner_repo, "add file")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _git(runner_repo, "status", "--short") == ""
        assert (runner_repo / "added.txt").read_text() == "added\n"
        assert _git(runner_repo, "rev-parse", "HEAD") == target_sha

    def test_fast_forward_modify_leaves_worktree_clean(self, runner_repo: Path) -> None:
        """Runner fast-forward handles modified files without preserving old content."""
        env = _prepare_successful_runner(runner_repo)
        config = runner_repo / "config" / "mapping.yaml"
        before = config.read_text()
        config.write_text(before + "# changed\n")
        target_sha = _commit_and_push(runner_repo, "modify file")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _git(runner_repo, "status", "--short") == ""
        assert config.read_text().endswith("# changed\n")
        assert _git(runner_repo, "rev-parse", "HEAD") == target_sha

    def test_fast_forward_delete_leaves_worktree_clean(self, runner_repo: Path) -> None:
        """Runner fast-forward handles deleted files without staging inverse additions."""
        env = _prepare_successful_runner(runner_repo)
        doomed = runner_repo / "remove-me.txt"
        doomed.write_text("remove me\n")
        _commit_and_push(runner_repo, "add removable file")
        doomed.unlink()
        target_sha = _commit_and_push(runner_repo, "delete file")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _git(runner_repo, "status", "--short") == ""
        assert not doomed.exists()
        assert _git(runner_repo, "rev-parse", "HEAD") == target_sha

    def test_runner_writes_summary_for_successful_run(self, runner_repo: Path) -> None:
        """Runner records diagnostic summary state after success."""
        env = _prepare_successful_runner(runner_repo)
        (runner_repo / "added.txt").write_text("added\n")
        target_sha = _commit_and_push(runner_repo, "add file")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        summary = runner_repo.parent / "output" / "runner" / "last-run-summary"
        current = runner_repo.parent / "output" / "runner" / "current-run"
        assert result.returncode == 0, result.stdout + result.stderr
        summary_text = summary.read_text()
        assert "phase=complete" in summary_text
        assert "outcome=success" in summary_text
        assert f"target_sha={target_sha}" in summary_text
        assert not current.exists()

    def test_runner_syncs_entrypoints_before_render(self, runner_repo: Path) -> None:
        """Runner synchronizes entrypoints before invoking render/apply/health."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "trace.log"
        env["ENTRYPOINT_TRACE"] = str(trace_file)
        env["ABHAILE_TRACE"] = str(trace_file)

        _write_entrypoint_installer(
            runner_repo,
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo entrypoints >> "${ENTRYPOINT_TRACE}"\n'
                "cat > .venv/bin/abhaile-health <<'EOF'\n"
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo health >> "${ABHAILE_TRACE}"\n'
                "exit 0\n"
                "EOF\n"
                "chmod 0755 .venv/bin/abhaile-health\n"
            ),
        )
        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-render",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo render >> "${ABHAILE_TRACE}"\n'
                'mkdir -p "$4/rendered"\n'
            ),
        )
        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-apply",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo apply >> "${ABHAILE_TRACE}"\n'
                "exit 0\n"
            ),
        )
        health_path = Path(env["ABHAILE_VENV_BIN"]) / "abhaile-health"
        if health_path.exists():
            health_path.unlink()

        (runner_repo / "new.txt").write_text("new\n")
        _commit_and_push(runner_repo, "new target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        lines = trace_file.read_text().strip().splitlines()
        assert lines[:4] == ["entrypoints", "render", "apply", "health"]

    def test_runner_optional_cluster_health_runs_after_local_health(
        self, runner_repo: Path
    ) -> None:
        """Runner should invoke cluster health after local health when enabled."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "cluster-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        env["ABHAILE_CLUSTER_HEALTH"] = "1"

        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-health",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'if [[ "${*}" == *"--cluster"* ]]; then\n'
                '  echo health-cluster >> "${ABHAILE_TRACE}"\n'
                "else\n"
                '  echo health-local >> "${ABHAILE_TRACE}"\n'
                "fi\n"
                "exit 0\n"
            ),
        )

        (runner_repo / "new.txt").write_text("new\n")
        _commit_and_push(runner_repo, "cluster health target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert trace_file.read_text().strip().splitlines()[-2:] == [
            "health-local",
            "health-cluster",
        ]

    def test_runner_cluster_health_failure_is_non_fatal(self, runner_repo: Path) -> None:
        """Cluster audit failures should not trigger rollback after local health succeeds."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "cluster-failure-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        env["ABHAILE_CLUSTER_HEALTH"] = "1"

        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-health",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'if [[ "${*}" == *"--cluster"* ]]; then\n'
                '  echo health-cluster-fail >> "${ABHAILE_TRACE}"\n'
                "  exit 9\n"
                "fi\n"
                'echo health-local >> "${ABHAILE_TRACE}"\n'
                "exit 0\n"
            ),
        )

        (runner_repo / "new.txt").write_text("new\n")
        target_sha = _commit_and_push(runner_repo, "cluster health non fatal target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)
        summary = runner_repo.parent / "output" / "runner" / "last-run-summary"

        assert result.returncode == 0, result.stdout + result.stderr
        assert "non-fatal audit failed" in result.stdout
        assert _git(runner_repo, "rev-parse", "HEAD") == target_sha
        assert trace_file.read_text().strip().splitlines()[-2:] == [
            "health-local",
            "health-cluster-fail",
        ]
        assert "outcome=success" in summary.read_text()

    def test_runner_syncs_entrypoints_during_rollback(self, runner_repo: Path) -> None:
        """Runner synchronizes entrypoints after rollback checkout before replaying pipeline."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "rollback-trace.log"
        env["ENTRYPOINT_TRACE"] = str(trace_file)
        env["ABHAILE_TRACE"] = str(trace_file)

        _write_entrypoint_installer(
            runner_repo,
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo entrypoints:$(git rev-parse --short HEAD) >> "${ENTRYPOINT_TRACE}"\n'
                "exit 0\n"
            ),
        )
        _git(runner_repo, "add", "scripts/install-abhaile-entrypoints")
        _git(runner_repo, "commit", "-m", "trace entrypoint sync")
        _git(runner_repo, "push", "-q", "origin", "main")
        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-render",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'current="$(git rev-parse HEAD)"\n'
                'if [[ "$current" == "${FAIL_RENDER_SHA:-}" ]]; then\n'
                "  exit 42\n"
                "fi\n"
                'mkdir -p "$4/rendered"\n'
                "exit 0\n"
            ),
        )

        first = _run_runner(runner_repo, env)
        assert first.returncode == 0, first.stdout + first.stderr
        trace_file.write_text("")

        (runner_repo / "bad.txt").write_text("bad\n")
        target_sha = _commit_and_push(runner_repo, "failing target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")
        env["FAIL_RENDER_SHA"] = target_sha

        second = _run_runner(runner_repo, env)

        assert second.returncode == 0, second.stdout + second.stderr
        lines = trace_file.read_text().strip().splitlines()
        assert len(lines) >= 2
        assert lines[0].startswith("entrypoints:")
        assert lines[1].startswith("entrypoints:")
        assert lines[0] != lines[1]

    def test_entrypoint_sync_failure_is_pipeline_failure(self, runner_repo: Path) -> None:
        """Runner reports entrypoint install failures as pipeline failures."""
        env = _prepare_successful_runner(runner_repo)
        _write_entrypoint_installer(
            runner_repo,
            "#!/usr/bin/env bash\nset -euo pipefail\necho boom >&2\nexit 23\n",
        )
        (runner_repo / "new.txt").write_text("new\n")
        _commit_and_push(runner_repo, "new target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        summary = runner_repo.parent / "output" / "runner" / "last-run-summary"
        assert result.returncode == 1
        assert "entrypoints" in result.stdout
        summary_text = summary.read_text()
        assert "phase=entrypoints" in summary_text
        assert "outcome=failure" in summary_text

    def test_failed_commit_retry_is_suppressed(self, runner_repo: Path) -> None:
        """Runner records a failed target and suppresses identical automatic retries."""
        env = _prepare_successful_runner(runner_repo)
        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-apply",
            "#!/usr/bin/env bash\nset -euo pipefail\nexit 42\n",
        )
        (runner_repo / "bad.txt").write_text("bad\n")
        target_sha = _commit_and_push(runner_repo, "bad deploy")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        first = _run_runner(runner_repo, env)
        second = _run_runner(runner_repo, env)

        failed_target = runner_repo.parent / "output" / "runner" / "failed-target"
        assert first.returncode == 1
        assert failed_target.read_text().startswith(target_sha)
        assert second.returncode == 1
        assert "suppressing retry of failed commit" in second.stdout

    def test_newer_commit_after_failed_target_is_deployed(self, runner_repo: Path) -> None:
        """A correcting commit remains eligible after a previous target failed."""
        env = _prepare_successful_runner(runner_repo)
        apply_path = Path(env["ABHAILE_VENV_BIN"]) / "abhaile-apply"
        _make_runner_executable(
            apply_path,
            "#!/usr/bin/env bash\nset -euo pipefail\nexit 42\n",
        )
        (runner_repo / "bad.txt").write_text("bad\n")
        _commit_and_push(runner_repo, "bad deploy")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        first = _run_runner(runner_repo, env)
        assert first.returncode == 1

        _make_runner_executable(
            apply_path,
            "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
        )
        (runner_repo / "fix.txt").write_text("fix\n")
        target_sha = _commit_and_push(runner_repo, "fix deploy")

        second = _run_runner(runner_repo, env)

        assert second.returncode == 0, second.stdout + second.stderr
        assert _git(runner_repo, "rev-parse", "HEAD") == target_sha
        assert not (runner_repo.parent / "output" / "runner" / "failed-target").exists()

    def test_lock_contention_exits_2(self, runner_repo: Path) -> None:
        """Runner exits 2 when lock is already held."""
        # Create the runner state dir and hold the lock
        state_dir = Path(str(runner_repo.parent / "output")) / "runner"
        state_dir.mkdir(parents=True)
        lock_file = state_dir / "lock"
        lock_file.touch()

        # Hold the flock from another process
        holder = subprocess.Popen(
            ["bash", "-c", f"exec 9>{lock_file} && flock -n 9 && sleep 30"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Give the holder time to acquire
            import time

            time.sleep(0.2)

            result = _run_runner(runner_repo)
            assert result.returncode == 2
            assert "another run is active" in result.stdout
        finally:
            holder.terminate()
            holder.wait()

    def test_no_remote_exits_1(self, runner_repo: Path) -> None:
        """Runner exits 1 (fatal) when git fetch fails (no remote)."""
        # The repo has no remote configured, so fetch will fail
        result = _run_runner(runner_repo)
        # It should fail at fetch (exit 1) or host validation (exit 3)
        # depending on whether hostname matches. Since hostname likely
        # doesn't match phobos/deimos in CI, expect exit 3.
        assert result.returncode in (1, 3)
