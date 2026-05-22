# Spec: Network Device Configuration

## Metadata

```yaml
id: SPEC-2026-021
title: Network Device Configuration
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-06-05
related_adrs: []
supersedes: null
superseded_by: null
scope:
  hosts: []
  services: [omada-controller]
```

## Context

Phase 4 covers the network infrastructure managed via Omada Controller — the
ER605 gateway, managed switches (SG2218, SG2016P, SG2008P), and four EAP653
access points. This equipment forms the physical and logical network layer that
all Abhaile services depend on.

This spec documents the desired network configuration state. Omada Controller
manages this state through its UI/API, not through the Abhaile GitOps
render/apply pipeline. The spec serves as a reference for what the network
should look like when correctly configured and as a validation target for drift
detection.

The services VLAN (ID 20, 172.20.20.0/24) and DMZ VLAN (ID 100,
172.20.100.0/24) are already defined in `config/network.yaml` and used by
host networking and service addressing. This spec covers the full VLAN set
including client and device VLANs not represented in the Abhaile render
pipeline.

## Requirements

- [ ] Document ER605 VLAN and routing configuration
- [ ] Document DHCP scope configuration for all VLANs
- [ ] Document inter-VLAN ACL policy with explicit allow/deny rules
- [ ] Document WireGuard VPN server configuration and client profiles
- [ ] Document NAT hairpin rules for DMZ service access
- [ ] Document switch port profiles and spanning tree configuration
- [ ] Document wireless SSID-to-VLAN mappings and Wi-Fi 6 settings
- [ ] Document QoS policy for gaming and real-time traffic
- [ ] Establish Omada backup schedule and validate restore process

## Constraints

- All configuration changes go through Omada Controller — no CLI or direct
  device management.
- `config/network.yaml` remains the source of truth for service addressing
  and DNS records. This spec documents the broader network state that Omada
  owns.
- No rendered artifacts are produced. This spec is documentation and
  validation only.
- ER605 firmware must support WireGuard (firmware v2.2+ or Omada Controller
  5.14+).
- Switch and AP firmware must be Omada SDN compatible for centralized
  management.

## Design

### VLAN Architecture

| VLAN ID | Name | Subnet | Gateway | Purpose |
| --- | --- | --- | --- | --- |
| 1 | Default | — | — | Native VLAN (unused, management transition) |
| 99 | Management | 172.20.99.0/24 | 172.20.99.1 | Network device management (switches, APs, ER605) |
| 20 | Services | 172.20.20.0/24 | 172.20.20.1 | Abhaile hosts and containerized services |
| 30 | Trusted | 172.20.30.0/24 | 172.20.30.1 | Trusted client devices (workstations, phones) |
| 40 | Gaming | 172.20.40.0/24 | 172.20.40.1 | Gaming consoles and PCs (UPnP exception) |
| 50 | Guest | 172.20.50.0/24 | 172.20.50.1 | Guest network (internet only, isolated) |
| 60 | IoT | 172.20.60.0/24 | 172.20.60.1 | IoT devices (sensors, smart home, cameras) |
| 70 | Cast | 172.20.70.0/24 | 172.20.70.1 | Casting devices (Chromecast, AirPlay receivers) |
| 80 | Camera | 172.20.80.0/24 | 172.20.80.1 | IP cameras (isolated, NVR access only) |
| 90 | VPN | 172.20.90.0/24 | 172.20.90.1 | WireGuard VPN clients |
| 100 | DMZ | 172.20.100.0/24 | 172.20.100.1 | Public-facing services (Caddy-DMZ) |

### ER605 Gateway Configuration

#### DHCP Scopes

Each VLAN gets a DHCP scope with appropriate options:

| VLAN | Range | Option 6 (DNS) | Option 42 (NTP) | Option 15/119 (Domain) |
| --- | --- | --- | --- | --- |
| 99 | .100–.199 | coredns-clean | chrony-a, chrony-b | mgmt.abhaile.home.arpa |
| 20 | .100–.199 | coredns-filtered | chrony-a, chrony-b | svc.abhaile.home.arpa |
| 30 | .100–.199 | coredns-filtered | chrony-a, chrony-b | abhaile.home.arpa |
| 40 | .100–.199 | coredns-filtered | chrony-a, chrony-b | abhaile.home.arpa |
| 50 | .100–.199 | coredns-clean | chrony-a, chrony-b | — |
| 60 | .100–.199 | coredns-clean | chrony-a, chrony-b | iot.abhaile.home.arpa |
| 70 | .100–.199 | coredns-filtered | chrony-a, chrony-b | abhaile.home.arpa |
| 80 | .100–.199 | coredns-clean | chrony-a, chrony-b | — |

