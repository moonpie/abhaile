# Spec: Bootstrap

## Metadata

```yaml
id: SPEC-2026-014
title: Bootstrap
status: accepted
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0006-secrets-model-and-bootstrap-artifacts
  - 0007-sops-bootstrap-policy-and-layout
  - 0003-gitops-runner-responsibility-boundary
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [vault, vault-agent]
```

## Context

A fresh Debian 13 host has no repo, no Vault access, and no runtime secrets. Bootstrap bridges
the gap between bare metal and a functioning GitOps-managed host where Vault Agent renders
runtime secrets. The old project implemented a working curl-bash bootstrap at
`tools/bootstrap/bootstrap.sh` with preflight checks, repo clone, venv setup, render, apply,
and GitOps unit installation. This spec redesigns bootstrap for the rewritten codebase
(`src/abhaile/`, Python CLI entrypoints, SOPS bootstrap policy per ADR 0007, and the runner
boundary per ADR 0003).

Bootstrap is the only phase that operates on a host before the GitOps runner exists. It must
establish exactly enough trust and state for the runner to take over, then get out of the way.

### Secrets Boundary

Bootstrap handles pre-Vault trust establishment only:

- **Bootstrap owns:** age decryption identity (operator-placed), sealed Vault Agent bootstrap
  artifacts (`secrets/<host>/vault-agent.sops.yaml`), Vault AppRole SecretID handoff, repo access
  credential (deploy key).
- **Bootstrap does NOT own:** runtime service secrets (API keys, DB passwords, TLS keypairs,
  SMTP credentials). These belong to Vault Agent at runtime per ADR 0006.
- **Handoff point:** bootstrap places Vault Agent AppRole files at
  `/home/abhaile/.config/vault-agent/role-id` and
  `/home/abhaile/.config/vault-agent/secret-id`. From that point, Vault Agent authenticates with
  native AppRole auto-auth and renders runtime secrets to host-only paths.

## Requirements

- [x] Implement `scripts/bootstrap.sh` as a curl-bash entry point for fresh host enrollment.
- [x] Implement sealed Vault Agent artifact decryption and consumption without plaintext persistence.
- [x] Define and document the complete host enrollment flow from bare metal to first successful apply.
- [x] Implement SecretID handoff handling that refuses to run without explicit input.

## Constraints

- Bootstrap runs as root on the target host.
- No secrets committed to git in plaintext. Sealed artifacts use `sops`/age per ADR 0007.
- Decrypted bootstrap material must not persist in durable paths after enrollment completes.
- Bootstrap must not duplicate render/apply business logic; it invokes `abhaile-render` and
  `abhaile-apply` as consumers.
- The runner boundary per ADR 0003 applies: bootstrap does not own scheduled execution,
  commit selection, or rollback. It performs one-shot enrollment only.
- Bootstrap must be idempotent for partial re-runs on hosts that failed mid-enrollment.
- External key material (age identity, deploy key) is operator-placed out-of-band before
  bootstrap runs.

## Design

### 1. Curl-Bash Bootstrap (`scripts/bootstrap.sh`)

Entry point: `curl -fsSL <raw-url>/scripts/bootstrap.sh | sudo bash -s -- <hostname>`

The script performs these stages in order, aborting on any failure:

#### Stage 1 — Preflight

1. Verify running as root.
1. Verify Debian 13 (trixie).
1. Verify hostname argument provided.
1. Test network connectivity (GitHub/repo host reachable).

#### Stage 2 — Prerequisites

1. Install base packages: `git`, `python3`, `python3-venv`, `podman`, `crun`, `age`, `jq`,
   `curl`, `unzip`, and `systemd-container`.
1. Install `sops` binary (from GitHub release, pinned version, verified checksum).
1. Install Vault CLI binary (from HashiCorp release, pinned minor version).
1. Enable `systemd-networkd` and `systemd-resolved`.

#### Stage 3 — User and Credential Validation

