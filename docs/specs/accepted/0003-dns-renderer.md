# Spec: DNS Renderer

## Metadata

```yaml
id: SPEC-2026-003
title: DNS Renderer
status: accepted
owner: moonpie
created: 2026-06-04
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The DNS renderer is implemented and in production use. This accepted spec documents
what was built as reference material for future maintenance and audits.

Implemented behavior spans:

1. Zone file generation from `config/network.yaml` using provider-driven templates.
1. SOA serial validation based on rendered content hashing and git-aware increment rules.
1. Automatic PTR generation for reverse zones from forward records marked with `ptr: true`.
1. Split-horizon behavior where internal zones are rendered and external zones are intentionally skipped.
1. DNS data contracts enforced across schema (`schemas/network.schema.json`) and runtime validation
   (`src/abhaile/validation/dns.py`, `src/abhaile/dns/serial_validator.py`).

## Requirements

- [x] Document how internal DNS zones are generated and where rendered artifacts are written.
- [x] Document implemented SOA serial/content-hash validation and git-aware counter behavior.
- [x] Document implemented PTR record generation behavior and boundaries.
- [x] Document split-horizon internal/external handling.
- [x] Document DNS data contracts from `config/network.yaml` and `schemas/network.schema.json`.
- [x] Record DNS-related historical TODO Decision Log outcomes that shaped final behavior.

## Constraints

- `config/network.yaml` is the source of truth for DNS zones, serial metadata, and host/service records.
- Rendering is deterministic for identical config and mapping inputs.
- Only zones with `provider.type: internal` are rendered to zone artifacts.
- Validation runs in render flow and fails before successful completion when serials are out of sync.
- Serial validation uses the same template-rendering path as zone rendering to avoid hash drift.
- Reverse PTR synthesis currently supports IPv4 reverse zones; IPv6 reverse zone PTR synthesis is not implemented.

## Design

### Render Entry Points and Flow

`render_dns()` in `src/abhaile/dns/renderer.py` is called from render CLI host workflow.

1. Read `network.dns.zones`.
1. Build provider mapping for services on the current host (`build_provider_mapping`) using:
   - direct provider mode (service defines `dns.zone_files`), and
   - transitive provider mode (service includes provider via `composition.include` and has `dns.zone_files`).
1. For each zone:
   - require `zone.name` and `zone.provider.name`.
   - skip if provider type is not `internal`.
   - collect zone records from hosts and deployed services in deterministic order.
   - resolve provider `dns.zone_files` config and match zone pattern (`*` or exact zone).
   - render template and write zone file under:
     `rendered/services/<providing-service>/<destination-parent>/<zone>.zone`.
1. Register zone artifacts with owner metadata and apply hints for CoreDNS zone reload behavior.

Zones render to deployed provider services (coredns-clean, coredns-filtered) rather than the
base service (coredns-common) because base services don't appear in `mapping.yaml` and therefore
don't receive quadlets or systemd units. This mirrors the ingress aggregation pattern where
caddy-dmz/caddy-internal aggregate from all services but only render on their own host.

### Zone Generation

Zone rendering uses provider-owned templates from service composition (`dns.zone_files`) and
record data collected by `collect_zone_records()` in `src/abhaile/dns/records.py`.

Record collection contract:

1. Host DNS records are included in host definition order.
1. Service DNS records are included only for services deployed in mapping, in mapping order.
1. Original per-entity record order is preserved.
1. Record `rdata` placeholders are resolved through shared placeholder resolution.
1. Record `type` is normalized to uppercase in rendered records.

Template rendering contract (`render_zone_template`):

- Zone template path format is `service/path/to/template.j2`.
- Zone serial is required in zone configuration.
- SOA serial is rendered as `serial.date` + zero-padded two-digit `serial.counter`.
- Rendered zone files use fixed-width columns for owner, class, type, and data fields to keep
  output readable and stable.
- Rendered records are grouped by type in this order: `A`, `AAAA`, `CNAME`, `MX`, `SRV`, `TXT`,
  `PTR`.
- Within each record type group, records retain the deterministic collection order: host records
  in `config/network.yaml` host order, then deployed service records in `config/mapping.yaml`
  service order, with each host/service preserving its local record order.
- Missing template path, missing template file, template render failures, or missing serial data raise `RenderError`.

### SOA Serial Validation

`validate_dns_serials()` in `src/abhaile/validation/dns.py` runs after host rendering and calls
`validate_zone_serial_collect()` from `src/abhaile/dns/serial_validator.py`.

Validation behavior:

1. Validate only internal zones.
1. For each zone, render canonical content using the same template/record path as renderer.
1. Compute SHA-256 content hash and compare with `zone.serial.content_hash`.
1. If mismatched:
   - read `config/network.yaml` from git HEAD when available,
   - compute expected serial date/counter based on today vs HEAD serial date,
   - re-render expected content and compute expected hash,
   - report only fields that differ (`serial.date`, `serial.counter`, `serial.content_hash`).
1. Collect all zone mismatches and raise one aggregated `RenderError` message.

The serial increment rule is once per commit, not per render. The git-HEAD-based logic prevents
counter exhaustion (counters are 00–99 in `YYYYMMDDCC` format). Multiple renders from the same
commit produce the same serial; the counter only increments when the commit changes. This
prevents exhausting the 2-digit counter space during iterative development.

This implements the documented decision to prevent false drift by hashing rendered template output,
not a synthetic representation.

### PTR Record Generation

PTR generation is implemented in `src/abhaile/dns/records.py`.

Behavior:

1. Forward records with `ptr: true` and type `A` are eligible for PTR synthesis.
1. When rendering a reverse zone (`*.in-addr.arpa.`), renderer scans host and deployed-service
   forward records and selects A records whose IP belongs to that reverse zone.
1. PTR name is derived from remaining octets relative to zone depth.
1. PTR `rdata` is emitted as FQDN with trailing dot: `<record-name>.<forward-zone>.`.
1. PTR TTL defaults to `3600` unless source record provides `ttl`.
1. IPv6 reverse zones (`*.ip6.arpa.`) currently raise `RenderError` for PTR generation.

### Split-Horizon Internal and External Behavior

Split-horizon behavior is implemented through zone provider typing:

- Internal zones (`provider.type: internal`) are rendered into CoreDNS zone files for provider services.
- External zones (`provider.type: external`) are not rendered by DNS renderer and are skipped.

This allows internal authoritative zones and external DNS provider declarations to coexist in
`config/network.yaml` while only internal zones produce rendered artifacts.

### DNS Data Contracts

Implemented DNS contracts are defined across `config/network.yaml` and
`schemas/network.schema.json`.

Zone-level contract:

- `dns.zones[]` entries require:
  - `name` ending with `.`
  - optional `provider` with:
    - `type` in `internal|external`
    - optional `name`
  - optional `serial` with:
    - `date` as `YYYYMMDD` string or integer
    - `counter` as two-digit string or integer
    - `content_hash` string
  - optional inline `records[]` with record type/name/rdata/ptr fields

Current consumption note:

- `dns.zones[].records[]` is schema-defined but is not currently consumed by the DNS renderer record
  aggregation path. Rendered records are collected from `hosts.<host>.dns[]` and
  `services.<service>.dns[]` definitions.

Host/service DNS record contract:

- `hosts.<host>.dns[].records[]` and `services.<service>.dns[].records[]` support:
  - `type` in `a|aaaa|cname|ptr|txt|mx|srv`
  - `name` string
  - optional `rdata` string (supports placeholder syntax)
  - optional `ptr` boolean

Runtime contract additions enforced by renderer/validator:

- All zones currently require `provider.name` during render-time validation. External zones are
  then skipped for artifact generation after provider validation.
- Provider service must resolve `dns.zone_files` as a list of objects.
- At least one zone-files entry must match a zone by exact match or `*`.
- Zone serial is required for template rendering and serial validation.

## Decision Notes

- Decision: Keep DNS serial validation hash generation on the same template rendering path as DNS render output.

- Rationale: Eliminates false-positive serial drift caused by mismatched canonicalization.

- Impact: `serial.content_hash` now tracks real rendered zone content and validation output is actionable.

- ADR: null

- Decision: Require `config_root` for DNS serial validation path.

- Rationale: Validation depends on provider templates and composition resolution.

- Impact: Removed legacy fallback behavior and aligned tests/CLI around required config-root input.

- ADR: null

- Decision: Auto-generate IPv4 PTR records from forward A records marked with `ptr: true`.

- Rationale: Keeps reverse DNS synchronized with forward records from one source of truth.

- Impact: Reverse zones are populated automatically for matching IP ranges; IPv6 reverse synthesis remains unsupported.

- ADR: null

- Decision: Render only internal zones while preserving external zones in config model.

- Rationale: Supports split-horizon intent without generating artifacts for external providers.

- Impact: External provider declarations remain declarative metadata for non-rendered DNS paths.

- ADR: null

## Acceptance Criteria

- [x] Reference spec documents implemented zone generation behavior.
- [x] Reference spec documents implemented SOA serial and content-hash validation behavior.
- [x] Reference spec documents implemented PTR synthesis behavior.
- [x] Reference spec documents split-horizon internal/external behavior.
- [x] Reference spec documents DNS data contracts in schema and runtime.
- [x] Reference spec includes DNS-related TODO Decision Log context.

### Evidence

Criterion: Zone generation behavior.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (summary in [implementation-evidence.md](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete)), modules
  [src/abhaile/dns/renderer.py](../../../src/abhaile/dns/renderer.py), [src/abhaile/dns/records.py](../../../src/abhaile/dns/records.py), [src/abhaile/cli/render.py](../../../src/abhaile/cli/render.py).
- Validation evidence: [tests/unit/python/renderers/test_dns_render.py](../../../tests/unit/python/renderers/test_dns_render.py),
  [tests/unit/python/renderers/test_dns_template.py](../../../tests/unit/python/renderers/test_dns_template.py), [tests/integration/test_dns.py](../../../tests/integration/test_dns.py).

Criterion: SOA serial and content-hash validation behavior.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (summary in [implementation-evidence.md](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete)), modules
  [src/abhaile/validation/dns.py](../../../src/abhaile/validation/dns.py), [src/abhaile/dns/serial_validator.py](../../../src/abhaile/dns/serial_validator.py).
- Validation evidence: [tests/unit/python/renderers/test_dns_serial.py](../../../tests/unit/python/renderers/test_dns_serial.py),
  [tests/unit/python/renderers/test_dns_hash.py](../../../tests/unit/python/renderers/test_dns_hash.py), [tests/integration/test_dns.py](../../../tests/integration/test_dns.py).

Criterion: PTR synthesis behavior.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (summary in [implementation-evidence.md](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete)), module
  [src/abhaile/dns/records.py](../../../src/abhaile/dns/records.py).
- Validation evidence: [tests/unit/python/renderers/test_dns_records.py](../../../tests/unit/python/renderers/test_dns_records.py),
  [tests/integration/test_dns.py](../../../tests/integration/test_dns.py).

Criterion: Split-horizon behavior.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` (summary in [implementation-evidence.md](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete)), module
  [src/abhaile/dns/renderer.py](../../../src/abhaile/dns/renderer.py) (`provider.type` gate for render path).
