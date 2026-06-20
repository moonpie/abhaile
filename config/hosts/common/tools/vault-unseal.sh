#!/usr/bin/env bash
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:?VAULT_ADDR is required}"
UNSEAL_FILE="${UNSEAL_FILE:?UNSEAL_FILE is required}"
SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:?SOPS_AGE_KEY_FILE is required}"

log() { printf '[vault-unseal] %s\n' "$*" >&2; }

if [[ ! -f "$UNSEAL_FILE" ]]; then
    log "No sealed bootstrap artifact found at ${UNSEAL_FILE}; skipping"
    exit 0
fi

if [[ ! -f "$SOPS_AGE_KEY_FILE" ]]; then
    log "ERROR: age identity not found at ${SOPS_AGE_KEY_FILE}"
    exit 1
fi

log "Using VAULT_ADDR=${VAULT_ADDR}"

key_count="$(
    SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" sops --decrypt --output-type json "$UNSEAL_FILE" |
        jq '.unseal_keys | if type == "array" then length else 0 end'
)"

if [[ "$key_count" -eq 0 ]]; then
    log "No unseal_keys in sealed bootstrap artifact; skipping"
    exit 0
fi

log "Waiting for Vault HTTP listener"
for _ in {1..60}; do
    if curl -sS "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -sS "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
    log "ERROR: Vault HTTP listener not reachable"
    exit 1
fi

sealed="$(
    curl -sS "${VAULT_ADDR}/v1/sys/seal-status" |
        jq -r '.sealed'
)"

if [[ "$sealed" != "true" ]]; then
    log "Vault already unsealed"
    exit 0
fi

log "Vault is sealed; applying unseal keys"
SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" sops --decrypt --output-type json "$UNSEAL_FILE" |
    jq -r '.unseal_keys[]?' |
    while IFS= read -r key; do
        python3 -c \
            "import json, sys; print(json.dumps({'key': sys.stdin.read().rstrip('\n')}))" \
            <<<"$key" |
            curl -sS -X PUT "${VAULT_ADDR}/v1/sys/unseal" \
                -H "Content-Type: application/json" \
                -d @- >/dev/null || true
    done

sealed="$(
    curl -sS "${VAULT_ADDR}/v1/sys/seal-status" |
        jq -r '.sealed'
)"

if [[ "$sealed" == "true" ]]; then
    log "ERROR: Vault still sealed after applying unseal keys"
    exit 1
fi

log "Vault successfully unsealed"
