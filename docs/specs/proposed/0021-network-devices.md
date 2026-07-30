# Spec: Network Device Configuration

## Metadata

```yaml
id: SPEC-2026-021
title: Network Device Configuration
status: proposed
owner: moonpie
created: 2026-06-05
updated: 2026-07-28
related_adrs:
  - 0001-output-root-and-environment-paths
  - 0002-hash-based-drift-detection-and-state-model
  - 0004-apply-execution-model
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

This spec defines how Abhaile should manage controller-owned network
configuration. The preferred end state is vendor-neutral network intent in git,
live-state discovery from the network controller, drift reporting, and
controlled apply through a dedicated network automation tool. Omada Controller
is the first target controller, but the intent model should not require an
overhaul if the network later moves to another controller-backed vendor such as
Ubiquiti. Manual controller UI changes remain a break-glass path, not the
desired steady state.

The services VLAN (ID 20, 172.20.20.0/24) and DMZ VLAN (ID 100,
172.20.100.0/24) are already defined in `config/network.yaml` and used by
host networking and service addressing. This spec covers the full VLAN set
including client and device VLANs not represented in the Abhaile render
pipeline.

The first implementation targets Omada and depends on API capability. Home
Assistant's TP-Link Omada integration confirms that local Omada Controller
access can read and control Omada devices through a controller account, but it
exposes only a limited operational surface. The `tplink-omada-client` Python
package confirms a local controller API exists, with support for login,
controller/site/device discovery, firmware actions, switch port
status/configuration, access point LAN port configuration, and some gateway port
controls. It also documents that only a subset of controller features is
currently exposed and that the Omada platform is transitioning toward a newer
OpenAPI API.

Because of that uncertainty, Phase 4 starts with API capability discovery before
committing to automated writes for VLANs, DHCP, ACLs, SSIDs, VPN, backups, or
other high-impact network state.

## Requirements

- [ ] Discover and document controller API capabilities for each desired resource type
- [ ] Define a machine-readable desired-state model for controller-owned network configuration
- [ ] Store network desired state under `config/networks/`
- [ ] Keep desired network intent vendor-neutral where practical
- [ ] Render or normalize desired network state deterministically
- [ ] Read live network state using an adapter for the target controller
- [ ] Produce dry-run drift reports before any write support
- [ ] Apply only resource types that have proven idempotent API support
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

- All automated configuration changes go through a controller adapter. The
  initial adapter targets Omada Controller. Do not manage ER605, switches, or
  access points through direct device CLI or per-device web UIs.
- `config/network.yaml` remains the source of truth for service addressing
  and DNS records.
- `config/networks/` owns network infrastructure intent such as VLAN
  interfaces, DHCP scopes, ACLs, port profiles, SSIDs, VPN profiles, backup
  policy, and QoS. `config/network.yaml` may be referenced by network config,
  but must not be duplicated.
- Vendor-specific controller details belong in adapter configuration, not in
  the core network intent model unless the capability cannot be represented
  generically.
- Render and diff must be deterministic and must not query the controller
  during render.
- Network apply must default to dry-run. Live writes require an explicit operator
  request and should be limited to resource types with proven idempotent
  endpoints.
- Controller credentials are secrets. Store them in Vault or operator-owned
  runtime material, never in git or rendered artifacts.
- ER605 firmware must support WireGuard (firmware v2.2+ or Omada Controller
  5.14+).
- Switch and AP firmware must be Omada SDN compatible for centralized
  management.

## Automation Design

### Source Of Truth

Network intent lives under `config/networks/`. Proposed files:

```text
config/networks/
  site.yaml
  vlans.yaml
  dhcp.yaml
  acl.yaml
  port-profiles.yaml
  controllers.yaml
  devices.yaml
  wireless.yaml
  vpn.yaml
  qos.yaml
  backups.yaml
