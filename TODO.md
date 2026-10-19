# TODO: Abhaile Project Tracker

Working scratchpad. Specs and ADRs are the durable record; this file tracks the next execution
sequence only.

## Next Up After the Reconciliation Migration

These are the next planned homelab content and functionality phases. The unplanned Python-to-Ansible
reconciliation migration temporarily takes precedence; resume this roadmap after that migration is
complete. The user explicitly approved retaining these stale items on 2026-10-07. Their phase names
belong to the wider project roadmap and are independent of the migration phase numbers below.

- [ ] 2026-06-21 Work through Phase 3 service specs.
- [ ] 2026-06-21 Work through Phase 4 network/controller spec.
- [ ] 2026-06-21 Work through Phase 5 CI/dependency automation spec.

## Ansible Reconciliation Migration

The repository contains the initial Ansible migration scaffold, but it is not ready for live
convergence. Keep the legacy Python apply path authoritative until every cutover gate below has
passed. Complete the phases in order.

Completed Phases 0-5 record evidence for the quarantined prototype and are retained temporarily
until Phase 5.2 deletes or replaces that implementation. They are historical, not authority for
the target design; active Spec 0028 and ADR 0013 govern all new work.

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
- [x] 2026-09-13 Replace the current mutating play with a fail-closed preflight-only scaffold until trusted staging and manifest convergence are ready. Historical evidence: `ansible/playbooks/converge.yml`, the then-unconditional `--ansible` rejection in `src/abhaile/cli/apply.py`, and `tests/unit/python/test_ansible_layout.py`; Phase 5.2 subsequently removed the dead selector without enabling the scaffold.
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
- [x] 2026-09-13 Inventory and define every apply safety/behavior flag, reject unsupported/conflicting combinations, and test the compatibility contract. Historical evidence: `FLAG_CONTRACT`, typed `ApplyIntent`, complete parser inventory, table-driven conflict tests, and the then-unconditional `--ansible` rejection. Phase 5.2 removed the dead selector and its mirrored contract entry; manifest-dependent prototype work remained quarantined.
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
and execute rollback. This historical deferral was closed by deleting the unsupported `--ansible`
selector in Phase 5.2 rather than enabling it.

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

- [x] 2026-09-26 Before implementing Phase 5, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Evidence: the 2026-10-01 Architect and SysAdmin audits classified each item; repository-only filesystem/download/identity/transaction evidence may proceed, host-global package/systemd/udev/kernel/reboot evidence requires a disposable Debian 13 VM, installed-host proof remains Phases 6/7, and executable network convergence is absent from the Phase 4 admitted model.
- [x] 2026-09-13 Replace Ansible operation confidence based only on file-existence and keyword checks with syntax, behavior, check-mode, failure, and idempotence tests. Evidence: the real isolated production playbook/role harness proves deterministic syntax and role loading, complete preflight, validation failure before mutation, check mode, first-run change, unchanged rerun, exact publication metadata, path/symlink confinement, named-user rejection, and synthetic-secret suppression. Structural layout tests remain only as bounded dispatcher/configuration guardrails, not operation evidence.
- [x] 2026-10-02 Complete the Phase 5 implementation-readiness audit after closing protected boot identity, stage-aware network interruption recovery, sealed-capsule production construction, and complete independent recovery-installation identity. Evidence: the fixed-policy revision-only constructor retains one exact-cover Ansible/network request with private plan-bound capabilities; derives protected prior-state removals and internal transaction/token authority; coordinates apply/network commits without an adjacent callback; implements authority-first cleanup and approved pre-disarm rollback/post-disarm independently revalidated finish-forward; and verifies the exact helper/interpreter/module/package/unit installation plus monotonic effective manager state. Architect, SysAdmin, and independent Code Reviewer approved the final repository mechanics. `pytest -q --no-cov` passes 1,497 tests; coverage executes all tests but the repository-wide 83.36% result remains below the configured 85% gate and is not described as green; `make lint` including mypy, interrogate 91.4%, and gitleaks passes. Both authoritative manifest-v2 host renders are byte-identical (Deimos 51, Phobos 122). VM systemd/networkd/reboot/peer proof remains separate.
- [x] 2026-09-29 On a disposable Debian 13 VM, prove the bounded production manifest-v2 dispatcher across every Phase 4-admitted family, installed validator, and real handler boundary, including first/second run, check mode, secret suppression, and failure before state commit. Evidence: the sealed Deimos manifest compiled an exact-cover host-global projection of 11 entries spanning packages, four directories, kernel modules/options, system units, immutable binary and archive downloads, unattended upgrades, and candidate-only sudo policy; every entry passed production-role preflight under injected roots and a real Debian manager in check mode, which completed `ok=127 changed=11 failed=0` without publication. The separately completed safe-publication harness proved check/first/unchanged-second runs, exact metadata, installed structural/resolved/Caddy/CoreDNS/systemd/Quadlet validators, secret suppression, and invalid-input refusal before publication; named-user, guarded-network, rollback/state, offline, and real systemd callback suites cover their protected executors and handler boundaries. The complete unprojected host plan also failed before mutation when the clean VM lacked Abhaile's custom CoreDNS plugins, preserving that prerequisite as a Phase 6 adoption gate rather than weakening validation. Exact-cover support now recognizes only the compiler's fixed `/etc/sudoers.d/abhaile` to `/var/lib/abhaile/sudo-candidates/abhaile` staging transform and rejects arbitrary target substitutions.
- [x] 2026-09-29 On a disposable Debian 13 VM, prove each named-user operation compares sealed identity authority with real account, linger, runtime-directory, user-bus, and user-manager observations before PAM-free execution. Evidence: Debian 13.7 supplied the real `proof` UID/GID 1000, `/home/proof`, `/bin/bash`, enabled linger, active user manager, UID-owned mode-0700 runtime directory, and UID-owned bus socket; those exact independently observed values were sealed into a manifest-v2 named-user Quadlet operation and compiled through the production planner. Root-run quarantined convergence under fresh `/tmp` roots proved inert check mode, first publication followed by the fixed PAM-free `setpriv` user-manager reload, `changed=0` rerun, and refusal before publication when the observed bus UID was altered. No real Quadlet or container was installed or started; installed-host adoption proof remains Phases 6/7.
- [x] 2026-09-29 On a disposable Debian 13 VM, prove end-to-end applied-state rollback convergence, wider-health ordering, interruption/reboot recovery, and real runner manager reload/rearm behavior. Evidence: 31 Debian cases proved failed convergence/dry-run writes no state, exact safe prune and drift refusal, interrupted state rotation, wider-health failure authority, blocked admission before rollback, and retained-LKG rollback across all nine terminal-finalization boundaries. A runtime-only proof systemd service/timer then proved real daemon reload, enabled/active scheduling, service binding, monotonic rearm, and cleanup; the production committed-runner publication, ordered reload/rearm, and interrupted-rearm recovery tests passed against the same Debian manager environment. The guarded-network controller interruption also completed real changed-boot recovery before networkd startup.
- [x] 2026-10-02 Complete the ADR 0011 guarded networkd transition controller. Evidence: closed probe schema; exact-cover plan-bound handoff; fixed-policy sealed-capsule construction; exact protected removals; boot and confirmation authority; nonce-safe durable authorization plus fresh reachability; stage-aware pre-disarm changed-boot rollback and post-disarm revalidated finish-forward; ambiguous-effect inspection; verified restoration with active-journal retention on failure; private capabilities; coordinator apply/network commits; authority-first cleanup; and policy-anchored direct-Python recovery installation with exact installed Debian package state and realistic effective systemd observation all pass focused and full repository tests. Architect, SysAdmin, and Code Reviewer approve. Quarantine remains intact. Resolver and alternative backends remain rejected; real Debian manager/network/reboot/peer proof stays open below.
- [x] 2026-10-03 Before Phase 6, review whether all reconciliation can use one protected locally retained last-successful capsule and one durable apply commit point, with network rollback treated only as an early-boot/offline enforcement mechanism rather than a second definition of success. Evidence: Phase 5.1 replaced this preliminary formulation with ADR 0012's accepted-only recovery authority, immutable revision exports, and constrained early boot guard without separate network success state.
- [x] 2026-09-13 On a disposable Debian 13 VM with console access and independent peers, prove the completed guarded networkd controller: timed revert, out-of-band-equivalent recovery, typed affected-network reachability, explicit confirmation, reboot/controller-interruption recovery, separately approved deletions, dry-run inertness, and idempotence. Evidence: on the checkpointed Debian 13.7 Hyper-V VM, a proof-only veth and separate network namespace completed the real source/interface-bound nonce-bearing bidirectional peer protocol; deliberately withheld confirmation crossed the 60-second deadline and the independently scheduled systemd watchdog restored both candidate files to prior absence and recorded `REVERTED`; fresh confirmed and distinct same-desired-state transactions reached `CONFIRMED`, bound the durable apply commit, and cleaned the terminal journal. A controller interruption immediately after durable `CANDIDATE_APPLIED` was rebooted from boot ID `3957c02f-525d-47bf-ae59-348aec5f5c84` into `7ec74ef6-c6f5-4c1e-9024-763944c81f07`; boot journal evidence showed recovery starting at 8.7s and finishing at 10.3s before networkd started at 10.35s, with both candidate files absent and the journal `REVERTED`. A separate dry-run created no journal, publication, timer, or probe, and an exact approved proof-file removal committed successfully. The installed recovery role reran with `changed=0`; the complete installation identity and scheduled timer verified; the Debian suite passed 1,493 tests with one expected SOPS skip after isolating the helper-chain test from the installed root-only recovery path. `eth0` remained networkd-unmanaged throughout; final state has no proof artifacts or active journal, networkd inactive/disabled, recovery timer inactive/enabled, and `networking.service` active. Live `deimos` proof still requires fresh Phase 6 approval.
- [x] 2026-09-13 Make the full test suite independent of a workstation-local `abhaile` account. Evidence: drift planning now accepts injected UID/GID resolvers while retaining production account lookup and unresolved-identity errors; the real-config integration test uses test-owned numeric identity authority, and final `pytest -q --no-cov` passes all 1,497 tests without a local `abhaile` account.
- [x] 2026-09-28 On a disposable Debian 13 VM with rootless Podman, prove whether a candidate observation transport avoids file creation, storage refresh, user-manager initialization, and socket activation. Evidence: on Debian 13.7 with Podman 5.4.2, the fixed `ROOTLESS_PODMAN` observation returned `PODMAN_TRANSPORT_UNPROVEN` without invoking Podman; before/after fingerprints showed no user storage or configuration directory, no Podman socket, no Podman/conmon process, and no user-manager state change. No independently proven non-initializing Podman transport exists, so the implemented terminal conflict remains authoritative and installed-host active Podman state requires separately authorized operator evidence during Phases 6/7.
- [x] 2026-09-13 On a disposable Debian 13 VM, prove real manifest convergence, failed-state preservation, safe pruning, health gating, and rollback. Evidence: the production Ansible manifest role converged its complete safe publication family plan in real check/first/second-run passes; named-user and network lanes used real manager and peer effects; the 31-case state/coordinator bundle proved failure preservation, exact safe prune, drift refusal, health ordering, blocked admission, and retained-state rollback across every durable finalization boundary. The full Debian suite passed 1,493 tests with one expected SOPS skip.
- [x] 2026-09-13 On a disposable Debian 13 VM with external network access disabled, prove actual offline manifest-only convergence from an already-admitted sealed last-known-good capsule with no Git fetch or checkout invocation. Evidence: a root-created Linux network namespace had only a down loopback device and no route. Inside it, the production offline launcher selected and prepared the already-admitted revision without calling fetch, protected Git retained-LKG admission passed, binary and archive operations proved unchanged/check-mode no-acquisition behavior, and the complete safe publication-family manifest plan converged; all five cases passed in 148.34 seconds.
- [x] 2026-09-13 On a disposable Debian 13 VM, prove cold-boot and degraded Vault, network, rootless user-manager, Quadlet, and runner recovery without Git or Ansible availability. Evidence: after a real reboot, recovery ran from its fixed protected helper at 8.7 seconds and completed before networkd began at 10.35 seconds, with no Git or Ansible dependency. With Vault absent, no runner units installed, and Ansible absent from system `PATH`, the lingered `proof` user manager was active with UID-owned mode-0700 runtime, the installed Quadlet generator responded, and 88 active-discovery, runtime, bootstrap-order, initial-runner-staging, and runner-update degraded/recovery cases passed. The independent network journal restored on changed boot; unavailable Podman observation remains the intentional fail-closed result already recorded above.
- [x] 2026-09-13 After the disposable Debian 13 proof suite, record its evidence against every active migration acceptance criterion and close only criteria supported by commit/PR plus validation references. Evidence: Spec 0028's Phase 5 evidence matrix maps every acceptance criterion to repository/VM validation and its remaining Phase 6/7 gate. No criterion was checked because this worktree has no commit or PR reference, as required by the criterion-closing rule.

