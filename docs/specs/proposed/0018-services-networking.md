# Spec: Networking Services

## Metadata

```yaml
id: SPEC-2026-018
title: Networking Services
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
  hosts: [deimos]
  services: [gluetun, qbittorrent]
```

## Context

Media acquisition traffic (qBittorrent) must egress exclusively through a VPN tunnel. If the
tunnel drops, traffic must not leak to the host's default route. The old project planned this
via Gluetun as a VPN gateway container with qBittorrent sharing its network namespace
(`Network=container:gluetun`), plus host-level nftables rules enforcing per-UID egress routing
so the service user can only reach the internet through the VPN container.

Gluetun already has a `service.yaml` stub (`podman.network: ipvlan-l2`, rootful) and a
deterministic `/32` address at `172.20.20.239` on the services VLAN. qBittorrent has a stub
declaring `podman.network: container:gluetun`, meaning it shares Gluetun's network namespace
and has no independent network identity.

This spec covers the service definitions, container composition, VPN credential delivery via
Vault Agent, and the coordination surface with host-level kill-switch rules. The actual nftables
ruleset and per-UID policy routing belong to the host-hardening spec (SPEC-2026-020); this spec defines what
that hardening must enforce for this service group.

## Requirements

- [ ] Define complete `service.yaml` for gluetun and qbittorrent per the service authoring model (ADR 0005)
- [ ] Route all qBittorrent egress through Gluetun's VPN tunnel with no direct internet path
- [ ] Deliver VPN provider credentials to Gluetun via Vault Agent templates (no secrets in git)
- [ ] Enforce start ordering: Gluetun must be healthy before qBittorrent starts
- [ ] Define the contract between this service group and the host-hardening spec for kill-switch enforcement

## Constraints

- Both services run rootful on deimos.
- qBittorrent shares Gluetun's network namespace (`Network=container:gluetun` in quadlet). It does not get its own ipvlan-l2 address.
- Gluetun requires `NET_ADMIN` and access to `/dev/net/tun` for WireGuard/OpenVPN tunnel creation.
- VPN credentials are runtime secrets — Vault Agent renders them to a host path consumed by the Gluetun container at startup.
- No secrets in rendered output. VPN credential paths are references only.
- Kill-switch nftables rules and per-UID routing table configuration are out of scope for this spec (owned by host-hardening) but the interface contract is defined here.
- The service must tolerate VPN provider reconnections without manual intervention.

## Design

### Service Group Composition

Gluetun and qBittorrent form a tightly-coupled service group. Gluetun owns the network
namespace; qBittorrent is a network consumer within it.

```text
┌─────────────────────────────────────────────┐
│ Gluetun container (ipvlan-l2: 172.20.20.239)│
│  - WireGuard/OpenVPN tunnel                 │
│  - tun0 interface                           │
│  - Built-in firewall (iptables)             │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │ qBittorrent container                  │ │
│  │  - Network=container:gluetun           │ │
│  │  - Shares network namespace            │ │
│  │  - WebUI on localhost:8080             │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### Gluetun `service.yaml` Structure

```yaml
name: gluetun
podman:
  user: root
  network: ipvlan-l2
composition:
  container:
    image: ghcr.io/qdm12/gluetun
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun
    environment:
      VPN_SERVICE_PROVIDER: "{{ provider }}"
      VPN_TYPE: wireguard
      FIREWALL_VPN_INPUT_PORTS: "8080"  # qBittorrent WebUI
    volumes:
      - data:/gluetun
    health_check:
      test: /gluetun-entrypoint healthcheck
      interval: 30s
      timeout: 10s
      retries: 3
  config:
    - source: gluetun/config/gluetun.env
      destination: /srv/gluetun/config/gluetun.env
      description: Non-secret environment variables
  vault_agent:
    templates:
      - source: gluetun/templates/vpn-credentials.env.ctmpl
        destination: /srv/gluetun/config/vpn-credentials.env
        perms: "0640"
        description: VPN provider credentials (private key, endpoint)
```

### qBittorrent `service.yaml` Structure

```yaml
name: qbittorrent
podman:
  user: root
  network: container:gluetun
composition:
  container:
    image: ghcr.io/linuxserver/qbittorrent
    environment:
      PUID: "1000"
      PGID: "1000"
      WEBUI_PORT: "8080"
    volumes:
      - config:/config
      - downloads:/downloads
  systemd:
    - unit: qbittorrent.container
      after:
        - gluetun.service
      requires:
        - gluetun.service
