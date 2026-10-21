# Spec: Adaptive Reconciliation Fast Path

## Metadata

```yaml
id: SPEC-2026-029
title: Adaptive Reconciliation Fast Path
status: active
owner: moonpie
created: 2026-10-20
updated: 2026-10-21
related_adrs:
  - 0013-last-successful-ansible-reconciliation
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [abhaile-runner]
```

## Context

The five-minute GitOps runner currently renders and executes complete Ansible check and live
passes even when `origin/main`, the local checkout, and `last-successful-commit` all identify the
same revision. This correctly repairs drift, but an unchanged run already takes about 103 seconds
on Deimos and 275 seconds on Phobos. The planned service estate is several times larger than the
current 4 and 10 mapped services, so unchanged full runs are likely to exceed five minutes and
consume nearly continuous CPU time.

The existing `abhaile-health` command completes quickly, and the rendered manifest contains a
deterministic inventory of managed targets and regular-file content identities. These can support
a read-only fast path when the desired commit is unchanged, without weakening interrupted-run or
last-successful recovery.

This spec changes one part of
[Spec 0028](../accepted/0028-target-host-reconciliation-model.md): an unchanged desired revision
will no longer run full Ansible reconciliation on every timer activation. ADR 0013 was amended and
its index entry and accepted Spec 0028 were updated in the activation change. This active spec is
authoritative only for the unchanged-commit fast path, fetch-outage behavior, timer semantics, and
non-authoritative scheduling records, including whether a suppressed failed target requires an
unchanged full reconciliation; all other Spec 0028 recovery and convergence contracts remain
authoritative. The deployed runners remain always-full until the staged enabling revision is
deployed and validated.

### Activation Record

The 2026-10-20 activation review approved the ADR 0013 amendment, updated the ADR index, and added
reciprocal authority notes to accepted Spec 0028. Architect, SysAdmin, and Code Reviewer found no
remaining design, operational, or governance blocker. This is lifecycle evidence rather than
runtime implementation evidence; all delivery acceptance criteria below remain open.

## Requirements

- [ ] Preserve `last-successful-commit`, `current-run`, and `failed-target` as the only recovery
  authority records.
- [ ] Resolve enrollment, malformed state, stale committed markers, and interrupted mutation
  recovery before considering the fast path.
- [ ] Fetch the configured remote branch and compare its exact target commit with
  `last-successful-commit`; do not use working-tree `HEAD` alone as admission evidence.
- [ ] Render the exact selected commit into the current run's temporary directory before auditing;
  do not trust a persistent `/var/lib/abhaile/rendered` tree as fast-path authority.
- [ ] Admit a fast successful exit only when the target equals `last-successful-commit`, no
  unapplied failed target requires handling, the fresh manifest passes integrity audit, locally
  actionable health passes, and full reconciliation is not due.
- [ ] Run full reconciliation for a new target commit other than the currently suppressed
  `failed-target`, actionable local-health failure, detected ordinary managed drift, ordinary-entry
  audit uncertainty or execution failure, `ABHAILE_FORCE_FULL=1`, or expired maximum-full interval.
  Failed-target and reserved-foundation handling retain precedence.
- [ ] Keep cluster, peer, and external/upstream health diagnostic. Their failure must not trigger
  local mutation or block an otherwise clean fast path.
- [ ] Keep every fast-path operation read-only with respect to managed host state. It may fetch,
  check out, render into a temporary directory, inspect live state, and atomically update
  diagnostic runner records; it must not write `current-run`, advance `last-successful-commit`,
  clear `failed-target`, invoke Ansible, restart units, or publish files.
- [ ] Change recurring scheduling from `OnUnitActiveSec=5min` to
  `OnUnitInactiveSec=5min`, retaining a bounded post-boot activation. Runs must neither overlap nor
  queue, and the next routine activation must occur approximately five minutes after the previous
  service run becomes inactive.
