# Spec: Networking Renderer

## Metadata

```yaml
id: SPEC-2026-002
title: Networking Renderer
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

The networking renderer is implemented and in active use. This accepted spec is
reference documentation for the host/service networking contracts that were
delivered.

The implementation covers two coupled concerns:

1. Rendering host-scoped `systemd-networkd` artifacts from host composition
   entries targeting `/etc/systemd/network/`.
1. Rendering per-service `systemd-networkd` drop-ins for services using
   `service-32` or `ipvlan-l2` network modes, based on `config/network.yaml`
   VLAN/address assignments.

This behavior is validated by schema checks and network sanity checks before
rendering. The result is deterministic host networking output with explicit
ownership/dependency metadata used by downstream diff/apply execution.

## Requirements

- [x] Document the `systemd-networkd` renderer contract for host config entries.
- [x] Document VLAN-aware drop-in generation for `service-32` and `ipvlan-l2` services.
- [x] Document deterministic `/32` service-address handling and output file naming.
- [x] Document host/service networking validation contracts from `src/abhaile/validation/`.
- [x] Record networking-related TODO and historical Decision Log outcomes that shaped implementation.
- [x] Reconcile historical Decision Log wording with current implemented drop-in directory scope.
- [x] Document current automated test coverage boundaries for networking drop-in error paths.

## Constraints

- Source of truth is declarative config under `config/`; no manual edits under rendered output.
- Rendering must be deterministic for identical inputs.
- Render is unprivileged and host-scoped; apply consumes metadata for ordered execution.
- Networking contracts must fail fast on ambiguous interface/VLAN mappings.
- Service `/32` addresses must remain consistent with VLAN CIDR and `ipvlanl2_range` rules.

## Design

### Inputs and Validation Gates

Primary inputs:

- `config/network.yaml` for VLANs, host interfaces, service addresses, and VLAN mapping.
- `config/hosts/<host>/host.yaml` and common host config for networkd-targeted composition entries.
- `config/services/<service>/service.yaml` for service network mode (`service-32` or `ipvlan-l2`).
- `schemas/network.schema.json` for shape/field validation of network configuration.

Validation path (executed before rendering):

1. Schema validation for `network.yaml` via `validate_schema(..., network.schema.json)`.
1. `validate_network_sanity()` enforces:
   - VLAN references exist for host interfaces and services.
   - Host and service addresses are inside declared VLAN CIDRs.
   - Service addresses are within VLAN `ipvlanl2_range` when configured.
   - No duplicate IP use across host interfaces and services.
1. `validate_host_physical_device()` ensures a host `physical_device` exists in that host's
   interface map in `network.yaml`.

These checks define the host/service networking contract used by the renderer.

### systemd-networkd Artifact Rendering

`render_networkd_config()` renders only host/common composition config entries whose
destination prefix is `/etc/systemd/network/`.

Behavior:

1. Process common host entries first.
1. Process host-specific entries second (override/additive behavior).
1. Render static files, templated files, and directory entries via shared config renderer.
1. Register owner metadata for interface-scoped artifacts (`iface:<name>`).

Interface dependency modeling implemented for owner metadata:

- Dotted interfaces depend on their base interface (for example `iface:enp0s31f6.100` requires `iface:enp0s31f6`).
- `ipvlan-l2*` interfaces depend on host physical uplink or VLAN subinterface,
  derived from host `physical_device` and interface suffix.

This owner graph is consumed by diff/apply to preserve safe ordering when
network interfaces are changed or removed.

### VLAN-Aware Drop-in Generation

`render_networkd_dropins()` generates per-service drop-ins for mapped services on a host.

Selection rules:

1. Services without `podman.network` or `systemd.network` set to `service-32` or `ipvlan-l2` are skipped.
1. Service entry must exist in `network.services` with both `vlan` and `address`.
1. Host must have exactly one drop-in directory mapped to the target VLAN.

Interface and directory mapping rules:

1. Drop-in directories are discovered from existing `*.network.d` directories in
   rendered networkd output.
1. Base file is resolved by stripping `.d` from directory name.
1. Interface identity is extracted from `[Match] Name=` in the base file, not from filename stem.
1. VLAN mapping is determined from `network.hosts.<host>.interfaces.<name>.vlan`.

Scope reconciliation note:

- A historical TODO Decision Log entry says to allow any `*.d` drop-in directory.
- Current implemented behavior is narrower and intentionally scoped to `.network.d`
  discovery (`path.name.endswith(".network.d")`).
- This accepted spec documents the implemented contract as the authoritative current
  behavior. If broader `*.d` support is desired later, it should be tracked as new
  spec work with matching code and tests.

Failure cases are explicit `RenderError` outcomes for:

- Unknown interface referenced by a drop-in directory.
- Missing VLAN on interface.
- Multiple drop-in directories for the same VLAN.
- Missing service network entry/vlan/address.
- Missing corresponding drop-in directory for service VLAN.
- Missing `[Match] Name=` in base file.

### Deterministic /32 Service Addressing Contract

Drop-in filenames are deterministic and derived from service address:

1. CIDR is stripped from service address.
1. IPv4 last octet is parsed.
1. Filename is `<last-octet-zero-padded>-<service-name>.conf`.

Examples:

- `172.20.20.200/32` -> `200-caddy.conf`
- `172.20.30.234/32` -> `234-blocky.conf`

Template choice is mode-specific:

- `service-32` -> `service-addr.conf.j2` (address drop-in)
- `ipvlan-l2` -> `service-route.conf.j2` (route drop-in)

Only IPv4 is supported for drop-in filename generation; invalid or non-IPv4
addresses fail fast.

## Decision Notes

- Decision: Resolve networkd drop-in interface identity from base-file `[Match] Name=` and support drop-in directories through that authoritative mapping path.

- Rationale: Avoid fragile filename parsing and bind drop-ins to real interface match semantics.

- Impact: Safer VLAN-to-interface mapping and explicit failure on malformed/missing base network files.

- ADR: null

- Decision: Enforce service `/32` placement within VLAN CIDR and `ipvlanl2_range` via validation before render.

- Rationale: Keep service addressing deterministic and prevent invalid host/service network contracts from entering render/apply flow.

- Impact: Invalid address plans fail early with actionable error messages instead of producing partial networkd artifacts.

- ADR: null

- Decision: Register interface owners and dependencies for networkd artifacts (`network`, `netdev`, `dropin`) in render metadata.

- Rationale: Apply ordering for interface changes/removals requires explicit dependency graph edges.

- Impact: Diff/apply can execute child-first deletes and parent-first create/update sequences safely.

- ADR: 0002-hash-based-drift-detection-and-state-model

- Decision: Treat `.network.d`-only drop-in discovery as the current authoritative contract for networking renderer behavior.

- Rationale: This matches implemented selection logic and current tests; it avoids documenting broader behavior that is not implemented.

- Impact: Documentation, implementation, and tests are aligned; historical TODO wording is treated as superseded implementation context.

- ADR: null

## Acceptance Criteria

- [x] The accepted spec documents host networkd rendering behavior and output contract.
- [x] The accepted spec documents VLAN handling and drop-in generation behavior for `service-32` and `ipvlan-l2`.
- [x] The accepted spec documents deterministic `/32` service-address naming and failure conditions.
- [x] The accepted spec documents validation contracts from `src/abhaile/validation/` and `schemas/network.schema.json`.
- [x] The accepted spec records networking-relevant TODO historical decisions as implementation context.
- [x] The accepted spec explicitly reconciles TODO historical wording against current `.network.d` implementation scope.
- [x] The accepted spec identifies current test coverage limits for drop-in error branches.

### Evidence

Criterion: Host networkd rendering behavior and output contract.

- Implementation evidence: `src/abhaile/renderers/networkd.py` and commit records in `docs/specs/accepted/implementation-evidence.md` (`cfa1f56`, `56211e3`).
- Validation evidence: `tests/unit/python/renderers/test_networkd.py`.

Criterion: VLAN handling and drop-in generation for `service-32` and `ipvlan-l2`.

- Implementation evidence: `src/abhaile/renderers/networkd.py` (`render_networkd_dropins`, `_get_dropin_dirs_by_vlan`, `_interface_from_base_file`).
- Validation evidence: `tests/unit/python/renderers/test_networkd.py` (drop-in mode selection, missing VLAN/directory cases, `[Match] Name` owner mapping).

Criterion: Deterministic `/32` service-address naming and failure behavior.

- Implementation evidence: `src/abhaile/renderers/networkd.py` (`_get_last_octet`, filename formatting, IPv4 enforcement).
- Validation evidence: `tests/unit/python/renderers/test_networkd.py` (`200-caddy.conf`, `234-blocky.conf` assertions, plus missing service/drop-in directory error paths).

Criterion: Validation contracts for host/service networking.

- Implementation evidence: `src/abhaile/validation/network.py`, `src/abhaile/validation/schema.py`, and `src/abhaile/cli/render.py` validation call path.
- Validation evidence: `tests/unit/python/validation/test_network.py`.

Criterion: Networking-related TODO and Decision Log coverage.

- Implementation evidence: `TODO.md` historical decision entry on networkd drop-in interface resolution (2026-02-02), and network/schema validation decision entries (2026-02-01).
- Validation evidence: Behavior cross-checked against `src/abhaile/renderers/networkd.py`, `src/abhaile/validation/network.py`, and `schemas/network.schema.json`.

Criterion: Reconciled directory-scope contract.

- Implementation evidence: `src/abhaile/renderers/networkd.py` `.network.d` discovery logic in `_get_dropin_dirs_by_vlan`.
- Validation evidence: `tests/unit/python/renderers/test_networkd.py` current drop-in tests all use `.network.d` fixtures.

### Testability Notes

Current automated coverage is strong for happy-path rendering plus two primary
error paths (`missing from network.yaml`, `No drop-in directory found`).

Known unasserted error branches in current unit tests:

- unknown interface referenced by discovered drop-in directory
- missing VLAN on host interface used by drop-in mapping
- multiple drop-in directories resolving to one VLAN
- base file missing for drop-in directory
- missing `[Match] Name=` in base file
- invalid IP address passed to drop-in filename derivation
- non-IPv4 address rejected by drop-in filename derivation

These are implemented fail-fast branches in `src/abhaile/renderers/networkd.py`
and should be added as dedicated unit tests when tightening regression coverage.

## Out of Scope

- Any new networking renderer behavior or schema changes.
- DNS zone rendering behavior beyond shared use of `config/network.yaml` data.
- Apply runtime executor internals beyond renderer metadata contracts.
- Network design changes to VLAN IDs, CIDRs, or host/service assignments.

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `src/abhaile/renderers/networkd.py`
- `src/abhaile/validation/network.py`
- `src/abhaile/validation/schema.py`
- `src/abhaile/cli/render.py`
- `config/network.yaml`
- `schemas/network.schema.json`
- `tests/unit/python/renderers/test_networkd.py`
- `tests/unit/python/validation/test_network.py`
- `TODO.md`
- `docs/specs/accepted/implementation-evidence.md`
