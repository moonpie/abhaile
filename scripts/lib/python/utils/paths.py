"""Path resolution for render/apply output and configuration."""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Dict

from utils.errors import RenderError

REQUIRED_PATH_KEYS = {
    "output_root_default",
    "target_root",
    "config_root",
    "schemas_root",
    "hosts_subdir",
    "services_subdir",
    "rendered_dir_name",
    "state_dir_name",
    "systemd_networkd_dir",
    "systemd_resolved_dir",
    "systemd_units_dir",
}


def get_repo_root(script_file: Path) -> Path:
    """Calculate repository root from a script file path.

    Assumes script is in scripts/ directory at repo root.

    Args:
        script_file: Path to the calling script (typically __file__).

    Returns:
        Path to repository root.
    """
    return script_file.resolve().parents[1]


def load_paths(repo_root: Path) -> Dict[str, str]:
    """Load paths from scripts/paths.ini (required).

    Args:
        repo_root: Root of the repository.

    Returns:
        Dictionary of path configuration.

    Raises:
        RenderError: If paths.ini is missing or incomplete.
    """
    paths_ini = repo_root / "scripts" / "paths.ini"
    if not paths_ini.exists():
        raise RenderError(f"Missing required paths file: {paths_ini}")

    config = configparser.ConfigParser()
    config.read(paths_ini)
    if "paths" not in config:
        raise RenderError(f"Missing [paths] section in {paths_ini}")

    values: Dict[str, str] = {}
    missing = []
    for key in sorted(REQUIRED_PATH_KEYS):
        if key not in config["paths"]:
            missing.append(key)
        else:
            values[key] = config["paths"][key].strip()

    if missing:
        missing_str = ", ".join(missing)
        raise RenderError(f"paths.ini missing required keys: {missing_str}")

    return values


def resolve_output_root(
    host: str,
    output_override: Path | None,
    paths: Dict[str, str],
    all_mode: bool,
) -> Path:
    """Resolve output root per ADR 0001.

    The output root is the parent directory of rendered/ and state/ subdirectories.

    Args:
        host: Host name.
        output_override: Optional output root override.
        paths: Path configuration from load_paths().
        all_mode: True if rendering all hosts (--all).

    Returns:
        Output root path.
    """
    if all_mode:
        if output_override is None:
            raise RenderError("--all requires --output to avoid host path collisions")
        return output_override / host

    if output_override is not None:
        return output_override

    return Path(paths["output_root_default"])