1. Create `abhaile` user and group if absent (uid 1001, gid 1001, group `abhaile`,
   shell `/bin/bash`, home `/home/abhaile`, not a system user — matches
   `config/hosts/common/host.yaml`). User must exist before credential path checks.
1. Require SecretID handoff material (see §4 below).
1. Verify age decryption identity exists at `/home/abhaile/.config/sops/age/keys.txt` (or
   root path for root-scoped artifacts). Abort with instructions if missing.
1. Verify repo access credential at `/home/abhaile/.ssh/gitops_ed25519`. Abort if missing.

#### Stage 4 — Repo and Environment

1. Clone repo to `/opt/abhaile` (or pull if directory exists for re-run idempotency).
1. Checkout target branch (default: `main`).
1. Create Python venv at `/opt/abhaile/.venv`, install `requirements.txt`.

#### Stage 5 — Configuration Validation

1. Verify hostname exists in `config/mapping.yaml`.
1. Verify hostname exists in `config/network.yaml`.
1. Abort with clear error if host is not defined in config.

#### Stage 6 — Sealed Artifact Handoff

1. Locate the sealed Vault Agent artifact at `secrets/<hostname>/vault-agent.sops.yaml`.
1. Decrypt required artifacts to ephemeral tmpdir (mode 0700, tmpfs preferred).
1. Consume values and write Vault Agent AppRole files.
1. Remove ephemeral tmpdir unconditionally (trap-guarded cleanup).

#### Stage 7 — First Render and Apply

1. Enable user lingering for `abhaile` user (`loginctl enable-linger abhaile`) — required
   before apply can manage rootless quadlets (vault-agent runs as `podman.user: abhaile`).
1. Run `abhaile-render --host <hostname> --output /var/lib/abhaile`.
1. Run `abhaile-apply --host <hostname> --output /var/lib/abhaile` (live apply, not dry-run).
1. Abort on failure with clear error and state summary.
1. Wait for Vault Agent `.ready` sentinel at `/srv/vault/agent/out/.ready` with configurable
   timeout (default 60s, polling interval 2s). If timeout expires, log warning but do not
   abort — runner handles steady-state convergence.

#### Stage 8 — GitOps Runner Registration

1. Enable and start `abhaile-runner.timer`.
1. Print summary: enrolled host, active services, next GitOps run time.

**Idempotency:** Each stage checks preconditions. Already-completed stages (user exists, repo
cloned, packages installed) are skipped with a log message. Partial failures resume from the
last incomplete stage on re-run.

### 2. Bootstrap Sealed Artifact Handoff

Per ADR 0007, sealed bootstrap and recovery artifacts live at `secrets/<host>/`.

**Required sealed artifacts per host:**

| Artifact | Contents | Consumed by |
| --- | --- | --- |
| `vault-agent.sops.yaml` | AppRole `role_id` for Vault Agent auth (`secret_id` is provided out of band at runtime) | Bootstrap Stage 6 |

Vault unseal keys are not part of the Vault Agent bootstrap artifact. On the Vault host, automated
unseal recovery uses `vault-unseal.sops.yaml`, owned by the host recovery path rather than the
Vault Agent bootstrap path.

**Decryption and consumption flow:**

1. Create ephemeral working directory (`mktemp -d` on tmpfs if available, otherwise
   `/tmp` with restrictive permissions). Use `mktemp -d --tmpdir=/dev/shm` as the
   preferred tmpfs path on Debian. Set mode 0700 immediately.
1. Decrypt with `sops --decrypt --output <tmpdir>/<artifact>.yaml <sealed-path>`.
1. Parse YAML, extract values into shell variables (never write to persistent files).
1. Use extracted values to:
   - Write RoleID to `/home/abhaile/.config/vault-agent/role-id` (mode 0600,
     owner `abhaile:abhaile`).
   - Write SecretID from the out-of-band handoff to
     `/home/abhaile/.config/vault-agent/secret-id` (mode 0600, owner `abhaile:abhaile`).
