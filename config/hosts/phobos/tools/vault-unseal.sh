#!/usr/bin/env bash
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:?VAULT_ADDR is required}"
UNSEAL_FILE="${UNSEAL_FILE:?UNSEAL_FILE is required}"
SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:?SOPS_AGE_KEY_FILE is required}"
UNSEAL_KEY_COUNT="${UNSEAL_KEY_COUNT:-2}"

log() { printf '[vault-unseal] %s\n' "$*" >&2; }

_decrypted_file=""

cleanup() {
    if [[ -n "$_decrypted_file" && -f "$_decrypted_file" ]]; then
        shred -u "$_decrypted_file" 2>/dev/null || rm -f "$_decrypted_file"
    fi
}

trap cleanup EXIT

if [[ ! -f "$UNSEAL_FILE" ]]; then
    log "ERROR: sealed recovery artifact not found at ${UNSEAL_FILE}"
    exit 1
fi

if [[ ! -f "$SOPS_AGE_KEY_FILE" ]]; then
    log "ERROR: age identity not found at ${SOPS_AGE_KEY_FILE}"
    exit 1
fi

if [[ ! "$UNSEAL_KEY_COUNT" =~ ^[0-9]+$ || "$UNSEAL_KEY_COUNT" -lt 1 ]]; then
    log "ERROR: UNSEAL_KEY_COUNT must be a positive integer"
    exit 1
fi

log "Using VAULT_ADDR=${VAULT_ADDR}"

_decrypted_file="$(mktemp)"
chmod 0600 "$_decrypted_file"

if ! SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" \
    sops --decrypt --output-type json "$UNSEAL_FILE" >"$_decrypted_file"; then
    log "ERROR: failed to decrypt sealed recovery artifact"
    exit 1
fi

key_count="$(jq '.unseal_keys | if type == "array" then length else 0 end' "$_decrypted_file")"

if [[ "$key_count" -eq 0 ]]; then
    log "No unseal_keys in sealed recovery artifact; skipping"
    exit 0
fi

if [[ "$key_count" -lt "$UNSEAL_KEY_COUNT" ]]; then
    log "ERROR: unseal key count ${key_count} is less than required ${UNSEAL_KEY_COUNT}"
    exit 1
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

log "Vault is sealed; applying ${UNSEAL_KEY_COUNT} pseudo-random unseal keys"
jq -r '.unseal_keys[]?' "$_decrypted_file" |
    shuf -n "$UNSEAL_KEY_COUNT" |
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
