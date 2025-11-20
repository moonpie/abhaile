# Home Lab Network Design Specification - *abhaile*

## Overview

The **abhaile** home lab is an IPv4-only environment composed of:

* Two Debian-based hosts
  * Host networking managed by **systemd-networkd** and **systemd-resolved**
* TP-Link Omada SDN network fabric
* Fully segmented VLAN architecture
* Container runtime **Podman** with two patterns, managed via quadlets:
  * **Rootful ipvlan-l2** for containerized services, each with a **/32** on VLAN 20
  * **Rootless** only for helpers (e.g., Vault Agent), no LAN binds

This document specifies the *final design state* for implementation and maintenance, covering:

* Physical and logical topology
* Addressing and VLAN scheme
* Core services and roles
* Security, access, and ACL policy
* Boot, recovery, and operational procedures
* GitOps model and configuration layout

## Physical Infrastructure & Port Mapping

### Compute Hosts

|Host|Role|Hardware|OS / Stack|Notes|
|---|---|---|---|---|
|**phobos**|Infrastructure|Intel i7-3632QM, iGPU HD4000, Coral TPU|Debian + systemd|Infra, monitoring, automation, DMZ proxy|
|**deimos**|Media|Intel i7-3632QM, iGPU HD4000|Debian + systemd|Media & downloads|

### Network Devices

|Device|Model|Role|Notes|
|---|---|---|---|
|**Gateway**|TP-Link ER605|Router / VLAN gateway|WireGuard, NAT, DHCP, ACLs|
|**Core Switch**|TP-Link SG2218|L2 aggregation|RSTP root, some wired endpoints|
|**House Access Switch**|TP-Link SG2016P|L2 access|PoE for APs & cameras, some wired endpoints|
|**Garage Access Switch**|TP-Link SG2008P|L2 access|PoE for AP & cameras|
|**Access Points**|4x TP-Link EAP653|Wi-Fi 6 Access Point|Omada-managed, VLAN trunks|
|**Zigbee Coordinator**|SMLight SLZB-06|IoT gateway (PoE)|On VLAN 50|

### Switch Port Mappings

#### Gateway (ER605)

|Port|Connection|Notes|
|---|---|---|
|1|WAN|ISP uplink|
|2|Core Switch (port 16)|Trunk (all VLANs, native VLAN 99)|
|3-4| - |Spare|
|5|Break-glass|Untagged VLAN 1 (initial adoption)|

#### Core Switch (SG2218)

|Port|Connection|Profile|Notes|
|---|---|---|---|
|1|phobos|TRUNK-Phobos|Native VLAN 20; tagged VLAN 100|
|2|deimos|ACCESS-Services (VLAN 20)| - |
|3-12|Wired endpoints|ACCESS-General (VLAN 30)|User devices|
|13|House Access Switch (port 16)|TRUNK-AccessSwitch|Uplink|
|14| - |Spare| - |
|15|Garage Access Switch (port 8)|TRUNK-AccessSwitch|Uplink|
|16|Gateway (port 2)|TRUNK-Core|Uplink|
|17-18| - |Spare|SFP Slots|

Switch safeguards:

* Storm control & MAC limiting on TRUNK-Phobos
* BPDU Guard enabled on all access ports, disabled on trunks

#### House Access Switch (SG2016P)

|Port|Connection|Profile|Notes|
|---|---|---|---|
|1|Kitchen AP|AP-Uplink (trunk)|PoE|
|2|Hallway AP|AP-Uplink (trunk)|PoE|
|3|Sitting Room AP|AP-Uplink (trunk)|PoE|
|4-7|Cameras|ACCESS-Cameras (VLAN 60)|PoE|
|8|Zigbee Coordinator SLZB-06|ACCESS-IoT (VLAN 50)|PoE, intra-VLAN isolation|
|9-10| - |Spare| - |
|11-14|Wired endpoint|ACCESS-General (VLAN 30)|User devices|
|15| - |Spare| - |
|16|Core Switch (port 13)|TRUNK-AccessSwitch|Uplink|

#### Garage Access Switch (SG2008P)

|Port|Connection|Profile|Notes|
|---|---|---|---|
|1|Garage AP|AP-Uplink (trunk)|PoE|
|2-4|Cameras|ACCESS-Cameras (VLAN 60)|PoE|
|5-7| - |Spare| - |
|8|Core Switch (port 15)|TRUNK-AccessSwitch|Uplink|

## Logical Network Design & Addressing

### IPv6 Policy

IPv6 is disabled on all elements (ER605, APs, VLAN interfaces, hosts, Podman). Block IPv6 at the gateway to avoid unsolicited RA / DHCPv6 and DNS leakage

### Topology

