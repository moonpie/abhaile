"""Centralized path resolution for development and production environments.

This module provides the PathConfig class for consistent path management
across all Abhaile Python tools. It handles:
- Repository root detection
- Dev vs prod path layouts from paths.ini
- Output/state/config/secrets directory resolution
- Path validation and writability checks

See docs/PATH_RESOLUTION.md for design rationale and usage patterns.
"""

import os
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PathConfig:
    """Centralized path resolution for development and production.

    Attributes:
        repo_root: Repository root directory (contains .git/)
        config_root: Configuration directory (config/)
        output_root: Rendered output directory (out/rendered/ or custom)
        state_root: State files directory (out/state/ or custom)
        secrets_root: Secrets directory (/etc/abhaile/ in prod, secrets/ in dev)
    """

    repo_root: Path
    config_root: Path
    output_root: Path
    state_root: Path
    secrets_root: Path

    @classmethod
    def from_env(
        cls,
        output_root: Optional[Path] = None,
        state_root: Optional[Path] = None,
        secrets_root: Optional[Path] = None,
    ) -> "PathConfig":
        """Create resolver from environment (dev or prod).

        Loads paths from tools/paths.ini and applies dev/prod mode detection.

        Args:
            output_root: Custom output directory (overrides paths.ini)
            state_root: Custom state directory (overrides paths.ini)
            secrets_root: Custom secrets directory (overrides paths.ini)

        Returns:
            PathConfig instance with resolved paths

        Raises:
            RuntimeError: If repository root cannot be found or paths.ini missing
        """
        repo_root = cls._find_repo_root()
        config_root = repo_root / "config"

        # Load paths from paths.ini
        ini_paths = cls._load_paths_ini(repo_root)

        # Detect production mode: check if repo is at production location
        # If repo_root matches the production path in INI, we're in production
        prod_repo_root = Path(ini_paths["repo_root"])
        dev_mode = repo_root.resolve() != prod_repo_root.resolve()

        # Use INI-defined paths unless overridden
        if output_root is None:
            if dev_mode:
                output_root = repo_root / ini_paths["dev_rendered_dir"]
            else:
                output_root = Path(ini_paths["rendered_dir"])

        # After output_root is set, re-check dev mode based on actual output location
        # If output is outside repo, it's production mode
        try:
            output_root.resolve().relative_to(repo_root.resolve())
            # Output is inside repo - keep current dev_mode setting
        except ValueError:
            # Output is outside repo - force production mode
            dev_mode = False

        if state_root is None:
            # If output_root was customized, derive state from its parent
            # Otherwise use INI-defined state path
            custom_output = output_root != (
                repo_root / ini_paths["dev_rendered_dir"]
            ) and output_root != Path(ini_paths["rendered_dir"])
            if custom_output:
                # Custom output_root: derive state from parent
                state_root = output_root.parent / "state"
            else:
                # Standard INI paths
                if dev_mode:
                    state_root = repo_root / ini_paths["dev_state_dir"]
                else:
                    state_root = Path(ini_paths["state_dir"])

        if secrets_root is None:
            if dev_mode:
                secrets_root = repo_root / "secrets"
            else:
                secrets_root = Path(ini_paths["secrets_base_dir"])

        return cls(
            repo_root=repo_root,
            config_root=config_root,
            output_root=output_root,
            state_root=state_root,
            secrets_root=secrets_root,
        )

    @staticmethod
    def _find_repo_root() -> Path:
        """Find repository root by searching for .git/ directory.

        Searches from current working directory first, then from module location.
        This supports both normal usage and integration tests with temp repos.

        Returns:
            Path to repository root

        Raises:
            RuntimeError: If .git/ directory not found (not in repo)
        """
        # First try from current working directory (supports integration tests)
        current = Path.cwd().resolve()
        while current != current.parent:
            if (current / ".git").is_dir():
                return current
            current = current.parent

        # Fall back to searching from module location
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        raise RuntimeError(
            "Could not find repository root (.git/ directory). "
            "Ensure this tool is run from within the abhaile repository."
        )

    @staticmethod
    def _load_paths_ini(repo_root: Path) -> dict[str, str]:
        """Load paths from tools/paths.ini.

        Args:
            repo_root: Repository root directory

        Returns:
            Dict with all path values from INI file

        Raises:
            RuntimeError: If paths.ini not found or cannot be parsed
        """
        ini_file = repo_root / "tools" / "paths.ini"
        if not ini_file.exists():
            raise RuntimeError(
                f"paths.ini not found at {ini_file}\n"
                f"Ensure you are running from the abhaile repository."
            )

        parser = ConfigParser()
        try:
            parser.read(ini_file)
        except Exception as e:
            raise RuntimeError(f"Failed to parse {ini_file}: {e}") from e

        # Extract all paths into flat dict for easy access
        paths = {}
        for section in parser.sections():
            for key, value in parser.items(section):
                paths[key] = value

        # Validate required keys exist
        required = [
            "repo_root",
            "rendered_dir",
            "state_dir",
            "secrets_base_dir",
            "dev_rendered_dir",
            "dev_state_dir",
        ]
        missing = [k for k in required if k not in paths]
        if missing:
            raise RuntimeError(f"paths.ini missing required keys: {', '.join(missing)}")

        return paths

    def validate_writable(self) -> None:
        """Validate that output and state directories are writable.

        Checks that parent directories exist and are writable before
        attempting to create output/state directories.

        Raises:
            PermissionError: If parent directories don't exist or aren't writable
        """
        for path in [self.output_root, self.state_root]:
            parent = path.parent
            if not parent.exists():
                raise PermissionError(
                    f"Parent directory does not exist: {parent}\n"
                    f"Create it first or adjust --output-dir / --state-dir flags."
                )
            if not os.access(parent, os.W_OK):
                raise PermissionError(
                    f"Parent directory not writable: {parent}\n"
                    f"Check permissions or run with appropriate privileges."
                )

    def ensure_dirs(self) -> None:
        """Create output and state directories if they don't exist.

        Creates directories with parents=True. Safe to call multiple times.

        Raises:
            PermissionError: If creation fails due to permissions
        """
        try:
            self.output_root.mkdir(parents=True, exist_ok=True)
            self.state_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise PermissionError(
                f"Failed to create directory: {e}\n"
                f"Check permissions or run with appropriate privileges."
            ) from e

    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        return (
            f"PathConfig(\n"
            f"  repo_root={self.repo_root},\n"
            f"  config_root={self.config_root},\n"
            f"  output_root={self.output_root},\n"
            f"  state_root={self.state_root},\n"
            f"  secrets_root={self.secrets_root}\n"
            f")"
        )
