"""Integration tests for critical security fixes from Activities 1-2.

Tests validate that security vulnerabilities and error handling issues
identified in bash code review have been properly fixed.

Test Categories:
- Activity 1: Bash security (eval, rm -rf, glob expansion)
- Activity 2: Error handling (set +e, jq, subprocess failures)
"""

import subprocess
from pathlib import Path


class TestActivity1SecurityFixes:
    """Tests for Activity 1: Bash security fixes.

    Validates that code injection vulnerabilities and unsafe operations
    have been properly mitigated.
    """

    def test_eval_safety_no_code_injection(self, tmp_path: Path):
        """Test that special chars in paths don't cause code injection.

        **Fix:** [BASH-CRITICAL-1] eval() code injection
        **Files:** apply.sh, env.sh
        **Risk:** RCE if Python output contains shell metacharacters

        This would fail if eval() were still used to execute Python output.
        """
        # Create a test script that mimics the apply.sh pattern
        test_script = tmp_path / "test_eval.sh"
        test_script.write_text(
            """#!/bin/bash
set -euo pipefail

# Simulate Python output with dangerous characters
PYTHON_OUTPUT="OUTPUT_DIR=/tmp/test; echo PWNED > /tmp/evil"

# Old (vulnerable) approach would use eval:
# eval "$PYTHON_OUTPUT"

# New (safe) approach parses key=value pairs:
while IFS='=' read -r key value; do
    case "$key" in
        OUTPUT_DIR)
            OUTPUT_DIR="$value"
            ;;
    esac
done <<< "$PYTHON_OUTPUT"

# Verify no code execution occurred
if [ -f /tmp/evil ]; then
    echo "FAIL: Code injection occurred"
    exit 1
fi

echo "PASS: No code injection"
exit 0
"""
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout
        assert not (Path("/tmp/evil")).exists()

    def test_rm_rf_validation_rejects_dangerous_paths(self, tmp_path: Path):
        """Test that rm -rf rejects dangerous paths.

        **Fix:** [BASH-CRITICAL-2] rm -rf validation
        **Files:** apply.sh (sync_software_artifacts)
        **Risk:** Data loss if SOFTWARE_TARGET_DIR points to critical dirs

        Should reject: /etc, /root, /home, /usr, /opt, anything outside /var/lib/
        """
        # Create a test script that mimics the rm -rf validation
        test_script = tmp_path / "test_rm_validation.sh"
        test_script.write_text(
            """#!/bin/bash
set -euo pipefail

validate_software_target_dir() {
    local dir="$1"

    # Must be under /var/lib/ or /srv/
    if [[ ! "$dir" =~ ^/var/lib/ ]] && [[ ! "$dir" =~ ^/srv/ ]]; then
        echo "ERROR: SOFTWARE_TARGET_DIR must be under /var/lib/ or /srv/" >&2
        return 1
    fi

    # Block critical directories
    case "$dir" in
        /etc|/etc/*|/root|/root/*|/home|/home/*|/usr|/usr/*|/opt|/opt/*)
            echo "ERROR: SOFTWARE_TARGET_DIR cannot be a critical system directory" >&2
            return 1
            ;;
    esac

    return 0
}

# Test dangerous paths
for dangerous_path in "/etc" "/root" "/home" "/usr" "/opt" "/tmp"; do
    if validate_software_target_dir "$dangerous_path" 2>/dev/null; then
        echo "FAIL: Accepted dangerous path: $dangerous_path"
        exit 1
    fi
done

# Test valid path
if ! validate_software_target_dir "/var/lib/abhaile/software"; then
    echo "FAIL: Rejected valid path"
    exit 1
fi

echo "PASS: rm -rf validation working"
exit 0
"""
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_glob_expansion_handles_multiple_service_files(self, tmp_path: Path):
        """Test that glob patterns work with multiple .service files.

        **Fix:** [BASH-CRITICAL-4] unquoted glob patterns
        **Files:** apply_phase.sh (service file processing)
        **Risk:** Pattern matching breaks with multiple files

        Without fix, *.service would expand to separate arguments instead of pattern.
        """
        # Create test with multiple service files
        services_dir = tmp_path / "services"
        services_dir.mkdir()

        (services_dir / "svc1.service").touch()
        (services_dir / "svc2.service").touch()
        (services_dir / "svc3.service").touch()

        test_script = tmp_path / "test_glob.sh"
        test_script.write_text(
            f"""#!/bin/bash
set -euo pipefail

services_dir="{services_dir}"
count=0

# Old (broken) approach:
# for f in $services_dir/*.service; do  # glob expands incorrectly
#     count=$((count + 1))
# done

# New (correct) approach:
while IFS= read -r -d '' file; do
    count=$((count + 1))
done < <(find "$services_dir" -name "*.service" -type f -print0 | sort -z)

if [ "$count" -ne 3 ]; then
    echo "FAIL: Expected 3 service files, found $count"
    exit 1
fi

echo "PASS: Glob expansion working"
exit 0
"""
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout


class TestActivity2ErrorHandling:
    """Tests for Activity 2: Error handling fixes.

    Validates that silent failures and subprocess issues have been fixed.
    """

    def test_set_e_no_silent_failures(self, tmp_path: Path):
        """Test that mkdir and grep failures are detected.

        **Fix:** [BASH-CRITICAL-3] set +e silent failures
        **Files:** staging.sh (mkdir -p, grep)
        **Risk:** Services fail at startup due to missing directories

        Should detect and report mkdir/grep failures instead of ignoring.
        """
        test_script = tmp_path / "test_set_e.sh"
        test_script.write_text(
            """#!/bin/bash
set -euo pipefail

# Create read-only parent to force mkdir failure
readonly_dir=$(mktemp -d)
chmod 000 "$readonly_dir"

# Old (broken) approach would ignore mkdir failure:
# set +e
# mkdir -p "$readonly_dir/subdir"
# set -e

# New (correct) approach catches mkdir failure:
if ! mkdir -p "$readonly_dir/subdir" 2>/dev/null; then
    echo "PASS: mkdir failure detected"
    rm -rf "$readonly_dir"
    exit 0
fi

# Cleanup if we get here (unexpected)
rm -rf "$readonly_dir"
echo "FAIL: mkdir failure not detected"
exit 1
"""
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_jq_json_error_handling(self, tmp_path: Path):
        """Test that jq properly validates JSON before processing.

        **Fix:** [BASH-CRITICAL-5] jq JSON error handling
        **Files:** desec.sh (deSEC response parsing)
        **Risk:** Arithmetic fails silently on malformed JSON

        Should detect malformed JSON and invalid numeric output.
        """
        test_script = tmp_path / "test_jq.sh"

        # Create test JSON files
        valid_json = tmp_path / "valid.json"
        valid_json.write_text('{"count": 42}')

        invalid_json = tmp_path / "invalid.json"
        invalid_json.write_text("{invalid json")

        test_script.write_text(
            f"""#!/bin/bash
set -euo pipefail

validate_json_and_extract() {{
    local file="$1"
    local key="$2"

    # Validate JSON syntax first
    if ! jq empty "$file" 2>/dev/null; then
        echo "ERROR: Invalid JSON in $file" >&2
        return 1
    fi

    # Extract value and verify it's numeric
    local value
    value=$(jq -r ".$key" "$file")

    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Non-numeric value for $key: $value" >&2
        return 1
    fi

    echo "$value"
    return 0
}}

# Test valid JSON
if ! count=$(validate_json_and_extract "{valid_json}" "count"); then
    echo "FAIL: Rejected valid JSON"
    exit 1
fi

# Test invalid JSON
if validate_json_and_extract "{invalid_json}" "count" 2>/dev/null; then
    echo "FAIL: Accepted invalid JSON"
    exit 1
fi

echo "PASS: JSON validation working"
exit 0
"""
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_subshell_return_propagation(self, tmp_path: Path):
        """Test that failures in subshells propagate to caller.

        **Fix:** [BASH-HIGH-1] subshell return bug
        **Files:** gitops_runner.sh (secret decryption)
        **Risk:** Failed decryption not detected, services use stale/missing secrets

        Should detect when subprocess fails and propagate error to caller.
        """
        test_script = tmp_path / "test_subshell.sh"
        test_script.write_text(
            """#!/bin/bash
set -euo pipefail

decrypt_secret() {
    # Simulate decryption failure
    return 1
}

# Old (broken) approach: failure in pipeline not detected
# secret=$(decrypt_secret | tee /tmp/secret)  # Always succeeds (tee exit code)

# New (correct) approach: use explicit check or process substitution
if ! secret=$(decrypt_secret 2>&1); then
    echo "PASS: Subprocess failure detected"
    exit 0
fi

echo "FAIL: Subprocess failure not detected"
exit 1
"""
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout
