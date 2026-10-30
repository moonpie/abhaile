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
    validate_native_graph: bool = False,
    extra_vars: dict[str, object] | None = None,
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
                        "abhaile_rootful_systemd_entries": [],
                        **(extra_vars or {}),
                    },
                    "roles": (
                        [{"role": "rootful_unit_preflight", "tags": ["quadlet_preflight"]}]
                        if validate_native_graph
                        else []
                    )
                    + ["rootful_quadlet_files"],
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
    """Generate and verify the unit while check mode preserves the target."""
    rendered = tmp_path / "rendered"
    entry = _entry(
        rendered,
        content="[Container]\nImage=docker.io/library/busybox:latest\nExec=sleep infinity\n",
    )
    playbook = _write_playbook(tmp_path, rendered, entry, validate_native_graph=True)

    code, stdout, stderr = _run_playbook(tmp_path / "valid", playbook)

    assert code == 0, stdout + stderr
    assert "Generate candidate rootful Quadlet units" in stdout
    assert "changed=0" in stdout


@pytest.mark.integration
def test_rootful_quadlet_rejects_invalid_generator_input(tmp_path: Path) -> None:
    """Reject malformed Quadlet content before publication."""
    rendered = tmp_path / "rendered"
    entry = _entry(rendered, content="[NotAQuadletSection]\nInvalid=true\n")
    playbook = _write_playbook(tmp_path, rendered, entry, validate_native_graph=True)

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
    for filename in ("builds.yml", "activate.yml"):
        tasks.extend(yaml.safe_load((role_path.parent / filename).read_text(encoding="utf-8")))
    activation = next(
        task
        for task in tasks
        if task.get("name") == "Start or restart changed automatic rootful containers and pods"
    )

    assert activation["ansible.builtin.systemd_service"]["state"] == "restarted"
    conditions = activation["when"]
    assert any(
        "item.changed or" in condition and "abhaile_deferred_config_units" in condition
        for condition in conditions
    )
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


def _auxiliary_entry(rendered: Path, kind: str) -> dict[str, object]:
    """Describe the exact native resource associated with an absent Quadlet."""
    resource: dict[str, object] = {
        "name": "systemd-abhaile-role-test",
        "driver": "local",
        "options": {"device": "/srv/abhaile-role-test/data", "o": "bind"},
    }
    content = "[Volume]\nDevice=/srv/abhaile-role-test/data\nOptions=bind\n"
    if kind == "network":
        resource = {
            "name": "systemd-abhaile-role-test",
            "driver": "ipvlan",
            "network_interface": "example.20",
            "subnets": [{"subnet": "192.0.2.0/24", "gateway": "192.0.2.1"}],
            "options": {"mode": "l2"},
            "internal": False,
            "dns_enabled": False,
            "ipv6_enabled": False,
            "ipam_options": {"driver": "host-local"},
        }
        content = "[Network]\nDriver=ipvlan\nSubnet=192.0.2.0/24\nGateway=192.0.2.1\n"
    elif kind == "image":
        content = "[Image]\nImage=docker.io/library/busybox:latest\n"
    render_path = f"services/example/etc/containers/systemd/abhaile-role-test.{kind}"
    source = rendered / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content)
    encoded = content.encode()
    return {
        "render_path": render_path,
        "target_path": f"/etc/containers/systemd/abhaile-role-test.{kind}",
        "kind": f"quadlet.{kind}",
        "owner_ref": f"unit:abhaile-role-test-{kind}.service",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "apply_hints": {"rootless": False, "podman_resource": resource},
    }


def _fake_podman(tmp_path: Path, observed: object, *, status: int = 0) -> Path:
    """Provide isolated native-command observations without touching Podman storage."""
    executable = tmp_path / "podman-observation"
    script = (
        "#!/usr/bin/python3\nimport json, sys\n"
        f"status = {status}\n"
        "if sys.argv[2] == 'exists':\n    sys.exit(status)\n"
        f"print(json.dumps({observed!r}))\n"
    )
    executable.write_text(script)
    executable.chmod(0o700)
    return executable


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["volume", "network", "image"])
def test_missing_auxiliary_quadlets_are_enrollable_in_check_mode(tmp_path: Path, kind: str) -> None:
    """Accept absence without creating native resources or publishing target files."""
    rendered = tmp_path / "rendered"
    entry = _auxiliary_entry(rendered, kind)
    command = _fake_podman(tmp_path, [], status=1)
    playbook = _write_playbook(
        tmp_path, rendered, entry, extra_vars={"abhaile_podman_binary": str(command)}
    )
    code, stdout, stderr = _run_playbook(tmp_path / "absent", playbook)
    assert code == 0, stdout + stderr
    assert "changed=0" in stdout


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["volume", "network"])
@pytest.mark.parametrize("compatible", [True, False])
def test_missing_quadlet_refuses_incompatible_existing_resource(
    tmp_path: Path, kind: str, compatible: bool
) -> None:
    """Reuse compatible objects while refusing changed bind paths or network parents."""
    rendered = tmp_path / "rendered"
    entry = _auxiliary_entry(rendered, kind)
    hints = entry["apply_hints"]
    assert isinstance(hints, dict)
    desired = hints["podman_resource"]
    assert isinstance(desired, dict)
    observed = dict(desired)
    if kind == "volume":
        observed = {
            "Name": desired["name"],
            "Driver": desired["driver"],
            "Options": desired["options"] if compatible else {"device": "/elsewhere", "o": "bind"},
        }
    elif not compatible:
        observed["network_interface"] = "different.20"
    command = _fake_podman(tmp_path, [observed])
    playbook = _write_playbook(
        tmp_path, rendered, entry, extra_vars={"abhaile_podman_binary": str(command)}
    )
    code, stdout, stderr = _run_playbook(tmp_path / "existing", playbook)
    assert (code == 0) is compatible, stdout + stderr
    if not compatible:
        assert "incompatible identity or options" in stdout + stderr


