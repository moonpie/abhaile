#!/bin/bash
# Abhaile GitOps runner
set -euo pipefail

# Source shared logging
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/bash_lib/logging.sh
if [[ -f "$SCRIPT_DIR/../bash_lib/logging.sh" ]]; then
	# shellcheck disable=SC1090
	source "$SCRIPT_DIR/../bash_lib/logging.sh"
else
	log_info()  { printf '[INFO] %s\n' "$*" >&2; }
	log_error() { printf '[ERROR] %s\n' "$*" >&2; }
fi

# Load paths from paths.ini
if [[ -f "$SCRIPT_DIR/../bash_lib/paths.sh" ]]; then
	# shellcheck disable=SC1091
	source "$SCRIPT_DIR/../bash_lib/paths.sh"
fi

# redact_secrets - Redact sensitive values from log output
# Usage: log_info "$(redact_secrets "some message with $GIT_SSH_KEY")"
# Args: $1 = message with potential secrets
# Returns: message with secrets replaced by [REDACTED]
# Note: Redacts GIT_SSH_KEY, SOPS_AGE_KEY, and common secret patterns
redact_secrets() {
	local message="$1"
	local redacted="$message"

	# Redact file paths containing sensitive keys
	if [[ -n "${GIT_SSH_KEY:-}" ]]; then
		redacted="${redacted//$GIT_SSH_KEY/[REDACTED_SSH_KEY]}"
	fi
	if [[ -n "${SOPS_AGE_KEY:-}" ]]; then
		redacted="${redacted//$SOPS_AGE_KEY/[REDACTED_AGE_KEY]}"
	fi

	# Redact common secret patterns (32+ hex chars, base64 with = padding, etc.)
	# This catches API tokens, hashes, and encoded secrets
	redacted=$(echo "$redacted" | sed -E 's/([a-f0-9]{32,})/[REDACTED_HEX]/g; s/(AGE-SECRET-KEY-[a-zA-Z0-9]+)/[REDACTED_AGE_SECRET]/g')

	echo "$redacted"
}

HOST_INSTANCE="${1:-}"
ENV_FILE="${ABHAILE_GITOPS_ENV_FILE:-/etc/abhaile/gitops/.env}"
# Default SOPS Age key to user home; allow override via SOPS_AGE_KEY_FILE
SOPS_AGE_KEY="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"

if [[ ! -f "$ENV_FILE" ]]; then
    log_error "Env file not found: $ENV_FILE"
    exit 1
fi

# Verify SOPS age key exists
if [[ ! -f "$SOPS_AGE_KEY" ]]; then
    log_warn "SOPS age key not found at $SOPS_AGE_KEY"
    log_warn "SOPS decryption will fail if secrets are encrypted"
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

: "${REPO_URL:?}"
: "${BRANCH:=main}"
: "${WORK_DIR:=${ABHAILE_REPOSITORY_REPO_ROOT:-/opt/abhaile}}"
: "${DRY_RUN:=1}"
: "${AUTO_RESTART:=1}"

# Setup git credentials if provided
if [[ -n "${GIT_SSH_KEY:-}" && -f "$GIT_SSH_KEY" ]]; then
	export GIT_SSH_COMMAND="ssh -i $GIT_SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
fi

log_info "Starting for $HOST_INSTANCE (repo: $REPO_URL, branch: $BRANCH)"
mkdir -p "$WORK_DIR"

if [[ ! -d "$WORK_DIR/.git" ]]; then
	git -C "$WORK_DIR" init
	git -C "$WORK_DIR" remote add origin "$REPO_URL" 2>/dev/null || git -C "$WORK_DIR" remote set-url origin "$REPO_URL"
fi

if ! timeout 60 git -C "$WORK_DIR" fetch --prune origin "$BRANCH"; then
	if [[ $? -eq 124 ]]; then
		log_error "Git fetch timed out after 60 seconds"
	else
		log_error "Git fetch failed"
	fi
	exit 2
fi

# Always checkout the latest from the fetched branch
if ! timeout 30 git -C "$WORK_DIR" checkout -qf FETCH_HEAD; then
	if [[ $? -eq 124 ]]; then
		log_error "Git checkout timed out after 30 seconds"
	else
		log_error "Git checkout failed"
	fi
	exit 2
fi
log_ok "Repo sync complete."

