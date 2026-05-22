# ADR 0002: Hash-based Drift Detection and State Model

## Status

2026-05-05: Updated Accepted
2026-01-31: Accepted

## Context

Render produces desired-state artifacts, and apply must determine what changed on the live system before making changes. The system needs deterministic drift detection without retaining old rendered trees, because render output is ephemeral and may be wiped before each run.

The original design used a single manifest concept. The current model separates the desired manifest emitted by render from the durable applied-state manifests maintained by apply.

## Decision

### Desired Manifest

Render writes the desired manifest to `<output>/rendered/manifest.json`. It describes the current desired state for the just-rendered tree.

### Applied State

Apply owns the durable state under `<output>/state/`:

- `state/manifest.json` — last successfully applied manifest
- `state/manifest.previous.json` — prior successfully applied manifest
- `state/history/manifest-<timestamp>.json` — retained apply history snapshots

History is rotated and pruned according to apply policy.

### Drift Detection Model

Drift detection compares:

1. the desired manifest in `rendered/`
1. the last-applied manifest in `state/`
1. the live host filesystem

This allows apply to identify:

- added artifacts
- changed artifacts
- missing artifacts
- removal candidates
- locally drifted files

### Reconciliation Behavior

Apply uses the desired manifest plus live-state inspection to plan reconciliation. Removal is guarded:

- `--prune` removes only artifacts that were previously applied, are no longer desired, and have not drifted on-host since last apply
- `--force-prune` allows removing those artifacts even if the on-host file has drifted

State is updated only after a successful apply.

### Why Hash-based

- **Deterministic**: same desired content yields the same manifest
- **Efficient**: content hashes are cheap to compare and automate around
- **Safe**: no need to keep old rendered trees
- **Auditable**: apply history provides durable snapshots of what was last applied
- **GitOps-aligned**: desired state, applied state, and live state are distinct and inspectable

## Alternatives Considered

- **Diff old render vs new render**: rejected because render output is ephemeral and retaining old trees adds storage and cleanup complexity.
- **Minimal drift-only manifest**: rejected because apply needed richer metadata and clearer separation between desired and last-applied state.
- **Single manifest owned by both render and apply**: rejected because it blurs ownership and makes it harder to distinguish desired state from successfully applied state.

## Consequences

- Drift detection has a stable contract even when render output is regenerated from scratch
- Apply has a durable audit trail and a clear rollback reference point
- Tooling can reason separately about desired state and last-known-good applied state
- Prune behavior is explicit and safer by default

## References

- ADR 0001: Output Root and Environment Paths
- ADR 0004: Apply Execution Model
