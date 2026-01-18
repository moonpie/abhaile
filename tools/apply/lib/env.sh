#!/bin/bash
# env.sh - argument parsing and prerequisite checks

# Resolve script and root directories.
# If caller already set `SCRIPT_DIR`/`ROOT_DIR`, respect those values.
: "${SCRIPT_DIR:=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
: "${ROOT_DIR:=$(dirname "$(dirname "$SCRIPT_DIR")")}"

# Load paths from paths.ini
if [[ -f "$ROOT_DIR/../bash_lib/paths.sh" ]]; then
    # shellcheck disable=SC2034 # ABHAILE_PATHS_NO_AUTO used by sourced paths.sh
    ABHAILE_PATHS_NO_AUTO=1
    # shellcheck disable=SC1091
    source "$ROOT_DIR/../bash_lib/paths.sh"
    abhaile_load_paths
fi

# Paths derived from paths.ini (loaded above)
# These are set by abhaile_load_paths() to production paths
export REPO_DIR="${ABHAILE_REPOSITORY_REPO_ROOT}"
PROD_RENDER_DIR="${ABHAILE_RUNTIME_RENDERED_DIR}"
PROD_STATE_DIR="${ABHAILE_RUNTIME_STATE_DIR}"
PROD_NET_CONFIG_DIR="${ABHAILE_SYSTEM_SYSTEMD_NETWORK_DIR}"
PROD_SOFTWARE_DIR="${ABHAILE_RUNTIME_SOFTWARE_DIR}"

# System configuration paths used by apply.sh (use paths.ini variables)
export SYSTEMD_NETWORK_DIR="${ABHAILE_SYSTEM_SYSTEMD_NETWORK_DIR}"
export SYSTEMD_SYSTEM_DIR="${ABHAILE_SYSTEM_SYSTEMD_SYSTEM_DIR}"
export SYSTEMD_RESOLVED_CONF="${ABHAILE_SYSTEM_SYSTEMD_RESOLVED_CONF}"
export CONTAINER_SYSTEMD_DIR="${ABHAILE_CONTAINERS_QUADLETS_ROOTFUL_DIR}"
export BACKUP_DIR_BASE="${ABHAILE_SYSTEM_BACKUP_DIR}"
export XDG_RUNTIME_DIR_TEMPLATE="${XDG_RUNTIME_DIR_TEMPLATE:-/run/user}"

usage() {
    cat >&2 << 'EOF'
apply.sh - Atomic systemd-networkd deployment

Usage:
  apply.sh [OPTIONS] [HOSTNAME]

Arguments:
  HOSTNAME    Target host to apply to (phobos/deimos, default: current hostname)

Options:
  --host HOSTNAME   Target host (alternative to positional argument)
  --mode MODE       Deployment mode: dry-run (default) or apply
  --apply           Apply changes to live system (default: dry-run)
  --dry-run-dir DIR Use custom directory for dry-run (default: ./out/)
  --verbose         Enable verbose output
  --skip-render     Reuse existing rendered output (skip cli.py)
    --skip-desec      Skip external DNS (deSEC) entirely
    --strict-desec    Fail if deSEC drift/apply cannot complete
    --skip-desec-sync Reuse existing deSEC plan (skip drift check)
  --help            Show this message

Examples:
  ./apply.sh phobos                              # Dry-run to ./out/
  ./apply.sh --host phobos --mode dry-run        # Dry-run (explicit)
  ./apply.sh --host phobos --mode apply          # Apply mode (explicit)
  ./apply.sh --dry-run-dir ./out_phobos phobos  # Dry-run to ./out_phobos/
  sudo ./apply.sh --apply phobos                 # Apply to production
EOF
}

# validate_hostname - Pre-validate hostname exists in configuration (L6)
# Usage: validate_hostname "$target_host" "$root_dir"
# Args: $1 = hostname to validate, $2 = repository root directory
# Returns: nothing
# Exit: 0 if valid, 1 if not found
# Note: Checks mapping.yaml for host entry
validate_hostname() {
	local target_host="$1"
	local root_dir="$2"
	local mapping_file="$root_dir/config/mapping.yaml"

	if [[ ! -f "$mapping_file" ]]; then
		log_warn "Cannot pre-validate hostname (mapping.yaml not found)"
		return 0  # Non-fatal; will be caught later by render
	fi

	# Check if hostname exists in mapping.yaml
	if ! grep -q "^${target_host}:" "$mapping_file"; then
		log_error "Host '$target_host' not found in configuration"
		log_error "Available hosts in mapping.yaml:"
		grep -E '^[a-z][a-z0-9-]*:' "$mapping_file" | sed 's/:.*$//' | sed 's/^/  - /'
		return 1
	fi

	return 0
}

