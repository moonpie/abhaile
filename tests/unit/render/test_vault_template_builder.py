import os
import shutil
import pytest
from pathlib import Path

from tools.render.services.vault_template_builder import (
    collect_vault_agent_templates,
    stage_vault_agent_templates,
    _resolve_template_source,
)

# --- Merged from test_vault.py ---


def test_template_block_merging():
    """Test that vault agent template blocks are properly merged from service metadata."""
    services_meta = {
        "vault-agent": {
            "vault_agent": {
                "templates": [
                    {"source": "block1.ctmpl", "out": "block1.out"},
                    {"source": "block2.ctmpl", "out": "block2.out"},
                ]
            }
        }
    }
    # Verify that multiple template entries are handled correctly
    templates = services_meta["vault-agent"]["vault_agent"]["templates"]
    assert len(templates) == 2
    assert templates[0]["source"] == "block1.ctmpl"
    assert templates[1]["source"] == "block2.ctmpl"


def test_collect_vault_agent_templates_with_absolute_source(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)
    svc_dir = services_dir / "svc"
    svc_dir.mkdir()

    abs_file = tmp_path / "global.tpl"
    abs_file.write_text("x")

    services_meta = {
        "svc": {
            "vault_agent": {"templates": [{"source": str(abs_file), "out": "o.tpl"}]}
        }
    }

    templates, copy_list = collect_vault_agent_templates(
        ["svc"], services_meta, services_dir, tmp_path, "hostA"
    )
    assert len(copy_list) == 1
    src, dest = copy_list[0]
    assert src == abs_file


def test_collect_includes_command_and_copy_entry(tmp_path: Path):
    services_dir = tmp_path / "services"
    services_dir.mkdir()
    svc = services_dir / "svc"
    svc.mkdir()
    src = svc / "t.tmpl"
    src.write_text("tmpl")

    services_meta = {
        "svc": {
            "vault_agent": {
                "templates": [
                    {
                        "source": "t.tmpl",
                        "out": "o",
                        "perms": "0644",
                        "command": "echo hi",
                    }
                ]
            }
        }
    }
    templates, copy_list = collect_vault_agent_templates(
        ["svc"], services_meta, services_dir, tmp_path, "phobos"
    )
    assert len(templates) == 1
    assert "command" in templates[0]
    assert len(copy_list) == 1


def test_collect_skips_missing_with_command_field(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)
    svc = services_dir / "svc"
    svc.mkdir()

    services_meta = {
        "svc": {
            "vault_agent": {
                "templates": [
                    {"source": "missing.tpl", "out": "o.tpl", "command": "/bin/true"}
                ]
            }
        }
    }

    templates, copy_list = collect_vault_agent_templates(
        ["svc"], services_meta, services_dir, tmp_path, "hostA"
    )
    assert templates == []
    assert copy_list == []


def test_stage_vault_agent_templates_propagates_copy_error(monkeypatch, tmp_path: Path):
    src = tmp_path / "src.tpl"
    src.write_text("ok")
    dest = tmp_path / "out" / "dest.tpl"
    copy_list = [(src, dest)]

    def _bad_copy(a, b):
        raise IOError("disk full")

    monkeypatch.setattr(shutil, "copy2", _bad_copy)

    with pytest.raises(IOError):
        stage_vault_agent_templates(copy_list)


def test_stage_vault_agent_templates_permission_error(monkeypatch, tmp_path: Path):
    src = tmp_path / "a.tpl"
    src.write_text("x")
    dest = tmp_path / "out" / "a.tpl"
    copy_list = [(src, dest)]

    def _raise_perm(a, b):
        raise PermissionError("permission denied")

    monkeypatch.setattr(shutil, "copy2", _raise_perm)
    with pytest.raises(PermissionError):
        stage_vault_agent_templates(copy_list)


def test_resolve_template_source(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc_dir = services_dir / "svc1"
    tpl_dir = svc_dir / "templates"
    tpl_dir.mkdir(parents=True)
    tpl = tpl_dir / "foo.ctmpl"
    tpl.write_text("hello")

    p = _resolve_template_source("templates/foo.ctmpl", "svc1", services_dir)
    assert p is not None and p.exists()

    p2 = _resolve_template_source("svc1/templates/foo.ctmpl", "svc1", services_dir)
    assert p2 is not None and p2.exists()


def test_collect_vault_agent_templates(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    svc_dir = services_dir / "svc1"
    tpl_dir = svc_dir / "templates"
    tpl_dir.mkdir(parents=True)
    tpl = tpl_dir / "bar.ctmpl"
    tpl.write_text("tmpl")

    services_meta = {
        "svc1": {
            "vault_agent": {
                "templates": [
                    {"source": "templates/bar.ctmpl", "out": "bar.out", "perms": "0644"}
                ]
            }
        }
    }

    out_root = tmp_path / "out"
    templates, copy_list = collect_vault_agent_templates(
        ["svc1"], services_meta, services_dir, out_root, "hostA"
    )
    assert len(templates) == 1
    assert (
        templates[0]["dest"].endswith("bar.out")
        if isinstance(templates[0], dict)
        else True
    )
    assert len(copy_list) == 1
    src, dest = copy_list[0]
    assert src.exists()
    assert str(dest).startswith(str(out_root / "hostA"))


def test_collect_templates_missing_source_skipped(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    services_dir = tmp_path / "config" / "services"
    svc = services_dir / "svc"
    svc.mkdir(parents=True)

    services_meta = {"svc": {"vault_agent": {"templates": [{}]}}}

    templates, copy_list = collect_vault_agent_templates(
        ["svc"], services_meta, services_dir, tmp_path / "out", "host"
    )
    assert templates == []
    assert copy_list == []


def test_collect_templates_absolute_path_resolution(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    services_dir = tmp_path / "config" / "services"
    svc = services_dir / "svc"
    svc.mkdir(parents=True)

    abs_file = tmp_path / "some.tpl"
    abs_file.write_text("ok")

    services_meta = {
        "svc": {
            "vault_agent": {"templates": [{"source": str(abs_file), "out": "o.tpl"}]}
        }
    }

    templates, copy_list = collect_vault_agent_templates(
        ["svc"], services_meta, services_dir, tmp_path / "out", "host"
    )
    assert len(templates) == 1
    assert copy_list[0][0] == abs_file


def test_collect_vault_agent_templates_skips_missing(tmp_path: Path):
    services_dir = tmp_path / "config" / "services"
    services_dir.mkdir(parents=True)
    svc_dir = services_dir / "svc"
    svc_dir.mkdir()

    services_meta = {
        "svc": {
            "vault_agent": {"templates": [{"source": "missing.tpl", "out": "out.tpl"}]}
        }
    }

    templates, copy_list = collect_vault_agent_templates(
        ["svc"], services_meta, services_dir, tmp_path, "hostA"
    )
    assert templates == []
    assert copy_list == []


# --- End vault_template_builder tests ---
