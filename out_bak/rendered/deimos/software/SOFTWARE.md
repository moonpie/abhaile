# Software Plan (Generated)

> This file is managed by the orchestrator - do not edit manually.

## Packages (apt)

- podman
- crun
- vim
- git
- vlan
- curl
- systemd-resolved
- lm-sensors
- sudo
- unattended-upgrades
- iperf
- iperf3
- chrony
- unzip
- age
- jq

## Downloads

- **Install latest SOPS binary** (`sops`) - Download the newest SOPS release from GitHub and install it into /usr/local/bin

## Commands

- **Enable unattended upgrades** (`unattended-upgrades`) - Configure Debian to automatically apply security updates
- **Load required kernel modules** (`kernel-modules`) - Ensure VLAN and sensor modules are loaded and set to persist across reboots
- **Switch host networking to systemd-networkd** (`systemd-networkd`) - Disable legacy /etc/network/interfaces and enable systemd-networkd
- **Enable systemd-resolved** (`systemd-resolved`) - Use systemd-resolved stub resolver and manage resolv.conf
- **Enable netavark DHCP proxy** (`netavark-dhcp-proxy`) - Start the Podman netavark DHCP proxy socket for ipvlan networks
