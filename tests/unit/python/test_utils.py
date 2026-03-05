"""Tests for scripts/lib/python/utils modules."""

from pathlib import Path

import pytest
from jinja2 import StrictUndefined

from abhaile.utils.errors import RenderError
from abhaile.utils.network import strip_cidr
from abhaile.utils.paths import load_paths, resolve_output_root
from abhaile.utils.placeholders import (
    get_available_placeholder_filters,
    resolve_placeholder_value,
    resolve_placeholders,
)
from abhaile.utils.templating import create_jinja_env


class TestLoadPaths:
    """Tests for load_paths function."""

    def test_load_paths_success(self, tmp_repo_with_config):
        """Test loading valid paths.ini."""
        paths = load_paths(tmp_repo_with_config)
        assert paths["output_root_default"] == "/var/lib/abhaile"
        assert paths["target_root"] == "/"
        assert paths["config_root"] == "config"
        assert paths["schemas_root"] == "schemas"

    def test_load_paths_missing_file(self, tmp_path):
        """Test error when paths.ini is missing."""
        with pytest.raises(RenderError, match="Missing required paths file"):
            load_paths(tmp_path)

    def test_load_paths_missing_section(self, tmp_path):
        """Test error when [paths] section is missing."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "paths.ini").write_text("")

        with pytest.raises(RenderError, match="Missing \\[paths\\] section"):
            load_paths(tmp_path)

    def test_load_paths_missing_keys(self, tmp_path):
        """Test error when required keys are missing."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "paths.ini").write_text("[paths]\noutput_root_default = /tmp\n")

        with pytest.raises(RenderError, match="missing required keys"):
            load_paths(tmp_path)


class TestResolveOutputRoot:
    """Tests for resolve_output_root function."""

    def test_resolve_single_host_default(self, tmp_repo_with_config):
        """Test single-host render with default output root."""
        paths = load_paths(tmp_repo_with_config)
        root = resolve_output_root("phobos", None, paths, all_mode=False)
        assert root == Path("/var/lib/abhaile")

    def test_resolve_single_host_override(self, tmp_repo_with_config, tmp_output):
        """Test single-host render with output override."""
        paths = load_paths(tmp_repo_with_config)
        root = resolve_output_root("phobos", tmp_output, paths, all_mode=False)
        assert root == tmp_output

    def test_resolve_all_mode_requires_output(self, tmp_repo_with_config):
        """Test that --all requires --output."""
        paths = load_paths(tmp_repo_with_config)
        with pytest.raises(RenderError, match="--all requires --output"):
            resolve_output_root("phobos", None, paths, all_mode=True)

    def test_resolve_all_mode_with_output(self, tmp_repo_with_config, tmp_output):
        """Test --all mode with output override."""
        paths = load_paths(tmp_repo_with_config)
        root = resolve_output_root("phobos", tmp_output, paths, all_mode=True)
        assert root == tmp_output / "phobos"

        root = resolve_output_root("deimos", tmp_output, paths, all_mode=True)
        assert root == tmp_output / "deimos"

    def test_resolve_output_structure(self, tmp_repo_with_config, tmp_output):
        """Test that output structure matches ADR 0001."""
        paths = load_paths(tmp_repo_with_config)

        # Single-host: <output>/rendered and <output>/state
        root = resolve_output_root("phobos", tmp_output, paths, all_mode=False)
        assert root == tmp_output
        rendered = root / paths["rendered_dir_name"]
        state = root / paths["state_dir_name"]
        assert rendered == tmp_output / "rendered"
        assert state == tmp_output / "state"

        # All-mode: <output>/<host>/rendered and <output>/<host>/state
        root_all = resolve_output_root("phobos", tmp_output, paths, all_mode=True)
        assert root_all == tmp_output / "phobos"
        rendered_all = root_all / paths["rendered_dir_name"]
        state_all = root_all / paths["state_dir_name"]
        assert rendered_all == tmp_output / "phobos" / "rendered"
        assert state_all == tmp_output / "phobos" / "state"


def test_strip_cidr_with_mask():
    assert strip_cidr("192.168.1.1/24") == "192.168.1.1"


def test_strip_cidr_without_mask():
    assert strip_cidr("192.168.1.1") == "192.168.1.1"


