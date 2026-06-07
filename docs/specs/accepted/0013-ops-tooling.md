# Spec: Ops Tooling

## Metadata

```yaml
id: SPEC-2026-013
title: Ops Tooling
status: accepted
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0007-sops-bootstrap-policy-and-layout
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The render and apply pipelines are complete with working CLI entrypoints (`abhaile-render`,
`abhaile-apply`, `abhaile-diff`). The project lacks operator-facing convenience tooling for
common workflows: Make targets for render/apply/validate, a host inventory view, full diff
capabilities, and sealed bootstrap artifact lifecycle management.

The diff entrypoint (`src/abhaile/cli/diff.py`) exists and compares desired vs applied
manifests using `plan_manifest_drift`. It accepts two manifest paths, supports `--json`
output, and prints a human-readable summary. What remains is defining exit-code semantics
for automation, explicit two-positional-path mode documentation, and integration into Make
targets.

Sealed bootstrap artifacts follow the layout in ADR 0007 (`config/bootstrap/sealed/<host>/`)
with `.sops.yaml` suffix and age-based recipient model. Operators need canonical tooling for
create/edit/rotate workflows that prevent accidental plaintext commits.

## Requirements

- [x] Makefile provides `render`, `apply`, and `validate` targets that call canonical CLI
  entrypoints and return non-zero on failure.
- [x] A host inventory command prints host-to-services mapping from `config/mapping.yaml` in
  deterministic order.
- [x] `abhaile-diff` defines predictable exit codes for automation (no diff, diff found,
  error).
- [x] Sealed bootstrap artifact tooling provides create, edit, and rotate workflows without
  exposing plaintext in git.
- [x] All new tooling is documented with usage examples.

## Constraints

- No network access required for any target.
- No secrets stored in the repository or rendered output.
- Make targets call Python entrypoints or thin wrappers; no business logic in Makefile.
- Read-only operations (diff, inventory, validate) require no host privileges.
- Sealed artifact tooling depends on `sops` and `age` being available on the workstation.
- Must not duplicate validation or rendering logic that already exists in `src/abhaile/`.

## Design

### Task 1: Make Targets

Add targets to the existing Makefile:

```makefile
render: $(VENV)
    $(VENV_PYTHON) -m abhaile.cli.render --all --output ./out

render-host: $(VENV)
    @test -n "$(HOST)" || (echo "Usage: make render-host HOST=phobos" >&2; exit 1)
    $(VENV_PYTHON) -m abhaile.cli.render --host $(HOST) --output ./out

apply: $(VENV)
    @test -n "$(HOST)" || (echo "Usage: make apply HOST=phobos" >&2; exit 1)
    $(VENV_PYTHON) -m abhaile.cli.render --host $(HOST) --output ./out
    $(VENV_PYTHON) -m abhaile.cli.apply --host $(HOST) --output ./out --dry-run

diff: $(VENV)
    $(VENV_PYTHON) -m abhaile.cli.diff --output ./out

validate: $(VENV)
    $(VENV_PYTHON) -m abhaile.cli.render --all --output ./out
```

Design decisions:

- `make render` renders all hosts by default; `make render-host HOST=x` renders a single host.
- `make apply` defaults to dry-run for safety. Live apply requires the operator to invoke
  `abhaile-apply` directly without `--dry-run`.
- `make diff` calls `abhaile-diff` with default output root (single-host mode).
- `make validate` is functionally equivalent to a full render (which runs all validation as
  part of the pipeline). A dedicated validate-only entrypoint is out of scope unless the
  pipeline grows a non-rendering validation mode.
- Output defaults to `./out` for workstation use.
- `HOST` is passed as a Make variable (e.g., `make render-host HOST=phobos`).

### Task 2: Host Inventory View

Provide a Python CLI entrypoint `abhaile-inventory` registered in `pyproject.toml`.

Module: `src/abhaile/cli/inventory.py`

Behavior:

- Reads `config/mapping.yaml` and prints each host with its mapped services.
- Deterministic output order: hosts sorted alphabetically, services in mapping-file order.
- Default output is human-readable table format.
- `--json` flag outputs machine-readable JSON.
- `--validate` flag checks that each mapped service has a corresponding
  `config/services/<service>/service.yaml` and exits non-zero if any are missing.
- Exit codes: 0 = success, 1 = validation failure or config error.

Example output (human-readable):

```text
deimos:
  coredns-clean
  caddy-internal
  ...

phobos:
  coredns-filtered
  caddy-dmz
  ...
