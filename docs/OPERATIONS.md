# Operations

Deployment workflows, drift management, service migration, automatic rollback.

For routine maintenance, backups, and troubleshooting, see [MAINTENANCE.md](MAINTENANCE.md); for task-first reference, see [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md).

## Deployment Workflow

### 1. Configuration Changes

```bash
# Edit service or network config
vim config/services/caddy-internal/service.yaml
vim config/network.yaml

# Validate before rendering
python3 tools/render/cli.py --validate-only

# Or run full pre-commit checks
pre-commit run --all-files
```

### 2. Render All Hosts

Rendering always processes all hosts from `config/mapping.yaml` (provides full context for Caddy, DNS, deSEC):

```bash
# Render all hosts
make render

# Or directly with Python
python3 tools/render/cli.py

# Outputs:
# - out/rendered/{phobos,deimos}/systemd-networkd/
# - out/rendered/{phobos,deimos}/services/
# - out/state/*.state (drift tracking)
```

### 3. Dry-Run Apply

```bash
# Shows drift without making changes
./tools/apply/apply.sh phobos

# Review output:
# - NEW: files not yet on host
# - CHANGED: files modified locally
# - REMOVED: files no longer in mapping
```

### 4. Apply Changes

```bash
# Apply to host (requires root)
sudo ./tools/apply/apply.sh --apply phobos

# Apply workflow:
# - Validates configs with systemd-analyze
# - Stages files atomically with backups
# - Reloads systemd-networkd and Podman
# - Updates state files in `/var/lib/abhaile/state/`
# - Sends gratuitous ARP for /32 addresses
```

#### Apply Safety Notes

- Apply is serialized with a state lock (flock) to prevent concurrent timer/manual runs; lock wait timeout 30s.
- systemctl reload/enable/start failures are fatal (no `|| true`); check journal if apply aborts.
- Rollback verifies the previous commit exists before checkout; failed verification stops the run for operator action.

### 5. Verify

```bash
# Check network interfaces
ip addr show

# Verify services
podman ps
systemctl status caddy-internal.service

# Confirm no drift
./tools/apply/apply.sh phobos | grep "drift: none"
```

## Drift Detection

### Understanding Drift Output

```text
WARN: networkd drift detected for phobos (4 new, 2 changed, 1 removed)
WARN: service drift detected for phobos (3 new, 1 changed, 2 removed)
INFO: dry-run; re-run with --apply to sync
```

**Drift states:**

- **NEW:** File in rendered output but not yet on host
- **CHANGED:** File on host differs from rendered version (modified locally)
- **REMOVED:** File in state but no longer in rendered output (decommissioned)

### State Files

Located at `out/state/` (dev) or `/var/lib/abhaile/state/` (production):

| File | Tracks |
| --- | --- |
| `networkd.state` | systemd-networkd `.network` and `.netdev` files |
| `services.state` | Service configs with target-path mapping (rootful/rootless) |
| `systemd.state` | Static `/etc/systemd/system` units |
| `resolved.state` | `/etc/resolv.conf` and `/etc/systemd/resolved.conf` |
| `software.state` | Software packages and auxiliary files |
| `users.state` | User and sudoers configuration |

Format: `<sha256_hash>  <path>` (simple) or `<sha256>  <render_path>  <target_path>` (services)

### Weekly Drift Review

```bash
# 1. Run dry-run to check for drift
./tools/apply/apply.sh phobos

# 2. If drift is expected (pending changes), review rendered output
cat out/rendered/phobos/systemd-networkd/*.network

# 3. If correct, apply
sudo ./tools/apply/apply.sh --apply phobos

# 4. Verify state updated
diff out/state/networkd.state.backup out/state/networkd.state
```

### Common Drift Scenarios

| Scenario | Drift Status | Action |
| --- | --- | --- |
| Normal GitOps: config changed, awaiting apply | NEW/CHANGED | Run `--apply` to sync |
| Local admin tweak | CHANGED | Revert local changes or update template in git |
| Service decommissioned | REMOVED | Run `--apply` to clean up files |
| Fresh bootstrap | NEW (all files) | Expected; run `--apply` after bootstrap |
| No pending changes | (all zeros) | Good! System in sync |

## Service Migration

Move a service `/32` between hosts:

### Pre-Checks

1. Confirm service ownership in `config/mapping.yaml`
1. Verify target host has required VLAN interface in `config/network.yaml`
1. Confirm service has `/32` address in `config/network.yaml`

### Migration Steps

