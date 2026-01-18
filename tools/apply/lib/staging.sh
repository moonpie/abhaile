#!/bin/bash
set -euo pipefail
# staging.sh - staging helpers for networkd and service configs

# stage_files - Copy rendered networkd configs to temporary staging directory
# Usage: stage_files
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $TEMP_DIR from environment)
# Returns: nothing
# Exit: 0 (always succeeds; missing files are ignored)
stage_files() {
    log_info "Staging networkd files to temporary directory..."
    local render_subdir="$RENDER_DIR/$TARGET_HOST/systemd-networkd"
    mkdir -p "$TEMP_DIR"
    cp -r "$render_subdir"/* "$TEMP_DIR/" 2>/dev/null || true
    log_ok "Networkd files staged to $TEMP_DIR"
}

# stage_service_files - Copy service quadlets and config files to temporary staging directory
# Usage: stage_service_files
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $TEMP_SERVICES_DIR from environment)
# Returns: nothing
# Exit: 0 (handles missing dirs gracefully)
# Note: Deduplicates shared volume units; stages service container quadlets
stage_service_files() {
    log_info "Staging service configuration files..."
    local services_dir="$RENDER_DIR/$TARGET_HOST/services"
    [[ ! -d "$services_dir" ]] && { log_info "No service configurations to stage"; return 0; }
    mkdir -p "$TEMP_SERVICES_DIR"
    cp -r "$services_dir"/* "$TEMP_SERVICES_DIR/" 2>/dev/null || true
    # Remove per-service host-certs.volume duplicates; rely on shared unit
    find "$TEMP_SERVICES_DIR" -type f -path "*/etc/containers/systemd/*-host-certs.volume" \( -not -path "*/_shared/*" \) -print0 | while IFS= read -r -d '' dup; do
        rm -f "$dup"
        log_info "Removed duplicate per-service volume: ${dup#$TEMP_SERVICES_DIR/}"
    done
    # Ensure shared volume units are staged even if no per-service files
    local shared_vol_dir="$services_dir/_shared/etc/containers/systemd"
    if [[ -d "$shared_vol_dir" ]]; then
        find "$shared_vol_dir" -type f -name "*.volume" -print0 | while IFS= read -r -d '' f; do
            local rel_path="${f#$services_dir/}"
            mkdir -p "$TEMP_SERVICES_DIR/$(dirname "$rel_path")"
            cp "$f" "$TEMP_SERVICES_DIR/$rel_path"
            log_ok "Staged shared volume unit: $rel_path"
        done
    fi
        # Stage service container quadlets to enable mounted_files directory checks
        if [[ -d "$services_dir" ]]; then
            while IFS= read -r -d '' unit; do
                local rel
                rel="${unit#$services_dir/}"
                local dest_dir
                dest_dir="$TEMP_SERVICES_DIR/$(dirname "$rel")"
                mkdir -p "$dest_dir"
                cp "$unit" "$dest_dir/"
            done < <(find "$services_dir" -type f -name '*.container' -print0 2>/dev/null)
        fi
        # Also stage host-level container quadlets (etc/containers/systemd) used by services
        local quadlet_dir="$RENDER_DIR/$TARGET_HOST/etc/containers/systemd"
        if [[ -d "$quadlet_dir" ]]; then
            while IFS= read -r -d '' unit; do
                local rel
                rel="${unit#$RENDER_DIR/$TARGET_HOST/}"
                local dest_dir
                dest_dir="$TEMP_SERVICES_DIR/$(dirname "$rel")"
                mkdir -p "$dest_dir"
                cp "$unit" "$dest_dir/"
            done < <(find "$quadlet_dir" -type f -name '*.container' -print0 2>/dev/null)
        fi
    log_ok "Service files staged to $TEMP_SERVICES_DIR"
}

create_volume_host_dirs() {
    local vol_root="$TEMP_SERVICES_DIR"
    [[ ! -d "$vol_root" ]] && return 0
    local count=0
    while IFS= read -r -d '' vf; do
        local device
        # Safely extract Device= value, treating grep failure as empty device
        if device=$(grep -E '^Device=' "$vf" 2>/dev/null | head -1); then
            device="${device#*=}"
        else
            device=""
        fi
        [[ -z "$device" ]] && continue
        # Only act on absolute paths
        if [[ "$device" =~ ^/ ]]; then
            if [[ $DRY_RUN -eq 1 ]]; then
                if [[ ! -d "$device" ]]; then
                    log_info "[dry-run] would create volume host directory: $device"
                fi
            else
                if [[ ! -d "$device" ]]; then
                    mkdir -p "$device" || { log_error "Failed to create volume host directory: $device"; return 1; }
                    log_ok "Created volume host directory: $device"
                fi
            fi
            count=$((count+1))
        fi
    done < <(find "$vol_root" -type f -name '*.volume' -print0 2>/dev/null)
    if [[ $VERBOSE -eq 1 ]]; then
        log_info "Processed $count volume units for host directory creation"
    fi
}

create_mounted_file_dirs() {
    # Ensure host directories for mounted_files defined in .container quadlets exist
    local services_root="$TEMP_SERVICES_DIR"
    [[ ! -d "$services_root" ]] && return 0
    local processed=0
    while IFS= read -r -d '' cf; do
        # Extract Volume= lines from container units
        while IFS= read -r line; do
            [[ "$line" != Volume=* ]] && continue
            # Format: Volume=<host_or_volume>:<mount>:<label>[,ro]
            local lhs rest
            lhs="${line#Volume=}"
            # Get the host/volume part (before first colon)
            local host_part="${lhs%%:*}"
            # Only consider absolute host paths; skip named volumes
            if [[ "$host_part" =~ ^/ ]]; then
                local host_dir
                host_dir="$(dirname "$host_part")"
                if [[ $DRY_RUN -eq 1 ]]; then
                    if [[ ! -d "$host_dir" ]]; then
                        log_info "[dry-run] would create mounted_files host directory: $host_dir"
                    fi
                else
                    if [[ ! -d "$host_dir" ]]; then
                        mkdir -p "$host_dir" || { log_error "Failed to create mounted_files directory: $host_dir"; return 1; }
                        chmod 0750 "$host_dir" || { log_error "Failed to chmod mounted_files directory: $host_dir"; return 1; }
                        log_ok "Created mounted_files host directory: $host_dir"
                    fi
                fi
                processed=$((processed+1))
            fi
        done < <(grep -E '^Volume=' "$cf" 2>/dev/null || true)
    done < <(find "$services_root" -type f -name '*.container' -print0 2>/dev/null)
    if [[ $VERBOSE -eq 1 ]]; then
        log_info "Processed $processed mounted_files entries for host directory creation"
    fi
}
