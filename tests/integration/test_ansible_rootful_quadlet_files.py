"""Exercise rootful Quadlet file preflight without mutating systemd."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(rendered_root: Path, *, content: str) -> dict[str, object]:
    """Write one rootful container source and return its selected entry."""
    render_path = "services/example/etc/containers/systemd/abhaile-role-test.container"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": "/etc/containers/systemd/abhaile-role-test.container",
        "kind": "quadlet.container",
        "owner_ref": "unit:abhaile-role-test.service",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {"rootless": False},
    }


def _build_entry(rendered_root: Path) -> dict[str, object]:
    """Write one rootful build source and return its selected entry."""
    content = "[Build]\nImageTag=localhost/abhaile-role-test:latest\nFile=/tmp/Containerfile\n"
    render_path = "services/example/etc/containers/systemd/abhaile-role-test.build"
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    return {
        "render_path": render_path,
        "target_path": "/etc/containers/systemd/abhaile-role-test.build",
        "kind": "quadlet.build",
        "owner_ref": "unit:abhaile-role-test-build.service",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {
            "rootless": False,
            "managed_build": {
                "consumers": ["abhaile-role-test.service"],
                "output_image": "localhost/abhaile-role-test:latest",
                "service": "example",
            },
        },
    }


def _write_playbook(
    tmp_path: Path,
    rendered_root: Path,
    entry: dict[str, object] | None,
    *,
    owners: dict[str, object] | None = None,
    cleanup_entries: list[dict[str, object]] | None = None,
) -> Path:
    """Write an isolated localhost play invoking the production role."""
    playbook = tmp_path / "rootful-quadlet.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test rootful Quadlet files",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_rootful_quadlet_entries": [entry] if entry else [],
                        "abhaile_rootful_quadlet_cleanup_entries": cleanup_entries or [],
                        "abhaile_rootful_quadlet_owners": owners or {},
                    },
                    "roles": ["rootful_quadlet_files"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return playbook


def _run_playbook(tmp_path: Path, playbook: Path) -> tuple[int, str, str]:
    """Run the isolated role in check mode and return its result fields."""
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
            "quadlet_preflight",
            str(playbook),
        ],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_rootful_quadlet_validates_without_publication(tmp_path: Path) -> None:
    """Run the real generator dry-run while check mode preserves the target."""
    rendered = tmp_path / "rendered"
    entry = _entry(
        rendered,
        content="[Container]\nImage=docker.io/library/busybox:latest\nExec=sleep infinity\n",
    )
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, stdout, stderr = _run_playbook(tmp_path / "valid", playbook)

    assert code == 0, stdout + stderr
    assert "Run the rootful Quadlet generator dry-run" in stdout
    assert "changed=0" in stdout


@pytest.mark.integration
def test_rootful_quadlet_rejects_invalid_generator_input(tmp_path: Path) -> None:
    """Reject malformed Quadlet content before publication."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, content="[NotAQuadletSection]\nInvalid=true\n")
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, _stdout, _stderr = _run_playbook(tmp_path / "invalid", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_rejects_owner_mismatch_before_validation(tmp_path: Path) -> None:
    """Bind the source filename to its generated systemd unit identity."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, content="[Container]\nImage=busybox\n")
    entry["owner_ref"] = "unit:different.service"
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, _stdout, _stderr = _run_playbook(tmp_path / "owner", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_rejects_rootless_entry(tmp_path: Path) -> None:
    """Keep named-user Quadlets out of the rootful execution context."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, content="[Container]\nImage=busybox\n")
    entry["apply_hints"] = {"rootless": True, "podman_user": "abhaile"}
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, _stdout, _stderr = _run_playbook(tmp_path / "rootless", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_rejects_invalid_restart_mode(tmp_path: Path) -> None:
    """Reject lifecycle behavior outside the closed automatic/manual contract."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, content="[Container]\nImage=busybox\n")
    entry["apply_hints"] = {"rootless": False, "restart_mode": "always"}
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, _stdout, _stderr = _run_playbook(tmp_path / "restart-mode", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_accepts_managed_build_contract(tmp_path: Path) -> None:
    """Accept an explicit managed build without requiring a pre-existing target."""
    rendered = tmp_path / "rendered"
    entry = _build_entry(rendered)
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, stdout, stderr = _run_playbook(tmp_path / "managed-build", playbook)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_rootful_quadlet_accepts_managed_build_post_build_contract(tmp_path: Path) -> None:
    """Accept the bounded install-unit and executable verification shape."""
    rendered = tmp_path / "rendered"
    entry = _build_entry(rendered)
    entry["apply_hints"]["managed_build"]["post_build"] = {  # type: ignore[index]
        "install_unit": "abhaile-role-test-install.service",
        "verify_binary": "/usr/local/bin/abhaile-role-test",
    }
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, stdout, stderr = _run_playbook(tmp_path / "managed-post-build", playbook)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_rootful_quadlet_accepts_candidate_cleanup_contract(tmp_path: Path) -> None:
    """Admit exact rootful candidate identity without needing desired entries."""
    cleanup: dict[str, object] = {
        "render_path": "services/example/etc/containers/systemd/abhaile-role-test.container",
        "target_path": "/etc/containers/systemd/abhaile-role-test.container",
        "kind": "quadlet.container",
        "owner_ref": "unit:abhaile-role-test.service",
        "candidate_sha256": "1" * 64,
        "live_sha256": "1" * 64,
        "apply_hints": {"rootless": False},
    }
    playbook = _write_playbook(
        tmp_path,
        tmp_path / "rendered",
        None,
        cleanup_entries=[cleanup],
    )

    code, stdout, stderr = _run_playbook(tmp_path / "cleanup", playbook)

    assert code == 0, stdout + stderr


@pytest.mark.integration
def test_rootful_quadlet_rejects_rootless_candidate_cleanup(tmp_path: Path) -> None:
    """Keep rootless cleanup outside the rootful system-manager boundary."""
    cleanup: dict[str, object] = {
        "render_path": "services/example/etc/containers/systemd/abhaile-role-test.container",
        "target_path": "/etc/containers/systemd/abhaile-role-test.container",
        "kind": "quadlet.container",
        "owner_ref": "unit:abhaile-role-test.service",
        "candidate_sha256": "1" * 64,
        "live_sha256": "1" * 64,
        "apply_hints": {"rootless": True, "podman_user": "abhaile"},
    }
    playbook = _write_playbook(
        tmp_path,
        tmp_path / "rendered",
        None,
        cleanup_entries=[cleanup],
    )

    code, _stdout, _stderr = _run_playbook(tmp_path / "cleanup-rootless", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_rejects_unsafe_managed_build_consumer(tmp_path: Path) -> None:
    """Reject consumer names outside the closed systemd service contract."""
    rendered = tmp_path / "rendered"
    entry = _build_entry(rendered)
    entry["apply_hints"]["managed_build"]["consumers"] = ["bad service"]  # type: ignore[index]
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, _stdout, _stderr = _run_playbook(tmp_path / "unsafe-consumer", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_rejects_manual_container_without_selected_parent_pod(
    tmp_path: Path,
) -> None:
    """Refuse a manual container without one selected parent pod."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, content="[Container]\nImage=busybox\n")
    entry["apply_hints"] = {"rootless": False, "restart_mode": "manual"}
    playbook = _write_playbook(tmp_path, rendered, entry)

    code, _stdout, _stderr = _run_playbook(tmp_path / "manual", playbook)

    assert code != 0


@pytest.mark.integration
def test_rootful_quadlet_accepts_manual_container_with_selected_parent_pod(
    tmp_path: Path,
) -> None:
    """Accept a manual container bound to exactly one selected parent pod."""
    rendered = tmp_path / "rendered"
    container = _entry(
        rendered,
        content="[Container]\nImage=docker.io/library/busybox:latest\nExec=sleep infinity\n",
    )
    container["apply_hints"] = {"rootless": False, "restart_mode": "manual"}
    pod_content = "[Pod]\n\n[Install]\nWantedBy=multi-user.target\n"
    pod_render_path = "services/example/etc/containers/systemd/abhaile-role-test.pod"
    pod_source = rendered / pod_render_path
    pod_source.write_text(pod_content, encoding="utf-8")
    pod_entry = {
        "render_path": pod_render_path,
        "target_path": "/etc/containers/systemd/abhaile-role-test.pod",
        "kind": "quadlet.pod",
        "owner_ref": "unit:abhaile-role-test-pod.service",
        "sha256": hashlib.sha256(pod_content.encode()).hexdigest(),
        "size": len(pod_content.encode()),
        "apply_hints": {"rootless": False},
    }
    playbook = tmp_path / "rootful-quadlet.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test manual rootful Quadlet member",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered),
                        "abhaile_rootful_quadlet_entries": [container, pod_entry],
                        "abhaile_rootful_quadlet_owners": {
                            container["owner_ref"]: {
                                "requires": [pod_entry["owner_ref"]],
                            }
                        },
                    },
                    "roles": ["rootful_quadlet_files"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    code, stdout, stderr = _run_playbook(tmp_path / "manual-parent", playbook)

    assert code == 0, stdout + stderr


def test_rootful_quadlet_activation_is_limited_to_supported_lifecycle_families() -> None:
    """Keep deferred resources and manual containers out of automatic activation."""
    role_path = (
        Path(__file__).resolve().parents[2] / "ansible/roles/rootful_quadlet_files/tasks/main.yml"
    )
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    activation = next(
        task
        for task in tasks
        if task.get("name") == "Start or restart changed automatic rootful containers and pods"
    )

    assert activation["ansible.builtin.systemd_service"]["state"] == "restarted"
    conditions = activation["when"]
    assert "item.changed" in conditions
    assert "item.item.kind in ['quadlet.container', 'quadlet.pod']" in conditions
    assert "item.item.apply_hints.restart_mode | default('try-restart') != 'manual'" in conditions
    build_activation = next(
        task for task in tasks if task.get("name") == "Run changed managed rootful builds"
    )
    assert "abhaile_build_publication.changed or" in build_activation["when"][-1]
    assert "abhaile_changed_service_config_owners" in build_activation["when"][-1]

    drift_repair = next(
        task
        for task in tasks
        if task.get("name") == "Ensure automatic rootful containers and pods are started"
    )
    assert drift_repair["ansible.builtin.systemd_service"]["state"] == "started"
    assert drift_repair["loop"] == "{{ abhaile_rootful_quadlet_entries }}"
    assert "item.changed" not in drift_repair["when"]

    manual_activation = next(
        task
        for task in tasks
        if task.get("name") == "Start or restart parent pods for changed manual rootful containers"
    )
    assert manual_activation["ansible.builtin.systemd_service"]["state"] == "restarted"
    assert manual_activation["loop"] == (
        "{{ abhaile_changed_rootful_parent_pods | default([]) | unique }}"
    )
    assert "item not in changed_rootful_pod_owner_refs" in manual_activation["when"]


def test_candidate_cleanup_stops_rechecks_removes_then_reloads() -> None:
    """Keep candidate removal bounded by identity and one manager reload."""
    role_path = (
        Path(__file__).resolve().parents[2] / "ansible/roles/rootful_quadlet_files/tasks/main.yml"
    )
    tasks = yaml.safe_load(role_path.read_text(encoding="utf-8"))
    names = [task.get("name") for task in tasks]

    pre_deactivation_inspection = names.index(
        "Reinspect candidate-only rootful Quadlet files before deactivation"
    )
    pre_deactivation_refusal = names.index(
        "Refuse changed candidate-only rootful Quadlets before deactivation"
    )
    stop = names.index("Stop loaded candidate-only rootful Quadlet generated units")
    post_deactivation_inspection = names.index(
        "Reinspect candidate-only rootful Quadlet files before removal"
    )
    post_deactivation_refusal = names.index(
        "Refuse changed candidate-only rootful Quadlet cleanup targets"
    )
    removal_index = names.index("Remove candidate-only rootful Quadlet files")

    assert pre_deactivation_inspection < pre_deactivation_refusal < stop
    assert stop < post_deactivation_inspection < post_deactivation_refusal < removal_index
    pre_deactivation = tasks[pre_deactivation_refusal]
    assert pre_deactivation["ansible.builtin.assert"]["that"] == [
        "item.stat.exists",
        "item.stat.isreg",
        "not item.stat.islnk",
        "item.stat.checksum == item.item.candidate_sha256",
    ]
    assert pre_deactivation["when"] == "not ansible_check_mode"
    post_deactivation = tasks[post_deactivation_refusal]
    assert post_deactivation["ansible.builtin.assert"]["that"] == [
        (
            "not item.stat.exists or (item.stat.isreg and not item.stat.islnk and "
            "item.stat.checksum == item.item.candidate_sha256)"
        )
    ]
    assert names.index("Remove candidate-only rootful Quadlet files") < names.index(
        "Reload the system manager after rootful Quadlet publication"
    )
    assert names.index("Reload the system manager after rootful Quadlet publication") < names.index(
        "Reinspect removed rootful Quadlet generated-unit failed states"
    )
    assert names.index(
        "Reinspect removed rootful Quadlet generated-unit failed states"
    ) < names.index("Clear removed rootful Quadlet failed-state residue")
    reset_failed = next(
        task
        for task in tasks
        if task.get("name") == "Clear removed rootful Quadlet failed-state residue"
    )
    assert reset_failed["ansible.builtin.command"]["argv"][1] == "reset-failed"
    assert reset_failed["changed_when"] is False
    assert reset_failed["loop"] == (
        "{{ abhaile_rootful_quadlet_post_reload_active_states.results | default([]) }}"
    )
    assert reset_failed["when"] == [
        "not ansible_check_mode",
        "item.stdout | trim == 'failed'",
    ]
    removal = next(
        task for task in tasks if task.get("name") == "Remove candidate-only rootful Quadlet files"
    )
    assert removal["ansible.builtin.file"]["state"] == "absent"
