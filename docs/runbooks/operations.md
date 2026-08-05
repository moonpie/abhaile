# Operations Runbook

Quick-reference for daily operations and incident response. See `docs/INVENTORY.md` for IPs and service names.

## Vault Sealed (Most Common 3am Event)

````bash
# Check seal status (phobos only)
curl -s http://172.20.20.204:8200/v1/sys/seal-status | jq .sealed

# If sealed → unseal (phobos only, manual):
/usr/local/bin/vault operator unseal    # paste unseal key from bootstrap

# After unseal → restart vault-agent on BOTH hosts:
# phobos:
machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service
# deimos:
machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service

# Verify secrets rendered (both hosts):
test -f /srv/vault/agent/out/.ready && echo "OK" || echo "NOT READY"
```

## Quick Reference

### Workstation Validation

```bash
# Render all hosts only.
make render

# Render one host only.
make render-host HOST=phobos

# Render all hosts, then dry-run apply phobos and deimos.
make validate

# Render one host, then dry-run apply that host.
make validate-host HOST=phobos

# Host-scoped render plus dry-run apply.
make apply HOST=phobos
```

Use `ALLOW_HOST_MISMATCH=1` only for workstation dry-run validation from a non-target host. It
adds only `--allow-host-mismatch` to dry-run apply commands and prints a dry-run-only override
notice.

### Render, Diff, Apply (Core 3 Commands)

```bash
# Render (on target host, from /opt/abhaile)
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/abhaile-render --host $(hostname -s) --output /var/lib/abhaile

# Dry-run apply (safe, read-only)
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile --dry-run

# Live apply
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile

# Local post-apply health gate
sudo /opt/abhaile/.venv/bin/abhaile-health --output /var/lib/abhaile

# Cluster consistency audit (non-local checks such as cross-node DNS SOA consistency)
sudo /opt/abhaile/.venv/bin/abhaile-health --output /var/lib/abhaile --cluster
```

<details>
<summary>Full Command Reference</summary>

```bash
# Render all hosts (workstation only, requires --output)
abhaile-render --all --output ./out

# Check drift (what would change)
sudo /opt/abhaile/.venv/bin/abhaile-diff --output /var/lib/abhaile

# Dry-run with validation commands (systemd-analyze, visudo -c, named-checkzone)
sudo /opt/abhaile/.venv/bin/abhaile-apply \
  --output /var/lib/abhaile \
  --dry-run \
  --dry-run-validations

# Apply with safe removals (only files unchanged on disk)
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile --prune

# Force-prune drifted removals (DESTRUCTIVE — requires --allow-destructive)
sudo /opt/abhaile/.venv/bin/abhaile-apply \
  --output /var/lib/abhaile \
  --force-prune \
  --allow-destructive

# JSON output for scripting
sudo /opt/abhaile/.venv/bin/abhaile-diff --output /var/lib/abhaile --json
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile --dry-run --json
```

</details>

### Runner Status

```bash
# Timer status
systemctl status abhaile-runner.timer
systemctl list-timers abhaile-runner.timer

# Last run result (format: "<exit_code> <timestamp> <commit_sha>")
sudo cat /var/lib/abhaile/runner/last-run-status

# Last successful commit
sudo cat /var/lib/abhaile/runner/last-successful-commit

# Diagnostic summary from the last completed run
sudo cat /var/lib/abhaile/runner/last-run-summary

# Active phase if a run is currently in progress
sudo test -f /var/lib/abhaile/runner/current-run && sudo cat /var/lib/abhaile/runner/current-run

# Runner logs (last run)
journalctl -u abhaile-runner.service --no-pager -n 50

# Trigger manual run
sudo systemctl start abhaile-runner.service

# Optional: enable report-only cluster audit after the runner's local health gate
sudo systemctl edit abhaile-runner.service
# Add:
# [Service]
# Environment=ABHAILE_CLUSTER_HEALTH=1
```

If the runner reports a dirty worktree, inspect staged and unstaged state before
repairing it:

```bash
sudo -H -u abhaile env HOME=/home/abhaile git -C /opt/abhaile status --short
sudo -H -u abhaile env HOME=/home/abhaile git -C /opt/abhaile diff --name-status
sudo -H -u abhaile env HOME=/home/abhaile git -C /opt/abhaile diff --cached --name-status
sudo -H -u abhaile env HOME=/home/abhaile git -C /opt/abhaile reflog -n 5 --date=iso
```

Only restore paths after confirming the change is not intentional local
operator work.

## Service Operations

### Rootful Containers

> **Pod naming:** Pod-based services (authelia) use `<service>-app.service` as the systemd unit.
> Container names: `systemd-<service>-app-<container>` (e.g., `systemd-authelia-app-authelia`).
> Simple container services (blocky, vault, caddy-\*) use `<service>.service`.

```bash
# Status / logs / restart
systemctl status <service>.service              # simple containers
systemctl status <service>-app.service          # pod services (authelia)
journalctl -u <service>.service --no-pager -n 100
systemctl restart <service>.service

