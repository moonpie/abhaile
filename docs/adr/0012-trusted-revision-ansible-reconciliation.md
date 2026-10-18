# ADR 0012: Trusted-Revision Ansible Reconciliation

## Status

2026-10-08: Superseded by ADR 0013.

2026-10-05: Accepted

Supersedes ADR 0010 and ADR 0011.

## Context

Abhaile is a two-host homelab. The owner reviews and pushes repository changes; the unattended
`abhaile` account fetches those trusted revisions and requests local convergence. Repository
content selected for deployment is trusted executable code, while dirty working-tree content and
caller-selected paths are not deployment authority.

The first Ansible migration design grew into a second configuration-management and transaction
platform: an independent root Git mirror, sealed capsules, an operation compiler and dispatcher,
two success ledgers, health challenges and receipts, runner self-publication, and a separate
guarded-network transaction controller. Although carefully implemented, that machinery was
disproportionate to the environment and undermined the purpose of adopting Ansible.

Abhaile still needs deterministic revision selection, safe privileged execution, crash recovery,
family-scoped offline recovery, network boot safety, safe deletion, and explicit destructive
approval. Those properties do not require a general transaction engine.

## Decision

### Trust model

- Reviewed commits at the exact fetched fast-forward `origin/main` tip are trusted release code
  and configuration.
- The `abhaile` account is trusted automation, not a hostile tenant. Root and deliberate malicious
  repository content are outside the recovery threat model.
- Root never executes uncommitted working-tree bytes, caller-selected repository paths, mutable
  refs, or the service-account virtual environment.
- The normal Git credential is fetch-only where the hosting platform permits it.

Under the shared host lock, the service account fetches into a fixed temporary ref. The launcher
verifies fast-forward ancestry from the current fixed `refs/remotes/origin/main` and from accepted
when it exists before atomically advancing that tracking ref. An internal launcher function accepts
only the exact verified tip and verifies the commit and tree using isolated fixed Git
configuration. The tracking ref remains cache/selection state rather than recovery authority;
process death may leave only an ignorable temporary ref, and non-fast-forward replacement requires
an explicit operator procedure. The export function is not a separate executable, service,
privilege interface, or installed component. Root creates a protected temporary revision bundle;
the trusted unprivileged `abhaile` identity renders only its exact `source/` export;
root validates a descriptor-anchored snapshot and materializes its bytes into fresh root-owned
`rendered/` inodes before sealing and atomically publishing `revisions/<sha>/`. Renderer-owned
inodes and any retained writable descriptors remain confined to abandoned scratch. It accepts no
caller repository, ref, destination, output, or environment override. This single
source-and-rendered cache object is not a
capsule activation, renderer-containment platform, or general trust graph.

Published bundles remain read-only execution inputs. Python and Ansible bytecode, temporary files,
caches, retries, logs, facts, and plugin output use fixed protected writable paths outside them;
ambient destinations are disabled. Bundle identity is verified before execution and remains
unchanged afterwards. This is protection from accidental mutation, not containment of trusted
promoted root code.

One installation-owned host identity selects rendering and is checked against the live short
hostname. The launcher accepts no caller host. Bundle metadata binds format version, host,
revision, source-tree identity, rendered-inventory digest, and one installation-owned render-ABI
identifier covering output-affecting installed toolchain behavior. Existing same-SHA bundles are
reused only after complete verification and supported-ABI validation; conflicting, partial,
corrupt, wrong-host, or nondeterministic same-input output fails closed and is never silently
replaced. Interrupted temporary trees have bounded, ownership-aware cleanup.

One root-owned launcher exposes `preview`, `reconcile`, and `enroll` to operators; `guard` is a
fixed internal mode available only to the installed boot service. It is their sole lock owner.
`reconcile` derives candidate, pending recovery, accepted repair, rejection, polling, and drift
branches from authoritative state; callers do not select them. One timer calls it at a fixed
interval. It performs recovery first, runs the fixed fetch as `abhaile` while retaining the lock,
and verifies the fetched SHA after returning to the privileged flow. When bundle construction is
needed, root creates protected scratch and separately invokes only the fixed exact-source render as
`abhaile`, then resumes privileged validation and publication. Neither identity transition accepts
caller-selected commands or grants sudo. Nested components never reacquire the lock or split
revision selection from convergence.
After cutover, `abhaile` has no sudo authorization: root systemd services own unattended privilege,
while human enrollment, retry, repair, and maintenance use the operator's separate existing
administrative access.

