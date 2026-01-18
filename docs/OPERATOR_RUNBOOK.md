# Operator Runbook (Quick Path)

Fast jump-off for on-call and routine ops. Keep this terse; follow links for detail.

## Command Sanity Table

| Command | Script Location | Args/Flags |
|---------|----------------|------------|
| Render configs | `tools/render/cli.py` | `[hostname...]`, `--validate-only` |
| Apply changes | `tools/apply/apply.sh` | `[hostname]`, `--apply`, `--verbose` |
| Generate inventory | `tools/inventory/cli.py` | (no args) |
| DNS sync | `tools/dns/cli.py` | `sync`, `diff`, `--dry-run` |
| Vault unseal | `tools/vault/vault_unseal.sh` | (no args) |
| Vault token refresh | `tools/vault/vault_token_refresh.sh` | (no args) |
| Bootstrap host | `tools/bootstrap/bootstrap.sh` | `<host>` `[repo_url]` `[branch]` |
| GitOps runner | `tools/gitops/gitops_runner.sh` | (called by systemd timer) |

## Core Loops (GitOps every 5 min)

- Check timer status: `systemctl status abhaile-gitops@<host>.timer`
- Dry-run drift: `./tools/apply/apply.sh <host>`
- Apply changes: `sudo ./tools/apply/apply.sh --apply <host>`
- Render-only validation: `python3 tools/render/cli.py --validate-only`

## Drift & Apply

- Drift categories and state files: see [tools/apply/README.md](../tools/apply/README.md)
- Drift meaning: NEW/CHANGED/REMOVED; run with `--apply` to sync
- Backups: `out/state/*.backup` (dev) or `/var/lib/abhaile/state/*.backup` (prod)

## Rollback / Recovery

- Automatic rollback behavior and detection: [OPERATIONS.md](OPERATIONS.md#automatic-rollback)
- Manual rollback if automation fails: stop timer → checkout known-good commit → `apply --apply` → start timer
- Restore from backups: see recovery steps in OPERATIONS.md

## Bootstrap / New Host

- One-liner: curl installer in [tools/bootstrap/README.md](../tools/bootstrap/README.md)
- Prereqs: Age key (root+abhaile), deploy key, required SOPS files, host entries in mapping/network

## Secrets

- SOPS and Age key handling: [secrets/README.md](../secrets/README.md)
- Vault usage and rotation guidance: [CREDENTIALS.md](CREDENTIALS.md)

## Where Things Live

All paths defined in `tools/paths.ini`:

- Render output: `/var/lib/abhaile/rendered` (prod), `out/rendered/` (dev)
- State files: `/var/lib/abhaile/state` (prod), `out/state/` (dev)
- Software artifacts: `/var/lib/abhaile/software` (prod), `out/software/` (dev)
- Systemd units: `/etc/systemd/system`; quadlets rootful: `/etc/containers/systemd`, rootless: `~/.config/containers/systemd`
- Secrets: `/etc/abhaile/` (gitops env, vault approle, etc.)
- Repo: `/opt/abhaile` (prod clone)

## Quick Checks

- Network: `ip addr` and systemd-networkd status
- Containers: `podman ps`
- DNS: `dig @172.20.20.235 <name>` (filtered) / `...236` (clean)
- Vault: `vault status`

## Escalation / Gaps

- If timer keeps failing: check secrets (Age key, deploy key), then render logs
- If rollback fails: follow manual recovery, then file an ADR update if behavior diverges
- Open TODOs for missing runbook steps as you find them
