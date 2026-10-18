# Phase 5.2 File Disposition and Baseline

Status: reporting-only execution artifact for active Spec 0028\
Checkpoint: `666086f3367525a0ff61415e196dc3fd3e91ca70`\
Phase 0 parent: `9060b860730cc64e705f67a8afa1a988871fc171`\
Created: 2026-10-07\
Deletion gate: remove this report after all dispositions are implemented, evidence is transferred to
Spec 0028, and the final repository-wide closure audit passes.

This report is not architectural authority. Active Spec 0028 and ADR 0013 control implementation.
It records the pre-change baseline and checked path disposition so prototype machinery is not
preserved merely because it exists or has tests.

## 2026-10-08 Disposition Reset

Repeated review of Phase 0 versus the current repository supersedes the implementation slices and
individual path dispositions below wherever they conflict with this reset:

| Area | Current disposition |
| --- | --- |
| Eleven changed `config/hosts/**/software/**/*.yaml` files | Restore exactly to Phase 0 content |
| `schemas/software-action.schema.json` | Restore the Phase 0 `id`/`name`/`commands` contract |
| `rendered/software/` | Retain deterministic render-only output; do not converge it in Phase 5.2 |
| Software/package/download/build/command execution | Defer to separately specified later work |
| Phase 0 `manifest.json` | Retain as the sole inventory for currently managed resource families |
| `convergence-manifest.json` and manifest v2 | Delete |
| Typed software models and generic operation compiler/dispatcher | Delete |
| Existing `abhaile` account, clone, venv, credentials, runner, bootstrap, lock, and sudo model | Retain |
| Protected mirror, capsules, immutable exports, copied runtime, new identities and launcher | Delete |
| Accepted/pending/rejected, runner-LKG, health challenge, publication, and transaction records | Delete |
| Existing `last-successful-commit`, `current-run`, and `failed-target` | Retain and minimally clarify |
| Crash detection | Add one marker at the first mutation boundary; do not add a replay graph |
| Ordinary recovery | Render and reconcile old last-successful from the existing local clone |
| Network recovery | Small pre-networkd mode of the existing runner; no independent controller |
| Bespoke discovery/classification and sudo-transition frameworks | Delete; use Ansible facts and an operator checklist |
| Ansible | Direct roles for manifest resource families; built-ins first |
| Deterministic timestamp/DNS cleanup | Retain and align accepted documentation |

The original checked-path table remains useful evidence of affected files, but its old RU/RS/RP/DP
codes are not instructions after this reset. Every implementation decision must follow the current
Phase 5.2 checklist and ADR 0013.

### Slice 1 evidence: authoring and render boundary

- The 11 software YAML documents parse identically to their Phase 0 (`ea888fb`) versions. The
  repository formatter wraps two long gasket command scalars without changing their values.
- `schemas/software-action.schema.json` is byte-identical to Phase 0.
- `src/abhaile/renderers/software.py` validates and renders the original command documents but no
  longer parses typed operations or registers software artifacts with a convergence manifest.
- Directory artifact targets retain their authored trailing slash; a focused networkd renderer
  regression test covers the behavior.
- The manifest-v2-only execution-identity map and its users-renderer producer are removed; the
  canonical manifest-v1 inventory never serialized or consumed them.
- Two independent renders of both hosts were byte-identical. `rendered/software/` was present, and
  neither emitted manifest contained a software entry.
- Validation: 35 focused renderer/integration tests passed; all 1,338 unit tests passed; the full
  integration suite was stopped after 22 passing tests in 270.77 seconds because long-duration
  quarantine scenarios are assigned to the later disposable-VM proof gate.

### Slice 2a evidence: remove manifest-v2 emission and generic dispatch

- `abhaile-render` emits only the canonical `manifest.json`; the convergence-manifest renderer and
  its dedicated tests are removed.
- `ansible/playbooks/converge.yml` is again an unconditional fail-closed debug/assert scaffold.
- The complete generic `manifest_convergence` role is removed, including 13 operation task files,
  11 parallel validation files, the envelope/exact-cover dispatcher, and two custom modules.
- The real-config integration test now proves deterministic manifest v1 output, render-only
  software, and absence of `convergence-manifest.json` for both hosts.
- The typed software model, compiler, execution identities, protected exact-cover plan, and their
  tests remain temporarily because the protected trust/network prototype still imports them. They
  must be deleted with that complete caller closure in Slice 2b; no adapter or new caller may be
  introduced.
- Validation: 30 focused renderer/quarantine/integration tests and all 1,299 remaining unit tests
  passed.

### Slice 2b evidence: remove the protected trust and transaction platform

- No surviving Python application module imported `src/abhaile/trust/`; its only external callers
  were the prototype launcher/network scripts and recovery installation artifacts.
- The complete 39-module trust package and 35-module trust test package are deleted together with
  the typed software model, protected exact-cover planner/compiler, integration quarantine harness,
  three launcher/network scripts, network recovery installation role/units, constrained sudo
  candidate, and obsolete `abhaile-network-recovery` package entry point.
- This removes the protected mirror/capsule/export and containment model; discovery classifiers;
  transaction/apply-state/runner-LKG/health/publication ledgers; guarded-network controller,
  watchdog, peer, probes, and recovery journal; copied runtime; and their compatibility readers.
- Repository-wide surviving-code scans find no reference to the deleted package, typed software
  kinds, prototype scripts, recovery role, or sudo candidate. Historical ADR text is deliberately
  retained as superseded evidence.
- Production Python now totals 14,402 lines and tests total 25,772 lines. The complete worktree
  delta at this boundary is 393 insertions and 28,352 deletions; final Phase 5.2 recounting remains
  open because direct Ansible roles and runner recovery have not yet been implemented.
- Validation: all 697 surviving unit and focused render/Ansible integration tests passed.

### Slice 3a evidence: begin direct Ansible resource roles

- `ansible/roles/managed_directories` consumes only directory entries already selected from the
  canonical manifest-v1 inventory. It does not parse the whole manifest, dispatch operation kinds,
  execute commands, or introduce another resource model.
