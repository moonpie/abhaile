#!/bin/bash
# Abhaile Bootstrap Script
# Minimal host enrollment: verify prerequisites, clone repo, print next steps
# Usage: curl -fsSL https://raw.githubusercontent.com/moonpie/abhaile/main/tools/bootstrap/bootstrap.sh | sudo bash -s -- <host> [repo_url] [branch]

set -euo pipefail

# Source shared logging
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/bash_lib/logging.sh
if [[ -f "$SCRIPT_DIR/../bash_lib/logging.sh" ]]; then
        # shellcheck disable=SC1090
        source "$SCRIPT_DIR/../bash_lib/logging.sh"
else
        log_info()  { printf '[INFO] %s\n' "$*"; }
        log_error() { printf '[ERROR] %s\n' "$*" >&2; }
        log_warn()  { printf '[WARN] %s\n' "$*"; }
fi

# Load paths from paths.ini if available (repo may not be cloned yet)
if [[ -f "$SCRIPT_DIR/../bash_lib/paths.sh" ]]; then
        # shellcheck disable=SC2034 # ABHAILE_PATHS_NO_AUTO used by sourced paths.sh
        ABHAILE_PATHS_NO_AUTO=1
        # shellcheck disable=SC1091
        source "$SCRIPT_DIR/../bash_lib/paths.sh"
        abhaile_load_paths
fi

# Default values
REPO_URL="${2:-git@github.com:moonpie/abhaile.git}"
BRANCH="${3:-main}"
# Repository root from paths.ini (loaded above)
GITOPS_WORK_DIR="${ABHAILE_REPOSITORY_REPO_ROOT}"

# Parse arguments
HOST="${1:-}"
if [[ -z "$HOST" ]]; then
        echo "Usage: $0 <host> [repo_url] [branch]" >&2
        echo "Example: $0 phobos git@github.com:moonpie/abhaile.git main" >&2
        exit 1
fi

# Check if running as root
if [[ $EUID -ne 0 ]]; then
        echo "ERROR: This script must be run with sudo" >&2
        exit 1
fi

# Logging helpers
log_step() {
        echo ""
        log_info "=== $* ==="
}

# ============================================================================
# STEP 1: Preflight Checks
# ============================================================================

log_step "Preflight Checks"

# 1.i: Infrastructure checks
log_info "Checking required commands..."
for cmd in git podman systemctl ssh-keygen age sops; do
        if ! command -v "$cmd" &> /dev/null; then
                log_error "Command '$cmd' not found; install required packages first"
                exit 1
        fi
done

# L5: Verify Python dependencies before rendering
log_info "Verifying Python dependencies..."
if ! python3 -c "import jinja2, yaml, jsonschema" 2>/dev/null; then
	log_error "Failed to import required Python packages (jinja2, yaml, jsonschema)"
	log_error "Install with: pip install jinja2 pyyaml jsonschema"
	exit 1
fi
log_ok "Python dependencies verified"

log_info "Detecting OS..."
if ! grep -q "Debian" /etc/os-release 2>/dev/null; then
        log_error "This script requires Debian; detected another OS"
        exit 1
fi

log_info "Checking network connectivity to github.com..."
if ! timeout 5 bash -c 'echo > /dev/tcp/github.com/22' 2>/dev/null; then
        log_error "Cannot reach github.com:22; check network and firewall"
        exit 1
fi

# 1.ii: Base packages (verify they exist; install if missing)
log_info "Verifying base packages..."
REQUIRED_PACKAGES=(git podman systemd-container age sops)
MISSING_PACKAGES=()

for pkg in "${REQUIRED_PACKAGES[@]}"; do
        if ! dpkg -l 2>/dev/null | grep -q "^ii  $pkg "; then
                MISSING_PACKAGES+=("$pkg")
        fi
done