### Phase 5.1: Reassess and Simplify the Reconciliation Architecture

Do not begin Phase 6 host adoption until this review is complete and its accepted decisions are
recorded in the authoritative spec and ADRs. The temporary `ARCH_REVIEW.md` brief was removed after
its then-accepted decisions transferred into active Spec 0028 and ADR 0012. Phase 5.2 later found
that model still disproportionate; ADR 0013 and the current Spec 0028 now supersede it.

- [x] 2026-10-04 Establish the minimum threat model, safety properties, and operational requirements that the post-migration design must satisfy. Evidence: ADR 0012 Trust Model and active Spec 0028 Requirements.
- [x] 2026-10-04 Measure the current and projected maintenance surface against the legacy apply implementation and the original Ansible migration objective. Evidence: the completed Phase 5.1 review classified the Phase 1-5 prototype as disproportionate; Spec 0028 requires pre/post complexity evidence and a stop/go comparison with selectively hardened legacy apply.
- [x] 2026-10-04 Inventory every reconciliation, trust, capsule, manifest, transaction, ledger, publication, recovery, and network component; classify each as retain, simplify, replace, transitional, or remove. Evidence: the completed Phase 5.1 module/state map was transferred into the active Spec 0028 Migration Plan and Phase 5.2 deletion tasks before the temporary review was removed.
- [x] 2026-10-04 Compare retaining the current design, substantially simplifying it, and retaining or refining the legacy apply path; include security, recovery, operability, testing, and maintenance costs. Evidence: ADR 0012 Alternatives Considered and Spec 0028's stop-for-review criterion.
- [x] 2026-10-04 Define the smallest coherent target architecture, including whether network convergence remains a separate subsystem and which component owns each durable commit and rollback boundary. Evidence: ADR 0012 and active Spec 0028 define accepted as sole recovery authority, ordinary reconciliation, and the constrained boot guard without an independent network protocol.
- [x] 2026-10-04 Produce an incremental transition and deletion plan that preserves quarantine, rollback, and the live-host safety boundary throughout the overhaul. Evidence: Spec 0028 Migration Plan and Phase 5.2 below.
- [x] 2026-10-04 Test the simplified last-successful reconciliation premise on the disposable Debian VM without using the guarded-network transaction as recovery authority. Evidence: an accepted proof-only networkd manifest `A` converged a dummy interface; an interrupted candidate `B` changed the accepted file and added a candidate-only file without committing apply state; ordinary reconciliation against `A` restored the accepted file but left the candidate-only file and then reported no drift. Supplying only retained `B` manifest context allowed the existing safe-prune classifier to remove the candidate-only file and reach an idempotent `A`. Rendering produced 49 artifacts inside a network namespace with no external connectivity. The installed guarded recovery journal remained empty and could not mask the result. The current runner is not itself offline/boot independent because it is ordered after `network-online.target` and performs a mandatory fetch before reconciliation. All proof artifacts were removed and the VM's original `eth0`, `networking.service`, and empty recovery state were verified. This establishes that normal reconciliation is the recovery mechanism, while a retained candidate export, a minimal pending absent-before record, and an offline-startable runner are still required; real reboot automation remains an implementation proof.
- [x] 2026-10-04 Obtain independent Architect, SysAdmin, and Code Reviewer review of the analysis and proposed target architecture; resolve or explicitly record every objection. Evidence: final independent confirmation on 2026-10-05 approved the corrected interruption, boot-guard, fetch cadence, preview, cleanup, acceptance, retention, and proof contracts with no remaining must-fix or should-fix finding.
- [x] 2026-10-04 Record accepted durable decisions once in Spec 0028 and one consolidated reconciliation ADR; supersede or minimally link Spec 0012 and ADRs 0003/0004/0010/0011 rather than duplicating the architecture across them; update later migration phases and remove `ARCH_REVIEW.md` once its open questions and findings have authoritative homes. Evidence: rewritten active Spec 0028, accepted ADR 0012, superseded Spec 0012 and ADRs 0010/0011, refined links from ADRs 0003/0004, updated Phases 6/7, and removal of the temporary review on 2026-10-05.
- [x] 2026-10-04 Complete an explicit Phase 5.1 go/no-go review before provisioning, installing, or converging anything on `deimos`. Evidence: the user accepted ADR 0012's simplified target, the decisions were transferred into active Spec 0028, repeated coherence and operability reviews ended with a clean pass on 2026-10-07, and Phase 6 remains blocked behind Phase 5.2 implementation and proof.

