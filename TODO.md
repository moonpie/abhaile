# TODO: Abhaile Project Tracker

Working scratchpad. Specs and ADRs are the durable record; this file tracks the next execution
sequence only.

## Next Up

- [ ] 2026-06-21 Work through Phase 3 service specs.
- [ ] 2026-06-21 Work through Phase 4 network/controller spec.
- [ ] 2026-06-21 Work through Phase 5 CI/dependency automation spec.

## Ansible Reconciliation Migration

The repository contains the initial Ansible migration scaffold, but it is not ready for live
convergence. Keep the legacy Python apply path authoritative until every cutover gate below has
passed. Complete the phases in order.

### Phase 0: Contain Risk and Restore Governance

- [x] 2026-09-26 Review every Phase 0 task against its prerequisites and evidence; confirm it is completable within this phase or split and move any later-phase dependency before implementation. Evidence: Phase 0 separated governance and trust-model decisions from the Phase 1 implementation work.
- [x] 2026-09-13 Keep Ansible convergence disabled in the GitOps runner and document the scaffold as experimental. Evidence: `scripts/abhaile-runner`, `scripts/bootstrap.sh`, and `docs/reference/apply.md`.
- [x] 2026-09-13 Normalize Spec 0028 lifecycle and create or identify the active implementation and migration authority. Evidence: `docs/specs/active/0028-target-host-reconciliation-model.md` and its Decision Notes.
- [x] 2026-09-13 Separate the fresh-host enrollment contract from the existing-host re-enrollment contract. Evidence: Host Lifecycle Contracts and Decision Notes in `docs/specs/active/0028-target-host-reconciliation-model.md`.
- [x] 2026-09-13 Replace the service-account-writable sudo design with a root-owned launcher, independently verified revision, and immutable root-owned convergence tree. Evidence: Spec 0028 Local Host Execution and ADR 0010 Privileged Code Trust.
- [x] 2026-09-13 Define separate apply-state and runner last-known-good ledgers, including rollback after wider health failure. Evidence: Spec 0028 Health, State, and Rollback Integration and ADR 0010 State and Health Boundaries.
- [x] 2026-09-13 Defer superseding Specs 0008 and 0009 until final cutover and add final-state authority and implementation acceptance gates to Spec 0028.
- [x] 2026-09-13 Define network recovery, runner self-management, secret redaction, Git host trust, offline rollback, rollback limits, and cold-boot safety contracts in Spec 0028.
- [x] 2026-09-13 Define the root-controlled revision trust source and bind code, config, render execution, manifest, and artifacts into one immutable trusted convergence capsule. Evidence: Spec 0028 Trusted Convergence Capsule and ADR 0010 Privileged Code Trust.

### Phase 1: Quarantine the Scaffold and Establish Trust

