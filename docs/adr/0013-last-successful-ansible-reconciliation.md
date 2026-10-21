# ADR 0013: Last-Successful Ansible Reconciliation

## Status

2026-10-08: Accepted

2026-10-20: Implemented on both hosts; the legacy Python mutation backend and applied-manifest
history were retired during Phase 8. Fresh bootstrap now uses the same Ansible check/live path.

2026-10-20: Amended with the active Spec 0029 adaptive reconciliation design. Recovery authority
remains unchanged.

2026-10-21: Amended with the explicit reserved runner-unit publication boundary.

Supersedes ADR 0012.

## Context

Abhaile is an owner-operated, two-host homelab. The owner reviews and pushes repository changes;
the trusted `abhaile` automation account polls that repository and performs local reconciliation.
The Ansible migration is intended to replace bespoke host-mutation code, not create a second
release, transaction, trust, or configuration-management platform.

Phases 1-5 introduced protected mirrors and exports, capsules, operation compilation, several
durable ledgers, health challenges, publication authority, and a separate network transaction
controller. Later review showed that these mechanisms duplicated the existing runner, local clone,
render manifest, lock, and last-successful commit while also changing authoring files that were
outside the migration's intended scope.

## Decision

### Trust and authoring boundary

- Reviewed repository commits and the existing `abhaile` automation account are trusted inputs.
- `config/` is restored to its Phase 0 contract. In particular, software declarations keep their
  original command-oriented content and remain future-facing render input.
- `rendered/software/` remains deterministic but is not applied in this migration.
- The existing `manifest.json` is the sole inventory for resource families already managed by the
  deployed resource inventory. Manifest v2, typed software operations, and the generic operation compiler are
  removed.
- Rendering remains unprivileged and deterministic. Ansible check mode is non-mutating; live
  reconciliation is privileged, validated, and explicitly authorized. Atomicity and recovery are
  claimed only where the resource family permits them.

### Reconciliation state and flow

The existing local clone retains revisions. The existing runner lock serializes work. Routine
authority consists only of:

1. the desired commit observed at the fixed tracked branch;
1. `last-successful-commit`, which is the sole automatic recovery target;
1. one minimal mutation marker identifying work that crossed the first mutation boundary; and
1. the existing `failed-target` suppression record.

Before mutation, failures stop without rollback. Immediately before the first managed-state
mutation, the runner durably records the candidate. Until health succeeds and
`last-successful-commit` is atomically advanced, every failure or later restart reconciles the old
last-successful revision. Recovery preserves the interrupted candidate marker while it applies the
old revision, because that identity is required for candidate-only cleanup if recovery is itself
interrupted. Only successful recovery clears that exact marker; recovery does not advance
last-successful. If the marker and last-successful revision already match after an interrupted
commit, reconciliation verifies that revision and clears the stale marker.

Each ordinary run first resolves interrupted work. It then fetches only to discover a newer desired
commit. An unchanged desired commit is still reconciled so drift is repaired. If fetch fails and a
last-successful revision exists locally, the runner warns and reconciles it from local Git objects.
Existing failed-target suppression prevents repeatedly applying the same failed candidate.

### Adaptive unchanged-commit admission amendment

Active Spec 0029 replaces only the preceding unconditional unchanged/full and fetch-failure/full
traversal rules. Recovery and failed-candidate handling still run first. A new unsuppressed desired
commit, an expired full deadline, or an explicit one-shot `ABHAILE_FORCE_FULL=1` request invokes the
existing full Ansible pipeline.

When the fetched target equals `last-successful-commit`, the runner freshly renders that exact
commit and consumes three independent Boolean results: a reserved enrollment-foundation diagnostic,
ordinary managed-artifact integrity, and locally actionable health. Foundation failure remains
operator-directed and never invokes ordinary repair. Ordinary integrity or health failure invokes
the existing full pipeline unless a recent unsuccessful repair is being deferred. External, peer,
cluster, and public-DNS health remain diagnostic because local Ansible cannot repair them. The
runner does not parse individual findings or duplicate Ansible policy.

After fetch failure, the runner applies the same Boolean checks to a fresh render of the retained
last-successful revision. If they pass and the periodic deadline is not due, it exits without
mutation while explicitly reporting offline degradation. If the deadline is due, it fully
reconciles the retained last-successful revision. Neither path advances recovery authority or
clears a failed remote target.

Ansible remains one dependency-ordered check/live path, and its existing family-local acceptance
remains candidate promotion authority. The fast path is read-only with respect to managed host
state and recovery authority. A suppressed failed candidate is not implicitly retried; its accepted
last-successful revision is audited and repaired under Spec 0029.

The non-authoritative `last-full-reconciliation` record binds the reconciled SHA, completion time,
and one Boolean `postcheck=clean|degraded` value for ordinary integrity and local health. A clean
record permits one immediate automatic repair. If a successful full repair remains degraded,
further automatic repair for the same accepted SHA waits until the record is one hour old. New
commits, interrupted recovery, failed-candidate retry, the periodic deadline, and explicit force
bypass that delay. No finding fingerprint, repair queue, or separate cooldown ledger is introduced.

Full reconciliation remains mandatory at least every six hours. The configurable interval accepts
3600 through 21600 seconds and defaults safely to 21600. Invalid input uses the six-hour schedule
and remains visible without creating state or a five-minute full-run loop. Any longer interval
requires a future spec and ADR-level review with stronger canonical drift coverage.

