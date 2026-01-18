# Merged quadlet builder tests
# Modules under test: tools.render.lib.quadlet.quadlet_builder, tools.render.lib.quadlet

from pathlib import Path
import os
import pytest
from jinja2 import UndefinedError

from tools.render.quadlet.quadlet_helpers import build_volume_lines, render_volume_units
from tools.render.quadlet.quadlet_renderers import render_container_service
from tools.render.quadlet.quadlet_builder import render_quadlets


# --- Begin merged content from test_quadlet.py ---
def test_build_volume_lines_named_and_mounted():
    meta = {
        "named_volumes": [
            {"name": "data", "host": "/srv/foo/data", "mount": "/data", "mode": "ro"},
            {
                "name": "shared",
                "host": "/srv/shared",
                "mount": "/shared",
                "shared": True,
            },
        ],
        "mounted_files": [
            {"host": "/srv/foo/conf.yml", "mount": "/etc/conf.yml", "mode": "rw"}
        ],
    }

    lines = build_volume_lines(meta, "svc1", None, use_volume_units=True)
    assert any("svc1-data.volume" in line for line in lines)
    assert any("shared.volume" in line for line in lines)
    assert any("/srv/foo/conf.yml:/etc/conf.yml" in line for line in lines)


def test_render_volume_units_writes_files(tmp_path: Path):
    quadlet_dir = tmp_path / "quadlets"
    out_dir = tmp_path
    quadlet_dir.mkdir()

    meta = {
        "named_volumes": [
            {
                "name": "appdata",
                "host": "/srv/app/data",
                "mount": "/data",
                "mode": "rw",
            },
            {
                "name": "hostcerts",
                "host": "/etc/ssl/certs",
                "mount": "/etc/ssl/certs",
                "shared": True,
            },
        ]
    }

    shared_set = set()
    render_volume_units(
        "svc2",
        meta,
        quadlet_dir,
        out_dir,
        shared_set,
        container_name=None,
        is_rootless=False,
    )

    assert any(
        p.name.endswith("svc2-appdata.volume") or p.name.endswith("svc2-appdata.volume")
        for p in quadlet_dir.iterdir()
    )
    shared_path = (
        out_dir
        / "services"
        / "_shared"
        / "etc"
        / "containers"
        / "systemd"
        / "hostcerts.volume"
    )
    assert shared_path.exists()


def test_build_volume_lines_handles_variants(tmp_path):
    meta = {
        "named_volumes": [
            {"name": "v1", "host": "/data/v1", "mount": "/mnt/v1", "mode": "rw"},
            {
                "name": "v2",
                "host": "/data/v2",
                "mount": "/mnt/v2",
                "mode": "ro",
                "shared": True,
            },
            {"name": "bad", "host": None, "mount": "/mnt/bad"},
        ],
        "mounted_files": [{"host": "/etc/hosts", "mount": "/tmp/hosts", "mode": "ro"}],
    }

    lines_units = build_volume_lines(meta, "svc", use_volume_units=True)
    assert any("v1.volume" in line for line in lines_units)
    assert any("v2.volume" in line for line in lines_units)
    assert any("/etc/hosts:/tmp/hosts:ro" in line for line in lines_units)

    lines_host = build_volume_lines(meta, "svc", use_volume_units=False)
    assert any(line.startswith("Volume=/data/v1") for line in lines_host)


def test_render_volume_units_creates_shared_and_regular(tmp_path):
    quadlet_dir = tmp_path / "quadlets"
    out_dir = tmp_path
    quadlet_dir.mkdir()

    meta = {
        "named_volumes": [
            {"name": "v1", "host": "/data/v1", "mount": "/mnt/v1"},
            {
                "name": "shared",
                "host": "/srv/shared",
                "mount": "/srv/shared",
                "shared": True,
            },
        ]
    }

    shared_set = set()
    render_volume_units("svc", meta, quadlet_dir, out_dir, shared_set)

    assert (quadlet_dir / "svc-v1.volume").exists()
    shared_file = (
        out_dir
        / "services"
        / "_shared"
        / "etc"
        / "containers"
        / "systemd"
        / "shared.volume"
    )
    assert shared_file.exists()


