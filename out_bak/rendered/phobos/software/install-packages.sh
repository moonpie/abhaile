#!/bin/bash
# Generated package installation script for Debian/Ubuntu
# This file is managed by the orchestrator - do not edit manually
set -euo pipefail

# Update package lists
apt-get update

# Install packages
apt-get install -y \
  podman \
  crun \
  vim \
  git \
  vlan \
  curl \
  systemd-resolved \
  lm-sensors \
  sudo \
  unattended-upgrades \
  iperf \
  iperf3 \
  chrony \
  unzip \
  age \
  jq \
  ddclient

# Clean up apt cache
apt-get clean
apt-get autoclean
