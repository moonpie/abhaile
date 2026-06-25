# Spec: GitOps Runner

## Metadata

```yaml
id: SPEC-2026-012
title: GitOps Runner
status: accepted
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

- [x] Runner wrapper that fetches git state, selects target commit, and invokes
  `abhaile-render` + `abhaile-apply` for the local host.
- [x] Last-successful commit tracking that persists applied commit SHA per host
  after full render+apply success.
- [x] Automatic rollback retry that checks out the last-known-good commit and
  re-runs render+apply when a newer commit fails.
- [x] Systemd service and timer that schedule the runner periodically with
  overlap protection.
- [x] Runner state and locking that prevents concurrent runs and documents
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
1. **Render** — invoke `.venv/bin/abhaile-render --host $(hostname -s) --output $ABHAILE_OUTPUT`.
1. **Apply** — invoke `sudo .venv/bin/abhaile-apply --output $ABHAILE_OUTPUT` (live mode, not dry-run).
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
to proceed (exit 3). The runner logs `git status --short`, staged
`git diff --cached --name-status`, unstaged `git diff --name-status`, and recent
reflog entries before exiting. The runner does not stash or clean; operator
intervention is required.

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
1. Verify the SHA is reachable locally (`git cat-file -t <sha>`). If not, skip
   rollback and exit with "rollback target unreachable; operator intervention
   required".
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
Environment=PATH=/opt/abhaile/.venv/bin:/usr/local/bin:/usr/bin:/bin
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
  invoked via `sudo /opt/abhaile/.venv/bin/abhaile-apply` since apply requires
  root to place files and reload systemd. A sudoers rule grants `abhaile`
  passwordless access to `abhaile-apply` only.
- `EnvironmentFile` allows operator overrides (branch, remote, log level)
  without editing the unit.

The runner is safe to invoke directly (`scripts/abhaile-runner`) without the
timer for operator-initiated reconciliation or debugging.

### Runner State and Locking

#### State Layout

All runner-owned state lives under `/var/lib/abhaile/runner/`:

```text
/var/lib/abhaile/runner/
├── current-run               # current phase while a run is active
├── last-successful-commit    # last applied commit record
├── last-run-summary          # diagnostic summary of the last completed run
├── lock                      # flock-based lock file
└── last-run-status           # exit code and timestamp of last run
```

This is separate from apply-owned state at `/var/lib/abhaile/state/`.

`last-run-status` format (plain text):

```text
<exit-code> <ISO 8601 timestamp> <commit-attempted>
```

`last-run-summary` format (plain text key/value pairs):

```text
host=<hostname>
branch=<branch>
remote=<remote>
started_at=<ISO 8601 timestamp>
finished_at=<ISO 8601 timestamp>
duration_seconds=<seconds>
phase=<final phase>
outcome=<success|failure|dirty-worktree|rollback-success|already-current|...>
exit_code=<exit code>
current_sha=<current HEAD>
target_sha=<commit-attempted>
last_good_sha=<last successful commit or none>
rollback_attempted=<true|false>
```

`current-run` uses the same key/value style for the active phase. It is updated
before fetch, checkout, render, apply, and rollback, and removed after a completed
success or failure. Monitoring can treat a stale `current-run` timestamp as a
possible hung runner.

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

- `/opt/abhaile/` — owned by `abhaile:abhaile`, mode `0750` or stricter compatible
  with git and venv updates.
- `/opt/abhaile/.venv/` — owned by `abhaile:abhaile`.
- `/var/lib/abhaile/rendered/` — owned by `abhaile:abhaile`, mode `0750`.
- `/var/lib/abhaile/runner/` — owned by `abhaile:abhaile`, mode `0750`.
- `/var/lib/abhaile/state/` — owned by `root:root`, mode `0750`.
- Runner state files within `/var/lib/abhaile/runner/` — owned by `abhaile:abhaile`,
  mode `0640`.
- Runner lock file — owned by `abhaile:abhaile`, mode `0600`.

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

- Decision: Runner is implemented in bash (not Python).

- Rationale: The runner is pure orchestration — git, flock, exec. Every operation is a subprocess call. ~100-150 lines. Shell is the natural tool for a thin wrapper that calls other tools.

- Impact: No Python dependency in the runner path; testability via integration rather than unit tests.

- ADR: null

- Decision: Branch and remote are configured via environment variables (`ABHAILE_BRANCH`, `ABHAILE_REMOTE`) defaulting to `main` and `origin`, loaded from `/etc/abhaile/runner.env` by systemd EnvironmentFile.

- Rationale: Separates runtime config from script logic; operators override per-host without editing units or scripts; `paths.ini` stays path-focused.

- Impact: No hardcoded branch; override requires only editing one env file.

- ADR: null

- Decision: Runner fetches use the host read-only deploy key at
  `/home/abhaile/.ssh/gitops_ed25519` by default, overridable with `ABHAILE_GIT_SSH_KEY`
  or an explicit `GIT_SSH_COMMAND`.

- Rationale: The deploy key is intentionally non-default, so steady-state fetches must select it
  explicitly just like bootstrap clone/pull operations.

- Impact: Runner does not depend on agent forwarding, default SSH key names, or interactive
  credentials.

- ADR: null

- Decision: Timer cadence is fixed at 5 minutes in the systemd timer unit; override via `systemctl edit abhaile-runner.timer`.

- Rationale: Timer cadence is a systemd concern. Environment variables can't influence timer intervals without convoluted ExecStartPre hacks.

- Impact: Simple; standard systemd override mechanism for per-host tuning.

- ADR: null

- Decision: Repository location is fixed at `/opt/abhaile`; set once during bootstrap via systemd WorkingDirectory.

- Rationale: Single known location simplifies the runner, sudoers, and operator expectations.
  Bootstrap owns initial placement and sets ownership so the unprivileged runner can fetch,
  checkout, and render.

- Impact: Runner script resolves venv entrypoints from `$PWD/.venv/bin` by default; systemd
  sets `$PWD` with `WorkingDirectory=/opt/abhaile`.

- ADR: null

- Decision: Single sudoers entry grants `abhaile` passwordless access to `abhaile-apply` only. Apply handles all internal privilege escalation (daemon-reload, restart, file placement) once running as root.

- Rationale: Minimal privilege surface; apply already owns all OS mutations internally.

- Impact: One sudoers line: `abhaile ALL=(root) NOPASSWD: /opt/abhaile/.venv/bin/abhaile-apply *`

- ADR: null

- Decision: Runner passes `--output /var/lib/abhaile` explicitly to both render and apply.

- Rationale: Explicit invocation is clearer in logs and `ps` output; aids troubleshooting. Value comes from `ABHAILE_OUTPUT` env var (default `/var/lib/abhaile`), overridable in `runner.env`.

- Impact: No reliance on `paths.ini` default at runtime; operator can see exact paths in journald.

- ADR: null

- Decision: Before rollback checkout, the runner verifies the target SHA exists locally (`git cat-file -t <sha>`). If unreachable, skip rollback and exit with a clear diagnostic.

- Rationale: Protects against edge case where branch changes or force-push removes the last-known-good commit from local history. Gives operator an actionable error rather than a cryptic git failure.

- Impact: One extra check; monitoring should alert on this failure mode (covered by SPEC-2026-016).

- ADR: null

## Acceptance Criteria

- [x] Runner wrapper exists at `scripts/abhaile-runner`, is executable, and
  performs fetch → detect → checkout → render → apply in sequence for the
  local host.
- [x] Runner exits non-zero on unrecoverable failure and logs each pipeline step.
- [x] Runner skips render+apply when already at the target commit.
- [x] Runner detects local host identity from hostname and validates against
  `config/mapping.yaml`.
- [x] Runner refuses to proceed on dirty worktree or fast-forward failure.
- [x] Last-successful commit file is written atomically only after render+apply
  success.
- [x] Commit record includes SHA, timestamp, and branch.
- [x] On render or apply failure at a new commit, the runner checks out the
  last-known-good commit and re-runs render+apply.
- [x] Rollback is attempted once only; double failure exits non-zero.
- [x] After rollback (success or failure), working tree returns to branch HEAD.
- [x] Successful rollback does not update the last-successful-commit file.
- [x] Systemd service unit is `Type=oneshot` and runs as user `abhaile`.
- [x] Systemd timer fires every 5 minutes with boot catch-up and jitter.
- [x] Runner uses `flock(2)` for serialization; concurrent invocations exit
  immediately with code 2.
- [x] Runner state layout is documented and lives under
  `/var/lib/abhaile/runner/` separate from apply state.
- [x] Runner state directory and files have correct ownership (`abhaile:abhaile`)
  and permissions.

### Evidence

- Implementation evidence: `scripts/abhaile-runner`, `config/hosts/common/systemd/`
- Validation evidence: `tests/integration/test_runner.py` (6 tests, all passing), `bash -n` syntax check, `make test` 500 passed

## Out of Scope

- Multi-host orchestration or cross-host coordination.
- Remote apply (runner always operates on the local host).
- Branch selection logic beyond a single configured branch.
- Render or apply business logic changes.
- Secrets management or Vault interaction (runner does not handle secrets).
- Bootstrap/enrollment (covered by the Bootstrap phase).
- Notification/alerting on runner failure — covered by SPEC-2026-016
  (monitoring). The runner writes `last-run-status` with exit code and
  commit; monitoring should alert on non-zero exit codes and on rollback
  events (host running prior commit rather than latest).

## Open Questions

All original open questions have been resolved. See Decision Notes.

## References

- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `docs/adr/0001-output-root-and-environment-paths.md`
- `src/abhaile/cli/render.py`
- `src/abhaile/cli/apply.py`
- `src/abhaile/cli/diff.py`
- `paths.ini`
- `docs/specs/proposed/0016-services-monitoring.md` (SPEC-2026-016 — runner failure alerting)
