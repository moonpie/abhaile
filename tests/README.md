# Tests Directory Structure

This directory contains unit and integration tests for the Abhaile project, organized by layer and concern.

## Directory Layout

```text
tests/
├── conftest.py                        # Root fixtures (repo_root, paths)
├── README.md                          # This file
│
├── unit/                              # Pure unit tests (mocked, no subprocess)
│   ├── conftest.py                    # Unit fixtures (mock configs, structures)
│   │
│   ├── common/
│   │   ├── __init__.py
│   │   └── test_core_lib.py           # RenderError, load_yaml, utils
│   │
│   ├── render/
│   │   ├── __init__.py
│   │   ├── test_render_orchestrator.py  # tools.render.render module
│   │   ├── test_dns_builder.py          # DNS zone generation
│   │   ├── test_host_builder.py         # .network/.netdev file generation
│   │   ├── test_network_builder.py      # VLAN topology & interface mapping
│   │   ├── test_quadlet_builder.py      # Podman network units
│   │   ├── test_services_service_builder.py  # Service config templating
│   │   ├── test_services_caddy_builder.py    # Caddy-specific logic
│   │   └── test_services_vault_template_builder.py  # Vault Agent templates
│   │
│   ├── inventory/
│   │   ├── __init__.py
│   │   ├── test_generate_inventory.py   # Orchestration
│   │   ├── test_analyzers.py            # Analysis logic
│   │   ├── test_collectors.py           # Data collection
│   │   └── test_formatters.py           # Output formatting
│   │
│   └── validate/
│       ├── __init__.py
│       └── test_validate_lib.py         # Schema validation
│
├── integration/                       # End-to-end tests (subprocess, real files)
│   ├── conftest.py                    # Integration fixtures
│   ├── __init__.py
│   │
│   ├── test_render_workflows.py       # Consolidated render pipeline tests
│   ├── test_apply_workflows.py        # Apply deployment workflow tests
│   ├── test_apply_full_workflow.py    # Legacy apply tests (to be merged)
│   └── test_dns_cli.py                # DNS CLI integration tests
│
└── fixtures/
    ├── __init__.py
    └── (future: shared test data builders)
```

## Test Categories

### Test Layer Philosophy

Abhaile uses a **three-tier testing strategy** that balances speed, maintainability, and confidence:

#### **Unit Tests** (`tests/unit/`) - Fast, Isolated, Focused

Unit tests verify individual functions and classes in isolation using mocks and temporary paths.

**Purpose:**

- Test single responsibility: one function/class per test
- Validate logic without external dependencies
- Enable rapid test-driven development (TDD)
- Provide fast feedback loop (\<1 second per test)

**Rules:**

- ❌ **Never** use `subprocess.run()` or spawn external processes
- ❌ **Never** depend on real network, filesystem (except tmp_path), or external services
- ✅ Use `tmp_path` fixture for temporary files
- ✅ Use `monkeypatch` for mocking imports/functions/environment variables
- ✅ Test logic and edge cases, not I/O workflows
- ✅ Run fast (\<1 second each)
- ✅ Use class-based organization for related tests (e.g., `TestStripCIDR`)

**When to write unit tests:**

- Testing pure functions (input → output)
- Validating error handling and edge cases
- Testing template rendering logic
- Verifying data transformations

**Example:**

```python
def test_strip_cidr_with_suffix():
    \"\"\"Unit test: pure function with mocked input.\"\"\"
    assert strip_cidr(\"192.168.1.1/24\") == \"192.168.1.1\"
```

______________________________________________________________________

#### **Integration Tests** (`tests/integration/`) - Real I/O, Multi-Module

Integration tests verify workflows across module boundaries using real subprocess calls and file I/O.

**Purpose:**

- Test complete workflows (mapping → render → apply)
- Verify multi-module interactions
- Validate real command execution and file operations
- Catch integration issues missed by unit tests

**Rules:**

