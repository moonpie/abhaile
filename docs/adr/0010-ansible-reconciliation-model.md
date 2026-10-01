# ADR 0010: Ansible Reconciliation Model

## Status

2026-09-05: Accepted

2026-09-30: Amended by active Spec 0028 with bounded publication and validation mechanics.

2026-10-01: Amended by active Spec 0028 with durable runner-LKG promotion mechanics.

## Context

Abhaile currently owns two responsibilities that are tightly coupled in a single custom apply pipeline: deterministic desired-state rendering and local host mutation. The repository uses a render/apply split with a manifest and hash-based drift model, and the GitOps runner is responsible for commit selection and rollback outside the apply engine.

The existing apply engine already performs file placement, owner-based execution, systemd activation, networkd operations, podman quadlet activation, validation, and state rotation. That behavior is valid and tested, but it also creates a significant bespoke maintenance surface that duplicates functionality already provided by established configuration-management tooling.

The migration goal is to keep the declarative authoring model and compiler intact while delegating generic host convergence to Ansible. This reduces the maintenance burden without collapsing the render boundary or the GitOps trust model.

This decision is architectural because it changes the host mutation model, the state contract, and the authority boundary between Abhaile and Ansible.

## Decision

Abhaile will continue to own declarative intent, render, validation, manifest generation, and GitOps orchestration. Ansible will become the local host reconciliation engine for generic host state mutation, while the current rendered artifact layout and compatibility manifest continue to define the boundary during the migration.

### Scope of the Decision

- `config/` remains the canonical source of declarative intent.
- `abhaile-render` remains the host-scoped compiler for the initial migration.
- `rendered/manifest.json` remains the compatibility boundary between renderer and converger.
- `abhaile-apply` remains the canonical operator-facing entry point and delegates host mutation to Ansible.
- Ansible runs locally on the target host, not through a central control plane or SSH fan-out.
- A reduced applied-state ledger remains for safe-prune, rollback planning, and reporting.
- Destructive operations and prune safety remain explicit and fail closed unless approval is provided.

### Privileged Code Trust

The `abhaile` service account must not be able to modify code or desired-state data that root
executes or consumes. The runner requests convergence of a full commit object ID through a
root-owned launcher. A root-owned updater fetches the configured branch into a bare mirror using a
pinned Git host key and root-controlled read-only credential. It rejects non-fast-forward updates
unless explicitly approved. The launcher accepts only commits reachable from the root-fetched
trusted ref or retained by the root-owned last-known-good ref.

The launcher exports an accepted revision into a new root-owned staging tree. A dedicated
non-login render identity reads that protected source and writes only to unique temporary output.
After render exits, root validates the manifest, host, paths, hashes, ownership metadata, and
completeness; removes render-identity write access; and atomically seals source and output as one
immutable convergence capsule. Root runs `abhaile-apply` and Ansible from the sealed source and
consumes only its sealed manifest and artifacts.

The launcher never copies executable or desired-state content from the service-account checkout.
The last-known-good ref and capsule remain cached for offline rollback. Mirror garbage collection
preserves trusted, last-known-good, active-transaction, and configured rollback-history objects.
Launcher and trust-policy updates are privileged atomic installations from an already trusted
capsule and take effect only on a subsequent invocation.

The sudo policy permits only the fixed root-owned launcher invocation. It does not grant
`NOPASSWD:ALL`, execute an entry point from the service-account-writable checkout or virtual
environment, or accept caller-controlled paths outside configured roots. Rootless service actions
explicitly transition from the root play context to the declared service user with the correct
home, runtime directory, and user manager.

Privileged publication never traverses ancestry writable by the target rootless identity.
Rootless Quadlets are published root-owned in Podman's system-wide per-UID search path,
`/etc/containers/systemd/users/<sealed-uid>/`, while activation still uses the manifest-sealed
named-user manager context. Other named-user-writable targets remain fail closed unless a later
accepted design provides equivalent race-free publication.

Every publication candidate is content-validated during the complete pre-mutation pass. Native
non-starting validators use fixed protected paths and argv. Renderer-owned Caddy and CoreDNS
configuration is also constrained by a project parser that accepts only the complete closed
grammar emitted by the renderer; unknown nesting, arity, directives, imports, or blocks fail
before mutation. Exact installed binary/plugin compatibility remains an adoption evidence gate
and cannot broaden the admitted grammar.

### State and Health Boundaries

Apply state and runner state are separate ledgers. Apply records a manifest only after convergence
and local validation succeed. The runner records a last-known-good revision only after its wider
health gate succeeds. If wider health fails, rollback retains the previous last-known-good revision
and plans reconvergence from the actual newly applied manifest to that revision's desired manifest.

