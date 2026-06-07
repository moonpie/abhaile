"""Path resolution for render/apply output and configuration."""

from __future__ import annotations

import configparser
from pathlib import Path

from abhaile.utils.errors import RenderError

REQUIRED_PATH_KEYS = {
    "output_root_default",
    "target_root",
    "config_root",
    "schemas_root",
    "hosts_subdir",
    "services_subdir",
    "rendered_dir_name",
    "state_dir_name",
    "system_dir_name",
    "software_dir_name",
    "users_dir_name",
    "services_dir_name",
}


def get_repo_root(script_file: Path) -> Path:
    """Calculate repository root from a script file path.

    Walks up parent directories until pyproject.toml is found.

    Args:
        script_file: Path to the calling script (typically __file__).

    Returns:
        Path to repository root.

    Raises:
        RenderError: If repository root cannot be determined.
    """
    for candidate in [script_file.resolve(), *script_file.resolve().parents]:
        check_dir = candidate if candidate.is_dir() else candidate.parent
        if (check_dir / "pyproject.toml").exists():
            return check_dir

    raise RenderError(f"Could not determine repository root from path: {script_file}")


def load_paths(repo_root: Path) -> dict[str, str]:
    """Load paths from repo-root paths.ini (required).

    Args:
        repo_root: Root of the repository.

    Returns:
        Dictionary of path configuration.

    Raises:
        RenderError: If paths.ini is missing or incomplete.
    """
    paths_ini = repo_root / "paths.ini"
    if not paths_ini.exists():
        raise RenderError(f"Missing required paths file: {paths_ini}")

    config = configparser.ConfigParser()
    config.read(paths_ini)
    if "paths" not in config:
        raise RenderError(f"Missing [paths] section in {paths_ini}")

    values: dict[str, str] = {}
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
    paths: dict[str, str],
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


def normalize_service_prefixed_path(service: str, raw_path: str) -> str:
    """Normalize a path that may be prefixed with a service name.

    Accepts either service-name/relative/path or relative/path and returns the
    normalized relative path without changing filenames or directory structure.
    """
    if raw_path.startswith(f"{service}/"):
        return raw_path[len(service) + 1 :]
    return raw_path
