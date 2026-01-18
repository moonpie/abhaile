# Bootstrap Script Guide

The `tools/bootstrap/bootstrap.sh` is a minimal curl-bash installer that enrolls a new Debian host into Abhaile GitOps. It handles credentials verification, repo cloning, and runs `apply.sh` to deploy everything.

**Philosophy:** Bootstrap does the bare minimum to get the repo on disk with working credentials. All deployment logic (systemd units, services, configs) is handled by `apply.sh`, which is also used by the GitOps runner for updates.

## Quick Start

**On a new Debian host with root access (via sudo):**

```bash
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/tools/bootstrap/bootstrap.sh | sudo bash -s -- phobos
```

**Prerequisites (must exist before running):**

- Age private key installed for both `root` and `abhaile` users
- Git deploy key installed for the `abhaile` user
- SOPS files present: `secrets/gitops-<host>.sops.env`, `secrets/vault-agent-approle-<host>.sops.env`, `secrets/caddy-dmz-desec.sops.yaml`, `secrets/vault-unseal.sops.yaml`
- Host entries present in `config/network.yaml` and `config/mapping.yaml`

**Arguments:**

```text
bootstrap.sh <host> [repo_url] [branch]

  <host>       – Host name (must exist in config/network.yaml and config/mapping.yaml)
  [repo_url]   – Git repository URL (default: git@github.com:moonpie/abhaile.git)
  [branch]     – Git branch to track (default: main)
```

**Example:**

```bash
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/tools/bootstrap/bootstrap.sh | \
  sudo bash -s -- phobos git@github.com:moonpie/abhaile.git main
```

## What the Script Does

### 1. Preflight Checks

- Verifies running as root
- Checks for required commands (git, python3, podman, age, systemctl)
- Confirms Debian OS
- Tests network connectivity to GitHub

### 2. Install Base Packages

- Updates package lists
- Installs dependencies: git, python3, podman, age, sops, curl, jq, systemd tools
- Enables systemd-networkd and systemd-resolved

### 3. SOPS Age Key Setup

- Verifies Age private key exists at `/root/.config/sops/age/keys.txt`
- **Aborts if key not found** (you must install manually beforehand)
- See [secrets/README.md](../../secrets/README.md) for Age key generation and rotation

### 4. Repository Clone

- Clones the Abhaile repo from REPO_URL at BRANCH
- Saves to `/opt/abhaile`
- Updates if already present

### 5. Python Environment

- Creates `.venv` in the work directory
- Installs `requirements.txt` dependencies
- Used for rendering and validation

### 6. Configuration Validation

- Confirms `<host>` is defined in `config/network.yaml`
- Confirms `<host>` is mapped in `config/mapping.yaml`
- Aborts if either check fails

### 7. Render Configurations

- Runs `python3 tools/render/cli.py <host>`
- Verifies `out/rendered/<host>/` contains systemd-networkd and services
- Stops if render fails

### 8. Deploy User and Keys Setup

- Ensures `abhaile` user exists
- **Aborts if** `/home/abhaile/.config/sops/age/keys.txt` not found
- **Aborts if** `/home/abhaile/.ssh/gitops_ed25519` not found (deploy key)
- Adds GitHub to `/home/abhaile/.ssh/known_hosts`

### 9. Apply Configuration

- Runs `tools/apply/apply.sh --apply <host>`
- This handles:
  - Installing all systemd units (gitops timer, vault-unseal, vault-token-refresh, etc.)
  - Applying networkd configs
  - Applying service quadlets
  - Enabling and starting services
  - Setting up GitOps automation

### 10. Summary

- Prints status and next steps

## Prerequisites (Manual Setup Before Running)

The bootstrap script **cannot** provide these; you must set up beforehand:

1. Age Private Key (for `abhaile`)

   - Generate on a trusted machine: `age-keygen -o keys.txt`
   - Install on the target host: `sudo install -m 600 keys.txt /home/abhaile/.config/sops/age/keys.txt && sudo chown abhaile:abhaile /home/abhaile/.config/sops/age/keys.txt`
   - See [secrets/README.md](../../secrets/README.md)

1. Git Deploy Key (Read-Only, for `abhaile`)

   - Generate SSH key for read-only repo access
   - Add to GitHub as a deploy key (or user key with restricted scope)
   - Install on target: `sudo install -m 600 gitops_ed25519 /home/abhaile/.ssh/gitops_ed25519 && sudo chown abhaile:abhaile /home/abhaile/.ssh/gitops_ed25519`

