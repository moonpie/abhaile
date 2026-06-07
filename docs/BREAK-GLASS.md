# Break-Glass Procedures

When normal operations fail. Use direct IPs. No DNS, no Vault, no runner required.

> **Offline access:** Bookmark this file on your phone (`raw.githubusercontent.com` URL).
> Keep a printed copy in the rack cabinet. Last verified: 2026-06-07.

## Quick Triage (Start Here)

| Symptom | Go to |
|---------|-------|
| All services on one host unreachable | [§3 Network Lockout](#3-network-lockout-recovery) |
| Only DMZ/external access broken | [§3 Network Lockout](#3-network-lockout-recovery) (check VLAN 100) |
| Vault sealed (services can't get secrets) | [§1 Vault Sealed](#1-vault-sealed-recovery) |
| Secrets not rendering (`.ready` missing) | [§1 Vault Sealed](#1-vault-sealed-recovery) then [§6 Vault-Agent Token Expiry](#6-vault-agent-token-expiry) |
| DNS not resolving | [§2 DNS Total Failure](#2-dns-total-failure) |
| Runner applying bad config repeatedly | [§4 Runner Crash Loop](#4-runner-crash-loop) |
| Disk full / OOM / container storage | [§7 Resource Exhaustion](#7-resource-exhaustion) |
| Everything down, need full recovery | [§5 Full Host Recovery](#5-full-host-recovery-worst-case--operational) |

## Direct Access Reference

| Host | Physical IP | SSH (no DNS) | Location |
|------|-------------|--------------|----------|
| phobos | 172.20.20.10 | `ssh root@172.20.20.10` | Rack top shelf, left unit. Label: "PHOBOS" |
| deimos | 172.20.20.11 | `ssh root@172.20.20.11` | Rack top shelf, right unit. Label: "DEIMOS" |
| ER605 | 172.20.99.1 | Web UI only (HTTPS) | Rack, physical port 5 = mgmt fallback |

Physical access: Both hosts have HDMI + USB ports. No IPMI, no serial console (HDMI only). Console login uses root password (set during bootstrap).

Gateway: 172.20.20.1 (ER605, VLAN 20 interface).

## 1. Vault Sealed Recovery

**Prereq:** SSH or physical access to phobos. Unseal keys — see below.

**Unseal key location:** Decrypt from `config/bootstrap/sealed/phobos/vault-bootstrap.sops.yaml` using the age key at `/home/abhaile/.config/sops/age/keys.txt` on phobos. Threshold: all keys in the artifact are needed (Shamir threshold from Vault init). Alternative: retrieve from operator password manager entry "Abhaile Vault Unseal Keys".

1. Set environment:

   ```bash
   export VAULT_ADDR=https://172.20.20.204:8200
   export VAULT_CACERT=/etc/ssl/certs/ca-certificates.crt
   ```

1. Verify sealed: `curl -sk https://172.20.20.204:8200/v1/sys/seal-status | jq .sealed`

1. If `true` → unseal (repeat for each key if multi-key threshold):

   ```bash
   vault operator unseal
   ```

   Alternative (no vault CLI needed):

   ```bash
   curl -sk --cacert /etc/ssl/certs/ca-certificates.crt \
     -X PUT https://172.20.20.204:8200/v1/sys/unseal \
     -H "Content-Type: application/json" \
     -d '{"key": "PASTE_KEY_HERE"}'
   ```

1. Restart vault-agent on phobos:

   ```bash
   machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service
   ```

1. Restart vault-agent on deimos:

   ```bash
   ssh root@172.20.20.11 'machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service'
   ```

1. Wait for secrets: `while [ ! -f /srv/vault/agent/out/.ready ]; do sleep 2; done`

1. All secret-dependent services (caddy-internal, caddy-dmz, authelia, ddclient, coredns) will recover via systemd path watchers once `.ready` appears.

**If Vault container won't start:** `systemctl restart vault.service` on phobos, then repeat from step 2.

## 2. DNS Total Failure

**Symptoms:** Nothing resolves. Services reachable by IP but not by name.

**Prereq:** SSH to phobos (172.20.20.10).

1. Check CoreDNS process: `systemctl status coredns.service`
1. Check blocky: `podman ps | grep blocky`
1. If CoreDNS down → restart: `systemctl restart coredns.service`
1. If blocky down → restart: `systemctl restart blocky.service`
1. Verify from another host: `dig @172.20.20.235 vault.svc.abhaile.home.arpa`
1. If still failing, check ipvlan-l2 (section 3 below).

**Temporary client workaround:** add critical entries to `/etc/hosts` using IPs from cheat sheet.

**deimos DNS (coredns-clean at 172.20.20.236):** same procedure, SSH to 172.20.20.11.

## 3. Network Lockout Recovery

**Symptoms:** Host unreachable via SSH. ipvlan-l2 gone. All /32 services dark.

**Prereq:** Physical keyboard + monitor attached to the host (HDMI, no serial).

1. Log in at console (root password).

1. Check physical link has carrier:

   ```bash
   cat /sys/class/net/enp0s31f6/carrier
   ```

   If `0` → cable or switch port issue. Check cable, verify switch port is up. ipvlan-l2 cannot work without physical carrier.

1. Check interface: `ip link show enp0s31f6` — must be UP.

1. Check ipvlan-l2: `ip link show ipvlan-l2`

1. If ipvlan-l2 missing → restart networkd:

   ```bash
   systemctl restart systemd-networkd
   ```

1. Wait 5s, verify: `ip -4 addr show dev ipvlan-l2 | grep "inet "`

1. If physical interface down:

   ```bash
   ip link set enp0s31f6 up
   systemctl restart systemd-networkd
   ```

1. Verify SSH reachable from another machine: `ssh root@172.20.20.10`

**DMZ VLAN 100 recovery** (caddy-dmz at 172.20.100.200 down, but services VLAN fine):

```bash
ip link show enp0s31f6.100      # VLAN sub-interface
ip link show ipvlan-l2.100      # DMZ ipvlan
# If missing:
systemctl restart systemd-networkd
# Verify:
ip -4 addr show dev ipvlan-l2.100 | grep "inet "
```

Note: Both VLANs depend on `enp0s31f6` carrier. If the physical link is down, both services VLAN and DMZ VLAN are affected.

**If networkd config is broken** (bad render applied):

```bash
# Manually fix /etc/systemd/network/ files, then:
systemctl restart systemd-networkd
```

## 4. Runner Crash Loop

**Symptoms:** Runner keeps firing, applying bad config, breaking services.

**Prereq:** SSH access to affected host.

1. Stop the timer immediately:

   ```bash
   systemctl stop abhaile-runner.timer
   systemctl stop abhaile-runner.service
   ```

1. Check what went wrong:

   ```bash
   cat /var/lib/abhaile/runner/last-run-status
   journalctl -u abhaile-runner.service --no-pager -n 50
   ```

1. Fix the issue (bad config in repo, broken render, etc.)

1. Test manually:

   ```bash
   cd /opt/abhaile && git pull
   abhaile-render --host $(hostname -s) --output /var/lib/abhaile
   sudo abhaile-apply --output /var/lib/abhaile --dry-run
   ```

1. If dry-run looks clean, live apply: `sudo abhaile-apply --output /var/lib/abhaile`

1. Re-enable timer: `systemctl start abhaile-runner.timer`

## 5. Full Host Recovery (Worst Case → Operational)

**Prereq:** Physical access. Host is powered on but all services are down.

1. **Console login** — attach keyboard/monitor (HDMI), log in as root.

1. **Network first:**

   ```bash
   cat /sys/class/net/enp0s31f6/carrier   # must be 1
   ip link set enp0s31f6 up
   systemctl restart systemd-networkd
   ```

1. **Stop the runner** (prevent it making things worse):

   ```bash
   systemctl stop abhaile-runner.timer
   ```

1. **Verify connectivity:** `ping 172.20.20.1` (gateway)

1. **On phobos — bring Vault up:**

   ```bash
   systemctl restart vault.service
   # Wait 10s, then unseal (set env first):
   export VAULT_ADDR=https://172.20.20.204:8200
   export VAULT_CACERT=/etc/ssl/certs/ca-certificates.crt
   vault operator unseal
   ```

1. **Bring vault-agent up** (secret-dependent services CANNOT start without this):

   ```bash
   machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service
   while [ ! -f /srv/vault/agent/out/.ready ]; do sleep 2; done
   ```

1. **DNS and time:**

   ```bash
   systemctl restart chrony.service
   systemctl restart coredns.service
   systemctl restart blocky.service
   ```

1. **Remaining services** (require secrets from step 6):

   ```bash
   systemctl restart caddy-internal.service caddy-dmz.service
   systemctl restart authelia-app.service
   systemctl restart omada-controller.service
   ```

1. **Verify:** `curl -sk https://172.20.20.204:8200/v1/sys/seal-status | jq .sealed`

1. **Re-render and re-apply if state is suspect:**

   ```bash
   cd /opt/abhaile && git fetch origin main && git checkout main && git pull
   abhaile-render --host $(hostname -s) --output /var/lib/abhaile
   sudo abhaile-apply --output /var/lib/abhaile
   ```

1. **Re-enable runner:** `systemctl start abhaile-runner.timer`

## 6. Vault-Agent Token Expiry

**Symptoms:** `.ready` sentinel missing or stale. vault-agent logs show authentication errors. Services waiting on secrets indefinitely.

**Prereq:** SSH to affected host.

1. Check vault-agent status:

   ```bash
   machinectl shell abhaile@ /bin/journalctl --user -u vault-agent.service --no-pager -n 20
   ```

1. If token expired/invalid, the seed token at `/home/abhaile/.config/vault-agent/token` needs replacement. This requires re-bootstrap of the token:

   - Mint a new AppRole SecretID from Vault (phobos, with a valid Vault token).
   - Re-run the token-minting step from bootstrap, or manually place a new wrapped token.

1. Restart vault-agent after token replacement:

   ```bash
   machinectl shell abhaile@ /bin/systemctl --user restart vault-agent.service
   while [ ! -f /srv/vault/agent/out/.ready ]; do sleep 2; done
   ```

**If the 6h token refresh (`vault-token-refresh.timer`) is failing**, check its journal for auth errors and ensure Vault is unsealed (§1).

## 7. Resource Exhaustion

### Disk Full

```bash
df -h /              # root filesystem
df -h /srv           # service data
du -sh /srv/*/       # identify large consumers

# Quick relief:
journalctl --vacuum-size=500M                    # trim journal
podman system prune -f                           # remove unused images/containers
sudo -u abhaile podman system prune -f           # rootless (vault-agent)

# If /srv/vault/agent/out/ is filling: vault-agent template error loop
machinectl shell abhaile@ /bin/journalctl --user -u vault-agent.service --no-pager -n 20
```

### Container Storage Exhausted

```bash
podman system df                                 # show usage
podman image prune -a -f                         # remove all unused images
podman volume prune -f                           # remove unused volumes

# Nuclear: reset container storage (ALL containers lost, will regenerate from quadlets)
systemctl stop vault.service blocky.service caddy-internal.service caddy-dmz.service authelia-app.service omada-controller.service
podman system reset --force
systemctl daemon-reload
# Then follow Full Host Recovery §5 from step 5
```

### OOM Killer

```bash
dmesg | grep -i "oom\|killed" | tail -20         # identify victim
journalctl -k | grep -i oom                      # kernel messages

# Identify current memory hogs:
ps aux --sort=-%mem | head -15

# Immediate relief: restart the largest non-critical container
# Long-term: set memory limits in quadlet unit files
```

## Quick IP Cheat Sheet

```bash
phobos host:      172.20.20.10    deimos host:      172.20.20.11
vault:            172.20.20.204   caddy-internal:   172.20.20.200
coredns-filtered: 172.20.20.235   coredns-clean:    172.20.20.236
blocky:           172.20.20.234   gateway:          172.20.20.1
ER605 mgmt:       172.20.99.1     caddy-dmz:        172.20.100.200
authelia:         172.20.20.201   omada-controller: 172.20.20.220
chrony-a:         172.20.20.237   chrony-b:         172.20.20.238
```
