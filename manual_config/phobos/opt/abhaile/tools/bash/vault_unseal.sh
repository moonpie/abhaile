#!/usr/bin/env bash
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://172.20.20.204:8200}"
UNSEAL_FILE="/opt/abhaile/secrets/vault-unseal.sops.yaml"
CONTAINER="systemd-vault"

log() { printf '[vault-unseal] %s\n' "$*" >&2; }

log "Using VAULT_ADDR=${VAULT_ADDR}"

# Ensure vault container is running
if ! podman ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  log "ERROR: Vault container '$CONTAINER' is not running"
  exit 1
fi

log "Waiting for Vault HTTP listener..."
for i in {1..60}; do
  if curl -sS "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
    log "Vault HTTP reachable"
    break
  fi
  sleep "$i"
done

if ! curl -sS "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
  log "ERROR: Vault HTTP not reachable after wait"
  exit 1
fi

log "Decrypting unseal keys..."
JSON="$(sops -d --output-type json "$UNSEAL_FILE")"
K1="$(printf '%s' "$JSON" | jq -r '.unseal_keys[0]')"
K2="$(printf '%s' "$JSON" | jq -r '.unseal_keys[1]')"

if [[ -z "$K1" || -z "$K2" ]]; then
  log "ERROR: Missing unseal keys in $UNSEAL_FILE"
  exit 1
fi

log "Checking sealed state (ignoring exit code)..."
STATUS_JSON="$(podman exec "$CONTAINER" sh -lc "VAULT_ADDR=$VAULT_ADDR vault status -format=json" || true)"

if [[ -z "$STATUS_JSON" ]]; then
  log "ERROR: Failed to get Vault status JSON"
  exit 1
fi

SEALED="$(printf '%s' "$STATUS_JSON" | jq -r '.sealed')"

if [[ "$SEALED" == "true" ]]; then
  log "Vault is sealed; applying unseal keys..."

  # Unseal attempts: ignore exit status (idempotent; wrong/duplicate keys would just be logged)
  podman exec "$CONTAINER" sh -lc "VAULT_ADDR=$VAULT_ADDR vault operator unseal '$K1'" || true
  podman exec "$CONTAINER" sh -lc "VAULT_ADDR=$VAULT_ADDR vault operator unseal '$K2'" || true

  # Re-check status
  STATUS_JSON="$(podman exec "$CONTAINER" sh -lc "VAULT_ADDR=$VAULT_ADDR vault status -format=json" || true)"
  if [[ -z "$STATUS_JSON" ]]; then
    log "ERROR: Failed to get Vault status JSON after unseal"
    exit 1
  fi

  SEALED="$(printf '%s' "$STATUS_JSON" | jq -r '.sealed')"

  if [[ "$SEALED" == "true" ]]; then
    log "ERROR: Vault still sealed after applying unseal keys"
    printf '%s\n' "$STATUS_JSON" >&2
    exit 1
  fi

  log "Vault successfully unsealed."
else
  log "Vault already unsealed."
fi

log "Final status (ignoring exit code for display):"
podman exec "$CONTAINER" sh -lc "VAULT_ADDR=$VAULT_ADDR vault status" || true

log "Complete."
exit 0
