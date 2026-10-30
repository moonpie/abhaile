# ADR 0005: Service Authoring Model

## Status

2026-10-29: Updated Accepted (container image authoring; replaces the uncommitted Podman image-pair decision)
2026-10-29: Updated Accepted (private volume directory management; delivery tracked by active spec 0033)
2026-06-26: Updated Accepted
2026-05-04: Updated Accepted
2026-05-03: Updated Accepted
2026-04-21: Accepted

## Context

Service definitions in `config/services/**/service.yaml` need a stable authored contract so contributors know where to declare files, units, lifecycle intent, and restart behavior. Earlier iterations blurred plain config placement with systemd lifecycle semantics.

## Decision

Service configuration uses section-based semantics.

### Authored Sections

- `composition.systemd` is the only authored home for service-owned systemd units
- `composition.config` is for plain config/env files and directories only
- `composition.vault_agent` defines Vault Agent control-plane inputs
- pod/container sections define runtime composition

### Runtime Context and Container Images

Delivery of this extension is tracked by
[spec 0032](../specs/accepted/0032-container-image-authoring.md), including schema, shared
validation, image resolution and migration evidence.

- `podman` contains only the required runtime fields `user` and `network`. Registry image and
  pull-policy fields are not authored there.
- `user` and `network` are local runtime declarations and are never inherited. Each mapped
  Podman service must declare both locally, preserving explicit privilege and network intent.
- Registry images and policies belong to `composition.container` for standalone containers and
  `composition.pod.containers[].container` for pod members. Both use the same container schema;
  pod-member wrapper-level image fields are also rejected.
- Every declared pod has at least one member; each member requires `name` and a nested
  `container` object. A structurally valid empty container object still needs its runtime
  image/build source to resolve before it can run.
- Shared container definitions use existing composition inheritance and need no `podman` section.
  Mapping determines deployment; each deployed Podman service supplies its local runtime context.
- There is no service-level registry image fallback. Container `pull_policy` remains optional
  with an effective default of `missing`. Existing container selection and local-build behavior
  remain unchanged, including the distinct managed-build policy.
- Per-file schemas enforce authored locations and field values. Shared project validation checks
  mapped services and included definitions before rendering and is also invoked by pre-commit.

This approved design replaces the uncommitted image-pair proposal of 2026-10-28. Revised
implementation and validation are tracked under active spec 0032; earlier test results are
retained as historical evidence rather than completion evidence for the revised design.

### Private Volume Directories

The approved extension is tracked by
[spec 0033](../specs/active/0033-private-volume-directory-management.md); implementation evidence and
the pending operator-run host checks are tracked there.

- Every non-shared bind-backed named volume supplies managed intent for its exact host directory.
  Remove `manage_host_ownership`; directory creation and metadata registration must not be
  suppressed by an incidental render-tree directory.
- Manage only the declared directory's owner, group and mode. Preserve application-owned
  descendants without recursive metadata changes, recreation or deletion.
- Adopt the inspected rootful directory metadata explicitly and preserve existing deterministic
  rootless defaults. Read-only private mounts need host-directory provisioning too.
- Preserve `shared: true` semantics: shared volume declarations do not claim host-directory
  ownership. Shared writable storage requires an agreed owner outside this private-root mechanism.
- Reuse coherent duplicate directory declarations and preserve provenance; reject conflicting
  identities or metadata rather than choosing by renderer order.
- Validate using disposable filesystem fixtures and operator-recorded host check-mode evidence
  from the normal runner or an optional manual check.
  An empty physical host is not required; a complete first-install deployment remains unverified
  unless separately performed.

This contract covers named-volume roots. Provisioning arbitrary file-only config parents remains
a separate decision; no generic parent-creation policy is introduced here.

### Lifecycle Intent

- `composition.systemd` entries may declare `enable` and `start` booleans
- apply enforces boot persistence with `systemctl enable/disable`
- helper units that are path-triggered are not independently enabled unless explicitly intended
- services that need Vault Agent output copied into bind-mounted runtime paths
  should model the copy as a service-owned oneshot prerequisite, with any path
  unit reusing that same oneshot for refresh

### Restart Behavior

- authored entry-level `apply` blocks are not part of the model
- service-owned config/env writes use explicit service-level `apply.config_change_restart_unit`
- renderer-internal apply hints carry the runtime metadata needed by apply
- copy/update oneshots should use `try-restart` for downstream services so
  first startup and refresh use the same unit without creating ordering cycles

## Alternatives Considered

- **Allow systemd units under `composition.config`**: rejected because it mixes plain file placement with service lifecycle behavior.
- **Keep authored entry-level `apply` blocks**: rejected because they create ambiguous, overly imperative config semantics.
- **Infer restart behavior entirely from file paths**: rejected because host-daemon units cannot always be derived safely from quadlet naming conventions.
- **Inherit the entire Podman block**: rejected because deployed services should declare their
  privilege and networking locally.
- **Service-level registry image defaults alongside container images**: rejected because they
  introduce overlapping declarations and precedence rules without a demonstrated deployed need.
- **Runtime and image pairs under `podman`**: replaced before commit by container-owned images,
  which already support shared composition and match multi-container pod authoring.
- **Permanent ownership opt-outs for private volume roots**: rejected for the inspected paths;
  they obscure provisioning intent despite available directory metadata.
- **Recursive enforcement of application data**: rejected because applications legitimately
  create descendants with different ownership and permissions.

## Consequences

- Service authoring intent is clearer and easier to validate
- Schema and runtime behavior align more closely
- Contributors have a stable model for where to place units versus plain config
- Apply can enforce lifecycle intent without relying on ambiguous authoring patterns
- First boot can materialize service-owned runtime config without waiting for a
  path event that may already have happened
- Shared images can have one declaration while deployed services retain explicit runtime intent.
- Standalone and pod containers share image validation and resolution; service-level image
  inheritance and fallback are removed. Mapping and local runtime declarations identify deployed
  Podman services, while shared container fragments remain reusable.
- Private volume declarations provide directory intent without duplicate config-directory
  entries. Registration conflicts fail clearly; application-created contents remain untouched.

## References

- ADR 0004: Apply Execution Model
- ADR 0006: Secrets Model and Bootstrap Artifacts
- [Spec 0032: Container Image Authoring](../specs/accepted/0032-container-image-authoring.md)
- [Spec 0033: Private Volume Directory Management](../specs/active/0033-private-volume-directory-management.md)
