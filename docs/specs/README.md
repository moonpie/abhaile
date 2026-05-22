# Specs

Specs are structured design documents that describe what to build and why. They serve as both planning artifacts and documentation of what was built.

## Lifecycle

| Status | Directory | Meaning |
|--------|-----------|---------|
| Proposed | `proposed/` | Drafted, awaiting review and agreement |
| Active | `active/` | Agreed and currently being implemented |
| Accepted | `accepted/` | Implementation complete and verified |
| Superseded | `accepted/` | Replaced by a newer spec, kept for history |
| Rejected | `archive/rejected/` | Decided against, with rationale recorded |

## Template

Use `_template.md` when creating new specs.

## Workflow

1. Draft a spec (or ask the Architect agent to draft one)
1. Review — check feasibility, completeness, operational implications
1. Move to `active/` when agreed and implementation begins
1. Move to `accepted/` when acceptance criteria are met
1. Update if behaviour changes later (specs are living documents)

## Naming

Use numeric prefix with lowercase kebab-case: `0009-apply-pipeline.md`, `0016-services-monitoring.md`, `0020-host-hardening.md`.

The four-digit prefix matches the numeric suffix of the spec ID (`SPEC-2026-009` → `0009-`).