The review must begin from requirements rather than treating the Phase 1-5 implementation as the
required end state. Passing tests and disposable-VM evidence establish behavior of the current
design; they do not by themselves establish that its complexity is proportionate. Prefer deletion
and consolidation where the same security property can be provided by a smaller, conventional,
and independently understandable mechanism. Do not weaken the root/service-account trust boundary,
dry-run default, explicit destructive approval, offline recovery, or live-network recovery merely
to reduce line count.

### Phase 5.2: Implement and Prove the Simplified Reconciliation Model

Begin only after Phase 5.1 decisions are accepted in Spec 0028 and the applicable ADRs. Keep
Ansible convergence quarantined and the legacy apply path authoritative throughout this phase. All
mutation and reboot evidence is limited to the disposable Debian VM; nothing here authorizes access
to or mutation of `deimos` or `phobos`.

The reviews after the initial Phase 5.2 implementation began found that its accepted/pending/bundle/
launcher design still retained too much of the platform it was meant to remove. ADR 0013 and the
current tasks below supersede that target. Spec 0028 remains the authoritative acceptance contract;
`PHASE_5_2_DISPOSITION.md` is reporting-only.

Execute work through these dependency stages:

1. Restore the Phase 0 authoring and render boundary.
1. Delete the unused Phase 1-5 platform before adding replacement behavior.
1. Replace only the legacy mutation backend with conventional Ansible roles.
1. Evolve the existing runner's last-successful loop and add the minimum crash marker.
1. Add the smallest pre-networkd restoration of last-successful network state.
1. Prove the complete flow on the disposable Debian VM.
1. Align durable documentation and later phases, then complete the Phase 5.2 go/no-go review.

#### Current Phase 5.2 tasks

- [x] 2026-10-08 Restore the 11 changed `config/hosts/**/software/**/*.yaml` files and `schemas/software-action.schema.json` exactly to their Phase 0 (`ea888fb`) contracts. Preserve the complete gasket/Coral and other declared command sequences; do not redesign or execute them in this migration. Evidence: all 11 parsed YAML documents are equal to `ea888fb` (the formatter only wraps two gasket command scalars), the schema is byte-identical, host-software schema validation passes, and the full original command sequences are retained.
- [x] 2026-10-08 Keep `rendered/software/` deterministic but render-only and outside `manifest.json` and Ansible convergence. Defer packages, downloads, builds, commands, and gasket packaging to separately specified later functionality. Evidence: two independent complete renders of both hosts are byte-identical; software artifacts exist under `rendered/software/` and no `software/` entry occurs in either emitted manifest; 1,338 unit tests and 35 focused renderer/integration tests pass.
- [x] 2026-10-08 Retain Phase 0 `manifest.json` as the sole inventory for resource families the legacy apply actually manages. Revert the Phase 3 target-path normalization unless separate evidence proves a legacy defect. Evidence: manifest v1 is the sole emitted inventory; directory target paths again preserve their Phase 0 trailing-slash semantics; the unused manifest-v2 execution-identity field and users-renderer producer are removed; and two complete renders of both hosts are byte-identical.
- [x] 2026-10-08 Remove `convergence-manifest.json`, manifest v2, execution identities, typed software operations/effects, exact-cover compilation, generic dispatch, and tests that exist only for those contracts. Evidence: render emits only deterministic manifest v1; the typed software model and taxonomy, convergence renderer, protected compiler/plan, complete trust caller closure, generic Ansible role, parallel validators, custom modules, and dedicated tests are deleted; `converge.yml` is fail-closed; no surviving production/test reference remains.
- [x] 2026-10-08 Retain only independently useful deterministic-render fixes: no authoritative timestamps and no ambient Git/date dependency in DNS validation. Align affected accepted specs, fixtures, and compatibility readers. Evidence: manifest v1 omits `rendered_at`; DNS serial validation computes and reports the declared serial's deterministic content hash without Git or clock access; focused tests and the 831-test repository suite pass; final accepted-spec compatibility remains part of the documentation audit.
- [x] 2026-10-08 Delete Phase 1-5 trust and transaction machinery by default: protected mirror/capsules, copied runtime and renderer containment, bespoke discovery, constrained sudo candidate, runner-LKG/health challenges, coordinator/publication authority, and guarded-network journals/probes. Retain a component only when a named surviving requirement lacks a simpler existing-project or Ansible mechanism. Evidence: the complete 39-module trust package, 35-module trust test package, quarantine harness, protected launcher/peer/recovery scripts, recovery installation role/units, constrained sudo candidate, and obsolete package entry point are removed; no surviving application module imported the package.
- [x] 2026-10-08 Preserve the existing trusted `abhaile` account, clone, credentials, virtual environment, runner service/timer, bootstrap path, host identity, lock, and privilege model during this migration. Do not add a root launcher, second clone, immutable export store, new renderer identity, accepted/pending/rejected ledger, render ABI, preview cache, or replacement installer. Evidence: obsolete copied-runtime paths and installers are deleted; the retained `/opt/abhaile` clone, virtualenv, service/timer, bootstrap, sudo model, and runner `flock` remain the only execution foundation; repository-wide caller scans find no replacement platform.
- [x] 2026-10-08 Replace only the legacy Python mutation responsibilities with dependency-ordered Ansible roles driven by `manifest.json`. Prefer built-in modules and handlers; justify each custom module against a concrete missing safety property. Evidence: every current manifest-v1 kind is selected exactly once by the fixed orchestrator and handled by direct roles using built-in modules plus installed native validators; unsupported destructive behavior remains explicit residue or maintenance-gated. Focused suites and the complete disposable-VM matrix prove publication, activation, readiness, drift repair, supported removal, failure recovery, and cleanup with zero custom Ansible modules.
  Historical implementation detail retained for review:
  Runtime correction: disposable-VM proof found that `state: started` does not reload a changed
  active oneshot unit: a valid `/bin/false` definition was published but the old active instance
  remained accepted. The rootful role now `try-restart`s a changed unit that declares activation,
  while retaining explicit restart modes and leaving unchanged runs undisturbed. Repeating the
  real-systemd proof failed at that restart, returned non-zero, reconciled the old last-successful
  revision, and restored the service.
  Completeness review: the ordinary service-config role now also covers the structurally identical
  `service.env` kind present on Phobos; all current manifest-v1 file kinds now have an explicit
  direct-role selection. A fixed manifest-v1 orchestrator now partitions the complete inventory,
  invokes explicit family roles in dependency order, and scopes service/Caddy calls by owner
  without a generic dispatcher. A repository-only reconciliation playbook now drives that same
  orchestrator in check or normal mode: check mode needs no mutation authorization, while normal
  mode requires an explicit Boolean live gate. Syntax, authorization, wrong-host, and empty
  check/normal paths pass through a closed Ansible environment. The existing runner now invokes
  this playbook through check mode and an explicit live gate. The later disposable-VM matrix
  completed the non-empty proof; the uncommitted path remains disabled on both live hosts.
  Final proportionality correction: the direct host-access role and its tests were removed.
  Ordinary orchestration now validates only the fixed bootstrap/adoption-owned sysusers,
  authorized-keys, and sudoers targets; it cannot mutate or remove them. Explicit enrollment and
  independent-administrator gates own those foundations. A disposable-VM check of the complete
  real Deimos manifest stopped before publication because the blank proof host lacked both the
  generated `coredns-omada-build.service` and `/usr/local/bin/coredns` produced by the existing
  software/build flow. Check mode left no managed file, validation scratch, runner marker, or
  network impact. This confirms that Phase 6 existing-host assessment must verify those adopted
  prerequisites; Phase 5.2 must not weaken native validation or turn recurring reconciliation into
  a second bootstrap/software installer merely to make a blank-host full-manifest check pass. The
  same review found a real check-before-live defect for files whose manifest-managed parent was new
  in the same revision: Ansible check mode predicted directory creation but `copy` then rejected the
  still-absent parent. Service roles accept only exact manifest-declared missing parents. The Vault
  role additionally models the immediate parent that native creation of an exact declared child
  directory will create, plus its fixed role-owned Quadlet directory; unrelated parents remain
  fail-closed. Both roles report planned drift without publication and retain ordinary built-in
  directory/copy ordering for live runs. Isolated service/Vault suites and the production
  orchestration suite prove new-directory publication without creating either path in check mode.
  Disposable-VM check mode then passed the real Deimos managed-build projection (`changed=1`) and
  complete Vault projection (`ok=48 changed=4 failed=0`), including Podman's installed rootless
  Quadlet generator and the Phase 0 Vault parent layout; no `config/` change or generic staging
  layer was introduced. Isolated live Quadlet proof on the same Debian 13 VM then used one
  disposable BusyBox image in each Podman store. Rootful and `abhaile` user-manager paths each
  passed non-mutating check mode, first publication/activation, `changed=0` reconciliation,
  deliberate stopped-unit repair without republication, and active-container verification. Exact-
  hash rootful candidate cleanup preserved the unit in check mode, stopped and removed it live,
  and was retry-safe. That proof exposed systemd's retained failed-state residue after generated-
  unit removal; the role now runs the one missing native operation, fixed-argv `systemctl reset-failed`, after daemon reload. Its retry completed `changed=0` with the unit
  `not-found/inactive/dead`. Rootless cleanup remained explicitly operator-owned. All proof
  Quadlets, containers, images, runtime paths, and scratch were removed afterward.
  Caddy VM proof found two runtime defects before cutover. Read-only container-existence and native
  candidate-validation commands were initially skipped by Ansible check mode; both now explicitly
  run without mutation. Atomic Caddyfile replacement then left the running container's single-file
  bind mount attached to the old inode, so an in-container reload reported success while continuing
  to serve the baseline. Changed Caddy publication now uses an ordinary systemd restart to remount
  the new inode before the existing active-state check; unchanged runs remain undisturbed. The
  corrected VM run changed the served response from `baseline` to `candidate`, followed by a
  `changed=0` pass. A separately hashed invalid candidate failed native Caddy parsing with
  `changed=0`, identical live hash, and the candidate response still served. Cleanup removed the
  unit, container, image, runtime path, and scratch. The cleanup also showed that
  `systemctl reset-failed` returns generic status `1` for a fully unloaded unit; rootful Quadlet
  cleanup now observes `ActiveState` after daemon reload, resets only units that remain `failed`,
  and skips missing units that are already `inactive`, without accepting ambiguous command
  failures.
  CoreDNS VM proof passed non-mutating check mode, first publication, unchanged reconciliation,
  and zone-only reload through the real service and watcher. It changed the answer from
  `192.0.2.10` to `192.0.2.20`, then to `192.0.2.30` without restarting for the zone-only update. A
  correctly hashed malformed zone failed native `named-checkzone` validation with `changed=0`
  before watcher shutdown or publication while preserving the live hash, answer, and active units.
  A separate managed-build fixture passed check, first, and unchanged runs; owner-configuration
  change with an unchanged `.build` file reran the completed oneshot, advanced its output-image
  label, and restarted its consumer. The bounded post-build install unit produced and verified a
  regular executable. Both fixtures were removed completely, including units, files, images,
  containers, listeners, binaries, and scratch.
  A manual pod-member fixture then passed check, first live activation through its parent pod, and
  an unchanged `changed=0` run. Changing only the member restarted the unchanged parent, recreated
  the member container, and exposed the new environment value. Cleanup check mode preserved both
  files and runtime objects. The first live cleanup exposed that pre-removal unit state could not
  safely decide post-reload failed-state cleanup: a generated unit may unload, while a removed
  member may retain a real failed state. The role now observes post-reload `ActiveState`, resets
  only `failed` units, and skips `inactive` missing units. Absent retry, residue repair, and a fresh
  recreate-and-cleanup cycle all succeeded; final units were `not-found/inactive/dead` with
  `Result=success`, and all proof Quadlets, Podman objects, images, and scratch were removed.
  Forward desired-state removal now uses the same exact-identity classifier as interrupted-
  candidate cleanup: changed revisions render last-successful once, compare candidate desired state
  against that prior manifest, and pass supported prior-only resources to existing direct cleanup
  roles. Unchanged drift reconciliation retains one render. Drifted bytes and incomplete identities
  fail before Ansible and before the mutation marker; unsupported family routing fails in Ansible
  check. Focused runner tests prove successful service-file removal, pre-mutation drift refusal, and
  recreation from last-successful after a later candidate failure. This added no journal, ledger,
  operation model, role, or custom module. Directories and Caddy candidate residue retain their
  existing inert-residue policy; Vault/rootless, drop-in, persistent Podman-object, and other
  destructive removals remain fail-closed or maintenance-gated pending an explicit family need.
