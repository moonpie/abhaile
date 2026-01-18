#!/bin/bash
# validation.sh - systemd-networkd config validation helpers

# validate_systemd_config - Validate systemd-networkd INI syntax
# Usage: validate_systemd_config
# Args: none (uses $RENDER_DIR and $TARGET_HOST from environment)
# Returns: nothing
# Exit: 0 if all configs valid, 1 if validation errors found
# Note: Uses Python configparser for structural validation; actual systemd validation deferred to runtime
validate_systemd_config() {
    log_info "Validating systemd-networkd configuration..."
    local render_subdir="$RENDER_DIR/$TARGET_HOST/systemd-networkd"
    local validation_errors=0
    local file
    # Python-based structural check: validates INI syntax and section structure.
    # Actual systemd validation happens when systemd-networkd loads the files on the host.
    while IFS= read -r file; do
        [[ -z "$file" || ! -f "$file" ]] && continue
        local filename; filename=$(basename "$file")
        local validation_output
        if ! validation_output=$(python3 -c "
import configparser,sys
try:
    cp=configparser.ConfigParser(strict=False, allow_no_value=True)
    cp.read('$file')
    if len(cp.sections())==0:
        print('ERROR: No sections found'); sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}'); sys.exit(1)
" 2>&1); then
            log_error "Syntax error in $filename: $validation_output"
            ((validation_errors++))
        else
            [[ ${VERBOSE:-0} -eq 1 ]] && log_info "  ✓ $filename"
        fi
    done < <(find "$render_subdir" \( -name "*.network" -o -name "*.netdev" -o -name "*.conf" \) 2>/dev/null)
    if [[ $validation_errors -gt 0 ]]; then
        log_error "Found $validation_errors validation error(s)"; exit 1
    fi
    local count; count=$(find "$render_subdir" \( -name "*.network" -o -name "*.netdev" -o -name "*.conf" \) 2>/dev/null | wc -l)
    log_ok "Configuration validation passed ($count files checked)"
}

# validate_safe_delete_path - Ensure a file path is safe to delete (with symlink resolution)
# Usage: validate_safe_delete_path "$path"
# Args: $1 = absolute file path intended for deletion
# Returns: nothing
# Exit: 0 if safe, 1 if unsafe
# Note: Resolves symlinks to prevent attacks where symlink points outside allowed directories
validate_safe_delete_path() {
    local path="$1"
    [[ -z "$path" ]] && { log_error "Empty path passed to validate_safe_delete_path"; return 1; }

    # Resolve symlinks to canonical path
    local resolved_path
    if command -v readlink >/dev/null 2>&1; then
        resolved_path=$(readlink -f "$path" 2>/dev/null) || resolved_path="$path"
    else
        # Fallback: use realpath if available, otherwise use original path
        if command -v realpath >/dev/null 2>&1; then
            resolved_path=$(realpath "$path" 2>/dev/null) || resolved_path="$path"
        else
            resolved_path="$path"
        fi
    fi

    # Must be absolute (after resolution)
    if [[ "$resolved_path" != /* ]]; then
        log_error "Unsafe delete (not absolute after resolution): $path → $resolved_path"
        return 1
    fi

    # Log symlink resolution if different from original
    if [[ "$resolved_path" != "$path" ]]; then
        log_info "Symlink resolved: $path → $resolved_path"
    fi

    # Allowed base prefixes
    local allowed=(
        "${NET_CONFIG_DIR:-${SYSTEMD_NETWORK_DIR}}/"
        "$SYSTEMD_SYSTEM_DIR/"
        "/etc/containers/systemd/"
        "$SOFTWARE_TARGET_DIR/"
        "$ABHAILE_SYSTEM_SUDOERS_DIR/"
    )

    # Rootless quadlets under /home/<user>/.config/containers/systemd/
    if [[ "$resolved_path" =~ ^/home/[^/]+/\.config/containers/systemd/ ]]; then
        return 0
    fi

    local ok=1
    for base in "${allowed[@]}"; do
        [[ -n "$base" && "$resolved_path" == "$base"* ]] && { ok=0; break; }
    done
    if [[ $ok -ne 0 ]]; then
        log_error "Unsafe delete (outside allowed prefixes): $resolved_path"
        [[ "$resolved_path" != "$path" ]] && log_error "  Original path: $path"
        return 1
    fi
    return 0
}
