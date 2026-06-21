# Abhaile Test Suite

## Overview

Pytest suite covering the Abhaile Python package: render, apply, DNS, validation, composition/include behavior, and manifest generation.

The test suite is organized into both unit and integration layers.

## Test Statistics

- **Unit Tests:** covers `utils`, `validation`, `renderers`, `dns`, `apply`, `plan`, `state`, and `cli`
- **Integration Tests:** render pipeline, apply pipeline, runner, bootstrap, and feature-level suites (DNS, ingress, quadlets, vault templates, composition includes)
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
│       ├── models/
│       │   └── test_artifact.py             # RenderMetadata and artifact model tests
│       ├── utils/
│       │   └── test_artifact_collector.py   # ArtifactCollector unit tests
│       ├── plan/
│       │   └── test_diff.py                 # Drift planning logic tests
│       ├── state/
│       │   └── test_history.py              # State rotation and history retention
│       ├── cli/
│       │   ├── test_apply_diff_cli.py       # Apply and diff CLI integration
│       │   ├── test_diff_exit_codes.py      # Diff exit code semantics
│       │   └── test_inventory.py            # Inventory CLI tests
│       ├── apply/
│       │   ├── test_actions.py              # File staging, atomic copy, validation
│       │   ├── test_systemd.py              # Systemd executor behavior
│       │   ├── test_users_executor.py       # User management executor
│       │   ├── test_coredns_executor.py     # CoreDNS executor
│       │   ├── test_caddy_executor.py       # Caddy executor
│       │   ├── test_vault_executor.py       # Vault-agent executor
│       │   ├── test_service_executor.py     # Service config executor
│       │   ├── test_networkd_executor.py    # Networkd executor
│       │   └── test_quadlet_executor.py     # Quadlet executor
│       ├── validation/
│       │   ├── test_network.py              # VLAN/IP/collision sanity checks
│       │   ├── test_schema.py              # Schema validation error reporting
│       │   ├── test_services.py             # Service definition checks
│       │   └── test_users.py                # UID/GID conflict validation
│       ├── dns/
│       │   ├── test_provider_resolution.py  # DNS provider/zone source resolution
│       │   └── test_serial_validator.py     # serial/hash validation logic
│       └── renderers/
│           ├── test_manifest.py             # Manifest generation and writing
│           ├── test_metadata.py             # Artifact metadata classification
│           ├── test_networkd.py             # networkd files + drop-ins
│           ├── test_users.py                # User/group/sudoers rendering
│           ├── test_software.py             # Software artifact rendering
│           ├── test_services_*.py           # Service config rendering behavior
│           ├── test_ingress*.py             # Ingress aggregation/error paths
│           ├── test_quadlets_*.py           # Container/pod/validation behavior
│           ├── test_dns_*.py                # DNS rendering and serial behavior
│           └── test_vault_templates_*.py    # Vault template discovery/rendering
└── integration/
    ├── test_render_e2e.py                   # End-to-end render pipeline tests
    ├── test_apply_integration.py            # Apply pipeline integration tests
    ├── test_runner.py                       # GitOps runner integration tests
    ├── test_bootstrap.py                    # Bootstrap script integration tests
    ├── test_dns.py                          # DNS integration scenarios
    ├── test_ingress.py                      # Ingress aggregation scenarios
    ├── test_quadlets.py                     # Quadlet integration scenarios
    ├── test_vault_templates.py              # Vault template integration scenarios
    └── test_composition_includes.py         # Include traversal across renderers
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
- Drift planning (write classification, removal safety, owner dependency ordering)
- Apply executor families (systemd, users, coredns, caddy, vault, networkd, quadlet, service)
- Apply CLI (dry-run, prune modes, host safety gate, JSON reporting)
- State rotation (manifest archival, history retention, bounded cleanup)
- GitOps runner (commit tracking, rollback retry, locking)
- Bootstrap (preflight checks, token input, stage sequencing)

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

- Artifact ordering by render_path
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
- ✓ Drift planning (write/removal classification, owner ordering)
- ✓ Apply executor families (systemd, users, coredns, caddy, vault, networkd, quadlet, service)
- ✓ Apply CLI (dry-run, prune, host safety, JSON output)
- ✓ Diff CLI (exit codes, metadata-only changes)
- ✓ Inventory CLI (JSON output, validation mode)
- ✓ State rotation (history retention, manifest archival)
- ✓ GitOps runner (fetch/detect/apply cycle, rollback, locking)
- ✓ Bootstrap (preflight, token handling, idempotency)

Not yet covered:

- Host-level shell orchestration tests for bootstrap/runner scripts (tested via integration smoke checks only)
- nftables ruleset validation (Phase 3/4 hardening, not yet implemented)

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
