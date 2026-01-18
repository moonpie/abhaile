#!/bin/bash
# Generated commands execution script
# This file is managed by the orchestrator - do not edit manually
set -euo pipefail

echo '=== Enable unattended upgrades (unattended-upgrades) ==='
echo "unattended-upgrades unattended-upgrades/enable_auto_updates boolean true" | sudo debconf-set-selections
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo '=== Load required kernel modules (kernel-modules) ==='
sudo modprobe nct6683 force=on || true
sudo modprobe 8021q || true
grep -q "^8021q" /etc/modules || echo "8021q" | sudo tee -a /etc/modules >/dev/null
grep -q "^nct6683" /etc/modules || echo "nct6683" | sudo tee -a /etc/modules >/dev/null

echo '=== Switch host networking to systemd-networkd (systemd-networkd) ==='
if [ -f /etc/network/interfaces ]; then sudo mv /etc/network/interfaces /etc/network/interfaces.save; fi
sudo systemctl enable systemd-networkd.service
sudo systemctl start systemd-networkd.service

echo '=== Enable systemd-resolved (systemd-resolved) ==='
sudo systemctl enable systemd-resolved.service
sudo systemctl start systemd-resolved.service
sudo ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

echo '=== Enable netavark DHCP proxy (netavark-dhcp-proxy) ==='
sudo systemctl enable --now netavark-dhcp-proxy.socket