```

`config/network.yaml` remains authoritative for Abhaile service addresses, DNS
records, and host interfaces. Network config may reference values from
`config/network.yaml` by stable keys, but should not copy service IPs or VLAN
CIDRs when a reference can be resolved deterministically.

Core files describe intent in generic terms: VLANs, networks, DHCP options,
security policies, wireless networks, port roles, and backup expectations.
`controllers.yaml` binds that intent to the active controller implementation,
including vendor, controller URL reference, site identity, adapter settings, and
capability overrides.

### Tooling Model

Add a dedicated network automation tool rather than extending host apply
directly at first. The tool should support:

- `discover`: authenticate through the selected controller adapter and report
  controller version, sites, supported endpoint groups, and discovered resource
  identifiers
- `render`: validate and normalize `config/networks/` intent without contacting
  the controller
- `diff`: compare normalized desired state with live controller state
- `apply --dry-run`: default mode; print the write plan without changing the
  controller
- `apply --live`: explicit live mode for supported, idempotent resource types

The network tool should expose a stable internal desired-state model and place
vendor-specific translation behind adapters. The initial adapter is Omada. A
future Ubiquiti or other controller adapter should be able to reuse the same
intent files when the concepts map cleanly, while rejecting unsupported
capabilities explicitly.

The network tool should write any comparison state under the normal Abhaile
state root only after successful live operations. It must not write
`out/state/` directly outside the established apply/state mechanisms.

### Controller Capability Matrix

Each resource type must be classified for each controller adapter before
implementation:

| Resource Type | Desired Support | Initial Mode |
| --- | --- | --- |
| Controller/site identity | read | discover |
| Devices and ports | read, limited write | diff first |
| VLAN interfaces | read/write if supported | spike |
| DHCP scopes/options | read/write if supported | spike |
| ACLs/firewall rules | read/write if supported | spike |
| Switch port profiles | read/write if supported | spike |
| SSIDs/wireless networks | read/write if supported | spike |
| WireGuard VPN | read/write if supported | spike |
| QoS policy | read/write if supported | spike |
| Controller backups | read/trigger/download if supported | spike |

Unsupported or unstable resources remain documented/manual until the controller
adapter surface is proven.

### Safety Model

- Dry-run is the default and must be read-only.
- Live apply requires an explicit flag.
- Apply should group changes by resource type and stop on first failed write.
- High-risk changes such as management VLAN, gateway interface, WAN, ACL default
  deny, and controller access paths require an additional confirmation flag.
- The tool must never delete unknown live resources until prune semantics are
  explicitly specified and tested.
- A backup should exist before high-risk live changes.

## Design

### VLAN Architecture

| VLAN ID | Name | Subnet | Gateway | SSID | Purpose |
| --- | --- | --- | --- | --- | --- |
| 1 | Adoption (Default) | 192.168.0.0/24 | 192.168.0.1 | N/A | Default/adoption network for initial device onboarding |
| 20 | Services | 172.20.20.0/24 | 172.20.20.1 | N/A | Abhaile hosts and containerized services |
| 30 | General | 172.20.30.0/24 | 172.20.30.1 | an t-idirlion | General client devices |
| 40 | Gaming | 172.20.40.0/24 | 172.20.40.1 | an t-idirlion.gaming | Gaming consoles and PCs (UPnP exception) |
| 50 | IoT | 172.20.50.0/24 | 172.20.50.1 | an t-idirlion.iot | IoT devices and smart-home endpoints |
| 60 | Camera | 172.20.60.0/24 | 172.20.60.1 | N/A | IP cameras (isolated, NVR access only) |
| 70 | Cast | 172.20.70.0/24 | 172.20.70.1 | an t-idirlion.cast | Casting devices (Chromecast, AirPlay receivers) |
| 80 | Guest | 172.20.80.0/24 | 172.20.80.1 | an t-idirlion.guest | Guest network (internet only, isolated) |
| 90 | VPN | 172.20.90.0/24 | 172.20.90.1 | N/A | WireGuard VPN clients |
| 99 | Mgmt | 172.20.99.0/24 | 172.20.99.1 | an t-idirlion.mgmt | Network device management (switches, APs, ER605) |
| 100 | DMZ | 172.20.100.0/24 | 172.20.100.1 | N/A | Public-facing services (Caddy-DMZ) |

### ER605 Gateway Configuration

#### DHCP Scopes

Each VLAN gets a DHCP scope with appropriate options:

| VLAN | Range | Option 6 (DNS) | Option 42 (NTP) | Option 15/119 (Domain) |
| --- | --- | --- | --- | --- |
| 1 | .100–.199 | coredns-clean | chrony-a, chrony-b | — |
| 99 | .100–.199 | coredns-clean | chrony-a, chrony-b | mgmt.abhaile.home.arpa |
| 20 | .100–.199 | coredns-clean | chrony-a, chrony-b | svc.abhaile.home.arpa |
| 30 | .100–.199 | coredns-filtered | chrony-a, chrony-b | abhaile.home.arpa |
| 40 | .100–.199 | coredns-filtered-light | chrony-a, chrony-b | abhaile.home.arpa |
| 50 | .100–.199 | coredns-filtered-strict | chrony-a, chrony-b | iot.abhaile.home.arpa |
| 60 | .100–.199 | coredns-filtered-strict | chrony-a, chrony-b | camera.abhaile.home.arpa |
| 70 | .100–.199 | coredns-filtered-light | chrony-a, chrony-b | abhaile.home.arpa |
| 80 | .100–.199 | coredns-filtered-strict | chrony-a, chrony-b | guest.abhaile.home.arpa |

VPN (90) and DMZ (100) do not run DHCP on the ER605 — VPN addresses are
assigned by WireGuard, and DMZ uses static /32 addressing.

DNS server addresses reference service IPs from `config/network.yaml`:

- coredns-filtered: 172.20.20.235
- coredns-clean: 172.20.20.236
- chrony-a: 172.20.20.237
- chrony-b: 172.20.20.238

If CoreDNS implements source-CIDR policy internally, ER605 DHCP may instead
provide the same highly available CoreDNS pair to every VLAN and let CoreDNS
select clean, filtered, lightly filtered, or strictly filtered upstream policy
from the client source subnet.

#### Inter-VLAN ACL Policy

Default stance: deny all inter-VLAN traffic, then add explicit allows.

Key allow rules:

| Source | Destination | Ports/Protocol | Purpose |
| --- | --- | --- | --- |
| VLAN 30 (General) | VLAN 20 (Services) | TCP/\* | Full service access |
| VLAN 30 (General) | VLAN 99 (Mgmt) | TCP/443, TCP/22 | Network device management |
| VLAN 30 (General) | VLAN 50 (IoT) | TCP/\* | IoT device management |
| VLAN 30 (General) | VLAN 70 (Cast) | TCP/UDP/\* | Casting |
| VLAN 40 (Gaming) | WAN | TCP/UDP/\* | Internet access (QoS priority) |
| VLAN 50 (IoT) | VLAN 20 (Services) | TCP/1883 | MQTT to mosquitto |
| VLAN 50 (IoT) | VLAN 20 (Services) | TCP/8123 | Home Assistant API |
| VLAN 60 (Camera) | VLAN 20 (Services) | — | Deny (go2rtc/frigate pull from cameras) |
| VLAN 20 (Services) | VLAN 50 (IoT) | TCP/554 | RTSP pull (go2rtc → cameras, if needed) |
| VLAN 20 (Services) | VLAN 60 (Camera) | TCP/554 | RTSP pull (go2rtc → cameras) |
| VLAN 90 (VPN) | VLAN 20 (Services) | TCP/\* | VPN admin access |
| VLAN 90 (VPN) | VLAN 99 (Mgmt) | TCP/443, TCP/22 | VPN network management |
| All VLANs | VLAN 20 (Services) | UDP/53, TCP/53 | DNS resolution |
| All VLANs | VLAN 20 (Services) | UDP/123 | NTP synchronization |

Key deny rules:

| Source | Destination | Ports/Protocol | Purpose |
| --- | --- | --- | --- |
| VLAN 80 (Guest) | RFC1918 | `*` | Guest isolation — internet only |
| VLAN 50 (IoT) | WAN | UDP/53, TCP/53, TCP/443 (DoH/DoT) | Force local DNS |
| VLAN 60 (Camera) | WAN | `*` | Camera internet block |
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
| user | 172.20.20.0/24, 172.20.30.0/24, 172.20.70.0/24 | Service, general, and cast VLAN access |
| travel | 0.0.0.0/0 (full tunnel) | Internet privacy, DNS through home |

#### NAT Hairpin

Allow internal clients to access DMZ services (\*.abhaile.dedyn.io) via the
public IP without leaving the network. Hairpin NAT rewrites traffic destined
for the WAN IP back to the DMZ VLAN (172.20.100.0/24).

#### Additional WAN Rules

- DoH/DoT blocklist enforcement: block outbound TCP/443 and TCP/853 to known
  DoH/DoT resolvers from IoT, Camera, and Guest VLANs.
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
| AP-Uplink | 20, 30, 40, 50, 70, 80, 99 | 1 | AP trunk ports; native VLAN 1 remains adoption/default only |
| ACCESS-General | — | 30 | Wired general client devices |
| ACCESS-IoT | — | 50 | Wired IoT devices |
| ACCESS-Camera | — | 60 | Wired IP cameras |
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
| an t-idirlion | 30 | 2.4 + 5 GHz | WPA3-Personal | General client network |
| an t-idirlion.gaming | 40 | 5 GHz only | WPA3-Personal | Low-latency, 5 GHz band steering |
| an t-idirlion.iot | 50 | 2.4 GHz only | WPA2-Personal | Legacy device compatibility |
| an t-idirlion.cast | 70 | 2.4 + 5 GHz | WPA3-Personal | Casting devices |
| an t-idirlion.guest | 80 | 2.4 + 5 GHz | WPA2-Personal | Captive portal optional, isolated |
| an t-idirlion.mgmt | 99 | 5 GHz only | WPA3-Personal | Restricted network management access |

#### Wi-Fi 6 Optimization

- OFDMA enabled (uplink and downlink)
- BSS Coloring enabled for interference mitigation
- Target Wake Time (TWT) enabled where supported
- Band steering: prefer 5 GHz for dual-band capable clients
- Minimum RSSI threshold to prevent sticky clients

#### Per-SSID Settings

- **an t-idirlion.iot**: PMF (Protected Management Frames) optional, 802.11k/v/r
  disabled (legacy device compatibility)
- **an t-idirlion.guest**: client isolation enabled
- **an t-idirlion.cast**: multicast enhancement enabled for mDNS/SSDP
- **an t-idirlion.mgmt**: restricted to admin devices and management workflows

#### Bonjour Gateway

One-way Bonjour/mDNS forwarding from VLAN 70 (Cast) to VLAN 30 (General).
Allows general client devices to discover casting targets without full L2 bridging.

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

- Decision: Controller-backed automation is the only automated management path
  for network devices.

- Rationale: Controller platforms provide centralized policy, firmware
  management, and backup. Automation should interact with the controller, not
  bypass it through direct device management.

- Impact: Direct device CLI/web management is out of scope. Controller adapter
  capability spikes decide which resource types can be managed automatically.

- ADR: null

- Decision: Phase 4 uses `config/networks/` for network infrastructure intent.

- Rationale: `config/network.yaml` already exists as a file and remains the
  source of truth for host/service networking. A separate `config/networks/`
  namespace avoids a disruptive path migration while keeping infrastructure
  network intent separate from vendor-specific controller adapters.

- Impact: Cross-file references are required where network policy depends on
  service IPs or VLAN CIDRs from `config/network.yaml`. Adapter configuration
  must bind generic network intent to concrete controller resources.

- ADR: null

- Decision: Network automation starts read-only and dry-run-first.

- Rationale: Controller API coverage for full network configuration is not yet
  proven. Discovery and drift reporting are useful without risking gateway,
  switch, wireless, or ACL changes.

- Impact: Some Phase 4 criteria may remain documented/manual until API support
  is verified.

- ADR: null

- Decision: Mgmt VLAN 99 replaces adoption/default VLAN 1 for steady-state device management.

- Rationale: Default VLAN 1 is a common attack surface and should remain limited to initial
  adoption. Migrating management traffic to VLAN 99 with ACL-restricted access improves
  security posture.

- Impact: All device management interfaces must be re-addressed after initial VLAN migration.

- ADR: null

- Decision: Separate DNS pools (filtered vs clean) per VLAN purpose.

- Rationale: Services, Mgmt, DMZ, and Adoption need predictable clean DNS for infrastructure
  and recovery. General, IoT, Camera, Cast, and Guest need filtered DNS policy, with lighter
  filtering for Gaming/Cast where compatibility is more fragile and stricter filtering for
  IoT/Camera/Guest.

- Impact: DHCP Option 6 may differ between VLANs, or CoreDNS may apply source-CIDR policy
  while DHCP provides the same HA resolver pair everywhere. Devices cannot bypass local DNS
  due to ACL blocking outbound DoH/DoT.

- ADR: null

- Decision: WireGuard on ER605 rather than a separate VPN service.

- Rationale: ER605 firmware supports WireGuard natively via Omada. Running it on the gateway simplifies routing (no extra NAT hop) and keeps VPN traffic off the service hosts.

- Impact: VPN throughput is limited by ER605 CPU. Acceptable for a homelab with limited concurrent VPN clients.

- ADR: null

## Acceptance Criteria

- [ ] Document ER605 VLAN and routing configuration
- [ ] Controller API capability discovery records controller version, sites, and supported endpoint groups
- [ ] Controller capability matrix classifies each resource type as read-only, writable, or manual
- [ ] `config/networks/` desired-state schemas are drafted for all in-scope resource types
- [ ] Network intent schemas separate vendor-neutral intent from adapter-specific bindings
- [ ] Network render/normalization produces deterministic output without contacting the controller
- [ ] Network diff compares desired state with live controller state in read-only mode
- [ ] Network apply defaults to dry-run and requires an explicit live flag for writes
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
- [ ] Document Bonjour gateway rules (Cast → General)
- [ ] Document QoS DSCP marking and priority queuing rules
- [ ] Configure automated Omada site backups (daily/weekly/monthly)
- [ ] Validate Omada backup restore process
- [ ] Complete phased network deployment validation (core → VLANs → ACLs → wireless → VPN → QoS)

### Evidence

For each completed criterion, include:

- Implementation evidence: [screenshot, Omada export, or configuration description]
- Validation evidence: [API discovery output, dry-run diff, connectivity test, ACL test matrix, or backup restore test]

## Out of Scope

- Direct Abhaile host apply integration for network controller writes. Phase 4
  starts with a dedicated network tool and may integrate with host apply only
  after the adapter model is proven.
- Host networking (systemd-networkd, ipvlan-l2) — already handled by the
  render pipeline and `config/network.yaml`.
- Service-level DNS records — managed by CoreDNS via render pipeline.
- Automated firmware upgrade scheduling. Firmware status discovery may be
  included, but unattended firmware writes require a separate decision.
- Physical cabling and rack layout.
- ISP router/modem configuration upstream of ER605.

## Open Questions

1. **API coverage** — Which Omada Controller API endpoints can safely read and
   write VLANs, DHCP, ACLs, SSIDs, port profiles, WireGuard, QoS, and backups on
   the deployed controller version?

1. **Client implementation** — Should Abhaile call Omada endpoints directly or
   vendor/adapt an existing client library behind an Omada adapter? Current
   `tplink-omada-client` releases require Python 3.13, while Abhaile currently
   targets Python 3.10+.

1. **Config granularity** — Should `config/networks/` use one file per resource
   type, one file per device/site, or a generated normalized model split by
   both type and device?

1. **Vendor-neutral boundary** — Which capabilities are common enough to belong
   in the generic network intent model, and which should remain adapter-specific
   extensions?

1. **Backup automation** — Omada Controller supports scheduled backups
   internally. If an API can trigger or download backups, should Abhaile also
   copy backups to a second host outside the controller?

1. **CrowdSec bouncer on ER605** — CrowdSec can push blocklists to the ER605
   via ACL updates through the Omada API. Is this feasible with the current
   Omada Controller version? What's the latency and rule-count limit for
   dynamic ACL entries?

## References

- `config/network.yaml` (VLAN 20 and 100 definitions, service addressing)
- `config/networks/` (planned network desired-state root)
- `config/services/omada-controller/service.yaml` (Omada Controller service definition)
- `docs/net/PORTS.md` (port mapping documentation)
- `docs/NETWORK.md` (network topology overview)
- `docs/runbooks/operations.md` (break-glass procedures reference ER605 port 5)
- `.old_docs/TODO.md` Phase 4 (original task breakdown)
- Home Assistant TP-Link Omada integration:
  `https://www.home-assistant.io/integrations/tplink_omada/`
- `tplink-omada-client` PyPI project:
  `https://pypi.org/project/tplink-omada-client/`