VPN (90) and DMZ (100) do not run DHCP on the ER605 — VPN addresses are
assigned by WireGuard, and DMZ uses static /32 addressing.

DNS server addresses reference service IPs from `config/network.yaml`:

- coredns-filtered: 172.20.20.235
- coredns-clean: 172.20.20.236
- chrony-a: 172.20.20.237
- chrony-b: 172.20.20.238

#### Inter-VLAN ACL Policy

Default stance: deny all inter-VLAN traffic, then add explicit allows.

Key allow rules:

| Source | Destination | Ports/Protocol | Purpose |
| --- | --- | --- | --- |
| VLAN 30 (Trusted) | VLAN 20 (Services) | TCP/\* | Full service access |
| VLAN 30 (Trusted) | VLAN 99 (Mgmt) | TCP/443, TCP/22 | Network device management |
| VLAN 30 (Trusted) | VLAN 60 (IoT) | TCP/\* | IoT device management |
| VLAN 30 (Trusted) | VLAN 70 (Cast) | TCP/UDP/\* | Casting |
| VLAN 40 (Gaming) | WAN | TCP/UDP/\* | Internet access (QoS priority) |
| VLAN 60 (IoT) | VLAN 20 (Services) | TCP/1883 | MQTT to mosquitto |
| VLAN 60 (IoT) | VLAN 20 (Services) | TCP/8123 | Home Assistant API |
| VLAN 80 (Camera) | VLAN 20 (Services) | — | Deny (go2rtc/frigate pull from cameras) |
| VLAN 20 (Services) | VLAN 60 (IoT) | TCP/554 | RTSP pull (go2rtc → cameras) |
| VLAN 20 (Services) | VLAN 80 (Camera) | TCP/554 | RTSP pull (go2rtc → cameras) |
| VLAN 90 (VPN) | VLAN 20 (Services) | TCP/\* | VPN admin access |
| VLAN 90 (VPN) | VLAN 99 (Mgmt) | TCP/443, TCP/22 | VPN network management |
| All VLANs | VLAN 20 (Services) | UDP/53, TCP/53 | DNS resolution |
| All VLANs | VLAN 20 (Services) | UDP/123 | NTP synchronization |

Key deny rules:

| Source | Destination | Ports/Protocol | Purpose |
| --- | --- | --- | --- |
| VLAN 50 (Guest) | RFC1918 | `*` | Guest isolation — internet only |
| VLAN 60 (IoT) | WAN | UDP/53, TCP/53, TCP/443 (DoH/DoT) | Force local DNS |
| VLAN 80 (Camera) | WAN | `*` | Camera internet block |
| All (except Admin/VPN) | WAN | UDP/123 | Block direct NTP to internet |
| All | All | UPnP | UPnP disabled (exception VLAN 40) |

#### WireGuard VPN

- Interface: wg0
- Address: 172.20.90.1/24
- Listen port: UDP 51820
- NAT: masquerade VPN traffic to all internal VLANs

Client profiles:

| Profile | Allowed IPs | Purpose |
| --- | --- | --- |
| admin | 0.0.0.0/0 (full tunnel) | Full network access including management |
| user | 172.20.20.0/24, 172.20.30.0/24, 172.20.70.0/24 | Service and trusted VLAN access |
| travel | 0.0.0.0/0 (full tunnel) | Internet privacy, DNS through home |

#### NAT Hairpin

Allow internal clients to access DMZ services (\*.abhaile.dedyn.io) via the
public IP without leaving the network. Hairpin NAT rewrites traffic destined
for the WAN IP back to the DMZ VLAN (172.20.100.0/24).

#### Additional WAN Rules

- DoH/DoT blocklist enforcement: block outbound TCP/443 and TCP/853 to known
  DoH/DoT resolvers from IoT and Camera VLANs.
- UPnP disabled globally, exception for VLAN 40 (Gaming).

### Switch Configuration

#### Switch Hardware

| Switch | Model | Role | Location |
| --- | --- | --- | --- |
| core-sw | SG2218 | Core/distribution, RSTP root | Rack |
| access-sw-1 | SG2016P | PoE access switch, RSTP secondary | Rack |
| access-sw-2 | SG2008P | PoE access switch | Remote |