```text
                ┌─────────────┐
   WAN ─────────┤    ER605    │
                │             │
                └──────┬──────┘
                       │ (LAN)
                       │
                ┌──────┴──────┐
                │    SG2218   │  ← Core / Distribution
                │             │
                └──────┬──────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
┌──────┴──────┐ ┌──────┴──────┐        ├─ phobos (.10)
│   SG2008P   │ │   SG2016P   │        ├─ deimos (.100)
│   (Garage)  │ │   (Attic)   │        └─ 10x Wired Endpoints
└┬────────────┘ └┬────────────┘        └─ 1x Spare
 │               │                     └─ 2x Spare (SFP)
 ├─ 1x EAP       ├─ 3x EAP
 └─ 3x Camera    ├─ 4x Camera
 └─ 3x Spare     ├─ 1x ZigBee
                 └─ 4x Wired Endpoints
                 └─ 3x Spare

```

* IGMP snooping: enabled globally

### VLANs & Subnets

Convention:

* `172.20.<VLAN>.0/24` for all VLANs
  * except VLAN 1 (Adoption): `192.168.0.0/24`
* Gateway at `172.20.<VLAN>.1`

|VLAN|Name|Purpose|Subnet|DHCP|Notes|
|---|---|---|---|---|---|
|1|Adoption (Default)|Temporary adoption|192.168.0.0/24|ON|Only for adoption / emergency|
|99|Mgmt|Admin / Device management|172.20.99.0/24|ON|Switches, APs, admin access|
|20|Services|Hosts & services|172.20.20.0/24|ON|phobos, deimos|
|30|General|User devices|172.20.30.0/24|ON|Phones, laptops|
|40|Gaming|Consoles / gaming devices|172.20.40.0/24|ON|QoS-prioritized|
|50|IoT|Smart home / IoT devices|172.20.50.0/24|ON|Clean DNS only (`172.20.20.236`); No WAN access|
|60|Camera|IP cameras|172.20.60.0/24|ON|No WAN access; intra-VLAN isolation|
|70|Cast|mDNS / cast bridge|172.20.70.0/24|ON|Bonjour to VLAN 20|
|80|Guest|Visitors|172.20.80.0/24|ON|WAN & HTTPS to DMZ only|
|90|VPN|WireGuard clients|172.20.90.0/24|OFF|Peer IPs only|
|100|DMZ|Reverse proxy|172.20.100.0/24|ON|phobos DMZ|

#### Address Allocation Guidelines

* `.1`: Gateway
* `.2–.9`: Reserved for infrastructure (switches, controllers)
* `.10–.29`: Static pool - assigned to hosts and services
* `.30–.99`: DHCP / reservation pool
* `.100–.199`: Dynamic DHCP pool
* `.200–.254`: Future spare addresses
  * Movable `/32` addresses on Services VLAN (20) use this range

### Wi-Fi SSIDs & VLAN Mapping

|SSID|VLAN|Band|Visibility|Security|Notes|
|---|---|---|---|---|---|
|an t-idirlion|30|Dual (2.4 / 5 GHz)|Visible|WPA2 / WPA3|General user devices|
|an t-idirlion.gaming|40|5 GHz only|Hidden|WPA2|Gaming consoles (prioritized)|
|an t-idirlion.iot|50|2.4 GHz only|Hidden|WPA2|IoT devices; PMF optional; 11k/v/r off|
|an t-idirlion.cast|70|Dual (2.4 / 5 GHz)|Hidden|WPA2|Chromecast, mDNS bridging|
|an t-idirlion.guest|80|Dual (2.4 / 5 GHz)|Visible|WPA2|Guests; isolation on|
|an t-idirlion.mgmt|99|Dual (2.4 / 5 GHz)|Hidden|WPA2 / WPA3|Admin / infrastructure access|

### Inter-VLAN Access & ACL Policy

* **Default**: Deny all inter-VLAN traffic (top-level ACL on ER605)
* **Explicit Allow**:

  |From --> To|Ports / Protocols|Use Case|
  |---|---|---|
  |VLAN 20 --> VLAN 60|RTSP (554), HTTP / HTTPS|NVR / infra controls cameras|
  |VLAN 20 <--> VLAN 50|MQTT (1883 / 8883), TCP 6638|Service <--> IoT|
  |VLAN 70 --> VLAN 20|App-specific (e.g., Jellyfin / casting)|Cast bridge targets|
  |VLAN 99 --> All LANs|SSH, HTTPS, SNMP|Management|
  |VLAN 90 --> VLAN 20|Full access|VPN admin / users --> services|
  |VLAN 80 --> VLAN 100|HTTPS only|Guest --> DMZ sites|

