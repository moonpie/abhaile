#!/bin/bash
# desec.sh - deSEC DNS record synchronization for apply.sh

# validate_desec_plan - Validate desec_plan.json structure and required fields
# Usage: validate_desec_plan "$plan_file"
# Args: $1 = path to desec_plan.json (required)
# Returns: nothing
# Exit: 0 if valid or missing, 1 if JSON invalid or missing required fields, 2 if other error
validate_desec_plan() {
    local plan_file="$1"
    [[ ! -f "$plan_file" ]] && return 0  # missing file is OK

    # Validate JSON syntax
    if ! jq empty "$plan_file" 2>/dev/null; then
        log_error "desec_plan.json is not valid JSON"
        return 1
    fi

    # Validate required fields exist
    local has_create has_update has_delete has_desired
    has_create=$(jq 'has("create")' "$plan_file" 2>/dev/null || echo false)
    has_update=$(jq 'has("update")' "$plan_file" 2>/dev/null || echo false)
    has_delete=$(jq 'has("delete")' "$plan_file" 2>/dev/null || echo false)
    has_desired=$(jq 'has("desired_records")' "$plan_file" 2>/dev/null || echo false)

    if [[ "$has_create" != "true" ]] || [[ "$has_update" != "true" ]] || \
       [[ "$has_delete" != "true" ]] || [[ "$has_desired" != "true" ]]; then
        log_error "desec_plan.json missing required fields (create, update, delete, desired_records)"
        return 1
    fi

    return 0
}

# detect_desec_drift - Detect and report deSEC DNS changes
# Usage: detect_desec_drift
# Args: none (uses $STATE_DIR, SKIP_DESEC from environment)
# Returns: nothing
# Exit: 0 if success, 1 if dry-run mode, 2 if validation failed
# Note: Skipped if SKIP_DESEC=1; reports CREATE, UPDATE, DELETE counts
detect_desec_drift() {
    [[ ${SKIP_DESEC:-0} -eq 1 ]] && { log_info "Skipping deSEC drift detection (--skip-desec)"; return 0; }
    local plan_file="$STATE_DIR/desec_plan.json"
    [[ ! -f "$plan_file" ]] && { log_info "No deSEC plan file found"; return 0; }

    # Validate plan file format
    if ! validate_desec_plan "$plan_file"; then
        log_error "desec_plan.json validation failed; cannot detect drift"
        return 2
    fi

    log_info "deSEC DNS drift detection..."

    # Parse desec_plan.json and check for drift
    local create_count update_count delete_count
    if command -v jq &>/dev/null; then
        # Use jq if available
        create_count=$(jq '.create | length' "$plan_file" 2>/dev/null) || create_count="0"
        # Ensure create_count is numeric; default to 0 if not a number
        if ! [[ "$create_count" =~ ^[0-9]+$ ]]; then
            log_warn "jq '.create | length' returned non-numeric: $create_count"
            create_count="0"
        fi
        update_count=$(jq '.update | length' "$plan_file" 2>/dev/null) || update_count="0"
        # Ensure update_count is numeric; default to 0 if not a number
        if ! [[ "$update_count" =~ ^[0-9]+$ ]]; then
            log_warn "jq '.update | length' returned non-numeric: $update_count"
            update_count="0"
        fi
        delete_count=$(jq '.delete | length' "$plan_file" 2>/dev/null) || delete_count="0"
        # Ensure delete_count is numeric; default to 0 if not a number
        if ! [[ "$delete_count" =~ ^[0-9]+$ ]]; then
            log_warn "jq '.delete | length' returned non-numeric: $delete_count"
            delete_count="0"
        fi

        if [[ $((create_count + update_count + delete_count)) -gt 0 ]]; then
            log_info "  Drift detected (has create/update/delete plan):"

            if [[ $create_count -gt 0 ]]; then
                jq -r '.create[] | "    [CREATE] \(.[0][0]) \(.[0][1]) -> \(.[1] | join(", "))"' "$plan_file"
            fi

            if [[ $update_count -gt 0 ]]; then
                jq -r '.update[] | "    [UPDATE] \(.[0][0]) \(.[0][1]) -> \(.[1] | join(", "))"' "$plan_file"
            fi

            if [[ $delete_count -gt 0 ]]; then
                jq -r '.delete[] as [$name, $type] | "    [DELETE] \($name) \($type)"' "$plan_file"
            fi
        else
            log_info "  No drift detected"
        fi
    else
        # Fallback: check if file contains non-empty arrays
        if grep -q '"create":\s*\[' "$plan_file" && \
           ! grep -q '"create":\s*\[\]' "$plan_file"; then
            log_info "  Drift detected (desec_plan.json contains changes)"
        else
            log_info "  No drift detected (or DESEC_TOKEN not set during render)"
        fi
    fi
}

# Apply deSEC DNS changes from plan file
apply_desec_changes() {
    [[ ${SKIP_DESEC:-0} -eq 1 ]] && { log_info "Skipping deSEC apply (--skip-desec)"; return 0; }
    local plan_file="$STATE_DIR/desec_plan.json"
    [[ ! -f "$plan_file" ]] && { log_info "No deSEC plan file; skipping deSEC apply"; return 0; }

    # Validate plan file format before applying
    if ! validate_desec_plan "$plan_file"; then
        log_error "desec_plan.json validation failed; cannot apply changes"
        return 2
    fi

    # Check if there are actual changes to apply
    if command -v jq &>/dev/null; then
        local total_changes
        total_changes=$(jq '.summary.total // 0' "$plan_file" 2>/dev/null || echo 0)
        if [[ $total_changes -eq 0 ]]; then
            log_ok "No deSEC changes to apply"
            return 0
        fi
    fi

    log_info "Applying deSEC DNS changes..."

    # Verify DESEC_TOKEN is available
    if [[ -z "${DESEC_TOKEN:-}" ]]; then
        log_error "DESEC_TOKEN not set; cannot apply deSEC changes (set env var or ~/.config/abhaile/desec.token)"
        return 2
    fi

    # Call unified DNS CLI to apply changes
    cd "$ROOT_DIR" || return 1
    local result
    if result=$(python3 tools/dns/cli.py apply --plan-file "$plan_file" --token "$DESEC_TOKEN" 2>&1); then
        log_ok "deSEC DNS records updated"
        [[ -n "$result" ]] && echo "$result" | sed 's/^/  /'
    else
        local rc=$?
        log_error "Failed to apply deSEC changes"
        echo "$result" >&2
        return $rc
    fi
}