- [x] 2026-10-08 Keep legacy apply authoritative until Ansible proves parity. Preserve dry-run by default and explicit live-apply authorization; remove the dead `--ansible` selector and migration-only compatibility when their callers are gone. Evidence: legacy `abhaile-apply` remains unchanged and authoritative; the dead selector and error-only compatibility are removed; the new playbook defaults to check mode and requires an explicit Boolean live gate, and no live-host service has been enabled against the uncommitted implementation.
- [x] 2026-10-08 Evolve the existing runner around `last-successful-commit`, `current-run`, `failed-target`, its local clone, and existing `flock`; do not duplicate those facts in another ledger.
  Evidence: an isolated state helper reuses all three existing filenames and assumes the existing
  runner lock; it introduces no lock or ledger. It reads the existing metadata-suffixed
  last-successful and failed-target records, writes strict SHA-only records atomically, rejects
  symlinks and malformed authority, and compare-clears previously observed suppression state. The
  existing runner now uses that helper under its existing lock; mutable phase diagnostics no longer
  occupy `current-run`. It renders into one run-scoped transient directory, invokes the fixed direct
  Ansible playbook, and reuses no second lock or ledger. Disposable-VM proofs exercise ordinary,
  interrupted, committed-but-uncleared, malformed, missing-baseline, unavailable-revision, lock-
  contention, early-network, and fetch-outage paths without another state authority.
- [x] 2026-10-08 Define one minimal marker written immediately before the first managed-state mutation. A crash before it must not trigger rollback; while it differs from `last-successful-commit`, restart must render and reconcile the old last-successful revision. Clear it only after proving it equals the durable last-successful revision.
  Evidence: strict SHA-only marker publication, legacy-compatible last-successful reading, direct
  startup classification, verified success advancement, and matching-marker cleanup are implemented
  and wired into the existing runner. Deterministic render, cleanup classification, and Ansible
  check mode complete before the marker is published immediately ahead of the only live Ansible
  invocation; a failure before that boundary suppresses the candidate without an unnecessary
  last-successful reconciliation. Per-run entrypoint rewriting was removed as redundant because
  bootstrap owns the fixed wrappers. Success advances last-successful before clearing the marker.
  Recovery preserves the interrupted candidate marker while applying the old last-successful
  revision so a second interruption retains candidate-only cleanup authority. It clears only that
  exact observed marker after successful recovery and never advances last-successful. Disposable
  candidate `d7de3e5` was killed after publication and before daemon reload; startup restored both
  file and manager state from old last-successful, then cleared the marker only after successful
  reconciliation. Focused interruption/retry coverage proves the original candidate cleanup
  context survives a failed recovery attempt.
- [x] 2026-10-08 Make ordinary reconciliation local-first: recover interrupted work first; fetch only to discover a newer desired commit; reconcile unchanged desired state to repair drift; on fetch failure reconcile last-successful from local Git objects; retain existing failed-target suppression without adding a retry protocol.
  Evidence: the existing runner now performs each control-flow branch above, refuses unattended
  mutation without an established last-successful baseline, while successful explicit bootstrap
  apply records and verifies the initial exact baseline before runner registration. It preserves failed-target across
  successful recovery, avoids duplicate recovery within one invocation, and returns non-zero for a
  failed candidate even when last-successful recovery passes. Focused integration tests exercise
  unchanged drift, offline recovery, interruption-before-fetch, suppression, correction, lock
  contention, check-mode failure, and live-call ordering. They also prove that a candidate which
  mutates a managed effect and then fails live apply is followed by exactly one check and live
  reconciliation of the old last-successful revision; the effect is restored, last-successful is
  unchanged, the candidate is rejected, and the pending marker is cleared. The runner's legacy
  apply/local-health backend is replaced by the direct Ansible playbook and its local-acceptance
  role. Disposable-VM execution with a deliberately nonexistent one-shot remote reconciled
  `c4daabe` entirely from retained local objects through real Ansible check and live paths, returned
  success, retained last-successful, created no marker or failed-target, left networkd active, and
  left the checkout clean.
