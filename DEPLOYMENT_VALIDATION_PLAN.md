# Deployment Validation Plan

**Date:** 2026-01-11
**Status:** Ready for execution
**Scope:** Phase 2 GitOps Deployment & Validation for deimos and phobos

## Executive Summary

This document provides a comprehensive analysis of the "Deployment Validation" section from TODO.md Phase 2, confirming implementation status, documenting the GitOps bootstrap flow, and providing actionable deployment plans for both hosts.

Key Findings:

- ✅ All core GitOps functionality is **implemented and ready**
- ✅ Atomic apply with backup is implemented in `tools/apply/lib/apply_phase.sh`
- ✅ Rollback mechanism exists via timestamped backups
- ⚠️ Services are already deployed on both hosts (manual migration to GitOps control needed)
- ⚠️ Some validation tasks (health checks, E2E tests, deSEC live apply) require post-deployment implementation

______________________________________________________________________

## 1. Implementation Status Confirmation

### 1.1 Checklist from TODO.md "Deployment Validation"

| Item | Status | Location/Evidence |
| --- | --- | --- |
| **Atomic apply with backup/rollback** | ✅ IMPLEMENTED | `tools/apply/lib/apply_phase.sh:apply_files()` creates timestamped backups in `/var/lib/abhaile/backups/` (from `tools/paths.ini`) before applying |
| **Rollback mechanism** | ✅ IMPLEMENTED | Automatic rollback via commit-based restoration in `gitops_runner.sh`: on render/apply failure, reverts to last successful commit, re-runs apply, stores rollback state in `/var/lib/abhaile/state/gitops.state` |
| **Deploy on deimos** | 🔄 READY (needs execution) | All tooling ready; plan in Section 3 |
| **Deploy on phobos** | 🔄 READY (needs execution) | All tooling ready; plan in Section 4 |
| **Service health checks** | ⚠️ PARTIAL | systemd status checks in apply.sh; needs formal health check framework |
| **End-to-end connectivity tests** | ❌ TODO | Needs implementation post-deployment |
| **DNS resolution validation** | ⚠️ PARTIAL | DNS zones rendered; needs automated validation tests |
| **TLS certificate validation** | ⚠️ PARTIAL | Internal CA via Caddy; needs cert verification tests |
| **deSEC apply phase validation** | ⚠️ PARTIAL | Plan generation implemented; live apply needs testing |
| **Trigger/poll/timer design** | ✅ IMPLEMENTED | `systemd/abhaile-gitops@.timer` (15min interval + 2min jitter) |
| **Change detection and validation** | ✅ IMPLEMENTED | `tools/apply/lib/drift.sh` with 6-category state tracking |
| **State file tracking** | ✅ IMPLEMENTED | `out/state/*.state` (networkd, services, systemd, resolved, software, users) |
| **Deployment state tracking** | ✅ IMPLEMENTED | State files updated post-apply; gitops runner tracks commit hash |

### 1.2 Core GitOps Components

Rendering Pipeline:

- ✅ `tools/render/cli.py` - Orchestrator for all rendering
- ✅ Multi-host context awareness (DNS, Caddy, deSEC need all hosts)
- ✅ Jinja2 template system with placeholder resolution (`%%path.to.value%%`)
- ✅ Validation at render time (schema, semantic, networkd syntax)

Apply Pipeline:

- ✅ `tools/apply/apply.sh` - Main orchestrator
- ✅ Modular bash libraries in `tools/apply/lib/`:
  - `drift.sh` - 6-category drift detection with state files
  - `staging.sh` - Atomic staging to temp directories
  - `apply_phase.sh` - Backup creation, file application, stale file removal
  - `runtime.sh` - systemd daemon-reload, service restarts, gratuitous ARP
  - `validation.sh` - systemd-analyze verify, quadlet syntax checks
  - `services.sh` - Rootful/rootless Podman quadlet handling
  - `desec.sh` - deSEC plan application and rollback

GitOps Runner:

- ✅ `tools/gitops/gitops_runner.sh` - Unprivileged sync-render loop
- ✅ `systemd/abhaile-gitops@.service` - Oneshot service (user: abhaile)
- ✅ `systemd/abhaile-gitops@.timer` - 15min periodic execution + jitter
- ✅ `systemd/abhaile-gitops-apply@.path` - Watches `.apply_ready` sentinel
- ✅ `systemd/abhaile-gitops-apply@.service` - Privileged apply (user: root)

Bootstrap:

- ✅ `tools/bootstrap/bootstrap.sh` - curl-bash installer for new hosts
- ✅ Preflight checks (age key, deploy key, SOPS files, packages)
- ✅ Initial deployment via `apply.sh --apply`

Secrets Management:

- ✅ SOPS decryption in gitops_runner.sh (`decrypt_secrets_if_changed()`)
- ✅ Vault AppRole token refresh (`tools/vault/vault_token_refresh.sh`)
- ✅ Vault unseal automation (`tools/vault/vault_unseal.sh`)
- ✅ SOPS file templates in `secrets/*.example`

______________________________________________________________________

## 2. GitOps Bootstrap Flow Analysis

### 2.1 Logical Flow Diagram

