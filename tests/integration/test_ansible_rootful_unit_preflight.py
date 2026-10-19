"""Exercise combined native rootful systemd and Quadlet validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.integration.test_ansible_scaffold import _ansible, _closed_environment


def _entry(
    rendered_root: Path,
    render_path: str,
    *,
    target_path: str,
    kind: str,
    owner_ref: str,
    content: str,
    apply_hints: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write one rendered source and return its manifest entry."""
    source = rendered_root / render_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content, encoding="utf-8")
    encoded = content.encode("utf-8")
    entry: dict[str, object] = {
        "render_path": render_path,
        "target_path": target_path,
        "kind": kind,
        "owner_ref": owner_ref,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
    }
    if apply_hints is not None:
        entry["apply_hints"] = apply_hints
    return entry


def _run_preflight(
    tmp_path: Path,
    rendered_root: Path,
    systemd_entries: list[dict[str, object]],
    quadlet_entries: list[dict[str, object]],
) -> tuple[int, str, str]:
    """Run the combined preflight and return its result fields."""
    playbook = tmp_path / "rootful-unit-preflight.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test combined rootful unit preflight",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "become": False,
                    "vars": {
                        "abhaile_rendered_root": str(rendered_root),
                        "abhaile_rootful_systemd_entries": systemd_entries,
                        "abhaile_rootful_quadlet_entries": quadlet_entries,
                    },
                    "roles": ["rootful_unit_preflight"],
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
        ["-i", "localhost,", "--connection=local", "--check", str(playbook)],
        _closed_environment(environment_root),
    )
    return result.returncode, result.stdout, result.stderr


@pytest.mark.integration
def test_preflight_resolves_systemd_dependency_on_generated_quadlet(tmp_path: Path) -> None:
    """Verify one graph containing an ordinary unit and a generated unit."""
    rendered = tmp_path / "rendered"
    generated = _entry(
        rendered,
        "services/example/etc/containers/systemd/abhaile-graph.container",
        target_path="/etc/containers/systemd/abhaile-graph.container",
        kind="quadlet.container",
        owner_ref="unit:abhaile-graph.service",
        content="[Container]\nImage=docker.io/library/busybox:latest\nExec=sleep infinity\n",
        apply_hints={"rootless": False},
    )
    ordinary = _entry(
        rendered,
        "services/example/etc/systemd/system/abhaile-graph-consumer.service",
        target_path="/etc/systemd/system/abhaile-graph-consumer.service",
        kind="systemd.unit",
        owner_ref="unit:abhaile-graph-consumer.service",
        content=(
            "[Unit]\nRequires=abhaile-graph.service\nAfter=abhaile-graph.service\n"
            "[Service]\nType=oneshot\nExecStart=/bin/true\n"
        ),
    )

    code, stdout, stderr = _run_preflight(tmp_path, rendered, [ordinary], [generated])

    assert code == 0, stdout + stderr
    assert "Generate candidate rootful Quadlet units" in stdout
    assert "Verify complete desired rootful unit graph" in stdout


@pytest.mark.integration
def test_preflight_rejects_missing_cross_family_dependency(tmp_path: Path) -> None:
    """Reject an ordinary unit whose required generated unit is absent."""
    rendered = tmp_path / "rendered"
    ordinary = _entry(
        rendered,
        "services/example/etc/systemd/system/abhaile-missing-consumer.service",
        target_path="/etc/systemd/system/abhaile-missing-consumer.service",
        kind="systemd.unit",
        owner_ref="unit:abhaile-missing-consumer.service",
        content=(
            "[Unit]\nRequires=abhaile-definitely-missing.service\n"
            "[Service]\nType=oneshot\nExecStart=/bin/true\n"
        ),
    )

    code, _stdout, _stderr = _run_preflight(tmp_path, rendered, [ordinary], [])

    assert code != 0
