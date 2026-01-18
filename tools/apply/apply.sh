#!/bin/bash
# apply.sh - Atomic systemd-networkd configuration deployment
#
# Path model (dev vs prod):
# All paths are defined in tools/paths.ini and loaded via tools/bash_lib/paths.sh
# - Dev mode (detected via out/ directory): uses paths.ini [development] section
# - Prod mode: uses paths.ini [runtime] and [system] sections
# - Repo root detected via this script location (../../). No env override.
# - Render/state directories set via ABHAILE_RENDERED_DIR and ABHAILE_STATE_DIR (from paths.ini)
# - System targets: /etc/systemd/network (prod) or dry-run dirs in tmp when not applying.
# - Services/software: follow render output under $RENDER_DIR/$TARGET_HOST; software sync validates safe paths.
# --skip-render requires existing rendered output and guards that sources are not newer than rendered.
#
# Usage:
#   ./apply.sh [OPTIONS] [HOSTNAME]
#
# Arguments:
#   HOSTNAME: Target host (phobos/deimos). If not specified, uses current hostname.
#
# Options:
#   --apply       Apply changes to live system (default: dry-run)
#   --verbose     Enable verbose output
#   --help        Show this message
#
# Default: dry-run (renders and validates without applying)
# --apply: Actually replaces files and reloads systemd-networkd
# --help: Show this message
#
# This script:
# 1. Runs tools/render/cli.py to render templates
# 2. Validates rendered .network/.netdev files with systemd-analyze
# 3. Compares against live config (drift detection)
# 4. Stages to /tmp for atomic replacement
# 5. Atomically replaces in /etc/systemd/network/ (if --apply)
# 6. Reloads systemd-networkd (if --apply)
# 7. Sends gratuitous ARP for /32 service IPs
# 8. Validates connectivity

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Load path configuration from tools/paths.ini
# Sets ABHAILE_* environment variables for all system paths
# shellcheck source=tools/bash_lib/paths.sh
if [[ -f "$ROOT_DIR/tools/bash_lib/paths.sh" ]]; then
    ABHAILE_PATHS_NO_AUTO=1  # Don't auto-load on source
    # shellcheck disable=SC1091
    source "$ROOT_DIR/tools/bash_lib/paths.sh"
    # Auto-detect dev mode (checks for out/ directory)
    abhaile_load_paths
fi

TEMP_DIR="$(mktemp -d "$ROOT_DIR/tmp/abhaile-networkd-XXXXXX")"
readonly TEMP_DIR
TEMP_SERVICES_DIR="$(mktemp -d "$ROOT_DIR/tmp/abhaile-services-XXXXXX")"
readonly TEMP_SERVICES_DIR

# Runtime directories (determined based on --apply and existence)
RENDER_DIR=""
STATE_DIR=""
NET_CONFIG_DIR=""
# COMPARE_DIR=""  # Directory to compare against for drift detection
SOFTWARE_TARGET_DIR=""

# Color codes for output
DRY_RUN=1
VERBOSE=0
TARGET_HOST=""
# DRY_RUN_DIR=""  # Optional custom dry-run directory
SKIP_RENDER=${SKIP_RENDER:-0}    # --skip-render flag (or env var)
# SKIP_DESEC_SYNC=0  # --skip-desec-sync flag
SKIP_DESEC=${SKIP_DESEC:-0}     # --skip-desec flag (skip external DNS entirely, or env var)
STRICT_DESEC=${STRICT_DESEC:-0}   # --strict-desec flag (fail on any deSEC error, or env var)

# Source modular bash libs
source "$SCRIPT_DIR/lib/logging.sh"
source "$SCRIPT_DIR/lib/env.sh"
source "$SCRIPT_DIR/lib/validation.sh"
source "$SCRIPT_DIR/lib/services.sh"
source "$SCRIPT_DIR/lib/drift.sh"
source "$SCRIPT_DIR/lib/staging.sh"
source "$SCRIPT_DIR/lib/apply_phase.sh"
source "$SCRIPT_DIR/lib/runtime.sh"
source "$SCRIPT_DIR/lib/desec.sh"