```bash
# 1. Update mapping
vim config/mapping.yaml    # Move service from source to target host

# 2. Render all hosts
python3 tools/render/cli.py

# 3. Dry-run both hosts
./tools/apply/apply.sh phobos
./tools/apply/apply.sh deimos

# 4. Apply on source host first (removes /32)
sudo ./tools/apply/apply.sh --apply phobos

# 5. Apply on target host (adds /32)
sudo ./tools/apply/apply.sh --apply deimos

# Gratuitous ARP sent automatically by apply.sh
```

### Validation

```bash
# Verify /32 on target
ip addr show | grep 172.20.20

# Verify DNS resolves correctly
dig @172.20.20.235 myservice.abhaile.home.arpa

# Check service health
curl -k https://myservice.abhaile.home.arpa
```

### Rollback

```bash
# Revert mapping.yaml
git revert HEAD

# Re-render and apply both hosts
python3 tools/render/cli.py
sudo ./tools/apply/apply.sh --apply phobos
sudo ./tools/apply/apply.sh --apply deimos
```

## Automatic Rollback

When GitOps render or apply fails, the system automatically reverts to the last known-good configuration without operator intervention.

### How It Works

1. **Detects failure:** apply.sh exits with non-zero code
1. **Reads previous commit:** Loads from `/var/lib/abhaile/state/gitops.state`
1. **Checks out previous commit:** `git checkout <LAST_SUCCESSFUL_COMMIT>`
1. **Retries apply:** Re-runs render and apply with previous configuration
1. **Records rollback:** Writes `status: rolled_back` to gitops.state

### Detection and Verification

**Check if rollback occurred:**

```bash
# View rollback status
jq '.status, .rollback_from' /var/lib/abhaile/state/gitops.state

# Check rollback logs
journalctl -u abhaile-gitops@<host>.service | grep -i rollback

# Verify system is on previous commit
git -C /opt/abhaile log --oneline -1
```

**Expected log messages:**

- `Attempting automatic rollback to last successful commit`
- `Rolled back to commit <HASH>`
- `Rollback successful; system restored to last known-good state`

### State File Format

Location: `/var/lib/abhaile/state/gitops.state`

**Normal success:**

```json
{
  "host": "phobos",
  "last_run": "2024-01-13T15:30:45+00:00",
  "commit": "abc1234",
  "status": "success"
}
```

**After rollback:**

```json
{
  "host": "phobos",
  "last_run": "2024-01-13T15:35:22+00:00",
  "commit": "abc1234",
  "status": "rolled_back",
  "rollback_from": "xyz9876",
  "rollback_reason": "apply_failure"
}
```

### Manual Recovery

If automatic rollback fails, manual intervention is required:

#### Option 1: Restore from Git

```bash
# Stop GitOps timer
systemctl stop abhaile-gitops@<host>.timer

# List commit history
git -C /opt/abhaile log --oneline -10

# Checkout known-good commit
git -C /opt/abhaile checkout <GOOD_COMMIT_HASH>

# Manually run apply
sudo /opt/abhaile/tools/apply/apply.sh --apply <host>

# Restart timer
systemctl start abhaile-gitops@<host>.timer
```

#### Option 2: Restore from Backups

```bash
# Stop GitOps timer
systemctl stop abhaile-gitops@<host>.timer

# List available backups (timestamped by category)
ls -lt /var/lib/abhaile/backups/

# Restore specific category
rsync -av /var/lib/abhaile/backups/networkd-<timestamp>/ /etc/systemd/network/
systemctl restart systemd-networkd

# Reset git repo if corrupted
git -C /opt/abhaile reset --hard origin/main

# Restart timer
systemctl start abhaile-gitops@<host>.timer
```

### Rollback Troubleshooting

| Problem | Check | Fix |
| --- | --- | --- |
| Rollback didn't happen | `journalctl -u abhaile-gitops@<host> \| grep rollback` | Check for "No previous commit available" - requires bootstrap |
| Rollback checkout failed | `git -C /opt/abhaile status` | Run `git -C /opt/abhaile reset --hard origin/main` |
| State file missing | `ls /var/lib/abhaile/state/` | Run first apply manually: `sudo /opt/abhaile/tools/apply/apply.sh --apply <host>` |
| State file corrupted | `jq . /var/lib/abhaile/state/gitops.state` | Delete and re-apply: `rm /var/lib/abhaile/state/gitops.state && sudo ...` |

## See Also

- [MAINTENANCE.md](MAINTENANCE.md) – Routine maintenance, backups, security, troubleshooting
- [QUICKSTART.md](QUICKSTART.md) – Get started quickly
- [DEVELOPMENT.md](DEVELOPMENT.md) – Rendering logic and testing
- [NETWORK.md](NETWORK.md) – Network topology and ACLs
- [CREDENTIALS.md](CREDENTIALS.md) – Secrets management
