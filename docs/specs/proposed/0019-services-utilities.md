# Spec: Utility Services

## Metadata

```yaml
id: SPEC-2026-019
title: Utility Services
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs:
  - 0005-service-authoring-model
  - 0006-secrets-model-and-bootstrap-artifacts
supersedes: null
superseded_by: null
scope:
  hosts: [phobos, deimos]
  services: [homepage, netbox, vaultwarden, postfix, crowdsec]
```

## Context

This spec covers the utility service group: a dashboard, IPAM/DCIM inventory,
password management, email relay, and intrusion detection. All five services
have stub `service.yaml` files in `config/services/` with `podman.user: root`,
`podman.network: ipvlan-l2`, and empty composition blocks. They already have
/32 addresses assigned in `config/network.yaml` (172.20.20.202–207) and DNS A
records in `svc.abhaile.home.arpa.` but are not yet in `config/mapping.yaml`.

Netbox uses `composition.pod: {}` — it requires PostgreSQL as a sidecar,
following the pod pattern established by Authelia (app + database containers
sharing a pod network namespace).

This group introduces patterns beyond Phase 1 core services:

- Pod-based multi-container deployment with database sidecar (Netbox + PostgreSQL)
- VLAN-based SMTP relay restrictions (Postfix accepts mail only from services VLAN)
- Host-log and reverse-proxy log consumption for intrusion detection (CrowdSec)
- Cross-service integration with ingress and firewall layers (CrowdSec bouncers for Caddy, nftables, ER605)
- Service discovery aggregation for dashboard rendering (Homepage reads service metadata)

The existing quadlet renderer, ingress aggregation, vault-agent template
collection, and include mechanism handle the standard composition patterns.
This spec defines how each service fits those patterns and what integration
points require coordination with other service groups.

## Requirements

- [ ] Define complete `service.yaml` for all five services following ADR 0005
  patterns.
- [ ] Add services to `config/mapping.yaml` under their target hosts.
- [ ] Define vault-agent templates for services that need runtime secrets.
- [ ] Define ingress blocks for web-accessible services (homepage, netbox,
  vaultwarden).
- [ ] Define Postfix relay restrictions scoped to the services VLAN.
- [ ] Define CrowdSec integration points (log acquisition, bouncer outputs).
- [ ] Define the Netbox pod pattern (app + PostgreSQL sidecar).

## Constraints

- All services run rootful on ipvlan-l2 (VLAN 20) with /32 addressing — already
  declared in stubs.
- No runtime secrets in rendered output — vault-agent delivers credentials at
  runtime per ADR 0006.
- Postfix must not relay mail from outside the services VLAN (172.20.20.0/24).
  VLAN-based restrictions enforce this at the MTA level.
- CrowdSec operates in alert-only mode for LAN-sourced traffic. Active blocking
  applies only to WAN-facing sources via the ER605 bouncer.
- CrowdSec's API and dashboard are restricted to Admin/VPN and Prometheus
  scraping — no general LAN access.
- Netbox uses the pod pattern: app container and PostgreSQL container share a
  pod network namespace, communicating over localhost.
- Homepage runs on both hosts to provide dashboard availability regardless of
  which host is reachable.

## Design

### Service Group Overview

| Service | Address | Host | Role |
| --- | --- | --- | --- |
| homepage | 172.20.20.202/32 | phobos, deimos | Dashboard / service index |
| netbox | 172.20.20.203/32 | phobos | IPAM/DCIM documentation |
| vaultwarden | 172.20.20.205/32 | phobos | Password management (Bitwarden-compatible) |
| postfix | 172.20.20.206/32 | phobos | SMTP relay for internal services |
| crowdsec | 172.20.20.207/32 | phobos | Intrusion detection and response |

### Per-Service Design

#### homepage

Lightweight dashboard aggregating links and status for all deployed services.

Composition:

- `composition.container` with named volumes: `config`
- `composition.config` for `settings.yaml`, `services.yaml`, `bookmarks.yaml`
  (templates rendered from service metadata and network config)
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (protected by Authelia forward auth)

Ports: 3000 (HTTP UI)

Design notes:

- Homepage reads service metadata at render time to produce a static dashboard
  config. No runtime service discovery API calls.
- Runs on both hosts — each instance renders its own dashboard config reflecting
  the services mapped to that host plus cross-links.
- No vault-agent templates needed — dashboard content is non-secret.

#### netbox

IPAM/DCIM tool for documenting network infrastructure, IP assignments, devices,
and cabling. Requires PostgreSQL as a data store.

Composition:

- `composition.pod` with two containers: `netbox` (app) and `postgres` (database)
- Pod naming: `netbox-app.pod`, containers `netbox-app-netbox.container` and
  `netbox-app-postgres.container`