- The role validates the entire selection before mutation and delegates convergence solely to
  `ansible.builtin.file`; no custom module, plugin, handler, or Python adapter is involved.
- Isolated temporary-path integration tests cover first creation with exact mode, unchanged rerun,
  check-mode non-mutation, and refusal of the complete batch before mutation when one entry is
  invalid.
- The production convergence play remains fail-closed. This role is repository implementation
  evidence only and has no live-host caller until the remaining resource roles and cutover gates
  are complete.
- Ansible configuration no longer names the deleted copied/protected runtime; it points to the
  retained `/opt/abhaile` checkout roles and virtualenv interpreter while the play itself remains
  fail-closed. Global `no_log` is removed so ordinary failures remain operable; secret-bearing
  tasks retain responsibility for targeted suppression.
- Validation: all 701 surviving unit and focused render/Ansible integration tests passed; every
  pre-commit formatting, type, schema, lint, and secret-scanning hook passed.

### Direct-role implementation order

The legacy executor review fixes the remaining implementation order. Each family owns its
validation, publication, activation, readiness, and eligible removal behavior; no shared operation
dispatcher or partially authoritative generic file role is introduced.

1. Managed directories: complete as the inert prerequisite for later file families.
1. Host users and access files: validate the closed fixed inventory but reserve mutation for the
   existing bootstrap/adoption procedure and its administrative-access gates.
1. Rootful systemd and resolved files: isolated `systemd-analyze verify`, atomic publication,
   daemon reload, declared enable/activation behavior, readiness, and bounded removal.
1. Service configuration and Vault Agent files: publish by owner only after directories and units,
   then perform rootful or named-user restart/readiness through ordinary Ansible/systemd modules.
1. Quadlets: separate rootful and named-user contexts, daemon reload, generated-unit validation,
   activation/readiness, and logical-resource removal before file pruning.
1. Caddy and CoreDNS: retain their real configuration validators and owner-level reload/restart
   semantics rather than treating them as undifferentiated files.
1. Networkd: implement last because it also supplies the constrained pre-networkd recovery role;
   keep publication, reconfiguration, health, and removal within that family.

Safe prune is added with each family after its live-identity contract is proven. It is not a final
generic deletion pass. Software/package/build/command output remains outside this sequence.

### Slice 3b evidence: host users and access files

- The earlier direct `host_access` role was unnecessary and risked treating the existing automation
  identity and privilege foundation as routine reversible state. It and its dedicated test were
  removed during the final Phase 5.2 proportionality review.
- Manifest orchestration still requires the three kinds to use their exact fixed targets, so a
  malformed or spoofed inventory fails before family execution. It deliberately does not publish,
  activate, or remove those artifacts.
- Fresh bootstrap and explicit existing-host adoption own identity, authorized-key, and sudo-policy
  changes. Their independent administrator and recovery checks remain later adoption gates.

### Slice 3c evidence: rootful systemd and resolved

- `ansible/roles/rootful_systemd` accepts already-selected rootful unit, drop-in, resolved-config,
  and resolved-drop-in manifest-v1 entries. It rejects rootless hints and validates every source
  type, size, and SHA-256 before publication.
- The complete selected unit/drop-in set is staged into disposable scratch and verified through a
  fixed `systemd-analyze verify` invocation with an explicit unit search path. Cleanup runs even
  when validation fails; resolved configuration retains the legacy contract, which has no separate
  syntax validator.
- Built-in copy performs atomic root-owned publication. Unit changes trigger one daemon reload;
  declared enable, restart, and start behavior executes in that order, drop-ins use `try-restart`
  on their parent, and resolved changes produce one `reload-or-restart`.
- The role explicitly rejects `abhaile-runner.service` and `.timer`; active runner self-publication
  belongs to the later frozen runner/cutover slice and cannot occur implicitly in an ordinary unit
  loop.
- Isolated tests cover complete-context validation and check-mode non-mutation, invalid-unit and
  source-identity refusal before publication, and runner self-management refusal. They do not
  mutate this WSL system manager. Real first/unchanged activation and readiness remain disposable-
  VM evidence; removal remains absent until family-specific live-identity prune proof exists.
- Validation: all 710 surviving unit and focused render/Ansible integration tests passed.

### Slice 3d evidence: remove direct-role validation duplication

- A progress review found that the three direct roles repeated safe-path validation, and the two
  file-producing roles also repeated rendered-source type, size, and SHA-256 checks. The shared
  `manifest_entry_preflight` role now owns only those read-only manifest-v1 invariants.
- Resource kinds, apply hints, ownership, publication, activation, readiness, and removal remain in
  their family roles. The preflight role has no kind dispatcher and no mutation module, so this
  consolidation does not recreate the deleted generic convergence engine.
- The four production roles now total 428 lines, 17 fewer than the three roles before common
  validation was extracted. Their three focused integration tests remain 508 lines and exercise
  the shared preflight through invalid-path and source-identity failures before mutation.
- The complete worktree now contains 2,035 added and 28,380 deleted lines when all nine untracked
  Phase 5.2 role/test/ADR/report files are included. Of those additions, 576 lines are this
  temporary disposition report. Final complexity recounting remains a completion gate.
- Validation: all 13 direct-role integration tests passed after the consolidation; the complete
  repository suite passed with 814 tests, and every pre-commit formatting, type, schema, lint, and
  secret-scanning hook passed.

### Slice 3e evidence: ordinary service configuration

- A second review found that rootful-systemd validation still coerced the `rootless` hint through
  Ansible's boolean filter. It now requires an exact boolean and still rejects every rootless entry;
  focused coverage proves a string value fails before publication.
- `ansible/roles/service_config` accepts one non-empty, owner-homogeneous selection of
  `service.config` entries. This owner-scoped call contract supplies the grouping already required
  by the manifest and avoids rebuilding grouping, operation dispatch, or an owner graph in Ansible.