Fixed installation-owned systemd services supervise scheduled and boot requests with bounded
timeouts and control-group termination. An authorized human administrator may invoke the same
launcher directly. Both paths use the same lock, signal propagation, bounded waits, and descendant
quiescence; direct use adds no request queue, mode file, transient unit, or second reconciliation
protocol. The launcher releases the lock only after no fetch, render, Ansible, validator, or handler
process can continue mutation.

The guard service orders before `systemd-networkd.service`. The ordinary reconciliation service
orders after networkd, but not after `network-online.target`, preventing a boot-time shared-lock
inversion while preserving local-first accepted recovery and drift repair.

Direct human invocation defaults to `preview`; `reconcile` and `enroll` are explicit. The scheduled
unit specifies `reconcile`, and only the boot service specifies internal `guard`. No caller can
select the host, repository, revision, inventory, output, executable, or environment. Rejected
retry, non-fast-forward repair, destructive abandonment, disaster recovery, and installation
changes are operator procedures outside the routine launcher: they stop scheduling, take the same
lock, use fixed installation tooling, validate ordinary state, and resume reconciliation. Explicit
retry verifies the rejected SHA is still the exact eligible tip, atomically removes only that
rejection record, and returns to ordinary reconciliation; it cannot select a revision or mutate
managed state itself. Non-fast-forward repair publishes a reviewed remote bridge/merge tip that
descends the retained accepted/tracking history; it never bypasses ancestry by resetting the local
tracking ref. Intentional unrelated-history replacement is disaster recovery through explicit
foundation reinstall/re-enrollment and new initial acceptance. Ordinary
rollback is a reviewed Git revert at a new eligible tip; automatic recovery uses accepted, and
arbitrary historical revision selection is unsupported.

Quiescence covers launcher-owned Git, render, Ansible, validator, helper, and synchronous handler
processes, not persistent services deliberately managed through installed systemd units.
Reconciliation-triggered effects cannot use Ansible async, shell backgrounding, detached children,
transient units, or non-blocking activation. Autonomous path-triggered runtime behavior may proceed
independently; initial reconciliation waits through ordinary systemd/readiness checks for every
required resulting local service state.

Human administrative access is an adopted foundation. A separate session proves a named operator's
local and intended SSH/WireGuard access, independent sudo, and console recovery before legacy
automation sudo is removed. Candidate convergence cannot remove its account, keys, groups, or
policy unless they are explicitly transferred into a dedicated administrative-access policy.

Authoritative rendering and validation use only the exact source export, fixed host identity, and
versioned installed toolchain. They contain no timestamps and do not consult ambient Git state,
working directory, environment, account database, clock, network, or external state. Git-history
or date-based authoring assistance remains outside host reconciliation.

### Reconciliation and durable facts

One ordinary reconciliation procedure observes live state, renders a selected immutable revision,
uses conventional Ansible roles and handlers to converge it, performs bounded local acceptance,
and records success.

Before pending is durable, no managed-host mutation is permitted. Execution is limited to
unprivileged rendering, installation-owned structural validation, read-only observation, collision
checks, and reporting. Candidate Ansible roles, modules, validators, commands, handlers, and all
other root-capable candidate code run only after pending is durable; Ansible check mode does not
weaken this boundary. The only pre-pending authoritative write is an atomic exact-SHA rejection by
installation-owned launcher logic after a deterministic candidate error. Preview and
transient/tooling failures cannot make that write.

The only authoritative durable facts are:

1. `accepted`: the exact last-successful SHA and sole automatic recovery target;
1. `pending`: the attempted candidate SHA plus only bounded absent-before identities for eligible
   reversible candidate additions, using a closed resource-family vocabulary derived from the
   canonical inventory;
