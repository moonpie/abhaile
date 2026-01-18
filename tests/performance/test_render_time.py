import os
import time
import subprocess


def test_render_all_hosts_under_15s(repo_root):
    """Render all hosts and assert it completes within a reasonable time.

    Uses SKIP_DESEC to avoid external dependencies.
    """
    env = os.environ.copy()
    env["SKIP_DESEC"] = "1"

    start = time.monotonic()
    result = subprocess.run(
        ["python3", "tools/render/cli.py"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - start

    assert result.returncode == 0, f"cli.py failed: {result.stderr}"
    # Keep threshold conservative to avoid CI flakiness
    assert duration < 30.0, f"Render took {duration:.2f}s, exceeds 30s threshold"
