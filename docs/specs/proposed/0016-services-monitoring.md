# Spec: Monitoring and Observability Services

## Metadata

```yaml
id: SPEC-2026-016
title: Monitoring and Observability Services
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0005-service-authoring-model
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [prometheus, alertmanager, grafana, loki, promtail, node-exporter, podman-exporter, snmp-exporter, blackbox-exporter, uptime-kuma, librespeed, smokeping]
```

## Context

The homelab runs 20+ containerized services across two hosts with no centralized visibility
into service health, resource usage, network performance, or log aggregation. Operators
diagnose issues by SSH'ing into hosts and reading journals manually.

Phase 1 and 2 established the render/apply pipeline, quadlet generation, DNS, ingress, and
secrets infrastructure. This spec delivers the monitoring stack that observes those
foundations and all future services.

The service group divides into six logical areas:

- **Metrics collection** — Prometheus scrapes exporters and service endpoints.
- **Exporters** — node-exporter (host metrics), podman-exporter (container metrics),
  snmp-exporter (network devices), blackbox-exporter (endpoint probes).
- **Log aggregation** — Loki stores logs, Promtail ships them from both hosts.
- **Visualization** — Grafana provides dashboards backed by Prometheus and Loki datasources.
- **Alerting** — Alertmanager routes alerts from Prometheus to notification channels.
- **Network monitoring** — Uptime Kuma (status pages and checks), LibreSpeed (internal
  bandwidth testing), Smokeping (latency and packet loss tracking).

All monitoring services already have IP assignments in `config/network.yaml` (172.20.20.210–218)
and skeleton `service.yaml` files with empty `composition.container` blocks. This spec defines
the full service definitions and render/deploy requirements.

## Requirements

- [ ] Complete `service.yaml` definitions for all 12 services with container images, volumes,
  ports, environment, config mounts, and systemd dependencies.
- [ ] Prometheus scrape configuration discovers all in-scope targets from service metadata.
- [ ] Loki receives logs from Promtail on both hosts, and syslog from network devices
  (ER605, switches, APs) on UDP 514 and TCP 1514.
- [ ] Grafana starts with provisioned datasources (Prometheus, Loki) and no manual setup.
- [ ] Alertmanager receives alerts from Prometheus and delivers notifications.
- [ ] Blackbox exporter probes internal services, DMZ endpoints, and external dependencies.
- [ ] SNMP exporter polls ER605, switches, and access points at 60s intervals.
- [ ] Node-exporter and podman-exporter run on both hosts.
- [ ] Uptime Kuma, LibreSpeed, and Smokeping are reachable and functional.
- [ ] All containerized services use deterministic /32 ipvlan-l2 addressing.
- [ ] Vault-agent templates provide credentials where required (Grafana admin, Alertmanager
  notification creds, SNMP community strings).
- [ ] Alertmanager fires on GitOps runner failures: non-zero exit code, rollback events
  (host running prior commit), and unreachable rollback target (SPEC-2026-012).

## Constraints

- Service definitions follow the authoring model in ADR 0005.
- No secrets in rendered output — vault-agent templates for all credential material.
- Render remains deterministic and unprivileged; no external API calls during render.
- Host-network services (node-exporter, podman-exporter, promtail) bind to the host interface,
  not ipvlan-l2.
- Scrape targets derive from `config/` data only (no runtime service discovery such as
  Consul or DNS-SD).
- Container images use pinned tags managed by Renovate.

## Design

### Service Grouping and Dependencies

```text
┌─────────────────────────────────────────────────────────────┐
│                      Visualization                           │
│  Grafana ─────────────────┬─────────────────────────────────┤
│                           │ datasources                     │
├───────────────────────────┼─────────────────────────────────┤
│  Metrics                  │        Logs                     │
│  Prometheus ◄─────────────┤        Loki ◄── Promtail (×2)  │
│      │                    │          ▲                      │
│      ▼                    │          │ syslog (UDP/TCP)     │
│  Alertmanager             │     [network devices]           │
│      │                                                      │
│      ▼                                                      │
│  [notifications]                                            │
├─────────────────────────────────────────────────────────────┤
│  Exporters (scraped by Prometheus)                          │
│  node-exporter (×2) │ podman-exporter (×2)                  │
│  snmp-exporter      │ blackbox-exporter                     │
├─────────────────────────────────────────────────────────────┤
│  Network Monitoring (standalone)                            │
│  Uptime Kuma │ LibreSpeed │ Smokeping                       │
└─────────────────────────────────────────────────────────────┘
```

