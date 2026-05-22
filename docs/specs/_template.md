# Spec: [Title]

## Metadata

```yaml
id: SPEC-YYYY-NNN
title: [title]
status: proposed
owner: [name]
created: YYYY-MM-DD
updated: YYYY-MM-DD
related_adrs: []
supersedes: null
superseded_by: null
scope:
  hosts: []
  services: []
```

## Context

What problem are we solving? What triggered this work? Include enough background for someone unfamiliar with the specific area to understand the need.

## Requirements

What must be true when this work is complete? Be specific and testable.

- [ ] Requirement 1
- [ ] Requirement 2
- [ ] Requirement 3

## Constraints

What boundaries or limitations apply? (e.g., must not break existing behaviour, must work on Python 3.10, must not add new dependencies)

## Design

How will this be implemented? Include:

- Affected modules/files
- Data flow or control flow (if non-obvious)
- Key decisions and their rationale
- Interface contracts (function signatures, config schema changes)

Keep this proportionate to the complexity of the change. A simple feature needs a paragraph; a new subsystem needs diagrams and detailed breakdown.

## Decision Notes

Record implementation-level decisions made while delivering this spec.

- Decision: [what changed]
- Rationale: [why]
- Impact: [trade-offs and effects]
- ADR: [optional link if escalated]

## Acceptance Criteria

How do we know this is done? These should be verifiable.

- [ ] Criterion 1 (e.g., "unit tests pass for new renderer")
- [ ] Criterion 2 (e.g., "render output matches expected for phobos")
- [ ] Criterion 3 (e.g., "no regressions in existing integration tests")

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

If validation is not applicable, use `N/A` with a short rationale and reviewer approval.

## Out of Scope

What is explicitly not part of this work? Helps prevent scope creep.

## Open Questions

Unresolved decisions or unknowns that need input before or during implementation.

## References

- Links to relevant ADRs, docs, issues, or external resources