# render_templates - Render or validate systemd-networkd and service templates via Python render.py
# Usage: render_templates
# Args: none (uses $SKIP_RENDER, $ROOT_DIR, $RENDER_DIR, $TARGET_HOST, $SKIP_DESEC, $STRICT_DESEC)
# Returns: nothing
# Exit: 0 on success, 1 if render fails or guards fail (--skip-render safety checks)
# Note: With --skip-render, validates source configs are not newer than rendered output to prevent stale applies
render_templates() {
    if [[ $SKIP_RENDER -eq 1 ]]; then
        # Guard checks to ensure skipping render is safe
        if [[ ! -d "$RENDER_DIR/$TARGET_HOST/systemd-networkd" ]]; then
            log_error "--skip-render used but no existing rendered directory for $TARGET_HOST"
            exit 1
        fi
        # Check if any source config files are newer than rendered output
        local latest_source_mtime rendered_mtime
        latest_source_mtime=$(find "$ROOT_DIR/config" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -1 || echo 0)
        rendered_mtime=$(find "$RENDER_DIR/$TARGET_HOST" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -1 || echo 0)
        if awk -v s="$latest_source_mtime" -v r="$rendered_mtime" 'BEGIN{exit !(s>r)}'; then
            log_warn "Source configuration newer than rendered output; re-render recommended (omit --skip-render)"
            exit 1
        fi
        # Services-specific guard: ensure services outputs not stale
        local services_render_dir="$RENDER_DIR/$TARGET_HOST/services"
        if [[ -d "$services_render_dir" ]]; then
            local latest_service_source_mtime rendered_services_mtime
            latest_service_source_mtime=$( { find "$ROOT_DIR/config/services" -type f -printf '%T@\n' 2>/dev/null; \
                find "$ROOT_DIR/config" -maxdepth 1 -name 'mapping.yaml' -printf '%T@\n' 2>/dev/null; \
                find "$ROOT_DIR/config" -maxdepth 1 -name 'network.yaml' -printf '%T@\n' 2>/dev/null; } | sort -nr | head -1 || echo 0 )
            rendered_services_mtime=$(find "$services_render_dir" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -1 || echo 0)
            if awk -v s="$latest_service_source_mtime" -v r="$rendered_services_mtime" 'BEGIN{exit !(s>r)}'; then
                log_warn "Service source configuration newer than rendered service output; re-render required (omit --skip-render)"
                exit 1
            fi
            # Require existing services state file if services are present
            if [[ ! -f "$STATE_DIR/services.state" ]]; then
                log_warn "--skip-render used but services.state missing; re-render required to establish services state"
                exit 1
            fi
        fi
        log_info "Skipping render (--skip-render); using existing output"
        return 0
    fi
    log_info "Rendering systemd-networkd templates..."
    cd "$ROOT_DIR" || { log_error "Failed to change directory to $ROOT_DIR"; return 1; }
    local output
    local desec_flags=""
    [[ $SKIP_DESEC -eq 1 ]] && desec_flags+=" --skip-desec"
    [[ $STRICT_DESEC -eq 1 ]] && desec_flags+=" --strict-desec"
    # Render always processes all hosts (requires full context for Caddy, DNS, deSEC)
    if ! output=$(python3 tools/render/cli.py --output-dir "$RENDER_DIR" $desec_flags 2>&1); then
        log_error "cli.py failed"; echo "$output" >&2; exit 1
    fi
    [[ -d "$RENDER_DIR/$TARGET_HOST/systemd-networkd" ]] || { log_error "Rendered files not found"; exit 1; }
    [[ $VERBOSE -eq 1 ]] && echo "$output" | sed 's/^/  /'
    log_ok "Templates rendered to $RENDER_DIR/$TARGET_HOST/systemd-networkd"
}

# (validation now sourced from lib/validation.sh)

# All apply, validation, drift, staging, runtime, and state update functions are sourced from lib/*.sh

