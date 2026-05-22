# Spec: Manifest and Drift Model

## Metadata

```yaml
id: SPEC-2026-008
title: Manifest and Drift Model
status: accepted
owner: moonpie
created: 2026-06-04
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0003-gitops-runner-responsibility-boundary
  - 0004-apply-execution-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The manifest and drift model is implemented and is part of the current render,
diff, and apply workflow. This accepted spec records the implemented contracts
so future work can treat them as reference behavior rather than rediscovering
them from code, tests, ADRs, and historical TODO entries.

The model separates three states that participate in reconciliation:

1. Desired state from the current render under `<output>/rendered/manifest.json`.
1. Durable last-applied state under `<output>/state/manifest.json` and related history files.
1. Live host filesystem state observed at apply or diff time.

Drift detection is hash-based, host-scoped, and owner-aware. Render produces the
desired manifest. Diff and apply compare desired, applied, and live state to
classify writes and removals. Apply mutates durable state only after successful
execution.

## Requirements

- [x] Document the manifest schema emitted by render and consumed by diff/apply.
- [x] Document rendered versus applied state ownership and directory layout.
- [x] Document hash-based drift classification semantics for writes, removals, and prune safety.
- [x] Document owner metadata and dependency ordering contracts used by planning and apply.
- [x] Document state rotation, previous-manifest handling, and bounded history retention.
- [x] Record the implemented CLI and runner boundary decisions from TODO and ADR history.

## Constraints

- `config/` remains the source of truth; manifests are derived state.
- `<output>/rendered/` is ephemeral and may be wiped and rebuilt by render.
- `<output>/state/` is durable and apply-owned; render does not mutate it.
- Drift detection must remain deterministic for identical artifact content and target paths.
- Apply is single-host and must fail closed on host identity mismatch unless explicitly overridden.
- Dry-run is read-only and must not update durable state.
- Commit selection, scheduling, locking, and rollback remain outside this model in the GitOps runner layer.

## Design

### State Model and Layout

The implemented layout follows the repository-wide output-root conventions.

In single-host render mode, desired artifacts are written into
`<output>/rendered/`. In `--all` render mode, each host gets its own rendered
tree under `<output>/<host>/rendered/`. Apply remains single-host and resolves
its effective `rendered/` and `state/` roots from the manifest paths provided to
that invocation.

Desired-state layout:

- `rendered/system/` for atomic file-placement artifacts (systemd-networkd, resolved, sysusers, sudoers, authorized_keys).
- `rendered/software/` for execution-driven software specs.
- `rendered/services/<service>/` for service-scoped configs, quadlets, vault templates, and similar artifacts.
- `rendered/manifest.json` for the desired manifest inventory.

Applied-state layout:

- `state/manifest.json` for the last successfully applied manifest.
- `state/manifest.previous.json` for the immediately previous applied manifest.
- `state/history/manifest-<timestamp>.json` for timestamped history snapshots.

The rendered directory structure is organizational only. Apply decisions are made
from manifest metadata, especially absolute `target_path` values, not from the
render tree layout itself.

### Manifest Schema

`src/abhaile/renderers/manifest.py` serializes the manifest from collected
`RenderMetadata` in `src/abhaile/models/artifact.py`.

Top-level manifest contract:

- `version`: currently fixed to `"1"`.
- `host`: required host identifier for safety checks and state matching.
- `rendered_at`: UTC ISO 8601 timestamp with `Z` suffix.
- `entries`: ordered list of artifact records.
- `owners`: optional object keyed by owner reference.

Artifact entry contract:

- `render_path`: path relative to the rendered root.
- `target_path`: absolute on-host destination path.
- `kind`: typed artifact family used by apply executors.
- `owner_ref`: owner identifier used for grouping and dependency planning.
- `sha256`: content hash of the rendered artifact.
- `size`: rendered artifact size in bytes.
- `contributor_ref`: optional contributor identity for aggregated artifacts.
- `apply_hints`: optional structured hints for execution behavior.

Owner entry contract:

- key and `name` must match the owner reference.
- `description` is optional descriptive metadata.
- `requires` is an optional list of prerequisite owner references.
- `apply_hints` is optional owner-level execution metadata.

Serialization guarantees:

1. Entries are ordered by `render_path`.
1. Owners are ordered by owner name and emitted as a deterministic object.
1. Manifest serialization fails if any artifact is missing a computed hash or size.
1. The manifest JSON is pretty-printed with stable key ordering.

### Render Contract

Render collects artifacts, computes hashes and sizes against the rendered tree,
and writes `rendered/manifest.json` only after artifact metadata is complete.

The render-side contract consumed by diff/apply is:

1. Every manifest entry identifies one authoritative `target_path`.
1. Hashes represent rendered desired content, not live content.
1. Manifest host must match the rendered host and later the applied host state.
1. Owner metadata is included when needed for ordered execution and convergence.

This makes render the sole producer of desired manifests and keeps desired-state
representation independent from previous renders.

### Diff and Drift Semantics

`src/abhaile/plan/diff.py` defines the drift model used by both `abhaile-diff`
and `abhaile-apply`.

Manifest loading rules:

1. The desired manifest is required.
1. The applied manifest is optional; a missing applied manifest is treated as an empty state for the desired host.
1. Existing applied manifests must have the same `host` as the desired manifest.
1. Manifest validation is structural and fails on malformed entries, invalid hashes, non-absolute target paths, duplicate target paths, or invalid owner metadata.

Comparison identity rule:

- Entries are matched by `target_path`.

Desired-versus-applied diff classification:

- `added`: target paths present in desired but absent in applied.
- `changed`: target paths present in both manifests with different desired and applied hashes.
- `removed`: target paths present in applied but absent in desired.

Live-state classification refines sync behavior:

- `writes`: desired entries whose live host hash does not already match the desired hash.
- `removals_safe`: removed entries whose live host hash still matches the applied manifest hash.
- `removals_drifted`: removed entries whose live host content exists but no longer matches the applied manifest hash.
- `removals_missing`: removed entries whose live path is already absent.

Write reason contract:

- `missing`: target path absent on host.
- `add`: target path absent from applied state but present in desired and not already matching live.
- `change`: target path exists in both manifests and desired hash differs from applied hash.
- `drift`: target path matches applied state metadata but live host content diverges from desired.

Non-regular live files are treated as a special live-hash marker rather than as
matching content, which prevents silent convergence over symlinks or other
non-regular file types.

### Owner Model and Planning Contract

The manifest is not only a file inventory. It also carries the owner dependency
graph used for ordered apply behavior.

Planning behavior:

1. Writes and removals are grouped under the manifest owner reference.
1. Removal ownership comes from applied-state entries, not desired entries.
1. Owner prerequisite closure is expanded through `requires` inside `owner_plan` so planner output can preserve dependency context even when prerequisite owners have no direct file changes.
1. Owners are topologically sorted and owner cycles fail closed.

Planner outputs built from owner metadata include:

- `owner_plan` with ordered owner bundles, grouped writes/removals, and escalation markers.
- `networkd_netdev_delete_order` for child-first deletion ordering of networkd netdev owners.
- `quadlet_convergence_plans` for stop/start orchestration around changed quadlet network and volume owners.

`owner_plan` is primarily a planning and reporting structure. Current apply
execution does not generically dispatch unchanged prerequisite owners from that
plan; it consumes owner escalations plus specialized derived plans such as the
networkd delete order and quadlet convergence plans.

Escalation semantics currently include at least:

- `prune-drifted` when a removal candidate has local drift.
- `missing-owner-metadata` when the planner must operate without owner metadata for a changed owner.

### Apply Contract

`src/abhaile/cli/apply.py` consumes the drift plan and applies it to the local
host.

Path resolution contract:

- By default, desired state resolves to `<output>/rendered/manifest.json`.
- By default, applied state resolves to `<output>/state/manifest.json`.
- Explicit manifest paths are supported and redefine the effective rendered/state roots for that invocation.

Host safety contract:

1. `manifest.host` must be present.
1. An explicit `--host` must match the manifest host unless `--allow-host-mismatch` is set.
1. The local short hostname must match the expected host unless `--allow-host-mismatch` is set.

Mutation contract:

1. Apply copies desired write artifacts from the rendered tree to their `target_path` locations.
1. `service.directory` entries are represented in the manifest but bypass the generic file-copy path.
1. `service.directory` entries are enforced idempotently during service-owner execution using directory apply hints.
1. Removals are never executed by default.
1. `--prune` applies only `removals_safe`.
1. `--force-prune` applies `removals_safe` and `removals_drifted`, gated by destructive-action approval.
1. Owner-family executors run after file synchronization using typed `kind` values and owner/apply hints.
1. Durable state is updated only after successful non-dry-run execution.

Dry-run contract:

- `--dry-run` produces plan output only and performs no mutations.
- `--dry-run-validations` is allowed only with `--dry-run` and runs read-only validation commands for selected artifact families.
- Dry-run does not dispatch owner actions and does not rotate state manifests.

### State Rotation and History

`src/abhaile/state/history.py` owns durable manifest rotation after successful
apply.

Rotation behavior:

1. On first successful apply, only `state/manifest.json` is created.
1. On subsequent successful applies, the previous current manifest is copied to `state/manifest.previous.json`.
1. That same prior current manifest is archived into `state/history/manifest-<timestamp>.json`.
1. Timestamp collisions are resolved by appending `-<counter>`.
1. History retention is bounded by `keep_history`, defaulting to `10`.
1. State rotation fails closed if the desired manifest is missing or if state writes cannot complete.

This creates a durable record of successful applies without requiring retention
of previous rendered trees.

### CLI and Runner Boundary

The implemented CLI split is:

- `abhaile-diff` for read-only manifest drift summaries.
- `abhaile-apply` for host-local reconciliation.

The manifest and drift model deliberately stops at plan and apply execution.
Commit selection, scheduling, locking, and rollback-to-last-known-good remain in
the GitOps runner layer and are not part of `src/abhaile/plan/`,
`src/abhaile/apply/`, or `src/abhaile/state/`.

## Decision Notes

- Decision: Separate desired render manifests from durable applied-state manifests.

- Rationale: Desired state is ephemeral and render-owned, while last-applied state must survive across renders and host runs.

- Impact: Drift detection compares desired, applied, and live state instead of diffing old and new rendered trees.

- ADR: 0002-hash-based-drift-detection-and-state-model

- Decision: Treat manifest entries as hash-based inventories keyed by absolute `target_path` with typed ownership metadata.

- Rationale: Apply needs both deterministic content identity and execution context beyond plain file paths.

- Impact: Planner and executors can classify drift, group by owner, and order runtime actions safely.

- ADR: 0002-hash-based-drift-detection-and-state-model

- Decision: Keep `<output>/rendered/` ephemeral and `<output>/state/` durable and apply-owned.

- Rationale: Render should be disposable and unprivileged, while durable reconciliation history belongs to successful apply outcomes.

- Impact: Render never mutates apply state and apply updates durable manifests only after success.

- ADR: 0001-output-root-and-environment-paths

- Decision: Keep apply and diff as Python CLI entrypoints with orchestration in `src/abhaile/cli/` and implementation in `plan/`, `apply/`, and `state/`.

- Rationale: The drift model is typed, testable, and shared across command surfaces.

- Impact: Read-only diff and mutating apply use the same planning contract instead of parallel implementations.

- ADR: null

- Decision: Keep prune conservative by default and require explicit destructive allowance for drifted removals.

- Rationale: A removed desired artifact may have been changed locally and should not be deleted implicitly.

- Impact: `--prune` is safe-only, while `--force-prune` plus destructive approval is required for locally drifted removals.

- ADR: 0004-apply-execution-model

- Decision: Leave commit tracking, rollback, and scheduling outside the manifest/state subsystem.

- Rationale: Those concerns belong to the GitOps runner boundary, not to render/apply core logic.

- Impact: `state/` records applied manifests, not runner progress or commit-selection state.

- ADR: 0003-gitops-runner-responsibility-boundary

## Acceptance Criteria

- [x] The accepted spec documents the implemented manifest schema and owner metadata contracts.
- [x] The accepted spec documents rendered versus applied state layout and ownership boundaries.
- [x] The accepted spec documents implemented hash-based drift, write, and prune classification semantics.
- [x] The accepted spec documents the apply contract for dry-run, prune, safety gates, and state updates.
- [x] The accepted spec documents state rotation and bounded history behavior.
- [x] The accepted spec records relevant TODO and ADR decisions that shaped the final model.

### Evidence

Criterion: Manifest schema and owner metadata contracts.

- Implementation evidence: `src/abhaile/renderers/manifest.py`, `src/abhaile/models/artifact.py`.
- Validation evidence: `tests/unit/python/renderers/test_manifest.py` and `tests/unit/python/renderers/test_metadata.py`.

Criterion: Rendered versus applied state layout and ownership boundaries.

- Implementation evidence: `src/abhaile/cli/common.py`, `src/abhaile/cli/render.py`, `src/abhaile/state/history.py`.
- Validation evidence: `tests/integration/test_render_e2e.py` and `tests/unit/python/state/test_history.py`.

Criterion: Hash-based drift, write, and prune classification semantics.

- Implementation evidence: `src/abhaile/plan/diff.py`, `src/abhaile/cli/diff.py`, `src/abhaile/cli/apply.py`.
- Validation evidence: `tests/unit/python/plan/test_diff.py`, `tests/unit/python/cli/test_apply_diff_cli.py`, and `tests/integration/test_apply_integration.py`.

Criterion: Apply contract for dry-run, prune, safety gates, and state updates.

- Implementation evidence: `src/abhaile/cli/apply.py`, `src/abhaile/apply/`, `src/abhaile/cli/common.py`.
- Validation evidence: `tests/unit/python/cli/test_apply_diff_cli.py` and `tests/integration/test_apply_integration.py`.

Criterion: State rotation and bounded history behavior.

- Implementation evidence: `src/abhaile/state/history.py`.
- Validation evidence: `tests/unit/python/state/test_history.py` and `tests/integration/test_apply_integration.py`.

Criterion: Decision capture for manifests, state, and drift.

- Implementation evidence: TODO decision entries for the manifest/state model, apply/diff CLI split, single-host apply, and runner boundary in `TODO.md`, plus ADRs 0001 through 0004.
- Validation evidence: `N/A` for executable validation; this criterion is documentary traceability for an accepted reference spec and was validated by source cross-check against `TODO.md`, ADRs 0001 through 0004, `src/abhaile/renderers/manifest.py`, `src/abhaile/plan/diff.py`, `src/abhaile/cli/apply.py`, and `src/abhaile/state/history.py`.

## Out of Scope

- Changing manifest versioning, entry schema, or owner metadata semantics.
- Defining GitOps runner commit-tracking or rollback state formats.
- Adding new apply executors or artifact kinds.
- Introducing state writes during dry-run.
- Any implementation changes solely to align documentation wording.

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `docs/specs/accepted/0001-render-pipeline.md`
- `README.md`
- `docs/APPLY.md`
- `TODO.md`
- `src/abhaile/renderers/manifest.py`
- `src/abhaile/models/artifact.py`
- `src/abhaile/plan/diff.py`
- `src/abhaile/state/history.py`
- `src/abhaile/cli/common.py`
- `src/abhaile/cli/diff.py`
- `src/abhaile/cli/apply.py`
- `src/abhaile/apply/`
- `docs/adr/0001-output-root-and-environment-paths.md`
- `docs/adr/0002-hash-based-drift-detection-and-state-model.md`
- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `docs/adr/0004-apply-execution-model.md`
