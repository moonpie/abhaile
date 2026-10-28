"""Exercise canonical container image schemas and shared project validation against production schemas."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from abhaile.cli.render import load_and_validate
from abhaile.cli.validate_services import main, validate_project_services
from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.manifest import build_manifest
from abhaile.renderers.quadlets.renderer import render_service_quadlets
from abhaile.utils.config import clear_config_cache
from abhaile.utils.errors import RenderError
from abhaile.utils.paths import load_paths

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]
RUNTIME = {"user": "root", "network": "host"}
IMAGE = {"image": "example.invalid/app:1", "pull_policy": "missing"}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create an isolated service project using the production schema set."""
    shutil.copytree(REPO / "schemas", tmp_path / "schemas")
    shutil.copy(REPO / "paths.ini", tmp_path / "paths.ini")
    config = tmp_path / "config"
    config.mkdir()
    (config / "mapping.yaml").write_text("abhaile:\n  - phobos: [leaf]\n")
    _service(tmp_path, "leaf", RUNTIME, {"include": ["common"]})
    _service(tmp_path, "common", None, {"container": IMAGE})
    clear_config_cache()
    return tmp_path


def _service(
    project: Path,
    name: str,
    podman: dict[str, Any] | None,
    composition: dict[str, Any] | None = None,
) -> Path:
    """Write one temporary definition, allowing native services and shared container fragments."""
    path = project / "config" / "services" / name / "service.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"name": name, "composition": composition or {"container": {}}}
    if podman is not None:
        data["podman"] = podman
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize("in_pod", [False, True])
@pytest.mark.parametrize("policy", [None, "always", "missing", "never", "newer"])
def test_canonical_container_settings(project: Path, in_pod: bool, policy: str | None) -> None:
    """Use the same registry settings for standalone and nested pod containers."""
    container = {"image": IMAGE["image"]}
    if policy is not None:
        container["pull_policy"] = policy
    composition = (
        {"pod": {"containers": [{"name": "app", "container": container}]}}
        if in_pod
        else {"container": container}
    )
    _service(project, "leaf", RUNTIME, composition)
    validate_project_services(project)


@pytest.mark.parametrize(
    "podman",
    [
        {},
        {"user": "root"},
        {"network": "host"},
        IMAGE,
        {**RUNTIME, **IMAGE},
        {**RUNTIME, "image": IMAGE["image"]},
        {**RUNTIME, "pull_policy": "missing"},
        {**RUNTIME, "other": True},
        {"user": "root", "network": "bridge"},
        {"user": "abhaile", "network": "ipvlan-l2"},
        {"user": "abhaile", "network": "container:"},
    ],
)
def test_invalid_runtime_or_service_image_settings(project: Path, podman: dict[str, Any]) -> None:
    """Require local runtime fields and reject removed service-level image declarations."""
    _service(project, "leaf", podman)
    with pytest.raises(RenderError, match="Schema validation failed"):
        validate_project_services(project)


@pytest.mark.parametrize(
    "pod",
    [
        {},
        {"containers": []},
        {"containers": [{}]},
        {"containers": [{"name": "app"}]},
        {"containers": [{"container": {}}]},
        {"containers": [{"name": "app", "container": {}, "image": "app:1"}]},
        {"containers": [{"name": "app", "container": {}, "pull_policy": "missing"}]},
    ],
)
def test_invalid_pod_shape(project: Path, pod: dict[str, Any]) -> None:
    """Reject empty pods, incomplete members, and wrapper-level registry settings."""
    _service(project, "leaf", RUNTIME, {"pod": pod})
    with pytest.raises(RenderError, match="Schema validation failed"):
        validate_project_services(project)


@pytest.mark.parametrize("in_pod", [False, True])
@pytest.mark.parametrize(
    "container",
    [
        {"image": ""},
        {"image": 42},
        {"image": "app:1", "pull_policy": "sometimes"},
        {"image": "app:1", "unknown": True},
    ],
)
def test_invalid_container_values(project: Path, in_pod: bool, container: dict[str, Any]) -> None:
    """Enforce the shared container schema for both runtime shapes."""
    composition = (
        {"pod": {"containers": [{"name": "app", "container": container}]}}
        if in_pod
        else {"container": container}
    )
    _service(project, "leaf", RUNTIME, composition)
    with pytest.raises(RenderError, match="Schema validation failed"):
        validate_project_services(project)


