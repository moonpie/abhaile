#!/usr/bin/env bash
# scripts/bootstrap.sh — Abhaile host bootstrap (curl-bash entry point).
# Enrolls a fresh Debian 13 host into GitOps-managed desired state.
# See: docs/specs/active/0014-bootstrap.md
set -euo pipefail

# --- Configuration -----------------------------------------------------------

readonly SOPS_VERSION="v3.9.4"
readonly SOPS_SHA256="4540307a0889c4e4bcbec4079b67050b4e49e9937e7a0543a40cb2e33e63a596"
readonly SOPS_URL="https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64"

readonly REPO_URL="${ABHAILE_REPO_URL:-git@github.com:moonpie/abhaile.git}"
readonly REPO_DIR="/opt/abhaile"
readonly REPO_BRANCH="${ABHAILE_BRANCH:-main}"
readonly OUTPUT_DIR="/var/lib/abhaile"
readonly LOG_DIR="/var/log/abhaile"
readonly LOG_FILE="${LOG_DIR}/bootstrap.log"

readonly VAULT_ADDR="${VAULT_ADDR:-https://vault.svc.abhaile.home.arpa:8200}"
readonly VAULT_TOKEN_PATH="/home/abhaile/.config/vault-agent/token"
readonly READY_SENTINEL="/srv/vault/agent/out/.ready"
readonly BOOTSTRAP_READY_TIMEOUT="${BOOTSTRAP_READY_TIMEOUT:-60}"

readonly SEALED_DIR="config/bootstrap/sealed"
readonly AGE_KEY_PATH="/home/abhaile/.config/sops/age/keys.txt"
readonly DEPLOY_KEY_PATH="/home/abhaile/.ssh/gitops_ed25519"

# --- Logging -----------------------------------------------------------------

_log_initialized=0

init_logging() {
    mkdir -p "$LOG_DIR"
    chmod 0750 "$LOG_DIR"
    _log_initialized=1
    # Redirect all subsequent output to both stdout and log file
    exec > >(tee -a "$LOG_FILE") 2>&1
}

log() { printf '[bootstrap] %s\n' "$*"; }
die() { log "FATAL: $*"; exit 1; }

# --- Token handling ----------------------------------------------------------

_bootstrap_token=""

acquire_bootstrap_token() {
    if [[ -n "${BOOTSTRAP_TOKEN:-}" ]]; then
        _bootstrap_token="$BOOTSTRAP_TOKEN"
        unset BOOTSTRAP_TOKEN
        log "Token acquired from BOOTSTRAP_TOKEN env"
        return 0
    fi

    if [[ -n "${BOOTSTRAP_TOKEN_FD:-}" ]]; then
        _bootstrap_token=$(cat <&"${BOOTSTRAP_TOKEN_FD}")
        log "Token acquired from BOOTSTRAP_TOKEN_FD"
        return 0
    fi

    if [[ -t 0 ]]; then
        log "No token found in env or fd; prompting..."
        read -rsp "[bootstrap] Enter bootstrap token (AppRole secret_id): " _bootstrap_token
        echo
        log "Token acquired from interactive prompt"
        return 0
    fi

    die "No bootstrap token provided. Set BOOTSTRAP_TOKEN, BOOTSTRAP_TOKEN_FD, or run interactively."
}

# --- Ephemeral tmpdir management ---------------------------------------------

_ephemeral_dir=""

create_ephemeral_dir() {
    if [[ -d /dev/shm ]]; then
        _ephemeral_dir=$(mktemp -d --tmpdir=/dev/shm abhaile-bootstrap.XXXXXX)
    else
        _ephemeral_dir=$(mktemp -d /tmp/abhaile-bootstrap.XXXXXX)
    fi
    chmod 0700 "$_ephemeral_dir"
}

cleanup_ephemeral() {
    if [[ -n "$_ephemeral_dir" && -d "$_ephemeral_dir" ]]; then
        find "$_ephemeral_dir" -type f -exec shred -u {} \; 2>/dev/null || true
        rm -rf "$_ephemeral_dir"
        _ephemeral_dir=""
    fi
    # Wipe token from memory
    _bootstrap_token=""
}

trap cleanup_ephemeral EXIT

# --- Stage 1: Preflight -----------------------------------------------------

