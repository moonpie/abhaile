# Unit tests for tools.render.cli and service config helpers

from pathlib import Path
import yaml
import pytest
from tools.common.core import RenderError, PathConfig
import tools.render.cli as render_mod
from tools.render.services import service_builder


def test_render_host_missing_vlan_raises(tmp_path, monkeypatch):
    # Create PathConfig with tmp_path as repo root
    paths = PathConfig(
        repo_root=tmp_path,
        config_root=tmp_path / "config",
        output_root=tmp_path / "out" / "rendered",
        state_root=tmp_path / "out" / "state",
        secrets_root=tmp_path / "secrets",
    )
    (tmp_path / "config").mkdir()
    mapping = {"abhaile": [{"phobos": ["svc1"]}]}
    (tmp_path / "config" / "mapping.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "mapping.yaml").write_text(yaml.safe_dump(mapping))

    network = {
        "vlans": {"vlanA": {"id": 10}, "vlanB": {"id": 20}},
        "hosts": {
            "phobos": {
                "physical_device": "enp0s31f6",
                "interfaces": {"enp0s31f6": {"vlan": "vlanB"}},
            }
        },
        "services": {"svc1": {"address": "172.20.10.5", "vlan": "vlanA"}},
    }
    (tmp_path / "config" / "network.yaml").write_text(yaml.safe_dump(network))

    svc_dir = tmp_path / "config" / "services" / "svc1"
    svc_dir.mkdir(parents=True)
    (svc_dir / "service.yaml").write_text(
        yaml.safe_dump({"type": "container", "network": "ipvlan-l2"})
    )

    (tmp_path / "config" / "hosts" / "phobos" / "systemd-networkd").mkdir(parents=True)

    with pytest.raises(RenderError):
        render_mod.render_host(
            "phobos",
            tmp_path / "out" / "rendered",
            paths,
        )


def test_render_host_raises_on_vlan_mismatch(tmp_path: Path, monkeypatch):
    mapping = {"abhaile": [{"phobos": ["svc"]}]}
    network = {
        "hosts": {"phobos": {"interfaces": {}}},
        "services": {"svc": {"address": "172.20.10.5/32", "vlan": "vlan10"}},
        "vlans": {"vlan10": {"id": 10}},
    }

    def fake_load_yaml(path):
        s = str(path)
        if "mapping.yaml" in s:
            return mapping
        if "network.yaml" in s:
            return network
        return {}

    monkeypatch.setattr(render_mod, "load_yaml", fake_load_yaml)
    # Create PathConfig with tmp_path as repo root
    paths = PathConfig(
        repo_root=tmp_path,
        config_root=tmp_path / "config",
        output_root=tmp_path / "out",
        state_root=tmp_path / "out" / "state",
        secrets_root=tmp_path / "secrets",
    )
    monkeypatch.setattr(
        render_mod,
        "load_service_meta_with_includes",
        lambda svc, sd, cache: {"type": "container", "network": "ipvlan-l2"},
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(RenderError):
        render_mod.render_host("phobos", out_dir, paths)


def test_main_validation_error(monkeypatch):
    import tools.render.validate as validate

    # Force validation to report an error without touching filesystem
    monkeypatch.setattr(validate, "validate_all", lambda paths: ["error"])
    # Mock PathConfig.from_env to return a test instance
    test_paths = PathConfig(
        repo_root=Path("."),
        config_root=Path(".") / "config",
        output_root=Path(".") / "out" / "rendered",
        state_root=Path(".") / "out" / "state",
        secrets_root=Path(".") / "secrets",
    )
    monkeypatch.setattr(PathConfig, "from_env", lambda **kwargs: test_paths)
    assert render_mod.main() == 2


def test_main_render_error_propagated(monkeypatch):
    monkeypatch.setattr(
        render_mod,
        "load_yaml",
        lambda p: (
            {"abhaile": [{"phobos": []}]} if p.name.endswith("mapping.yaml") else {}
        ),
    )

    def fake_render_host(hostname, out, paths):
        raise RenderError("boom")

    monkeypatch.setattr(render_mod, "render_host", fake_render_host)
    assert render_mod.main() == 1


def test_render_service_configs_renders_template_and_copies_static(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc_dir = services_dir / "foo"
    svc_dir.mkdir(parents=True)

    (svc_dir / "template.j2").write_text("Hello {{ config.name }}")
    (svc_dir / "static.txt").write_text("STATIC")

    services_meta = {
        "foo": {
            "config": [
                {
                    "source": {
                        "template": "template.j2",
                        "variables": {"name": "world"},
                    },
                    "destination": "/etc/foo.conf",
                },
                {"source": "static.txt", "destination": "/srv/foo/static.txt"},
            ]
        }
    }

    ctx = {"dns": {}, "services": {}}
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    service_builder.render_service_configs(
        "hostA", ["foo"], services_meta, ctx, out_dir, services_dir
    )

    rendered = out_dir / "services" / "foo" / "etc" / "foo.conf"
    assert rendered.exists()
    assert rendered.read_text().strip() == "Hello world"

    copied = out_dir / "services" / "foo" / "srv" / "foo" / "static.txt"
    assert copied.exists()
    assert copied.read_text() == "STATIC"


def test_render_service_configs_dynamic_zone_placeholder(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc_dir = services_dir / "bar"
    svc_dir.mkdir(parents=True)

    coredns_common = services_dir / "coredns-common" / "config" / "zones"
    coredns_common.mkdir(parents=True)
    zone_tpl = coredns_common / "zone.zone.j2"
    zone_tpl.write_text("zone {{ zone.name }}")

    services_meta = {
        "bar": {
            "config": [
                {
                    "source": {
                        "template": "coredns-common/config/zones/zone.zone.j2",
                        "variables": {},
                    },
                    "destination": "/etc/coredns/zones/DYNAMIC_ZONE_PLACEHOLDER",
                }
            ]
        }
    }

    ctx = {"dns": {"zones_common": [{"name": "example."}]}}
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    service_builder.render_service_configs(
        "hostA", ["bar"], services_meta, ctx, out_dir, services_dir
    )

    out_zone = (
        out_dir / "services" / "bar" / "etc" / "coredns" / "zones" / "example.zone"
    )
    assert out_zone.exists()
    assert "zone example" in out_zone.read_text()


def test_render_service_configs_missing_destination_skipped(tmp_path: Path):
    services_dir = tmp_path / "config_services"
    services_dir.mkdir()
    svc_dir = services_dir / "foo"
    svc_dir.mkdir()
    (svc_dir / "template.j2").write_text("hello {{ config.val }}")

    services_meta = {
        "foo": {
            "config": [
                {"source": {"template": "template.j2", "variables": {"val": "x"}}}
            ]
        }
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    service_builder.render_service_configs(
        "phobos", ["foo"], services_meta, {}, out_dir, services_dir
    )
    assert not any(out_dir.rglob("*"))


def test_missing_template_raises(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc = services_dir / "svc1"
    svc.mkdir(parents=True)

    services_meta = {
        "svc1": {
            "config": [
                {
                    "source": {"template": "missing.j2", "variables": {}},
                    "destination": "etc/missing.conf",
                }
            ]
        }
    }

    with pytest.raises((FileNotFoundError, Exception)):
        service_builder.render_service_configs(
            "phobos", ["svc1"], services_meta, {}, tmp_path / "out", services_dir
        )


def test_unresolved_jinja_raises_undefined(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc = services_dir / "svc3"
    svc.mkdir(parents=True)
    (svc / "bad.j2").write_text("{{ config.missing }}")

    services_meta = {
        "svc3": {
            "config": [
                {
                    "source": {"template": "bad.j2", "variables": {}},
                    "destination": "etc/bad.conf",
                }
            ]
        }
    }

    from jinja2 import UndefinedError

    with pytest.raises((UndefinedError, Exception)):
        service_builder.render_service_configs(
            "phobos", ["svc3"], services_meta, {}, tmp_path / "out", services_dir
        )


def test_duplicate_destination_last_wins(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc = services_dir / "svc5"
    svc.mkdir(parents=True)
    (svc / "a.j2").write_text("first")
    (svc / "b.j2").write_text("second")

    services_meta = {
        "svc5": {
            "config": [
                {
                    "source": {"template": "a.j2", "variables": {}},
                    "destination": "etc/dup.conf",
                },
                {
                    "source": {"template": "b.j2", "variables": {}},
                    "destination": "etc/dup.conf",
                },
            ]
        }
    }

    service_builder.render_service_configs(
        "phobos", ["svc5"], services_meta, {}, tmp_path / "out", services_dir
    )

    outp = tmp_path / "out" / "services" / "svc5" / "etc" / "dup.conf"
    assert outp.exists()
    assert outp.read_text() == "second\n"
