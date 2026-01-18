# Deploy Tools

Scripts for rendering and applying host configuration.

- `apply.sh`: orchestrates render, validate, drift-check, stage, and apply. Uses the `lib/` helpers alongside it.
- `lib/`: shared Bash helpers for logging, env detection, validation, drift, staging, apply, runtime actions, and deSEC sync.

Usage (from repo root):

```bash
./tools/apply/apply.sh phobos          # dry-run to out/
sudo ./tools/apply/apply.sh --apply phobos  # apply to host
```

## Validation & Error Handling

Validation occurs in three phases:

### Pre-Apply Validation (Dry-Run by Default)

**When:** Before any changes to live system
**Behavior:** Dry-run is default; no changes applied unless `--apply` flag provided

**Checks:**

1. **Syntax validation:** Validate `.network`, `.netdev`, and `.conf` files

   - FAIL if malformed INI structure or missing sections detected
   - Exit code: 1 (blocks apply)

1. **Drift detection:** Compare rendered output vs. live configs

   - WARN if drift detected (manual review recommended)
   - FAIL if staging/backup preparation fails
   - Exit code: 1 (blocks apply)

1. **File existence:** Verify all referenced files and drop-ins exist

   - FAIL if missing files detected
   - Exit code: 1 (blocks apply)

### Apply-Time Validation

**When:** During atomic file replacement (with `--apply` flag)
**Behavior:** Atomic staging with automatic rollback on failure

**Checks:**

1. **Backup creation:** Ensure backup directory created successfully

   - FAIL AND ABORT if backup fails
   - Exit code: 1 (no partial state)

1. **Atomic staging:** Stage all changes to temporary directory before live replacement

   - FAIL AND ABORT if staging fails
   - Exit code: 1 (no partial state)

1. **Service reload:** Reload `systemd-networkd`, Podman, and other systemd services

   - FAIL AND ROLLBACK if reload fails
   - Restore from backup and exit code: 1
   - No `|| true` on systemctl calls; failures are fatal and logged

1. **State lock:** Serialize apply runs with a flock-based lock (30s timeout)

   - Prevents concurrent timer + manual apply from corrupting state
   - Fails fast if lock cannot be acquired; rerun after active apply completes

### Post-Apply Validation

**When:** After changes applied to live system
**Behavior:** Verify system remains functional

**Checks:**

1. **Connectivity check:** Verify network connectivity after networkd reload

   - Gratuitous ARP for all service `/32` addresses
   - FAIL AND ROLLBACK if connectivity lost
   - Restore from backup and exit code: 1

1. **State update:** Update drift tracking state files

   - WARN if state update fails (apply succeeded but drift tracking incomplete)

## Concurrency & Locking

- State updates are protected by a lock file (flock) with a 30-second timeout.
- GitOps timer and manual applies should not run concurrently; a blocked apply exits with an error if lock acquisition times out.
- Rollback path verifies the target commit exists (`git cat-file -e <sha>`) before checkout.

## Error Recovery & Rollback

### Automated Rollback (GitOps)

When render/apply fails during GitOps automation:

1. `gitops_runner.sh` reads last successful commit from `/var/lib/abhaile/state/gitops.state`
1. Checks out previous commit: `git checkout <LAST_SUCCESSFUL_COMMIT>`
1. Re-runs render and apply to restore to last known-good state
1. Writes rollback state with `status: rolled_back` to gitops.state

### Manual Rollback (Fallback)

Operator can manually restore from timestamped backups:

```bash
# List available backups
ls -lt /var/lib/abhaile/backups/

# Restore specific category
rsync -av /var/lib/abhaile/backups/networkd-<timestamp>/ /etc/systemd/network/
systemctl restart systemd-networkd

# State files remain unchanged (previous state preserved)
```

### Exit Codes

- `0`: Success (all validation passed, changes applied or dry-run completed)
- `1`: Critical error (validation failed, apply blocked or rolled back)
- `2`: Warnings present (drift detected, manual review recommended)

