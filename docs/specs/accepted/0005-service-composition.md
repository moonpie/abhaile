# Spec: Service Composition

## Metadata

```yaml
id: SPEC-2026-005
title: Service Composition
status: accepted
owner: moonpie
created: 2026-06-04
updated: 2026-06-05
related_adrs:
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

Service composition is fully implemented and used by the render pipeline.
This accepted spec is reference documentation for how declarative service intent
in `config/services/*/service.yaml` is translated into deterministic rendered
artifacts under `out/rendered/.../services/`.

The implemented model combines:

- include-driven composition inheritance (`composition.include`),
- config and systemd entry rendering,
- ingress block aggregation into host-local base Caddy services,
- host-local vault-agent template aggregation and base config rendering,
- quadlet pod/container resolution and rendering.

The spec records those contracts and reconciles historical TODO Decision Log
entries with current implementation behavior.

## Requirements

- [x] Document include mechanism semantics and traversal order.
- [x] Document service config/systemd aggregation and rendering behavior.
- [x] Document ingress aggregation contracts and host/all-service scope boundaries.
- [x] Document vault-agent template aggregation contracts and secrets boundary.
- [x] Document pod/container resolution behavior tied to service composition.
- [x] Document schema constraints that define valid service composition intent.
- [x] Record related TODO and Historical Decision Log entries as implementation context.

## Constraints

- Service intent source of truth is `config/services/*/service.yaml` validated by `schemas/service.schema.json`.
- Rendering is deterministic and idempotent for identical inputs.
- Include cycles must fail fast with explicit errors.
- Render outputs are host-scoped; no manual edits under rendered output are part of this model.
- Vault secret payloads remain runtime-only and are not rendered into repo-managed artifacts.

## Design

### Include Mechanism (Authoritative Contract)

Implementation utilities in `src/abhaile/utils/composition.py` define include behavior:

1. `walk_service_includes()` performs depth-first traversal.
1. Included services are returned before the including service.
1. Shared `visited` deduplicates transitive includes across traversal roots.
1. `stack` tracking provides explicit cycle errors (`Service include cycle detected: ...`).
1. Missing included service definitions fail with `RenderError`.

Mapping-wide aggregation paths use `walk_mapping_includes()` to preserve mapping order
while expanding each service include graph depth-first with dedupe.

### Service Config and Systemd Aggregation

`src/abhaile/renderers/services.py` implements service-level composition rendering:

1. For each mapped service, collect `composition.config` and `composition.systemd`
   from the full include chain using `_collect_service_composition_entries()`.
1. Include-first ordering allows local service entries to override inherited artifacts
   by destination/path precedence in later processing.
1. Contributor markers (`_abhaile_contributor_ref`) are attached to inherited entries
   for artifact metadata traceability.
1. Template variables are placeholder-resolved from network context before render.
1. Internal apply hints are attached for restart/activation and directory ownership behavior.
1. Final rendering is delegated to `render_config_entries()` in
   `src/abhaile/renderers/config.py`, which handles static files, templates, and
   directory entries with artifact classification.

Implemented examples from service intent:

- `config/services/coredns-filtered/service.yaml` includes `coredns-common` and
  `coredns-omada`, then adds/overrides `composition.config` for `Corefile`.
- `config/services/coredns-clean/service.yaml` uses the same include mechanism with
  different direct variables, demonstrating include + local override behavior.
- `config/services/coredns-omada/service.yaml` contributes inherited `systemd` and
  `vault_agent.templates` entries consumed by including services.

### Ingress Aggregation

`src/abhaile/renderers/ingress.py` implements ingress composition semantics:

1. Base ingress services are discovered on the current host only via
   `composition.ingress.<zone>.base`.
1. Ingress block contributors are collected from all mapped services (cross-host),
   in mapping order with include expansion (`walk_mapping_includes`).
1. Paths may be service-prefixed and are normalized via
   `normalize_service_prefixed_path`.
1. Aggregation appends deterministic section markers:
   `# ========== Aggregated Ingress Blocks ==========` and per-service headers.
1. Output is written only to the host-local base ingress services.

Implemented examples:

- `config/services/caddy-dmz/service.yaml` defines DMZ base output.
- `config/services/caddy-internal/service.yaml` defines internal base output.
- `config/services/omada-controller/service.yaml` and
  `config/services/authelia/service.yaml` contribute ingress blocks.

### Vault-Agent Template Aggregation

`src/abhaile/renderers/vault_templates/` implements host-local vault-agent composition:

1. Discover host-local base vault-agent service via `vault_agent.base`.
1. Collect `vault_agent.templates` from services on the same host only, following
   include graphs depth-first with dedupe.
