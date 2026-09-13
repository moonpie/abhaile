# Spec: Target Host Reconciliation Model

## Metadata

```yaml
id: SPEC-2026-028
title: Target Host Reconciliation Model
status: active
owner: moonpie
created: 2026-09-04
updated: 2026-09-13
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

## Decision Notes

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
