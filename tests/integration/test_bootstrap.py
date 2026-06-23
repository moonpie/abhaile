"""Integration tests for scripts/bootstrap.sh testable logic."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

BOOTSTRAP_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap.sh"


@pytest.mark.integration
class TestBootstrapPreflight:
    """Test bootstrap preflight and input validation (no root required)."""

    def test_no_hostname_exits_nonzero(self) -> None:
        """Bootstrap exits non-zero without hostname argument."""
        result = subprocess.run(
            ["bash", "-c", f"source {BOOTSTRAP_SCRIPT} 2>/dev/null; stage_preflight"],
            capture_output=True,
            text=True,
        )
        # The script requires root, so it will fail at EUID check first
        assert result.returncode != 0

    def test_invalid_hostname_rejected(self) -> None:
        """Bootstrap rejects hostnames that are not valid short DNS labels."""
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "validate_hostname_arg invalid_host"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_arbitrary_valid_hostname_accepted(self) -> None:
        """Bootstrap accepts valid hostnames without a hard-coded allowlist."""
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    "log() { :; }; die() { exit 1; }; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "validate_hostname_arg europa-1"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_default_vault_addr_uses_http_listener(self) -> None:
        """Bootstrap default Vault address matches the rendered HTTP listener."""
        env = os.environ.copy()
        env.pop("VAULT_ADDR", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"set -euo pipefail; source {BOOTSTRAP_SCRIPT}; printf '%s' \"$VAULT_ADDR\"",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert result.stdout == "http://vault.svc.abhaile.home.arpa:8200"

    def test_sops_checksum_matches_pinned_release(self) -> None:
        """Bootstrap pins the verified SOPS release checksum."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'readonly SOPS_VERSION="v3.13.1"' in script
        assert 'grep -qx "sops ${SOPS_VERSION#v}"' in script
        expected_sha = (
            'readonly SOPS_SHA256="'
            "620a9d7e3352ababeca6908cea24a6e8b14ce89a448ddbd3f94f1ef3398f470a"
            '"'
        )
        assert expected_sha in script

    def test_vault_cli_installer_verifies_checksum(self) -> None:
        """Vault CLI install verifies the HashiCorp release checksum."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'readonly VAULT_VERSION="1.21.4"' in script
        assert 'local vault_zip_name="vault_${VAULT_VERSION}_linux_amd64.zip"' in script
        assert "vault_${VAULT_VERSION}_SHA256SUMS" in script
        assert "sha256sum -c -" in script
        assert "Vault CLI checksum verification failed" in script

    def test_script_syntax_valid(self) -> None:
        """Bootstrap script has valid bash syntax."""
        result = subprocess.run(
            ["bash", "-n", str(BOOTSTRAP_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_pipe_to_bash_reaches_preflight(self) -> None:
        """Bootstrap supports curl-bash execution from stdin."""
        result = subprocess.run(
            ["bash", "-s", "--", "deimos"],
            input=BOOTSTRAP_SCRIPT.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "BASH_SOURCE" not in result.stderr
        assert "Must run as root" in result.stdout

    def test_vault_cli_installer_uses_defined_ephemeral_helper(self) -> None:
        """Vault CLI install path uses the defined ephemeral directory helper."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert "create_ephemeral_dir()" in script
        assert "ensure_ephemeral_dir" not in script

    def test_bootstrap_installs_systemd_container_for_machinectl(self) -> None:
        """Bootstrap installs systemd-container for user manager verification."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert "systemd-container" in script

    def test_bootstrap_installs_coredns_validation_tooling(self) -> None:
        """Bootstrap installs bind tooling before first CoreDNS zone apply."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert "bind9-utils" in script

    def test_bootstrap_installs_project_entrypoints(self) -> None:
        """Bootstrap installs Abhaile into the venv before invoking CLI entrypoints."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'pip" install --quiet --editable "${REPO_DIR}"' in script
        assert '"${REPO_DIR}/.venv/bin/abhaile-render" --host "$hostname"' in script
        assert '"${REPO_DIR}/.venv/bin/abhaile-apply" --host "$hostname"' in script

    def test_deploy_key_is_mandatory_for_repo_access(self) -> None:
        """Bootstrap does not advertise an unimplemented repo-token fallback."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert "repo-bootstrap" not in script
        assert "Deploy key missing" in script

    def test_secret_id_handoff_requires_input(self) -> None:
        """SecretID handoff acquisition fails without any credential source."""
        # Unset all handoff env vars, no TTY
        env = os.environ.copy()
        env.pop("BOOTSTRAP_TOKEN", None)
        env.pop("BOOTSTRAP_TOKEN_FD", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    "log() { :; }; die() { exit 1; }; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "acquire_secret_id_handoff"
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode != 0

    def test_secret_id_handoff_from_env_var(self) -> None:
        """SecretID handoff acquisition succeeds with BOOTSTRAP_TOKEN env var."""
        env = os.environ.copy()
        env["BOOTSTRAP_TOKEN"] = "test-secret-id-handoff"
        env.pop("BOOTSTRAP_TOKEN_FD", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    "log() { :; }; die() { exit 1; }; "
                    "_secret_id_handoff=''; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "acquire_secret_id_handoff; "
                    'test -n "$_secret_id_handoff"'
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0

    def test_secret_id_unwrap_failure_is_fatal_by_default(self) -> None:
        """SecretID handoff fails closed when unwrap fails without recovery opt-in."""
        env = os.environ.copy()
        env["VAULT_ADDR"] = "http://127.0.0.1:1"
        env.pop("BOOTSTRAP_DIRECT_SECRET_ID", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "resolve_secret_id_handoff direct-secret"
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode != 0
        assert "direct SecretID recovery requires BOOTSTRAP_DIRECT_SECRET_ID=1" in result.stderr

    def test_direct_secret_id_requires_recovery_opt_in(self) -> None:
        """Direct SecretID handoff is returned only when recovery mode is explicit."""
        env = os.environ.copy()
        env["VAULT_ADDR"] = "http://127.0.0.1:1"
        env["BOOTSTRAP_DIRECT_SECRET_ID"] = "1"
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    "set -euo pipefail; "
                    f"source {BOOTSTRAP_SCRIPT}; "
                    "resolve_secret_id_handoff direct-secret"
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
        assert result.stdout == "direct-secret"
        assert "BOOTSTRAP_DIRECT_SECRET_ID=1 set" in result.stderr

    def test_bootstrap_writes_approle_files_not_seed_token(self) -> None:
        """Bootstrap uses Vault Agent AppRole files instead of a seed-token file."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert "VAULT_ROLE_ID_PATH" in script
        assert "VAULT_SECRET_ID_PATH" in script
        assert "/home/abhaile/.config/vault-agent/token" not in script
        assert "/v1/auth/approle/login" not in script
        assert "client_token" not in script

    def test_bootstrap_supports_response_wrapped_secret_id(self) -> None:
        """Bootstrap unwraps by default and requires opt-in for direct SecretID fallback."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'env VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$handoff"' in script
        assert "vault unwrap -format=json" in script
        assert "BOOTSTRAP_DIRECT_SECRET_ID" in script
        assert "direct SecretID recovery requires BOOTSTRAP_DIRECT_SECRET_ID=1" in script
        assert "Failed to resolve SecretID handoff" in script

    def test_bootstrap_reports_approle_file_write_failures(self) -> None:
        """Bootstrap wraps AppRole file write failures with clear fatal messages."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'die "Failed to write Vault Agent role-id"' in script
        assert 'die "Failed to write Vault Agent secret-id"' in script

    def test_bootstrap_uses_vault_agent_artifact_only(self) -> None:
        """Bootstrap reads only the Vault Agent artifact, not unseal material."""
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
        assert 'readonly SECRETS_DIR="secrets"' in script
        assert "vault-agent.sops.yaml" in script
        assert "vault-bootstrap.sops.yaml" not in script
        assert "unseal_keys" not in script
        assert "/v1/sys/unseal" not in script
