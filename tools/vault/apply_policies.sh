#!/usr/bin/env bash
set -euo pipefail

# Apply Vault policies from the `policies/` directory.
# Default: dry-run. Pass --apply to actually write policies.

# Source shared utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/vault_common.sh
source "$SCRIPT_DIR/lib/vault_common.sh"

REPO_ROOT="$(get_repo_root)" || exit 1

APPLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true; shift ;;
    --dry-run) APPLY=false; shift ;;
    -h|--help) echo "Usage: $0 [--dry-run|--apply]"; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

POL_DIR="$REPO_ROOT/policies"
if [[ ! -d "$POL_DIR" ]]; then
  log_vault_error "No policies directory found at $POL_DIR"
  exit 1
fi

log_vault_info "Vault policy apply helper"
log_vault_info "VAULT_ADDR=${VAULT_ADDR:-<not set>}"
if [[ -z "${VAULT_ADDR:-}" ]]; then
  log_vault_warn "Please set VAULT_ADDR and VAULT_TOKEN (or login via 'vault login')"
fi

for f in "$POL_DIR"/*.hcl; do
  [[ -f "$f" ]] || continue
  name=$(basename "$f" .hcl)
  if [[ "$APPLY" = true ]]; then
    log_vault_info "Applying policy: $name -> $f"
    vault policy write "$name" "$f"
  else
    log_vault_info "DRY-RUN: vault policy write $name $f"
  fi
done

log_vault_ok "Done"
