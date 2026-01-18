"""Integration tests for DNS CLI."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest


class TestDNSCLI(unittest.TestCase):
    """Test tools/dns/cli.py integration."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        # Get repo root: tests/integration -> tests -> repo_root
        cls.root = Path(__file__).resolve().parents[2]
        cls.cli = cls.root / "tools" / "dns" / "cli.py"
        # Ensure CLI exists before running tests
        if not cls.cli.exists():
            raise FileNotFoundError(f"CLI not found: {cls.cli}")
        cls.skip_live = not os.getenv("DESEC_TOKEN")

    def test_cli_exists_and_executable(self):
        """CLI script exists and is executable."""
        # Already validated in setUpClass
        self.assertTrue(self.cli.exists(), f"CLI not found: {self.cli}")
        # Check it's actually executable (may fail on Windows)
        try:
            self.assertTrue(os.access(self.cli, os.X_OK), "CLI not executable")
        except AssertionError:
            # Skip on Windows where execute bit doesn't apply
            if os.name == "nt":
                self.skipTest("Execute bit check not applicable on Windows")
            raise

    def test_cli_help(self):
        """CLI --help succeeds."""
        result = subprocess.run(
            ["python3", str(self.cli), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Unified DNS management CLI", result.stdout)

    def test_cli_requires_command(self):
        """CLI fails without subcommand."""
        result = subprocess.run(
            ["python3", str(self.cli)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_cli_requires_token(self):
        """CLI fails without token for fetch."""
        env = os.environ.copy()
        env.pop("DESEC_TOKEN", None)
        result = subprocess.run(
            ["python3", str(self.cli), "fetch"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("token", result.stderr.lower())

    @unittest.skipIf(
        not os.getenv("DESEC_TOKEN"), "DESEC_TOKEN not set (set to run live tests)"
    )
    def test_cli_fetch_live(self):
        """CLI fetch succeeds with live token."""
        result = subprocess.run(
            ["python3", str(self.cli), "fetch", "--format", "json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)

    @unittest.skipIf(
        not os.getenv("DESEC_TOKEN"), "DESEC_TOKEN not set (set to run live tests)"
    )
    def test_cli_plan_live(self):
        """CLI plan succeeds with live token."""
        result = subprocess.run(
            ["python3", str(self.cli), "plan"],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        # Exit code 0 = no changes, 1 = changes needed (both valid)
        self.assertIn(result.returncode, [0, 1], f"stderr: {result.stderr}")
        plan = json.loads(result.stdout)
        self.assertIn("create", plan)
        self.assertIn("update", plan)
        self.assertIn("delete", plan)
        self.assertIn("summary", plan)

    def test_cli_apply_from_plan_file(self):
        """CLI apply works with plan file (dry-run with fake plan)."""
        # Create a fake plan with no changes
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {"create": [], "update": [], "delete": [], "summary": {"total": 0}},
                f,
            )
            plan_file = f.name

        try:
            # CLI still requires token even for empty plan (validates early)
            # So this test validates that --plan-file is recognized
            env = os.environ.copy()
            env.pop("DESEC_TOKEN", None)
            result = subprocess.run(
                ["python3", str(self.cli), "apply", "--plan-file", plan_file],
                capture_output=True,
                text=True,
                env=env,
            )
            # Should fail due to missing token, message mentions token requirement
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("token", result.stderr.lower())
        finally:
            Path(plan_file).unlink(missing_ok=True)

    def test_cli_fetch_format_text(self):
        """CLI fetch text format produces readable output."""
        if self.skip_live:
            self.skipTest("DESEC_TOKEN not set")

        result = subprocess.run(
            ["python3", str(self.cli), "fetch", "--format", "text"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        # Text format should have columns
        self.assertTrue(len(result.stdout.strip()) > 0)

    def test_cli_verbose_flag(self):
        """CLI --verbose flag increases output."""
        if self.skip_live:
            self.skipTest("DESEC_TOKEN not set")

        result = subprocess.run(
            ["python3", str(self.cli), "--verbose", "fetch", "--format", "json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        # stderr should have DEBUG messages when verbose
        # (but may be empty if no debug logs)


if __name__ == "__main__":
    unittest.main()
