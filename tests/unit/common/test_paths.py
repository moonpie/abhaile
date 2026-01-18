"""Tests for PathConfig centralized path management."""

from pathlib import Path
import pytest
from tools.common.core.paths import PathConfig


def test_path_resolver_from_env_defaults():
    """Test PathConfig with default paths (dev mode)."""
    resolver = PathConfig.from_env()

    # Repo root should be detected
    assert resolver.repo_root.exists()
    assert (resolver.repo_root / ".git").exists()

    # Config root should be repo_root/config
    assert resolver.config_root == resolver.repo_root / "config"

    # Default output root should be repo_root/out/rendered
    assert resolver.output_root == resolver.repo_root / "out" / "rendered"

    # Default state root should be repo_root/out/state
    assert resolver.state_root == resolver.repo_root / "out" / "state"

    # Default secrets root should be repo_root/secrets (dev mode)
    assert resolver.secrets_root == resolver.repo_root / "secrets"


def test_path_resolver_custom_output_root():
    """Test PathConfig with custom output directory."""
    custom_output = Path("/tmp/test-rendered")
    resolver = PathConfig.from_env(output_root=custom_output)

    assert resolver.output_root == custom_output
    # State root should be derived from output parent
    assert resolver.state_root == custom_output.parent / "state"


def test_path_resolver_custom_state_root():
    """Test PathConfig with custom state directory."""
    custom_output = Path("/tmp/test-rendered")
    custom_state = Path("/tmp/test-state")
    resolver = PathConfig.from_env(output_root=custom_output, state_root=custom_state)

    assert resolver.output_root == custom_output
    assert resolver.state_root == custom_state


def test_path_resolver_prod_secrets_path():
    """Test PathConfig detects prod mode and uses /etc/abhaile for secrets."""
    prod_output = Path("/var/lib/abhaile/rendered")
    resolver = PathConfig.from_env(output_root=prod_output)

    # Should detect production mode (output outside repo)
    assert resolver.secrets_root == Path("/etc/abhaile")


def test_path_resolver_dev_secrets_path():
    """Test PathConfig uses repo/secrets in dev mode."""
    resolver = PathConfig.from_env()

    # Dev mode: output inside repo
    assert str(resolver.output_root).startswith(str(resolver.repo_root))
    assert resolver.secrets_root == resolver.repo_root / "secrets"


def test_path_resolver_validate_writable_success(tmp_path):
    """Test validate_writable succeeds when parent dirs are writable."""
    output_root = tmp_path / "rendered"
    state_root = tmp_path / "state"

    resolver = PathConfig.from_env(output_root=output_root, state_root=state_root)

    # Should not raise
    resolver.validate_writable()


def test_path_resolver_validate_writable_missing_parent(tmp_path):
    """Test validate_writable fails when parent doesn't exist."""
    output_root = tmp_path / "nonexistent" / "nested" / "rendered"
    resolver = PathConfig.from_env(output_root=output_root)

    with pytest.raises(PermissionError, match="Parent directory does not exist"):
        resolver.validate_writable()


def test_path_resolver_ensure_dirs_creates_directories(tmp_path):
    """Test ensure_dirs creates output and state directories."""
    output_root = tmp_path / "rendered"
    state_root = tmp_path / "state"

    resolver = PathConfig.from_env(output_root=output_root, state_root=state_root)

    assert not output_root.exists()
    assert not state_root.exists()

    resolver.ensure_dirs()

    assert output_root.exists()
    assert state_root.exists()


def test_path_resolver_ensure_dirs_idempotent(tmp_path):
    """Test ensure_dirs is safe to call multiple times."""
    output_root = tmp_path / "rendered"
    state_root = tmp_path / "state"

    resolver = PathConfig.from_env(output_root=output_root, state_root=state_root)

    resolver.ensure_dirs()
    resolver.ensure_dirs()  # Should not raise

    assert output_root.exists()
    assert state_root.exists()


def test_path_resolver_repr():
    """Test PathConfig string representation for debugging."""
    resolver = PathConfig.from_env()
    repr_str = repr(resolver)

    assert "PathConfig" in repr_str
    assert "repo_root=" in repr_str
    assert "config_root=" in repr_str
    assert "output_root=" in repr_str
    assert "state_root=" in repr_str
    assert "secrets_root=" in repr_str


def test_find_repo_root_finds_git_directory():
    """Test _find_repo_root successfully locates .git/ directory."""
    root = PathConfig._find_repo_root()

    assert root.exists()
    assert (root / ".git").exists()
    assert (root / "config").exists()  # Sanity check for abhaile repo


def test_path_resolver_state_derived_from_output():
    """Test state_root is derived from output_root parent when not specified."""
    # Custom output at /var/lib/abhaile/rendered
    output_root = Path("/var/lib/abhaile/rendered")
    resolver = PathConfig.from_env(output_root=output_root)

    # State should be /var/lib/abhaile/state (sibling to rendered)
    assert resolver.state_root == Path("/var/lib/abhaile/state")

    # Custom output at /tmp/test/rendered
    output_root2 = Path("/tmp/test/rendered")
    resolver2 = PathConfig.from_env(output_root=output_root2)

    # State should be /tmp/test/state
    assert resolver2.state_root == Path("/tmp/test/state")
