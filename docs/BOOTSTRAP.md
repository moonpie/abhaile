# Bootstrap — Host Enrollment

Enrolls a fresh Debian 13 (trixie) host into Abhaile GitOps management.

## Pre-Bootstrap (Operator Actions)

Complete these steps on the target host before running bootstrap:

### 1. Install Debian 13

Set hostname to `phobos` or `deimos`. Ensure the host is defined in
`config/mapping.yaml` and `config/network.yaml` (commit to repo first).

### 2. Create the abhaile user

```bash
groupadd -g 1001 abhaile
useradd -u 1001 -g abhaile -m -s /bin/bash -d /home/abhaile abhaile
```

Bootstrap is idempotent and will skip creation if the user exists.

### 3. Place age decryption identity

```bash
install -d -m 0700 -o abhaile -g abhaile /home/abhaile/.config/sops/age
# Copy the host's age private key:
install -m 0600 -o abhaile -g abhaile <key-source> /home/abhaile/.config/sops/age/keys.txt
```

### 4. Place git deploy key

```bash
install -d -m 0700 -o abhaile -g abhaile /home/abhaile/.ssh
install -m 0600 -o abhaile -g abhaile <deploy-key> /home/abhaile/.ssh/gitops_ed25519
# Add repo host to known_hosts:
ssh-keyscan github.com >> /home/abhaile/.ssh/known_hosts
chown abhaile:abhaile /home/abhaile/.ssh/known_hosts
```

Add the corresponding public key as a read-only deploy key on the repository.

### 5. Ensure sealed artifacts exist

Verify `config/bootstrap/sealed/<hostname>/vault-bootstrap.sops.yaml` exists in the
repo. Create with: `scripts/sops-bootstrap create <hostname> vault-bootstrap`

### 6. Ensure Vault is reachable

- **phobos (first host):** Vault must be running on this host. Bootstrap will unseal
  it using keys from the sealed artifact.
- **deimos:** Vault on phobos must be running and network-accessible.

### 7. Prepare one-time bootstrap token

Generate a short-lived AppRole `secret_id` from Vault:

```bash
vault write -f auth/approle/role/bootstrap/secret-id
```

Keep the `secret_id` value ready for the bootstrap prompt (or export as
`BOOTSTRAP_TOKEN`).

## Execution

### Interactive (recommended for first run)

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/abhaile/main/scripts/bootstrap.sh \
  | sudo bash -s -- <hostname>
```

Or from an already-cloned repo:

```bash
sudo /opt/abhaile/scripts/bootstrap.sh <hostname>
```

The script will prompt for the bootstrap token interactively.

### Automated

```bash
export BOOTSTRAP_TOKEN="s.xxxxxxxx"
sudo -E /opt/abhaile/scripts/bootstrap.sh <hostname>
```

Or via file descriptor:

```bash
sudo bash -c 'BOOTSTRAP_TOKEN_FD=3 /opt/abhaile/scripts/bootstrap.sh <hostname> 3< <(vault write -f -field=secret_id auth/approle/role/bootstrap/secret-id)'
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BOOTSTRAP_TOKEN` | — | AppRole secret_id (one-time) |
| `BOOTSTRAP_TOKEN_FD` | — | File descriptor to read token from |
| `VAULT_ADDR` | `https://vault.svc.abhaile.home.arpa:8200` | Vault API address |
| `ABHAILE_REPO_URL` | `git@github.com:moonpie/abhaile.git` | Repository URL |
| `ABHAILE_BRANCH` | `main` | Branch to checkout |
| `BOOTSTRAP_READY_TIMEOUT` | `60` | Seconds to wait for Vault Agent sentinel |

## Post-Bootstrap Verification

```bash
# GitOps timer active
systemctl status abhaile-runner.timer

# Vault Agent running (rootless, under abhaile user)
sudo -u abhaile systemctl --user status vault-agent

# Secrets ready
test -f /srv/vault/agent/out/.ready && echo "OK" || echo "NOT READY"

# Check services
systemctl list-units --type=service --state=running | grep -E "caddy|blocky|coredns|authelia"
```

## Troubleshooting

### "Must run as root"

Bootstrap requires root. Use `sudo bash -s -- <hostname>`.

### "Deploy key missing"

Place the SSH deploy key at `/home/abhaile/.ssh/gitops_ed25519` before running
bootstrap. The `abhaile` user must own the file with mode 0600.

### "Age decryption key not found"

The age private key must exist at `/home/abhaile/.config/sops/age/keys.txt`.

### "Sealed artifact decryption failed"

Wrong age key for this host, or the sealed artifact was encrypted for a different
recipient. Re-encrypt with `scripts/sops-bootstrap edit <host> vault-bootstrap`.

### "Vault AppRole login failed"

- Vault is not running or not reachable at `$VAULT_ADDR`
- The one-time token (secret_id) has already been consumed — generate a new one
- The role_id in the sealed artifact doesn't match the Vault AppRole configuration

### "Vault Agent ready sentinel not found"

Non-fatal. The runner will converge on the next scheduled run. Check:

```bash
sudo -u abhaile journalctl --user -u vault-agent -n 50
sudo -u abhaile podman logs vault-agent
```

### "sops checksum mismatch"

The downloaded sops binary doesn't match the pinned checksum. Possible causes:
network MITM, GitHub CDN issue, or the checksum constant in `bootstrap.sh` needs
updating after a sops version bump.

### Re-running bootstrap

Bootstrap is idempotent. Each stage checks preconditions and skips completed work.
Re-running on a partially enrolled host resumes from the last incomplete stage.

Note: if the one-time token was consumed during a previous failed run, you must
generate a new `secret_id` before re-running.

### Logs

All bootstrap output is logged to `/var/log/abhaile/bootstrap.log`.
No secret material appears in logs.
