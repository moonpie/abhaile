"""Exercise rootful systemd role validation without mutating the live manager."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(
    rendered_root: Path,
    target: Path,
    *,
    kind: str,
    owner_ref: str,
    content: str,
    apply_hints: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write one source and return its selected manifest entry."""
    render_path = f"system/systemd/{target.name}"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": str(target),
        "kind": kind,
        "owner_ref": owner_ref,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": apply_hints,
    }


def _write_playbook(
    tmp_path: Path,
    rendered_root: Path,
    entries: list[dict[str, object]],
    *,
    cleanup_entries: list[dict[str, object]] | None = None,
) -> Path:
    """Write an isolated localhost play that invokes the production role."""
    playbook = tmp_path / "rootful-systemd.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test rootful systemd",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_rootful_systemd_entries": entries,
                        "abhaile_rootful_systemd_cleanup_entries": cleanup_entries or [],
                    },
                    "roles": ["rootful_systemd"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return playbook


def _run_playbook(tmp_path: Path, playbook: Path, *, check: bool = False) -> tuple[int, str, str]:
    """Run the isolated role play and return its result fields."""
    tmp_path.mkdir(parents=True)
    environment_root = tmp_path / "env"
    environment_root.mkdir()
    arguments = ["-i", "localhost,", "--connection=local"]
    if check:
        arguments.append("--check")
    arguments.append(str(playbook))
    result = _ansible("ansible.cli.playbook", arguments, _closed_environment(environment_root))
    return result.returncode, result.stdout, result.stderr


def _run_contract(tmp_path: Path, playbook: Path) -> tuple[int, str, str]:
    """Run only non-mutating rootful systemd contract checks."""
    tmp_path.mkdir(parents=True)
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
            "rootful_systemd_contract",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_rootful_systemd_validates_and_reports_without_mutation(tmp_path: Path) -> None:
    """Validate a complete unit context and report publication in check mode."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "abhaile-role-test.service"
    entry = _entry(
        rendered,
        target,
        kind="systemd.unit",
        owner_ref="unit:abhaile-role-test.service",
        content=(
            "[Unit]\nDescription=Abhaile role test\n"
            "[Service]\nType=oneshot\nExecStart=/bin/true\n"
        ),
    )
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, stdout, stderr = _run_playbook(tmp_path / "check", playbook, check=True)

    assert code == 0, stdout + stderr
    assert "changed=1" in stdout
    assert not target.exists()


@pytest.mark.integration
def test_rootful_systemd_accepts_omitted_apply_hints(tmp_path: Path) -> None:
    """Accept the optional hint field exactly as emitted by real manifests."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "without-hints.service"
    entry = _entry(
        rendered,
        target,
        kind="systemd.unit",
        owner_ref="unit:without-hints.service",
        content="[Service]\nType=oneshot\nExecStart=/bin/true\n",
    )
    entry.pop("apply_hints")
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, stdout, stderr = _run_contract(tmp_path / "without-hints", playbook)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_rootful_systemd_rejects_invalid_unit_before_publication(tmp_path: Path) -> None:
    """Reject a native fatal unit-validation error before publication."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "invalid.service"
    entry = _entry(
        rendered,
        target,
        kind="systemd.unit",
        owner_ref="unit:invalid.service",
        content="[Service]\nType=oneshot\nExecStart=/definitely/missing\n",
    )
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "invalid", playbook, check=True)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
def test_rootful_systemd_rejects_source_mismatch_before_publication(tmp_path: Path) -> None:
    """Reject a source identity mismatch before validation or publication."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "mismatch.service"
    entry = _entry(
        rendered,
        target,
        kind="systemd.unit",
        owner_ref="unit:mismatch.service",
        content="[Service]\nType=oneshot\nExecStart=/bin/true\n",
    )
    entry["sha256"] = "0" * 64
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "mismatch", playbook, check=True)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    "unit_name",
    [
        "abhaile-network-restore.service",
        "abhaile-runner.service",
        "abhaile-runner.timer",
    ],
)
def test_rootful_systemd_rejects_runner_self_management(
    tmp_path: Path,
    unit_name: str,
) -> None:
    """Keep active runner-unit publication in the later cutover-owned slice."""
    rendered = tmp_path / "rendered"
    target = tmp_path / unit_name
    entry = _entry(
        rendered,
        target,
        kind="systemd.unit",
        owner_ref=f"unit:{unit_name}",
        content="[Service]\nType=oneshot\nExecStart=/bin/true\n",
    )
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "runner", playbook, check=True)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
def test_rootful_systemd_rejects_coerced_rootless_hint(tmp_path: Path) -> None:
    """Reject string booleans rather than coercing their meaning."""
    rendered = tmp_path / "rendered"
    target = tmp_path / "coerced.service"
    entry = _entry(
        rendered,
        target,
        kind="systemd.unit",
        owner_ref="unit:coerced.service",
        content="[Service]\nType=oneshot\nExecStart=/bin/true\n",
        apply_hints={"rootless": "false"},
    )
    playbook = _write_playbook(tmp_path, rendered, [entry])

    code, _stdout, _stderr = _run_playbook(tmp_path / "coerced", playbook, check=True)

    assert code != 0
    assert not target.exists()