```text
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 1: Manual Prerequisites (Operator Actions)                │
├─────────────────────────────────────────────────────────────────┤
│ 1. Generate Age keypair on trusted machine                      │
│    → age-keygen -o keys.txt                                     │
│    → Record public recipient (age1...) for .sops.yaml           │
│                                                                 │
│ 2. Generate Git deploy key (read-only)                          │
│    → ssh-keygen -t ed25519 -f gitops_ed25519 -C "gitops@host"   │
│    → Add public key to GitHub as deploy key                     │
│                                                                 │
│ 3. Create SOPS-encrypted secrets                                │
│    → secrets/gitops-<host>.sops.env (repo URL, branch)          │
│    → secrets/vault-agent-approle-<host>.sops.env (AppRole)      │
│    → secrets/caddy-dmz-desec.sops.yaml (deSEC token)            │
│    → secrets/vault-unseal.sops.yaml (unseal keys - existing)    │
│                                                                 │
│ 4. Install Age key on target host                               │
│    → /root/.config/sops/age/keys.txt (mode 0600)                │
│    → /home/abhaile/.config/sops/age/keys.txt (mode 0600)        │
│                                                                 │
│ 5. Install deploy key on target host                            │
│    → /home/abhaile/.ssh/gitops_ed25519 (mode 0600)              │
│    → Add github.com to known_hosts                              │
│                                                                 │
│ 6. Define host in config files                                  │
│    → config/network.yaml (interfaces, VLANs, addressing)        │
│    → config/mapping.yaml (host -> services assignment)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2: Bootstrap Script Execution                             │
├─────────────────────────────────────────────────────────────────┤
│ curl -fsSL .../bootstrap.sh | sudo bash -s -- <host>            │
│                                                                 │
│ → tools/bootstrap/bootstrap.sh:                                 │
│   1. Preflight checks                                           │
│      - Verify root user                                         │
│      - Check commands: git, podman, age, sops, systemctl        │
│      - Confirm Debian OS                                        │
│      - Test GitHub connectivity                                 │
│                                                                 │
│   2. Install base packages                                      │
│      - git, python3-venv, podman, age, sops, curl, jq           │
│      - Enable systemd-networkd and systemd-resolved             │
│                                                                 │
│   3. Verify Age keys exist                                      │
│      - /root/.config/sops/age/keys.txt                          │
│      - /home/abhaile/.config/sops/age/keys.txt                  │
│      - ABORT if not found (operator must install manually)      │
│                                                                 │
│   4. Clone repo                                                 │
│      - git clone $REPO_URL /opt/abhaile                         │
│      - checkout $BRANCH                                         │
│                                                                 │
│   5. Setup Python venv                                          │
│      - python3 -m venv /opt/abhaile/.venv                       │
│      - pip install -r requirements.txt                          │
│                                                                 │
│   6. Validate configuration                                     │
│      - Confirm host in config/network.yaml                      │
│      - Confirm host in config/mapping.yaml                      │
│      - ABORT if either missing                                  │
│                                                                 │
│   7. Render configurations                                      │
│      - python3 tools/render/cli.py <host>                       │
│      - Output to out/rendered/<host>/                           │
│      - ABORT if render fails                                    │
│                                                                 │
│   8. Verify deploy user and keys                                │
│      - Create 'abhaile' user if not exists                      │
│      - Check /home/abhaile/.ssh/gitops_ed25519                  │
│      - Add github.com to known_hosts                            │
│      - ABORT if deploy key missing                              │
│                                                                 │
│   9. Apply configuration                                        │
│      - tools/apply/apply.sh --apply <host>                      │
│      - Installs all systemd units                               │
│      - Applies networkd, services, resolved, users, software    │
│      - Enables and starts services                              │
│                                                                 │
│  10. Summary and next steps                                     │
│      - Print GitOps timer status                                │
│      - Print validation commands                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 3: GitOps Automation (Steady State)                       │
├─────────────────────────────────────────────────────────────────┤
│ Timer: abhaile-gitops@<host>.timer                              │
│   → Runs every 15 minutes (RandomizedDelaySec=120s)             │
│   → Triggers abhaile-gitops@<host>.service                      │
│                                                                 │
│ Service: abhaile-gitops@<host>.service (User: abhaile)          │
│   → WorkingDirectory=/opt/abhaile                               │
│   → EnvironmentFile=/etc/abhaile/gitops/.env                    │
│   → ExecStart=/opt/abhaile/tools/gitops/gitops_runner.sh        │
│                                                                 │
│ gitops_runner.sh workflow:                                      │
│   1. Load environment from /etc/abhaile/gitops/.env             │
│      - REPO_URL, BRANCH, DRY_RUN, AUTO_RESTART                  │
│      - GIT_SSH_KEY (deploy key path)                            │
│                                                                 │
│   2. Git fetch + checkout                                       │
│      - git fetch origin $BRANCH                                 │
│      - git checkout -qf FETCH_HEAD                              │
│                                                                 │
│   3. Decrypt SOPS secrets (if changed)                          │
│      - decrypt_secrets_if_changed()                             │
│      - Checks mtime; skips if plaintext newer                   │
│      - Decrypts to /etc/abhaile/<service>/                      │
│      - Sets permissions 0600                                    │
│                                                                 │
│   4. Render configurations                                      │
│      - python3 tools/render/cli.py $HOST_INSTANCE               │
│      - Output to /var/lib/abhaile/rendered/$HOST_INSTANCE/      │
│                                                                 │
│   5. Touch sentinel flag                                        │
│      - touch /var/lib/abhaile/rendered/.apply_ready             │
│      - Triggers abhaile-gitops-apply@<host>.path                │
│                                                                 │
│ Path: abhaile-gitops-apply@<host>.path                          │
│   → Watches /var/lib/abhaile/rendered/.apply_ready              │
│   → Triggers abhaile-gitops-apply@<host>.service                │
│                                                                 │
│ Service: abhaile-gitops-apply@<host>.service (User: root)       │
│   → ExecStart=/opt/abhaile/tools/apply/apply.sh --skip-render \ │
│                --apply $HOST_INSTANCE                           │
│   → Removes .apply_ready flag post-execution                    │
│                                                                 │
│ apply.sh workflow (privileged):                                 │
│   1. Validate environment                                       │
│      - Detect RENDER_DIR, STATE_DIR, NET_CONFIG_DIR             │
│      - Load config.py env vars                                  │
│                                                                 │
│   2. Skip render (--skip-render flag)                           │
│      - Uses existing /var/lib/abhaile/rendered/ output          │
│      - Validates freshness (sources not newer than rendered)    │
│                                                                 │
│   3. Validate configurations                                    │
│      - systemd-analyze verify (networkd files)                  │
│      - Quadlet syntax checks                                    │
│      - Semantic validation (IP uniqueness, VLAN consistency)    │
│                                                                 │
│   4. Detect drift (6 categories)                                │
│      - networkd.state (systemd-networkd configs)                │
│      - services.state (quadlets + service configs)              │
│      - systemd.state (static systemd units)                     │
│      - resolved.state (resolv.conf + resolved.conf)             │
│      - software.state (packages + aux files)                    │
│      - users.state (users + sudoers)                            │
│      - Compare SHA256 hashes; log NEW/CHANGED/REMOVED           │
│                                                                 │
│   5. Stage files atomically                                     │
│      - Copy to tmp/ staging directory                           │
│      - Verify all files before applying                         │
│                                                                 │
│   6. Create backups                                             │
│      - Timestamped backup dirs for each category                │
│      - /var/backups/abhaile/<category>-<timestamp>/             │
│                                                                 │
│   7. Apply changes                                              │
│      - Copy staged files to target locations                    │
│      - Remove stale files (REMOVED drift entries)               │
│      - Handle rootful/rootless Podman quadlets                  │
│      - Create named volume host directories                     │
│                                                                 │
│   8. Reload services                                            │
│      - systemctl daemon-reload (rootful)                        │
│      - systemctl --user daemon-reload (per rootless user)       │
│      - systemctl restart (changed services only if AUTO_RESTART)│
│      - systemctl reload systemd-networkd                        │
│                                                                 │
│   9. Send gratuitous ARP                                        │
│      - For all /32 service addresses on ipvlan-l2 interfaces    │
│      - arping -c 3 -I <interface> <ip>                          │
│                                                                 │
│  10. Update state files                                         │
│      - mv *.state.new -> *.state                                │
│      - Tracks current deployment state                          │
│                                                                 │
│  11. deSEC DNS sync (if enabled)                                │
│      - Apply deSEC plan (if drift detected)                     │
│      - Rollback on failure (if STRICT_DESEC=1)                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Directory Structure Alignment

Development vs Production Paths:

| Context | Rendered Output | State Files | Network Config | Software | GitOps Work Dir |
| --- | --- | --- | --- | --- | --- |
| **Dev** (local) | `$REPO/out/rendered/` | `$REPO/out/state/` | `$REPO/out/rendered/<host>/systemd-networkd/` | `$REPO/out/rendered/<host>/software/` | N/A |
| **Prod** (host) | `/var/lib/abhaile/rendered/` | `/var/lib/abhaile/state/` | `/etc/systemd/network/` | `/var/lib/abhaile/software/` | `/opt/abhaile/` |

Service File Targets:

| Type | Rendered Path | Target Path (Rootful) | Target Path (Rootless) |
| --- | --- | --- | --- |
| Quadlets | `rendered/<host>/services/<svc>/*.{container,volume,network}` | `/etc/containers/systemd/` | `/home/<user>/.config/containers/systemd/` |
| Config Files | `rendered/<host>/services/<svc>/config/*` | `/srv/<svc>/config/` | `/home/<user>/<svc>/config/` |
| Static systemd | `rendered/<host>/systemd/` | `/etc/systemd/system/` | N/A |
| Vault Agent templates | `rendered/<host>/services/vault-agent/templates/` | `/srv/vault/agent/templates/` | N/A |
| Vault Agent output | N/A (Vault Agent writes) | `/srv/vault/agent/out/` | N/A |

State File Locations:

- Dev: `$REPO/out/state/*.state`
- Prod: `/var/lib/abhaile/state/*.state`

State files use production paths (`/var/lib/abhaile/state/`) even during dev when `--apply` is used.

### 2.3 Prerequisites Checklist (Detailed)

Before running bootstrap.sh:

✅ **Age Keys (Manual Installation Required)**

- Generate on trusted machine: `age-keygen -o keys.txt`

- Record public recipient (starts with `age1...`) for `.sops.yaml`

- Install for root:

  ```bash
  sudo mkdir -p /root/.config/sops/age
  sudo install -m 600 keys.txt /root/.config/sops/age/keys.txt
  ```

- Install for abhaile user:

  ```bash
  sudo mkdir -p /home/abhaile/.config/sops/age
  sudo install -m 600 keys.txt /home/abhaile/.config/sops/age/keys.txt
  sudo chown -R abhaile:abhaile /home/abhaile/.config/sops
  ```

✅ **Git Deploy Key (Manual Installation Required)**

- Generate SSH key for read-only repo access:

  ```bash
  ssh-keygen -t ed25519 -f gitops_ed25519 -C "gitops@<host>" -N ""
  ```

- Add `gitops_ed25519.pub` to GitHub as deploy key (Settings → Deploy keys → Read-only)

- Install on target host:

  ```bash
  sudo mkdir -p /home/abhaile/.ssh
  sudo install -m 600 gitops_ed25519 /home/abhaile/.ssh/gitops_ed25519
  sudo chown -R abhaile:abhaile /home/abhaile/.ssh
  ```

✅ **SOPS-Encrypted Secrets (Must exist in repo)**

1. `secrets/gitops-<host>.sops.env`:

   ```bash
   # Copy template
   cp secrets/gitops-phobos.sops.env.example /tmp/gitops-phobos.env

   # Edit with real values
   vim /tmp/gitops-phobos.env
   # REPO_URL=git@github.com:moonpie/abhaile.git
   # BRANCH=main
   # WORK_DIR=/opt/abhaile
   # GIT_SSH_KEY=/home/abhaile/.ssh/gitops_ed25519
   # DRY_RUN=0
   # AUTO_RESTART=1

   # Encrypt with SOPS
   sops -e /tmp/gitops-phobos.env > secrets/gitops-phobos.sops.env

   # Verify
   sops -d secrets/gitops-phobos.sops.env | head

   # Commit encrypted file
   git add secrets/gitops-phobos.sops.env
   git commit -m "feat: add gitops config for phobos"
   ```

1. `secrets/vault-agent-approle-<host>.sops.env`:

   ```bash
   # Copy template
   cp secrets/vault-agent-approle-phobos.sops.env.example /tmp/vault-agent-approle-phobos.env

   # Generate AppRole credentials in Vault (manual step via vault CLI)
   # vault write auth/approle/role/<host>-vault-agent ... (see Vault docs)
   # vault read auth/approle/role/<host>-vault-agent/role-id
   # vault write -f auth/approle/role/<host>-vault-agent/secret-id

   # Edit with role-id and secret-id
   vim /tmp/vault-agent-approle-phobos.env
   # VAULT_ADDR=http://172.20.20.204:8200
   # VAULT_ROLE_ID=<role-id>
   # VAULT_ROLE_SECRET_ID=<secret-id>

   # Encrypt
   sops -e /tmp/vault-agent-approle-phobos.env > secrets/vault-agent-approle-phobos.sops.env

   # Commit
   git add secrets/vault-agent-approle-phobos.sops.env
   git commit -m "feat: add vault approle for phobos"
   ```

1. `secrets/caddy-dmz-desec.sops.yaml` (if not already present):

   ```bash
   # Copy template
   cp secrets/caddy-dmz-desec.sops.yaml.example /tmp/caddy-dmz-desec.yaml

   # Edit with real deSEC token
   vim /tmp/caddy-dmz-desec.yaml
   # DESEC_TOKEN: "<your-token>"

   # Encrypt
   sops -e /tmp/caddy-dmz-desec.yaml > secrets/caddy-dmz-desec.sops.yaml

   # Commit
   git add secrets/caddy-dmz-desec.sops.yaml
   git commit -m "feat: add desec token"
   ```

1. `secrets/vault-unseal.sops.yaml` (already exists, verify):

   ```bash
   # Verify decryption works
   sops -d secrets/vault-unseal.sops.yaml | head
   ```

✅ **Host Configuration (Must exist in config/)**

1. `config/network.yaml`:

   - Host entry under `hosts.<hostname>` with interfaces, addresses, VLANs
   - DNS records for host in `hosts.<hostname>.dns`
   - Example: hosts.phobos, hosts.deimos already present

1. `config/mapping.yaml`:

   - Host entry under `abhaile[].hostname` with service list
   - Example: phobos → ddclient, chrony-a, coredns-filtered, etc.

1. Service configurations:

   - All services in mapping must have `config/services/<svc>/service.yaml`
   - Validate with: `python3 tools/render/cli.py --validate-only`

✅ **Network Connectivity**

- Host can reach github.com:22 (SSH for git clone)
- Host has working network configuration (manual DHCP or static IP)
- DNS resolution working (for package installation)

______________________________________________________________________

## 3. Deployment Plan: Deimos

**Host:** deimos
**Services:** chrony-b, coredns-clean, vault-agent
**Current State:** Services already deployed manually
**Goal:** Migrate to GitOps control without disruption

### 3.1 Pre-Deployment Validation

**Check current service state:**

```bash

# On deimos, check what's already running

ssh deimos "systemctl list-units --type=service --state=running | grep -E 'chrony|coredns|vault-agent'"

# Check Podman containers

ssh deimos "podman ps -a"

# Check systemd-networkd configs

ssh deimos "ls -la /etc/systemd/network/"

# Check existing state files (if any)

ssh deimos "ls -la /var/lib/abhaile/state/ 2>/dev/null || echo 'No state files yet'"
```

Expected output:

- chrony-b.service running
- coredns-clean.service running
- vault-agent.service running (rootless under 'abhaile' user)
- ipvlan-l2 interface configured
- /32 service addresses assigned

Validation steps:

- Verify services are in mapping.yaml for deimos
- Verify network.yaml has correct addresses for deimos services
- Render locally and compare with live configs

```bash

# On dev machine, render deimos

make render

# Compare rendered networkd configs with live

diff -ur out/rendered/deimos/systemd-networkd/ <(ssh deimos "cat /etc/systemd/network/*.network /etc/systemd/network/*.netdev 2>/dev/null")

# Review services drift (expect all NEW since no state files yet)

./tools/apply/apply.sh deimos
```

### 3.2 Migration Steps (Deimos)

### Step 1 (Deimos): Create Age Keys

```bash

# On trusted machine, generate Age key

age-keygen -o deimos-keys.txt

# Save the public recipient (age1...) for .sops.yaml

# Copy to deimos

scp deimos-keys.txt root@deimos:/tmp/

# On deimos, install Age keys

ssh root@deimos "mkdir -p /root/.config/sops/age && install -m 600 /tmp/deimos-keys.txt /root/.config/sops/age/keys.txt && rm /tmp/deimos-keys.txt"
ssh root@deimos "mkdir -p /home/abhaile/.config/sops/age && install -m 600 /root/.config/sops/age/keys.txt /home/abhaile/.config/sops/age/keys.txt && chown -R abhaile:abhaile /home/abhaile/.config/sops"

# Verify

ssh root@deimos "sops -d /opt/abhaile/secrets/vault-unseal.sops.yaml | head"
```

### Step 2 (Deimos): Create Deploy Key

```bash

# On dev machine, generate deploy key

ssh-keygen -t ed25519 -f gitops_ed25519_deimos -C "gitops@deimos" -N ""

# Add gitops_ed25519_deimos.pub to GitHub as deploy key (read-only)

# Copy to deimos

scp gitops_ed25519_deimos root@deimos:/tmp/

# On deimos, install deploy key

ssh root@deimos "mkdir -p /home/abhaile/.ssh && install -m 600 /tmp/gitops_ed25519_deimos /home/abhaile/.ssh/gitops_ed25519 && chown -R abhaile:abhaile /home/abhaile/.ssh && rm /tmp/gitops_ed25519_deimos"
ssh root@deimos "su - abhaile -c 'ssh-keyscan github.com >> ~/.ssh/known_hosts'"

# Verify

ssh root@deimos "su - abhaile -c 'ssh -T git@github.com 2>&1 | grep successfully'"
```

### Step 3 (Deimos): Create SOPS Secrets

```bash

# On dev machine, create gitops env file

cat > /tmp/gitops-deimos.env <<EOF
REPO_URL=git@github.com:moonpie/abhaile.git
BRANCH=main
WORK_DIR=/opt/abhaile
GIT_SSH_KEY=/home/abhaile/.ssh/gitops_ed25519
DRY_RUN=0
AUTO_RESTART=1
EOF

# Encrypt

sops -e /tmp/gitops-deimos.env > secrets/gitops-deimos.sops.env

# Create vault-agent approle (requires existing Vault with AppRole configured)

# Manual step: Generate role-id and secret-id in Vault

# vault write auth/approle/role/deimos-vault-agent ...

# vault read auth/approle/role/deimos-vault-agent/role-id

# vault write -f auth/approle/role/deimos-vault-agent/secret-id

cat > /tmp/vault-agent-approle-deimos.env <<EOF
VAULT_ADDR=http://172.20.20.204:8200
VAULT_ROLE_ID=<role-id>
VAULT_ROLE_SECRET_ID=<secret-id>
EOF

# Encrypt

sops -e /tmp/vault-agent-approle-deimos.env > secrets/vault-agent-approle-deimos.sops.env

# Commit to repo

git add secrets/gitops-deimos.sops.env secrets/vault-agent-approle-deimos.sops.env
git commit -m "feat: add gitops and vault-agent secrets for deimos"
git push
```

### Step 4 (Deimos): Run Bootstrap (Dry-Run)

```bash

# On dev machine, copy bootstrap script to deimos

scp tools/bootstrap/bootstrap.sh root@deimos:/tmp/

# On deimos, run bootstrap (will clone repo, render, and apply)

ssh root@deimos "bash /tmp/bootstrap.sh deimos git@github.com:moonpie/abhaile.git main"

# Expected output:

# - Repo cloned to /opt/abhaile

# - Rendered configs to /var/lib/abhaile/rendered/

# - Applied configs to /etc/systemd/network/, /etc/containers/systemd/, etc.

# - GitOps timer enabled and started

```

### Step 5 (Deimos): Verify Deployment

```bash

# Check GitOps timer status

ssh root@deimos "systemctl status abhaile-gitops@deimos.timer"

# Check last GitOps run

ssh root@deimos "journalctl -u abhaile-gitops@deimos.service -n 50"

# Check services are running

ssh root@deimos "systemctl status chrony-b.service coredns-clean.service"
ssh root@deimos "systemctl --user -M abhaile@ status vault-agent.service"

# Check networkd configs applied

ssh root@deimos "networkctl status"

# Check /32 addresses

ssh root@deimos "ip addr show ipvlan-l2 | grep inet"

# Check state files created

ssh root@deimos "ls -la /var/lib/abhaile/state/"

# Verify DNS resolution (coredns-clean)

dig @172.20.20.236 test.abhaile.home.arpa +short
```

### Step 6 (Deimos): Validate Drift Detection

```bash

# Make a small change to a config file in repo

echo "# Test comment" >> config/services/coredns-clean/config/Corefile
git add config/services/coredns-clean/config/Corefile
git commit -m "test: add comment to coredns-clean Corefile"
git push

# Wait for GitOps timer (or trigger manually)

ssh root@deimos "systemctl start abhaile-gitops@deimos.service"

# Check apply log for drift detection

ssh root@deimos "journalctl -u abhaile-gitops-apply@deimos.service -n 50 | grep CHANGED"

# Verify service reloaded (if AUTO_RESTART=1)

ssh root@deimos "journalctl -u coredns-clean.service -n 20 | grep Reloaded"

# Revert test change

git revert HEAD
git push
```

### 3.3 Deimos Validation Coverage

| Validation Task | Coverage | Notes |
| --- | --- | --- |
| **Atomic apply with backup** | ✅ FULL | Backups created in /var/backups/abhaile/ |
| **Rollback mechanism** | ✅ FULL | Manual rollback via timestamped backups |
| **Service health checks** | ⚠️ PARTIAL | systemctl status checks; needs formal health framework |
| **DNS resolution (clean)** | ✅ FULL | coredns-clean forwards to upstream (no filtering) |
| **DNS resolution (internal)** | ❌ N/A | No internal DNS zones on deimos |
| **TLS certificate** | ❌ N/A | No Caddy on deimos |
| **deSEC apply** | ❌ N/A | No deSEC on deimos |
| **Trigger/timer** | ✅ FULL | abhaile-gitops@deimos.timer enabled |
| **Change detection** | ✅ FULL | Drift detection for all 6 categories |
| **State tracking** | ✅ FULL | State files in /var/lib/abhaile/state/ |

**Path Configuration:**

All system paths are centralized in `tools/paths.ini` and loaded via `tools/bash_lib/paths.sh`:

| Section | Key | Default (Production) | Description |
|---------|-----|---------------------|-------------|
| `[repository]` | `repo_root` | `/opt/abhaile` | Git repository location |
| `[runtime]` | `rendered_dir` | `/var/lib/abhaile/rendered` | Rendered configurations |
| `[runtime]` | `state_dir` | `/var/lib/abhaile/state` | Drift tracking state files |
| `[system]` | `backup_dir` | `/var/lib/abhaile/backups` | Timestamped backups |
| `[secrets]` | `gitops_env_file` | `/etc/abhaile/gitops/.env` | GitOps runner config |
| `[secrets]` | `sops_age_key_file` | `/home/abhaile/.config/sops/age/keys.txt` | SOPS decryption key |

**Environment Variables:**
All paths exported as `ABHAILE_*` variables (e.g., `ABHAILE_SYSTEM_BACKUP_DIR=/var/lib/abhaile/backups`).

Deimos validates:

- GitOps workflow (timer → render → apply)
- Drift detection and state tracking
- SOPS decryption
- Vault-Agent token refresh (AppRole-based)
- Rootless Podman quadlets (vault-agent)
- systemd-networkd drop-ins for /32 addresses
- Backup and rollback mechanisms

Deimos does NOT validate:

- Caddy ingress (no caddy-internal or caddy-dmz)
- Authelia SSO (no authelia)
- deSEC DNS apply (no caddy-dmz)
- Internal DNS zones (no coredns-filtered)
- Vault unseal (Vault runs on phobos)

______________________________________________________________________

## 4. Deployment Plan: Phobos

**Host:** phobos
**Services:** ddclient, chrony-a, coredns-filtered, blocky, caddy-internal, caddy-dmz, vault, vault-agent, authelia, omada-controller
**Current State:** Services already deployed manually
**Goal:** Migrate to GitOps control with full validation coverage

### 4.1 Pre-Deployment Validation

**Check current service state:**

```bash

# On phobos, check running services

ssh phobos "systemctl list-units --type=service --state=running | grep -E 'chrony|coredns|blocky|caddy|vault|authelia|omada'"

# Check Podman containers

ssh phobos "podman ps -a"

# Check systemd-networkd configs

ssh phobos "ls -la /etc/systemd/network/"

# Check Vault status

ssh phobos "curl -s http://172.20.20.204:8200/v1/sys/health | jq"

# Check Caddy-internal TLS

curl -k https://test.abhaile.home.arpa/ -I

# Check Caddy-dmz (if public DNS resolves)

curl -I https://omada.abhaile.dedyn.io/
```

Expected output:

- All services running
- Vault unsealed
- Caddy-internal serving HTTPS with internal CA
- Caddy-dmz serving HTTPS with Let's Encrypt (deSEC DNS-01)
- Authelia SSO protecting internal services
- Omada Controller accessible via Caddy ingress

**Validation steps:**

```bash

# Render phobos locally

make render

# Compare rendered configs with live

./tools/apply/apply.sh phobos

# Review drift (expect all NEW since no state files yet)

```

### 4.2 Migration Steps (Phobos)

### Step 1 (Phobos): Create Age Keys

```bash

# On trusted machine, generate Age key

age-keygen -o phobos-keys.txt

# Copy to phobos

scp phobos-keys.txt root@phobos:/tmp/

# On phobos, install Age keys

ssh root@phobos "mkdir -p /root/.config/sops/age && install -m 600 /tmp/phobos-keys.txt /root/.config/sops/age/keys.txt && rm /tmp/phobos-keys.txt"
ssh root@phobos "mkdir -p /home/abhaile/.config/sops/age && install -m 600 /root/.config/sops/age/keys.txt /home/abhaile/.config/sops/age/keys.txt && chown -R abhaile:abhaile /home/abhaile/.config/sops"

# Verify

ssh root@phobos "sops -d /opt/abhaile/secrets/vault-unseal.sops.yaml | head"
```

### Step 2 (Phobos): Create Deploy Key

```bash

# On dev machine, generate deploy key

ssh-keygen -t ed25519 -f gitops_ed25519_phobos -C "gitops@phobos" -N ""

# Add to GitHub as deploy key (read-only)

# Copy to phobos

scp gitops_ed25519_phobos root@phobos:/tmp/

# On phobos, install

ssh root@phobos "mkdir -p /home/abhaile/.ssh && install -m 600 /tmp/gitops_ed25519_phobos /home/abhaile/.ssh/gitops_ed25519 && chown -R abhaile:abhaile /home/abhaile/.ssh && rm /tmp/gitops_ed25519_phobos"
ssh root@phobos "su - abhaile -c 'ssh-keyscan github.com >> ~/.ssh/known_hosts'"

# Verify

ssh root@phobos "su - abhaile -c 'ssh -T git@github.com 2>&1 | grep successfully'"
```

### Step 3 (Phobos): Create SOPS Secrets

```bash

# Create gitops env file

cat > /tmp/gitops-phobos.env <<EOF
REPO_URL=git@github.com:moonpie/abhaile.git
BRANCH=main
WORK_DIR=/opt/abhaile
GIT_SSH_KEY=/home/abhaile/.ssh/gitops_ed25519
DRY_RUN=0
AUTO_RESTART=1
EOF

sops -e /tmp/gitops-phobos.env > secrets/gitops-phobos.sops.env

# Create vault-agent approle

cat > /tmp/vault-agent-approle-phobos.env <<EOF
VAULT_ADDR=http://172.20.20.204:8200
VAULT_ROLE_ID=<role-id>
VAULT_ROLE_SECRET_ID=<secret-id>
EOF

sops -e /tmp/vault-agent-approle-phobos.env > secrets/vault-agent-approle-phobos.sops.env

# Commit

git add secrets/gitops-phobos.sops.env secrets/vault-agent-approle-phobos.sops.env
git commit -m "feat: add gitops and vault-agent secrets for phobos"
git push
```

### Step 4 (Phobos): Run Bootstrap

```bash

# Copy bootstrap script

scp tools/bootstrap/bootstrap.sh root@phobos:/tmp/

# Run bootstrap

ssh root@phobos "bash /tmp/bootstrap.sh phobos git@github.com:moonpie/abhaile.git main"

# Monitor progress

ssh root@phobos "journalctl -u abhaile-gitops@phobos.service -f"
```

### Step 5 (Phobos): Verify Deployment

```bash

# Check GitOps timer

ssh root@phobos "systemctl status abhaile-gitops@phobos.timer"

# Check services

ssh root@phobos "systemctl status vault.service caddy-internal.service caddy-dmz.service authelia-app.service omada-controller-app.service coredns-filtered.service blocky.service chrony-a.service"

# Check Vault unsealed

ssh root@phobos "curl -s http://172.20.20.204:8200/v1/sys/health | jq '.sealed'"

# Check Caddy-internal TLS

curl -k https://test.abhaile.home.arpa/ -I | grep "200 OK"

# Check DNS resolution (filtered)

dig @172.20.20.235 test.abhaile.home.arpa +short

# Check Authelia SSO

curl -k https://authelia.abhaile.home.arpa/ -I | grep "200 OK"

# Check Omada Controller

curl -k https://omada.abhaile.home.arpa/ -I | grep "200 OK"
```

### Step 6 (Phobos): Validate deSEC Apply

```bash

# Check current deSEC records

python3 tools/dns/cli.py --provider desec --zone abhaile.dedyn.io list

# Make a small DNS change in config

# Add test record to config/network.yaml under services.caddy-dmz.dns

vim config/network.yaml

# Add:

# - type: a

#   name: test-deploy

#   rdata: "%%services.caddy-dmz.address | strip_cidr%%"

git add config/network.yaml
git commit -m "test: add test-deploy DNS record"
git push

# Wait for GitOps apply or trigger manually

ssh root@phobos "systemctl start abhaile-gitops@phobos.service"

# Check deSEC plan applied

ssh root@phobos "journalctl -u abhaile-gitops-apply@phobos.service -n 100 | grep -E 'deSEC|DNS'"

# Verify record created

python3 tools/dns/cli.py --provider desec --zone abhaile.dedyn.io list | grep test-deploy

# Revert

git revert HEAD
git push
```

### Step 7 (Phobos): Test Service Restart

```bash

# Modify a service config

echo "# Test comment" >> config/services/caddy-internal/config/Caddyfile
git add config/services/caddy-internal/config/Caddyfile
git commit -m "test: trigger caddy-internal restart"
git push

# Monitor apply

ssh root@phobos "journalctl -u abhaile-gitops-apply@phobos.service -f"

# Verify service restarted (if AUTO_RESTART=1)

ssh root@phobos "systemctl status caddy-internal.service | grep 'Active: active'"

# Check Caddy still serving

curl -k https://test.abhaile.home.arpa/ -I | grep "200 OK"

# Revert

git revert HEAD
git push
```

### 4.3 Phobos Validation Coverage

| Validation Task | Coverage | Notes |
| --- | --- | --- |
| **Atomic apply with backup** | ✅ FULL | Backups in /var/backups/abhaile/ |
| **Rollback mechanism** | ✅ FULL | Timestamped backups; manual rollback |
| **Service health checks** | ⚠️ PARTIAL | systemctl status; needs formal framework |
| **DNS resolution (filtered)** | ✅ FULL | coredns-filtered → blocky → upstream |
| **DNS resolution (internal)** | ✅ FULL | Internal zones (abhaile.home.arpa, svc.abhaile.home.arpa) |
| **TLS certificate (internal CA)** | ✅ FULL | Caddy-internal with `tls internal` |
| **TLS certificate (public ACME)** | ✅ FULL | Caddy-dmz with Let's Encrypt (deSEC DNS-01) |
| **deSEC apply phase** | ✅ FULL | Plan generation + live API apply |
| **Trigger/timer** | ✅ FULL | abhaile-gitops@phobos.timer enabled |
| **Change detection** | ✅ FULL | All 6 categories |
| **State tracking** | ✅ FULL | State files in /var/lib/abhaile/state/ |
| **E2E connectivity** | ⚠️ PARTIAL | Manual curl/dig tests; needs automated suite |

Phobos validates:

- Full GitOps workflow (timer → render → apply)
- All 6 drift categories
- SOPS decryption
- Vault unseal automation
- Vault-Agent token refresh
- Caddy ingress (internal + DMZ)
- Authelia SSO
- deSEC DNS apply and rollback
- TLS certificates (internal CA + Let's Encrypt)
- Internal DNS zones (CoreDNS)
- Ad-blocking DNS (Blocky)
- Omada Controller integration

Phobos does NOT validate:

- Automated health check framework (needs implementation)
- Automated E2E test suite (needs implementation)

______________________________________________________________________

## 5. Outstanding Tasks Plan

### 5.1 Immediate Post-Deployment Tasks

**Task 1: Service Health Checks Framework** (Priority: HIGH)

- **Status:** ⚠️ Needs implementation
- **Scope:** Automated health checks for all services
- **Approach:**
  - Create `tools/health/check_health.sh` script
  - Per-service health check configs in `config/services/<svc>/health.yaml`
  - Check types: HTTP (curl), TCP (nc), systemd status, Podman health
  - Integration with apply.sh post-deployment validation
  - Optional: Prometheus/Blackbox exporter integration

Implementation steps:

1. Create `tools/health/check_health.sh` skeleton
1. Define `health.yaml` schema (check type, endpoint, expected response)
1. Implement check types (http, tcp, systemd, podman)
1. Add to apply.sh post-apply phase
1. Test on deimos and phobos
1. Document in `tools/health/README.md`

**Task 2: E2E Connectivity Tests** (Priority: MEDIUM)

- **Status:** ❌ Needs implementation
- **Scope:** Automated end-to-end connectivity validation
- **Approach:**
  - Create `tests/e2e/test_connectivity.py`
  - Test scenarios:
    - DNS resolution (internal + DMZ zones)
    - HTTP/HTTPS endpoints (Caddy, Authelia, Omada)
    - Service-to-service connectivity (within VLANs)
    - Vault API reachability
    - Blocky ad-blocking (verify blocked domains)
  - Run post-deployment as validation gate

Implementation steps:

1. Create `tests/e2e/test_connectivity.py` with pytest fixtures
1. Define test matrix (host, service, endpoint, expected response)
1. Implement DNS tests (dig/nslookup)
1. Implement HTTP tests (requests library)
1. Implement TCP tests (socket)
1. Add to CI/CD pipeline (optional: nightly only)
1. Document in `tests/e2e/README.md`

**Task 3: DNS Resolution Validation** (Priority: MEDIUM)

- **Status:** ⚠️ Partial (zones rendered, needs automated tests)
- **Scope:** Validate DNS zones after deployment
- **Approach:**
  - Automated validation of CoreDNS zones
  - deSEC record verification
  - PTR record validation

Implementation steps:

1. Create `tools/dns/validate_zones.sh`
1. For each zone in `config/network.yaml`, query DNS server
1. Compare responses with expected records
1. Validate PTR records (reverse DNS)
1. Add to apply.sh post-apply phase
1. Document in `tools/dns/README.md`

**Task 4: TLS Certificate Validation** (Priority: MEDIUM)

- **Status:** ⚠️ Partial (certs issued, needs validation tests)
- **Scope:** Validate TLS certificates post-deployment
- **Approach:**
  - Check Caddy-internal internal CA certs
  - Check Caddy-dmz Let's Encrypt certs
  - Validate cert expiry dates
  - Validate trust chain

Implementation steps:

1. Create `tools/security/validate_certs.sh`
1. Use `openssl s_client` to check cert details
1. Validate expiry (warn if < 30 days)
1. Validate trust chain
1. Add to apply.sh post-apply phase (optional: pre-apply check)
1. Document in `tools/security/README.md`

**Task 5: deSEC Live Apply Validation** (Priority: HIGH)

- **Status:** ⚠️ Partial (plan generation works, needs live apply testing)
- **Scope:** Full deSEC API integration testing
- **Approach:**
  - Test create/update/delete operations
  - Validate rollback on failure
  - Stress test with multiple record changes

Implementation steps:

1. Create `tests/integration/test_desec_live.py`
1. Use deSEC sandbox/test zone (not production)
1. Test create operation (add new record)
1. Test update operation (modify TTL/rdata)
1. Test delete operation (remove record)
1. Test rollback on API failure
1. Test STRICT_DESEC=1 behavior
1. Document in `tools/dns/README.md`

### 5.2 Future Enhancements (Phase 3+)

**Task 6: Automated Rollback on Failure** (Priority: LOW)

- **Status:** ❌ Needs implementation
- **Scope:** Automatic rollback if apply phase fails
- **Approach:**
  - Detect failures in apply.sh
  - Restore from timestamped backup
  - Alert operator via log/notification

**Task 7: Deployment State Tracking** (Priority: LOW)

- **Status:** ⚠️ Partial (state files exist, needs dashboard)
- **Scope:** Dashboard/UI for deployment state
- **Approach:**
  - Parse state files into JSON/YAML
  - Generate deployment report
  - Optional: Web UI for state visualization

**Task 8: Service Migration Validation** (Priority: LOW)

- **Status:** ❌ Needs implementation
- **Scope:** Automated validation of /32 service migrations
- **Approach:**
  - Pre-flight checks (target host has correct VLAN)
  - Post-migration validation (gratuitous ARP sent, DNS updated)
  - Automated smoke tests after migration

______________________________________________________________________

## 6. Validation Checklist Summary

### 6.1 Pre-Deployment Validation

- [ ] Age keys installed on both hosts (root + abhaile user)
- [ ] Deploy keys installed on both hosts
- [ ] SOPS secrets created and encrypted
  - [ ] `secrets/gitops-<host>.sops.env` for both hosts
  - [ ] `secrets/vault-agent-approle-<host>.sops.env` for both hosts
  - [ ] `secrets/caddy-dmz-desec.sops.yaml` (shared)
  - [ ] `secrets/vault-unseal.sops.yaml` (existing)
- [ ] Host configurations present
  - [ ] `config/network.yaml` entries for phobos and deimos
  - [ ] `config/mapping.yaml` entries for phobos and deimos
  - [ ] All service configs in `config/services/` exist
- [ ] Render locally and review output
  - [ ] `make render` succeeds
  - [ ] Review `out/rendered/phobos/` and `out/rendered/deimos/`
  - [ ] No validation errors

### 6.2 Deimos Deployment Validation

- [ ] Bootstrap completes successfully
- [ ] GitOps timer enabled and running
- [ ] All services running (chrony-b, coredns-clean, vault-agent)
- [ ] systemd-networkd configs applied
- [ ] /32 addresses assigned to ipvlan-l2
- [ ] State files created in `/var/lib/abhaile/state/`
- [ ] Drift detection working (manual config change test)
- [ ] Backup mechanism tested (automatic backups before apply)
- [ ] Manual rollback tested (restore from `/var/lib/abhaile/backups/` directory)
- [x] **Automated rollback on failure** - Implemented via commit-based restoration in `gitops_runner.sh`

### 6.3 Phobos Deployment Validation

- [ ] Bootstrap completes successfully
- [ ] GitOps timer enabled and running
- [ ] All services running (ddclient, chrony-a, coredns-filtered, blocky, caddy-internal, caddy-dmz, vault, vault-agent, authelia, omada-controller)
- [ ] Vault unsealed automatically
- [ ] Caddy-internal serving HTTPS with internal CA
- [ ] Caddy-dmz serving HTTPS with Let's Encrypt
- [ ] Authelia SSO protecting internal services
- [ ] Omada Controller accessible via ingress
- [ ] DNS zones resolving (internal + DMZ)
- [ ] deSEC records applied successfully
- [ ] State files created
- [ ] Drift detection working
- [ ] Backup/rollback tested

### 6.4 Post-Deployment Tasks

- [x] **Automated rollback on failure** - Implemented via commit-based restoration in `gitops_runner.sh`; reverts to last successful commit and re-applies on render/apply failures
- [ ] Service health checks framework implemented
- [ ] E2E connectivity tests implemented
- [ ] DNS resolution validation automated
- [ ] TLS certificate validation automated
- [ ] deSEC live apply fully tested
- [ ] Documentation updated (QUICKSTART.md, OPERATIONS.md)
- [ ] Runbook created for common issues

______________________________________________________________________

## 7. Risk Assessment and Mitigation

### 7.1 Risks

| Risk | Impact | Probability | Mitigation |
| --- | --- | --- | --- |
| **Bootstrap fails due to missing Age key** | HIGH | MEDIUM | Pre-flight check in bootstrap.sh aborts early; operator installs manually |
| **SOPS decryption fails** | HIGH | LOW | Verify SOPS key before bootstrap; test decryption locally |
| **GitOps runner cannot clone repo** | HIGH | LOW | Deploy key verification in bootstrap; SSH test before clone |
| **Service restart breaks Vault** | HIGH | LOW | Vault unseal automation; backup before apply |
| **deSEC API rate limit** | MEDIUM | LOW | Plan validation before apply; batch operations |
| **Network drift during apply** | MEDIUM | LOW | Atomic apply with backups; rollback mechanism |
| **Caddy TLS cert renewal failure** | MEDIUM | LOW | Manual renewal via `caddy reload`; monitoring alerts |

### 7.2 Rollback Procedures

### Automated Rollback Process

Rollback is **fully automated** and implemented in `tools/gitops/gitops_runner.sh`:

1. **Detect failure:** Apply returns non-zero exit code
1. **Check previous state:** Read last successful commit from `/var/lib/abhaile/state/gitops.state`
1. **Checkout previous commit:** `git checkout <LAST_SUCCESSFUL_COMMIT>`
1. **Retry apply:** Re-run render and apply with restored configs
1. **Update state:** Write rollback status to `gitops.state` with `status: rolled_back` and `rollback_from: <failed_commit>`
1. **Success:** System restored to last known-good configuration, ready for next GitOps cycle

**Failure handling:** If rollback checkout or re-apply fails, exit with error and require manual intervention.

### Manual Rollback (Fallback)

If automated rollback is unavailable, manual restoration from timestamped backups:

```bash

# Stop GitOps timer

systemctl stop abhaile-gitops@<host>.timer

# Restore from latest backup (manual process)
# Backups stored in /var/lib/abhaile/backups/<category>-<timestamp>/

LATEST_BACKUP=$(ls -t /var/backups/abhaile/networkd-* | head -1)
cp -r $LATEST_BACKUP/* /etc/systemd/network/

# Reload systemd-networkd

systemctl daemon-reload
systemctl restart systemd-networkd

# Restore services

LATEST_SERVICES=$(ls -t /var/backups/abhaile/services-* | head -1)
cp -r $LATEST_SERVICES/* /etc/containers/systemd/

# Reload Podman

systemctl daemon-reload
podman system service --time=0
```

**Selective Rollback (Per-Service):**

```bash

# Restore single service config

LATEST_BACKUP=$(ls -t /var/backups/abhaile/services-* | head -1)
cp $LATEST_BACKUP/<service>/<file> /srv/<service>/<file>

# Restart service

systemctl restart <service>.service
```

______________________________________________________________________

## 8. Next Steps

1. **Review this plan** with stakeholders
1. **Execute deimos deployment** following Section 3
1. **Validate deimos** per Section 6.2
1. **Execute phobos deployment** following Section 4
1. **Validate phobos** per Section 6.3
1. **Implement post-deployment tasks** from Section 5.1
1. **Update TODO.md** with completed tasks
1. **Update documentation** (QUICKSTART.md, OPERATIONS.md)
1. **Create runbook** for common operations

______________________________________________________________________

## Appendix A: Quick Reference Commands

### Check GitOps Status

```bash

# Timer status

systemctl status abhaile-gitops@<host>.timer

# Last run

journalctl -u abhaile-gitops@<host>.service -n 50

# State files

ls -la /var/lib/abhaile/state/

# Backups

ls -lt /var/lib/abhaile/backups/

# View latest backup for specific category
ls -lt /var/lib/abhaile/backups/networkd-*/
ls -lt /var/lib/abhaile/backups/services-*/