- [x] 2026-10-08 Retain enough interrupted-candidate manifest context to remove candidate-only additions during recovery. Remove only Abhaile-managed paths or units whose live identity still matches the candidate; stop on ambiguity or irreversible effects. Do not add an execution replay graph or absent-before journal.
  Evidence: the existing manifest planner now compares an exact last-successful manifest with an
  interrupted-candidate manifest, requires the same host and unique targets, considers only targets
  absent from last-successful, and classifies matching regular-file bytes, already-missing paths,
  and blocked drift/non-regular/directory identities without authorizing deletion. Live inspection
  uses `lstat`, so dangling symlinks cannot masquerade as missing. Recovery now checks out and
  deterministically regenerates both the exact interrupted-candidate and last-successful manifests
  inside its run-scoped transient directory, stops before mutation on blocked evidence, and passes
  only matching entries to Ansible. The first vertical removal family is now
  complete for `service.config` and `service.env`: the fixed orchestrator accepts only matching
  cleanup evidence for those kinds, folds cleanup-only owners into its existing batches, rechecks a
  regular file's SHA immediately before `state: absent`, supports check mode, rejects desired/cleanup
  overlap or mixed runtime context, and reuses the single owner restart/readiness boundary.
  Candidate-only CoreDNS zones now use the same pattern inside the existing watcher-safe batch and
  trigger its single CoreDNS reload; the required Corefile remains non-removable. Candidate-only
  ordinary rootful `.service`, `.path`, `.timer`, and `.socket` unit files are stopped and disabled,
  but only after an in-role identity check; they are checked again immediately before removal and
  included in the role's single daemon-reload boundary. Runner units remain reserved. Drop-ins,
  resolved configuration remain fail-closed until their ordinary roles own the necessary
  dependency-aware lifecycle. Candidate-only rootful Quadlets are stopped in reverse order,
  identity-rechecked, removed, and included in the role's existing daemon-reload boundary.
  Rootless Quadlet removal remains fail-closed, while Podman objects/build outputs and
  candidate-only service directories or Caddy files may remain honest inert/irreversible residue.
  Candidate-only networkd files are selected only from the
  network kinds, constrained beneath `/etc/systemd/network`, bound to their interface filename, and
  rechecked immediately before removal. Candidate-created network directories remain as inert
  residue rather than being recursively removed without complete content identity.
- [x] 2026-10-08 Use the existing health boundary as the single commit gate: after Ansible and bounded local checks pass, atomically update `last-successful-commit`; otherwise reconcile the old last-successful revision. Keep external observations diagnostic and software/irreversible effects deferred or maintenance-gated.
  Evidence: direct roles synchronously verify the candidate-controlled units and services they
  activate. After networkd changes, `local_acceptance` derives the canonical physical management
  interface and address from host/network intent, requires that interface online, and requires a
  structured kernel route lookup for the services gateway to select the exact interface and source.
  Check mode validates intent without executing either command. The runner treats successful live Ansible completion,
  including this role and synchronous family readiness checks, as the sole local commit gate before
  atomically advancing `last-successful-commit`. Failure after the marker reconciles the old
  last-successful revision. The broader legacy health CLI is retained only for the optional,
  non-fatal `--cluster` diagnostic pending its final legacy disposition. Disposable candidate
  `8f518cc` failed a real system-manager check after mutation and reconciled `c4daabe`; the
  interrupted `d7de3e5` publication likewise recovered without advancing last-successful.
  Disposable-VM evidence on 2026-10-10 showed that the Hyper-V gateway had a valid route and
  reachable neighbour while refusing ICMP, even though external ICMP and SSH remained healthy.
  The literal gateway ping therefore had a false-failure mode and was replaced by the bounded local
  management-path checks above. ICMP, ARP, SSH, Internet, and peer observations remain diagnostics;
  no configurable probe framework was added.
- [x] 2026-10-08 Add only a small pre-networkd mode to the existing runner. Under the same lock, it reads local last-successful/interruption state, renders from retained local Git objects, and applies only the last-successful network role before networkd. It owns no separate journal, timer, probe protocol, success state, or remote dependency.
  Evidence: `abhaile-runner --restore-network` now acquires the existing lock, performs no fetch,
  and exits successfully without inspecting the checkout or toolchain unless `current-run` differs
  from `last-successful-commit`. For that interrupted state it
  renders the exact interrupted candidate only when needed for cleanup evidence, renders the exact
  last-successful revision, and invokes a dedicated network-only playbook. The playbook restores
  last-successful networkd files and removes only matching candidate-only network files; it skips
  `networkctl` because networkd has not started. The mode does not write or clear runner authority.
  Disposable-VM proof at VM-local accepted revision `c4daabe` exercised an interrupted candidate
  whose live network file differed from last-successful. After reboot, the early service rendered
  both retained revisions, restored the accepted bytes, and completed successfully before networkd
  started and configured `eth0`; ordinary reconciliation then restored full state and cleared the
  marker without advancing last-successful. A separate inert candidate `e342db8` added one
  candidate-only `.network` file; early check and live recovery revalidated its exact hash, removed
  only that file, and did not contact the running networkd manager. Focused runner coverage proves that
  malformed `current-run` or `last-successful-commit` authority exits before Ansible without a
  traceback, and that an interrupted enrollment with no last-successful baseline preserves its
  marker and performs no mutation. Disposable-VM execution with a malformed `current-run` produced
  the expected concise `ApplyError`, failed the enabled restore oneshot before Ansible, left
  networkd active, and returned to a successful no-op after exact fixture removal. A second
  disposable-VM proof removed only a protected backup of last-successful while retaining a valid
  interruption marker: early restore failed without mutation, preserved the marker, invented no
  baseline, and left networkd active. Restoring the exact baseline and removing the fixture returned
  the oneshot to a successful no-op; original diagnostics were restored and no proof state remained.
- [x] 2026-10-08 Audit bootstrap and systemd ordering so ordinary reconciliation runs without `network-online.target`, early network restoration cannot race it, and no second installer or scheduler is introduced.
  Evidence: the existing common host composition now renders one installation-owned
  `abhaile-network-restore.service` before the existing runner service. It has no ordinary
  reconciliation enable/start hint. Fresh bootstrap and the explicit existing-host adoption path
  enable its effective `RequiredBy=systemd-networkd.service` relationship only after validating a
  last-successful baseline; both verify the installed dependency and boot ordering before allowing
  network-backend adoption. The early service runs the existing runner's
  `--restore-network` mode before networkd, while the ordinary runner is ordered after both the
  restore service and networkd and no longer waits for `network-online.target`. The existing timer
  remains the sole scheduler and bootstrap still enables only that timer. Manifest orchestration
  treats the restore service, runner service, and runner timer as one closed installation-owned
  inventory rather than asking ordinary Ansible reconciliation to replace or remove itself.
  Disposable-VM installation, cutover enablement, and reboot proof now show the early oneshot
  completing before networkd starts, with the ordinary runner remaining after both units. An
  intentionally mis-owned proof marker also demonstrated fail-closed dependency behavior and the
  documented console repair path; it was a proof-fixture error, not runner-produced state. Lock
  contention returned exit 2 before work, while malformed and missing-baseline state made the
  required early oneshot fail without disrupting the already-running network and recovered cleanly
  after exact fixture removal.
- [x] 2026-10-08 Use ordinary Ansible facts, fixed read-only commands, and an operator checklist for existing-host assessment; delete the bespoke discovery/classification framework. Evidence: `discovery.py`, `active_discovery.py`, their classifiers, collectors, callers, and dedicated tests are deleted; the bootstrap guide and Phase 6/7 tasks retain explicit existing-host and independent-administrator assessment gates without another discovery model.
  Progress: the bespoke discovery and five-way classification implementation was removed with the
  Phase 1-5 trust package. The bootstrap guide now defines one operator-owned, read-only assessment
  using ordinary Ansible platform facts plus fixed observations of the account, sudo policy,
  checkout, virtual environment, runner units, rootless manager, Podman, networkd state, and
  SHA-shaped runner records. It separately proves independent administrator and recovery access
  before any automation-account policy change and treats remote Git authentication as discovery,
  not local recovery authority. It deliberately creates no classifier, report schema, host ledger,
  or mutation playbook. Disposable-VM execution and the later existing-host adoption proof remain
  open, so this item is not complete.
- [x] 2026-10-10 Keep Debian network-backend adoption outside the recurring runner: fresh bootstrap must require networkd/resolved enablement; an explicit operator playbook must publish and validate networkd, enable it, and only then disable—but not stop—the legacy backend for the next boot. Preserve interfaces files, ifupdown packages/hooks, and resolver ownership until separately reviewed; require console access and successful reboot proof before adoption is complete. Evidence: disposable-VM proof through VM-local revision `c4daabe` and focused repository tests.
  The disposable VM first booted with `eth0` down after `networking.service` was disabled while
  networkd was active but not enabled. Console execution of `systemctl enable --now systemd-networkd.service` immediately restored `172.22.190.118/20` and the expected default
  route. A second reboot returned automatically; the early restore no-op completed before enabled
  networkd configured the same static address. Candidate-bound playbook proof then exposed and
  corrected skipped acceptance for unchanged network files. Check mode validated canonical intent
  without mutation; ordinary reconciliation refused an enabled legacy backend; live adoption ran
  real interface and structured route/source checks before disabling it; an invalid proof-only
  source address failed while preserving legacy enablement and the live network; a second live run
  reported `changed=0`; and reboot returned with restore-before-networkd ordering. The installed
  runner accepted the state-neutral correction as last-successful `c4daabe`; proof scratch and
  mutation/failure markers were absent afterward. Interfaces files, ifupdown packages/hooks, and
  resolver ownership remain intentionally preserved for separate later disposition.
