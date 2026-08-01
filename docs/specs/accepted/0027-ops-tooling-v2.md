# Spec: Ops Tooling v2

## Metadata

```yaml
id: SPEC-2026-027
title: Ops Tooling v2
status: accepted
owner: moonpie
created: 2026-07-31
updated: 2026-08-01
related_adrs:
  - 0007-sops-bootstrap-policy-and-layout
supersedes: SPEC-2026-013
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

`SPEC-2026-013` made `make validate` equivalent to a full render. That catches render
failures, but not apply-planner failures. This spec supersedes it with a validation contract
that renders first, then dry-runs apply without changing live systems.

## Requirements

- [x] `make render` and `make render-host HOST=x` remain render-only.
- [x] `make validate` renders all hosts, then dry-run applies each supported host.
- [x] `make validate-host HOST=x` renders and dry-run applies one host.
- [x] `ALLOW_HOST_MISMATCH=1` adds only `--allow-host-mismatch` to validation dry-runs.
- [x] Existing `apply`, `diff`, `docs`, inventory, and sealed bootstrap targets remain
  unchanged unless separately superseded.
- [x] Required variables fail with clear usage errors.

## Constraints

- Make targets must remain thin wrappers around canonical Python entrypoints.
- Validation must not perform live apply.
- `ALLOW_HOST_MISMATCH=1` must not imply any other apply option or safety bypass.
- Render output remains under `./out`.
- No new dependency is required.
- No behavior changes to `abhaile-render` or `abhaile-apply` are required unless current CLI
  coverage is insufficient.

## Design

The Makefile target contract is:

- `make render`: `abhaile.cli.render --all --output ./out`.
- `make render-host HOST=x`: `abhaile.cli.render --host x --output ./out`.
- `make validate`: render all hosts to `./out`, then dry-run apply `phobos` from
  `./out/phobos` and `deimos` from `./out/deimos`.
- `make validate-host HOST=x`: render one host to `./out`, then dry-run apply that host from
  `./out`.
- `make apply HOST=x`: existing host-scoped render plus dry-run apply workflow.

`ALLOW_HOST_MISMATCH=1` is only a workstation dry-run escape hatch. It appends
`--allow-host-mismatch` to validation dry-runs and prints a notice that the override is
dry-run-only.

All other ops tooling from `SPEC-2026-013` remains authoritative under this spec unless a
later spec supersedes it.

## Decision Notes

- Decision: Keep `make render` render-only.
  Rationale: Operators need a fast command that validates render inputs without exercising apply
  planning.
  Impact: Existing render workflows and expectations remain stable.

- Decision: Redefine `make validate` as render all hosts plus dry-run apply all hosts.
  Rationale: Validation should catch apply-planner failures, not only render failures.
  Impact: `make validate` becomes stronger and may take longer than render-only validation.

- Decision: Add `make validate-host HOST=x`.
  Rationale: Operators need the same validation contract for focused host work.
  Impact: Single-host changes can be checked without running all host dry-runs.

- Decision: Gate `--allow-host-mismatch` behind `ALLOW_HOST_MISMATCH=1`.
  Rationale: Workstation dry-runs may need to validate a target host from another machine, but
  the bypass should be explicit and narrow.
  Impact: The variable adds exactly one CLI flag and does not weaken other apply safeguards.

- Decision: Supersede `SPEC-2026-013` with an Ops Tooling v2 spec rather than editing it in
  place.
  Rationale: Keep the accepted spec as history while giving future readers one current ops
  tooling contract.
  Impact: `SPEC-2026-013` moves to `docs/specs/superseded/` with `superseded_by: SPEC-2026-027`.

## Acceptance Criteria

- [x] `make render` renders all hosts and does not call `abhaile.cli.apply`.
- [x] `make render-host HOST=phobos` renders only `phobos` and does not call
  `abhaile.cli.apply`.
- [x] `make render-host HOST=deimos` renders only `deimos` and does not call
  `abhaile.cli.apply`.
- [x] `make validate` renders all hosts and dry-runs apply for `phobos` and `deimos`.
- [x] `make validate-host HOST=phobos` renders only `phobos` and dry-runs apply for `phobos`.
- [x] `make validate-host HOST=deimos` renders only `deimos` and dry-runs apply for `deimos`.
- [x] `make validate-host` without `HOST` exits non-zero with a usage message.
- [x] `ALLOW_HOST_MISMATCH=1 make validate` passes `--allow-host-mismatch` to each dry-run
  apply command.
- [x] `ALLOW_HOST_MISMATCH=1 make validate-host HOST=phobos` passes `--allow-host-mismatch` to
  the dry-run apply command.
- [x] `ALLOW_HOST_MISMATCH` unset or set to any value other than `1` does not pass
  `--allow-host-mismatch`.
- [x] `make validate` and `make validate-host` cannot perform live apply.
- [x] `make apply HOST=x` behavior is unchanged.
- [x] Existing `make diff`, `make docs`, and `make bootstrap-*` behavior is unchanged.
- [x] `SPEC-2026-013` is marked `superseded` and moved to `docs/specs/superseded/`.
- [x] Spec governance documents `docs/specs/superseded/` as the location for superseded specs.

### Evidence

- Implementation evidence: commit `75201e2` updates `Makefile`, `README.md`,
  `docs/ARCHITECTURE.md`, and `docs/runbooks/operations.md` for the v2 target contract.
- Spec evidence: `SPEC-2026-013` moved to `docs/specs/superseded/` and governance/index docs
  updated for the superseded lifecycle directory.
- Validation evidence: `tests/integration/test_makefile_ops_tooling.py` covers render-only,
  validate all-host, validate-host, host-mismatch flag behavior, and unchanged legacy ops
  targets.
- Command evidence:
  - `.venv/bin/python -m pytest tests/integration/test_makefile_ops_tooling.py -q --no-cov`
  - `make validate ALLOW_HOST_MISMATCH=1`
  - `make validate-host HOST=phobos ALLOW_HOST_MISMATCH=1`

## Documentation Updates

- Update operator docs for the `render`, `validate`, `validate-host`, and
  `ALLOW_HOST_MISMATCH=1` contract.
- Update spec governance and the spec index for `docs/specs/superseded/`.

## Out of Scope

- Live apply behavior.
- Changes to render or apply CLI semantics beyond Make target wiring.
- Changing host inventory, diff, docs generation, or sealed bootstrap tooling behavior from
  `SPEC-2026-013`.
- Adding CI-specific validation targets.

## References

- [SPEC-2026-013 Ops Tooling](../superseded/0013-ops-tooling.md)
- [SPEC-2026-009 Apply Pipeline](0009-apply-pipeline.md)
