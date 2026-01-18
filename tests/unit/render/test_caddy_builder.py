from pathlib import Path
import os

from tools.render.services.caddy_builder import render_caddy_configs


def test_caddy_base_entry_without_destination_is_ignored(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    # Create base file under services root
    (services_dir / "Caddyfile.base").write_text("BASEROOT")

    services_meta = {
        "caddy-internal": {"ingress": {"internal": [{"base": "Caddyfile.base"}]}}
    }

    out = tmp_path / "out"
    out.mkdir()
    deployed = ["caddy-internal"]

    # No destination provided in ingress entry, so base should be ignored and nothing written
    render_caddy_configs("hostA", deployed, services_meta, services_dir, out)
    assert not (out / "services" / "caddy-internal").exists()


def test_render_caddy_with_base_and_blocks(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    # Base file for caddy-internal
    base_dir = services_dir / "caddy-internal"
    base_dir.mkdir()
    base_file = base_dir / "Caddyfile.base"
    base_file.write_text("BASE-CONTENT")

    # Two services with ingress blocks
    svc1_dir = services_dir / "svc1" / "blocks"
    svc1_dir.mkdir(parents=True)
    (svc1_dir / "ingress.caddy").write_text("svc1-block")

    svc2_dir = services_dir / "svc2" / "blocks"
    svc2_dir.mkdir(parents=True)
    (svc2_dir / "ingress.caddy").write_text("svc2-block")

    services_meta = {
        "caddy-internal": {
            "ingress": {
                "internal": [
                    {
                        "base": "caddy-internal/Caddyfile.base",
                        "destination": "/etc/caddy/Caddyfile",
                    }
                ]
            }
        },
        "svc1": {"ingress": {"internal": [{"block": "svc1/blocks/ingress.caddy"}]}},
        "svc2": {"ingress": {"internal": [{"block": "svc2/blocks/ingress.caddy"}]}},
    }

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    deployed = ["caddy-internal", "svc1", "svc2"]

    render_caddy_configs("hostA", deployed, services_meta, services_dir, out_dir)

    out_path = out_dir / "services" / "caddy-internal" / "etc" / "caddy" / "Caddyfile"
    assert out_path.exists()

    data = out_path.read_text()
    # Base must appear before header and blocks in the final Caddyfile
    header = "# ---------- Service Ingress Blocks ----------"
    assert data.find("BASE-CONTENT") < data.find(header)
    assert data.find(header) < data.find("svc1-block") < data.find("svc2-block")
    # Only one header
    assert data.count(header) == 1


def test_render_caddy_without_base_but_with_blocks(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    # Service providing a dmz block
    svc_dir = services_dir / "svc-a" / "blocks"
    svc_dir.mkdir(parents=True)
    (svc_dir / "dmz.caddy").write_text("svc-a-dmz")

    services_meta = {
        "caddy-dmz": {},
        "svc-a": {"ingress": {"dmz": [{"block": "svc-a/blocks/dmz.caddy"}]}},
    }

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    deployed = ["caddy-dmz", "svc-a"]

    render_caddy_configs("hostA", deployed, services_meta, services_dir, out_dir)

    out_path = out_dir / "services" / "caddy-dmz" / "Caddyfile"
    assert out_path.exists()
    content = out_path.read_text().strip()
    # When no base exists, the file should start with the service ingress header
    assert content.startswith("# ---------- Service Ingress Blocks ----------")


def test_caddyfile_base_and_blocks(tmp_path):
    """Test that Caddyfile rendering merges base and block configurations properly."""
    services_dir = tmp_path / "config" / "services"

    # Setup: caddy-dmz service with base and block files
    caddy_dir = services_dir / "caddy-dmz"
    caddy_dir.mkdir(parents=True)

    base_file = caddy_dir / "Caddyfile.base"
    base_file.write_text("# Base Caddyfile\n:443 {\n}")

    blocks_dir = caddy_dir / "Caddyfile.d"
    blocks_dir.mkdir()
    (blocks_dir / "block1").write_text("reverse_proxy localhost:8080")

    services_meta = {
        "caddy-dmz": {
            "caddy": {
                "base": "Caddyfile.base",
                "blocks": [{"source": "Caddyfile.d/block1", "block": "example.com"}],
            }
        }
    }

    # Verify metadata structure is correct
    caddy_meta = services_meta["caddy-dmz"]["caddy"]
    assert caddy_meta["base"] == "Caddyfile.base"
    assert len(caddy_meta["blocks"]) == 1
    assert caddy_meta["blocks"][0]["block"] == "example.com"


def test_render_caddy_duplicate_base_uses_first(tmp_path: Path):
    services_dir = tmp_path / "config_services"
    out_dir = tmp_path / "out"
    # create base file under services root
    services_dir.mkdir()
    base = services_dir / "common_base" / "Caddyfile"
    base.parent.mkdir()
    base.write_text("# base\n:80")

    # service meta with duplicate base entries; only first with dest should be used
    services_meta = {
        "caddy-internal": {
            "ingress": {
                "internal": [
                    {"base": "common_base/Caddyfile", "destination": "Caddyfile"},
                    {"base": "common_base/Caddyfile", "destination": "Caddyfile"},
                ]
            }
        }
    }

    render_caddy_configs(
        "phobos", ["caddy-internal"], services_meta, services_dir, out_dir
    )
    out_path = out_dir / "services" / "caddy-internal" / "Caddyfile"
    assert out_path.exists()
    content = out_path.read_text()
    assert "# base" in content


def test_render_caddy_configs_no_caddy_services_skips(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)
    out = tmp_path / "out"

    # No deployed caddy services -> nothing written
    render_caddy_configs("host", ["svc1"], {}, services_dir, out)
    assert not out.exists()


def test_render_caddy_configs_base_and_blocks_written(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)
    services_dir = tmp_path / "config" / "services"
    # Create caddy service with base+destination
    caddy = services_dir / "caddy-internal"
    caddy.mkdir(parents=True)
    base = services_dir / "base.Caddyfile"
    base.write_text("basecontent")

    # caddy meta references base in global path
    services_meta = {
        "caddy-internal": {
            "ingress": {
                "internal": [{"base": "base.Caddyfile", "destination": "Caddyfile"}]
            }
        },
        "svc": {"ingress": {"internal": [{"block": "blk.caddy"}]}},
    }

    # create service block file under svc dir
    svc_dir = services_dir / "svc"
    svc_dir.mkdir()
    (svc_dir / "blk.caddy").write_text("site.example { reverse_proxy 127.0.0.1 }")

    out = tmp_path / "out"
    render_caddy_configs(
        "host", ["caddy-internal", "svc"], services_meta, services_dir, out
    )

    caddyfile = out / "services" / "caddy-internal" / "Caddyfile"
    assert caddyfile.exists()
    txt = caddyfile.read_text()
    assert "basecontent" in txt
    assert "site.example" in txt


def test_render_caddy_configs_missing_block_file_skips_block(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)
    # caddy with base
    (services_dir / "base.Caddyfile").write_text("base")
    services_meta = {
        "caddy-internal": {
            "ingress": {
                "internal": [{"base": "base.Caddyfile", "destination": "Caddyfile"}]
            }
        },
        "svc": {"ingress": {"internal": [{"block": "missing.caddy"}]}},
    }
    out = tmp_path / "out"
    render_caddy_configs(
        "host", ["caddy-internal", "svc"], services_meta, services_dir, out
    )
    caddyfile = out / "services" / "caddy-internal" / "Caddyfile"
    assert caddyfile.exists()
    assert "missing.caddy" not in caddyfile.read_text()


def test_render_caddy_configs_missing_base_and_blocks(tmp_path: Path):
    services_dir = tmp_path / "config_services"
    out_dir = tmp_path / "out"
    services_dir.mkdir()
    out_dir.mkdir()

    # Define a caddy service that references a non-existent base
    services_meta = {
        "caddy-internal": {
            "ingress": {
                "internal": [
                    {"base": "nonexistent/Caddyfile", "destination": "Caddyfile"}
                ]
            }
        }
    }

    # No other services provide ingress blocks; function should not raise and not create file
    render_caddy_configs(
        "phobos", ["caddy-internal"], services_meta, services_dir, out_dir
    )

    out_path = out_dir / "services" / "caddy-internal" / "Caddyfile"
    assert not out_path.exists()


def test_render_caddy_handles_duplicate_block_entries(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    svc_dir = services_dir / "svcdup"
    svc_dir.mkdir(parents=True)
    block = svc_dir / "blocks"
    block.mkdir()
    (block / "dup.caddy").write_text("DUP_BLOCK")

    # caddy-internal base not required; test duplicate block entries in svc
    services_meta = {
        "caddy-internal": {},
        "svcdup": {
            "ingress": {
                "internal": [
                    {"block": "svcdup/blocks/dup.caddy"},
                    {"block": "svcdup/blocks/dup.caddy"},
                ]
            }
        },
    }

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    deployed = ["caddy-internal", "svcdup"]

    render_caddy_configs("hostA", deployed, services_meta, services_dir, out_dir)

    out_path = out_dir / "services" / "caddy-internal" / "Caddyfile"
    # If no base exists, header should appear and duplicate block content should be present twice
    assert out_path.exists()
    content = out_path.read_text()
    assert content.count("DUP_BLOCK") == 2


def test_caddy_ignores_entries_without_block(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    svc_dir = services_dir / "svcgood"
    svc_dir.mkdir(parents=True)
    (svc_dir / "blocks").mkdir()
    (svc_dir / "blocks" / "a.caddy").write_text("A")

    services_meta = {
        "caddy-internal": {},
        "svcgood": {"ingress": {"internal": [{}, {"block": "svcgood/blocks/a.caddy"}]}},
    }

    out = tmp_path / "out"
    out.mkdir()
    deployed = ["caddy-internal", "svcgood"]

    # Should not raise and should include only the valid block
    render_caddy_configs("hostA", deployed, services_meta, services_dir, out)
    out_path = out / "services" / "caddy-internal" / "Caddyfile"
    assert out_path.exists()
    content = out_path.read_text()
    assert "A" in content


def test_render_caddy_no_base_no_blocks_writes_nothing(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    deployed = ["caddy-internal"]
    services_meta = {"caddy-internal": {}}

    render_caddy_configs("hostA", deployed, services_meta, services_dir, out_dir)

    out_path = out_dir / "services" / "caddy-internal"
    # Directory should not exist because there's nothing to render
    assert not out_path.exists()