1. `rm -rf` ephemeral directory in EXIT trap (unconditional cleanup).
1. Defense-in-depth: implementation should also `shred` individual decrypted files
   before `rm -rf`, as `rm` on tmpfs does not guarantee immediate overwrite. The EXIT
   trap cannot protect against SIGKILL/OOM-kill; tmpfs residue is cleared on next reboot.

**Failure modes:**

- Missing sealed artifact: abort with message naming the expected file.
- Decryption failure (wrong/missing age key): abort with instructions to verify key placement.
- Vault API unreachable: abort with message; Vault must be running (either already on this
  host or on the other host) before bootstrap can complete credential handoff.
- Malformed artifact contents: abort with validation error.

### 3. Host Enrollment Flow

Complete operator workflow from bare metal to steady-state:

**Pre-bootstrap (operator actions, out-of-band):**

1. Install Debian 13 on target host. Set hostname (`phobos` or `deimos`).
1. Ensure host is defined in `config/mapping.yaml` and `config/network.yaml` (commit to repo).
1. Create `abhaile` user and group manually (`useradd -u 1001 -m -s /bin/bash abhaile`,
   `groupadd -g 1001 abhaile` if not already done). Bootstrap Stage 3 is idempotent and
   will skip creation if the user exists.
1. Generate and place age decryption identity:
   - `/home/abhaile/.config/sops/age/keys.txt` (mode 0600, owner `abhaile:abhaile`)
1. Generate and place git deploy key:
   - `/home/abhaile/.ssh/gitops_ed25519` (mode 0600, owner `abhaile:abhaile`)
   - Add public key to repo as read-only deploy key.
   - Add repo host to `/home/abhaile/.ssh/known_hosts`.
   - Bootstrap uses `GIT_SSH_COMMAND='ssh -i /home/abhaile/.ssh/gitops_ed25519 -o IdentitiesOnly=yes'`
     to force the deploy key (non-default key name requires explicit selection).
1. Ensure the sealed Vault Agent artifact exists in repo for this host
   (`secrets/<host>/vault-agent.sops.yaml`).
1. Ensure Vault is reachable from the target host (running on the other host, or on this
   host if it is the Vault host being re-enrolled).

**Bootstrap execution:**

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/<repo>/main/scripts/bootstrap.sh \
  | sudo bash -s -- <hostname>