1. `rejected-candidate`: the exact SHA suppressed from unattended retry; and
1. one kernel-released `flock` shared by timer, boot-guard, and direct human-admin invocations.

The immutable accepted and pending revision bundles contain their validated artifact inventories;
records do not duplicate them. There is no durable applied ledger, execution-stage journal, health
challenge, receipt, promotion transaction, callback authority, or separate network success state.

Until `accepted` is atomically replaced, recovery always selects the old accepted SHA. Any failure
after pending exists, including interruption discovered by a later invocation, atomically records
the pending SHA as rejected before attempting accepted recovery. Pending clears only after accepted
reconciliation passes. A crash between rejection and cleanup is therefore idempotent. An unchanged
rejected tip is not retried automatically; branch advance or explicit operator retry permits a new
attempt.

Pending with no accepted record is an initial-enrollment state, not ordinary recovery. Unattended
work and the normal boot guard fail without mutation. Explicit enrollment may idempotently resume
only that same candidate; choosing another candidate requires authorized exact abandonment and
cleanup or reinstall. Rejection records failure but cannot imply rollback before a first accepted
revision exists, and the pre-enrollment network baseline remains installation-owned.

A rejected candidate invocation remains non-zero even when its single accepted recovery attempt
passes; recovery proves safe host state, not candidate success. The reconciliation service uses
`Restart=no`, leaving the next attempt to the fixed timer and avoiding a restart loop. A fetch
outage followed by accepted `PASS` remains success-with-warning because no candidate was rejected.

The guard and networkd dependency are installed but inactive before accepted. Fresh enrollment may
activate them once accepted is durable. During existing-host adoption they may be activated and
reboot-tested only inside the temporary one-writer window; the operator then continues directly to
cutover or disables the dependency and verifies the legacy network baseline before resuming legacy
scheduling. Permanent activation occurs at cutover. Once permanently activated, missing or corrupt
accepted authority fails closed; returning to the installation-owned network baseline requires the
explicit reinstall/disaster-recovery procedure.

### Acceptance, rollback, and irreversible effects

Promotion requires bounded deterministic local evidence: valid render/inventory, successful
Ansible and handlers, expected local files and units, changed-service readiness where controlled by
the candidate, and one bounded check to the canonical gateway/router address when networking
changed. That address is derived from existing network intent and checked with an ordinary installed
command; no peer daemon, helper protocol, configurable probe schema, callback, namespace, or
separate authority exists. Other cross-host, Vault, DNS, Internet, cluster, and
external-dependency checks are report-only.

Each resource family classifies checks as required local invariants, candidate-controlled
readiness, external report-only observations, or unavailable/ambiguous observations. Unavailable
required evidence is `UNKNOWN`. Exit status and structured redacted journald messages are
diagnostic evidence; an optional read-only status summary may inspect authoritative records,
bundles, systemd results, and journal entries but never authorizes promotion or recovery.

Acceptance is host-local and the two hosts may temporarily accept different SHAs. Work requiring
fleet-atomic behavior is maintenance-gated; no cross-host transaction is implied.

Rollback means ordinary Ansible reconciliation of supported reversible state to accepted. It does
not claim to reverse package maintainer scripts, database or volume mutation, UID/GID migration,
arbitrary builds, external API effects, or other irreversible work. Such operations are
forward-only, maintenance-gated, backup-dependent, separately approved, or excluded from
unattended convergence.

Phobos `gasket-dkms` package production is a concrete maintenance-gated case: an operator builds,
validates, and installs the Debian package through reviewed Debian tooling. Unattended
reconciliation manages only the resulting declared package/module/udev state and never runs the
container build; accepted recovery assumes the required package remains installed or retained.

Offline recovery is guaranteed only when the accepted payload is retained in the bundle or proven
present locally. Packages, images, downloads, builds, and other acquisition-dependent families
must define retention explicitly or be classified as online, maintenance-gated, or non-reversible.
Accepted remains the desired recovery authority when unavailable prerequisites make restoration
fail or remain unknown; it is not a claim of universal offline reversibility.

### Network boot safety

Network configuration uses the same pending, accepted, and promotion rule as every other resource.
There is no independent network transaction or confirmation authority.

