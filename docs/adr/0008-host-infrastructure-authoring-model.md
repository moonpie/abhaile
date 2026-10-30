# ADR 0008: Host Infrastructure Authoring Model

## Status

2026-10-30: Updated Accepted (bounded enrollment under active Spec 0034)
2026-06-19: Updated Accepted
2026-06-18: Accepted

## Context

Abhaile already has a clear service authoring model. Service-owned systemd units live in
`config/services/**/service.yaml` under `composition.systemd`, while plain service files live under
`composition.config`.

Host-owned infrastructure has not had the same explicit contract. Host composition can place files,
and render/apply can classify systemd destinations, but there has been no host-level
`composition.systemd` section for unit lifecycle intent.

This creates ambiguous ownership for infrastructure that belongs to the host rather than to an
application service:

- the Vault unseal helper is host infrastructure, but modeling it under `vault-agent` makes script
  updates look like service-owned config changes
- the GitOps runner is host infrastructure, but modeling it as a mapped service makes service
  mapping carry deployment mechanism details
- placing systemd units through generic config placement hides enable/start intent from the authored
  source of truth

The model must align with ADR 0003, ADR 0004, and ADR 0005 without adding imperative apply hooks or
weakening render/apply determinism.

## Decision

Host-owned infrastructure uses host composition.

### Authored Sections

- Host-owned systemd units and drop-ins belong in host `composition.systemd`.
- Host-owned plain files, scripts, and directories belong in host `composition.config`.
- Service-owned systemd units remain in service `composition.systemd`.
- Service-owned plain files remain in service `composition.config`.

Host `composition.config` must not be used to author files under `/etc/systemd/system/`.

### Lifecycle Intent

Host `composition.systemd` uses the same public lifecycle fields as service `composition.systemd`:

- `enable`
- `start`

Unit files and drop-ins may carry enable/start intent. For a drop-in, that intent applies to its
parent unit, including a vendor unit installed by a declared package. Drop-ins do not have an
independent lifecycle. Publish their inputs before parent activation or refresh.

### Host Infrastructure Boundary

Service mapping represents application or service placement intent. It must not include a service
solely to install host infrastructure units.

Host infrastructure includes units that operate the local GitOps host or host bootstrap state rather
than a single application service. Current examples are:

- `/usr/local/lib/abhaile/tools/vault-unseal.sh`
- `abhaile-vault-unseal.service`
- `abhaile-runner.service`
- `abhaile-runner.timer`

Host-owned does not imply common-host-owned. Privileged recovery units such as Vault unseal are
authored only on hosts that hold the corresponding recovery material. Common host composition is
reserved for infrastructure that should exist on every managed host.

The GitOps runner remains outside `src/abhaile/` as defined by ADR 0003. This ADR decides where the
runner unit and timer are authored, not what the runner is responsible for.

### Apply Model

Host systemd artifacts use the existing Ansible resource-family roles and renderer-internal apply
hints under ADR 0013. This ADR does not add free-form apply commands, manifest-level hooks, or new
imperative lifecycle blocks.

### Declared Host Prerequisites

[Spec 0034](../specs/active/0034-host-and-service-enrollment.md) tracks the approved extension for
additional-host and incremental enrollment; implementation evidence remains in that active spec.

Host composition owns ordinary user/group and supported package intent. Reconciliation creates
missing declared identities, memberships and packages through native facilities before dependent
directories, user managers and services. Existing incompatible UID/GID assignments fail rather
than being renumbered. Rootless prerequisites, including subordinate IDs and lingering, need
explicit deterministic intent; they must not depend on discovering arbitrary free IDs during render.

The automation identity, its access material and reserved runner units retain their protected
bootstrap/operator publication boundaries under ADR 0013. Provisioning an ordinary service user
does not grant authority to replace automation access or weaken administrative recovery.

Protected access publication requires the explicit bootstrap enrollment boundary; ordinary
reconciliation rejects changed protected files. Rootless runtime homes follow the current
`/home/<user>` render contract, with explicitly declared subordinate-ID ranges for new rootless
accounts. Lingering enablement is additive; a false declaration does not disable existing policy.

Managed file parents receive deterministic manifest directory intent after explicit directories
and private volume roots. Rootful defaults are root-owned `0755`; rootless private parents are
user-owned `0700`, with distant ancestors outside that home root-owned `0755`. Existing explicit
metadata takes precedence, conflicting inferred metadata fails, and account homes/distribution
roots remain foundations rather than inferred service ownership.

Declared host VLANs/interfaces must be ready before dependent service networks and workloads.
Use the current networkd adoption and last-successful recovery model, not the superseded network
transaction controller. Existing local storage and external network configuration remain explicit
prerequisites; host intent does not authorize formatting disks or configuring external switches.

Bootstrap establishes trust and minimum tools, then uses ordinary roles. Additional-host enrollment
assumes an existing Vault and the operator-provisioned handoff. Arbitrary command-oriented software
actions remain deferred; supporting another acquisition mechanism needs a concrete design.

## Alternatives Considered

- **Keep host systemd units in host `composition.config`**: rejected because it mixes plain file
  placement with systemd lifecycle intent and repeats the ambiguity ADR 0005 removed from service
  authoring.
- **Keep host infrastructure as pseudo-services in service mapping**: rejected because service
  mapping should describe service placement, not host bootstrap or GitOps mechanism details.
- **Add free-form apply hooks for host units**: rejected because it weakens the typed apply model in
  ADR 0004 and makes side effects harder to validate.
- **Create a separate host-infrastructure service layer**: rejected for now because host
  `composition.systemd` and `composition.config` are sufficient for the current host-owned units.

## Consequences

- Host-owned units have the same clear lifecycle authoring model as service-owned units.
- The Vault unseal helper can move out of `vault-agent` service ownership and avoid unintended
  `vault-agent.service` restart or validation coupling.
- The GitOps runner unit and timer can move out of service mapping while preserving the runner
  responsibility boundary from ADR 0003.
- Render and apply stay deterministic and use existing typed executor behavior.
- Contributors must decide whether each unit is host-owned or service-owned before authoring it.
- Existing host-authored systemd artifacts must migrate from generic config placement to host
  `composition.systemd`.

## References

- ADR 0003: GitOps Runner Responsibility Boundary
- ADR 0004: Apply Execution Model
- ADR 0005: Service Authoring Model
- SPEC-2026-023: Host Systemd Composition
- [ADR 0013: Last-Successful Ansible Reconciliation](0013-last-successful-ansible-reconciliation.md)
- [Spec 0034: Host and Service Enrollment](../specs/active/0034-host-and-service-enrollment.md)