The single timer becomes completion-relative with `OnUnitInactiveSec=5min`, `OnBootSec=2min`, up to
30 seconds of randomized delay, and one-second accuracy. `Persistent=true` is removed. Runs neither
overlap nor queue; a long full traversal is followed by the ordinary post-completion delay.

Delivery remains recovery-compatible: a state-neutral revision introduces checks, parsing,
outcomes, and tests while retaining always-full behavior. Only after that revision is
last-successful on both hosts may a later revision enable the fast path, enhanced scheduling record,
and timer semantics. Recovery of the enabling revision through the compatibility revision must be
proved before promotion.

The network-restore service, runner service, and runner timer are reserved self-management
foundations. Ordinary reconciliation validates them but does not publish them while the runner is
executing. Fresh bootstrap and later operator-controlled updates publish only this fixed unit set
through an explicit installer after the exact repository revision is already
`last-successful-commit`, while the timer and service are quiescent and the shared runner lock is
held. Publication reloads systemd but never activates these units; activation remains a separate
operator or bootstrap boundary.

`last-full-reconciliation` cannot select a recovery revision. This ADR remains authoritative for
candidate promotion, the mutation marker, last-successful recovery, candidate-only cleanup, and
network boot recovery. The deployed runners remain always-full until Spec 0029's staged enabling
revision is deployed and validated.

Candidate-only additions are cleaned using the retained interrupted-candidate and last-successful
manifests. Removal is limited to Abhaile-managed resources whose live identity still matches the
candidate. Ambiguous or irreversible cases stop for operator recovery. No execution replay graph,
absent-before ledger, promotion transaction, or second last-known-good record is introduced.

Ansible replaces only the mutation backend for the resource families represented in
`manifest.json`. Conventional roles, built-in modules, and handlers are preferred. Custom modules
require a demonstrated safety gap in standard Ansible behavior.

### Network boot recovery

Network configuration follows the same last-successful rule. A small early mode of the existing
runner executes before `systemd-networkd`: under the same lock, it exits successfully without
checkout or toolchain dependencies unless `current-run` differs from `last-successful-commit`.
Only then does it read retained local Git objects, render the last-successful revision, remove
matching interrupted-candidate-only network artifacts, and apply only the last-successful network
role.

This mode does not fetch, promote, run ordinary service convergence, or own another journal,
timer, probe protocol, confirmation state, or success definition. Normal reconciliation and health
remain the only path that advances `last-successful-commit`.

### Migration boundary

The existing service account, clone, credentials, virtual environment, runner service/timer,
bootstrap mechanism, lock, and privilege model are retained during this migration. Changing those
foundations requires a separate demonstrated need and decision. The Phase 1-5 protected trust and
transaction platform is deleted unless a surviving requirement cannot be met by the existing
project model, standard Ansible, or the minimal recovery flow above.

## Alternatives Considered

### Protected bundles and accepted/pending/rejected records

Rejected because they duplicate the local clone and runner state, introduce installation and
compatibility lifecycles, and are disproportionate to the trusted two-host environment.

### Separate guarded-network transaction controller

Rejected because the desired recovery rule is identical for network and non-network state: until
success is committed, restore last-successful. Only boot ordering requires special treatment.

### Keep the Python apply engine indefinitely

Retained as the fallback if the smaller Ansible implementation does not materially reduce custom
code and operational concepts. Phase 5.2 includes an explicit go/no-go comparison.

## Consequences

- The migration returns to its original scope: replace common mutation mechanics with Ansible.
- Recovery has one durable commit point and one target that operators can explain and inspect.
- Network boot safety adds a constrained early invocation, not another transaction system.
- Software/package/build execution remains deferred rather than being silently broadened into this
  migration.
- Recovery depends on the last-successful revision and required inputs remaining in the local Git
  object database; destructive Git maintenance must preserve them.
- Recovery-affecting runner, renderer, state, playbook, and role changes are first accepted in a
  state-neutral revision. A later revision may depend on them only after revision N has proved it
  can recover N+1. Defects already accepted in recovery code require explicit operator or console
  repair; no second installed recovery runtime is introduced.
- Network acceptance proves canonical local interface, source-address, and route coherence.
  Gateway, neighbour, SSH, Internet, and peer reachability are diagnostic rather than promotion
  authority.
- Irreversible effects and ambiguous candidate-only cleanup remain explicit operator concerns.
- Clean unchanged polls can avoid Ansible, while new commits and six-hour assurance retain the
  existing full pipeline.
- Static integrity cannot prove every semantic invariant, so periodic full reconciliation remains
  the safety net.
- Persistent ordinary failure remains visible while automatic retries are spaced by one hour; a
  changed failure during that window may wait for the same boundary unless explicitly forced.
- Long full runs extend the timer cycle by design and do not accumulate queued work.
- Runner self-unit changes require an explicit quiescent publication step after their commit is
  accepted; they cannot silently replace the active reconciliation foundation.
- ADR 0012 and its superseded ADRs remain historical evidence, not implementation authority.

## References

- [Spec 0028: Target Host Reconciliation Model](../specs/accepted/0028-target-host-reconciliation-model.md)
- [Spec 0029: Adaptive Reconciliation Fast Path](../specs/active/0029-adaptive-reconciliation-fast-path.md)
- [ADR 0012: Trusted-Revision Ansible Reconciliation](0012-trusted-revision-ansible-reconciliation.md)
- [Phase 5.2 checklist](../../TODO.md)