# Manual restore example (operator decision required)
cp -a /var/lib/abhaile/backups/networkd-<timestamp>/* /etc/systemd/network/
systemctl restart systemd-networkd
```

### Manual GitOps Trigger

```bash

# Render only (unprivileged)

systemctl start abhaile-gitops@<host>.service

# Apply (privileged)

systemctl start abhaile-gitops-apply@<host>.service
```

### Manual Apply (Dev)

```bash

# Dry-run

./tools/apply/apply.sh <host>

# Apply

sudo ./tools/apply/apply.sh --apply <host>

# Skip render

sudo ./tools/apply/apply.sh --skip-render --apply <host>
```

### SOPS Operations

```bash

# Decrypt

sops -d secrets/gitops-<host>.sops.env

# Edit in place

sops secrets/gitops-<host>.sops.env

# Re-encrypt

sops -e /tmp/plaintext.env > secrets/gitops-<host>.sops.env
```

### Vault Operations

```bash

# Check status

curl -s http://172.20.20.204:8200/v1/sys/health | jq

# Unseal manually

/opt/abhaile/tools/vault/vault_unseal.sh

# Refresh AppRole token

/opt/abhaile/tools/vault/vault_token_refresh.sh <host>
```

______________________________________________________________________

### End of Deployment Validation Plan
