"""Check deterministic parent intent for fresh service files."""

from pathlib import Path

import pytest

from abhaile.renderers.collector import ArtifactCollector
from abhaile.renderers.parents import register_file_parents
from abhaile.utils.errors import RenderError


def test_file_parents_preserve_explicit_metadata_and_are_idempotent(tmp_path: Path) -> None:
    collector = ArtifactCollector()
    collector.register_artifact(
        "explicit",
        "/srv/app/config",
        "service.directory",
        "service:app",
        "",
        is_directory=True,
        apply_hints={"owner": 1883, "group": 1883, "mode": "0750"},
    )
    collector.register_artifact(
        "config", "/srv/app/config/server.conf", "service.config", "service:app", ""
    )
    collector.register_artifact(
        "dropin",
        "/etc/systemd/system/app.service.d/10-config.conf",
        "systemd.dropin",
        "unit:app.service",
        "",
    )
    register_file_parents(collector, tmp_path)
    before = collector.get_all_artifacts()
    register_file_parents(collector, tmp_path)
    assert collector.get_all_artifacts() == before
    entries = {entry.target_path: entry for entry in before}
    assert entries["/srv/app/config"].apply_hints == {"owner": 1883, "group": 1883, "mode": "0750"}
    assert entries["/etc/systemd/system/app.service.d"].apply_hints == {
        "owner": "root",
        "group": "root",
        "mode": "0755",
    }
    assert "/etc" not in entries


def test_authorized_key_parent_retains_private_principal_metadata(tmp_path: Path) -> None:
    collector = ArtifactCollector()
    collector.register_artifact(
        "keys",
        "/home/runtime/.ssh/authorized_keys",
        "host.authorized_keys",
        "principal:runtime",
        "",
        apply_hints={"owner_user": "runtime", "owner_group": "apps"},
    )
    register_file_parents(collector, tmp_path)
    entries = {entry.target_path: entry for entry in collector.get_all_artifacts()}
    assert entries["/home/runtime/.ssh"].apply_hints == {
        "owner": "runtime",
        "group": "apps",
        "mode": "0700",
    }
    assert "/home/runtime" not in entries


def test_required_parent_cannot_also_be_a_file(tmp_path: Path) -> None:
    collector = ArtifactCollector()
    collector.register_artifact("parent", "/srv/app", "service.config", "service:app", "")
    collector.register_artifact("child", "/srv/app/config", "service.config", "service:app", "")
    with pytest.raises(RenderError, match="required directory"):
        register_file_parents(collector, tmp_path)


def test_rootless_parents_use_declared_user_without_claiming_home(tmp_path: Path) -> None:
    collector = ArtifactCollector()
    collector.register_artifact(
        "quadlet",
        "/home/runtime/.config/containers/systemd/app.container",
        "quadlet.container",
        "unit:app.service",
        "",
        apply_hints={"rootless": True, "podman_user": "runtime"},
    )
    register_file_parents(collector, tmp_path)
    entries = {entry.target_path: entry for entry in collector.get_all_artifacts()}
    assert entries["/home/runtime/.config"].apply_hints == {
        "owner": "runtime",
        "group": "runtime",
        "mode": "0700",
    }
    assert "/home/runtime" not in entries


def test_different_runtime_users_need_explicit_intent_for_a_shared_parent(tmp_path: Path) -> None:
    collector = ArtifactCollector()
    for user in ("first", "second"):
        collector.register_artifact(
            user,
            f"/srv/shared/{user}.conf",
            "service.config",
            f"service:{user}",
            "",
            apply_hints={"rootless": True, "podman_user": user},
        )
    with pytest.raises(RenderError, match="Conflicting implicit directory"):
        register_file_parents(collector, tmp_path)


def test_runtime_private_directory_does_not_claim_shared_ancestors(tmp_path: Path) -> None:
    collector = ArtifactCollector()
    collector.register_artifact(
        "root", "/srv/vault/vault.env", "service.config", "service:vault", ""
    )
    collector.register_artifact(
        "agent",
        "/srv/vault/agent/config/agent.hcl",
        "vault.config",
        "service:vault-agent",
        "",
        apply_hints={"rootless": True, "podman_user": "agent"},
    )
    register_file_parents(collector, tmp_path)
    entries = {entry.target_path: entry for entry in collector.get_all_artifacts()}
    assert entries["/srv/vault/agent/config"].apply_hints == {
        "owner": "agent",
        "group": "agent",
        "mode": "0700",
    }
    assert entries["/srv/vault"].apply_hints == {"owner": "root", "group": "root", "mode": "0755"}
