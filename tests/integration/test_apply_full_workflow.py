import stat
import subprocess
from pathlib import Path
import pytest

# mark all tests in this module as slow
pytestmark = pytest.mark.slow


def _write_apply_tree(
    tmp_path: Path, apply_sh_src: Path, lib_overrides: dict | None = None
):
    # create tree
    ap_dir = tmp_path / "tools" / "apply"
    lib_dir = ap_dir / "lib"
    lib_dir.mkdir(parents=True)

    # copy apply.sh
    content = apply_sh_src.read_text()
    target = ap_dir / "apply.sh"
    target.write_text(content)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)

    # ensure tmp dir exists under repo root so mktemp templates work
    (tmp_path / "tmp").mkdir(parents=True, exist_ok=True)

    # create a minimal render stub so apply.sh can invoke tools/render/cli.py
    render_dir = tmp_path / "tools" / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / "cli.py").write_text(
        """#!/usr/bin/env python3
import sys
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()

# Always render all hosts (phobos and deimos)
for host in ["phobos", "deimos"]:
    out = os.path.join(args.output_dir, host, "systemd-networkd")
    os.makedirs(out, exist_ok=True)

# Also create state dir
state_dir = os.path.join(os.path.dirname(args.output_dir), "state")
os.makedirs(state_dir, exist_ok=True)

print('render_stub created all hosts')
sys.exit(0)
"""
    )
    (render_dir / "cli.py").chmod(0o755)
    # default libs
    libs = {
        "logging.sh": """
            log_info(){ echo "INFO: $*"; }
            log_warn(){ echo "WARN: $*"; }
            log_error(){ echo "ERROR: $*"; }
            log_ok(){ echo "OK: $*"; }
        """,
        "env.sh": """
            parse_args(){
                DRY_RUN=1
                TARGET_HOST=""
                while [[ $# -gt 0 ]]; do
                    case "$1" in
                        --apply) DRY_RUN=0; shift ;;
                        --verbose) VERBOSE=1; shift ;;
                        --skip-render) SKIP_RENDER=1; shift ;;
                        --*) shift ;;
                        *) TARGET_HOST="$1"; shift ;;
                    esac
                done
                TARGET_HOST=${TARGET_HOST:-phobos}
                # point render/state dirs to repo-relative out/ during tests
                RENDER_DIR="$ROOT_DIR/out/rendered"
                STATE_DIR="$ROOT_DIR/out/state"
                return 0
            }
            check_prerequisites(){
                # create expected dirs
                :
                return 0
            }
        """,
        "validation.sh": """
            validate_systemd_config(){ echo "validate_systemd_config"; return 0; }
        """,
        "drift.sh": """
            validate_simple_state_file(){ echo "validate_simple_state_file $1 $2"; return 0; }
            validate_services_state_file(){ echo "validate_services_state_file $1"; return 0; }
            detect_drift(){ echo "detect_drift"; return 0; }
            detect_service_drift(){ echo "detect_service_drift"; return 0; }
            detect_static_systemd_drift(){ echo "detect_static_systemd_drift"; return 0; }
            detect_resolved_drift(){ echo "detect_resolved_drift"; return 0; }
            detect_software_drift(){ echo "detect_software_drift"; return 0; }
            detect_users_drift(){ echo "detect_users_drift"; return 0; }
            detect_desec_drift(){ echo "detect_desec_drift"; return 0; }
            update_state(){ echo "update_state"; return 0; }
        """,
        "staging.sh": """
            stage_files(){ echo "stage_files"; return 0; }
            stage_service_files(){ echo "stage_service_files"; return 0; }
            create_volume_host_dirs(){ echo "create_volume_host_dirs"; return 0; }
            create_mounted_file_dirs(){ echo "create_mounted_file_dirs"; return 0; }
        """,
        "apply_phase.sh": """
            apply_files(){ echo "apply_files"; return 0; }
            apply_service_files(){ echo "apply_service_files"; return 0; }
            apply_resolved_config(){ echo "apply_resolved_config"; return 0; }
            apply_software_artifacts(){ echo "apply_software_artifacts"; return 0; }
            apply_users_config(){ echo "apply_users_config"; return 0; }
            apply_desec_changes(){ echo "apply_desec_changes"; return 0; }
            apply_static_systemd_units(){ echo "apply_static_systemd_units"; return 0; }
            reload_networkd(){ echo "reload_networkd"; return 0; }
            validate_connectivity(){ echo "validate_connectivity"; return 0; }
            send_gratuitous_arp(){ echo "send_gratuitous_arp"; return 0; }
        """,
        "runtime.sh": """
            update_state(){ echo "update_state"; return 0; }
        """,
        "desec.sh": """
            validate_desec_plan(){ echo "validate_desec_plan $1"; return 0; }
            detect_desec_drift(){ echo "detect_desec_drift"; return 0; }
            apply_desec_changes(){ echo "apply_desec_changes"; return 0; }
        """,
        "services.sh": """
            # Stub service helpers for tests
            list_services(){ echo "list_services"; return 0; }
        """,
    }

    # apply overrides
    if lib_overrides:
        libs.update(lib_overrides)

    for name, txt in libs.items():
        (lib_dir / name).write_text(txt)
        (lib_dir / name).chmod(0o644)

    return ap_dir