# decrypt_secrets_if_changed - Decrypt SOPS .yaml and .env files from secrets/ to /etc/abhaile/<svc>/
# Usage: decrypt_secrets_if_changed "$WORK_DIR"
# Args: $1 = work directory (repo root)
# Returns: nothing
# Exit: 0 on success, 1 if decryption fails for any SOPS file
# Note: Uses SHA256 hash comparison to detect changes; skips decryption if hash unchanged
#       Stores hashes in /var/lib/abhaile/state/secrets.hash (format: <hash>  <path>)
#       This avoids mtime issues on NFS and with clock skew
decrypt_secrets_if_changed() {
	local work_dir="$1"
	local secrets_dir="$work_dir/secrets"
	local state_file="${ABHAILE_STATE_DIR}/secrets.hash"

	if [[ ! -d "$secrets_dir" ]]; then
		log_info "No secrets directory found; skipping decryption."
		return 0
	fi

	log_info "Checking for SOPS secrets to decrypt..."
	local decrypted_any=0

	# Ensure state directory exists
	mkdir -p "$(dirname "$state_file")"

	# Load existing hashes into associative array
	declare -A previous_hashes
	if [[ -f "$state_file" ]]; then
		while IFS= read -r line; do
			# Parse format: <hash>  <path>
			if [[ "$line" =~ ^([a-f0-9]{64})[[:space:]]+(.+)$ ]]; then
				local hash="${BASH_REMATCH[1]}"
				local path="${BASH_REMATCH[2]}"
				previous_hashes["$path"]="$hash"
			fi
		done < "$state_file"
	fi

	# Temporary file for new state
	local new_state_file="${state_file}.new"
	echo "" > "$new_state_file"

	# Process both .sops.env and .sops.yaml secrets
	find "$secrets_dir" -maxdepth 1 \( -name "*.sops.yaml" -o -name "*.sops.env" \) -print0 |
	while IFS= read -r -d '' sops_file; do
		local service
		if [[ "$sops_file" == *.sops.env ]]; then
			service=$(basename "$sops_file" .sops.env)
		else
			service=$(basename "$sops_file" .sops.yaml)
		fi
		local plaintext_dir="${ABHAILE_SECRETS_BASE_DIR}/$service"

		# Compute current hash of SOPS file
		local current_hash
		current_hash=$(sha256sum "$sops_file" | awk '{print $1}') || {
			log_error "Failed to compute hash for $sops_file"
			return 1
		}

		# Write current hash to new state file
		echo "$current_hash  $sops_file" >> "$new_state_file"

		# Check if hash has changed
		local previous_hash="${previous_hashes[$sops_file]:-}"
		if [[ "$current_hash" == "$previous_hash" ]] && [[ -f "$plaintext_dir/$service.env" ]]; then
			log_info "Hash unchanged for $sops_file; skipping decryption."
			continue
		fi

		log_info "Hash changed for $sops_file; decrypting..."

		mkdir -p "$plaintext_dir"

		# Decrypt and write env file
		if sops -d "$sops_file" > "$plaintext_dir/$service.env.tmp" 2>/dev/null; then
			chmod 0600 "$plaintext_dir/$service.env.tmp"
			mv "$plaintext_dir/$service.env.tmp" "$plaintext_dir/$service.env"
			log_ok "Decrypted and wrote to $plaintext_dir"
			decrypted_any=1
		else
			log_error "Failed to decrypt $sops_file"
			rm -f "$new_state_file"
			return 1
		fi
	done

	# Atomically update state file
	mv "$new_state_file" "$state_file"

	if [[ $decrypted_any -eq 1 ]]; then
		log_info "Secrets decrypted; systemctl daemon-reload may be needed."
	fi
	return 0
}

# read_last_successful_commit - Read last successful commit from gitops.state
# Usage: read_last_successful_commit
# Args: none (uses $STATE_FILE)
# Returns: commit hash on success, empty string if no previous state
# Exit: 0 always (missing file is not an error)
read_last_successful_commit() {
	local state_file="${ABHAILE_FLAGS_GITOPS_STATE_FILE}"
	if [[ ! -f "$state_file" ]]; then
		echo ""
		return 0
	fi
	# Extract commit field from JSON
	if command -v jq &>/dev/null; then
		jq -r '.commit // empty' "$state_file" 2>/dev/null || echo ""
	else
		# Fallback: grep for commit line
		grep -oP '"commit":\s*"\K[^"]+' "$state_file" 2>/dev/null || echo ""
	fi
}

# _validate_commit_hash - Validate commit hash format (40-char hex)
# Usage: _validate_commit_hash "$hash"
# Args: $1 = commit hash to validate
# Returns: nothing
# Exit: 0 if valid, 1 if format invalid
_validate_commit_hash() {
	local hash="$1"
	if [[ ! "$hash" =~ ^[a-f0-9]{40}$ ]]; then
		log_error "Invalid commit hash format: $hash (expected 40-char hex)"
		return 1
	fi
	return 0
}

# _validate_repo_integrity - Check repository integrity
# Usage: _validate_repo_integrity "$work_dir"
# Args: $1 = git repository path
# Returns: nothing
# Exit: 0 if OK, 1 if corrupted
_validate_repo_integrity() {
	local work_dir="$1"
	log_info "Checking repository integrity..."
	if ! git -C "$work_dir" fsck --full >/dev/null 2>&1; then
		log_error "Repository integrity check failed; repo may be corrupted"
		return 1
	fi
	return 0
}

