#!/usr/bin/env bash
# vault_common.sh - shared utilities for Vault scripts
#
# Provides logging, repo detection, container checks, Vault status, SOPS decryption,
# and common Vault operations.

# Source shared logging
COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../common"
# shellcheck source=tools/common/logging.sh
if [[ -f "$COMMON_DIR/logging.sh" ]]; then
    # shellcheck disable=SC1090
    source "$COMMON_DIR/logging.sh"
else
    # Fallback minimal log functions
    log_info()  { printf '[INFO] %s\n' "$*" >&2; }
    log_ok()    { printf '[OK] %s\n' "$*" >&2; }
    log_warn()  { printf '[WARN] %s\n' "$*" >&2; }
    log_error() { printf '[ERROR] %s\n' "$*" >&2; }
fi

# get_repo_root - Detect repo root from anywhere in the repo
# Args: none
# Returns: repo root path
# Exit: 0 on success, 1 if .git not found
get_repo_root() {
    local current="$PWD"
    while [[ "$current" != "/" ]]; do
        if [[ -f "$current/.git/config" ]] || [[ -d "$current/.git" ]]; then
            printf '%s' "$current"
            return 0
        fi
        current="$(dirname "$current")"
    done
    log_error "Could not find repo root (.git directory)"
    return 1
}

# wait_for_vault_http - Wait for Vault HTTP API to become available
# Args:
#   $1 = VAULT_ADDR (required)
#   $2 = max_wait_seconds (default 60)
# Returns: 0 on success, 1 if timeout
wait_for_vault_http() {
    local vault_addr="${1:?VAULT_ADDR required}"
    local max_wait="${2:-60}"
    local attempt=0

    log_info "Waiting for Vault HTTP listener at ${vault_addr}..."
    while [[ $attempt -lt $max_wait ]]; do
        if curl -sS "${vault_addr}/v1/sys/health" >/dev/null 2>&1; then
            log_ok "Vault HTTP reachable"
            return 0
        fi
        ((attempt++))
        sleep 1
    done

    log_error "Vault HTTP not reachable after ${max_wait}s"
    return 1
}

# check_container_running - Check if a Podman container is running
# Args:
#   $1 = container_name (required)
# Returns: 0 if running, 1 if not
check_container_running() {
    local container="${1:?Container name required}"
    local pod_output
    pod_output=$(podman ps --format '{{.Names}}' 2>&1)
    if echo "$pod_output" | grep -qx "$container"; then
        return 0
    else
        log_error "Container '$container' is not running"
        return 1
    fi
}

# get_vault_status_json - Get Vault status as JSON
# Args:
#   $1 = container_name (required)
#   $2 = VAULT_ADDR (required)
# Returns: JSON status output
# Exit: 0 on success, 1 if failed
get_vault_status_json() {
    local container="${1:?Container name required}"
    local vault_addr="${2:?VAULT_ADDR required}"
    local status_json

    status_json="$(podman exec "$container" sh -lc "VAULT_ADDR=$vault_addr vault status -format=json" 2>/dev/null || true)"

    if [[ -z "$status_json" ]]; then
        log_error "Failed to get Vault status JSON"
        return 1
    fi

    printf '%s' "$status_json"
}

# is_vault_sealed - Check if Vault is sealed
# Args:
#   $1 = status_json (from get_vault_status_json)
# Returns: 0 if sealed, 1 if unsealed
is_vault_sealed() {
    local status_json="${1:?Status JSON required}"
    local sealed

    sealed="$(printf '%s' "$status_json" | jq -r '.sealed' 2>/dev/null || echo "unknown")"

    if [[ "$sealed" == "true" ]]; then
        return 0  # Sealed
    else
        return 1  # Not sealed or unknown
    fi
}

# decrypt_sops_yaml_to_json - Decrypt SOPS file to JSON
# Args:
#   $1 = sops_file_path (required)
# Returns: JSON output
# Exit: 0 on success, 1 if failed
decrypt_sops_yaml_to_json() {
    local sops_file="${1:?SOPS file path required}"

    if [[ ! -f "$sops_file" ]]; then
        log_vault_error "SOPS file not found: $sops_file"
        return 1
    fi

    if ! sops -d --output-type json "$sops_file" 2>/dev/null; then
        log_vault_error "Failed to decrypt SOPS file: $sops_file"
        return 1
    fi
}

# require_env_vars - Validate required environment variables
# Args:
#   variable names as arguments (e.g., "VAULT_ADDR" "VAULT_TOKEN")
# Returns: nothing
# Exit: 0 on all present, 1 if any missing
require_env_vars() {
    local missing=()
    for var in "$@"; do
        if [[ -z "${!var:-}" ]]; then
            missing+=("$var")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required environment variables: ${missing[*]}"
        return 1
    fi
    return 0
}

# Execute vault command in container with retry logic
# Args: $1 = container, $2 = vault_addr, $3... = vault command args
vault_exec() {
    local container="${1:?Container name required}"
    local vault_addr="${2:?VAULT_ADDR required}"
    shift 2

    podman exec "$container" sh -lc "VAULT_ADDR=$vault_addr vault $*"
}
