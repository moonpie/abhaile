# ADR 0001: Host-Level GitOps as the Source of Truth

- **Status:** Accepted
- **Date:** 2025-12-19
- **Related Docs:** `docs/ARCHITECTURE.md`, `docs/QUICKSTART.md`, `docs/OPERATIONS.md`

## Context

The lab needs a repeatable, auditable way to manage host configs, service deployment, and network state across two Debian hosts. Manual edits cause drift, regressions, and unclear rollback paths.

## Decision

Adopt a host-level GitOps model with a privilege boundary:

- The Git repository is the source of truth.
- `tools/render/cli.py` renders all configs from `config/` (unprivileged phase).
- `tools/apply/apply.sh` applies changes atomically with drift checks and backups (privileged phase).
- Systemd timers and path units automate render (unprivileged) and apply (privileged) with clear handoff via `.apply_ready` flag.

## Consequences

- ✅ Changes are reviewable, consistent, and reproducible.
- ✅ Drift is detected before apply, reducing surprise regressions.
- ✅ Minimal root exposure; unprivileged failures prevent privileged apply.
- ⚠️ Manual hotfixes are overwritten unless they are captured in Git.
- ⚠️ Requires two systemd units (render + apply) instead of one.

## Implementation: Two-Phase GitOps Runner Model

**Phase 1: Render (unprivileged, `abhaile` user)**

- Systemd timer: `abhaile-gitops@.timer` (every 15 minutes)
- Executes: `gitops_runner.sh` via `abhaile-gitops@.service` with `User=abhaile`
- Tasks: repo sync → SOPS decryption → render via `tools/render/cli.py` → drift detection
- Secrets sourced from Age key at `/home/abhaile/.config/sops/age/keys.txt`
- On success, creates `.apply_ready` flag

**Phase 2: Apply (privileged, `root`)**

- Systemd path unit: `abhaile-gitops-apply@.path` (watches for `.apply_ready` flag)
- Executes: `apply.sh --skip-render --apply` via `abhaile-gitops-apply@.service` with `User=root`
- Tasks: atomic apply → systemd reload → state update
- Removes `.apply_ready` flag on completion

**Handoff mechanism:** `.apply_ready` flag prevents privileged apply from running until unprivileged render succeeds. See [ADR 0010](0029-gitops-privilege-boundary.md) for detailed security analysis.

## Alternatives Considered

- **Manual host management**: rejected due to drift risk.
- **Single privileged service**: rejected; large blast radius for dependency vulnerabilities.
- **Agent-based config management** (e.g., Ansible): viable but would need equivalent drift checks and atomic apply semantics.

## Notes

Any future replacement must meet or exceed the current safety guarantees (dry-run, drift detection, atomic apply, and privilege separation).