- [x] 2026-09-26 Review every Phase 1 task against its prerequisites and evidence; confirm it is completable within this phase or split and move any later-phase dependency before implementation. Evidence: repository-safe trust lifecycle and metadata-level discovery work remains here; active rootless runtime and unit observation, manifest integration, convergence proof, host reports, sudo installation, and legacy-policy removal are assigned to Phases 2, 3, 5, 6, 7, and 8.
- [x] 2026-09-13 Prevent convergence from fetching, checking out, or otherwise changing the runner-selected Git revision. Evidence: `ansible/playbooks/converge.yml` contains only fail-closed debug/assert tasks; `tests/unit/python/test_ansible_layout.py` rejects Git, command, and role execution.
- [x] 2026-09-13 Replace the current mutating play with a fail-closed preflight-only scaffold until trusted staging and manifest convergence are ready. Evidence: `ansible/playbooks/converge.yml`, unconditional `--ansible` rejection in `src/abhaile/cli/apply.py`, and `tests/unit/python/test_ansible_layout.py`.
- [x] 2026-09-13 Implement and test the repository-side root-owned launcher and trust foundation: protected bare mirror, trusted-revision admission, non-fast-forward rejection, immutable source/render staging, root-only capsule sealing and activation, protected refs, cached last-known-good selection, and rollback-object retention. Scope: trust primitives and component behavior using injected roots; excludes complete real-render capsule preparation and host convergence. Evidence: `src/abhaile/trust/` and `tests/unit/python/trust/`.
- [x] 2026-09-13 Complete protected capsule-cache lifecycle hygiene: implement bounded sealed-capsule retention and garbage collection while preserving trusted, active, transaction, last-known-good, and configured rollback-history capsules. Scope: repository-safe lifecycle work under the protected trust lock; excludes render-orphan deletion until Phase 2 establishes root-verifiable renderer-process containment. Evidence: `CapsuleStore.garbage_collect()` uses an explicit admitted-ref policy, closed namespace validation, full pre-deletion capsule verification, atomic quarantine, directory fsync, and retry-safe removal; failure, incoming-ref, protected-ref, and interrupted/recreated-capsule tests are in `tests/unit/python/trust/test_capsule.py`.
- [x] 2026-09-13 Prove manifest tampering and render-to-apply time-of-check/time-of-use attacks cannot cross the root trust boundary. Evidence: one descriptor-anchored snapshot is structurally validated and copied into new root-only inodes; strict manifest path/kind/owner/hash/completeness checks and retained-writable-descriptor, symlink, hard-link, tampering, activation, and failure-injection tests live under `src/abhaile/trust/` and `tests/unit/python/trust/`.
- [x] 2026-09-13 Define whether dry-run may populate the protected mirror or capsule cache, while keeping managed host state mutation-free. Evidence: Spec 0028 Decision Notes and `src/abhaile/trust/launcher.py`; the fixed launcher exposes only required dry-run capsule preparation and does not activate capsules or update applied/LKG state.
- [x] 2026-09-13 Implement and test the typed, read-only existing-host discovery model and five-way classification using injected synthetic observations, with fail-closed ambiguity and sanitized output. Scope: observation and classification contracts only; excludes actual host collection and reports. Evidence: `src/abhaile/trust/discovery.py` and `tests/unit/python/trust/test_discovery.py`.
- [x] 2026-09-13 Implement fixed read-only discovery collectors and parsers for metadata-level identity, sudo, repository/SSH, ledger, runtime prerequisites, unit/Quadlet paths, Vault prerequisites, and networkd configuration. Scope: injected command and filesystem fixtures only; excludes active rootless Podman and user-unit observation until Phase 2 establishes its non-mutating transport, and excludes collection from `deimos` or `phobos`. Evidence: `FixedDiscoveryBackend` defines 18 separately classified probes, four shell-free observational commands, an injectable filesystem root and I/O contracts, bounded execution requirements, strict parsers, and sanitized fail-closed results; synthetic coverage is in `tests/unit/python/trust/test_discovery.py`.
- [x] 2026-09-13 Pin and validate Git host keys and prove that already-admitted trusted or retained last-known-good revisions and cached capsules can be selected in offline preflight without GitHub. Scope: trust admission and cached preflight selection only; excludes the selected revision's complete real render and actual convergence. Evidence: `src/abhaile/trust/git.py`, `src/abhaile/trust/launcher.py`, and their tests under `tests/unit/python/trust/`.
- [x] 2026-09-13 Implement and test constrained-sudo candidate artifacts and the fail-closed launcher-first installation and validation plan. Scope: repository artifacts and an injected ordered plan only; excludes installation, policy replacement, and claims that the executable cutover/rollback path is complete. Evidence: `ansible/sudoers/abhaile-converge.candidate`, `scripts/abhaile-converge-launcher`, `src/abhaile/trust/sudo.py`, and `tests/unit/python/trust/test_sudo.py`.

### Phase 2: Repair the Compatibility Entry Point and Runtime Foundations

- [ ] 2026-09-26 Before implementing Phase 2, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope.
- [ ] 2026-09-26 Establish a root-created renderer process-containment boundary, prove the complete process tree is quiescent, and only then implement bounded cleanup of isolated `.render-orphan.*` scratch. Scope: process-group or cgroup supervision and root-verifiable completion; do not delete retained scratch based only on callback return, elapsed time, or PID disappearance.
- [ ] 2026-09-26 Define and test a strictly observational transport for active rootless Podman, user-manager, system-unit, user-unit, and generated Quadlet state without initializing runtime or storage. Scope: fixed injectable collectors and parsers that build on Phase 1 metadata discovery; actual host collection remains in Phases 6 and 7.
- [ ] 2026-09-13 Make Ansible configuration, role discovery, working directory, inventory, and callback selection deterministic.
- [ ] 2026-09-13 Map every supported apply safety flag into Ansible and reject unsupported combinations explicitly.
- [ ] 2026-09-13 Replace ad hoc host and SOPS checks with the repository's structured validation semantics.
- [ ] 2026-09-13 Prevent Ansible output, diffs, facts, temporary files, JSON, errors, and journald from exposing secret material.
- [ ] 2026-09-13 Define and test safe self-management for the active runner service, timer, locking, and next invocation.
- [ ] 2026-09-13 Establish correct rootless user-manager, Podman environment, runtime-directory, and Vault Agent behavior.