```

Or on a host with repo already cloned:

```bash
sudo /opt/abhaile/scripts/bootstrap.sh <hostname>
```

**Post-bootstrap verification:**

1. Confirm GitOps timer is active: `systemctl status abhaile-runner.timer`
1. Confirm Vault Agent is running: `sudo -u abhaile systemctl --user status vault-agent`
1. Confirm secrets sentinel: `test -f /srv/vault/agent/out/.ready`
1. Confirm services are running: `systemctl status <service>` for mapped services.

**First-host special case (Vault host):**

When enrolling phobos (which runs Vault), the operator must have Vault already running and
accessible before bootstrap executes. Vault deployment, initial setup, and any required manual
unseal are documented as pre-bootstrap operator steps. Automated unseal after steady-state boot is
owned by the host recovery path, not onboarding bootstrap.

### 4. SecretID Handoff Handling

Bootstrap requires explicit credential input and refuses to proceed without it.

**Accepted credential forms (mutually exclusive, checked in order):**

1. Environment variable: `BOOTSTRAP_TOKEN` — response-wrapped AppRole SecretID preferred;
   direct AppRole SecretID allowed for recovery only when `BOOTSTRAP_DIRECT_SECRET_ID=1`.
1. File descriptor: `BOOTSTRAP_TOKEN_FD` — file descriptor number to read SecretID handoff
   material from (supports process substitution and pipe-based handoff).
1. Interactive prompt: if stdin is a TTY and neither env/fd is set, prompt once with
   no-echo (`read -rs`).

**Security properties:**

- SecretID handoff material is never written to disk except for the final host SecretID file.
- SecretID handoff material is never logged or echoed to stdout/stderr.
- SecretID handoff material is never passed as a command-line argument (avoids
  `/proc/<pid>/cmdline` exposure).
- SecretID handoff variable is unset immediately after consumption.
- Bootstrap exits non-zero if no credential is provided by any method.
- Bootstrap exits non-zero when SecretID unwrap fails unless `BOOTSTRAP_DIRECT_SECRET_ID=1`
  explicitly allows direct SecretID recovery.

**SecretID lifecycle:**

- Response-wrapping tokens are short-lived, one-time-use handoff credentials.
- The unwrapped AppRole SecretID is durable host credential material and is written to the host.
- If bootstrap fails after unwrapping but before SecretID placement, the operator must issue a new
  wrapped SecretID.
- Direct SecretID recovery is fail-closed by default and must be explicitly enabled for that run.

**Disposal:**

- `unset BOOTSTRAP_TOKEN` after value is captured into a local variable.
- Local variable is overwritten and unset after use.
- No token material survives the bootstrap process exit.

## Decision Notes

- Decision: Bootstrap is a shell script, not Python.

- Rationale: Bootstrap runs before the Python venv exists. Shell provides direct access to
  system package installation, user creation, and service management without runtime
  dependencies. The old project used this approach successfully.

- Impact: Business logic (render, apply, validation) stays in Python; bootstrap is
  orchestration and prerequisite setup only.

- ADR: null

- Decision: Sealed artifacts are decrypted to an ephemeral tmpdir, never to persistent paths.

- Rationale: ADR 0007 requires no plaintext bootstrap secrets persisting in durable paths.
  Ephemeral decryption with trap-guarded cleanup enforces this boundary.

- Impact: If bootstrap fails mid-consumption, no secret remnants remain. Re-run requires
  the operator to have the age key still available (it is persistent by design).

- ADR: 0007-sops-bootstrap-policy-and-layout

- Decision: Vault Agent AppRole files are the bootstrap-to-runtime auth handoff artifacts.

- Rationale: ADR 0009 defines native AppRole auto-auth as the durable host identity model.
  RoleID and SecretID files let Vault Agent re-authenticate after restart without custom refresh
  timers or seed-token lifecycle ambiguity.

- Impact: Bootstrap must place RoleID and SecretID files with strict permissions; Vault Agent takes
  over authentication and runtime token management from there.

- ADR: 0009-vault-agent-approle-auto-auth

- Decision: Bootstrap invokes the same `abhaile-render` and `abhaile-apply` entrypoints the
  runner uses.

- Rationale: Single code path for render/apply ensures bootstrap and steady-state produce
  identical results. No divergent apply logic.

- Impact: Python venv must be set up before first render/apply can run.

- ADR: 0003-gitops-runner-responsibility-boundary

- Decision: One-time token input uses env var, file descriptor, or interactive prompt (not
  CLI argument).

- Rationale: CLI arguments are visible in `/proc/<pid>/cmdline` and shell history. Env vars
  are visible in `/proc/<pid>/environ` only to same-uid or root. FD-based input is invisible
  to process listing. Interactive prompt is safest for manual use.

- Impact: Automated bootstrap must pass credentials via env or fd; operators use the prompt.

- ADR: null

- Decision: Vault is a pre-requisite, not something bootstrap creates.

- Rationale: Vault deployment and initial configuration are manual operator steps (like SSH keys
  and age identities). Bootstrap only unseals when authorized and places Vault Agent AppRole
  material.

- Impact: Operator must have Vault running and accessible before bootstrap. Documented as a pre-bootstrap step.

- ADR: null

- Decision: Require a read-only deploy key for repo access.

- Rationale: Deploy keys are standard for automated read-only access and avoid adding a sealed
  artifact type for repository credentials.

- Impact: Operators must place `/home/abhaile/.ssh/gitops_ed25519` before bootstrap. Hosts with an
  existing clone still use the deploy key for fetch and pull.

- ADR: null

- Decision: Re-enrollment is always idempotent fresh (preserve runner state, redo everything else).

- Rationale: Simplest model — no "detect and preserve" logic. Runner state is harmless to keep; next run updates it.

- Impact: Operator can re-run bootstrap safely on a partially enrolled or previously enrolled host.

- ADR: null

- Decision: Bootstrap installs sops in Stage 2 (prerequisites) via direct binary download from GitHub release with checksum.

- Rationale: sops is needed for sealed artifact decryption in Stage 6, before the software renderer can run. The software renderer later manages the canonical version via config/hosts/common/software/downloads/sops.yaml.

- Impact: Minor duplication between bootstrap prerequisite install and software renderer; second apply overwrites with the canonical pinned version.

- ADR: null

- Decision: Bootstrap waits for Vault Agent `.ready` sentinel after apply, with configurable timeout (default 60s).

- Rationale: Confirms the host is fully operational. Timeout value is provisional and should be adjusted during initial deployment testing.

- Impact: If sentinel doesn't appear within timeout, log warning but don't abort — runner handles steady-state convergence.

- ADR: null

- Decision: Bootstrap logs to both stdout and `/var/log/abhaile/bootstrap.log` via tee.

- Rationale: First-run bootstrap is outside systemd, so journald doesn't capture it. A log file is essential for post-mortem debugging.

- Impact: Log file persists for operator review; no secret material is logged.

## Acceptance Criteria

- [x] `scripts/bootstrap.sh` exists and is executable.
- [x] Running `scripts/bootstrap.sh` without a hostname argument exits non-zero with usage message.
- [x] Running `scripts/bootstrap.sh` without SecretID handoff material exits non-zero with credential requirement message.
- [x] Bootstrap installs all required packages and creates the `abhaile` user.
- [x] Bootstrap clones the repo and sets up the Python venv.
- [x] Bootstrap validates the host exists in `config/mapping.yaml` and `config/network.yaml`.
- [x] Bootstrap decrypts sealed Vault Agent artifacts from `secrets/<host>/` and removes all decrypted material on exit (success or failure).
- [x] Bootstrap places Vault Agent AppRole files with correct ownership and mode.
- [x] Bootstrap invokes `abhaile-render` and `abhaile-apply` for the target host.
- [x] Bootstrap enables and starts `abhaile-runner.timer`.
- [x] Bootstrap is idempotent: re-running on a partially enrolled host resumes without duplicating work.
- [x] No plaintext secret material persists in the repo tree, logs, or process-visible locations after bootstrap completes.
- [x] SecretID handoff supports env var (`BOOTSTRAP_TOKEN`), file descriptor (`BOOTSTRAP_TOKEN_FD`), and interactive prompt input methods.
- [x] Host enrollment flow is documented with pre-bootstrap operator steps, execution, and post-verification.
- [x] First-host (Vault host) enrollment handles the chicken-and-egg case where Vault is not yet running.
- [x] Unit tests cover token input validation, preflight checks, and stage sequencing logic (where testable without root).

### Evidence

- Implementation evidence: `scripts/bootstrap.sh`, `docs/guides/bootstrap.md`
- Validation evidence: `tests/integration/test_bootstrap.py` (5 tests), `bash -n` syntax check, `make test` 515 passed

## Out of Scope

- GitOps runner implementation (commit selection, scheduling, rollback) — covered by the
  GitOps Runner phase.
- Vault server setup, policy creation, or AppRole configuration — these are operator
  prerequisites documented but not automated by bootstrap.
- Runtime secret rendering — owned by Vault Agent after bootstrap handoff.
- Sealed bootstrap artifact creation tooling — covered by the Ops Tooling phase
  (Sealed bootstrap artifact tooling task).
- Network device configuration or VLAN setup on switches/routers.
- Package/software execution beyond what `abhaile-apply` already handles.

## Open Questions

All original open questions have been resolved. See Decision Notes.

## References

- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/adr/0007-sops-bootstrap-policy-and-layout.md`
- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `TODO.md` Phase: Bootstrap (all 4 tasks and session prompts)
- `.old_docs/TODO.md` Phase 2: Bootstrap (prior art implementation)
- `.old_docs/DEPLOYMENT_VALIDATION_PLAN.md` (old bootstrap flow diagram)
- `README.md` Bootstrap section and SOPS Bootstrap Policy section