# sync_software_artifacts - Copy rendered software artifacts from $RENDER_DIR to $SOFTWARE_TARGET_DIR
# Usage: sync_software_artifacts
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $SOFTWARE_TARGET_DIR, $DRY_RUN)
# Returns: nothing
# Exit: 0 on success, 1 if SOFTWARE_TARGET_DIR unsafe or not set; skips if no software artifacts in render
# Note: Validates SOFTWARE_TARGET_DIR is under /var/lib/, /opt/abhaile/, or /tmp/ (or repo root in dev)
sync_software_artifacts() {
    local source_dir="$RENDER_DIR/$TARGET_HOST/software"
    [[ ! -d "$source_dir" ]] && { log_info "No software artifacts to process"; return 0; }
    if [[ -z "$SOFTWARE_TARGET_DIR" ]]; then
        log_warn "SOFTWARE_TARGET_DIR is not set; skipping software artifact sync"
        return 0
    fi

    # Validate SOFTWARE_TARGET_DIR is under safe base directories
    # Prevent accidental deletion of critical system paths
    # In development (DRY_RUN=1), allow paths under repo root (e.g., ./out/)
    local safe_bases=("/var/lib/" "/opt/abhaile/" "/tmp/")

    # Allow development paths when running in dry-run mode from repo
    if [[ $DRY_RUN -eq 1 && -n "$ROOT_DIR" && "$SOFTWARE_TARGET_DIR" == "$ROOT_DIR"* ]]; then
        log_info "[dry-run] Using development path for SOFTWARE_TARGET_DIR: $SOFTWARE_TARGET_DIR"
    else
        # Production: validate against safe base directories
        local is_safe=0
        for base in "${safe_bases[@]}"; do
            if [[ "$SOFTWARE_TARGET_DIR" == "$base"* ]]; then
                is_safe=1
                break
            fi
        done

        if [[ $is_safe -eq 0 ]]; then
            log_error "SOFTWARE_TARGET_DIR '$SOFTWARE_TARGET_DIR' is not under safe base directories (/var/lib/, /opt/abhaile/, /tmp/)"
            log_error "In dry-run mode, paths under repo root are allowed; in production, use /var/lib/abhaile/"
            exit 1
        fi
    fi

    local dest_dir="$SOFTWARE_TARGET_DIR/$TARGET_HOST"
    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "[dry-run] syncing software artifacts to $dest_dir"
    else
        log_info "Deploying software artifacts to $dest_dir"
    fi
    rm -rf "$dest_dir"
    mkdir -p "$dest_dir"
    cp -a "$source_dir/." "$dest_dir/"
    log_ok "Software artifacts synchronized to $dest_dir"
}

