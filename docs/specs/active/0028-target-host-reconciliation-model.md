# Spec: Target Host Reconciliation Model

## Metadata

```yaml
id: SPEC-2026-028
title: Target Host Reconciliation Model
status: active
owner: moonpie
created: 2026-09-04
updated: 2026-10-19
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0003-gitops-runner-responsibility-boundary
  - 0004-apply-execution-model
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0013-last-successful-ansible-reconciliation
supersedes: SPEC-2026-012
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

Abhaile is a trusted, owner-operated, two-host homelab. The owner reviews and pushes repository
changes. The existing `abhaile` automation account polls the repository and runs reconciliation
locally. This migration replaces the legacy Python mutation backend with conventional Ansible; it
does not create a second release, trust, transaction, or configuration-management platform.

The existing account, clone, credentials, virtual environment, runner service and timer, host
lock, bootstrap path, and privilege model remain in place during migration. The legacy apply path
remains authoritative until the replacement proves parity on a disposable Debian VM and is
explicitly cut over.

```text
trusted desired commit in the existing clone
  -> deterministic unprivileged render
  -> manifest.json resource inventory
  -> dependency-ordered Ansible roles
  -> bounded local health checks
  -> atomic last-successful-commit update
```

Until the final update succeeds, the old `last-successful-commit` remains the sole automatic
recovery target.

## Goals

- Replace only mutation responsibilities already represented in `manifest.json`.
- Prefer normal Ansible roles, built-in modules, and handlers.
- Preserve deterministic unprivileged rendering and explicit privileged apply.
- Repair drift even when the desired commit has not changed.
- Recover interruption and failed candidates through the same reconciliation procedure.
- Keep network boot recovery local and small.
- Be materially smaller and easier to operate than both the Phase 1-5 prototype and continued
  extension of the legacy Python apply engine.

## Non-Goals

- Applying rendered software packages, downloads, builds, or command declarations.
- A protected mirror, second clone, immutable export store, capsule, copied runtime, renderer
  identity, generic operation compiler, or root launcher.
- Accepted/pending/rejected ledgers, transaction stages, replay graphs, health receipts, or a
  second last-known-good record.
- A separate network transaction controller, watchdog, peer protocol, or success definition.
- Containment against malicious reviewed content or a compromised automation account.
- Live-host enrollment, privilege replacement, or production cutover during implementation.

## Render and Inventory Boundary

All desired intent remains in `config/`. Phase 5.2 restores its Phase 0 authoring contracts.
Software declarations keep their original command-oriented form and are not redesigned for this
migration.

Rendering runs unprivileged from the selected trusted commit. It is deterministic and does not
depend on timestamps, ambient Git state, the current date, network access, or other external state.
`out/rendered/<host>/manifest.json` is the sole inventory for resource families managed by the
legacy apply path. `rendered/software/` remains deterministic output but is excluded from the
manifest and Ansible convergence.

Each selected manifest file entry binds a relative render path, absolute target path, artifact
kind, owner reference, SHA-256 digest, and size. Before mutation, Ansible verifies that the source
is a regular non-symlink file beneath the rendered root and matches its manifest identity. Each
resource-family role validates its own target, metadata, validator, activation, readiness, and
removal contract.

## Ansible Boundary

Roles are organized by resource family rather than a generic operation vocabulary. Families are
introduced in dependency order:

1. managed directories;
1. bootstrap-owned host identity and access inventory, reserved from ordinary reconciliation;
1. rootful systemd units, drop-ins, and resolved configuration;
1. ordinary service and Vault Agent configuration;
1. rootful and rootless Quadlets;
1. Caddy and CoreDNS configuration;
1. systemd-networkd configuration.

Roles consume entries already selected from the complete manifest. They may use fixed installed
validators such as `visudo`, `systemd-analyze`, and the Podman system generator. They do not
interpret arbitrary commands or operations. A custom module requires evidence that built-ins and
fixed commands cannot provide a necessary safety property.

Rootful unit validation treats ordinary systemd units and units generated from rootful Quadlets as
one dependency graph. A disposable preflight stages the complete desired ordinary-unit and
Quadlet inputs, runs the installed Podman system generator into disposable output directories,
and gives those outputs plus the ordinary units to `systemd-analyze verify`. Family roles retain
their publication and lifecycle responsibilities; they do not repeat isolated validators that
cannot resolve cross-family dependencies.

Rootful and named-user resources retain separate systemd managers and Podman contexts. Required
handlers complete synchronously and pass bounded local readiness checks. Runtime secrets remain
outside desired-state artifacts and rollback data.

Removal is family-specific. An obsolete resource may be removed automatically only when its live
identity still matches Abhaile's managed identity and the family permits reversible pruning.
Drifted, ambiguous, destructive, or irreversible cases stop for operator action.

The `abhaile` account definition, authorized keys, and sudo policy are enrollment/adoption
foundations. The manifest must contain only their fixed paths, but ordinary reconciliation neither
publishes nor removes them. Changing those foundations requires the explicit bootstrap/adoption
procedure and independent administrator checks.

## Runner State

Routine reconciliation reuses the existing runner directory and lock. Its only durable
reconciliation-authority facts are:

1. `last-successful-commit`: the exact commit that most recently passed convergence and health;
1. `current-run`: the candidate commit that crossed the first mutation boundary; and
1. `failed-target`: the existing suppression record for an unchanged failed candidate.

`current-run` is written atomically immediately before the first managed-state mutation. Rendering,
schema validation, read-only discovery, planning, and fixed validator checks occur before it.
`last-successful-commit` advances atomically only after convergence and required local health pass.
The marker clears only after it is proven equal to the durable last-successful value. No other
ledger or recovery authority is introduced.

The local clone retains the last-successful and interrupted candidate Git objects. Destructive Git
maintenance is outside routine reconciliation and must preserve both recovery inputs.

## Ordinary Reconciliation

Every run acquires the existing host lock and performs these steps:

1. If `current-run` differs from `last-successful-commit`, preserve that interrupted-candidate
   marker while rendering and reconciling the old last-successful revision. Clear exactly that
   marker only after recovery convergence and cleanup pass; an interrupted recovery retries with
   the same candidate identity.
1. If `current-run` equals `last-successful-commit`, verify that revision and clear the stale
   marker.
1. Fetch only to discover newer desired state. On fetch failure, reconcile last-successful locally
   when its Git objects exist.
1. If desired equals `failed-target`, reconcile last-successful for drift without retrying it.
1. Render and validate the selected desired revision.
1. Write `current-run` immediately before the first mutation.
1. Run dependency-ordered Ansible convergence and bounded local health.
1. On success, atomically update `last-successful-commit`, then clear matching marker and obsolete
   failed-target state.
1. On failure, record `failed-target`, reconcile the old last-successful revision once, and return
   failure even when recovery succeeds.

An unchanged desired revision is still reconciled to repair drift. Recovery is not a partial
inverse or replay: it is ordinary desired/current/reconcile with old last-successful as desired.
Without a last-successful revision, unattended mutation is forbidden. Fresh enrollment and
existing-host adoption explicitly establish the initial baseline only after the explicitly
authorized legacy apply succeeds. Bootstrap writes and verifies that first exact commit before it
enables runner scheduling; routine reconciliation cannot create the baseline.

## Candidate-Only Additions

Interrupted recovery compares the candidate and last-successful manifests. A candidate-only
resource may be removed only when its family supports removal, it is in a closed managed scope,
its live identity still matches the candidate, and removal is reversible. Missing or mismatched
evidence stops for operator action. Rootful candidate-only Quadlets stop their generated units,
recheck exact file identity, remove the files, and reload the system manager. Podman objects and
build outputs may remain as inert or irreversible residue. Candidate-only service directories,
network drop-in directories, and Caddy configuration files may remain as known inert residue after
the owning runtime has been removed or restored; they are not recursively pruned. This requires no
absent-before journal, execution graph, or per-operation rollback record.

## Health and Failure

Successful convergence plus its family-local runtime checks is the sole commit gate. Each direct
role owns only the checks needed for the resource it changed: systemd and user-manager activation,
declared Quadlet/container readiness, and fixed Caddy, CoreDNS, or Vault Agent readiness where
applicable. Phase 5.2 adds no parallel generic process, socket, unit, or container health engine.
After a networkd mutation, the canonical physical management interface must satisfy networkd's
online contract and the kernel's structured route lookup for the canonical services gateway must
select that exact interface and declared host source address. This proves locally coherent
management-path configuration, not gateway or end-to-end reachability. External, neighbour, and
cross-host observations are diagnostic only.

A failed candidate apply or family-local runtime check after the mutation marker triggers one
last-successful reconciliation. Failure before mutation rejects the candidate without an
unnecessary recovery pass. Failed or unknown recovery preserves evidence, reports degraded state,
and stops without recursion. Irreversible effects are never described as automatically rolled
back; software execution remains deferred.

## Network Boot Recovery

Networking uses the same last-successful rule. A small early mode of the existing runner is ordered
before `systemd-networkd.service`. Under the same host lock it reads local runner state. It exits
successfully without inspecting the checkout or toolchain unless `current-run` differs from
`last-successful-commit`. Only for that interrupted-mutation state does it render from retained
local Git objects, remove matching candidate-only network artifacts when safe, and apply the
last-successful network role.

Early mode does not fetch, advance success, run ordinary services, probe peers, or own another
timer, journal, watchdog, confirmation record, or rollback protocol. Ordinary reconciliation runs
after networkd without requiring `network-online.target`. Shared locking prevents races.

Recovery implementation changes use staged compatibility. A state-neutral revision containing the
runner, renderer, state, playbook, or recovery-role change must first become last-successful. Only
a later revision may depend on that new recovery behavior or introduce resources whose automatic
cleanup requires it. VM evidence must show accepted revision N recovering candidate N+1. A defect
already present in accepted recovery code is an explicit operator/console recovery case; Phase 5.2
does not add a second installed execution platform to repair it automatically.

## Migration and Proof

Apply remains dry-run by default and live mutation remains explicitly authorized. During Phase
5.2, `ansible/playbooks/converge.yml` stays fail-closed and legacy Python apply stays authoritative.

Direct roles are tested in isolation and on a disposable Debian 13 VM before receiving a production
caller. VM evidence covers drift repair, candidate success, apply and health failure recovery,
interruption around durable boundaries, candidate-only cleanup, fetch outage, reboot before
networkd, idempotence, and dry-run non-mutation.

Fresh bootstrap enables networkd and resolved as required foundations and fails if enablement
fails. Existing-host network-backend adoption is a separate, explicitly authorized operator
playbook, not a runner branch. It publishes networkd desired state, enables and starts networkd,
passes bounded local management-path acceptance, and only then disables `networking.service` for
the next boot. It does not stop the live legacy backend, remove ifupdown packages or hooks, alter
`/etc/network/interfaces{,.save}`, or change `/etc/resolv.conf`. Console access and a successful
reboot are required before adoption is complete.

Ordinary reconciliation refuses to perform implicit adoption while `networking.service` remains
enabled. Once adopted, it repairs networkd enablement and activation as ordinary service drift.
Early restoration publishes only last-successful network files and never manages service
enablement.

Existing-host adoption inventories actual account, SSH, sudo, clone, runtime, service, Podman, and
network state. Independent human administrative access and console recovery are proven before any
automation-account privilege change. No live host changes occur during implementation or proof.

Cutover requires a final complexity recount and go/no-go review proving material simplification.
Accepted specs and runbooks are then aligned, migration-only compatibility is removed, and legacy
apply is retained if the replacement fails that gate.

## Acceptance Criteria

- [x] Phase 1-5 trust, transaction, and guarded-network machinery is removed. Evidence:
  `PHASE_5_2_DISPOSITION.md` deletion inventory and reference scans.
- [x] Phase 0 config and software-schema contracts are restored; software remains render-only.
  Evidence: semantic comparison with `ea888fb` and deterministic dual-host renders.
- [x] Manifest v2, typed software operations, execution identities, and generic Ansible dispatch
  are removed. Evidence: deletion inventory and full-suite validation.
- [x] Manifest v1 has no timestamp and DNS validation has no ambient Git or clock dependency.
- [x] Direct roles cover each in-scope family with validation, publication, activation, readiness,
  and either proven safe removal or an explicit residue, forward-only, or maintenance boundary.
- [x] Rootful and rootless Quadlets are proven with target Podman/systemd versions. Evidence: an
  isolated Debian 13 VM fixture passed generator validation, non-mutating check mode, first live
  publication/activation, unchanged reconciliation, stopped-unit repair without republication,
  and active-container checks through both the system manager and the lingering `abhaile` user
  manager. A manual pod member was activated through its parent pod, remained unchanged on repeat,
  and was recreated by restarting that parent after only the member changed. Exact-hash rootful
  cleanup was check-safe, live, retry-safe, and left removed units without failed-state residue;
  all proof state and images were removed.
- [x] The runner implements local-first reconciliation, one marker, last-successful advancement,
  failed-target suppression, and bounded recovery.
- [x] Candidate-only cleanup is proven without a transaction journal or replay graph.
- [x] Pre-networkd last-successful restoration and non-racing ordering are proven.
- [x] Required VM scenarios pass and proof state is removed.
- [ ] Existing-host adoption and independent administrator checks are documented and proven.
- [x] Final code/state recount proves material simplification. Evidence: the reproducible recount in
  `PHASE_5_2_DISPOSITION.md` records material net deletion, removal of every prototype state
  family and custom Ansible module, and reduction of the reviewed model surface from 70
  dataclasses/12 enums/9 protocols to 1/0/0.
- [x] Accepted specs, ADRs, runbooks, and later phases contain no obsolete prototype behavior as
  current guidance. Evidence: ADR 0013 and this spec define the current model; accepted Spec 0008
  records deterministic timestamp-free manifest v1; architecture and apply references distinguish
  the deployed legacy backend from the migration path; Phases 6-8 use ordinary facts,
  last-successful recovery, and per-host one-writer cutover; superseded ADRs remain historical only.

## Decision Notes

- 2026-10-19: Legacy `--dry-run-validations` verifies changed systemd units by unit name against
  the complete rendered desired unit set prepended to systemd's normal manager-specific unit load
  path. It does not construct an empty alternate operating-system root or copy selected executable
  dependencies into one. The former model failed closed first on an absent runner executable and
  then on standard `sysinit.target`, proving that dependency-by-dependency staging was incomplete.
  The replacement retains native executable and installed-unit checks against the real host,
  includes unchanged desired peer units, preserves separate system and named-user contexts, and
  leaves publication untouched. Accepted Spec 0009 remains the deployed legacy reference until
  this active migration spec is accepted; its per-source validation description is not authority
  for the migration implementation.
- 2026-10-19: The one-time migration candidate intentionally replaces already-pushed Phase 1-4
  history and is therefore not a descendant of the deployed legacy revision. Existing-host proof
  binds exact reviewed legacy and candidate SHAs while scheduling is stopped; it does not weaken
  the routine runner's fast-forward-only rule. After successful proof and separate cutover
  approval, an administrator write credential promotes the exact candidate with
  `--force-with-lease` bound to the observed legacy remote tip, verifies the remote result, and
  explicitly aligns the stopped host's local `main`. The read-only host deploy key is not granted
  promotion authority. Refusal before promotion leaves the polled branch at the legacy revision.
- 2026-10-18: Final Phase 5.2 review preserved the interrupted candidate marker throughout
  last-successful recovery and clears it only after successful recovery, so interruption during
  recovery retains candidate-only cleanup authority. The pre-networkd no-op path now admits state
  with fixed shell checks before Python, Git, rendering, or Ansible. Fresh bootstrap and explicit
  existing-host adoption enable and verify the restore unit's effective networkd dependency only
  after a valid last-successful baseline exists.
- 2026-10-18: Existing-host proof uses an exact non-polled candidate under the shared lock while
  production scheduling remains stopped. An approved legacy apply establishes the candidate state
  before its exact SHA-only recovery baseline, recovery installation, network adoption, and direct
  Ansible proof. Acceptance promotes only that proven SHA; rejection restores exact legacy files,
  baseline, branch, units, and boot-network authority. Architect, SysAdmin, and Code Reviewer
  approved the resulting Phase 5.2 design and implementation with no remaining must-fix finding.
- 2026-10-08: ADR 0013 replaced the protected-bundle and accepted/pending/rejected design with the
  existing runner, last-successful commit, one mutation marker, and failed-target.
- 2026-10-10: Host identity and access artifacts remain bootstrap/adoption-owned foundations;
  ordinary reconciliation validates their fixed inventory but does not mutate them.
- 2026-10-10: Successful explicit bootstrap apply establishes the initial last-successful commit;
  routine runner execution continues to fail closed without that baseline.
- 2026-10-10: Candidate-only rootful Quadlet files receive bounded lifecycle cleanup, while known
  inactive directories/files and irreversible Podman/build effects may remain honest residue.
- 2026-10-10: Disposable-VM proof rejected ICMP response from the canonical gateway as a portable
  health invariant: Hyper-V provided a valid route and reachable neighbour while its gateway
  refused ICMP and external connectivity remained healthy. Phase 5.2 must select one bounded
  canonical management-path check without recreating configurable probe machinery.
- 2026-10-10: Disposable-VM recovery proved that last-successful reconciliation executes the
  retained revision's implementation as well as its desired state. Installation and cutover must
  therefore prove that the boot/runtime reader can execute every retained recovery revision across
  supported updates; a fix available only in a newer rejected candidate is not a recovery path.
- 2026-10-10: Network promotion validates only locally controlled management-path state: the
  canonical physical interface must be online and structured route lookup must select its declared
  source for the canonical gateway. ICMP, ARP, SSH, Internet, and peer reachability remain
  diagnostics rather than promotion authority.
- 2026-10-10: Pre-networkd restoration is required only when `current-run` differs from
  `last-successful-commit`; ordinary and stale-committed-marker boots must not depend on the Git
  checkout, renderer, virtual environment, or Ansible before networking starts.
- 2026-10-10: Recovery-affecting implementation changes use a state-neutral N then dependent N+1
  rollout. Accepted recovery defects require operator repair rather than another installed runtime.
- 2026-10-10: A disposable-VM reboot with valid static networkd files left `eth0` down because the
  legacy backend had been disabled while networkd was active but not enabled. Enabling networkd
  immediately restored the expected address and route; a second reboot returned automatically and
  proved restore-before-networkd ordering. Backend adoption is therefore an explicit one-time
  operator procedure. The recurring runner may repair an already adopted backend but must not
  autonomously replace an enabled legacy backend.
- 2026-10-11: Disposable-VM execution found that adoption initially reused change-triggered local
  acceptance and therefore skipped management-path checks when the network file was already
  correct. Explicit adoption now requires those checks independently of file drift. Candidate-bound
  check mode validated intent without mutation; ordinary reconciliation refused an enabled legacy
  backend; live adoption validated interface, source, and route before disabling it; a deliberate
  invalid source failed while retaining legacy enablement; a second live run was idempotent; and
  reboot returned automatically with restore-before-networkd ordering. VM-local revision
  `c4daabe` then reconciled unchanged and became last-successful before later dependence.
- 2026-10-11: With `c4daabe` retained as last-successful, disposable candidate `4c03693` supplied
  distinct live network bytes and an interruption marker across reboot. The early runner restored
  the accepted bytes before networkd started, while ordinary reconciliation subsequently cleared
  the marker without changing the last-successful revision. A deliberately root-owned proof marker
  first exercised the fail-closed console-repair path; real runner records remain owned by
  `abhaile`. Review of the completed flow removed an unnecessary second reconciliation when fetch
  selects the revision already reconciled during startup recovery.
- 2026-10-11: Disposable candidate `e342db8` added one inert candidate-only `.network` file.
  Early recovery classified its live identity against the retained candidate manifest, rechecked
  the exact hash immediately before removal, removed only that file in check/live proof, and did
  not invoke networkd. The VM remained on accepted `c4daabe`; focused repository tests, rather than
  the installed older runner, prove the subsequent duplicate-reconciliation optimization.
- 2026-10-12: A malformed disposable-VM `current-run` record made the enabled early restore
  oneshot fail with a concise domain error before Ansible while networkd remained active. Removing
  exactly the proof record restored a successful no-op. Focused integration coverage applies the
  same fail-closed contract to malformed last-successful authority. A separate real-systemd proof
  removed only a protected backup of last-successful while preserving a valid interruption marker:
  restore failed without mutation, retained the marker, created no authority, and left networkd
  active. Exact restoration removed all proof state and returned the oneshot to success.
- 2026-10-12: A disposable-VM runner invocation named a nonexistent remote without changing clone
  configuration. Fetch failed as intended, after which the runner rendered retained `c4daabe` from
  local Git objects and completed real Ansible check/live reconciliation unchanged. It returned
  success with last-successful unchanged, no current-run or failed-target, an active network, and a
  clean checkout.
- 2026-10-13: Check mode against the complete real Deimos manifest on the otherwise minimal proof
  host stopped before publication because native systemd validation could not resolve the generated
  `coredns-omada-build.service` or the installed `/usr/local/bin/coredns` output. Those are existing-
  host software/build prerequisites, not ordinary reconciliation outputs to synthesize or ignore.
  The run left no managed files, validation scratch, runner records, or network impact. Phase 6
  assessment must verify them before Deimos cutover; representative family proofs may install only
  explicit disposable fixtures and must not broaden the recurring runner into bootstrap.
- 2026-10-13: Review of the same blank-host boundary found that a new manifest-managed directory
  remained absent during check mode, causing a later built-in `copy` to fail before the live run
  that would create it. Ordinary service and Vault roles receive only the exact declared directory
  targets. Service files require their exact parent; Vault also models the immediate parent that
  native creation of an exact managed child directory will create, preserving its Phase 0 layout
  without adding config intent or managing new ancestor metadata. Check mode reports planned child
  publication without creating anything; unrelated, redirected, and non-directory parents remain
  fail-closed. Vault's fixed rootless Quadlet directory is similarly role-owned. Live mode retains
  normal directory-before-copy order; no staging filesystem or generic publication layer was added.
  Disposable-VM check mode subsequently passed both the real Deimos managed-build projection
  (`changed=1`) and complete Vault projection (`ok=48 changed=4 failed=0`), including the installed
  rootless Quadlet generator, without publication or runtime activation.
- 2026-10-13: Isolated live rootful and Vault-owned rootless Quadlets on Debian 13 passed check,
  first, unchanged, and stopped-unit repair runs against the installed Podman generators and real
  system/user managers. Exact-hash rootful candidate cleanup left systemd's removed generated unit
  in its failed set, so the role now performs the narrow native `systemctl reset-failed` operation
  after daemon reload; a cleanup retry was `changed=0` and left the unit
  `not-found/inactive/dead`. Rootless cleanup remains outside ordinary reconciliation as designed.
  Both Podman stores, all proof paths, units, containers, images, and scratch were then clean.
- 2026-10-13: A real rendered Deimos inventory invoked with expected host `phobos` exited before
  family selection with `changed=0`; only input validation, manifest loading, and the host-envelope
  assertion ran. Wrong-host inventory therefore cannot reach native validators or mutation roles.
- 2026-10-13: The runner intentionally records no execution phase between mutation-marker
  publication and success commit. A strengthened recovery test seeds candidate-managed effects
  with `current-run=candidate` and `last-successful=old`, then proves startup restores only old
  effects and authority, suppresses the candidate, and clears the marker. That identical durable
  state covers interruption during publication, after mutation, and after family readiness. The
  complementary matching-marker test covers interruption after last-successful advancement and
  before marker cleanup.
- 2026-10-13: Disposable Caddy proof showed that Ansible check mode skipped the role's read-only
  installed-container and native candidate-validation commands; they now use explicit
  `check_mode: false`. It also proved that atomic replacement of a single-file bind mount leaves
  the running container attached to the old inode: in-container reload succeeded but continued to
  serve baseline bytes. Changed Caddy publication now restarts its existing systemd-managed
  container to remount the new inode, then verifies active state. This uses ordinary lifecycle
  behavior and leaves unchanged runs untouched. The corrected VM run served the candidate, was
  `changed=0` on repeat, and rejected a correctly hashed invalid candidate before publication while
  preserving the live hash and response. All proof state was removed. Cleanup observation also
  refined rootful Quadlet failed-state clearing: the role now observes `ActiveState` after daemon
  reload, resets only units that remain `failed`, and skips missing units that are already
  `inactive`. This avoids treating systemd's generic status `1` for an unloaded unit as proof that
  no genuine failed-state residue exists elsewhere in the same cleanup batch.
- 2026-10-13: Isolated CoreDNS proof on Debian 13 passed non-mutating check mode, first live
  publication, unchanged reconciliation, and zone-only reload through the real system manager.
  The first run changed both the Corefile and zone, restarted CoreDNS, restored its path watcher,
  and changed the served answer from `192.0.2.10` to `192.0.2.20`; the repeat was `changed=0`.
  A zone-only candidate left the Corefile unchanged, used the installed reload path rather than a
  restart, restored the watcher, and served `192.0.2.30`. A separately sealed malformed zone passed
  manifest identity checks but failed native `named-checkzone` validation with `changed=0` before
  watcher shutdown or publication; the live hash, DNS answer, service, and watcher were unchanged.
  The disposable units, configuration, extracted validator/runtime binary, container image,
  listener, and proof bundles were then removed and verified absent.
- 2026-10-13: An isolated rootful Quadlet managed-build fixture on Debian 13 passed non-mutating
  check mode, first live build, and an unchanged `changed=0` rerun. The generated build oneshot
  completed successfully to `inactive/dead`, and an unchanged `.build` file plus a declared owner-
  configuration change reran the build, advanced the output-image label from `v1` to `v2`, and
  restarted its consumer. A second triggered build exercised the bounded post-build install unit,
  verified the resulting regular executable, advanced the image to `v3`, and left the consumer
  active. Exact teardown removed the generated unit, consumer and install fixtures, Quadlet,
  installed artifact, output and base images, containers, and proof bundle.
- 2026-10-14: An isolated manual pod-member fixture on Debian 13 passed non-mutating check mode,
  first live activation through its parent pod, and an unchanged `changed=0` rerun. Changing only
  the member Quadlet restarted the unchanged parent, recreated the member container, and exposed
  the new environment value. Exact-hash cleanup remained non-mutating in check mode and removed
  both files and runtime objects live. The first live cleanup exposed a race in using pre-removal
  unit state to decide whether to call `systemctl reset-failed`: generated units could unload
  between observation and cleanup, while a removed member could retain a real failed state. The
  role now observes `ActiveState` after daemon reload, resets only `failed` units, and skips
  `inactive` missing units. Absent retry, residue repair, and a fresh recreate-and-cleanup cycle all
  completed successfully; final units were `not-found/inactive/dead` with `Result=success`, and all
  Quadlets, Podman objects, images, and proof files were removed.
- 2026-10-15: Ordinary changed-revision reconciliation now renders last-successful once before the
  candidate and reuses the existing exact-identity removal classifier in the opposite direction.
  Supported resources present only in last-successful are passed to their existing direct cleanup
  roles; changed live bytes, unsafe path types, incomplete directory identity, unsupported family
  routing, and reserved resources fail during planning or Ansible check before the mutation marker.
  Unchanged drift reconciliation retains one render. Focused runner proof removes an
  identity-matched service file, rejects a drifted removal without invoking Ansible, and recreates
  the accepted file when later candidate work fails. No journal, removal ledger, generic operation,
  role, or custom module was added. Directories and Caddy candidate residue remain explicitly
  ignored only under their existing inert-residue policy; unsupported Vault/rootless, drop-in,
  persistent Podman-object, and other destructive removals remain fail-closed or maintenance-gated.
- 2026-10-17: A disposable Debian 13 real-systemd proof exercised forward removal through the
  runner rather than an isolated family playbook. An accepted active oneshot was removed from the
  next revision, exact last-successful identity authorized its cleanup, and last-successful advanced
  only after successful check/live convergence. A later candidate removed the restored accepted
  unit and then deliberately failed while activating a second syntactically valid unit. The runner
  returned failure, retained the prior accepted SHA, cleared `current-run`, removed the failed
  candidate, and recreated and reactivated the accepted unit. The first recovery left the removed
  failed service `not-found` but `failed/exit-code`; the rootful systemd role now observes removed
  units after daemon reload and calls fixed-argument `systemctl reset-failed` only for those still
  failed. Repeating the same failed revision finished with the removed candidate
  `not-found/inactive` and `Result=success`. This uses the same native systemd lifecycle already
  proven for Quadlets and adds no journal, dispatcher, or recovery state. Exact teardown removed
  both fixtures and every proof namespace; both units finished `not-found/inactive` with
  `Result=success`, networkd and SSH remained active on the DHCP address, and the production runner
  retained no `current-run` marker.
- 2026-10-08: Software declarations returned to Phase 0 and were deferred from this migration.
- 2026-10-09: Superseded architecture text was removed instead of retained behind an authority
  note.

## References

- [ADR 0013](../../adr/0013-last-successful-ansible-reconciliation.md)
- [Superseded Spec 0012](../superseded/0012-gitops-runner.md)
- [Phase 5.2 checklist](../../../TODO.md)
- [Phase 5.2 disposition](../../../PHASE_5_2_DISPOSITION.md)