- [ ] Record the last successful full reconciliation atomically as non-authoritative scheduling
  state. Missing, unreadable, malformed, SHA-mismatched, or future-dated state must force a full
  reconciliation. A fast run, recovery-only run, or failed full run must not advance it.
- [ ] Configure the full-reconciliation interval with
  `ABHAILE_FULL_RECONCILE_INTERVAL_SECONDS`, accepting only an integer from 3600 through 21600
  seconds inclusive and defaulting to 21600 seconds. Missing uses the default. Invalid input uses
  that safe default for scheduling and remains visibly degraded; it does not create separate state
  or force a full run on every five-minute activation.
- [ ] Bound repeated full reconciliation after a successful full run leaves integrity or actionable
  health degraded. Record that Boolean post-check result in the existing last-full scheduling
  record and defer another automatic repair for one hour. A new commit, recovery, periodic
  deadline, or `ABHAILE_FORCE_FULL=1` is never deferred.
- [ ] Preserve the existing failure contract: candidate failure and failed recovery remain
  failures, successful recovery does not accept a failed candidate, and irreversible effects are
  not described as rolled back.
- [ ] Distinguish fast, full, degraded, suppressed, and recovery outcomes in the journal,
  `last-run-status`, and `last-run-summary` without exposing secrets or unbounded drift-path lists.

## Constraints

- `config/` remains the source of truth and render remains deterministic and unprivileged.
- The fast path must not introduce a second accepted revision, applied-state ledger, transaction
  journal, desired-state cache, scheduler service, or recovery authority.
- The current host lock remains the single serialization boundary for ordinary reconciliation and
  boot recovery.
- Rendering and auditing must operate on the same exact commit. A checkout change between them is
  forbidden under the runner lock.
- Integrity checks must not follow target symlinks or block indefinitely on FIFOs, devices, sockets,
  or unexpectedly large files.
- `mapping.yaml` is host-assignment intent, not a one-to-one deployed-service inventory. A logical
  service may render multiple units, containers, pods, volumes, paths, and configuration files.
- The manifest owner/artifact graph is the desired managed inventory. Runtime discovery must be
  limited to closed Abhaile-managed scopes and must not classify unrelated administrator-managed
  units or containers as drift.
- Remove `Persistent=true`; `OnBootSec` and the full-reconciliation record govern post-boot
  behavior, and monotonic activations are not replayed.
- Implementation must use staged recovery compatibility. A state-neutral compatibility revision
  must become last-successful before a later revision depends on new manifest fields, runner state,
  or recovery behavior.
- No additional runtime dependency is introduced without separate justification.

## Design

### Runner Decision Flow

The runner keeps its existing startup and recovery handling ahead of all remote discovery and fast
admission:

```text
acquire host lock
  -> validate runner state and recover/verify interrupted work when required
  -> fetch desired branch
  -> resolve exact target and last-successful commits
  -> target equals suppressed failed-target?
       yes: preserve candidate failure and apply failed-target rules
       no: new target, ABHAILE_FORCE_FULL=1, or periodic deadline?
           yes: existing full check/apply/recovery pipeline
           no: render the exact audit revision into the run temporary directory
               -> run reserved-foundation diagnostic
               -> foundation diagnostic returns nonzero?
                    yes: record degraded-enrollment-foundation and exit without mutation
                    no: run ordinary integrity and actionable local health
               -> either ordinary command returns nonzero?
                    yes: degraded post-check for same SHA less than one hour old?
                         yes: record degraded-repair-deferred and exit without mutation
                         no: existing full check/apply/recovery pipeline
                    no: record fast-clean outcome and exit without mutation
```

A new remote commit that is not the currently suppressed `failed-target` always takes the full
path. Failed-target handling retains precedence and never retries the same rejected candidate
without the existing force-retry control. The fast path applies only when the fetched target and
last-successful commit are identical. `ABHAILE_FORCE_FULL=1` on a direct runner invocation is the
ephemeral force-full control for operators and tests; it creates no file or persistent systemd
environment and is distinct from force-retry. Missing means false; any other value is invalid and
fails before mutation.