# Enter container
podman exec -it systemd-<service> /bin/sh                         # simple
podman exec -it systemd-<service>-app-<container> /bin/sh         # pod

# Container logs
podman logs systemd-<service>                                     # simple
podman logs systemd-<service>-app-<container>                     # pod
```

**Host mapping:**

- phobos: vault, blocky, caddy-internal, caddy-dmz, authelia (pod), omada-controller
- deimos: (subset — check mapping.yaml for current list)

### Rootless Services (vault-agent — both hosts)

```bash
# Status (from root — must set XDG_RUNTIME_DIR or use machinectl)
machinectl shell abhaile@ /bin/systemctl --user status vault-agent.service
machinectl shell abhaile@ /bin/journalctl --user -u vault-agent.service --no-pager -n 50

# Restart
machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service

# Alternative (if machinectl unavailable):
sudo -u abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) systemctl --user status vault-agent.service
```

### Host-Daemon Services (chrony, coredns-filtered, coredns-clean)

```bash
systemctl status <service>.service
journalctl -u <service>.service --no-pager -n 50
systemctl restart <service>.service
```

- chrony-a → `chrony.service` (phobos only)
- chrony-b → `chrony.service` (deimos only)
- coredns-filtered → phobos, coredns-clean → phobos (check mapping.yaml)

### Secrets Readiness

```bash
# Check sentinel (both hosts)
test -f /srv/vault/agent/out/.ready && echo "OK" || echo "NOT READY"

# Check secrets-ready gate
systemctl status abhaile-secrets-ready.service

# List rendered secrets
ls -la /srv/vault/agent/out/
```

### Vault Admin Operations

Use the human `userpass` admin account for routine Vault operations such as KV
updates, policy writes, and AppRole inspection. Do not use the Vault Agent sink
token for operator work, and reserve the initial root token for break-glass
recovery only.

```bash
export VAULT_ADDR=http://172.20.20.204:8200
vault login -method=userpass username=admin
vault token lookup
```

If the command is not attached to a TTY, run it from an interactive terminal.
Do not paste Vault tokens, passwords, or SecretIDs into chat or shell history.

To confirm Vault Agent is working and that its token came from AppRole:

```bash
# Host-local rendered output and readiness sentinel
sudo test -f /srv/vault/agent/out/.ready && echo "vault-agent ready"
sudo ls -l /srv/vault/agent/out

# User service health and recent auth/template logs
sudo -u abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) \
  systemctl --user status vault-agent.service --no-pager -l
sudo -u abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) \
  journalctl --user -u vault-agent.service --no-pager -n 80 -l

# Configured auth method
sudo grep -A8 'method "approle"' /srv/vault/agent/config.hcl

# Sink token lookup without printing the token itself
sudo VAULT_ADDR="$VAULT_ADDR" \
  VAULT_TOKEN="$(sudo cat /srv/vault/agent/run/vault-agent-token)" \
  vault token lookup -format=json \
  | jq '{display_name: .data.display_name, policies: .data.policies, renewable: .data.renewable, ttl: .data.ttl, period: .data.period, meta: .data.meta}'
```

Expected result: the service is active, `.ready` exists, the config uses the
`approle` auth method, and the token lookup shows the `vault-agent` policy.

To update runtime KV values, write only the new fields into a temporary file
with restrictive permissions and patch the existing secret:

```bash
umask 077
tmp="$(mktemp)"
vi "$tmp"
vault kv patch secret/abhaile/omada @"$tmp"
rm -f "$tmp"
```

The admin policy includes Vault's `patch` capability so `vault kv patch` can use
HTTP PATCH without falling back to older update semantics.

For the Omada external MongoDB deployment, the temporary file should contain
these fields:

```json
{
  "mongodb_root_username": "<root-admin-username>",
  "mongodb_root_password": "<root-admin-password>",
  "mongodb_username": "<omada-application-username>",
  "mongodb_password": "<omada-application-password>"
}
```

Vault Agent can already read `secret/data/abhaile/omada` through the
`vault-agent` policy. If a future service needs a new Vault path, update and
apply the policy as an admin:

```bash
vault policy fmt policies/vault-agent.hcl
vault policy write vault-agent policies/vault-agent.hcl
vault policy read vault-agent
```

Then restart Vault Agent on each affected host or wait for the next normal
template render interval:

```bash
sudo -u abhaile XDG_RUNTIME_DIR=/run/user/$(id -u abhaile) \
  systemctl --user restart vault-agent.service
