"""Exercise the CoreDNS installer's atomic replacement with temporary executables."""

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("copy_fails", [False, True])
def test_install_preserves_running_binary(tmp_path: Path, copy_fails: bool) -> None:
    """Replace a running executable atomically, retaining it if staging fails."""
    sleep = shutil.which("sleep")
    true = shutil.which("true")
    if sleep is None or true is None:
        pytest.skip("Executable replacement test requires sleep and true")

    unit = (
        Path(__file__).resolve().parents[2]
        / "config/services/coredns-omada/systemd/install.service"
    )
    command = next(
        line.removeprefix("ExecStart=")
        for line in unit.read_text().splitlines()
        if line.startswith("ExecStart=")
    )
    arguments = shlex.split(command)
    script = arguments[arguments.index("-c") + 1].replace("$$", "$")
    source = tmp_path / "source"
    destination = tmp_path / "coredns"
    shutil.copy2(sleep, destination)
    if not copy_fails:
        shutil.copy2(true, source)
    script = script.replace("cp /coredns ", f"cp {shlex.quote(str(source))} ")
    script = script.replace("/out/", f"{tmp_path}/")
    before = destination.read_bytes()

    process = subprocess.Popen([str(destination), "60"])
    try:
        result = subprocess.run(["/bin/sh", "-c", script], capture_output=True, timeout=10)
        assert process.poll() is None
        assert not list(tmp_path.glob(".coredns.*"))
        if copy_fails:
            assert result.returncode != 0
            assert destination.read_bytes() == before
        else:
            assert result.returncode == 0, result.stderr.decode()
            assert destination.read_bytes() == source.read_bytes()
            assert destination.stat().st_mode & 0o777 == 0o755
            subprocess.run([str(destination)], check=True, timeout=10)
    finally:
        process.terminate()
        process.wait(timeout=10)
