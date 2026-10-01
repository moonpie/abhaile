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

Phase 2 implements local, injected foundations only. Spec 0028 remains the durable authority.
No item below authorizes host collection, Ansible delegation, installation, or convergence.

- [x] 2026-09-26 Review every Phase 2 task against prerequisites and evidence. Evidence: inspection of `fed6bfc`, trust modules, CLI, scaffold, canonical account config, and Architect/SysAdmin consultations on 2026-09-27. In-scope and deferred work is recorded below; no implementation completion is implied.
- [x] 2026-09-27 Repair inherited split trust-root validation for `/var/lib/abhaile/mirror.git` and `/etc/abhaile/{known_hosts,git-fetch-identity}`. Evidence: fixed production namespaces with full ancestor validation and a constructor-only synthetic filesystem seam in `model.py`, `git.py`, and `launcher.py`; split-layout and caller-root rejection tests in `test_git.py` and `test_launcher.py`.
- [x] 2026-09-27 Repair inherited discovery presence/conformance conflation. Evidence: `AccountIdentity`, distinct presence/conformance parsing, unambiguous exit-2 absence, `Linger=yes/no`, bounded numeric fields, and sanitized malformed/relationship failure coverage in `discovery.py` and `test_discovery.py`.
- [x] 2026-09-28 Repair inherited privileged-launcher import isolation. Evidence: the root-owned wrapper invokes only the protected trust runtime with Python isolated mode, and the layout regression rejects loss of `-I`; host installation remains a later explicit adoption gate.
- [x] 2026-09-26 Establish root-created renderer containment and independently prove complete process-tree quiescence before sealing or bounded orphan cleanup. Evidence: root-created cgroup-v2 supervision, pre-exec attachment, PAM-free identity transition, protected runtime dependency closure, kernel `populated=0` proof, ancestor migration-control validation, store-owned boundary binding, boot/inode-bound receipts, failed-render retention, and bounded retry-safe scratch plus cgroup retirement in `containment.py`, `orphans.py`, and capsule tests. Creation records the new child's inode before validating controls, removes only that exact protected child on validation failure, and tells the capsule store when rollback is proven so failed setup scratch is removed; failure injection and repeated-retry tests prevent untracked accumulation. Operator-provided checks on both Debian 13.7 hosts confirmed cgroup-v2 transaction creation, descendant population, subtree kill, `populated=0`, empty-group removal, and rejection of unprivileged ancestor migration on 2026-09-28. Dry-run never collects. The installed dedicated-identity chain remains an explicit Phase 6/7 adoption proof.
- [x] 2026-09-26 Define and test strictly observational active Podman, user-manager, system-unit, user-unit, and generated Quadlet collectors. Evidence: fixed bounded system/user-unit collectors, generated Vault Agent provenance, and a typed terminal Podman capability blocker in `active_discovery.py`. Tests prove unavailable Podman observation performs no filesystem, socket, subprocess, retry, or initialization activity and classifies as a sanitized conflict rather than false absence. Positive Podman platform proof is assigned to Phase 5; actual reports remain Phases 6/7.
- [x] 2026-09-13 Make Ansible configuration, roles/collections, working directory, inventory, callbacks, interpreter, and sealed paths deterministic. Evidence: independently admitted and verified non-executable plan, fixed protected runtime/capsule/temp namespaces, and a closed environment in `ansible.py`. The protected argv's `-i localhost,` is the sole inventory authority, only the builtin `host_list` inventory plugin is enabled, ambient inventory and callback variables are absent, and the fixed default callback is used without an empty callback list. A real isolated `ansible-core` 2.20.9 integration test verifies the effective config dump, resolves exactly the inline localhost inventory and builtin assert/debug modules, and passes `converge.yml --syntax-check`; manifest execution remains Phases 3/4.
- [x] 2026-09-13 Inventory and define every apply safety/behavior flag, reject unsupported/conflicting combinations, and test the compatibility contract. Evidence: `FLAG_CONTRACT`, typed `ApplyIntent`, complete parser inventory, table-driven conflict tests, and unchanged unconditional `--ansible` rejection. Manifest-dependent execution remains Phases 3/4.
- [x] 2026-09-13 Replace ad hoc Ansible-era host and SOPS checks with structured Python/schema validation. Evidence: `config_validation.py` reuses canonical schemas, mapping, network, and composed-user validation; preserves first-match/catch-all behavior for the repository's supported age-only creation-rule subset; validates encrypted-bundle metadata without reading payloads; unsupported SOPS features fail closed. The dormant Ansible role now only asserts quarantine.
- [x] 2026-09-13 Establish reusable secret-safe execution, temporary-path, no_log, diff, and report boundaries. Evidence: protected temporary namespace/mode checks, explicit plugin/report suppression, `SecretTaskPolicy`, sanitized exception chains, and placeholder leakage tests in `ansible.py` and `test_ansible.py`. Complete task/callback/journald leakage proof remains Phases 4/5.
- [x] 2026-09-13 Define and test runner service/timer self-management planning, existing lock preservation, validation before publication, deferred effects, and failure recovery. Evidence: pure ordered state machine and recovery contract in `runner_update.py` and `test_runner_update.py`. Publication and transaction integration remain Phases 3/4; cutover remains Phase 7.
- [x] 2026-09-13 Establish rootless identity, linger, HOME, runtime-directory ownership/lifecycle, Podman environment, and rootless Vault Agent contracts. Evidence: typed prerequisite metadata, closed environment, PAM-free `setpriv` transport, ownership/mode fail-closed tests, and rootless generated-unit observation in `runtime.py`, `active_discovery.py`, and their tests. Service mutation remains Phase 4 and boot/recovery evidence Phase 5.

