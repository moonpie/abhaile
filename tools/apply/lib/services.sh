#!/bin/bash
set -euo pipefail
# services.sh - helpers for service file path resolution

# service_file_target_path - Resolve target path for service config file
# Usage: service_file_target_path "$service_dir" "$file"
# Args: $1 = service directory path (required), $2 = file path (required)
# Returns: target path (printed to stdout)
# Exit: 0 on success, 1 if rootless user not found
# Note: Maps home/user/.config/ paths to actual user home for rootless containers
service_file_target_path() {
    local service_dir="$1"; local file="$2"
    local rel_path="${file#$service_dir/}"
    local dest_path="/$rel_path"

    if [[ "$rel_path" =~ ^home/([^/]+)/\.config/containers/systemd/(.+\.(container|volume|network|kube|image|build))$ ]]; then
        local rootless_user="${BASH_REMATCH[1]}"
        local unit_name="${BASH_REMATCH[2]}"
        local user_home
        user_home=$(getent passwd "$rootless_user" | cut -d: -f6)
        if [[ -z "$user_home" ]]; then
            log_error "User $rootless_user not found; skipping rootless unit $unit_name"
            return 1
        fi
        dest_path="$user_home/.config/containers/systemd/$unit_name"
    fi

    printf '%s' "$dest_path"
}
