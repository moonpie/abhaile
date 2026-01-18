import pytest

from tools.common.core import resolve_placeholders, RenderError


def test_resolve_placeholder_strip_cidr():
    ctx = {"services": {"svc": {"address": "10.0.0.5/32"}}}
    out = resolve_placeholders("%%services.svc.address|strip_cidr%%", ctx)
    assert out == "10.0.0.5"


def test_resolve_placeholder_mixed_literal():
    ctx = {"services": {"api": {"host": "api.local", "port": "8443"}}}
    out = resolve_placeholders(
        "https://%%services.api.host%%:%%services.api.port%%", ctx
    )
    assert out == "https://api.local:8443"


def test_resolve_placeholder_missing_key_raises():
    ctx = {"services": {}}
    with pytest.raises(RenderError, match="missing key 'svc'"):
        resolve_placeholders("%%services.svc.address%%", ctx)


def test_resolve_placeholder_nested_resolution():
    ctx = {
        "services": {
            "a": {"ref": "%%services.b.ip%%"},
            "b": {"ip": "172.20.20.10"},
        }
    }
    out = resolve_placeholders("%%services.a.ref%%", ctx)
    assert out == "172.20.20.10"


def test_resolve_placeholder_circular_reference_errors():
    ctx = {"services": {"loop": {"val": "%%services.loop.val%%"}}}
    with pytest.raises(RenderError, match="circular reference"):
        resolve_placeholders("%%services.loop.val%%", ctx)


def test_resolve_placeholder_preserves_special_chars():
    ctx = {"secrets": {"token": 'p@ss"$word`'}}
    out = resolve_placeholders("token=%%secrets.token%%", ctx)
    assert out == 'token=p@ss"$word`'


def test_resolve_placeholder_unsupported_filter_errors():
    ctx = {"services": {"a": {"ip": "1.2.3.4"}}}
    with pytest.raises(RenderError, match="unsupported filter"):
        resolve_placeholders("%%services.a.ip|unknown%%", ctx)


def test_resolve_placeholder_empty_value_ok():
    ctx = {"services": {"a": {"note": ""}}}
    out = resolve_placeholders("prefix-%%services.a.note%%", ctx)
    assert out == "prefix-"