- Validation evidence: [tests/unit/python/renderers/test_dns_render.py](../../../tests/unit/python/renderers/test_dns_render.py),
  [tests/integration/test_dns.py](../../../tests/integration/test_dns.py).

Criterion: Data contract coverage.

- Implementation evidence: commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78` (summary in [implementation-evidence.md](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete)), files
  [config/network.yaml](../../../config/network.yaml), [schemas/network.schema.json](../../../schemas/network.schema.json), [src/abhaile/dns/renderer.py](../../../src/abhaile/dns/renderer.py),
  [src/abhaile/validation/dns.py](../../../src/abhaile/validation/dns.py).
- Validation evidence: schema validation path in [src/abhaile/validation/schema.py](../../../src/abhaile/validation/schema.py) and DNS validation path in
  [src/abhaile/validation/dns.py](../../../src/abhaile/validation/dns.py).

Criterion: DNS Decision Log context.

- Implementation evidence: commit `cfa1f564c3ef3d566c5c990121b327f85a202f51` and commit `56211e3579c072f9a15f77b4d94f2e4b3bfcdb78` (summaries in [implementation-evidence.md](implementation-evidence.md)), aligned with DNS decision entries dated
  2026-02-08 and 2026-03-09 in [TODO.md](../../../TODO.md).
- Validation evidence: Behaviors described by those entries match current modules listed above and are covered in [tests/integration/test_dns.py](../../../tests/integration/test_dns.py).

## Out of Scope

- Introducing new DNS providers or changing provider wiring contracts.
- Implementing IPv6 PTR synthesis for `ip6.arpa` zones.
- Changing zone template format or CoreDNS plugin behavior.
- Changing DNS ownership/apply executor behavior beyond existing artifact metadata.

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `docs/specs/accepted/0001-render-pipeline.md`
- `docs/specs/accepted/implementation-evidence.md`
- `config/network.yaml`
- `schemas/network.schema.json`
- `src/abhaile/dns/renderer.py`
- `src/abhaile/dns/records.py`
- `src/abhaile/dns/serial_validator.py`
- `src/abhaile/validation/dns.py`
- `src/abhaile/validation/schema.py`
- `src/abhaile/cli/render.py`
- `tests/unit/python/renderers/test_dns_render.py`
- `tests/unit/python/renderers/test_dns_template.py`
- `tests/unit/python/renderers/test_dns_serial.py`
- `tests/unit/python/renderers/test_dns_hash.py`
- `tests/unit/python/renderers/test_dns_records.py`
- `tests/integration/test_dns.py`
- `TODO.md`