* **Explicit Deny**:
  * VLAN 50 (IoT) --> WAN (except DNS / NTP to internal servers)
  * VLAN 60 (Cameras) --> WAN
  * Any VLAN --> VLAN 99 (Mgmt) (except explicit admin flows above)
  * Hosts using external DNS / DoT / DoH to WAN (force internal resolvers)
  * UDP/123 (NTP) to WAN blocked (except admin / VPN peers)

#### Enforcement notes

* Push DNS / NTP via DHCP (Options 6 / 42) and firewall to prevent bypass
* Maintain DoH / DoT blocklist (IP + SNI) at `/opt/abhaile/config/firewall/doh-blocklist.yaml` (auto-refreshed monthly)

## Core Network Services

### DHCP

Server: **ER605**

* **Option 6 (DNS)**: `172.20.20.235`, `172.20.20.236`
  * VLAN 50 override: **`172.20.20.236` only** (Clean DNS)
* **Option 42 (NTP)**: `172.20.20.237`, `172.20.20.238`
* **Option 15 / 119 (Domain / Search)**: `home.arpa`

### DNS

Two **CoreDNS** instances (authoritative + recursive stubs) with identical zones

|Role|Host|IP|Behavior|
|---|---|---|---|
|Filtered|phobos|172.20.20.235|Local zones; forwards --> **Blocky** --> Upstream|
|Clean|deimos|172.20.20.236|Local zones; forwards directly to Upstream|

* Split-horizon:
  * Service IPs under `*.svc.abhaile.home.arpa` (**A records** mapping to ipvlan-2 /32s)
  * Internal services under `*.abhaile.home.arpa` (**CNAME records** for user-facing FQDNs)
  * Default: `*.abhaile.home.arpa` **CNAME --> internal Caddy** `/32` (172.20.20.200)
  * Explicit bypass: `*.abhaile.home.arpa CNAME *.svc.abhaile.home.arpa` if not fronted by Caddy
  * DMZ mirrors `*.abhaile.dedyn.io` --> `172.20.100.200` (DMZ Caddy). No internal redirection otherwise
* Upstreams:
  * Quad9 (`9.9.9.9`, `149.112.112.112`)
  * Cloudflare (`1.1.1.1`, `1.0.0.1`)
  * DNSSEC: enabled
  * EDNS Client Subnet: disabled
* Reverse zones:
  * `20.20.172.in-addr.arpa` (Services VLAN 20)
  * `99.20.172.in-addr.arpa` (Mgmt VLAN 99)
  * `100.20.172.in-addr.arpa` (DMZ VLAN 100)
* Outbound DNS/DoT to WAN: **blocked**
* Omada plugin provides dynamic records for **devices/clients** only (not services)

#### Blocky

|Role|Host|IP|Behavior|
|---|---|---|---|
|Ad-Block DNS|phobos|172.20.20.234|Filters DNS requests|

* Blocklists: OISD Full
  * *TODO:* Investigate
* Response: `0.0.0.0` with category logging
* Enforced SafeSearch / Restricted Mode

### NTP

Two **Chrony** instances:

|Role|Host|IP|Behavior|
|---|---|---|---|
|NTP-A|phobos|172.20.20.237|Local NTP server|
|NTP-B|deimos|172.20.20.238|Redundant NTP server|

* Upstreams:
  * `pool.ntp.org`
  * `time.google.com`
* Local servers (peers to each other)
  * `172.20.20.237`
  * `172.20.20.238`

### Certificates & TLS

Two **Caddy** instances:

|Role|Host|IP|Behavior|
|---|---|---|---|
|Internal|phobos|172.20.20.200|Fronts all HTTP service `/32` IPs|
|DMZ|phobos|172.20.100.200|Public reverse proxy via DNS-01 ACME|

* **Internal domain**: `home.arpa`
  * Issued via Caddy with `tls internal`
  * Published for trust bootstrap at `https://ca.abhaile.home.arpa/abhaile-ca.crt`
* **External domain**: `abhaile.dedyn.io`
  * Issued externally via DNS-01 using deSEC, no EAB (handled by DMZ Caddy)
* NAT loopback (hairpin NAT) is enabled on ER605 to allow internal clients to reach `*.abhaile.dedyn.io`
  * No WAN exposure except explicitly configured DMZ sites

**Security headers**: Standard security headers (CSP default-src 'self'; Referrer-Policy; X-Frame-Options DENY; etc.)

**HSTS**: **Enabled** on DMZ (1y, includeSubDomains, preload); **Disabled** on Internal

**deSEC token handling**: stored in Vault; Vault Agent templates render `/etc/caddy/dns.env`

### Omada Controller

