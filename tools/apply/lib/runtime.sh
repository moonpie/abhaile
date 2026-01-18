#!/bin/bash
# runtime.sh - runtime operations (reload, connectivity, arp)

# reload_networkd - Reload systemd-networkd service with timeout and validation
# Usage: reload_networkd [backup_dir]
# Args: $1 = (optional) backup directory to restore on failure
# Returns: nothing
# Exit: 0 on success, 1 if reload failed or validation failed
# Note: Uses 30-second timeout; validates service active after reload; restores backup on failure
reload_networkd() {
    local backup_dir="${1:-}"
    log_info "Reloading systemd-networkd..."

    # Attempt reload with 30-second timeout
    if timeout 30 systemctl reload systemd-networkd 2>&1 | tee /tmp/networkd-reload.log; then
        # Wait for service to stabilize
        sleep 2

        # Validate service is active
        if ! systemctl is-active systemd-networkd >/dev/null 2>&1; then
            log_error "systemd-networkd is not active after reload"
            if [[ -n "$backup_dir" ]]; then
                log_warn "Attempting automatic rollback from $backup_dir"
                restore_networkd_backup "$backup_dir"
            fi
            return 1
        fi

        log_ok "systemd-networkd reloaded successfully"
    else
        local rc=$?
        log_error "Failed to reload systemd-networkd (exit code: $rc)"

        # Check if timeout occurred (exit code 124)
        if [[ $rc -eq 124 ]]; then
            log_error "Reload timed out after 30 seconds"
        fi

        # Attempt automatic rollback
        if [[ -n "$backup_dir" ]]; then
            log_warn "Attempting automatic rollback from $backup_dir"
            restore_networkd_backup "$backup_dir"
        fi
        return 1
    fi
}

# restore_networkd_backup - Restore systemd-networkd configuration from backup
# Usage: restore_networkd_backup <backup_dir>
# Args: $1 = backup directory path
# Returns: nothing
# Exit: 0 on success, 1 if restoration failed
# Note: Removes current config, copies from backup, reloads service
restore_networkd_backup() {
    local backup_dir="$1"

    if [[ ! -d "$backup_dir" ]]; then
        log_error "Backup directory not found: $backup_dir"
        return 1
    fi

    log_info "Restoring networkd configuration from backup..."

    # Remove current configuration
    if [[ -d "$SYSTEMD_NETWORK_DIR" ]]; then
        rm -rf "${SYSTEMD_NETWORK_DIR:?}"/*
    fi

    # Restore from backup
    if cp -r "$backup_dir"/* "$SYSTEMD_NETWORK_DIR/" 2>/dev/null; then
        log_ok "Configuration restored from backup"
    else
        log_error "Failed to restore configuration from backup"
        return 1
    fi

    # Reload with restored configuration (no backup this time to avoid recursion)
    log_info "Reloading with restored configuration..."
    if timeout 30 systemctl reload systemd-networkd 2>&1; then
        sleep 2
        if systemctl is-active systemd-networkd >/dev/null 2>&1; then
            log_ok "Rollback successful; systemd-networkd is active"
            return 0
        else
            log_error "Rollback failed; systemd-networkd is not active"
            return 1
        fi
    else
        log_error "Rollback failed; reload command failed"
        return 1
    fi
}

# send_gratuitous_arp - Send gratuitous ARP for all service /32 addresses
# Usage: send_gratuitous_arp
# Args: none (uses $RENDER_DIR and $TARGET_HOST from environment)
# Returns: nothing
# Exit: 0 (logs announcements via log_ok)
# Note: Sends 3 ARP packets per address using arping or ip neighbor proxy
#       Parses .network file [Match] Name= to extract interface (robust against template changes)
send_gratuitous_arp() {
    log_info "Sending gratuitous ARP for service addresses..."
    local render_subdir="$RENDER_DIR/$TARGET_HOST/systemd-networkd"
    local conf_file arp_sent=0
    while IFS= read -r conf_file; do
        [[ -z "$conf_file" || ! -f "$conf_file" ]] && continue
        while IFS= read -r line; do
            if [[ $line =~ Address=([0-9.]+)/32 ]]; then
                local address="${BASH_REMATCH[1]}" interface=""
                # Parse .network file [Match] Name= to extract interface
                # Assumes .conf file is in NN-<name>.network.d/ directory
                local dir_name; dir_name=$(dirname "$conf_file")
                local network_file="${dir_name%.d}.network"
                if [[ ! -f "$network_file" ]]; then
                    log_warn "Cannot find network file $network_file for $conf_file"
                    continue
                fi
                # Extract Name= from [Match] section
                interface=$(awk '/^\[Match\]/,/^\[/ {
                    if ($0 ~ /^Name=/) {
                        sub(/^Name=/, "", $0)
                        gsub(/^[ \t]+|[ \t]+$/, "", $0)
                        print $0
                        exit
                    }
                }' "$network_file")

                if [[ -z "$interface" ]]; then
                    log_warn "Cannot extract interface name from $network_file"
                    continue
                fi

                # Verify interface exists before sending ARP
                if ip link show dev "$interface" >/dev/null 2>&1; then
                    # Send gratuitous ARP using arping (3 packets, 1 second interval)
                    if command -v arping >/dev/null 2>&1; then
                        arping -c 3 -A -I "$interface" "$address" >/dev/null 2>&1 && \
                            log_ok "Gratuitous ARP: $address on $interface" && ((arp_sent++))
                    else
                        # Fallback: use ip neighbor proxy if arping not available
                        if ip neighbor add proxy "$address" dev "$interface" 2>/dev/null; then
                            log_ok "Gratuitous ARP (proxy): $address on $interface"; ((arp_sent++))
                        fi
                    fi
                fi
            fi
        done < "$conf_file"
    done < <(find "$render_subdir" -name "*.conf" 2>/dev/null)
    [[ $arp_sent -gt 0 ]] && log_ok "Sent $arp_sent gratuitous ARP announcements"
}

# validate_connectivity - Validate host network connectivity
# Usage: validate_connectivity
# Args: none
# Returns: nothing
# Exit: 0 if all checks passed, 1 if critical checks failed
# Checks: primary interface UP, default route exists, systemd-resolved status
validate_connectivity() {
    log_info "Validating connectivity..."
    local errors=0 primary_iface="enp0s31f6"
    local link_output
    link_output=$(ip link show dev "$primary_iface" 2>&1)
    if ! echo "$link_output" | grep -q "UP"; then
        log_error "Primary interface $primary_iface is not UP"; ((errors++))
    else
        log_ok "Primary interface $primary_iface is UP"
    fi
    local route_output
    route_output=$(ip route 2>&1)
    if ! echo "$route_output" | grep -q "default"; then
        log_error "No default route found"; ((errors++))
    else
        log_ok "Default route is present"
    fi
    if systemctl status systemd-resolved >/dev/null 2>&1; then
        log_ok "systemd-resolved is active"
    else
        log_warn "systemd-resolved not active (may be expected)"
    fi
    if [[ $errors -gt 0 ]]; then
        log_warn "Some connectivity checks failed"; return 1
    fi
    log_ok "Connectivity validation passed"; return 0
}
