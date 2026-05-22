# Spec: GitOps Runner

## Metadata

```yaml
id: SPEC-2026-012
title: GitOps Runner
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0003-gitops-runner-responsibility-boundary
  - 0001-output-root-and-environment-paths
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: ["*"]
```

## Context

The render and apply pipelines are complete. `abhaile-render` produces
deterministic host-scoped artifacts from `config/`, and `abhaile-apply`
reconciles those artifacts against the live host filesystem with drift
detection. Both are single-invocation tools with no awareness of git history,
scheduling, or recovery.

The GitOps runner is the outer orchestration layer that owns the full
reconciliation loop: fetch repository state, select a commit, invoke
render+apply for the local host, track success, and recover from failures by
rolling back to the last-known-good commit. ADR 0003 establishes that this
commit-aware orchestration belongs outside `src/abhaile/`.

The runner lives in `scripts/` as an executable wrapper. It is the sole consumer
of git operations in the reconciliation path. Render and apply remain
workspace-state tools with no git awareness.

## Requirements

- [ ] Runner wrapper that fetches git state, selects target commit, and invokes
  `abhaile-render` + `abhaile-apply` for the local host.
- [ ] Last-successful commit tracking that persists applied commit SHA per host
  after full render+apply success.
- [ ] Automatic rollback retry that checks out the last-known-good commit and
  re-runs render+apply when a newer commit fails.
- [ ] Systemd service and timer that schedule the runner periodically with
  overlap protection.
- [ ] Runner state and locking that prevents concurrent runs and documents
  state layout.

## Constraints

- Orchestration only: render/apply business logic remains in `src/abhaile/`.
- No secrets stored in the repository or runner state files.
- No git checkout/revision logic inside `src/abhaile/`.
- Runner must be safe to invoke manually outside the systemd timer.
- Runner must not hide failures; non-zero exit on unrecoverable error.
- Apply defaults to dry-run per project guardrails; runner passes the required
  flag for live apply explicitly.
- Single-host scoped: each host runs its own runner instance against its own
  state.

## Design

### Runner Wrapper

The runner lives at `scripts/abhaile-runner` (executable, shell or Python
script). It is the top-level entry for scheduled and manual reconciliation.

Pipeline steps executed in order:

1. **Acquire lock** — exit immediately if another run is active.
1. **Fetch** — `git fetch origin` from the configured remote/branch.
1. **Detect** — compare fetched HEAD against last-applied commit; skip if equal.
1. **Checkout** — update working tree to fetched HEAD (fast-forward only).
1. **Render** — invoke `abhaile-render --host $(hostname)`.
1. **Apply** — invoke `sudo abhaile-apply` (live mode, not dry-run).
1. **Record** — on success, write the applied commit SHA to runner state.
1. **Release lock**.

Each step logs clearly to stdout/stderr (captured by journald when run via
systemd).

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Success (applied or already at target commit) |
| 1 | Unrecoverable failure (after rollback attempt if applicable) |
| 2 | Lock contention (another run active) |
| 3 | Configuration error (missing host in mapping, bad repo state) |

#### Host Detection

The runner determines the local host identity by matching `$(hostname -s)`
against host keys in `config/mapping.yaml`. If the hostname is absent from
mapping, the runner exits with code 3 and a clear error message.

#### Dirty Worktree Handling

If the working tree has uncommitted changes at runner start, the runner refuses
to proceed (exit 3). The runner does not stash or clean; operator intervention
is required.

#### Fast-Forward Failure

If `origin/<branch>` cannot be fast-forwarded to (diverged history), the runner
exits with code 1. No force-pull or reset.

### Last-Successful Commit Tracking

After render+apply succeed for the local host, the runner writes a state file
recording the applied commit.

State file: `/var/lib/abhaile/runner/last-successful-commit`

Format (plain text, one record):

```text
<40-char SHA> <ISO 8601 timestamp> <branch>
```

Example:

```text
a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2 2026-06-05T12:30:00+01:00 main
```

Write semantics:

- Written atomically (write to temp file, fsync, rename).
- Written only after `abhaile-apply` exits 0.
- If render succeeds but apply reports no changes needed (already converged),
  the commit is still recorded as successful — the workspace state is valid.

The runner reads this file at startup to determine the rollback target.

### Automatic Rollback Retry

When render or apply fails at a newer commit, the runner attempts recovery:

1. Read last-known-good SHA from `/var/lib/abhaile/runner/last-successful-commit`.
1. If no last-known-good exists (first run ever), skip rollback and fail immediately.
1. Checkout last-known-good commit (detached HEAD).
1. Re-run render+apply at that commit.
1. If rollback succeeds, exit 0 but log a warning that the host is running a
   prior commit, not latest.
1. If rollback also fails, exit 1.
1. After rollback (success or failure), return the working tree to the
   configured branch HEAD. The runner does not leave the repo on a detached
   HEAD.

Failures that trigger rollback:

- `abhaile-render` exits non-zero at the new commit.
- `abhaile-apply` exits non-zero at the new commit.

Failures that do NOT trigger rollback (immediate hard failure):

- Git fetch failure (network/auth issue, not a bad commit).
- Dirty worktree.
- Fast-forward failure.
- Lock acquisition failure.
- Host not found in mapping.

Rollback is attempted exactly once. No retry loops.

On successful rollback, the last-successful-commit file is NOT updated (it
already points to the commit that was just re-applied). This prevents the runner
from losing its rollback target.

### Systemd Service and Timer

#### Service Unit: `abhaile-runner.service`

```ini
[Unit]
Description=Abhaile GitOps Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/abhaile/scripts/abhaile-runner
User=abhaile
Group=abhaile
WorkingDirectory=/opt/abhaile
Environment=PATH=/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-/etc/abhaile/runner.env
StandardOutput=journal
StandardError=journal
```

#### Timer Unit: `abhaile-runner.timer`

```ini
[Unit]
Description=Abhaile GitOps Runner Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=30s
Persistent=true

[Install]
WantedBy=timers.target
```

Design choices:

- `Type=oneshot` prevents systemd from treating the runner as a long-running
  daemon; the timer fires independent invocations.
- `Persistent=true` catches up missed runs after reboot/sleep.
- `RandomizedDelaySec` prevents both hosts from hitting the remote
  simultaneously.
- No `ExecStartPre` lock — locking is owned by the runner itself (see below)
  so manual invocations are equally protected.
- The service user is `abhaile` (unprivileged for git/render); apply is
  invoked via `sudo abhaile-apply` since apply requires root to place files
  and reload systemd. A sudoers rule grants `abhaile` passwordless access to
  `abhaile-apply` only.
- `EnvironmentFile` allows operator overrides (branch, remote, log level)
  without editing the unit.

The runner is safe to invoke directly (`scripts/abhaile-runner`) without the
timer for operator-initiated reconciliation or debugging.

### Runner State and Locking

#### State Layout

All runner-owned state lives under `/var/lib/abhaile/runner/`:

```text
/var/lib/abhaile/runner/
├── last-successful-commit    # last applied commit record
├── lock                      # flock-based lock file
└── last-run-status           # exit code and timestamp of last run
```

This is separate from apply-owned state at `/var/lib/abhaile/state/`.

`last-run-status` format (plain text):

```text
<exit-code> <ISO 8601 timestamp> <commit-attempted>
```

#### Locking Strategy

The runner uses `flock(2)` (exclusive, non-blocking) on
`/var/lib/abhaile/runner/lock`.

- On lock acquisition failure, the runner exits immediately with code 2.
- The lock file is a regular empty file; `flock` releases automatically on
  process exit or crash.
- No stale-lock recovery logic is needed: kernel-level `flock` is released on
  process termination regardless of cause (SIGKILL, OOM, reboot).
- Systemd's `ExecStart` will not overlap due to `Type=oneshot`, but the lock
  still protects against concurrent manual invocations.

#### Ownership and Permissions

- `/var/lib/abhaile/runner/` — owned by `abhaile:abhaile`, mode `0750`.
- State files within — owned by `abhaile:abhaile`, mode `0640`.
- Lock file — owned by `abhaile:abhaile`, mode `0600`.

## Decision Notes

- Decision: Commit-aware orchestration (fetch, checkout, rollback, scheduling) lives outside `src/abhaile/` in a runner wrapper under `scripts/`.

- Rationale: Keeps render/apply focused on workspace-state reconciliation; runner concerns can evolve independently.

- Impact: `src/abhaile/` never imports git libraries or performs revision operations.

- ADR: 0003-gitops-runner-responsibility-boundary

- Decision: Runner state is separate from apply state under a distinct `/var/lib/abhaile/runner/` directory.

- Rationale: Runner owns commit tracking and locking; apply owns manifests and drift history. Different lifecycles, different ownership boundaries.

- Impact: Clear separation of concerns; runner state can be wiped without affecting apply state and vice versa.

- ADR: 0001-output-root-and-environment-paths