### Host Distribution

| Service | Host(s) | Network Mode | IP Address |
| --- | --- | --- | --- |
| prometheus | phobos | ipvlan-l2 | 172.20.20.210 |
| alertmanager | phobos | ipvlan-l2 | 172.20.20.211 |
| grafana | phobos | ipvlan-l2 | 172.20.20.212 |
| blackbox-exporter | phobos | ipvlan-l2 | 172.20.20.213 |
| snmp-exporter | phobos | ipvlan-l2 | 172.20.20.214 |
| uptime-kuma | phobos | ipvlan-l2 | 172.20.20.215 |
| librespeed | phobos | ipvlan-l2 | 172.20.20.216 |
| smokeping | phobos | ipvlan-l2 | 172.20.20.217 |
| loki | phobos | ipvlan-l2 | 172.20.20.218 |
| node-exporter | phobos, deimos | host | — |
| podman-exporter | phobos, deimos | host | — |
| promtail | phobos, deimos | host | — |

Rationale: Centralize the metrics/log store and visualization on phobos (primary host).
Host-bound exporters and log shippers run on both hosts to provide full coverage.

### Service Definitions (conceptual)

#### Prometheus

- Container image: `prom/prometheus` (pinned tag)
- Volumes: `/srv/prometheus/data` (TSDB), config mount for `prometheus.yml`
- Config: rendered `prometheus.yml` with scrape jobs built from service metadata
- Scrape jobs: node-exporter (both hosts), podman-exporter (both hosts), snmp-exporter,
  blackbox-exporter, Prometheus self, Grafana, Loki, Alertmanager, Caddy metrics, Vault
  metrics, any service exposing a `/metrics` endpoint
- Systemd: After vault (for availability ordering)
- Alerting: `alertmanager_config` pointing to alertmanager.svc.abhaile.home.arpa

#### Alertmanager

- Container image: `prom/alertmanager` (pinned tag)
- Volumes: `/srv/alertmanager/data` (state/silences)
- Config: rendered `alertmanager.yml` with receiver configuration
- Vault-agent template: notification credentials (SMTP relay, future Matrix/Telegram webhook)
- Systemd: After abhaile-secrets-ready (needs notification creds)

#### Grafana

- Container image: `grafana/grafana` (pinned tag)
- Volumes: `/srv/grafana/data` (dashboards, plugins, sqlite)
- Config: provisioning directory with datasource YAML (Prometheus URL, Loki URL)
- Vault-agent template: admin password, optional OIDC client secret (Authelia integration)
- Caddy ingress: `grafana.abhaile.home.arpa` → internal reverse proxy
- Systemd: After prometheus, loki (datasource availability)

#### Loki

- Container image: `grafana/loki` (pinned tag)
- Volumes: `/srv/loki/data` (chunks, index)
- Config: rendered `loki-config.yaml` with retention settings, syslog receiver config
- Ports: 3100 (HTTP API), 514/udp (syslog), 1514/tcp (syslog)
- Retention: infrastructure logs 30d, application logs 7d (configurable per tenant/label)
- Systemd: no special ordering (standalone store)

#### Promtail

- Runs as systemd service on host network (not containerized) or as a privileged container
  with journal/log access
- Config: rendered `promtail-config.yaml` with journal scrape and Loki push URL
- Ships: systemd journal, `/var/log/` contents
- Labels: host, unit, service name
- Push target: loki.svc.abhaile.home.arpa:3100

#### Node Exporter

- Runs on host network (systemd unit or privileged container with host PID/net/fs)
- Exposes host metrics: CPU, memory, disk, network, filesystem
- Bind: host IP port 9100
- Collectors: default set plus systemd collector for unit states

#### Podman Exporter

- Runs on host network (systemd unit)
- Exposes container metrics via podman socket
- Bind: host IP port 9882
- Requires read access to podman socket

