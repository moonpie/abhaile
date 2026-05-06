"""Unit tests for config rendering error handling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abhaile.renderers.config import render_config_entries
from abhaile.utils.artifact_collector import ArtifactCollector
from abhaile.utils.errors import RenderError


class TestRenderConfigEntries:
    """Tests for render_config_entries() error handling."""

    def test_missing_destination_raises_error(self, tmp_path: Path) -> None:
        """Config entry without destination raises clear error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        entries = [{"source": "some/file.txt"}]

        with pytest.raises(RenderError, match="Config entry missing destination"):
            render_config_entries(
                entries,
                config_root,
                config_root,
                output_dir,
                {},
            )

    def test_missing_static_source_includes_destination(self, tmp_path: Path) -> None:
        """Error for missing static file includes destination path."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        entries = [
            {
                "source": "nonexistent/file.txt",
                "destination": "/etc/app/config.txt",
            }
        ]

        with pytest.raises(RenderError) as exc_info:
            render_config_entries(
                entries,
                config_root,
                config_root,
                output_dir,
                {},
            )

        error_msg = str(exc_info.value)
        assert "nonexistent/file.txt" in error_msg
        assert "/etc/app/config.txt" in error_msg
        assert "destination:" in error_msg

    def test_template_error_includes_destination(self, tmp_path: Path, write_file: Any) -> None:
        """Template rendering error includes destination path."""
        config_root = tmp_path / "config"
        template_dir = tmp_path / "templates"
        output_dir = tmp_path / "output"

        # Create template with undefined variable
        write_file(
            template_dir / "app.conf.j2",
            "port={{ undefined_var }}\n",
        )

        entries = [
            {
                "source": {
                    "template": "app.conf.j2",
                    "variables": {},
                },
                "destination": "/etc/app/app.conf",
            }
        ]

        with pytest.raises(RenderError) as exc_info:
            render_config_entries(
                entries,
                config_root,
                template_dir,
                output_dir,
                {},
            )

        error_msg = str(exc_info.value)
        assert "app.conf.j2" in error_msg
        assert "/etc/app/app.conf" in error_msg

    def test_missing_template_key_raises_error(self, tmp_path: Path) -> None:
        """Template entry without 'template' key raises error."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        entries = [
            {
                "source": {"variables": {}},
                "destination": "/etc/app/config.txt",
            }
        ]

        with pytest.raises(RenderError, match="missing 'template' key"):
            render_config_entries(
                entries,
                config_root,
                config_root,
                output_dir,
                {},
            )

    def test_authored_apply_block_is_ignored_for_apply_hints(
        self,
        tmp_path: Path,
        write_file: Any,
    ) -> None:
        """Authored entry-level apply blocks are ignored by config renderer."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        # Create source file
        write_file(
            config_root / "test.conf",
            "test content",
        )

        entries = [
            {
                "source": "test.conf",
                "destination": "/etc/app/config.conf",
                "apply": {
                    "activation_mode": "enable-start",
                    "restart_mode": "try-restart",
                    "requires": ["unit:network-online.target"],
                },
            }
        ]

        collector = ArtifactCollector()
        rendered_root = output_dir

        render_config_entries(
            entries,
            config_root,
            config_root,
            output_dir,
            {},
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = collector.get_all_artifacts()
        assert len(artifacts) == 1

        artifact = artifacts[0]
        assert artifact.apply_hints is None

    def test_apply_hints_none_when_no_apply_block(self, tmp_path: Path, write_file: Any) -> None:
        """Config entry without apply block has None apply_hints."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        # Create source file
        write_file(
            config_root / "test.conf",
            "test content",
        )

        entries = [
            {
                "source": "test.conf",
                "destination": "/etc/app/config.conf",
            }
        ]

        collector = ArtifactCollector()
        rendered_root = output_dir

        render_config_entries(
            entries,
            config_root,
            config_root,
            output_dir,
            {},
            collector=collector,
            rendered_root=rendered_root,
        )

        artifacts = collector.get_all_artifacts()
        artifact = artifacts[0]
        assert artifact.apply_hints is None

    def test_precomputed_apply_hints_used_even_with_authored_apply_present(
        self,
        tmp_path: Path,
        write_file: Any,
    ) -> None:
        """Internal precomputed apply hints are the only source for emitted apply_hints."""
        config_root = tmp_path / "config"
        output_dir = tmp_path / "output"

        write_file(
            config_root / "test.conf",
            "test content",
        )

        entries = [
            {
                "source": "test.conf",
                "destination": "/etc/app/config.conf",
                "apply": {
                    "restart_mode": "try-restart",
                },
                "_abhaile_apply_hints": {
                    "enable_mode": "enable",
                },
            }
        ]

        collector = ArtifactCollector()

        render_config_entries(
            entries,
            config_root,
            config_root,
            output_dir,
            {},
            collector=collector,
            rendered_root=output_dir,
        )

        artifacts = collector.get_all_artifacts()
        artifact = artifacts[0]
        assert artifact.apply_hints == {"enable_mode": "enable"}
