# ADR Index

This index improves discoverability. Each ADR file remains the source of truth.

## Usage

Add one row per ADR. Keep links current when ADR status changes.

## ADRs

| ADR | Title | Status | Date | Supersedes | Superseded By | Linked Specs |
| --- | ----- | ------ | ---- | ---------- | ------------- | ------------ |
| [0001](0001-output-root-and-environment-paths.md) | Output Root and Environment Paths | Accepted | 2026-05-05 | - | - | 001, 002, 003, 004, 006, 007, 008, 009, 012 |
| [0002](0002-hash-based-drift-detection-and-state-model.md) | Hash-based Drift Detection and State Model | Accepted | 2026-05-05 | - | - | 001, 002, 003, 004, 005, 006, 007, 008, 009 |
| [0003](0003-gitops-runner-responsibility-boundary.md) | GitOps Runner Responsibility Boundary | Accepted | 2026-03-14 | - | - | 001, 008, 009, 012, 014 |
| [0004](0004-apply-execution-model.md) | Apply Execution Model | Accepted | 2026-04-22 | - | - | 008, 009, 011 |
| [0005](0005-service-authoring-model.md) | Service Authoring Model | Accepted | 2026-05-04 | - | - | 001, 002, 003, 004, 005, 006, 007, 009, 011, 015, 016, 017, 018, 019, 020 |
| [0006](0006-secrets-model-and-bootstrap-artifacts.md) | Secrets Model and Bootstrap Artifacts | Accepted | 2026-05-05 | - | - | 001, 005, 007, 010, 011, 014, 015, 018, 019, 020 |
| [0007](0007-sops-bootstrap-policy-and-layout.md) | SOPS Bootstrap Policy and Layout | Accepted | 2026-05-05 | - | - | 010, 013, 014 |

## Status Values

- `Proposed`
- `Accepted`
- `Deprecated`
- `Superseded`

## Notes

- Use ADRs for durable architecture-level decisions.
- Keep implementation-level decisions in the relevant spec.
- Link specs and ADRs both ways when decisions are promoted.
- Linked Specs column uses the numeric suffix from `SPEC-2026-NNN` IDs.