### Phase 3: Define and Implement the Manifest Contract

- [ ] 2026-09-26 Before implementing Phase 3, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope.
- [ ] 2026-09-13 Audit every convergence family against the manifest and define its schema version, path trust, owner/action vocabulary, validation ownership, and compatibility rules.
- [ ] 2026-09-13 Define manifest kinds, completeness rules, and convergence semantics for `software/*`, then prove the selected trusted revision's real renderer produces a complete manifest that can be validated and sealed into one immutable capsule. Scope: real-render and capsule integration; the Phase 1 trust primitives remain independently complete.
- [ ] 2026-09-13 Make the rendered manifest and artifacts the sole desired-state input to Ansible convergence.
- [ ] 2026-09-13 Preserve owner ordering, validation hints, rootful and rootless context, and handler boundaries.
- [ ] 2026-09-13 Implement distinct apply-state and runner last-known-good commit gates and health-failure rollback planning.

### Phase 4: Port Convergence Families Incrementally

- [ ] 2026-09-26 Before implementing Phase 4, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope.
- [ ] 2026-09-13 Correct repository, deploy-key, `known_hosts`, entrypoint, virtualenv, runner-unit, and runtime-directory ordering.
- [ ] 2026-09-13 Port directories, files, identities, system units, rootless units, services, packages, downloads, and builds with Python-backend parity evidence.
- [ ] 2026-09-13 Preserve applied-state rotation, safe-prune classification, destructive approval, health gates, and documented rollback classes.
- [ ] 2026-09-13 Remove hidden failures and always-changed behavior; prove unchanged convergence is idempotent.
- [ ] 2026-09-13 Implement network convergence last, with snapshots, out-of-band access, timed revert, reachability tests, and separately approved deletions.

### Phase 5: Build Migration Evidence

- [ ] 2026-09-26 Before implementing Phase 5, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope.
- [ ] 2026-09-13 Replace Ansible file-existence and keyword tests with syntax, behavior, check-mode, failure, and idempotence tests.
- [ ] 2026-09-13 Make the full test suite independent of a workstation-local `abhaile` account.
- [ ] 2026-09-13 Prove manifest convergence, failed-state preservation, safe pruning, health gating, and rollback in an isolated environment.
- [ ] 2026-09-13 Prove actual offline manifest-only convergence from an already-admitted sealed last-known-good capsule in an isolated environment, with GitHub and other network access unavailable and no Git fetch or checkout invocation. Scope: end-to-end convergence evidence after the manifest-only non-mutating integration gate exists; do not weaken the Phase 1 quarantine to obtain it.
- [ ] 2026-09-13 Prove cold-boot and degraded Vault, network, rootless user-manager, Quadlet, and runner recovery without Git or Ansible availability.
- [ ] 2026-09-13 Record implementation and validation evidence against every active migration acceptance criterion.

### Phase 6: Assess and Migrate `deimos`

- [ ] 2026-09-26 Before implementing Phase 6, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Treat live-host access and every mutation as separately authorized gates.
- [ ] 2026-09-13 Inventory `deimos` live state without mutation; classify prerequisites, adopted legacy state, drift, conflicts, and gated removals; and record the reviewed discovery report. Scope: explicitly authorized read-only collection from `deimos`, using the Phase 1 metadata collectors and classification model plus the Phase 2 active runtime and unit collectors.
- [ ] 2026-09-13 Confirm the age identity, deploy key, `known_hosts`, sealed Vault Agent bundle, SOPS recipient rule, runner state, and last-known-good revision without exposing secret material.
- [ ] 2026-09-13 Run the supported Ansible syntax, offline, wrapper preflight, and dry-run checks for `deimos` and review the complete plan.
- [ ] 2026-09-13 Install and validate the root-owned launcher and constrained sudo policy on `deimos` alongside the legacy policy. Syntax-check both artifacts, run the root self-test, and prove the exact `runuser` to `sudo -n` offline dry-run command and recovery path before relying on it; do not remove the legacy policy in this phase.
- [ ] 2026-09-13 With explicit live-apply approval, converge `deimos` in staged non-network and network gates, then prove idempotence, health, and rollback.