### Phase 3: Define and Implement the Manifest Contract

Deferred from Phase 2: integrate sealed invocation and safety-flag contracts with the completed
manifest; bind runner update staging to transaction commit evidence.

- [x] 2026-09-26 Before implementing Phase 3, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Evidence: 2026-09-29 governance audit and Architect/SysAdmin consultations split pure contract, planning, sealing, and commit-gate work from the Phase 4/5 execution and evidence items below.
- [x] 2026-09-13 Audit every convergence family against the manifest and define its schema version, path trust, owner/action vocabulary, validation ownership, and compatibility rules. Evidence: strict transitional v2 contract in `renderers/convergence_manifest.py`, `trust/manifest.py`, and their tests; legacy v1 remains authoritative for Python apply.
- [x] 2026-09-13 Define manifest kinds, completeness rules, and convergence semantics for `software/*`, then prove the selected trusted revision's real renderer produces a complete manifest that can be validated and sealed into one immutable capsule. Evidence: shared closed typed parsing in `models/software.py`, effect authority in manifest metadata, privileged payload/effect agreement and global collision checks in `trust/manifest.py`, unsafe-value/collision tests, and deterministic both-host real-render validation. Container-build execution remains explicitly integrity-blocked for Phase 4.
- [x] 2026-09-13 Make the sealed manifest and artifacts the sole desired-state input to protected Ansible planning. Evidence: `trust/ansible.py` exposes only capsule-internal v2 manifest/rendered paths and an independently validated `ConvergencePlan`; execution remains quarantined and is deferred to Phase 4.
- [x] 2026-09-13 Preserve owner ordering, validation hints, rootful and rootless context, and handler boundaries in pure planning. Evidence: dependency-preserving contiguous owner blocks in `trust/convergence.py`, lower-phase-dependent regression coverage, deterministic repeated renders, and both-host audits proving every prerequisite owner precedes its dependent; handler execution remains Phase 4.
- [x] 2026-09-13 Implement distinct apply-state and runner last-known-good commit gates and health-failure rollback planning. Evidence: transaction-bound apply/LKG commit digests in `trust/transaction.py`; exact revision, capsule, manifest, service, timer, recovery-record, and ledger-evidence binding in `trust/runner_update.py`; mismatch/replay/dry-run tests; I/O and publication remain Phase 4/5.

### Phase 4: Port Convergence Families Incrementally