- ✅ Use `subprocess.run()` for real command execution
- ✅ Test complete workflows (e.g., render all hosts → verify output structure)
- ✅ Use `integration_tmp_repo` fixture for realistic repo structures
- ✅ Focus on real-world scenarios and error conditions
- ❌ Don't test low-level logic (belongs in unit tests)
- ❌ Don't duplicate unit test coverage

**When to write integration tests:**

- Testing CLI commands end-to-end
- Validating file generation workflows
- Testing drift detection and apply logic
- Verifying error handling across module boundaries

**Example:**

```python
def test_render_all_hosts_success(tmp_path):
    \"\"\"Integration test: real subprocess call, file I/O.\"\"\"
    result = subprocess.run(
        [\"python3\", \"tools/render/cli.py\"],
        cwd=tmp_path, capture_output=True
    )
    assert result.returncode == 0
    assert (tmp_path / \"out/rendered/phobos\").exists()
```

______________________________________________________________________

#### **E2E Tests** (`tests/e2e/`) - Full Stack, External Dependencies

End-to-end tests verify the complete system with real external services (future).

**Purpose:**

- Test complete deployment cycles
- Verify integration with Vault, deSEC, Podman
- Validate production-like scenarios
- Serve as smoke tests before releases

**Rules:**

- ✅ Use real external services (Vault, deSEC, containers)
- ✅ Test complete user workflows
- ✅ Slow but comprehensive (>30 seconds per test)
- ✅ Require environment variables or test credentials
- ❌ Should not run in CI by default (opt-in via `E2E_SMOKE=1`)

**Current Status:** Minimal E2E tests; most testing done at unit/integration layers.

______________________________________________________________________

### Test Organization Guidelines

**Eliminate Duplication:**

- Each piece of functionality should be tested **once** at the appropriate layer
- If testing the same logic in multiple layers, consolidate to the lowest appropriate layer
- Use class-based organization for related tests (e.g., `TestStripCIDR`, `TestValidateNetworkConfig`)

**Layer Selection:**

- **Unit:** Pure functions, data transformations, validation logic
- **Integration:** CLI commands, file generation, multi-module workflows
- **E2E:** Complete system tests with external dependencies

**Test Naming:**

- Unit tests: `test_<function_name>_<scenario>` (e.g., `test_strip_cidr_with_suffix`)
- Integration tests: `test_<workflow>_<outcome>` (e.g., `test_render_all_hosts_success`)
- Test classes: `Test<ComponentName>` (e.g., `TestStripCIDR`, `TestRenderOrchestrator`)

______________________________________________________________________

### Test Tier Philosophy (Legacy - kept for reference)

- **Unit tests**: Test individual functions/classes in isolation with mocked dependencies
- **Integration tests**: Test workflows across module boundaries with real I/O
- **E2E tests** (future): Test complete system with external dependencies (Vault, deSEC, containers)

### Unit Tests (`tests/unit/`)

Pure unit tests that test single modules/functions in isolation using mocks and temporary paths.

**Rules for unit tests:**

- ❌ **Never** use `subprocess.run()` or spawn external processes
- ✅ Use `tmp_path` for temporary files
- ✅ Use `monkeypatch` for mocking imports/functions
- ✅ Test logic, not I/O
- ✅ Run fast (\<1 second each)

**By subdirectory:**

#### `common/`

- Core utilities: `RenderError`, `load_yaml()`, validation helpers
- Path resolution and config handling

#### `render/`

- **test_render_orchestrator.py**: `render_host()`, context building, file mapping logic
- **test_dns_builder.py**: DNS zone generation, Corefile assembly, serial management
- **test_host_builder.py**: `.network` templating, drop-in generation, interface binding
- **test_network_builder.py**: VLAN topology, host↔service mapping, validation
- **test_quadlet_builder.py**: Podman network unit generation per VLAN
- **test_services_service_builder.py**: Service config rendering, templating, placeholder substitution
- **test_services_caddy_builder.py**: Caddy-specific configuration logic
- **test_services_vault_template_builder.py**: Vault Agent template collection

