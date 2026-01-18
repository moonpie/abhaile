from tools.render.validate import validate_all
from tools.common.core import PathConfig


def test_validate_repo_has_no_errors(repo_root):
    """Validate that the actual repository has no config errors."""
    # Build a PathConfig rooted at the fixture repo_root to avoid env coupling
    paths = PathConfig(
        repo_root=repo_root,
        config_root=repo_root / "config",
        output_root=repo_root / "out" / "rendered",
        state_root=repo_root / "out" / "state",
        secrets_root=repo_root / "secrets",
    )
    errors = validate_all(paths)
    assert errors == [], f"Validation produced errors: {errors}"