Deferred from Phase 2: execute flag mappings, publish validated runner updates after commit,
converge rootless runtime/Vault Agent, and apply secret-safe task boundaries.

Deferred from Phase 3: consume the protected v2 plan in real Ansible tasks; execute typed package,
download, build, prerequisite, file, identity, unit, network, Quadlet, and Vault operations;
perform validation/handler effects; atomically write apply state; publish staged runner updates;
and execute rollback. Keep `--ansible` unavailable until those gates are proven.

- [x] 2026-09-26 Before implementing Phase 4, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Evidence: the 2026-09-29 Architect and SysAdmin audits split repository mechanics from Phase 5 isolated execution evidence, Phase 6/7 adoption, and live network proof; the user explicitly approved only the stale existing Phase 4 scope.
- [x] 2026-09-13 Define deterministic repository, credential, protected-runtime, renderer, state-directory, rootless-runtime, sudo-candidate, and runner-candidate prerequisite ownership and ordering. Evidence: `trust/bootstrap_order.py` and `test_bootstrap_order.py`; bootstrap/adoption-owned foundations are preservation-only during normal convergence. Installed-host ordering proof remains Phase 6/7.
- [x] 2026-09-13 Compile the sealed manifest-v2 convergence plan into a closed, dependency-ordered, data-only Ansible operation vocabulary while retaining unconditional mutation quarantine. Evidence: `trust/convergence_engine.py`, `trust/ansible.py`, `ansible/roles/manifest_convergence/`, and focused tests reject network, container-build, mismatched, unverified, and unsupported input before mutation. This is not executable family parity.
- [x] 2026-09-13 Close manifest-v2 restart authority with an explicit renderer-owned unit relation, authority owner, execution context, and bounded restart mode. Evidence: rendering and privileged validation reject missing/unmanaged, cross-owner, cross-context, named-identity-mismatched, runner-self, and tampered targets; `manual` authorizes no automatic restart.
- [x] 2026-09-13 Seal renderer-owned named-user name, UID, GID, HOME, and shell authority in manifest v2 and carry it unchanged into bounded operations. Evidence: `renderers/convergence_manifest.py`, `trust/manifest.py`, `trust/convergence_engine.py`, and manifest/compiler tests use `context` plus the exact sealed `execution_identity` as the sole operation authority; the production role rejects missing, false, malformed, contradictory, cross-context, or unexpected protected runtime observations before mutation. Phase 5 proves the integrated protected observation transport in an authorized disposable environment; installed proof remains Phases 6/7.
- [x] 2026-09-13 Implement one production manifest-v2 dispatcher behind an isolated-disposable execution gate, with a complete preflight pass before mutation and no test-only convergence copy. Evidence: `ansible/roles/manifest_convergence/`, `trust/convergence_engine.py`, `test_ansible_quarantine_definitions.py`, and `test_ansible_quarantine_harness.py`; the protected production plan does not emit the gate and public/launcher execution remains rejected.
- [x] 2026-09-30 Implement and test the production role's isolated-disposable mapping for lifecycle-free system-context ordinary directories and ordinary service config/env files. Evidence: closed operation/kind/action/validation/effect relations, sealed source digest/type validation, capsule-shipped protected publication, secret-safe output, and isolated check-mode/idempotence/path-escape tests.
- [x] 2026-09-30 Harden ordinary live-target file/directory publication against parent replacement and unexpected trusted-directory changes between preflight and mutation. Evidence: capsule-shipped `abhaile_publish`, `trust/publication.py`, and `test_publication.py` retain no-follow directory descriptors through inspection and atomic replacement, reject links/types/unsafe ancestry, fsync publication, preserve exact numeric ownership/mode, map manifest absolute paths beneath injected disposable roots, and implement truthful check/idempotence semantics.
- [x] 2026-09-30 Implement package presence, system-unit prerequisites, unattended-upgrades state, and udev publication/reload. Evidence: closed compiler operations and production role definitions use native `apt`, `systemd_service`, and `debconf`, descriptor-safe udev publication, and fixed `/usr/bin/udevadm` argv; a separate protected host-global-isolation gate prevents workstation execution. Phase 5 retains package-availability and real module behavior evidence.
- [x] 2026-09-30 Implement systemd-unit publication and lifecycle/handler effects at owner/dependency boundaries. Evidence: unit files use validated descriptor-safe publication; `convergence_engine.py` coalesces effects once per owner and execution context; changed-owner/context tracking prevents unchanged reloads/restarts; restart authority is manifest-bound and runner self-restart remains rejected.
- [x] 2026-09-30 Implement identity/sysusers activation and sudoers candidate-only publication without authorizing sudo-policy installation. Evidence: sysusers input is validated before descriptor-safe publication and activated only through fixed `systemd-sysusers --root` argv behind host-global isolation; sudoers is validated and redirected to `/var/lib/abhaile/sudo-candidates/abhaile`, never installed at its live policy target.
- [x] 2026-09-30 Complete production Caddy, CoreDNS, resolved, Quadlet, Vault Agent, and remaining service validation/publication mechanics. Evidence: `trust/service_validation.py` and capsule-shipped `abhaile_publish` parse sealed Caddy/CoreDNS/resolved bytes with closed renderer grammars covering nesting, arity, values, blocks, and named imports during the global pre-mutation pass; fixed systemd/sysusers/sudoers/Vault/zone/Quadlet validator argv remain closed; CoreDNS zone origin is compiler-sealed; every named-user operation requires exact runtime observations; and rootless Quadlets publish root-owned beneath `/etc/containers/systemd/users/<sealed-uid>/` rather than user-writable HOME ancestry. Exact installed binary/plugin behavior remains Phase 5 evidence; Phase 6/7 own installed directory/adoption proof.
- [x] 2026-09-30 Integrate state, prune, runner-publication, rollback, and network-recovery mechanics through a protected production transaction coordinator. Evidence: `ProtectedTransactionCoordinator.run()` holds one descriptor-safe coordinator lock while it orders recovery persistence before separately authorized networking, convergence and authorized prune before local apply-state commit, a post-commit unpredictable health challenge and bounded wait for a no-follow ownership/mode-checked result bound to the challenge, transaction, and apply evidence, immediate apply-state and retained-LKG revalidation, journaled CAS/verification of the protected mirror LKG, a separate durable runner-LKG receipt, and optional runner publication. The health lifecycle uses an exact protected active journal plus transaction-scoped terminal records: success is finalized only after receipt/ref verification, failure remains active until exact rollback apply state is durable, and interrupted terminal cleanup finishes forward only after re-verifying that durable authority. Consecutive and fresh same-desired-state transactions reuse the same protected roots without stale evidence crossing transactions; rollback-finalization retry does not replay state rotation. Commit evidence and receipts bind both candidate and retained revision/manifest identities. Dry-run and every failed local boundary write no state. Phase 5 owns authorized disposable end-to-end and reboot proof, not implementation of these gates.
- [x] 2026-09-30 Implement immutable binary and archive downloads. Evidence: manifest authority now bounds HTTPS origins, redirects, bytes, archive and extracted-output SHA-256, member bytes, compression ratio, and exact member; capsule-shipped `abhaile_download` first inspects the protected local target so unchanged/offline and all check-mode runs perform no acquisition, then uses `trust/download.py` and descriptor-safe atomic publication when required, rejecting digest mismatch, redirects, traversal, links/special members, duplicates, encryption, expansion, ambiguous output, and unsafe targets.
- [x] 2026-09-30 Implement kernel-module declaration, options, and loading mechanics. Evidence: the production role publishes manifest-authorized modules-load/modprobe fragments descriptor-safely, observes `/sys/module` without initializing state, and invokes only fixed `/usr/sbin/modprobe -- <sealed-name>` for an absent module behind the protected host-global-isolation gate. Phase 5 retains privileged disposable-environment evidence.
- [x] 2026-09-13 Implement protected transaction-bound applied-state rotation and interruption-safe bounded-history mechanics under injected roots. Evidence: `trust/state_store.py` admits a commit only after explicit convergence, validation, handler, and prune success evidence; permits fresh same-revision no-op/repair transactions; rejects transaction/evidence replay; and uses descriptor-relative atomic writes, fsync, bounded history, and deterministic finish-forward recovery across every injected gap. `trust/coordinator.py` composes the production commit boundary; end-to-end rollback convergence and reboot proof remain Phase 5.
- [x] 2026-09-13 Implement safe-prune classification, distinct destructive/network/volume approval, and authorized removal mechanics. Evidence: `trust/prune.py` and `test_phase4_safety.py` revalidate the exact authorized identity immediately before descriptor-relative removal, reject links/unknown state/changed ancestry, keep dry-run inert, and make retry after an interrupted completed deletion truthful.
- [x] 2026-09-13 Implement transaction-bound recoverable runner pair publication after successful staging, without live activation. Evidence: `trust/runner_lkg.py`, `trust/coordinator.py`, and `trust/runner_publication.py` require a verifier-issued in-process authority for the exact durable runner-LKG receipt digest and re-verified protected mirror ref at both publication and recovery boundaries; a caller-supplied digest cannot authorize mutation. Pair recovery retains prior bytes/UID/GID/mode, journals transitions, rejects ambiguous non-idempotent rearm, and never restarts the active runner. Real manager behavior remains Phase 5; activation remains Phases 6/7.
- [x] 2026-09-30 Make initial runner service/timer/recovery-record staging interruption-safe. Evidence: `trust/runner_publication.py` writes transaction-bound initialization authority first, assembles and fsyncs the exact service, timer, recovery record, and staging identity in an executor-owned private sibling, atomically publishes the complete directory, and safely resumes every injected transition gap; `test_runner_initial_staging.py` rejects links, unsafe modes, malformed or mismatched retained state, and proves exact retry/idempotence.
- [x] 2026-09-13 Prove the production ordinary file/directory mapping's check mode, first-run change, unchanged second run, safe execution-gate rejection, and path/symlink escape rejection. Evidence: `tests/integration/test_ansible_quarantine_harness.py`. Phase 5 retains broad disposable-environment evidence only for production mappings already implemented in Phase 4.
- [x] 2026-09-13 Persist a protected transaction- and digest-bound network snapshot, candidate, deletion approval, and closed transition journal without network mutation. Evidence: `trust/network_recovery.py` privately stages and fsyncs the complete bound tuple before atomic directory publication; failure injection proves retry across every initialization gap and rejects malformed, linked, unsafe, or mismatched retained state. This does not arm a timer, test reachability, alter networking, or prove reboot recovery.