# parse_args - Parse command-line arguments for apply.sh
# Usage: parse_args "$@"
# Args: $@ = all command-line arguments
# Returns: nothing (sets global variables: TARGET_HOST, DRY_RUN, DRY_RUN_DIR, VERBOSE, etc.)
# Exit: 0 on success, 1 if unknown option or invalid mode
# Note: Respects VERBOSE environment variable; can be overridden with --verbose flag (L7)
parse_args() {
    # L7: Respect VERBOSE from environment (set by gitops_runner.sh)
    if [[ -n "${VERBOSE:-}" && "$VERBOSE" != "0" ]]; then
        export VERBOSE=1
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --host) shift; TARGET_HOST="$1" ;;
            --mode)
                shift
                case "$1" in
                    dry-run) DRY_RUN=1 ;;
                    apply) DRY_RUN=0 ;;
                    *) log_error "Invalid mode: $1 (use 'dry-run' or 'apply')"; usage; exit 1 ;;
                esac
                ;;
            --apply) DRY_RUN=0 ;;
            --dry-run-dir) shift; DRY_RUN_DIR="$1" ;;
            --verbose) export VERBOSE=1 ;;
            --skip-render) export SKIP_RENDER=1 ;;
            --skip-desec) export SKIP_DESEC=1 ;;
            --strict-desec) export STRICT_DESEC=1 ;;
            --skip-desec-sync) export SKIP_DESEC_SYNC=1 ;;
            --help) usage; exit 0 ;;
            *)
                if [[ "$1" != -* ]]; then
                    TARGET_HOST="$1"
                else
                    log_error "Unknown option: $1"; usage; exit 1
                fi
                ;;
        esac
        shift
    done
    [[ -z "$TARGET_HOST" ]] && TARGET_HOST=$(hostname)

    # L6: Pre-validate hostname exists in configuration
    if ! validate_hostname "$TARGET_HOST" "$ROOT_DIR"; then
        exit 1
    fi

    return 0
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    local dev_render_dir="${DRY_RUN_DIR:-$ROOT_DIR/out}/rendered"
    local dev_state_dir="${DRY_RUN_DIR:-$ROOT_DIR/out}/state"
    if [[ $DRY_RUN -eq 0 ]]; then
        export RENDER_DIR="$PROD_RENDER_DIR"; export STATE_DIR="$PROD_STATE_DIR"; export NET_CONFIG_DIR="$PROD_NET_CONFIG_DIR"; export SOFTWARE_TARGET_DIR="$PROD_SOFTWARE_DIR"
        log_info "Apply mode: using production directories"
    else
        export RENDER_DIR="$dev_render_dir"; export STATE_DIR="$dev_state_dir"; export SOFTWARE_TARGET_DIR="${DRY_RUN_DIR:-$ROOT_DIR/out}/software"
        [[ -n "${DRY_RUN_DIR:-}" ]] && log_info "Dry-run mode: using custom directory $DRY_RUN_DIR" || log_info "Dry-run mode: using default directory ./out/"
        [[ -d "$PROD_STATE_DIR" ]] && log_info "Production state found at $PROD_STATE_DIR"
    fi
    mkdir -p "$STATE_DIR"
    mkdir -p "$SOFTWARE_TARGET_DIR"
    if [[ ! -f "$ROOT_DIR/tools/render/cli.py" ]]; then log_error "cli.py not found"; exit 1; fi
    command -v systemd-analyze >/dev/null || { log_error "systemd-analyze not found"; exit 1; }
    command -v ip >/dev/null || { log_error "ip command not found"; exit 1; }
    if [[ $DRY_RUN -eq 0 && $EUID -ne 0 ]]; then log_error "--apply requires root"; exit 1; fi
    log_ok "Prerequisites OK"
}