#### SNMP Exporter

- Container image: `prom/snmp-exporter` (pinned tag)
- Config: rendered `snmp.yml` with per-device modules (ER605, SG2218, SG2016P, SG2008P, EAP653)
- Community string: delivered via vault-agent template (SNMPv2c)
- Prometheus scrapes SNMP exporter with `target` parameter for each network device

#### Blackbox Exporter

- Container image: `prom/blackbox-exporter` (pinned tag)
- Config: rendered `blackbox.yml` with probe modules (http, dns, tcp, icmp)
- Probe targets (rendered into Prometheus relabeling config):
  - Internal HTTP: `*.abhaile.home.arpa`, `*.svc.abhaile.home.arpa` services
  - DMZ HTTP: `*.abhaile.dedyn.io` via hairpin NAT
  - TCP: DNS :53, MQTT :1883, Vault :8200
  - External: `1.1.1.1`, `9.9.9.9`, `desec.io`, `deb.debian.org`

#### Uptime Kuma

- Container image: `louislam/uptime-kuma` (pinned tag)
- Volumes: `/srv/uptime-kuma/data` (sqlite, monitors config)
- Provides status pages and alerting independent of Prometheus/Alertmanager
- Caddy ingress: `uptime.abhaile.home.arpa` → internal reverse proxy

#### LibreSpeed

- Container image: `linuxserver/librespeed` (pinned tag)
- Volumes: minimal (stateless speed test server)
- Provides internal network bandwidth testing between clients and the services VLAN
- Caddy ingress: `speed.abhaile.home.arpa` → internal reverse proxy

#### Smokeping

- Container image: `linuxserver/smokeping` (pinned tag)
- Volumes: `/srv/smokeping/data` (RRD files), config mount for targets
- Config: rendered `Targets` file with ping destinations (gateway, upstream DNS, WAN
  endpoints, inter-host latency)
- Caddy ingress: `smokeping.abhaile.home.arpa` → internal reverse proxy

### Scrape Target Discovery

Prometheus scrape targets derive from `config/mapping.yaml` (which services run where) and
`config/network.yaml` (service IP addresses). The renderer builds `prometheus.yml` scrape
jobs statically at render time:

- For ipvlan-l2 services: target is `<service>.svc.abhaile.home.arpa:<metrics_port>`
- For host-network services: target is `<host-ip>:<exporter_port>`
- SNMP and blackbox use relabeling with a `targets` list rendered from known device IPs

No runtime service discovery. Adding a new scrape target means updating the source config and
re-rendering.

### Secrets Requirements

| Secret | Delivery | Consumer |
| --- | --- | --- |
| Grafana admin password | vault-agent template → env file | Grafana container |
| Grafana OIDC client secret | vault-agent template → env file | Grafana container |
| Alertmanager SMTP credentials | vault-agent template → alertmanager.yml section | Alertmanager container |
| SNMP community strings | vault-agent template → snmp.yml or env file | SNMP exporter container |

### Caddy Ingress

| Service | FQDN | Auth |
| --- | --- | --- |
| grafana | grafana.abhaile.home.arpa | Authelia forward-auth |
| uptime-kuma | uptime.abhaile.home.arpa | Authelia forward-auth |
| librespeed | speed.abhaile.home.arpa | none (LAN-only utility) |
| smokeping | smokeping.abhaile.home.arpa | Authelia forward-auth |
| prometheus | prometheus.abhaile.home.arpa | Authelia forward-auth |
| alertmanager | alertmanager.abhaile.home.arpa | Authelia forward-auth |

### Systemd Dependency Chain

```text
vault → vault-agent → abhaile-secrets-ready
                          │
                          ├── alertmanager (needs notification creds)
                          └── grafana (needs admin password + OIDC)

prometheus → alertmanager (alerting route)
loki (independent)
promtail → loki (push target must resolve via DNS)
node-exporter, podman-exporter (independent, early boot)
```

## Decision Notes

_To be recorded during implementation._

## Acceptance Criteria

- [ ] Detail `service.yaml` definitions for all services in this group
- [ ] Render produces valid quadlet units (.container, .volume, .image) for all containerized
  services
