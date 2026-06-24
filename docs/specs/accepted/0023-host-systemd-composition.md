# Spec: Host Systemd Composition

## Metadata

```yaml
id: SPEC-2026-023
title: Host Systemd Composition
status: accepted
owner: moonpie
created: 2026-06-08
updated: 2026-06-23
related_adrs:
  - 0003-gitops-runner-responsibility-boundary
  - 0004-apply-execution-model
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0007-sops-bootstrap-policy-and-layout
  - 0008-host-infrastructure-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [vault-agent, abhaile-runner]
```

## Status

Accepted.

## Context

Abhaile currently has a service composition model for service-owned systemd units, but host-owned
systemd units do not have an equivalent authoring surface. Host configuration can place files, and
the apply pipeline can classify systemd destinations, but there is no host-level
`composition.systemd` contract with the same `enable` and `start` semantics used by services.

This gap has made host infrastructure awkward to model. The Vault unseal helper is host
infrastructure, but placing the script or unit under `vault-agent` service composition makes the
artifact service-owned. That causes apply-order and restart coupling problems: service config can
request validation or restart of `vault-agent.service` before the corresponding quadlet owner has
applied the unit on first deployment.

The GitOps runner has a similar ownership issue. ADR 0003 defines its responsibility boundary, but
the runner itself is host infrastructure rather than an application service. Keeping it in
`config/services/` makes the service mapping carry deployment mechanism details instead of only
host service intent.

## Goals

- Add a host-level `composition.systemd` authoring contract for host-owned units and drop-ins.
- Reuse service `composition.systemd` behavior where the semantics are already correct.
- Move Vault unseal systemd ownership out of `vault-agent` service composition.
- Move GitOps runner systemd ownership out of service mapping.
- Keep rendered artifacts deterministic and apply-owned state unchanged.
- Produce a durable ADR for the host infrastructure authoring model.

## Non-Goals

- Do not change the service composition systemd contract except for shared helper extraction needed
  to avoid duplication.
- Do not add per-entry restart policies or arbitrary apply hooks.
- Do not change the GitOps runner execution logic or scheduling behavior beyond moving unit
  ownership.
- Do not automate Vault CLI version updates.
- Do not introduce a new dependency or external render-time lookup.
- Do not perform a live apply as part of this work.

## Requirements

### Host Composition Schema

`host.schema.json` must support `composition.systemd` entries with the same public fields and
meaning as service `composition.systemd` entries:

- `source`
- `destination`
- `enable`
- `start`

Host systemd destinations must be under `/etc/systemd/system/`. Unit files and drop-ins must be
supported. The schema and validation should make `composition.systemd` the intended home for
host-owned systemd artifacts.

Host `composition.config` must not place files under `/etc/systemd/system/`. Existing generic
config placement remains valid for non-systemd files.

### Render Behavior

The host renderer must render host systemd entries from common and host-specific host composition.
Ordering must remain deterministic:

1. common host entries
1. host-specific entries
1. entry order as authored inside each file

Systemd entries must support static file placement and Jinja2 templates. The template context must
include the current host name, network data, and the list of services mapped to the host so host
infrastructure units can express local ordering decisions without hard-coded host names.

Rendered host systemd artifacts must use the same apply metadata shape as service systemd artifacts,
including enable and activation hints. Unit files must be enableable/startable when requested.
Drop-ins must be applied as systemd artifacts but must not receive independent enable or start
behavior. Applying host systemd artifacts must not require a new executor type if the existing
systemd executor already represents the operation.

### Vault Unseal Ownership

The Vault unseal helper script must be hosted by Vault-host composition, not by `vault-agent`
service composition. The script must not carry `restart_unit` behavior and must not restart or
validate `vault-agent.service` when the script changes.

`abhaile-vault-unseal.service` must be authored through host `composition.systemd`. The unit must:

- run after `network-online.target`
- run after `vault.service` on hosts where the `vault` service is mapped locally
- render only on hosts authorized to perform Vault unseal recovery
- fail visibly if the sealed recovery artifact is missing on an authorized Vault host
- use the root-owned SOPS age key and sealed recovery artifact locations defined by the secrets
  contract
- be enabled and startable through normal systemd apply hints
- avoid exposing unseal keys in unit files, rendered artifacts, logs, environment variables, or
  process command arguments

The unit must be omitted from hosts that only consume Vault after it is unsealed. Rootless
`vault-agent.service` must not depend on the system unseal unit; Vault Agent should start after
network readiness and recover through its own retry/restart behavior.

### GitOps Runner Ownership

The GitOps runner unit and timer must be moved to host `composition.systemd`:

- the unit and timer must be authored in common host composition and rendered for every managed host
- `abhaile-runner.service` and `abhaile-runner.timer` must be rendered as host-owned artifacts
- the timer must remain enabled and started
- the service must keep its current execution behavior
- `abhaile-runner` must no longer be required in `config/mapping.yaml`
- documentation and inventory output must not present the runner as an application service

