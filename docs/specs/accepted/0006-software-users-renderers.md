# Spec: Software and Users Renderers

## Metadata

```yaml
id: SPEC-2026-006
title: Software and Users Renderers
status: accepted
owner: moonpie
created: 2026-06-04
updated: 2026-06-05
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: []
```

## Context

The software and users renderers are implemented. This accepted
spec documents the delivered contracts between host intent in `config/hosts/<host>/host.yaml`
and rendered artifacts under host output directories.

Documented behavior includes:

1. Software package selection and deterministic `packages.txt` generation.
1. Per-entry software action rendering for `downloads`, `builds`, and `commands`.
1. Include-merged user/group/sudo intent and rendered `sysusers` and `sudoers` artifacts.
1. Validation expectations across schema validation, include-merge checks, and renderer fail-fast checks.
1. Historical implementation decisions captured in TODO Decision Log entries for software and user management.

## Requirements

- [x] Document `packages.txt` generation and package selection semantics across host includes.
- [x] Document rendered output contracts for software action specs (`downloads`, `builds`, `commands`).
- [x] Document `sysusers` output contract, ordering rules, and group membership output.
- [x] Document `sudoers` output contract and include-merge semantics.
- [x] Document validation expectations from host schema, software action schema, and user id validation.
- [x] Document contract boundaries from host intent to rendered artifacts with failure conditions.
- [x] Record relevant TODO Decision Log outcomes that shaped the implemented behavior.

## Constraints

- Host intent is authored only in `config/hosts/<host>/host.yaml` and include-linked host files.
- Rendering must be deterministic and idempotent for identical config input.
- Duplicate or ambiguous software/user definitions fail fast with `RenderError`.
- Render remains unprivileged; apply owns execution and reconciliation of rendered artifacts.

## Design

### Host Include Composition Contract

Both renderers resolve host composition through depth-first `composition.include` traversal
using `_walk_host_includes()`.

Ordering contract:

1. Included hosts are processed before the direct host.
1. Each host appears at most once via visited tracking.
1. Include cycles are rejected with explicit cycle path errors.

For current host intent:

- `phobos` includes `common`, so software and user-management content is merged as `common` then `phobos`.
- `deimos` includes `common`; it currently inherits package baseline and adds no host-local software entries.

### Software Renderer Contract

`render_software_artifacts()` consumes `composition.software` keys:

- `packages`
- `downloads`
- `builds`
- `commands`

#### Package selection and `packages.txt`

Contract:

1. Package IDs are merged in include traversal order and in-list order.
1. Duplicate package IDs across include chain are render errors.
1. Output is a newline-delimited file at `rendered/software/packages.txt`.
1. No sorting is applied; deterministic order comes from deterministic include traversal plus list order.

Observed current intent behavior:

- `common` defines baseline packages (for example `podman`, `curl`, `sudo`, `chrony`).
- `phobos` adds `ddclient`.
- `deimos` currently contributes no additional software keys.

#### Action-spec rendering (`downloads`, `builds`, `commands`)

Contract:

1. Each referenced action ID must exist as `config/hosts/<source-host>/software/<key>/<id>.yaml`.
1. Source host for each ID is the host where that ID was introduced in include traversal.
1. Each spec is validated against `schemas/software-action.schema.json`.
1. Spec `id` must equal the referenced ID.
1. Output is one YAML file per ID under:
   - `rendered/software/downloads/<id>.yaml`
   - `rendered/software/builds/<id>.yaml`
   - `rendered/software/commands/<id>.yaml`

Failure contract:

- Missing referenced spec file -> `RenderError`.
- Schema validation failure -> `RenderError`.
- Referenced ID and spec `id` mismatch -> `RenderError`.
- Duplicate IDs across include chain for any software key -> `RenderError`.

### Users Renderer Contract

`render_users_artifacts()` consumes `composition.user_management`:

- `users`
- `groups`
- `sudoers`

Merge semantics across include chain:

1. Users and groups merge by name.
1. User scalar fields (`uid`, `system`, `primary_group`, `home`, `shell`, `gecos`) must match if redefined.
1. User list fields (`additional_groups`, `ssh_authorized_keys`) are unioned in first-seen order.
1. Group `gid` must match if redefined.
1. Sudoers merge by entry `name`; rules are deduplicated and appended in first-seen order before final write.

#### `sysusers` output

Contract:

1. Output path is `rendered/system/etc/sysusers.d/abhaile.conf`.
1. Header line is always `# Managed by Abhaile. Do not edit.`.
1. Group records are emitted first, sorted by group name:
   - `g <group> <gid-or->`
1. User records are emitted next, sorted by user name:
   - `u <user> <uid-or-> <primary-group> <gecos-or-> <home-or-> <shell-or->`
1. Membership records follow each user with sorted unique additional groups:
   - `m <user> <group>`

Validation before writing:

1. User `primary_group` must exist in merged groups (defaults to user name if absent).
1. All `additional_groups` must exist in merged groups.
1. Missing group references produce aggregated `RenderError` output.

#### `sudoers` output

Contract:

1. Output path is `rendered/system/etc/sudoers.d/abhaile`.
1. Header line is always `# Managed by Abhaile. Do not edit.`.
1. Rules are written sorted and deduplicated by merged sudoer-name bucket.
1. `sudoer.name` is a merge key only; output content is the rule lines.

#### `authorized_keys` output

Contract:

1. For users with non-empty `ssh_authorized_keys`, output path is `<home>/.ssh/authorized_keys`
   under rendered system tree.
1. Key lines are sorted and deduplicated with managed header.
1. Users with home `-` are skipped.

### Artifact Metadata and Apply Hints Contract

When a collector is provided, users renderer registers artifact metadata used by apply:

- `host.sysusers` -> target `/etc/sysusers.d/abhaile.conf`, mode `0644`, owner `root:root`.
- `host.sudoers` -> target `/etc/sudoers.d/abhaile`, mode `0440`, owner `root:root`, requires `host-users:<host>`.
- `host.authorized_keys` -> target `<home>/.ssh/authorized_keys`, mode `0600`, `.ssh` dir mode `0700`, owner `<user>:<primary_group-or-user>`, requires `host-users:<host>`.

This metadata bridges render outputs to ordered apply execution semantics.

### Validation Expectations

Validation is enforced at multiple layers:

1. Host schema validation (`schemas/host.schema.json`) requires `composition.software` and `composition.user_management` keys and constrains field shapes/types.
1. User id/gid and scalar conflict validation (`validate_user_management_ids`) runs during host validation in render CLI and fails on duplicate uid/gid across different names or conflicting scalar redefinitions.
1. Software action schema validation (`schemas/software-action.schema.json`) is enforced per rendered action spec.
1. Renderer-level validations enforce include shape, list typing, reference existence, and merge conflict rules.

Contract summary:

- Invalid host intent should fail in validation before or during rendering, never silently produce partial ambiguous artifacts.

## Decision Notes

- Decision: Software output uses mixed granularity (`packages.txt` plus per-entry action specs) with duplicate ID rejection.

- Rationale: Keep package reconciliation simple while preserving fine-grained drift/apply targeting for downloads/builds/commands.

- Impact: Stable package artifact plus explicit action-spec units and fail-fast ambiguity handling.

- ADR: null

- Decision: User management schema and renderer use sysusers-aligned `gecos`, include-merge semantics, and strict scalar/list validation.

- Rationale: Declarative identity management must stay deterministic and conflict-safe across host includes.

- Impact: Consistent merged user intent, explicit uid/gid conflict detection, and deterministic `sysusers`/`sudoers` artifacts.

- ADR: null

- Decision: User management rendering outputs declarative `sysusers` and `sudoers` files instead of imperative setup scripts.

- Rationale: Aligns host identity reconciliation with idempotent drift/apply model.

