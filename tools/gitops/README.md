# GitOps Runner Tools

Utilities for the host-level GitOps automation with privilege boundary pattern (see [ADR 0010](../../docs/ADR/0010-gitops-privilege-boundary.md)).

- `gitops_runner.sh`: sync-render-apply loop executed by the `abhaile-gitops@.service` timer
- `gitops_runner.env.example`: example runner environment (repo URL, branch, work dir, dry-run flags)

Systemd units reference scripts directly from the repo clone at `/opt/abhaile/tools/gitops/`. No installation to `/usr/local/sbin/` is needed.

## Two-Phase Architecture

GitOps automation uses a **privilege boundary pattern** to minimize root exposure:

### Phase 1: Render (unprivileged, every 5 minutes)

**Timer:** `abhaile-gitops@<host>.timer`
**Service:** `abhaile-gitops@<host>.service` (runs as `User=abhaile`)
**Executes:** `gitops_runner.sh`

**Operations:**

1. Pull Git repo into `/opt/abhaile`
1. Decrypt secrets with Age key (`/home/abhaile/.config/sops/age/keys.txt`)
1. Render configs via `tools/render/cli.py`
1. Validate syntax and detect drift (read-only)
1. Write rendered output to `/var/lib/abhaile/rendered/`
1. Signal success by writing `.apply_ready` flag

**Failure modes:** All abort safely; no changes applied or written

### Phase 2: Apply (privileged, triggered by flag)

**Path unit:** `abhaile-gitops-apply@<host>.path` (watches for `.apply_ready`)
**Service:** `abhaile-gitops-apply@<host>.service` (runs as `User=root`)
**Executes:** `tools/apply/apply.sh --skip-render --apply`

**Operations:**

1. Read rendered configs from Phase 1
1. Apply changes atomically to `/etc/systemd/network/`, `/etc/containers/`, etc.
1. Reload systemd services
1. Update drift state files
1. Clean up `.apply_ready` flag on success

**Failure modes:** If apply fails, `.apply_ready` persists; path unit will retry; operator must investigate

## Systemd Unit Flow

```text
┌─────────────────────────────────────────────────────┐
│ abhaile-gitops@<host>.timer                         │
│ (every 5 minutes)                                   │
└──────────────────┬────────────────────────────────┘
                   │
                   ├─→ [ExecStartPre] rm -f .apply_ready
                   │
                   ├─→ [ExecStart] gitops_runner.sh
                   │    └─→ pull, decrypt, render, validate
                   │
                   └─→ [ExecStartPost] touch .apply_ready
                      (only if ExecStart succeeded, exit 0)
                             │
┌────────────────────────────┴────────────────────────┐
│ abhaile-gitops-apply@<host>.path                    │
│ (watches for /var/lib/abhaile/rendered/.apply_ready)│
└──────────────────┬────────────────────────────────┘
                   │
                   ├─→ [ExecStart] apply.sh --skip-render --apply
                   │    └─→ apply rendered, reload systemd, update state
                   │
                   └─→ [ExecStartPost] rm -f .apply_ready
                      (cleanup, only if apply succeeded)
```

## Key File Locations

**Runtime:**

- Repo clone: `/opt/abhaile/` (owned by `abhaile:abhaile`)
- Rendered output: `/var/lib/abhaile/rendered/` (written by abhaile, applied by root)
- State tracking: `/var/lib/abhaile/state/` (written by both phases)

**Secrets:**

- SSH deploy key: `/home/abhaile/.ssh/gitops_ed25519` (mode 600)
- Age private key: `/home/abhaile/.config/sops/age/keys.txt` (mode 600)
- GitOps env file: `/etc/abhaile/gitops/.env` (decrypted from SOPS, sourced by timer)

## Operational Procedures

### Check Phase 1 Status

```bash
sudo systemctl status abhaile-gitops@phobos.service
sudo journalctl -u abhaile-gitops@phobos.service -n 50 -f
```

### Check Phase 2 Status

```bash
sudo systemctl status abhaile-gitops-apply@phobos.service
sudo journalctl -u abhaile-gitops-apply@phobos.service -n 50
```

### Manual Render Trigger

```bash
sudo systemctl start abhaile-gitops@phobos.service
```

### Manual Apply Trigger

```bash
sudo systemctl start abhaile-gitops-apply@phobos.service
```

### Inspect Flag State

```bash
ls -la /var/lib/abhaile/rendered/.apply_ready
# exists = ready for apply
# missing = apply completed or render failed
```

### Debug Failed Apply

If `.apply_ready` exists but doesn't get cleared:

```bash
# 1. Check apply logs
sudo journalctl -u abhaile-gitops-apply@phobos.service | tail -50

# 2. Manually inspect rendered configs
cat /var/lib/abhaile/rendered/phobos/systemd-networkd/*.network

# 3. Dry-run apply manually
sudo ./tools/apply/apply.sh phobos

# 4. Fix underlying issue, then trigger apply again
sudo systemctl start abhaile-gitops-apply@phobos.service

# 5. If needed, clean up flag manually
sudo rm -f /var/lib/abhaile/rendered/.apply_ready
```

## Monitoring & Alerting

**Healthy cycle:**

- `.apply_ready` created and destroyed within seconds
- Both phase services succeed
- Systemd journal shows "render complete" → "apply started" → "apply complete"

**Alerts to set up:**

- `.apply_ready` exists for >1 minute (apply stuck)
- Phase 1 service fails (render error)
- Phase 2 service fails (apply error)
- No successful runs in >15 minutes (both phases stuck)