#### Port Profiles

| Profile | Tagged VLANs | Untagged VLAN | Use Case |
| --- | --- | --- | --- |
| TRUNK-Core | All (20,30,40,50,60,70,80,90,99,100) | 99 | Core ↔ ER605 uplink |
| TRUNK-Phobos | 20, 100 | 20 | Phobos host (services + DMZ) |
| TRUNK-Deimos | 20 | 20 | Deimos host (services only) |
| TRUNK-AccessSwitch | All | 99 | Core ↔ access switch |
| AP-Uplink | 20, 30, 40, 50, 60, 70 | 99 | AP trunk ports |
| ACCESS-Trusted | — | 30 | Wired trusted devices |
| ACCESS-IoT | — | 60 | Wired IoT devices |
| ACCESS-Camera | — | 80 | Wired IP cameras |
| ACCESS-Gaming | — | 40 | Wired gaming devices |

#### Spanning Tree (RSTP)

- Root bridge: core-sw (SG2218) — priority 4096
- Secondary root: access-sw-1 (SG2016P) — priority 8192
- BPDU Guard enabled on all access ports
- Root Guard on downlink ports from core-sw

#### IGMP Snooping

- Enabled on VLAN 20 (Services) and VLAN 70 (Cast)
- Querier on core-sw for both VLANs
- Prevents multicast flooding on non-subscriber ports

#### Port Security

- Storm control on TRUNK-Phobos (broadcast/multicast/unknown-unicast thresholds)
- MAC address limiting on trunk ports (prevent MAC table overflow)
- LLDP enabled on all ports for topology discovery
- Descriptive port names matching connected device/function

### Access Point Configuration

#### Access Point Hardware

Four EAP653 (Wi-Fi 6, 802.11ax) deployed across the premises.

#### SSID Configuration

| SSID | VLAN | Band | Security | Notes |
| --- | --- | --- | --- | --- |
| Abhaile | 30 | 2.4 + 5 GHz | WPA3-Personal | Primary trusted network |
| Abhaile-Gaming | 40 | 5 GHz only | WPA3-Personal | Low-latency, 5 GHz band steering |
| Abhaile-Guest | 50 | 2.4 + 5 GHz | WPA2-Personal | Captive portal optional, isolated |
| Abhaile-IoT | 60 | 2.4 GHz only | WPA2-Personal | Legacy device compatibility |
| Abhaile-Cast | 70 | 2.4 + 5 GHz | WPA3-Personal | Casting devices |
| Abhaile-Cameras | 80 | 2.4 GHz only | WPA2-Personal | Wireless cameras (if any) |

#### Wi-Fi 6 Optimization

- OFDMA enabled (uplink and downlink)
- BSS Coloring enabled for interference mitigation
- Target Wake Time (TWT) enabled where supported
- Band steering: prefer 5 GHz for dual-band capable clients
- Minimum RSSI threshold to prevent sticky clients

#### Per-SSID Settings

- **Abhaile-IoT**: PMF (Protected Management Frames) optional, 802.11k/v/r
  disabled (legacy device compatibility)
- **Abhaile-Guest**: client isolation enabled
- **Abhaile-Cameras**: client isolation enabled
- **Abhaile-Cast**: multicast enhancement enabled for mDNS/SSDP

#### Bonjour Gateway

One-way Bonjour/mDNS forwarding from VLAN 70 (Cast) to VLAN 30 (Trusted).
Allows trusted devices to discover casting targets without full L2 bridging.

### QoS Configuration

| Rule | Source | Destination | DSCP | Priority | Purpose |
| --- | --- | --- | --- | --- | --- |
| Gaming egress | VLAN 40 | WAN | EF/CS6 | High | Low-latency gaming traffic |
| VoIP/realtime | VLAN 30 | WAN | EF | High | Voice/video calls |
| Bulk/default | All other | WAN | BE | Normal | Best effort |

- Trust DSCP markings on trunk and AP uplink ports.
- ER605 applies per-VLAN QoS queuing on WAN egress.
- No rate limiting on internal inter-VLAN traffic.

### Backup and Recovery

- Omada Controller automated site backup: daily retention (7), weekly (4),
  monthly (3).
- Backup storage: `/opt/abhaile/backups/omada/` on the Omada Controller host.
- Validate restore process by test-restoring to a staging Omada instance
  annually or after major firmware upgrades.

## Decision Notes

- Decision: Omada Controller manages all network device configuration.

