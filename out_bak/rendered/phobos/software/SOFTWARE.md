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
- ddclient

## Downloads

- **Install latest SOPS binary** (`sops`) - Download the newest SOPS release from GitHub and install it into /usr/local/bin

## Builds

- **Build and install gasket-dkms** (`gasket-dkms`) - Prepare Google's Coral EdgeTPU repo, build gasket-dkms, and ensure apex devices have the right permissions

## Commands

- **Enable unattended upgrades** (`unattended-upgrades`) - Configure Debian to automatically apply security updates
- **Load required kernel modules** (`kernel-modules`) - Ensure VLAN and sensor modules are loaded and set to persist across reboots
- **Switch host networking to systemd-networkd** (`systemd-networkd`) - Disable legacy /etc/network/interfaces and enable systemd-networkd
- **Enable systemd-resolved** (`systemd-resolved`) - Use systemd-resolved stub resolver and manage resolv.conf
- **Enable netavark DHCP proxy** (`netavark-dhcp-proxy`) - Start the Podman netavark DHCP proxy socket for ipvlan networks
- **Enable ddclient** (`ddclient`) - Ensure ddclient is enabled and running so dynamic DNS updates occur
- **Load Coral TPU kernel modules** (`coral-tpu-modules`) - Load gasket and apex modules for Google Coral TPU (phobos-specific)
- **Install Coral TPU udev rules** (`coral-tpu-udev`) - Configure udev rules for Google Coral TPU device access (phobos-specific)
