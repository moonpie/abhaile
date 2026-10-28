"""Validate mapped service definitions and include closures without rendering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from abhaile.utils.config import clear_config_cache, read_json, read_yaml_mapping
from abhaile.utils.errors import RenderError
from abhaile.utils.paths import load_paths
from abhaile.validation.schema import validate_schema
from abhaile.validation.services import (
    parse_mapping,
    validate_config_change_restart_units,
    validate_service_definitions,
    validate_service_names,
)


def validate_project_services(repo_root: Path) -> None:
    """Validate mapping, service names, include closures and runtime declarations."""
    clear_config_cache()
    paths = load_paths(repo_root)
    config_root = repo_root / paths["config_root"]
    schemas_root = repo_root / paths["schemas_root"]
    mapping_path = config_root / "mapping.yaml"
    mapping_schema_path = schemas_root / "mapping.schema.json"
    mapping = read_yaml_mapping(mapping_path)
    validate_schema(mapping, read_json(mapping_schema_path), str(mapping_path), mapping_schema_path)
    host_services = parse_mapping(mapping)
    validate_service_names(config_root)
    service_schema_path = schemas_root / "service.schema.json"
    validate_service_definitions(
        config_root,
        sorted({service for services in host_services.values() for service in services}),
        read_json(service_schema_path),
        service_schema_path,
    )
    validate_config_change_restart_units(config_root, host_services)


def main(argv: list[str] | None = None) -> int:
    """Run read-only service validation for the selected repository."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        validate_project_services(args.repo_root)
    except RenderError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