# _commit_exists - Verify commit exists in repository
# Usage: _commit_exists "$work_dir" "$commit"
# Args: $1 = git repository path, $2 = commit hash
# Returns: nothing
# Exit: 0 if commit exists, 1 if not found
_commit_exists() {
	local work_dir="$1"
	local commit="$2"
	if ! git -C "$work_dir" cat-file -e "$commit" 2>/dev/null; then
		log_error "Commit $commit not found in repository"
		log_error "Commit may have been force-pushed or removed from history"
		return 1
	fi
	return 0
}

# Decrypt secrets before delegating to apply.sh
if ! decrypt_secrets_if_changed "$WORK_DIR"; then
    log_error "Secret decryption failed; aborting."
    exit 1
fi

# Delegate all remaining tasks (render, validate, drift, apply) to apply.sh
# Set environment variables for apply.sh
export ROOT_DIR="$WORK_DIR"
export SCRIPT_DIR="$WORK_DIR/tools/apply"
export VERBOSE="${VERBOSE:-}"

# Capture current commit and last successful commit before running apply
CURRENT_COMMIT=$(git -C "$WORK_DIR" rev-parse HEAD)
LAST_SUCCESSFUL_COMMIT=$(read_last_successful_commit)

log_info "Invoking apply.sh for render, validation, drift detection (dry-run only)..."

# Always run apply.sh in dry-run when executing as unprivileged user
"$WORK_DIR/tools/apply/apply.sh" "$HOST_INSTANCE"

APPLY_EXIT=$?
if [[ $APPLY_EXIT -ne 0 ]]; then
    log_error "apply.sh failed with exit code $APPLY_EXIT"

    # Attempt automatic rollback if we have a previous successful commit
    if [[ -n "$LAST_SUCCESSFUL_COMMIT" && "$LAST_SUCCESSFUL_COMMIT" != "$CURRENT_COMMIT" ]]; then
		log_warn "Attempting automatic rollback to last successful commit: $LAST_SUCCESSFUL_COMMIT"

		# Validate commit hash format
		if ! _validate_commit_hash "$LAST_SUCCESSFUL_COMMIT"; then
			log_error "Invalid commit hash in state file; rollback aborted"
			return 1
		fi

		# Check repository integrity before attempting checkout
		if ! _validate_repo_integrity "$WORK_DIR"; then
			log_error "Cannot rollback: repository integrity check failed"
			return 1
		fi

		# Verify commit exists in repository
		if ! _commit_exists "$WORK_DIR" "$LAST_SUCCESSFUL_COMMIT"; then
			log_error "Cannot rollback: commit may have been force-pushed out of history"
			log_error "Manual intervention required; check git history and deploy key state"
			return 1
		fi

		# Checkout last successful commit (with verbose output on error)
		if ! timeout 30 git -C "$WORK_DIR" checkout -f "$LAST_SUCCESSFUL_COMMIT" 2>&1 | log_error_pipe; then
			if [[ $? -eq 124 ]]; then
				log_error "Git checkout timed out after 30 seconds during rollback"
			else
				log_error "Manual intervention required; unable to rollback as git checkout failed"
			fi
			return 1
		fi
		log_info "Rolled back to commit $LAST_SUCCESSFUL_COMMIT"

		# Retry apply once
		log_info "Retrying apply after rollback..."
		if "$WORK_DIR/tools/apply/apply.sh" "$HOST_INSTANCE"; then
			log_ok "Rollback successful; system restored to last known-good state"

            # Write rollback state
            STATE_FILE="${ABHAILE_FLAGS_GITOPS_STATE_FILE}"
            mkdir -p "$(dirname "$STATE_FILE")"
            cat > "$STATE_FILE" <<EOF
{
  "host": "$HOST_INSTANCE",
  "last_run": "$(date -Iseconds)",
  "commit": "$LAST_SUCCESSFUL_COMMIT",
  "branch": "$BRANCH",
  "dry_run": $DRY_RUN,
  "status": "rolled_back",
  "rollback_from": "$CURRENT_COMMIT",
  "rollback_reason": "apply_failure"
}
EOF
            exit 0
        else
            log_error "Rollback attempt failed; manual intervention required"
            exit 1
        fi
    else
        log_error "No previous successful commit available for rollback"
        exit $APPLY_EXIT
    fi
fi

# Update state file
STATE_FILE="${ABHAILE_FLAGS_GITOPS_STATE_FILE}"
mkdir -p "$(dirname "$STATE_FILE")"
cat > "$STATE_FILE" <<EOF
{
  "host": "$HOST_INSTANCE",
  "last_run": "$(date -Iseconds)",
  "commit": "$(git -C "$WORK_DIR" rev-parse HEAD)",
  "branch": "$BRANCH",
  "dry_run": $DRY_RUN,
  "status": "success"
}
EOF

log_ok "GitOps run completed successfully."
exit 0
