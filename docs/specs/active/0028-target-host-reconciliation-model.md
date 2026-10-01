# Spec: Target Host Reconciliation Model

## Metadata

```yaml
id: SPEC-2026-028
title: Target Host Reconciliation Model
status: active
owner: moonpie
created: 2026-09-04
updated: 2026-10-01
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0003-gitops-runner-responsibility-boundary
  - 0004-apply-execution-model
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0010-ansible-reconciliation-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

Abhaile's project-specific value is in its declarative configuration model, service composition, validation, and GitOps orchestration. Generic host convergence is a separate concern and is better implemented by established configuration tooling than by a custom mutation engine that duplicates ordinary system state management.

This spec defines the desired end state for the host reconciliation architecture. It is not a migration narrative. It is the target design that implementation work aligns to. Historical apply and drift specs remain useful as reference for the current implementation and compatibility constraints, but this document is the authoritative wanted position for the future architecture.

The desired model is:

```text
config/
   │
   ▼
abhaile-render
   │
   ├── resolve composition/includes
   ├── validate service and network intent
   ├── aggregate ingress, DNS, Vault, and Quadlet data
   ├── compute rendered manifest metadata
   └── emit deterministic host-scoped artifacts
   │
   ▼
rendered/
   │
   ▼
Ansible convergence
   │
   ├── packages and software prerequisites
   ├── users, groups, SSH, sudoers, permissions
   ├── systemd, networkd, and service files
   ├── Podman/Quadlet activation and validation
   ├── Caddy, CoreDNS, and Vault Agent handlers
   └── state ledger and safe-prune reporting
   │
   ▼
live host
```

The GitOps runner remains the outer reconciliation controller and owns candidate fetch and commit
selection, lock handling, health gating, and rollback. Only the root-owned updater's independent
fetch into the trusted mirror establishes whether a selected commit is admissible for privileged
convergence. The runner invokes preview render and the local convergence path, but it does not
become the host mutation engine or privileged trust authority.

This spec therefore defines the desired responsibility split rather than a migration sequence. Migration work is a separate execution plan that should reference this spec and preserve safety, rollback, and compatibility constraints during transition.

## Requirements

- [ ] Abhaile remains the source of declarative intent and the host-scoped compiler.
- [ ] Ansible becomes the authoritative local host convergence engine for generic system state.
- [ ] The rendered manifest remains the compatibility boundary between the compiler and the converger.
- [ ] Ansible consumes generated artifacts and manifest metadata without re-deriving service composition.
- [ ] The GitOps runner continues to own commit selection, health gating, and rollback semantics.
- [ ] Generic host mutation logic is delegated to Ansible roles and modules instead of custom Python executor classes.
- [ ] Systemd, networkd, Podman/Quadlet, Caddy, CoreDNS, Vault Agent, users, packages, and files are converged through Ansible-native primitives where practical.
- [ ] Rootless and rootful services remain distinct and supported without simplification to a single execution model.
- [ ] Destructive operations remain explicit, gated, and fail closed unless approval is granted.
- [ ] The applied-state ledger remains minimal and is used for safe-prune and recovery reporting, not as the primary drift engine.
- [ ] The design preserves the existing secrets boundary: runtime secrets stay out of the repo and rendered output.
- [ ] The design preserves host-local reconciliation without a central Ansible control plane.
- [ ] Fresh enrollment and adoption of an existing managed host use explicit, distinct lifecycle contracts.
- [ ] `abhaile-apply` remains the stable operator interface while its custom Python mutation backend and temporary `--ansible` selector are removed before this spec is accepted.
- [ ] The desired model is deterministic, idempotent, and safe to re-run against unchanged state.

## Constraints

### Responsibility Boundaries

Abhaile owns:

- declarative configuration in `config/`;
- host and service composition;
- render-time validation and aggregation;
- deterministic manifest generation;
- GitOps orchestration and rollback;
- host-local health gating.

Ansible owns:

- file creation and replacement;
- package and dependency state;
- users, groups, SSH, sudoers, and permissions;
- systemd activation and reload ordering;
- networkd state and interface changes;
- Podman Quadlet activation and lifecycle;
- Caddy, CoreDNS, Vault Agent, and similar service-specific convergence where they are system-management tasks.

### Local Host Execution

Ansible must run locally on the target host and must not introduce a central control-plane
dependency. SSH fan-out between hosts is explicitly out of scope.

The GitOps runner runs as the unprivileged `abhaile` service account. It selects a revision and
renders without privilege, then requests convergence through one root-owned launcher. The launcher
independently verifies that the requested revision is trusted and prepares a root-owned immutable
staging tree. Root executes `abhaile-apply` and Ansible only from that tree; it never executes
Python, Ansible, configuration, plugins, or templates from the service-account-writable checkout or
virtual environment.

The runner supplies a revision identifier, not root-executed repository content. The trusted
revision is verified against a root-owned bare mirror before staging. The staging tree, launcher,
Ansible configuration, privileged runtime dependencies, and sealed desired-state bundle are
root-owned and not writable by `abhaile`. The mirror and sealed last-known-good bundle support
rollback when the remote is unavailable.

The runner's sudo policy permits only the root-owned launcher with its fixed runner invocation. It
must not grant unrestricted `NOPASSWD:ALL`, execute an `abhaile`-writable entry point, or accept
caller-controlled manifest and output paths outside configured roots. Interactive operators use a
separate root invocation of the same validated interface; there is no supported direct
`ansible-playbook` invocation on a managed host. The play does not install or depend on its own
sudo permission during convergence.

System-level mutation runs in the root play context without repeated escalation. Rootless systemd
and Podman actions explicitly target the declared service user with its correct `HOME`,
`XDG_RUNTIME_DIR`, and user manager. Bootstrap runs as root only to establish initial trust and the
canonical entry point. Steady-state repository selection and preview rendering remain owned by
`abhaile`; the authoritative render used for privileged convergence runs as the restricted render
identity inside the trusted capsule workflow.

### Trusted Convergence Capsule

The privileged launcher binds the revision, source configuration, renderer, manifest, artifacts,
and Ansible content into one immutable convergence capsule:

1. Bootstrap provisions a root-owned bare mirror, pinned Git host keys, and a read-only fetch
   credential through an out-of-band or approved sealed-secret handoff. Secret material is never
   copied from the `abhaile` account, printed, or stored in the repository.
1. A root-owned updater fetches the configured remote and branch into the mirror. It rejects a
   non-fast-forward trusted-ref update unless an operator explicitly approves that event.
1. The launcher accepts only a host, full commit object ID, and constrained safety switches. It
   accepts an object ID only when it is reachable from the root-fetched trusted ref or is retained
   by the root-owned last-known-good ref.
1. The launcher exports the accepted revision from the mirror into a new root-owned staging tree.
   It does not copy source, Git metadata, Python environments, or generated data from the
   service-account checkout.
1. A dedicated non-login render identity reads the protected staged source and writes to a unique
   temporary output directory. It cannot write the source, mirror, launcher, final capsule,
   applied state, or live host targets.
1. After the renderer exits, root validates the manifest schema, host, paths, hashes, ownership
   metadata, and completeness. Root then removes render-identity write access and atomically seals
   the source revision and rendered output as one root-owned capsule.
1. Ansible runs from the sealed source and consumes only the sealed manifest and artifacts. Root
   never consumes a caller-writable desired-state bundle, even for dry-run.
1. The root-owned last-known-good ref and its sealed capsule are retained until a newer revision
   passes convergence and the runner health gate. Garbage collection must preserve the current
   trusted ref, last-known-good ref, active transaction, and configured rollback history.

Interactive convergence uses the same admission rules. A locally named branch, service-account
Git ref, or arbitrary object ID is not trusted merely because it exists. Updating the launcher,
updater, or trust policy is itself a privileged atomic installation from an already trusted
capsule and takes effect on a subsequent invocation, never midway through its own transaction.

### Host Lifecycle Contracts

Fresh enrollment and adoption of an existing managed host are separate operations. They share the
same final desired state and canonical apply entry point, but they do not share mutation
preconditions.

Fresh enrollment starts from the documented Debian baseline. Bootstrap may establish the service
account, repository checkout, prerequisite tooling, runtime directories, and initial trust handoff
before invoking render and the canonical local converger. It must still fail closed on conflicting
pre-existing identities or credential paths.

Existing-host adoption starts with read-only discovery while the legacy runner remains
authoritative. Discovery records the service-account identity and effective sudo policy;
repository revision, ownership, and SSH identity; rendered, applied, and runner state; rootless
user-manager and Podman state; active system and user units; Vault Agent readiness; and networkd
configuration. It classifies live state as:

- a prerequisite to preserve;
- legacy-managed state that the new converger can adopt;
- desired drift that is safe to reconcile;
- conflicting state requiring operator resolution; or
- obsolete state whose removal requires the applicable prune or destructive approval gate.

Adoption must not recreate identities, truncate SSH material, rewrite repository history, replace
sudo policy, restart networking, or remove legacy state merely because those actions are valid for
a fresh host. Mutation begins only after the discovery report has been reviewed and the relevant
apply gate has been explicitly approved. `deimos` is adopted and proven before `phobos`.

### Render Boundary

The renderer remains deterministic and unprivileged. The manifest remains the boundary between compiler output and host convergence. The authoring model in `config/` remains the source of truth.

### Runtime Independence

A converged host must continue booting and starting its services without requiring Ansible, GitOps, or an external control plane. Systemd and Podman are the runtime mechanisms, not Ansible.

### Security and Secret Boundaries

Ansible must not render runtime service secret payloads. Secrets remain handled by bootstrap trust and Vault Agent templates at runtime. Higher-privilege execution must be explicit and reviewed because the repository-defined Ansible content is executed with elevated privileges.

### Safety Model

Destructive operations remain explicit and reversible only by documented approval paths. No automatic deletion, network teardown, or Podman volume recreation occurs without an approval gate.

## Design

### 1. Desired Architecture

The long-term model is:

```text
config/
  ↓