### Phase 7: Migrate `phobos` and Cut Over

- [ ] 2026-09-26 Before implementing Phase 7, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Treat live-host access, cutover, and every mutation as separately authorized gates.
- [ ] 2026-09-13 Repeat the read-only assessment and staged proof on `phobos`, including its VLAN, Coral TPU, Vault, and infrastructure-specific state, and record the reviewed discovery and classification report. Scope: explicitly authorized read-only collection from `phobos`.
- [ ] 2026-09-13 Install and validate the root-owned launcher and constrained sudo policy on `phobos` alongside the legacy policy, repeating the exact-command and recovery gates used for `deimos`; do not remove the legacy policy in this phase.
- [ ] 2026-09-13 Enable Ansible in the runner behind an explicit feature flag and observe timer-driven convergence on both hosts.
- [ ] 2026-09-13 Confirm both hosts track runner-selected revisions and retain working health-gate and rollback behavior.
- [ ] 2026-09-13 Complete an explicit go or no-go review before making Ansible the default converger.

### Phase 8: Post-Migration Cleanup

- [ ] 2026-09-26 Before implementing Phase 8, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Require explicit cutover approval before destructive or access-policy cleanup.
- [ ] 2026-09-13 Remove legacy apply branches only where Ansible parity and rollback evidence prove they are redundant.
- [ ] 2026-09-13 Remove each unrestricted legacy sudo policy only after the constrained launcher is installed and usable, the exact permitted invocation and recovery path are proven, both hosts are stable on the supported path, and explicit cutover approval is recorded.
- [ ] 2026-09-13 Remove duplicate compatibility and temporary state scaffolding only where no operational dependency remains.
- [ ] 2026-09-13 Update specs, ADRs, runbooks, and operator guidance to match deployed behavior.
- [ ] 2026-09-13 Accept the implementation spec and remove this checklist only after all evidence and cleanup gates pass.

### Migration Context and Constraints

Both `deimos` and `phobos` are live hosts already enrolled through the legacy bootstrap and Python
apply flow. They must not be treated as blank machines. The Ansible scaffold was pushed to the
tracked branch on 2026-09-09, but neither the normal runner nor bootstrap currently selects the
optional Ansible compatibility mode. This limits the current blast radius and must remain true
until the migration path is safe.

The migration preserves these authority boundaries:

- `config/` remains the source of declarative intent.
- Render remains deterministic and unprivileged.
- `rendered/manifest.json` and rendered artifacts form the converger input contract.
- The runner owns candidate fetch and selection, locking, health gating, and rollback.
- Only the root-owned updater's independent fetch establishes privileged revision trust.
- Root executes only independently verified repository content from an immutable root-owned tree.
- Apply records successfully converged state; the runner records last-known-good only after health.
- Runtime secrets remain outside repository-managed rendered output.
- Destructive actions, network changes, and drifted removals fail closed without explicit approval.

The initial scaffold must not be promoted unchanged. The current play can update its own Git
checkout, does not consume the rendered manifest, depends on ambiguous live sudo state, and mixes
bootstrap, runner, and convergence responsibilities. Role discovery is not deterministic through
the wrapper. Git access does not explicitly use or validate the non-default deploy key. Several
tasks run in an unsafe order, suppress errors, or always report changes. Rootless Podman command
construction is incorrect, and Vault Agent is targeted as a system service instead of an
`abhaile` user service.

The compatibility CLI must preserve the established safety contract. `--dry-run` remains
non-mutating; prune and destructive flags must never be silently ignored; and host mismatch checks
remain fail-closed. Apply state is committed after convergence and local validation. The runner
commits its last-known-good revision only after the wider health gate; a health failure rolls back
from the actual applied state. The runner and bootstrap continue using the legacy apply path until
the explicit cutover phase.