def test_rootless_shared_volume_path_and_dedup(tmp_path):
    quadlet_dir = tmp_path / "quad"
    quadlet_dir.mkdir()
    out_dir = tmp_path
    meta = {
        "named_volumes": [
            {"name": "sh", "host": "/srv/sh", "mount": "/srv/sh", "shared": True}
        ]
    }
    shared = set()
    render_volume_units("svc", meta, quadlet_dir, out_dir, shared, is_rootless=False)
    assert (
        out_dir
        / "services"
        / "_shared"
        / "etc"
        / "containers"
        / "systemd"
        / "sh.volume"
    ).exists()

    render_volume_units(
        "svc",
        meta,
        quadlet_dir,
        out_dir,
        shared,
        is_rootless=True,
        rootless_user="jdoe",
    )
    rootless_file = (
        out_dir
        / "services"
        / "_shared"
        / "home"
        / "jdoe"
        / ".config"
        / "containers"
        / "systemd"
        / "sh.volume"
    )
    assert rootless_file.exists()


def test_render_volume_units_io_failure_propagates(tmp_path, monkeypatch):
    quadlet_dir = tmp_path / "q"
    quadlet_dir.mkdir()
    out_dir = tmp_path
    meta = {
        "named_volumes": [
            {"name": "v", "host": "/data/v", "mount": "/m", "shared": False}
        ]
    }
    shared = set()

    real_write = Path.write_text

    def fake_write(self, data, encoding=None):
        if str(self).endswith("v.volume"):
            raise IOError("disk full")
        return real_write(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", fake_write)

    with pytest.raises(IOError):
        render_volume_units("svc", meta, quadlet_dir, out_dir, shared)


def test_template_strict_undefined_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc_dir = tmp_path / "config" / "services" / "svc"
    qd = svc_dir / "quadlets"
    qd.mkdir(parents=True)

    (qd / "svc.container.j2").write_text("{{ services.NONEXISTENT.value }}")
    (qd / "svc.image").write_text("Image=xyz")

    svc_meta = {"type": "container", "mode": "rootful", "container": {}}
    network = {"services": {}}

    with pytest.raises(UndefinedError):
        render_container_service(
            "svc", svc_meta, network, tmp_path / "out", "host", set(), root=tmp_path
        )


def test_build_volume_lines_host_paths_when_use_volume_units_false():
    container_meta = {
        "named_volumes": [
            {"name": "data", "host": "/var/lib/data", "mount": "/data", "mode": "rw"}
        ],
        "mounted_files": [{"host": "/etc/foo", "mount": "/etc/foo", "mode": "ro"}],
    }

    lines = build_volume_lines(container_meta, "svc", use_volume_units=False)
    assert any(line.startswith("Volume=/var/lib/data") for line in lines)
    assert any(line.startswith("Volume=/etc/foo") for line in lines)


def test_render_quadlets_missing_quadlet_dir_skips(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    services_meta = {"noquad": {"type": "container", "container": {}}}
    out = tmp_path / "out"

    render_quadlets("host", ["noquad"], {}, services_meta, out, root=tmp_path)
    files = [p for p in out.rglob("*") if p.is_file()]
    assert files == []


def test_container_template_undefined_error(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    svc = "qsvc"
    svc_quadlet_dir = tmp_path / "config" / "services" / svc / "quadlets"
    svc_quadlet_dir.mkdir(parents=True)

    (svc_quadlet_dir / "q.container.j2").write_text("Value={{ missing }}")

    services_meta = {svc: {"type": "container", "container": {}}}
    out = tmp_path / "out"

    with pytest.raises(UndefinedError):
        render_quadlets(
            "host", [svc], {"services": {}}, services_meta, out, root=tmp_path
        )


def test_build_volume_lines_skips_incomplete_entries():
    meta = {
        "named_volumes": [
            {"name": "data", "host": "/var/lib/data", "mount": "/data", "mode": "rw"},
            {"name": "bad", "host": None, "mount": "/bad"},
        ],
        "mounted_files": [
            {"host": "/etc/hosts", "mount": "/hosts"},
            {"host": None, "mount": "/nope"},
        ],
    }

    lines = build_volume_lines(meta, "svc")
    assert any("data.volume" in line or "/var/lib/data" in line for line in lines)
    assert any("/etc/hosts" in line for line in lines)
    assert not any("/nope" in line for line in lines)


def test_render_volume_units_handles_shared_and_rootless(tmp_path: Path):
    quadlet_dir = tmp_path / "quadlets"
    out_dir = tmp_path / "out"
    quadlet_dir.mkdir()
    out_dir.mkdir()

    meta = {
        "named_volumes": [
            {"name": "svol", "host": "/srv/svol", "mount": "/svol", "shared": True}
        ]
    }
    shared = set()

    render_volume_units("svc", meta, quadlet_dir, out_dir, shared, is_rootless=False)
    expected = (
        out_dir
        / "services"
        / "_shared"
        / "etc"
        / "containers"
        / "systemd"
        / "svol.volume"
    )
    assert expected.exists()


def test_build_volume_lines_skips_incomplete_entries_alt(tmp_path: Path):
    container_meta = {
        "named_volumes": [
            {"name": "v1", "host": "/data/v1"},
            {"name": "v2", "mount": "/mnt/v2"},
            {"name": "v3", "host": "/data/v3", "mount": "/mnt/v3"},
        ],
        "mounted_files": [{"host": "/etc/hosts", "mount": "/etc/hosts"}],
    }

    lines = build_volume_lines(container_meta, "svc")
    assert any("v3" in line for line in lines)
    assert any("/etc/hosts" in line for line in lines)


def test_render_volume_units_creates_shared_once(tmp_path: Path):
    quadlet_dir = tmp_path / "quadlets"
    out_dir = tmp_path / "out"
    quadlet_dir.mkdir()
    out_dir.mkdir()

    container_meta = {
        "named_volumes": [
            {
                "name": "sharedvol",
                "host": "/srv/shared",
                "mount": "/srv/shared",
                "shared": True,
            }
        ]
    }

    shared_set = set()
    render_volume_units(
        "svc", container_meta, quadlet_dir, out_dir, shared_set, is_rootless=False
    )
    render_volume_units(
        "svc", container_meta, quadlet_dir, out_dir, shared_set, is_rootless=False
    )

    p = (
        out_dir
        / "services"
        / "_shared"
        / "etc"
        / "containers"
        / "systemd"
        / "sharedvol.volume"
    )
    assert p.exists()


def test_shared_volume_created_for_rootless_and_rootful(tmp_path: Path):
    quadlet_dir = tmp_path / "quadlets"
    out_dir = tmp_path / "out"
    quadlet_dir.mkdir()
    out_dir.mkdir()

    container_meta = {
        "named_volumes": [
            {
                "name": "sharedvol",
                "host": "/srv/shared",
                "mount": "/srv/shared",
                "shared": True,
            }
        ]
    }

    created = set()
    render_volume_units(
        "svc", container_meta, quadlet_dir, out_dir, created, is_rootless=True
    )
    render_volume_units(
        "svc", container_meta, quadlet_dir, out_dir, created, is_rootless=False
    )

    rootless_path = (
        out_dir
        / "services"
        / "_shared"
        / "home"
        / "abhaile"
        / ".config"
        / "containers"
        / "systemd"
        / "sharedvol.volume"
    )
    rootful_path = (
        out_dir
        / "services"
        / "_shared"
        / "etc"
        / "containers"
        / "systemd"
        / "sharedvol.volume"
    )
    assert rootless_path.exists()
    assert rootful_path.exists()


# --- End merged content ---