abhaile-render
  ↓
rendered/manifest.json + rendered artifacts
  ↓
Ansible local convergence
  ↓
live host
```

The runner and privileged trust boundary sit outside that path:

```text
runner candidate fetch and selection
  -> root updater trust fetch and admission
    -> protected render -> apply/converge -> health -> success or rollback
```

Ansible does not replace the runner; it replaces the custom host mutation engine inside the apply stage.

### 2. Declared State and Manifest Contract

The rendered manifest remains the contract between Abhaile and Ansible. It contains enough metadata for deterministic file placement, validation hooks, owner grouping, and prerequisite ordering while avoiding duplicated service composition logic.

The manifest must continue to include at least the information needed for:

- file contents and target paths;
- owner and dependency metadata;
- validation and lifecycle hints;
- hash-based verification for file integrity;
- safe-prune and reporting logic.

The manifest is a compatibility boundary and should be treated as an explicit contract, not a private implementation detail.

Before owner-family migration begins, the manifest contract must be audited for every state family
Ansible will converge. The contract must define a schema version, trusted rendered root and target
path constraints, owner and action vocabulary, validation ownership, compatibility behavior, and
the metadata required for packages, users, directories, services, safe pruning, and state
reporting. Missing intent is added through renderer and schema changes, not reconstructed from
`config/` by Ansible roles.

#### Transitional Manifest v2 Contract

Phase 3 introduces `convergence-manifest.json` with integer `schema_version: 2`. The existing
`manifest.json` v1 remains unchanged and authoritative for the legacy Python apply path until
final cutover. Protected Ansible planning accepts only v2; it performs no version coercion or
v1-to-v2 inference inside the privileged boundary.

The v2 root contains exactly `schema_version`, `host`, `rendered_root`, `entries`, and `owners`.
`rendered_root` is the capsule-relative value `.`. Each ordinary artifact entry declares canonical
source and target paths; a closed kind/action pair; a declared owner and system or named-user execution context;
SHA-256 and byte size; complete file or software-operation metadata; validation ownership;
sorted lifecycle effects; and a safe-prune class. Owners declare a closed owner kind, context,
and sorted dependency list. An owner coordinating system publication and user-manager lifecycle
uses the explicit `orchestrator` context while every entry retains its concrete context.

Software entries have no synthetic `target_path`. Their metadata contains an exact copy of the
typed operation's explicit effects. Each effect names a collision namespace and effective target:
canonical allowlisted filesystem paths, systemd units, kernel modules, package/debconf state, or a
single-cardinality safe artifact set. Primary, backup, link, rule, declaration, activation, and
output effects participate in global collision detection against other software effects and
ordinary artifact targets. Root reparses the sealed YAML with the same closed typed parser used at
render time and requires exact agreement with manifest metadata; schema validation alone is not
trusted as privileged authorization.

Missing owners or dependencies, cycles, duplicate source or target paths, non-canonical paths,
unknown fields, versions, kinds, actions, contexts, validations, lifecycle effects, or prune
classes, incomplete kind-specific metadata, integrity mismatches, and unmanifested output all
fail closed. The only tree exceptions are the two manifest files and fixed empty software
category directories created by the renderer.

The action vocabulary is `publish`, `create`, `install`, `fetch`, `build`, and `ensure`. Kind
families cover systemd/resolved, identities, CoreDNS, Caddy, Vault Agent, networkd, Quadlet,
service files/directories, and `software.packages`, `software.download`, `software.build`, and
`software.prerequisite`. Software sources use enumerated operations with explicit parameters,
validation, and expected results. Free-form `commands` and generic shell or argv actions are not
part of the contract.

Protected planning topologically orders owners. The ready-owner queue uses the owner's lowest
entry phase and lexical owner name only as deterministic tie-breakers. Every owner's entries form
one contiguous block, sorted by typed phase and canonical target/source path within that block.
Consequently no phase preference can invert a declared dependency. An owner spanning multiple
phases is an explicit orchestration boundary: all of its steps complete, in internal phase order,
before a dependent owner begins. Missing dependencies and cycles are unreconcilable and fail
closed. Lifecycle values remain deferred handler boundaries; Phase 3 executes none of them.

### 3. Converger Responsibilities

Ansible is responsible for the runtime mechanics of desired state, including the following families where practical:

- file and directory management;
- user/group management and SSH/sudoers enforcement;
- package and software prerequisites;
- systemd activation and reload semantics;
- systemd-networkd convergence;
- Podman/Quadlet activation and lifecycle;
- Caddy validation and reload;
- CoreDNS validation and reload;
- Vault Agent configuration updates and restarts;
- safe-prune and drifted-removal reporting.

Ansible must prefer built-in modules and native task semantics over shell-based escape hatches except where the platform requires imperative commands.

### 4. Operational Ordering

The order of convergence must remain deterministic and safe. The target order is:

```text
preflight
  ↓
