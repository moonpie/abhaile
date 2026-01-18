#!/bin/bash
# Generated downloads execution script
# This file is managed by the orchestrator - do not edit manually
set -euo pipefail

echo '=== Install latest SOPS binary (sops) ==='
SOPS_VER=$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r .tag_name)
echo "Installing SOPS ${SOPS_VER}"
sudo curl -Lo /usr/local/bin/sops "https://github.com/getsops/sops/releases/download/${SOPS_VER}/sops-${SOPS_VER}.linux.amd64"
sudo chmod 0755 /usr/local/bin/sops
