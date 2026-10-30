"""Exercise the runner's actual cleanup selection for a newly enrolled template."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.unit.python.state.test_removals import _entry, _manifest


@pytest.mark.integration
def test_runner_retains_unused_template_but_routes_candidate_units(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    script = (repo / "scripts/abhaile-runner").read_text()
    function = script.split("write_ansible_vars() {", 1)[1]
    code = function.split('"$ABHAILE_PYTHON" -c \'\n', 1)[1].split('\n\' "$host"', 1)[0]
    accepted = tmp_path / "accepted.json"
    candidate = tmp_path / "candidate.json"
    template = tmp_path / "new.env.ctmpl"
    unit = tmp_path / "new.service"
    quadlet = tmp_path / "new.container"
    for target in (template, unit, quadlet):
        target.write_text("candidate\n")
    _manifest(accepted, "phobos", [])
    _manifest(
        candidate,
        "phobos",
        [
            _entry(template, "candidate\n", kind="vault.template", owner_ref="service:vault-agent"),
            _entry(unit, "candidate\n", kind="systemd.unit", owner_ref="unit:new.service"),
            _entry(quadlet, "candidate\n", kind="quadlet.container", owner_ref="unit:new.service"),
        ],
    )
    output = tmp_path / "vars.json"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            "phobos",
            str(tmp_path),
            str(repo / "config"),
            str(output),
            str(accepted),
            str(candidate),
            "all",
        ],
        env={**os.environ, "PYTHONPATH": str(repo / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    cleanup = json.loads(output.read_text())["abhaile_candidate_cleanup_entries"]
    assert {entry["kind"] for entry in cleanup} == {"systemd.unit", "quadlet.container"}
    assert template.read_text() == "candidate\n"
