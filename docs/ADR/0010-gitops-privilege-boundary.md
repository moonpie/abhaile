# ADR 0010: GitOps Privilege Boundary Pattern

- **Status:** Accepted
- **Date:** 2025-12-26
- **Related Docs:** `docs/OPERATIONS.md`, [tools/bootstrap/README.md](../../tools/bootstrap/README.md), [tools/gitops/README.md](../../tools/gitops/README.md)

## Context

GitOps automation requires Git access, SOPS decryption, rendering, and filesystem operations. Running all as `root` creates a large blast radius; a single dependency vulnerability could compromise the entire host.

## Decision

Implement a **two-phase privilege boundary pattern**:

**Phase 1: Render (unprivileged, `abhaile` user)**

- Systemd timer triggers every 5 minutes
- Pulls repo, decrypts secrets, renders configs
- Detects drift (read-only)
- Writes `.apply_ready` flag on success

**Phase 2: Apply (privileged, `root`)**

- Systemd path unit watches for `.apply_ready`
- Applies rendered configs atomically
- Cleans up flag on success

## Consequences

- ✅ Minimal root exposure (no rendering as root)
- ✅ Failures are isolated (bad render blocks apply)
- ✅ Clear separation of concerns
- ⚠️ Two systemd units required
- ⚠️ `.apply_ready` flag coordination needed

See [tools/gitops/README.md](../../tools/gitops/README.md) for systemd architecture, file locations, and operational procedures.

## Alternatives Considered

- **Single privileged service:** Large blast radius; rejected
- **Manual apply:** Not automated; defeats GitOps purpose; rejected
- **Separate keys per phase:** No security benefit; key complexity; rejected