- Common source identity remains in `manifest_entry_preflight`. The family role validates exact
  ownership context, optional mode, and one consistent optional restart unit before using built-in
  copy for atomic publication. Rootful files default to `root:root` mode `0644`; supported rootless
  files use the declared user for both owner and group, matching the legacy staging contract.
- A changed owner selection performs at most one fixed `systemctl try-restart`, followed by an
  active-state check. Null or absent restart hints publish static/build/tooling content without a
  runtime action. Check mode publishes nothing and never contacts systemd.
- Isolated tests cover rootless first/unchanged publication with exact mode, restart-bearing check
  mode, complete mixed-owner refusal, and exact-boolean refusal. Root-owned first/unchanged and
  actual restart/readiness proof remain disposable-VM evidence because this unprivileged test
  environment cannot safely chown temporary files to root or mutate its system manager.
- Validation: all nine focused rootful-systemd/service-config tests passed, including the review
  regression; all four service-config tests passed again after the final selection guard; every
  pre-commit formatting, type, schema, lint, and secret-scanning hook passed; the complete
  repository suite passed with 819 tests.

### Slice 3f evidence: Vault Agent configuration

- The actual phobos and deimos manifests establish a closed Vault contract: one
  `service:vault-agent` owner, one `vault.config`, zero or more `vault.template` files, one declared
  rootless user, exact `restart` behavior, and explicit templates-before-config ordering. The role
  encodes that contract directly rather than extending the general service role.
- `ansible/roles/vault_agent_config` delegates only common source/path identity to
  `manifest_entry_preflight`. It validates the exact kinds, owner, boolean rootless marker, shared
  user, restart mode, ordering hints, and single-config cardinality before mutation.
- Built-in copy publishes every template before the config with the declared rootless user and
  mode `0644`. Any changed publication causes one fixed user-manager restart of
  `vault-agent.service`, followed by an active-state check. Check mode never publishes or contacts
  systemd; unchanged files cause no runtime action.
- Focused tests cover unchanged idempotence without a systemd call, check-mode ordering and
  non-mutation, malformed ordering refusal, and mixed-identity refusal. Changed publication plus
  real restart/readiness remains disposable-VM evidence.
- The post-implementation review found no duplicated dispatcher, owner grouping, dynamic unit
  selection, validator framework, or secret-management behavior. Caddy/CoreDNS, Quadlets, pruning,
  and runtime secret output remain outside this role.
- The same review exposed formatter-unstable, expression-heavy command construction in the prior
  service-config slice. Explicit rootful and rootless restart/readiness tasks plus short local
  variables replaced it; the focused behavior tests and the exact formatter/linter gate pass.
- Validation: all eight focused service/Vault integration tests passed after simplification; the
  complete repository suite passed with 823 tests, and the exact affected-file formatting, type,
  YAML, Markdown, Python, and secret-scanning hooks passed.

### Slice 3g evidence: rootful Quadlet file boundary

- Review of both real host manifests found six Quadlet kinds rather than only containers and pods:
  container, pod, network, volume, build, and potentially image. Network/volume recreation,
  managed-build execution, ordinary activation, manual pod sequencing, and removal have distinct
  semantics and are not collapsed into one generic lifecycle loop.
- `ansible/roles/rootful_quadlet_files` accepts all six rootful file kinds but owns only their
  common file boundary. It validates exact boolean context, the fixed rootful target directory, and
  the filename-to-generated-unit identity before mutation.
- The complete selected set is staged in disposable scratch and passed to the installed
  `podman-system-generator -dryrun` using `QUADLET_UNIT_DIRS`. Cleanup is unconditional. Only a
  successful dry-run permits built-in copy publication; changed files cause one system-manager
  daemon reload and generated-unit load-state verification.
- Read-only preflight carries an explicit test tag so the unprivileged suite can exercise the real
  installed generator without weakening `/etc/containers/systemd` ownership or pretending to have
  root publication authority. Normal untagged execution still runs the complete role.
- Focused tests cover a valid generator dry-run, malformed Quadlet refusal, owner/unit mismatch,
  and rootless-context refusal. Root-owned publication, daemon reload, and generated-unit
  verification remain disposable-VM evidence. The role has no production caller while convergence
  remains fail-closed.
- Rootless Quadlets are explicitly deferred: correct preflight must run the user generator under
  the declared account and environment, not merely point the rootful path at a home directory.
  Activation, managed builds, network/volume object recreation, and safe removal are also later
  bounded slices.
- Candidate-only rootful Quadlet files now use the same family role: generated units are stopped in
  reverse dependency order, file identity is checked again, matching files are removed, and the
  existing single daemon-reload boundary is reused. Podman objects and build outputs are honestly
  retained as inert or irreversible residue; rootless candidate cleanup remains fail-closed.
- Validation: all four focused rootful-Quadlet preflight tests passed; the exact affected-file
  formatting, type, YAML, Python, and secret-scanning hooks passed; the complete repository suite
  passed with 827 tests.

### Slice 3h evidence: bounded rootful Quadlet activation

- Legacy behavior and real manifests confirm that automatic containers and pods need first-install
  start and changed-run restart, while pod-member containers marked `restart_mode: manual` are
  controlled by separate pod/dependency sequencing. Built units, networks, volumes, and images have
  further family-specific lifecycle effects.
- Changed automatic rootful containers and pods now use ordinary `systemd_service` with
  `state: restarted`, which starts an inactive first installation and restarts an active unit. A
  fixed `systemctl is-active --quiet` check follows each activation. Check mode performs neither.
- The role accepts only exact absent/`try-restart`/`manual` restart semantics, and `manual` is valid
  only for container entries. No dynamic action vocabulary or lifecycle dispatcher is introduced.
- Post-implementation review found that silently publishing a changed deferred kind would create a
  false success. Before any mutation, the role now requires manual containers, builds, networks,
  volumes, and images to be present at their exact desired SHA-256. They may supply unchanged
  generator context, but a change fails closed until its family-specific lifecycle slice exists.