* Running as rootful container with `ipvlan` networking
* FQDN: `omada.abhaile.home.arpa`
* Reachable from **VLAN 99** (admin) and from **VLAN 20** via Caddy (per admin access rules)

### Access Control & SSO (Authelia)

* **SSO enforced**:
  * All `*.abhaile.dedyn.io` (DMZ sites)
  * Admin / infra apps on VLAN 20 (Vault, NetBox, Prometheus, Grafana, etc.)
* **SSO not enforced**:
  * Jellyfin, Home Assistant, Mosquitto, Zigbee2MQTT, Omada Controller (on VLAN 20)
* Identity backend: local YAML (future: LDAP)
* MFA: TOTP (future: WebAuthn)
* RBAC groups: `admins`, `users`, `guests`
* DMZ exposure: **none** by default; explicit opt-in per site

### Admin & Remote Access

|Method|VLAN|Purpose|
|---|---|---|
|Wired admin|99|Direct infra access|
|SSID `an t-idirlion.mgmt`|99|Wireless admin access|
|WireGuard VPN|90|Remote user / admin|

Controls:

* ACL `ALLOW-MGMT-to-Devices`: VLAN 99 --> VLAN 20 for SSH / HTTPS / SNMP
* No other VLAN may reach VLAN 99
* Omada/ER605 UIs restricted to VLAN 99 sources
* Admin SSID keys rotated periodically; admin device IPs allowlisted on ER605
* LLDP + descriptive device names on all gear

#### Break-glass

* ER605 port 5: untagged VLAN 1
* Maintain a laptop with static IP + local admin creds; rotate quarterly; store in Vault / Vaultwarden

### WireGuard VPN

#### Server (ER605)

* `wg0` = `172.20.90.1/24` (UDP 51820)
* Endpoint: `vpn.abhaile.dedyn.io`
* ACL: VLAN 90 --> VLAN 20 only
* MTU: 1420
* PersistentKeepalive=25
* Hairpin NAT for DMZ consistency

#### Client Profiles

|Profile|Tunnel|Peer IP|DNS|Allowed IPs|Notes|
|---|---|---|---|---|---|
|admin|Full|`172.20.90.10/24`|`172.20.20.236`|`0.0.0.0/0`, `172.20.20.0/24`|Clean DNS only; WAN via VPN allowed|
|user|Split|`172.20.90.20/24`|`172.20.20.235`, `172.20.20.236`|`172.20.20.0/24`|Filtered then Clean fallback|
|travel|Split|`172.20.90.30/24`|`172.20.20.235`,`172.20.20.236`|`172.20.20.0/24`, `172.20.70.0/24`, `172.20.100.0/24`|Adds Cast & DMZ|

* Clients enforce DNS to `172.20.20.235`, `172.20.20.236` - others blocked

## IP Assignments & Service Layout

### Host Interfaces & Core Addresses

|Host|VLAN|IP|Role|
|---|---|---|---|
|phobos|20|172.20.20.10|Primary|
|phobos|20|172.20.20.20|ipvlan shim|
|phobos|100|172.20.100.10|DMZ / reverse proxy|
|phobos|100|172.20.100.20|DMZ ipvlan shim|
|deimos|20|172.20.20.11|Primary|
|deimos|20|172.20.20.21|ipvlan shim|

#### Service `/32` Addresses & Management

* Assigned as secondary `/32` addresses on VLAN 20
  * **Host services** (CoreDNS/Chrony) bind to specific `/32`s on the host
    * `/32` addresses must be configured on the host's ipvlan shim interface
  * **Container services** receive dedicated `/32` addresses via **ipvlan-l2** networks (rootful Podman)
    * Pods only when components must share one netns (e.g., app+DB+cache)
    * Otherwise **per-service /32** for telemetry/ACLs
* On service migration:
  1. Remove from old host
  1. Add to new host
  1. Send gratuitous ARP
* HTTP apps are fronted by **Internal Caddy** unless explicitly bypassed

### Ingress, Auth & UI Services

|Service|Host|Mode|IP|Ports|Notes|
|---|---|---|---|---|---|
|Caddy (DMZ)|phobos|Container|172.20.100.200|80, 443|Public proxy for `*.abhaile.dedyn.io`|
|Caddy (Internal)|phobos|Container|172.20.20.200|80, 443|SSO/TLS for `*.abhaile.home.arpa`|
|Authelia|phobos|Container|172.20.20.201|9091|SSO IdP; proxied per-host via Caddy|
|Homepage|phobos|Container|172.20.20.202|3000|Landing dashboard|
|NetBox|phobos|Pod (app+DB+Redis on localhost)|172.20.20.203|8000|DB/Redis in pod|

### Networking, Core Infrastructure & Abuse Protection