1. Validate each template spec (`source`, `out`, `perms`) and resolve service-prefixed paths.
1. Copy templates into the base service templates host root (from named volume mapping).
1. Build template metadata for rendered base config (`source`, `dest`, `perms`) using
   container mount roots.
1. Render base config template with resolved placeholder variables and template list.
1. Ensure runtime output parent directories are represented as rendered directory artifacts
   with ownership/mode apply hints.

Secrets boundary:

- Rendered artifacts include control-plane config, template sources, and output parent
  directories only.
- Secret values resolved by vault-agent at runtime are not rendered into repo-managed output.

Implemented examples:

- `config/services/vault-agent/service.yaml` defines base config and named volume roots.
- `config/services/coredns-omada/service.yaml`, `config/services/caddy-dmz/service.yaml`,
  and `config/services/authelia/service.yaml` define template contributors.

### Quadlet Composition Resolution

Quadlet rendering in `src/abhaile/renderers/quadlets/` consumes service composition:

1. `render_service_quadlets()` resolves `composition.pod` and `composition.container`
   using include-aware helpers (`_resolve_pod_definition`, `_resolve_container_definition`).
1. Pod services render pod and per-container units with volume/build/image wiring.
1. Container services render single container units plus optional image/build units.
1. `ipvlan-l2` services accumulate VLANs for shared network quadlet rendering.
1. Rootful/rootless output roots and apply hints are inferred from `podman.user`.

Template foundations under `config/_templates/services/quadlets/` provide shared
quadlet template primitives (`network.network.j2`, `volume.volume.j2`) used by the
quadlet renderer family.

### Schema Contract for Service Intent

`schemas/service.schema.json` defines composition shape and constraints:

- `composition.include` is an array of service names.
- `composition.config` and `composition.systemd` are typed entry arrays.
- `composition.vault_agent` supports `base` and `templates` with required fields.
- `composition.ingress` supports zone-domain structures from common schema.
- `composition.pod` and `composition.container` are mutually allowed according to podman mode.
- Podman conditional schema enforces network-mode constraints for rootful vs rootless services.

### Failure Modes and Testability Contracts

The implemented service composition model is fail-fast and explicitly tested for
common configuration and resolution errors:

- Include traversal fails on cycles and missing services (render aborts with `RenderError`).
- Service config rendering fails on missing source/template paths, template errors,
  or invalid entry shape (`destination`/`source` contract violations).
- Ingress rendering fails on missing base Caddyfile definitions, missing block files,
  and missing service definitions in include/mapping traversal.
- Vault-agent rendering fails on invalid template entries (missing `source`/`out`/`perms`),
  missing base template definitions, missing template source files, or missing
  required `templates`/`out` named volumes on base service.
- Quadlet rendering fails on unresolved podman prerequisites (missing podman user,
  missing quadlets directory/templates, invalid container/pod definitions,
  and include resolution failures).

These failures are covered by unit and integration tests listed in the Evidence
section and are part of the accepted behavior contract.

## Decision Notes

- Decision: All composition-aware renderers recursively follow `composition.include` with depth-first include-first ordering, cycle detection, and dedupe.

- Rationale: Keep inheritance semantics consistent across config, ingress, vault-agent, and quadlet resolution.

- Impact: Shared/base services can contribute reusable composition fragments without duplicate render output.

- ADR: null

- Decision: Ingress aggregates contributor blocks from all mapped services but renders only to host-local base ingress services.

- Rationale: Base reverse proxies need global service view while output remains host-scoped.

- Impact: Deterministic cross-host contributor aggregation without non-local base output writes.

- ADR: null

- Decision: Vault-agent template aggregation is host-local and emits only non-secret control-plane artifacts.

- Rationale: Vault-agent writes runtime outputs on-host and secrets must not appear in repo-managed render output.

- Impact: Base config/template assets are rendered; resolved secret payloads remain runtime-only.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

- Decision: Service config/systemd rendering annotates artifacts with contributor and apply-hint metadata.

- Rationale: Apply planning needs owner-aware activation/restart/ownership context beyond file bytes.

- Impact: Manifest metadata supports ordered and targeted apply behavior.

- ADR: 0002-hash-based-drift-detection-and-state-model

- Decision: `config/_templates/services/quadlets/*` remains shared template infrastructure for service quadlet outputs.

- Rationale: Centralized reusable quadlet template primitives reduce duplication.

- Impact: Service composition can focus on intent while renderer/template contracts handle concrete unit syntax.

- ADR: null

Historical alignment source:

- TODO Historical Decision Log entries dated 2026-02-04 and 2026-02-07 for
  service include ordering and cross-renderer include support are reflected in
  current implementation and tests.

## Acceptance Criteria

