#!/usr/bin/env bash
# Vault AppRole token refresh script
# Mints a new token using AppRole credentials and writes to token file for vault-agent
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

INSTANCE="${1:-}"
ENV_FILE="${ABHAILE_SECRETS_VAULT_APPROLE_DIR}/${INSTANCE}.env"
TOKEN_FILE="${ABHAILE_RUNTIME_VAULT_TOKEN_FILE}"

if [[ ! -f "$ENV_FILE" ]]; then
  log_vault_error "AppRole env file not found: $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

# Validate required variables
require_env_vars VAULT_ADDR VAULT_ROLE_ID VAULT_ROLE_SECRET_ID || exit 1

log_vault_info "Minting AppRole token for $INSTANCE"

# Call Vault API to mint token
RESPONSE=$(curl -s -X POST \
  "${VAULT_ADDR}/v1/auth/approle/login" \
  -d "{\"role_id\":\"${VAULT_ROLE_ID}\",\"secret_id\":\"${VAULT_ROLE_SECRET_ID}\"}")

if ! TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['auth']['client_token'])"); then
  log_vault_error "Failed to mint token; API response: $RESPONSE"
  exit 1
fi

# Write token to file with secure permissions
mkdir -p "$(dirname "$TOKEN_FILE")"
echo "$TOKEN" > "$TOKEN_FILE.tmp"
chmod 0600 "$TOKEN_FILE.tmp"
mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"
chown abhaile:abhaile "$TOKEN_FILE"

log_vault_ok "Token minted and written to $TOKEN_FILE"