1. SOPS-Encrypted Secrets

   - `secrets/gitops-<host>.sops.env` – GitOps runner env (repo URL, branch, work dir)
   - `secrets/vault-agent-approle-<host>.sops.env` – Vault AppRole credentials
   - `secrets/caddy-dmz-desec.sops.yaml` – deSEC API token
   - `secrets/vault-unseal.sops.yaml` – Vault unseal keys (existing)
   - See [secrets/README.md](../../secrets/README.md) for templates and creation workflow

1. Host Configuration

   - Entry in `config/network.yaml` defining interfaces, VLANs, addressing
   - Entry in `config/mapping.yaml` mapping the host to services
   - Service templates in `config/services/` (already present)

## Usage Workflow

### Local Testing (Development)

Run from the repo root (not via curl):

```bash
sudo bash tools/bootstrap/bootstrap.sh phobos git@github.com:moonpie/abhaile.git main
```

### Remote Deployment (Production)

On the new host:

```bash
# Install prerequisites (Age key, deploy key)
# Then run:
curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/tools/bootstrap/bootstrap.sh | \
  sudo bash -s -- phobos

# Monitor first GitOps run:
sudo journalctl -u abhaile-gitops@phobos.timer -f

# When ready, apply changes:
sudo /opt/abhaile/tools/apply/apply.sh --apply phobos
```

## Idempotency

The script is **idempotent** – you can run it multiple times safely:

- Already-cloned repos are updated (git fetch/checkout)
- Existing systemd units are overwritten (idempotent install)
- SOPS decryption skips if plaintext is fresh

## Error Handling

The script uses `set -euo pipefail` to exit on errors:

- Missing required commands → exit 1
- Failed git operations → exit 1
- Missing host definition → exit 1
- Render failures → exit 1
- Missing Age key or deploy key → exit 1

Warnings (non-fatal):

- SOPS decryption failure → uses template, logs warning
- AppRole env not found → logs note, continues
- Vault-unseal.sops.yaml missing → logs error but continues

## Output & Logging

The script logs all actions with `[bootstrap]` prefix:

```text
[bootstrap] Preflight Checks
[bootstrap] Checking required commands...
[bootstrap] === Installing Base Packages ===
...
```

**View past runs:**

```bash
sudo journalctl -S "1 hour ago" | grep bootstrap
```

**Full console output during execution:**

```bash
curl -fsSL ... | sudo bash -s -- phobos 2>&1 | tee /tmp/bootstrap.log
```

## Troubleshooting

| Issue | Solution |
| -------------------------------- | ----------------------------------------------------------------- |
| "Age key not found" | Manually install: `sudo install -m 600 age-key /root/.config/sops/age/keys.txt` |
| "Deploy key not found" | Install SSH key: `sudo install -m 600 gitops_ed25519 /home/abhaile/.ssh/gitops_ed25519 && sudo chown abhaile:abhaile /home/abhaile/.ssh/gitops_ed25519` |
| "Host not found in config" | Add entry to `config/network.yaml` and `config/mapping.yaml`; push to repo |
| "Git clone failed" | Check SSH key permissions, GitHub SSH access, network routing |
| "Orchestrator failed" | Run manually to see errors: `python3 tools/render/cli.py <host>` |
| GitOps timer doesn't run | Check: `systemctl status abhaile-gitops@phobos.timer` and journalctl |

## Next Steps After Bootstrap

1. **Decrypt secrets (if not done by script):**

   ```bash
   cd /opt/abhaile
   sops -d secrets/gitops-phobos.sops.env > /etc/abhaile/gitops/.env
   sudo chmod 600 /etc/abhaile/gitops/.env
   ```

1. **Monitor GitOps timer:**

   ```bash
   sudo journalctl -u abhaile-gitops@phobos.timer -f
   ```

1. **Apply configuration (dry-run first):**

   ```bash
   cd /opt/abhaile
   sudo ./tools/apply/apply.sh phobos       # Dry-run
   sudo ./tools/apply/apply.sh --apply phobos  # Apply
   ```

1. **Verify deployment:**

   - Check IP addresses: `ip addr`
   - List containers: `podman ps`
   - Verify Vault: `vault status`
   - Check systemd: `systemctl status abhaile-*`

## See Also

- [docs/QUICKSTART.md](../../docs/QUICKSTART.md) – Detailed manual bootstrap checklist
- [docs/OPERATIONS.md](../../docs/OPERATIONS.md) – Post-deployment validation
- [secrets/README.md](../../secrets/README.md) – How to create SOPS files
- [secrets/README.md](../../secrets/README.md) – Age key management and SOPS keys