- Named volumes: `netbox-media`, `netbox-reports`, `postgres-data`
- Shared volumes: none (containers communicate over pod-internal localhost)
- `composition.config` for Netbox `configuration.py` (template with database
  connection on localhost, Redis disabled or embedded, allowed hosts)
- `composition.vault_agent.templates` for database credentials, Netbox secret
  key, and superuser bootstrap password
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (protected by Authelia forward auth)

Ports: 8080 (HTTP UI via pod address)

Design notes:

- PostgreSQL listens on localhost:5432 within the pod — no external database
  exposure.
- Follows the Authelia pod pattern: shared pod network namespace, per-container
  volumes, health checks on both containers.
- Netbox media volume stores uploaded images/attachments (operator-managed
  content).
- Initial superuser creation handled via vault-agent-delivered environment
  variables on first start.

#### vaultwarden

Bitwarden-compatible password manager. Self-contained with an embedded SQLite
database.

Composition:

- `composition.container` with named volumes: `data`
- `composition.vault_agent.templates` for admin token, SMTP credentials
  (for password reset emails via postfix), and optional push notification keys
- `composition.ingress.internal.blocks` contributing to caddy-internal
  (protected by Authelia forward auth for admin panel; Bitwarden clients
  authenticate directly)
- `composition.ingress.dmz.blocks` contributing to caddy-dmz for external
  client sync (e.g., `vault.abhaile.dedyn.io`)

Ports: 80 (HTTP), 3012 (WebSocket notifications)

Design notes:

- Vaultwarden's admin panel requires a hashed admin token delivered by
  vault-agent.
- SMTP integration uses postfix as the relay — credentials delivered by
  vault-agent.
- WebSocket support needed for live sync — Caddy must proxy `/notifications/hub`
  to port 3012.
- External access via caddy-dmz allows mobile/browser clients to sync outside
  the LAN.
- SQLite is adequate for single-household use — no external database needed.

#### postfix

SMTP relay for all internal services that send email (alertmanager, vaultwarden,
netbox, authelia). Does not accept mail from the internet.

Composition:

- `composition.container` with named volumes: `config`, `queue`
- `composition.config` for `main.cf` and `transport` (templates with
  relay host, mynetworks restriction, TLS settings)
- `composition.vault_agent.templates` for upstream relay credentials
  (smarthost authentication to external SMTP provider)

Ports: 25 (SMTP, restricted to services VLAN)

Design notes:

- `mynetworks` restricts relay access to 172.20.20.0/24 (services VLAN) and
  127.0.0.0/8. All other sources are rejected.
- Postfix relays outbound mail through an external smarthost (e.g., Fastmail,
  Mailgun). Smarthost credentials come from vault-agent.
- No ingress block needed — SMTP is not web-accessible. Services connect
  directly to postfix's /32 address on port 25.
- TLS enforced for smarthost connection (`smtp_tls_security_level = encrypt`).
- No local delivery — relay-only configuration.

#### crowdsec

Intrusion detection engine that parses logs, detects attack patterns, and
pushes decisions to bouncers (Caddy, nftables, ER605).

Composition:

- `composition.container` with named volumes: `config`, `data`, `hub`
- `composition.container.mounted_files` for log access (Caddy access logs,
  host auth logs via bind-mount)
- `composition.config` for `acquis.yaml` (log acquisition sources),
  `profiles.yaml` (alert-only for LAN, ban for WAN), and
  `local_api_credentials.yaml`
- `composition.vault_agent.templates` for LAPI credentials, bouncer API
  keys, and optional CrowdSec Central API enrollment key

Ports: 8080 (LAPI), 6060 (Prometheus metrics)

Design notes:

- CrowdSec reads caddy-internal and caddy-dmz access logs via host bind-mounts.
  The renderer maps log paths from the caddy services' known output locations.
- Three bouncers integrate with CrowdSec LAPI:
  - **Caddy bouncer**: runs as a Caddy module or sidecar, queries LAPI for
    ban decisions on incoming requests.
  - **nftables bouncer**: runs on the host, manages an nftables set of banned
    IPs for direct packet filtering.
  - **ER605 bouncer**: pushes ban decisions to the gateway ACL via API
    (implementation deferred — requires ER605 API access pattern).
- LAN sources (172.20.0.0/16) trigger alerts but not bans — `profiles.yaml`
  routes these to alert-only remediation.
- CrowdSec LAPI access is restricted via Caddy/nftables to Admin VLAN
  (172.20.99.0/24), VPN VLAN (172.20.90.0/24), and Prometheus scraping
  address.
- Prometheus metrics exposed on :6060 for scraping by the monitoring stack.

### Vault-Agent Template Aggregation

Services declaring `composition.vault_agent.templates` have their templates
collected by vault-agent on the target host. New templates for this group:

| Service | Template | Output | Content |
| --- | --- | --- | --- |
| netbox | `netbox-env.ctmpl` | `netbox.env` | DB credentials, secret key, superuser password |
| vaultwarden | `vaultwarden-env.ctmpl` | `vaultwarden.env` | Admin token, SMTP credentials, push keys |
| postfix | `postfix-relay.ctmpl` | `postfix-relay-credentials` | Smarthost username/password (sasl_passwd format) |
| crowdsec | `crowdsec-env.ctmpl` | `crowdsec.env` | LAPI credentials, bouncer keys, enrollment key |

Homepage does not need vault-agent templates — its config is non-secret.

### Ingress Aggregation

Web-accessible services contribute internal ingress blocks to caddy-internal:

| Service | FQDN | Auth | Notes |
| --- | --- | --- | --- |
| homepage | `home.abhaile.home.arpa` | Authelia forward auth | |
| netbox | `netbox.abhaile.home.arpa` | Authelia forward auth | |
| vaultwarden | `passwords.abhaile.home.arpa` | None (client auth) | Admin panel uses Authelia |

Vaultwarden also contributes a DMZ ingress block to caddy-dmz:

| Service | FQDN | Auth | Notes |
| --- | --- | --- | --- |
| vaultwarden | `vault.abhaile.dedyn.io` | None (client auth) | Bitwarden client sync |

Postfix and CrowdSec do not need ingress — they serve non-HTTP protocols or
are access-restricted via nftables.

### DNS Records

Already defined in `config/network.yaml`:

- `homepage.svc.abhaile.home.arpa. A 172.20.20.202`
- `netbox.svc.abhaile.home.arpa. A 172.20.20.203`
- `vaultwarden.svc.abhaile.home.arpa. A 172.20.20.205`
- `postfix.svc.abhaile.home.arpa. A 172.20.20.206`
- `crowdsec.svc.abhaile.home.arpa. A 172.20.20.207`

CNAME records in `abhaile.home.arpa.` for user-facing names will be added to
`config/network.yaml` during implementation (e.g., `home` → caddy,
`netbox` → caddy, `passwords` → caddy).

### Systemd Boot Ordering

All services in this group start after `abhaile-secrets-ready.service`
(vault-agent rendered credentials), except homepage which has no secret
dependencies:

```text
abhaile-secrets-ready.service
  → netbox (After=abhaile-secrets-ready)
  → vaultwarden (After=abhaile-secrets-ready)
  → postfix (After=abhaile-secrets-ready)
  → crowdsec (After=abhaile-secrets-ready, After=caddy-internal, After=caddy-dmz)

network-online.target
  → homepage (no secret dependency, starts after network)
```

CrowdSec starts after Caddy services because it reads their log files — the
logs must exist before CrowdSec attempts acquisition.

### CrowdSec Integration Architecture

```text
Log Sources:
  caddy-internal access.log ──┐
  caddy-dmz access.log ───────┤
  /var/log/auth.log ───────────┼──→ CrowdSec Engine (parse + detect)
  (future: nftables log) ─────┘           │
                                          ▼
                                    CrowdSec LAPI
                                    ┌─────┼─────┐
                                    ▼     ▼     ▼
                              Caddy    nftables  ER605
                              bouncer  bouncer   bouncer
                              (ban at  (ban at   (ban at
                               L7)     L3/L4)    gateway)
```

### Postfix Relay Topology

```text
Internal services (172.20.20.0/24)
  alertmanager ──┐
  vaultwarden ───┤
  netbox ────────┼──→ Postfix (172.20.20.206:25)
  authelia ──────┘         │
                           ▼
                    External smarthost
                    (authenticated TLS relay)
                           │
                           ▼
                    Recipient mailboxes
```

## Decision Notes

- Decision: Netbox uses the pod pattern with PostgreSQL sidecar.

- Rationale: Netbox requires PostgreSQL. Running it as a pod sidecar (like Authelia + Redis) keeps the database local, avoids a shared database service, and uses the existing pod renderer.

- Impact: Pod rendering already works from Phase 1. Netbox gets a dedicated PostgreSQL instance with data isolation.

- ADR: null

- Decision: CrowdSec operates alert-only for LAN sources.

- Rationale: Banning LAN IPs risks locking out legitimate users on shared subnets. Alert-only mode provides visibility without disruption for internal traffic while still blocking external attackers.

- Impact: CrowdSec profiles must distinguish LAN (172.20.0.0/16) from WAN sources and route them to different remediation actions.

- ADR: null

- Decision: Postfix restricts relay by source network (mynetworks).

- Rationale: Only services on VLAN 20 need to send mail. Network-level restriction is simpler and more reliable than per-service SASL authentication for internal relay.

- Impact: Any future service outside VLAN 20 that needs email must route through a VLAN 20 service or get an explicit exception.

- ADR: null

- Decision: Vaultwarden gets DMZ ingress for external client sync.