- [x] 2026-10-08 Prove on the disposable Debian 13 VM with its real systemd and user managers, systemd-networkd, Podman/Quadlet generators, and installed validators: first enrollment success and blocked/failed/interrupted enrollment; correct- and wrong-host inventory binding; first, unchanged, and drift-repair runs; candidate success; validator failure before mutation; apply or family-local runtime-check failure recovery; interruption before the mutation marker, during publication, after mutation, after family-local runtime checks, and after last-successful update; candidate-only cleanup; failed-target suppression; fetch outage with retained local Git objects; missing, malformed, and mismatched runner records or recovery revisions; lock contention; real service activation/readiness; reboot before networkd and local network restoration; idempotence; check-mode non-mutation; and proof cleanup. Evidence: the scenario record below covers each durable boundary and representative family; the final real-systemd forward-removal/failure proof retained the accepted SHA, restored its active unit, cleared the marker and failed-unit residue, and exact teardown left no proof namespace while networkd and SSH remained active.
  Progress: on 2026-10-10 the VM proved explicit initial-baseline establishment, changed success,
  unchanged idempotence, ordinary drift repair, interrupted candidate-only systemd cleanup,
  last-successful retention, current-run clearing, and failed-target suppression using real systemd
  and Ansible. It also found and regression-tested three fail-closed defects before production use:
  ordinary rootful-systemd and networkd manifest files may omit optional `apply_hints`; live
  authorization must reach Ansible as a JSON Boolean; and network recovery must permit a verified
  cleanup-only selection when accepted has no network files. A healthy Hyper-V network exposed the
  gateway-ICMP false failure described above. Recovery of that failed candidate also proved that a
  fix present only after the accepted revision cannot repair recovery executed from the older
  accepted roles; boot-runtime/update compatibility therefore remains a real gate. The first
  backend-adoption reboot then exposed missing persistent networkd enablement and left `eth0` down.
  After console enablement, the static address and route returned immediately, and a second reboot
  proved automatic network return plus restore-before-networkd ordering. The explicit adoption
  playbook subsequently proved check-mode non-mutation, refusal of implicit adoption, mandatory
  acceptance even for unchanged bytes, failure-before-disablement, live idempotence, reboot, clean
  scratch teardown, and state-neutral acceptance as VM-local `c4daabe`. A later reboot staged
  candidate `4c03693` with distinct live network bytes while retaining `c4daabe` as last-successful.
  The early service restored the accepted hash before networkd started; ordinary reconciliation
  then cleared `current-run`, left last-successful at `c4daabe`, and returned an unchanged full
  apply. The proof-only branch, refs, and render scratch were removed. A review of that execution
  also removed a redundant second reconciliation when fetch still selects the revision already
  restored during startup; the focused integration suite proves that optimization because the VM
  intentionally remained on accepted `c4daabe`. A separate `e342db8` fixture proved exact-identity
  candidate-only network cleanup in both check and live early recovery. The proof-only branches,
  refs, files, and scratch were removed. Real lock contention returned exit `2` before work, and a
  valid-but-unavailable interrupted SHA failed before Ansible, preserved its marker and live network
  hash, and was then removed through the exact state helper. Malformed records now produce one
  concise domain error rather than a Python traceback, with focused runner tests. A VM state with
  `current-run == last-successful-commit` proved the interruption after durable success but before
  marker removal: startup selected `verify-committed`, reconciled the accepted revision, and
  cleared the marker. Focused coverage proves the simplified runner does not repeat that completed
  recovery after fetch. A focused live-failure regression additionally proves candidate check/live
  ordering followed by old-LKG check/live reconciliation, restoration of a simulated managed
  effect, unchanged durable LKG, failed-target publication, and marker clearance. The remaining
  matrix stays open. A real proof-service candidate initially exposed that changed active oneshot
  definitions were not restarted and could be incorrectly accepted. After the direct systemd role
  was corrected to `try-restart` changed activation-managed units, candidate `8f518cc` failed at
  the real manager, the runner reapplied `c4daabe`, returned non-zero, and left the original service
  active. A final unchanged pass cleared failed-target; checkout, private origin, LKG, service,
  networkd, and temporary proof state were all restored to the clean `c4daabe` baseline. A separate
  native-validator proof first established that systemd warning-only diagnostics are not a failure
  contract and must not be reimplemented as custom grammar. Candidate `0f0aa8c`, whose unit named a
  missing executable, then failed `systemd-analyze verify` during Ansible check: runner exit was
  non-zero, the live unit hash and `c4daabe` LKG were unchanged, no current-run marker or recovery
  pass occurred, and the exact failed target was suppressed. Restoring the private ref and running
  unchanged `c4daabe` cleared suppression and left the VM clean. Installed first-enrollment proof
  then removed only a protected backup of the LKG: routine reconciliation refused before fetch or
  Ansible with no baseline; adding `current-run=c4daabe` produced `recovery-blocked`, preserved the
  marker, and made the explicit enrollment helper refuse to overwrite authority. After explicit
  exact marker cleanup, the helper established and verified `c4daabe` as mode-0600 LKG and startup
  classified `normal`. The original LKG and diagnostic files were restored byte-for-byte; focused
  runner coverage now locks the no-baseline and interrupted-enrollment branches. A proof-only
  candidate `d7de3e5` then paused immediately after atomically publishing changed proof-service
  bytes and before daemon reload. After both candidate bytes and `current-run` were observed, its
  disposable systemd cgroup was killed; every descendant stopped and the shared lock became
  available while LKG remained `c4daabe`, current-run retained the candidate, and failed-target was
  absent. Ordinary runner startup rendered the interrupted manifest, reconciled `c4daabe` exactly
  once, restored both file and manager state, cleared current-run, suppressed the candidate, and
  returned non-zero. An unchanged accepted pass cleared suppression; the transient unit, commit,
  refs, logs, and scratch were removed and the VM was verified clean. A later forced fetch outage
  used a nonexistent one-shot remote without changing clone configuration; the runner reconciled
  retained `c4daabe` through real check/live Ansible, returned success, kept authority unchanged,
  and left no marker, suppression, checkout drift, or network impact. A real Deimos manifest
  invoked with expected host `phobos` then exited `2` with `changed=0` at the manifest-envelope
  assertion after only three read-only tasks. No family selection, native validator, publication,
  or runtime action ran, proving wrong-host inventory binding fails before mutation. Recovery tests
  now explicitly model candidate-managed effects remaining after live reconciliation but before
  success commit: with `current-run=candidate` and `last-successful=old`, startup reapplies only the
  old revision, removes the candidate effect, preserves old authority, suppresses the candidate,
  and clears the marker. This one durable state covers interruption during publication, after
  mutation, and after family-local readiness but before success commit without a phase journal.
  The existing `current-run == last-successful` proof covers interruption after durable advancement
  and before marker removal. Isolated CoreDNS proof then exercised the installed validator and real
  system manager: check mode predicted publication without mutation; the first live run published
  the Corefile and zone, restarted CoreDNS, restored its watcher, and changed the answer from
  `192.0.2.10` to `192.0.2.20`; the repeat was `changed=0`. A zone-only candidate used reload rather
  than restart and served `192.0.2.30`. A correctly hashed malformed zone passed manifest identity
  checks but failed native `named-checkzone` validation with `changed=0` before watcher shutdown or
  publication, preserving the live hash, answer, service, and watcher. Exact teardown removed and
  verified absence of its units, configuration, extracted binary, image, listener, and all proof
  bundles. An isolated rootful Quadlet managed-build fixture then passed check mode, first live
  build, and an unchanged `changed=0` rerun. Its generated oneshot completed successfully to
  `inactive/dead`; a declared owner-configuration trigger with an unchanged `.build` file rebuilt
  the image from label `v1` to `v2` and restarted its consumer. A second trigger exercised the
  bounded post-build install unit, verified its regular executable, advanced the image to `v3`,
  and retained an active consumer. Exact teardown removed and verified absence of the generated,
  consumer, and install units; Quadlet; artifact; output and base images; containers; and proof
  bundle. A manual pod-member fixture passed check mode, first activation through its parent pod,
  unchanged reconciliation, member-only change with parent restart and container recreation, and
  non-mutating cleanup check mode. Live cleanup exposed and corrected post-reload systemd
  failed-state handling; absent retry, residue repair, and a fresh recreate-and-cleanup cycle all
  passed. Final units were clean `not-found/inactive/dead`, and exact teardown removed the
  Quadlets, pod, member container, base image, and proof files. Repository integration now proves
  forward desired-state removal, pre-mutation drift refusal, and failed-removal recreation through
  the runner. A narrow Debian 13 real-systemd runner proof then rendered the accepted manifest as
  removal context, removed an exact-matching active unit, advanced last-successful, restored and
  accepted the unit, and deliberately failed a later candidate after removing it. Recovery kept the
  prior accepted SHA, cleared `current-run`, removed the failed candidate unit, and recreated and
  reactivated the accepted unit. The first recovery exposed ordinary systemd failed-state residue:
  the removed candidate was `not-found` but remained `failed/exit-code`. The existing rootful
  systemd role now mirrors the proven Quadlet lifecycle by observing `ActiveState` after daemon
  reload and invoking fixed-argument `systemctl reset-failed` only for `failed` removed units. The
  retry finished with the failed unit `not-found/inactive` and `Result=success`. No additional
  interruption-boundary fixtures are required because they collapse to the already-proven marker
  states. Exact teardown left both proof units `not-found/inactive` with `Result=success`, removed
  the proof source, state, archive, and temporary static-network backup, preserved active networkd
  and SSH on the DHCP address, and confirmed the production runner had no `current-run` marker. The
  disposable-VM execution matrix is complete pending final evidence reconciliation.