def test_empty_nested_container_is_structurally_valid(project: Path) -> None:
    """Allow an empty container object without asserting it has a runnable image source."""
    _service(project, "leaf", RUNTIME, {"pod": {"containers": [{"name": "app", "container": {}}]}})
    validate_project_services(project)


@pytest.mark.parametrize(
    ("user", "network"),
    [
        ("root", "ipvlan-l2"),
        ("root", "container:peer"),
        ("abhaile", "host"),
        ("abhaile", "container:peer"),
    ],
)
def test_runtime_network_constraints(project: Path, user: str, network: str) -> None:
    """Keep supported rootful and rootless network combinations."""
    _service(project, "leaf", {"user": user, "network": network}, {"include": ["common"]})
    validate_project_services(project)


def test_project_validation_is_read_only(project: Path) -> None:
    """Validate image inheritance without reading network or host state or writing files."""
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    validate_project_services(project)
    after = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert after == before
    assert not (project / "config" / "network.yaml").exists()
    assert not (project / "out").exists()


def test_removed_service_image_fails_project_and_render_validation(project: Path) -> None:
    """Reject removed service-level fields through both validation entry points."""
    _service(project, "leaf", IMAGE)
    # Supply real network intent for the render loader; the hook needs no network file.
    shutil.copy(REPO / "config" / "network.yaml", project / "config" / "network.yaml")
    for validate in [
        validate_project_services,
        lambda root: load_and_validate(root, load_paths(root)),
    ]:
        with pytest.raises(RenderError, match="Schema validation failed"):
            validate(project)
    assert not (project / "out").exists()


def test_render_validation_keeps_only_mapped_service_paths(project: Path) -> None:
    """Validate included fragments without returning them as deployed runtime services."""
    shutil.copy(REPO / "config" / "network.yaml", project / "config" / "network.yaml")
    validated = load_and_validate(project, load_paths(project))
    assert validated.service_paths == [project / "config/services/leaf/service.yaml"]
    assert validated.host_services == {"phobos": ["leaf"]}
    assert not (project / "out").exists()


def test_inherited_runtime_does_not_complete_local_runtime(project: Path) -> None:
    """Included runtime settings cannot complete an incomplete local declaration."""
    _service(project, "common", RUNTIME, {"container": IMAGE})
    _service(project, "leaf", {"user": "abhaile"}, {"include": ["common"]})
    with pytest.raises(RenderError, match="Schema validation failed"):
        validate_project_services(project)


def test_invalid_included_image_is_validated(project: Path) -> None:
    """Validate included definitions even when a leaf supplies a valid local container."""
    path = _service(project, "common", None, {"container": {"image": ""}})
    _service(project, "leaf", RUNTIME, {"include": ["common"], "container": IMAGE})
    with pytest.raises(RenderError, match="Schema validation failed") as error:
        validate_project_services(project)
    assert str(path) in str(error.value)


def test_malformed_included_composition_has_schema_diagnostic(project: Path) -> None:
    """Validate document shape before attempting to walk malformed include content."""
    _service(project, "common", None, {"include": "not-a-list"})
    with pytest.raises(RenderError, match="Schema validation failed"):
        validate_project_services(project)


@pytest.mark.parametrize("cycle", [False, True])
def test_include_diagnostics_are_preserved(project: Path, cycle: bool) -> None:
    """Preserve canonical missing-definition and cycle errors."""
    _service(project, "common", None, {"include": ["leaf" if cycle else "absent"]})
    message = "Service include cycle detected" if cycle else "Missing service definition"
    with pytest.raises(RenderError, match=message):
        validate_project_services(project)


def test_native_service_without_podman_remains_valid(project: Path) -> None:
    """Keep non-Podman service definitions valid."""
    _service(project, "leaf", None)
    validate_project_services(project)


def test_runtime_still_requires_composition(project: Path) -> None:
    """A runtime definition still needs container, pod, or include composition."""
    path = _service(project, "common", RUNTIME)
    data = json.loads(path.read_text())
    data["composition"] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(RenderError, match="Schema validation failed"):
        validate_project_services(project)


def test_validator_cli_success_and_diagnostic(project: Path, capsys: Any) -> None:
    """Provide a nonzero exit and useful diagnostic for hook failures."""
    assert main(["--repo-root", str(project)]) == 0
    _service(project, "leaf", IMAGE)
    assert main(["--repo-root", str(project)]) == 1
    assert "Schema validation failed" in capsys.readouterr().err


