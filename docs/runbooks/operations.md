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

### Render, Diff, Apply (Core 3 Commands)

```bash
# Render (on target host, from /opt/abhaile)
abhaile-render --host $(hostname -s) --output /var/lib/abhaile

# Dry-run apply (safe, read-only)
sudo abhaile-apply --output /var/lib/abhaile --dry-run

# Live apply
sudo abhaile-apply --output /var/lib/abhaile
```

<details>
<summary>Full Command Reference</summary>

```bash
# Render all hosts (workstation only, requires --output)
abhaile-render --all --output ./out

# Check drift (what would change)
abhaile-diff --output /var/lib/abhaile

# Dry-run with validation commands (systemd-analyze, visudo -c, named-checkzone)
sudo abhaile-apply --output /var/lib/abhaile --dry-run --dry-run-validations

# Apply with safe removals (only files unchanged on disk)
sudo abhaile-apply --output /var/lib/abhaile --prune

# Force-prune drifted removals (DESTRUCTIVE — requires --allow-destructive)
sudo abhaile-apply --output /var/lib/abhaile --force-prune --allow-destructive

# JSON output for scripting
abhaile-diff --output /var/lib/abhaile --json
sudo abhaile-apply --output /var/lib/abhaile --dry-run --json
```

</details>

### Runner Status

```bash
# Timer status
systemctl status abhaile-runner.timer
systemctl list-timers abhaile-runner.timer

# Last run result (format: "<exit_code> <timestamp> <commit_sha>")
cat /var/lib/abhaile/runner/last-run-status

# Last successful commit
cat /var/lib/abhaile/runner/last-successful-commit

# Runner logs (last run)
journalctl -u abhaile-runner.service --no-pager -n 50

# Trigger manual run
sudo systemctl start abhaile-runner.service
```

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
```

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
# On target host, as root:
cd /opt/abhaile
git fetch origin main && git checkout main && git pull

# Full re-render
abhaile-render --host $(hostname -s) --output /var/lib/abhaile

# Force apply (use --prune for safe removals, --force-prune --allow-destructive if desperate)
sudo abhaile-apply --output /var/lib/abhaile --prune

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
cd /opt/abhaile && git pull
abhaile-render --host $(hostname -s) --output /var/lib/abhaile
sudo abhaile-apply --output /var/lib/abhaile
```

### DNS Serial Workflow

When zone records change in `config/network.yaml`:

1. `abhaile-render --host $(hostname -s) --output /tmp/dns-check` — it will fail with serial mismatch and print the new `content_hash`.
1. In `config/network.yaml`, update the matching zone's `serial`:
   - `date`: today as `YYYYMMDD` (e.g., `20260607`)
   - `counter`: `00` (or increment if same day)
   - `content_hash`: paste the hash from the error message
1. `abhaile-render --host $(hostname -s) --output /tmp/dns-check` — should succeed.
1. Commit and push.
1. Verify propagation after apply:

```bash
   dig @172.20.20.235 svc.abhaile.home.arpa SOA +short   # serial should match
   dig @172.20.20.236 svc.abhaile.home.arpa SOA +short   # both resolvers
```

### Image Updates

Container images are pinned in quadlet `.image` files. To update:

1. Edit the image tag in `config/services/<service>/quadlets/image.image`.
1. Commit, push, wait for runner (or manual render+apply).
1. Verify: `podman images | grep <service>`

### State and History Cleanup

```bash
# Applied manifests (last 10 kept automatically)
ls /var/lib/abhaile/state/history/

# Podman image pruning (manual, not automated)
sudo podman image prune -a
sudo -u abhaile podman image prune -a
```

### NTP Verification

```bash
chronyc tracking        # chrony-a on phobos, chrony-b on deimos
chronyc sources -v
```

## Break-Glass: ER605 Console

If network is completely unreachable, the ER605 management interface is on VLAN 99 (172.20.99.1). Physical access: ER605 port 5 is the management fallback port (untagged VLAN 99).

````
