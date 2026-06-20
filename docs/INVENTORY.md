# Abhaile Infrastructure Inventory

Generated: 2026-06-07T15:32:38Z

## VLAN Summary

| VLAN | ID | CIDR | Gateway | ipvlan-l2 Range |
|------|----|------|---------|-----------------|
| services | 20 | 172.20.20.0/24 | 172.20.20.1 | 172.20.20.200-172.20.20.254 |
| dmz | 100 | 172.20.100.0/24 | 172.20.100.1 | 172.20.100.200-172.20.100.254 |

## Hosts

### deimos

| Interface | Address | VLAN |
|-----------|---------|------|
| enp0s31f6 | 172.20.20.11/24 | services |
| ipvlan-l2 | 172.20.20.21/32 | services |

### phobos

| Interface | Address | VLAN |
|-----------|---------|------|
| enp0s31f6 | 172.20.20.10/24 | services |
| enp0s31f6.100 | 172.20.100.10/24 | dmz |
| ipvlan-l2 | 172.20.20.20/32 | services |
| ipvlan-l2.100 | 172.20.100.20/32 | dmz |

## Services by Host

### deimos (3 services)

| Service | Address | VLAN | Network Mode |
|---------|---------|------|--------------|
| chrony-b | 172.20.20.238/32 | services | service-32 |
| coredns-clean | 172.20.20.236/32 | services | service-32 |
| vault-agent | - | - | host |

### phobos (10 services)

| Service | Address | VLAN | Network Mode |
|---------|---------|------|--------------|
| ddclient | - | - | host |
| chrony-a | 172.20.20.237/32 | services | service-32 |
| coredns-filtered | 172.20.20.235/32 | services | service-32 |
| blocky | 172.20.20.234/32 | services | ipvlan-l2 |
| caddy-internal | 172.20.20.200/32 | services | ipvlan-l2 |
| caddy-dmz | 172.20.100.200/32 | dmz | ipvlan-l2 |
| vault | 172.20.20.204/32 | services | ipvlan-l2 |
| vault-agent | - | - | host |
| authelia | 172.20.20.201/32 | services | ipvlan-l2 |
| omada-controller | 172.20.20.220/32 | services | ipvlan-l2 |

## Address Allocation

| Address | Service/Host | VLAN |
|---------|--------------|------|
| 172.20.20.10/24 | phobos/enp0s31f6 | services |
| 172.20.20.11/24 | deimos/enp0s31f6 | services |
| 172.20.20.20/32 | phobos/ipvlan-l2 | services |
| 172.20.20.21/32 | deimos/ipvlan-l2 | services |
| 172.20.20.200/32 | caddy-internal | services |
| 172.20.20.201/32 | authelia | services |
| 172.20.20.202/32 | homepage | services |
| 172.20.20.203/32 | netbox | services |
| 172.20.20.204/32 | vault | services |
| 172.20.20.205/32 | vaultwarden | services |
| 172.20.20.206/32 | postfix | services |
| 172.20.20.207/32 | crowdsec | services |
| 172.20.20.210/32 | prometheus | services |
| 172.20.20.211/32 | alertmanager | services |
| 172.20.20.212/32 | grafana | services |
| 172.20.20.213/32 | blackbox-exporter | services |
| 172.20.20.214/32 | snmp-exporter | services |
| 172.20.20.215/32 | uptime-kuma | services |
| 172.20.20.216/32 | librespeed | services |
| 172.20.20.217/32 | smokeping | services |
| 172.20.20.218/32 | loki | services |
| 172.20.20.220/32 | omada-controller | services |
| 172.20.20.221/32 | home-assistant | services |
| 172.20.20.222/32 | mosquitto | services |
| 172.20.20.223/32 | zigbee2mqtt | services |
| 172.20.20.224/32 | esphome | services |
| 172.20.20.225/32 | go2rtc | services |
| 172.20.20.226/32 | frigate | services |
| 172.20.20.234/32 | blocky | services |
| 172.20.20.235/32 | coredns-filtered | services |
| 172.20.20.236/32 | coredns-clean | services |
| 172.20.20.237/32 | chrony-a | services |
| 172.20.20.238/32 | chrony-b | services |
| 172.20.20.239/32 | gluetun | services |
| 172.20.20.240/32 | immich | services |
| 172.20.20.241/32 | jellyfin | services |
| 172.20.20.242/32 | tdarr | services |
| 172.20.20.243/32 | radarr | services |
| 172.20.20.244/32 | sonarr | services |
| 172.20.20.245/32 | lidarr | services |
| 172.20.20.246/32 | readarr | services |
| 172.20.20.247/32 | bazarr | services |
| 172.20.20.248/32 | prowlarr | services |
| 172.20.20.249/32 | jellyseerr | services |
| 172.20.20.250/32 | flaresolverr | services |
| 172.20.100.10/24 | phobos/enp0s31f6.100 | dmz |
| 172.20.100.20/32 | phobos/ipvlan-l2.100 | dmz |
| 172.20.100.200/32 | caddy-dmz | dmz |

## DNS Zones

| Zone | Type | Provider |
|------|------|----------|
| 100.20.172.in-addr.arpa. | internal | coredns-common |
| 20.20.172.in-addr.arpa. | internal | coredns-common |
| abhaile.dedyn.io. | external | desec.io |
| abhaile.home.arpa. | internal | coredns-common |
| svc.abhaile.home.arpa. | internal | coredns-common |
