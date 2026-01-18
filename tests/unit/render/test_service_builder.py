from pathlib import Path
import os
import pytest

from tools.render.services.service_builder import (
    substitute_variables,
    render_service_configs,
)
from tools.common.core import RenderError


# --- Tests from test_substitution.py ---


def test_substitute_variables_handles_circular_placeholder():
    ctx = {"services": {"a": {"address": "%%services.a.address%%"}}}
    vars_in = {"v": "prefix %%services.a.address%% suffix"}
    with pytest.raises(RenderError, match="circular reference"):
        substitute_variables(vars_in, ctx)


def test_substitute_variables_unmatched_placeholder_left_as_is():
    ctx = {"services": {"a": {"address": "1.2.3.4"}}}
    vars_in = {"v": "prefix %%services.a.address"}
    out = substitute_variables(vars_in, ctx)
    assert out["v"].startswith("prefix %%services.a.address")


def test_substitute_variables_mixed_literal_and_placeholder(tmp_path: Path):
    ctx = {"services": {"svc": {"addr": "1.2.3.4/24"}}}
    variables = {"endpoint": "%%services.svc.addr | strip_cidr%%:8053"}
    res = substitute_variables(variables, ctx)
    assert res["endpoint"] == "1.2.3.4:8053"


def test_substitute_variables_unmatched_placeholder_left_intact():
    vars_in = {"x": "prefix %%services.missing"}
    ctx = {"services": {}}
    out = substitute_variables(vars_in, ctx)
    assert "%%services.missing" in out.get("x")


def test_substitute_variables_circular_like_but_uses_ctx_only():
    # Test successful resolution first
    vars_in = {"a": "%%services.a.ip%%"}
    ctx = {"services": {"a": {"ip": "1.2.3.4"}}}
    out = substitute_variables(vars_in, ctx)
    assert out["a"].startswith("1.2.3.4")
    # Service 'b' doesn't exist - should now fail
    with pytest.raises(
        RenderError, match="Failed to resolve placeholder.*services.b.ip"
    ):
        vars_missing = {"b": "%%services.b.ip%%"}
        substitute_variables(vars_missing, ctx)


def test_substitute_variables_basic():
    ctx = {"foo": {"bar": "baz"}}
    variables = {"x": "%%foo.bar%%"}
    result = substitute_variables(variables, ctx)
    assert result["x"] == "baz"


def test_substitute_variables_filter():
    ctx = {"foo": {"bar": "1.2.3.4/32"}}
    variables = {"x": "%%foo.bar|strip_cidr%%"}
    result = substitute_variables(variables, ctx)
    assert result["x"] == "1.2.3.4"


def test_substitute_variables_mixed():
    ctx = {"foo": {"bar": "1.2.3.4"}}
    variables = {"x": "%%foo.bar%%:8053"}
    result = substitute_variables(variables, ctx)
    assert result["x"] == "1.2.3.4:8053"


def test_substitute_variables_keeps_placeholder_when_path_missing():
    """Test that missing placeholders now raise RenderError instead of keeping placeholder."""
    ctx = {"services": {}}
    vars_in = {"addr": "%%services.nope.address%%"}
    with pytest.raises(
        RenderError, match="Failed to resolve placeholder.*services.nope.address"
    ):
        substitute_variables(vars_in, ctx)


def test_substitute_variables_strip_cidr_on_bad_value_leaves_placeholder():
    ctx = {"foo": {"bar": 123}}
    vars_in = {"v": "%%foo.bar|strip_cidr%%"}
    with pytest.raises(RenderError, match="Failed to resolve placeholder.*foo.bar"):
        substitute_variables(vars_in, ctx)


# --- Tests from test_io_permission_failures.py ---


def test_render_service_write_permission_error(tmp_path: Path, monkeypatch):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)
    services_dir = tmp_path / "config" / "services"
    svc_dir = services_dir / "p"
    svc_dir.mkdir(parents=True)
    # template
    (svc_dir / "t.j2").write_text("{{ config.x }}")

    services_meta = {
        "p": {
            "config": [
                {
                    "source": {"template": "t.j2", "variables": {"x": "1"}},
                    "destination": "out.conf",
                }
            ]
        }
    }
    out = tmp_path / "out"

    orig = Path.write_text

    def fake_write_text(self, data, encoding=None):
        if str(self).startswith(str(out)):
            raise PermissionError("noperms")
        return (
            orig(self, data, encoding=encoding)
            if encoding is not None
            else orig(self, data)
        )

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    with pytest.raises(PermissionError):
        render_service_configs("h", ["p"], services_meta, {}, out, services_dir)


# --- End service_builder tests ---