```

### Vault-Agent Copy Units

Services that copy Vault Agent output into bind-mounted runtime paths should
be checked at both the copy unit and container level.

```bash
systemctl status authelia-config.service authelia-redis-conf.service --no-pager -l
systemctl status authelia-app-authelia.service authelia-app-redis.service --no-pager -l
podman volume inspect systemd-authelia-app-authelia-config
```

If a container cannot see a file that exists on the host, compare the volume
`Options.device` path with the rendered `.volume` unit. A stale Podman named
volume can keep pointing at an old bind source. Stop the dependent container,
remove the stale volume only after confirming it is a bind volume, then start
the generated `*-volume.service` and dependent container again.

## Diagnostics

### DNS

```bash
# Internal resolution (from any host on VLAN 20)
dig @172.20.20.235 vault.svc.abhaile.home.arpa    # coredns-filtered (phobos)
dig @172.20.20.236 vault.svc.abhaile.home.arpa    # coredns-clean (phobos)

# Reverse lookup
dig @172.20.20.235 -x 172.20.20.204

# Check zone serial (verify after zone change)
dig @172.20.20.235 svc.abhaile.home.arpa SOA +short
dig @172.20.20.236 svc.abhaile.home.arpa SOA +short   # both resolvers should match

# CoreDNS logs (phobos)
journalctl -u coredns-filtered.service --no-pager -n 30
journalctl -u coredns-clean.service --no-pager -n 30

# Zone reload watcher
journalctl -u coredns-zones.service -n 5

# Blocky logs (phobos)
podman logs systemd-blocky --tail 30
```

### Networking

```bash
# Check ipvlan-l2 interface exists
ip link show ipvlan-l2 || echo "INTERFACE GONE — restart networkd"

# Check /32 service addresses
ip -4 addr show dev ipvlan-l2 | grep "inet "

# Check drop-ins (service /32 addresses)
ls /etc/systemd/network/21-ipvlan-l2.network.d/

# Full networkd state
networkctl status ipvlan-l2
networkctl list
journalctl -u systemd-networkd.service --no-pager -n 20

# Ping service by /32 address
ping -c 1 172.20.20.200   # caddy-internal
ping -c 1 172.20.20.204   # vault

# Cross-host check
ping -c1 172.20.20.11     # deimos from phobos
ping -c1 172.20.20.10     # phobos from deimos
```

#### Network Interface Recovery

If ipvlan-l2 disappears (all /32 services go dark simultaneously):

```bash
ip link show ipvlan-l2 || echo "INTERFACE GONE"
systemctl restart systemd-networkd
# Wait ~5s, then verify:
ip -4 addr show dev ipvlan-l2 | grep "inet "
# All /32 addresses should reappear
```

### Vault and Vault-Agent

```bash
# Vault seal status (phobos only — vault only runs on phobos)
curl -s http://172.20.20.204:8200/v1/sys/seal-status | jq .sealed

# Vault-agent logs (both hosts)
machinectl shell abhaile@ /bin/journalctl --user -u vault-agent.service --no-pager -n 50

# Check vault-agent token freshness
ls -la /srv/vault/agent/run/vault-agent-token
stat /srv/vault/agent/out/.ready

# Vault-agent template render errors
machinectl shell abhaile@ /bin/journalctl --user -u vault-agent.service --grep "error" --no-pager
```

### Caddy

```bash
# Validate config (in-container, phobos only)
podman exec systemd-caddy-internal /usr/bin/caddy validate -c /etc/caddy/Caddyfile
podman exec systemd-caddy-dmz /usr/bin/caddy validate -c /etc/caddy/Caddyfile

# Reload without restart
podman exec systemd-caddy-internal /usr/bin/caddy reload -c /etc/caddy/Caddyfile