@pytest.mark.integration
def test_rootful_systemd_accepts_matching_candidate_only_unit_cleanup(tmp_path: Path) -> None:
    """Accept exact identity evidence for one ordinary rootful unit file."""
    rendered = tmp_path / "rendered"
    digest = hashlib.sha256(b"candidate unit\n").hexdigest()
    cleanup: dict[str, object] = {
        "kind": "systemd.unit",
        "owner_ref": "unit:obsolete.service",
        "target_path": "/etc/systemd/system/obsolete.service",
        "candidate_sha256": digest,
        "live_sha256": digest,
    }
    playbook = _write_playbook(tmp_path, rendered, [], cleanup_entries=[cleanup])

    code, stdout, stderr = _run_contract(tmp_path / "cleanup", playbook)

    assert code == 0, stdout + stderr


@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "systemd.dropin"),
        ("target_path", "/etc/systemd/system/different.service"),
        ("live_sha256", "0" * 64),
        ("owner_ref", "unit:abhaile-network-restore.service"),
        ("owner_ref", "unit:abhaile-runner.service"),
        ("owner_ref", "unit:abhaile-runner.timer"),
    ],
)
def test_rootful_systemd_rejects_unsafe_candidate_cleanup(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Reject unsupported, mismatched, or reserved candidate-only unit cleanup."""
    rendered = tmp_path / "rendered"
    digest = hashlib.sha256(b"candidate unit\n").hexdigest()
    cleanup: dict[str, object] = {
        "kind": "systemd.unit",
        "owner_ref": "unit:obsolete.service",
        "target_path": "/etc/systemd/system/obsolete.service",
        "candidate_sha256": digest,
        "live_sha256": digest,
    }
    cleanup[field] = value
    playbook = _write_playbook(tmp_path, rendered, [], cleanup_entries=[cleanup])

    code, _stdout, _stderr = _run_contract(tmp_path / "unsafe-cleanup", playbook)

    assert code != 0


def test_rootful_systemd_repairs_enablement_and_activation_without_file_change() -> None:
    """Keep desired unit enablement and activation independent of publication drift."""
    role_path = Path(__file__).resolve().parents[2] / "ansible/roles/rootful_systemd/tasks/main.yml"
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))

    for task_name in ["Enable declared rootful units", "Start declared rootful units"]:
        task = next(item for item in tasks if item.get("name") == task_name)
        assert "item.changed" not in task["when"]

    restart = next(
        item for item in tasks if item.get("name") == "Apply declared rootful unit restart"
    )
    assert "item.changed" in restart["when"]
    assert any("activation_mode" in condition for condition in restart["when"])
    assert "else 'try-restart'" in restart["ansible.builtin.command"]["argv"][1]
    assert restart["vars"]["supported_restart_modes"] == [
        "try-restart",
        "reload-or-restart",
    ]


def test_rootful_systemd_cleanup_stops_before_removal_and_reloads_once() -> None:
    """Keep logical deactivation ahead of exact file removal and manager reload."""
    role_path = Path(__file__).resolve().parents[2] / "ansible/roles/rootful_systemd/tasks/main.yml"
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task["name"] for task in tasks]

    inspect_index = names.index("Inspect candidate-only rootful units before deactivation")
    refusal_index = names.index("Refuse ambiguous candidate-only rootful units before deactivation")
    trigger_index = names.index("Stop and disable candidate-only rootful trigger units")
    service_index = names.index("Stop and disable candidate-only rootful services")
    recheck_index = names.index("Recheck candidate-only rootful units immediately before removal")
    removal_index = names.index("Remove matching candidate-only rootful unit files")
    reload_index = names.index("Reload the system manager after unit publication")
    inspect_residue_index = names.index("Reinspect removed rootful systemd unit failed states")
    reset_residue_index = names.index("Clear removed rootful systemd unit failed-state residue")
    assert (
        inspect_index
        < refusal_index
        < trigger_index
        < service_index
        < recheck_index
        < removal_index
        < reload_index
        < inspect_residue_index
        < reset_residue_index
    )

    inspect_residue = tasks[inspect_residue_index]
    assert inspect_residue["ansible.builtin.command"]["argv"][1:] == [
        "show",
        "{{ item.owner_ref | regex_replace('^unit:', '') }}",
        "--property=ActiveState",
        "--value",
    ]
    reset_residue = tasks[reset_residue_index]
    assert reset_residue["ansible.builtin.command"]["argv"][1] == "reset-failed"
    assert "item.stdout | trim == 'failed'" in reset_residue["when"]
