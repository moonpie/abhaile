import os
from pathlib import Path


from tools.render.services.vault_template_builder import (
    collect_vault_agent_templates,
    stage_vault_agent_templates,
)


def test_vault_collect_and_stage_integration(tmp_path: Path):
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
    finally:
        os.chdir(original_cwd)

    services_dir = tmp_path / "config" / "services"
    svc1_dir = services_dir / "svc1"
    tpl1_dir = svc1_dir / "templates"
    tpl1_dir.mkdir(parents=True)
    (tpl1_dir / "a.ctmpl").write_text("hello")

    svc2_dir = services_dir / "svc2"
    tpl2_dir = svc2_dir / "templates"
    tpl2_dir.mkdir(parents=True)
    (tpl2_dir / "b.ctmpl").write_text("world")

    services_meta = {
        "svc1": {
            "vault_agent": {
                "templates": [{"source": "templates/a.ctmpl", "out": "a.out"}]
            }
        },
        "svc2": {
            "vault_agent": {
                "templates": [{"source": "templates/b.ctmpl", "out": "b.out"}]
            }
        },
    }

    out_root = tmp_path / "out"
    templates, copy_list = collect_vault_agent_templates(
        ["svc1", "svc2"], services_meta, services_dir, out_root, "phobos"
    )

    assert len(templates) == 2
    assert len(copy_list) == 2

    stage_vault_agent_templates(copy_list)

    # Verify source template files staged under host path
    staged_a = (
        out_root
        / "phobos"
        / "services"
        / "vault-agent"
        / "srv"
        / "vault"
        / "agent"
        / "templates"
        / "a.ctmpl"
    )
    staged_b = (
        out_root
        / "phobos"
        / "services"
        / "vault-agent"
        / "srv"
        / "vault"
        / "agent"
        / "templates"
        / "b.ctmpl"
    )
    assert staged_a.exists()
    assert staged_b.exists()