## Integration with Validation Strategy

Apply validation assumes config files are:

- Schema-valid (pre-commit verified)
- Semantically correct (render verified)
- Syntax-correct for systemd (apply verifies)
- Safe to deploy (drift detection + rollback capability)

See [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md) for render-time error handling.

## Drift Detection & State Tracking

The apply workflow detects drift across 6 categories:

1. **Network Config** (`networkd.state`): systemd-networkd `.network` and `.netdev` files
1. **Service Files** (`services.state`): rendered service configs with target-path mapping
1. **Static Systemd Units** (`systemd.state`): hand-written `/etc/systemd/system` units
1. **Resolved Config** (`resolved.state`): `/etc/resolv.conf` and `/etc/systemd/resolved.conf`
1. **Software Artifacts** (`software.state`): software packages and aux files
1. **Users Config** (`users.state`): user and sudoers configuration

### State File Format

State files (in `out/state/`) are plain-text hash maps for drift detection:

**Simple Format** (networkd, systemd, resolved, software, users):

```text
<sha256_hash>  <relative_file_path>
```

Example (`software.state`):

```text
a3b4c5d6e7f8...  phobos/backup-script.sh
f1e2d3c4b5a6...  phobos/cron-cleanup.conf
```

**Services Format** (services.state with target mapping):

```text
<sha256_hash>  <rendered_path>  <target_path>
```

Example (`services.state`):

```text
9d8e7f6g5h4i...  phobos/services/caddy-internal/Caddyfile  /opt/caddy-internal/Caddyfile
1b2c3d4e5f6g...  phobos/services/vault-agent/config.hcl  /home/vault-agent/.config/vault-agent/config.hcl
```

**State File Validation**:

Before drift detection, existing state files are validated for format correctness:

- **Simple format**: must be `<64-char-hex-hash>  <path>`
- **Services format**: must be `<64-char-hex-hash>  <render_path>  <absolute_target_path>`
- **deSEC plan** (`desec_plan.json`): validated as JSON with required fields (`create`, `update`, `delete`, `desired_records`)

If validation fails, drift detection aborts with an error. This prevents corruption from propagating through the apply workflow.

### Drift Detection Mechanics

Drift is detected by comparing current hashes in state files with newly computed hashes during the dry-run phase:

- **NEW**: Hash exists in `.state.new` but not in `.state` → file not yet deployed
- **CHANGED**: Hash differs between `.state.new` and `.state` → file was modified
- **REMOVED**: Hash exists in `.state` but not in `.state.new` → file was deleted or no longer needed

During `--apply`, stale files (marked as REMOVED) are deleted from the target directory before new files are staged.

### Example Drift Output

Typical dry-run drift warnings:

```text
WARN: networkd drift detected for phobos (4 new, 2 changed, 1 removed)
WARN: service drift detected for phobos (3 new, 1 changed, 2 removed)
WARN: static systemd drift detected for phobos (1 new)
WARN: software drift detected for phobos (2 new, 1 removed)
WARN: users drift detected for phobos (1 changed)
INFO: dry-run; drift warnings are informational. Re-run with --apply to sync.
```

### Removal Logic

When `--apply` is used:

- Files marked as REMOVED are backed up to `<target>.<timestamp>.backup` before deletion
- Service files use target-path resolution (rootful vs rootless Podman detection) before removal
- Software and users artifacts are removed from their respective target directories
- State files (`*.state`) are updated post-apply to reflect current state

### Viewing State & History

```bash
# View current state for a category
cat out/state/networkd.state
cat out/state/services.state

# Compare with last run
diff out/state/networkd.state.backup out/state/networkd.state

# Dry-run to see latest drift without applying
./tools/apply/apply.sh phobos

# Apply changes (interactive backup available if issues occur)
sudo ./tools/apply/apply.sh --apply phobos
```
