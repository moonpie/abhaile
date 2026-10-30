"""Exercise the owner-scoped Caddy configuration Ansible role."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(rendered_root: Path) -> dict[str, object]:
    """Write one Caddy candidate and return its manifest entry."""
    content = ':80 {\n    respond "ok"\n}\n'
    render_path = "services/caddy-internal/srv/caddy/internal/Caddyfile"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": "/srv/caddy/internal/Caddyfile",
        "kind": "caddy.config",
        "owner_ref": "caddy:internal",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {"contributors": ["service:example"]},
    }


def _run_contract(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
) -> tuple[int, str, str]:
    """Run only the non-mutating Caddy contract tasks."""
    playbook = tmp_path / "caddy.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test Caddy configuration contract",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_caddy_config_entries": entries,
                    },
                    "roles": ["caddy_config"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    environment_root = tmp_path / "env"
    environment_root.mkdir()
    result = _ansible(
        "ansible.cli.playbook",
        [
            "-i",
            "localhost,",
            "--connection=local",
            "--check",
            "--tags",
            "caddy_contract",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_caddy_contract_accepts_exact_segment(tmp_path: Path) -> None:
    """Accept one source-bound Caddy segment without runtime mutation."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered)

    code, stdout, stderr = _run_contract(tmp_path, rendered, [entry])

    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
def test_caddy_contract_rejects_target_segment_mismatch(tmp_path: Path) -> None:
    """Reject an owner whose fixed live path names another segment."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered)
    entry["target_path"] = "/srv/caddy/dmz/Caddyfile"

    code, _stdout, _stderr = _run_contract(tmp_path, rendered, [entry])

    assert code != 0


def _run_runtime_role(
    tmp_path: Path,
    role: str,
    variables: dict[str, Any],
    *,
    check: bool,
    create_parents: bool = True,
    image_status: int = 0,
    validation_status: int = 0,
) -> tuple[int, str, list[dict[str, Any]]]:
    """Exercise production roles with only filesystem and external-tool boundaries redirected."""
    repository = Path(__file__).resolve().parents[2]
    isolated_roles = tmp_path / "roles"
    role_tasks = isolated_roles / role / "tasks"
    role_tasks.mkdir(parents=True)
    log = tmp_path / "runtime-calls.jsonl"
    command = tmp_path / "native-tool"
    command.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "data = sys.stdin.read() if 'validate' in args else ''\n"
        f"path = Path({str(log)!r})\n"
        "with path.open('a') as handle: handle.write(json.dumps({'argv': args, 'stdin': data}) + '\\n')\n"
        f"sys.exit({image_status} if args[:2] == ['image', 'exists'] else ({validation_status} if 'validate' in args else 0))\n"
    )
    command.chmod(0o755)
    replacements = {
        "/srv/caddy/": str(tmp_path / "live/caddy") + "/",
        "/etc/coredns/": str(tmp_path / "live/coredns") + "/",
        "/usr/bin/podman": str(command),
        "/usr/bin/systemctl": str(command),
        "/usr/bin/named-checkzone": str(command),
    }

    def translate(value: Any) -> Any:
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [translate(item) for item in value]
        if isinstance(value, dict):
            result = {key: translate(item) for key, item in value.items()}
            if result.get("owner") == "root":
                result["owner"] = str(os.getuid())
            if result.get("group") == "root":
                result["group"] = str(os.getgid())
            unit = result.pop("ansible.builtin.systemd_service", None)
            if unit is not None:
                result["ansible.builtin.command"] = {
                    "argv": [str(command), "systemd", unit["state"], unit["name"]]
                }
            return result
        return value

    for source in (repository / "ansible/roles" / role / "tasks").glob("*.yml"):
        (role_tasks / source.name).write_text(
            yaml.safe_dump(translate(yaml.safe_load(source.read_text())))
        )
    for key in ("abhaile_caddy_config_entries", "abhaile_coredns_entries"):
        for entry in variables.get(key, []):
            entry["target_path"] = translate(entry["target_path"])
            if create_parents:
                Path(entry["target_path"]).parent.mkdir(parents=True, exist_ok=True)
    variables["abhaile_defer_activation"] = True
    variables["abhaile_directory_entries"] = [
        {"target_path": str(Path(entry["target_path"]).parent)}
        for key in ("abhaile_caddy_config_entries", "abhaile_coredns_entries")
        for entry in variables.get(key, [])
    ]
    playbook = tmp_path / "runtime.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Exercise initial configuration publication",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": variables,
                    "roles": [role],
                }
            ]
        )
    )
    environment_root = tmp_path / "runtime-environment"
    environment_root.mkdir()
    environment = _closed_environment(environment_root)
    environment["ANSIBLE_ROLES_PATH"] = (
        str(isolated_roles) + ":" + environment["ANSIBLE_ROLES_PATH"]
    )
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    result = _ansible("ansible.cli.playbook", [*arguments, str(playbook)], environment)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result.returncode, result.stdout + result.stderr, calls


def _caddy_runtime_variables(
    tmp_path: Path, *, managed_build: bool = False
) -> tuple[dict[str, Any], Path]:
    """Provide a candidate configuration and image without an installed target container."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered)
    quadlet = rendered / "caddy.container"
    image = "caddy-internal.build" if managed_build else "example.invalid/caddy:candidate"
    quadlet.write_text(
        f"[Container]\nImage={image}\nEnvironmentFile=/protected/candidate.env\nVolume=config.volume:/config\nVolume=data.volume:/data\n\n[Service]\nExecStartPre=/usr/bin/true\nExecStartPre=/usr/bin/true\n"
    )
    variables: dict[str, Any] = {
        "abhaile_rendered_root": str(rendered),
        "abhaile_caddy_config_entries": [entry],
        "abhaile_rootful_quadlet_entries": [
            {
                "kind": "quadlet.container",
                "owner_ref": "unit:caddy-internal.service",
                "render_path": "caddy.container",
            }
        ],
    }
    if managed_build:
        variables["abhaile_rootful_quadlet_entries"].append(
            {
                "kind": "quadlet.build",
                "owner_ref": "unit:caddy-internal-build.service",
                "target_path": "/etc/containers/systemd/caddy-internal.build",
                "apply_hints": {
                    "managed_build": {"output_image": "example.invalid/caddy:candidate"}
                },
            }
        )
    return variables, rendered / str(entry["render_path"])