packages and prerequisites
  ↓
users, groups, directories, permissions
  ↓
managed files
  ↓
systemd daemon reload
  ↓
service-specific validation
  ↓
network and Quadlet infrastructure
  ↓
service activation and restart
  ↓
post-convergence validation
  ↓
state commit
```

Where later tasks depend on earlier reloads or restarts, Ansible must flush handlers at the required boundaries rather than delaying all restart behavior to the end of the play.

### 5. Destructive and Prune Safety

The target architecture preserves explicit destructive approval. Prune and destructive operations are considered high-risk and must remain gated by host-safe logic, not implicit convergence behavior.

The desired safety model is:

- safe removals are allowed only when live content matches the previous applied artifact or is already absent;
- drifted removals remain blocked unless explicit destructive approval is granted;
- network or volume recreation remains fail closed unless approval is present;
- state update occurs only after convergence succeeds.

### 6. Rootless and Host Environment Integrity

The target model preserves rootless systemd and rootless Podman behavior. The `abhaile` user manager must execute in the correct user context, with the expected `linger` and runtime directory behavior on Debian 13.

This is not a matter of implementation convenience; it is an operational and security requirement.

### 7. Health, State, and Rollback Integration

The runner remains the authority for health and rollback behavior. Ansible convergence is one step in the local reconciliation loop, not the entire GitOps contract.

The desired loop is:

```text
render -> converge -> health -> record success