- Focused tests cover the automatic activation task contract, invalid restart-mode refusal, and
  changed manual-container refusal in addition to the existing generator and context tests. Live
  first-install/restart/readiness remains disposable-VM evidence.
- Validation: all seven focused rootful-Quadlet tests passed; the exact affected-file formatting,
  type, YAML, Python, and secret-scanning hooks passed; the complete repository suite passed with
  830 tests.

### Slice 3i evidence: manual rootful pod members

- A review against both rendered host manifests confirmed that every rootful container marked
  `restart_mode: manual` is a pod member. Its owner metadata requires exactly one selected
  `quadlet.pod`; other requirements are volumes and therefore cannot be used as lifecycle targets.
- The direct role validates that one-hop relationship before mutation. Changed manual containers
  are published with the complete generator-validated selection, then their parent pods are
  deduplicated, restarted once, and required to become active. If the parent `.pod` file also
  changed, the existing automatic pod activation owns the single restart.
- This deliberately does not import the legacy transitive owner graph. Missing, ambiguous, or
  unselected pod relationships fail closed, and deferred build/network/volume/image changes remain
  blocked before publication.
- The local WSL environment has Podman 4.9.3, whose generator rejects the project-used `Pod=` key.
  Focused tests therefore prove the manifest relationship and task contract using generator-valid
  isolated inputs; actual pod-member generation, restart, and readiness remain Debian 13 disposable-
  VM evidence.
- Validation: all eight focused rootful-Quadlet integration tests and all 831 repository tests
  passed. The exact affected-file formatting, type, YAML, Markdown, Python, and secret-scanning
  hooks passed twice after formatter stabilization; `git diff --check` passed.

### Slice 3j evidence: whole-delta authority and simplification review

- A complete tracked/untracked worktree inventory and surviving-reference scan confirmed that the
  implementation direction is deletion-led: 39 trust modules, the generic convergence role,
  guarded-network runtime, custom modules, launchers, and their dedicated tests are removed. No
  production, test, packaging, or operator path imports the deleted trust package or invokes the
  deleted runtime; the remaining `convergence-manifest.json` mention asserts its absence.
- The review found that active Spec 0028 still placed an authority note above the obsolete
  bundle/launcher/accepted/pending architecture. It was rewritten as one 240-line ADR-0013-aligned
  contract using the existing clone, runner, `last-successful-commit`, one `current-run` marker,
  existing `failed-target`, conventional family roles, and the small pre-networkd mode. Obsolete
  machinery appears only as rejected non-goals or historical decision context.
- Config and software-schema changes are restoration of the Phase 0 authoring contract, not new
  Ansible intent. Software remains render-only. Surviving Python changes either delete transitional
  manifest/software models or retain independently useful deterministic-render behavior.
- The seven direct roles remain explicit resource-family code using built-in modules and fixed
  validators. Review did not approve copying the 258-line rootful Quadlet role for the five
  rootless Vault Agent artifacts; that next slice must use the smallest owner-specific or shared
  boundary justified by the actual manifest.
- Common source validation had one real path-containment gap: leading `.`, `..`, `./`, and `../`
  render paths could pass its internal-segment checks. They are now rejected before mutation with
  isolated integration coverage.
- Validation: all eight focused managed-directory/preflight tests and all 835 repository tests
  passed. The affected-file pre-commit gate passed after the spec rewrite and `git diff --check`
  passed.

### Slice 3k evidence: Vault Agent rootless runtime

- Both host manifests contain the same complete rootless surface: four bind-volume Quadlets and one
  `vault-agent.container`, all owned by the `abhaile` user manager. No other rootless Quadlet owner
  exists, so a copied general rootless role would add an abstraction without a second consumer.
- `vault_agent_config` now treats those five Quadlets, Vault templates, and `config.hcl` as one
  owner-specific convergence boundary. It requires the exact owner set and runtime identity,
  validates all sources and the complete Quadlet selection before mutation, publishes Quadlets
  before configuration, reloads the user manager once, and uses the existing single restart and
  readiness boundary for any changed input.
- Generator validation runs as the declared runtime identity. Isolated tests use their actual
  current identity and an injected disposable home; production uses the account database and a
  fixed `runuser` identity transition. No rootless command dispatcher or generic lifecycle model is
  introduced, and the legacy bootstrap role remains untouched pending adoption/cutover.
- Post-implementation review removed YAML merge anchors and repeated identity/change expressions
  in favor of plainly named runtime facts and change flags. Six focused integration/static cases
  and all 837 repository tests pass. Real `abhaile` user-manager reload, generated-unit loading,
  restart/readiness, and boot enablement remain Debian 13 disposable-VM evidence.

### Slice 3l evidence: managed rootful builds

- The legacy executor and both current host manifests were reviewed before implementation. The
  repository has two rootful managed builds, no rootful image entries, and no second build
  protocol: Caddy produces one local image; CoreDNS produces one local image and then runs one
  install unit whose executable is checked.
- The existing rootful Quadlet role now admits changed `.build` files under a closed metadata
  contract. It starts the generated build unit with `systemd_service`, verifies the declared image
  with fixed `podman image exists` arguments, runs the optional declared install unit, verifies its
  regular executable output, and restarts declared service consumers. It introduces no custom
  module, transaction object, operation graph, fingerprint ledger, or generic command executor.
- Build input changes are not inferred solely from the `.build` copy result. The existing
  owner-scoped service-config role records owners whose files changed, so a changed Containerfile
  triggers its matching build even when the Quadlet definition is unchanged. Consumers already
  restarted by a build are excluded from the subsequent changed-container restart, avoiding a
  duplicate activation.
- Network and volume definition changes remain refused before publication because the legacy
  behavior recreates Podman objects and is destructive. No current manifest contains a rootful
  image entry. Those families are not made safe by treating their files as ordinary Quadlets.
- Eleven focused rootful-Quadlet cases, the combined 15 rootful-Quadlet/service-config cases, and
  all 840 repository tests pass. The exact affected-file pre-commit gate is stable across two
  consecutive runs. Actual build execution, image visibility, post-build installation, and
  consumer restart remain Debian 13 disposable-VM evidence while production convergence stays
  fail-closed.