- Rationale: TP-Link Omada SDN provides a single management plane for ER605, switches, and APs with centralized policy, firmware management, and backup. GitOps-rendering switch port configs would require unsupported API interaction and gain nothing over the Omada UI.

- Impact: Network device state is not tracked in git diffs. This spec and Omada backups serve as the reference and recovery mechanism.

- ADR: null

- Decision: Management VLAN 99 replaces default VLAN 1.

- Rationale: Default VLAN 1 is a common attack surface. Migrating management traffic to VLAN 99 with ACL-restricted access improves security posture.

- Impact: All device management interfaces must be re-addressed after initial VLAN migration.

- ADR: null

- Decision: Separate DNS pools (filtered vs clean) per VLAN purpose.

- Rationale: IoT and camera VLANs get unfiltered DNS (coredns-clean) because ad-blocking can break device functionality. Client VLANs get filtered DNS (coredns-filtered via Blocky) for ad/tracker blocking.

- Impact: DHCP Option 6 differs between VLANs. Devices cannot bypass local DNS due to ACL blocking outbound DoH/DoT.

- ADR: null

- Decision: WireGuard on ER605 rather than a separate VPN service.

- Rationale: ER605 firmware supports WireGuard natively via Omada. Running it on the gateway simplifies routing (no extra NAT hop) and keeps VPN traffic off the service hosts.

- Impact: VPN throughput is limited by ER605 CPU. Acceptable for a homelab with limited concurrent VPN clients.

- ADR: null

## Acceptance Criteria

- [ ] Document ER605 VLAN and routing configuration
- [ ] Document DHCP scopes with correct DNS, NTP, and domain options per VLAN
- [ ] Document inter-VLAN ACL rules with explicit allow/deny matrix
- [ ] Document WireGuard VPN configuration and validate admin/user/travel profiles
- [ ] Document NAT hairpin configuration for DMZ access
- [ ] Document DoH/DoT blocking and NTP WAN restrictions
- [ ] Document switch port profiles for all three switches
- [ ] Document RSTP topology with root/secondary bridge assignment
- [ ] Document IGMP snooping and storm control settings
- [ ] Document SSID-to-VLAN mappings and per-SSID security settings
- [ ] Document Wi-Fi 6 optimization and band steering configuration
- [ ] Document Bonjour gateway rules (Cast → Trusted)
- [ ] Document QoS DSCP marking and priority queuing rules
- [ ] Configure automated Omada site backups (daily/weekly/monthly)
- [ ] Validate Omada backup restore process
- [ ] Complete phased network deployment validation (core → VLANs → ACLs → wireless → VPN → QoS)

### Evidence

For each completed criterion, include:

- Implementation evidence: [screenshot, Omada export, or configuration description]
- Validation evidence: [connectivity test, ACL test matrix, or backup restore test]

## Out of Scope

- Abhaile render/apply pipeline changes — this is manual Omada configuration.
- Host networking (systemd-networkd, ipvlan-l2) — already handled by the
  render pipeline and `config/network.yaml`.
- Service-level DNS records — managed by CoreDNS via render pipeline.
- Firmware upgrade scheduling — handled operationally outside this spec.
- Physical cabling and rack layout.
- ISP router/modem configuration upstream of ER605.

## Open Questions

1. **Validation approach** — How do we verify that live Omada configuration
   matches this spec? Options: (a) manual checklist walkthrough, (b) Omada API
   queries compared against a machine-readable version of this spec,
   (c) SNMP-based auditing via snmp-exporter + Prometheus alerting on drift.

1. **Backup automation** — Omada Controller supports scheduled backups
   internally. Should we also pull backups via the Omada API to a separate
   location (e.g., git-tracked export minus secrets, or rsync to a second
   host)?

1. **CrowdSec bouncer on ER605** — CrowdSec can push blocklists to the ER605
   via ACL updates through the Omada API. Is this feasible with the current
   Omada Controller version? What's the latency and rule-count limit for
   dynamic ACL entries?

## References

- `config/network.yaml` (VLAN 20 and 100 definitions, service addressing)
- `config/services/omada-controller/service.yaml` (Omada Controller service definition)
- `docs/net/PORTS.md` (port mapping documentation)
- `docs/NETWORK.md` (network topology overview)
- `docs/OPERATIONS.md` (break-glass procedures reference ER605 port 5)
- `.old_docs/TODO.md` Phase 4 (original task breakdown)