@pytest.mark.integration
@pytest.mark.parametrize("status", [125, 127])
def test_auxiliary_resource_observation_errors_do_not_mean_absence(
    tmp_path: Path, status: int
) -> None:
    """Fail on unavailable Podman storage or executables rather than adopt blindly."""
    rendered = tmp_path / "rendered"
    entry = _auxiliary_entry(rendered, "volume")
    command = _fake_podman(tmp_path, [], status=status)
    playbook = _write_playbook(
        tmp_path, rendered, entry, extra_vars={"abhaile_podman_binary": str(command)}
    )
    code, stdout, stderr = _run_playbook(tmp_path / "error", playbook)
    assert code != 0, stdout + stderr


def test_publication_defers_builds_and_workload_activation() -> None:
    """Keep publication independent from later builds and post-config activation."""
    tasks_root = Path(__file__).resolve().parents[2] / "ansible/roles/rootful_quadlet_files/tasks"
    tasks = yaml.safe_load((tasks_root / "main.yml").read_text())
    for name in ("builds.yml", "activate.yml"):
        task = next(task for task in tasks if task.get("ansible.builtin.include_tasks") == name)
        assert task["when"] == "not abhaile_defer_activation | default(false)"
    build_tasks = yaml.safe_load((tasks_root / "converge_build.yml").read_text())
    consumer = next(
        task for task in build_tasks if task["name"] == "Restart managed rootful build consumers"
    )
    assert consumer["when"] == "not abhaile_defer_build_consumers | default(false)"


@pytest.mark.integration
@pytest.mark.parametrize(
    "changed,status,expected", [(False, 0, False), (False, 1, True), (True, 0, True)]
)
def test_build_selection_repairs_missing_outputs_without_running_consumers(
    tmp_path: Path, changed: bool, status: int, expected: bool
) -> None:
    """Exercise production image probing and selection with only the build action substituted."""
    rendered = tmp_path / "rendered"
    entry = _build_entry(rendered)
    command = _fake_podman(tmp_path, [], status=status)
    tasks_root = Path(__file__).resolve().parents[2] / "ansible/roles/rootful_quadlet_files/tasks"
    tasks = yaml.safe_load((tasks_root / "builds.yml").read_text())
    selection = next(task for task in tasks if task["name"] == "Run changed managed rootful builds")
    del selection["ansible.builtin.include_tasks"]
    selection["ansible.builtin.set_fact"] = {"abhaile_test_build_selected": True}
    tasks.append(
        {
            "name": "Verify selected build behavior",
            "ansible.builtin.assert": {
                "that": [
                    f"abhaile_test_build_selected | default(false) is sameas {str(expected).lower()}"
                ]
            },
        }
    )
    playbook = tmp_path / "build-selection.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "abhaile_podman_binary": str(command),
                        "abhaile_rootful_quadlet_publications": {
                            "results": [{"item": entry, "changed": changed}]
                        },
                    },
                    "tasks": tasks,
                }
            ],
            sort_keys=False,
        )
    )
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    result = _ansible(
        "ansible.cli.playbook",
        ["-i", "localhost,", "--connection=local", str(playbook)],
        _closed_environment(environment_root),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.integration
@pytest.mark.parametrize("matching", [False, True])
def test_existing_auxiliary_definition_cannot_be_changed(tmp_path: Path, matching: bool) -> None:
    """Exercise the production immutable-source guard without writing a system target."""
    tasks_root = Path(__file__).resolve().parents[2] / "ansible/roles/rootful_quadlet_files/tasks"
    tasks = yaml.safe_load((tasks_root / "main.yml").read_text())
    task = next(
        task
        for task in tasks
        if task["name"] == "Refuse existing auxiliary rootful Quadlet definition changes"
    )
    playbook = tmp_path / "immutable-resource.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "abhaile_deferred_quadlet_targets": {
                            "results": [
                                {
                                    "item": {
                                        "target_path": "/unmodified-test-source.volume",
                                        "sha256": "a" * 64,
                                    },
                                    "stat": {
                                        "exists": True,
                                        "isreg": True,
                                        "islnk": False,
                                        "checksum": ("a" if matching else "b") * 64,
                                    },
                                }
                            ]
                        }
                    },
                    "tasks": [task],
                }
            ],
            sort_keys=False,
        )
    )
    code, stdout, stderr = _run_playbook(tmp_path / "guard", playbook)
    assert (code == 0) is matching, stdout + stderr
    if not matching:
        assert "explicit resource migration" in stdout + stderr