def test_source_wrapper_without_installed_package(project: Path, tmp_path: Path) -> None:
    """Run the source wrapper from outside the checkout without an installed package."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(REPO / "scripts" / "validate-services.py"),
            "--repo-root",
            str(project),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "changed",
    [
        "config/services/blocky-common/service.yaml",
        "schemas/service.schema.json",
        "schemas/common.schema.json",
        "config/mapping.yaml",
        "paths.ini",
        "src/abhaile/validation/services.py",
        "src/abhaile/cli/validate_services.py",
        "src/abhaile/renderers/quadlets/helpers.py",
        "src/abhaile/utils/composition.py",
        ".pre-commit-config.yaml",
        "scripts/validate-services.py",
    ],
)
def test_project_hook_triggers_for_dependencies(changed: str) -> None:
    """Select project validation for shared definitions and schema-only changes."""
    config = yaml.safe_load((REPO / ".pre-commit-config.yaml").read_text())
    hook = next(
        h
        for repo in config["repos"]
        for h in repo["hooks"]
        if h["id"] == "validate-service-project"
    )
    assert re.search(hook["files"], changed)
    assert hook["pass_filenames"] is False
    # Pre-commit omits deleted paths: still validate deletion-only commits.
    assert hook["always_run"] is True


def test_project_hook_rejects_deleted_include(project: Path) -> None:
    """Run the real hook on a deletion-only commit rather than skipping deleted paths."""
    config = yaml.safe_load((REPO / ".pre-commit-config.yaml").read_text())
    hook = next(
        h
        for repo in config["repos"]
        for h in repo["hooks"]
        if h["id"] == "validate-service-project"
    )
    # Reuse the installed test environment; do not install dependencies during tests.
    hook["language"] = "system"
    hook.pop("additional_dependencies")
    hook["entry"] = shlex.join([sys.executable, str(REPO / "scripts" / "validate-services.py")])
    (project / ".pre-commit-config.yaml").write_text(
        yaml.safe_dump({"repos": [{"repo": "local", "hooks": [hook]}]})
    )
    for args in [
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "--no-gpg-sign",
            "-m",
            "fixture",
        ],
        ["rm", "config/services/common/service.yaml"],
    ]:
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    result = subprocess.run(
        [sys.executable, "-m", "pre_commit", "run", "validate-service-project"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Missing service definition" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("service", "host"),
    [("blocky-a", "phobos"), ("blocky-b", "deimos"), ("vault-agent", "phobos")],
)
def test_image_migration_preserves_artifacts_and_runtime_metadata(
    tmp_path: Path, service: str, host: str
) -> None:
    """Keep output and runtime metadata identical when complete containers move through includes."""
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
    service_path = config / "services" / service / "service.yaml"
    data = yaml.safe_load(service_path.read_text())

    def render_snapshot(destination: Path) -> tuple[dict[Path, bytes], dict[str, Any]]:
        clear_config_cache()
        collector = ArtifactCollector()
        render_service_quadlets(
            host,
            [service],
            yaml.safe_load((config / "network.yaml").read_text()),
            config,
            destination / "services",
            collector=collector,
            rendered_root=destination,
        )
        collector.compute_hashes_and_sizes(destination)
        files = {
            p.relative_to(destination): p.read_bytes()
            for p in destination.rglob("*")
            if p.is_file()
        }
        return files, build_manifest(host, collector.get_metadata())

    before = render_snapshot(tmp_path / "before")
    if service.startswith("blocky"):
        common_path = config / "services" / "blocky-common" / "service.yaml"
        common = yaml.safe_load(common_path.read_text())
        data["composition"]["container"] = common["composition"]["container"]
    else:
        # Included runtime settings deliberately disagree with the rootless leaf.
        fragment = config / "services" / "shared-container" / "service.yaml"
        fragment.parent.mkdir()
        fragment.write_text(
            yaml.safe_dump(
                {
                    "name": "shared-container",
                    "podman": {"user": "root", "network": "ipvlan-l2"},
                    "composition": {"container": data["composition"].pop("container")},
                }
            )
        )
        data["composition"].setdefault("include", []).append("shared-container")
    service_path.write_text(yaml.safe_dump(data))
    after = render_snapshot(tmp_path / "after")
    assert after == before
    unit = next(e for e in after[1]["entries"] if e["kind"] == "quadlet.container")
    assert unit["apply_hints"]["rootless"] is (service == "vault-agent")
    if service == "vault-agent":
        assert unit["apply_hints"]["podman_user"] == "abhaile"
        assert unit["target_path"].startswith("/home/abhaile/")