Runner last-known-good promotion is a protected durable transaction, not an in-memory health
marker. One coordinator entry point holds a protected process lock across apply-state verification,
protected wider-health-result verification, promotion, and publication authorization. Health
success is derived from closed observations in a no-follow ownership/mode-checked persisted result
bound to an unpredictable challenge created only after apply commit and to the exact transaction
and apply evidence; a caller boolean, callback, or predated result is not authority. The
coordinator re-verifies current apply state, retained applied-state identity, and the retained
mirror ref immediately before persisting and fsyncing a journal bound to candidate and retained
revision/manifest identities, capsule, health, and apply evidence. It compare-and-swap rotates the admitted mirror last-known-good and rollback
refs, verifies the resulting ref, then atomically persists a separate runner-LKG receipt. Only a
verifier-issued authority produced by re-reading that receipt and ref permits transaction-bound
runner-unit publication or recovery. Recovery finishes forward only from the journal's exact prior
or candidate ref state; a same-revision promotion performs no redundant ref mutation. Mismatched,
stale, fabricated, predated, or third-state authority fails closed. A
health failure never mutates the LKG ref or runner ledger. If candidate and retained desired-state
identities are equal, the result is an explicit same-desired-state recovery plan rather than a
fictitious revision rollback.

Protected wider-health evidence also has a durable completion boundary. An exact active journal
retains the challenge and transaction identity across interruption, and immutable results cannot
be reused across transactions. Success becomes terminal only after the LKG receipt and mirror ref
are re-verified. Failure remains active and excludes new transactions until the protected rollback
coordinator durably commits the exact retained apply state. Transaction-scoped terminal records
are written before active evidence is cleared. Interrupted cleanup finishes forward only after
the corresponding receipt/ref or rollback state is independently re-verified; it never relies on
timestamps, caller assertions, or blind deletion. This permits consecutive and fresh
same-revision reconciliations while preserving exact retry recovery and stale-evidence isolation.

### Required Migration Constraints

- No change to the config authoring model during the initial migration.
- No change to the GitOps runner's commit selection, locking, health gate, or rollback semantics.
- No change to the secrets trust boundary: runtime secrets remain stored and rendered by Vault Agent and host-local runtime paths.
- No direct migration of the host to a central Ansible controller or remote orchestration model.
- No hidden broadening of privileged trust boundaries.
- No root execution of repository content controlled by the `abhaile` service account.
- No root consumption of manifests or artifacts controlled by the `abhaile` service account.
- No dependency on remote availability when reconverging a cached last-known-good revision.

### Operational Model

The compatibility path is:

```text
config/ -> abhaile-render -> rendered/ -> Ansible -> live host
```

The GitOps runner remains the outer reconciliation controller and continues to own commit selection and rollback. Ansible is an execution engine inside that loop, not a replacement for the GitOps process itself.

## Alternatives Considered

### Option A: Keep the custom apply engine indefinitely

- Pros: no migration cost; preserves current behavior and contracts.
- Cons: continues the bespoke maintenance burden, duplicates common configuration-management concerns, and increases the cost of host operations.

### Option B: Replace the custom apply engine immediately with Ansible and redesign render at the same time

- Pros: simpler eventual architecture in one pass.
- Cons: high risk; combines two large boundary changes; harder to validate; increases chance of regression during service migration.

### Option C: Use Ansible only for host mutation while preserving the current render/apply contract as the compatibility boundary

- Pros: best balance of correctness and incremental migration; reduces maintenance without destabilizing the compiler or operator workflow.
- Cons: requires temporary compatibility scaffolding and a reduced applied-state ledger for safe pruning.

This option is the chosen direction.

## Consequences

### Positive

- Reduces bespoke host-mutation logic without rewriting the declarative configuration model.
- Preserves the project’s current GitOps and render contracts during migration.
- Keeps live service startup independent from Ansible availability after convergence.
- Allows incremental proof of idempotence and safety before removing custom executor logic.

### Negative / Trade-offs

- A compatibility layer is required during the migration.
- The current apply and drift semantics must be documented as a constrained transitional model.
- Some state and prune semantics remain temporarily more complex than a pure Ansible model.
- Operators continue using the stable Abhaile CLI surface after the custom Python mutation backend
  and temporary Ansible selector are removed.
- Root-owned revision staging introduces a protected checkout and trust-verification mechanism that
  must be maintained alongside the unprivileged runner checkout.

## References

- [Spec 0028: Target Host Reconciliation Model](../specs/active/0028-target-host-reconciliation-model.md)
- ADR 0002: Hash-based Drift Detection and State Model
- ADR 0003: GitOps Runner Responsibility Boundary
- ADR 0004: Apply Execution Model
- ADR 0006: Secrets Model and Bootstrap Artifacts
- [docs/specs/accepted/0008-manifest-drift-model.md](../specs/accepted/0008-manifest-drift-model.md)
- [docs/specs/accepted/0009-apply-pipeline.md](../specs/accepted/0009-apply-pipeline.md)
- [docs/specs/accepted/0012-gitops-runner.md](../specs/accepted/0012-gitops-runner.md)