#### `inventory/`

- **test_generate_inventory.py**: Orchestration, file writing, deployment filtering
- **test_analyzers.py**: Service classification, deployment graphs, network analysis
- **test_collectors.py**: Metadata extraction, YAML parsing
- **test_formatters.py**: Markdown/JSON generation, validation reporting

#### `validate/`

- Config schema validation, consistency checks

### Integration Tests (`tests/integration/`)

End-to-end tests that exercise real workflows using subprocess calls, actual file I/O, and multi-module interactions.

**Rules for integration tests:**

- ✅ Use `subprocess.run()` for real command execution
- ✅ Test complete workflows (mapping → render → apply)
- ✅ Use `integration_tmp_repo` fixture for realistic repo structures
- ❌ Don't test low-level logic (belongs in unit tests)
- ✅ Focus on real-world scenarios and error conditions

**Test files:**

- **test_render_workflows.py**:

  - All render workflows consolidated into one file
  - `cli.py` (all hosts) renders phobos and deimos with full context
  - Single host rendering, output structure verification
  - Idempotency checks (multiple renders produce same output)
  - Error handling (missing configs, invalid YAML)
  - Mapping-driven rendering logic
  - Bootstrap scenarios (minimal repo initialization)

- **test_apply_workflows.py**:

  - Apply deployment workflows (dry-run, verbose mode)
  - Drift detection and validation
  - Error handling (missing host, missing render output)
  - Help/usage information
  - Network file validation
  - Skip-render functionality

- **test_dns_cli.py**:

  - DNS CLI command integration tests
  - Zone management operations

- **test_apply_full_workflow.py**:

  - Legacy apply tests (lower-level implementation details)
  - To be reviewed/merged into test_apply_workflows.py

## Recent Changes (2026-01-08)

### Test Suite Simplification

The test suite was streamlined to reduce duplication and maintenance burden:

**Removed:**

- 4 bash unit test files (~350 LOC) - replaced by shellcheck + integration tests
- 3 redundant integration test files consolidated into `test_render_workflows.py`
  - `test_render_full_pipeline.py`
  - `test_mapping_to_rendering.py`
  - `test_deployment_cycle.py`
  - `test_bootstrap_full_setup.py`

**Added:**

- `test_render_workflows.py` - consolidated render integration tests
- `test_apply_workflows.py` - comprehensive apply workflow tests

**Result:**

- Reduced test count by ~30% (291 → ~210 tests)

- Eliminated ~40% of integration test duplication

- Improved coverage of critical apply.sh workflows

- Maintained quality while reducing maintenance burden

  - Bootstrap → Render → Apply (dry-run) → Verify
  - Repeated renders are idempotent
  - No drift on second render

## Running Tests

```bash
# Run all tests
pytest

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run a specific test file
pytest tests/unit/render/test_dns_builder.py

# Run a specific test class or function
pytest tests/unit/render/test_dns_builder.py::TestDNSZoneGeneration::test_zone_from_services

# Verbose output
pytest -v

# Show print statements
pytest -s

# Stop on first failure
pytest -x

# Run with coverage
pytest --cov=tools tests/
```

## Fixtures

### Root Fixtures (`tests/conftest.py`)

- `repo_root`: Repository root path
- `config_dir`: Path to `config/` directory
- `tools_dir`: Path to `tools/` directory

### Unit Fixtures (`tests/unit/conftest.py`)

- `mock_network_config`: Standard network.yaml structure in tmp_path
- `mock_service_metadata`: Standard service metadata
- `mock_mapping_config`: Standard mapping.yaml structure
- `inventory_dir`: Mock inventory directory with empty JSON files
- `rendered_dir`: Mock output directory with host subdirectories

### Integration Fixtures (`tests/integration/conftest.py`)