|Service|Host|Mode|IP|Ports|Notes|
|---|---|---|---|---|---|
|Vault|phobos|Container|172.20.20.204|8200|UI via Caddy; agents may go direct or via Caddy|
|Vaultwarden|phobos|Container|172.20.20.205|8080|Bitwarden-compatible|
|Postfix (SMTP relay)|phobos|Container|172.20.20.206|25 (SMTP), 587 (Submission, optional)|LAN relay for services; restrict by VLAN/hosts|
|Fail2ban|Both|Host| - | - |nftables bans|
|CrowdSec|phobos|Container|172.20.20.207|8080 (API)|Bouncer integrates w/ ER605|
|Omada Controller|phobos|Container|172.20.20.220|8043, 8088, 29814/29815| - |
|Blocky|phobos|Container|172.20.20.234|8053/tcp,udp (+ 4000/metrics)|Ad-block DNS (enable HTTP :4000 for metrics)|
|CoreDNS (Filtered)|phobos|Host|172.20.20.235|53/tcp, 53/udp|Forwards --> Blocky|
|CoreDNS (Clean)|deimos|Host|172.20.20.236|53/tcp, 53/udp|Forwards --> Quad9/CF|
|Chrony A|phobos|Host|172.20.20.237|123/udp|NTP server A|
|Chrony B|deimos|Host|172.20.20.238|123/udp|NTP server B|

### Monitoring & Observability

|Service|Host|Mode|IP|Ports|Notes|
|---|---|---|---|---|---|
|Prometheus|phobos|Container|172.20.20.210|9090| - |
|Alertmanager|phobos|Container|172.20.20.211|9093| - |
|Grafana|phobos|Container|172.20.20.212|3000|Dashboards|
|node_exporter|Both|Host|host IP|9100|Host metrics|
|podman_exporter|Both|Host|host IP|9882|Container metrics|
|blackbox_exporter|phobos|Container|172.20.20.213|9115|Probes `*.abhaile.home.arpa` & `*.svc.abhaile.home.arpa`|
|snmp_exporter|phobos|Container|172.20.20.214|9116|Polls ER605/switches/APs|
|Uptime Kuma|phobos|Container|172.20.20.215|3001|Status page|
|Librespeed|phobos|Container|172.20.20.216|3010|LAN speed test|
|SmokePing|phobos|Container|172.20.20.217|8022|Latency/jitter graphs|
|Promtail|Both|Host|host IP|9080|Ships logs --> Loki|
|Loki|phobos|Container|172.20.20.218|3100|Log store|

### Surveillance, Home Automation & IoT

|Service|Host|Mode|IP|Ports|Notes|
|---|---|---|---|---|---|
|Home Assistant|phobos|Container|172.20.20.221|8123|SSO via Caddy|
|Mosquitto (MQTT)|phobos|Container|172.20.20.222|1883, 8883|Broker for HA/Z2M/Frigate|
|Zigbee2MQTT|phobos|Container|172.20.20.223|8080|UI; MQTT targets `.222`|
|ESPHome|phobos|Container|172.20.20.224|6052| - |
|go2rtc|phobos|Container|172.20.20.225|1984, 8554|Restream|
|Frigate (NVR)|phobos|Container|172.20.20.226|5000 (UI), 8554 (RTSP)|Coral TPU|

### Media & Entertainment

|Service|Host|Mode|IP|Ports|Notes|
|---|---|---|---|---|---|
|Gluetun (VPN)|deimos|Container|172.20.20.239|51820/udp (+provider pfwd)|qB shares netns|
|qBittorrent|deimos|Container (Network=container:gluetun)|shares gluetun netns|8080| - |
|Immich|deimos|Pod (app+DB+Redis on localhost)|172.20.20.240|2283|DB/Redis in pod|
|Jellyfin|deimos|Container|172.20.20.241|8096|VAAPI; render group|
|Tdarr|deimos|Container|172.20.20.242|8265|Transcoding|
|Radarr|deimos|Container|172.20.20.243|7878| - |
|Sonarr|deimos|Container|172.20.20.244|8989| - |
|Lidarr|deimos|Container|172.20.20.245|8686| - |
|Readarr|deimos|Container|172.20.20.246|8787| - |
|Bazarr|deimos|Container|172.20.20.247|6767| - |
|Prowlarr|deimos|Container|172.20.20.248|9696| - |
|Jellyseerr|deimos|Container|172.20.20.249|5055| - |
|Flaresolverr|deimos|Container|172.20.20.250|8191| - |

qBittorrent / Gluetun isolation:

* `Network=container:gluetun`; qBittorrent publishes **no ports**
* Start order enforced (Gluetun before qBittorrent)
* Kill-switch: nftables per-UID egress bound to Gluetun + policy routing table `vpn`