on failure: rollback to last-known-good -> render -> converge -> health
```

Two ledgers record different facts:

- Apply state records the manifest that was successfully converged after its local validations.
- Runner state records the last-known-good revision only after the wider host health gate succeeds.

If wider health fails after apply state is committed, the runner retains its previous
last-known-good revision and reconverges that revision. The rollback plan compares the newly
recorded applied manifest with the last-known-good desired manifest, so it represents the state
actually present on the host rather than pretending the failed revision made no changes.

Rollback guarantees must be classified honestly. Managed file placement and unit activation may
be transactional. Downloaded images, completed builds, and package caches may be retained side
effects. Package upgrades, database schema changes, persistent-volume mutation, and external
service writes are not automatically reversible and require a documented backup, restore, or
maintenance strategy before approval.

This keeps Abhaile's operational recovery semantics intact even though the mutation engine has
changed.

### 8. Operational Safety Contracts

- Network changes require syntax and semantic validation, a root-owned pre-change snapshot,
  console or equivalent out-of-band access, a timed automatic revert mechanism, and reachability
  checks from the affected networks. Address, VLAN, route, and link deletion remain separately
  approved destructive actions.
- The active runner service is never stopped or restarted by its own convergence process. Runner
  and timer changes are validated and deferred until the current transaction succeeds, while the
  existing lock continues to prevent overlap.
- Secret-bearing tasks and paths use `no_log`, diff suppression, restricted temporary storage, and
  callback/error sanitization. Decrypted values must not enter Ansible facts, caches, JSON output,
  subprocess errors, or journald.
- Git host trust uses pinned, validated host keys established through bootstrap or another
  root-controlled trust path. `accept-new`, an empty `known_hosts`, or file existence alone is not
  proof of readiness.
- A cached runner-selected revision can converge and roll back without GitHub. Network checks are
  transaction-specific: fetch belongs to the runner, while package, image, and build connectivity
  is required only when the plan needs acquisition.
- Acceptance includes cold-boot and degraded-dependency tests for system units, rootless user
  units, Quadlets, Vault Agent, network-online behavior, the runner timer, and recovery after
  temporary Vault or network unavailability.

## Phase 3 Working-Tree Evidence

Phase 3 implements the compatibility and planning boundary without enabling convergence:

- `src/abhaile/renderers/convergence_manifest.py` emits deterministic v2 beside legacy v1.
- The software renderer, schema, and host declarations replace command bundles with typed,
  non-executable plans.
- `src/abhaile/trust/manifest.py` validates vocabulary, paths, ownership, dependencies,
  completeness, and integrity before sealing.
- `src/abhaile/trust/convergence.py` creates dependency-preserving owner blocks with deterministic
  phase/path ordering inside each block; both-host tests audit every real dependency edge.
- `src/abhaile/trust/ansible.py` accepts only verified capsule-internal manifest/artifact paths
  and remains non-executable.
- `src/abhaile/trust/transaction.py` models separate apply-state and runner-LKG gates, immutable
  commit evidence, rollback planning, and explicit rollback failure. `runner_update.py` binds the
  transaction, revision, capsule, manifest, staged unit pair, recovery record, and both ledger
  commits before publication can become eligible.
- Focused unit tests and both-host temporary real-render tests provide working-tree validation.

This evidence lacks the commit or PR reference required by governance, so acceptance criteria
remain open. Phase 4 must implement real Ansible consumption, convergence, local validation,
handlers, state I/O, publication, and rollback execution. Phase 5 must provide isolated and
wider-health evidence and workstation-account portability. Host adoption, installation, and
cutover remain in their existing later phases.

## Decision Notes

- Decision: Emit a strict deterministic convergence manifest v2 alongside the legacy v1 manifest
  during migration.

- Rationale: The legacy Python apply path must remain authoritative while protected Ansible
  planning needs a complete contract that rejects missing intent.

- Impact: v1 behavior is preserved; v2 is the only desired-state input to protected Ansible
  planning, and final single-manifest authority remains a cutover decision.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Replace software command bundles with typed declarative operations, expose every
  effective mutation target in manifest effects, and defer all
  package, network, download, build, service, and device effects.

- Rationale: A generic shell escape hatch cannot provide deterministic validation, ordering,
  integrity, or least-privilege semantics.

- Impact: Phase 3 renders and independently validates software plans and detects cross-family
  authority collisions. Phase 4 must implement each enumerated operation with bounded native task
  semantics before execution can be enabled. The gasket container build is explicitly
  `phase4-integrity-blocked`: its Git tag and OCI tag are not immutable admission evidence and
  must be replaced by an admitted commit/archive digest and OCI digest before implementation.

- ADR: null

- Decision: Represent apply state and runner last-known-good as separate transaction gates, with
  runner publication possible only after both commits and exact immutable publication evidence.

- Rationale: Local convergence records what is applied, while wider health determines recovery
  authority; neither claim may be falsified by later failure.

- Impact: Wider-health failure after apply commit plans rollback from the actual candidate
  manifest to the retained LKG manifest. Publication evidence binds the transaction ID, candidate
  revision, capsule digest, convergence-manifest digest, service/timer/recovery-record digests,
  apply-state commit evidence, and runner-LKG commit evidence. Mismatched, stale, or replayed
  evidence fails closed. Dry-run advances neither ledger and publishes nothing.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Validate and hash capsule trees through directory-file-descriptor-anchored,
  no-follow traversal, comparing file identity and metadata before and after each read.

- Rationale: Pathname checks followed by later pathname reads leave a replacement window in
  which a caller-controlled link or inode could cross the root trust boundary.

- Impact: Descriptor snapshots reject links, special files, hard-linked files, type changes, and
  files that change during an opened-descriptor read. Root materializes the validated snapshot as
  new inodes beneath a root-only parent. Renderer-held descriptors and surviving renderer children
  can therefore mutate only abandoned scratch inodes, never the sealed capsule.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Bind a trusted fetch to one canonical SSH URL host, user, and port and retain trusted,
  last-known-good, active-transaction, named-transaction, and bounded rollback-history objects
  through root-owned mirror refs.

- Rationale: Pinned key material is insufficient if the configured remote can select another
  transport or hostname, and object caching is not durable unless garbage collection has explicit
  protected roots.

- Impact: Production fetch rejects HTTP, local paths, shorthand URLs, aliases, and endpoint
  mismatches before invoking Git. Local remotes remain available only through an explicit test
  injection. An exclusive protected lock serializes fetch, capsule preparation, activation, ref
  rotation, and garbage collection. Named transaction refs, the active ref, last-known-good, and
  bounded distinct rollback refs protect required objects.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Derive sealed-capsule retention from valid revisions named by the protected trusted,
  last-known-good, active-transaction, named-transaction, and rollback refs, and collect only
  verified canonical capsules outside that set. The incoming fetch ref is not admitted
  capsule-retention authority.

- Rationale: Capsule age is not evidence that a revision is disposable. Trusted,
  last-known-good, active-transaction, named-transaction, and rollback refs are the root-owned
  authority for revisions that must remain available.

- Impact: Capsule garbage collection holds the exclusive trust lock, treats the host capsule
  directory as a closed fail-closed namespace, validates all candidates before deletion, and
  atomically quarantines collectible capsules before bounded removal. Dry-run never invokes this
  lifecycle operation.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Retain isolated `.render-orphan.*` scratch until a root-created process-containment
  boundary can prove that the complete renderer process tree is quiescent.

- Rationale: Return of the direct renderer process does not prove that descendants have exited or
  released writable descriptors. Elapsed time, PID disappearance, or a renderer-supplied boolean
  cannot establish that trust-boundary fact.

- Impact: Phase 1 preserves abandoned render scratch rather than deleting it unsafely. A later
  runtime-foundation task must provide root-verifiable process-group or cgroup containment before
  bounded orphan cleanup may be enabled.

- ADR: null

- Decision: Phase 1 validates the existing manifest v1 structural and security contract without
  defining Phase 3 convergence semantics.

- Rationale: Root must reject malformed ownership graphs, unknown artifact kinds, non-canonical or
  duplicate paths, incomplete output, and hash/type mismatches, but target-root allowlists and
  per-kind lifecycle behavior belong to the later manifest-contract audit.

- Impact: Every rendered file except `manifest.json` and necessary parent directories must have a
  manifest entry. Existing implicit `service:` and `unit:` owner references remain a narrow legacy
  vocabulary; all other owners must be declared. Current unmanifested `software/*` output is
  rejected fail closed until Phase 3 defines its artifact kinds and convergence semantics.

- ADR: null

- Decision: Existing-host discovery uses typed, injected read-only observations and emits only
  sanitized classifications, reasons, and provenance.

- Rationale: Identity, sudo, repository/SSH, state, runtime, unit, Vault, and network evidence have
  different ambiguity and secrecy risks; category-labelled path existence is insufficient.

- Impact: Unavailable, malformed, ambiguous, or relationship-mismatched evidence is a conflict.
  Fixed collectors accept only catalogued command and metadata requests, use bounded shell-free
  execution, and emit no raw evidence. Phase 1 covers metadata-level prerequisites; active
  rootless runtime, Podman, user-manager, unit, and generated-Quadlet observation follows the
  Phase 2 runtime transport design. Repository tests use synthetic backends only. Actual host
  reports remain later explicitly authorized adoption gates.

- ADR: null

- Decision: During scaffold quarantine, offline Phase 1 evidence covers admission, protected
  render, sealed capsule verification, and preflight selection; it does not claim host convergence.

- Rationale: Claiming actual offline convergence would contradict the unconditional `--ansible`
  rejection and fail-closed Ansible play required until manifest convergence is ready.

- Impact: Actual offline host convergence remains a later cutover gate. Phase 1 does not weaken
  quarantine merely to satisfy that future operational proof.

- ADR: null

- Decision: Constrained sudo cutover stages and syntax-checks both artifacts, activates the
  root-owned launcher first, exercises the exact offline dry-run invocation, and only then
  activates and revalidates the constrained policy while retaining the legacy recovery rule.

- Rationale: Enabling sudo before proving its only permitted launcher command creates a remote
  lockout hazard.

- Impact: The repository provides injectable planning and candidate artifacts, but live policy
  installation and legacy-policy removal remain explicit host gates outside this session.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Protected rendering uses the fixed root-policy interpreter in isolated mode, inserts
  only the admitted capsule's `src/` directory as the application import root, and passes the
  transaction root through the renderer's existing output override.

- Rationale: The interpreter and dependency environment must be protected independently, while
  the renderer implementation and configuration must come from the same admitted revision as the
  capsule. A caller-selected checkout or an installed copy of Abhaile cannot satisfy that binding.

- Impact: Capsule preparation keeps the exported source root-owned and read-only, temporarily
  assigns only isolated scratch to the configured render identity, snapshots the validated tree,
  and materializes fresh root-owned inodes for sealing. Renderer-owned scratch remains quarantined
  until independently proven quiescent cleanup. The renderer CLI does not gain a caller-controlled
  repository-root option.

- ADR: null

- Decision: During Phase 2 quarantine, the protected Ansible argv's explicit `-i localhost,`
  argument is the sole inventory authority. The closed environment enables only the builtin
  `host_list` inventory plugin, fixes the default stdout callback, and supplies neither an ambient
  inventory variable nor an enabled-callback list.

- Rationale: An INI `inventory = localhost,` value is interpreted as inventory paths and does not
  establish the intended inline localhost inventory. The fixed launcher argument is effective,
  independently testable, and cannot be replaced by caller environment or Ansible defaults.

- Impact: Effective-config and inventory-loader integration tests prove ambient inventory and
  callback variables are excluded and that the only resolved inventory host is `localhost`.
  Ansible execution remains disabled until the later manifest and convergence phases.

- ADR: null

- Decision: Dry-run may refresh the root-owned trusted mirror and populate the sealed capsule
  cache, but it may not activate a capsule, update apply or runner last-known-good state, install
  policy, run garbage collection, or mutate managed host state.

- Rationale: Independent trust fetch and protected rendering are prerequisites for a useful
  preview, while state activation and retention changes imply convergence success that dry-run
  cannot establish.

- Impact: Online dry-run can warm protected rollback inputs. Offline dry-run accepts only an
  already admitted trusted or retained last-known-good revision and its cached objects.

- ADR: null

- Decision: Use this spec as the durable implementation authority for the final host
  reconciliation model; keep the temporary host-by-host migration sequence in `TODO.md`.

- Rationale: The accepted specification set should describe the supported final implementation,
  while `TODO.md` is the repository's temporary execution tracker.

- Impact: This spec remains active until Ansible convergence is complete, the obsolete custom
  mutation path is removed, affected specs and ADRs are reconciled, and every acceptance criterion
  has implementation and validation evidence.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Treat fresh enrollment and existing-host adoption as distinct lifecycle contracts.

- Rationale: Both deployed hosts already contain legacy-managed identities, credentials, runtime
  state, and services. Treating them as blank hosts can destroy required state or make convergence
  depend on accidental live-host conditions.

- Impact: Existing-host migration requires a reviewed discovery and classification report before
  mutation; fresh-only initialization tasks cannot run implicitly during adoption.

- ADR: null

- Decision: Use a root-owned launcher and immutable root-owned staging tree as the privilege and
  code-trust boundary between the unprivileged runner and root-local Ansible convergence.

- Rationale: Restricting sudo to an entry point owned by `abhaile` does not provide least privilege,
  because a compromised service account could replace the Python or Ansible code that root runs.

- Impact: Direct `ansible-playbook` execution is unsupported on managed hosts. The privileged
  launcher independently verifies and stages trusted revisions, constrains paths and flags, and
  replaces unrestricted sudo only after the new invocation and a recovery path are proven.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Bind trusted source and rendered desired state into one root-owned immutable
  convergence capsule.

- Rationale: Protecting executable code alone is insufficient when a caller can alter the manifest
  and artifacts that authorize privileged file, identity, service, and network changes.

- Impact: A root-owned mirror admits revisions, a restricted render identity produces temporary
  output from protected source, root validates and seals that output, and Ansible consumes only the
  sealed capsule. Last-known-good source and output remain available offline.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Keep apply state and runner last-known-good state as separate ledgers with separate
  commit gates.

- Rationale: Successful convergence records what is actually on the host, while wider health
  determines whether the selected revision is safe for future runner recovery.

- Impact: Health failure after convergence leaves apply state at the failed revision, retains the
  prior runner last-known-good revision, and plans rollback from the actual applied state.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Defer superseding Specs 0008 and 0009 until Spec 0028 is accepted at final cutover.

- Rationale: Those specs continue to govern the live Python apply path during migration; declaring
  them superseded now would leave current production behavior without an unambiguous authority.

- Impact: At acceptance, update both specs atomically to `superseded`, reconcile Specs 0012 and
  0014, and audit ADRs 0002 and 0004 against the final implementation.

- ADR: null

- Decision: Abhaile is the declarative compiler and orchestration layer; Ansible is the local convergence engine.

- Rationale: This separates project-specific intent from generic system-state management and keeps the design aligned with the repository's architecture and operational constraints.

- Impact: The legacy custom apply engine becomes a compatibility implementation detail rather than the desired long-term architecture.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: The rendered manifest remains the compatibility boundary between compiler output and host convergence.

- Rationale: This preserves the deterministic render contract while allowing the host mutation implementation to evolve without rewriting service composition logic.

- Impact: Implementation may change underneath the boundary without changing the declarative authoring model or render contract.

- ADR: null

- Decision: The runner remains responsible for health and rollback semantics.

- Rationale: These are GitOps and system recovery responsibilities, not host mutation responsibilities.

- Impact: Ansible can converge state without owning the repository-level safety model.

- ADR: null

- Decision: The applied-state ledger remains minimal and transitional.

- Rationale: It is needed for safe prune reporting and recovery diagnostics, but it is not the primary drift engine.

- Impact: The health of the host is judged against desired vs live state, not primarily against an old applied manifest.

- ADR: null

- Decision: Anchor production trust paths to fixed root-owned namespaces: repository and capsule
  state beneath `/var/lib/abhaile`, Git pins and fetch identity beneath `/etc/abhaile`, and protected
  runtimes beneath `/usr/lib`. Validate every path component from the filesystem root. Policy may
  select descendants only within those namespaces; synthetic roots remain constructor-only test
  seams.

- Rationale: The mirror and credential paths intentionally have different parents. A common
  policy-selected ancestor either rejects the production layout or turns policy into trust-root
  authority.

- Impact: Production fetch supports the intended split layout without accepting caller-controlled
  anchors. Local remotes remain an explicit test injection.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Contain each protected renderer in a root-created, nondelegated cgroup v2 boundary,
  attach before the PAM-free UID/GID transition, terminate surviving descendants, and require
  kernel-observed `populated=0` before snapshot validation or sealing.

- Rationale: Callback return, one PID, elapsed time, and process groups cannot prove that the
  complete renderer process tree released writable access.

- Impact: New scratch receives a root-owned, boot-bound cgroup receipt after quiescence proof.
  Explicit non-dry-run cleanup removes only canonical receipt-associated scratch and its exact
  empty cgroup in bounded, retry-safe batches. Retirement intent is durable before kernel evidence
  is removed; failed renders retain receipt-backed scratch when quiescence is proven. Legacy,
  reboot-invalidated, malformed, populated, or ambiguous evidence is retained. Debian 13.7 checks
  on both target hosts confirmed the required kernel operations and ancestor nondelegation; the
  installed dedicated-identity chain remains a later host-adoption gate. Child creation records
  its inode before control validation and removes only that exact protected child if validation
  fails before any process can attach. A proven rollback also removes the associated failed setup
  scratch; identity or ownership ambiguity preserves the boundary and fails closed.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Active runtime discovery uses only fixed injected observations over an already-existing
  PAM-free user runtime transport. It does not invoke local Podman while a query could initialize
  storage or activate a socket.

- Rationale: Existing-host adoption starts with observation, and supposedly read-only client
  commands may create precisely the runtime state being assessed.

- Impact: Missing user-runtime prerequisites and unavailable Podman transport classify as sanitized
  conflicts. A typed terminal capability blocker performs no filesystem, socket, process, retry, or
  initialization fallback. Positive non-initializing Podman transport evidence remains a migration
  evidence gate; actual host collection remains in Phases 6 and 7 and convergence remains Phase 4.

- ADR: null

## Phase 4 Repository Evidence

Phase 4 implements production convergence mechanics; Phase 5 proves those same mechanics in
authorized disposable environments. The protected planner turns an independently validated sealed
v2 manifest into a dependency-ordered data-only operation list. One production role performs a
complete validation pass before its mutation pass. There is no test-only convergence copy. Its
temporary execution gate admits only the explicit `isolated-disposable-v1` scope beneath a
canonical `/tmp` root. The protected production plan does not emit that scope, `--ansible` remains
rejected, and the privileged launcher remains non-executable for convergence.

The current closed mapping is:

| Manifest family | Admitted operation | Phase 4 status |
| --- | --- | --- |
| `service.directory` / `create` | `directory` | Capsule-shipped descriptor-bound publisher maps the absolute manifest namespace beneath an injected root, retains no-follow ancestry, and applies exact numeric ownership/mode with truthful check and idempotence behavior |
| ordinary and validated file families / `publish` | `publish` | Sealed source digest/type is preflighted; a fixed validator vocabulary runs before descriptor-bound atomic publication; Caddy and CoreDNS Corefile use the closed offline structural validators described below |
| `systemd.unit`, Quadlet, and lifecycle-bearing publication | `publish`, `lifecycle` | Effects are coalesced once per owner and execution context; only changed owner-context pairs reload/restart; named-user effects require exact protected observations and use PAM-free `setpriv` transport |
| `software.packages` and host-global prerequisites | `packages`, `systemd-units`, `unattended-upgrades`, `udev-rule` | Native modules or fixed argv are defined behind a separate protected host-global-isolation gate; Phase 5 must prove package availability/check-mode and real platform behavior |
| sysusers and sudoers | `publish`, `sudo-candidate` | Sysusers validates, publishes, and activates through fixed root-aware argv; sudoers validates and stages only at the protected candidate path, never the live policy target |
| resolved, Quadlet, Vault Agent, CoreDNS zone | `publish`, `lifecycle` | Fixed validation/publication mechanics are present; named-user variants require exact protected observation authority before PAM-free execution |
| Caddy and CoreDNS Corefile | `publish`, `lifecycle` | Capsule-internal bytes first pass closed renderer grammars covering UTF-8, nesting, directive placement, arity, bounded values, blocks, and safe named imports without starting a service; publication and changed-owner effects then use the same descriptor-safe path. Phase 5 proves compatibility with exact installed binaries/plugins and fails adoption rather than broadening the grammar |
| immutable binary/archive download / `fetch` | `binary-download`, `archive-download` | HTTPS origin/redirect/byte/archive-digest/extracted-output-digest authority and archive member/count/type/traversal/encryption/expansion bounds precede descriptor-safe atomic publication; an exact local target skips acquisition and check mode never acquires |
| kernel modules / `ensure` | `kernel-modules` | Modules-load and modprobe fragments publish descriptor-safely; absent modules load only through fixed `/usr/sbin/modprobe --` argv behind host-global isolation |
| resolver/network backend / `ensure` | none | Rejected as network-affecting operations |
| container build / `build` | none | Fails closed because the current source ref and OCI base tag are not immutable root-verifiable inputs |
| networkd publication/effects | none | Fails closed before mutation; only the separate repository recovery state machine exists |
| named-user operations | lifecycle only with sealed `execution_identity` | The exact common envelope contains no derived identity flag: `context` and `execution_identity` are a biconditional authority. Manifest v2 supplies exact name, UID, GID, HOME, and shell values; manager effects require matching protected linger, manager, runtime-directory, and bus observations plus fixed PAM-free transport. Rootless Quadlets publish as root beneath `/etc/containers/systemd/users/<sealed-uid>/`; other publication beneath named-user-writable ancestry remains rejected. |

Repository-safe slices additionally cover a versioned transaction-derived apply-state rotation
journal, no-follow identity-aware prune classification and authorized descriptor-relative removal,
distinct prune/destructive/network/volume gates, transaction-gated runner pair publication with
retained prior bytes and metadata, and a transaction- and digest-bound network snapshot/candidate
journal.
Private runner evidence metadata and content are validated through the same no-follow descriptor.
State interruption recovery deterministically completes the authorized current/previous/history
tuple under injected roots. Runner recovery reauthorizes exact apply/LKG and lock evidence,
restores the prior pair on pre-reload ambiguity, and permits a repeated timer rearm only through an
explicit idempotence contract. Initial runner candidate staging writes transaction-bound
initialization authority first, assembles and fsyncs the exact candidate pair, recovery record, and
staging identity in a private sibling, then atomically publishes the complete directory. Exact
retries finish forward; malformed, linked, unsafe, or transaction-mismatched retained state fails
closed without deletion. None of this invokes a real system manager or networking.
All sealed candidate content and fixed external validators run in the first pass before the first
mutation. The protected production coordinator persists network recovery authority before any separate
network executor, executes only exactly authorized prunes before local apply-state commit,
advances runner LKG only after wider health, binds rollback convergence to the protected prior
revision/capsule/manifest before rotating apply state, and publishes runner units only after both
ledger commits. One protected coordinator entry point holds a descriptor-safe process lock across
network-recovery preparation, convergence, apply-state commit, protected health-result
verification, runner-LKG promotion, and optional runner publication. Health success is derived
from a no-follow ownership/mode-checked persisted result whose closed observations are bound to an
unpredictable challenge created only after apply-state commit and to the exact transaction and apply
evidence, not from a caller boolean, callback, or predated result. The current apply-state record,
protected retained applied state, and mirror LKG ref are re-read under the same lock immediately
before promotion or rollback planning. Runner-LKG
advancement persists a protected promotion journal, compare-and-swap rotates and verifies the
admitted mirror ref, atomically persists a candidate/retained-revision/manifest/health-bound
receipt, and removes the journal only after directory fsync. Recovery finishes forward only when
the ref is the exact prior or candidate revision. Runner publication and recovery require a
verifier-issued in-process authority after re-reading the receipt and ref, and bind its receipt
digest into publication evidence. Phase 5 is reserved for proving this integrated path in an
authorized disposable environment.

Focused tests exercise production role gate rejection, complete preflight, ordinary publication
check mode, first change, unchanged rerun, path/symlink rejection, compiler exhaustiveness, bounded
download/archive behavior, and the repository state/recovery mechanics. This is proportionate
Phase 4 implementation testing, not the broad isolated evidence assigned to Phase 5. Phase 5 owns
installed-binary compatibility and broad behavioral proof only after a family is admitted. Phases
6 and 7 own installed runtime, sudo-policy installation, host adoption, canary, live network proof,
publication activation, and cutover.

## Phase 4 Decision Notes

- Decision: A restart lifecycle is executable authority only when manifest v2 carries an exact
  renderer-owned unit, authority owner, execution context, and bounded `restart` or `try-restart`
  mode. The requesting owner must declare the same authority, and a corresponding managed unit or
  explicit owner-level external-unit authority must resolve without ambiguity.

- Rationale: A bare `service-restart` effect would require the privileged converger to infer a
  target from an owner, task name, or path. `manual` Quadlet policy means no immediate restart and
  must not be translated into a restart request.

- Impact: Unknown, unmanaged, cross-owner, cross-context, identity-mismatched, or runner-self
  restart targets fail before mutation. `manual` authorizes no automatic action. The strict v2
  shape was completed in place because it has no adopted executable consumer; no new ADR is
  required under ADR 0010's existing trust boundary.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Rootless Quadlet publication uses Podman's root-owned per-UID search path
  `/etc/containers/systemd/users/<sealed-uid>/`, while activation still occurs through the sealed
  named-user manager context.

- Rationale: Publishing through a directory writable by the target user creates an unavoidable
  pathname replacement race for a privileged publisher. Podman's system-wide per-UID Quadlet
  search path separates root-owned publication from user-manager activation.

- Impact: Manifest v2 rewrites only rootless Quadlet targets and ownership; legacy manifest v1 is
  unchanged. Bootstrap/adoption must establish and verify the root-owned ancestry. Any other
  named-user-writable publication target remains fail closed.

- ADR: null

- Decision: Caddy, CoreDNS Corefile, and resolved candidates use sealed-input project parsers for
  the complete renderer-owned grammar, including bounded size, UTF-8 and NUL checks, nesting,
  directive placement and arity, bounded values, and safe Caddy named imports. Every content and
  fixed external validator runs during the global pre-mutation pass.

- Rationale: CoreDNS exposes no accepted non-starting configuration-check interface, and invoking
  a service merely to validate a candidate violates the pre-publication boundary. The checked-in
  configuration vocabulary is finite and renderer-owned.

- Impact: Unknown or misplaced directives, invalid arity/values, and unsafe imports fail before
  any publication or handler. Phase 5 must
  prove the closed parser accepts the exact rendered configurations and agrees with installed
  Caddy/CoreDNS/plugin behavior in a disposable environment; installed incompatibility blocks
  adoption rather than weakening validation.

- ADR: null

- Decision: Desired-state identity is not transaction replay identity. A fresh transaction may
  reconcile the same revision, capsule, and manifest; only a reused transaction ID, reused apply
  commit evidence, fabricated evidence, or mismatched interrupted transaction is replay.

- Rationale: Current-revision drift repair, post-reboot repair, and retry after interruption must
  not require a false desired revision change.

- Impact: A successful no-op and a successful same-revision drift repair each append one truthful,
  bounded chronological transaction record while retaining the same desired-state identity and
  recording `no-op` or `changed` convergence outcome. Non-expiring opaque replay markers are
  independent of bounded diagnostic history. Dry-run advances nothing. Apply state remains
  distinct from runner LKG.

- ADR: null

- Decision: Initial network recovery state is assembled and fsynced in a private transaction
  directory, binding transaction, snapshot, candidate, deletion approval, and recovery token,
  then atomically published beneath an already protected parent.

- Rationale: Publishing the final directory before its journal makes both retry and recovery
  ambiguous after interruption.

- Impact: Failure injection around every durable initialization transition permits deterministic
  retry or finish-forward. Existing links, malformed state, unsafe metadata, and identity mismatch
  fail closed without deletion. No network command, timer, or reachability test is implemented by
  this repository state machine.

- ADR: null

- Decision: Bootstrap and adoption own credentials, trust runtimes, identities, linger, runtime
  namespaces, and sudo installation; ordinary convergence verifies these prerequisites and does
  not recreate or overwrite them opportunistically.

- Rationale: Both hosts contain existing state, and credential or identity replacement cannot be
  made safe by treating adoption as fresh enrollment.

- Impact: The deterministic prerequisite graph records preservation and later live-proof phases.
  Sudo publication, installed runtime proof, and credential handling remain Phases 6 and 7.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Applied-state, safe-prune, runner publication, and network recovery must use closed,
  transaction-bound repository mechanics before any executable integration is admitted.

- Rationale: Crash recovery and destructive authority must be testable independently of Ansible
  task execution and cannot be reconstructed after a partial mutation.

- Impact: The repository slices now implement crash-coherent finish-forward state rotation,
  descriptor-relative prune identity, exact apply/LKG/lock-bound runner pair recovery, and a
  protected transaction-bound network snapshot/candidate journal. They do not prove actual
  rollback convergence, real system-manager reload/rearm behavior, an independently armed network
  revert, typed affected-network reachability, or reboot recovery. Those behavioral gates remain
  Phase 5; irreversible package/build/external effects are not claimed reversible.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

- Decision: Named-user execution authority is renderer-owned manifest data, not a value inferred
  from task names, target paths, or the executor account database.

- Rationale: UID, GID, HOME, and shell are security-relevant inputs, while linger, runtime
  directory, user bus, and manager availability are protected runtime observations.

- Impact: Manifest v2 seals exact name/UID/GID/HOME/shell values and the compiler carries them
  unchanged. The common operation envelope deliberately omits the redundant
  `runtime_identity_required` flag: named-user context exists if and only if the exact sealed
  execution identity exists. Production-role preflight compares it with protected linger,
  manager, UID-bound runtime-directory, and UID-bound bus observations before any mutation.
  Phase 5 proves the integrated observation transport; installed proof remains Phases 6/7.

- ADR: null

- Decision: Runner last-known-good promotion is a separate durable commit protocol rather than an
  in-memory transaction-stage transition.

- Rationale: Runner-unit publication must not be authorized by a caller assertion or by evidence
  derived before the protected mirror and runner ledger durably agree.

- Impact: Under one protected coordinator lock, the coordinator verifies exact durable apply
  state, creates and fsyncs an unpredictable post-apply challenge, boundedly awaits and validates a
  protected challenge/transaction/apply-bound health result, re-verifies candidate apply state and
  the retained mirror/applied-state authority, writes and fsyncs a promotion journal,
  compare-and-swap
  advances and verifies the protected mirror LKG ref, and atomically writes a separate
  candidate/retained/health-bound runner-LKG receipt before returning commit evidence. Apply and
  runner evidence also bind the retained revision and manifest. Interruption retries finish
  forward from the exact prior/candidate states; third-state, mismatched, stale, fabricated, or
  caller-boolean authority fails closed. Health failure retains the prior LKG and plans recovery
  from the actual applied candidate. When candidate and retained desired identities are equal, the
  result is an explicit same-desired-state recovery plan rather than a fictitious revision
  rollback. Same-revision promotion treats the already-equal ref as satisfied and never repeats CAS
  during recovery. Publication and recovery require verifier-issued durable authority and include
  the receipt digest in their evidence.

  Wider-health evidence has an explicit protected lifecycle. A single active journal binds the
  unpredictable challenge and exact transaction/revision/capsule/manifest/apply identity. Its
  result is immutable once published. A successful result remains active until the runner-LKG
  receipt and admitted mirror ref are both durable and re-verified; only then is a
  transaction-scoped `promoted` terminal record written and fsynced before active evidence is
  cleared. A failed result advances to `failed-awaiting-rollback` and blocks every unrelated
  transaction until the exact retained-state rollback apply record is durable. The rollback
  coordinator then writes a transaction-scoped `rollback-completed` terminal record before
  clearing active evidence. If interrupted after either terminal write, recovery re-verifies the
  runner receipt/ref or rollback apply record and finishes cleanup; terminal presence alone is not
  authority. Exact retries are idempotent, while a fresh transaction at the same desired revision
  remains distinct through transaction and apply evidence. Stale, mismatched, malformed, or
  unowned challenge/result/terminal state fails closed and is not blindly deleted.

- ADR: [docs/adr/0010-ansible-reconciliation-model.md](../../adr/0010-ansible-reconciliation-model.md)

## Acceptance Criteria

- [ ] The target architecture is documented as Abhaile compiler/orchestrator + Ansible local converger.
- [ ] The rendered manifest is defined as the explicit compatibility boundary between render and converge.
- [ ] The source-of-truth and trust boundaries remain explicit: config remains authoritative; runtime secrets remain outside repository-managed rendered output.
- [ ] Ansible local convergence is documented as host-local and not requiring a central control plane.
- [ ] Fresh enrollment and existing-host adoption have distinct, testable preconditions, preservation rules, and mutation gates.
- [ ] Root executes only independently verified repository content and consumes only a sealed desired-state bundle from one immutable root-owned convergence capsule.
- [ ] Revision admission uses a root-owned mirror, pinned Git host keys, non-fast-forward protection, retained last-known-good refs, and offline-capable object retention.
- [ ] Protected rendering uses a restricted non-login identity and proves that manifest tampering or render-to-apply time-of-check/time-of-use attacks cannot cross the root boundary.
- [ ] The runner contract remains the authoritative GitOps health and rollback model.
- [ ] Apply state and runner last-known-good state have distinct commit gates, and health-failure rollback is proven against the actual applied manifest.
- [ ] Rootless and rootful service execution semantics remain explicit operational requirements.
- [ ] Destructive operations remain fail-closed without explicit approval.
- [ ] State ledger semantics remain minimal and are defined as safe-prune/reporting support rather than the primary drift engine.
- [ ] The design remains deterministic and idempotent for repeated convergence runs.
- [ ] Network recovery, runner self-management, secret redaction, pinned Git host trust, offline rollback, rollback limits, and cold-boot recovery are tested and documented.
- [ ] Both `deimos` and `phobos` pass adoption, convergence, idempotence, health, rollback, and reboot gates.
- [ ] `abhaile-apply` is the sole production interface, backed by Ansible without the temporary `--ansible` selector or custom Python mutation backend.
- [ ] Specs 0008 and 0009 are superseded, Specs 0012 and 0014 match final behavior, and ADRs 0002, 0004, and 0010 accurately identify current and historical decisions.
- [ ] A repository-wide authority and documentation audit finds no obsolete functionality presented as supported current behavior.

## Out of Scope

- Rewriting the authoring model in `config/`.
- Introducing a central Ansible control server.
- Replacing the GitOps runner or its rollback model.
- Replacing Vault Agent or the secrets trust boundary.
- Replacing Debian 13 as the target OS.
- Introducing a registry or CI dependency for host convergence.

## References

- `docs/specs/GOVERNANCE.md`
- `docs/specs/accepted/0008-manifest-drift-model.md`
- `docs/specs/accepted/0009-apply-pipeline.md`
- `docs/specs/accepted/0012-gitops-runner.md`
- `docs/adr/0010-ansible-reconciliation-model.md`
- `src/abhaile/renderers/`
- `src/abhaile/cli/apply.py`
- `scripts/abhaile-runner`
- `scripts/bootstrap.sh`
