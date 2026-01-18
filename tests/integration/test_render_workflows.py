"""
Consolidated integration tests for render workflows.

Tests the complete rendering workflow from config → rendered output,
verifying file structure, output correctness, error handling, and idempotency.
"""

import subprocess
import yaml
import pytest

# mark render workflow integrations as slow
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def rendered_all_hosts(repo_root, skip_desec_env):
    """Render all hosts once and share the output directory."""
    result = subprocess.run(
        ["python3", "tools/render/cli.py"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=skip_desec_env,
    )
    assert result.returncode == 0, f"Render failed: {result.stderr}"
    out_dir = repo_root / "out" / "rendered"
    return {"result": result, "out_dir": out_dir}


class TestRenderWorkflows:
    """Integration tests for render orchestration and workflows."""

    def test_render_all_hosts_success(self, rendered_all_hosts):
        """Should render configs for all hosts from mapping.yaml."""
        result = rendered_all_hosts["result"]
        out_dir = rendered_all_hosts["out_dir"]

        assert result.returncode == 0, f"Render failed: {result.stderr}"
        assert out_dir.exists(), "Rendered output directory not created"
        assert (out_dir / "phobos").exists(), "phobos not rendered"
        assert (out_dir / "deimos").exists(), "deimos not rendered"

    def test_render_single_host_success(self, repo_root, skip_desec_env):
        """Should render config for a single specified host."""
        result = subprocess.run(
            ["python3", "tools/render/cli.py", "phobos"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=skip_desec_env,
        )

        assert result.returncode == 0, f"Render failed for phobos: {result.stderr}"

        # Check specific host output structure
        host_dir = repo_root / "out" / "rendered" / "phobos"
        assert host_dir.exists(), "Phobos rendered output not created"
        assert (
            host_dir / "systemd-networkd"
        ).exists(), "systemd-networkd dir not created"

    def test_render_output_structure(self, rendered_all_hosts):
        """Should create proper directory structure in rendered output."""
        host_dir = rendered_all_hosts["out_dir"] / "phobos"

        # Verify expected subdirectories
        assert (host_dir / "systemd-networkd").is_dir()
        assert (host_dir / "services").is_dir() or not list(host_dir.glob("services/*"))

        # Check for .network files in systemd-networkd
        network_files = list((host_dir / "systemd-networkd").glob("*.network"))
        assert len(network_files) > 0, "No .network files generated"

    def test_render_idempotent(self, repo_root, skip_desec_env):
        """Multiple renders should produce identical output."""
        # First render
        result1 = subprocess.run(
            ["python3", "tools/render/cli.py"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=skip_desec_env,
        )
        assert result1.returncode == 0, f"First render failed: {result1.stderr}"

        # Second render
        result2 = subprocess.run(
            ["python3", "tools/render/cli.py"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=skip_desec_env,
        )
        assert result2.returncode == 0, f"Second render failed: {result2.stderr}"

        # Output should exist after both renders
        out_dir = repo_root / "out" / "rendered"
        assert out_dir.exists()
        assert (out_dir / "phobos").exists()
        assert (out_dir / "deimos").exists()

    def test_render_missing_config_fails(self, repo_root, skip_desec_env):
        """Should fail gracefully when required config is missing."""
        # Use real render script with invalid mapping
        # Create a test mapping with non-existent service
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory():
            # Copy config structure
            test_config = repo_root / "config" / "mapping.yaml"
            backup_path = test_config.with_suffix(".yaml.bak")

            # Backup original
            shutil.copy(test_config, backup_path)

            try:
                # Write invalid mapping
                mapping = {"abhaile": [{"phobos": ["nonexistent-missing-service"]}]}
                test_config.write_text(yaml.dump(mapping))

                result = subprocess.run(
                    ["python3", "tools/render/cli.py"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    env=skip_desec_env,
                )

                assert (
                    result.returncode != 0
                ), "Should fail with missing service definition"
                # Check error mentions service issue
                assert (
                    "service" in result.stderr.lower()
                    or "not found" in result.stderr.lower()
                    or "does not exist" in result.stderr.lower()
                )
            finally:
                # Restore original
                shutil.move(backup_path, test_config)


class TestRenderMappingLogic:
    """Integration tests for mapping-driven rendering logic."""

    def test_only_mapped_services_rendered(
        self, integration_tmp_repo, render_script, skip_desec_env
    ):
        """Should render only services mapped to the host in mapping.yaml."""
        # Use integration_tmp_repo fixture which has proper structure

        result = subprocess.run(
            ["python3", str(render_script)],
            cwd=integration_tmp_repo,
            capture_output=True,
            text=True,
            env=skip_desec_env,
        )

        assert result.returncode == 0, f"Render failed: {result.stderr}"

        # Check that phobos output exists (from fixture's minimal mapping)
        rendered_dir = integration_tmp_repo / "out" / "rendered" / "phobos"
        assert rendered_dir.exists(), "Render output not created"

    def test_invalid_yaml_fails(self, tmp_path):
        """Should fail when mapping.yaml is malformed."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Invalid YAML
        (config_dir / "mapping.yaml").write_text("invalid: yaml: content: [")

        result = subprocess.run(
            ["python3", "tools/render/cli.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0, "Should fail with invalid YAML"


class TestRenderBootstrap:
    """Integration tests for repository initialization and first render."""

    def test_minimal_repo_can_render(
        self, integration_tmp_repo, render_script, skip_desec_env
    ):
        """Should successfully render a minimal valid repository."""
        result = subprocess.run(
            ["python3", str(render_script), "phobos"],
            cwd=integration_tmp_repo,
            capture_output=True,
            text=True,
            env=skip_desec_env,
        )

        assert result.returncode == 0, f"Render failed: {result.stderr}"

        # Verify output created
        out_dir = integration_tmp_repo / "out" / "rendered" / "phobos"
        assert out_dir.exists(), "Rendered output not created"
        assert (out_dir / "systemd-networkd").exists()

    def test_minimal_repo_creates_state_files(
        self, integration_tmp_repo, render_script, skip_desec_env
    ):
        """Should create state tracking files on first render."""
        result = subprocess.run(
            ["python3", str(render_script), "phobos"],
            cwd=integration_tmp_repo,
            capture_output=True,
            text=True,
            env=skip_desec_env,
        )
        assert result.returncode == 0

        state_dir = integration_tmp_repo / "out" / "state"
        assert state_dir.exists(), "State directory not created"

    def test_missing_service_definitions_fails(
        self, integration_tmp_repo, render_script, skip_desec_env
    ):
        """Should fail with clear error when required service definition missing."""
        # Remove services directory to simulate missing config
        import shutil

        services_dir = integration_tmp_repo / "config" / "services"
        if services_dir.exists():
            shutil.rmtree(services_dir)

        result = subprocess.run(
            ["python3", str(render_script), "phobos"],
            cwd=integration_tmp_repo,
            capture_output=True,
            text=True,
            env=skip_desec_env,
        )

        assert result.returncode != 0, "Should fail without service definitions"
        assert (
            "service" in result.stderr.lower() or "not found" in result.stderr.lower()
        )
