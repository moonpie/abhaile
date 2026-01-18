"""tools.common: Shared utilities used across tools/ modules.

Modules:
- core: Canonical home for shared Python helpers (YAML loading, error classes, CIDR utilities).

Import from core directly:
  from tools.common.core import load_yaml, ValidationError, RenderError, strip_cidr

Core Exports:
- load_yaml(path: str | Path) -> dict: Load and parse YAML file.
- ValidationError: Exception for configuration/data validation failures.
- RenderError: Exception for template rendering failures.
- strip_cidr(value: str | None) -> str | None: Remove /prefix from CIDR notation (returns None for None input).
"""

__all__ = ["core"]