### Slice 3m evidence: Caddy configuration

- The legacy executor, both current host manifests, and the rendered Caddy Quadlets were reviewed
  before implementation. Only Phobos currently owns Caddy configuration, with one file for each of
  the `dmz` and `internal` segments. Each file is bind-mounted at `/etc/caddy/Caddyfile` in its
  corresponding `systemd-caddy-<segment>` container.
- Caddy's installed plugin-capable binary provides the necessary validator directly. The
  owner-scoped `caddy_config` role requires one exact segment entry, verifies its source and fixed
  `/srv/caddy/<segment>/Caddyfile` target, and streams the exact candidate bytes to `caddy validate --config - --adapter caddyfile` inside the existing segment container before publication.
- A successful validation permits ordinary atomic `copy` publication. A changed file then uses the
  same container's `caddy reload` command and requires the corresponding systemd service to remain
  active. There is no copied Caddy grammar, custom module, temporary host publication, operation
  model, or fallback restart policy.
- The existing container is deliberately required for candidate validation. Existing-host drift
  repair can first restore the declared Quadlet runtime; fresh enrollment sequencing remains an
  explicit later proof rather than silently skipping validation.
- Three isolated cases cover the exact segment contract, owner/target mismatch refusal, and the
  fixed validate-before-publish-before-reload command boundary; all 843 repository tests pass, and
  the exact affected-file pre-commit gate is stable across two consecutive runs. Actual
  plugin-aware validation, reload, readiness, first enrollment, and recovery remain Debian 13
  disposable-VM evidence while production convergence stays fail-closed.

### Slice 3n evidence: unchanged-runtime drift repair

- Review before CoreDNS found that the direct rootful-systemd, rootful-Quadlet, and Vault Agent
  roles still coupled activation to changed file publication. An unchanged desired revision could
  therefore leave a declared service stopped, contrary to Spec 0028's ordinary reconciliation
  model and the Caddy role's requirement for an available validation runtime.
- Rootful systemd enablement and `state: started` now run idempotently for every declared unit on
  every non-check run. Restart and parent-drop-in consequences remain change-triggered, so drift
  repair does not cause routine restarts.
- Automatic rootful containers and pods now receive an idempotent `state: started` pass and active
  verification even when their Quadlet files are unchanged. Managed builds remain change/input
  triggered, and manual pod members remain controlled through their parent pod.
- The owner-specific Vault Agent role now observes its user unit, starts it only when inactive, and
  always verifies readiness. Changed Quadlets/templates/config still share the existing single
  restart boundary. Check mode retains file-drift reporting without attempting a user-manager
  repair.
- Focused tests distinguish idempotent start/enable from change-triggered restart and cover the
  Vault Agent observation/start/readiness sequence; all 844 repository tests pass, and the exact
  affected-file pre-commit gate is stable across two consecutive runs. Real inactive-unit repair
  remains Debian 13 disposable-VM evidence while production convergence stays fail-closed.

### Slice 3o evidence: CoreDNS configuration

- Both current host manifests contain one `/etc/coredns/Corefile` and the same four authoritative
  zone identities. The legacy executor, systemd service, zone watcher, rendered Corefiles, and
  managed-build ordering were reviewed before implementation.
- The owner-scoped `coredns_config` role requires one exact Corefile plus at least one exact
  owner/path-bound zone. Every candidate zone is checked with the installed
  `/usr/bin/named-checkzone` before any target write; no DNS grammar is copied into Ansible or
  Python.
- A read-only target inspection detects content, type, symlink, owner, group, and mode drift before
  publication. Only a genuinely changed live batch stops `coredns-zones.path`. The complete batch
  is then atomically published per file, a Corefile change causes one restart, a zone-only change
  causes one reload, and CoreDNS must be active afterward. The watcher is restored through
  Ansible's `always` path even if publication or runtime activation fails. An unchanged run neither
  stops nor starts the watcher.
- CoreDNS has no parse-only mode for the repository's explicitly port-bound and address-bound
  Corefile. Starting a parallel validator would conflict with the live listener or require a
  synthetic network/runtime environment. The role therefore relies on the installed service
  restart to reject a bad Corefile and on ordinary last-successful reconciliation to restore it;
  it does not retain the retired custom parser.
- Three isolated cases cover the complete contract, owner/target mismatch refusal, fixed zone
  validation ordering, drift inspection, and watcher-safe batch/finalization structure; all 847
  repository tests pass, and the exact affected-file pre-commit gate is stable across two
  consecutive runs. Actual `named-checkzone`, restart/reload, watcher restoration, Corefile failure
  recovery, and unchanged idempotence remain Debian 13 disposable-VM evidence while production
  convergence stays fail-closed.

### Slice 3p evidence: ordinary networkd publication

- Both current host manifests were reviewed with the legacy executor and ADR 0013. Their network
  inventory contains only `.network` files, `.netdev` files, managed drop-in directories, and
  `.conf` drop-ins. Routine legacy convergence publishes those resources, reloads networkd, and
  reconfigures affected interfaces; removal-only interface deletion is a distinct destructive
  path.
- The direct `networkd_config` role validates exact owner/numbered-filename relationships and the
  fixed `/etc/systemd/network` namespace before mutation. It uses built-in `file` for drop-in
  directories and `copy` for files. A small resource-specific include preserves canonical manifest
  order and records actual changes; no generic operation dispatcher or dependency graph is added.
- Changed owners share one fixed `/usr/bin/networkctl reload` and are reconfigured once in their
  first manifest occurrence order. This retains parent-before-dependent ordering from the canonical
  inventory rather than grouping directories ahead of files or sorting owners independently.
- Existing `.netdev` content changes fail before mutation. Upstream systemd documents that some
  netdev properties cannot change in place and require deleting the interface before reload.
  First installation and ordinary metadata repair remain possible, while destructive
  delete/recreate and its last-successful recovery proof stay maintenance-gated.
