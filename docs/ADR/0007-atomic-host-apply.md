# ADR 0007: Atomic Deployments via `apply.sh`

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/OPERATIONS.md`, `docs/QUICKSTART.md`

## Context

Manual file replacement risks partial updates and drift. Deployments should be repeatable, reviewable, and safe.

## Decision

Use `tools/apply/apply.sh` for atomic host deployments with two phases:

- **Render phase (unprivileged):** Validate configs and detect drift without modifying system
- **Apply phase (privileged):** Apply changes atomically with backups, validation, and rollback capability

The `--skip-render --apply` pattern prevents re-rendering as root, minimizing blast radius.

## Consequences

- ✅ Idempotent, reviewable deploys with fast rollback
- ✅ Clear privilege separation (render vs. apply)
- ✅ Unprivileged failures prevent privileged apply
- ⚠️ Two systemd units required (timer + path)
- ⚠️ Additional script complexity

See [tools/apply/README.md](../../tools/apply/README.md) for detailed validation, error handling, and recovery procedures.

## Alternatives Considered

- **Direct copy/rsync:** Rejected due to partial update risk
- **Single privileged service:** Rejected; large blast radius for dependency vulnerabilities
- **Ansible apply:** Viable but would need equivalent atomic apply semantics