stage_preflight() {
    log "=== Stage 1: Preflight ==="

    if [[ $EUID -ne 0 ]]; then
        die "Must run as root"
    fi

    if [[ -z "${1:-}" ]]; then
        echo "Usage: bootstrap.sh <hostname>" >&2
        echo "  hostname: phobos or deimos" >&2
        exit 1
    fi

    # Validate hostname against known hosts (prevents injection in downstream commands)
    if [[ "$1" != "phobos" && "$1" != "deimos" ]]; then
        die "Invalid hostname: '$1'. Must be 'phobos' or 'deimos'."
    fi

    # Verify Debian 13 (trixie)
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [[ "${ID:-}" != "debian" || "${VERSION_CODENAME:-}" != "trixie" ]]; then
            log "WARNING: Expected Debian 13 (trixie), got ${PRETTY_NAME:-unknown}"
        fi
    fi

    # Create log directory early
    mkdir -p "$LOG_DIR"
    chmod 0750 "$LOG_DIR"

    # Test network connectivity
    if ! curl -fsSo /dev/null --connect-timeout 10 https://github.com 2>/dev/null; then
        die "Network connectivity check failed (cannot reach github.com)"
    fi

    log "Preflight OK: root, network reachable"
}

# --- Stage 2: Prerequisites --------------------------------------------------