A separately installed root-owned boot guard is mandatory because pending candidate networkd files
or an interrupted accepted drift repair could otherwise leave partial files for activation before
the normal runner after reboot. Networkd always orders after the guard. Once active, the guard
always invokes only the accepted boot-critical network role: with no pending it verifies/restores
accepted files; when pending differs from accepted it additionally removes exactly matching
eligible candidate-only additions; and when pending equals accepted it preserves those now-accepted
additions while verifying/restoring accepted files. Successful normal reconciliation, not the
guard, later clears stale pending.

The guard owns no success, probe, retry, rollback, or journal state. It does not fetch, promote,
clear pending, call `networkctl`, reload networkd, resolve DNS, contact remote services, or run
ordinary network handlers. Its launcher, unit identities, networkd dependency, human
administrative access, and minimal runtime are installation/adoption-owned and excluded from
candidate convergence. Any additional
network helper requires a specific disposable-VM failure proving this constrained invocation is
insufficient.

The guard and accepted network role share one small versioned interface. Candidate preflight and
interruption-safe installation updates prove that the installed system Python/Ansible can execute
every retained accepted bundle needed for recovery. Operator rollback is part of an installation
update; a copied private runtime is introduced only if VM evidence demonstrates it is required.

Installation-owned readers must decode the current accepted and pending record/bundle formats
before activation. Format upgrades retain bounded backward-read support for accepted and pending
authority until it is gone; only unreferenced non-authoritative bundles may be removed and rebuilt
under the ordinary lock. Incompatible accepted or pending state blocks upgrade, and every temporary
compatibility reader has a removal gate.
Output-changing toolchain updates bump the render ABI while retaining execution/validation support
for accepted and pending bundles; they never rebuild those same-SHA bundles in place. Ordinary
locked cache cleanup may remove an unreferenced incompatible preview bundle before reconstruction,
otherwise a new reviewed revision is required.

### Ansible and inventory boundary

Ansible is the generic local converger. Resource intent passes directly from the renderer's one
artifact/resource inventory into dependency-ordered resource-family roles. Built-in modules and
ordinary handlers are preferred; maintained collections are considered next. A custom module is
allowed only for a demonstrated missing safety property, such as no-follow publication,
ownership-aware prune, bounded acquisition, a required validator, or rootless user-manager
transport.

The design does not retain a generic operation compiler, action/effect/phase language, exact-cover
VM, parallel Ansible schema, generated lifecycle protocol, or transaction coordinator. Ordinary
desired-state removal continues to obey safe-prune, destructive, network, volume, and explicit
approval gates. Pending cleanup is narrower authority and cannot broaden those rules. Ordinary
resource-family roles deactivate eligible candidate-only logical resources before removing their
files, and only while the bounded absent-before identity still matches; other families are
maintenance-gated or forward-only rather than expanding pending into an execution journal.

### Polling, drift, preview, and adoption

- One fixed-interval timer performs local pending recovery first, then fetches and attempts a
  changed eligible tip or reconciles accepted for drift when the tip is unchanged or equals the
  suppressed rejected SHA. A rejected tip with no accepted state fails without mutation pending
  explicit enrollment repair or retry. With accepted and no pending, fetch failure is reported and
  accepted still reconciles from its retained local bundle; remote availability gates only
  candidate discovery. Accepted `PASS` remains a successful invocation with warning diagnostics,
  while accepted `FAIL`/`UNKNOWN` determines failure status.
- Preview may fetch, export immutable cache content, render, validate, observe, and report. It may
  not write authoritative records, alter retention, clean up or mutate managed resources, execute
  handlers, activate networking, or reject a SHA. It uses installation-owned structural validation
  and read-only observation and never invokes candidate Ansible, including in check mode. Check mode
  remains isolated role-test or post-pending behavior, not a public mode or pre-pending boundary.
- Installation and existing-host adoption are explicit operator procedures. Fresh enrollment
  writes its first accepted SHA only after an explicitly authorized convergence and local
  acceptance pass; failure leaves accepted absent and requires operator repair, retry, or reinstall
  because no automatic rollback target exists. Existing-host adoption records a baseline only
  after observation or authorized convergence proves live conformance. Normal unattended operation
  fails without mutation when accepted is absent.
