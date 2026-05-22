# Spec: Bootstrap

## Metadata

```yaml
id: SPEC-2026-014
title: Bootstrap
status: proposed
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

- **Bootstrap owns:** age decryption identity (operator-placed), sealed bootstrap artifacts
  (`config/bootstrap/sealed/<host>/`), one-time Vault AppRole credential handoff, repo access
  credential (deploy key or token).
- **Bootstrap does NOT own:** runtime service secrets (API keys, DB passwords, TLS keypairs,
  SMTP credentials). These belong to Vault Agent at runtime per ADR 0006.
- **Handoff point:** bootstrap places the initial Vault Agent seed token at
  `/home/abhaile/.config/vault-agent/token`. From that point, Vault Agent renders all
  runtime secrets to host-only paths.

## Requirements

- [ ] Implement `scripts/bootstrap.sh` as a curl-bash entry point for fresh host enrollment.
- [ ] Implement sealed bootstrap artifact decryption and consumption without plaintext persistence.
- [ ] Define and document the complete host enrollment flow from bare metal to first successful apply.
- [ ] Implement one-time token/credential handling that refuses to run without explicit input.

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

1. Install base packages: `git`, `python3`, `python3-venv`, `podman`, `age`, `jq`, `curl`.
1. Install `sops` binary (from GitHub release, pinned version, verified checksum).
1. Enable `systemd-networkd` and `systemd-resolved`.

#### Stage 3 — Credential Validation

1. Require one-time bootstrap token (see §4 below).
1. Verify age decryption identity exists at `/home/abhaile/.config/sops/age/keys.txt` (or
   root path for root-scoped artifacts). Abort with instructions if missing.
1. Verify repo access credential (deploy key at `/home/abhaile/.ssh/gitops_ed25519` or
   token from one-time input). Abort if neither available.

#### Stage 4 — Repo and Environment

1. Create `abhaile` system user if absent (uid from `config/`, shell `/bin/bash`,
   home `/home/abhaile`).
1. Clone repo to `/opt/abhaile` (or pull if directory exists for re-run idempotency).
1. Checkout target branch (default: `main`).
1. Create Python venv at `/opt/abhaile/.venv`, install `requirements.txt`.

#### Stage 5 — Configuration Validation

1. Verify hostname exists in `config/mapping.yaml`.
1. Verify hostname exists in `config/network.yaml`.
1. Abort with clear error if host is not defined in config.

#### Stage 6 — Sealed Artifact Handoff

1. Locate sealed artifacts at `config/bootstrap/sealed/<hostname>/`.
1. Decrypt required artifacts to ephemeral tmpdir (mode 0700, tmpfs preferred).
1. Consume values (place Vault seed token, configure AppRole initial auth).
1. Remove ephemeral tmpdir unconditionally (trap-guarded cleanup).

#### Stage 7 — First Render and Apply

1. Run `abhaile-render --host <hostname> --output /var/lib/abhaile`.
1. Run `abhaile-apply --host <hostname> --output /var/lib/abhaile` (live apply, not dry-run).
1. Abort on failure with clear error and state summary.

#### Stage 8 — GitOps Runner Registration

1. Enable and start `abhaile-runner.timer`.
1. Enable user lingering for `abhaile` user (`loginctl enable-linger abhaile`).
1. Print summary: enrolled host, active services, next GitOps run time.

**Idempotency:** Each stage checks preconditions. Already-completed stages (user exists, repo
cloned, packages installed) are skipped with a log message. Partial failures resume from the
last incomplete stage on re-run.

### 2. Bootstrap Sealed Artifact Handoff

Per ADR 0007, sealed bootstrap artifacts live at `config/bootstrap/sealed/<host>/`.

**Required sealed artifacts per host:**

| Artifact | Contents | Consumed by |
| --- | --- | --- |
| `vault-bootstrap.sops.yaml` | Vault AppRole role_id and initial wrapped secret_id for seed token minting | Bootstrap Stage 6 |
| `repo-bootstrap.sops.yaml` | (Optional) Repo access token if deploy key is not pre-placed | Bootstrap Stage 3/4 |

**Decryption and consumption flow:**

1. Create ephemeral working directory (`mktemp -d` on tmpfs if available, otherwise
   `/tmp` with restrictive permissions).
1. Decrypt with `sops --decrypt --output <tmpdir>/<artifact>.yaml <sealed-path>`.
1. Parse YAML, extract values into shell variables (never write to persistent files).
1. Use extracted values to:
   - Mint initial Vault Agent seed token via Vault API (AppRole login).
   - Write seed token to `/home/abhaile/.config/vault-agent/token` (mode 0600,
     owner `abhaile:abhaile`).
1. `rm -rf` ephemeral directory in EXIT trap (unconditional cleanup).

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
1. Generate and place age decryption identity:
   - `/home/abhaile/.config/sops/age/keys.txt` (mode 0600, owner `abhaile:abhaile`)
   - `/root/.config/sops/age/keys.txt` (mode 0600, for root-scoped decryption if needed)
1. Generate and place git deploy key:
   - `/home/abhaile/.ssh/gitops_ed25519` (mode 0600, owner `abhaile:abhaile`)
   - Add public key to repo as read-only deploy key.
   - Add repo host to `/home/abhaile/.ssh/known_hosts`.
1. Ensure sealed bootstrap artifacts exist in repo for this host
   (`config/bootstrap/sealed/<host>/vault-bootstrap.sops.yaml`).
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

When enrolling the first host (phobos, which runs Vault), Vault is not yet available for
AppRole token minting. Bootstrap handles this by:

1. Skipping Vault API token minting in Stage 6.
1. Using sealed Vault unseal keys to start and unseal Vault.
1. Creating the initial AppRole and minting the seed token locally post-Vault-start.
1. Proceeding with the normal flow from Stage 7 onward.

### 4. One-Time Token Handling

Bootstrap requires explicit credential input and refuses to proceed without it.

**Accepted credential forms (mutually exclusive, checked in order):**

1. Environment variable: `BOOTSTRAP_TOKEN` — a one-time wrapped token or AppRole secret_id
   passed via the calling environment.
1. File descriptor: `BOOTSTRAP_TOKEN_FD` — file descriptor number to read token from
   (supports process substitution and pipe-based handoff).
1. Interactive prompt: if stdin is a TTY and neither env/fd is set, prompt once with
   no-echo (`read -rs`).

**Security properties:**

- Token is never written to disk.
- Token is never logged or echoed to stdout/stderr.
- Token is never passed as a command-line argument (avoids `/proc/<pid>/cmdline` exposure).
- Token variable is unset immediately after consumption.
- Bootstrap exits non-zero if no credential is provided by any method.

**Token lifecycle:**

- The token is a short-lived, one-time-use credential (wrapped SecretID or similar).
- After bootstrap uses it to mint the initial Vault Agent seed token, the one-time token
  is consumed/expired on the Vault side.
- If bootstrap fails after token consumption but before seed token placement, the operator
  must issue a new one-time token.

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

- Decision: The Vault seed token at `/home/abhaile/.config/vault-agent/token` is the single
  bootstrap-to-runtime handoff artifact.

- Rationale: ADR 0006 defines this path as the bootstrap-only input that Vault Agent consumes
  to begin runtime operation. Everything downstream is Vault-managed.

- Impact: Bootstrap must mint or place this token; Vault Agent takes over from there.

- ADR: 0006-secrets-model-and-bootstrap-artifacts

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

## Acceptance Criteria

- [ ] `scripts/bootstrap.sh` exists and is executable.
- [ ] Running `scripts/bootstrap.sh` without a hostname argument exits non-zero with usage message.
- [ ] Running `scripts/bootstrap.sh` without a bootstrap token exits non-zero with credential requirement message.
- [ ] Bootstrap installs all required packages and creates the `abhaile` user.
- [ ] Bootstrap clones the repo and sets up the Python venv.
- [ ] Bootstrap validates the host exists in `config/mapping.yaml` and `config/network.yaml`.
- [ ] Bootstrap decrypts sealed artifacts from `config/bootstrap/sealed/<host>/` and removes all decrypted material on exit (success or failure).
- [ ] Bootstrap places the Vault Agent seed token at `/home/abhaile/.config/vault-agent/token` with correct ownership and mode.
- [ ] Bootstrap invokes `abhaile-render` and `abhaile-apply` for the target host.
- [ ] Bootstrap enables and starts `abhaile-runner.timer`.
- [ ] Bootstrap is idempotent: re-running on a partially enrolled host resumes without duplicating work.
- [ ] No plaintext secret material persists in the repo tree, logs, or process-visible locations after bootstrap completes.
- [ ] One-time token handling supports env var (`BOOTSTRAP_TOKEN`), file descriptor (`BOOTSTRAP_TOKEN_FD`), and interactive prompt input methods.
- [ ] Host enrollment flow is documented with pre-bootstrap operator steps, execution, and post-verification.
- [ ] First-host (Vault host) enrollment handles the chicken-and-egg case where Vault is not yet running.
- [ ] Unit tests cover token input validation, preflight checks, and stage sequencing logic (where testable without root).

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

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

1. **Vault availability for first-host bootstrap:** When enrolling phobos (which hosts Vault),
   should bootstrap start Vault from rendered quadlets before attempting AppRole auth, or
   should the operator start Vault manually first? The old project had Vault unseal as a
   separate systemd unit — does the new design keep that pattern?

1. **Deploy key vs token for repo access:** Should bootstrap accept both a pre-placed deploy
   key and a token-based repo clone (e.g., GitHub PAT), or standardize on one? The old
   project used deploy keys exclusively.

1. **Bootstrap re-enrollment:** If a host is being rebuilt (not first-time), should bootstrap
   detect existing state and offer a "re-enroll" path that preserves runner state, or always
   start clean? The old project treated re-runs as idempotent fresh installs.

1. **sops binary installation method:** Pin to a specific GitHub release with checksum
   verification, or rely on a Debian package if available in trixie? The old project used
   direct binary download.

1. **Vault Agent startup timing:** After bootstrap places the seed token and apply installs
   Vault Agent quadlets, should bootstrap explicitly wait for the `.ready` sentinel before
   declaring success, or is it sufficient that the GitOps timer will handle steady-state
   convergence?

1. **Bootstrap logging:** Should bootstrap log to a file under `/var/log/abhaile/` for
   post-mortem debugging, or is systemd journal capture (when run via a unit) sufficient?
   The script itself runs outside systemd on first execution.

## References

- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/adr/0007-sops-bootstrap-policy-and-layout.md`
- `docs/adr/0003-gitops-runner-responsibility-boundary.md`
- `TODO.md` Phase: Bootstrap (all 4 tasks and session prompts)
- `.old_docs/TODO.md` Phase 2: Bootstrap (prior art implementation)
- `.old_docs/DEPLOYMENT_VALIDATION_PLAN.md` (old bootstrap flow diagram)
- `README.md` Bootstrap section and SOPS Bootstrap Policy section