### Fresh Render Authority

Each fast run checks out and renders the exact last-successful commit beneath `RUN_CONTEXT_DIR`.
The integrity and health commands receive that temporary output root explicitly. The run removes
the tree through the existing cleanup trap.

This costs more than reading a retained manifest but avoids a second durable desired-state copy,
stale `/var/lib/abhaile/rendered` content, and ambiguity between config and manifest revisions.
Render failure or manifest validation uncertainty selects the full path; it never produces a clean
fast result.

### Integrity Audit

For every ordinary-reconciliation manifest entry, the initial audit proves the identity actually
expressed by the current manifest:

- the target exists;
- the target is the expected regular-file or directory type;
- the target leaf is not accepted through a symlink substitution;
- a regular file has the declared size and SHA-256 digest;
- a directory has the declared type and any owner, group, or mode metadata explicitly carried by
  the manifest.

The auditor assumes the configured absolute target's ancestor directories retain their existing
root-controlled trust boundary. For the target leaf it uses `lstat`, opens regular files with
`O_NOFOLLOW`, confirms the opened identity and type with `fstat`, rejects a size different from the
manifest before hashing, caps any hash operation at 64 MiB, and verifies stable identity and size
after hashing. FIFO, device, socket, symlink, oversize, permission, race, and I/O cases are bounded
audit uncertainty, never clean results. Drift output reports totals and at most ten redacted paths.
The integrity auditor is invoked with two closed scopes and returns only zero or nonzero for each.
The `ordinary` scope reports zero only when it proves ordinary-reconciliation entries clean. Known
identity or content mismatch is logged as drift; unreadable targets, unsafe types, resource-limit
breaches, races, malformed entries, and incomplete traversal are logged as uncertainty. The runner
treats any nonzero ordinary result identically and selects the full path; it does not interpret
individual findings.

The `enrollment-foundations` scope contains only the reserved `host.sysusers`, `host.sudoers`, and
`host.authorized_keys` fixed paths. Any absence, unreadability, type change, or content mismatch
returns nonzero. The runner records code 1 `degraded-enrollment-foundation`, requires operator
bootstrap/adoption action, and does not enter ordinary repair or its one-hour deferral logic. A
clean foundation diagnostic is required for `fast-clean`.

Render continues as the unprivileged `abhaile` account. Live-target integrity and the actionable
health profile execute read-only as root through the same existing sudo boundary used by the
runner's Ansible and health commands, so root-readable managed targets can be verified. The
auditor receives only the validated fresh manifest root and exposes no arbitrary command, target,
or write operation. This spec does not broaden the enrollment-owned sudo policy.

The current manifest does not universally encode expected owner, group, mode, unit enablement,
masking, symlink destinations, or directory membership. The implementation must not infer these by
duplicating Ansible-role policy. Any expanded metadata becomes deterministic canonical manifest
data, is schema-validated, and is introduced through the staged compatibility rule.

Full Ansible reconciliation remains the semantic safety net for behavior not proven by static
identity, including handler effects, generator behavior, dependency ordering, runtime arguments,
safe removal classification, arbitrary stale extras, metadata absent from the manifest, unit
enablement/masking, and directory membership outside explicitly closed scopes.

### Actionable Health Profile

The runner invokes the independently operator-visible
`abhaile-health --profile local-actionable --output <fresh-run-root>`. The profile is restricted to
the current host's manifest and mapping and checks:

- required local addresses;
- manifest-selected local systemd and Quadlet units;
- the mapped rootless Vault Agent unit;
- manifest-selected local images and obsolete generated image units;
- the local secrets-readiness gate;
- health state of manifest-selected local containers; and
- authoritative DNS answers from the current host's own mapped CoreDNS endpoint.

The profile returns zero only when these locally actionable checks pass and nonzero otherwise. The
runner treats that as a Boolean repair input and does not parse individual check names or results.
Detailed findings remain operator-facing command and journal output.