# Check TLS certificate expiry (from host, no container needed)
openssl s_client -connect 172.20.20.200:443 -servername vault.abhaile.home.arpa </dev/null 2>/dev/null | openssl x509 -noout -dates
```

### Quadlets

```bash
# List quadlet-generated units (rootful)
ls /run/systemd/generator/*.service 2>/dev/null

# List quadlet-generated units (rootless, abhaile user)
ls /run/user/$(id -u abhaile)/systemd/generator/*.service 2>/dev/null

# List pod-related units
systemctl list-units '*-app*' --no-pager

# Regenerate quadlet units (dry-run check, before daemon-reload)
/usr/libexec/podman/quadlet --dryrun

# Check why a container won't start
systemctl status <unit>.service
podman logs systemd-<container-name>

# Confirm a registry image is local without contacting the registry
podman image exists ghcr.io/0xerr0r/blocky:v0.27.0
machinectl shell abhaile@ /usr/bin/podman image exists docker.io/hashicorp/vault:1.21.4
```

Registry-backed containers are rendered as direct `Image=<registry-ref>` entries in
`.container` Quadlets with `Pull=missing`. Normal boot uses the existing local image and does not
depend on external DNS or registry availability unless the desired image is absent locally.
Separate `.image` Quadlets are not expected for registry-backed services.

Managed `.build` Quadlets also use `Pull=missing`, but that only controls missing base images.
Builds are GitOps transactions keyed by declared build inputs and are not expected to run during
ordinary boot recovery. A failed managed build or post-build action should block deployment before
consumer services are restarted.

## Decision Tree: Service Unreachable

```bash
Service unreachable?
├── ALL services on one host down simultaneously?
│   ├── YES → Network interface failure:
│   │        ip link show ipvlan-l2 || systemctl restart systemd-networkd
│   │        Verify: ip -4 addr show dev ipvlan-l2 | grep "inet "
│   └── NO → Continue below
├── Only external (DMZ) access broken, internal works?
│   ├── YES → Check caddy-dmz and VLAN 100:
│   │        systemctl status caddy-dmz.service
│   │        ip link show ipvlan-l2.100
│   │        networkctl status ipvlan-l2.100
│   └── NO → Continue below
├── Can you ping the /32 address?
│   ├── NO → Check ipvlan-l2 interface: networkctl status ipvlan-l2
│   │        Check networkd drop-in exists: ls /etc/systemd/network/21-ipvlan-l2.network.d/
│   │        Restart networkd: systemctl restart systemd-networkd
│   └── YES → Continue below
├── Is the container running?
│   ├── NO → systemctl status <service>.service (or <service>-app.service for pods)
│   │        journalctl -u <service>.service -n 50
│   │        Is it crash-looping? → systemctl show <unit> -p NRestarts
│   │        Is it a secrets dependency? → Check: test -f /srv/vault/agent/out/.ready
│   └── YES → Continue below
├── Is the port listening?
│   ├── NO → podman exec systemd-<service> ss -tlnp
│   │        Check container logs for bind errors
│   └── YES → Continue below
├── Is Caddy routing to it?
│   ├── Check Caddy logs: podman logs systemd-caddy-internal --tail 20
│   │   Check Caddy config: podman exec systemd-caddy-internal cat /etc/caddy/Caddyfile
│   └── Check DNS resolves the FQDN: dig <service>.abhaile.home.arpa
└── Is Authelia blocking?
    └── Check Authelia logs: podman logs systemd-authelia-app-authelia --tail 20
```

## Nuclear Option: Full Reconvergence

When confused at 3am and need to blow it all away:

```bash
# On target host:
cd /opt/abhaile
sudo -H -u abhaile env HOME=/home/abhaile git fetch origin main
sudo -H -u abhaile env HOME=/home/abhaile git checkout main
sudo -H -u abhaile env HOME=/home/abhaile git pull --ff-only origin main

# Full re-render
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/abhaile-render --host $(hostname -s) --output /var/lib/abhaile

# Force apply (use --prune for safe removals, --force-prune --allow-destructive if desperate)
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile --prune

# Reload systemd
systemctl daemon-reload

# Restart all quadlet services (example for phobos):
systemctl restart caddy-internal.service caddy-dmz.service blocky.service
systemctl restart authelia-app.service
machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service

# Wait for secrets:
while [ ! -f /srv/vault/agent/out/.ready ]; do sleep 2; done
echo "Secrets ready, services should converge"
```

**Dependency order for full restart:**

1. `systemd-networkd` (addresses)
1. Vault container (phobos; if sealed → unseal)
1. vault-agent (both hosts)
1. Wait for `/srv/vault/agent/out/.ready`
1. All other services (they depend on secrets-ready)

## Routine Maintenance

### Force Re-render and Apply

```bash
# On target host
cd /opt/abhaile
sudo -H -u abhaile env HOME=/home/abhaile git pull --ff-only origin main
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/abhaile-render --host $(hostname -s) --output /var/lib/abhaile
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile
```

### DNS Serial Workflow

When zone records change in `config/network.yaml`:

1. `sudo -H -u abhaile env HOME=/home/abhaile /opt/abhaile/.venv/bin/abhaile-render --host $(hostname -s) --output /tmp/dns-check` — it will fail with serial mismatch and print the new `content_hash`.
1. In `config/network.yaml`, update the matching zone's `serial`:
   - `date`: today as `YYYYMMDD` (e.g., `20260607`)
   - `counter`: `00` (or increment if same day)
   - `content_hash`: paste the hash from the error message
1. `sudo -H -u abhaile env HOME=/home/abhaile /opt/abhaile/.venv/bin/abhaile-render --host $(hostname -s) --output /tmp/dns-check` — should succeed.
1. Commit and push.
1. Verify propagation after apply:

```bash
   dig @172.20.20.235 svc.abhaile.home.arpa SOA +short   # serial should match
   dig @172.20.20.236 svc.abhaile.home.arpa SOA +short   # both resolvers
```

### Image Updates

Container images are pinned in `service.yaml`, not separate Quadlet `.image` files. To update:

1. Edit `podman.image` for simple/rootless containers, or the per-container `image` field for pod
   members.
1. Prefer immutable version tags or digests. Keep `pull_policy: missing` unless there is a
   deliberate reason to change boot behavior.
1. Commit, push, wait for runner (or manual render+apply).
1. Verify: `podman image exists <image-ref>` in the same rootful/rootless context as the service.

During live apply, `abhaile-apply` pre-pulls a changed image before staging the new `.container`
or restarting the service. If the pull fails, apply reports `deployment blocked during image
acquisition`, leaves the live service and applied state unchanged, and does not remove migration
`.image` artifacts.

### Registry Image Quadlet Migration

Migrate one host at a time. Keep that host's runner timer stopped until migration, health, and a
second convergence dry-run have succeeded. Do Deimos first, then Phobos.

```bash
# On deimos first, then repeat on phobos after deimos is healthy.
sudo systemctl stop abhaile-runner.timer
sudo systemctl stop abhaile-runner.service

cd /opt/abhaile
sudo -H -u abhaile env HOME=/home/abhaile git pull --ff-only origin main
sudo -H -u abhaile env HOME=/home/abhaile \
  /opt/abhaile/.venv/bin/abhaile-render --host $(hostname -s) --output /var/lib/abhaile

# Review planned writes, safe removals, and image acquisitions.
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile --dry-run --json

# Live migration. Safe, manifest-matching .image removals are applied automatically.
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile

# Health and convergence checks.
sudo /opt/abhaile/.venv/bin/abhaile-health --output /var/lib/abhaile
sudo /opt/abhaile/.venv/bin/abhaile-apply --output /var/lib/abhaile --dry-run

# Confirm obsolete image units and files are gone.
systemctl --failed
test ! -e /etc/containers/systemd/blocky-b.image
test ! -e /etc/containers/systemd/blocky-a.image
test ! -e /home/abhaile/.config/containers/systemd/vault-agent.image
systemctl list-units 'blocky*-image.service' 'vault-agent-image.service' --all --no-pager

# Re-enable only after health and the second dry-run are clean.
sudo systemctl start abhaile-runner.timer
```

For the outage recovery case, if the desired images already exist locally, Blocky and Vault Agent
should restart even while external registry DNS is unavailable. Failed registry access should only
affect a service whose desired image is genuinely absent locally. Do not restart generated
`*-image.service` units; after migration, they should not be loaded or failed.

### State and History Cleanup

```bash
# Applied manifests (last 10 kept automatically)
sudo ls /var/lib/abhaile/state/history/

# Podman image pruning (manual, not automated)
sudo podman image prune -a
sudo -u abhaile podman image prune -a
```

Do not run image pruning as part of a deployment transaction. Old images are rollback material
until an operator verifies that no container, applied manifest, or other service still references
them.

### NTP Verification

```bash
chronyc tracking        # chrony-a on phobos, chrony-b on deimos
chronyc sources -v
```

## Break-Glass: ER605 Console

If network is completely unreachable, the ER605 management interface is on VLAN 99 (172.20.99.1). Physical access: ER605 port 5 is the management fallback port (untagged VLAN 99).

````