Future host-specific opt-out behavior is out of scope for this spec.

### ADR

ADR 0008 records the host infrastructure authoring model and is linked from the ADR index. It
covers:

- when a unit belongs in host `composition.systemd`
- when a unit belongs in service `composition.systemd`
- how host scripts and host units should be paired
- why service mapping should not carry host infrastructure solely to install units
- the relationship to ADR 0003, ADR 0004, and ADR 0005

### Documentation

Documentation must describe the new host systemd authoring contract and update operational
references that currently imply service-owned or host-name-specific Vault unseal behavior.

At minimum, update:

- bootstrap documentation where it describes Vault unseal prerequisites or host unit placement
- secrets documentation where it describes sealed recovery artifacts and optional unseal keys
- any inventory or mapping documentation affected by moving the runner out of service mapping

Documentation must stay generic. It may list prerequisites such as Vault availability, SOPS access,
and host SSH access, but it must not make one host the default procedure.

## Design

### Authoring Model

Host composition keeps the same top-level shape as service composition:

```yaml
composition:
  config:
    - source: phobos/tools/vault-unseal.sh
      destination: /usr/local/lib/abhaile/tools/vault-unseal.sh
  systemd:
    - source: phobos/systemd/abhaile-vault-unseal.service.j2
      destination: /etc/systemd/system/abhaile-vault-unseal.service
      enable: true
      start: true
```

Host `composition.config` owns plain host files. Host `composition.systemd` owns units and drop-ins.
This matches the service composition split and avoids hiding systemd lifecycle intent inside a
generic file placement list.

### Render Context

The host renderer should receive mapped services for the target host. Templates may use that context
for host-owned infrastructure decisions. Vault unseal is intentionally authored only on Vault hosts
that have the root recovery age identity and sealed recovery artifact.

### Apply Semantics

Host systemd artifacts should be classified as systemd artifacts during render and applied by the
existing systemd apply path. The implementation should prefer extracting shared render helpers from
the service renderer rather than adding a parallel host-only implementation.

The apply pipeline must preserve dry-run behavior and must not write `out/state/` except through the
normal apply process.

## Acceptance Criteria

- [x] `host.schema.json` accepts host `composition.systemd` entries with `source`, `destination`,
  `enable`, and `start`.
- [x] Host systemd entries render from both common and host-specific host composition.
- [x] Host systemd entries render static files and Jinja2 templates with deterministic output.
- [x] Host systemd templates receive `host_name`, network data, and mapped `host_services`.
- [x] Rendered host systemd artifacts carry systemd apply hints for enable and start behavior.
- [x] Host systemd drop-ins do not receive independent enable or start behavior.
- [x] Host `composition.config` rejects `/etc/systemd/system/` destinations.
- [x] Vault unseal script is placed by Vault-host `composition.config`.
- [x] Vault unseal script changes do not request `vault-agent.service` restart or validation.
- [x] Vault unseal handling does not expose unseal keys in unit files, rendered artifacts, logs,
  environment variables, or process command arguments.
- [x] `abhaile-vault-unseal.service` is placed by host `composition.systemd`.
- [x] `abhaile-vault-unseal.service` renders only on hosts authorized to perform Vault unseal
  recovery.
- [x] `abhaile-vault-unseal.service` orders after `vault.service` and `network-online.target` on
  the Vault host.
- [x] Rootless `vault-agent.service` does not depend on `abhaile-vault-unseal.service`.
- [x] GitOps runner unit and timer are authored in common host composition and render for every
  managed host.
- [x] GitOps runner unit and timer are moved to host `composition.systemd`.
- [x] `abhaile-runner` is removed from service mapping and is not listed as an
  application service in generated or maintained documentation.
- [x] A host infrastructure authoring ADR is added and the ADR index is updated.
- [x] Bootstrap, secrets, and inventory documentation are aligned with the new host ownership model.
- [x] Unit tests cover schema validation, host systemd rendering, template context, and apply
  metadata.
- [x] Render integration tests cover phobos and deimos output for the migrated units.
- [x] `make lint` and `make test-fast` pass.

## Completion Evidence

- Implementation evidence: current change set; final commit or PR reference to be added when the
  branch is published.
- Validation evidence: `make lint` passed on 2026-06-20.
- Validation evidence: `make test-fast` passed on 2026-06-20.
- Validation evidence: `pytest --no-cov tests/integration/test_render_apply_e2e.py -q` passed on
  2026-06-20.

## Risks

- Moving the runner out of service mapping may affect assumptions in inventory generation or
  bootstrap docs.
- Adding mapped services to host render context can blur the boundary between host and service
  rendering if used for service-specific config. The intended use is host-owned infrastructure
  decisions only.
- Rejecting systemd destinations in host `composition.config` requires any existing host-authored
  units to migrate to host `composition.systemd` in the same implementation.