- Decision: Locking uses kernel-level `flock(2)` rather than PID files or systemd-only serialization.

- Rationale: `flock` is automatically released on process death (no stale lock risk); works for both timer-triggered and manual runs.

- Impact: No stale-lock recovery code needed; simple and correct.

- ADR: null

- Decision: Rollback is attempted exactly once with no retry loop.

- Rationale: Infinite retry risks masking persistent issues; single attempt provides recovery without runaway behavior.

- Impact: If both new commit and last-known-good fail, the runner fails loudly and requires operator intervention.

- ADR: null

- Decision: The runner passes live-apply flags explicitly; it does not override apply's dry-run default through implicit means.

- Rationale: Maintains the project guardrail that apply defaults to dry-run; the runner is an explicit, auditable caller.

- Impact: Runner invocation is transparent in logs.

- ADR: null

## Acceptance Criteria

- [ ] Runner wrapper exists at `scripts/abhaile-runner`, is executable, and
  performs fetch → detect → checkout → render → apply in sequence for the
  local host.
- [ ] Runner exits non-zero on unrecoverable failure and logs each pipeline step.
- [ ] Runner skips render+apply when already at the target commit.
- [ ] Runner detects local host identity from hostname and validates against
  `config/mapping.yaml`.
- [ ] Runner refuses to proceed on dirty worktree or fast-forward failure.
- [ ] Last-successful commit file is written atomically only after render+apply
  success.
- [ ] Commit record includes SHA, timestamp, and branch.
- [ ] On render or apply failure at a new commit, the runner checks out the
  last-known-good commit and re-runs render+apply.
- [ ] Rollback is attempted once only; double failure exits non-zero.
- [ ] After rollback (success or failure), working tree returns to branch HEAD.
- [ ] Successful rollback does not update the last-successful-commit file.
- [ ] Systemd service unit is `Type=oneshot` and runs as user `abhaile`.
- [ ] Systemd timer fires every 5 minutes with boot catch-up and jitter.
- [ ] Runner uses `flock(2)` for serialization; concurrent invocations exit
  immediately with code 2.
- [ ] Runner state layout is documented and lives under
  `/var/lib/abhaile/runner/` separate from apply state.
- [ ] Runner state directory and files have correct ownership (`abhaile:abhaile`)
  and permissions.

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- Multi-host orchestration or cross-host coordination.
- Remote apply (runner always operates on the local host).
- Branch selection logic beyond a single configured branch.
- Notification/alerting on failure (may be added by a future spec).
- Render or apply business logic changes.
- Secrets management or Vault interaction (runner does not handle secrets).
- Bootstrap/enrollment (covered by the Bootstrap phase).

## Open Questions

1. **Runner implementation language:** Shell script (simpler, fewer
   dependencies, aligns with `scripts/` convention) vs Python (testable,
   consistent with `src/abhaile/`, structured error handling)? The decision log
   places the runner in `scripts/` which suggests shell, but testability may
   favor Python with a `scripts/abhaile-runner` thin wrapper.

1. **Branch configuration:** Where does the runner read its target branch and
   remote? Candidates: hardcoded `main`, environment variable via
   `runner.env`, or a field in `paths.ini`.

1. **Partial apply success:** If `abhaile-apply` partially applies (some
   owners succeed, others fail) and exits non-zero, should the runner treat
   this as full failure (trigger rollback) or record partial success? Current
   design treats any non-zero apply exit as failure.

1. **Timer cadence:** 5 minutes is a starting point. Should this be
   configurable per-host via `runner.env` or fixed in the timer unit?

1. **Repository location on host:** The spec assumes `/opt/abhaile` as the
   working directory. Should this be configurable, or is it fixed by the
   bootstrap enrollment process?

1. **Apply escalation mechanism:** The runner runs as `abhaile` but apply
   requires root. The design specifies `sudo abhaile-apply` with a sudoers
   rule. Confirm whether additional sudo entries are needed for systemd
   operations that apply delegates (daemon-reload, restart), or whether apply
   handles all privileged subprocess calls internally once launched as root.

1. **Render output path:** Should the runner pass `--output` to render
   explicitly, or rely on the default `/var/lib/abhaile` from `paths.ini`?

## References

- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `docs/adr/0001-output-root-and-environment-paths.md`
- `src/abhaile/cli/render.py`
- `src/abhaile/cli/apply.py`
- `src/abhaile/cli/diff.py`
- `paths.ini`
- `TODO.md` — Phase: GitOps Runner
