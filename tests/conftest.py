"""Root pytest configuration for tests/.

Defines **global-scope fixtures** that apply to all test layers. Layer-specific
fixtures must live in the relevant subpackage conftest (e.g., tests/unit/conftest.py)
to keep the hierarchy clear (global → layer → module).
"""

__all__ = [
    "dns_test_dates",
    "repo_root",
    "config_dir",
    "tools_dir",
]

import types
import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def dns_test_dates():
    """Shared dates for DNS-related tests to avoid hardcoding.

    **Source:** Hardcoded test constants
    **Version:** 2026-01-11
    **Used in:**
    - tests/unit/render/test_dns_builder.py (serial management)
    - tests/unit/render/test_dns_serial.py (date-based serial calculations)

    **Refresh:** Update if DNS serial format changes or when testing
    date-dependent serial rollover behavior.

    Attributes:
    - TODAY: Simulated current date for serial calculations (YYYYMMDD format)
    - SERIAL_META: Date used in network serial metadata fixtures
    - PREVIOUS: Prior committed date for testing rollover scenarios
    """
    return types.SimpleNamespace(
        TODAY="20260101",
        SERIAL_META="20260105",
        PREVIOUS="20251231",
    )


@pytest.fixture(scope="session")
def repo_root():
    """Provide the repository root directory.

    **Source:** Computed from __file__ location
    **Used in:** All test files requiring repo-relative paths
    **Refresh:** Never (computed dynamically)

    Returns absolute path to repository root (parent of tests/ directory).
    """
    return Path(__file__).parent.parent


@pytest.fixture
def config_dir(repo_root):
    """Provide the config directory path.

    **Source:** Derived from repo_root
    **Used in:** Tests that read mapping.yaml, network.yaml, service configs
    **Refresh:** Never (computed dynamically)

    Returns path to config/ directory containing source-of-truth YAML files.
    """
    return repo_root / "config"


@pytest.fixture
def tools_dir(repo_root):
    """Provide the tools directory path.

    **Source:** Derived from repo_root
    **Used in:** Tests that verify tool scripts exist or load modules
    **Refresh:** Never (computed dynamically)

    Returns path to tools/ directory containing render/apply/inventory scripts.
    """
    return repo_root / "tools"
