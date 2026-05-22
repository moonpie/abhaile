# Spec: Render Pipeline

## Metadata

```yaml
id: SPEC-2026-001
title: Render Pipeline
status: accepted
owner: moonpie
created: 2026-06-02
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0003-gitops-runner-responsibility-boundary
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The render pipeline is complete and in production use. This accepted spec is a
reference record of implemented contracts, boundaries, and design decisions.

Render transforms declarative intent from `config/` into deterministic,
host-scoped artifacts under `<output>/rendered` for single-host mode and
`<output>/<host>/rendered` for `--all` mode, plus a manifest for diff/apply.
Render is unprivileged and idempotent. Apply owns `<output>/state/` and live
host mutation.

## Requirements

- [x] Document CLI render contract and host selection semantics.
- [x] Document renderer module contracts (inputs, outputs, failure behavior).
- [x] Document artifact ownership/metadata contract used for manifest generation.
- [x] Document deterministic ordering and include-resolution behavior.
- [x] Record implementation decisions from TODO render-phase decision history.

## Constraints

- No plaintext secrets in rendered repo artifacts; runtime secret values remain host-only.
- Render must be deterministic for identical inputs (stable ordering, stable paths, stable hashing model).
- Render runs unprivileged and must not mutate apply-owned state.
- Host rendering scope is single host or all hosts; partial host lists are out of scope.
- Source-of-truth remains only under `config/`; rendered output is ephemeral.

## Design

### CLI Contract

Entrypoint and command surface: `abhaile-render` from `abhaile.cli.render:main`.

Arguments and selection semantics:

1. `--host <name>` renders exactly one mapped host.
1. `--all` renders all hosts in sorted host key order.
1. `--host` and `--all` are mutually exclusive.
1. One of `--host` or `--all` is required.
1. `--output` is optional for `--host` mode.
1. `--output` is required for `--all` mode; each host renders under `<output>/<host>/rendered`.

Validation gate before rendering includes mapping/network schema validation,
network sanity checks, host and service schema validation, service definition
existence checks, host physical-device checks, user ID/GID checks, and
post-render DNS serial validation.

Output ownership: render wipes and recreates the selected host rendered directory
tree and does not modify apply-owned state directories.

### End-to-End Render Flow

1. Load paths/config roots/schemas.
1. Validate mapping/network/hosts/services.
1. For each selected host, prepare rendered directories (`system`, `software`, `services`).
1. Render host/system artifacts.
1. Render software artifacts.
1. Render user-management artifacts.
1. Render service artifacts (service configs/systemd, quadlets, ingress, vault-agent config/templates, DNS zones).
1. Compute artifact hashes/sizes and write manifest.
1. Validate DNS serial consistency against rendered outputs.

### Module Contracts

`renderers/config.py`

- Purpose: unified rendering engine for `composition.config` and `composition.systemd` entries.
- Input contract: directory/static/template entries with absolute destination paths and optional internal contributor/apply-hint annotations.
- Output contract: materialized files/directories under host/service render trees and optional artifact metadata (`kind`, `owner_ref`, contributor, apply hints).
- Failure contract: missing destination/source/template, template errors, and missing source files raise `RenderError`.

`renderers/host.py` and `renderers/networkd.py`

- Purpose: split host rendering into non-networkd host/system artifacts and `/etc/systemd/network` artifacts, plus networkd drop-ins for `service-32` and `ipvlan-l2`.
- Input contract: host config, common host config, network model, mapped host services.
- Output contract: system files targeting `/etc/systemd/*` and networkd drop-ins derived from service IP ordering/interface mapping.
- Failure contract: ambiguous/missing drop-in dirs, missing service network entries, invalid addresses, missing `[Match] Name=` in base files, or missing VLAN mapping raise `RenderError`.

`renderers/services.py`

- Purpose: render `composition.config` and `composition.systemd` for mapped services.
- Input contract: host service list, network context, `config/services` tree with depth-first include resolution.
- Output contract: service artifacts under `rendered/services/<service>/...` with resolved placeholders and internal apply hints.
- Failure contract: missing service definitions and rendering failures raise `RenderError`.

`renderers/software.py`

- Purpose: render host software artifacts from host include chains.
- Input contract: host include graph and `composition.software` lists for packages/downloads/builds/commands.
- Output contract: deterministic `rendered/software/packages.txt` and per-entry specs under `rendered/software/downloads|builds|commands/<id>.yaml`, schema-validated.
- Failure contract: include cycles, duplicate IDs, missing specs, schema mismatch, or ID mismatch raise `RenderError`.

`renderers/users.py`

- Purpose: render host user, group, sudo, and SSH authorized-keys artifacts.
- Input contract: include-merged user-management definitions with scalar equality and list union semantics.
- Output contract: `/etc/sysusers.d/abhaile.conf`, `/etc/sudoers.d/abhaile`, per-user `authorized_keys`, and ownership/mode apply hints.
- Failure contract: include cycles, type mismatches, conflicting scalar definitions, or unknown groups raise `RenderError`.

`renderers/quadlets/*`

- Purpose: render container/pod quadlets, named volumes, image/build units, and shared network quadlets.
- Input contract: services with `podman` config and container/pod composition definitions, with named volume definitions.
- Output contract: rootful/rootless quadlet artifacts with naming conventions, shared-volume handling, and per-VLAN network quadlet deduplication.
- Failure contract: missing templates, missing podman user, invalid volume entries, illegal host-path reuse, or template-variable dependency mismatches raise `RenderError`.

`renderers/ingress.py`

- Purpose: aggregate Caddy ingress blocks into base ingress service files.
- Input contract: base ingress services discovered on current host; contributors collected from all mapped services in mapping/include order.
- Output contract: aggregated Caddyfile per base destination with deterministic contributor ordering and section markers.
- Failure contract: missing base/block files, invalid ingress definitions, or missing service definitions raise `RenderError`.

`renderers/vault_templates/*`

- Purpose: aggregate/copy vault-agent templates for current host and render base vault-agent config.
- Input contract: host-local base vault-agent service, same-host template contributors, required `templates` and `out` named volumes.
- Output contract: copied template sources, rendered base vault-agent config, and runtime output parent directories represented as directory artifacts.
- Failure contract: missing base config, missing templates, invalid template specs, or missing named volumes raise `RenderError`.

`dns/renderer.py`

- Purpose: render internal DNS zone files for current-host providers while aggregating records from all mapped services.
- Input contract: `network.dns.zones`, provider resolution via direct/include-transitive service composition, zone-file templates from provider service composition.
- Output contract: rendered zone files with `zone.zone` substitution and `coredns.zone` artifact metadata with owner dependencies.
- Failure contract: missing provider config, invalid zones, unresolved template paths, missing host providers, or template render errors raise `RenderError`.

`renderers/metadata.py` and `renderers/manifest.py`

- Purpose: classify artifacts by kind/owner and serialize deterministic manifest output.
- Input contract: collector-populated artifacts with render path, target path, ownership, and computed hash/size.
- Output contract: `rendered/manifest.json` with deterministic entries/owners and per-artifact metadata (`render_path`, `target_path`, `kind`, `owner_ref`, `sha256`, `size`, optional contributor/apply hints).
- Failure contract: missing hash/size at serialization time or manifest write failures raise `RenderError`.

### Contracts for Inputs and Outputs

Canonical render inputs are `config/mapping.yaml`, `config/network.yaml`,
`config/hosts/<host>/host.yaml`, `config/services/<service>/service.yaml`, and
static/template sources under `config/`.

Canonical render outputs per host are `rendered/system/...`,
`rendered/software/...`, `rendered/services/...`, and `rendered/manifest.json`.

Behavioral guarantees are deterministic ordering/serialization, full
rendered-tree rebuild per run, and fail-fast behavior on invalid or ambiguous
config.

## Decision Notes

- Decision: Host render selection is single-host (`--host`) or full mapping (`--all`) only.

- Rationale: Keeps reconciliation and troubleshooting deterministic.

- Impact: No partial explicit host list support in render command.

- ADR: 0001-output-root-and-environment-paths

- Decision: Service include resolution is recursive depth-first with cycle detection and include-first ordering.

- Rationale: Shared/base service composition must be reusable while preserving explicit service override order.

- Impact: All renderers consume inherited composition consistently.

- ADR: null

- Decision: Ingress aggregates from all mapped services but renders only on host-local base ingress services.

- Rationale: Reverse proxies need global service view while rendered artifacts remain host-scoped.

- Impact: Deterministic cross-host aggregation without writing ingress artifacts to non-host services.

- ADR: null

- Decision: Vault-agent template aggregation is host-local (not global) and outputs only non-secret control-plane artifacts.

- Rationale: Vault-agent runtime writes occur on local host filesystems; secret payloads remain runtime-only.

- Impact: Render includes templates/base config/output directories, but never resolved secret contents.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

- Decision: Software output uses mixed granularity (merged packages list, per-entry action specs) with duplicate ID rejection.

- Rationale: Keeps apt package behavior simple while preserving fine-grained drift/apply targeting for procedural actions.

- Impact: Reduced drift noise for packages, explicit targeting for downloads/builds/commands.

- ADR: null

- Decision: User management outputs sysusers/sudoers/authorized_keys artifacts from include-merged host definitions.

- Rationale: Declarative host identity management aligns with idempotent apply model.

- Impact: Deterministic user/group/sudo state with strict merge conflict checks.

- ADR: null

- Decision: Manifest includes artifact kind/owner/apply-hint metadata in addition to hash/size inventory.

- Rationale: Apply requires typed ownership and activation context, not only file diffs.

- Impact: Drift/apply planning can make owner-aware execution decisions.

- ADR: 0002-hash-based-drift-detection-and-state-model

## Acceptance Criteria

- [x] The accepted spec documents CLI render behavior and host selection contract.
- [x] The accepted spec documents each renderer family with input/output/failure contracts.
- [x] The accepted spec records render-phase implementation decisions and rationale.
- [x] The accepted spec captures manifest/metadata contract used by downstream diff/apply.

### Evidence

Criterion: CLI render behavior and host selection contract.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/cli/render.py](../../../src/abhaile/cli/render.py) and [src/abhaile/utils/paths.py](../../../src/abhaile/utils/paths.py).
- Validation evidence: [tests/integration/test_render_e2e.py](../../../tests/integration/test_render_e2e.py).

Criterion: Renderer family contracts.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/renderers/](../../../src/abhaile/renderers/) and [src/abhaile/dns/renderer.py](../../../src/abhaile/dns/renderer.py).
- Validation evidence: [tests/unit/python/renderers/](../../../tests/unit/python/renderers/), [tests/integration/test_composition_includes.py](../../../tests/integration/test_composition_includes.py), [tests/integration/test_dns.py](../../../tests/integration/test_dns.py), [tests/integration/test_ingress.py](../../../tests/integration/test_ingress.py), [tests/integration/test_quadlets.py](../../../tests/integration/test_quadlets.py), and [tests/integration/test_vault_templates.py](../../../tests/integration/test_vault_templates.py).

Criterion: Decision capture from completed render phase.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete), [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete), and render-phase decision records in [TODO.md](../../../TODO.md).
- Validation evidence: cross-check against [src/abhaile/cli/render.py](../../../src/abhaile/cli/render.py), [src/abhaile/renderers/](../../../src/abhaile/renderers/), and rendering decision records in [TODO.md](../../../TODO.md).

Criterion: Manifest/metadata contract.

- Implementation evidence: [commit cfa1f56 record](implementation-evidence.md#commit-cfa1f56-rewrite-render-complete) and [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/renderers/metadata.py](../../../src/abhaile/renderers/metadata.py) and [src/abhaile/renderers/manifest.py](../../../src/abhaile/renderers/manifest.py).
- Validation evidence: [tests/unit/python/renderers/test_metadata.py](../../../tests/unit/python/renderers/test_metadata.py) and [tests/unit/python/renderers/test_manifest.py](../../../tests/unit/python/renderers/test_manifest.py).

## Out of Scope

- Any new render pipeline behavior or schema changes.
- Apply pipeline implementation details beyond interfaces consumed by render metadata.
- GitOps runner orchestration (commit selection, scheduling, rollback strategy).
- Creating new implementation behavior solely to satisfy documentation evidence requirements.

## Open Questions

- None.

## References

- `docs/specs/GOVERNANCE.md`
- `docs/specs/_template.md`
- `src/abhaile/cli/render.py`
- `src/abhaile/renderers/`
- `src/abhaile/dns/renderer.py`
- `TODO.md`
- `docs/adr/0001-output-root-and-environment-paths.md`
- `docs/adr/0002-hash-based-drift-detection-and-state-model.md`
- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `docs/adr/0005-service-authoring-model.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
