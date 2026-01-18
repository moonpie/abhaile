#!/bin/bash
# Abhaile Path Configuration Loader
# Loads paths from tools/paths.ini for consistent path resolution across Bash tooling
# Usage: source tools/bash_lib/paths.sh

# abhaile_detect_repo_root - Find repository root by locating .git directory
# Returns: prints repo root path to stdout
# Exit: 0 on success, 1 if .git not found
abhaile_detect_repo_root() {
    local current="${BASH_SOURCE[0]}"
    current="$(cd "$(dirname "$current")" && pwd)"

    while [[ "$current" != "/" ]]; do
        if [[ -d "$current/.git" ]]; then
            echo "$current"
            return 0
        fi
        current="$(dirname "$current")"
    done

    echo "[ERROR] Could not find repository root (no .git directory)" >&2
    return 1
}

# abhaile_load_paths - Load all paths from paths.ini into environment variables
# Sets global variables: ABHAILE_* for all paths
# Args: $1 = dev_mode (1 for development paths, 0 for production, default: auto-detect)
# Returns: nothing
# Exit: 0 on success, 1 if paths.ini not found or parse error
abhaile_load_paths() {
    local dev_mode="${1:-}"

    # Find repo root
    local repo_root
    repo_root=$(abhaile_detect_repo_root) || return 1
    export ABHAILE_REPO_ROOT="$repo_root"

    # Path to paths.ini
    local paths_ini="$repo_root/tools/paths.ini"
    if [[ ! -f "$paths_ini" ]]; then
        echo "[ERROR] paths.ini not found at $paths_ini" >&2
        return 1
    fi

    # Parse INI file and export paths
    # Simple INI parser: reads [section] and key = value pairs
    local current_section=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue

        # Section header
        if [[ "$line" =~ ^\[([^]]+)\] ]]; then
            current_section="${BASH_REMATCH[1]}"
            continue
        fi

        # Key = value
        if [[ "$line" =~ ^[[:space:]]*([^=]+)[[:space:]]*=[[:space:]]*(.+)$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local value="${BASH_REMATCH[2]}"
            # Trim whitespace
            key="${key#"${key%%[![:space:]]*}"}"
            key="${key%"${key##*[![:space:]]}"}"
            value="${value#"${value%%[![:space:]]*}"}"
            value="${value%"${value##*[![:space:]]}"}"

            # Convert section.key to ABHAILE_SECTION_KEY
            local var_name="ABHAILE_${current_section^^}_${key^^}"
            var_name="${var_name//-/_}"

            # Resolve relative paths against repo root
            if [[ "$value" != /* ]]; then
                value="$repo_root/$value"
            fi

            export "$var_name=$value"
        fi
    done < "$paths_ini"

    # Auto-detect dev mode if not specified
    # Production mode: repo is at /opt/abhaile (or whatever repo_root is in paths.ini)
    # Development mode: repo is anywhere else
    if [[ -z "$dev_mode" ]]; then
        if [[ -n "${ABHAILE_DEV:-}" ]]; then
            dev_mode=1
        else
            # Compare actual repo location to production repo_root from INI
            local prod_repo_root="${ABHAILE_REPOSITORY_REPO_ROOT}"
            local actual_repo_root
            actual_repo_root=$(cd "$repo_root" && pwd)
            local prod_repo_resolved
            prod_repo_resolved=$(cd "$prod_repo_root" 2>/dev/null && pwd || echo "$prod_repo_root")

            if [[ "$actual_repo_root" == "$prod_repo_resolved" ]]; then
                dev_mode=0  # Production
            else
                dev_mode=1  # Development
            fi
        fi
    fi

    # Override with development paths if dev_mode is enabled
    if [[ $dev_mode -eq 1 ]]; then
        export ABHAILE_RENDERED_DIR="$ABHAILE_DEVELOPMENT_DEV_RENDERED_DIR"
        export ABHAILE_STATE_DIR="$ABHAILE_DEVELOPMENT_DEV_STATE_DIR"
        export ABHAILE_SOFTWARE_DIR="$ABHAILE_DEVELOPMENT_DEV_SOFTWARE_DIR"
    else
        export ABHAILE_RENDERED_DIR="$ABHAILE_RUNTIME_RENDERED_DIR"
        export ABHAILE_STATE_DIR="$ABHAILE_RUNTIME_STATE_DIR"
        export ABHAILE_SOFTWARE_DIR="$ABHAILE_RUNTIME_SOFTWARE_DIR"
    fi

    # Export production repo root for convenience
    export ABHAILE_REPO_ROOT_PROD="$ABHAILE_REPOSITORY_REPO_ROOT"
    export ABHAILE_DEV_MODE="$dev_mode"
}

# Auto-load paths when sourced (unless ABHAILE_PATHS_NO_AUTO is set)
if [[ -z "${ABHAILE_PATHS_NO_AUTO:-}" ]]; then
    abhaile_load_paths
fi