- Impact: Apply can validate and execute user-management changes with typed artifact behavior.

- ADR: 0005-service-authoring-model

## Acceptance Criteria

- [x] Accepted reference spec documents implemented package selection and `packages.txt` generation.
- [x] Accepted reference spec documents per-entry software action rendering and validation behavior.
- [x] Accepted reference spec documents implemented `sysusers` and `sudoers` output contracts.
- [x] Accepted reference spec documents host intent to rendered artifact contracts for software and users.
- [x] Accepted reference spec documents validation expectations across schema, CLI validation, and renderer checks.
- [x] Accepted reference spec records relevant TODO Decision Log context for software and users behavior.

### Evidence

Criterion: Package selection and `packages.txt` generation.

- Implementation evidence: `src/abhaile/renderers/software.py` (`_walk_host_includes`, `_collect_software_refs`, `_write_packages_file`).
- Validation evidence: `tests/unit/python/renderers/test_software.py` (`test_render_software_merges_and_renders_artifacts`, duplicate and missing-spec error tests).

Criterion: Per-entry software action rendering and validation.

- Implementation evidence: `src/abhaile/renderers/software.py` (schema load, `validate_schema`, id-match enforcement).
- Validation evidence: `tests/unit/python/renderers/test_software.py`.

Criterion: `sysusers` and `sudoers` output contracts.

- Implementation evidence: `src/abhaile/renderers/users.py` (`_write_sysusers_file`, `_write_sudoers_file`, `_validate_user_group_references`).
- Validation evidence: `tests/unit/python/renderers/test_users.py` (`test_render_users_merges_and_renders_sysusers_and_sudoers`, conflict and missing-group tests).

Criterion: Host intent to rendered artifact metadata contracts.

- Implementation evidence: `src/abhaile/renderers/users.py` (`_register_users_artifact`, apply hints and owner dependencies), `src/abhaile/cli/render.py` (`_render_host_software`, `_render_host_users`).
- Validation evidence: `tests/unit/python/renderers/test_users.py` (`test_render_users_registers_metadata`), `tests/unit/python/apply/test_users_executor.py` (sysusers/sudoers executor behavior), `tests/unit/python/cli/test_apply_diff_cli.py` (`host.sysusers` owner-execution integration path).

Criterion: Validation expectations.

- Implementation evidence: `schemas/host.schema.json`, `src/abhaile/validation/users.py`, `src/abhaile/cli/render.py` (host validation path), `src/abhaile/renderers/software.py` (action schema enforcement).
- Validation evidence: `tests/unit/python/validation/test_users.py`, `tests/unit/python/validation/test_schema.py`.

Criterion: TODO Decision Log context.

- Implementation evidence: TODO entries dated 2026-03-05 and 2026-03-06 covering software granularity, sysusers/sudoers approach, schema alignment, and include-merge semantics in `TODO.md`.
- Validation evidence: Current behavior in renderers/validation modules matches those decision statements.

## Out of Scope

- Changing host schema shape or user/software merge rules.
- Introducing new software action categories beyond `downloads`, `builds`, and `commands`.
- Changing apply executor behavior for software or user artifacts.
- Any changes to host intent in `config/hosts/*/host.yaml`.

## Open Questions

- None.

## References

- `docs/specs/_template.md`
- `docs/specs/GOVERNANCE.md`
- `src/abhaile/renderers/software.py`
- `src/abhaile/renderers/users.py`
- `src/abhaile/cli/render.py`
- `src/abhaile/validation/users.py`
- `config/hosts/common/host.yaml`
- `config/hosts/phobos/host.yaml`
- `config/hosts/deimos/host.yaml`
- `schemas/host.schema.json`
- `schemas/software-action.schema.json`
- `tests/unit/python/renderers/test_software.py`
- `tests/unit/python/renderers/test_users.py`
- `tests/unit/python/validation/test_users.py`
- `TODO.md`