Existing-host migration begins with observation, not mutation. Before re-enrollment, confirm the
service-account identity and effective sudo policy; repository revision, ownership, and SSH
identity; age and Vault Agent prerequisites; rendered, applied, and runner state; rootless user
manager and Podman state; active system and user units; and current networkd configuration. Do not
print or copy private key, token, SecretID, role ID, or decrypted SOPS content while collecting
evidence.

Validation must include real Ansible syntax and role discovery, check mode, first-run behavior,
an unchanged second run, failure injection before state commit, safe and drifted prune cases,
rootless service activation, health failure, and rollback to an immutable last-known-good
revision. Keyword-presence tests are insufficient evidence. The current full local suite also has
one pre-existing portability failure because drift planning resolves the `abhaile` account through
the workstation account database; fix that test boundary before treating the suite as a clean
migration signal.

`deimos` is the canary. Live convergence requires explicit approval and separates lower-risk work
from network changes. `phobos` follows only after `deimos` is stable and rollback has been proven.
Cleanup cannot begin until both hosts are stable, standard reconciliation requires no manual host
edits, the compatibility path is demonstrably redundant, and the active spec matches deployed
operational reality.

The Architect and SysAdmin reviews on 2026-09-13 required the root-owned code-trust boundary,
two-ledger transaction model, deferred supersession, expanded final-state acceptance criteria, and
the reordered operational foundations above. Phase 0 was revisited and updated before Phase 1.

## Specs

| Phase | Spec / Authority |
| --- | --- |
| Phase 3 services | `docs/specs/proposed/0015-services-home-automation.md` through `0020-host-hardening.md` |
| Phase 4 network/controller automation | `docs/specs/proposed/0021-network-devices.md` |
| Phase 5 CI/dependency automation | `docs/specs/proposed/0024-ci-dependency-automation.md` |

### Phase 3 Specs

| Spec | Scope |
| --- | --- |
| `docs/specs/proposed/0015-services-home-automation.md` | Home Assistant, Mosquitto, Zigbee2MQTT, ESPHome, Frigate, Go2rtc |
| `docs/specs/proposed/0016-services-monitoring.md` | Prometheus, Grafana, Loki, Alertmanager, exporters |
| `docs/specs/proposed/0017-services-media.md` | Immich, Jellyfin, Tdarr, \*arr stack, Jellyseerr, Flaresolverr |
| `docs/specs/proposed/0018-services-networking.md` | Gluetun, qBittorrent VPN egress |
| `docs/specs/proposed/0019-services-utilities.md` | Homepage, Netbox, Vaultwarden, Postfix, CrowdSec |
| `docs/specs/proposed/0020-host-hardening.md` | nftables, fail2ban, CIS-lite, per-UID routing |

Acceptance criteria live in each spec. Don't duplicate them here.

## Implementation decisions

- Record in the active spec's Decision Notes section.
- Promote to ADR when a decision crosses service/host/agent boundaries or is expensive to reverse.

## Working With Agents

### Common Tasks

**Add a new service** — start with Architect:

> Design the `service.yaml` structure for `<service>`. Consider: container mode, storage, dependencies, ingress, vault-agent. Reference existing services (authelia for pods, omada-controller for single container, coredns-filtered for includes).

**Change a config schema** — start with Architect:

> Add `<field>` to `<config file>`. Design the schema change with backward compatibility. Propose updates to `schemas/` and renderer changes.

**Debug a failed render or test** — start with Developer:

> `make test` fails with: [error]. Investigate and fix. Read relevant test and source first.

**Write an ADR** — start with Architect:

> Write ADR for [decision]. Use `docs/adr/0000-adr-template.md`. Cover: context, alternatives, decision, consequences.

### Session Prompt

Use with the **Architect** agent. It orchestrates Developer, Code Reviewer, and Technical Writer via subagent.

```text
Follow `AGENTS.md`. Here is the work:

Spec: <path to spec>
Task: <what to implement, or "all remaining acceptance criteria">

Workflow:
1. Review the spec. Flag any ambiguities or design gaps before proceeding.
2. Once clear, hand off to Developer for implementation.
3. After implementation, hand off to Code Reviewer for validation.
4. After review passes, hand off to Technical Writer for any doc updates.
5. Report results. If all acceptance criteria are met, move spec to accepted/.

Record implementation decisions in the spec's Decision Notes.
If a durable architectural decision emerges, create or update an ADR.
```
