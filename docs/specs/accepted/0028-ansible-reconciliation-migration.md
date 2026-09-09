# Spec: Target Host Reconciliation Model

## Metadata

```yaml
id: SPEC-2026-028
title: Target Host Reconciliation Model
status: accepted
owner: moonpie
created: 2026-09-04
updated: 2026-09-09
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0003-gitops-runner-responsibility-boundary
  - 0004-apply-execution-model
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0010-ansible-reconciliation-model
supersedes:
  - SPEC-2026-008
  - SPEC-2026-009
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

The GitOps runner remains the outer reconciliation controller and owns commit selection, lock handling, health gating, and rollback. It invokes render and the local convergence path, but it does not become the host mutation engine itself.

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
- [ ] Raw `abhaile-apply` behavior is retained as a compatibility wrapper until a separate explicit decision removes it.
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

Ansible must run locally on the target host and must not introduce a central control-plane dependency. SSH fan-out between hosts is explicitly out of scope.

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

The runner sits outside that path and is responsible for:

```text
git fetch -> commit selection -> render -> apply/converge -> health -> success or rollback
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

### 7. Health and Rollback Integration

The runner remains the authority for health and rollback behavior. Ansible convergence is one step in the local reconciliation loop, not the entire GitOps contract.

The desired loop is:

```text
render -> converge -> health -> record success

on failure: rollback to last-known-good -> render -> converge -> health
```

This keeps Abhaile's operational recovery semantics intact even though the mutation engine has changed.

## Decision Notes

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
- [ ] The runner contract remains the authoritative GitOps health and rollback model.
- [ ] Rootless and rootful service execution semantics remain explicit operational requirements.
- [ ] Destructive operations remain fail-closed without explicit approval.
- [ ] State ledger semantics remain minimal and are defined as safe-prune/reporting support rather than the primary drift engine.
- [ ] The design remains deterministic and idempotent for repeated convergence runs.
- [ ] Documentation and implementation work are aligned with this target model rather than with the legacy custom apply code as the long-term design.

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