stage_prerequisites() {
    log "=== Stage 2: Prerequisites ==="

    local packages=(git python3 python3-venv podman crun age jq curl)
    local to_install=()

    for pkg in "${packages[@]}"; do
        if ! dpkg -s "$pkg" &>/dev/null; then
            to_install+=("$pkg")
        fi
    done

    if [[ ${#to_install[@]} -gt 0 ]]; then
        log "Installing packages: ${to_install[*]}"
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${to_install[@]}"
    else
        log "All required packages already installed"
    fi

    # Install sops (pinned version with checksum)
    if [[ -x /usr/local/bin/sops ]] && /usr/local/bin/sops --version 2>/dev/null | grep -q "${SOPS_VERSION#v}"; then
        log "sops ${SOPS_VERSION} already installed"
    else
        log "Installing sops ${SOPS_VERSION}"
        local sops_tmp
        sops_tmp=$(mktemp)
        curl -fsSL -o "$sops_tmp" "$SOPS_URL"
        local actual_sha
        actual_sha=$(sha256sum "$sops_tmp" | awk '{print $1}')
        if [[ "$actual_sha" != "$SOPS_SHA256" ]]; then
            rm -f "$sops_tmp"
            die "sops checksum mismatch: expected=${SOPS_SHA256} actual=${actual_sha}"
        fi
        install -m 0755 "$sops_tmp" /usr/local/bin/sops
        rm -f "$sops_tmp"
        log "sops ${SOPS_VERSION} installed (checksum verified)"
    fi

    # Enable systemd-networkd and systemd-resolved
    systemctl enable --now systemd-networkd 2>/dev/null || true
    systemctl enable --now systemd-resolved 2>/dev/null || true

    log "Prerequisites OK"
}

# --- Stage 3: User and Credential Validation ---------------------------------

stage_user_and_credentials() {
    local hostname="$1"
    log "=== Stage 3: User and Credential Validation ==="

    # Create abhaile user/group if absent
    if ! getent group abhaile &>/dev/null; then
        groupadd -g 1001 abhaile
        log "Created group abhaile (gid=1001)"
    fi

    if ! id abhaile &>/dev/null; then
        useradd -u 1001 -g abhaile -m -s /bin/bash -d /home/abhaile abhaile
        log "Created user abhaile (uid=1001)"
    fi

    # Require bootstrap token
    acquire_bootstrap_token
    if [[ -z "$_bootstrap_token" ]]; then
        die "Bootstrap token is empty"
    fi

    # Verify age decryption identity
    if [[ ! -f "$AGE_KEY_PATH" ]]; then
        die "Age decryption key not found at ${AGE_KEY_PATH}. Place the key before running bootstrap."
    fi

    # Verify repo access credential (deploy key preferred)
    if [[ ! -f "$DEPLOY_KEY_PATH" ]]; then
        log "WARNING: Deploy key not found at ${DEPLOY_KEY_PATH}"
        log "Will attempt sealed repo-bootstrap.sops.yaml fallback after clone"
        # If no deploy key exists, we can't clone. Check if repo already exists.
        if [[ ! -d "$REPO_DIR/.git" ]]; then
            die "Deploy key missing at ${DEPLOY_KEY_PATH} and repo not yet cloned. Place the deploy key first."
        fi
    fi

    log "Credentials OK"
}

# --- Stage 4: Repo and Environment -------------------------------------------

stage_repo_and_env() {
    log "=== Stage 4: Repo and Environment ==="

    local git_ssh_cmd="ssh -i ${DEPLOY_KEY_PATH} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

    if [[ -d "$REPO_DIR/.git" ]]; then
        log "Repo already cloned at ${REPO_DIR}; pulling latest"
        cd "$REPO_DIR"
        GIT_SSH_COMMAND="$git_ssh_cmd" git fetch origin "$REPO_BRANCH"
        git checkout "$REPO_BRANCH"
        GIT_SSH_COMMAND="$git_ssh_cmd" git pull origin "$REPO_BRANCH"
    else
        log "Cloning repo to ${REPO_DIR}"
        GIT_SSH_COMMAND="$git_ssh_cmd" git clone -b "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
        cd "$REPO_DIR"
    fi

    # Create/update Python venv
    if [[ ! -d "${REPO_DIR}/.venv" ]]; then
        log "Creating Python venv"
        python3 -m venv "${REPO_DIR}/.venv"
    fi

    log "Installing Python dependencies"
    "${REPO_DIR}/.venv/bin/pip" install --quiet --upgrade pip
    "${REPO_DIR}/.venv/bin/pip" install --quiet -r "${REPO_DIR}/requirements.txt"

    # Ensure CLI entrypoints are on PATH
    export PATH="${REPO_DIR}/.venv/bin:${PATH}"

    log "Repo and environment OK"
}

# --- Stage 5: Configuration Validation ---------------------------------------

stage_config_validation() {
    local hostname="$1"
    log "=== Stage 5: Configuration Validation ==="

    cd "$REPO_DIR"

    # Verify hostname in mapping.yaml
    if ! ABHAILE_HOST="$hostname" python3 -c "
import yaml, sys, os
host = os.environ['ABHAILE_HOST']
m = yaml.safe_load(open('config/mapping.yaml'))
hosts = [k for item in m.get('abhaile', []) for k in item]
if host not in hosts:
    print(f'Host {host} not found in config/mapping.yaml', file=sys.stderr)
    sys.exit(1)
"; then
        die "Host '${hostname}' not defined in config/mapping.yaml"
    fi

    # Verify hostname in network.yaml
    if ! ABHAILE_HOST="$hostname" python3 -c "
import yaml, sys, os
host = os.environ['ABHAILE_HOST']
n = yaml.safe_load(open('config/network.yaml'))
if host not in n.get('hosts', {}):
    print(f'Host {host} not found in config/network.yaml hosts', file=sys.stderr)
    sys.exit(1)
"; then
        die "Host '${hostname}' not defined in config/network.yaml"
    fi

    log "Configuration validation OK: host '${hostname}' defined in mapping and network"
}

# --- Stage 6: Sealed Artifact Handoff ----------------------------------------

stage_sealed_handoff() {
    local hostname="$1"
    log "=== Stage 6: Sealed Artifact Handoff ==="

    cd "$REPO_DIR"

    local sealed_path="${SEALED_DIR}/${hostname}/vault-bootstrap.sops.yaml"
    if [[ ! -f "$sealed_path" ]]; then
        die "Sealed artifact not found: ${sealed_path}"
    fi

    create_ephemeral_dir
    log "Decrypting sealed artifacts to ephemeral dir"

    local decrypted="${_ephemeral_dir}/vault-bootstrap.yaml"
    if ! SOPS_AGE_KEY_FILE="$AGE_KEY_PATH" sops --decrypt --output "$decrypted" "$sealed_path"; then
        die "Sealed artifact decryption failed. Verify age key at ${AGE_KEY_PATH}"
    fi

    # Extract role_id from decrypted artifact
    local role_id
    role_id=$(python3 -c "
import yaml, sys
data = yaml.safe_load(open('$decrypted'))
print(data.get('role_id', ''), end='')
")
    if [[ -z "$role_id" ]]; then
        die "role_id not found in sealed artifact"
    fi

    # Vault unseal (phobos only — has unseal keys in sealed artifact)
    if [[ "$hostname" == "phobos" ]]; then
        log "Vault unseal (phobos only)"
        local unseal_keys
        unseal_keys=$(python3 -c "
import yaml, sys, json
data = yaml.safe_load(open('$decrypted'))
keys = data.get('unseal_keys', [])
print(json.dumps(keys))
")
        if [[ "$unseal_keys" != "[]" ]]; then
            local key
            for key in $(echo "$unseal_keys" | python3 -c "import json,sys; [print(k) for k in json.load(sys.stdin)]"); do
                curl -fsSo /dev/null --cacert /etc/ssl/certs/ca-certificates.crt \
                    -X PUT "${VAULT_ADDR}/v1/sys/unseal" \
                    -H "Content-Type: application/json" \
                    -d "{\"key\": \"${key}\"}" 2>/dev/null || true
            done
            log "Vault unseal keys applied"
        fi
    fi

    # Mint seed token via AppRole login
    log "Minting Vault Agent seed token via AppRole"
    local login_payload="{\"role_id\": \"${role_id}\", \"secret_id\": \"${_bootstrap_token}\"}"
    local login_response
    login_response=$(curl -fsS --cacert /etc/ssl/certs/ca-certificates.crt \
        -X POST "${VAULT_ADDR}/v1/auth/approle/login" \
        -H "Content-Type: application/json" \
        -d "$login_payload") || die "Vault AppRole login failed (is Vault running and accessible?)"

    local seed_token
    seed_token=$(echo "$login_response" | python3 -c "
import json, sys
data = json.load(sys.stdin)
token = data.get('auth', {}).get('client_token', '')
print(token, end='')
")

    if [[ -z "$seed_token" ]]; then
        die "Failed to extract client_token from Vault AppRole login response"
    fi

    # Place seed token at handoff path
    local token_dir
    token_dir=$(dirname "$VAULT_TOKEN_PATH")
    install -d -m 0700 -o abhaile -g abhaile "$token_dir"
    # Write token atomically — use temp file to avoid exposing value in process args
    local token_tmp="${token_dir}/.token.tmp.$$"
    (umask 077 && printf '%s' "$seed_token" > "$token_tmp")
    chown abhaile:abhaile "$token_tmp"
    mv "$token_tmp" "$VAULT_TOKEN_PATH"

    log "Seed token placed at ${VAULT_TOKEN_PATH}"

    # Wipe sensitive variables
    role_id=""
    seed_token=""
    login_payload=""
    login_response=""

    # Shred and remove ephemeral dir (also handled by EXIT trap)
    cleanup_ephemeral

    log "Sealed artifact handoff OK"
}

# --- Stage 7: First Render and Apply -----------------------------------------

stage_render_apply() {
    local hostname="$1"
    log "=== Stage 7: First Render and Apply ==="

    cd "$REPO_DIR"
    export PATH="${REPO_DIR}/.venv/bin:${PATH}"

    # Enable user lingering for abhaile (required for rootless quadlets)
    if ! loginctl show-user abhaile 2>/dev/null | grep -q "Linger=yes"; then
        loginctl enable-linger abhaile
        log "Enabled user linger for abhaile"
        # Wait for user manager to be ready
        local retries=0
        while [[ $retries -lt 10 ]]; do
            if systemctl --user -M abhaile@ is-system-running --wait 2>/dev/null | grep -qE "running|degraded"; then
                break
            fi
            sleep 1
            retries=$((retries + 1))
        done
    fi

    # Initialize podman storage for abhaile user
    if ! sudo -u abhaile podman system info &>/dev/null; then
        sudo -u abhaile podman system migrate 2>/dev/null || true
    fi

    # Render
    log "Running abhaile-render --host ${hostname}"
    abhaile-render --host "$hostname" --output "$OUTPUT_DIR"

    # Apply
    log "Running abhaile-apply (live)"
    abhaile-apply --host "$hostname" --output "$OUTPUT_DIR"

    # Wait for Vault Agent .ready sentinel
    log "Waiting for Vault Agent ready sentinel (timeout=${BOOTSTRAP_READY_TIMEOUT}s)"
    local waited=0
    while [[ $waited -lt $BOOTSTRAP_READY_TIMEOUT ]]; do
        if [[ -f "$READY_SENTINEL" ]]; then
            log "Vault Agent ready sentinel found after ${waited}s"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done

    if [[ ! -f "$READY_SENTINEL" ]]; then
        log "WARNING: Vault Agent ready sentinel not found after ${BOOTSTRAP_READY_TIMEOUT}s"
        log "Runner will handle convergence on next run"
    fi

    log "Render and apply OK"
}

# --- Stage 8: GitOps Runner Registration -------------------------------------

stage_registration() {
    log "=== Stage 8: GitOps Runner Registration ==="

    systemctl enable --now abhaile-runner.timer 2>/dev/null \
        || log "WARNING: abhaile-runner.timer not found (will be created on next apply)"

    local next_run
    next_run=$(systemctl list-timers abhaile-runner.timer --no-pager 2>/dev/null | tail -n +2 | head -1 || echo "unknown")

    log "=== Bootstrap Complete ==="
    log "Host: $(hostname -s)"
    log "Repo: ${REPO_DIR} (branch: ${REPO_BRANCH})"
    log "Output: ${OUTPUT_DIR}"
    log "Next GitOps run: ${next_run}"
}

# --- Main --------------------------------------------------------------------

main() {
    local hostname="${1:-}"

    stage_preflight "$hostname"
    init_logging

    log "Bootstrap started for host: ${hostname}"
    log "Timestamp: $(date --iso-8601=seconds)"

    stage_prerequisites
    stage_user_and_credentials "$hostname"
    stage_repo_and_env
    stage_config_validation "$hostname"
    stage_sealed_handoff "$hostname"
    stage_render_apply "$hostname"
    stage_registration

    exit 0
}

main "$@"
