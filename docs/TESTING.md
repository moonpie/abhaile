# Abhaile Render Test Suite

## Overview

Comprehensive pytest suite for the Abhaile Python package, with strong coverage across render, DNS, validation, composition/include behavior, and manifest generation.

The test suite is organized into both unit and integration layers.

## Test Statistics

- **Unit Tests:** broad coverage across `utils`, `validation`, `renderers`, and `dns`
- **Integration Tests:** render pipeline and feature-level integration suites (DNS, ingress, quadlets, vault templates, composition includes)
- **Total:** hundreds of tests (see "Counting tests" below for exact current values)
- **Execution Time:** depends on environment and selected markers

### Counting tests

Use collection mode to get an exact current count:

```bash
pytest --collect-only -q tests/
```

## Test Structure

```text
tests/
├── conftest.py                              # Shared pytest fixtures
├── unit/
│   └── python/
│       ├── test_utils.py                    # Paths, templating filters, placeholders
│       ├── test_composition.py              # include resolution and cycle checks
│       ├── test_cli_host_configs.py         # host/common config loading behavior
│       ├── validation/
│       │   ├── test_network.py              # VLAN/IP/collision sanity checks
│       │   └── test_schema.py               # schema validation error reporting
│       ├── dns/
│       │   ├── test_provider_resolution.py  # DNS provider/zone source resolution
│       │   └── test_serial_validator.py     # serial/hash validation logic
│       └── renderers/
│           ├── test_manifest.py             # Manifest generation and writing
│           ├── test_networkd.py             # networkd files + drop-ins
│           ├── test_services_*.py           # service config rendering behavior
│           ├── test_ingress*.py             # ingress aggregation/error paths
│           ├── test_quadlets_*.py           # container/pod/validation behavior
│           ├── test_dns_*.py                # DNS rendering and serial behavior
│           └── test_vault_templates_*.py    # vault template discovery/rendering
└── integration/
    ├── test_render_e2e.py                   # End-to-end render pipeline tests
    ├── test_dns.py                          # DNS integration scenarios
    ├── test_ingress.py                      # ingress aggregation scenarios
    ├── test_quadlets.py                     # quadlet integration scenarios
    ├── test_vault_templates.py              # vault template integration scenarios
    └── test_composition_includes.py         # include traversal across renderers
```

## Fixtures (conftest.py)

### `tmp_repo`

Creates a minimal temporary repository structure with paths.ini.

- Creates minimal config/schema/script paths used by tests
- Generates valid repo-root `paths.ini` with all required keys

### `tmp_repo_with_config`

Extends `tmp_repo` with realistic config files for testing.

- **config/mapping.yaml:** Maps phobos/deimos hosts to test-service
- **config/network.yaml:** Defines VLANs (services 172.20.20.0/24), hosts, service IPs
- **config/services/test-service/service.yaml:** Valid service definition
- **schemas/\*.schema.json:** JSON Schema draft-07 files for validation

### `tmp_output`

Provides a temporary output directory for render artifact testing.

## Coverage Highlights

Representative areas covered by tests include:

- Path loading and output root resolution (`--host`, `--all`, and `--output` semantics)
- Network sanity validation (VLAN existence, subnet membership, duplicate IP detection)
- Schema validation diagnostics and error pointer quality
- Host and service composition include traversal and cycle detection
- Service config rendering (static + templated), placeholder resolution, and deterministic ordering
- Systemd-networkd rendering plus service drop-in generation
- Quadlets rendering for containers and pods, including validation/error paths
- DNS record rendering, provider resolution, and serial/content hash validation
- Ingress and vault-template aggregation behavior
- Manifest generation (`sha256`, permissions, uid/gid, deterministic ordering)

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
pytest tests/ --cov=src/abhaile --cov-report=html

# Equivalent Make targets
make test
make unit-test
make integration-test
make coverage
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
- ✓ Composition include traversal and cycle detection
- ✓ DNS rendering, ordering, and serial/hash validation
- ✓ Ingress aggregation and error-path handling
- ✓ Quadlets rendering and validation checks
- ✓ Vault template rendering/discovery and error paths
- ✓ Manifest generation (hashing, ordering, metadata)
- ✓ Manifest writing (file creation, formatting)
- ✓ Error handling (RenderError exceptions)
- ✓ Determinism (consistent outputs)

Not yet covered (planned):

- Apply pipeline execution/orchestration (drift planning is still not implemented)
- Users/software renderer implementation coverage as those renderers are completed
- Host-level shell orchestration tests for future apply/bootstrapping scripts

## Continuous Integration

To integrate with CI/CD:

```bash
# In GitHub Actions / GitLab CI / etc.
python -m pip install -q -r requirements-dev.txt
python -m pytest tests/ -v --tb=short --junit-xml=test-results.xml
```

## Maintenance

- Update fixtures in conftest.py when schema or config format changes
- Add tests for new renderers in `tests/unit/python/renderers/test_<renderer>.py`
- Add integration tests for new end-to-end scenarios
- Keep test data in conftest.py fixtures aligned with actual config schema
- Keep this document aligned with active CLI/package paths (`src/abhaile/`, not legacy script paths)