def _run_apply(tmp_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["bash", "tools/apply/apply.sh"] + args
    return subprocess.run(
        cmd, cwd=tmp_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )


def test_detect_drift_nonfatal(tmp_path: Path):
    repo_root = Path.cwd()
    apply_sh_src = repo_root / "tools" / "apply" / "apply.sh"
    # override detect_drift to return 2
    lib_overrides = {
        "drift.sh": """
            detect_drift(){ echo "detect_drift simulated fail"; return 2; }
            detect_service_drift(){ echo "detect_service_drift"; return 0; }
            detect_desec_drift(){ echo "detect_desec_drift"; return 0; }
        """,
    }
    _write_apply_tree(tmp_path, apply_sh_src, lib_overrides=lib_overrides)

    proc = _run_apply(tmp_path, ["phobos"])
    assert proc.returncode == 0
    assert "DRY RUN COMPLETE" in proc.stdout or "DRY RUN MODE" in proc.stdout


def test_stage_files_failure_aborts(tmp_path: Path):
    repo_root = Path.cwd()
    apply_sh_src = repo_root / "tools" / "apply" / "apply.sh"
    lib_overrides = {
        "staging.sh": """
            stage_files(){ echo "stage_files failing"; return 1; }
            stage_service_files(){ echo "stage_service_files"; return 0; }
            create_volume_host_dirs(){ return 0; }
            create_mounted_file_dirs(){ return 0; }
        """,
    }
    _write_apply_tree(tmp_path, apply_sh_src, lib_overrides=lib_overrides)

    proc = _run_apply(tmp_path, ["phobos"])
    assert proc.returncode != 0
    assert "stage_files failing" in proc.stdout


def test_reload_networkd_failure_in_apply_mode_returns_nonzero(tmp_path: Path):
    repo_root = Path.cwd()
    apply_sh_src = repo_root / "tools" / "apply" / "apply.sh"
    lib_overrides = {
        "apply_phase.sh": """
            apply_files(){ echo "apply_files"; return 0; }
            apply_service_files(){ echo "apply_service_files"; return 0; }
            apply_resolved_config(){ echo "apply_resolved_config"; return 0; }
            apply_software_artifacts(){ echo "apply_software_artifacts"; return 0; }
            apply_desec_changes(){ echo "apply_desec_changes"; return 0; }
            apply_static_systemd_units(){ echo "apply_static_systemd_units"; return 0; }
            apply_users_config(){ echo "apply_users_config"; return 0; }
        """,
        "runtime.sh": """
            update_state(){ echo "update_state"; return 0; }
            reload_networkd(){ echo "reload_networkd failing"; return 2; }
            validate_connectivity(){ echo "validate_connectivity"; return 0; }
            send_gratuitous_arp(){ echo "send_gratuitous_arp"; return 0; }
        """,
    }
    _write_apply_tree(tmp_path, apply_sh_src, lib_overrides=lib_overrides)

    # run in apply mode
    proc = _run_apply(tmp_path, ["--apply", "phobos"])
    assert proc.returncode != 0
    assert "reload_networkd failing" in proc.stdout