```

### Systemd Dependency and Start Order

The quadlet renderer produces:

- `gluetun.container` — starts Gluetun with ipvlan-l2 networking, `NET_ADMIN`, `/dev/net/tun`.
- `qbittorrent.container` — declares `After=gluetun.service` and `Requires=gluetun.service`.
  Systemd guarantees qBittorrent only starts after Gluetun is running. If Gluetun stops,
  qBittorrent stops.

Gluetun's health check (built into the image) validates the VPN tunnel is active. The
`Requires=` dependency ensures qBittorrent does not outlive Gluetun.

### VPN Credential Delivery

Vault Agent renders VPN credentials from a Vault KV path to
`/srv/gluetun/config/vpn-credentials.env`. The Gluetun container mounts this file as an
`EnvironmentFile` (or bind-mount, depending on provider config format).

The `.ctmpl` source lives in `config/services/gluetun/templates/vpn-credentials.env.ctmpl`
and references Vault paths for:

- WireGuard private key
- WireGuard endpoint address and public key
- (Or OpenVPN username/password if using OpenVPN provider)

Vault Agent collects this template via the standard `vault_agent.templates` mechanism
(ADR 0005, existing vault-agent service inclusion).

### Kill-Switch Interface Contract (Host-Hardening Boundary)

This spec defines what the host-hardening spec must enforce. The kill-switch operates at
two levels:

**Level 1 — Container-internal (Gluetun built-in):**

Gluetun's built-in iptables rules block all container egress except through `tun0`. This is
the first line of defense and operates without host cooperation.

**Level 2 — Host-level nftables (owned by host-hardening spec):**

The host-hardening spec must implement:

1. **Per-UID egress restriction:** Traffic from the UID running the Gluetun container process
   may only egress to the VPN endpoint IP(s) on the WAN interface. All other egress from
   that UID is dropped.
1. **Policy routing table (`vpn`):** A dedicated routing table that forces traffic from the
   service UID through the VPN tunnel interface.
1. **Default deny for the service network namespace:** If the VPN tunnel is down and Gluetun's
   internal firewall is somehow bypassed, host nftables drop any traffic from the
   `172.20.20.239` source that is not destined for the local network.

This spec provides the host-hardening spec with:

- The container UID (rootful, so `root` or a mapped sub-UID depending on user namespace config)
- The service IP (`172.20.20.239/32`)
- The VPN endpoint IP range (provider-dependent, defined at implementation time)
- The allowed local destinations (services VLAN `172.20.20.0/24`, gateway `172.20.20.1`)

### Ingress Path

qBittorrent's WebUI listens on port 8080 within Gluetun's network namespace. Since Gluetun
has the ipvlan-l2 address `172.20.20.239`, the WebUI is reachable at `172.20.20.239:8080`
from the services VLAN. Caddy-internal can reverse-proxy this for authenticated access.

Gluetun's `FIREWALL_VPN_INPUT_PORTS` must include `8080` to allow inbound WebUI connections
through its internal firewall.

### DNS

Gluetun already has a DNS record defined in `network.yaml`:

- `gluetun.svc.abhaile.home.arpa` → `172.20.20.239`

qBittorrent does not need its own DNS record since it shares Gluetun's IP. A CNAME alias
(`qbittorrent.svc.abhaile.home.arpa` → `gluetun.svc.abhaile.home.arpa`) may be added for
discoverability if desired.

## Decision Notes

_To be recorded during implementation._

## Acceptance Criteria

- [ ] Detail `service.yaml` definitions for all services in this group
- [ ] Gluetun quadlet renders with `NET_ADMIN` capability, `/dev/net/tun` device, ipvlan-l2 networking, and health check.
- [ ] qBittorrent quadlet renders with `Network=container:gluetun` and `After=/Requires=gluetun.service`.
- [ ] Vault Agent template for VPN credentials is defined and collected by the vault-agent service.
- [ ] No secret values appear in rendered output; only Vault template references and destination paths.
- [ ] Kill-switch interface contract is documented with specific UIDs, IPs, and allowed destinations for the host-hardening spec.
- [ ] Gluetun container forwards port 8080 (qBittorrent WebUI) through its internal firewall.
- [ ] Integration test validates render output for both services on deimos.
- [ ] Systemd dependency chain prevents qBittorrent from running without a healthy Gluetun.

### Evidence

For each completed criterion, include:

- Implementation evidence: [commit or PR link]
- Validation evidence: [test, dry-run, or equivalent]

## Out of Scope

- Host-level nftables ruleset implementation (host-hardening spec owns this).
- Per-UID policy routing table setup (host-hardening spec).
- Caddy ingress configuration for qBittorrent WebUI (covered by the media services or ingress spec).
- VPN provider account creation or credential provisioning in Vault (operator task).
- Download directory layout, media library integration, or \*arr stack connectivity.
- Gluetun port forwarding for torrent seeding (future enhancement).

## Open Questions

1. **VPN provider selection:** Which provider will Gluetun connect to? This determines the
   credential format (WireGuard private key vs OpenVPN user/pass), endpoint IPs for
   kill-switch rules, and any provider-specific Gluetun environment variables. Mullvad and
   AirVPN both support WireGuard and port forwarding; ProtonVPN supports WireGuard but has
   limited port forwarding. Decision needed before implementation.

1. **Kill-switch implementation detail:** Should the host-level nftables rules use cgroup-based
   matching (matching the container's cgroup path) or UID-based matching? Rootful podman
   containers run as root, so UID-based matching is insufficient without user namespaces. The
   host-hardening spec needs to determine the most reliable matching strategy for
   container-originated traffic.

1. **Interaction with host-hardening spec:** Should this spec block on host-hardening, or
   can the services deploy without host-level kill-switch (relying solely on Gluetun's
   internal firewall) and have host-level rules applied later? Gluetun's built-in firewall
   provides defense-in-depth, but the host-level rules are the authoritative kill-switch.

1. **Port forwarding for seeding:** Does the VPN provider support port forwarding, and should
   Gluetun be configured to request a forwarded port? This affects Gluetun environment
   variables and potentially the host-hardening rules for inbound VPN traffic.

1. **Health check failure behavior:** If Gluetun's health check fails (VPN tunnel drops),
   should systemd automatically restart qBittorrent, or should it remain stopped until
   manual intervention? `Requires=` will stop qBittorrent if Gluetun stops, but a degraded
   (unhealthy but running) Gluetun may not trigger this.

## References

- `config/services/gluetun/service.yaml` (stub)
- `config/services/qbittorrent/service.yaml` (stub)
- `config/network.yaml` — gluetun address `172.20.20.239/32` on services VLAN
- `docs/adr/0005-service-authoring-model.md` — service.yaml contract
- `docs/adr/0006-secrets-model-and-bootstrap-artifacts.md` — secrets boundary
- `docs/specs/proposed/0020-host-hardening.md` (SPEC-2026-020 — kill-switch implementation owner)
- `.old_docs/TODO.md` — Phase 3 Networking & VPN section
