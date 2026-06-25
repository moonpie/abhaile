# ADR 0004: Apply Execution Model

## Status

2026-04-22: Updated Accepted
2026-04-21: Accepted

## Context

Abhaile manages multiple artifact families with different runtime behaviors: systemd units, networkd artifacts, service configs, DNS-related assets, quadlets, and host-managed files. Apply needs a deterministic and testable way to reconcile changed artifacts without relying on ad hoc shell hooks.

## Decision

Apply uses typed owner-based execution driven by planner output and renderer-internal apply hints.

### Core Model

- the planner emits an ordered `convergence_plan`
- manifest entries are grouped by `owner_ref`
- executors handle typed families such as `systemd.*`, `networkd.*`, `quadlet.*`, `service.*`, `caddy.*`, and `vault.*`
- renderer-internal apply hints provide scoped runtime metadata such as restart behavior, rootless context, and unit lifecycle intent

### Explicit Safety Rules

- dry-run must not mutate host state
- service directories are enforced idempotently at apply time
- non-directory file writes are staged with deterministic ownership and mode
- reload/restart behavior is scoped to changed owners
- free-form manifest-level `reload_actions` are not part of the model

## Alternatives Considered

- **Free-form reload commands in manifests**: rejected because they weaken safety guarantees and are harder to validate or test.
- **Re-derive execution ordering inside each executor**: rejected because plan-time ordering is easier to test and keeps executors focused on side effects.
- **Defer service-directory ownership enforcement**: rejected because directory drift can silently break service startup.

## Consequences

- Apply behavior is deterministic and family-specific
- Apply normalizes managed file metadata instead of inheriting render-time
  umask or temporary-file ownership
- Runtime side effects are easier to test and reason about
- Planner logic and executor logic stay separated
- Service-specific behavior can be extended through typed hints instead of ad hoc scripting

## References

- ADR 0003: GitOps Runner Responsibility Boundary
- ADR 0005: Service Authoring Model
- `docs/reference/apply.md`