- There is no official candidate-only networkd parser in the installed toolchain. The role checks
  fixed `networkctl` availability, while reload/reconfigure failure and the later gateway/local
  health gate drive last-successful recovery. It does not recreate the removed network controller,
  journal, watchdog, peer, or probe protocol.
- Three isolated cases cover the complete file/directory contract, owner/filename mismatch refusal,
  netdev-change refusal presence, manifest-order publication, one reload, and deduplicated
  reconfiguration structure. Actual reload/reconfigure, connectivity acceptance, failure recovery,
  boot recovery, and unchanged idempotence remain Debian 13 disposable-VM evidence while
  production convergence stays fail-closed.
- Validation: all three focused networkd integration tests and all 850 repository tests passed;
  the exact affected-file pre-commit gate passed after formatter stabilization.

### Slice 3q evidence: direct-role completeness review

- Before adding orchestration, both current host manifests were compared against every direct-role
  admission contract. This found one uncovered canonical kind: Phobos renders one `service.env`
  entry for Vault alongside its ordinary `service.config` files.
- Environment files share the same owner, source-identity, atomic-copy, ownership, mode, restart,
  and readiness semantics as ordinary service configuration. The existing owner-scoped role now
  admits both exact kinds; no new role, dispatcher, file publisher, or lifecycle abstraction was
  introduced.
- Focused integration coverage publishes a mixed config/environment owner batch and retains the
  existing refusal of mixed owners and coerced execution context. Orchestration remains deferred
  until the now-complete direct-role selection surface receives its own bounded review.
- Validation: all five focused service-config integration tests and all 851 repository tests
  passed.

### Slice 3r evidence: fixed manifest orchestration

- `manifest_orchestration` loads only `manifest.json`, binds version 1 to the expected host, rejects
  unknown envelope fields and unsupported resource kinds, and partitions every entry exactly once.
  The optional empty `owners` field is accepted because orchestration does not consume the legacy
  dependency graph.
- Family calls are explicit and remain in the Spec 0028 order: managed directories, reserved
  bootstrap-owned host-access inventory, rootful systemd/resolved, owner-scoped service files,
  Vault Agent/rootless Quadlets, rootful Quadlets, owner-scoped Caddy, CoreDNS, and networkd. The
  reserved inventory is validated but has no ordinary mutation role. There is no action vocabulary,
  dynamic role name, generic dispatcher, compiler, or parallel resource model.
- Rootless Quadlets are admitted only through the existing closed Vault Agent owner set. Service
  owners preserve first manifest occurrence; Caddy receives one exact owner entry at a time. Both
  current real host renders partition completely in isolated selection tests.
- The role has no production play or runner caller. The public convergence play remains fail-closed.
  Before later runner integration, the same orchestration must complete one check-mode validation
  pass before the run marker and one normal pass afterward; this slice does not claim that boundary
  is wired or that check mode is a public preview/security boundary.
- Validation: all seven focused orchestration tests and all 858 repository tests passed.

### Slice 3s evidence: bounded local acceptance

- Review of every direct role and the legacy health audit found that candidate-controlled file,
  unit, service, container, Caddy, CoreDNS, Vault Agent, and networkd readiness is already enforced
  synchronously by the family that performs the mutation. Repeating those checks in another health
  engine would create a second interpretation and less useful failure locality.
- Disposable-VM evidence rejected ICMP as a portable promotion invariant. The final
  `local_acceptance` role therefore loads the schema-validated canonical host and network intent
  only after network files or networkd runtime state change, waits for the declared management
  interface to become operational, and uses one structured `ip route get` to require the canonical
  gateway route to select that interface and its declared source address. Check mode validates
  intent without making post-change reachability claims.
- Failure or ambiguous local interface/route evidence fails the Ansible run directly. ICMP,
  neighbour, SSH, Internet, and peer reachability remain diagnostics rather than promotion
  authority. There is no health result model, challenge, receipt, retry state, configurable probe
  vocabulary, peer, callback, namespace, or separate authority.
- The orchestrator invokes acceptance last but still has no production caller. Runner wiring must
  retain the complete check-mode preflight, mutation marker, normal convergence/acceptance, and
  last-successful commit order.
- Validation: all 11 focused acceptance/orchestration tests and all 862 repository tests passed.

### Slice 4a evidence: minimal reconciliation state primitive

- Review found that the legacy runner already uses the target filenames but gives `current-run` the
  wrong meaning: it is a timestamped phase/status document written from startup through health and
  removed on most exits. Spec 0028 instead requires one SHA-only marker written immediately before
  the first mutation. Runner integration must replace that legacy meaning; adding another marker
  was rejected.
- `state.reconciliation` is an isolated durability primitive under the existing runner lock. It
  reads the existing metadata-suffixed `last-successful-commit` for migration compatibility, writes
  new SHA-only records through same-directory atomic replacement, syncs the file and directory,
  rejects symlinks and malformed identities, and introduces no new durable filename.
- Startup has only the direct combinations of the two facts: normal operation, verify a committed
  success whose marker was not cleared, recover old last-successful from a different interrupted
  candidate, require explicit enrollment when no baseline exists, or block recovery when mutation
  occurred without a baseline. This is comparison logic, not an execution replay graph.
- Success may advance only when the exact candidate marker exists. It writes and verifies
  `last-successful-commit` before removing that matching marker, so interruption after the commit
  leaves an unambiguous verify-on-start condition. Publication failure leaves no temporary record.
- The existing runner now calls the helper under its existing lock. Explicit bootstrap enrollment
  uses a separate baseline function only after legacy live apply succeeds and before runner
  registration; the routine runner still refuses to invent a missing baseline. No second lock or
  ledger is introduced.
- Validation: all 14 focused reconciliation-state tests and all 876 repository tests passed.

### Slice 4b evidence: runner and pre-networkd recovery integration

