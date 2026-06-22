#!/usr/bin/env bash
# scripts/bootstrap.sh — Abhaile host bootstrap (curl-bash entry point).
# Enrolls a fresh Debian 13 host into GitOps-managed desired state.
# See: docs/specs/accepted/0014-bootstrap.md
set -euo pipefail

# --- Configuration -----------------------------------------------------------

readonly SOPS_VERSION="v3.9.4"
readonly SOPS_SHA256="4540307a0889c4e4bcbec4079b67050b4e49e9937e7a0543a40cb2e33e63a596"
readonly SOPS_URL="https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64"
readonly VAULT_VERSION="1.21"
readonly VAULT_RELEASE_API="https://api.releases.hashicorp.com/v1/releases/vault/${VAULT_VERSION}?license_class=oss"

readonly REPO_URL="${ABHAILE_REPO_URL:-git@github.com:moonpie/abhaile.git}"
readonly REPO_DIR="/opt/abhaile"
readonly REPO_BRANCH="${ABHAILE_BRANCH:-main}"
readonly OUTPUT_DIR="/var/lib/abhaile"
readonly LOG_DIR="/var/log/abhaile"
readonly LOG_FILE="${LOG_DIR}/bootstrap.log"

readonly VAULT_ADDR="${VAULT_ADDR:-http://vault.svc.abhaile.home.arpa:8200}"
readonly VAULT_AGENT_DIR="/home/abhaile/.config/vault-agent"
readonly VAULT_ROLE_ID_PATH="${VAULT_AGENT_DIR}/role-id"
readonly VAULT_SECRET_ID_PATH="${VAULT_AGENT_DIR}/secret-id"
readonly READY_SENTINEL="/srv/vault/agent/out/.ready"
readonly BOOTSTRAP_READY_TIMEOUT="${BOOTSTRAP_READY_TIMEOUT:-60}"

readonly SECRETS_DIR="secrets"
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

# --- SecretID handoff --------------------------------------------------------

_secret_id_handoff=""

validate_hostname_arg() {
    local hostname="${1:-}"

    if [[ -z "$hostname" ]]; then
        echo "Usage: bootstrap.sh <hostname>" >&2
        echo "  hostname: short host name present in config/mapping.yaml and config/network.yaml" >&2
        exit 1
    fi

    if [[ ! "$hostname" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]]; then
        die "Invalid hostname: '${hostname}'. Use a short DNS label from host config."
    fi
}

acquire_secret_id_handoff() {
    if [[ -n "${BOOTSTRAP_TOKEN:-}" ]]; then
        _secret_id_handoff="$BOOTSTRAP_TOKEN"
        unset BOOTSTRAP_TOKEN
        log "SecretID handoff acquired from BOOTSTRAP_TOKEN env"
        return 0
    fi

    if [[ -n "${BOOTSTRAP_TOKEN_FD:-}" ]]; then
        _secret_id_handoff=$(cat <&"${BOOTSTRAP_TOKEN_FD}")
        log "SecretID handoff acquired from BOOTSTRAP_TOKEN_FD"
        return 0
    fi

    if [[ -t 0 ]]; then
        log "No SecretID handoff found in env or fd; prompting..."
        local prompt="[bootstrap] Enter response-wrapped AppRole SecretID handoff: "
        if [[ "${BOOTSTRAP_DIRECT_SECRET_ID:-}" == "1" ]]; then
            prompt="[bootstrap] Enter direct AppRole SecretID recovery handoff: "
        fi
        read -rsp "$prompt" _secret_id_handoff
        echo
        log "SecretID handoff acquired from interactive prompt"
        return 0
    fi

    die "No SecretID handoff provided. Set BOOTSTRAP_TOKEN, BOOTSTRAP_TOKEN_FD, or run interactively."
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
    # Wipe SecretID handoff from memory
    _secret_id_handoff=""
}

