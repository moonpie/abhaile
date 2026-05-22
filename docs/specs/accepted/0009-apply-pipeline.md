# Spec: Apply Pipeline

## Metadata

```yaml
id: SPEC-2026-009
title: Apply Pipeline
status: accepted
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0003-gitops-runner-responsibility-boundary
  - 0004-apply-execution-model
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The apply pipeline is complete and in production use. This accepted spec is a
reference record of implemented contracts, boundaries, and design decisions.

Apply takes rendered desired-state artifacts from `<output>/rendered/` and
reconciles them against the live host filesystem using hash-based drift
detection. Apply is privileged, host-scoped, and owns durable state under
`<output>/state/`. Drift planning, file staging, owner-scoped execution, and
state rotation are distinct phases within a single atomic run.

The diff CLI (`abhaile-diff`) shares the same drift planning logic and provides
read-only comparison without any host mutation.

## Requirements

- [x] Document CLI apply and diff contracts, argument semantics, and safety gates.
- [x] Document drift planning logic (manifest loading, comparison, write/removal classification).
- [x] Document owner-based execution model and phase ordering.
- [x] Document each executor family with inputs, actions, and failure behavior.
- [x] Document state management (manifest rotation, history retention).
- [x] Record apply-phase implementation decisions from TODO and ADR history.

## Constraints

- Apply defaults to dry-run; live mutation requires omitting `--dry-run`.
- Dry-run must not mutate host state.
- Apply runs on a single host only; multi-host orchestration belongs to the GitOps runner.
- Host identity gate prevents accidental cross-host apply.
- Removals require explicit `--prune` or `--force-prune` flags.
- Destructive operations (quadlet volume/network recreate) require `--allow-destructive`.
- Apply never writes secrets into repo-managed rendered output; it consumes rendered non-secret
  artifacts and references host-local runtime secret paths without materializing payloads.
- State (`<output>/state/`) is apply-owned; render must not mutate it.

## Design

### CLI Contract — Apply

Entrypoint: `abhaile-apply` from `abhaile.cli.apply:main`.

Arguments:

1. `--output` — output root override (default from `paths.ini`).
1. `--desired-manifest` — explicit path to desired rendered manifest.
1. `--applied-manifest` — explicit path to last applied manifest.
1. `--host` — expected host name override.
1. `--allow-host-mismatch` — bypass host safety gate (explicitly unsafe).
1. `--dry-run` — plan only; make no changes.
1. `--dry-run-validations` — in dry-run, also run read-only validation commands.
1. `--prune` — delete only prune-safe removals (live content matches applied hash).
1. `--force-prune` — delete removals even when live content drifted from applied hash.
1. `--allow-destructive` — allow destructive operations (volume/network recreate/delete).
1. `--json` — output structured JSON report.

Flag constraints:

- `--prune` and `--force-prune` cannot be combined.
- `--dry-run-validations` requires `--dry-run`.

Path resolution uses `abhaile.cli.common:resolve_cli_paths` which reads
`paths.ini` for default `output_root_default`, `rendered_dir_name`, and
`state_dir_name`. When explicit manifest paths are provided, rendered and state
directories derive from those paths.

### CLI Contract — Diff

Entrypoint: `abhaile-diff` from `abhaile.cli.diff:main`.

Arguments:

1. Positional: `desired_manifest` and `applied_manifest` (optional).
1. `--output` — output root override.
1. `--desired-manifest` — explicit desired manifest path.
1. `--applied-manifest` — explicit applied manifest path.
1. `--json` — print full JSON diff output.

Diff calls `plan_manifest_drift` and prints the result. It is strictly
read-only and never mutates host or state.

### Host Safety Gate

`_check_host_safety` in `abhaile.cli.apply` enforces three checks:

1. Desired manifest must contain a non-empty `host` field.
1. If `--host` is provided, it must match the manifest host.
1. Live hostname (`socket.gethostname()` short form) must match the expected host.

All three checks are bypassed only by `--allow-host-mismatch`.

### End-to-End Apply Flow

1. Parse arguments and validate flag combinations.
1. Resolve output/rendered/state paths via `resolve_cli_paths`.
1. Call `plan_manifest_drift` (drift planning).
1. Run host safety gate.
1. Collect owner escalations from planner output.
1. Print or return diff summary.
1. **Dry-run exit:** if `--dry-run`, optionally run read-only validations, then exit.
1. **Phase 7.1 — File staging:** copy all write actions to target paths; process removals per prune flags.
1. **Phase 7.2 — Systemd owner actions:** daemon-reload, enable, restart, start for changed systemd units/drop-ins/resolved.
1. **Phase 7.3 — User management actions:** sysusers reconcile, sudoers validate, authorized_keys placement.
1. **Phase 7.4 — CoreDNS actions:** zone validation, zone reload, service restart.
1. **Phase 7.5 — Caddy actions:** in-container validate, reload, fallback restart.
1. **Phase 7.6 — Vault-agent actions:** grouped restart per owner.
1. **Phase 7.7 — Service config actions:** directory enforcement, unit restart, active-state check.
1. **Phase 7.8 — Networkd actions:** interface deletion, reload, reconfigure.
1. **Phase 7.9 — Quadlet actions:** object removal, daemon-reload, start/restart with convergence plans.
1. **Phase 8 — State rotation:** copy desired manifest to state, rotate previous/history.
1. Report results (JSON or human-readable).

### Drift Planning

Module: `abhaile.plan.diff`

Function: `plan_manifest_drift(rendered_manifest_path, applied_manifest_path)`

Manifest loading (`_load_manifest`):

- Validates version `"1"`, required `host` string, `entries` list, optional `owners` dict.
- Each entry requires: `target_path` (absolute), `sha256` (64-char hex), `render_path`,
  `kind`, `owner_ref`, `size` (non-negative int).
- Optional per-entry fields: `contributor_ref`, `apply_hints`.
- Owner entries require: `name` matching key, optional `description`, `requires` (list of strings), `apply_hints`.
- Applied manifest may be missing (treated as empty with desired host).

Comparison logic:

- Index entries by `target_path` (uniqueness enforced).
- Compute target sets: `added` (desired only), `removed` (applied only), `common`.
- Changed targets: common entries where `sha256` differs between desired and applied.
- Write classification against live filesystem:
  - For each desired target, hash the live file via `sha256_file`.
  - Skip targets where live hash already matches desired (already converged).
  - Classify write reason: `missing` (file absent), `add` (new in desired), `change` (desired differs from applied), `drift` (live drifted from applied but applied matches desired).
- Removal classification against live filesystem:
  - `removals_safe`: live hash matches applied hash (safe to delete).
  - `removals_drifted`: live hash differs from applied hash (content changed outside apply).
  - `removals_missing`: live file does not exist (already absent).

Owner plan construction (`_build_owner_plan`):

- Group writes and removals by `owner_ref`.
- Expand affected owners through transitive `requires` edges.
- Topologically sort expanded owners (dependencies ordered first).
- Attach escalation labels: `prune-drifted` for drifted removals, `missing-owner-metadata` for unregistered owners.

Networkd netdev delete order (`_build_networkd_netdev_delete_order`):

- Collect `networkd.netdev` removal owner refs.
- Topologically sort by `requires`, then reverse to child-first order.

Quadlet convergence plans (`_build_quadlet_convergence_plans`):

- Identify changed `quadlet.network` and `quadlet.volume` owners.
- Expand reverse dependency closure to find container dependents.
- Emit `stop` actions before infrastructure owner change and `start` actions after.

### File Staging (Phase 7.1)

Module: `abhaile.apply.actions`

`atomic_copy_file` / `atomic_copy_file_with_perms`:

- Creates parent directories.
- Writes to a temp file in the target directory.
- Sets mode and ownership on temp file.
- Atomically replaces target via `os.replace`.
- Rejects non-absolute targets and missing sources.

`resolve_rendered_source`:

- Resolves render_path under rendered_dir.
- Rejects path traversal (source must stay within rendered directory).

`remove_target_file`:

- Removes regular files and symlinks.
- No-ops for absent targets.
- Rejects non-file targets (directories, devices).

User-managed artifacts (`host.sysusers`, `host.sudoers`, `host.authorized_keys`) receive
strict ownership/mode enforcement via `apply_hints` (owner_user, owner_group, mode,
ssh_dir_mode). Sudoers files are validated with `visudo -cf` before placement.
Authorized_keys parents (`.ssh` directory) are created with strict ownership and mode.

Prune gating:

- `--prune` applies only `removals_safe`.
- `--force-prune` applies both `removals_safe` and `removals_drifted`, gated behind
  `check_destructive_gate` which requires `--allow-destructive` when owner escalations
  include `prune-drifted`.

### Executor Model

Apply behavior is typed and owner-based per ADR 0004. Each executor handles a
specific artifact kind family with deterministic action sequences. Executors
receive entry metadata and apply hints from the manifest; they do not derive
behavior from free-form reload commands.

All executors share `run_command` from `abhaile.apply.actions` which:

- Accepts explicit `argv` (no shell interpretation).
- Supports `run_as_user` via `sudo -u <user> --`.
- Returns structured `ExecutionResult` with action_id, success, return_code, stdout, stderr.
- Raises `ApplyError` when `check=True` and exit code is non-zero.

### Phase 7.2 — SystemdExecutor

Module: `abhaile.apply.systemd`

Handles: `systemd.unit`, `systemd.dropin`, `resolved.config`, `resolved.dropin`.

Unit write workflow:

1. `daemon-reload` (mandatory after file write).
1. `enable` if apply_hints.enable_mode is `"enable"`.
1. `try-restart` if apply_hints.restart_mode is `"try-restart"`.
1. `start` if apply_hints.activation_mode is `"start"` or `"start-now"`.

Supports rootless execution (`--user` mode) with `run_as_user` derived from
apply_hints.rootless and apply_hints.podman_user.

Drop-in write workflow:

1. `daemon-reload`.
1. `try-restart` parent unit (derived from target path or owner_ref `unit:` prefix).

Resolved config write: reload `systemd-resolved.service` via `reload-or-restart`.

Unit removal workflow:

1. `disable` if enable_mode was `"enable"`.
1. `stop`.
1. `daemon-reload`.

### Phase 7.3 — UserManagementExecutor

Module: `abhaile.apply.users`

Handles: `host.sysusers`, `host.sudoers`, `host.authorized_keys`.

Sysusers write: runs `systemd-sysusers` to reconcile users/groups from drop-in fragments.

Sudoers write: runs `visudo -cf` post-placement validation (also used as pre-write
validation in dry-run and during file staging).

Authorized_keys write: no runtime command; file placement with strict ownership is
sufficient.

Dry-run validations:

- `systemd-sysusers --dry-run` for sysusers.
- `visudo -cf <rendered-source>` for sudoers.

### Phase 7.4 — CorednsExecutor

Module: `abhaile.apply.coredns`

Handles: `coredns.config`, `coredns.zone`.

Config write: `try-restart coredns.service` (Corefile changes require full restart).

Zone write:

1. `named-checkzone <zone_name> <target_path>` validation (strict, raises on failure).
1. `systemctl start coredns-zones.service` to trigger deterministic zone reload.

Zone removal: `systemctl start coredns-zones.service` (reload without validation
since file is already deleted).

Zone name derivation: strips `.zone` extension from target filename.

Missing `named-checkzone` in non-strict mode returns a warning result instead of
raising.

### Phase 7.5 — CaddyExecutor

Module: `abhaile.apply.caddy`

Handles: `caddy.config`.

Config write workflow:

1. `podman exec systemd-caddy-<segment> /usr/bin/caddy validate -c /etc/caddy/Caddyfile` (strict).
1. `podman exec systemd-caddy-<segment> /usr/bin/caddy reload -c /etc/caddy/Caddyfile`.
1. If reload fails and apply_hints.restart_on_failure is true: `try-restart caddy-<segment>.service`.
1. If reload fails without restart_on_failure: raises `ApplyError`.

Segment derivation: from owner_ref `caddy:<segment>` prefix, falling back to parsing
`/caddy/<segment>/` from target path.

### Phase 7.6 — VaultExecutor

Module: `abhaile.apply.vault`

Handles: `vault.config`, `vault.template`.

Groups all vault changes by owner_ref. For each affected owner, restarts
`vault-agent.service` via the user systemd manager (`systemctl --user restart`
running as the resolved user, default `abhaile`).

User resolution: from apply_hints.podman_user, falling back to `VaultExecutor.DEFAULT_USER`.

### Phase 7.7 — ServiceConfigExecutor

Module: `abhaile.apply.service`

Handles: `service.config`, `service.env`, `service.directory`.

Directory enforcement (`apply_directory_change`):

- Creates target directory with `mkdir -p`.
- Sets owner/group/mode from apply_hints (defaults: root:root:0750).

Owner convergence (`apply_owner_change`):

- If apply_hints.restart_unit is set and writes exist: `try-restart <unit>`.
- After restart: queries `ActiveState` via `systemctl show -p ActiveState --value`.
- Raises `ApplyError` if unit is not `active` after restart.
- Supports rootless via apply_hints.rootless and apply_hints.podman_user.

### Phase 7.8 — NetworkdExecutor

Module: `abhaile.apply.networkd`

Handles: `networkd.netdev`, `networkd.network`, `networkd.dropin`.

Standard owner convergence:

1. `networkctl reload` (reload configuration files).
1. `networkctl reconfigure <interface>` (apply to specific interface).

Remove-only netdev owners (interface teardown):

1. `ip link delete <interface>` (idempotent, missing devices succeed).
1. Batched `networkctl reload` once for all removed netdev owners.

Interface derivation: from owner_ref `iface:<name>` prefix, or by parsing
numbered networkd filenames (stripping `XX-` prefix from `10-eth0.network`).

Ordering: remove-only netdev owners use child-first topological order from the
planner's `networkd_netdev_delete_order`; remaining owners sort lexicographically.

### Phase 7.9 — QuadletExecutor

Module: `abhaile.apply.quadlet`

Handles: `quadlet.network`, `quadlet.volume`, `quadlet.image`, `quadlet.build`,
`quadlet.pod`, `quadlet.container`.

Owner convergence workflow:

1. For network/volume writes (recreate objects): `podman <type> rm <object>` first
   (absent objects treated as success).
1. `daemon-reload` (rootful or rootless scope).
1. Action depends on artifact and phase:
   - Remove-only: `stop` unit, then `podman <type> rm` object for network/volume.
   - Network/volume/image/build: `start` unit.
   - Container/pod: `try-restart` unit.

Convergence plans from planner:

- Pre-steps: `stop` dependent containers before infrastructure change.
- Post-steps: `start` dependent containers after infrastructure change.
- Dependent containers identified via transitive reverse `requires` edges.

Unit name: derived from owner_ref `unit:<name>` prefix.

Podman object naming: `systemd-<stem>` where stem strips the `-network.service`
or `-volume.service` suffix from the unit name.

Rootless execution: applies `--user` to systemctl and `run_as_user` for sudo
when apply_hints.rootless is true.

### Dry-Run Validations

When `--dry-run --dry-run-validations` is set, apply runs read-only validation
commands against rendered source files without staging or mutating:

- `systemd-analyze verify <source>` for systemd.unit/dropin/resolved.
- `visudo -cf <source>` for host.sudoers.
- `systemd-sysusers --dry-run` for host.sysusers.
- `named-checkzone <zone> <source>` for coredns.zone (non-strict).
- `podman exec ... caddy validate` for caddy.config (non-strict).
- `networkctl --version` for networkd artifacts (non-strict).
- `systemctl [--user] --version` for quadlet artifacts (non-strict).

Results include target_path, kind, success, return_code, and optional warnings.

### State Management

Module: `abhaile.state.history`

Function: `update_state_manifests(desired_manifest_path, state_dir, *, keep_history=10)`

Called once after all apply phases succeed. Workflow:

1. If current `state/manifest.json` exists:
   - Copy to `state/manifest.previous.json`.
   - Copy to `state/history/manifest-<UTC-timestamp>.json` (with counter suffix for
     sub-second collisions).
1. Copy desired manifest to `state/manifest.json`.
1. Prune history files exceeding `keep_history` (oldest first, default 10).

State is updated only after full apply success. Partial failures leave state
unchanged, preserving the previous known-good manifest for next run comparison.

### JSON Output

Apply produces structured JSON when `--json` is set:

Dry-run mode:

```json
{
  "mode": "dry-run",
  "validations_run": <int>,
  "validation_results": [...],
  "owner_escalations": [...],
  "quadlet_convergence_plans": {...}
}
```

Live apply mode:

```json
{
  "mode": "apply",
  "writes": <int>,
  "removals": <int>,
  "state_updated": true,
  "allow_destructive": <bool>,
  "owner_execution": [...]
}
```

Owner execution entries include phase, kind, owner_ref, summary with action
sequences and return codes.

## Decision Notes

- Decision: Apply is always single-host; multi-host orchestration belongs to the GitOps runner.

- Rationale: Single-host scope simplifies atomicity and safety gates; runner layer owns commit selection and rollback.

- Impact: No multi-host coordination inside apply; each host converges independently.

- ADR: 0003-gitops-runner-responsibility-boundary

- Decision: Drift detection compares desired manifest against both applied manifest and live filesystem.

- Rationale: Three-way comparison catches both desired→applied drift and external live drift, giving accurate write classification.

- Impact: Apply can distinguish "already converged" targets from "needs write" even when applied manifest is stale.

- ADR: 0002-hash-based-drift-detection-and-state-model

- Decision: Apply behavior is driven by typed owner execution and renderer-internal apply hints, not free-form reload commands.

- Rationale: Typed executors with explicit action sequences are testable, auditable, and safe; manifest-level reload_actions would weaken safety guarantees.

- Impact: Each artifact family has a dedicated executor with deterministic action ordering; adding new service types requires a new executor or extending an existing one.

- ADR: 0004-apply-execution-model

- Decision: Removal requires explicit prune flags; drifted removals are gated behind destructive gate.

- Rationale: Files whose live content differs from the applied hash may have been intentionally modified; deleting them without acknowledgment risks data loss.

- Impact: Default apply never deletes files; operators must opt in with `--prune` or `--force-prune`.

- ADR: null

- Decision: Quadlet network/volume changes stop dependent containers before and start them after via convergence plans.

- Rationale: Podman network/volume recreation while containers are running causes failures; planner-emitted stop/start ordering keeps convergence safe.

- Impact: Dependent containers experience brief downtime during infrastructure owner changes; ordering is deterministic via reverse requires edges.

- ADR: null

- Decision: Networkd netdev deletions use child-first topological order with ip link delete.

- Rationale: Deleting a parent interface (VLAN trunk) before child interfaces (ipvlan-l2) leaves orphan links; child-first ordering avoids kernel errors.

- Impact: Netdev removal ordering is planner-driven and independent from the write ordering.

- ADR: null

- Decision: Vault-agent changes trigger grouped restart per owner rather than per-file.

- Rationale: Vault-agent reads all templates on startup; restarting once per owner group is sufficient and avoids unnecessary churn.

- Impact: Multiple template/config changes for the same vault-agent instance result in a single restart.

- ADR: null

- Decision: Service directory ownership enforcement is idempotent at apply time.

- Rationale: Directories may exist but with incorrect permissions; applying owner/group/mode on every run keeps state converged without special-casing first-run.

- Impact: Service directories are always correct after apply regardless of prior state.

- ADR: 0004-apply-execution-model

- Decision: State rotation occurs only after full apply success.

- Rationale: If apply fails mid-run, the previous manifest remains valid for next comparison; partial state updates would corrupt drift detection.

- Impact: Interrupted applies are safe to retry without manual state cleanup.

- ADR: 0002-hash-based-drift-detection-and-state-model

- Decision: Caddy config reload uses in-container podman exec, with fallback restart on failure when hinted.

- Rationale: Caddy supports graceful reload inside the running container; full service restart is a last resort when reload fails (e.g., after breaking config fix).

- Impact: Most config changes are zero-downtime; restart_on_failure hint provides operator control for known risky changes.

- ADR: null

- Decision: File staging uses atomic rename (temp file + os.replace) for all artifacts.

- Rationale: Atomic rename prevents partial writes visible to running services; temp file in same directory avoids cross-filesystem copies.

- Impact: Each staged file is either fully present with correct content or absent; no corrupt intermediate states.

- ADR: null

## Acceptance Criteria

- [x] The accepted spec documents CLI apply and diff behavior, argument semantics, and safety gates.
- [x] The accepted spec documents drift planning logic with manifest loading, comparison, and write/removal classification.
- [x] The accepted spec documents owner-based execution model with phase ordering.
- [x] The accepted spec documents each executor family with inputs, actions, and failure behavior.
- [x] The accepted spec documents state management with manifest rotation and history retention.
- [x] The accepted spec records apply-phase implementation decisions and rationale.

### Evidence

Criterion: CLI apply and diff behavior, argument semantics, and safety gates.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/cli/apply.py](../../../src/abhaile/cli/apply.py) and [src/abhaile/cli/diff.py](../../../src/abhaile/cli/diff.py).
- Validation evidence: [tests/unit/python/cli/test_apply_diff_cli.py](../../../tests/unit/python/cli/test_apply_diff_cli.py) and [tests/integration/test_apply_integration.py](../../../tests/integration/test_apply_integration.py).

Criterion: Drift planning logic with manifest loading, comparison, and write/removal classification.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/plan/diff.py](../../../src/abhaile/plan/diff.py).
- Validation evidence: [tests/unit/python/plan/test_diff.py](../../../tests/unit/python/plan/test_diff.py) and [tests/integration/test_apply_integration.py](../../../tests/integration/test_apply_integration.py).

Criterion: Owner-based execution model with phase ordering.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/cli/apply.py](../../../src/abhaile/cli/apply.py) (phase dispatch functions) and [src/abhaile/apply/](../../../src/abhaile/apply/) (executor modules).
- Validation evidence: [tests/unit/python/apply/](../../../tests/unit/python/apply/) (per-executor unit tests) and [tests/integration/test_apply_integration.py](../../../tests/integration/test_apply_integration.py).

Criterion: Executor family contracts.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/apply/systemd.py](../../../src/abhaile/apply/systemd.py), [src/abhaile/apply/users.py](../../../src/abhaile/apply/users.py), [src/abhaile/apply/coredns.py](../../../src/abhaile/apply/coredns.py), [src/abhaile/apply/caddy.py](../../../src/abhaile/apply/caddy.py), [src/abhaile/apply/vault.py](../../../src/abhaile/apply/vault.py), [src/abhaile/apply/networkd.py](../../../src/abhaile/apply/networkd.py), [src/abhaile/apply/quadlet.py](../../../src/abhaile/apply/quadlet.py), and [src/abhaile/apply/service.py](../../../src/abhaile/apply/service.py).
- Validation evidence: [tests/unit/python/apply/test_systemd.py](../../../tests/unit/python/apply/test_systemd.py), [tests/unit/python/apply/test_users_executor.py](../../../tests/unit/python/apply/test_users_executor.py), [tests/unit/python/apply/test_coredns_executor.py](../../../tests/unit/python/apply/test_coredns_executor.py), [tests/unit/python/apply/test_caddy_executor.py](../../../tests/unit/python/apply/test_caddy_executor.py), [tests/unit/python/apply/test_vault_executor.py](../../../tests/unit/python/apply/test_vault_executor.py), [tests/unit/python/apply/test_networkd_executor.py](../../../tests/unit/python/apply/test_networkd_executor.py), [tests/unit/python/apply/test_quadlet_executor.py](../../../tests/unit/python/apply/test_quadlet_executor.py), and [tests/unit/python/apply/test_service_executor.py](../../../tests/unit/python/apply/test_service_executor.py).

Criterion: State management with manifest rotation and history retention.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete) for [src/abhaile/state/history.py](../../../src/abhaile/state/history.py).
- Validation evidence: [tests/unit/python/state/test_history.py](../../../tests/unit/python/state/test_history.py).

Criterion: Apply-phase implementation decisions and rationale.

- Implementation evidence: [commit 56211e3 record](implementation-evidence.md#commit-56211e3-rewrite-apply--secrets-complete), apply-phase canonical decisions in [TODO.md](../../../TODO.md), and [ADR 0004](../../adr/0004-apply-execution-model.md).
- Validation evidence: cross-check against [src/abhaile/cli/apply.py](../../../src/abhaile/cli/apply.py), [src/abhaile/apply/](../../../src/abhaile/apply/), and [src/abhaile/plan/diff.py](../../../src/abhaile/plan/diff.py).

## Out of Scope

- Any new apply pipeline behavior or executor additions.
- Render pipeline implementation details beyond the manifest contract consumed by diff/apply.
- GitOps runner orchestration (commit selection, scheduling, rollback strategy).
- Software artifact execution (packages, downloads, builds, commands) — these are rendered but
  apply execution is deferred to a future phase.
- Creating new implementation behavior solely to satisfy documentation evidence requirements.

## Open Questions

- None.

## References

- `docs/specs/GOVERNANCE.md`
- `docs/specs/_template.md`
- `src/abhaile/cli/apply.py`
- `src/abhaile/cli/diff.py`
- `src/abhaile/cli/common.py`
- `src/abhaile/plan/diff.py`
- `src/abhaile/apply/actions.py`
- `src/abhaile/apply/systemd.py`
- `src/abhaile/apply/users.py`
- `src/abhaile/apply/coredns.py`
- `src/abhaile/apply/caddy.py`
- `src/abhaile/apply/vault.py`
- `src/abhaile/apply/networkd.py`
- `src/abhaile/apply/quadlet.py`
- `src/abhaile/apply/service.py`
- `src/abhaile/state/history.py`
- `TODO.md`
- `docs/adr/0001-output-root-and-environment-paths.md`
- `docs/adr/0002-hash-based-drift-detection-and-state-model.md`
- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `docs/adr/0004-apply-execution-model.md`
- `docs/adr/0005-service-authoring-model.md`