The profile excludes unrelated failed units, the runner's own prior failed state, unmanaged Podman
objects, other-host endpoints, public recursive DNS success, and cluster consistency. The existing
default operator output remains compatible.

Public DNS reachability, cross-host CoreDNS queries, SOA consistency, and other peer or upstream
observations remain diagnostic. The existing `--cluster` behavior remains report-only.

Existing Ansible family-local acceptance remains the candidate promotion gate. The broader
actionable profile is a repair trigger and post-full diagnostic; it does not reject or roll back a
new candidate that passed the existing gate. After any successful full pipeline, the runner first
commits normal last-successful/current-run state, reruns both integrity scopes and actionable
health, and then atomically records the completed full traversal with its ordinary Boolean
post-check result. An ordinary-integrity or health residual returns service and `last-run-status`
code 1 with a `degraded-post-full` summary. A foundation residual instead remains
`degraded-enrollment-foundation` and operator-directed. Neither result marks the accepted SHA as
`failed-target` nor invokes recovery against the same accepted SHA.

The last-full record also stores `postcheck=clean|degraded` for ordinary integrity and actionable
health only. When a new failure in either is observed after a `clean` full record, the runner
attempts one full repair immediately. If that full run succeeds but its ordinary post-check remains
nonzero, the record becomes `degraded`. Further ordinary repair for the same accepted SHA is
deferred until that record is one hour old. Deferral returns code 1
`degraded-repair-deferred`; it never produces `fast-clean`.

This deliberately uses no finding fingerprints and no separate cooldown record. A changed local
failure during the one-hour window is reported immediately but may wait for the same retry
boundary. A new target, interrupted recovery, failed-candidate retry, periodic deadline, or
`ABHAILE_FORCE_FULL=1` bypasses deferral. A later successful full post-check writes `clean`.

The actionable profile must avoid a feedback loop from the runner's own prior failed unit state.
Fetch, failed-target, or diagnostic failures remain visible without causing an unrelated full local
reconciliation solely because `abhaile-runner.service` appears in `systemctl --failed`.

### Fetch Failure and Failed Targets

On fetch failure, the runner audits a fresh render of the exact retained last-successful commit. If
integrity and actionable health pass and a periodic full run is not due, it performs no mutation,
does not advance authority state, exits 0 at the systemd and `last-run-status` levels, and records
`fast-offline-clean` plus remote degradation in the summary and journal. Monitoring consumes that
explicit outcome rather than `systemctl --failed`.

If the periodic deadline is due during a fetch outage, the runner fully reconciles the retained
last-successful SHA. A successful offline full run may advance the scheduling record for that same
SHA and exits 0 with `full-periodic-offline`; it does not advance recovery authority or clear a
failed remote target.

When the remote target still equals `failed-target`, the runner preserves the failure and does not
retry that candidate. After any required recovery has succeeded, it audits last-successful and
performs another full run only for local drift, actionable health, expiry, a new target, or an
`ABHAILE_FORCE_FULL=1` request. A clean audit must not clear or visually overwrite the
failed-candidate condition. Suppressed failed-target runs return code 1 and retain a
`failed-target-suppressed` summary even when the accepted local audit is clean.

### Full-Reconciliation Scheduling State

`/var/lib/abhaile/runner/last-full-reconciliation` is an `abhaile:abhaile`, mode `0600`, regular
non-symlink file written atomically. Its closed format binds an RFC 3339 timestamp and
`postcheck=clean|degraded` to the exact full-reconciled SHA. It is not read by boot network recovery
and cannot select a recovery revision.

The record advances only after the normal full check/apply pipeline succeeds and candidate success
has been committed to `last-successful-commit` with its matching `current-run` cleared. A crash
before this later scheduling write safely causes another full run. Candidate and periodic full runs
count; recovery-only runs do not. Ordinary integrity and actionable health determine the record's
Boolean status without erasing the fact that the full traversal completed. The separate foundation
diagnostic does not alter it. A crash before the post-check or record write safely causes another
full run. Clock rollback, an implausibly future timestamp, an unexpected SHA, or any parse/type
error forces full reconciliation.

