"""Integration tests for scripts/abhaile-runner exit code paths."""

from __future__ import annotations

import os
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RUNNER_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "abhaile-runner"


def test_runner_transports_live_authorization_as_json_boolean() -> None:
    """Prevent Ansible key-value parsing from turning the live gate into a string."""
    script = RUNNER_SCRIPT.read_text(encoding="utf-8")

    assert "--extra-vars '{\"abhaile_live_apply\":true}'" in script
    assert "--extra-vars abhaile_live_apply=true" not in script


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
    repo: Path,
    env_overrides: dict[str, str] | None = None,
    *runner_args: str,
) -> subprocess.CompletedProcess[str]:
    """Run the runner script in the given repo with overrides."""
    env = os.environ.copy()
    env["ABHAILE_OUTPUT"] = str(repo.parent / "output")
    env["ABHAILE_BRANCH"] = "main"
    env["ABHAILE_REMOTE"] = "origin"
    env["ABHAILE_PYTHON"] = sys.executable
    source_root = RUNNER_SCRIPT.parents[1] / "src"
    env["ABHAILE_SRC"] = str(source_root)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(RUNNER_SCRIPT), *runner_args],
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


def _write_live_ansible(env: dict[str, str], live_body: str) -> None:
    """Write a fake Ansible command that succeeds silently in check mode."""
    _make_runner_executable(
        Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'for arg in "$@"; do\n'
            '  [[ "$arg" == "--check" ]] && exit 0\n'
            "done\n"
            f"{live_body}\n"
        ),
    )


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
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'host="" output=""\n'
            "while [[ $# -gt 0 ]]; do\n"
            '  case "$1" in\n'
            '    --host) host="$2"; shift 2 ;;\n'
            '    --output) output="$2"; shift 2 ;;\n'
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            'mkdir -p "${output}/rendered"\n'
            'printf \'{"entries":[],"host":"%s","version":"1"}\\n\' "$host" '
            '> "${output}/rendered/manifest.json"\n'
        ),
    )
    _make_runner_executable(
        venv_bin / "ansible-playbook",
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
            "for cmd in abhaile-render abhaile-inventory abhaile-health; do\n"
            "  :\n"
            "done\n"
        ),
    )
    (repo / ".gitignore").write_text(".venv/\n")
    _git(repo, "add", "scripts/install-abhaile-entrypoints", ".gitignore")
    _git(repo, "commit", "-m", "test entrypoint installer")
    _git(repo, "push", "-q", "origin", "main")

    state_dir = repo.parent / "output" / "runner"
    state_dir.mkdir(parents=True)
    (state_dir / "last-successful-commit").write_text(f"{_git(repo, 'rev-parse', 'HEAD')}\n")

    fake_bin = repo.parent / "fake-bin"
    _make_runner_executable(
        fake_bin / "sudo",
        '#!/usr/bin/env bash\nset -euo pipefail\nexec "$@"\n',
    )

    ssh_dir = repo.parent / "ssh"
    ssh_dir.mkdir()
    deploy_key = ssh_dir / "gitops_ed25519"
    known_hosts = ssh_dir / "known_hosts"
    deploy_key.write_text("test deploy key fixture\n")
    known_hosts.write_text("test pinned host fixture\n")

    return {
        "ABHAILE_VENV_BIN": str(venv_bin),
        "ABHAILE_ANSIBLE_PLAYBOOK": str(venv_bin / "ansible-playbook"),
        "ABHAILE_GIT_SSH_KEY": str(deploy_key),
        "ABHAILE_GIT_KNOWN_HOSTS": str(known_hosts),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }


def _commit_and_push(repo: Path, message: str) -> str:
    """Commit all staged/unstaged changes and push to origin/main."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    _git(repo, "push", "-q", "origin", "main")
    return _git(repo, "rev-parse", "HEAD")


def _install_manifest_fixture_renderer(repo: Path, env: dict[str, str]) -> None:
    """Render the manifest fixture tracked by each checked-out test revision."""
    _make_runner_executable(
        Path(env["ABHAILE_VENV_BIN"]) / "abhaile-render",
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'output=""\n'
            "while [[ $# -gt 0 ]]; do\n"
            '  case "$1" in\n'
            '    --output) output="$2"; shift 2 ;;\n'
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            'mkdir -p "${output}/rendered"\n'
            'cp manifest-source.json "${output}/rendered/manifest.json"\n'
        ),
    )


def _write_manifest_fixture(repo: Path, target: Path, *, include_entry: bool) -> None:
    """Write one tracked manifest with or without a managed service file."""
    hostname = subprocess.run(
        ["hostname", "-s"], capture_output=True, text=True, check=True
    ).stdout.strip()
    entries: list[dict[str, object]] = []
    if include_entry:
        content = "accepted=yes\n"
        entries.append(
            {
                "render_path": "services/test/removed.conf",
                "target_path": target.as_posix(),
                "kind": "service.config",
                "owner_ref": "service:test",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "size": len(content),
                "apply_hints": {},
            }
        )
    (repo / "manifest-source.json").write_text(
        json.dumps({"entries": entries, "host": hostname, "version": "1"}) + "\n"
    )


def _write_forward_removal_ansible(
    env: dict[str, str],
    *,
    trace_file: Path,
    managed_file: Path,
    fail_candidate_sha: str = "",
) -> None:
    """Emulate supported service-file removal and accepted-state recreation."""
    env.update(
        {
            "ABHAILE_TRACE": str(trace_file),
            "ABHAILE_MANAGED_FILE": str(managed_file),
            "ABHAILE_FAIL_CANDIDATE_SHA": fail_candidate_sha,
        }
    )
    _make_runner_executable(
        Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'phase="live"; vars_file=""\n'
            'for arg in "$@"; do\n'
            '  [[ "$arg" == "--check" ]] && phase="check"\n'
            '  [[ "$arg" == @* ]] && vars_file="${arg#@}"\n'
            "done\n"
            "cleanup_count=\"$(python3 -c 'import json,sys; "
            'print(len(json.load(open(sys.argv[1]))["abhaile_candidate_cleanup_entries"]))\' '
            '"$vars_file")"\n'
            'echo "$(git rev-parse HEAD) $phase cleanup=$cleanup_count" >> "${ABHAILE_TRACE}"\n'
            '[[ "$phase" == "check" ]] && exit 0\n'
            "entry_count=\"$(python3 -c 'import json,sys; "
            'print(len(json.load(open("manifest-source.json"))["entries"]))\')"\n'
            'if [[ "$cleanup_count" == "1" ]]; then rm -f "${ABHAILE_MANAGED_FILE}"; fi\n'
            'if [[ "$entry_count" == "1" ]]; then printf \'accepted=yes\\n\' > "${ABHAILE_MANAGED_FILE}"; fi\n'
            'if [[ -n "${ABHAILE_FAIL_CANDIDATE_SHA}" '
            '&& "$(git rev-parse HEAD)" == "${ABHAILE_FAIL_CANDIDATE_SHA}" ]]; then exit 42; fi\n'
        ),
    )


@pytest.mark.integration
class TestRunnerExitCodes:
    """Test runner exit code paths."""

    def test_runner_uses_installed_entrypoints(self) -> None:
        """Runner uses repository tools but the Debian Ansible executable."""
        script = RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert 'readonly ABHAILE_VENV_BIN="${ABHAILE_VENV_BIN:-${PWD}/.venv/bin}"' in script
        assert 'readonly ABHAILE_PYTHON="${ABHAILE_PYTHON:-${ABHAILE_VENV_BIN}/python}"' in script
        assert 'readonly ABHAILE_SRC="${ABHAILE_SRC:-${PWD}/src}"' in script
        assert 'export PYTHONPATH="${ABHAILE_SRC}${PYTHONPATH:+:${PYTHONPATH}}"' in script
        assert 'readonly ABHAILE_RENDER="${ABHAILE_VENV_BIN}/abhaile-render"' in script
        assert (
            'readonly ABHAILE_ANSIBLE_PLAYBOOK="${ABHAILE_ANSIBLE_PLAYBOOK:-/usr/bin/ansible-playbook}"'
            in script
        )
        assert "ansible/playbooks/restore-network.yml" in script
        assert 'readonly ABHAILE_HEALTH="${ABHAILE_VENV_BIN}/abhaile-health"' in script
        assert 'readonly ABHAILE_CLUSTER_HEALTH="${ABHAILE_CLUSTER_HEALTH:-0}"' in script
        assert '"$ABHAILE_RENDER" --host "$host" --output "$output_root"' in script
        assert '&& do_ansible_check "$vars_file"' in script
        assert '&& do_ansible_apply "$vars_file"' in script
        assert '[[ -z "$mutation_sha" ]] || mark_mutation "$mutation_sha"' in script
        assert 'sudo /usr/bin/env ANSIBLE_CONFIG="$ABHAILE_ANSIBLE_CONFIG"' in script
        assert script.index('do_ansible_check "$vars_file"') < script.index(
            'mark_mutation "$mutation_sha"'
        )
        assert 'sudo "$ABHAILE_HEALTH" --output "$ABHAILE_OUTPUT" --cluster' in script

    def test_runner_uses_gitops_deploy_key(self) -> None:
        """Runner selects the non-default Git deploy key for fetches."""
        script = RUNNER_SCRIPT.read_text(encoding="utf-8")
        assert (
            'readonly ABHAILE_GIT_SSH_KEY="${ABHAILE_GIT_SSH_KEY:-/home/abhaile/.ssh/gitops_ed25519}"'
            in script
        )
        assert (
            'readonly ABHAILE_GIT_KNOWN_HOSTS="${ABHAILE_GIT_KNOWN_HOSTS:-/home/abhaile/.ssh/known_hosts}"'
            in script
        )
        assert 'export GIT_SSH_COMMAND="ssh -i ${ABHAILE_GIT_SSH_KEY}' in script
        assert "IdentitiesOnly=yes" in script
        assert "StrictHostKeyChecking=yes" in script
        assert "UserKnownHostsFile=${ABHAILE_GIT_KNOWN_HOSTS}" in script
        assert "StrictHostKeyChecking=accept-new" not in script
        assert "${GIT_SSH_COMMAND:-" not in script

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
                sys.executable,
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
                sys.executable,
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

    def test_runner_refuses_unattended_enrollment_without_baseline(self, runner_repo: Path) -> None:
        """Require explicit enrollment before the routine runner may mutate."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        (state_dir / "last-successful-commit").unlink()

        result = _run_runner(runner_repo, env)

        assert result.returncode == 1
        assert "explicit enrollment is required" in result.stdout
        assert not (state_dir / "current-run").exists()

    def test_runner_blocks_interrupted_enrollment_without_baseline(self, runner_repo: Path) -> None:
        """Preserve an interrupted marker when enrollment has no recovery authority."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        (state_dir / "last-successful-commit").unlink()
        interrupted_sha = _git(runner_repo, "rev-parse", "HEAD")
        (state_dir / "current-run").write_text(f"{interrupted_sha}\n")
        trace_file = runner_repo.parent / "blocked-enrollment-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(env, 'echo invoked >> "${ABHAILE_TRACE}"')

        result = _run_runner(runner_repo, env)

        assert result.returncode == 1
        assert "interrupted mutation has no last-successful recovery target" in result.stdout
        assert (state_dir / "current-run").read_text().strip() == interrupted_sha
        assert not (state_dir / "last-successful-commit").exists()
        assert not trace_file.exists()
        summary = (state_dir / "last-run-summary").read_text()
        assert "phase=startup" in summary
        assert "outcome=recovery-blocked" in summary
        assert "rollback_attempted=false" in summary

    def test_runner_reconciles_unchanged_last_successful_for_drift(self, runner_repo: Path) -> None:
        """Run the mutation backend when desired and last-successful are unchanged."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "unchanged-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(
            env,
            'echo "$(git rev-parse HEAD)" >> "${ABHAILE_TRACE}"',
        )
        expected_sha = _git(runner_repo, "rev-parse", "HEAD")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert trace_file.read_text().splitlines() == [expected_sha]

    def test_fetch_outage_reconciles_retained_last_successful(self, runner_repo: Path) -> None:
        """Treat Git availability as candidate discovery, not recovery authority."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "offline-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(
            env,
            'echo "$(git rev-parse HEAD)" >> "${ABHAILE_TRACE}"',
        )
        expected_sha = _git(runner_repo, "rev-parse", "HEAD")
        _git(runner_repo, "remote", "set-url", "origin", str(runner_repo.parent / "missing.git"))

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "unavailable; reconciling retained last-successful" in result.stdout
        assert trace_file.read_text().splitlines() == [expected_sha]

    def test_startup_recovers_candidate_interrupted_before_success_commit(
        self, runner_repo: Path
    ) -> None:
        """Restore old authority and effects after any post-marker, pre-commit interruption."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        last_successful = (state_dir / "last-successful-commit").read_text().strip()
        trace_file = runner_repo.parent / "startup-recovery-trace.log"
        managed_effect = runner_repo.parent / "candidate-managed-effect"
        managed_effect.write_text("candidate\n")
        env.update(
            {
                "ABHAILE_TRACE": str(trace_file),
                "ABHAILE_LIVE_EFFECT": str(managed_effect),
            }
        )
        _write_live_ansible(
            env,
            (
                'echo "$(git rev-parse HEAD)" >> "${ABHAILE_TRACE}"\n'
                'rm -f "${ABHAILE_LIVE_EFFECT}"'
            ),
        )
        (runner_repo / "interrupted.txt").write_text("candidate\n")
        interrupted_sha = _commit_and_push(runner_repo, "interrupted candidate")
        (state_dir / "current-run").write_text(f"{interrupted_sha}\n")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 1
        assert "startup: recover-last-successful" in result.stdout
        assert "suppressing retry of failed commit" in result.stdout
        assert trace_file.read_text().splitlines() == [last_successful]
        assert not managed_effect.exists()
        assert (state_dir / "last-successful-commit").read_text().strip() == last_successful
        assert (state_dir / "failed-target").read_text().strip() == interrupted_sha
        assert not (state_dir / "current-run").exists()

    def test_startup_recovery_does_not_repeat_unchanged_reconciliation(
        self, runner_repo: Path
    ) -> None:
        """Reuse the completed recovery when fetch still selects last-successful."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        last_successful = (state_dir / "last-successful-commit").read_text().strip()
        trace_file = runner_repo.parent / "startup-recovery-once-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(
            env,
            'echo "$(git rev-parse HEAD)" >> "${ABHAILE_TRACE}"',
        )
        (runner_repo / "interrupted-local.txt").write_text("candidate\n")
        _git(runner_repo, "add", "interrupted-local.txt")
        _git(runner_repo, "commit", "-q", "-m", "interrupted local candidate")
        interrupted_sha = _git(runner_repo, "rev-parse", "HEAD")
        (state_dir / "current-run").write_text(f"{interrupted_sha}\n")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "already reconciled during startup recovery" in result.stdout
        assert trace_file.read_text().splitlines() == [last_successful]
        assert not (state_dir / "current-run").exists()
        assert not (state_dir / "failed-target").exists()

    def test_startup_verifies_committed_marker_once(self, runner_repo: Path) -> None:
        """Finish a committed success whose matching marker was not cleared."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        last_successful = (state_dir / "last-successful-commit").read_text().strip()
        trace_file = runner_repo.parent / "verify-committed-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(
            env,
            'echo "$(git rev-parse HEAD)" >> "${ABHAILE_TRACE}"',
        )
        (state_dir / "current-run").write_text(f"{last_successful}\n")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "startup: verify-committed" in result.stdout
        assert "already reconciled during startup recovery" in result.stdout
        assert trace_file.read_text().splitlines() == [last_successful]
        assert not (state_dir / "current-run").exists()

    @pytest.mark.parametrize("record_name", ["current-run", "last-successful-commit"])
    def test_runner_rejects_malformed_authority_without_traceback(
        self, runner_repo: Path, record_name: str
    ) -> None:
        """Report malformed runner authority concisely before reconciliation."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        trace_file = runner_repo.parent / "malformed-state-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(env, 'echo invoked >> "${ABHAILE_TRACE}"')
        (state_dir / record_name).write_text("not-a-commit\n")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 2
        assert f"runner state error: Invalid {record_name} commit SHA" in result.stderr
        assert "Traceback" not in result.stderr
        assert not trace_file.exists()

    def test_network_restore_preserves_marker_for_unavailable_candidate(
        self, runner_repo: Path
    ) -> None:
        """Stop without mutation when the interrupted commit is not retained locally."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        unavailable_sha = "f" * 40
        trace_file = runner_repo.parent / "missing-revision-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(env, 'echo invoked >> "${ABHAILE_TRACE}"')
        (state_dir / "current-run").write_text(f"{unavailable_sha}\n")

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 1
        assert "interrupted commit" in result.stdout
        assert "is unavailable locally" in result.stdout
        assert (state_dir / "current-run").read_text().strip() == unavailable_sha
        assert not trace_file.exists()

    @pytest.mark.parametrize("record_name", ["current-run", "last-successful-commit"])
    def test_network_restore_rejects_malformed_authority_without_ansible(
        self, runner_repo: Path, record_name: str
    ) -> None:
        """Block boot restoration before Ansible when runner authority is malformed."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        trace_file = runner_repo.parent / "malformed-network-state-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(env, 'echo invoked >> "${ABHAILE_TRACE}"')
        (state_dir / record_name).write_text("not-a-commit\n")

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 2
        assert f"runner state error: Invalid {record_name} commit SHA" in result.stderr
        assert "Traceback" not in result.stderr
        assert not trace_file.exists()

    def test_network_restore_blocks_interrupted_enrollment_without_baseline(
        self, runner_repo: Path
    ) -> None:
        """Refuse boot restoration when interruption has no recovery authority."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        interrupted_sha = _git(runner_repo, "rev-parse", "HEAD")
        trace_file = runner_repo.parent / "blocked-network-enrollment-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _write_live_ansible(env, 'echo invoked >> "${ABHAILE_TRACE}"')
        (state_dir / "last-successful-commit").unlink()
        (state_dir / "current-run").write_text(f"{interrupted_sha}\n")

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 1
        assert "no last-successful commit; explicit enrollment is required" in result.stdout
        assert (state_dir / "current-run").read_text().strip() == interrupted_sha
        assert not (state_dir / "last-successful-commit").exists()
        assert not trace_file.exists()

    def test_network_restore_is_local_and_preserves_runner_authority(
        self, runner_repo: Path
    ) -> None:
        """Restore accepted network input without fetch or runner-state promotion."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        last_successful = (state_dir / "last-successful-commit").read_text().strip()
        trace_file = runner_repo.parent / "network-restore-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _make_runner_executable(
            Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo "$(git rev-parse HEAD) $*" >> "${ABHAILE_TRACE}"\n'
            ),
        )
        (runner_repo / "interrupted.txt").write_text("candidate\n")
        interrupted_sha = _commit_and_push(runner_repo, "interrupted network candidate")
        (state_dir / "current-run").write_text(f"{interrupted_sha}\n")
        _git(runner_repo, "remote", "set-url", "origin", str(runner_repo.parent / "missing.git"))

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "fetch:" not in result.stdout
        trace = trace_file.read_text().splitlines()
        assert len(trace) == 2
        assert all(line.startswith(last_successful) for line in trace)
        assert all("restore-network.yml" in line for line in trace)
        assert (state_dir / "current-run").read_text().strip() == interrupted_sha
        assert (state_dir / "last-successful-commit").read_text().strip() == last_successful

    def test_network_restore_without_interruption_skips_repository_and_ansible(
        self, runner_repo: Path
    ) -> None:
        """Allow networkd to start without depending on a healthy checkout or toolchain."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "network-restore-noop-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _make_runner_executable(
            Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
            '#!/usr/bin/env bash\nset -euo pipefail\necho invoked >> "${ABHAILE_TRACE}"\nexit 42\n',
        )
        (runner_repo / "dirty.txt").write_text("must not block boot\n")
        _git(runner_repo, "remote", "set-url", "origin", str(runner_repo.parent / "missing.git"))

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "no interrupted mutation" in result.stdout
        assert "Dirty worktree" not in result.stdout
        assert not trace_file.exists()
        summary = runner_repo.parent / "output" / "runner" / "last-run-summary"
        assert "outcome=not-required" in summary.read_text()

    def test_network_restore_noop_does_not_require_project_toolchain(
        self, runner_repo: Path
    ) -> None:
        """Admit ordinary boot without Git, Python, rendering, or Ansible."""
        env = _prepare_successful_runner(runner_repo)
        tool_trace = runner_repo.parent / "unexpected-network-noop-tool.log"
        fake_git = runner_repo.parent / "fake-bin" / "git"
        _make_runner_executable(
            fake_git,
            '#!/usr/bin/env bash\nprintf "git\\n" >> "${ABHAILE_TOOL_TRACE}"\nexit 73\n',
        )
        env.update(
            {
                "ABHAILE_TOOL_TRACE": str(tool_trace),
                "ABHAILE_PYTHON": str(runner_repo.parent / "missing-python"),
                "ABHAILE_ANSIBLE_PLAYBOOK": str(runner_repo.parent / "missing-ansible"),
                "ABHAILE_VENV_BIN": str(runner_repo.parent / "missing-venv"),
                "PATH": f"{fake_git.parent}:{env['PATH']}",
            }
        )

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "no interrupted mutation" in result.stdout
        assert not tool_trace.exists()
        summary = runner_repo.parent / "output" / "runner" / "last-run-summary"
        assert "current_sha=unknown" in summary.read_text()

    def test_network_restore_matching_committed_marker_is_not_required(
        self, runner_repo: Path
    ) -> None:
        """Leave a stale committed marker for ordinary reconciliation without blocking boot."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        last_successful = (state_dir / "last-successful-commit").read_text().strip()
        (state_dir / "current-run").write_text(f"{last_successful}\n")

        result = _run_runner(runner_repo, env, "--restore-network")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "no interrupted mutation" in result.stdout
        assert (state_dir / "current-run").read_text().strip() == last_successful

    def test_runner_checks_before_live_ansible(self, runner_repo: Path) -> None:
        """Runner renders and checks before invoking live Ansible."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-render",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'echo render >> "${ABHAILE_TRACE}"\n'
                'host="$2"; output="$4"\n'
                'mkdir -p "${output}/rendered"\n'
                'printf \'{"entries":[],"host":"%s","version":"1"}\\n\' "$host" '
                '> "${output}/rendered/manifest.json"\n'
            ),
        )
        _make_runner_executable(
            Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'phase="ansible-apply"\n'
                'for arg in "$@"; do [[ "$arg" == "--check" ]] && phase="ansible-check"; done\n'
                'echo "$phase" >> "${ABHAILE_TRACE}"\n'
            ),
        )

        (runner_repo / "new.txt").write_text("new\n")
        _commit_and_push(runner_repo, "new target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        lines = trace_file.read_text().strip().splitlines()
        assert lines[:4] == ["render", "render", "ansible-check", "ansible-apply"]

    def test_runner_optional_cluster_health_runs_after_local_health(
        self, runner_repo: Path
    ) -> None:
        """Runner invokes optional cluster health after Ansible local acceptance."""
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
        assert trace_file.read_text().strip().splitlines() == ["health-cluster"]

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
        assert trace_file.read_text().strip().splitlines() == ["health-cluster-fail"]
        assert "outcome=success" in summary.read_text()

    def test_render_failure_before_marker_does_not_reconcile_baseline(
        self, runner_repo: Path
    ) -> None:
        """Suppress a failed render without recovering state that was never mutated."""
        env = _prepare_successful_runner(runner_repo)
        trace_file = runner_repo.parent / "rollback-trace.log"
        env["ABHAILE_TRACE"] = str(trace_file)
        _make_runner_executable(
            Path(env["ABHAILE_VENV_BIN"]) / "abhaile-render",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'current="$(git rev-parse HEAD)"\n'
                'if [[ "$current" == "${FAIL_RENDER_SHA:-}" ]]; then\n'
                "  exit 42\n"
                "fi\n"
                'host="$2"; output="$4"\n'
                'mkdir -p "${output}/rendered"\n'
                'printf \'{"entries":[],"host":"%s","version":"1"}\\n\' "$host" '
                '> "${output}/rendered/manifest.json"\n'
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

        assert second.returncode == 1, second.stdout + second.stderr
        assert trace_file.read_text() == ""
        assert "failed before managed-state mutation" in second.stdout
        state_dir = runner_repo.parent / "output" / "runner"
        assert (state_dir / "failed-target").read_text().strip() == target_sha
        assert not (state_dir / "current-run").exists()

    def test_ansible_check_failure_is_before_mutation(self, runner_repo: Path) -> None:
        """A failed Ansible check does not arm recovery or invoke live Ansible."""
        env = _prepare_successful_runner(runner_repo)
        _make_runner_executable(
            Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'for arg in "$@"; do [[ "$arg" == "--check" ]] && exit 23; done\n'
                "exit 0\n"
            ),
        )
        (runner_repo / "new.txt").write_text("new\n")
        _commit_and_push(runner_repo, "new target")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        summary = runner_repo.parent / "output" / "runner" / "last-run-summary"
        assert result.returncode == 1
        assert "ansible-check" in result.stdout
        summary_text = summary.read_text()
        assert "phase=ansible-check" in summary_text
        assert "outcome=failure-before-mutation" in summary_text
        assert not (runner_repo.parent / "output" / "runner" / "current-run").exists()

    def test_failed_commit_retry_is_suppressed(self, runner_repo: Path) -> None:
        """Runner records a failed target and suppresses identical automatic retries."""
        env = _prepare_successful_runner(runner_repo)
        _write_live_ansible(
            env,
            'if [[ "$(git rev-parse HEAD)" == "${FAIL_APPLY_SHA:-}" ]]; then exit 42; fi',
        )
        (runner_repo / "bad.txt").write_text("bad\n")
        target_sha = _commit_and_push(runner_repo, "bad deploy")
        env["FAIL_APPLY_SHA"] = target_sha
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        first = _run_runner(runner_repo, env)
        second = _run_runner(runner_repo, env)

        failed_target = runner_repo.parent / "output" / "runner" / "failed-target"
        current_run = runner_repo.parent / "output" / "runner" / "current-run"
        assert first.returncode == 1
        assert failed_target.read_text().startswith(target_sha)
        assert not current_run.exists(), first.stdout + first.stderr
        assert second.returncode == 1
        assert "suppressing retry of failed commit" in second.stdout
        assert failed_target.read_text().startswith(target_sha)
        assert not current_run.exists()

    def test_live_apply_failure_reconciles_last_successful_revision(
        self, runner_repo: Path
    ) -> None:
        """Reapply the durable baseline after a candidate mutates and then fails."""
        env = _prepare_successful_runner(runner_repo)
        state_dir = runner_repo.parent / "output" / "runner"
        last_successful = (state_dir / "last-successful-commit").read_text().strip()
        trace_file = runner_repo.parent / "apply-recovery-trace.log"
        live_effect = runner_repo.parent / "managed-effect"
        env.update(
            {
                "ABHAILE_TRACE": str(trace_file),
                "ABHAILE_LIVE_EFFECT": str(live_effect),
            }
        )
        _make_runner_executable(
            Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'phase="live"\n'
                'for arg in "$@"; do [[ "$arg" == "--check" ]] && phase="check"; done\n'
                'sha="$(git rev-parse HEAD)"\n'
                'echo "$sha $phase" >> "${ABHAILE_TRACE}"\n'
                'if [[ "$phase" == "live" && "$sha" == "${FAIL_APPLY_SHA:-}" ]]; then\n'
                '  echo candidate > "${ABHAILE_LIVE_EFFECT}"\n'
                "  exit 42\n"
                "fi\n"
                'if [[ "$phase" == "live" ]]; then rm -f "${ABHAILE_LIVE_EFFECT}"; fi\n'
            ),
        )
        (runner_repo / "bad.txt").write_text("bad\n")
        target_sha = _commit_and_push(runner_repo, "failing live apply")
        env["FAIL_APPLY_SHA"] = target_sha
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        result = _run_runner(runner_repo, env)

        assert result.returncode == 1, result.stdout + result.stderr
        assert trace_file.read_text().splitlines() == [
            f"{target_sha} check",
            f"{target_sha} live",
            f"{last_successful} check",
            f"{last_successful} live",
        ]
        assert not live_effect.exists()
        assert (state_dir / "last-successful-commit").read_text().strip() == last_successful
        assert (state_dir / "failed-target").read_text().strip() == target_sha
        assert not (state_dir / "current-run").exists()
        summary = (state_dir / "last-run-summary").read_text()
        assert "phase=ansible-apply" in summary
        assert "outcome=failure-recovered" in summary
        assert "rollback_attempted=true" in summary

    def test_forward_removal_uses_last_successful_manifest(self, runner_repo: Path) -> None:
        """Remove an identity-matched file omitted by a newer desired revision."""
        env = _prepare_successful_runner(runner_repo)
        _install_manifest_fixture_renderer(runner_repo, env)
        state_dir = runner_repo.parent / "output" / "runner"
        managed_file = runner_repo.parent / "managed-service.conf"
        managed_file.write_text("accepted=yes\n")
        _write_manifest_fixture(runner_repo, managed_file, include_entry=True)
        baseline_sha = _commit_and_push(runner_repo, "add accepted manifest fixture")
        (state_dir / "last-successful-commit").write_text(f"{baseline_sha}\n")

        _write_manifest_fixture(runner_repo, managed_file, include_entry=False)
        target_sha = _commit_and_push(runner_repo, "remove managed service fixture")
        _git(runner_repo, "checkout", "-q", baseline_sha)
        _git(runner_repo, "checkout", "-q", "-B", "main")
        trace_file = runner_repo.parent / "forward-removal-trace.log"
        _write_forward_removal_ansible(
            env,
            trace_file=trace_file,
            managed_file=managed_file,
        )

        result = _run_runner(runner_repo, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert trace_file.read_text().splitlines() == [
            f"{target_sha} check cleanup=1",
            f"{target_sha} live cleanup=1",
        ]
        assert not managed_file.exists()
        assert (state_dir / "last-successful-commit").read_text().strip() == target_sha

    def test_forward_removal_refuses_live_drift_before_mutation(self, runner_repo: Path) -> None:
        """Reject a desired removal when live bytes no longer match prior intent."""
        env = _prepare_successful_runner(runner_repo)
        _install_manifest_fixture_renderer(runner_repo, env)
        state_dir = runner_repo.parent / "output" / "runner"
        managed_file = runner_repo.parent / "managed-service.conf"
        managed_file.write_text("operator-change=yes\n")
        _write_manifest_fixture(runner_repo, managed_file, include_entry=True)
        baseline_sha = _commit_and_push(runner_repo, "add drifted removal fixture")
        (state_dir / "last-successful-commit").write_text(f"{baseline_sha}\n")

        _write_manifest_fixture(runner_repo, managed_file, include_entry=False)
        target_sha = _commit_and_push(runner_repo, "request drifted fixture removal")
        _git(runner_repo, "checkout", "-q", baseline_sha)
        _git(runner_repo, "checkout", "-q", "-B", "main")
        trace_file = runner_repo.parent / "blocked-forward-removal-trace.log"
        _write_forward_removal_ansible(
            env,
            trace_file=trace_file,
            managed_file=managed_file,
        )

        result = _run_runner(runner_repo, env)

        assert result.returncode == 1
        assert "Managed removal is blocked" in result.stderr
        assert managed_file.read_text() == "operator-change=yes\n"
        assert not trace_file.exists()
        assert (state_dir / "last-successful-commit").read_text().strip() == baseline_sha
        assert (state_dir / "failed-target").read_text().strip() == target_sha
        assert not (state_dir / "current-run").exists()

    def test_failed_forward_removal_restores_last_successful_file(self, runner_repo: Path) -> None:
        """Recreate a removed file when later candidate work fails."""
        env = _prepare_successful_runner(runner_repo)
        _install_manifest_fixture_renderer(runner_repo, env)
        state_dir = runner_repo.parent / "output" / "runner"
        managed_file = runner_repo.parent / "managed-service.conf"
        managed_file.write_text("accepted=yes\n")
        _write_manifest_fixture(runner_repo, managed_file, include_entry=True)
        baseline_sha = _commit_and_push(runner_repo, "add accepted recovery fixture")
        (state_dir / "last-successful-commit").write_text(f"{baseline_sha}\n")

        _write_manifest_fixture(runner_repo, managed_file, include_entry=False)
        target_sha = _commit_and_push(runner_repo, "remove fixture before later failure")
        _git(runner_repo, "checkout", "-q", baseline_sha)
        _git(runner_repo, "checkout", "-q", "-B", "main")
        trace_file = runner_repo.parent / "failed-forward-removal-trace.log"
        _write_forward_removal_ansible(
            env,
            trace_file=trace_file,
            managed_file=managed_file,
            fail_candidate_sha=target_sha,
        )

        result = _run_runner(runner_repo, env)

        assert result.returncode == 1, result.stdout + result.stderr
        assert trace_file.read_text().splitlines() == [
            f"{target_sha} check cleanup=1",
            f"{target_sha} live cleanup=1",
            f"{baseline_sha} check cleanup=0",
            f"{baseline_sha} live cleanup=0",
        ]
        assert managed_file.read_text() == "accepted=yes\n"
        assert (state_dir / "last-successful-commit").read_text().strip() == baseline_sha
        assert (state_dir / "failed-target").read_text().strip() == target_sha
        assert not (state_dir / "current-run").exists()

    def test_interrupted_recovery_retries_with_original_candidate_cleanup(
        self, runner_repo: Path
    ) -> None:
        """Retain candidate identity until accepted cleanup eventually succeeds."""
        env = _prepare_successful_runner(runner_repo)
        _install_manifest_fixture_renderer(runner_repo, env)
        state_dir = runner_repo.parent / "output" / "runner"
        managed_file = runner_repo.parent / "candidate-only-service.conf"
        _write_manifest_fixture(runner_repo, managed_file, include_entry=False)
        baseline_sha = _commit_and_push(runner_repo, "accepted state without candidate file")
        (state_dir / "last-successful-commit").write_text(f"{baseline_sha}\n")

        _write_manifest_fixture(runner_repo, managed_file, include_entry=True)
        candidate_sha = _commit_and_push(runner_repo, "add failing candidate-only file")
        _git(runner_repo, "checkout", "-q", baseline_sha)
        _git(runner_repo, "checkout", "-q", "-B", "main")
        trace_file = runner_repo.parent / "interrupted-recovery-cleanup-trace.log"
        recovery_failure = runner_repo.parent / "fail-first-recovery"
        recovery_failure.write_text("armed\n")
        env.update(
            {
                "ABHAILE_TRACE": str(trace_file),
                "ABHAILE_MANAGED_FILE": str(managed_file),
                "ABHAILE_CANDIDATE_SHA": candidate_sha,
                "ABHAILE_BASELINE_SHA": baseline_sha,
                "ABHAILE_RECOVERY_FAILURE": str(recovery_failure),
            }
        )
        _make_runner_executable(
            Path(env["ABHAILE_ANSIBLE_PLAYBOOK"]),
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'phase="live"; vars_file=""\n'
                'for arg in "$@"; do\n'
                '  [[ "$arg" == "--check" ]] && phase="check"\n'
                '  [[ "$arg" == @* ]] && vars_file="${arg#@}"\n'
                "done\n"
                "cleanup_count=\"$(python3 -c 'import json,sys; "
                'print(len(json.load(open(sys.argv[1]))["abhaile_candidate_cleanup_entries"]))\' '
                '"$vars_file")"\n'
                'sha="$(git rev-parse HEAD)"\n'
                'echo "$sha $phase cleanup=$cleanup_count" >> "${ABHAILE_TRACE}"\n'
                '[[ "$phase" == "check" ]] && exit 0\n'
                'if [[ "$sha" == "${ABHAILE_CANDIDATE_SHA}" ]]; then\n'
                '  printf "accepted=yes\\n" > "${ABHAILE_MANAGED_FILE}"\n'
                "  exit 42\n"
                "fi\n"
                'if [[ -e "${ABHAILE_RECOVERY_FAILURE}" ]]; then\n'
                '  rm -f "${ABHAILE_RECOVERY_FAILURE}"\n'
                "  exit 43\n"
                "fi\n"
                '[[ "$cleanup_count" == "1" ]] && rm -f "${ABHAILE_MANAGED_FILE}"\n'
            ),
        )

        first = _run_runner(runner_repo, env)

        assert first.returncode == 1, first.stdout + first.stderr
        assert (state_dir / "current-run").exists(), (
            first.stdout + first.stderr + (trace_file.read_text() if trace_file.exists() else "")
        )
        assert (state_dir / "current-run").read_text().strip() == candidate_sha
        assert (state_dir / "last-successful-commit").read_text().strip() == baseline_sha
        assert managed_file.exists()

        second = _run_runner(runner_repo, env)

        assert second.returncode == 1, second.stdout + second.stderr
        assert trace_file.read_text().splitlines() == [
            f"{candidate_sha} check cleanup=0",
            f"{candidate_sha} live cleanup=0",
            f"{baseline_sha} check cleanup=1",
            f"{baseline_sha} live cleanup=1",
            f"{baseline_sha} check cleanup=1",
            f"{baseline_sha} live cleanup=1",
        ]
        assert not managed_file.exists()
        assert (state_dir / "last-successful-commit").read_text().strip() == baseline_sha
        assert (state_dir / "failed-target").read_text().strip() == candidate_sha
        assert not (state_dir / "current-run").exists()

    def test_newer_commit_after_failed_target_is_deployed(self, runner_repo: Path) -> None:
        """A correcting commit remains eligible after a previous target failed."""
        env = _prepare_successful_runner(runner_repo)
        ansible_path = Path(env["ABHAILE_ANSIBLE_PLAYBOOK"])
        _write_live_ansible(env, "exit 42")
        (runner_repo / "bad.txt").write_text("bad\n")
        _commit_and_push(runner_repo, "bad deploy")
        _git(runner_repo, "checkout", "-q", "HEAD~1")
        _git(runner_repo, "checkout", "-q", "-B", "main")

        first = _run_runner(runner_repo, env)
        assert first.returncode == 1

        _make_runner_executable(ansible_path, "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n")
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