- [x] Include traversal semantics are documented with depth-first/include-first order, dedupe, and cycle behavior.
- [x] Service config/systemd composition translation to rendered service artifacts is documented.
- [x] Ingress base/contributor aggregation behavior and host/all-service boundaries are documented.
- [x] Vault-agent base/template aggregation and runtime-secrets boundary are documented.
- [x] Quadlet pod/container composition resolution from includes is documented.
- [x] Service schema constraints for composition are documented.
- [x] Related TODO and Historical Decision Log entries are captured as accepted implementation context.

### Evidence

Criterion: Include traversal semantics.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete), with implementation scope recorded in `docs/specs/accepted/implementation-evidence.md` and code in `src/abhaile/utils/composition.py`, `src/abhaile/renderers/services.py`, `src/abhaile/renderers/ingress.py`, `src/abhaile/renderers/vault_templates/discovery.py`.
- Validation evidence: `tests/integration/test_composition_includes.py`, `tests/unit/python/renderers/test_services_includes.py`.

Criterion: Service config/systemd translation.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete), plus subsequent renderer updates in commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78` (`56211e3`, Rewrite: Apply & Secrets Complete) for render metadata paths.
- Validation evidence: `tests/unit/python/renderers/test_services_render.py`, `tests/unit/python/renderers/test_services_ordering.py`, `tests/unit/python/renderers/test_services_context.py`, `tests/unit/python/renderers/test_config_errors.py`.

Criterion: Ingress aggregation boundaries.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete), with ingress implementation in `src/abhaile/renderers/ingress.py` and service intent in `config/services/caddy-dmz/service.yaml`, `config/services/caddy-internal/service.yaml`, `config/services/omada-controller/service.yaml`, `config/services/authelia/service.yaml`.
- Validation evidence: `tests/unit/python/renderers/test_ingress.py`, `tests/integration/test_ingress.py`.

Criterion: Vault-agent aggregation and secrets boundary.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete), with vault-template implementation in `src/abhaile/renderers/vault_templates/rendering.py`, `src/abhaile/renderers/vault_templates/discovery.py`, `src/abhaile/renderers/vault_templates/copying.py`, and base service intent in `config/services/vault-agent/service.yaml`.
- Validation evidence: `tests/unit/python/renderers/test_vault_templates_base.py`, `tests/unit/python/renderers/test_vault_templates_templates.py`, `tests/unit/python/renderers/test_vault_templates_errors.py`, `tests/unit/python/renderers/test_vault_templates_error_paths.py`, `tests/integration/test_vault_templates.py`.

Criterion: Quadlet include-aware pod/container resolution.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete), plus follow-on render/metadata updates in commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78` (`56211e3`), with code in `src/abhaile/renderers/quadlets/renderer.py`, `src/abhaile/renderers/quadlets/pod.py`, `src/abhaile/renderers/quadlets/container.py` and templates in `config/_templates/services/quadlets/network.network.j2`, `config/_templates/services/quadlets/volume.volume.j2`.
- Validation evidence: `tests/unit/python/renderers/test_quadlets_container.py`, `tests/unit/python/renderers/test_quadlets_pod.py`, `tests/unit/python/renderers/test_quadlets_validation.py`, `tests/unit/python/renderers/test_quadlets_error_paths.py`, `tests/integration/test_quadlets.py`, `tests/integration/test_composition_includes.py`.

Criterion: Schema contract coverage.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete), with schema contract in `schemas/service.schema.json` and schema validation wiring in render pipeline code.
- Validation evidence: `tests/unit/python/validation/test_schema.py`, `tests/integration/test_render_e2e.py`.

Criterion: TODO/Decision Log alignment.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (`cfa1f56`, Rewrite: Render Complete) plus `TODO.md` entries for 2026-02-04 (service config include ordering) and 2026-02-07 (cross-renderer include support, ingress, vault-agent).
- Validation evidence: `tests/integration/test_composition_includes.py`, cross-check against `src/abhaile/renderers/services.py`, `src/abhaile/renderers/ingress.py`, `src/abhaile/renderers/vault_templates/rendering.py`, and `src/abhaile/renderers/quadlets/renderer.py`.

## Out of Scope

- Any new composition behavior changes or schema expansions.
- Changing include merge strategy semantics beyond documented implementation.
- Refactoring renderer internals solely for documentation alignment.
- Apply execution internals beyond metadata/output contracts produced by render.

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `src/abhaile/renderers/services.py`
- `src/abhaile/renderers/config.py`
- `src/abhaile/renderers/ingress.py`
- `src/abhaile/renderers/quadlets/`
- `src/abhaile/renderers/vault_templates/`
- `src/abhaile/utils/composition.py`
- `schemas/service.schema.json`
- `config/services/*/service.yaml`
- `config/_templates/services/quadlets/network.network.j2`
- `config/_templates/services/quadlets/volume.volume.j2`
- `TODO.md`