if [[ ${#MISSING_PACKAGES[@]} -gt 0 ]]; then
        log_info "Installing missing packages: ${MISSING_PACKAGES[*]}"
        apt-get update -qq
        apt-get install -y "${MISSING_PACKAGES[@]}" || {
                log_error "Failed to install packages"
                exit 1
        }
fi

log_info "Enabling systemd-networkd and systemd-resolved..."
systemctl disable --now NetworkManager 2>/dev/null || true
systemctl enable --now systemd-networkd systemd-resolved

# 1.iii: Users and permissions
log_info "Checking user and permissions..."

if ! id abhaile &>/dev/null; then
        log_info "Creating unprivileged user 'abhaile' for GitOps..."
        useradd -r -m -d /home/abhaile -s /bin/bash -U abhaile || {
                log_error "Failed to create user 'abhaile'"
                exit 1
        }
fi

log_info "Ensuring abhaile user has necessary directories..."
# Create directories derived from paths.ini file paths
mkdir -p "$(dirname "${ABHAILE_SECRETS_SOPS_AGE_KEY_FILE}")" "$(dirname "${ABHAILE_CREDENTIALS_GIT_SSH_KEY}")"
chown -R abhaile:abhaile /home/abhaile

# Check if root has sudo access (should always be true, but verify)
if ! sudo -n true 2>/dev/null; then
        log_error "Root does not have sudo access; this should not happen"
        exit 1
fi

# validate_key_permissions - Validate key file permissions and ownership
# Usage: validate_key_permissions "$path" "$expected_mode" "$expected_owner" "$expected_group"
# Args: $1=file path, $2=expected mode (e.g., 0600), $3=expected owner, $4=expected group
# Returns: nothing
# Exit: 0 if valid, 1 if permissions/ownership incorrect
validate_key_permissions() {
	local file="$1"
	local expected_mode="$2"
	local expected_owner="$3"
	local expected_group="$4"

	# Check file exists
	if [[ ! -f "$file" ]]; then
		log_error "Key file not found: $file"
		return 1
	fi

	# Check readable
	if [[ ! -r "$file" ]]; then
		log_error "Key file not readable: $file"
		return 1
	fi

	# Get actual permissions (numeric, e.g., 0600)
	local actual_mode
	actual_mode=$(stat -c '%a' "$file" 2>/dev/null || stat -f '%Lp' "$file" 2>/dev/null)

	if [[ "$actual_mode" != "$expected_mode" ]]; then
		log_error "Key file has incorrect permissions: $file"
		log_error "  Expected: $expected_mode, Found: $actual_mode"
		log_error "  Fix with: sudo chmod $expected_mode $file"
		return 1
	fi

	# Get actual owner and group
	local actual_owner actual_group
	actual_owner=$(stat -c '%U' "$file" 2>/dev/null || stat -f '%Su' "$file" 2>/dev/null)
	actual_group=$(stat -c '%G' "$file" 2>/dev/null || stat -f '%Sg' "$file" 2>/dev/null)

	if [[ "$actual_owner" != "$expected_owner" || "$actual_group" != "$expected_group" ]]; then
		log_error "Key file has incorrect ownership: $file"
		log_error "  Expected: $expected_owner:$expected_group, Found: $actual_owner:$actual_group"
		log_error "  Fix with: sudo chown $expected_owner:$expected_group $file"
		return 1
	fi

	return 0
}

# verify_commit_sha - Optional: verify repository is at expected commit (L3)
# Usage: verify_commit_sha "$work_dir" "$expected_sha" (optional; skipped if $expected_sha empty)
# Args: $1 = git repository path, $2 = expected commit SHA (optional)
# Returns: nothing
# Exit: 0 if verified or verification skipped, 1 if mismatch
verify_commit_sha() {
	local work_dir="$1"
	local expected_sha="${2:-}"

	# If no expected SHA provided, skip verification
	if [[ -z "$expected_sha" ]]; then
		return 0
	fi

	# Validate SHA format (40-char hex)
	if ! [[ "$expected_sha" =~ ^[a-f0-9]{40}$ ]]; then
		log_error "Invalid commit SHA format: $expected_sha (expected 40-char hex)"
		return 1
	fi

	# Get current HEAD commit
	local current_sha
	current_sha=$(git -C "$work_dir" rev-parse HEAD 2>/dev/null) || {
		log_error "Cannot read commit SHA from repository"
		return 1
	}

	if [[ "$current_sha" != "$expected_sha" ]]; then
		log_error "Repository at unexpected commit:"
		log_error "  Expected: $expected_sha"
		log_error "  Found:    $current_sha"
		log_error "Possible MITM attack or branch mismatch; verify manually before proceeding"
		return 1
	fi

	log_ok "Repository verified at commit $expected_sha"
	return 0
}

# 1.iv: Keys exist (SSH for git clone, Age for SOPS) with correct permissions
log_info "Validating SSH deploy key for git clone..."
DEPLOY_KEY="${ABHAILE_CREDENTIALS_GIT_SSH_KEY}"
if [[ ! -f "$DEPLOY_KEY" ]]; then
	log_error "SSH deploy key not found at $DEPLOY_KEY"
	log_error "Install the deploy key before running bootstrap:"
	log_error "  sudo install -m 600 -o abhaile -g abhaile <your-key-file> $DEPLOY_KEY"
	exit 1
fi

if ! validate_key_permissions "$DEPLOY_KEY" "600" "abhaile" "abhaile"; then
	log_error "SSH deploy key validation failed"
	exit 1
fi
log_ok "SSH deploy key validated at $DEPLOY_KEY"

log_info "Adding github.com to known_hosts..."
sudo -u abhaile sh -c 'ssh-keyscan -t rsa,ed25519 github.com >> /home/abhaile/.ssh/known_hosts 2>/dev/null' || \
        log_warn "Could not add github.com to known_hosts"

log_info "Validating Age key for abhaile user..."
ABH_AGE_KEY="${ABHAILE_SECRETS_SOPS_AGE_KEY_FILE}"
if [[ ! -f "$ABH_AGE_KEY" ]]; then
	log_error "Age key not found at $ABH_AGE_KEY"
	log_error "Install the Age key before running bootstrap:"
	log_error "  sudo install -m 600 -o abhaile -g abhaile <your-age-key> $ABH_AGE_KEY"
	exit 1
fi

if ! validate_key_permissions "$ABH_AGE_KEY" "600" "abhaile" "abhaile"; then
	log_error "Age key validation failed for abhaile user"
	exit 1
fi
log_ok "Age key validated at $ABH_AGE_KEY"

log_info "Validating Age key for root user..."
ROOT_AGE_KEY="${ABHAILE_SECRETS_SOPS_AGE_KEY_FILE_ROOT}"
if [[ ! -f "$ROOT_AGE_KEY" ]]; then
	log_error "Age key not found at $ROOT_AGE_KEY"
	log_error "Install the Age key before running bootstrap:"
	log_error "  sudo install -m 600 -o root -g root <your-age-key> $ROOT_AGE_KEY"
	exit 1
fi

if ! validate_key_permissions "$ROOT_AGE_KEY" "600" "root" "root"; then
	log_error "Age key validation failed for root user"
	exit 1
fi
log_ok "Age key validated at $ROOT_AGE_KEY"

log_ok "All preflight checks passed"

# ============================================================================
# STEP 2: Clone Repository
# ============================================================================

log_step "Repository Setup"

log_info "Cloning repository to $GITOPS_WORK_DIR..."
mkdir -p "$GITOPS_WORK_DIR"

if [[ ! -d "$GITOPS_WORK_DIR/.git" ]]; then
        log_info "Cloning $REPO_URL (branch: $BRANCH)..."
        sudo -u abhaile git clone --branch "$BRANCH" "$REPO_URL" "$GITOPS_WORK_DIR" || {
                log_error "Git clone failed; check SSH key and repository access"
                exit 1
        }
        log_ok "Repository cloned"
else
        log_info "Repository already exists; fetching latest..."
        cd "$GITOPS_WORK_DIR" || { log_error "Failed to change directory to $GITOPS_WORK_DIR"; exit 1; }
        sudo -u abhaile git fetch origin "$BRANCH"
        sudo -u abhaile git checkout -f "origin/$BRANCH"
        log_ok "Repository updated"
fi

# L3: Optional commit SHA verification (if EXPECTED_COMMIT_SHA provided)
if [[ -n "${EXPECTED_COMMIT_SHA:-}" ]]; then
	log_info "Verifying repository commit SHA (L3 optional verification)..."
	if ! verify_commit_sha "$GITOPS_WORK_DIR" "$EXPECTED_COMMIT_SHA"; then
		log_error "Commit SHA verification failed"
		exit 1
	fi
fi

# Validate host exists in configuration
log_info "Validating host '$HOST' in configuration files..."

# Check mapping.yaml
MAPPING_FILE="$GITOPS_WORK_DIR/config/mapping.yaml"
if [[ ! -f "$MAPPING_FILE" ]]; then
        log_error "Configuration file not found: $MAPPING_FILE"
        exit 1
fi

# Use grep to check if host appears as a top-level key in mapping.yaml
if ! grep -q "^${HOST}:" "$MAPPING_FILE"; then
        log_error "Host '$HOST' not found in $MAPPING_FILE"
        log_error "Available hosts:"
        grep "^[a-z][a-z0-9-]*:" "$MAPPING_FILE" | sed 's/:$//' | sed 's/^/  - /' || echo "  (none)"
        exit 1
fi
log_ok "Host '$HOST' found in mapping.yaml"

# Check network.yaml
NETWORK_FILE="$GITOPS_WORK_DIR/config/network.yaml"
if [[ ! -f "$NETWORK_FILE" ]]; then
        log_error "Configuration file not found: $NETWORK_FILE"
        exit 1
fi

# Check if host appears under hosts: section in network.yaml
if ! grep -A 100 "^hosts:" "$NETWORK_FILE" | grep -q "^  ${HOST}:"; then
        log_error "Host '$HOST' not found in $NETWORK_FILE under 'hosts:' section"
        log_error "Available hosts:"
        grep -A 100 "^hosts:" "$NETWORK_FILE" | grep "^  [a-z][a-z0-9-]*:" | sed 's/:$//' | sed 's/^  /  - /' || echo "  (none)"
        exit 1
fi
log_ok "Host '$HOST' found in network.yaml"

log_ok "Host validation passed"

# ============================================================================
# STEP 3: Next Steps
# ============================================================================

log_step "Bootstrap Complete"

cat <<EOF

✓ Host $HOST bootstrap complete!

What was done:
- Verified commands, OS, network
- Installed base packages (git, podman, systemd-container, age, sops)
- Created unprivileged user 'abhaile'
- Verified SSH deploy key at $DEPLOY_KEY
- Verified Age key at $ABH_AGE_KEY
- Cloned repository to $GITOPS_WORK_DIR

Next steps:
1. Manually trigger the GitOps flow to render, validate, and apply configuration:

   cd $GITOPS_WORK_DIR
   sudo ./tools/gitops/gitops_runner.sh $HOST

2. This will:
   - Render all configuration from config/
   - Validate and drift-check against live system
   - Dry-run apply (no changes made yet)

3. Once validated, apply the configuration:

   cd $GITOPS_WORK_DIR
   sudo ./tools/apply/apply.sh --apply $HOST

4. This will:
   - Apply all configuration changes
   - Install and enable GitOps systemd timer
   - Schedule automatic sync every 15 minutes

For troubleshooting and details, see:
- docs/BOOTSTRAP.md
- docs/OPERATIONS.md
- tools/apply/README.md

EOF

exit 0
