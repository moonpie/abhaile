# Abhaile Render Test Suite

## Overview

Comprehensive pytest test suite for the Abhaile render pipeline. All tests pass (32/32 green).

## Test Statistics

- **Unit Tests:** 25 tests across utils, validation, and renderers modules
- **Integration Tests:** 7 end-to-end tests for full render pipeline
- **Total:** 32 tests, all passing
- **Execution Time:** ~7 seconds

## Test Structure

```text
tests/
├── conftest.py                    # Shared pytest fixtures
├── unit/
│   └── python/
│       ├── test_utils.py          # Path resolution, config loading, errors
│       ├── validation/
│       │   └── test_network.py    # Network sanity checks (VLANs, IPs, collisions)
│       └── renderers/
│           └── test_manifest.py   # Manifest generation and writing
└── integration/
    └── test_render_e2e.py         # End-to-end render pipeline tests
```

## Fixtures (conftest.py)

### `tmp_repo`

Creates a minimal temporary repository structure with paths.ini.

- Creates `config/services`, `schemas/`, `scripts/lib/python/` directories
- Generates valid `scripts/paths.ini` with all required keys

### `tmp_repo_with_config`

Extends `tmp_repo` with realistic config files for testing.

- **config/mapping.yaml:** Maps phobos/deimos hosts to test-service
- **config/network.yaml:** Defines VLANs (services 172.20.20.0/24), hosts, service IPs
- **config/services/test-service/service.yaml:** Valid service definition
- **schemas/\*.schema.json:** JSON Schema draft-07 files for validation

### `tmp_output`

Provides a temporary output directory for render artifact testing.

## Unit Tests

### test_utils.py (8 tests)

**TestLoadPaths:**

- `test_load_paths_success` - Loads valid paths.ini
- `test_load_paths_missing_file` - Raises RenderError when paths.ini missing
- `test_load_paths_missing_section` - Raises RenderError when [paths] section missing
- `test_load_paths_missing_keys` - Raises RenderError when required keys missing

**TestResolveOutputRoot:**

- `test_resolve_single_host_default` - Single host without --output uses /var/lib/abhaile
- `test_resolve_single_host_override` - Single host with --output uses provided path
- `test_resolve_all_mode_requires_output` - --all mode requires --output (raises RenderError)
- `test_resolve_all_mode_with_output` - --all mode with --output uses \<output>/\<host>
- `test_resolve_output_structure` - Verifies path structure matches ADR 0001

### test_network.py (8 tests)

**TestNetworkSanity:**

- `test_valid_network` - Valid config passes all checks
- `test_unknown_vlan_host_interface` - Host interface references undefined VLAN
- `test_unknown_vlan_service` - Service references undefined VLAN
- `test_ip_outside_vlan_subnet_host` - Host IP outside its VLAN subnet
- `test_ip_outside_vlan_subnet_service` - Service IP outside its VLAN subnet
- `test_service_ip_outside_ipvlan_range` - Service /32 outside ipvlanl2_range
- `test_duplicate_ip_detection` - Duplicate IPs across hosts detected
- `test_duplicate_ip_host_and_service` - Duplicate IP between host and service detected

### test_manifest.py (8 tests)

**TestBuildManifest:**

- `test_empty_rendered_dir` - Empty directory produces empty artifacts list
- `test_manifest_with_files` - Files in rendered dir become artifacts
- `test_manifest_rel_and_target_paths` - Relative and target paths calculated correctly
- `test_manifest_file_metadata` - SHA256, size, mode, uid, gid captured
- `test_manifest_determinism` - Multiple runs produce identical ordering

**TestWriteManifest:**

- `test_write_manifest_success` - Valid manifest written to JSON file
- `test_write_manifest_parent_creation` - Parent directories created automatically
- `test_write_manifest_formatting` - JSON formatted with indent=2 and trailing newline

## Integration Tests (test_render_e2e.py)

All 7 integration tests verify end-to-end render pipeline behavior:

1. **test_render_single_host_with_manifest** - Single host render produces valid manifest
1. **test_render_all_hosts_separate_manifests** - All-host mode creates separate manifests per host
1. **test_render_empty_dir_produces_empty_manifest** - Empty rendered dir produces valid empty manifest
1. **test_manifest_preserves_file_permissions** - File permissions (mode) preserved in manifest
1. **test_manifest_contains_valid_sha256_hashes** - SHA256 hashes are valid and correct
1. **test_render_with_nested_directories** - Nested directory structures preserved in manifest
1. **test_manifest_determinism_multiple_runs** - Deterministic manifest generation (same content = same manifest)

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run only unit tests
pytest tests/unit/python -v

# Run only integration tests
pytest tests/integration -v

# Run specific test class
pytest tests/unit/python/test_utils.py::TestLoadPaths -v

# Run with coverage
pytest tests/ --cov=scripts/lib/python --cov-report=html
```

## Key Testing Patterns

### Error Handling

Tests verify RenderError exceptions are raised for:

- Missing configuration files
- Invalid paths.ini
- Network sanity violations
- Manifest write failures

### Determinism

Multiple test cases verify deterministic behavior:

- Artifact ordering by rel_path
- Consistent SHA256 hashes
- Identical manifests from identical content

### Path Resolution

Tests cover all combinations:

- Single-host with/without --output
- All-host mode (requires --output)
- Default vs override output roots

### File Metadata

Tests verify manifest captures:

- SHA256 hashes (validated against actual file content)
- File sizes
- Permissions (mode as octal string)
- Owner/group (uid/gid)

## Coverage

The test suite covers:

- ✓ Path resolution (ADR 0001 compliance)
- ✓ Config loading (YAML, JSON)
- ✓ Schema validation (mapping, network, service)
- ✓ Network sanity checks (VLANs, IPs, ranges, collisions)
- ✓ Manifest generation (hashing, ordering, metadata)
- ✓ Manifest writing (file creation, formatting)
- ✓ Error handling (RenderError exceptions)
- ✓ Determinism (consistent outputs)

Not yet covered (planned):

- Networking renderer (systemd-networkd config generation)
- Users renderer (passwd/group rendering)
- Packages renderer (package list rendering)
- Quadlets renderer (Podman quadlet generation)
- Services renderer (service configuration)
- Ingress renderer (Caddy/reverse proxy config)
- Apply pipeline (drift detection, deployment)
- Bash utility library tests

## Continuous Integration

To integrate with CI/CD:

```bash
# In GitHub Actions / GitLab CI / etc.
python -m pip install -q -r requirements.txt pytest
python -m pytest tests/ -v --tb=short --junit-xml=test-results.xml
```

## Maintenance

- Update fixtures in conftest.py when schema or config format changes
- Add tests for new renderers in `tests/unit/python/renderers/test_<renderer>.py`
- Add integration tests for new end-to-end scenarios
- Keep test data in conftest.py fixtures aligned with actual config schema