def test_create_jinja_env_registers_strip_cidr(tmp_path: Path) -> None:
    template_path = tmp_path / "test.j2"
    template_path.write_text("{{ '10.0.0.1/24' | strip_cidr }}\n")

    env = create_jinja_env(tmp_path)
    template = env.get_template("test.j2")

    assert template.render() == "10.0.0.1\n"


def test_create_jinja_env_additional_filters(tmp_path: Path) -> None:
    template_path = tmp_path / "test.j2"
    template_path.write_text("{{ 'hello' | shout }}\n")

    env = create_jinja_env(tmp_path, additional_filters={"shout": str.upper})
    template = env.get_template("test.j2")

    assert template.render() == "HELLO\n"


def test_create_jinja_env_settings(tmp_path: Path) -> None:
    env = create_jinja_env(tmp_path)

    assert env.trim_blocks is True
    assert env.lstrip_blocks is True
    assert env.keep_trailing_newline is True
    assert env.undefined is StrictUndefined


class TestPlaceholders:
    """Tests for placeholder resolution functions."""

    def test_resolve_placeholder_value_simple(self) -> None:
        """Test resolving a simple placeholder."""
        network = {"services": {"test": {"address": "172.20.20.200/32"}}}
        result = resolve_placeholder_value("%%network.services.test.address%%", network)
        assert result == "172.20.20.200/32"

    def test_resolve_placeholder_value_with_strip_cidr(self) -> None:
        """Test placeholder with strip_cidr filter."""
        network = {"services": {"test": {"address": "172.20.20.200/32"}}}
        result = resolve_placeholder_value(
            "%%network.services.test.address | strip_cidr%%", network
        )
        assert result == "172.20.20.200"

    def test_resolve_placeholder_value_multiple_in_string(self) -> None:
        """Test multiple placeholders in a single string."""
        network = {
            "services": {
                "service1": {"address": "172.20.20.1/32"},
                "service2": {"address": "172.20.20.2/32"},
            }
        }
        result = resolve_placeholder_value(
            "first=%%network.services.service1.address | strip_cidr%% second=%%network.services.service2.address | strip_cidr%%",
            network,
        )
        assert result == "first=172.20.20.1 second=172.20.20.2"

    def test_resolve_placeholder_value_non_greedy(self) -> None:
        """Test that placeholder parsing is non-greedy (doesn't match across multiple placeholders)."""
        network = {
            "services": {
                "service1": {"address": "10.0.0.1/32"},
                "service2": {"address": "10.0.0.2/32"},
            }
        }
        # Without non-greedy matching, this would try to parse the entire expression
        # as one placeholder and fail. With non-greedy, it correctly parses two.
        result = resolve_placeholder_value(
            "%%network.services.service1.address%% and %%network.services.service2.address%%",
            network,
        )
        assert result == "10.0.0.1/32 and 10.0.0.2/32"

    def test_resolve_placeholder_value_non_string(self) -> None:
        """Test that non-string values are returned unchanged."""
        network: dict[str, object] = {}
        assert resolve_placeholder_value(123, network) == 123
        assert resolve_placeholder_value(None, network) is None
        assert resolve_placeholder_value([], network) == []

    def test_resolve_placeholder_value_invalid_path(self) -> None:
        """Test error message includes placeholder expression for invalid path."""
        network: dict[str, object] = {"services": {}}
        with pytest.raises(
            RenderError,
            match=r"Placeholder path not found.*in placeholder: %%network\.invalid\.path%%",
        ):
            resolve_placeholder_value("%%network.invalid.path%%", network)

    def test_resolve_placeholder_value_unknown_filter(self) -> None:
        """Test error message includes placeholder and filter name for unknown filter."""
        network = {"services": {"test": {"address": "172.20.20.200/32"}}}
        with pytest.raises(
            RenderError,
            match=r"Unknown placeholder filter: unknown_filter in placeholder: %%network\.services\.test\.address \| unknown_filter%%",
        ):
            resolve_placeholder_value("%%network.services.test.address | unknown_filter%%", network)

    def test_resolve_placeholder_value_unknown_filter_lists_available(self) -> None:
        """Test error message for unknown filter includes list of available filters."""
        network = {"services": {"test": {"address": "172.20.20.200/32"}}}
        with pytest.raises(
            RenderError,
            match=r"Available filters: strip_cidr",
        ):
            resolve_placeholder_value("%%network.services.test.address | unknown_filter%%", network)

    def test_resolve_placeholder_value_unsupported_root(self) -> None:
        """Test error for unsupported placeholder root."""
        network: dict[str, object] = {}
        with pytest.raises(
            RenderError,
            match=r"Unsupported placeholder root.*in placeholder:",
        ):
            resolve_placeholder_value("%%invalid.root.path%%", network)

    def test_resolve_placeholders_dict(self) -> None:
        """Test resolving placeholders in dictionaries."""
        network = {"services": {"test": {"address": "172.20.20.200/32"}}}
        config = {
            "bind_ip": "%%network.services.test.address | strip_cidr%%",
            "port": 8080,
        }
        result = resolve_placeholders(config, network)
        assert result == {"bind_ip": "172.20.20.200", "port": 8080}

    def test_resolve_placeholders_list(self) -> None:
        """Test resolving placeholders in lists."""
        network = {
            "services": {
                "service1": {"address": "172.20.20.1/32"},
                "service2": {"address": "172.20.20.2/32"},
            }
        }
        config = [
            "%%network.services.service1.address | strip_cidr%%",
            "%%network.services.service2.address | strip_cidr%%",
        ]
        result = resolve_placeholders(config, network)
        assert result == ["172.20.20.1", "172.20.20.2"]

    def test_resolve_placeholders_nested_structures(self) -> None:
        """Test resolving placeholders in nested dict/list structures."""
        network = {
            "services": {
                "service1": {"address": "172.20.20.1/32"},
                "service2": {"address": "172.20.20.2/32"},
            }
        }
        config = {
            "servers": [
                {
                    "name": "server1",
                    "address": "%%network.services.service1.address | strip_cidr%%",
                },
                {
                    "name": "server2",
                    "address": "%%network.services.service2.address | strip_cidr%%",
                },
            ]
        }
        result = resolve_placeholders(config, network)
        assert result == {
            "servers": [
                {"name": "server1", "address": "172.20.20.1"},
                {"name": "server2", "address": "172.20.20.2"},
            ]
        }

    def test_resolve_placeholders_empty_placeholder(self) -> None:
        """Test error for empty placeholder."""
        network: dict[str, object] = {}
        with pytest.raises(RenderError, match="Empty placeholder expression"):
            resolve_placeholder_value("%%%%", network)

    def test_resolve_placeholders_with_dots_in_key(self) -> None:
        """Test resolving placeholders with dots in interface names."""
        network = {
            "interfaces": {
                "enp0s31f6.100": {
                    "address": "192.168.100.1/24",
                }
            }
        }
        result = resolve_placeholder_value(
            "%%network.interfaces.enp0s31f6.100.address | strip_cidr%%", network
        )
        assert result == "192.168.100.1"

    def test_resolve_placeholders_multiple_filters_future_extensibility(self) -> None:
        """Test that multiple filters are processed in order (future extensibility test)."""
        # Currently only strip_cidr is supported, but this test ensures
        # the infrastructure is in place for future filters.
        network = {"services": {"test": {"address": "172.20.20.200/32"}}}
        result = resolve_placeholder_value(
            "%%network.services.test.address | strip_cidr%%", network
        )
        assert result == "172.20.20.200"

    def test_get_available_placeholder_filters(self) -> None:
        """Test that available filters can be queried."""
        filters = get_available_placeholder_filters()
        assert isinstance(filters, list)
        assert "strip_cidr" in filters
        # List should be sorted
        assert filters == sorted(filters)

    def test_placeholder_filter_registry_is_extensible(self) -> None:
        """Test that the filter registry can be extended with new filters.

        This test demonstrates how to add a new filter (e.g., upper_case).
        To actually add a filter:
        1. Implement the filter function: def upper_case(value: str) -> str: return value.upper()
        2. Add to _PLACEHOLDER_FILTERS: _PLACEHOLDER_FILTERS["upper_case"] = upper_case
        3. Add tests for the new filter
        """
        # Current: only strip_cidr is registered
        filters = get_available_placeholder_filters()
        assert len(filters) == 1
        assert filters[0] == "strip_cidr"

        # Future: adding a new filter would be as simple as:
        # from abhaile.utils.placeholders import _PLACEHOLDER_FILTERS
        # _PLACEHOLDER_FILTERS["upper_case"] = lambda x: x.upper()
        # Then: %%network.services.test.name | upper_case%%