The supported interval range in this spec is one through six hours, with a six-hour default and
hard maximum. The documented worst-case semantic-drift window includes six hours, the duration of
the full run, and the post-run timer delay. Any increase toward 24 hours requires a future spec/ADR
covering canonical metadata, unit/trigger state, scoped extra-artifact detection, and new host
evidence.

### Timer Semantics

The timer uses:

```ini
[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
RandomizedDelaySec=30s
AccuracySec=1s
```

There is no execution queue. A ten-to-fifteen-minute full run is followed by approximately five
minutes plus zero to thirty seconds of randomized delay before the next activation. A short fast
run is followed by the same post-completion delay. The service and existing nonblocking lock both
prevent overlap. A failed run and an operator-started run rearm the same inactive-relative delay;
they do not leave the timer elapsed indefinitely. The expected routine start window is therefore
5 minutes 0 seconds through 5 minutes 31 seconds after the service becomes inactive, allowing one
second of timer accuracy.

The specification does not rely on `Persistent=true` for missed monotonic activations. Post-boot
`OnBootSec` starts the runner, and the last-full record determines whether that run may exit fast.

### Observability

The journal and `last-run-summary` distinguish at least:

- `fast-clean`;
- `fast-offline-clean`;
- `full-new-commit`;
- `full-integrity-drift`;
- `full-actionable-health`;
- `full-periodic`;
- `full-periodic-offline`;
- `full-forced`;
- `degraded-post-full`;
- `degraded-repair-deferred`;
- `degraded-enrollment-foundation`;
- `degraded-invalid-full-interval`;
- `failed-target-suppressed`;
- recovery and failure outcomes.

Summaries include target and last-successful SHA, trigger, audit entry count, audit duration, drift
count, a bounded path sample, last-full age, and configured maximum age. Existing status consumers
must continue to distinguish a clean host from remote/degraded or failed-candidate conditions.

`last-run-status` retains its numeric exit-code-first format. `fast-clean`, normal successful full
outcomes, `fast-offline-clean`, and `full-periodic-offline` use code 0; the two offline outcomes are
still explicitly degraded in the summary. Candidate or recovery failure,
`failed-target-suppressed`, `degraded-post-full`, `degraded-repair-deferred`, and
`degraded-enrollment-foundation` use code 1. Invalid interval configuration uses code 1
`degraded-invalid-full-interval`; it uses the safe six-hour schedule and creates no additional
state.

### Staged Recovery Compatibility

Delivery uses at least two revisions. Revision N introduces the auditor, actionable health profile,
last-full record parser, outcome vocabulary, and tests while preserving the existing always-full
runner and timer behavior. It must become `last-successful-commit` on both hosts. Revision N+1 may
then enable the decision fast path, timer change, and enhanced last-full record. Recovery of N+1
through N must be proved in a VM or equivalent isolated host test before N+1 is promoted. A host
without a valid `last-full-reconciliation` record performs a full run after N+1; it never
synthesizes history.

Because the always-full Revision N runner does not yet invoke the entrypoint installer, its rollout
has one explicit existing-host prerequisite. With the runner quiescent and its existing lock held,
the operator runs `scripts/install-abhaile-entrypoints`, verifies that `abhaile-integrity --help`
executes from the repository virtual environment, and only then runs the Revision N candidate
reconciliation. This tool installation is compatibility preparation, not fast-path activation.
Revision N cannot be promoted or recorded as the recovery baseline on either host without this
proof. Revision N+1 may depend on the wrapper only after both hosts have completed that gate.

### Performance Budget

The current manifests contain 111 entries/104 regular files on Phobos and 44 entries/40 regular
files on Deimos. The regular-file payloads total only about 43 KiB and 18 KiB respectively. A local
single-process Python hash pass over the Phobos rendered files took about 0.24 seconds including
interpreter startup.

