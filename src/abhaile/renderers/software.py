"""Software renderer for host software artifacts."""

from __future__ import annotations

from pathlib import Path
import yaml

from abhaile.renderers.collector import ArtifactCollector
from abhaile.models.software import parse_software_operation
from abhaile.utils.composition import walk_host_includes
from abhaile.utils.config import read_json, read_yaml_mapping
from abhaile.utils.errors import RenderError
from abhaile.validation.schema import validate_schema

SOFTWARE_KEYS = ("packages", "downloads", "builds", "commands")
ENTRY_KEYS = ("downloads", "builds", "commands")


def render_software_artifacts(
    host: str,
    config_root: Path,
    output_dir: Path,
    *,
    collector: ArtifactCollector | None = None,
    rendered_root: Path | None = None,
) -> None:
    """Render software package/install artifacts for a host.

    Output:
    - software/packages.txt: merged package ids in deterministic order
    - software/downloads/<id>.yaml: resolved download specs
    - software/builds/<id>.yaml: resolved build specs
    - software/commands/<id>.yaml: resolved command specs
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    ordered_hosts = walk_host_includes(host, config_root)
    refs, sources = _collect_software_refs(ordered_hosts, config_root)

    packages_path = output_dir / "packages.txt"
    _write_packages_file(refs["packages"], packages_path)
    _register_software_artifact(
        collector,
        rendered_root,
        packages_path,
        operation_id="packages",
        operation_type="packages",
        kind="software.packages",
        effects=[
            {"kind": "package", "target": package, "role": "requirement"}
            for package in refs["packages"]
        ],
    )

    schema_path = config_root.parent / "schemas" / "software-action.schema.json"
    schema = read_json(schema_path)

    for key in ENTRY_KEYS:
        category_output_dir = output_dir / key
        category_output_dir.mkdir(parents=True, exist_ok=True)

        for ref in refs[key]:
            source_host = sources[(key, ref)]
            source_path = config_root / "hosts" / source_host / "software" / key / f"{ref}.yaml"
            if not source_path.exists():
                raise RenderError(f"Missing software {key} spec: {source_path}")

            spec = read_yaml_mapping(source_path)
            validate_schema(spec, schema, str(source_path), schema_path)
            operation = parse_software_operation(spec)

            spec_id = spec.get("id")
            if spec_id != ref:
                raise RenderError(
                    f"Software {key} spec id mismatch in {source_path}: "
                    f"expected id '{ref}', got '{spec_id}'"
                )

            rendered_path = category_output_dir / f"{ref}.yaml"
            rendered_path.write_text(
                yaml.safe_dump(spec, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )
            _register_software_artifact(
                collector,
                rendered_root,
                rendered_path,
                operation_id=ref,
                operation_type=operation.operation_type,
                execution_policy=operation.execution_policy,
                effects=[effect.manifest_value() for effect in operation.effects],
                kind={
                    "downloads": "software.download",
                    "builds": "software.build",
                    "commands": "software.prerequisite",
                }[key],
            )


def _collect_software_refs(
    ordered_hosts: list[str],
    config_root: Path,
) -> tuple[dict[str, list[str]], dict[tuple[str, str], str]]:
    """Collect merged software references with duplicate detection."""
    refs: dict[str, list[str]] = {key: [] for key in SOFTWARE_KEYS}
    seen: dict[str, set[str]] = {key: set() for key in SOFTWARE_KEYS}
    sources: dict[tuple[str, str], str] = {}

    for host_name in ordered_hosts:
        host_path = config_root / "hosts" / host_name / "host.yaml"
        host_data = read_yaml_mapping(host_path)
        composition = host_data.get("composition", {}) or {}
        software = composition.get("software", {}) or {}

        for key in SOFTWARE_KEYS:
            items = software.get(key, []) or []
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise RenderError(
                    f"composition.software.{key} must be a list of strings: {host_path}"
                )

            for item in items:
                if item in seen[key]:
                    raise RenderError(
                        f"Duplicate software {key} entry '{item}' while resolving host '{ordered_hosts[-1]}'"
                    )
                seen[key].add(item)
                refs[key].append(item)
                if key in ENTRY_KEYS:
                    sources[(key, item)] = host_name

    return refs, sources


def _write_packages_file(packages: list[str], destination: Path) -> None:
    """Write merged package list as a deterministic newline-delimited file."""
    lines = [f"{pkg}\n" for pkg in packages]
    destination.write_text("".join(lines), encoding="utf-8")


def _register_software_artifact(
    collector: ArtifactCollector | None,
    rendered_root: Path | None,
    path: Path,
    *,
    operation_id: str,
    operation_type: str,
    execution_policy: str = "admitted",
    effects: list[dict[str, object]] | None = None,
    kind: str,
) -> None:
    """Register a typed software plan without authorizing its execution."""
    if collector is None or rendered_root is None:
        return
    render_path = path.relative_to(rendered_root).as_posix()
    owner_ref = f"software:{operation_id}"
    collector.register_artifact(
        render_path=render_path,
        target_path="",
        kind=kind,
        owner_ref=owner_ref,
        content=path.read_bytes(),
        apply_hints={
            "operation_id": operation_id,
            "operation_type": operation_type,
            "execution_policy": execution_policy,
            "effects": effects or [],
        },
    )
    collector.register_owner(
        owner_ref,
        description=f"Typed software operation {operation_id}",
        requires=[] if operation_id == "packages" else ["software:packages"],
    )
