# Spec: Validation Pipeline

## Metadata

```yaml
id: SPEC-2026-007
title: Validation Pipeline
status: accepted
owner: moonpie
created: 2026-06-04
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

Configuration validation is foundational to the render pipeline. Abhaile's declarative
config spans multiple files (mapping.yaml, network.yaml, host.yaml, service.yaml) with
complex cross-file dependencies: VLANs referenced by hosts and services, user/group ID
uniqueness across host includes, DNS zones with content hashes, and service references.

Validation must fail early with precise, actionable error messages before rendering
artifacts, and must catch both schema violations (JSON Schema) and domain-level invariants
(IP collisions, duplicate IDs, missing references).

DNS zone serials require special handling: they track content hashes to detect when zone
records change, triggering operator updates to the serial date/counter fields in
network.yaml. Serial validation runs post-render so operators can examine the rendered
zone content before correcting the serial.

This accepted spec documents the implemented validation architecture,
error handling contracts, and CLI orchestration.

## Requirements

- [x] JSON Schema validation for mapping, network, host, and service config files.
- [x] Cross-file validation: VLAN references, IP uniqueness, host physical-device binding.
- [x] User/group management: UID/GID uniqueness checks across host includes.
- [x] DNS serial validation: content hash mismatch detection with operator guidance.
- [x] Service existence and naming consistency checks.
- [x] Unified error reporting with context (file paths, JSON pointers, schema locations).
- [x] Pre-render validation gate in CLI (synchronous, blocks render on failure).
- [x] Post-render DNS serial validation (after artifacts exist for operator inspection).
- [x] All validation errors raise `RenderError` for consistent CLI handling.

## Constraints

- Validation is deterministic: same input always produces same error or success.
- Schema validation uses JSON Schema draft-07 with local $ref resolution in schemas/ directory.
- Cross-file validation must not require render output (pre-render checks only, except DNS serials).
- Error messages must include file path, data location (JSON pointer), and schema location for debuggability.
- No external service calls during validation (no network access, file I/O only).
- Validation runs unprivileged and does not mutate any state.

## Design

### Validation Layers

The validation pipeline enforces constraints in layers:

1. **Schema validation (JSON Schema):** mapping.yaml, network.yaml, host.yaml, service.yaml validated against schemas/ files with $ref resolution.
1. **Basic network sanity:** VLAN references exist, addresses are within CIDR blocks, IP addresses are unique.
1. **Service checks:** service.yaml files exist for all referenced services, service names match directory names.
1. **Host-specific validation:** physical_device references are defined in network.yaml, user/group IDs are unique within host includes.
1. **DNS serial validation (post-render, per-host):** For each host being rendered, after zone artifacts are materialized, zone content hashes are checked against recorded serials, with operator guidance for corrections.

### Module Structure

#### `abhaile.validation.schema`

Purpose: JSON Schema validation with error formatting.

Functions:

- `validate_schema(data, schema, label, schema_path=None)`: Validate data against JSON Schema draft-07. Raises `RenderError` on validation failure with formatted error paths (JSON pointers) and schema references.
- `_to_json_pointer(path_parts)`: Convert validation error path to RFC 6901 JSON Pointer format for precise error location.
- `_schema_source_label(schema, schema_path)`: Generate readable schema source label for error messages.

Error format:

```text
Schema validation failed:
- <label> at /<path>/<to>/<field>: <message> (schema: <source>#/<schema>/<path>)
- <label> at /<path>/<another>/<field>: <message> (schema: <source>#/<schema>/<path>)
```

$ref resolution: Schemas in the same directory as the referenced schema are pre-loaded
and registered with the JSON Schema validator's registry. Enables modular schema composition.

#### `abhaile.validation.network`

Purpose: Network configuration sanity checks.

Functions:

- `validate_network_sanity(network)`: Validate VLAN definitions, host interface assignments, service addresses, IP collisions.

  - All host interface VLANs must exist in network.vlans.
  - All host interface addresses must be within their VLAN's CIDR block.
  - All service addresses must be within their VLAN's CIDR block.
  - All service /32 addresses must be within ipvlanl2_range (if configured).
  - No duplicate IPs across hosts and services.
  - Raises `RenderError` with all violations listed.

- `validate_host_physical_device(host, host_config, network)`: Ensure host's physical_device (from host.yaml composition.networkd.physical_device) is defined as a VLAN in network.yaml.

#### `abhaile.validation.services`

Purpose: Service reference and naming consistency.

Functions:

- `parse_mapping(mapping)`: Parse mapping.yaml into host -> services mapping. Validates structure (top-level `abhaile` list, single-key host objects, string or dict service entries). Returns dict\[host, list[service_names]\].

- `get_all_services_in_order(mapping)`: Extract unique service names in declaration order from mapping.yaml for DNS serial validation and manifest ordering.

- `ensure_service_definitions(config_root, services)`: Verify that
  config/services/\<service>/service.yaml exists for each service name.
  Returns list of paths. Raises `RenderError` if any missing.

- `validate_service_names(config_root)`: Verify that each service.yaml's
  `name` field matches its directory name
  (config/services/\<dir>/service.yaml must have name: \<dir>).

#### `abhaile.validation.users`

Purpose: User and group management ID consistency.

Functions:

- `validate_user_management_ids(host, config_root)`: Validate user/group ID uniqueness across host includes.
  - Walks host include chain (hosts/\<host>/host.yaml -> composition.include -> parent hosts).
  - Collects uid, gid, and user/group field values from each host in include order.
  - Detects duplicate uid/gid assignments (multiple user/group names with same ID).
  - Detects conflicting field values (same user/group with different uid/gid across includes).
  - Validates list fields (additional_groups, ssh_authorized_keys) are list of strings.
  - Raises `RenderError` with all violations listed.

#### `abhaile.validation.dns`

Purpose: DNS zone serial validation.

Functions:

- `validate_dns_serials(network, deployed_services, config_root)`: Post-render validation that checks if zone record content has changed since last serial update.
  - Collects all mismatches and reports them together (does not fail on first).
  - Runs post-render (after zone files are materialized) to allow operator inspection.
  - Raises `RenderError` with guidance for serial updates if any mismatches detected.

Supporting modules: `abhaile.dns.serial_validator` computes zone content hashes and detects drift:

- `validate_zone_serial(zone, network, deployed_services, config_root)`: Validate a single zone (fails fast).
- `validate_zone_serial_collect(zones, network, deployed_services, config_root)`: Collect all mismatches and return list of error messages (one per zone).
- `compute_content_hash(zone_content)`: SHA256 hash of zone content string.
- `_render_zone_content_for_hash(zone, network, deployed_services, config_root)`: Render zone content using DNS renderer template path to match exact output format.
- `_get_git_head_serial(zone_name)`: Get previous serial from git HEAD for comparison.

### CLI Integration

Entry point: `abhaile-render` (CLI command registered in pyproject.toml, implemented in `abhaile.cli.render:main`).

Validation orchestration in `abhaile.cli.render:load_and_validate`:

```python
def load_and_validate(repo_root, paths) -> ValidatedConfig:
    roots = _resolve_config_roots(repo_root, paths)
    schemas = _load_config_schemas(roots)
    mapping, network = _load_mapping_and_network(roots)
    _validate_mapping_and_network(mapping, network, roots, schemas)  # Pre-render
    host_services = _validate_hosts(mapping, network, roots, schemas)  # Pre-render
    service_paths = _validate_services(host_services, roots, schemas)  # Pre-render
    return ValidatedConfig(...)
```

Execution order within `render_host`:

```python
def render_host(..., mapping, network, ...) -> Path:
  # ... render system, software, users, services artifacts ...
  manifest_path = _write_manifest(host, rendered_dir, collector)

  # Validate DNS serials post-render (after zone files are materialized)
  all_services = get_all_services_in_order(mapping)
  validate_dns_serials(network, all_services, config_root=config_root)

  return manifest_path
```

Complete execution sequence per host:

1. Load and validate all config files (mapping, network, hosts, services).
1. Render host artifacts (system, software, users, services).
1. Write manifest.
1. Validate DNS serials (post-render, after zone files exist).

Failure handling: All validation errors raise `RenderError`. CLI catches `RenderError` and prints
error message to stderr, exits with code 1, and does not mutate any state.

### Error Handling Contract

All validation functions raise `RenderError` (from `abhaile.utils.errors`). Error messages
are user-facing and include:

- File path or config key where error occurred.
- JSON pointer to field within config (if schema error).
- Schema location (file path and JSON pointer within schema).
- List of all violations (not just first one) to minimize retry cycles.
- Actionable guidance (e.g., "Update all zones in config/network.yaml and re-run render").

Example:

```text
Schema validation failed:
- config/network.yaml at /vlans/internal/cidr: 'invalid' is not valid under any of the given schemas (schema: network.schema.json#/properties/vlans/additionalProperties)

Network sanity checks failed:
- Host phobos interface eth0 references unknown vlan 'bad_vlan'
- Service coredns address 10.0.1.5 not in vlan dns 10.0.2.0/24
- Duplicate IP 10.0.1.10 used by host:phobos:eth0, service:ingress

DNS zone serials out of sync:

- Zone 'internal.example.com' content changed but serial not updated
  Current content_hash: 8a3f2b1c...
  Computed content_hash: d9e4c2a7...
  Recommendation: increment serial.counter

Update all zones in config/network.yaml and re-run render.
```

### Data Flow

```text
config/mapping.yaml ─────┐
                         ├─> validate_schema ──> mapping/network/host/service
config/network.yaml ─────┤
                         ├─> validate_network_sanity ──> IP collisions, VLAN refs
config/hosts/*/host.yaml ┤
                         ├─> validate_user_management_ids ──> uid/gid collisions
config/services/*/service.yaml ┘
                         │
                         └─> validate_service_names ──> name/directory match
                         │
                         └─> ensure_service_definitions ──> service.yaml exists
                         │
                         └─> validate_host_physical_device ──> physical_device exists
                         │
                         ├─> RENDER ARTIFACTS
                         │
                         └─> validate_dns_serials ──> content_hash drift
                         │
                         └─> RENDER SUCCESS or RENDER ERROR
```

## Decision Notes

- Decision: Use JSON Schema draft-07 with local $ref resolution in schemas/ directory.

- Rationale: Allows modular schema composition without external registry; schemas remain version-controlled and deterministic.

- Impact: Pre-loads all schemas in same directory for registry; $ref must reference files in schemas/ directory.

- ADR: null

- Decision: Run DNS serial validation after rendering zone files, not before.

- Rationale: Operators need to inspect rendered zone content to decide if serial should be updated; content hash drift may be benign (record reordering, comment changes).

- Impact: Operator workflow includes re-running render until DNS serials pass; render is idempotent so safe to retry.

- ADR: null

- Decision: Collect all violations in each validation step, report together, fail after collecting all errors.

- Rationale: Minimizes retry cycles; operator can fix multiple issues in one config edit.

- Impact: Error messages may be long; helps user fix config systematically.

- ADR: null

- Decision: Walk include chain and detect UID/GID conflicts across parent hosts.

- Rationale: Sysusers benefit from explicit, static IDs; conflicts across includes indicate misconfiguration.

- Impact: Validation runs for each host independently; includes are walked in include order (parent to child).

- ADR: null

- Decision: Make `config_root` parameter required for DNS serial validation; remove legacy synthetic hash format fallback.

- Rationale: Legacy fallback caused inconsistent behavior; CLI always passes config_root, production never relied on fallback.

- Impact: DNS serial validation always uses exact template-rendered zone format; schema validation and dns validation run deterministically.

- ADR: null

- Decision: Compute DNS content hash using the same zone template rendering path as DNS renderer.

- Rationale: Validation must reflect actual rendered zone content; hashing different canonical string than renderer output caused spurious serial drift reports.

- Impact: Serial validation requires config_root and deployed_services to re-render zone content for hash comparison.

- ADR: null

## Acceptance Criteria

- [x] Schema validation implemented for mapping, network, host, service files with $ref resolution.
- [x] Cross-file validation implemented: VLAN refs, IP uniqueness, host physical-device binding.
- [x] User/group ID uniqueness validation implemented across host includes.
- [x] DNS serial validation implemented with content hash drift detection.
- [x] Service existence and naming validation implemented.
- [x] All validation errors use `RenderError` with JSON pointers and schema references.
- [x] Pre-render validation runs before artifact generation; DNS validation runs post-render.
- [x] CLI integration: validation gate in `load_and_validate`, called before rendering each host.
- [x] All validation functions tested (unit tests for logic, integration tests for CLI flow).
- [x] No regressions in existing render and apply tests.

### Evidence

Criterion: Schema validation for mapping, network, host, service files with $ref resolution.

- Implementation evidence: [src/abhaile/validation/schema.py](../../../src/abhaile/validation/schema.py), [schemas/](../../../schemas/) (mapping.schema.json, network.schema.json, service.schema.json, host.schema.json).
- Validation evidence: [tests/unit/python/validation/test_schema.py](../../../tests/unit/python/validation/test_schema.py).

Criterion: Cross-file validation (VLAN refs, IP uniqueness, host physical-device binding).

- Implementation evidence: [src/abhaile/validation/network.py](../../../src/abhaile/validation/network.py).
- Validation evidence: [tests/unit/python/validation/test_network.py](../../../tests/unit/python/validation/test_network.py).

Criterion: User/group ID uniqueness validation across host includes.

- Implementation evidence: [src/abhaile/validation/users.py](../../../src/abhaile/validation/users.py).
- Validation evidence: [tests/unit/python/validation/test_users.py](../../../tests/unit/python/validation/test_users.py).

Criterion: DNS serial validation with content hash drift detection.

- Implementation evidence: [src/abhaile/validation/dns.py](../../../src/abhaile/validation/dns.py), [src/abhaile/dns/serial_validator.py](../../../src/abhaile/dns/serial_validator.py).
- Validation evidence: [tests/integration/test_dns.py](../../../tests/integration/test_dns.py).

Criterion: Service existence and naming validation.

- Implementation evidence: [src/abhaile/validation/services.py](../../../src/abhaile/validation/services.py).
- Validation evidence: [tests/integration/test_render_e2e.py](../../../tests/integration/test_render_e2e.py).

Criterion: CLI integration (validation gate in `load_and_validate`).

- Implementation evidence: [src/abhaile/cli/render.py](../../../src/abhaile/cli/render.py).
- Validation evidence: [tests/unit/python/cli/test_apply_diff_cli.py](../../../tests/unit/python/cli/test_apply_diff_cli.py).

## Out of Scope

- Runtime validation during apply (post-render state checks are apply's responsibility).
- Vault Agent template validation (rendered by vault-agent on-host, not in render pipeline).
- Systemd unit validation (handled by systemctl dry-run during apply).
- CoreDNS zone file validation (handled by named-checkzone during apply if available).
- Podman/quadlet syntax validation (handled by podman/systemd during apply).

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `docs/specs/accepted/0001-render-pipeline.md`
- `docs/adr/0001-output-root-and-environment-paths.md`
- `docs/adr/0004-apply-execution-model.md`
- `docs/adr/0005-service-authoring-model.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `src/abhaile/validation/schema.py`
- `src/abhaile/validation/network.py`
- `src/abhaile/validation/services.py`
- `src/abhaile/validation/users.py`
- `src/abhaile/validation/dns.py`
- `src/abhaile/dns/serial_validator.py`
- `src/abhaile/cli/render.py`
- `schemas/mapping.schema.json`
- `schemas/network.schema.json`
- `schemas/service.schema.json`
- `schemas/host.schema.json`
- `tests/unit/python/validation/`
- `tests/integration/test_render_e2e.py`
- `tests/integration/test_dns.py`
- `README.md`