- [x] 2026-10-08 Recount complexity and durable state after deletion. Review every surviving Phase 0-5 addition for a live caller and proportionality; stop for a new go/no-go if Ansible is not materially simpler than selectively retaining legacy apply. Evidence: the reproducible post-overhaul recount in `PHASE_5_2_DISPOSITION.md` records production Python falling from 29,201 to 14,687 lines, the reviewed type surface from 70 dataclasses/12 enums/9 protocols to 1/0/0, and all 39 trust modules, custom Ansible modules, generic operation tasks, parallel operation validators, prototype durable-state families, protected refs, journals, and transition vocabularies removed. The surviving 600-line runner and 194-line state helper reuse one existing lock and three established records; the final complete-worktree delta is recorded in the disposition report.
- [x] 2026-10-10 Before pushing to any branch polled by a live host, review the complete tracked and untracked Phase 5.2 diff; prove that `config/` retains its intended Phase 0 semantics; run the complete repository validation suite; confirm exactly how the deployed legacy runner handles the pushed revision while Ansible remains fail-closed; and record the exact reviewed revision. Treat a non-polled review branch and a host-polled branch as different operational risk boundaries. Do not push to a polled branch or enable new behavior merely to gather missing repository or disposable-VM evidence. Evidence: Phase 0 config semantics and the complete working-tree disposition were reviewed; all 976 repository tests passed without coverage, all staged/all-files pre-commit hooks passed after formatter stabilization, docstring coverage passed at 99.6%, and `git diff --check` passed. Push-risk review proves a direct push to polled `main` would be a cutover: the running legacy process would fetch and legacy-apply the revision, publish the new runner and inactive restore unit, then the next timer invocation would execute direct Ansible. The reviewed one-writer guide therefore keeps proof on an exact non-polled ref with scheduling stopped, establishes exact recovery authority only after successful explicit legacy apply, and defines exact accept/reject promotion and restoration. The clean amended checkpoint was inspected with `git show --check`; its exact SHA is recorded in the handoff. No push or live enablement occurred.
- [x] 2026-10-08 Align Spec 0028, ADRs, accepted-spec drift notes, runbooks, and Phases 6-8 with the implemented model; obtain Architect, SysAdmin, and Code Reviewer approval before live-host work. Evidence: current architecture, legacy-apply reference, bootstrap/adoption guidance, operations, ADR 0013, active Spec 0028, accepted Spec 0008, and Phases 6-8 describe the implemented last-successful model; superseded ADRs remain explicitly historical; canceled Phase 5.2 planning inventories were removed after their evidence and disposition were retained. Final review corrections preserve interrupted-candidate authority across failed recovery, make boot no-op admission independent of Python/Git/render/Ansible, align the runner with system Ansible, enable and verify the recovery dependency only after a valid baseline, recheck Quadlet identity immediately before deactivation, and include networkd service repair in local acceptance. The executable one-writer guide binds proof to an exact non-polled candidate, establishes SHA-only recovery authority only after an approved successful legacy apply, installs recovery before adoption, and defines exact accept/reject branch, state, unit, and boot-network restoration. Architect, SysAdmin, and Code Reviewer independently approved Phase 5.2 on 2026-10-18 with no remaining must-fix finding. Optional standalone clarification of stale Phase 6/7 task wording remains governance-paused pending explicit user approval and is not an implementation or approval blocker.

### Phase 6: Assess and Migrate `deimos`

Assess the first live host and prove the repository implementation without changing authority until
explicit cutover approval.

- [x] 2026-09-26 Before implementing Phase 6, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Treat live-host access and every mutation as separately authorized gates. Evidence: the 2026-10-18 repository-only review rendered Deimos successfully from the squashed migration tree based on pre-review commit `b26f925`, confirmed the declared networkd/resolved, custom CoreDNS build, rootless Vault Agent/Podman, and runner-state adoption dependencies, and reordered proof so syntax, render, dry-run, manifest parity, recovery, boot-order, and complete-plan review precede any live apply. The exact adoption revision will be recorded after this review is committed and before publication. Read-only host assessment, secret-safe credential presence checks, candidate-branch publication, host mutation, live convergence, reboot proof, cutover, and timer observation remain separate gates below.
- [x] 2026-09-13 Assess `deimos` without mutation using ordinary Ansible facts, fixed read-only commands, and the operator checklist; record prerequisites, adopted foundations, live legacy state, conflicts, and gated removals without requiring the superseded discovery/classification framework. Evidence: the 2026-10-18 operator-run assessment confirmed Debian 13.7 on physical host `deimos`, the declared `enp0s31f6` management path and networkd addresses, a clean legacy checkout at `297a080720853d76fc0626d71b0b2c010f217107`, healthy timer-driven fetches, the matching legacy three-field last-successful record, no current-run or failed-target record, and successful runner-equivalent Git authentication. Networkd, resolved, Chrony, custom CoreDNS and its zone watcher, rootful Blocky, rootless Vault Agent, linger, Podman, required entry points, and root-owned live units/configuration were present and healthy with no failed system units. The broad legacy `abhaile` sudo policy is retained as a gated post-cutover review; the system-scoped Vault Agent unit is correctly absent because it is a generated user unit, and the network-restore unit is correctly absent until separately approved adoption. The initial generic Git and rootless Podman observations failed only because they omitted the runner's dedicated SSH identity and used an unreadable inherited working directory; corrected fixed read-only commands succeeded.
- [x] 2026-09-13 Confirm the age identity, fetch-only deploy key, pinned `known_hosts`, sealed Vault Agent bundle, SOPS recipient rule, legacy runner/apply state, and exact intended adoption revision without exposing secret material. Separately prove the named human administrator's local, intended SSH/WireGuard, sudo, and console paths. Evidence: on 2026-10-18, secret-safe operator checks proved that Deimos's age identity decrypts its sealed Vault Agent bundle, the stored GitHub RSA/ECDSA/Ed25519 fingerprints match GitHub's published identities, strict authenticated fetch succeeds with the dedicated deploy key, and GitHub marks that key read-only. The operator separately confirmed local and intended WireGuard SSH, independent `moonpie` sudo, and console recovery. The legacy checkout and last-successful record both identify `297a080720853d76fc0626d71b0b2c010f217107`. Candidate `544fa13aac3288ff16aa964bd84090154bb92ba9` exposed the documented fast-forward assumption before checkout. Candidates `5f2bec302d75c432b70b3af3e702e5447c1e1798` and `159f85af7690d9e196cd728c89b0cdb18a2bc781` then exposed that legacy systemd dry-run validation incorrectly constructed an empty alternate operating-system root: it failed first on an absent runner executable and, after narrow staging, on the missing standard `sysinit.target`. Candidate `03456885e1e02ab018cd18ac5ae141b6522b73b2` passed deterministic render, manifest parity, and retained legacy dry-run validation, then exposed that Ansible validated ordinary systemd units separately from candidate Quadlet-generated units: `coredns-omada-install.service` could not resolve `coredns-omada-build.service`. All four candidates failed closed without live publication and are superseded. The replacement stages ordinary units and rootful Quadlets together, runs the real Podman generator, and validates their combined dependency graph through native systemd paths; named-user validation remains in the target identity. All repository hooks, both Ansible syntax checks, the 51-case affected-role suite, and the complete 980-test repository suite pass; docstring coverage remains 99.6%, and no `config/` file changed. The next exact candidate must be recorded only after this correction is committed and reviewed.
- [ ] 2026-09-28 With separate remote-publication and host-mutation approval, begin the Section 11 one-writer procedure from `docs/guides/bootstrap.md`: publish the exact reviewed candidate on a non-polled review branch; stop the timer and service; prove process/lock quiescence; and detach only that candidate revision. Do not run a live apply, the candidate runner, or install/enable recovery at this gate. Evidence so far: the first window stopped the legacy runner, proved job and lock quiescence, and fetched the exact review ref, but correctly aborted before checkout when the intentional squash was found not to be a fast-forward. The legacy checkout remained unchanged and its timer was restored with a successful seeded run and a future activation.
- [ ] 2026-09-13 While the scheduler remains stopped, run repository and host syntax checks, deterministic render, retained legacy Python apply dry-run with validations, Ansible check mode, manifest parity, local last-successful recovery, and boot-order preflight for `deimos`; review the complete plan, health boundary, cleanup limits, custom CoreDNS build prerequisite, rootless Vault Agent/Podman prerequisite, and cutover/rejection procedure before approving live convergence.
- [ ] 2026-09-13 With explicit live-mutation and reboot approval, continue the same stopped-scheduler window: run the reviewed candidate revision's retained legacy Python apply live; only after it succeeds, atomically establish and verify its exact SHA-only last-successful baseline; install and verify pre-networkd recovery; adopt networkd if required; then manually run the candidate runner with its branch explicitly bound to the same non-polled ref. Prove Ansible convergence, unchanged idempotence, failure/interruption recovery, fetch-outage recovery, and pre-networkd reboot recovery without enabling scheduled candidate execution.
- [ ] 2026-10-10 After accepting the Deimos proof, perform cutover only with separate explicit approval while the one-writer window remains active: use an administrator write credential to promote exactly the proven candidate SHA with `--force-with-lease` bound to the observed legacy remote tip, then fetch, explicitly align, and verify both local and remote refs. This one-time intentional history replacement does not weaken routine fast-forward-only runner behavior and must not grant write access to the host deploy key. Reconfirm reconciliation, health, last-successful, recovery dependency, and administrator access; then enable the updated timer and prove legacy mutation cannot run concurrently. If approval is refused before promotion, disable and verify removal of the candidate recovery dependency, restore the exact legacy files and SHA-only baseline, restore or explicitly verify legacy boot-network authority, leave both polled refs at the legacy revision, and only then re-enable legacy scheduling.
- [ ] 2026-10-10 Observe timer-driven reconciliation on Deimos and confirm desired/current/last-successful behavior, failed-target suppression, local health, unchanged drift repair, fetch-outage recovery, reboot recovery, and documented rollback limits. Complete a Deimos go/no-go review before beginning Phobos migration.

