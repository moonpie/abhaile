#!/usr/bin/env bash
set -euo pipefail

echo "[bootstrap] Validating bootstrap.sh uses ABHAILE_* variables from paths.ini..."

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
bootstrap_path="${repo_root}/tools/bootstrap/bootstrap.sh"
paths_ini="${repo_root}/tools/paths.ini"

if [[ ! -f "$bootstrap_path" ]]; then
  echo "[bootstrap] ✗ bootstrap.sh not found at $bootstrap_path" >&2
  exit 1
fi

if [[ ! -f "$paths_ini" ]]; then
  echo "[bootstrap] ✗ paths.ini not found at $paths_ini" >&2
  exit 1
fi

# Parse paths.ini to extract all INI keys
declare -A ini_keys
# shellcheck disable=SC2034 # value is not used but needed for parsing
while IFS='=' read -r key value; do
  # Skip comments and empty lines
  [[ "$key" =~ ^[[:space:]]*# ]] && continue
  [[ -z "$key" ]] && continue

  # Skip section markers [section]
  [[ "$key" =~ ^\[.*\]$ ]] && continue

  # Trim whitespace
  key=$(echo "$key" | xargs)

  ini_keys["$key"]=1
done < "$paths_ini"

# Verify that bootstrap.sh uses ABHAILE_* variables sourced from paths.ini
# Expected variables from paths.ini being used in bootstrap.sh:
declare -A expected_vars=(
  ["ABHAILE_REPOSITORY_REPO_ROOT"]="repository.repo_root"
  ["ABHAILE_CREDENTIALS_GIT_SSH_KEY"]="credentials.git_ssh_key"
  ["ABHAILE_SECRETS_SOPS_AGE_KEY_FILE"]="secrets.sops_age_key_file"
)

declare -a errors
errors=()

# Check that bootstrap.sh uses ABHAILE_* variables
for var in "${!expected_vars[@]}"; do
  ini_key="${expected_vars[$var]}"
  # Remove section prefix for lookup
  ini_key_clean="${ini_key#*.}"

  # Verify variable is used in bootstrap.sh
  if ! grep -q "ABHAILE_REPOSITORY_REPO_ROOT\|ABHAILE_CREDENTIALS_GIT_SSH_KEY\|ABHAILE_SECRETS_SOPS_AGE_KEY_FILE" "$bootstrap_path"; then
    errors+=("bootstrap.sh does not use expected ABHAILE_* variables")
    break
  fi

  # Verify INI key exists
  if [[ -z "${ini_keys[$ini_key_clean]:-}" ]]; then
    errors+=("INI key '$ini_key_clean' not found in paths.ini (required for $var)")
  fi
done

# Check that bootstrap.sh sources paths.sh to load ABHAILE_* variables
if ! grep -q 'source.*paths\.sh' "$bootstrap_path" && ! grep -q 'abhaile_load_paths' "$bootstrap_path"; then
  errors+=("bootstrap.sh does not source paths.sh or call abhaile_load_paths")
fi

# Verify bootstrap.sh uses ABHAILE_REPOSITORY_REPO_ROOT for GITOPS_WORK_DIR
if ! grep -q 'GITOPS_WORK_DIR=.*ABHAILE_REPOSITORY_REPO_ROOT' "$bootstrap_path"; then
  errors+=("GITOPS_WORK_DIR not set to ABHAILE_REPOSITORY_REPO_ROOT in bootstrap.sh")
fi

# Verify bootstrap.sh uses ABHAILE_CREDENTIALS_GIT_SSH_KEY for DEPLOY_KEY
if ! grep -q 'DEPLOY_KEY=.*ABHAILE_CREDENTIALS_GIT_SSH_KEY' "$bootstrap_path"; then
  errors+=("DEPLOY_KEY not set to ABHAILE_CREDENTIALS_GIT_SSH_KEY in bootstrap.sh")
fi

# Verify bootstrap.sh uses ABHAILE_SECRETS_SOPS_AGE_KEY_FILE for ABH_AGE_KEY
if ! grep -q 'ABH_AGE_KEY=.*ABHAILE_SECRETS_SOPS_AGE_KEY_FILE' "$bootstrap_path"; then
  errors+=("ABH_AGE_KEY not set to ABHAILE_SECRETS_SOPS_AGE_KEY_FILE in bootstrap.sh")
fi

# Report results
if [[ ${#errors[@]} -gt 0 ]]; then
  echo "[bootstrap] ✗ Bootstrap validation failed:" >&2
  for error in "${errors[@]}"; do
    echo "  - $error" >&2
  done
  exit 1
fi

echo "[bootstrap] ✓ Bootstrap.sh correctly uses ABHAILE_* variables from paths.ini"