## QoS, RSTP, IGMP / mDNS

### Quality of Service (QoS)

* High: VLAN 40 (Gaming) --> WAN
  * mark EF / CS6 at ER605
  * trust on trunks / AP uplinks
* Normal: VLAN 30, VLAN 70
* Low: VLAN 50, VLAN 60

### Spanning Tree (RSTP)

* Enabled globally; root = SG2218 (prio 4096); secondary = SG2016P (prio 8192)
* Portfast on end-host / AP ports; BPDU Guard on access ports

### IGMP / mDNS Bridging

* IGMP snooping globally; IGMP querier on VLAN 20 and 70
* Bonjour gateway (one-way) VLAN 70 --> VLAN 20 for `_googlecast._tcp`, `_airplay._tcp`, `_spotify-connect._tcp`
* Multicast enhancements enabled on APs

## Security & Host Hardening

* Block outbound DoH / DoT to WAN (monthly refreshed blocklist)
* Block UDP/123 to WAN **except** admin / VPN peers
  * Force LAN NTP servers
* Disable UPnP / NAT-PMP
  * Exception: VLAN 40 (Gaming)
* VLAN 60 (Camera): client isolation
  * Only Frigate / NVR may access cameras
* `/32` service IPs with ARP announce
  * Host services via `systemd-networkd` drop-ins
  * Container services via ipvlan networks
* nftables:
  * Default deny inbound; allow only required ports
  * Permit outbound: Debian mirrors, ACME, internal DNS, WireGuard to ER605, SMTP relay, NTP to LAN, SNMP to LAN gear
  * Enforce per-UID VPN routing for qBittorrent (egress restricted to Gluetun)
* CrowdSec:
  * ER605 gateway bouncer; mirror ban decisions to hosts
  * **Access restricted** to Admin/VPN + Prometheus (nftables + ER605 ACL)
  * **No auto-blocks for LAN sources** (alert-only)
* Fail2ban on hosts (nftables actions)
* SNMP community `abhaile-ro` stored in Vault

### Vault / Secrets

* Vault on phobos (Integrated Storage / Raft at `/srv/vault/data`)
* Init: 2-of-3 unseal; keys in SOPS-encrypted file + offline printed copy
* Unseal at boot via `abhaile-vault-unseal.service`:
  1. Decrypt SOPS file with host age / GPG key;
  1. Submit unseal keys; wait until active
* Vault Agent templates render env files (Caddy, Authelia, CrowdSec, SMTP) and trigger reloads
  * Watcher copies Agent outputs into /srv/\<svc>/config

## Observability

* **Prometheus + Alertmanager**: metrics collection / alerts
  * SNMP v2c (read-only) on network devices via `snmp_exporter` (60s)
  * Enable metrics: CoreDNS (`:9153`), Blocky (`:4000/metrics`), Caddy (`/metrics`), Authelia (`/metrics`), Vault (`/v1/sys/metrics`), Loki (`/metrics`)
* **SmokePing**: latency/jitter per critical `/32` (DNS, MQTT, Frigate, Vault, Caddy)
* **Loki + Promtail**: central logs
  * Syslog (UDP 514 / TCP 1514) from Omada / ER605 / switches --> Promtail --> Loki
  * Retention: Infra 30d; Apps 7d
* **Blackbox exporter**: probes internal and DMZ
  * Internal: `*.abhaile.home.arpa` (via internal Caddy) and `*.svc.abhaile.home.arpa` (direct)
  * DMZ: `*.abhaile.dedyn.io` (via DMZ Caddy (hairpin OK))
* **Uptime Kuma**: UI checks; complementary to Blackbox; status landing page
* Alert delivery: email (credentials / targets via Vault)

External probe targets: `1.1.1.1`, `9.9.9.9`, `desec.io`, `deb.debian.org`, `abhaile.dedyn.io`

### Core targets (Prometheus jobs)

* node_exporter: phobos:9100, deimos:9100
* podman_exporter: phobos:9882, deimos:9882
* CoreDNS (enable plugin prometheus :9153 on both):
  * 172.20.20.235:9153 (Filtered), 172.20.20.236:9153 (Clean)
* Blocky (httpPort: 4000 + prometheus.enable: true): 172.20.20.234:4000/metrics
* Chrony: via node_exporter textfile or use chrony_exporter (optional)
* Caddy (internal & DMZ): enable global prometheus module in Caddyfile:
  * Internal: 172.20.20.200:2019/metrics (admin API) --> or expose :metrics listener as configured
  * DMZ: 172.20.100.200:2019/metrics
