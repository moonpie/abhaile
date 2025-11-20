#!/bin/bash
set -euo pipefail

LEAF="/srv/caddy/internal/data/certificates/local/omada-controller.svc.abhaile.home.arpa/omada-controller.svc.abhaile.home.arpa.crt"
KEY="/srv/caddy/internal/data/certificates/local/omada-controller.svc.abhaile.home.arpa/omada-controller.svc.abhaile.home.arpa.key"
ROOT="/srv/caddy/internal/data/pki/authorities/local/root.crt"

OUTDIR="/srv/omada-controller/cert"
OUTCRT="$OUTDIR/tls.crt"
OUTKEY="$OUTDIR/tls.key"

# Rebuild full chain
sudo install -d -m 750 -o 508 -g 508 "$OUTDIR"
cat "$LEAF" "$ROOT" | sudo tee "$OUTCRT" >/dev/null
sudo cp "$KEY" "$OUTKEY"
sudo chown 508:508 "$OUTCRT" "$OUTKEY"
sudo chmod 640 "$OUTCRT" "$OUTKEY"

# Restart Omada
sudo systemctl restart omada-controller.service