# Cleanup
# cleanup - Remove temporary staging directories created during apply
# Usage: cleanup
# Args: none (uses $TEMP_DIR, $TEMP_SERVICES_DIR)
# Returns: nothing
# Exit: preserves original exit code (does not modify $?)
# Note: Called automatically via trap on script exit; preserves exit code for proper error reporting (L2)
cleanup() {
    local exit_code=$?  # L2: Capture exit code before cleanup

    if [[ -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
    if [[ -d "$TEMP_SERVICES_DIR" ]]; then
        rm -rf "$TEMP_SERVICES_DIR"
    fi
    # Clean up .new state files from interrupted runs (M5)
    if [[ -n "${STATE_DIR:-}" && -d "$STATE_DIR" ]]; then
        rm -f "$STATE_DIR"/*.state.new
    fi
    if [[ -n "${PROD_STATE_DIR:-}" && -d "$PROD_STATE_DIR" ]]; then
        rm -f "$PROD_STATE_DIR"/*.state.new
    fi

    return "$exit_code"  # L2: Restore and exit with original code
}

# Main execution
# main - Orchestrate apply workflow: validate, render, stage, detect drift, apply, reload
# Usage: main
# Args: none (uses global vars from parse_args and environment)
# Returns: nothing
# Exit: 0 on success or dry-run, 1 if any step fails
# Note: Trap cleanup on EXIT; respects DRY_RUN flag for validation without side effects
main() {
    trap cleanup EXIT

    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "=== DRY RUN MODE ==="
    else
        log_info "=== APPLY MODE ==="
    fi

    log_info "Target host: $TARGET_HOST"
    log_info "Render directory: $RENDER_DIR"
    log_info "Config directory: $NET_CONFIG_DIR"
        if [[ $SKIP_DESEC -eq 1 ]]; then
            log_info "External DNS (deSEC): skipped (--skip-desec)"
        elif [[ $STRICT_DESEC -eq 1 ]]; then
            log_info "External DNS (deSEC): strict mode (fail on errors)"
            # Validate DESEC_TOKEN early in strict mode
            if [[ -z "${DESEC_TOKEN:-}" ]]; then
                log_error "DESEC_TOKEN not set; required for strict-desec mode"
                log_error "Set via environment variable or in ~/.config/abhaile/desec.token"
                log_error "Or use --skip-desec to bypass deSEC operations"
                exit 1
            fi
            # Validate token format (should be hex string, 40 chars for deSEC API tokens)
            if ! [[ "$DESEC_TOKEN" =~ ^[a-fA-F0-9]{32,}$ ]]; then
                log_error "DESEC_TOKEN format invalid; expected hexadecimal string (32+ chars)"
                log_error "Check token at ~/.config/abhaile/desec.token or environment"
                exit 1
            fi
            log_ok "DESEC_TOKEN validated"
        else
            log_info "External DNS (deSEC): standard mode (availability warnings only)"
        fi

    check_prerequisites
    render_templates
    validate_systemd_config
    # Check state file freshness before drift detection
    check_state_freshness
    # Drift detection: treat malformed state (rc=2) as fatal, drift (rc=1) as informational
    if ! detect_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    if ! detect_service_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    if ! detect_static_systemd_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    if ! detect_resolved_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    if ! detect_software_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    if ! detect_users_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    if ! detect_desec_drift; then rc=$?; if [[ $rc -eq 2 ]]; then exit 1; fi; fi
    stage_files
    stage_service_files

    # Ensure host directories for named volumes exist (or report in dry-run)
    create_volume_host_dirs

    # Ensure mounted_files host directories exist before apply
    create_mounted_file_dirs

    if [[ $DRY_RUN -eq 1 ]]; then
        sync_software_artifacts
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        log_ok "=== DRY RUN COMPLETE ==="
        log_info "To apply these changes, run: sudo ./tools/apply/apply.sh --apply"
        exit 0
    fi

    # Apply phase
    log_info "=== APPLYING CHANGES ==="
    apply_files
    apply_service_files
    apply_resolved_config
    apply_software_artifacts
    apply_users_config

    # deSEC apply handling respects skip/strict flags
    if [[ $SKIP_DESEC -eq 1 ]]; then
        log_info "Skipping external DNS (deSEC) apply (--skip-desec)"
    else
        if apply_desec_changes; then
            log_ok "External DNS (deSEC) updated successfully"
        else
            rc=$?
            if [[ $STRICT_DESEC -eq 1 ]]; then
                log_error "External DNS (deSEC) update failed (strict mode)"
                exit 1
            fi
            if [[ $rc -eq 2 ]]; then
                log_error "External DNS (deSEC) update failed: missing/invalid DESEC_TOKEN"
            else
                log_warn "External DNS (deSEC) update failed or skipped (continuing deployment)"
            fi
        fi
    fi

    apply_static_systemd_units
    update_state

    # Pass most recent networkd backup to reload for rollback capability
    local latest_backup
    latest_backup=$(find "$BACKUP_DIR_BASE" -maxdepth 1 -type d -name "networkd-*" 2>/dev/null | sort -r | head -n1)

    if ! reload_networkd "$latest_backup"; then
        log_error "Network reload failed; automatic rollback attempted"
        log_error "Manual intervention may be required"
        exit 1
    fi

    validate_connectivity
    send_gratuitous_arp

    log_ok "=== DEPLOYMENT COMPLETE ==="
}

parse_args "$@"
main
