# ADR 0005: Service Authoring Model

## Status

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

### Lifecycle Intent

- `composition.systemd` entries may declare `enable` and `start` booleans
- apply enforces boot persistence with `systemctl enable/disable`
- helper units that are path-triggered are not independently enabled unless explicitly intended
- services that need Vault Agent output copied into bind-mounted runtime paths
  should model the copy as a service-owned oneshot prerequisite, with any path
  unit reusing that same oneshot for refresh

### Restart Behavior

- authored entry-level `apply` blocks are not part of the model
- host daemons without quadlet-derived unit names use explicit service-level `apply.restart_unit`
- renderer-internal apply hints carry the runtime metadata needed by apply
- copy/update oneshots should use `try-restart` for downstream services so
  first startup and refresh use the same unit without creating ordering cycles

## Alternatives Considered

- **Allow systemd units under `composition.config`**: rejected because it mixes plain file placement with service lifecycle behavior.
- **Keep authored entry-level `apply` blocks**: rejected because they create ambiguous, overly imperative config semantics.
- **Infer restart behavior entirely from file paths**: rejected because host-daemon units cannot always be derived safely from quadlet naming conventions.

## Consequences

- Service authoring intent is clearer and easier to validate
- Schema and runtime behavior align more closely
- Contributors have a stable model for where to place units versus plain config
- Apply can enforce lifecycle intent without relying on ambiguous authoring patterns
- First boot can materialize service-owned runtime config without waiting for a
  path event that may already have happened

## References

- ADR 0004: Apply Execution Model
- ADR 0006: Secrets Model and Bootstrap Artifacts
