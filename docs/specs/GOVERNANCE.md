# Specs Governance

This document defines how specs are used for roadmap, delivery tracking, and implementation decision capture.

## Scope

- `TODO.md` is temporary working state only.
- Durable decisions do not live in `TODO.md`.
- Specs are the canonical workflow for planned work.

## Lifecycle

Specs move through these directories:

1. `proposed/`
1. `active/`
1. `accepted/`

### Status Handling And Transitions

Spec lifecycle is represented by directory location.

- `proposed` specs live in `proposed/`.
- `active` specs live in `active/`.
- `accepted` specs live in `accepted/`.

Statuses `rejected` and `superseded` are valid metadata values for historical outcomes.

- A `rejected` spec is moved to `docs/specs/archive/rejected/` when status changes to `rejected`.
- A `superseded` spec should include `superseded_by` and link to the replacement spec.
- A `superseded` spec remains in `accepted/` to preserve historical delivery context.
- Reactivating a `rejected` or `superseded` spec requires setting `status: active`, clearing or updating
  supersession metadata as appropriate, and moving the file to `active/`.

Directory location is authoritative for lifecycle state. Metadata `status` must match the
directory, except:

- `status: rejected` lives in `docs/specs/archive/rejected/`
- `status: superseded` lives in `docs/specs/accepted/`

If status and directory disagree, do not implement against the spec until the mismatch is
resolved. The resolution should update the file location, metadata, or both in one change.

## Required Metadata

Each spec should include a metadata header near the top.

```yaml
id: SPEC-YYYY-NNN
title: Short descriptive title
status: proposed
owner: <name>
created: YYYY-MM-DD
updated: YYYY-MM-DD
related_adrs: []
supersedes: null
superseded_by: null
scope:
  hosts: []
  services: []
```

Allowed status values:

- `proposed`
- `active`
- `accepted`
- `rejected`
- `superseded`

## Decision Notes

Implementation-level decisions should be recorded in the spec as concise decision notes.

Recommended note shape:

```md
- Decision: <what>
- Rationale: <why>
- Impact: <trade-offs and effects>
- ADR: <optional link if escalated>
```

Promote to ADR when a decision is cross-cutting, long-lived, or expensive to reverse.

Promote to ADR when any of these objective triggers apply:

- security boundary or trust model changes
- host or network contract changes
- cross-service interface or API contract changes
- state, drift-detection, or reconciliation model changes
- decisions expected to persist beyond one feature cycle or expensive to reverse

## Completion Tracking

Use acceptance criteria checkboxes in the active spec as the primary task tracker.

Specs are the authoritative completion tracker. Any separate tracker is reporting-only.

Each completed acceptance criterion should include links to evidence:

- implementation commit or PR
- tests or validation evidence

Minimum evidence rule per acceptance criterion:

- one implementation reference (commit or PR)
- one validation reference (test, dry-run output, or equivalent verification)

If a validation reference is not applicable, record `N/A` with a short rationale and reviewer approval
in the spec note for that criterion.

When all criteria are complete:

1. move spec to `accepted/`
1. update related ADR links

## Relationship With ADRs

- ADRs are for durable architecture decisions.
- Specs are for delivery and implementation decisions.
- Link specs and ADRs both ways when a decision is promoted.

When an ADR is created, superseded, or status-changed during spec delivery:

- the PR author updates `docs/adr/README.md` in the same PR
- the reviewer verifies ADR file and index consistency before approval

## PR Checklist Gate

Every PR that changes ADR status/content or creates a new ADR should include this checklist item:

- [ ] If ADRs changed, `docs/adr/README.md` is updated in the same PR

Until automated checks are added, reviewers should treat an unchecked or missing item as a blocking issue.