- The existing runner now owns local-first startup recovery, candidate discovery by fetch,
  unchanged drift repair, failed-target suppression, check-before-marker ordering, normal apply,
  and atomic last-successful advancement. It retains the existing clone, service account, sudo
  path, virtual environment, scheduler, and lock rather than introducing a launcher or second
  installation.
- Its early mode shares the same lock and durable records. It performs no fetch and exits without
  checkout or toolchain access unless `current-run` differs from `last-successful-commit`; only
  then does it render the retained candidate for cleanup identity and apply the accepted network
  role without managing the not-yet-started networkd service.
- On the Debian 13 VM, accepted revision `c4daabe` recovered distinct candidate `4c03693` across a
  reboot. The early service restored the accepted network-file hash and finished before networkd
  started. Ordinary reconciliation then cleared the marker, preserved `c4daabe` as last-successful,
  and left no failed target. The proof-only branch, refs, and render scratch were removed.
- A separate inert candidate `e342db8` added one candidate-only `.network` file. Early check and
  live recovery derived cleanup solely from the retained manifests, revalidated the exact live
  hash immediately before removal, removed only that file, and skipped the running networkd
  manager. Its branch, refs, live file, and scratch were removed afterward.
- The proof initially used a root-owned mode-0600 marker rather than the runner-owned `abhaile`
  record. Early recovery failed closed and networkd remained stopped until console repair corrected
  ownership. This is retained as malformed-state/operator-repair evidence, not claimed as a
  production interruption result.
- Review of the successful trace removed one redundant full reconciliation: after startup recovery,
  if fetch selects the already-restored last-successful revision, the runner records recovery
  success directly. The VM deliberately retained older accepted code, so focused repository tests
  prove this optimization and the distinct case where the interrupted candidate remains the remote
  tip and must stay suppressed.
- Real VM lock contention returned exit `2` before checkout, render, or Ansible. A controlled
  valid-but-unavailable interrupted SHA made early recovery fail before mutation while retaining
  both the marker and live network hash; exact cleanup used the existing state helper. Runner-level
  malformed-record tests now prove concise domain errors without Python tracebacks or Ansible
  invocation.
- A VM state with matching `current-run` and `last-successful-commit` represented interruption
  after the durable commit but before marker removal. Startup selected `verify-committed`,
  reconciled the accepted revision, and cleared the marker. Focused integration coverage proves
  the simplified runner performs that recovery once rather than repeating it after fetch.
- A focused live-failure regression records candidate check, candidate live mutation/failure,
  accepted check, and accepted live reconciliation in exact order. The accepted pass removes the
  simulated candidate-managed effect, while the durable last-successful revision remains
  unchanged, the exact candidate becomes failed-target, and current-run is cleared. This supplies
  deterministic repository evidence for the apply-failure recovery contract without adding a
  production failure-injection framework.
- A disposable-VM candidate changed an already-active oneshot proof service to `/bin/false`. The
  first run exposed that publishing plus `state: started` retained the old active instance and
  incorrectly accepted the revision. The rootful systemd role now uses the declared restart mode,
  or `try-restart` for a changed activation-managed unit, before its ordinary start/repair step.
  Repeating the proof as candidate `8f518cc` failed at the real systemd restart, invoked the normal
  runner recovery, restored and started the `c4daabe` service, preserved `c4daabe` as LKG, and
  returned non-zero. A final unchanged run cleared exact failed-target state; the checkout, private
  origin, live service, networkd, runner records, and proof scratch were verified clean at
  `c4daabe`.
- Native systemd validation intentionally follows the installed validator's exit status rather
  than copying its grammar: an unknown directive produced a warning and was accepted, which
  corrected an overbroad fixture description. Candidate `0f0aa8c` instead named a missing
  executable, causing `systemd-analyze verify` to fail during Ansible check. The runner returned
  non-zero before its mutation marker, did not invoke recovery, preserved the live unit hash and
  `c4daabe` LKG, and recorded the exact failed target. After the private ref returned to `c4daabe`,
  one unchanged reconciliation cleared suppression; all VM state and proof scratch were clean.
- An installed first-enrollment proof preserved the VM's original LKG and diagnostics, then removed
  only the live LKG. Routine runner startup returned non-zero before fetch or Ansible and left live
  state unchanged. With `current-run=c4daabe` and no LKG it reported `recovery-blocked`, retained
  the marker, and the explicit enrollment helper independently refused to overwrite interrupted
  authority. After exact operator cleanup, that helper atomically established and verified a
  mode-0600 `c4daabe` baseline and startup classified `normal`. The original records were restored
  exactly and all proof files removed. Focused integration coverage now proves both missing-baseline
  refusal and interrupted-enrollment preservation.
- Publication-interruption candidate `d7de3e5` changed only the disposable proof-unit description
  and inserted a proof-only pause immediately after Ansible's atomic systemd-file publication and
  before daemon reload. Once the live candidate bytes and durable current-run marker were both
  observed, a disposable external systemd test cgroup killed the runner and every Ansible
  descendant. The cgroup became inactive and the shared lock was available; LKG remained
  `c4daabe`, current-run retained `d7de3e5`, failed-target was absent, the manager still held its
  old unit definition, and only the atomically complete candidate file was live. Ordinary runner
  startup rendered the retained candidate for cleanup context, reconciled `c4daabe` exactly once,
  restored file and manager state, cleared current-run, recorded candidate suppression, and
  returned non-zero. After the private tip returned to `c4daabe`, one unchanged pass cleared
  suppression. The proof commit, refs, injected task, transient unit, logs, and scratch were
  removed; checkout, origin, LKG, services, network, and lock were verified clean.

## Disposition Codes

| Code | Meaning |
| --- | --- |
| RU | Retain unchanged |
| RS | Retain and simplify |
| RP | Replace, then remove superseded implementation |
| DP | Delete after replacement/proof gate |
| HD | Historical documentation only |

## Baseline

