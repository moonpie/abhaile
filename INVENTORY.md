# Abhaile Infrastructure Inventory

Auto-generated from `config/mapping.yaml` and `config/network.yaml` (Updated: 2026-01-13)

## Quick Stats

- **Hosts:** 2
- **Deployed Services:** 12
- **VLANs:** 2
- **DNS Zones:** 4 internal, 1 external

## Network Topology

### VLANs

| VLAN | ID | CIDR | Gateway | IPvlan L2 Range |
| --- | --- | --- | --- | --- |
| services | 20 | 172.20.20.0/24 | 172.20.20.1 | 172.20.20.200-172.20.20.254 |
| dmz | 100 | 172.20.100.0/24 | 172.20.100.1 | 172.20.100.200-172.20.100.254 |

### DNS Zones

#### Internal Zones (CoreDNS)

- abhaile.home.arpa
- svc.abhaile.home.arpa
- 20.20.172.in-addr.arpa
- 100.20.172.in-addr.arpa

#### External Zones (deSEC)

- abhaile.dedyn.io

## Hosts Summary

### phobos

#### Network (phobos)

Network Device: `enp0s31f6`

Network Interfaces:

| Interface | Address | VLAN |
| --- | --- | --- |
| `enp0s31f6` | 172.20.20.10/24 | services |
| `ipvlan-l2` | 172.20.20.20/32 | services |
| `enp0s31f6.100` | 172.20.100.10/24 | dmz |
| `ipvlan-l2.100` | 172.20.100.20/32 | dmz |

#### Deployed Services (phobos)

10 services deployed:

- authelia
- blocky
- caddy-dmz
- caddy-internal
- chrony-a
- coredns-filtered
- ddclient
- omada-controller
- vault
- vault-agent

### deimos

#### Network (deimos)

Network Device: `enp0s31f6`

Network Interfaces:

| Interface | Address | VLAN |
| --- | --- | --- |
| `enp0s31f6` | 172.20.20.11/24 | services |
| `ipvlan-l2` | 172.20.20.21/32 | services |

#### Deployed Services (deimos)

3 services deployed:

- chrony-b
- coredns-clean
- vault-agent

## Service Catalog

| Service | Host | VLAN | IP |
| --- | --- | --- | --- |
| alertmanager | - | services | 172.20.20.211 |
| authelia | phobos | services | 172.20.20.201 |
| bazarr | - | services | 172.20.20.247 |
| blackbox-exporter | - | services | 172.20.20.213 |
| blocky | phobos | services | 172.20.20.234 |
| caddy-dmz | phobos | dmz | 172.20.100.200 |
| caddy-internal | phobos | services | 172.20.20.200 |
| chrony-a | phobos | services | 172.20.20.237 |
| chrony-b | deimos | services | 172.20.20.238 |
| coredns-clean | deimos | services | 172.20.20.236 |
| coredns-filtered | phobos | services | 172.20.20.235 |
| crowdsec | - | services | 172.20.20.207 |
| ddclient | phobos | - | - |
| esphome | - | services | 172.20.20.224 |
| flaresolverr | - | services | 172.20.20.250 |
| frigate | - | services | 172.20.20.226 |
| gluetun | - | services | 172.20.20.239 |
| go2rtc | - | services | 172.20.20.225 |
| grafana | - | services | 172.20.20.212 |
| home-assistant | - | services | 172.20.20.221 |
| homepage | - | services | 172.20.20.202 |
| immich | - | services | 172.20.20.240 |
| jellyfin | - | services | 172.20.20.241 |
| jellyseerr | - | services | 172.20.20.249 |
| librespeed | - | services | 172.20.20.216 |
| lidarr | - | services | 172.20.20.245 |
| loki | - | services | 172.20.20.218 |
| mosquitto | - | services | 172.20.20.222 |
| netbox | - | services | 172.20.20.203 |
| omada-controller | phobos | services | 172.20.20.220 |
| postfix | - | services | 172.20.20.206 |
| prometheus | - | services | 172.20.20.210 |
| prowlarr | - | services | 172.20.20.248 |
| radarr | - | services | 172.20.20.243 |
| readarr | - | services | 172.20.20.246 |
| smokeping | - | services | 172.20.20.217 |
| snmp-exporter | - | services | 172.20.20.214 |
| sonarr | - | services | 172.20.20.244 |
| tdarr | - | services | 172.20.20.242 |
| uptime-kuma | - | services | 172.20.20.215 |
| vault | phobos | services | 172.20.20.204 |
| vault-agent | phobos, deimos | - | - |
| vaultwarden | - | services | 172.20.20.205 |
| zigbee2mqtt | - | services | 172.20.20.223 |

______________________________________________________________________

*Generated from `config/mapping.yaml` and `config/network.yaml` artifacts*