- `integration_tmp_repo`: Full temporary repo with minimal valid config (mapping, network, services, hosts)
- `render_script`: Path to `tools/render/cli.py`
- `apply_script`: Path to `tools/apply/apply.sh`
- `repo_root`: Repository root path

## Conventions

### Naming Standards

All test files follow consistent naming patterns:

| Convention | Rule | Example |
|------------|------|---------|
| **File names** | `test_<module>.py` or `test_<workflow>.py` | `test_dns_builder.py`, `test_render_full_pipeline.py` |
| **Class names** | `Test<Feature>` or `Test<Component><Action>` | `TestDNSBuilder`, `TestSerialCalculation` |
| **Function names** | `test_<what>_<condition>_<expectation>` | `test_build_dns_context_creates_ptr_records()` |

**Subject-to-filename mapping:**

- Unit tests mirror source modules: `tests/unit/render/test_dns_builder.py` tests `tools/render/dns/dns_builder.py`
- Integration tests describe workflows: `test_render_full_pipeline.py` tests complete render execution
- All 26 test files use `test_*.py` pattern (no `*_test.py` variants)

### Tier Comparison

| Aspect | Unit | Integration | E2E (future) |
|--------|------|-------------|--------------|
| **Location** | `tests/unit/<domain>/` | `tests/integration/` | `tests/e2e/` |
| **Scope** | Single module | Multi-module workflow | Full system |
| **I/O** | Mocked (tmp_path) | Real (subprocess, files) | Production-like |
| **Speed** | Fast (\<1s) | Moderate (1-30s) | Slow (minutes) |
| **Subprocess** | ❌ Never | ✅ Required | ✅ Required |
| **External Deps** | ❌ None | ❌ None | ✅ Containers, Vault, deSEC |

## Writing New Tests

### Test Design Principles

1. **One assertion concept per test** - test one behavior at a time
1. **Arrange-Act-Assert** - clear three-part structure
1. **Descriptive names** - test name should describe expected behavior
1. **Use fixtures** - share setup via conftest.py
1. **Avoid interdependence** - tests should be runnable in any order
1. **Keep tests fast** - optimize for fast feedback loops
1. **Test behavior, not implementation** - focus on outcomes

### Adding a Unit Test

1. Find or create the appropriate subdirectory under `tests/unit/`
1. Create `test_<module_name>.py` matching the source module structure
1. Import and mock dependencies using `monkeypatch` or `tmp_path`
1. Use fixtures from `tests/unit/conftest.py` for common structures
1. Example:

```python
# tests/unit/render/test_dns_builder.py
import pytest
from tools.render.dns import build_zones

def test_zones_from_deployed_services(mock_mapping_config, tmp_path):
    """Should build DNS zones only for deployed services."""
    mapping, _ = mock_mapping_config
    services = {"svc1": {...}, "svc2": {...}}

    zones = build_zones(mapping, services)

    assert len(zones) == 1  # Only deployed
    assert "svc1" in zones
```

### Adding an Integration Test

1. Create a new file in `tests/integration/test_<workflow_name>.py`
1. Use `integration_tmp_repo` fixture to set up a realistic repo
1. Call subprocess commands and verify outputs
1. Example:

```python
# tests/integration/test_render_full_pipeline.py
import subprocess

def test_render_all_hosts(integration_tmp_repo, render_script):
    """Should render all hosts without errors."""
    result = subprocess.run(
        ["python3", str(render_script)],
        cwd=integration_tmp_repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    out_dir = integration_tmp_repo / "out" / "rendered"
    assert (out_dir / "phobos").exists()
    assert (out_dir / "deimos").exists()
```

## Notes

- The structure mirrors `tools/` layout: if you add a new tool, add corresponding tests under `tests/unit/<tool>/`
- Integration tests focus on **workflows**, not individual commands
- Keep unit tests fast; slow tests discourage running them frequently
- See `conftest.py` files for available fixtures before writing setup code
