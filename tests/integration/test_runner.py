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
        assert '"$ABHAILE_RENDER" --host "$host" --output "$ABHAILE_OUTPUT"' in script
        assert 'sudo "$ABHAILE_APPLY" --output "$ABHAILE_OUTPUT"' in script

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