- Rationale: Mobile and browser Bitwarden clients need to sync outside the LAN. Caddy-dmz with public ACME provides TLS termination. Bitwarden's own client authentication handles access control.

- Impact: Adds a public DNS record and DMZ ingress block. Attack surface is limited to Vaultwarden's authentication layer.

- ADR: null

- Decision: Homepage runs on both hosts.

- Rationale: A dashboard should be reachable regardless of which host is available. Homepage is stateless and lightweight — running two instances adds negligible overhead.

- Impact: Homepage appears in mapping.yaml for both phobos and deimos. Each instance renders a dashboard config reflecting all services.

- ADR: null

## Acceptance Criteria

- [ ] Detail `service.yaml` definitions for all services in this group
- [ ] Netbox pod composition renders app + PostgreSQL containers with shared pod network
- [ ] All services added to `config/mapping.yaml` under target hosts
- [ ] Vault-agent templates defined for netbox, vaultwarden, postfix, and crowdsec
- [ ] Postfix main.cf restricts relay to services VLAN (mynetworks = 172.20.20.0/24, 127.0.0.0/8)
- [ ] CrowdSec acquis.yaml references correct log paths for caddy-internal and caddy-dmz
- [ ] CrowdSec profiles route LAN sources to alert-only remediation
- [ ] Ingress blocks render for homepage, netbox, and vaultwarden with Authelia forward auth
- [ ] Vaultwarden DMZ ingress block renders for external client sync
- [ ] Homepage renders on both phobos and deimos
- [ ] Unit tests pass for new composition patterns
- [ ] Integration test: full render of phobos produces correct artifacts for all five services
- [ ] No regressions in existing integration tests

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- CrowdSec ER605 bouncer implementation (requires gateway API access pattern — separate spec).
- Netbox data population (operator-managed IPAM/DCIM content).
- External smarthost provider selection and account setup for Postfix.
- CrowdSec scenario/collection curation beyond defaults.
- Vaultwarden user onboarding and organization setup.
- Homepage widget configuration beyond service links (operator customization).
- nftables bouncer installation and rule management (Phase 4 host hardening).
- CrowdSec Central API hub enrollment (optional, operator decision).

## Open Questions

1. **CrowdSec log bind-mount paths** — Caddy access logs must be bind-mounted
   into the CrowdSec container. Confirm the log output paths for caddy-internal
   and caddy-dmz containers (likely `/srv/caddy-internal/logs/access.log` and
   `/srv/caddy-dmz/logs/access.log`). Are these volume-backed or host-path?

1. **CrowdSec bouncer deployment model** — Should the Caddy bouncer run as a
   Caddy HTTP module (compiled in), a sidecar container querying LAPI, or a
   Caddy layer4 plugin? Each has different build and runtime implications.

1. **Postfix smarthost provider** — Which external SMTP relay? Fastmail,
   Mailgun, AWS SES, or another provider? This affects credential format in the
   vault-agent template and `main.cf` relay configuration.

1. **Vaultwarden external FQDN** — Proposed `vault.abhaile.dedyn.io` for
   Bitwarden client sync. Confirm this does not conflict with HashiCorp Vault's
   external needs (currently Vault has no DMZ ingress, but `vault` as a
   subdomain could cause confusion). Alternative: `passwords.abhaile.dedyn.io`.

1. **Homepage service discovery scope** — Should Homepage render dashboard
   entries for all services in mapping.yaml, or only services on the same host?
   Cross-host links require the other host's services to be reachable, which
   depends on /32 address migration status.

1. **Netbox Redis requirement** — Newer Netbox versions require Redis for
   caching and task queuing. Should Redis be a third container in the pod, or
   can Netbox operate without it for a documentation-only use case?

1. **CrowdSec LAPI access control** — The spec restricts LAPI to Admin/VPN/
   Prometheus. Should bouncers on the same host connect via localhost (pod
   network), or via the /32 address with API key authentication?

## References

- `config/services/homepage/service.yaml` (stub)
- `config/services/netbox/service.yaml` (stub — pod composition)
- `config/services/vaultwarden/service.yaml` (stub)
- `config/services/postfix/service.yaml` (stub)
- `config/services/crowdsec/service.yaml` (stub)
- `config/network.yaml` (address assignments, 172.20.20.202–207)
- `config/services/authelia/service.yaml` (reference for pod pattern)
- `docs/adr/0005-service-authoring-model.md`
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md`
- `docs/specs/proposed/0020-host-hardening.md` (SPEC-2026-020 — nftables bouncer set, CrowdSec accommodation)
- `docs/specs/proposed/0016-services-monitoring.md` (SPEC-2026-016 — CrowdSec metrics scraping)
- `docs/specs/accepted/0011-core-services.md` (SPEC-2026-011 — Phase 1 reference implementation)