### Phase 5: Build Migration Evidence

Deferred from Phase 2: end-to-end task/callback/temp-file/journald secret-leakage proof and
runner/rootless/Vault failure, reboot, and recovery evidence.

Deferred from Phase 3: isolated evidence for the transaction commit state machine, wider-health
runner-LKG promotion, rollback execution/failure recovery, and target-account portability.

- [ ] 2026-09-26 Before implementing Phase 5, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope.
- [ ] 2026-09-13 Replace Ansible file-existence and keyword tests with syntax, behavior, check-mode, failure, and idempotence tests.
- [ ] 2026-09-29 Prove the bounded production manifest-v2 dispatcher in an authorized disposable environment; cover every Phase 4-admitted family, validator, handler boundary, first/second run, check mode, secret suppression, and failure before state commit. Phase 5 provides evidence and must not become the primary implementation phase for rejected families.
- [ ] 2026-09-29 Prove each named-user operation compares sealed identity authority with protected account, linger, runtime-directory, user-bus, and user-manager observations before PAM-free execution; installed-host proof remains Phases 6/7.
- [ ] 2026-09-29 Prove end-to-end applied-state rollback convergence, wider-health ordering, interruption/reboot recovery, and real runner manager reload/rearm behavior in an authorized disposable environment.
- [ ] 2026-09-13 Prove network convergence with an independently executing timed revert, out-of-band-equivalent recovery, typed affected-network reachability, explicit confirmation, reboot/controller-interruption recovery, and separately approved deletions. Live `deimos` proof requires fresh Phase 6 approval.
- [ ] 2026-09-13 Make the full test suite independent of a workstation-local `abhaile` account.
- [ ] 2026-09-28 In a disposable rootless Podman environment, prove a candidate observation transport does not create files, refresh storage, initialize a user manager, or activate a socket. If no such transport exists, preserve the Phase 2 terminal conflict and document that active Podman state requires separately authorized operator evidence during host adoption.
- [ ] 2026-09-13 Prove manifest convergence, failed-state preservation, safe pruning, health gating, and rollback in an isolated environment.
- [ ] 2026-09-13 Prove actual offline manifest-only convergence from an already-admitted sealed last-known-good capsule in an isolated environment, with GitHub and other network access unavailable and no Git fetch or checkout invocation. Scope: end-to-end convergence evidence after the manifest-only non-mutating integration gate exists; do not weaken the Phase 1 quarantine to obtain it.
- [ ] 2026-09-13 Prove cold-boot and degraded Vault, network, rootless user-manager, Quadlet, and runner recovery without Git or Ansible availability.
- [ ] 2026-09-13 Record implementation and validation evidence against every active migration acceptance criterion.

