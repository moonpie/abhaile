# Maintenance

Day-to-day operations: routine checks, backups, security rotations, troubleshooting.

For deployment and drift workflows, see [OPERATIONS.md](OPERATIONS.md); for task-first reference, see [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md).

## Routine Maintenance

| Cadence | Checklist |
| --------- | -------------------------------------------------------------------------------------------------------- |
| **Daily** | Confirm `abhaile-gitops@<host>.timer` success, scan Alertmanager, ensure Vault unsealed, check Prometheus targets |
| **Weekly** | Review drift warnings, verify Omada backups, inspect CrowdSec ban list |
| **Monthly** | Test Vault restore, run `pre-commit run --all-files`, audit `policies/*.hcl` for stale roles |
| **Quarterly** | Rotate admin SSID keys, retire unused `/32` addresses, review ADRs, run DR drill |

## Backup and Disaster Recovery

### Backup Scope

**Vault snapshots:**

- Daily local (retain 7)
- Weekly NAS (retain 4)
- Monthly with restore test (retain 3)

**Configs:**

- `/etc/coredns`, `/etc/caddy`, systemd units
- Rendered configs at `/var/lib/abhaile/rendered`

**App data:**

- `/srv/<service>` via ZFS send or rsync

### Validation Steps

```bash
# Bump CoreDNS zone serials on changes (automatic via render)
python3 tools/render/cli.py

# Validate Caddy config
caddy validate --config /opt/caddy-internal/Caddyfile

# Confirm state hashes
cat /var/lib/abhaile/state/networkd.state
```

### Quarterly Restore Drill

1. Restore Vault snapshot to staging Vault
1. Re-render and apply configs
1. Validate DNS, ingress, core services
1. Document any gaps or issues

### Disaster Recovery (High-Level)

1. Restore network access (VLAN 99 admin or break-glass port)
1. Restore Vault from last known-good snapshot
1. Re-render and apply via GitOps runner or `apply.sh`
1. Validate DNS, ingress, core services before apps
1. Re-enable monitoring and alerting

## Security Operations

### Rotation Schedule

| Item | Cadence | Location |
| --- | --- | --- |
| deSEC token | Quarterly | Vault `secret/abhaile/shared/desec` |
| SMTP relay creds | Quarterly | Vault `secret/abhaile/shared/postfix` |
| CrowdSec bouncer key | Quarterly | Vault `secret/abhaile/crowdsec` |
| Admin SSID keys | Quarterly | Omada controller |
| WireGuard keys | Quarterly | ER605 VPN config |
| Internal CA | Annual | Audit trust store; rotate if manageable |

### Security Posture

**Network controls:**

- Block outbound DoH/DoT to WAN (force internal DNS)
- Block outbound UDP/123 except admin/VPN peers (force internal NTP)
- Disable UPnP/NAT-PMP globally (exception VLAN 40 if required)
- nftables default-deny on hosts; allow only required services

**Service isolation:**

- qBittorrent uses `Network=container:gluetun` with no direct ports
- nftables per-UID routing restricts qBittorrent to VPN path
- CrowdSec bouncer restricted to Admin/VPN + Prometheus; no auto-blocks for LAN
- SNMP community stored in Vault; scraping only from monitoring subnets

### Break-Glass Access

**Emergency access:**

- ER605 port 5 provides untagged VLAN 1
- Maintain laptop with static VLAN 1 IP and stored credentials
- Rotate break-glass credentials quarterly
- Update Vault records after rotation

## Troubleshooting

| Symptom | Check | Action |
| --- | --- | --- |
| Services missing `/32` IPs | `ip addr`, `systemctl status systemd-networkd` | Reapply host configs; verify drop-in ordering; send ARP: `arping -c 3 -I ipvlan-l2 <ip>` |
| Podman container flapping | `journalctl -u <quadlet>.service` | Check Vault Agent outputs; adjust service config; redeploy |
| DNS failures | `dig @172.20.20.235 <name>` | Verify CoreDNS config, Blocky upstreams, zone serials |
| GitOps apply failed | `journalctl -u abhaile-gitops@<host>` | Check for "Attempting automatic rollback" in logs; see [OPERATIONS.md](OPERATIONS.md#automatic-rollback) |
| GitOps sync fails | `journalctl -u abhaile-gitops@<host>` | Check deploy key, Age key, network connectivity |
| Vault sealed | `vault status` | Run `abhaile-vault-unseal.service` or manual unseal with SOPS keys |
| State lock timeout | `journalctl -u abhaile-gitops@<host> -b | grep lock` | Re-run apply once lock clears; avoid concurrent manual/timer applies |
| State file corrupted | `head -n1 /var/lib/abhaile/state/*.state` | Move corrupted file aside, restore from latest backup in `/var/lib/abhaile/backups/state/`, rerun apply |

### State File Recovery

1. Stop the timer during recovery: `systemctl stop abhaile-gitops@<host>.timer`
1. Inspect state files: `ls -l /var/lib/abhaile/state/*.state`
1. If a state file is truncated or invalid, move it aside: `mv /var/lib/abhaile/state/networkd.state /var/lib/abhaile/state/networkd.state.bad`
1. Restore the latest backup from `/var/lib/abhaile/backups/state/` or regenerate by re-running apply (dry-run recomputes `.state.new`).
1. Re-run apply: `sudo /opt/abhaile/tools/apply/apply.sh --apply <host>`
1. Verify drift: `./tools/apply/apply.sh <host> | grep drift`
1. Restart the timer: `systemctl start abhaile-gitops@<host>.timer`

## Observability Targets

**Prometheus scrape jobs:**

- node-exporter (`:9100`)
- podman-exporter (`:9882`)
- CoreDNS (`:9153`)
- Blocky (`:4000/metrics`)
- Caddy (`:2019/metrics`)
- Authelia (`:9091/metrics`)
- Vault (`/v1/sys/metrics?format=prometheus`)
- Loki (`:3100/metrics`)
- Prometheus (`:9090/metrics`)
- Alertmanager (`:9093/metrics`)
- Grafana (`:3000/metrics`)

**Blackbox probes:**

- HTTPS: Internal and DMZ sites
- TCP: DNS (`:53`), MQTT (`:1883`), SMTP (`:25`)
- HTTP: Vault (`:8200`), Loki (`:3100`)

**External checks:**

- `1.1.1.1`, `9.9.9.9` (upstream DNS)
- `desec.io`, `deb.debian.org` (service reachability)
- `abhaile.dedyn.io` (external DNS/DMZ)

## Ops Window

**Planned maintenance window:** 02:00-04:00 local (Europe/Dublin)

**Future utilities** (not yet implemented):

- `make cordon <host>` – Mark host for maintenance
- `make drain <host>` – Migrate services before maintenance
- `make bootstrap <host>` – Automated enrollment wrapper

## See Also

- [OPERATIONS.md](OPERATIONS.md) – Deployment workflows and drift management
- [QUICKSTART.md](QUICKSTART.md) – Get started quickly
- [DEVELOPMENT.md](DEVELOPMENT.md) – Rendering logic and testing
- [CREDENTIALS.md](CREDENTIALS.md) – Secrets management
