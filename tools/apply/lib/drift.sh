#!/bin/bash
set -euo pipefail
# drift.sh - drift detection & state update

# file_hash - Calculate SHA256 hash of a file
# Usage: file_hash "$path"
# Args: $1 = file path (required)
# Returns: SHA256 hash (64 hex chars)
# Exit: 0 on success, fails silently if file not found
file_hash() { sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

# check_state_freshness - Validate age of state files and warn if stale
# Usage: check_state_freshness
# Args: none (uses $PROD_STATE_DIR or $STATE_DIR)
# Returns: nothing
# Exit: 0 always (warnings only, no failures)
# Note: Warns if state files are older than 24 hours (86400 seconds)
check_state_freshness() {
    local state_dir
    if [[ $DRY_RUN -eq 0 ]]; then
        state_dir="$PROD_STATE_DIR"
    else
        state_dir="$STATE_DIR"
    fi

    local stale_threshold=86400  # 24 hours in seconds
    local now
    now=$(date +%s)
    local state_files=("networkd.state" "services.state" "systemd.state" "resolved.state" "software.state" "users.state")

    for state_file in "${state_files[@]}"; do
        local state_path="$state_dir/$state_file"
        if [[ ! -f "$state_path" ]]; then
            continue  # Skip missing state files (expected on first run)
        fi

        local file_mtime
        file_mtime=$(stat -c %Y "$state_path" 2>/dev/null || echo "$now")
        local age=$((now - file_mtime))

        if [[ $age -gt $stale_threshold ]]; then
            local age_hours=$((age / 3600))
            log_warn "$state_file is ${age_hours} hours old (threshold: 24h)"
            log_warn "Consider running apply.sh --apply to refresh state"
        fi
    done
}

# validate_simple_state_file - Validate state file format (hash + path)
# Usage: validate_simple_state_file "$state_file" "$state_type"
# Args: $1 = path to state file (required), $2 = state type name for errors (required)
# Returns: nothing
# Exit: 0 if valid or missing, 1 if format invalid
validate_simple_state_file() {
    local state_file="$1"
    local state_type="$2"  # for error messages
    [[ ! -f "$state_file" ]] && return 0  # missing file is OK

    local line_num=0
    while IFS= read -r line; do
        line_num=$((line_num + 1))
        [[ -z "$line" ]] && continue  # skip empty lines

        # Expected format: <hash>  <path>
        if ! echo "$line" | grep -E '^[a-f0-9]{64}  .+$' >/dev/null; then
            log_error "Invalid ${state_type}.state format at line $line_num: expected '<hash>  <path>'"
            return 1
        fi
    done < "$state_file"
    return 0
}

# validate_services_state_file - Validate services state file format (hash + render_path + target_path)
# Usage: validate_services_state_file "$state_file"
# Args: $1 = path to services.state file (required)
# Returns: nothing
# Exit: 0 if valid or missing, 1 if format invalid
validate_services_state_file() {
    local state_file="$1"
    [[ ! -f "$state_file" ]] && return 0  # missing file is OK

    local line_num=0
    while IFS= read -r line; do
        line_num=$((line_num + 1))
        [[ -z "$line" ]] && continue  # skip empty lines

        # Expected format: <hash>  <render_path>  <target_path>
        # Target path should start with /
        if ! echo "$line" | grep -E '^[a-f0-9]{64}  [^ ]+  /.+$' >/dev/null; then
            log_error "Invalid services.state format at line $line_num: expected '<hash>  <render_path>  <target_path>'"
            return 1
        fi
    done < "$state_file"
    return 0
}

# _detect_generic_drift - Internal: detect file drift for networkd/services/systemd
# Usage: _detect_generic_drift "$type" "$scan_path" "$find_expr"
# Args: $1 = type (networkd|services|systemd), $2 = scan path, $3+ = find expression
# Returns: nothing (prints drift to stdout)
# Exit: 0, sets drift_found flag
# Private: called by detect_drift and detect_*_drift functions
_detect_generic_drift() {
    # Args: type (networkd|services|systemd) scan_path [find args...]
    local type="$1"; shift
    local scan_path="$1"; shift

    local new_state_file="$STATE_DIR/${type}.state.new"
    true > "$new_state_file"
    local file
    # Use find with explicit arguments, avoiding eval for safety.
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        local rel_path="${file#$scan_path/}"; local new_hash; new_hash=$(file_hash "$file")
        echo "$new_hash  $rel_path" >> "$new_state_file"
    done < <(find "$scan_path" "$@" -type f -print 2>/dev/null | sort)

    local old_state_file
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state_file="$PROD_STATE_DIR/${type}.state"
    else
        old_state_file="$STATE_DIR/${type}.state"
    fi

    local drift_found=0
    if [[ -f "$old_state_file" ]]; then
        while IFS= read -r new_entry; do
            [[ -z "$new_entry" ]] && continue
            local rel_path="${new_entry#* }"; local new_hash="${new_entry%% *}"
            local old_hash; old_hash=$(grep " $rel_path$" "$old_state_file" 2>/dev/null | awk '{print $1}')
            if [[ -z "$old_hash" ]]; then log_info "  [NEW] $rel_path"; drift_found=1
            elif [[ "$new_hash" != "$old_hash" ]]; then log_info "  [CHANGED] $rel_path"; drift_found=1; fi
        done < "$new_state_file"
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local rel_path="${old_entry#* }"
            if ! grep -q " $rel_path$" "$new_state_file"; then log_info "  [REMOVED] $rel_path"; drift_found=1; fi
        done < "$old_state_file"
    else
        while IFS= read -r new_entry; do
            [[ -z "$new_entry" ]] && continue
            local rel_path="${new_entry#* }"; log_info "  [NEW] $rel_path"
        done < "$new_state_file"; drift_found=1
    fi

    if [[ $drift_found -eq 0 ]]; then
        log_ok "No ${type} configuration drift detected"; return 0
    else
        log_info "${type^} configuration changes detected"; return 1
    fi
}

# detect_drift - Detect drift in networkd configurations
# Usage: detect_drift "$type"
# Args: $1 = drift type (networkd|services|systemd|resolved|software)
# Returns: nothing
# Exit: 0 if no drift, prints drift to stdout
detect_drift() {
    log_info "Detecting configuration drift..."

    # Validate existing networkd.state format before processing
    local old_state
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state="$PROD_STATE_DIR/networkd.state"
    else
        old_state="$STATE_DIR/networkd.state"
    fi
    if ! validate_simple_state_file "$old_state" "networkd"; then
        log_error "Existing networkd.state is malformed; cannot proceed"
        return 2
    fi

    local render_subdir="$RENDER_DIR/$TARGET_HOST/systemd-networkd"
    _detect_generic_drift networkd "$render_subdir" \
        -name '*.network' -o -name '*.netdev' -o -name '*.conf'
}

detect_service_drift() {
    log_info "Detecting service configuration drift..."
    local services_dir="$RENDER_DIR/$TARGET_HOST/services"
    [[ ! -d "$services_dir" ]] && { log_info "No service configurations to deploy"; return 0; }

    local new_state_file="$STATE_DIR/services.state.new"
    true > "$new_state_file"
    local old_state_file
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state_file="$PROD_STATE_DIR/services.state"
    else
        old_state_file="$STATE_DIR/services.state"
    fi

    # Validate existing services.state format before processing
    if ! validate_services_state_file "$old_state_file"; then
        log_error "Existing services.state is malformed; cannot proceed"
        return 2
    fi

    declare -A old_hash_by_target old_render_by_target
    if [[ -f "$old_state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local old_hash old_render old_target
            read -r old_hash old_render old_target <<<"$old_entry"
            [[ -z "$old_target" ]] && old_target="/$old_render"
            old_hash_by_target["$old_target"]="$old_hash"
            old_render_by_target["$old_target"]="$old_render"
        done < "$old_state_file"
    fi

    local drift_found=0
    declare -A touched_targets

    while IFS= read -r service_dir; do
        [[ -z "$service_dir" || ! -d "$service_dir" ]] && continue
        local service_name; service_name=$(basename "$service_dir")
        while IFS= read -r file; do
            [[ -z "$file" || ! -f "$file" ]] && continue
            local rel_path="${file#$service_dir/}"
            local render_rel="$service_name/$rel_path"
            local dest_path
            if ! dest_path=$(service_file_target_path "$service_dir" "$file"); then
                continue
            fi
            local new_hash; new_hash=$(file_hash "$file")
            echo "$new_hash  $render_rel  $dest_path" >> "$new_state_file"
            local old_hash="${old_hash_by_target[$dest_path]:-}"
            if [[ -z "$old_hash" ]]; then
                log_info "  [NEW] $render_rel -> $dest_path"; drift_found=1
            elif [[ "$new_hash" != "$old_hash" ]]; then
                log_info "  [CHANGED] $render_rel -> $dest_path"; drift_found=1
            fi
            touched_targets["$dest_path"]=1
        done < <(find "$service_dir" -type f -print 2>/dev/null | sort)
    done < <(find "$services_dir" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort)

    for target_path in "${!old_hash_by_target[@]}"; do
        if [[ -z "${touched_targets[$target_path]:-}" ]]; then
            local render_rel="${old_render_by_target[$target_path]:-}"
            log_info "  [REMOVED] ${render_rel:-$target_path} -> $target_path"; drift_found=1
        fi
    done

    summarize_service_drift "$services_dir"
    if [[ $drift_found -eq 0 ]]; then
        log_ok "No service configuration drift detected"; return 0
    else
        log_info "Service configuration changes detected"; return 1
    fi
}

detect_static_systemd_drift() {
    log_info "Detecting static systemd units drift..."
    local repo_systemd_dir="$ROOT_DIR/systemd"
    [[ ! -d "$repo_systemd_dir" ]] && { log_info "No static systemd units to deploy"; return 0; }

    # Validate existing systemd.state format before processing
    local old_state
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state="$PROD_STATE_DIR/systemd.state"
    else
        old_state="$STATE_DIR/systemd.state"
    fi
    if ! validate_simple_state_file "$old_state" "systemd"; then
        log_error "Existing systemd.state is malformed; cannot proceed"
        return 2
    fi

    _detect_generic_drift systemd "$repo_systemd_dir" \
        -name '*.service' -o -name '*.path' -o -name '*.timer' -o -name '*.target'
}

detect_resolved_drift() {
    log_info "Detecting systemd-resolved configuration drift..."
    local resolved_dir="$RENDER_DIR/$TARGET_HOST/systemd-resolved/etc/systemd"
    [[ ! -d "$resolved_dir" ]] && { log_info "No systemd-resolved config to deploy"; return 0; }

    # Validate existing resolved.state format before processing
    local old_state
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state="$PROD_STATE_DIR/resolved.state"
    else
        old_state="$STATE_DIR/resolved.state"
    fi
    if ! validate_simple_state_file "$old_state" "resolved"; then
        log_error "Existing resolved.state is malformed; cannot proceed"
        return 2
    fi

    _detect_generic_drift resolved "$resolved_dir" "-type f"
}

detect_software_drift() {
    log_info "Detecting software artifacts drift..."
    local software_dir="$RENDER_DIR/$TARGET_HOST/software"
    [[ ! -d "$software_dir" ]] && { log_info "No software artifacts to deploy"; return 0; }

    local new_state_file="$STATE_DIR/software.state.new"
    true > "$new_state_file"
    local old_state_file
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state_file="$PROD_STATE_DIR/software.state"
    else
        old_state_file="$STATE_DIR/software.state"
    fi

    # Validate existing software.state format before processing
    if ! validate_simple_state_file "$old_state_file" "software"; then
        log_error "Existing software.state is malformed; cannot proceed"
        return 2
    fi

    declare -A old_hash_by_name
    if [[ -f "$old_state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local old_hash old_name
            read -r old_hash old_name <<<"$old_entry"
            old_hash_by_name["$old_name"]="$old_hash"
        done < "$old_state_file"
    fi

    local drift_found=0
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        local rel_path="${file#$software_dir/}"
        local new_hash; new_hash=$(file_hash "$file")
        echo "$new_hash  $rel_path" >> "$new_state_file"
        local old_hash="${old_hash_by_name[$rel_path]:-}"
        if [[ -z "$old_hash" ]]; then
            log_info "  [NEW] $rel_path"; drift_found=1
        elif [[ "$new_hash" != "$old_hash" ]]; then
            log_info "  [CHANGED] $rel_path"; drift_found=1
        fi
    done < <(find "$software_dir" -type f -print 2>/dev/null | sort)

    for old_name in "${!old_hash_by_name[@]}"; do
        if ! grep -q " $old_name$" "$new_state_file"; then
            log_info "  [REMOVED] $old_name"; drift_found=1
        fi
    done

    if [[ $drift_found -eq 0 ]]; then
        log_ok "No software artifacts drift detected"; return 0
    else
        log_info "Software artifacts changes detected"; return 1
    fi
}

detect_users_drift() {
    log_info "Detecting users configuration drift..."
    local users_dir="$RENDER_DIR/$TARGET_HOST/users"
    [[ ! -d "$users_dir" ]] && { log_info "No users configuration to deploy"; return 0; }

    local new_state_file="$STATE_DIR/users.state.new"
    true > "$new_state_file"
    local old_state_file
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state_file="$PROD_STATE_DIR/users.state"
    else
        old_state_file="$STATE_DIR/users.state"
    fi

    # Validate existing users.state format before processing
    if ! validate_simple_state_file "$old_state_file" "users"; then
        log_error "Existing users.state is malformed; cannot proceed"
        return 2
    fi

    declare -A old_hash_by_name
    if [[ -f "$old_state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local old_hash old_name
            read -r old_hash old_name <<<"$old_entry"
            old_hash_by_name["$old_name"]="$old_hash"
        done < "$old_state_file"
    fi

    local drift_found=0
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        local rel_path="${file#$users_dir/}"
        local new_hash; new_hash=$(file_hash "$file")
        echo "$new_hash  $rel_path" >> "$new_state_file"
        local old_hash="${old_hash_by_name[$rel_path]:-}"
        if [[ -z "$old_hash" ]]; then
            log_info "  [NEW] $rel_path"; drift_found=1
        elif [[ "$new_hash" != "$old_hash" ]]; then
            log_info "  [CHANGED] $rel_path"; drift_found=1
        fi
    done < <(find "$users_dir" -type f -print 2>/dev/null | sort)

    for old_name in "${!old_hash_by_name[@]}"; do
        if ! grep -q " $old_name$" "$new_state_file"; then
            log_info "  [REMOVED] $old_name"; drift_found=1
        fi
    done

    if [[ $drift_found -eq 0 ]]; then
        log_ok "No users configuration drift detected"; return 0
    else
        log_info "Users configuration changes detected"; return 1
    fi
}

update_state() {
    local lockfile="/var/lock/abhaile-state-update.lock"
    log_info "Updating state files (acquiring lock)..."

    # Use file descriptor 200 for lock file
    (
        # Acquire exclusive lock with 30-second timeout
        if ! flock -x -w 30 200; then
            log_error "Failed to acquire state lock after 30s timeout (possibly another apply running)"
            return 1
        fi

        log_info "State lock acquired; proceeding with updates..."

        # Atomically move all .new state files to active state
        [[ -f "$STATE_DIR/networkd.state.new" ]] && \
            mv "$STATE_DIR/networkd.state.new" "$STATE_DIR/networkd.state" && \
            log_ok "Networkd state updated"

        [[ -f "$STATE_DIR/services.state.new" ]] && \
            mv "$STATE_DIR/services.state.new" "$STATE_DIR/services.state" && \
            log_ok "Services state updated"

        [[ -f "$STATE_DIR/systemd.state.new" ]] && \
            mv "$STATE_DIR/systemd.state.new" "$STATE_DIR/systemd.state" && \
            log_ok "Systemd units state updated"

        [[ -f "$STATE_DIR/resolved.state.new" ]] && \
            mv "$STATE_DIR/resolved.state.new" "$STATE_DIR/resolved.state" && \
            log_ok "Systemd-resolved state updated"

        [[ -f "$STATE_DIR/software.state.new" ]] && \
            mv "$STATE_DIR/software.state.new" "$STATE_DIR/software.state" && \
            log_ok "Software artifacts state updated"

        [[ -f "$STATE_DIR/users.state.new" ]] && \
            mv "$STATE_DIR/users.state.new" "$STATE_DIR/users.state" && \
            log_ok "Users configuration state updated"

        log_ok "All state files updated atomically"
    ) 200>"$lockfile"

    local lock_status=$?
    if [[ $lock_status -ne 0 ]]; then
        return 1
    fi
}

# Summarize per-service drift (new/changed/removed file counts)
summarize_service_drift() {
    local services_dir="$1"
    local new_state_file="$STATE_DIR/services.state.new"
    local old_state_file
    if [[ $DRY_RUN -eq 0 ]]; then
        old_state_file="$PROD_STATE_DIR/services.state"
    else
        old_state_file="$STATE_DIR/services.state"
    fi
    [[ ! -f "$new_state_file" ]] && return 0

    declare -A new_counts changed_counts removed_counts touched

    declare -A old_hash_by_target old_service_by_target
    if [[ -f "$old_state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local old_hash old_render old_target
            read -r old_hash old_render old_target <<<"$old_entry"
            [[ -z "$old_target" ]] && old_target="/$old_render"
            old_hash_by_target["$old_target"]="$old_hash"
            old_service_by_target["$old_target"]="${old_render%%/*}"
        done < "$old_state_file"
    fi

    declare -A new_targets

    # Build associative arrays for new/changed
    while IFS= read -r new_entry; do
        [[ -z "$new_entry" ]] && continue
        local new_hash render_path target_path
        read -r new_hash render_path target_path <<<"$new_entry"
        [[ -z "$target_path" ]] && target_path="/$render_path"
        local svc="${render_path%%/*}"
        local old_hash="${old_hash_by_target[$target_path]:-}"
        if [[ -z "$old_hash" ]]; then
            new_counts[$svc]=$(( ${new_counts[$svc]:-0} + 1 ))
        elif [[ "$new_hash" != "$old_hash" ]]; then
            changed_counts[$svc]=$(( ${changed_counts[$svc]:-0} + 1 ))
        fi
        touched[$svc]=1
        new_targets["$target_path"]=1
    done < "$new_state_file"

    # Removed files
    for target_path in "${!old_hash_by_target[@]}"; do
        if [[ -z "${new_targets[$target_path]:-}" ]]; then
            local svc="${old_service_by_target[$target_path]:-unknown}"
            removed_counts[$svc]=$(( ${removed_counts[$svc]:-0} + 1 ))
            touched[$svc]=1
        fi
    done

    # If nothing touched, exit quietly
    if [[ ${#touched[@]} -eq 0 ]]; then
        return 0
    fi
    log_info "Per-service drift summary:"
    # Sort service names
    for svc in $(printf '%s\n' "${!touched[@]}" | sort); do
        local n=${new_counts[$svc]:-0}
        local c=${changed_counts[$svc]:-0}
        local r=${removed_counts[$svc]:-0}
        local total=$(( n + c + r ))
        log_info "  Service ${svc}: new=${n} changed=${c} removed=${r} total=${total}"
    done
}