- [ ] Render produces systemd unit files for host-network services (node-exporter,
  podman-exporter, promtail) on both hosts
- [ ] Prometheus `prometheus.yml` is rendered with correct scrape jobs for all targets
  assigned to the same host
- [ ] Loki config includes syslog receiver on UDP 514 and TCP 1514
- [ ] Promtail config ships journal and log files to Loki with correct labels
- [ ] Grafana provisioning includes Prometheus and Loki datasource definitions
- [ ] Blackbox exporter config includes probe modules and target lists for internal, DMZ, and
  external endpoints
- [ ] SNMP exporter config includes per-device modules for ER605, switches, and APs
- [ ] Vault-agent templates exist for Grafana admin password, Alertmanager notification
  credentials, and SNMP community strings
- [ ] Caddy ingress blocks are rendered for Grafana, Uptime Kuma, LibreSpeed, Smokeping,
  Prometheus, and Alertmanager
- [ ] DNS records in `config/network.yaml` resolve correctly for all monitoring services
- [ ] `config/mapping.yaml` updated with monitoring service assignments for both hosts
- [ ] Smokeping targets config rendered with gateway, upstream DNS, WAN, and inter-host
  entries
- [ ] Unit tests cover render output for each service type
- [ ] Integration tests verify full monitoring stack renders without errors for both hosts
- [ ] No secrets appear in rendered output

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- Dashboard content (JSON models) — provision empty Grafana, dashboards added operationally.
- Alert rules content — Prometheus rule files are a follow-up once scrape targets are stable.
- Uptime Kuma monitor definitions — configured via UI after deployment.
- Optional exporters (chrony-exporter, smartctl-exporter, ups-exporter, custom nftables
  exporter) — defer until core stack is operational.
- High-availability (multi-instance Prometheus/Loki) — single-host deployment is sufficient
  for this homelab scale.
- Log retention automation (compaction, deletion) — Loki handles this internally per config.

## Open Questions

1. **SNMP community strings:** Deliver via vault-agent template into the SNMP exporter config
   file directly, or as an environment variable the exporter reads? Direct config injection
   keeps the standard `snmp.yml` format intact but requires re-rendering the full config on
   secret rotation.

1. **Retention policies:** Loki proposes 30d for infrastructure, 7d for application logs.
   Prometheus TSDB retention needs a decision — 15d, 30d, or 90d? Storage on a 32GB RAM
   machine with limited disk constrains this.

1. **Scrape target discovery mechanism:** Static render-time generation from `config/` is
   proposed. Should services declare a `metrics_port` field in `service.yaml` to make
   Prometheus config generation fully automatic, or maintain an explicit scrape job list in
   Prometheus config?

1. **Host placement:** This spec places all centralized monitoring on phobos. Should any
   services (Loki, Prometheus) run on deimos instead to balance load, or does consolidation
   on the primary host simplify operations?

1. **Promtail deployment model:** Run as a host systemd service (access to journal natively)
   or as a privileged container with journal bind-mount? The skeleton `service.yaml` uses
   `systemd: network: host` suggesting the former.

1. **LibreSpeed authentication:** The spec proposes no auth (LAN-only utility). Confirm this
   is acceptable or whether Authelia forward-auth should protect it.

## References

- `docs/adr/0005-service-authoring-model.md`
- `config/network.yaml` — IP assignments (172.20.20.210–218 block)
- `config/mapping.yaml` — current host-to-service mapping (monitoring not yet assigned)
- `config/services/*/service.yaml` — skeleton definitions for all 12 services
- `docs/specs/proposed/0015-services-home-automation.md` (SPEC-2026-015 — scrape targets on phobos)
- `docs/specs/proposed/0017-services-media.md` (SPEC-2026-017 — scrape targets on deimos)
- `docs/specs/proposed/0019-services-utilities.md` (SPEC-2026-019 — CrowdSec metrics, Postfix metrics)
- `docs/specs/proposed/0021-network-devices.md` (SPEC-2026-021 — SNMP targets for ER605, switches, APs)
- Phase 3 TODO items: "Monitoring & Observability", "Host Hardening & Observability",
  "Network Monitoring" sections
