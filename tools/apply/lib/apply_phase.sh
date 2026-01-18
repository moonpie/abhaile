#!/bin/bash
set -euo pipefail
# apply.sh - apply networkd and service configuration files

# apply_files - Apply rendered systemd-networkd .network and .netdev files to host
# Usage: apply_files
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $SYSTEMD_NETWORK_DIR, $BACKUP_DIR_BASE, $STATE_DIR)
# Returns: nothing
# Exit: 0 on success; logs backup location and applied/removed files
# Note: Creates timestamped backup in $BACKUP_DIR_BASE; removes files tracked in networkd.state but not in render
apply_files() {
    log_info "Applying configuration to $SYSTEMD_NETWORK_DIR..."
    local render_subdir="$RENDER_DIR/$TARGET_HOST/systemd-networkd"
    local backup_dir
    backup_dir="$BACKUP_DIR_BASE/networkd-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"
    if [[ -d "$NET_CONFIG_DIR" ]]; then
        cp -r "$NET_CONFIG_DIR"/* "$backup_dir/" 2>/dev/null || true
        log_ok "Backup created at $backup_dir"
    fi
    local file
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        local rel_path="${file#$render_subdir/}"
        local target="$NET_CONFIG_DIR/$rel_path"
        mkdir -p "$(dirname "$target")"
        cp "$file" "$target"
        log_ok "Applied $rel_path"
    done < <(find "$render_subdir" \( -name "*.network" -o -name "*.netdev" -o -name "*.conf" \) 2>/dev/null)
    local state_file="$STATE_DIR/networkd.state"
    if [[ -f "$state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local rel_path="${old_entry#* }"
            local target="$NET_CONFIG_DIR/$rel_path"
            if [[ ! -f "$render_subdir/$rel_path" && -f "$target" ]]; then
                if ! validate_safe_delete_path "$target"; then
                    log_error "Refusing to delete unsafe path: $target"
                    return 1
                fi
                rm "$target"
                log_ok "Removed $rel_path"
            fi
        done < "$state_file"
    fi
    log_ok "Files applied to $NET_CONFIG_DIR"
}

# apply_service_files - Apply service quadlets, volumes, and config files to host
# Usage: apply_service_files
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $SYSTEMD_SYSTEM_DIR, $HOME env vars for rootless)
# Returns: nothing
# Exit: 0 on success, 1 if service_file_target_path fails
# Note: Handles rootful and rootless quadlets; deduplicates shared volumes; removes stale services from state
apply_service_files() {
    log_info "Applying service configuration files..."
    local services_dir="$RENDER_DIR/$TARGET_HOST/services"
    [[ ! -d "$services_dir" ]] && { log_info "No service configurations to apply"; return 0; }
    local backup_dir
    backup_dir="$BACKUP_DIR_BASE/services-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"
    local reloaded=0
    local to_enable=()
    # Track rootless users that need daemon-reload and their units
    declare -A rootless_users_reload
    declare -A rootless_users_units

    local new_state_file="$STATE_DIR/services.state.new"
    declare -A new_targets
    local new_state_available=0
    if [[ -f "$new_state_file" ]]; then
        new_state_available=1
        while IFS= read -r new_entry; do
            [[ -z "$new_entry" ]] && continue
            local _ render_path target_path
            read -r _ render_path target_path <<<"$new_entry"
            [[ -z "$target_path" ]] && target_path="/$render_path"
            new_targets["$target_path"]=1
        done < "$new_state_file"
    else
        log_warn "services.state.new not found; skipping stale service removal"
    fi

    local service_dir
    while IFS= read -r service_dir; do
        [[ -z "$service_dir" || ! -d "$service_dir" ]] && continue
        local service_name; service_name=$(basename "$service_dir")
        log_info "  Applying configs for $service_name..."
        local file
        while IFS= read -r file; do
            [[ -z "$file" || ! -f "$file" ]] && continue
            local rel_path="${file#$service_dir/}"
            local dest_path
            if ! dest_path=$(service_file_target_path "$service_dir" "$file"); then
                continue
            fi

            # Detect rootless quadlets under home/<user>/.config/containers/systemd/
            if [[ "$rel_path" =~ ^home/([^/]+)/\.config/containers/systemd/(.+\.(container|volume|network|kube|image|build))$ ]]; then
                local rootless_user="${BASH_REMATCH[1]}"
                local unit_name="${BASH_REMATCH[2]}"
                local user_home
                user_home=$(getent passwd "$rootless_user" | cut -d: -f6)
                if [[ -z "$user_home" ]]; then
                    log_error "User $rootless_user not found; skipping rootless unit $unit_name"
                    continue
                fi
                dest_path="$user_home/.config/containers/systemd/$unit_name"
                if [[ -f "$dest_path" ]]; then
                    mkdir -p "$backup_dir/$service_name/home/$rootless_user/.config/containers/systemd"
                    cp "$dest_path" "$backup_dir/$service_name/home/$rootless_user/.config/containers/systemd/$unit_name" 2>/dev/null || true
                fi
                mkdir -p "$(dirname "$dest_path")"
                cp "$file" "$dest_path"
                chown "$rootless_user:$rootless_user" "$dest_path"
                log_ok "    Applied rootless $unit_name for user $rootless_user"

                # Track for user daemon-reload and enable
                rootless_users_reload["$rootless_user"]=1
                if [[ "$unit_name" == *.container ]]; then
                    if [[ -z "${rootless_users_units[$rootless_user]:-}" ]]; then
                        rootless_users_units["$rootless_user"]="$unit_name"
                    else
                        rootless_users_units["$rootless_user"]+=" $unit_name"
                    fi
                fi
                continue
            fi

            # Standard rootful path handling
            if [[ -f "$dest_path" ]]; then
                mkdir -p "$backup_dir/$service_name/$(dirname "$rel_path")"
                cp "$dest_path" "$backup_dir/$service_name/$rel_path" 2>/dev/null || true
            fi
            mkdir -p "$(dirname "$dest_path")"
            cp "$file" "$dest_path"
            log_ok "    Applied $rel_path"
            # Track if we installed any systemd unit files to trigger daemon-reload
            if [[ "$dest_path" == $SYSTEMD_SYSTEM_DIR/*.service || "$dest_path" == $SYSTEMD_SYSTEM_DIR/*.path ]]; then
                reloaded=1
                # Queue unit for enablement (basename before extension)
                local unit_name
                unit_name="$(basename "$dest_path")"
                to_enable+=("$unit_name")
            fi
        done < <(find "$service_dir" -type f 2>/dev/null)
    done < <(find "$services_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
    [[ -d "$backup_dir" ]] && log_ok "Service config backup created at $backup_dir"

    # Remove stale service files based on previous state (only when new state is available)
    if [[ $new_state_available -eq 1 && -f "$STATE_DIR/services.state" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local _ old_render old_target
            read -r _ old_render old_target <<<"$old_entry"
            [[ -z "$old_target" ]] && old_target="/$old_render"
            if [[ -z "${new_targets[$old_target]:-}" ]]; then
                if [[ -f "$old_target" ]]; then
                    if ! validate_safe_delete_path "$old_target"; then
                        log_error "Refusing to delete unsafe service path: $old_target"
                        return 1
                    fi
                    rm "$old_target"
                    log_ok "    Removed stale service file $old_target"
                    if [[ "$old_target" == $SYSTEMD_SYSTEM_DIR/* ]]; then
                        reloaded=1
                    fi
                    if [[ "$old_target" =~ ^/home/([^/]+)/\.config/containers/systemd/.+ ]]; then
                        local rootless_user="${BASH_REMATCH[1]}"
                        rootless_users_reload["$rootless_user"]=1
                    fi
                fi
            fi
        done < "$STATE_DIR/services.state"
    fi

    # Reload and enable rootful systemd units
    if [[ $reloaded -eq 1 ]]; then
        log_info "Reloading systemd daemon due to unit changes..."
        if ! systemctl daemon-reload; then
            log_error "systemctl daemon-reload failed; new units not loaded"
            return 1
        fi

        # Enable installed units with verification
        for unit in "${to_enable[@]}"; do
            log_info "Enabling unit $unit"
            if ! systemctl enable "$unit" 2>&1 | tee -a "/tmp/enable_${unit}.log"; then
                log_error "Failed to enable $unit; check /tmp/enable_${unit}.log"
                return 1
            fi

            # Verify enablement succeeded
            if ! systemctl is-enabled "$unit" >/dev/null 2>&1; then
                log_error "Unit $unit enabled but is-enabled check failed"
                return 1
            fi
            log_ok "Unit $unit enabled and verified"
        done
    fi

    # Reload and enable rootless systemd units per user (in sorted order for determinism)
    # Extract and sort rootless users to ensure deterministic iteration order
    local -a sorted_rootless_users
    while IFS= read -r user; do
        [[ -n "$user" ]] && sorted_rootless_users+=("$user")
    done < <(printf '%s\n' "${!rootless_users_reload[@]}" | sort)

    for rootless_user in "${sorted_rootless_users[@]}"; do
        log_info "Reloading systemd --user daemon for $rootless_user..."

        # Validate XDG_RUNTIME_DIR exists before systemctl --user
        local runtime_dir
        runtime_dir="/run/user/$(id -u "$rootless_user")"
        if [[ ! -d "$runtime_dir" ]]; then
            log_error "XDG_RUNTIME_DIR missing for $rootless_user: $runtime_dir"
            return 1
        fi

        # Enable lingering so user services start at boot
        if ! loginctl enable-linger "$rootless_user" 2>/dev/null; then
            log_error "Failed to enable lingering for $rootless_user"
            return 1
        fi

        # Reload user daemon with explicit error handling
        if ! sudo -u "$rootless_user" XDG_RUNTIME_DIR="$runtime_dir" systemctl --user daemon-reload; then
            log_error "systemctl --user daemon-reload failed for $rootless_user"
            return 1
        fi

        # Enable container units
        if [[ -n "${rootless_users_units[$rootless_user]:-}" ]]; then
            # Parse space-separated units safely (avoid glob expansion)
            local units_to_enable
            units_to_enable="${rootless_users_units[$rootless_user]}"
            while IFS=' ' read -r unit; do
                [[ -z "$unit" ]] && continue
                log_info "Enabling rootless unit $unit for $rootless_user"
                if ! sudo -u "$rootless_user" XDG_RUNTIME_DIR="$runtime_dir" systemctl --user enable "$unit"; then
                    log_error "Failed to enable rootless unit $unit for $rootless_user"
                    return 1
                fi
                log_ok "Rootless unit $unit enabled for $rootless_user"
            done < <(echo "$units_to_enable" | tr ' ' '\n' | sort)
        fi
        log_ok "User systemd daemon reloaded for $rootless_user"
    done

    log_ok "Service configuration files applied"
}

# apply_static_systemd_units - Install static .service, .timer, .path, .target units from repo
# Usage: apply_static_systemd_units
# Args: none (uses $ROOT_DIR/systemd, $SYSTEMD_SYSTEM_DIR, $STATE_DIR)
# Returns: nothing
# Exit: 0 on success; skips if no systemd dir found
# Note: Enables .service and .timer by default; removes units tracked in systemd.state but missing from repo
apply_static_systemd_units() {
    # Install and enable static, non-templated systemd units from repo-level systemd folder
    # Also handles removal of units no longer in repo (drift tracking via systemd.state)
    local repo_systemd_dir="$ROOT_DIR/systemd"
    [[ ! -d "$repo_systemd_dir" ]] && { return 0; }
    log_info "Applying static systemd units from $repo_systemd_dir..."
    local reload_needed=0
    local unit

    # First, install/update all units from repo
    while IFS= read -r unit; do
        [[ -z "$unit" || ! -f "$unit" ]] && continue
        local unit_name; unit_name="$(basename "$unit")"
        local dest_path="$SYSTEMD_SYSTEM_DIR/$unit_name"
        cp "$unit" "$dest_path"
        log_ok "Installed $unit_name"
        reload_needed=1
    done < <(find "$repo_systemd_dir" -maxdepth 1 -type f \( -name '*.service' -o -name '*.path' -o -name '*.timer' -o -name '*.target' \) 2>/dev/null)

    # Second, check systemd.state for units that should be removed
    local state_file="$STATE_DIR/systemd.state"
    if [[ -f "$state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local unit_name="${old_entry#* }"
            local dest_path="$SYSTEMD_SYSTEM_DIR/$unit_name"
            # If unit is in old state but not in current repo, remove it
            if [[ ! -f "$repo_systemd_dir/$unit_name" && -f "$dest_path" ]]; then
                if ! validate_safe_delete_path "$dest_path"; then
                    log_error "Refusing to delete unsafe systemd unit path: $dest_path"
                    return 1
                fi
                rm "$dest_path"
                log_ok "Removed $unit_name (no longer in repo)"
                reload_needed=1
            fi
        done < "$state_file"
    fi

    if [[ $reload_needed -eq 1 ]]; then
        log_info "Reloading systemd daemon due to unit changes..."
        if ! systemctl daemon-reload; then
            log_error "systemctl daemon-reload failed for static units"
            return 1
        fi

        # Enable .service and .timer units by default; skip .target unless explicit
        while IFS= read -r unit; do
            local unit_name; unit_name="$(basename "$unit")"
            case "$unit_name" in
                *.service|*.timer)
                    log_info "Enabling unit $unit_name"
                    if ! systemctl enable "$unit_name"; then
                        log_error "Failed to enable $unit_name"
                        return 1
                    fi
                    if ! systemctl is-enabled "$unit_name" >/dev/null 2>&1; then
                        log_error "Unit $unit_name enabled but is-enabled check failed"
                        return 1
                    fi
                    log_ok "Unit $unit_name enabled and verified"
                    ;;
                *) ;;
            esac
        done < <(find "$repo_systemd_dir" -maxdepth 1 -type f \( -name '*.service' -o -name '*.timer' \) 2>/dev/null)
    fi
}

# apply_resolved_config - Apply systemd-resolved.conf to host
# Usage: apply_resolved_config
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $SYSTEMD_RESOLVED_CONF, $STATE_DIR)
# Returns: nothing
# Exit: 0 on success, 1 if restart fails; skips if no resolved config in render
# Note: Restarts systemd-resolved if changes made; removes resolved.conf if no longer in render
apply_resolved_config() {
    log_info "Applying systemd-resolved configuration..."
    local resolved_dir="$RENDER_DIR/$TARGET_HOST/systemd-resolved/etc/systemd"
    [[ ! -d "$resolved_dir" ]] && { log_info "No systemd-resolved config to apply"; return 0; }

    local backup_dir
    backup_dir="$BACKUP_DIR_BASE/resolved-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"

    # Backup existing resolved.conf if present
    if [[ -f "$SYSTEMD_RESOLVED_CONF" ]]; then
        cp "$SYSTEMD_RESOLVED_CONF" "$backup_dir/resolved.conf"
        log_ok "Backup created at $backup_dir/resolved.conf"
    fi

    local reload_needed=0

    # Apply resolved.conf
    local resolved_conf="$resolved_dir/resolved.conf"
    if [[ -f "$resolved_conf" ]]; then
        cp "$resolved_conf" "$SYSTEMD_RESOLVED_CONF"
        log_ok "Applied resolved.conf to $(dirname $SYSTEMD_RESOLVED_CONF)"
        reload_needed=1
    else
        # No resolved.conf in render, check if we should remove it
        local state_file="$STATE_DIR/resolved.state"
        if [[ -f "$state_file" ]] && grep -q "resolved.conf" "$state_file"; then
            # File was previously managed, should remove it
            if [[ -f "$SYSTEMD_RESOLVED_CONF" ]]; then
                if ! validate_safe_delete_path "$SYSTEMD_RESOLVED_CONF"; then
                    log_error "Refusing to delete unsafe resolved path: $SYSTEMD_RESOLVED_CONF"
                    return 1
                fi
                rm "$SYSTEMD_RESOLVED_CONF"
                log_ok "Removed resolved.conf (no longer in render output)"
                reload_needed=1
            fi
        else
            log_info "No resolved.conf found in rendered output"
        fi
    fi

    # Restart systemd-resolved if changes were made
    if [[ $reload_needed -eq 1 ]]; then
        log_info "Restarting systemd-resolved..."
        if systemctl restart systemd-resolved; then
            log_ok "systemd-resolved restarted"
        else
            log_error "Failed to restart systemd-resolved"
            return 1
        fi
    fi
}
# apply_software_artifacts - Copy software artifacts (binaries, configs) from render to target dir
# Usage: apply_software_artifacts
# Args: none (uses $RENDER_DIR, $TARGET_HOST, $SOFTWARE_TARGET_DIR)
# Returns: nothing\n# Exit: 0 on success, 1 if software_target_dir not set; skips if no software dir in render
# Note: Copied to $SOFTWARE_TARGET_DIR/$TARGET_HOST
apply_software_artifacts() {
    log_info "Applying software artifacts..."
    local software_source_dir="$RENDER_DIR/$TARGET_HOST/software"
    [[ ! -d "$software_source_dir" ]] && { log_info "No software artifacts to apply"; return 0; }

    if [[ -z "$SOFTWARE_TARGET_DIR" ]]; then
        log_warn "SOFTWARE_TARGET_DIR not set; skipping software artifact apply"
        return 0
    fi

    local software_target_dir="$SOFTWARE_TARGET_DIR/$TARGET_HOST"
    mkdir -p "$software_target_dir"

    local backup_dir
    backup_dir="$BACKUP_DIR_BASE/software-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"

    # Backup existing software if present
    if [[ -d "$software_target_dir" ]]; then
        cp -r "$software_target_dir"/* "$backup_dir/" 2>/dev/null || true
        log_ok "Backup created at $backup_dir"
    fi

    # Install/update all software files from render
    local file_count=0
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        local rel_path="${file#$software_source_dir/}"
        local target="$software_target_dir/$rel_path"
        mkdir -p "$(dirname "$target")"
        cp "$file" "$target"
        log_ok "Installed software artifact: $rel_path"
        file_count=$((file_count + 1))
    done < <(find "$software_source_dir" -type f -print 2>/dev/null | sort)

    # Remove stale software files based on previous state
    local state_file="$STATE_DIR/software.state"
    if [[ -f "$state_file" ]]; then
        while IFS= read -r old_entry; do
            [[ -z "$old_entry" ]] && continue
            local old_name="${old_entry#* }"
            local target="$software_target_dir/$old_name"
            if [[ ! -f "$software_source_dir/$old_name" && -f "$target" ]]; then
                if ! validate_safe_delete_path "$target"; then
                    log_error "Refusing to delete unsafe software path: $target"
                    return 1
                fi
                rm "$target"
                log_ok "Removed stale software artifact: $old_name"
                file_count=$((file_count + 1))
            fi
        done < "$state_file"
    fi

    log_ok "Software artifacts applied ($file_count files)"
}

# apply_users_config - Apply sudoers and user setup scripts to host
# Usage: apply_users_config
# Args: none (uses $RENDER_DIR, $TARGET_HOST)
# Returns: nothing
# Exit: 0 on success; skips if no users config in render
# Note: Applies sudoers.d-abhaile; stages users.yaml and setup-users.sh at /opt/abhaile/users for manual execution
apply_users_config() {
    log_info "Applying users configuration..."
    local users_source_dir="$RENDER_DIR/$TARGET_HOST/users"
    [[ ! -d "$users_source_dir" ]] && { log_info "No users configuration to apply"; return 0; }

    local backup_dir
    backup_dir="$BACKUP_DIR_BASE/users-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"

    # Apply sudoers configuration
    local sudoers_file="$users_source_dir/sudoers.d-abhaile"
    if [[ -f "$sudoers_file" ]]; then
        local sudoers_target="${ABHAILE_SYSTEM_SUDOERS_DIR}/abhaile"
        if [[ -f "$sudoers_target" ]]; then
            cp "$sudoers_target" "$backup_dir/sudoers.d-abhaile"
        fi
        cp "$sudoers_file" "$sudoers_target"
        chmod 0440 "$sudoers_target"
        log_ok "Applied sudoers configuration to $sudoers_target"
    fi

    # Copy users.yaml and setup-users.sh for manual review/execution
    local users_yaml="$users_source_dir/users.yaml"
    if [[ -f "$users_yaml" ]]; then
        cp "$users_yaml" "$backup_dir/users.yaml" 2>/dev/null || true
        mkdir -p /opt/abhaile/users 2>/dev/null || true
        cp "$users_yaml" /opt/abhaile/users/users.yaml 2>/dev/null || { log_warn "Could not copy users.yaml to /opt/abhaile/users"; true; }
        log_ok "Users definition available at /opt/abhaile/users/users.yaml (manual review required)"
    fi

    local setup_script="$users_source_dir/setup-users.sh"
    if [[ -f "$setup_script" ]]; then
        cp "$setup_script" "$backup_dir/setup-users.sh" 2>/dev/null || true
        mkdir -p /opt/abhaile/users 2>/dev/null || true
        cp "$setup_script" /opt/abhaile/users/setup-users.sh 2>/dev/null || { log_warn "Could not copy setup-users.sh to /opt/abhaile/users"; true; }
        chmod 0755 /opt/abhaile/users/setup-users.sh 2>/dev/null || true
        log_ok "User setup script available at /opt/abhaile/users/setup-users.sh (manual execution required)"
        log_info "  To create/update users, run: sudo /opt/abhaile/users/setup-users.sh"
    fi

    log_ok "Users configuration staged"
}