The standalone integrity audit must complete within five seconds for a synthetic manifest of at
least 1,000 small regular-file entries. The complete clean fast path—including fetch, render,
integrity, and actionable health—must be measured on both production hosts and must normally finish
within 30 seconds.

Every external operation is bounded. One fetch attempt has a 15-second deadline, the integrity
audit has a 10-second deadline, and the complete actionable-health profile has a 30-second
deadline. The total clean fast-path decision has a 60-second hard deadline. Fetch timeout follows
the specified offline branch; an integrity, render, or actionable-health timeout is uncertainty
and selects the full path. The subsequent full reconciliation is intentionally not constrained by
the five-minute timer interval.

## Decision Notes

- Decision: Use one existing timer and one runner service rather than separate fast and full
  schedulers.
  Rationale: One lock, process, and decision point avoids scheduler races and duplicated recovery
  behavior.
  Impact: The runner owns a small non-authoritative last-full scheduling record.
  ADR: ADR 0013 amendment dated 2026-10-20.
- Decision: Schedule with `OnUnitInactiveSec` rather than `OnUnitActiveSec`.
  Rationale: Variable-duration full runs must rearm from completion without overlap or a queued
  backlog.
  Impact: A long full run intentionally stretches one polling cycle.
- Decision: Start with a six-hour forced full interval.
  Rationale: The current manifest cannot prove all metadata, unit-state, and closed-scope inventory
  invariants.
  Impact: Any consideration of a 24-hour interval requires a future spec and ADR.
- Decision: Render the exact accepted revision on every fast run.
  Rationale: The persistent render tree is not commit-bound current authority, while a fresh render
  is deterministic and avoids a second desired-state cache.
  Impact: Fast runs include render cost but remain far cheaper than two Ansible passes.
- Decision: Separate repair-triggering local health from external and cluster diagnostics.
  Rationale: Remote or upstream outages cannot be repaired by local convergence and must not cause
  repeated full runs.
  Impact: Health results gain an explicit operational classification.
- Decision: Treat post-full actionable health as a degraded diagnostic, not candidate authority.
  Rationale: The existing Ansible family-local acceptance gates determine whether a candidate may
  be accepted; broader health can identify a repair need without falsely rolling back a valid
  desired revision.
  Impact: A completed full run can accept its SHA and still return `degraded-post-full`.
- Decision: Reuse the last-full post-check result to space unsuccessful repairs by one hour.
  Rationale: A Boolean field on the existing scheduling record prevents a five-minute repair loop
  without adding fingerprints, a cooldown record, or another state machine.
  Impact: Persistent failure stays nonzero and visible. A changed local failure during the deferral
  window may wait for the same boundary, while new commits, recovery, periodic runs, and explicit
  force bypass it.

## Acceptance Criteria

- [ ] An unchanged target with clean integrity, passing actionable health, and a non-expired full
  deadline exits without invoking Ansible or mutating managed state or recovery authority.
- [ ] A new target other than the currently suppressed `failed-target`,
  `ABHAILE_FORCE_FULL=1`, and an expired full deadline select the full pipeline before fast-path
  integrity or health can return clean; the matching failed-target branch retains precedence and
  does not retry implicitly.
- [ ] Ordinary managed missing/content/type/symlink drift, actionable health failure,
  audit/render error, `ABHAILE_FORCE_FULL=1`, and expired/missing/malformed/future last-full state
  each select the full path.
- [ ] Reserved host-access foundation drift returns code 1
  `degraded-enrollment-foundation`, identifies explicit bootstrap/adoption as the remedy, and does
  not start ordinary full repair.
- [ ] Interrupted `current-run`, enrollment-required, stale committed marker, and failed-target
  handling retain precedence and their existing recovery guarantees.
- [ ] A fetch outage before the deadline yields code 0 `fast-offline-clean` only after auditing the
  exact last-successful revision; an outage after the deadline runs a full retained-SHA traversal
  and may yield code 0 `full-periodic-offline`, without changing recovery authority or clearing a
  failed remote target.
