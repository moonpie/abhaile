# ADR 0003: GitOps Runner Responsibility Boundary

## Status

2026-03-14: Accepted

## Context

`src/abhaile/` provides deterministic render, diff, and apply behavior for a given workspace state. The broader GitOps workflow also requires repository fetch/checkout, scheduled execution, run serialization, and recovery from bad revisions.

Those concerns can either live inside apply or in an outer orchestration layer.

## Decision

Commit-aware orchestration belongs to a GitOps runner layer outside `src/abhaile/`.

The runner is responsible for:

- fetching or updating repo state
- selecting the commit to render/apply
- invoking `abhaile-render` and `abhaile-apply` for the local host
- serializing runs and maintaining runner-owned state
- tracking the last successful commit per host
- retrying rollback to last-known-good when a newer commit fails
- integrating with systemd service/timer scheduling

`src/abhaile/` remains responsible for:

- rendering desired artifacts from the current workspace
- diffing manifests/state
- applying a given desired state safely to the host

## Alternatives Considered

- **Embed commit selection and rollback in apply**: rejected because it mixes workspace orchestration with reconciliation logic and makes apply harder to test and reason about.
- **Delegate scheduling/rollback to ad hoc shell or cron without a defined boundary**: rejected because it creates unclear ownership and inconsistent operational behavior.

## Consequences

- Apply stays focused on host reconciliation for a known workspace state
- Rollback and scheduling policy can evolve without destabilizing render/apply internals
- Runner state and locking can be managed independently from apply state
- Operators get a clearer mental model of where git/revision logic lives

## References

- ADR 0001: Output Root and Environment Paths
- ADR 0002: Hash-based Drift Detection and State Model
- ADR 0004: Apply Execution Model