* Authelia: enable telemetry.prometheus: true --> 172.20.20.201:9091/metrics
* Vault: telemetry { prometheus_retention_time = "24h" } --> 172.20.20.204:8200/v1/sys/metrics?format=prometheus
* Mosquitto: use prometheus-mqtt-exporter or mosquitto-exporter (recommend a tiny exporter container bound to .? ? ?)
* Omada devices: snmp_exporter scraping ER605 + SG/Switches + APs:
  * 172.20.20.214:9116 with per-device modules
* Loki: 172.20.20.218:3100/metrics
* Prometheus / Alertmanager: native metrics at :9090/metrics, :9093/metrics
* Grafana: 172.20.20.212:3000/metrics (enable metrics_enabled = true)
* Blackbox Exporter: 172.20.20.213:9115/metrics (jobs for https://*.abhaile.home.arpa, TCP 53, TCP 25, TCP 8200, etc.)
* Uptime Kuma / Librespeed / SmokePing: use Blackbox to probe their UIs; SmokePing runs its own ICMP/latency stores (optionally expose a small exporter if desired).
* Frigate: optional frigate-exporter (3rd-party) --> otherwise Blackbox the UI and RTSP TCP connect
* Jellyfin/Immich: optional community exporters; otherwise Blackbox on UIs
* qBittorrent/Gluetun: Blackbox TCP to the WebUI if exposed; add a custom exporter for VPN status (or script to /metrics via node_exporter textfile)

### Blackbox probe set (examples)

* `https://authelia.abhaile.home.arpa`, `https://vault.abhaile.home.arpa`, `https://homeassistant.abhaile.home.arpa`, all main UIs
* `tcp://172.20.20.235:53`, `tcp://172.20.20.236:53` (DNS listeners)
* `tcp://172.20.20.222:1883` (MQTT), `tcp://172.20.20.206:25` (SMTP)
* `tcp://172.20.20.239:8200` (Vault), `tcp://172.20.20.218:3100` (Loki)
* `https://*.abhaile.dedyn.io` through DMZ Caddy (hairpin path)

### Optional add-on exporters

* chrony_exporter, smartctl_exporter, node_exporter textfile for custom counters (e.g., nftables bytes/packets per /32)
* ups_exporter if ever attach a UPS (NUT)

## Boot, Recovery & Operations

### Boot / Dependency Order

1. `network-online.target`
1. Chrony --> CoreDNS --> Blocky
1. Vault (sealed) --> unseal via `abhaile-vault-unseal.service` --> `vault-ready.service`
1. Authelia, DMZ Caddy, SMTP (wait on `vault-ready`)
1. Internal Caddy (`tls internal`)
1. Application services (Omada, NetBox, Home Assistant, etc.)
1. Monitoring & protection (exporters, CrowdSec, Fail2ban)

`qBittorrent` remains **offline** if `Gluetun` unavailable

Prefer reloads over restarts for Caddy, CoreDNS, Authelia (unless unsupported)

Drift detection stores checksums under `/var/lib/abhaile/state/`

### Filesystem Layout

```text
/
├─ opt/abhaile/                                 # Git repo (read-only by convention)
├─ etc/
│  ├─ containers/systemd/                       # Rootful quadlets
│  └─ systemd/
│     ├─ networkd/
│     ├─ resolved.conf
│     └─ system/
├─ home/abhaile/.config/containers/systemd/     # Rootless quadlets
├─ srv/
│  ├─ media/                                    # Shared media root
│  └─ <service>/{config,data}/
└─ var/
   ├─ cache/<service>/                          # Ephemeral cache
   └─ lib/abhaile/
      ├─ rendered/                              # Rendered configs
      └─ state/                                 # Checksums, diff snapshots
```

* ext4
* `noatime`; `_netdev` for network-dependent mounts

## GitOps & Orchestration

### Model

Hybrid approach:

* **Declarative orchestrator** (Python 3.12) for templating / validation / Omada API
* **Host apply layer** (Bash) for atomic writes / reloads / system control

Hosted on GitHub with Actions CI/CD (schema validation, linting, rendering, inventory)
All commits to `main` are signed; protected branch rules require green CI

### Repository Layout

```text
abhaile/
├── config/                    # Host / service / network / mappings (YAML)
├── schemas/                   # JSON schemas
├── tools/
│   ├── orchestrate.py         # Main orchestrator
│   ├── validate.py            # Lint / schema checking
│   ├── inventory_gen.py
│   ├── caddy_build.py
│   ├── coredns_build.py
│   ├── hashing.py
│   └── bash/
│       ├── lib.sh
│       ├── host_apply.sh
│       ├── quadlet_apply.sh
│       ├── caddy_apply.sh
│       ├── coredns_apply.sh
│       └── vault_unseal.sh
└── systemd/
    ├── git-sync@.service
    ├── git-sync@.timer
    └── abhaile-vault-unseal.service
```

CI auto-generates `INVENTORY.md` (Service|Host|VLAN|IP|Ports|Internal FQDN|Public FQDN|Notes)
Renovate manages Container image / Actions / Python / pre-commit versions

### Deployment Workflow

1. `git-sync@<host>.timer` pulls `/opt/abhaile` (every 5 min ± 0-60s jitter)
1. `tools/orchestrate.py` phases: `render --> host --> services --> caddy --> coredns`
1. Outputs to `/var/lib/abhaile/rendered/`; checksums to `/var/lib/abhaile/state/`
1. Bash helpers atomically replace files; trigger targeted reloads / restarts
1. Quadlet changes batch `daemon-reload`; Caddy / CoreDNS reload only on config change
1. Post-apply blackbox probe verifies health before success

Defaults: dry-run; `--apply` required for live apply
Omada changes follow plan --> review --> apply gating

### Secrets & Vault Integration

* Bootstrap: secrets in Git (SOPS / age); decrypted at runtime
* Runtime: Vault Agent templates feed services and trigger reloads
* Secret paths: `secret/abhaile/<service>`

### CI / Policy

* `make render` in CI; JSON Schema validation; `systemd-analyze verify`
* OPA / Conftest enforce policy; linting: yamllint, shellcheck, markdownlint, gitleaks
* Drift detection compares live unit hashes vs last applied
* Nightly CI (02:00 - 04:00 Europe/Dublin) for heavy jobs; light validation per PR

## Runbook

### Normal Startup / Recovery

1. System / network / mounts online
1. Vault starts sealed --> unseal job runs
1. Git sync --> orchestrator runs
1. Config applied; services start / reload in order
1. Monitoring active; lab operational

### Daily & Maintenance

* All changes via Git; no manual host edits
* Secrets via Vault and Agent templates
* Monitor Prometheus / Loki / Alertmanager
* Service migration: move `/32` + gratuitous ARP
* After ACL / DNS changes: validate reachability and policy
* Document / commit changes

Utilities:

* `make cordon <host>` - stop new placements
* `make drain <host>` - migrate `/32` services
* `make bootstrap <host>` - generate `dist/bootstrap-<host>.sh`

**Ops window:** 02:00-04:00 local (Europe/Dublin, UTF-8)

### Network Implementation Phases

1. **Core init**: ER605 / switches / APs on VLAN 1; bring up VLAN 99 + trunks
1. **VLANs / Subnets**: create VLANs; validate DHCP scopes
1. **Permissive ACLs**: broad allows; validate (e.g., 20<-->99, 20-->60)
1. **Wireless**: SSIDs bound to VLANs; validate DHCP / isolation
1. **Tighten ACLs**: enforce DNS / NTP / IoT blocks
1. **VPN**: deploy WireGuard; validate profiles
1. **QoS / Multicast**: confirm DSCP & IGMP querier
1. **Monitoring / Backups**: SNMP + syslog; Omada backups
1. **Docs/GitOps export**: export Omada site config to `/opt/abhaile/backups/omada/`

## Backup, Validation & Versioning

* Backup: `/etc/coredns`, `/etc/caddy`, systemd units/quadlets, app configs, Vault snapshots
  Schedule: daily local + weekly NAS + monthly restore test
* CoreDNS: bump zone serials on change
* `caddy validate` in CI & pre-deploy
* Omada backups: Daily (retain 7) / Weekly (retain 4) / Monthly (retain 3); export to `phobos:/opt/abhaile/backups/omada/`
* Git = source of truth; CI ensures reproducibility and rollback

## Maintenance & Lifecycle

* Drift Detection: checksums; diffs surfaced in CI
* Secrets Rotation: scheduled for SMTP, PIA, deSEC
* Inventory Automation: CI updates `INVENTORY.md` in active PR
* Commit Policy: signed commits; Conventional Commits
* Docs: MkDocs auto-generated from schemas

## Future Notes

* Potential LACP uplink: SG2218 <--> SG2016P secondary trunk
* VLAN 1 DHCP stays disabled (emergency adoption only)
* Consider selective IPv6 re-enable if PD needed from ISP
* Set resource limits via Quadlet for heavy apps (Frigate / Immich / Tdarr / Jellyfin), e.g., `CPUQuota=200%`, `MemoryMax=4G`
* Add Matrix / Telegram secondary alerts (gateway / DNS / Vault sealed)
* Apply CIS-lite baseline: disable unused protocols; `rp_filter=strict`; SYN cookies; FS hardening; minimal `auditd`; SSH hardening (no passwords for admins); tuned logrotate