write_vault_agent_secret_file() {
    local path="$1"
    local value="$2"
    local secret_dir
    secret_dir=$(dirname "$path")

    install -d -m 0700 -o abhaile -g abhaile "$secret_dir"

    local secret_tmp
    secret_tmp=$(mktemp "${secret_dir}/.$(basename "$path").tmp.XXXXXX")
    if ! (umask 077 && printf '%s' "$value" >"$secret_tmp"); then
        rm -f "$secret_tmp"
        return 1
    fi
    if ! chown abhaile:abhaile "$secret_tmp"; then
        rm -f "$secret_tmp"
        return 1
    fi
    if ! chmod 0600 "$secret_tmp"; then
        rm -f "$secret_tmp"
        return 1
    fi
    if ! mv "$secret_tmp" "$path"; then
        rm -f "$secret_tmp"
        return 1
    fi
}

resolve_secret_id_handoff() {
    local handoff="$1"
    local unwrap_response=""
    local secret_id=""

    if unwrap_response=$(VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$handoff" \
        /usr/local/bin/vault unwrap -format=json 2>/dev/null); then
        secret_id=$(printf '%s' "$unwrap_response" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data.get('data', {}).get('secret_id', ''), end='')
")
        if [[ -z "$secret_id" ]]; then
            log "Wrapped SecretID response did not contain secret_id" >&2
            return 1
        fi
        printf '%s' "$secret_id"
        return 0
    fi

    if [[ "${BOOTSTRAP_DIRECT_SECRET_ID:-}" != "1" ]]; then
        log "SecretID handoff did not unwrap; direct SecretID recovery requires BOOTSTRAP_DIRECT_SECRET_ID=1" \
            >&2
        return 1
    fi

    log "SecretID handoff did not unwrap; BOOTSTRAP_DIRECT_SECRET_ID=1 set, treating it as a direct SecretID" \
        >&2
    printf '%s' "$handoff"
}

trap cleanup_ephemeral EXIT

install_vault_cli() {
    if [[ -x /usr/local/bin/vault ]] &&
        /usr/local/bin/vault version 2>/dev/null | grep -Eq "Vault v${VAULT_VERSION}(\\.|$)"; then
        log "Vault CLI ${VAULT_VERSION} already installed"
        return 0
    fi

    log "Installing Vault CLI ${VAULT_VERSION}"

    local vault_release
    vault_release=$(curl -fsSL "$VAULT_RELEASE_API" | jq -r .version)

    local version_regex
    version_regex="^${VAULT_VERSION//./\\.}(\\.[0-9]+)?$"
    if [[ ! "$vault_release" =~ $version_regex ]]; then
        die "Unexpected Vault release version from HashiCorp API: ${vault_release}"
    fi

    create_ephemeral_dir
    local vault_zip="${_ephemeral_dir}/vault.zip"
    local vault_bin="${_ephemeral_dir}/vault"

    curl -fsSL -o "$vault_zip" \
        "https://releases.hashicorp.com/vault/${vault_release}/vault_${vault_release}_linux_amd64.zip"
    unzip -p "$vault_zip" vault >"$vault_bin"
    install -m 0755 "$vault_bin" /usr/local/bin/vault
    rm -f "$vault_zip" "$vault_bin"

    /usr/local/bin/vault version >/dev/null
    log "Vault CLI ${vault_release} installed"
}

# --- Stage 1: Preflight -----------------------------------------------------

stage_preflight() {
    log "=== Stage 1: Preflight ==="

    if [[ $EUID -ne 0 ]]; then
        die "Must run as root"
    fi

    validate_hostname_arg "${1:-}"

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

    local packages=(git python3 python3-venv podman crun age jq curl unzip systemd-container)
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

    install_vault_cli

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

    # Require SecretID handoff material.
    acquire_secret_id_handoff
    if [[ -z "$_secret_id_handoff" ]]; then
        die "SecretID handoff is empty"
    fi

    # Verify age decryption identity
    if [[ ! -f "$AGE_KEY_PATH" ]]; then
        die "Age decryption key not found at ${AGE_KEY_PATH}. Place the key before running bootstrap."
    fi

    # Verify repo access credential.
    if [[ ! -f "$DEPLOY_KEY_PATH" ]]; then
        die "Deploy key missing at ${DEPLOY_KEY_PATH}. Place the read-only deploy key first."
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

# --- Stage 6: Sealed Vault Agent Artifact Handoff ----------------------------

stage_sealed_handoff() {
    local hostname="$1"
    log "=== Stage 6: Sealed Vault Agent Artifact Handoff ==="

    cd "$REPO_DIR"

    local sealed_path="${SECRETS_DIR}/${hostname}/vault-agent.sops.yaml"
    if [[ ! -f "$sealed_path" ]]; then
        die "Sealed Vault Agent artifact not found: ${sealed_path}"
    fi

    create_ephemeral_dir
    log "Decrypting sealed Vault Agent artifact to ephemeral dir"

    local decrypted="${_ephemeral_dir}/vault-agent.yaml"
    if ! SOPS_AGE_KEY_FILE="$AGE_KEY_PATH" sops --decrypt --output "$decrypted" "$sealed_path"; then
        die "Sealed Vault Agent artifact decryption failed. Verify age key at ${AGE_KEY_PATH}"
    fi

    # Extract role_id from decrypted artifact
    local role_id
    role_id=$(python3 -c "
import yaml, sys
data = yaml.safe_load(open('$decrypted')) or {}
print(data.get('role_id', ''), end='')
")
    if [[ -z "$role_id" ]]; then
        die "role_id not found in sealed Vault Agent artifact"
    fi

    log "Preparing Vault Agent AppRole files"
    local secret_id
    if ! secret_id=$(resolve_secret_id_handoff "$_secret_id_handoff"); then
        die "Failed to resolve SecretID handoff"
    fi
    if [[ -z "$secret_id" ]]; then
        die "Resolved SecretID is empty"
    fi

    write_vault_agent_secret_file "$VAULT_ROLE_ID_PATH" "$role_id" \
        || die "Failed to write Vault Agent role-id"
    write_vault_agent_secret_file "$VAULT_SECRET_ID_PATH" "$secret_id" \
        || die "Failed to write Vault Agent secret-id"

    log "Vault Agent AppRole files placed at ${VAULT_AGENT_DIR}"

    # Wipe sensitive variables
    role_id=""
    secret_id=""
    _secret_id_handoff=""

    # Shred and remove ephemeral dir (also handled by EXIT trap)
    cleanup_ephemeral

    log "Sealed Vault Agent artifact handoff OK"
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

    local abhaile_uid
    abhaile_uid=$(id -u abhaile)
    local abhaile_runtime_dir="/run/user/${abhaile_uid}"
    local abhaile_env=(HOME=/home/abhaile XDG_RUNTIME_DIR="$abhaile_runtime_dir")

    # Initialize podman storage for abhaile user from a readable cwd with a stable user runtime.
    if ! sudo -H -u abhaile env "${abhaile_env[@]}" bash -lc 'cd /tmp && podman system info' &>/dev/null; then
        sudo -H -u abhaile env "${abhaile_env[@]}" bash -lc 'cd /tmp && podman system migrate' \
            2>/dev/null || true
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

    SCRIPT_START=$(date +%s)
    log "Bootstrap started for host: ${hostname}"
    log "Timestamp: $(date --iso-8601=seconds)"

    stage_prerequisites
    log "stage complete: prerequisites ($(( $(date +%s) - SCRIPT_START ))s elapsed)"

    stage_user_and_credentials "$hostname"
    log "stage complete: user_and_credentials ($(( $(date +%s) - SCRIPT_START ))s elapsed)"

    stage_repo_and_env
    log "stage complete: repo_and_env ($(( $(date +%s) - SCRIPT_START ))s elapsed)"

    stage_config_validation "$hostname"
    log "stage complete: config_validation ($(( $(date +%s) - SCRIPT_START ))s elapsed)"

    stage_sealed_handoff "$hostname"
    log "stage complete: sealed_handoff ($(( $(date +%s) - SCRIPT_START ))s elapsed)"

    stage_render_apply "$hostname"
    log "stage complete: render_apply ($(( $(date +%s) - SCRIPT_START ))s elapsed)"

    stage_registration
    log "bootstrap complete ($(( $(date +%s) - SCRIPT_START ))s total)"

    exit 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