@pytest.mark.integration
@pytest.mark.parametrize("managed_build", [False, True])
def test_caddy_first_publication_validates_candidate_before_activation(
    tmp_path: Path, managed_build: bool
) -> None:
    """Publish using the selected candidate image and environment without touching old workloads."""
    variables, source = _caddy_runtime_variables(tmp_path, managed_build=managed_build)
    code, output, calls = _run_runtime_role(tmp_path, "caddy_config", variables, check=False)
    assert code == 0, output
    target = Path(variables["abhaile_caddy_config_entries"][0]["target_path"])
    assert target.read_bytes() == source.read_bytes()
    validation = next(call for call in calls if "run" in call["argv"])
    assert "example.invalid/caddy:candidate" in validation["argv"]
    assert "/protected/candidate.env" in validation["argv"]
    assert "--network=none" in validation["argv"]
    assert validation["stdin"] == source.read_text()
    assert all("exec" not in call["argv"] and "systemd" not in call["argv"] for call in calls)


@pytest.mark.integration
def test_caddy_invalid_candidate_is_not_published(tmp_path: Path) -> None:
    """An initial semantic validation failure leaves the target absent."""
    variables, _source = _caddy_runtime_variables(tmp_path)
    code, _output, calls = _run_runtime_role(
        tmp_path,
        "caddy_config",
        variables,
        check=False,
        validation_status=1,
    )
    assert code != 0
    assert not Path(variables["abhaile_caddy_config_entries"][0]["target_path"]).exists()
    assert any("run" in call["argv"] for call in calls)


@pytest.mark.integration
@pytest.mark.parametrize("image_status", [0, 1])
def test_caddy_check_reports_pending_without_creating_runtime(
    tmp_path: Path, image_status: int
) -> None:
    """A missing parent or image remains pending without pulling images or running containers."""
    variables, _source = _caddy_runtime_variables(tmp_path)
    code, output, calls = _run_runtime_role(
        tmp_path,
        "caddy_config",
        variables,
        check=True,
        create_parents=False,
        image_status=image_status,
    )
    assert code == 0, output
    assert "Report first Caddy validation pending image acquisition" in output
    assert not Path(variables["abhaile_caddy_config_entries"][0]["target_path"]).parent.exists()
    assert all(call["argv"][:2] == ["image", "exists"] for call in calls)


@pytest.mark.integration
def test_caddy_refuses_dangling_target_before_validation_or_publication(tmp_path: Path) -> None:
    """Do not adopt a redirected config leaf even when its referent is absent."""
    variables, _source = _caddy_runtime_variables(tmp_path)
    target = tmp_path / "live/caddy/internal/Caddyfile"
    target.parent.mkdir(parents=True)
    referent = tmp_path / "must-not-create"
    target.symlink_to(referent)
    code, output, calls = _run_runtime_role(tmp_path, "caddy_config", variables, check=False)
    assert code != 0
    assert target.is_symlink()
    assert not referent.exists()
    assert not calls, output


@pytest.mark.integration
def test_caddy_repeated_directives_without_environment_file(tmp_path: Path) -> None:
    """Read repeated Quadlet keys without requiring an optional environment file."""
    variables, _ = _caddy_runtime_variables(tmp_path)
    quadlet = Path(variables["abhaile_rendered_root"]) / "caddy.container"
    quadlet.write_text(
        quadlet.read_text().replace("EnvironmentFile=/protected/candidate.env\n", "")
    )
    code, output, calls = _run_runtime_role(tmp_path, "caddy_config", variables, check=False)
    assert code == 0, output
    validation = next(call for call in calls if "run" in call["argv"])
    assert "--env-file" not in validation["argv"]