### Phase 7: Migrate and Cut Over `phobos`

Repeat the proven and accepted Deimos migration on the second host, then cut over Phobos separately.

- [ ] 2026-09-26 Before implementing Phase 7, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Treat live-host access, cutover, and every mutation as separately authorized gates.
- [ ] 2026-09-13 Repeat the ordinary-facts/read-only-command/operator-checklist assessment and staged proof on `phobos`, including VLAN, Coral TPU, Vault, and infrastructure-specific state; record adopted foundations, conflicts, gated removals, intended revision, and separately proven human administrative access without using the superseded discovery/classification framework.
- [ ] 2026-09-28 With explicit host-mutation approval, repeat the proven Section 11 one-writer procedure on `phobos`: use the exact reviewed candidate on a non-polled review branch, stop timer/service execution, prove lock quiescence, and use only its retained legacy Python apply path for the reviewed dry-run and explicitly approved live apply before establishing candidate recovery authority. Do not run or schedule the candidate reconciliation path concurrently with legacy scheduling.
- [ ] 2026-09-13 Repeat the `deimos` syntax, dry-run, manifest-parity, local recovery, human-access, and console-recovery gates on `phobos`.
- [ ] 2026-09-13 With explicit live-mutation and reboot approval, continue the stopped-scheduler proof: establish the exact SHA-only baseline only after successful candidate legacy apply, install and verify recovery, complete any required networkd adoption, and manually bind the candidate runner to the same non-polled ref. Prove Ansible convergence, unchanged idempotence, interrupted-candidate recovery, fetch-outage recovery, and pre-networkd recovery while the exact legacy revision and boot authority remain available for rejection.
- [ ] 2026-09-13 Complete the Phobos cutover only with separate approval while the one-writer window remains active: promote and verify exactly the proven SHA on the polled branch, reconfirm health, last-successful, recovery dependency, and administrator access, then enable the updated timer and prove legacy mutation cannot run concurrently. On refusal, execute the same exact legacy files/state/branch/boot-authority restoration used for Deimos before re-enabling legacy scheduling.
- [ ] 2026-09-13 Observe timer-driven reconciliation on Phobos and reconfirm desired/current/last-successful behavior, failed-target suppression, local health, unchanged drift repair, fetch-outage recovery, and rollback limits on both hosts. Permit temporary host-local SHA skew and maintenance-gate fleet-atomic changes.
- [ ] 2026-09-13 Complete an explicit final go/no-go review before declaring Ansible authoritative across both hosts; after each host's cutover, recover through last-successful rather than restarting stale legacy mutation code.

### Phase 8: Post-Migration Cleanup

- [ ] 2026-09-26 Before implementing Phase 8, review every task against its prerequisites and current evidence; confirm it is completable within this phase or split and move each later-phase dependency, with explicit in-scope and deferred scope. Require explicit cutover approval before destructive or access-policy cleanup.
- [ ] 2026-09-13 Remove legacy Python mutation branches only where Ansible parity and last-successful recovery evidence prove them redundant; do not claim rollback for deferred software or irreversible effects.
- [ ] 2026-09-13 Remove all remaining Phase 1-5 prototype code, installed artifacts, dependencies, state readers/writers, and tests; verify no live unit, sudo rule, path, or documentation references them.
- [ ] 2026-09-13 Review the retained `abhaile` sudo/runtime model separately after successful cutover. Do not couple an access-policy redesign to this migration without a new approved requirement.
- [ ] 2026-09-13 Update specs, ADRs, runbooks, and operator guidance to match deployed behavior.
- [ ] 2026-09-13 Accept the implementation spec and remove this checklist only after all evidence and cleanup gates pass.

### Migration Context and Constraints

Both `deimos` and `phobos` are live hosts already managed by the legacy bootstrap and Python apply
flow; neither may be treated as a blank machine. The legacy runner remains authoritative and the
new Ansible path remains quarantined until the explicit per-host cutover gates pass.

Current architectural authority lives in active Spec 0028 and ADR 0013. In summary:

- `config/` remains authoritative declarative intent; rendering stays deterministic and
  unprivileged.
- The existing local clone, `last-successful-commit`, mutation marker, `failed-target`, and shared
  lock are the complete routine reconciliation state model.
- Ordinary reconciliation applies desired state, repairs unchanged drift, and restores
  last-successful after failure or interruption. A small early runner mode restores only
  last-successful network state before networkd.
- Ansible check mode reports planned change without authorizing live mutation; reviewed repository
  code is trusted, so check mode is not treated as a security or containment boundary. Destructive,
  irreversible, and insufficiently recoverable effects remain explicitly gated or excluded.
- Runtime secrets remain outside repository-managed rendered output, and reports remain redacted.
- The existing trusted `abhaile` automation account, clone, credentials, runner, bootstrap, and
  privilege model are retained during this migration.
- `rendered/software/` remains render-only; software/package/build execution is deferred.
- Offline recovery depends on the last-successful revision remaining in the local Git object
  database and applies only supported `manifest.json` resource families.

Existing-host migration begins with read-only observation using ordinary Ansible facts, bounded
fixed commands, and an operator checklist. Secret material must never be printed or copied while
collecting evidence. Every pre-cutover mutation stops legacy scheduling and proves quiescence
before using the replacement path; only one mutation backend may run during the maintenance
window. Every live-host mutation, reboot, network change, access-policy change, or cutover requires
explicit approval in the current conversation.

`deimos` is the canary. `phobos` follows only after the Deimos evidence is accepted. The Ansible
reconciler becomes authoritative per host only after last-successful state, direct reconciliation,
scheduled execution, recovery, human administrative access, and legacy exclusion are proven.
Final cleanup follows both host cutovers and must leave specs, ADRs, runbooks, installed state, and
repository behavior aligned.

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
