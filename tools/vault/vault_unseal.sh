#!/usr/bin/env bash
set -euo pipefail

# Source shared utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/vault_common.sh
source "$SCRIPT_DIR/lib/vault_common.sh"

# Load paths from paths.ini
REPO_ROOT=$(get_repo_root) || exit 1
if [[ -f "$REPO_ROOT/tools/bash_lib/paths.sh" ]]; then
    ABHAILE_PATHS_NO_AUTO=1
    # shellcheck disable=SC1091
    source "$REPO_ROOT/tools/bash_lib/paths.sh"
    abhaile_load_paths
fi

# VAULT_ADDR uses IP address by default to avoid circular dependency risk:
# - coredns requires Vault (unsealed) for Vault Agent templates (Omada credentials)
# - vault_unseal is one of the first recovery actions after power outage
# - In recovery scenario: if coredns can't start without unsealed Vault, but vault_unseal
#   can't resolve hostname without coredns running → deadlock
# Override via VAULT_ADDR env var for normal operations if DNS is desired.
VAULT_ADDR="${VAULT_ADDR:-http://172.20.20.204:8200}"
UNSEAL_FILE="${ABHAILE_REPOSITORY_REPO_ROOT}/secrets/vault-unseal.sops.yaml"
CONTAINER="systemd-vault"

log_info "Using VAULT_ADDR=${VAULT_ADDR}"

# Ensure vault container is running
check_container_running "$CONTAINER" || exit 1

# Wait for Vault HTTP API
wait_for_vault_http "$VAULT_ADDR" || exit 1

log_info "Decrypting unseal keys..."
JSON="$(decrypt_sops_yaml_to_json "$UNSEAL_FILE")" || exit 1
K1="$(printf '%s' "$JSON" | jq -r '.unseal_keys[0]')"
K2="$(printf '%s' "$JSON" | jq -r '.unseal_keys[1]')"

if [[ -z "$K1" || -z "$K2" ]]; then
  log_error "Missing unseal keys in $UNSEAL_FILE"
  exit 1
fi

log_info "Checking sealed state..."
STATUS_JSON="$(get_vault_status_json "$CONTAINER" "$VAULT_ADDR")" || exit 1

if is_vault_sealed "$STATUS_JSON"; then
  log_info "Vault is sealed; applying unseal keys..."

  # Unseal attempts: ignore exit status (idempotent; wrong/duplicate keys would just be logged)
  vault_exec "$CONTAINER" "$VAULT_ADDR" operator unseal "'$K1'" || true
  vault_exec "$CONTAINER" "$VAULT_ADDR" operator unseal "'$K2'" || true

  # Re-check status
  STATUS_JSON="$(get_vault_status_json "$CONTAINER" "$VAULT_ADDR")" || exit 1

  if is_vault_sealed "$STATUS_JSON"; then
    log_error "Vault still sealed after applying unseal keys"
    printf '%s\n' "$STATUS_JSON" >&2
    exit 1
  fi

  log_ok "Vault successfully unsealed"
else
  log_ok "Vault already unsealed"
fi

log_info "Final status:"
vault_exec "$CONTAINER" "$VAULT_ADDR" status || true

log_info "Complete."
exit 0