- [ ] After every successful full traversal, including both new-candidate and already-accepted/LKG
  paths, ordinary residual failure records `degraded-post-full` without creating `failed-target` or
  recovering against that accepted SHA. Foundation residual failure remains
  `degraded-enrollment-foundation` and never becomes an ordinary repair trigger.
- [ ] A clean last-full post-check permits one immediate repair for newly observed health or
  ordinary-integrity failure. A degraded post-check defers repeated automatic repair for the same
  accepted SHA until the record is one hour old, while every specified bypass starts a new full
  attempt.
- [ ] Interval parsing accepts only 3600 through 21600 seconds. Invalid input uses the six-hour
  default for scheduling, remains visibly degraded, and creates no additional state or
  five-minute full-run loop.
- [ ] Fast-path tests prove that `current-run`, `last-successful-commit`, `failed-target`, and
  `last-full-reconciliation` obey their specified mutation boundaries, and that the fast path may
  update only bounded diagnostic records such as `last-run-*`.
- [ ] Timer validation with `systemd-analyze verify` and an intentionally longer-than-five-minute
  service proves no overlap/backlog and a new activation 5 minutes 0 seconds through 5 minutes
  31 seconds after service completion, including after failure and an operator start.
- [ ] Reboot validation proves the two-minute boot activation, recovery-before-fast-path ordering,
  and conservative handling of the full deadline.
- [ ] Both hosts demonstrate a clean fast run with no Ansible process, controlled harmless drift
  detection and repair, locally stopped-service repair, correct failed-target visibility, and clean
  runner/unit state afterward.
- [ ] Performance evidence shows the standalone 1,000-entry integrity audit within five seconds,
  the complete clean production-host fast path normally within 30 seconds, and every phase plus the
  overall decision respecting its specified hard deadline.
- [ ] The initial deployed maximum full interval is six hours; one through six hours is supported,
  and any longer interval is deferred to a future spec and ADR.
- [ ] Revision N becomes last-successful on both hosts before revision N+1 enables the fast path;
  isolated recovery evidence proves N+1 can recover through N.
- [ ] Any live drift/repair experiment uses an explicitly approved harmless, non-network artifact;
  live apply and service restarts require explicit approval in that current conversation.
- [ ] Unit, integration, runner recovery, health, manifest, timer, deterministic-render, and full
  repository validation pass with evidence linked here before acceptance.

### Evidence

For each completed criterion, record:

- Implementation evidence: commit or PR.
- Validation evidence: named automated test, VM/host transcript, or equivalent verification.

## Out of Scope

- Replacing Ansible or changing resource-family convergence behavior.
- Changing the last-successful recovery authority or boot network-recovery contract.
- Adding a second scheduler, daemon, queue, event bus, or remote webhook.
- Treating `mapping.yaml`, Podman container names, or systemd units alone as a complete service
  inventory.
- Auditing arbitrary administrator-managed files, units, containers, or directories outside closed
  Abhaile-managed scopes.
- Repairing enrollment-owned account, authorized-key, or sudo-policy foundations through ordinary
  reconciliation.
- Expanding the manifest to universal ownership, mode, enablement, masking, trigger, symlink, or
  closed-directory-membership metadata.
- Increasing the maximum full-reconciliation interval beyond six hours, including to 24 hours.
- Making cluster or internet availability a local mutation gate.
- Promising immediate detection of semantic drift that is not represented in canonical desired
  metadata.
- Changing the five-minute polling delay independently of the timer semantic correction.

## Open Questions

No behavioral questions remain. Activation is complete; implementation begins with the
state-neutral compatibility revision defined by this spec.

## References

- [Spec 0028: Target Host Reconciliation Model](../accepted/0028-target-host-reconciliation-model.md)
- [ADR 0013: Last-Successful Ansible Reconciliation](../../adr/0013-last-successful-ansible-reconciliation.md)
- [Operations runbook](../../runbooks/operations.md)
- [systemd runner timer](../../../config/hosts/common/systemd/abhaile-runner.timer)
