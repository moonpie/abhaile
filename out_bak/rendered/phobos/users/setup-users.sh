#!/bin/bash
# Generated user configuration script
# Creates groups and users, sets up sudoers
set -euo pipefail

groupadd -g 1001 abhaile 2>/dev/null || true
groupadd -g 1002 apex 2>/dev/null || true
groupadd -g 27 sudo 2>/dev/null || true

useradd -u 1001 -g 1001 -d /home/abhaile -s /bin/bash -c 'Abhaile service account' abhaile 2>/dev/null || true
usermod -aG sudo,apex abhaile
mkdir -p /home/abhaile
chown 1001:1001 /home/abhaile
chmod 0750 /home/abhaile
