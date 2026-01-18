#!/usr/bin/env bash
set -euo pipefail

echo "[security] Running local security pattern checks..."

# Check 1: No unsafe eval() in shell scripts
if grep -rn --exclude='tools/pre-commit/security_checks.sh' "eval \"" tools/**/*.sh 2>/dev/null | grep -v "# " >/tmp/pc_eval.txt; then
  echo "[security] ✗ Found unsafe eval usage:" >&2
  cat /tmp/pc_eval.txt >&2
  exit 1
fi

# Check 2: No eval find patterns
if grep -rn --exclude='tools/pre-commit/security_checks.sh' "eval \"find" tools/**/*.sh 2>/dev/null >/tmp/pc_eval_find.txt; then
  echo "[security] ✗ Found eval find usage:" >&2
  cat /tmp/pc_eval_find.txt >&2
  exit 1
fi

# Check 3: No broad set +e disabling
if grep -rn --exclude='tools/pre-commit/security_checks.sh' "set +e" tools/**/*.sh 2>/dev/null >/tmp/pc_sete.txt; then
  echo "[security] ✗ Found set +e usage (disable-only blocks):" >&2
  cat /tmp/pc_sete.txt >&2
  exit 1
fi

# Check 4: No unsafe rm -rf
if grep -rn --exclude='tools/pre-commit/security_checks.sh' "rm -rf" tools/**/*.sh 2>/dev/null | grep -vE "TEMP_DIR|TEMP_SERVICES_DIR|dest_dir|# " >/tmp/pc_rmrf.txt; then
  echo "[security] ✗ Found rm -rf usage (non-temp path):" >&2
  cat /tmp/pc_rmrf.txt >&2
  exit 1
fi

# Check 5: cd validation (must have guard on same line)
if grep -rn --exclude='tools/pre-commit/security_checks.sh' --exclude='tools/bootstrap/bootstrap.sh' "^\s*cd\s" tools/**/*.sh 2>/dev/null | grep -vE "\|\||&&|#" >/tmp/pc_cd.txt; then
  echo "[security] ✗ Found unvalidated cd commands:" >&2
  cat /tmp/pc_cd.txt >&2
  exit 1
fi

# Check 6: jq safety (informational warning)
if grep -rn --exclude='tools/pre-commit/security_checks.sh' "jq" tools/**/*.sh 2>/dev/null >/tmp/pc_jq.txt; then
  if ! grep -rn --exclude='tools/pre-commit/security_checks.sh' "numbers\|--raw-output" tools/**/*.sh 2>/dev/null >/dev/null; then
    echo "[security] ⚠ jq usage present; ensure type filters (numbers) or raw-output are used" >&2
  fi
fi

# Check 7: Disabled tests by naming convention
if grep -rn "^def dnsp_\|^def dnsneg_" tests/unit/render/test_dns_builder.py 2>/dev/null >/tmp/pc_tests.txt; then
  echo "[security] ✗ Found disabled tests (dnsp_/dnsneg_ prefixes); use test_ prefix" >&2
  cat /tmp/pc_tests.txt >&2
  exit 1
fi

# Check 8: Hardcoded credentials (informational)
if grep -r "password\|api_key\|secret" tools/ config/ 2>/dev/null | grep -v "VAULT\|deSEC\|example\|#\|test\|mock" >/tmp/pc_creds.txt; then
  echo "[security] ⚠ Potential hardcoded credentials detected; review:" >&2
  cat /tmp/pc_creds.txt >&2 || true
fi

echo "[security] ✓ Security pattern checks passed"