| Measure | Checkpoint value |
| --- | ---: |
| Git seed paths from Phase 0 parent through checkpoint | 178 |
| Classified paths including unchanged closure | 204 |
| Trust Python modules | 39 |
| Trust Python production lines | 13,795 |
| Trust unit-test modules | 35 |
| Trust unit-test lines | 10,656 |
| Transitional manifest/network Ansible lines | 1,328 |
| Custom Ansible modules | 2 |
| Generic operation task files | 13 |
| Parallel validation task files | 11 |
| Dataclasses in reviewed model/render/trust surface | 70 |
| Enums in reviewed model/render/trust surface | 12 |
| Protocols in reviewed model/render/trust surface | 9 |
| Prototype durable-state mechanism families | 9 |
| Protected Git ref namespaces/prefixes | 6 |
| Distinct journal schemas | 4 |
| Distinct lock-file authorities | 3 |
| Stage/transition vocabularies | 7 |
| Parallel validation layers | 5 |

Repeat these measurements after the overhaul. Material deletion in permanent concepts and
maintenance surface is required; line-count reduction alone is insufficient.

The state count groups capsule activation/metadata, applied state/history/replay, runner LKG,
wider-health evidence, runner publication, guarded-network recovery, recovery-installation
identity, containment/orphan receipts, and sudo/install planning. The six Git namespaces are
trusted, incoming, LKG, active transaction, transaction history, and rollback. The four journal
schemas are applied-state rotation, runner-LKG promotion, runner publication, and guarded network;
health active/terminal records are counted in their state family rather than again as journals.
The lock count covers mirror/trust, coordinator, and network-transition authority. Transition
vocabularies cover transaction, state rotation, runner update, runner publication, runner LKG,
health lifecycle, and network recovery. Validation layers are renderer/schema validation,
privileged manifest validation, compiler/exact-cover validation, parallel Ansible operation
validation, and installed service/config validation.

## Post-Overhaul Recount

The final recount repeats the checkpoint measurements against the surviving working tree after the
direct-role, runner, recovery, and disposable-VM slices. Python totals use all `*.py` files beneath
`src/abhaile/` and `tests/`; model counts use the same model/render/trust surface as the baseline.
Ansible totals use YAML beneath `ansible/playbooks/` and `ansible/roles/`, excluding deleted files.

| Measure | Checkpoint | Post-overhaul |
| --- | ---: | ---: |
| Production Python modules | 115 | 75 |
| Production Python lines | 29,201 | 14,687 |
| Test Python modules | 124 | 101 |
| Test Python lines | 37,521 | 29,900 |
| Trust Python modules | 39 | 0 |
| Trust Python production lines | 13,795 | 0 |
| Trust unit-test modules | 35 | 0 |
| Trust unit-test lines | 10,656 | 0 |
| Ansible playbook/role YAML lines | 1,381 | 2,949 |
| Custom Ansible modules | 2 | 0 |
| Generic operation task files | 13 | 0 |
| Parallel validation task files | 11 | 0 |
| Dataclasses in reviewed model/render/trust surface | 70 | 1 |
| Enums in reviewed model/render/trust surface | 12 | 0 |
| Protocols in reviewed model/render/trust surface | 9 | 0 |
| Prototype durable-state mechanism families | 9 | 0 |
| Protected Git ref namespaces/prefixes | 6 | 0 |
| Distinct journal schemas | 4 | 0 |
| Distinct lock-file authorities | 3 | 1 |
| Stage/transition vocabularies | 7 | 0 |
| Parallel validation layers | 5 | 2 |

The one retained lock is the pre-existing runner `flock`. Its three established files—
`last-successful-commit`, `current-run`, and `failed-target`—form one small reconciliation authority,
not three ledgers or a replay journal. Validation now has two non-parallel layers: deterministic
authoring/render/schema validation, then direct family preflight/native validation plus bounded
local acceptance. There is no compiler, generic operation validator, protected-manifest validator,
or transaction coordinator between them.

At the completed Phase 5.2 validation checkpoint, the working-tree delta is 10,331 additions and
29,369 deletions, including untracked replacement files: a net reduction of 19,038 lines. The
reporting-only disposition document itself accounts for 757 added lines. Ansible YAML increased by
1,568 lines because the checkpoint's
prototype was incomplete, while production Python fell by 14,514 lines and test Python by 7,621
lines. The surviving runner is 600 lines and its state helper 194 lines; together they replace the
13,795-line trust platform without adding another installer, clone, identity, lock, ledger,
journal, dispatcher, custom module, or network protocol.

The post-overhaul result is materially simpler and proportionate for the two-host homelab. Final
repository validation, durable-document alignment, independent review, and live-host adoption
remain separate gates; this recount does not authorize cutover.

## Final Disposition

Phase 5.2 retains the existing account, clone, credentials, virtual environment, runner
service and timer, bootstrap path, host identity, lock, and privilege model. It replaces
only manifest-v1 mutation with direct Ansible resource-family roles and one minimal
last-successful recovery marker. Software execution remains deferred. Unsupported or
irreversible removals remain explicit residue or maintenance work.

The earlier bundle, launcher, accepted/pending/rejected, preview, copied-runtime, and
transaction-coordinator plan is rejected and is not an implementation backlog. Its detailed
planning inventory was removed after the implemented path disposition, deletion closure, VM
evidence, and complexity recount above replaced it. Git history retains that review record.

The deployed-runner push-risk review confirms that merging directly to polled `main` is the
cutover boundary, not a harmless publication step. Repository work therefore remains off the
polled branch until the documented one-writer procedure receives separate approval. Remaining
The final independent Architect, SysAdmin, and Code Reviewer re-reviews approved Phase 5.2 after
the recovery-marker, boot no-op, restore dependency, service-repair acceptance, immediate cleanup
identity, and exact-ref cutover corrections. Final repository validation passed all 976 tests,
all staged/all-files pre-commit checks, 99.6% docstring coverage, and `git diff --check`. The clean
amended checkpoint received an exact-revision inspection, with its SHA recorded in the handoff.
Per-host adoption and cutover remain separately authorized later phases.
Nothing in this report authorizes a push to a host-polled branch or mutation of Deimos or Phobos.