### Phase 6: Assess and Migrate `deimos`

Deferred from Phase 2: provision the protected trust, render, and Ansible validation foundations
on the first host without changing the active legacy runner or enabling Ansible convergence.

- [ ] 2026-09-26 Before implementing Phase 6, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Treat live-host access and every mutation as separately authorized gates.
- [ ] 2026-09-13 Inventory `deimos` live state without mutation; classify prerequisites, adopted legacy state, drift, conflicts, and gated removals; and record the reviewed discovery report. Scope: explicitly authorized read-only collection from `deimos`, using the Phase 1 metadata collectors and classification model plus the Phase 2 active runtime and unit collectors.
- [ ] 2026-09-13 Confirm the age identity, deploy key, `known_hosts`, sealed Vault Agent bundle, SOPS recipient rule, runner state, and last-known-good revision without exposing secret material.
- [ ] 2026-09-28 With explicit host-mutation approval, provision and validate the dedicated non-login renderer identity, protected trust/render/Ansible runtimes, fixed trust policy and stores, private temporary paths, and root-owned nondelegated cgroup parent on `deimos`. Keep the legacy timer and Python apply path authoritative; do not activate a capsule, install the constrained sudo policy, or enable Ansible convergence in this step.
- [ ] 2026-09-13 Run the supported Ansible syntax, offline, wrapper preflight, and dry-run checks for `deimos` and review the complete plan.
- [ ] 2026-09-13 Install and validate the root-owned launcher and constrained sudo policy on `deimos` alongside the legacy policy. Syntax-check both artifacts, run the root self-test, and prove the exact `runuser` to `sudo -n` offline dry-run command and recovery path before relying on it; do not remove the legacy policy in this phase.
- [ ] 2026-09-13 With explicit live-apply approval, converge `deimos` in staged non-network and network gates, then prove idempotence, health, and rollback.

### Phase 7: Migrate `phobos` and Cut Over

Deferred from Phase 2: repeat the approved protected-runtime provisioning on the second host before
runner integration or cutover.

- [ ] 2026-09-26 Before implementing Phase 7, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Treat live-host access, cutover, and every mutation as separately authorized gates.
- [ ] 2026-09-13 Repeat the read-only assessment and staged proof on `phobos`, including its VLAN, Coral TPU, Vault, and infrastructure-specific state, and record the reviewed discovery and classification report. Scope: explicitly authorized read-only collection from `phobos`.
- [ ] 2026-09-28 With explicit host-mutation approval, provision and validate on `phobos` the same dedicated renderer identity, protected runtimes, fixed trust policy and stores, private temporary paths, and cgroup-parent contract proven on `deimos`. Keep the legacy timer and Python apply path authoritative until the later cutover gate.
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