- Every pre-cutover mutation or recovery proof through the new path uses a temporary one-writer
  window: stop legacy scheduling, prove its process/lock quiescent, align both implementations on
  one revision, perform and verify the new operation, then either resume legacy before the fallback
  boundary or continue into cutover. Before legacy resumes, disable any temporary guard dependency
  and verify the legacy network baseline. The two writers and boot authorities never overlap.

Only accepted and pending bundles are retained automatically. A bounded sweep removes other
unreferenced bundles. Corrupt or lost records, bundles, or clone authority use a
documented operator repair from independently known authority or a complete reinstall and explicit
re-enrollment; they do not weaken validation.

Preview removes its incomplete scratch, reuses verified bundles, and refuses new unreferenced cache
publication beyond fixed count/byte ceilings. It does not evict unrelated content. Mutation-capable
locked work owns bounded cache cleanup; accepted and pending are never eviction candidates.

Hostname and installed host identity are adoption foundations outside ordinary candidate
convergence. Changing them requires an explicit console-recoverable procedure that coherently
updates config mapping, installed identity, bundle expectations, and host state.

Cutover has exactly one mutation writer and a frozen promotion window. Both implementations first
align on one proven revision; the operator then stops and disables legacy scheduling, proves the
legacy process and lock quiescent, establishes and verifies accepted authority, runs the new
reconciliation explicitly, enables the new reconciliation timer, and proves the legacy service
cannot auto-start. Legacy fallback is available only until the new runner accepts a different
revision. After that boundary recovery uses the new accepted model rather than attempting to
synchronize or reactivate stale legacy state.

## Alternatives Considered

### Complete the Phase 1-5 protected transaction platform

Rejected because its mirrors, capsules, operation VM, multiple ledgers, receipts, and specialized
network controller impose disproportionate implementation and operational cost.

### Treat promoted repository content as hostile

Rejected for this environment. Meaningful containment would require separately installed models,
release packaging, compatibility management, and runtime confinement while still allowing broad
root mutation.

### Retain and selectively harden the legacy apply engine

Retained as the fallback if the simplified Ansible implementation cannot delete more complexity
than it adds. It remains production-authoritative until replacement proof and explicit cutover.

### Use ordinary Ansible without a pre-network guard

Rejected because systemd-networkd can activate pending candidate files before a post-boot runner
restores accepted state.

## Consequences

### Positive

- Accepted is the single recovery authority.
- Apply, retry, drift repair, and rollback share one reconciliation procedure.
- Ansible replaces rather than duplicates configuration-management behavior.
- The durable state and interruption model are small enough to inspect and operate manually.
- Network recovery preserves early-boot safety without a second success protocol.
- Large portions of the Phase 1-5 trust, transaction, health, publication, and network machinery
  become deletable after replacement proof.

### Negative and trade-offs

- Trusted repository content may execute as root; this design does not contain malicious promoted
  code.
- An interrupted candidate is conservatively rejected even if it might have been sound.
- A fetch outage with accepted and no pending reports candidate discovery unavailable, reconciles
  accepted immediately from its retained local bundle, and retries discovery on the next invocation.
- Irreversible effects require separate operational policy and are not automatically rolled back.
- The launcher's internal exact-export function and the separately ordered boot guard remain small
  custom privileged code that requires VM proof and operator recovery documentation; only the guard
  is a separate installed runtime component.

## References

- [ADR 0013: Last-Successful Ansible Reconciliation](0013-last-successful-ansible-reconciliation.md)
- [Spec 0028: Target Host Reconciliation Model](../specs/active/0028-target-host-reconciliation-model.md)
- [ADR 0003: GitOps Runner Responsibility Boundary](0003-gitops-runner-responsibility-boundary.md)
- [ADR 0004: Apply Execution Model](0004-apply-execution-model.md)
- [ADR 0010: Ansible Reconciliation Model](0010-ansible-reconciliation-model.md)
- [ADR 0011: Guarded systemd-networkd Convergence](0011-guarded-networkd-convergence.md)