```

Design decisions:

- Python entrypoint (not a shell script) to reuse `abhaile.validation.services` and
  `abhaile.utils.config` modules.
- Validation is opt-in to keep default usage fast and read-only.
- Does not duplicate full config validation (schema, network sanity, etc.) — that belongs to
  the render pipeline.

### Task 3: Diff Tool (`abhaile-diff`)

The entrypoint exists at `src/abhaile/cli/diff.py` with working comparison logic via
`plan_manifest_drift`. The implementation reads two manifest files, classifies entries as
added/changed/removed, and outputs a summary.

What exists:

- Two-positional-path mode and `--desired-manifest`/`--applied-manifest` named arguments.
- `--output` for path resolution from standard output root.
- `--json` for structured output.
- Human-readable summary via `print_diff_summary`.
- Comparison by `target_path` with SHA256 hash checking.

What remains to implement:

- **Exit codes for automation:**
  - `0` — no differences found.
  - `1` — differences found (added, changed, or removed entries present).
  - `2` — error (invalid manifest, missing file, schema mismatch).
- **Metadata-only change reporting:** entries where `target_path` and `sha256` match but
  `kind`, `owner_ref`, or `apply_hints` differ are reported as metadata changes (distinct
  from content changes).
- **Make target:** `make diff` calls `abhaile-diff` with default paths.

Design decisions:

- Exit code 1 for "diff found" follows the `diff(1)` convention and enables use in shell
  conditionals and CI gates.
- Current implementation always returns 0; adding exit-code semantics is backward-compatible
  for JSON consumers (they parse output, not exit code).
- Metadata-only changes are informational but do not affect content drift decisions.

### Task 4: Sealed Bootstrap Artifact Tooling

Provide Make targets and a thin wrapper script for `sops` operations on sealed bootstrap
artifacts under `config/bootstrap/sealed/`.

#### Make Targets

```makefile
bootstrap-create:
    @test -n "$(HOST)" || (echo "Usage: make bootstrap-create HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
    @test -n "$(NAME)" || (echo "Usage: make bootstrap-create HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
    scripts/sops-bootstrap create $(HOST) $(NAME)

bootstrap-edit:
    @test -n "$(HOST)" || (echo "Usage: make bootstrap-edit HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
    @test -n "$(NAME)" || (echo "Usage: make bootstrap-edit HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
    scripts/sops-bootstrap edit $(HOST) $(NAME)

bootstrap-rotate:
    @test -n "$(HOST)" || (echo "Usage: make bootstrap-rotate HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
    @test -n "$(NAME)" || (echo "Usage: make bootstrap-rotate HOST=phobos NAME=vault-bootstrap" >&2; exit 1)
    scripts/sops-bootstrap rotate $(HOST) $(NAME)

bootstrap-validate:
    scripts/sops-bootstrap validate
```

#### Wrapper Script: `scripts/sops-bootstrap`

A shell script that enforces:

- Correct path derivation: `config/bootstrap/sealed/<host>/<name>.sops.yaml`.
- Correct `.sops.yaml` configuration for age recipients (reads from a project-level
  `.sops.yaml` creation rules file or explicit recipient arguments).
- `create` — initializes a new encrypted file with the correct recipients.
- `edit` — opens the encrypted file with `sops edit` (decrypts in memory via editor).
- `rotate` — runs `sops updatekeys` to apply new/changed recipients from `.sops.yaml`.
- `validate` — verifies all files under `config/bootstrap/sealed/` are encrypted (not
  plaintext), have valid SOPS metadata, and match the expected naming convention.

Safety guarantees:

- `validate` runs as a pre-commit check to block accidental plaintext commits.
- `create` refuses to overwrite existing artifacts without `--force`.
- No decrypted content is written to disk outside the editor tmpfile managed by `sops`.

#### SOPS Configuration

A repo-root `.sops.yaml` defines creation rules:

```yaml
creation_rules:
  - path_regex: config/bootstrap/sealed/phobos/.*\.sops\.yaml$
    age: >-
      <phobos-host-recipient>,
      <operator-recovery-recipient>
  - path_regex: config/bootstrap/sealed/deimos/.*\.sops\.yaml$
    age: >-
      <deimos-host-recipient>,
      <operator-recovery-recipient>
```

Design decisions:

- Shell wrapper (not Python) because `sops` is inherently an interactive CLI tool and the
  wrapper is orchestration-only with no business logic.
- `validate` is a separate subcommand suitable for pre-commit integration.
- Recipient configuration lives in `.sops.yaml` (standard `sops` convention) rather than
  duplicating recipient lists in the wrapper.
- Key rotation uses `sops updatekeys` which re-encrypts data keys for the current recipient
  set without requiring access to the plaintext data.

## Decision Notes

- Decision: Make targets default to `--dry-run` for apply.
  Rationale: Aligns with guardrails requiring explicit user request for live apply.
  Impact: Operators must call `abhaile-apply` directly for live mutations.

- Decision: `abhaile-diff` exit codes follow `diff(1)` convention (0=same, 1=different, 2=error).
  Rationale: Standard unix convention enables shell conditionals and CI gating without parsing output.
  Impact: Current behavior (always exit 0) changes; downstream scripts relying on exit 0 need update.

- Decision: Host inventory is a Python entrypoint, not a shell script.
  Rationale: Reuses existing config loading and validation modules; avoids YAML parsing in shell.
  Impact: Requires `pyproject.toml` entrypoint registration.

- Decision: Sealed artifact tooling is a shell wrapper around `sops`.
  Rationale: `sops` is an interactive CLI tool; Python adds no value for path/recipient orchestration.
  Impact: Requires `sops` and `age` installed on operator workstation.

- Decision: `make validate` is equivalent to a full render (no separate validate-only mode).
  Rationale: Validation is tightly coupled to rendering. Splitting them duplicates setup for negligible speed gain on a 2-node homelab.
  Impact: None — validation already runs as part of render.

- Decision: `abhaile-inventory --validate` checks service definition existence only, not network.yaml cross-references.
  Rationale: Network-level validation belongs to the render pipeline. Inventory answers one question: are mapping.yaml references broken?
  Impact: Simple, fast, single-concern validation.

- Decision: Metadata-only manifest changes (kind/owner_ref differ but sha256 matches) produce exit 0 from `abhaile-diff`.
  Rationale: Metadata differences don't indicate host filesystem drift. Exit 1 means "host needs reconciliation."
  Impact: Metadata changes are reported in output but do not trigger non-zero exit.

- Decision: `.sops.yaml` creation rules are the exclusive recipient source. No `--recipient` override.
  Rationale: One source of truth prevents operator mistakes. Ad-hoc recipients bypass the per-host model.
  Impact: Testing with different recipients requires editing `.sops.yaml` temporarily.

- Decision: `bootstrap-validate` runs in CI only, not pre-commit.
  Rationale: `sops` is not a standard dev dependency. Pre-commit should work with Python + standard tools only.
  Impact: Developers without `sops` are not blocked; CI catches issues.

## Acceptance Criteria

### Acceptance: Make Targets

- [x] `make render` renders all hosts and exits non-zero on validation or render failure.
- [x] `make render-host HOST=phobos` renders a single host.
- [x] `make apply HOST=phobos` runs render then dry-run apply for the specified host.
- [x] `make validate` runs a full render pass (exercising all validation) and exits non-zero on failure.
- [x] `make diff` runs `abhaile-diff` with default output root paths.
- [x] All targets print clear error messages when required variables are missing.

### Host Inventory

- [x] `abhaile-inventory` prints all hosts and their mapped services in deterministic order.
- [x] `--json` outputs machine-readable JSON with host keys and service list values.
- [x] `--validate` exits non-zero and reports missing service definitions.
- [x] Entrypoint registered in `pyproject.toml`.
- [x] Unit tests cover normal output, JSON mode, and validation failure.

### Diff Tool

- [x] `abhaile-diff` exits 0 when manifests are identical.
- [x] `abhaile-diff` exits 1 when differences (added/changed/removed) are present.
- [x] `abhaile-diff` exits 2 on invalid input (missing file, malformed manifest).
- [x] Metadata-only changes are reported distinctly from content changes.
- [x] Existing JSON output and human-readable summary remain functional.
- [x] `make diff` target calls `abhaile-diff` correctly.
- [x] Unit tests cover all three exit code paths and metadata-only detection.

### Sealed Bootstrap Artifact Tooling

- [x] `scripts/sops-bootstrap create <host> <name>` creates an encrypted artifact at the
  canonical path with correct recipients.
- [x] `scripts/sops-bootstrap edit <host> <name>` opens the artifact for editing without
  writing plaintext to disk.
- [x] `scripts/sops-bootstrap rotate <host> <name>` re-encrypts with current recipients from
  `.sops.yaml`.
- [x] `scripts/sops-bootstrap validate` checks all sealed artifacts are encrypted and
  correctly named.
- [x] `validate` subcommand is suitable for CI integration (not pre-commit; sops is not a
  standard dev dependency).
- [x] `.sops.yaml` creation rules define per-host recipient sets.
- [x] `create` refuses to overwrite existing files without `--force`.
- [x] Make targets `bootstrap-create`, `bootstrap-edit`, `bootstrap-rotate`, and
  `bootstrap-validate` call the wrapper with correct arguments.
- [x] No plaintext secret material is written to repo-managed paths at any point.

### Evidence

- Implementation evidence: `Makefile` (targets), `src/abhaile/cli/inventory.py`, `src/abhaile/cli/diff.py` (exit codes), `scripts/sops-bootstrap`, `.sops.yaml`
- Validation evidence: `tests/unit/python/cli/test_inventory.py`, `tests/unit/python/cli/test_diff_exit_codes.py`, `bash -n` syntax checks, `make test` 510 passed

## Out of Scope

- GitOps runner integration (separate phase with its own spec).
- Full config validation mode without rendering (render already validates as a side effect).
- Automated key generation or identity provisioning for age recipients.
- Bootstrap script (`scripts/bootstrap.sh`) — that belongs to the Bootstrap phase.
- `abhaile-diff` comparing live filesystem state (live hash checking is apply's domain).

## Open Questions

All original open questions have been resolved. See Decision Notes.

## References

- `docs/adr/0007-sops-bootstrap-policy-and-layout.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/specs/accepted/0009-apply-pipeline.md` (SPEC-2026-009 — `abhaile-diff` and `abhaile-apply` contracts)
- `src/abhaile/cli/diff.py` — existing diff entrypoint
- `src/abhaile/cli/render.py` — existing render entrypoint
- `src/abhaile/plan/diff.py` — drift planning implementation
- `Makefile` — current development targets
