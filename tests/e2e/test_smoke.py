import os
import subprocess
import pytest


@pytest.mark.slow
@pytest.mark.skipif(os.getenv("E2E_SMOKE") != "1", reason="E2E_SMOKE!=1")
def test_smoke_render_then_apply_dry_run(repo_root):
    env = os.environ.copy()
    env["SKIP_DESEC"] = "1"

    r = subprocess.run(
        ["python3", "tools/render/cli.py"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"render failed: {r.stderr}"

    for host in ("phobos", "deimos"):
        a = subprocess.run(
            ["bash", "tools/apply/apply.sh", host],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert a.returncode == 0, f"apply dry-run failed for {host}: {a.stderr}"
